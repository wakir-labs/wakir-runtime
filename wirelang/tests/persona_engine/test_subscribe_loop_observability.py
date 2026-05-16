# SPDX-License-Identifier: BUSL-1.1
"""Tests for the subscribe-loop observability integration — Sprint-SRE Tag-15.

Drives :class:`NatsSubscribeLoop` with an injected in-memory
:class:`PersonaEngineObservability` and an in-memory message
iterator, then asserts the loop emits the right subscribe-lag
metric and span per inbound message.
"""

from __future__ import annotations

import asyncio
import io
import json
import time
from dataclasses import dataclass

import pytest

from wirelang.persona_engine.bridge_audit_writer import BridgeAuditWriter
from wirelang.persona_engine.llm_call_shim import EchoReflectionLlmHook
from wirelang.persona_engine.nats_subscribe_loop import (
    ACCEPTED_INBOUND_SCHEMA,
    NatsSubscribeLoop,
    SubscribeLoopConfig,
    _compute_subscribe_lag_seconds,
    build_subscribe_subject,
)
from wirelang.persona_engine.observability import (
    PersonaEngineObservability,
)


# ---------------------------------------------------------------------------
# Lag computation helper
# ---------------------------------------------------------------------------


def test_compute_subscribe_lag_seconds_handles_z_suffix():
    # 1 second in the past relative to now.
    one_sec_ago = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1)
    )
    lag = _compute_subscribe_lag_seconds(one_sec_ago)
    assert lag is not None
    assert lag >= 0
    assert lag < 5  # generous slack for test scheduling jitter


def test_compute_subscribe_lag_seconds_returns_none_for_garbage():
    assert _compute_subscribe_lag_seconds("nope") is None
    assert _compute_subscribe_lag_seconds("") is None


# ---------------------------------------------------------------------------
# In-memory message + iterator fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeMsg:
    data: bytes
    subject: str


async def _msg_iterator(messages):
    """Async generator yielding the provided messages, then exiting."""
    for m in messages:
        yield m


def _build_inbound_envelope(*, persona_id: str, ts_utc: str, auftrag_id: str = "auf-1") -> bytes:
    envelope = {
        "schema": ACCEPTED_INBOUND_SCHEMA,
        "event_kind": "agent.task.assigned",
        "org_id": "acme",
        "persona_id": persona_id,
        "auftrag_id": auftrag_id,
        "ts_utc": ts_utc,
        "source": "mira-dispatch",
        "prompt_sha256": "sha256:" + "0" * 64,
        "prompt_payload": "hello, persona.",
        "metadata": {},
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# End-to-end subscribe-loop instrumentation test
# ---------------------------------------------------------------------------


def test_subscribe_loop_emits_lag_metric_and_span_per_message():
    sink = io.StringIO()
    obs = PersonaEngineObservability(inmemory_sink=True)
    bridge = BridgeAuditWriter(
        org_id="acme",
        persona_id="tomas",
        session_id="s-test",
        engine_version="0.4.2-pilot",
        v907_pin="sha256:" + "a" * 64,
        wakir_runtime_sink=sink,
    )
    hook = EchoReflectionLlmHook()
    config = SubscribeLoopConfig(
        env="dev",
        persona_slug="tomas",
        org_id="acme",
        bridge_writer=bridge,
        hook=hook,
        publish_output=False,  # no live publish in hermetic mode
        observability=obs,
    )
    loop_obj = NatsSubscribeLoop(config=config, publish_sink=None, log_sink=sink)
    one_sec_ago = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1)
    )
    msg = _FakeMsg(
        data=_build_inbound_envelope(
            persona_id="tomas", ts_utc=one_sec_ago, auftrag_id="auf-1"
        ),
        subject=build_subscribe_subject("dev", "tomas"),
    )

    async def _drive():
        await loop_obj.run_with_iterator(_msg_iterator([msg]))

    asyncio.run(_drive())

    # Exactly one subscribe-lag metric must have landed.
    lag_metrics = [
        m for m in obs.records.metrics
        if m.metric_name == "persona_engine.subscribe.lag_seconds"
    ]
    assert len(lag_metrics) == 1
    assert lag_metrics[0].attributes["subject"] == "wakir.dev.agent.agent.task.assigned.tomas"
    assert lag_metrics[0].value >= 0

    # The per-message span must have landed.
    spans = [
        s for s in obs.records.spans
        if s.span_name == "persona_engine.subscribe.handle_message"
    ]
    assert len(spans) == 1
    span = spans[0]
    assert span.status == "ok"
    assert span.attributes["auftrag_id"] == "auf-1"
    assert span.attributes["persona_id"] == "tomas"


def test_subscribe_loop_runs_unchanged_without_observability():
    """The legacy code path (config.observability=None) must keep working."""
    sink = io.StringIO()
    bridge = BridgeAuditWriter(
        org_id="acme",
        persona_id="tomas",
        session_id="s-test",
        engine_version="0.4.2-pilot",
        v907_pin="sha256:" + "a" * 64,
        wakir_runtime_sink=sink,
    )
    hook = EchoReflectionLlmHook()
    config = SubscribeLoopConfig(
        env="dev",
        persona_slug="tomas",
        org_id="acme",
        bridge_writer=bridge,
        hook=hook,
        publish_output=False,
        observability=None,  # explicit
    )
    loop_obj = NatsSubscribeLoop(config=config, publish_sink=None, log_sink=sink)
    one_sec_ago = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1)
    )
    msg = _FakeMsg(
        data=_build_inbound_envelope(
            persona_id="tomas", ts_utc=one_sec_ago, auftrag_id="auf-2"
        ),
        subject=build_subscribe_subject("dev", "tomas"),
    )

    async def _drive():
        await loop_obj.run_with_iterator(_msg_iterator([msg]))

    asyncio.run(_drive())
    # No observability — loop must still have processed.
    assert loop_obj.processed_count == 1
