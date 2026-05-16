# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for the engine_async <-> subscribe-loop wiring (OI-PEFR-6).

Covers:
- ``attach_subscribe_loop`` after spawn wires the loop with the right
  config (env, persona_slug, org_id pulled from EnvContract).
- ``attach_subscribe_loop`` before spawn raises.
- Engine version bumped to 0.4.0-pilot.
- ``set_svid_factories`` works with the new constructor params.
- Default LLM hook is EchoReflectionLlmHook.
- Custom LLM hook is honoured.
- WAKIR_ENV env-var is honoured.
- The subscribe-runner runs to completion on a sentinel-stop iterator.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

from wirelang.persona_engine.engine import EnvContract
from wirelang.persona_engine.engine_async import (
    ASYNC_ENGINE_VARIANT,
    ASYNC_ENGINE_VERSION,
    AsyncPersonaEngine,
)
from wirelang.persona_engine.llm_call_shim import (
    EchoReflectionLlmHook,
    LlmCallResult,
)
from wirelang.persona_engine.nats_subscribe_loop import (
    ACCEPTED_INBOUND_SCHEMA,
    NatsSubscribeLoop,
    iter_from_queue,
)
from wirelang.tests.persona_engine._v907_compute_skip import (
    requires_v907_compute_deps,
)


PERSONA_DEF_TEMPLATE = """---
slug: tomas
title: Tomás Reinhart
version: 0.1
---

# Tomás Reinhart — test persona
"""


def _make_env(tmp_path: Path, *, nats_servers: str = "") -> EnvContract:
    axis_a = tmp_path / "tomas.md"
    axis_a.write_text(PERSONA_DEF_TEMPLATE)
    axis_c = tmp_path / "tomas.json"
    axis_c.write_text("{}")
    return EnvContract(
        persona_id="tomas",
        org_id="acme",
        nats_servers=nats_servers,
        spiffe_endpoint_socket="unix:///nonexistent/sock-async-test",
        persona_state_bucket=None,
        v907_expected_pin=None,
        axis_a_path=axis_a,
        axis_c_path=axis_c,
    )


def _good_envelope(*, auftrag_id: str = "a-1", prompt: str = "hello") -> bytes:
    return json.dumps({
        "schema": ACCEPTED_INBOUND_SCHEMA,
        "event_kind": "agent.task.assigned",
        "org_id": "acme",
        "persona_id": "tomas",
        "auftrag_id": auftrag_id,
        "ts_utc": "2026-05-15T22:00:00Z",
        "source": "mira-sandbox",
        "prompt_sha256": "sha256:" + ("0" * 64),
        "prompt_payload": prompt,
        "metadata": {},
    }, sort_keys=True).encode("utf-8")


class _FakeMsg:
    def __init__(self, data):
        self.data = data
        self.subject = "wakir.dev.agent.agent.task.assigned.tomas"

    async def ack(self):
        return None


class _FakePublishSink:
    def __init__(self):
        self.published: List[Tuple[str, bytes]] = []

    async def publish(self, subject, payload):
        self.published.append((subject, payload))


# ---------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------


def test_engine_async_version_bumped():
    assert ASYNC_ENGINE_VERSION == "0.5.0-pilot"


def test_engine_async_variant_unchanged():
    assert ASYNC_ENGINE_VARIANT == "real-async"


# ---------------------------------------------------------------------
# Construction: default LLM hook
# ---------------------------------------------------------------------


def test_default_llm_hook_is_echo_reflection(tmp_path: Path):
    env = _make_env(tmp_path)
    sink = io.StringIO()
    engine = AsyncPersonaEngine(env, log_sink=sink)
    assert isinstance(engine._llm_hook, EchoReflectionLlmHook)


def test_custom_llm_hook_honoured(tmp_path: Path):
    env = _make_env(tmp_path)
    sink = io.StringIO()
    custom = EchoReflectionLlmHook(prompt_prefix_chars=42)
    engine = AsyncPersonaEngine(env, log_sink=sink, llm_hook=custom)
    assert engine._llm_hook is custom


def test_default_subscribe_env_dev(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("WAKIR_ENV", raising=False)
    env = _make_env(tmp_path)
    sink = io.StringIO()
    engine = AsyncPersonaEngine(env, log_sink=sink)
    assert engine._subscribe_env == "dev"


def test_subscribe_env_from_env_var(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WAKIR_ENV", "staging")
    env = _make_env(tmp_path)
    sink = io.StringIO()
    engine = AsyncPersonaEngine(env, log_sink=sink)
    assert engine._subscribe_env == "staging"


def test_subscribe_env_explicit_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("WAKIR_ENV", "staging")
    env = _make_env(tmp_path)
    sink = io.StringIO()
    engine = AsyncPersonaEngine(env, log_sink=sink, subscribe_env="prod")
    assert engine._subscribe_env == "prod"


# ---------------------------------------------------------------------
# attach_subscribe_loop
# ---------------------------------------------------------------------


def test_attach_subscribe_loop_before_spawn_raises(tmp_path: Path):
    env = _make_env(tmp_path)
    sink = io.StringIO()
    engine = AsyncPersonaEngine(env, log_sink=sink)
    with pytest.raises(RuntimeError):
        engine.attach_subscribe_loop(msg_iter=iter([]))


@pytest.mark.asyncio
@requires_v907_compute_deps
async def test_attach_subscribe_loop_after_spawn_succeeds(tmp_path: Path):
    env = _make_env(tmp_path)
    sink = io.StringIO()
    engine = AsyncPersonaEngine(env, log_sink=sink)
    await engine.boot()
    await engine.spawn()

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(None)
    loop = engine.attach_subscribe_loop(msg_iter=iter_from_queue(queue))
    assert isinstance(loop, NatsSubscribeLoop)


@pytest.mark.asyncio
@requires_v907_compute_deps
async def test_subscribe_loop_processes_via_engine_runner(tmp_path: Path):
    env = _make_env(tmp_path)
    sink = io.StringIO()
    engine = AsyncPersonaEngine(env, log_sink=sink)
    await engine.boot()
    await engine.spawn()

    publish = _FakePublishSink()
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_FakeMsg(_good_envelope(auftrag_id="a-1")))
    await queue.put(_FakeMsg(_good_envelope(auftrag_id="a-2")))
    await queue.put(None)

    loop = engine.attach_subscribe_loop(
        msg_iter=iter_from_queue(queue),
        publish_sink=publish,
    )

    # Drive the engine's subscribe-runner directly.
    engine._stop_event = asyncio.Event()
    await engine._subscribe_runner()

    assert loop.processed_count == 2
    assert len(publish.published) == 2


@pytest.mark.asyncio
@requires_v907_compute_deps
async def test_subscribe_loop_uses_engine_env_persona(tmp_path: Path):
    env = _make_env(tmp_path)
    sink = io.StringIO()
    engine = AsyncPersonaEngine(env, log_sink=sink)
    await engine.boot()
    await engine.spawn()

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(None)
    loop = engine.attach_subscribe_loop(msg_iter=iter_from_queue(queue))

    assert loop.config.env == "dev"  # default
    assert loop.config.persona_slug == "tomas"
    assert loop.config.org_id == "acme"


@pytest.mark.asyncio
@requires_v907_compute_deps
async def test_subscribe_loop_env_override(tmp_path: Path):
    env = _make_env(tmp_path)
    sink = io.StringIO()
    engine = AsyncPersonaEngine(env, log_sink=sink)
    await engine.boot()
    await engine.spawn()

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(None)
    loop = engine.attach_subscribe_loop(
        msg_iter=iter_from_queue(queue),
        env="staging",
    )
    assert loop.config.env == "staging"


@pytest.mark.asyncio
@requires_v907_compute_deps
async def test_subscribe_loop_publish_only_when_sink_provided(tmp_path: Path):
    env = _make_env(tmp_path)
    sink = io.StringIO()
    engine = AsyncPersonaEngine(env, log_sink=sink)
    await engine.boot()
    await engine.spawn()

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(None)
    loop_no_sink = engine.attach_subscribe_loop(msg_iter=iter_from_queue(queue))
    assert loop_no_sink.config.publish_output is False


@pytest.mark.asyncio
async def test_engine_task_tracker_property(tmp_path: Path):
    env = _make_env(tmp_path)
    sink = io.StringIO()
    engine = AsyncPersonaEngine(env, log_sink=sink)
    tracker = engine.task_tracker
    assert tracker.tasks_processed == 0


@pytest.mark.asyncio
async def test_engine_subscribe_loop_property_none_before_attach(tmp_path: Path):
    env = _make_env(tmp_path)
    sink = io.StringIO()
    engine = AsyncPersonaEngine(env, log_sink=sink)
    assert engine.subscribe_loop is None


@pytest.mark.asyncio
@requires_v907_compute_deps
async def test_engine_subscribe_loop_property_set_after_attach(tmp_path: Path):
    env = _make_env(tmp_path)
    sink = io.StringIO()
    engine = AsyncPersonaEngine(env, log_sink=sink)
    await engine.boot()
    await engine.spawn()
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(None)
    loop = engine.attach_subscribe_loop(msg_iter=iter_from_queue(queue))
    assert engine.subscribe_loop is loop


@pytest.mark.asyncio
@requires_v907_compute_deps
async def test_engine_spawn_emits_async_variant(tmp_path: Path):
    env = _make_env(tmp_path)
    sink = io.StringIO()
    engine = AsyncPersonaEngine(env, log_sink=sink)
    await engine.boot()
    await engine.spawn()
    # The first emission was an audit_annotation containing the variant.
    sink_text = sink.getvalue()
    assert ASYNC_ENGINE_VARIANT in sink_text
