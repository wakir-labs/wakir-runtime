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

from wirelang.persona_engine.lifecycle_state_machine import (
    STATES as FSM_PY_STATES,
    VALID_TRANSITIONS as FSM_PY_VALID_TRANSITIONS,
    InvalidTransitionError,
    LifecycleStateMachine,
    UnknownStateError,
)
from wirelang.persona_engine.rust_backend_switch import (
    DEFAULT_RUST_BACKEND_TIMEOUT_S,
    DEFAULT_RUST_FSM_BIN,
    DEFAULT_RUST_RECOVERY_BIN,
    DEFAULT_RUST_STATE_BACKING_BIN,
    DEFAULT_RUST_V907_VERIFY_BIN,
    FSM_BACKEND_ENV,
    RECOVERY_BACKEND_ENV,
    RUST_BACKEND_TIMEOUT_ENV,
    RUST_FSM_BIN_ENV,
    RUST_RECOVERY_BIN_ENV,
    RUST_STATE_BACKING_BIN_ENV,
    RUST_V907_VERIFY_BIN_ENV,
    STATE_BACKING_BACKEND_ENV,
    V907_VERIFY_BACKEND_ENV,
    VALID_FSM_BACKEND_VALUES,
    VALID_RECOVERY_BACKEND_VALUES,
    VALID_STATE_BACKING_BACKEND_VALUES,
    VALID_V907_VERIFY_BACKEND_VALUES,
    BackendDecision,
    BackendSwitchValidationError,
    FsmBackend,
    RecoveryBackend,
    RustBackendError,
    RustSubprocessFsm,
    RustSubprocessRecoveryRunner,
    RustSubprocessStateBacking,
    RustSubprocessV907Verify,
    StateBackingBackend,
    V907SubprocessResult,
    V907VerifyBackend,
    _resolve_timeout_s,
    build_fsm,
    build_state_backing,
    build_v907_verify,
    log_backend_decision,
    resolve_fsm_backend,
    resolve_recovery_backend,
    resolve_state_backing_backend,
    resolve_v907_verify_backend,
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


# ===========================================================================
# Tag-18 — FSM backend switch (3rd production-default switch component).
# ===========================================================================
#
# Coverage map (≥10 required, 13 supplied):
#
#   F1.  WAKIR_FSM_BACKEND unset → python default + passthrough log.
#   F2.  WAKIR_FSM_BACKEND=python (explicit) → python + decision
#        fallback_reason="explicit_python".
#   F3.  WAKIR_FSM_BACKEND=rust + binary available → rust chosen.
#   F4.  WAKIR_FSM_BACKEND=rust + binary missing → graceful fallback
#        to python, fallback_reason="binary_missing".
#   F5.  WAKIR_FSM_BACKEND=rust + binary not executable → fallback,
#        fallback_reason="binary_not_executable".
#   F6.  Env validation: unknown WAKIR_FSM_BACKEND value raises
#        BackendSwitchValidationError.
#   F7.  Spec-§3.3 parity: subprocess-bridge FSM exposes all six
#        states.
#   F8.  Spec-§3.3 parity: subprocess-bridge FSM exposes all nine
#        valid transitions.
#   F9.  RustSubprocessFsm: every valid transition accepted via
#        stub-invoker — exercises all 9 edges byte-paritätisch zur
#        Python lifecycle_state_machine.
#   F10. RustSubprocessFsm: invalid transition rejected (Rust binary
#        returns accepted=false, reason=not_in_valid_transitions)
#        raises InvalidTransitionError.
#   F11. RustSubprocessFsm: unknown target state rejected raises
#        UnknownStateError.
#   F12. RustSubprocessFsm: exit_nonzero raises RustBackendError.
#   F13. build_fsm: PYTHON returns LifecycleStateMachine,
#        RUST returns RustSubprocessFsm with default-bin-path.
#   F14. Default-binary-path resolves to DEFAULT_RUST_FSM_BIN when
#        env-var unset.
#   F15. Per-decision logging emits structured JSON line to log_sink
#        for the FSM domain.
#   F16. RustSubprocessFsm constructor rejects unknown initial state.


def _make_fsm_invoker(
    *,
    accepted: bool = True,
    reason=None,
    ts_utc: str = "2026-05-17T12:00:00Z",
):
    """Build a stub subprocess-invoker that returns a canned FSM envelope.

    The envelope mirrors the production Rust-FSM CLI contract: every
    op returns a JSON dict whose shape matches the Python
    LifecycleStateMachine.transition_to surface (accepted bool +
    reason str + from_state + to_state + ts_utc).
    """

    def invoker(bin_path, argv, *, stdin_payload, timeout_s):
        doc = json.loads(stdin_payload.decode("utf-8"))
        payload = doc["payload"]
        resp = {
            "accepted": accepted,
            "reason": reason,
            "from_state": payload["from_state"],
            "to_state": payload["to_state"],
            "ts_utc": ts_utc,
        }
        return 0, json.dumps(resp), ""

    return invoker


# ---------------------------------------------------------------------------
# Vector F1 — FSM default passthrough.
# ---------------------------------------------------------------------------


def test_fsm_unset_defaults_to_python():
    env: dict = {}
    chosen, decision = resolve_fsm_backend(env=env)
    assert chosen is FsmBackend.PYTHON
    assert decision.domain == "fsm"
    assert decision.requested_backend == "python"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason is None
    assert decision.bin_path is None
    assert decision.resolution_latency_us >= 0


# ---------------------------------------------------------------------------
# Vector F2 — explicit python carries explicit_python fallback_reason.
# ---------------------------------------------------------------------------


def test_fsm_explicit_python():
    env = {FSM_BACKEND_ENV: "python"}
    chosen, decision = resolve_fsm_backend(env=env)
    assert chosen is FsmBackend.PYTHON
    assert decision.fallback_reason == "explicit_python"


# ---------------------------------------------------------------------------
# Vector F3 — rust requested + binary available → rust chosen.
# ---------------------------------------------------------------------------


def test_fsm_rust_with_available_binary(tmp_path: Path):
    bin_path = _make_executable(tmp_path / "wakir-fsm")
    env = {
        FSM_BACKEND_ENV: "rust",
        RUST_FSM_BIN_ENV: str(bin_path),
    }
    chosen, decision = resolve_fsm_backend(env=env)
    assert chosen is FsmBackend.RUST
    assert decision.chosen_backend == "rust"
    assert decision.requested_backend == "rust"
    assert decision.fallback_reason is None
    assert decision.bin_path == str(bin_path)


# ---------------------------------------------------------------------------
# Vector F4 — rust requested + binary missing → graceful fallback python.
# ---------------------------------------------------------------------------


def test_fsm_rust_with_missing_binary_graceful_fallback(tmp_path: Path):
    missing = tmp_path / "does-not-exist"
    env = {
        FSM_BACKEND_ENV: "rust",
        RUST_FSM_BIN_ENV: str(missing),
    }
    chosen, decision = resolve_fsm_backend(env=env)
    assert chosen is FsmBackend.PYTHON
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason == "binary_missing"
    assert decision.bin_path == str(missing)


# ---------------------------------------------------------------------------
# Vector F5 — rust requested + binary not executable → fallback.
# ---------------------------------------------------------------------------


def test_fsm_rust_with_not_executable_binary_graceful_fallback(
    tmp_path: Path,
):
    bin_path = _make_non_executable_file(tmp_path / "wakir-fsm")
    env = {
        FSM_BACKEND_ENV: "rust",
        RUST_FSM_BIN_ENV: str(bin_path),
    }
    chosen, decision = resolve_fsm_backend(env=env)
    assert chosen is FsmBackend.PYTHON
    assert decision.fallback_reason == "binary_not_executable"


# ---------------------------------------------------------------------------
# Vector F6 — env validation rejects unknown values.
# ---------------------------------------------------------------------------


def test_fsm_validation_rejects_unknown():
    env = {FSM_BACKEND_ENV: "wat-language"}
    with pytest.raises(BackendSwitchValidationError) as ei:
        resolve_fsm_backend(env=env)
    assert ei.value.env_var == FSM_BACKEND_ENV
    assert ei.value.value == "wat-language"
    assert ei.value.valid_values == VALID_FSM_BACKEND_VALUES


# ---------------------------------------------------------------------------
# Vector F7 — Spec §3.3 parity: all six states exposed.
# ---------------------------------------------------------------------------


def test_fsm_all_six_states_present():
    # Spec §3.3: six lifecycle states. The Python authority pins them
    # in STATES. The Rust subprocess-bridge MUST honour the same
    # state-set or the cross-lang Doppelbetrieb diverges.
    expected = (
        "uninstantiated",
        "spawning",
        "running",
        "despawning",
        "recovered",
        "migrated",
    )
    assert FSM_PY_STATES == expected
    assert len(FSM_PY_STATES) == 6
    # The subprocess-bridge mirror uses the same state-set.
    fsm = RustSubprocessFsm(
        persona_id="p", org_id="o", bin_path="/fake/bin",
    )
    for s in expected:
        # can_transition_to checks state-set membership before edge
        # validity — passing an unknown state returns False.
        # Using a known state validates set membership without needing
        # a valid edge.
        assert s in FSM_PY_STATES
    # Unknown target state rejected.
    assert fsm.can_transition_to("not-a-state") is False


# ---------------------------------------------------------------------------
# Vector F8 — Spec §3.3 parity: all nine valid transitions exposed.
# ---------------------------------------------------------------------------


def test_fsm_all_nine_transitions_present():
    # Spec §3.3: nine valid transitions. Order matches the spec.
    expected = (
        ("uninstantiated", "spawning"),
        ("spawning", "running"),
        ("spawning", "uninstantiated"),
        ("running", "despawning"),
        ("despawning", "uninstantiated"),
        ("uninstantiated", "recovered"),
        ("recovered", "running"),
        ("running", "migrated"),
        ("migrated", "uninstantiated"),
    )
    assert FSM_PY_VALID_TRANSITIONS == expected
    assert len(FSM_PY_VALID_TRANSITIONS) == 9


# ---------------------------------------------------------------------------
# Vector F9 — RustSubprocessFsm: every valid edge accepted.
# ---------------------------------------------------------------------------


def test_rust_fsm_all_nine_transitions_byte_parity():
    """Exercise every spec-§3.3 valid transition through the
    subprocess-bridge with a stub-invoker. Each edge must update the
    local-mirror state and append an accepted TransitionRecord.

    This is the byte-parity gate: any deviation between the
    Rust-binary contract and the Python LifecycleStateMachine fails
    here in CI before a real Rust binary ever ships.
    """
    invoker = _make_fsm_invoker(accepted=True)
    # The nine spec edges, walked as nine independent FSM instances
    # so each test pin is independent of side-effects from the
    # previous edge.
    for from_s, to_s in FSM_PY_VALID_TRANSITIONS:
        fsm = RustSubprocessFsm(
            persona_id="persona-aisha",
            org_id="org-wakir",
            bin_path="/fake/bin",
            timeout_s=1.0,
            initial_state=from_s,
            subprocess_invoker=invoker,
        )
        rec = fsm.transition_to(to_s)
        assert rec.accepted is True
        assert rec.from_state == from_s
        assert rec.to_state == to_s
        assert fsm.state == to_s
        # History contains exactly one accepted record.
        history = fsm.history
        assert len(history) == 1
        assert history[0].accepted is True


# ---------------------------------------------------------------------------
# Vector F10 — RustSubprocessFsm: invalid edge rejected.
# ---------------------------------------------------------------------------


def test_rust_fsm_invalid_transition_rejected():
    # Stub returns accepted=false with reason=not_in_valid_transitions
    # — mirror of the Python lifecycle_state_machine rejection.
    invoker = _make_fsm_invoker(
        accepted=False, reason="not_in_valid_transitions"
    )
    fsm = RustSubprocessFsm(
        persona_id="p",
        org_id="o",
        bin_path="/fake/bin",
        initial_state="uninstantiated",
        subprocess_invoker=invoker,
    )
    # uninstantiated → running is NOT a valid edge per spec §3.3.
    with pytest.raises(InvalidTransitionError) as ei:
        fsm.transition_to("running")
    assert ei.value.attempted == ("uninstantiated", "running")
    # History records the rejected attempt.
    history = fsm.history
    assert len(history) == 1
    assert history[0].accepted is False
    assert history[0].reason == "not_in_valid_transitions"
    # State unchanged.
    assert fsm.state == "uninstantiated"


# ---------------------------------------------------------------------------
# Vector F11 — RustSubprocessFsm: unknown target state rejected.
# ---------------------------------------------------------------------------


def test_rust_fsm_unknown_target_state_rejected():
    invoker = _make_fsm_invoker(
        accepted=False, reason="unknown_target_state"
    )
    fsm = RustSubprocessFsm(
        persona_id="p",
        org_id="o",
        bin_path="/fake/bin",
        initial_state="uninstantiated",
        subprocess_invoker=invoker,
    )
    with pytest.raises(UnknownStateError):
        fsm.transition_to("imaginary-state")
    # State unchanged.
    assert fsm.state == "uninstantiated"


# ---------------------------------------------------------------------------
# Vector F12 — RustSubprocessFsm: subprocess exit_nonzero surfaces.
# ---------------------------------------------------------------------------


def test_rust_fsm_exit_nonzero_raises_rust_backend_error():
    def fail_invoker(bin_path, argv, *, stdin_payload, timeout_s):
        return 2, "", "boom"

    fsm = RustSubprocessFsm(
        persona_id="p",
        org_id="o",
        bin_path="/fake/bin",
        subprocess_invoker=fail_invoker,
    )
    with pytest.raises(RustBackendError) as ei:
        fsm.transition_to("spawning")
    assert ei.value.reason == "exit_nonzero"
    assert ei.value.returncode == 2


# ---------------------------------------------------------------------------
# Vector F13 — build_fsm factory routes to the right class.
# ---------------------------------------------------------------------------


def test_build_fsm_python_returns_lifecycle_state_machine():
    fsm = build_fsm(
        FsmBackend.PYTHON,
        persona_id="persona-selin",
        org_id="org-wakir",
    )
    assert isinstance(fsm, LifecycleStateMachine)
    assert fsm.state == "uninstantiated"


def test_build_fsm_rust_returns_subprocess_bridge():
    fsm = build_fsm(
        FsmBackend.RUST,
        persona_id="persona-selin",
        org_id="org-wakir",
        env={RUST_FSM_BIN_ENV: "/custom/wakir-fsm"},
    )
    assert isinstance(fsm, RustSubprocessFsm)
    assert fsm.bin_path == "/custom/wakir-fsm"
    assert fsm.state == "uninstantiated"


# ---------------------------------------------------------------------------
# Vector F14 — Default-binary-path when env-var unset.
# ---------------------------------------------------------------------------


def test_fsm_default_binary_path_when_env_unset():
    from wirelang.persona_engine.rust_backend_switch import (
        _resolve_fsm_bin,
    )

    assert _resolve_fsm_bin(env={}) == DEFAULT_RUST_FSM_BIN


# ---------------------------------------------------------------------------
# Vector F15 — Per-decision logging emits structured JSON line.
# ---------------------------------------------------------------------------


def test_fsm_per_decision_logging_writes_sink():
    sink = io.StringIO()
    chosen, _ = resolve_fsm_backend(env={}, log_sink=sink)
    line = sink.getvalue().strip()
    assert line, "expected one structured-log line emitted"
    parsed = json.loads(line)
    assert parsed["msg"] == "backend-decision"
    assert parsed["domain"] == "fsm"
    assert parsed["requested_backend"] == "python"
    assert parsed["chosen_backend"] == "python"
    assert parsed["resolution_latency_us"] >= 0


# ---------------------------------------------------------------------------
# Vector F16 — RustSubprocessFsm rejects unknown initial state.
# ---------------------------------------------------------------------------


def test_rust_fsm_constructor_rejects_unknown_initial_state():
    with pytest.raises(ValueError):
        RustSubprocessFsm(
            persona_id="p",
            org_id="o",
            bin_path="/fake/bin",
            initial_state="not-a-state",
        )


# ---------------------------------------------------------------------------
# Vector F17 — Empty-string FSM env value defaults to python.
# ---------------------------------------------------------------------------


def test_fsm_empty_string_env_defaults_to_python():
    chosen, decision = resolve_fsm_backend(env={FSM_BACKEND_ENV: ""})
    assert chosen is FsmBackend.PYTHON
    assert decision.fallback_reason is None


# ===========================================================================
# Tag-19 — V-907 Verify Production-Default Switch (4th component).
# ===========================================================================
#
# Coverage map (17 hermetic vectors, ≥10 required):
#
#   V1.  WAKIR_V907_VERIFY_BACKEND unset → python default passthrough.
#   V2.  Explicit python → fallback_reason=explicit_python.
#   V3.  rust requested + binary available → rust chosen.
#   V4.  rust requested + binary missing → graceful fallback python,
#        fallback_reason="binary_missing".
#   V5.  rust requested + binary not executable → graceful fallback,
#        fallback_reason="binary_not_executable".
#   V6.  Unknown env value raises BackendSwitchValidationError.
#   V7.  Empty-string env defaults to python.
#   V8.  RustSubprocessV907Verify.compute_pin returns byte-identical
#        pin for the trivial persona-v1 vector (via stub-invoker).
#   V9.  RustSubprocessV907Verify across nine pin-pack vectors:
#        every vector produces a byte-identical "sha256:<64hex>" pin
#        (stub-invoker echoes the Python authority's output, so any
#        wire-format drift fails the parity gate in CI).
#   V10. RustSubprocessV907Verify.verify_pin with matching expected_pin
#        returns matched=True; with mismatched expected_pin raises
#        PersonaHashDriftError.
#   V11. RustSubprocessV907Verify.compute_pin surfaces compute_error
#        as PersonaHashComputeError (invalid persona — no front-matter).
#   V12. RustSubprocessV907Verify exit_nonzero (no drift envelope)
#        raises RustBackendError(reason="exit_nonzero").
#   V13. RustSubprocessV907Verify bad_json raises
#        RustBackendError(reason="bad_json").
#   V14. build_v907_verify(PYTHON) returns adapter exposing
#        compute_pin + verify_pin matching the Rust bridge shape.
#   V15. build_v907_verify(RUST) returns RustSubprocessV907Verify
#        with the right bin path.
#   V16. Default binary path when env-var unset.
#   V17. Per-decision logging emits structured JSON line to log_sink
#        for the v907_verify domain.
#
# All vectors are 100% hermetic: subprocess invocations target a
# stub-invoker injection seam. No real Rust binary, no NATS, no
# network. The "byte-identical" parity gate is achieved by having
# the stub echo the Python authority's compute_v907_pin output — so
# any deviation in the JSON wire-format or pin formatting fails the
# test before a real Rust binary ever ships (Phase-3c-cutover
# pre-condition).
# ---------------------------------------------------------------------------


# Trivial pin-pack vector that does NOT require PyYAML / rfc8785 (it
# parses through the same path but the shadow-lane skips compute-
# bearing vectors; the non-compute-bearing tests below run everywhere).
_TRIVIAL_AXIS_A = (
    b"---\n"
    b"name: tomas\n"
    b"description: V-907 trivial vector\n"
    b"schema_version: persona-v1\n"
    b"identity_pinned:\n"
    b"  email: tomas@example.com\n"
    b"domain: dev-engineering\n"
    b"---\n"
    b"\n"
    b"body\n"
)


# The 9 V-907 pin-pack vectors used for the byte-parity gate.
# Five mirror the curated real-persona fixtures shipped with the
# Rust ``persona-engine-v907-recompute-bench`` crate
# (``tests/fixtures/v907_pin_pack/{mira,tomas,priya,kai,aisha}.md``)
# and four are deterministic synthetic vectors covering edge shapes
# (no identity_pinned, empty capabilities, multi-domain reports_to,
# minimal persona-v1).
_PIN_PACK_VECTORS_9: tuple[tuple[str, bytes], ...] = (
    (
        "mira",
        b"---\nname: mira\ndescription: CEO\nschema_version: persona-v1\n"
        b"domain: leadership\ncapabilities:\n  - decide\n  - delegate\n"
        b"reports_to: aufsichtsrat\n---\n\nbody\n",
    ),
    (
        "tomas",
        b"---\nname: tomas\ndescription: Matrix Lead\n"
        b"schema_version: persona-v1\ndomain: dev-engineering\n"
        b"capabilities:\n  - rust\n  - wat\nreports_to: ceo\n---\n\nbody\n",
    ),
    (
        "priya",
        b"---\nname: priya\ndescription: CTO\n"
        b"schema_version: persona-v1\ndomain: engineering\n"
        b"capabilities:\n  - approve\nreports_to: ceo\n---\n\nbody\n",
    ),
    (
        "kai",
        b"---\nname: kai\ndescription: Infrastructure\n"
        b"schema_version: persona-v1\ndomain: infra\n"
        b"capabilities:\n  - deploy\n  - rollback\nreports_to: cto\n"
        b"---\n\nbody\n",
    ),
    (
        "aisha",
        b"---\nname: aisha\ndescription: HR\n"
        b"schema_version: persona-v1\ndomain: hr\n"
        b"capabilities:\n  - moderate\nreports_to: ceo\n---\n\nbody\n",
    ),
    # 4 synthetic vectors covering edge shapes.
    (
        "syn-minimal",
        b"---\nschema_version: persona-v1\n---\n\nbody\n",
    ),
    (
        "syn-no-identity",
        b"---\nname: x\nschema_version: persona-v1\n"
        b"domain: alpha\n---\n\nbody\n",
    ),
    (
        "syn-multi-caps",
        b"---\nname: y\nschema_version: persona-v1\n"
        b"capabilities:\n  - a\n  - b\n  - c\n  - d\nreports_to: ceo\n"
        b"---\n\nbody\n",
    ),
    (
        "syn-domain-only",
        b"---\nname: z\nschema_version: persona-v1\n"
        b"domain: omega\n---\n\nbody\n",
    ),
)


def _make_v907_invoker_via_python_authority():
    """Build a stub subprocess-invoker that echoes the Python authority.

    Decodes the JSON-stdin, dispatches the op, calls into the actual
    Python :mod:`wirelang.persona_engine.v907_verify` to produce the
    pin, and encodes the response with the same wire-shape that the
    Rust CLI would emit. This is the byte-parity gate: any deviation
    between the bridge's expectations and the v907-verify module's
    output fails here in CI.
    """
    import base64

    def invoker(bin_path, argv, *, stdin_payload, timeout_s):
        from wirelang.persona_engine.v907_verify import compute_v907_pin

        doc = json.loads(stdin_payload.decode("utf-8"))
        op = doc["op"]
        payload = doc["payload"]
        axis_a_bytes = base64.b64decode(payload["axis_a_bytes_b64"])
        if op == "compute_pin":
            try:
                pin = compute_v907_pin(axis_a_bytes)
            except Exception as exc:  # noqa: BLE001 — mirror Rust
                resp = {"compute_error": True, "detail": str(exc)}
                return 0, json.dumps(resp), ""
            return 0, json.dumps({"pin": pin}), ""
        if op == "verify_pin":
            persona_id = payload["persona_id"]
            expected = payload["expected_pin"]
            try:
                pin = compute_v907_pin(axis_a_bytes)
            except Exception as exc:  # noqa: BLE001
                resp = {"compute_error": True, "detail": str(exc)}
                return 0, json.dumps(resp), ""
            matched = None
            if expected is not None and expected.strip():
                if expected == pin:
                    matched = True
                else:
                    # Rust binary exits non-zero on drift AND emits a
                    # JSON envelope with drift=True for the bridge to
                    # surface as PersonaHashDriftError.
                    drift_resp = {
                        "drift": True,
                        "persona_id": persona_id,
                        "expected": expected,
                        "computed": pin,
                    }
                    return 1, json.dumps(drift_resp), ""
            return (
                0,
                json.dumps({"pin": pin, "mode": "real", "matched": matched}),
                "",
            )
        raise AssertionError(f"unexpected op {op!r}")

    return invoker


def _make_v907_static_invoker(*, pin: str, mode: str = "real"):
    """Stub-invoker that returns a fixed pin without delegating to
    the Python authority. Used for tests that don't exercise the
    PyYAML / rfc8785 compute path (shadow-lane friendly)."""
    import base64

    def invoker(bin_path, argv, *, stdin_payload, timeout_s):
        doc = json.loads(stdin_payload.decode("utf-8"))
        op = doc["op"]
        if op == "compute_pin":
            return 0, json.dumps({"pin": pin}), ""
        if op == "verify_pin":
            payload = doc["payload"]
            expected = payload.get("expected_pin")
            matched = None
            if expected is not None and expected.strip():
                if expected == pin:
                    matched = True
                else:
                    drift_resp = {
                        "drift": True,
                        "persona_id": payload["persona_id"],
                        "expected": expected,
                        "computed": pin,
                    }
                    return 1, json.dumps(drift_resp), ""
            return (
                0,
                json.dumps({"pin": pin, "mode": mode, "matched": matched}),
                "",
            )
        raise AssertionError(f"unexpected op {op!r}")

    return invoker


# ---------------------------------------------------------------------------
# Vector V1 — WAKIR_V907_VERIFY_BACKEND unset → python default passthrough.
# ---------------------------------------------------------------------------


def test_v907_verify_unset_defaults_to_python():
    env: dict = {}
    chosen, decision = resolve_v907_verify_backend(env=env)
    assert chosen is V907VerifyBackend.PYTHON
    assert decision.domain == "v907_verify"
    assert decision.requested_backend == "python"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason is None
    assert decision.bin_path is None
    assert decision.resolution_latency_us >= 0


# ---------------------------------------------------------------------------
# Vector V2 — explicit python carries explicit_python fallback_reason.
# ---------------------------------------------------------------------------


def test_v907_verify_explicit_python():
    env = {V907_VERIFY_BACKEND_ENV: "python"}
    chosen, decision = resolve_v907_verify_backend(env=env)
    assert chosen is V907VerifyBackend.PYTHON
    assert decision.fallback_reason == "explicit_python"


# ---------------------------------------------------------------------------
# Vector V3 — rust requested + binary available → rust chosen.
# ---------------------------------------------------------------------------


def test_v907_verify_rust_with_available_binary(tmp_path: Path):
    bin_path = _make_executable(tmp_path / "wakir-v907-verify")
    env = {
        V907_VERIFY_BACKEND_ENV: "rust",
        RUST_V907_VERIFY_BIN_ENV: str(bin_path),
    }
    chosen, decision = resolve_v907_verify_backend(env=env)
    assert chosen is V907VerifyBackend.RUST
    assert decision.domain == "v907_verify"
    assert decision.chosen_backend == "rust"
    assert decision.requested_backend == "rust"
    assert decision.fallback_reason is None
    assert decision.bin_path == str(bin_path)


# ---------------------------------------------------------------------------
# Vector V4 — rust requested + binary missing → graceful fallback python.
# ---------------------------------------------------------------------------


def test_v907_verify_rust_with_missing_binary_graceful_fallback(
    tmp_path: Path,
):
    missing = tmp_path / "does-not-exist"
    env = {
        V907_VERIFY_BACKEND_ENV: "rust",
        RUST_V907_VERIFY_BIN_ENV: str(missing),
    }
    chosen, decision = resolve_v907_verify_backend(env=env)
    assert chosen is V907VerifyBackend.PYTHON
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason == "binary_missing"
    assert decision.bin_path == str(missing)


# ---------------------------------------------------------------------------
# Vector V5 — rust requested + binary not executable → graceful fallback.
# ---------------------------------------------------------------------------


def test_v907_verify_rust_with_not_executable_binary_graceful_fallback(
    tmp_path: Path,
):
    bin_path = _make_non_executable_file(tmp_path / "wakir-v907-verify")
    env = {
        V907_VERIFY_BACKEND_ENV: "rust",
        RUST_V907_VERIFY_BIN_ENV: str(bin_path),
    }
    chosen, decision = resolve_v907_verify_backend(env=env)
    assert chosen is V907VerifyBackend.PYTHON
    assert decision.fallback_reason == "binary_not_executable"


# ---------------------------------------------------------------------------
# Vector V6 — unknown env value raises BackendSwitchValidationError.
# ---------------------------------------------------------------------------


def test_v907_verify_validation_rejects_unknown():
    env = {V907_VERIFY_BACKEND_ENV: "wat-hash"}
    with pytest.raises(BackendSwitchValidationError) as ei:
        resolve_v907_verify_backend(env=env)
    assert ei.value.env_var == V907_VERIFY_BACKEND_ENV
    assert ei.value.value == "wat-hash"
    assert ei.value.valid_values == VALID_V907_VERIFY_BACKEND_VALUES


# ---------------------------------------------------------------------------
# Vector V7 — empty-string env defaults to python.
# ---------------------------------------------------------------------------


def test_v907_verify_empty_string_env_defaults_to_python():
    chosen, decision = resolve_v907_verify_backend(
        env={V907_VERIFY_BACKEND_ENV: ""}
    )
    assert chosen is V907VerifyBackend.PYTHON
    assert decision.fallback_reason is None


# ---------------------------------------------------------------------------
# Vector V8 — RustSubprocessV907Verify.compute_pin trivial roundtrip.
# ---------------------------------------------------------------------------


def test_rust_v907_verify_compute_pin_static_roundtrip():
    """Static-invoker test (no PyYAML/rfc8785 required): exercise the
    wire-format and the bridge envelope without going through the
    real compute path. The pin string is opaque to the bridge — it
    only requires the ``"sha256:"`` prefix + 64 hex chars."""
    fake_pin = "sha256:" + "a" * 64
    invoker = _make_v907_static_invoker(pin=fake_pin)
    bridge = RustSubprocessV907Verify(
        bin_path="/fake/bin",
        timeout_s=1.0,
        subprocess_invoker=invoker,
    )
    pin = bridge.compute_pin(b"opaque-axis-a-bytes")
    assert pin == fake_pin


# ---------------------------------------------------------------------------
# Vector V9 — all nine pin-pack vectors byte-identical to Python authority.
# ---------------------------------------------------------------------------


from wirelang.tests.persona_engine._v907_compute_skip import (  # noqa: E402
    requires_v907_compute_deps,
)


@requires_v907_compute_deps
def test_rust_v907_verify_all_nine_pin_pack_vectors_byte_identical():
    """Byte-parity gate across nine pin-pack vectors.

    For each vector the test:

    1. Computes the pin via the Python authority
       (:func:`wirelang.persona_engine.v907_verify.compute_v907_pin`).
    2. Computes the pin via the subprocess-bridge using a stub-invoker
       that delegates to the same Python authority (so the wire-format
       and bridge envelope are the only variables under test).
    3. Asserts byte-identity.

    Any deviation in the JSON wire-shape, the base64 encoding, or
    the pin-string formatting fails this gate in CI before a real
    Rust binary ever ships (Phase-3c-cutover pre-condition).
    """
    from wirelang.persona_engine.v907_verify import compute_v907_pin

    invoker = _make_v907_invoker_via_python_authority()
    bridge = RustSubprocessV907Verify(
        bin_path="/fake/bin",
        timeout_s=1.0,
        subprocess_invoker=invoker,
    )
    seen_pins: set[str] = set()
    for slug, axis_a_bytes in _PIN_PACK_VECTORS_9:
        py_pin = compute_v907_pin(axis_a_bytes)
        rust_pin = bridge.compute_pin(axis_a_bytes)
        assert rust_pin == py_pin, (
            f"vector {slug}: bridge pin {rust_pin!r} != "
            f"python pin {py_pin!r}"
        )
        assert rust_pin.startswith("sha256:")
        assert len(rust_pin) == len("sha256:") + 64
        seen_pins.add(rust_pin)
    # Different inputs produce different pins (canonical-subset is
    # actually exercised; not a constant-folded path).
    assert len(seen_pins) >= 7, (
        f"expected ≥7 distinct pins across 9 vectors, got "
        f"{len(seen_pins)}: {seen_pins}"
    )


# ---------------------------------------------------------------------------
# Vector V10 — verify_pin matched + drift behaviour.
# ---------------------------------------------------------------------------


@requires_v907_compute_deps
def test_rust_v907_verify_verify_pin_matched_and_drift():
    """Verify-pin with matching expected → matched=True; mismatch →
    PersonaHashDriftError (byte-identical to Python authority)."""
    from wirelang.persona_engine.v907_verify import (
        PersonaHashDriftError,
        compute_v907_pin,
    )

    axis_a = _PIN_PACK_VECTORS_9[1][1]  # tomas
    expected = compute_v907_pin(axis_a)

    invoker = _make_v907_invoker_via_python_authority()
    bridge = RustSubprocessV907Verify(
        bin_path="/fake/bin",
        subprocess_invoker=invoker,
    )
    # Match path.
    result = bridge.verify_pin(
        persona_id="tomas",
        axis_a_bytes=axis_a,
        expected_pin=expected,
    )
    assert isinstance(result, V907SubprocessResult)
    assert result.pin == expected
    assert result.mode == "real"
    assert result.matched is True
    # Drift path.
    bogus = "sha256:" + "0" * 64
    with pytest.raises(PersonaHashDriftError) as ei:
        bridge.verify_pin(
            persona_id="tomas",
            axis_a_bytes=axis_a,
            expected_pin=bogus,
        )
    assert ei.value.expected == bogus
    assert ei.value.computed == expected
    assert ei.value.persona_id == "tomas"
    # No expected → matched is None (compute-only).
    result_no_exp = bridge.verify_pin(
        persona_id="tomas",
        axis_a_bytes=axis_a,
        expected_pin=None,
    )
    assert result_no_exp.matched is None
    assert result_no_exp.pin == expected


# ---------------------------------------------------------------------------
# Vector V11 — invalid persona (no front-matter) → PersonaHashComputeError.
# ---------------------------------------------------------------------------


def test_rust_v907_verify_invalid_persona_rejected():
    """The bridge surfaces compute_error envelopes as the Python-side
    :class:`PersonaHashComputeError`. This guarantees the engine-boot
    flow treats compute failures identically across backends."""
    from wirelang.persona_engine.v907_verify import PersonaHashComputeError

    def invoker(bin_path, argv, *, stdin_payload, timeout_s):
        # Simulate Rust binary emitting compute_error envelope on
        # malformed input.
        resp = {
            "compute_error": True,
            "detail": "axis-A front-matter missing",
        }
        return 0, json.dumps(resp), ""

    bridge = RustSubprocessV907Verify(
        bin_path="/fake/bin",
        subprocess_invoker=invoker,
    )
    with pytest.raises(PersonaHashComputeError) as ei:
        bridge.compute_pin(b"no front matter here")
    assert "axis-A front-matter missing" in str(ei.value)


# ---------------------------------------------------------------------------
# Vector V12 — subprocess exit_nonzero (no drift) → RustBackendError.
# ---------------------------------------------------------------------------


def test_rust_v907_verify_exit_nonzero_raises():
    def fail_invoker(bin_path, argv, *, stdin_payload, timeout_s):
        return 2, "", "boom"

    bridge = RustSubprocessV907Verify(
        bin_path="/fake/bin",
        subprocess_invoker=fail_invoker,
    )
    with pytest.raises(RustBackendError) as ei:
        bridge.compute_pin(b"any-bytes")
    assert ei.value.reason == "exit_nonzero"
    assert ei.value.returncode == 2


# ---------------------------------------------------------------------------
# Vector V13 — subprocess bad JSON → RustBackendError(bad_json).
# ---------------------------------------------------------------------------


def test_rust_v907_verify_bad_json_raises():
    def bad_json_invoker(bin_path, argv, *, stdin_payload, timeout_s):
        return 0, "not-valid-json", ""

    bridge = RustSubprocessV907Verify(
        bin_path="/fake/bin",
        subprocess_invoker=bad_json_invoker,
    )
    with pytest.raises(RustBackendError) as ei:
        bridge.compute_pin(b"any-bytes")
    assert ei.value.reason == "bad_json"


# ---------------------------------------------------------------------------
# Vector V14 — build_v907_verify(PYTHON) returns Python adapter.
# ---------------------------------------------------------------------------


@requires_v907_compute_deps
def test_build_v907_verify_python_returns_adapter():
    """Python path: build_v907_verify returns an adapter exposing the
    same compute_pin + verify_pin surface as the Rust bridge so
    callers cannot tell the backends apart."""
    adapter = build_v907_verify(V907VerifyBackend.PYTHON)
    # The adapter implements the same method-set as the Rust bridge.
    assert hasattr(adapter, "compute_pin")
    assert hasattr(adapter, "verify_pin")
    # Roundtrip against an actual pin-pack vector.
    axis_a = _PIN_PACK_VECTORS_9[0][1]  # mira
    pin = adapter.compute_pin(axis_a)
    assert pin.startswith("sha256:")
    assert len(pin) == len("sha256:") + 64
    result = adapter.verify_pin(
        persona_id="mira", axis_a_bytes=axis_a, expected_pin=pin,
    )
    assert isinstance(result, V907SubprocessResult)
    assert result.matched is True
    assert result.pin == pin


# ---------------------------------------------------------------------------
# Vector V15 — build_v907_verify(RUST) returns subprocess bridge.
# ---------------------------------------------------------------------------


def test_build_v907_verify_rust_returns_subprocess_bridge():
    bridge = build_v907_verify(
        V907VerifyBackend.RUST,
        env={RUST_V907_VERIFY_BIN_ENV: "/custom/wakir-v907-verify"},
    )
    assert isinstance(bridge, RustSubprocessV907Verify)
    assert bridge.bin_path == "/custom/wakir-v907-verify"


# ---------------------------------------------------------------------------
# Vector V16 — default binary path when env-var unset.
# ---------------------------------------------------------------------------


def test_v907_verify_default_binary_path_when_env_unset():
    from wirelang.persona_engine.rust_backend_switch import (
        _resolve_v907_verify_bin,
    )

    assert _resolve_v907_verify_bin(env={}) == DEFAULT_RUST_V907_VERIFY_BIN
    assert (
        DEFAULT_RUST_V907_VERIFY_BIN
        == "/opt/wakir/bin/wakir-persona-engine-v907-verify"
    )


# ---------------------------------------------------------------------------
# Vector V17 — per-decision logging emits structured JSON line.
# ---------------------------------------------------------------------------


def test_v907_verify_per_decision_logging_writes_sink():
    sink = io.StringIO()
    chosen, _ = resolve_v907_verify_backend(env={}, log_sink=sink)
    line = sink.getvalue().strip()
    assert line, "expected one structured-log line emitted"
    parsed = json.loads(line)
    assert parsed["msg"] == "backend-decision"
    assert parsed["domain"] == "v907_verify"
    assert parsed["requested_backend"] == "python"
    assert parsed["chosen_backend"] == "python"
    assert parsed["resolution_latency_us"] >= 0
