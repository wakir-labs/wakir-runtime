# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Sprint-Pengine-12 Bug-41 CLI-async-wrap.

Substance under test
--------------------

``wirelang.persona_engine.cli.run_spawn`` was rewritten in Sprint-
Pengine-12 so that:

1. When ``WAKIR_SUBSCRIBE_ENV`` is unset (or empty) the legacy sync-
   engine path is taken (backward-compat with the v0.4.1-pilot
   container behaviour).
2. When ``WAKIR_SUBSCRIBE_ENV`` is set to a non-empty value the CLI
   dispatches to the asyncio path which boots :class:`AsyncPersonaEngine`,
   constructs a :class:`NatsSubscribeLoop` bound to the canonical
   ``wakir.<env>.agent.agent.task.assigned.<persona-slug>`` subject,
   logs a ``cli-async-dispatch`` record, and (when ``--one-shot`` is
   not passed) waits for SIGTERM / SIGINT via the engine's stop-event.

These hermetic tests exercise the dispatch decision, the env-var
contract (missing NATS_SERVERS, missing axis-A), and the signal-
handling fast-path. The live NATS binding (``nats.connect``) is the
single substance-anchor we do *not* execute hermetically — Live-
Verify-Plan in the outbox brief covers the operator-hand container
restart.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch

import pytest

from wirelang.persona_engine.cli import (
    EXIT_ENV_MISCONFIG,
    EXIT_INPUT_NOT_FOUND,
    EXIT_SUCCESS,
    NATS_TOKEN_ENV_VAR,
    NATS_URL_ENV_VAR,
    SUBSCRIBE_ENV_VAR,
    _resolve_async_subscribe_env,
    _run_spawn_async,
    build_parser,
    run_spawn,
)
from wirelang.tests.persona_engine._v907_compute_skip import (
    requires_v907_compute_deps,
)


SAMPLE_AXIS_A = """---
name: tomas
description: Sample test persona
schema_version: persona-v1
identity_pinned:
  email: tomas@example.com
domain: dev-engineering
---

Body.
"""


def _write_axis_a(tmp_path: Path) -> Path:
    axis_a = tmp_path / "tomas.md"
    axis_a.write_text(SAMPLE_AXIS_A, encoding="utf-8")
    return axis_a


# ===========================================================================
# 1. _resolve_async_subscribe_env — unit-level dispatch decision.
# ===========================================================================


def test_resolve_async_subscribe_env_unset_returns_none():
    """No env var -> sync path (None)."""
    assert _resolve_async_subscribe_env(env={}) is None


def test_resolve_async_subscribe_env_empty_returns_none():
    """Empty env var -> sync path (treated as unset)."""
    assert _resolve_async_subscribe_env(env={SUBSCRIBE_ENV_VAR: ""}) is None


def test_resolve_async_subscribe_env_dev_returns_dev():
    """Non-empty env var -> async path with that tag."""
    assert _resolve_async_subscribe_env(
        env={SUBSCRIBE_ENV_VAR: "dev"}
    ) == "dev"


# ===========================================================================
# 2. CLI dispatch — sync path stays untouched when env var absent.
# ===========================================================================


@requires_v907_compute_deps
def test_run_spawn_falls_back_to_sync_when_subscribe_env_unset(
    tmp_path, monkeypatch,
):
    """Backward-compat: no SUBSCRIBE_ENV var -> sync engine boots
    one-shot end-to-end without ever entering asyncio."""
    axis_a = _write_axis_a(tmp_path)
    monkeypatch.setenv("WAKIR_PERSONA_ID", "tomas")
    monkeypatch.setenv("WAKIR_ORG_ID", "acme")
    monkeypatch.setenv("WAKIR_PERSONA_AXIS_A_PATH", str(axis_a))
    monkeypatch.setenv("WAKIR_NATS_SERVERS", "")  # force in-memory fence
    monkeypatch.delenv(SUBSCRIBE_ENV_VAR, raising=False)
    p = build_parser()
    args = p.parse_args(["spawn", "--persona-slug", "tomas", "--one-shot"])
    rc = run_spawn(args)
    assert rc == EXIT_SUCCESS


# ===========================================================================
# 3. CLI dispatch — async path activates when env var set.
# ===========================================================================


@requires_v907_compute_deps
def test_run_spawn_dispatches_to_async_when_subscribe_env_set(
    tmp_path, monkeypatch, capsys,
):
    """SUBSCRIBE_ENV_VAR=dev -> CLI logs ``cli-async-dispatch`` and
    runs the async path. We exercise ``--one-shot`` so the run-loop
    short-circuits via despawn-clean without ever needing a live
    NATS connection. ``WAKIR_NATS_SERVERS`` stays empty so the engine
    state-backing fences to in-memory hermetically; the CLI's NATS-URL
    validation tolerates the empty value on the --one-shot escape
    hatch (no live subscribe-loop is bound)."""
    axis_a = _write_axis_a(tmp_path)
    monkeypatch.setenv("WAKIR_PERSONA_ID", "tomas")
    monkeypatch.setenv("WAKIR_ORG_ID", "acme")
    monkeypatch.setenv("WAKIR_PERSONA_AXIS_A_PATH", str(axis_a))
    monkeypatch.setenv("WAKIR_NATS_SERVERS", "")  # in-memory fence
    monkeypatch.setenv(SUBSCRIBE_ENV_VAR, "dev")
    p = build_parser()
    args = p.parse_args(["spawn", "--persona-slug", "tomas", "--one-shot"])
    rc = run_spawn(args)
    captured = capsys.readouterr()
    # The async path logs to stderr; we expect the dispatch event.
    assert rc == EXIT_SUCCESS
    assert "cli-async-dispatch" in captured.err
    assert "subscribe_env" in captured.err
    # Canonical subject must be present in the dispatch log.
    assert "wakir.dev.agent.agent.task.assigned.tomas" in captured.err


# ===========================================================================
# 4. CLI async path — missing NATS_SERVERS short-circuits to ENV_MISCONFIG.
# ===========================================================================


def test_run_spawn_async_missing_nats_servers_returns_env_misconfig(
    tmp_path, monkeypatch,
):
    """If the async path is triggered in *live* mode (no --one-shot)
    but WAKIR_NATS_SERVERS is empty we cannot bind the subscribe-loop
    — bail with ENV_MISCONFIG so the operator sees a clear remediation
    instead of a silent retry loop on connect(). The --one-shot path
    tolerates the empty value (see test 3) because it skips the run-
    loop entirely."""
    axis_a = _write_axis_a(tmp_path)
    monkeypatch.setenv("WAKIR_PERSONA_ID", "tomas")
    monkeypatch.setenv("WAKIR_ORG_ID", "acme")
    monkeypatch.setenv("WAKIR_PERSONA_AXIS_A_PATH", str(axis_a))
    monkeypatch.setenv("WAKIR_NATS_SERVERS", "")  # missing on async path
    monkeypatch.setenv(SUBSCRIBE_ENV_VAR, "dev")
    p = build_parser()
    # NB: no --one-shot — exercise the live path's validation.
    args = p.parse_args(["spawn", "--persona-slug", "tomas"])
    rc = run_spawn(args)
    assert rc == EXIT_ENV_MISCONFIG


# ===========================================================================
# 5. CLI async path — missing axis-A returns INPUT_NOT_FOUND.
# ===========================================================================


def test_run_spawn_async_missing_axis_a_returns_input_not_found(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("WAKIR_PERSONA_ID", "tomas")
    monkeypatch.setenv("WAKIR_ORG_ID", "acme")
    monkeypatch.setenv(
        "WAKIR_PERSONA_AXIS_A_PATH", str(tmp_path / "no-such.md"),
    )
    monkeypatch.setenv("WAKIR_NATS_SERVERS", "")
    monkeypatch.setenv(SUBSCRIBE_ENV_VAR, "dev")
    p = build_parser()
    args = p.parse_args(["spawn", "--persona-slug", "tomas", "--one-shot"])
    rc = run_spawn(args)
    assert rc == EXIT_INPUT_NOT_FOUND


# ===========================================================================
# 6. CLI async path — engine state is wired (subscribe-loop attached).
# ===========================================================================


@pytest.mark.asyncio
@requires_v907_compute_deps
async def test_run_spawn_async_wires_subscribe_loop_with_canonical_subject(
    tmp_path, monkeypatch, capsys,
):
    """After the async-path runs --one-shot we verify via the captured
    stderr that the engine logged ``cli-async-dispatch`` with the
    canonical subject + version. This is the "subscribe-loop-activation"
    acceptance: the runner callable must be set on the engine before
    run_until_signal / despawn happens, and the dispatch log records
    the canonical subject."""
    axis_a = _write_axis_a(tmp_path)
    monkeypatch.setenv("WAKIR_PERSONA_ID", "tomas")
    monkeypatch.setenv("WAKIR_ORG_ID", "acme")
    monkeypatch.setenv("WAKIR_PERSONA_AXIS_A_PATH", str(axis_a))
    monkeypatch.setenv("WAKIR_NATS_SERVERS", "")  # in-memory fence
    monkeypatch.setenv(SUBSCRIBE_ENV_VAR, "dev")

    p = build_parser()
    args = p.parse_args(["spawn", "--persona-slug", "tomas", "--one-shot"])

    rc = await _run_spawn_async(args, subscribe_env="dev")
    captured = capsys.readouterr()

    assert rc == EXIT_SUCCESS
    log = captured.err
    # cli-async-dispatch must be present.
    assert "cli-async-dispatch" in log
    # Canonical subject must be in the dispatch log.
    assert "wakir.dev.agent.agent.task.assigned.tomas" in log
    # Engine version must be the Sprint-Pengine-12 bump.
    assert "0.5.3-rc1" in log


# ===========================================================================
# 7. CLI async path — signal-handling: stop-event terminates run loop.
# ===========================================================================


@pytest.mark.asyncio
@requires_v907_compute_deps
async def test_run_spawn_async_run_until_signal_terminates_on_stop(
    tmp_path, monkeypatch,
):
    """Verify SIGTERM-equivalent stop-event behaviour. We trigger the
    async path *without* ``--one-shot`` so it enters the run-loop, then
    set the engine's stop_event from a side-task to simulate the
    SIGTERM-handler firing. The function must return EXIT_SUCCESS
    after graceful shutdown."""
    axis_a = _write_axis_a(tmp_path)
    monkeypatch.setenv("WAKIR_PERSONA_ID", "tomas")
    monkeypatch.setenv("WAKIR_ORG_ID", "acme")
    monkeypatch.setenv("WAKIR_PERSONA_AXIS_A_PATH", str(axis_a))
    # Provide a URL so the live-mode validation passes; the actual
    # nats.connect() is patched out below.
    monkeypatch.setenv("WAKIR_NATS_SERVERS", "nats://hermetic:4222")
    monkeypatch.setenv(SUBSCRIBE_ENV_VAR, "dev")

    from wirelang.persona_engine import engine_async as ea
    from wirelang.persona_engine import state_backing as sb

    real_async_engine_cls = ea.AsyncPersonaEngine
    captured_engine: List[ea.AsyncPersonaEngine] = []

    class _CapturingEngine(real_async_engine_cls):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            captured_engine.append(self)

    # Force the state-backing to fence in-memory by making the live
    # NATS-KV connect raise the standard backing-error. The engine
    # already handles this path (Sprint-Pengine-8 fence pattern).
    async def _fake_connect(self):
        raise sb.PersonaStateBackingError(
            "hermetic-test: NATS-KV unavailable"
        )

    p = build_parser()
    args = p.parse_args(["spawn", "--persona-slug", "tomas"])

    with patch.object(ea, "AsyncPersonaEngine", _CapturingEngine), \
         patch.object(sb.NatsKvPersonaStateBackingAsync, "connect", _fake_connect):
        # Watcher: when the engine reaches the run-loop wait, set the
        # stop-event so the loop exits gracefully.
        async def _stop_when_ready():
            for _ in range(300):  # max ~3s
                await asyncio.sleep(0.01)
                if (
                    captured_engine
                    and captured_engine[0]._stop_event is not None
                ):
                    captured_engine[0].request_stop()
                    return
            raise AssertionError("engine never reached stop_event-ready state")

        # Shim ``import nats`` to raise ImportError so the _live_runner
        # exits cleanly before connect() (parity with the engine's
        # fence-on-import-error pattern).
        original_import = __import__

        def _fake_import(name, *a, **kw):
            if name == "nats":
                raise ImportError("hermetic-test: no nats-py")
            return original_import(name, *a, **kw)

        with patch("builtins.__import__", _fake_import):
            stop_task = asyncio.create_task(_stop_when_ready())
            try:
                rc = await asyncio.wait_for(
                    _run_spawn_async(args, subscribe_env="dev"),
                    timeout=5.0,
                )
            finally:
                if not stop_task.done():
                    stop_task.cancel()
                    try:
                        await stop_task
                    except (asyncio.CancelledError, Exception):
                        pass

    assert rc == EXIT_SUCCESS


# ===========================================================================
# 8. CLI async path — subscribe-loop config carries correct env+slug.
# ===========================================================================


@pytest.mark.asyncio
@requires_v907_compute_deps
async def test_run_spawn_async_subscribe_loop_config_matches_env(
    tmp_path, monkeypatch, capsys,
):
    """The :class:`SubscribeLoopConfig` constructed by the CLI must
    carry the env-tag from WAKIR_SUBSCRIBE_ENV and the persona-slug
    from the EnvContract (i.e. either --persona-slug or
    WAKIR_PERSONA_ID). Asserted via the log line ``cli-async-dispatch``
    which echoes both fields."""
    axis_a = tmp_path / "kai.md"
    axis_a.write_text(SAMPLE_AXIS_A, encoding="utf-8")
    monkeypatch.setenv("WAKIR_PERSONA_ID", "kai")
    monkeypatch.setenv("WAKIR_ORG_ID", "acme")
    monkeypatch.setenv("WAKIR_PERSONA_AXIS_A_PATH", str(axis_a))
    # Empty NATS URL -> state-backing fences to in-memory (hermetic);
    # the CLI dispatch log carries the empty value verbatim because
    # --one-shot bypasses the live-mode URL validation.
    monkeypatch.setenv("WAKIR_NATS_SERVERS", "")
    monkeypatch.setenv(SUBSCRIBE_ENV_VAR, "staging")

    p = build_parser()
    args = p.parse_args(["spawn", "--persona-slug", "kai", "--one-shot"])
    rc = await _run_spawn_async(args, subscribe_env="staging")
    captured = capsys.readouterr()
    assert rc == EXIT_SUCCESS
    # Parse the cli-async-dispatch log line out of stderr.
    dispatch_lines = [
        json.loads(line)
        for line in captured.err.splitlines()
        if line.strip().startswith("{") and "cli-async-dispatch" in line
    ]
    assert dispatch_lines, "cli-async-dispatch log line not found"
    rec = dispatch_lines[0]
    assert rec["subscribe_env"] == "staging"
    assert rec["persona_slug"] == "kai"
    assert rec["subscribe_subject"] == (
        "wakir.staging.agent.agent.task.assigned.kai"
    )
    # In hermetic --one-shot mode the URL is the empty string (no live
    # NATS binding is exercised); the dispatch event still records
    # whatever is in the env-var so operators can audit the value.
    assert rec["nats_url"] == ""


# ===========================================================================
# 9. CLI parser surface unchanged — argparse signature stable.
# ===========================================================================


def test_cli_parser_spawn_signature_unchanged():
    """Quadlet contract guarantee: the Sprint-Pengine-12 CLI keeps the
    same argparse surface as Pengine-11. The async-wrap is env-var
    gated so we MUST NOT add a flag (Quadlet ``Exec=`` line stays
    byte-stable)."""
    p = build_parser()
    args = p.parse_args(
        ["spawn", "--persona-slug", "tomas",
         "--pilot-phase", "doppelbetrieb-shadow"]
    )
    assert args.command == "spawn"
    assert args.persona_slug == "tomas"
    assert args.pilot_phase == "doppelbetrieb-shadow"
    assert args.one_shot is False


# ===========================================================================
# 10. Env var name discipline — exported constants stable.
# ===========================================================================


def test_cli_env_var_names_match_spec():
    """The Bug-41 dispatch decision pivots on these env var names —
    they are externally observable via Quadlet and the operator
    smoke-test. Locking them prevents an accidental rename from
    silently disabling the async path in production."""
    assert SUBSCRIBE_ENV_VAR == "WAKIR_SUBSCRIBE_ENV"
    assert NATS_URL_ENV_VAR == "WAKIR_NATS_SERVERS"
    assert NATS_TOKEN_ENV_VAR == "WAKIR_NATS_TOKEN"
