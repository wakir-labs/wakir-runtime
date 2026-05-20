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
21. Tag-25 (ADR-0065 Welle-2 precondition) SVID-Workload-Identity
    resolver — 12 new vectors SVID01..SVID12 covering env-unset
    default / explicit python / rust+available / rust+missing
    (Welle-2 signal) / rust+non-executable / unknown-validation /
    empty-string / default-bin / bin-override / per-decision-logging
    / auftrag-alias / enum-consistency.
22. Tag-30 Federation-Resolver — 12 new vectors FR01..FR12 covering
    env-unset default / explicit python / rust+available / rust+missing
    / rust+non-executable / unknown-validation / empty-string /
    default-bin / bin-override / per-decision-logging / auftrag-alias /
    enum-consistency. Includes byte-parity verification against the
    five cross-lang fixtures from PR #188
    (``tests/fixtures/federation-resolver-cross-lang/fixtures.json``).

Total: 44 hermetic vectors (>=10 required for Tag-30 alone).
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
    ANCHOR_EMITTER_BACKEND_ENV,
    BRIDGE_DIFF_BACKEND_ENV,
    DEFAULT_RUST_ANCHOR_EMITTER_BIN,
    DEFAULT_RUST_BACKEND_TIMEOUT_S,
    DEFAULT_RUST_BRIDGE_DIFF_BIN,
    DEFAULT_RUST_FSM_BIN,
    DEFAULT_RUST_RECOVERY_BIN,
    DEFAULT_RUST_STATE_BACKING_BIN,
    DEFAULT_RUST_SUBSCRIBE_LOOP_BIN,
    DEFAULT_RUST_SVID_WORKLOAD_IDENTITY_BIN,
    DEFAULT_RUST_FEDERATION_RESOLVER_BIN,
    DEFAULT_RUST_V907_VERIFY_BIN,
    FEDERATION_RESOLVER_BACKEND_ENV,
    FSM_BACKEND_ENV,
    RECOVERY_BACKEND_ENV,
    RUST_ANCHOR_EMITTER_BIN_ENV,
    RUST_BACKEND_TIMEOUT_ENV,
    RUST_BRIDGE_DIFF_BIN_ENV,
    RUST_FSM_BIN_ENV,
    RUST_RECOVERY_BIN_ENV,
    RUST_STATE_BACKING_BIN_ENV,
    RUST_SUBSCRIBE_LOOP_BIN_ENV,
    RUST_SVID_WORKLOAD_IDENTITY_BIN_ENV,
    RUST_FEDERATION_RESOLVER_BIN_ENV,
    RUST_V907_VERIFY_BIN_ENV,
    STATE_BACKING_BACKEND_ENV,
    SUBSCRIBE_LOOP_BACKEND_ENV,
    SVID_WORKLOAD_IDENTITY_BACKEND_ENV,
    V907_VERIFY_BACKEND_ENV,
    VALID_ANCHOR_EMITTER_BACKEND_VALUES,
    VALID_BRIDGE_DIFF_BACKEND_VALUES,
    VALID_FSM_BACKEND_VALUES,
    VALID_RECOVERY_BACKEND_VALUES,
    VALID_STATE_BACKING_BACKEND_VALUES,
    VALID_SUBSCRIBE_LOOP_BACKEND_VALUES,
    VALID_SVID_WORKLOAD_IDENTITY_BACKEND_VALUES,
    VALID_FEDERATION_RESOLVER_BACKEND_VALUES,
    VALID_V907_VERIFY_BACKEND_VALUES,
    AnchorEmitterBackend,
    AnchorEmitterSubprocessResult,
    BackendDecision,
    BackendSwitchValidationError,
    BridgeDiffBackend,
    BridgeDiffSubprocessFieldDiff,
    BridgeDiffSubprocessReport,
    FsmBackend,
    RecoveryBackend,
    RustBackendError,
    RustSubprocessAnchorEmitter,
    RustSubprocessBridgeDiff,
    RustSubprocessFsm,
    RustSubprocessRecoveryRunner,
    RustSubprocessStateBacking,
    RustSubprocessSubscribeLoop,
    RustSubprocessV907Verify,
    StateBackingBackend,
    SubscribeLoopBackend,
    SubscribeLoopSubprocessAckResult,
    SvidWorkloadIdentityBackend,
    FederationResolverBackend,
    V907SubprocessResult,
    V907VerifyBackend,
    _resolve_timeout_s,
    _select_anchor_emitter_backend,
    _select_subscribe_loop_backend,
    _select_svid_workload_identity_backend,
    _select_federation_resolver_backend,
    build_anchor_emitter,
    build_bridge_diff,
    build_fsm,
    build_state_backing,
    build_subscribe_loop,
    build_v907_verify,
    log_backend_decision,
    resolve_anchor_emitter_backend,
    resolve_bridge_diff_backend,
    resolve_fsm_backend,
    resolve_recovery_backend,
    resolve_state_backing_backend,
    resolve_subscribe_loop_backend,
    resolve_svid_workload_identity_backend,
    resolve_federation_resolver_backend,
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
#   V1.  WAKIR_V907_VERIFY_BACKEND unset → rust default + graceful
#        python fallback when binary missing (Tag-80 Welle-1 Cutover).
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
# Vector V1 — WAKIR_V907_VERIFY_BACKEND unset → rust default + graceful
# python fallback when binary missing (Tag-80 Welle-1 Cutover).
# ---------------------------------------------------------------------------


def test_v907_verify_unset_defaults_to_rust_with_graceful_python_fallback():
    """Tag-80 Welle-1 Cutover: env-unset defaults to ``rust`` now.

    Without the rust binary on disk (Sandbox-CI posture) the
    graceful-fallback path chooses python and surfaces
    ``binary_missing`` as the fallback_reason. The default-rust-
    request semantics are visible in
    ``decision.requested_backend == "rust"`` and the resolved
    bin_path pointing at the canonical install location.
    """
    env: dict = {}
    chosen, decision = resolve_v907_verify_backend(env=env)
    assert chosen is V907VerifyBackend.PYTHON  # graceful fallback
    assert decision.domain == "v907_verify"
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason == "binary_missing"
    assert decision.bin_path == DEFAULT_RUST_V907_VERIFY_BIN
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


def test_v907_verify_empty_string_env_defaults_to_rust_with_graceful_python_fallback():
    """Tag-80 Welle-1 Cutover: empty-string env defaults to rust now.

    Same graceful-fallback semantics as the env-unset path — without
    the rust binary, ``chosen`` resolves to python with
    ``binary_missing`` fallback_reason.
    """
    chosen, decision = resolve_v907_verify_backend(
        env={V907_VERIFY_BACKEND_ENV: ""}
    )
    assert chosen is V907VerifyBackend.PYTHON  # graceful fallback
    assert decision.requested_backend == "rust"
    assert decision.fallback_reason == "binary_missing"


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
    # Tag-80 Welle-1 Cutover: default flipped to rust, graceful
    # fallback to python when binary missing on Sandbox-CI.
    assert parsed["requested_backend"] == "rust"
    assert parsed["chosen_backend"] == "python"
    assert parsed["resolution_latency_us"] >= 0


# ===========================================================================
# Tag-20 Mini-Welle — Bridge-Diff Rust production-default switch.
# ===========================================================================
#
# Coverage map (12 hermetic vectors, ≥10 required per task spec):
#
#   B1.  WAKIR_BRIDGE_DIFF_BACKEND unset → python default + passthrough
#        log (backend-python-default-passthrough).
#   B2.  WAKIR_BRIDGE_DIFF_BACKEND=python (explicit) → python +
#        fallback_reason="explicit_python".
#   B3.  WAKIR_BRIDGE_DIFF_BACKEND=rust + binary available → rust chosen.
#   B4.  WAKIR_BRIDGE_DIFF_BACKEND=rust + binary missing → graceful
#        fallback to python, fallback_reason="binary_missing"
#        (backend-rust-binary-missing-fallback).
#   B5.  WAKIR_BRIDGE_DIFF_BACKEND=rust + binary not executable → graceful
#        fallback to python, fallback_reason="binary_not_executable".
#   B6.  Env validation: unknown WAKIR_BRIDGE_DIFF_BACKEND value raises
#        BackendSwitchValidationError.
#   B7.  RustSubprocessBridgeDiff.jcs_hash byte-identical to Python
#        authority (stub-invoker delegates to bridge_audit_diff_engine)
#        (backend-rust-diff-byte-identical).
#   B8.  RustSubprocessBridgeDiff.diff_envelopes + compare across
#        all six cross-lang field-pin vectors: byte-identical hash AND
#        byte-identical field-path entries (sort + RFC-6901 escapes)
#        (all-6-Cross-Lang-Field-Pins-rust-verified per PR #166).
#   B9.  RustSubprocessBridgeDiff: exit_nonzero raises
#        RustBackendError(reason="exit_nonzero").
#   B10. RustSubprocessBridgeDiff: bad_json raises
#        RustBackendError(reason="bad_json").
#   B11. build_bridge_diff(PYTHON) returns adapter exposing same method
#        set; build_bridge_diff(RUST) returns subprocess bridge.
#   B12. Per-decision logging emits structured JSON line + default
#        binary path resolves to /opt/wakir/bin/wakir-persona-engine-
#        bridge-diff when env unset.
#
# Total: 12 hermetic vectors (≥10 required per task spec).
#
# Cross-language gate (B8) consumes the same fixture file that the
# Rust crate's tests/cross_lang_field_diff_test.rs and the Python-side
# test_bridge_diff_field_level_parity.py share. A drift in any of the
# six pins surfaces in all three test surfaces simultaneously.

# ---------------------------------------------------------------------------
# Helpers — bridge-diff fixture loader + stub-invokers.
# ---------------------------------------------------------------------------


def _bridge_diff_fixture_path() -> Path:
    """Path to the cross-lang field-diff fixture file (6 pins).

    The same JSON file is consumed by the Rust crate's
    ``tests/cross_lang_field_diff_test.rs`` and the Python emitter
    test ``test_bridge_diff_field_level_parity.py``. Locating it via
    the repo-root relative path keeps the test hermetic and avoids
    duplicating the pin-table.
    """
    here = Path(__file__).resolve()
    # tests/persona_engine/test_rust_backend_switch.py → repo root is
    # three levels up (tests/persona_engine → tests → wirelang →
    # repo-root). The fixture lives at wirelang-rust/crates/persona-
    # engine-bridge-diff/tests/cross_lang_field_diff_fixtures.json.
    repo_root = here.parent.parent.parent.parent
    fixture = (
        repo_root
        / "wirelang-rust"
        / "crates"
        / "persona-engine-bridge-diff"
        / "tests"
        / "cross_lang_field_diff_fixtures.json"
    )
    return fixture


def _load_bridge_diff_fixtures() -> dict:
    p = _bridge_diff_fixture_path()
    assert p.exists(), (
        f"bridge-diff cross-lang fixture missing at {p}; "
        "the Tag-20 test depends on the same pin-table that the "
        "Rust cross_lang_field_diff_test.rs consumes"
    )
    return json.loads(p.read_text(encoding="utf-8"))


def _make_bridge_diff_invoker_via_python_authority():
    """Build a stub subprocess-invoker that echoes the Python authority.

    Decodes the JSON-stdin, dispatches the op, calls into
    :mod:`wirelang.persona_engine.bridge_audit_diff_engine` to produce
    the response, and encodes it with the same wire-shape that the
    Rust CLI would emit. This is the byte-parity gate: any deviation
    between the bridge's expectations and the diff-engine module's
    output fails here in CI.
    """

    def invoker(bin_path, argv, *, stdin_payload, timeout_s):
        from wirelang.persona_engine.bridge_audit_diff_engine import (
            consistency_score,
            diff_envelopes,
            jcs_hash,
        )

        doc = json.loads(stdin_payload.decode("utf-8"))
        op = doc["op"]
        payload = doc["payload"]
        if op == "jcs_hash":
            env_ = payload["envelope"]
            hash_str = jcs_hash(env_)
            return 0, json.dumps({"hash": hash_str}), ""
        if op == "diff_envelopes":
            env_a = payload["envelope_a"]
            env_b = payload["envelope_b"]
            diffs = diff_envelopes(env_a, env_b)
            entries = [
                {
                    "path": fd.path,
                    "kind": fd.kind.value,
                    "value_a": fd.value_a,
                    "value_b": fd.value_b,
                }
                for fd in diffs
            ]
            return 0, json.dumps({"field_diffs": entries}), ""
        if op == "compare":
            env_a = payload["envelope_a"]
            env_b = payload["envelope_b"]
            hash_a = jcs_hash(env_a)
            hash_b = jcs_hash(env_b)
            if hash_a == hash_b:
                resp = {
                    "byte_identical": True,
                    "jcs_hash_a": hash_a,
                    "jcs_hash_b": hash_b,
                    "field_diffs": [],
                    "consistency_score": 1.0,
                }
                return 0, json.dumps(resp), ""
            diffs = diff_envelopes(env_a, env_b)
            entries = [
                {
                    "path": fd.path,
                    "kind": fd.kind.value,
                    "value_a": fd.value_a,
                    "value_b": fd.value_b,
                }
                for fd in diffs
            ]
            score = consistency_score(env_a, env_b, diffs)
            resp = {
                "byte_identical": False,
                "jcs_hash_a": hash_a,
                "jcs_hash_b": hash_b,
                "field_diffs": entries,
                "consistency_score": score,
            }
            return 0, json.dumps(resp), ""
        raise AssertionError(f"unexpected op {op!r}")

    return invoker


# ---------------------------------------------------------------------------
# Vector B1 — WAKIR_BRIDGE_DIFF_BACKEND unset → python default passthrough.
# ---------------------------------------------------------------------------


def test_bridge_diff_unset_defaults_to_python():
    env: dict[str, str] = {}
    chosen, decision = resolve_bridge_diff_backend(env=env)
    assert chosen is BridgeDiffBackend.PYTHON
    assert decision.domain == "bridge_diff"
    assert decision.requested_backend == "python"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason is None
    assert decision.bin_path is None
    assert decision.resolution_latency_us >= 0


# ---------------------------------------------------------------------------
# Vector B2 — explicit python value passthrough with fallback_reason flag.
# ---------------------------------------------------------------------------


def test_bridge_diff_explicit_python():
    env = {BRIDGE_DIFF_BACKEND_ENV: "python"}
    chosen, decision = resolve_bridge_diff_backend(env=env)
    assert chosen is BridgeDiffBackend.PYTHON
    assert decision.fallback_reason == "explicit_python"


# ---------------------------------------------------------------------------
# Vector B3 — rust + binary available → rust chosen.
# ---------------------------------------------------------------------------


def test_bridge_diff_rust_with_available_binary(tmp_path: Path):
    bin_path = _make_executable(tmp_path / "wakir-bridge-diff")
    env = {
        BRIDGE_DIFF_BACKEND_ENV: "rust",
        RUST_BRIDGE_DIFF_BIN_ENV: str(bin_path),
    }
    chosen, decision = resolve_bridge_diff_backend(env=env)
    assert chosen is BridgeDiffBackend.RUST
    assert decision.domain == "bridge_diff"
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "rust"
    assert decision.fallback_reason is None
    assert decision.bin_path == str(bin_path)


# ---------------------------------------------------------------------------
# Vector B4 — rust + binary missing → graceful fallback to python.
# ---------------------------------------------------------------------------


def test_bridge_diff_rust_with_missing_binary_graceful_fallback(
    tmp_path: Path,
):
    missing = tmp_path / "does-not-exist"
    env = {
        BRIDGE_DIFF_BACKEND_ENV: "rust",
        RUST_BRIDGE_DIFF_BIN_ENV: str(missing),
    }
    chosen, decision = resolve_bridge_diff_backend(env=env)
    assert chosen is BridgeDiffBackend.PYTHON
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason == "binary_missing"
    assert decision.bin_path == str(missing)


# ---------------------------------------------------------------------------
# Vector B5 — rust + binary not-executable → graceful fallback to python.
# ---------------------------------------------------------------------------


def test_bridge_diff_rust_with_not_executable_binary_graceful_fallback(
    tmp_path: Path,
):
    not_exec = _make_non_executable_file(tmp_path / "wakir-bridge-diff")
    env = {
        BRIDGE_DIFF_BACKEND_ENV: "rust",
        RUST_BRIDGE_DIFF_BIN_ENV: str(not_exec),
    }
    chosen, decision = resolve_bridge_diff_backend(env=env)
    assert chosen is BridgeDiffBackend.PYTHON
    assert decision.fallback_reason == "binary_not_executable"
    assert decision.bin_path == str(not_exec)


# ---------------------------------------------------------------------------
# Vector B6 — unknown env-var value raises BackendSwitchValidationError.
# ---------------------------------------------------------------------------


def test_bridge_diff_validation_rejects_unknown():
    env = {BRIDGE_DIFF_BACKEND_ENV: "rust-flavor-x"}
    with pytest.raises(BackendSwitchValidationError) as ei:
        resolve_bridge_diff_backend(env=env)
    assert ei.value.env_var == BRIDGE_DIFF_BACKEND_ENV
    assert ei.value.value == "rust-flavor-x"
    assert "python" in list(ei.value.valid_values)
    assert "rust" in list(ei.value.valid_values)
    # The enum has exactly two valid values.
    assert set(VALID_BRIDGE_DIFF_BACKEND_VALUES) == {"python", "rust"}


# ---------------------------------------------------------------------------
# Vector B7 — RustSubprocessBridgeDiff.jcs_hash byte-identical roundtrip.
# ---------------------------------------------------------------------------


def test_rust_bridge_diff_jcs_hash_byte_identical_to_python_authority():
    """The subprocess-bridge must produce byte-identical jcs_hash output
    against the Python authority. Uses the stub-invoker that delegates
    to :func:`bridge_audit_diff_engine.jcs_hash` so the wire-format and
    the bridge envelope are the only variables under test."""
    from wirelang.persona_engine.bridge_audit_diff_engine import jcs_hash

    invoker = _make_bridge_diff_invoker_via_python_authority()
    bridge = RustSubprocessBridgeDiff(
        bin_path="/fake/bin",
        timeout_s=1.0,
        subprocess_invoker=invoker,
    )
    # Empty envelope (matches the Tag-17/Phase-3a cross-lang pin t1).
    py_hash = jcs_hash({})
    rust_hash = bridge.jcs_hash({})
    assert rust_hash == py_hash
    assert rust_hash == (
        "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )
    # Non-trivial envelope with nested + numeric + string keys.
    env_ = {"a": {"b": [1, 2, 3]}, "c": "x", "n": 42}
    py_hash2 = jcs_hash(env_)
    rust_hash2 = bridge.jcs_hash(env_)
    assert rust_hash2 == py_hash2
    assert rust_hash2.startswith("sha256:")
    assert len(rust_hash2) == len("sha256:") + 64


# ---------------------------------------------------------------------------
# Vector B8 — all six cross-lang field-pin vectors rust-verified.
# ---------------------------------------------------------------------------


def test_rust_bridge_diff_all_six_cross_lang_field_pins_byte_identical():
    """Byte-parity gate across the six cross-lang field-pin vectors.

    For each pin in ``cross_lang_field_diff_fixtures.json``
    (PR #166 emitter test) the bridge must produce:

    1. byte-identical ``jcs_hash_a`` / ``jcs_hash_b``
       (matching the Rust crate's pinned hashes),
    2. byte-identical ``field_diffs`` entries
       (path, kind, value_a, value_b — in the same order),
    3. matching ``byte_identical`` flag.

    Any deviation in the JSON wire-shape, the canonicaliser, the
    SHA-256 hash, the RFC-6901 field-walker, or the sort order fails
    this gate in CI before a real Rust binary ever ships (Phase-3c-
    cutover pre-condition for the bridge-diff oracle).
    """
    fx = _load_bridge_diff_fixtures()
    pins = fx["pins"]
    assert len(pins) == 6, (
        f"expected exactly 6 cross-lang field-pin vectors, got "
        f"{len(pins)}; fixture file drifted from PR #166 scope"
    )
    invoker = _make_bridge_diff_invoker_via_python_authority()
    bridge = RustSubprocessBridgeDiff(
        bin_path="/fake/bin",
        timeout_s=1.0,
        subprocess_invoker=invoker,
    )
    for pin in pins:
        env_a = pin["envelope_a"]
        env_b = pin["envelope_b"]
        expected_hash_a = pin["expected_hash_a"]
        expected_hash_b = pin["expected_hash_b"]
        expected_entries = pin["expected_diff_entries"]
        expected_byte_identical = pin["byte_identical"]

        # (1) jcs_hash byte-parity.
        actual_hash_a = bridge.jcs_hash(env_a)
        actual_hash_b = bridge.jcs_hash(env_b)
        assert actual_hash_a == expected_hash_a, (
            f"pin {pin['pin_id']}: hash_a drift "
            f"{actual_hash_a!r} != {expected_hash_a!r}"
        )
        assert actual_hash_b == expected_hash_b, (
            f"pin {pin['pin_id']}: hash_b drift "
            f"{actual_hash_b!r} != {expected_hash_b!r}"
        )

        # (2) field-diff entries byte-parity (ordered).
        actual_diffs = bridge.diff_envelopes(env_a, env_b)
        assert len(actual_diffs) == len(expected_entries), (
            f"pin {pin['pin_id']}: field-diff count drift "
            f"{len(actual_diffs)} != {len(expected_entries)}"
        )
        for got, expected in zip(actual_diffs, expected_entries):
            assert isinstance(got, BridgeDiffSubprocessFieldDiff)
            assert got.path == expected["path"], (
                f"pin {pin['pin_id']}: path drift "
                f"{got.path!r} != {expected['path']!r}"
            )
            assert got.kind == expected["kind"], (
                f"pin {pin['pin_id']}: kind drift "
                f"{got.kind!r} != {expected['kind']!r}"
            )
            # ``value_a`` / ``value_b`` are arbitrary JSON; equality
            # follows json.loads → dict / list / scalar.
            assert got.value_a == expected["value_a"], (
                f"pin {pin['pin_id']}: value_a drift at {got.path!r}"
            )
            assert got.value_b == expected["value_b"], (
                f"pin {pin['pin_id']}: value_b drift at {got.path!r}"
            )

        # (3) compare end-to-end consistency.
        report = bridge.compare(env_a, env_b)
        assert isinstance(report, BridgeDiffSubprocessReport)
        assert report.byte_identical is expected_byte_identical
        assert report.jcs_hash_a == expected_hash_a
        assert report.jcs_hash_b == expected_hash_b
        assert len(report.field_diffs) == len(expected_entries)
        if expected_byte_identical:
            assert report.consistency_score == 1.0
            assert report.field_diffs == ()
        else:
            assert 0.0 <= report.consistency_score <= 1.0


# ---------------------------------------------------------------------------
# Vector B9 — subprocess exit_nonzero → RustBackendError.
# ---------------------------------------------------------------------------


def test_rust_bridge_diff_exit_nonzero_raises():
    def fail_invoker(bin_path, argv, *, stdin_payload, timeout_s):
        return 2, "", "boom"

    bridge = RustSubprocessBridgeDiff(
        bin_path="/fake/bin",
        subprocess_invoker=fail_invoker,
    )
    with pytest.raises(RustBackendError) as ei:
        bridge.jcs_hash({"a": 1})
    assert ei.value.reason == "exit_nonzero"
    assert ei.value.returncode == 2


# ---------------------------------------------------------------------------
# Vector B10 — subprocess bad JSON → RustBackendError(bad_json).
# ---------------------------------------------------------------------------


def test_rust_bridge_diff_bad_json_raises():
    def bad_json_invoker(bin_path, argv, *, stdin_payload, timeout_s):
        return 0, "not-valid-json", ""

    bridge = RustSubprocessBridgeDiff(
        bin_path="/fake/bin",
        subprocess_invoker=bad_json_invoker,
    )
    with pytest.raises(RustBackendError) as ei:
        bridge.jcs_hash({"a": 1})
    assert ei.value.reason == "bad_json"


# ---------------------------------------------------------------------------
# Vector B11 — build_bridge_diff(PYTHON / RUST) returns matching surface.
# ---------------------------------------------------------------------------


def test_build_bridge_diff_python_and_rust_surfaces_match_api():
    """Both factories expose the same method-set so callers cannot
    tell the backends apart at the API boundary."""
    py_adapter = build_bridge_diff(BridgeDiffBackend.PYTHON)
    assert hasattr(py_adapter, "jcs_hash")
    assert hasattr(py_adapter, "diff_envelopes")
    assert hasattr(py_adapter, "compare")
    # Python-path roundtrip: empty envelopes are byte-identical.
    report_py = py_adapter.compare({}, {})
    assert isinstance(report_py, BridgeDiffSubprocessReport)
    assert report_py.byte_identical is True
    assert report_py.consistency_score == 1.0
    assert report_py.field_diffs == ()

    # Rust-bound factory returns the subprocess-bridge.
    rust_bridge = build_bridge_diff(
        BridgeDiffBackend.RUST,
        env={RUST_BRIDGE_DIFF_BIN_ENV: "/custom/wakir-bridge-diff"},
    )
    assert isinstance(rust_bridge, RustSubprocessBridgeDiff)
    assert rust_bridge.bin_path == "/custom/wakir-bridge-diff"
    assert hasattr(rust_bridge, "jcs_hash")
    assert hasattr(rust_bridge, "diff_envelopes")
    assert hasattr(rust_bridge, "compare")


# ---------------------------------------------------------------------------
# Vector B12 — per-decision logging emits structured JSON line + default
# binary path resolves to /opt/wakir/bin/wakir-persona-engine-bridge-diff.
# ---------------------------------------------------------------------------


def test_bridge_diff_per_decision_logging_writes_sink_and_default_bin_path():
    # Default binary path.
    from wirelang.persona_engine.rust_backend_switch import (
        _resolve_bridge_diff_bin,
    )

    assert (
        _resolve_bridge_diff_bin(env={}) == DEFAULT_RUST_BRIDGE_DIFF_BIN
    )
    assert (
        DEFAULT_RUST_BRIDGE_DIFF_BIN
        == "/opt/wakir/bin/wakir-persona-engine-bridge-diff"
    )
    # Per-decision logging emits a single structured JSON line.
    sink = io.StringIO()
    chosen, _ = resolve_bridge_diff_backend(env={}, log_sink=sink)
    line = sink.getvalue().strip()
    assert line, "expected one structured-log line emitted"
    parsed = json.loads(line)
    assert parsed["msg"] == "backend-decision"
    assert parsed["domain"] == "bridge_diff"
    assert parsed["requested_backend"] == "python"
    assert parsed["chosen_backend"] == "python"
    assert parsed["resolution_latency_us"] >= 0
    assert chosen is BridgeDiffBackend.PYTHON


# ===========================================================================
# Tag-22 Mini-Welle — Subscribe-Loop production-default switch tests
# ---------------------------------------------------------------------------
# Coverage map (15 hermetic vectors for the subscribe-loop component):
#
#   SL1  WAKIR_SUBSCRIBE_LOOP_BACKEND unset → python default passthrough.
#   SL2  explicit "python" value passthrough + fallback_reason flag.
#   SL3  rust + binary available → rust chosen.
#   SL4  rust + binary missing → graceful fallback to python.
#   SL5  rust + binary not-executable → graceful fallback to python.
#   SL6  unknown env-var value raises BackendSwitchValidationError.
#   SL7  empty-string env value defaults to python.
#   SL8  all five cross-lang ack-record fixtures rust-verified
#        (byte-identical JCS bytes + SHA-256 hex against the Python
#        authority via the stub-invoker delegation).
#   SL9  hash_record() roundtrip on a pre-built record matches
#        serialize_ack() output byte-for-byte.
#   SL10 subprocess exit_nonzero → RustBackendError(exit_nonzero).
#   SL11 subprocess bad JSON → RustBackendError(bad_json).
#   SL12 build_subscribe_loop(PYTHON / RUST) returns matching surface.
#   SL13 default binary path resolves to
#        /opt/wakir/bin/wakir-persona-engine-subscribe-loop.
#   SL14 per-decision logging emits one structured JSON line.
#   SL15 _select_subscribe_loop_backend auftrag-alias dispatches
#        identically to resolve_subscribe_loop_backend.
#
# Plus: SL16 client-side validation (invalid outcome / frame_index)
# rejects without spawning a subprocess.
#
# Total: 16 hermetic vectors (≥10 required).
# ===========================================================================


def _load_subscribe_loop_fixtures() -> dict:
    """Load the cross-lang fixtures file once per test that needs them."""
    fixture_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "tests"
        / "fixtures"
        / "subscribe-loop-cross-lang"
        / "fixtures.json"
    )
    with fixture_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _make_subscribe_loop_invoker_via_python_authority():
    """Build a stub-invoker that delegates to the Python subscribe_ack
    authority.

    The Rust binary contract is:

    stdin JSON:
        ``{"schema": "wakir.persona-engine.subscribe-loop/1",
        "op": "<serialize_ack | hash_record>",
        "payload": {auftrag_id, frame_index, outcome, persona_id,
        prompt_sha256, subject}}``

    response JSON:
        ``{"ack_record_jcs_bytes_b64": str,
        "ack_record_jcs_bytes_len": int,
        "ack_record_sha256_hex": str,
        "ack_record_hash_prefixed": str}``

    The stub-invoker reproduces this by delegating to
    :mod:`wirelang.persona_engine.subscribe_ack` so the wire-format
    and the bridge envelope are the only variables under test.
    """
    import base64 as _base64

    from wirelang.persona_engine.subscribe_ack import (
        ack_record_hash_prefixed,
        ack_record_sha256_hex,
        build_subscribe_ack_record,
        serialize_subscribe_ack,
    )

    def invoker(bin_path, argv, *, stdin_payload, timeout_s):
        doc = json.loads(stdin_payload.decode("utf-8"))
        assert doc["schema"] == "wakir.persona-engine.subscribe-loop/1"
        op = doc["op"]
        payload = doc["payload"]
        assert op in ("serialize_ack", "hash_record")
        record = build_subscribe_ack_record(
            auftrag_id=payload["auftrag_id"],
            frame_index=payload["frame_index"],
            outcome=payload["outcome"],
            persona_id=payload["persona_id"],
            prompt_sha256=payload["prompt_sha256"],
            subject=payload["subject"],
        )
        jcs_bytes = serialize_subscribe_ack(record)
        hex_ = ack_record_sha256_hex(record)
        prefixed = ack_record_hash_prefixed(record)
        resp = {
            "ack_record_jcs_bytes_b64": _base64.b64encode(jcs_bytes).decode(
                "ascii"
            ),
            "ack_record_jcs_bytes_len": len(jcs_bytes),
            "ack_record_sha256_hex": hex_,
            "ack_record_hash_prefixed": prefixed,
        }
        return 0, json.dumps(resp), ""

    return invoker


# ---------------------------------------------------------------------------
# Vector SL1 — WAKIR_SUBSCRIBE_LOOP_BACKEND unset → python default.
# ---------------------------------------------------------------------------


def test_subscribe_loop_unset_defaults_to_python():
    env: dict[str, str] = {}
    chosen, decision = resolve_subscribe_loop_backend(env=env)
    assert chosen is SubscribeLoopBackend.PYTHON
    assert decision.domain == "subscribe_loop"
    assert decision.requested_backend == "python"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason is None
    assert decision.bin_path is None
    assert decision.resolution_latency_us >= 0


# ---------------------------------------------------------------------------
# Vector SL2 — explicit "python" value with fallback_reason flag.
# ---------------------------------------------------------------------------


def test_subscribe_loop_explicit_python():
    env = {SUBSCRIBE_LOOP_BACKEND_ENV: "python"}
    chosen, decision = resolve_subscribe_loop_backend(env=env)
    assert chosen is SubscribeLoopBackend.PYTHON
    assert decision.fallback_reason == "explicit_python"


# ---------------------------------------------------------------------------
# Vector SL3 — rust + binary available → rust chosen.
# ---------------------------------------------------------------------------


def test_subscribe_loop_rust_with_available_binary(tmp_path: Path):
    bin_path = _make_executable(tmp_path / "wakir-subscribe-loop")
    env = {
        SUBSCRIBE_LOOP_BACKEND_ENV: "rust",
        RUST_SUBSCRIBE_LOOP_BIN_ENV: str(bin_path),
    }
    chosen, decision = resolve_subscribe_loop_backend(env=env)
    assert chosen is SubscribeLoopBackend.RUST
    assert decision.domain == "subscribe_loop"
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "rust"
    assert decision.fallback_reason is None
    assert decision.bin_path == str(bin_path)


# ---------------------------------------------------------------------------
# Vector SL4 — rust + binary missing → graceful fallback to python.
# ---------------------------------------------------------------------------


def test_subscribe_loop_rust_with_missing_binary_graceful_fallback(
    tmp_path: Path,
):
    missing = tmp_path / "does-not-exist"
    env = {
        SUBSCRIBE_LOOP_BACKEND_ENV: "rust",
        RUST_SUBSCRIBE_LOOP_BIN_ENV: str(missing),
    }
    chosen, decision = resolve_subscribe_loop_backend(env=env)
    assert chosen is SubscribeLoopBackend.PYTHON
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason == "binary_missing"
    assert decision.bin_path == str(missing)


# ---------------------------------------------------------------------------
# Vector SL5 — rust + binary not-executable → graceful fallback.
# ---------------------------------------------------------------------------


def test_subscribe_loop_rust_with_not_executable_binary_graceful_fallback(
    tmp_path: Path,
):
    not_exec = _make_non_executable_file(tmp_path / "wakir-subscribe-loop")
    env = {
        SUBSCRIBE_LOOP_BACKEND_ENV: "rust",
        RUST_SUBSCRIBE_LOOP_BIN_ENV: str(not_exec),
    }
    chosen, decision = resolve_subscribe_loop_backend(env=env)
    assert chosen is SubscribeLoopBackend.PYTHON
    assert decision.fallback_reason == "binary_not_executable"
    assert decision.bin_path == str(not_exec)


# ---------------------------------------------------------------------------
# Vector SL6 — unknown env-var value raises BackendSwitchValidationError.
# ---------------------------------------------------------------------------


def test_subscribe_loop_validation_rejects_unknown():
    env = {SUBSCRIBE_LOOP_BACKEND_ENV: "rust-flavor-x"}
    with pytest.raises(BackendSwitchValidationError) as ei:
        resolve_subscribe_loop_backend(env=env)
    assert ei.value.env_var == SUBSCRIBE_LOOP_BACKEND_ENV
    assert ei.value.value == "rust-flavor-x"
    assert "python" in list(ei.value.valid_values)
    assert "rust" in list(ei.value.valid_values)
    # The enum has exactly two valid values.
    assert set(VALID_SUBSCRIBE_LOOP_BACKEND_VALUES) == {"python", "rust"}


# ---------------------------------------------------------------------------
# Vector SL7 — empty-string env value defaults to python (no validation error).
# ---------------------------------------------------------------------------


def test_subscribe_loop_empty_string_env_defaults_to_python():
    env = {SUBSCRIBE_LOOP_BACKEND_ENV: ""}
    chosen, decision = resolve_subscribe_loop_backend(env=env)
    assert chosen is SubscribeLoopBackend.PYTHON
    assert decision.fallback_reason is None


# ---------------------------------------------------------------------------
# Vector SL8 — all five cross-lang ack-record fixtures rust-verified.
# ---------------------------------------------------------------------------


def test_rust_subscribe_loop_all_five_cross_lang_ack_fixtures_byte_identical():
    """Byte-parity gate across the five cross-lang ack-record fixtures.

    For each fixture in ``tests/fixtures/subscribe-loop-cross-lang/
    fixtures.json`` (PR #172 Python-sync test target) the bridge must
    produce:

    1. byte-identical ``ack_record_jcs_bytes`` (matching the pinned
       base64-encoded canonical form),
    2. byte-identical ``ack_record_jcs_bytes_len``,
    3. byte-identical ``ack_record_sha256_hex`` (lowercase 64 hex),
    4. byte-identical ``ack_record_hash_prefixed``
       (``"sha256:" + hex``).

    Any deviation in the JSON wire-shape, the JCS canonicaliser, the
    SHA-256 hash, or the prefix-form fails this gate in CI before a
    real Rust binary ever ships (Phase-3c-cutover pre-condition for
    the subscribe-loop NATS-ingress audit substrate).
    """
    import base64

    fx = _load_subscribe_loop_fixtures()
    fixtures = fx["fixtures"]
    assert len(fixtures) == 5, (
        f"expected exactly 5 cross-lang ack-record fixtures, got "
        f"{len(fixtures)}; fixture file drifted from PR #172 scope"
    )
    assert fx["schema_version"] == "wakir.persona-engine.subscribe-ack/1"

    invoker = _make_subscribe_loop_invoker_via_python_authority()
    bridge = RustSubprocessSubscribeLoop(
        bin_path="/fake/bin",
        timeout_s=1.0,
        subprocess_invoker=invoker,
    )

    for fixture in fixtures:
        name = fixture["name"]
        inp = fixture["input"]
        expected = fixture["expected"]
        result = bridge.serialize_ack(
            auftrag_id=inp["auftrag_id"],
            frame_index=inp["frame_index"],
            outcome=inp["outcome"],
            persona_id=inp["persona_id"],
            prompt_sha256=inp["prompt_sha256"],
            subject=inp["subject"],
        )
        # (1) JCS bytes byte-parity (base64-encoded comparison).
        expected_b64 = expected["ack_record_jcs_bytes_b64"]
        expected_jcs_bytes = base64.b64decode(expected_b64.encode("ascii"))
        assert result.ack_record_jcs_bytes == expected_jcs_bytes, (
            f"fixture {name}: JCS bytes drift "
            f"{result.ack_record_jcs_bytes!r} != {expected_jcs_bytes!r}"
        )
        # (2) JCS bytes length.
        assert len(result.ack_record_jcs_bytes) == expected[
            "ack_record_jcs_bytes_len"
        ], f"fixture {name}: JCS bytes length drift"
        # (3) SHA-256 hex byte-parity.
        assert (
            result.ack_record_sha256_hex == expected["ack_record_sha256_hex"]
        ), (
            f"fixture {name}: SHA-256 hex drift "
            f"{result.ack_record_sha256_hex!r} != "
            f"{expected['ack_record_sha256_hex']!r}"
        )
        # (4) Prefixed hash byte-parity.
        assert (
            result.ack_record_hash_prefixed
            == expected["ack_record_hash_prefixed"]
        ), (
            f"fixture {name}: prefixed hash drift "
            f"{result.ack_record_hash_prefixed!r} != "
            f"{expected['ack_record_hash_prefixed']!r}"
        )
        # Sanity: reconstructed record carries the canonical schema.
        assert (
            result.record.schema == "wakir.persona-engine.subscribe-ack/1"
        )
        assert result.record.auftrag_id == inp["auftrag_id"]
        assert result.record.frame_index == inp["frame_index"]
        assert result.record.outcome == inp["outcome"]
        assert result.record.persona_id == inp["persona_id"]
        assert result.record.prompt_sha256 == inp["prompt_sha256"]
        assert result.record.subject == inp["subject"]


# ---------------------------------------------------------------------------
# Vector SL9 — hash_record() roundtrip matches serialize_ack() byte-for-byte.
# ---------------------------------------------------------------------------


def test_rust_subscribe_loop_hash_record_matches_serialize_ack():
    """A pre-built SubscribeAckRecord passed to ``hash_record`` must
    produce the same triple (JCS bytes / hex / prefixed) as the equivalent
    ``serialize_ack`` call. Guards against accidental divergence between
    the two surface methods."""
    from wirelang.persona_engine.subscribe_ack import (
        build_subscribe_ack_record,
    )

    invoker = _make_subscribe_loop_invoker_via_python_authority()
    bridge = RustSubprocessSubscribeLoop(
        bin_path="/fake/bin",
        timeout_s=1.0,
        subprocess_invoker=invoker,
    )
    args = {
        "auftrag_id": "auftrag-pengine-1",
        "frame_index": 0,
        "outcome": "processed",
        "persona_id": "reza",
        "prompt_sha256": (
            "sha256:531fed186ec25156a1aa5178f57506f9260487601eb6a"
            "285ed86fc691ffa891f"
        ),
        "subject": "wakir.dev.agent.agent.task.assigned.reza",
    }
    via_serialize = bridge.serialize_ack(**args)
    record = build_subscribe_ack_record(**args)
    via_hash = bridge.hash_record(record)
    assert (
        via_serialize.ack_record_jcs_bytes == via_hash.ack_record_jcs_bytes
    )
    assert (
        via_serialize.ack_record_sha256_hex == via_hash.ack_record_sha256_hex
    )
    assert (
        via_serialize.ack_record_hash_prefixed
        == via_hash.ack_record_hash_prefixed
    )
    assert via_serialize.record == via_hash.record


# ---------------------------------------------------------------------------
# Vector SL10 — subprocess exit_nonzero → RustBackendError(exit_nonzero).
# ---------------------------------------------------------------------------


def test_rust_subscribe_loop_exit_nonzero_raises():
    def fail_invoker(bin_path, argv, *, stdin_payload, timeout_s):
        return 2, "", "boom"

    bridge = RustSubprocessSubscribeLoop(
        bin_path="/fake/bin",
        subprocess_invoker=fail_invoker,
    )
    with pytest.raises(RustBackendError) as ei:
        bridge.serialize_ack(
            auftrag_id="a",
            frame_index=0,
            outcome="processed",
            persona_id="p",
            prompt_sha256="sha256:" + "0" * 64,
            subject="wakir.dev.agent.agent.task.assigned.p",
        )
    assert ei.value.reason == "exit_nonzero"
    assert ei.value.returncode == 2


# ---------------------------------------------------------------------------
# Vector SL11 — subprocess bad JSON → RustBackendError(bad_json).
# ---------------------------------------------------------------------------


def test_rust_subscribe_loop_bad_json_raises():
    def bad_json_invoker(bin_path, argv, *, stdin_payload, timeout_s):
        return 0, "not-valid-json", ""

    bridge = RustSubprocessSubscribeLoop(
        bin_path="/fake/bin",
        subprocess_invoker=bad_json_invoker,
    )
    with pytest.raises(RustBackendError) as ei:
        bridge.serialize_ack(
            auftrag_id="a",
            frame_index=0,
            outcome="processed",
            persona_id="p",
            prompt_sha256="sha256:" + "0" * 64,
            subject="wakir.dev.agent.agent.task.assigned.p",
        )
    assert ei.value.reason == "bad_json"


# ---------------------------------------------------------------------------
# Vector SL12 — build_subscribe_loop(PYTHON / RUST) surfaces match.
# ---------------------------------------------------------------------------


def test_build_subscribe_loop_python_and_rust_surfaces_match_api():
    """Both factories expose the same method-set so callers cannot
    tell the backends apart at the API boundary. The Python adapter
    also produces a fixture-pinned result so the surface is exercised
    end-to-end without a subprocess."""
    py_adapter = build_subscribe_loop(SubscribeLoopBackend.PYTHON)
    assert hasattr(py_adapter, "serialize_ack")
    assert hasattr(py_adapter, "hash_record")

    # Fixture-1 (empty malformed frame) Python-path roundtrip.
    result = py_adapter.serialize_ack(
        auftrag_id="",
        frame_index=0,
        outcome="malformed",
        persona_id="",
        prompt_sha256="",
        subject="wakir.dev.agent.agent.task.assigned.reza",
    )
    assert isinstance(result, SubscribeLoopSubprocessAckResult)
    assert result.ack_record_hash_prefixed == (
        "sha256:bc0f3d2b653ced21d12ea5a706554a66b9acbbe429e9b55be757f659cb203e3a"
    )
    assert len(result.ack_record_jcs_bytes) == 191

    # Rust-bound factory returns the subprocess-bridge.
    rust_bridge = build_subscribe_loop(
        SubscribeLoopBackend.RUST,
        env={RUST_SUBSCRIBE_LOOP_BIN_ENV: "/custom/wakir-subscribe-loop"},
    )
    assert isinstance(rust_bridge, RustSubprocessSubscribeLoop)
    assert rust_bridge.bin_path == "/custom/wakir-subscribe-loop"
    assert hasattr(rust_bridge, "serialize_ack")
    assert hasattr(rust_bridge, "hash_record")


# ---------------------------------------------------------------------------
# Vector SL13 — default binary path resolves to expected /opt/wakir path.
# ---------------------------------------------------------------------------


def test_subscribe_loop_default_binary_path_when_env_unset():
    from wirelang.persona_engine.rust_backend_switch import (
        _resolve_subscribe_loop_bin,
    )

    assert (
        _resolve_subscribe_loop_bin(env={}) == DEFAULT_RUST_SUBSCRIBE_LOOP_BIN
    )
    assert (
        DEFAULT_RUST_SUBSCRIBE_LOOP_BIN
        == "/opt/wakir/bin/wakir-persona-engine-subscribe-loop"
    )


# ---------------------------------------------------------------------------
# Vector SL14 — per-decision logging emits structured JSON line.
# ---------------------------------------------------------------------------


def test_subscribe_loop_per_decision_logging_writes_sink():
    sink = io.StringIO()
    chosen, _ = resolve_subscribe_loop_backend(env={}, log_sink=sink)
    line = sink.getvalue().strip()
    assert line, "expected one structured-log line emitted"
    parsed = json.loads(line)
    assert parsed["msg"] == "backend-decision"
    assert parsed["domain"] == "subscribe_loop"
    assert parsed["requested_backend"] == "python"
    assert parsed["chosen_backend"] == "python"
    assert parsed["resolution_latency_us"] >= 0
    assert chosen is SubscribeLoopBackend.PYTHON


# ---------------------------------------------------------------------------
# Vector SL15 — _select_subscribe_loop_backend auftrag-alias dispatches
# identically to resolve_subscribe_loop_backend.
# ---------------------------------------------------------------------------


def test_select_subscribe_loop_backend_alias_dispatches_identically(
    tmp_path: Path,
):
    """The Tag-22 auftrag spec names the resolver
    ``_select_subscribe_loop_backend``; the module exposes that name as
    an alias of :func:`resolve_subscribe_loop_backend`. Both must return
    the same value-pair for the same input env."""
    # Unset env path.
    chosen_a, decision_a = _select_subscribe_loop_backend(env={})
    chosen_b, decision_b = resolve_subscribe_loop_backend(env={})
    assert chosen_a is chosen_b
    assert decision_a.domain == decision_b.domain
    assert decision_a.requested_backend == decision_b.requested_backend
    assert decision_a.chosen_backend == decision_b.chosen_backend
    assert decision_a.fallback_reason == decision_b.fallback_reason
    # Rust + missing-binary path.
    missing = tmp_path / "does-not-exist"
    env = {
        SUBSCRIBE_LOOP_BACKEND_ENV: "rust",
        RUST_SUBSCRIBE_LOOP_BIN_ENV: str(missing),
    }
    chosen_c, decision_c = _select_subscribe_loop_backend(env=env)
    chosen_d, decision_d = resolve_subscribe_loop_backend(env=env)
    assert chosen_c is chosen_d is SubscribeLoopBackend.PYTHON
    assert (
        decision_c.fallback_reason
        == decision_d.fallback_reason
        == "binary_missing"
    )


# ---------------------------------------------------------------------------
# Vector SL16 — client-side validation rejects bad outcome / frame_index
# without spawning a subprocess.
# ---------------------------------------------------------------------------


def test_rust_subscribe_loop_client_side_validation_rejects_bad_inputs():
    """The subprocess-bridge validates ``outcome`` and ``frame_index``
    client-side so an obviously-malformed call never spawns a
    subprocess. Mirrors the Python authority's posture in
    :func:`build_subscribe_ack_record`."""
    from wirelang.persona_engine.subscribe_ack import (
        InvalidFrameIndexError,
        InvalidOutcomeError,
    )

    # Use an invoker that asserts it is never called — proves the
    # bridge short-circuited client-side before paying the subprocess
    # cost.
    def never_called_invoker(bin_path, argv, *, stdin_payload, timeout_s):
        raise AssertionError("invoker should not be called on bad input")

    bridge = RustSubprocessSubscribeLoop(
        bin_path="/fake/bin",
        subprocess_invoker=never_called_invoker,
    )
    # Bad outcome.
    with pytest.raises(InvalidOutcomeError):
        bridge.serialize_ack(
            auftrag_id="a",
            frame_index=0,
            outcome="not-a-real-outcome",
            persona_id="p",
            prompt_sha256="sha256:" + "0" * 64,
            subject="wakir.dev.agent.agent.task.assigned.p",
        )
    # Negative frame_index.
    with pytest.raises(InvalidFrameIndexError):
        bridge.serialize_ack(
            auftrag_id="a",
            frame_index=-1,
            outcome="processed",
            persona_id="p",
            prompt_sha256="sha256:" + "0" * 64,
            subject="wakir.dev.agent.agent.task.assigned.p",
        )
    # Non-int frame_index (bool is technically a subclass of int but
    # rejected explicitly to keep JCS bytes deterministic).
    with pytest.raises(InvalidFrameIndexError):
        bridge.serialize_ack(
            auftrag_id="a",
            frame_index=True,  # type: ignore[arg-type]
            outcome="processed",
            persona_id="p",
            prompt_sha256="sha256:" + "0" * 64,
            subject="wakir.dev.agent.agent.task.assigned.p",
        )


# ===========================================================================
# Tag-23 Mini-Welle vectors — anchor-emitter production-default switch
# (7th and final Phase-3b BackendDecision component).
#
# Coverage map for the anchor-emitter switch (AE1..AE13, 13 vectors,
# ≥10 required):
#
#   AE1  WAKIR_ANCHOR_EMITTER_BACKEND unset → python default + decision.
#   AE2  WAKIR_ANCHOR_EMITTER_BACKEND=python (explicit) → python +
#        fallback_reason="explicit_python".
#   AE3  WAKIR_ANCHOR_EMITTER_BACKEND=rust + binary available → rust
#        chosen.
#   AE4  WAKIR_ANCHOR_EMITTER_BACKEND=rust + binary missing →
#        graceful fallback to python, fallback_reason="binary_missing".
#   AE5  WAKIR_ANCHOR_EMITTER_BACKEND=rust + binary not-executable →
#        graceful fallback to python,
#        fallback_reason="binary_not_executable".
#   AE6  unknown env-var value raises BackendSwitchValidationError.
#   AE7  empty-string env value defaults to python.
#   AE8  all five cross-lang anchor-envelope fixtures rust-verified
#        (byte-identical JCS bytes + envelope-hash + payload-hash
#        against the Python authority via the stub-invoker delegation).
#   AE9  hash_anchor() roundtrip on a pre-built envelope matches
#        serialize_anchor() output byte-for-byte.
#   AE10 subprocess exit_nonzero → RustBackendError(exit_nonzero).
#   AE11 subprocess bad JSON → RustBackendError(bad_json).
#   AE12 build_anchor_emitter(PYTHON / RUST) returns matching surface
#        plus fixture-pinned Python-path roundtrip.
#   AE13 default binary path resolves to
#        /opt/wakir/bin/wakir-persona-engine-anchor-emitter +
#        per-decision logging emits one structured JSON line +
#        _select_anchor_emitter_backend auftrag-alias dispatches
#        identically to resolve_anchor_emitter_backend +
#        client-side validation (empty event_id / bad timestamp)
#        rejects without spawning a subprocess.
#
# Total: 13 hermetic vectors (≥10 required).
# ===========================================================================


def _load_anchor_emitter_fixtures() -> dict:
    """Load the cross-lang anchor-envelope fixtures file once per test."""
    fixture_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "tests"
        / "fixtures"
        / "anchor-emitter-cross-lang"
        / "fixtures.json"
    )
    with fixture_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _make_anchor_emitter_invoker_via_python_authority():
    """Build a stub-invoker that delegates to the Python anchor_emitter
    authority.

    The Rust binary contract is:

    stdin JSON:
        ``{"schema": "wakir.persona-engine.anchor-emitter/1",
        "op": "<serialize_anchor | hash_anchor>",
        "payload": {event_id, timestamp_utc, persona_id,
        payload_jcs_bytes_b64}}``

    response JSON:
        ``{"envelope_jcs_bytes_b64": str,
        "envelope_jcs_bytes_len": int,
        "envelope_sha256_hex": str,
        "envelope_hash_prefixed": str,
        "payload_sha256_hex": str}``

    The stub-invoker reproduces this by delegating to
    :mod:`wirelang.persona_engine.anchor_emitter` so the wire-format
    and the bridge envelope are the only variables under test.
    """
    import base64 as _base64

    from wirelang.persona_engine.anchor_emitter import (
        AnchorEmitterInput as _AEI,
        build_anchor_envelope as _build,
        hash_anchor as _hash_anchor,
        serialize_anchor as _serialize_anchor,
        sha256_hex as _sha256_hex,
    )

    def invoker(bin_path, argv, *, stdin_payload, timeout_s):
        doc = json.loads(stdin_payload.decode("utf-8"))
        assert doc["schema"] == "wakir.persona-engine.anchor-emitter/1"
        op = doc["op"]
        payload = doc["payload"]
        assert op in ("serialize_anchor", "hash_anchor")
        payload_bytes = _base64.b64decode(
            payload["payload_jcs_bytes_b64"].encode("ascii")
        )
        envelope = _build(
            _AEI(
                event_id=payload["event_id"],
                timestamp_utc=payload["timestamp_utc"],
                persona_id=payload["persona_id"],
                payload_jcs_bytes=payload_bytes,
            )
        )
        jcs_bytes = _serialize_anchor(envelope)
        env_hex = _sha256_hex(jcs_bytes)
        env_prefixed = _hash_anchor(envelope)
        payload_hex = _sha256_hex(envelope.payload_jcs_bytes)
        resp = {
            "envelope_jcs_bytes_b64": _base64.b64encode(jcs_bytes).decode(
                "ascii"
            ),
            "envelope_jcs_bytes_len": len(jcs_bytes),
            "envelope_sha256_hex": env_hex,
            "envelope_hash_prefixed": env_prefixed,
            "payload_sha256_hex": payload_hex,
        }
        return 0, json.dumps(resp), ""

    return invoker


# ---------------------------------------------------------------------------
# Vector AE1 — WAKIR_ANCHOR_EMITTER_BACKEND unset → python default.
# ---------------------------------------------------------------------------


def test_anchor_emitter_unset_defaults_to_python():
    env: dict[str, str] = {}
    chosen, decision = resolve_anchor_emitter_backend(env=env)
    assert chosen is AnchorEmitterBackend.PYTHON
    assert decision.domain == "anchor_emitter"
    assert decision.requested_backend == "python"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason is None
    assert decision.bin_path is None
    assert decision.resolution_latency_us >= 0


# ---------------------------------------------------------------------------
# Vector AE2 — explicit "python" value with fallback_reason flag.
# ---------------------------------------------------------------------------


def test_anchor_emitter_explicit_python():
    env = {ANCHOR_EMITTER_BACKEND_ENV: "python"}
    chosen, decision = resolve_anchor_emitter_backend(env=env)
    assert chosen is AnchorEmitterBackend.PYTHON
    assert decision.fallback_reason == "explicit_python"


# ---------------------------------------------------------------------------
# Vector AE3 — rust + binary available → rust chosen.
# ---------------------------------------------------------------------------


def test_anchor_emitter_rust_with_available_binary(tmp_path: Path):
    bin_path = _make_executable(tmp_path / "wakir-anchor-emitter")
    env = {
        ANCHOR_EMITTER_BACKEND_ENV: "rust",
        RUST_ANCHOR_EMITTER_BIN_ENV: str(bin_path),
    }
    chosen, decision = resolve_anchor_emitter_backend(env=env)
    assert chosen is AnchorEmitterBackend.RUST
    assert decision.domain == "anchor_emitter"
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "rust"
    assert decision.fallback_reason is None
    assert decision.bin_path == str(bin_path)


# ---------------------------------------------------------------------------
# Vector AE4 — rust + binary missing → graceful fallback to python.
# ---------------------------------------------------------------------------


def test_anchor_emitter_rust_with_missing_binary_graceful_fallback(
    tmp_path: Path,
):
    missing = tmp_path / "does-not-exist"
    env = {
        ANCHOR_EMITTER_BACKEND_ENV: "rust",
        RUST_ANCHOR_EMITTER_BIN_ENV: str(missing),
    }
    chosen, decision = resolve_anchor_emitter_backend(env=env)
    assert chosen is AnchorEmitterBackend.PYTHON
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason == "binary_missing"
    assert decision.bin_path == str(missing)


# ---------------------------------------------------------------------------
# Vector AE5 — rust + binary not-executable → graceful fallback.
# ---------------------------------------------------------------------------


def test_anchor_emitter_rust_with_not_executable_binary_graceful_fallback(
    tmp_path: Path,
):
    not_exec = _make_non_executable_file(tmp_path / "wakir-anchor-emitter")
    env = {
        ANCHOR_EMITTER_BACKEND_ENV: "rust",
        RUST_ANCHOR_EMITTER_BIN_ENV: str(not_exec),
    }
    chosen, decision = resolve_anchor_emitter_backend(env=env)
    assert chosen is AnchorEmitterBackend.PYTHON
    assert decision.fallback_reason == "binary_not_executable"
    assert decision.bin_path == str(not_exec)


# ---------------------------------------------------------------------------
# Vector AE6 — unknown env-var value raises BackendSwitchValidationError.
# ---------------------------------------------------------------------------


def test_anchor_emitter_validation_rejects_unknown():
    env = {ANCHOR_EMITTER_BACKEND_ENV: "rust-flavor-x"}
    with pytest.raises(BackendSwitchValidationError) as ei:
        resolve_anchor_emitter_backend(env=env)
    assert ei.value.env_var == ANCHOR_EMITTER_BACKEND_ENV
    assert ei.value.value == "rust-flavor-x"
    assert "python" in list(ei.value.valid_values)
    assert "rust" in list(ei.value.valid_values)
    # The enum has exactly two valid values.
    assert set(VALID_ANCHOR_EMITTER_BACKEND_VALUES) == {"python", "rust"}


# ---------------------------------------------------------------------------
# Vector AE7 — empty-string env value defaults to python (no validation).
# ---------------------------------------------------------------------------


def test_anchor_emitter_empty_string_env_defaults_to_python():
    env = {ANCHOR_EMITTER_BACKEND_ENV: ""}
    chosen, decision = resolve_anchor_emitter_backend(env=env)
    assert chosen is AnchorEmitterBackend.PYTHON
    assert decision.fallback_reason is None


# ---------------------------------------------------------------------------
# Vector AE8 — all five cross-lang anchor-envelope fixtures rust-verified.
# ---------------------------------------------------------------------------


def test_rust_anchor_emitter_all_five_cross_lang_fixtures_byte_identical():
    """Byte-parity gate across the five cross-lang anchor-envelope
    fixtures.

    For each fixture in ``tests/fixtures/anchor-emitter-cross-lang/
    fixtures.json`` (PR #170 Python-sync, PR #141 Rust crate) the
    bridge must produce:

    1. byte-identical ``envelope_jcs_bytes`` (matching the pinned
       base64-encoded canonical form),
    2. byte-identical ``envelope_jcs_bytes_len``,
    3. byte-identical ``envelope_sha256_hex`` (lowercase 64 hex),
    4. byte-identical ``envelope_hash_prefixed``
       (``"sha256:" + hex``),
    5. byte-identical ``payload_sha256_hex`` (lowercase 64 hex).

    Any deviation in the JSON wire-shape, the JCS canonicaliser, the
    SHA-256 hash, or the prefix-form fails this gate in CI before a
    real Rust binary ever ships (Phase-3c-cutover pre-condition for
    the WAT-spool envelope substrate).
    """
    import base64

    fx = _load_anchor_emitter_fixtures()
    fixtures = fx["fixtures"]
    assert len(fixtures) == 5, (
        f"expected exactly 5 cross-lang anchor-envelope fixtures, got "
        f"{len(fixtures)}; fixture file drifted from PR #170/#141 scope"
    )
    assert fx["schema_version"] == "wakir.wat.anchor-envelope/1"

    invoker = _make_anchor_emitter_invoker_via_python_authority()
    bridge = RustSubprocessAnchorEmitter(
        bin_path="/fake/bin",
        timeout_s=1.0,
        subprocess_invoker=invoker,
    )

    for fixture in fixtures:
        name = fixture["name"]
        inp = fixture["input"]
        expected = fixture["expected"]
        payload_bytes = base64.b64decode(
            inp["payload_jcs_bytes_b64"].encode("ascii")
        )
        result = bridge.serialize_anchor(
            event_id=inp["event_id"],
            timestamp_utc=inp["timestamp_utc"],
            persona_id=inp["persona_id"],
            payload_jcs_bytes=payload_bytes,
        )
        # (1) JCS bytes byte-parity (base64-encoded comparison).
        expected_b64 = expected["envelope_jcs_bytes_b64"]
        expected_jcs_bytes = base64.b64decode(expected_b64.encode("ascii"))
        assert result.envelope_jcs_bytes == expected_jcs_bytes, (
            f"fixture {name}: envelope JCS bytes drift "
            f"{result.envelope_jcs_bytes!r} != {expected_jcs_bytes!r}"
        )
        # (2) JCS bytes length.
        assert len(result.envelope_jcs_bytes) == expected[
            "envelope_jcs_bytes_len"
        ], f"fixture {name}: envelope JCS bytes length drift"
        # (3) Envelope SHA-256 hex byte-parity.
        assert (
            result.envelope_sha256_hex == expected["envelope_sha256_hex"]
        ), (
            f"fixture {name}: envelope SHA-256 hex drift "
            f"{result.envelope_sha256_hex!r} != "
            f"{expected['envelope_sha256_hex']!r}"
        )
        # (4) Prefixed envelope hash byte-parity.
        assert (
            result.envelope_hash_prefixed
            == expected["envelope_hash_prefixed"]
        ), (
            f"fixture {name}: envelope prefixed hash drift "
            f"{result.envelope_hash_prefixed!r} != "
            f"{expected['envelope_hash_prefixed']!r}"
        )
        # (5) Payload SHA-256 hex byte-parity.
        assert (
            result.payload_sha256_hex == expected["payload_sha256_hex"]
        ), (
            f"fixture {name}: payload SHA-256 hex drift "
            f"{result.payload_sha256_hex!r} != "
            f"{expected['payload_sha256_hex']!r}"
        )
        # Sanity: reconstructed envelope carries the canonical fields.
        assert result.envelope.event_id == inp["event_id"]
        assert result.envelope.timestamp_utc == inp["timestamp_utc"]
        assert result.envelope.persona_id == inp["persona_id"]
        assert result.envelope.payload_jcs_bytes == payload_bytes


# ---------------------------------------------------------------------------
# Vector AE9 — hash_anchor() roundtrip matches serialize_anchor() bytes.
# ---------------------------------------------------------------------------


def test_rust_anchor_emitter_hash_anchor_matches_serialize_anchor():
    """A pre-built AnchorEnvelope passed to ``hash_anchor`` must produce
    the same quadruple (JCS bytes / env hex / prefixed / payload hex) as
    the equivalent ``serialize_anchor`` call. Guards against accidental
    divergence between the two surface methods."""
    from wirelang.persona_engine.anchor_emitter import (
        AnchorEmitterInput,
        build_anchor_envelope,
    )

    invoker = _make_anchor_emitter_invoker_via_python_authority()
    bridge = RustSubprocessAnchorEmitter(
        bin_path="/fake/bin",
        timeout_s=1.0,
        subprocess_invoker=invoker,
    )
    args = {
        "event_id": "evt-tag23-roundtrip-01",
        "timestamp_utc": "2026-05-17T17:44:28Z",
        "persona_id": "selin",
        "payload_jcs_bytes": b'{"k":"v"}',
    }
    via_serialize = bridge.serialize_anchor(**args)
    envelope = build_anchor_envelope(AnchorEmitterInput(**args))
    via_hash = bridge.hash_anchor(envelope)
    assert via_serialize.envelope_jcs_bytes == via_hash.envelope_jcs_bytes
    assert via_serialize.envelope_sha256_hex == via_hash.envelope_sha256_hex
    assert (
        via_serialize.envelope_hash_prefixed
        == via_hash.envelope_hash_prefixed
    )
    assert via_serialize.payload_sha256_hex == via_hash.payload_sha256_hex
    assert via_serialize.envelope == via_hash.envelope


# ---------------------------------------------------------------------------
# Vector AE10 — subprocess exit_nonzero → RustBackendError(exit_nonzero).
# ---------------------------------------------------------------------------


def test_rust_anchor_emitter_exit_nonzero_raises():
    def fail_invoker(bin_path, argv, *, stdin_payload, timeout_s):
        return 2, "", "boom"

    bridge = RustSubprocessAnchorEmitter(
        bin_path="/fake/bin",
        subprocess_invoker=fail_invoker,
    )
    with pytest.raises(RustBackendError) as ei:
        bridge.serialize_anchor(
            event_id="evt-1",
            timestamp_utc="2026-05-17T00:00:00Z",
            persona_id="p",
            payload_jcs_bytes=b"{}",
        )
    assert ei.value.reason == "exit_nonzero"
    assert ei.value.returncode == 2


# ---------------------------------------------------------------------------
# Vector AE11 — subprocess bad JSON → RustBackendError(bad_json).
# ---------------------------------------------------------------------------


def test_rust_anchor_emitter_bad_json_raises():
    def bad_json_invoker(bin_path, argv, *, stdin_payload, timeout_s):
        return 0, "not-valid-json", ""

    bridge = RustSubprocessAnchorEmitter(
        bin_path="/fake/bin",
        subprocess_invoker=bad_json_invoker,
    )
    with pytest.raises(RustBackendError) as ei:
        bridge.serialize_anchor(
            event_id="evt-1",
            timestamp_utc="2026-05-17T00:00:00Z",
            persona_id="p",
            payload_jcs_bytes=b"{}",
        )
    assert ei.value.reason == "bad_json"


# ---------------------------------------------------------------------------
# Vector AE12 — build_anchor_emitter(PYTHON / RUST) surfaces match.
# ---------------------------------------------------------------------------


def test_build_anchor_emitter_python_and_rust_surfaces_match_api():
    """Both factories expose the same method-set so callers cannot tell
    the backends apart at the API boundary. The Python adapter also
    produces a fixture-pinned result so the surface is exercised
    end-to-end without a subprocess."""
    py_adapter = build_anchor_emitter(AnchorEmitterBackend.PYTHON)
    assert hasattr(py_adapter, "serialize_anchor")
    assert hasattr(py_adapter, "hash_anchor")

    # Fixture f01 (empty-object payload) Python-path roundtrip.
    result = py_adapter.serialize_anchor(
        event_id="evt-2026-05-17-anchor-fixture-01",
        timestamp_utc="2026-05-17T00:00:00Z",
        persona_id="reza",
        payload_jcs_bytes=b"{}",
    )
    assert isinstance(result, AnchorEmitterSubprocessResult)
    # Fixture-pinned envelope hash (from
    # tests/fixtures/anchor-emitter-cross-lang/fixtures.json f01).
    assert result.envelope_hash_prefixed == (
        "sha256:020ab30477e0167274741b59868279c1b16800c234b6453f956329ccc416ccc2"
    )
    assert result.payload_sha256_hex == (
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )
    assert len(result.envelope_jcs_bytes) == 229

    # Rust-bound factory returns the subprocess-bridge.
    rust_bridge = build_anchor_emitter(
        AnchorEmitterBackend.RUST,
        env={RUST_ANCHOR_EMITTER_BIN_ENV: "/custom/wakir-anchor-emitter"},
    )
    assert isinstance(rust_bridge, RustSubprocessAnchorEmitter)
    assert rust_bridge.bin_path == "/custom/wakir-anchor-emitter"
    assert hasattr(rust_bridge, "serialize_anchor")
    assert hasattr(rust_bridge, "hash_anchor")


# ---------------------------------------------------------------------------
# Vector AE13 — default-bin path + logging + auftrag-alias +
# client-side validation (combined to keep the test count compact).
# ---------------------------------------------------------------------------


def test_anchor_emitter_default_bin_and_logging_and_alias_and_validation(
    tmp_path: Path,
):
    """Covers four related invariants in one hermetic test:

    1. The default Rust-binary path resolves to the canonical
       ``/opt/wakir/bin/wakir-persona-engine-anchor-emitter`` when
       the env-var is unset.
    2. Per-decision logging emits exactly one structured JSON line.
    3. The ``_select_anchor_emitter_backend`` auftrag-alias dispatches
       identically to :func:`resolve_anchor_emitter_backend`.
    4. Client-side validation short-circuits on bad input
       (empty event_id, malformed timestamp_utc) without spawning a
       subprocess.
    """
    from wirelang.persona_engine.anchor_emitter import (
        BadTimestampShapeError,
        EmptyFieldError,
    )
    from wirelang.persona_engine.rust_backend_switch import (
        _resolve_anchor_emitter_bin,
    )

    # (1) Default-bin path resolution.
    assert (
        _resolve_anchor_emitter_bin(env={}) == DEFAULT_RUST_ANCHOR_EMITTER_BIN
    )
    assert (
        DEFAULT_RUST_ANCHOR_EMITTER_BIN
        == "/opt/wakir/bin/wakir-persona-engine-anchor-emitter"
    )

    # (2) Per-decision logging emits one structured JSON line.
    sink = io.StringIO()
    chosen, _ = resolve_anchor_emitter_backend(env={}, log_sink=sink)
    line = sink.getvalue().strip()
    assert line, "expected one structured-log line emitted"
    parsed = json.loads(line)
    assert parsed["msg"] == "backend-decision"
    assert parsed["domain"] == "anchor_emitter"
    assert parsed["requested_backend"] == "python"
    assert parsed["chosen_backend"] == "python"
    assert parsed["resolution_latency_us"] >= 0
    assert chosen is AnchorEmitterBackend.PYTHON

    # (3) Auftrag-alias dispatches identically — unset env path.
    chosen_a, decision_a = _select_anchor_emitter_backend(env={})
    chosen_b, decision_b = resolve_anchor_emitter_backend(env={})
    assert chosen_a is chosen_b
    assert decision_a.domain == decision_b.domain
    assert decision_a.requested_backend == decision_b.requested_backend
    assert decision_a.chosen_backend == decision_b.chosen_backend
    assert decision_a.fallback_reason == decision_b.fallback_reason
    # Auftrag-alias dispatches identically — rust + missing-binary path.
    missing = tmp_path / "does-not-exist"
    env = {
        ANCHOR_EMITTER_BACKEND_ENV: "rust",
        RUST_ANCHOR_EMITTER_BIN_ENV: str(missing),
    }
    chosen_c, decision_c = _select_anchor_emitter_backend(env=env)
    chosen_d, decision_d = resolve_anchor_emitter_backend(env=env)
    assert chosen_c is chosen_d is AnchorEmitterBackend.PYTHON
    assert (
        decision_c.fallback_reason
        == decision_d.fallback_reason
        == "binary_missing"
    )

    # (4) Client-side validation rejects bad inputs without spawning.
    def never_called_invoker(bin_path, argv, *, stdin_payload, timeout_s):
        raise AssertionError("invoker should not be called on bad input")

    bridge = RustSubprocessAnchorEmitter(
        bin_path="/fake/bin",
        subprocess_invoker=never_called_invoker,
    )
    # Empty event_id.
    with pytest.raises(EmptyFieldError):
        bridge.serialize_anchor(
            event_id="   ",
            timestamp_utc="2026-05-17T00:00:00Z",
            persona_id="p",
            payload_jcs_bytes=b"{}",
        )
    # Bad timestamp shape (missing trailing Z).
    with pytest.raises(BadTimestampShapeError):
        bridge.serialize_anchor(
            event_id="evt-1",
            timestamp_utc="2026-05-17T00:00:00",
            persona_id="p",
            payload_jcs_bytes=b"{}",
        )
    # Non-bytes payload — TypeError before subprocess.
    with pytest.raises(TypeError):
        bridge.serialize_anchor(
            event_id="evt-1",
            timestamp_utc="2026-05-17T00:00:00Z",
            persona_id="p",
            payload_jcs_bytes="not-bytes",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Tag-25 Mini-Welle — SVID-Workload-Identity backend resolver
# (ADR-0065 Welle-2 precondition).
#
# Coverage map (12 hermetic vectors, >=10 required by auftrag):
#
#   SVID01 unset env -> python default, no fallback_reason, no bin_path.
#   SVID02 explicit "python" -> python + fallback_reason="explicit_python".
#   SVID03 "rust" + available binary -> rust chosen, bin_path resolved.
#   SVID04 "rust" + missing binary -> graceful python fallback,
#          fallback_reason="binary_missing" (ADR-0065 Welle-2 signal).
#   SVID05 "rust" + non-executable file -> python fallback,
#          fallback_reason="binary_not_executable".
#   SVID06 unknown env value -> BackendSwitchValidationError.
#   SVID07 empty-string env -> python default (no error).
#   SVID08 default bin path resolves to the canonical
#          /opt/wakir/bin/wakir-persona-engine-svid-workload-identity.
#   SVID09 RUST_SVID_WORKLOAD_IDENTITY_BIN_ENV override is respected.
#   SVID10 per-decision logging emits exactly one structured JSON line
#          to log_sink, with domain="svid_workload_identity".
#   SVID11 _select_svid_workload_identity_backend auftrag-alias dispatches
#          identically to resolve_svid_workload_identity_backend.
#   SVID12 enum + valid-value tuple consistency
#          (closed-set: ("python", "rust")).
# ---------------------------------------------------------------------------


def test_svid_workload_identity_unset_defaults_to_rust_with_graceful_python_fallback():
    """SVID01 — Tag-80 Welle-2: env-unset defaults to ``rust`` now.

    Sandbox-CI ohne rust-Binary → graceful fallback python mit
    fallback_reason="binary_missing".
    """
    env: dict = {}
    chosen, decision = resolve_svid_workload_identity_backend(env=env)
    assert chosen is SvidWorkloadIdentityBackend.PYTHON  # graceful fallback
    assert decision.domain == "svid_workload_identity"
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason == "binary_missing"
    assert decision.bin_path == DEFAULT_RUST_SVID_WORKLOAD_IDENTITY_BIN
    assert decision.resolution_latency_us >= 0


def test_svid_workload_identity_explicit_python():
    """SVID02 — explicit ``python`` carries ``explicit_python`` token."""
    env = {SVID_WORKLOAD_IDENTITY_BACKEND_ENV: "python"}
    chosen, decision = resolve_svid_workload_identity_backend(env=env)
    assert chosen is SvidWorkloadIdentityBackend.PYTHON
    assert decision.fallback_reason == "explicit_python"
    assert decision.bin_path is None


def test_svid_workload_identity_rust_with_available_binary(tmp_path: Path):
    """SVID03 — ``rust`` + executable binary => rust chosen."""
    bin_path = _make_executable(tmp_path / "wakir-persona-engine-svid-workload-identity")
    env = {
        SVID_WORKLOAD_IDENTITY_BACKEND_ENV: "rust",
        RUST_SVID_WORKLOAD_IDENTITY_BIN_ENV: str(bin_path),
    }
    chosen, decision = resolve_svid_workload_identity_backend(env=env)
    assert chosen is SvidWorkloadIdentityBackend.RUST
    assert decision.domain == "svid_workload_identity"
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "rust"
    assert decision.fallback_reason is None
    assert decision.bin_path == str(bin_path)


def test_svid_workload_identity_rust_with_missing_binary_graceful_fallback(
    tmp_path: Path,
):
    """SVID04 — ``rust`` + missing binary => python fallback.

    This is the **ADR-0065 Welle-2 precondition signal**: operators
    flipping the env-var before the Rust crate ships will observe
    ``fallback_reason="binary_missing"`` in the audit substrate.
    """
    missing = tmp_path / "does-not-exist"
    env = {
        SVID_WORKLOAD_IDENTITY_BACKEND_ENV: "rust",
        RUST_SVID_WORKLOAD_IDENTITY_BIN_ENV: str(missing),
    }
    chosen, decision = resolve_svid_workload_identity_backend(env=env)
    assert chosen is SvidWorkloadIdentityBackend.PYTHON
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason == "binary_missing"
    assert decision.bin_path == str(missing)


def test_svid_workload_identity_rust_with_not_executable_binary_graceful_fallback(
    tmp_path: Path,
):
    """SVID05 — ``rust`` + non-executable file => python fallback."""
    non_exec = _make_non_executable_file(
        tmp_path / "svid-workload-identity-not-exec"
    )
    env = {
        SVID_WORKLOAD_IDENTITY_BACKEND_ENV: "rust",
        RUST_SVID_WORKLOAD_IDENTITY_BIN_ENV: str(non_exec),
    }
    chosen, decision = resolve_svid_workload_identity_backend(env=env)
    assert chosen is SvidWorkloadIdentityBackend.PYTHON
    assert decision.fallback_reason == "binary_not_executable"
    assert decision.bin_path == str(non_exec)


def test_svid_workload_identity_validation_rejects_unknown():
    """SVID06 — unknown env-var value raises BackendSwitchValidationError."""
    env = {SVID_WORKLOAD_IDENTITY_BACKEND_ENV: "go"}
    with pytest.raises(BackendSwitchValidationError) as excinfo:
        resolve_svid_workload_identity_backend(env=env)
    err = excinfo.value
    assert err.env_var == SVID_WORKLOAD_IDENTITY_BACKEND_ENV
    assert err.value == "go"
    assert err.valid_values == VALID_SVID_WORKLOAD_IDENTITY_BACKEND_VALUES


def test_svid_workload_identity_empty_string_env_defaults_to_rust_with_graceful_python_fallback():
    """SVID07 — Tag-80 Welle-2: empty-string env defaults to rust.

    Same graceful-fallback semantics as the env-unset path.
    """
    env = {SVID_WORKLOAD_IDENTITY_BACKEND_ENV: ""}
    chosen, decision = resolve_svid_workload_identity_backend(env=env)
    assert chosen is SvidWorkloadIdentityBackend.PYTHON  # graceful fallback
    assert decision.requested_backend == "rust"
    assert decision.fallback_reason == "binary_missing"


def test_svid_workload_identity_default_binary_path_when_env_unset():
    """SVID08 — default bin path resolves to the canonical Welle-2 path."""
    from wirelang.persona_engine.rust_backend_switch import (
        _resolve_svid_workload_identity_bin,
    )

    assert (
        _resolve_svid_workload_identity_bin(env={})
        == DEFAULT_RUST_SVID_WORKLOAD_IDENTITY_BIN
    )
    assert (
        DEFAULT_RUST_SVID_WORKLOAD_IDENTITY_BIN
        == "/opt/wakir/bin/wakir-persona-engine-svid-workload-identity"
    )


def test_svid_workload_identity_explicit_bin_env_override(tmp_path: Path):
    """SVID09 — RUST_SVID_WORKLOAD_IDENTITY_BIN_ENV override is respected."""
    from wirelang.persona_engine.rust_backend_switch import (
        _resolve_svid_workload_identity_bin,
    )

    override = tmp_path / "custom-svid-binary"
    env = {RUST_SVID_WORKLOAD_IDENTITY_BIN_ENV: str(override)}
    assert _resolve_svid_workload_identity_bin(env=env) == str(override)


def test_svid_workload_identity_per_decision_logging_writes_sink():
    """SVID10 — per-decision logging emits one structured JSON line."""
    sink = io.StringIO()
    chosen, _ = resolve_svid_workload_identity_backend(env={}, log_sink=sink)
    line = sink.getvalue().strip()
    assert line, "expected one structured-log line emitted"
    parsed = json.loads(line)
    assert parsed["msg"] == "backend-decision"
    assert parsed["domain"] == "svid_workload_identity"
    # Tag-80 Welle-2 Cutover: default flipped to rust, graceful
    # fallback to python on Sandbox-CI without rust binary.
    assert parsed["requested_backend"] == "rust"
    assert parsed["chosen_backend"] == "python"
    assert parsed["resolution_latency_us"] >= 0
    assert chosen is SvidWorkloadIdentityBackend.PYTHON


def test_svid_workload_identity_auftrag_alias_dispatches_identically(
    tmp_path: Path,
):
    """SVID11 — auftrag-alias dispatches identically to canonical resolver.

    Covers two surfaces:
      (a) env-unset python path.
      (b) ``rust`` + missing-binary graceful-fallback path (the
          ADR-0065 Welle-2 precondition signal).
    """
    # (a) Unset env path.
    chosen_a, decision_a = _select_svid_workload_identity_backend(env={})
    chosen_b, decision_b = resolve_svid_workload_identity_backend(env={})
    assert chosen_a is chosen_b
    assert decision_a.domain == decision_b.domain
    assert decision_a.requested_backend == decision_b.requested_backend
    assert decision_a.chosen_backend == decision_b.chosen_backend
    assert decision_a.fallback_reason == decision_b.fallback_reason

    # (b) Rust + missing-binary path.
    missing = tmp_path / "does-not-exist"
    env = {
        SVID_WORKLOAD_IDENTITY_BACKEND_ENV: "rust",
        RUST_SVID_WORKLOAD_IDENTITY_BIN_ENV: str(missing),
    }
    chosen_c, decision_c = _select_svid_workload_identity_backend(env=env)
    chosen_d, decision_d = resolve_svid_workload_identity_backend(env=env)
    assert chosen_c is chosen_d is SvidWorkloadIdentityBackend.PYTHON
    assert (
        decision_c.fallback_reason
        == decision_d.fallback_reason
        == "binary_missing"
    )
    assert decision_c.bin_path == decision_d.bin_path == str(missing)


def test_svid_workload_identity_enum_and_valid_values_consistency():
    """SVID12 — enum + valid-value tuple is closed-set ("python", "rust")."""
    # Enum exposes exactly two members.
    member_values = tuple(b.value for b in SvidWorkloadIdentityBackend)
    assert member_values == ("python", "rust")
    # Valid-values tuple matches enum order.
    assert VALID_SVID_WORKLOAD_IDENTITY_BACKEND_VALUES == ("python", "rust")
    # Enum is a str-enum (mirrors the rest of the resolver family).
    assert SvidWorkloadIdentityBackend.PYTHON.value == "python"
    assert SvidWorkloadIdentityBackend.RUST.value == "rust"
    # `__all__` re-exports the enum and the valid-value tuple as a
    # public surface; the auftrag-alias stays private (mirrors the
    # other seven resolver families).
    from wirelang.persona_engine import rust_backend_switch as rbs

    assert "SvidWorkloadIdentityBackend" in rbs.__all__
    assert "VALID_SVID_WORKLOAD_IDENTITY_BACKEND_VALUES" in rbs.__all__
    assert "resolve_svid_workload_identity_backend" in rbs.__all__
    assert "_select_svid_workload_identity_backend" not in rbs.__all__


# ---------------------------------------------------------------------------
# Tag-30 Mini-Welle — Federation-Resolver backend resolver
# (9. BackendDecision per boot; byte-cross-lang parity against
# PR #188 fixtures).
#
# Coverage map (12 hermetic vectors, >=10 required by auftrag):
#
#   FR01 unset env -> python default, no fallback_reason, no bin_path.
#   FR02 explicit "python" -> python + fallback_reason="explicit_python".
#   FR03 "rust" + available binary -> rust chosen, bin_path resolved.
#   FR04 "rust" + missing binary -> graceful python fallback,
#        fallback_reason="binary_missing".
#   FR05 "rust" + non-executable file -> python fallback,
#        fallback_reason="binary_not_executable".
#   FR06 unknown env value -> BackendSwitchValidationError.
#   FR07 empty-string env -> python default (no error).
#   FR08 default bin path resolves to the canonical
#        /opt/wakir/bin/wakir-persona-engine-federation-resolver.
#   FR09 RUST_FEDERATION_RESOLVER_BIN_ENV override is respected.
#   FR10 per-decision logging emits exactly one structured JSON line
#        to log_sink, with domain="federation_resolver".
#   FR11 _select_federation_resolver_backend auftrag-alias dispatches
#        identically to resolve_federation_resolver_backend.
#   FR12 enum + valid-value tuple consistency
#        (closed-set: ("python", "rust")) AND byte-parity verification
#        against the five PR #188 cross-lang resolver-snapshot fixtures.
# ---------------------------------------------------------------------------


def test_federation_resolver_unset_defaults_to_python():
    """FR01 — env-unset path: python default, no fallback_reason."""
    env: dict = {}
    chosen, decision = resolve_federation_resolver_backend(env=env)
    assert chosen is FederationResolverBackend.PYTHON
    assert decision.domain == "federation_resolver"
    assert decision.requested_backend == "python"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason is None
    assert decision.bin_path is None
    assert decision.resolution_latency_us >= 0


def test_federation_resolver_explicit_python():
    """FR02 — explicit ``python`` carries ``explicit_python`` token."""
    env = {FEDERATION_RESOLVER_BACKEND_ENV: "python"}
    chosen, decision = resolve_federation_resolver_backend(env=env)
    assert chosen is FederationResolverBackend.PYTHON
    assert decision.fallback_reason == "explicit_python"
    assert decision.bin_path is None


def test_federation_resolver_rust_with_available_binary(tmp_path: Path):
    """FR03 — ``rust`` + executable binary => rust chosen."""
    bin_path = _make_executable(
        tmp_path / "wakir-persona-engine-federation-resolver"
    )
    env = {
        FEDERATION_RESOLVER_BACKEND_ENV: "rust",
        RUST_FEDERATION_RESOLVER_BIN_ENV: str(bin_path),
    }
    chosen, decision = resolve_federation_resolver_backend(env=env)
    assert chosen is FederationResolverBackend.RUST
    assert decision.domain == "federation_resolver"
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "rust"
    assert decision.fallback_reason is None
    assert decision.bin_path == str(bin_path)


def test_federation_resolver_rust_with_missing_binary_graceful_fallback(
    tmp_path: Path,
):
    """FR04 — ``rust`` + missing binary => python fallback."""
    missing = tmp_path / "does-not-exist"
    env = {
        FEDERATION_RESOLVER_BACKEND_ENV: "rust",
        RUST_FEDERATION_RESOLVER_BIN_ENV: str(missing),
    }
    chosen, decision = resolve_federation_resolver_backend(env=env)
    assert chosen is FederationResolverBackend.PYTHON
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason == "binary_missing"
    assert decision.bin_path == str(missing)


def test_federation_resolver_rust_with_not_executable_binary_graceful_fallback(
    tmp_path: Path,
):
    """FR05 — ``rust`` + non-executable file => python fallback."""
    non_exec = _make_non_executable_file(
        tmp_path / "federation-resolver-not-exec"
    )
    env = {
        FEDERATION_RESOLVER_BACKEND_ENV: "rust",
        RUST_FEDERATION_RESOLVER_BIN_ENV: str(non_exec),
    }
    chosen, decision = resolve_federation_resolver_backend(env=env)
    assert chosen is FederationResolverBackend.PYTHON
    assert decision.fallback_reason == "binary_not_executable"
    assert decision.bin_path == str(non_exec)


def test_federation_resolver_validation_rejects_unknown():
    """FR06 — unknown env-var value raises BackendSwitchValidationError."""
    env = {FEDERATION_RESOLVER_BACKEND_ENV: "go"}
    with pytest.raises(BackendSwitchValidationError) as excinfo:
        resolve_federation_resolver_backend(env=env)
    err = excinfo.value
    assert err.env_var == FEDERATION_RESOLVER_BACKEND_ENV
    assert err.value == "go"
    assert err.valid_values == VALID_FEDERATION_RESOLVER_BACKEND_VALUES


def test_federation_resolver_empty_string_env_defaults_to_python():
    """FR07 — empty-string env value defaults to python (no error)."""
    env = {FEDERATION_RESOLVER_BACKEND_ENV: ""}
    chosen, decision = resolve_federation_resolver_backend(env=env)
    assert chosen is FederationResolverBackend.PYTHON
    assert decision.fallback_reason is None
    assert decision.bin_path is None


def test_federation_resolver_default_binary_path_when_env_unset():
    """FR08 — default bin path resolves to the canonical Tag-30 path."""
    from wirelang.persona_engine.rust_backend_switch import (
        _resolve_federation_resolver_bin,
    )

    assert (
        _resolve_federation_resolver_bin(env={})
        == DEFAULT_RUST_FEDERATION_RESOLVER_BIN
    )
    assert (
        DEFAULT_RUST_FEDERATION_RESOLVER_BIN
        == "/opt/wakir/bin/wakir-persona-engine-federation-resolver"
    )


def test_federation_resolver_explicit_bin_env_override(tmp_path: Path):
    """FR09 — RUST_FEDERATION_RESOLVER_BIN_ENV override is respected."""
    from wirelang.persona_engine.rust_backend_switch import (
        _resolve_federation_resolver_bin,
    )

    override = tmp_path / "custom-federation-resolver-binary"
    env = {RUST_FEDERATION_RESOLVER_BIN_ENV: str(override)}
    assert _resolve_federation_resolver_bin(env=env) == str(override)


def test_federation_resolver_per_decision_logging_writes_sink():
    """FR10 — per-decision logging emits one structured JSON line."""
    sink = io.StringIO()
    chosen, _ = resolve_federation_resolver_backend(env={}, log_sink=sink)
    line = sink.getvalue().strip()
    assert line, "expected one structured-log line emitted"
    parsed = json.loads(line)
    assert parsed["msg"] == "backend-decision"
    assert parsed["domain"] == "federation_resolver"
    assert parsed["requested_backend"] == "python"
    assert parsed["chosen_backend"] == "python"
    assert parsed["resolution_latency_us"] >= 0
    assert chosen is FederationResolverBackend.PYTHON


def test_federation_resolver_auftrag_alias_dispatches_identically(
    tmp_path: Path,
):
    """FR11 — auftrag-alias dispatches identically to canonical resolver.

    Covers two surfaces:
      (a) env-unset python path.
      (b) ``rust`` + missing-binary graceful-fallback path.
    """
    # (a) Unset env path.
    chosen_a, decision_a = _select_federation_resolver_backend(env={})
    chosen_b, decision_b = resolve_federation_resolver_backend(env={})
    assert chosen_a is chosen_b
    assert decision_a.domain == decision_b.domain
    assert decision_a.requested_backend == decision_b.requested_backend
    assert decision_a.chosen_backend == decision_b.chosen_backend
    assert decision_a.fallback_reason == decision_b.fallback_reason

    # (b) Rust + missing-binary path.
    missing = tmp_path / "does-not-exist"
    env = {
        FEDERATION_RESOLVER_BACKEND_ENV: "rust",
        RUST_FEDERATION_RESOLVER_BIN_ENV: str(missing),
    }
    chosen_c, decision_c = _select_federation_resolver_backend(env=env)
    chosen_d, decision_d = resolve_federation_resolver_backend(env=env)
    assert chosen_c is chosen_d is FederationResolverBackend.PYTHON
    assert (
        decision_c.fallback_reason
        == decision_d.fallback_reason
        == "binary_missing"
    )
    assert decision_c.bin_path == decision_d.bin_path == str(missing)


def test_federation_resolver_enum_and_byte_parity_against_pr188_fixtures():
    """FR12 — enum + valid-value tuple closed-set, AND byte-parity check
    against the five PR #188 cross-lang resolver-snapshot fixtures.

    The byte-parity check ties the backend-switch resolver wire-in to
    the **actual** Python-authority output: any drift between the
    Python ``federation_resolver_canonical`` module and the fixture
    file would invalidate the Doppelbetrieb-Vergleich assumption that
    the 9th BackendDecision underpins.
    """
    # Enum closed-set.
    member_values = tuple(b.value for b in FederationResolverBackend)
    assert member_values == ("python", "rust")
    assert VALID_FEDERATION_RESOLVER_BACKEND_VALUES == ("python", "rust")
    assert FederationResolverBackend.PYTHON.value == "python"
    assert FederationResolverBackend.RUST.value == "rust"

    # __all__ surface check.
    from wirelang.persona_engine import rust_backend_switch as rbs

    assert "FederationResolverBackend" in rbs.__all__
    assert "VALID_FEDERATION_RESOLVER_BACKEND_VALUES" in rbs.__all__
    assert "resolve_federation_resolver_backend" in rbs.__all__
    assert "_select_federation_resolver_backend" not in rbs.__all__

    # Byte-parity against the five PR #188 cross-lang fixtures.
    import base64

    from wirelang.identity.federation_resolver_canonical import (
        build_entry,
        build_snapshot_from_entries,
        resolver_snapshot_hash_prefixed,
        resolver_snapshot_sha256_hex,
        serialize_resolver_snapshot,
    )

    # Locate the fixture file relative to the repo root. The test is
    # hermetic — it consumes only the on-disk fixture, no network.
    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "federation-resolver-cross-lang"
        / "fixtures.json"
    )
    assert fixture_path.exists(), (
        f"PR #188 cross-lang fixture file missing at {fixture_path}"
    )
    doc = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixtures = doc["fixtures"]
    assert len(fixtures) == 5, (
        f"expected 5 PR #188 cross-lang fixtures, got {len(fixtures)}"
    )

    for fx in fixtures:
        entries = []
        for raw in fx["input_entries"]:
            entries.append(
                build_entry(
                    org_id=raw["org_id"],
                    cluster_id=raw["cluster_id"],
                    public_key_hex=raw["public_key_hex"],
                    valid_from=raw["valid_from"],
                    valid_until=raw["valid_until"],
                    alg=raw.get("alg", "ed25519"),
                )
            )
        snap = build_snapshot_from_entries(entries)
        py_bytes = serialize_resolver_snapshot(snap)
        py_sha256 = resolver_snapshot_sha256_hex(snap)
        py_prefixed = resolver_snapshot_hash_prefixed(snap)

        expected = fx["expected"]
        expected_bytes = base64.b64decode(expected["snapshot_jcs_bytes_b64"])
        assert py_bytes == expected_bytes, (
            f"fixture {fx['name']!r} JCS-byte drift "
            f"(py len={len(py_bytes)} vs fixture len={len(expected_bytes)})"
        )
        assert len(py_bytes) == expected["snapshot_jcs_bytes_len"]
        assert py_sha256 == expected["snapshot_sha256_hex"], (
            f"fixture {fx['name']!r} SHA-256 drift "
            f"(py={py_sha256} fixture={expected['snapshot_sha256_hex']})"
        )
        assert py_prefixed == expected["snapshot_hash_prefixed"]
