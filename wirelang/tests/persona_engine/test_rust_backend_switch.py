# SPDX-License-Identifier: BUSL-1.1
"""Hermetic tests for the Tag-17 Rust-backend production-default switch.

Substance anchor: :mod:`wirelang.persona_engine.rust_backend_switch`.

100% hermetic: no real Rust binary, no real NATS, no network, no time
sources beyond ``time.perf_counter`` for latency measurement.
Subprocess invocations target a fake-invoker injection seam so the
suite runs in any CI sandbox.

Coverage map (15 hermetic vectors, ≥12 required):

1.  ``WAKIR_RECOVERY_BACKEND`` unset → python default + passthrough log.
2.  ``WAKIR_STATE_BACKING_BACKEND`` unset → python default + passthrough.
3.  ``WAKIR_RECOVERY_BACKEND=python`` (explicit) → python + decision
    fallback_reason="explicit_python".
4.  ``WAKIR_RECOVERY_BACKEND=rust`` + binary available → rust chosen.
5.  ``WAKIR_RECOVERY_BACKEND=rust`` + binary missing → graceful
    fallback to python, fallback_reason="binary_missing".
6.  ``WAKIR_STATE_BACKING_BACKEND=rust_inmemory`` + binary available →
    rust_inmemory chosen.
7.  ``WAKIR_STATE_BACKING_BACKEND=rust_natskv`` + binary available →
    rust_natskv chosen.
8.  ``WAKIR_STATE_BACKING_BACKEND=rust_inmemory`` + binary not
    executable → graceful fallback to python,
    fallback_reason="binary_not_executable".
9.  Env validation: unknown ``WAKIR_RECOVERY_BACKEND`` value raises
    BackendSwitchValidationError.
10. Env validation: unknown ``WAKIR_STATE_BACKING_BACKEND`` value
    raises BackendSwitchValidationError.
11. Subprocess-bridge state-backing roundtrip: snapshot + restore_latest
    (stub invoker, byte-stable JCS shape).
12. Subprocess-bridge state-backing: list_snapshots returns sorted
    offsets.
13. Subprocess-bridge state-backing: atomic_swap_pinned_offset calls
    invoker exactly once.
14. Subprocess-bridge state-backing: exit_nonzero raises
    RustBackendError(reason="exit_nonzero").
15. Subprocess-bridge state-backing: bad_json raises
    RustBackendError(reason="bad_json").
16. Subprocess-bridge recovery runner: run() success returns parsed
    envelope.
17. Subprocess-bridge recovery runner: exit_nonzero raises
    RustBackendError.
18. Per-decision logging emits structured JSON line to log_sink.
19. Resolution latency is recorded (non-negative microseconds).
20. ``WAKIR_RUST_BACKEND_TIMEOUT_S`` parsing — default / valid /
    invalid / negative paths.

Total: 20 hermetic vectors (≥12 required).
"""

from __future__ import annotations

import io
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import List, Tuple

import pytest

from wirelang.persona_engine.rust_backend_switch import (
    DEFAULT_RUST_BACKEND_TIMEOUT_S,
    DEFAULT_RUST_RECOVERY_BIN,
    DEFAULT_RUST_STATE_BACKING_BIN,
    RECOVERY_BACKEND_ENV,
    RUST_BACKEND_TIMEOUT_ENV,
    RUST_RECOVERY_BIN_ENV,
    RUST_STATE_BACKING_BIN_ENV,
    STATE_BACKING_BACKEND_ENV,
    VALID_RECOVERY_BACKEND_VALUES,
    VALID_STATE_BACKING_BACKEND_VALUES,
    BackendDecision,
    BackendSwitchValidationError,
    RecoveryBackend,
    RustBackendError,
    RustSubprocessRecoveryRunner,
    RustSubprocessStateBacking,
    StateBackingBackend,
    _resolve_timeout_s,
    build_state_backing,
    log_backend_decision,
    resolve_recovery_backend,
    resolve_state_backing_backend,
)
from wirelang.persona_engine.state_backing import (
    PersonaStateSnapshot,
)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _make_executable(path: Path) -> Path:
    """Create a tiny sh-script and chmod it executable."""
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _make_non_executable_file(path: Path) -> Path:
    path.write_text("not executable\n", encoding="utf-8")
    # Strip the execute bits explicitly.
    path.chmod(0o644)
    return path


def _stub_snapshot() -> PersonaStateSnapshot:
    return PersonaStateSnapshot(
        persona_hash="sha256:" + "a" * 64,
        audit_trace_offset=42,
        capability_token_ids=("cap-1", "cap-2"),
        snapshot_at_utc="2026-05-17T12:00:00Z",
        workspace_state_hash="sha256:" + "b" * 64,
    )


# ---------------------------------------------------------------------------
# Vector 1 — recovery default passthrough.
# ---------------------------------------------------------------------------


def test_recovery_unset_defaults_to_python():
    env: dict = {}
    chosen, decision = resolve_recovery_backend(env=env)
    assert chosen is RecoveryBackend.PYTHON
    assert decision.requested_backend == "python"
    assert decision.chosen_backend == "python"
    # No explicit env => fallback_reason is None.
    assert decision.fallback_reason is None
    assert decision.bin_path is None
    assert decision.resolution_latency_us >= 0


# ---------------------------------------------------------------------------
# Vector 2 — state-backing default passthrough.
# ---------------------------------------------------------------------------


def test_state_backing_unset_defaults_to_python():
    env: dict = {}
    chosen, decision = resolve_state_backing_backend(env=env)
    assert chosen is StateBackingBackend.PYTHON
    assert decision.requested_backend == "python"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason is None


# ---------------------------------------------------------------------------
# Vector 3 — explicit python carries explicit_python fallback_reason.
# ---------------------------------------------------------------------------


def test_recovery_explicit_python():
    env = {RECOVERY_BACKEND_ENV: "python"}
    chosen, decision = resolve_recovery_backend(env=env)
    assert chosen is RecoveryBackend.PYTHON
    assert decision.fallback_reason == "explicit_python"


# ---------------------------------------------------------------------------
# Vector 4 — rust requested + binary available → rust chosen.
# ---------------------------------------------------------------------------


def test_recovery_rust_with_available_binary(tmp_path: Path):
    bin_path = _make_executable(tmp_path / "wakir-recovery")
    env = {
        RECOVERY_BACKEND_ENV: "rust",
        RUST_RECOVERY_BIN_ENV: str(bin_path),
    }
    chosen, decision = resolve_recovery_backend(env=env)
    assert chosen is RecoveryBackend.RUST
    assert decision.chosen_backend == "rust"
    assert decision.requested_backend == "rust"
    assert decision.fallback_reason is None
    assert decision.bin_path == str(bin_path)


# ---------------------------------------------------------------------------
# Vector 5 — rust requested + binary missing → graceful fallback python.
# ---------------------------------------------------------------------------


def test_recovery_rust_with_missing_binary_graceful_fallback(tmp_path: Path):
    missing = tmp_path / "does-not-exist"
    env = {
        RECOVERY_BACKEND_ENV: "rust",
        RUST_RECOVERY_BIN_ENV: str(missing),
    }
    chosen, decision = resolve_recovery_backend(env=env)
    assert chosen is RecoveryBackend.PYTHON
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason == "binary_missing"
    assert decision.bin_path == str(missing)


# ---------------------------------------------------------------------------
# Vector 6 — rust_inmemory + binary available → rust_inmemory.
# ---------------------------------------------------------------------------


def test_state_backing_rust_inmemory_available(tmp_path: Path):
    bin_path = _make_executable(tmp_path / "wakir-sb")
    env = {
        STATE_BACKING_BACKEND_ENV: "rust_inmemory",
        RUST_STATE_BACKING_BIN_ENV: str(bin_path),
    }
    chosen, decision = resolve_state_backing_backend(env=env)
    assert chosen is StateBackingBackend.RUST_INMEMORY
    assert decision.chosen_backend == "rust_inmemory"
    assert decision.fallback_reason is None


# ---------------------------------------------------------------------------
# Vector 7 — rust_natskv + binary available → rust_natskv.
# ---------------------------------------------------------------------------


def test_state_backing_rust_natskv_available(tmp_path: Path):
    bin_path = _make_executable(tmp_path / "wakir-sb")
    env = {
        STATE_BACKING_BACKEND_ENV: "rust_natskv",
        RUST_STATE_BACKING_BIN_ENV: str(bin_path),
    }
    chosen, decision = resolve_state_backing_backend(env=env)
    assert chosen is StateBackingBackend.RUST_NATSKV
    assert decision.chosen_backend == "rust_natskv"


# ---------------------------------------------------------------------------
# Vector 8 — rust_inmemory + binary present-but-not-executable → fallback.
# ---------------------------------------------------------------------------


def test_state_backing_rust_inmemory_not_executable(tmp_path: Path):
    bin_path = _make_non_executable_file(tmp_path / "wakir-sb")
    env = {
        STATE_BACKING_BACKEND_ENV: "rust_inmemory",
        RUST_STATE_BACKING_BIN_ENV: str(bin_path),
    }
    chosen, decision = resolve_state_backing_backend(env=env)
    assert chosen is StateBackingBackend.PYTHON
    assert decision.fallback_reason == "binary_not_executable"


# ---------------------------------------------------------------------------
# Vector 9 — unknown WAKIR_RECOVERY_BACKEND raises validation error.
# ---------------------------------------------------------------------------


def test_recovery_validation_rejects_unknown():
    env = {RECOVERY_BACKEND_ENV: "wat"}
    with pytest.raises(BackendSwitchValidationError) as ei:
        resolve_recovery_backend(env=env)
    assert ei.value.env_var == RECOVERY_BACKEND_ENV
    assert ei.value.value == "wat"
    assert ei.value.valid_values == VALID_RECOVERY_BACKEND_VALUES


# ---------------------------------------------------------------------------
# Vector 10 — unknown WAKIR_STATE_BACKING_BACKEND raises validation error.
# ---------------------------------------------------------------------------


def test_state_backing_validation_rejects_unknown():
    env = {STATE_BACKING_BACKEND_ENV: "garbage_value"}
    with pytest.raises(BackendSwitchValidationError) as ei:
        resolve_state_backing_backend(env=env)
    assert ei.value.env_var == STATE_BACKING_BACKEND_ENV
    assert ei.value.value == "garbage_value"
    assert ei.value.valid_values == VALID_STATE_BACKING_BACKEND_VALUES


# ---------------------------------------------------------------------------
# Vector 11 — subprocess-bridge state-backing roundtrip.
# ---------------------------------------------------------------------------


def test_rust_state_backing_snapshot_restore_roundtrip():
    calls: List[Tuple] = []

    def fake_invoker(
        bin_path, argv, *, stdin_payload, timeout_s
    ):
        doc = json.loads(stdin_payload.decode("utf-8"))
        calls.append((bin_path, tuple(argv), doc, timeout_s))
        op = doc["op"]
        if op == "snapshot":
            resp = {"offset": 7}
        elif op == "restore_latest":
            resp = {
                "snapshot": {
                    "persona_hash": "sha256:" + "a" * 64,
                    "audit_trace_offset": 7,
                    "capability_token_ids": ["cap-1", "cap-2"],
                    "snapshot_at_utc": "2026-05-17T12:00:00Z",
                    "workspace_state_hash": "sha256:" + "b" * 64,
                }
            }
        else:
            resp = {}
        return 0, json.dumps(resp), ""

    backing = RustSubprocessStateBacking(
        bin_path="/fake/bin",
        timeout_s=1.0,
        kind="rust_inmemory",
        subprocess_invoker=fake_invoker,
    )
    snap = _stub_snapshot()
    offset = backing.snapshot("persona-tomas", snap)
    assert offset == 7

    restored = backing.restore_latest("persona-tomas")
    assert restored is not None
    assert restored.audit_trace_offset == 7
    assert restored.capability_token_ids == ("cap-1", "cap-2")

    # Verify wire format: schema + kind + op present in stdin doc.
    snapshot_call = calls[0]
    assert snapshot_call[2]["schema"] == "wakir.persona-engine.state-backing/1"
    assert snapshot_call[2]["kind"] == "rust_inmemory"
    assert snapshot_call[2]["op"] == "snapshot"


# ---------------------------------------------------------------------------
# Vector 12 — list_snapshots returns offsets list.
# ---------------------------------------------------------------------------


def test_rust_state_backing_list_snapshots():
    def fake_invoker(
        bin_path, argv, *, stdin_payload, timeout_s
    ):
        return 0, json.dumps({"offsets": [0, 1, 2, 3]}), ""

    backing = RustSubprocessStateBacking(
        bin_path="/fake/bin",
        kind="rust_natskv",
        subprocess_invoker=fake_invoker,
    )
    offsets = backing.list_snapshots("persona-x")
    assert offsets == [0, 1, 2, 3]


# ---------------------------------------------------------------------------
# Vector 13 — atomic_swap_pinned_offset invokes subprocess exactly once.
# ---------------------------------------------------------------------------


def test_rust_state_backing_atomic_swap():
    invocations: List = []

    def fake_invoker(
        bin_path, argv, *, stdin_payload, timeout_s
    ):
        invocations.append(json.loads(stdin_payload.decode("utf-8")))
        return 0, json.dumps({"ok": True}), ""

    backing = RustSubprocessStateBacking(
        bin_path="/fake/bin",
        kind="rust_inmemory",
        subprocess_invoker=fake_invoker,
    )
    backing.atomic_swap_pinned_offset("persona-y", 3, 5)
    assert len(invocations) == 1
    assert invocations[0]["op"] == "atomic_swap_pinned_offset"
    assert invocations[0]["payload"] == {
        "persona_id": "persona-y",
        "from_offset": 3,
        "to_offset": 5,
    }


# ---------------------------------------------------------------------------
# Vector 14 — exit_nonzero raises RustBackendError.
# ---------------------------------------------------------------------------


def test_rust_state_backing_exit_nonzero():
    def fake_invoker(
        bin_path, argv, *, stdin_payload, timeout_s
    ):
        return 7, "", "boom"

    backing = RustSubprocessStateBacking(
        bin_path="/fake/bin",
        kind="rust_inmemory",
        subprocess_invoker=fake_invoker,
    )
    with pytest.raises(RustBackendError) as ei:
        backing.list_snapshots("p")
    assert ei.value.reason == "exit_nonzero"
    assert ei.value.returncode == 7


# ---------------------------------------------------------------------------
# Vector 15 — bad_json raises RustBackendError.
# ---------------------------------------------------------------------------


def test_rust_state_backing_bad_json():
    def fake_invoker(
        bin_path, argv, *, stdin_payload, timeout_s
    ):
        return 0, "not-json-at-all", ""

    backing = RustSubprocessStateBacking(
        bin_path="/fake/bin",
        kind="rust_inmemory",
        subprocess_invoker=fake_invoker,
    )
    with pytest.raises(RustBackendError) as ei:
        backing.list_snapshots("p")
    assert ei.value.reason == "bad_json"


# ---------------------------------------------------------------------------
# Vector 16 — subprocess-bridge recovery runner success.
# ---------------------------------------------------------------------------


def test_rust_recovery_runner_success():
    def fake_invoker(
        bin_path, argv, *, stdin_payload, timeout_s
    ):
        doc = json.loads(stdin_payload.decode("utf-8"))
        assert doc["org_id"] == "acme"
        assert doc["persona_id"] == "persona-z"
        assert doc["triggers"]["crash_detected"] is True
        env = {
            "trigger": "CrashDetected",
            "success": True,
            "total_elapsed_sec": 0.12,
            "final_state": "running",
            "phases": [
                {"phase": "R1", "terminal_status": "detected"},
                {"phase": "R2", "terminal_status": "reloaded"},
                {"phase": "R3", "terminal_status": "re_registered"},
                {"phase": "R4", "terminal_status": "resumed"},
            ],
        }
        return 0, json.dumps(env), ""

    runner = RustSubprocessRecoveryRunner(
        bin_path="/fake/bin",
        timeout_s=2.0,
        subprocess_invoker=fake_invoker,
    )
    result = runner.run(
        org_id="acme",
        persona_id="persona-z",
        crash_detected=True,
    )
    assert result["success"] is True
    assert result["final_state"] == "running"
    assert len(result["phases"]) == 4


# ---------------------------------------------------------------------------
# Vector 17 — recovery runner exit_nonzero.
# ---------------------------------------------------------------------------


def test_rust_recovery_runner_exit_nonzero():
    def fake_invoker(
        bin_path, argv, *, stdin_payload, timeout_s
    ):
        return 1, "", "recovery failed"

    runner = RustSubprocessRecoveryRunner(
        bin_path="/fake/bin",
        subprocess_invoker=fake_invoker,
    )
    with pytest.raises(RustBackendError) as ei:
        runner.run(org_id="acme", persona_id="x", crash_detected=True)
    assert ei.value.reason == "exit_nonzero"
    assert ei.value.returncode == 1


# ---------------------------------------------------------------------------
# Vector 18 — per-decision logging emits JSON line to log_sink.
# ---------------------------------------------------------------------------


def test_backend_decision_logged_to_sink(tmp_path: Path):
    bin_path = _make_executable(tmp_path / "wakir-recovery")
    env = {
        RECOVERY_BACKEND_ENV: "rust",
        RUST_RECOVERY_BIN_ENV: str(bin_path),
    }
    sink = io.StringIO()
    chosen, decision = resolve_recovery_backend(env=env, log_sink=sink)
    assert chosen is RecoveryBackend.RUST
    sink_value = sink.getvalue()
    assert sink_value.strip() != ""
    parsed = json.loads(sink_value.strip().splitlines()[-1])
    assert parsed["msg"] == "backend-decision"
    assert parsed["domain"] == "recovery"
    assert parsed["requested_backend"] == "rust"
    assert parsed["chosen_backend"] == "rust"
    assert "resolution_latency_us" in parsed
    assert "bin_path" in parsed


# ---------------------------------------------------------------------------
# Vector 19 — resolution latency is non-negative microseconds.
# ---------------------------------------------------------------------------


def test_resolution_latency_recorded():
    chosen, decision = resolve_recovery_backend(env={})
    assert isinstance(decision.resolution_latency_us, int)
    assert decision.resolution_latency_us >= 0


# ---------------------------------------------------------------------------
# Vector 20 — timeout-env parsing: default / valid / invalid / negative.
# ---------------------------------------------------------------------------


def test_timeout_env_parsing_default():
    assert _resolve_timeout_s(env={}) == DEFAULT_RUST_BACKEND_TIMEOUT_S


def test_timeout_env_parsing_valid():
    assert _resolve_timeout_s(env={RUST_BACKEND_TIMEOUT_ENV: "12.5"}) == 12.5


def test_timeout_env_parsing_invalid_falls_back():
    assert (
        _resolve_timeout_s(env={RUST_BACKEND_TIMEOUT_ENV: "not-a-number"})
        == DEFAULT_RUST_BACKEND_TIMEOUT_S
    )


def test_timeout_env_parsing_negative_falls_back():
    assert (
        _resolve_timeout_s(env={RUST_BACKEND_TIMEOUT_ENV: "-3.0"})
        == DEFAULT_RUST_BACKEND_TIMEOUT_S
    )


def test_timeout_env_parsing_zero_falls_back():
    assert (
        _resolve_timeout_s(env={RUST_BACKEND_TIMEOUT_ENV: "0"})
        == DEFAULT_RUST_BACKEND_TIMEOUT_S
    )


# ---------------------------------------------------------------------------
# Vector 21 — build_state_backing factory: PYTHON path delegates to factory.
# ---------------------------------------------------------------------------


def test_build_state_backing_python_uses_factory():
    sentinel = object()

    def factory():
        return sentinel

    result = build_state_backing(
        StateBackingBackend.PYTHON,
        python_fallback_factory=factory,
    )
    assert result is sentinel


def test_build_state_backing_python_default_inmemory_when_no_factory():
    """No factory + Python backend → InMemoryPersonaStateBacking."""
    from wirelang.persona_engine.state_backing import (
        InMemoryPersonaStateBacking,
    )

    result = build_state_backing(StateBackingBackend.PYTHON)
    assert isinstance(result, InMemoryPersonaStateBacking)


def test_build_state_backing_rust_returns_subprocess_binding():
    result = build_state_backing(
        StateBackingBackend.RUST_INMEMORY,
        env={
            RUST_STATE_BACKING_BIN_ENV: "/some/bin",
            RUST_BACKEND_TIMEOUT_ENV: "2.0",
        },
    )
    assert isinstance(result, RustSubprocessStateBacking)
    assert result.bin_path == "/some/bin"
    assert result.kind == "rust_inmemory"
    assert result.timeout_s == 2.0


# ---------------------------------------------------------------------------
# Vector 22 — default-binary-paths default when env-vars unset.
# ---------------------------------------------------------------------------


def test_default_binary_paths_when_env_unset():
    from wirelang.persona_engine.rust_backend_switch import (
        _resolve_recovery_bin,
        _resolve_state_backing_bin,
    )

    assert _resolve_recovery_bin(env={}) == DEFAULT_RUST_RECOVERY_BIN
    assert (
        _resolve_state_backing_bin(env={}) == DEFAULT_RUST_STATE_BACKING_BIN
    )


# ---------------------------------------------------------------------------
# Vector 23 — log_backend_decision standalone is idempotent.
# ---------------------------------------------------------------------------


def test_log_backend_decision_writes_sink():
    sink = io.StringIO()
    decision = BackendDecision(
        domain="recovery",
        requested_backend="rust",
        chosen_backend="python",
        resolution_latency_us=10,
        fallback_reason="binary_missing",
        bin_path="/no/such/bin",
    )
    log_backend_decision(decision, log_sink=sink)
    parsed = json.loads(sink.getvalue().strip())
    assert parsed["domain"] == "recovery"
    assert parsed["fallback_reason"] == "binary_missing"
    assert parsed["bin_path"] == "/no/such/bin"


# ---------------------------------------------------------------------------
# Vector 24 — empty-string env value defaults to python (parity with unset).
# ---------------------------------------------------------------------------


def test_empty_string_env_defaults_to_python():
    chosen, decision = resolve_recovery_backend(
        env={RECOVERY_BACKEND_ENV: ""}
    )
    assert chosen is RecoveryBackend.PYTHON
    assert decision.fallback_reason is None
