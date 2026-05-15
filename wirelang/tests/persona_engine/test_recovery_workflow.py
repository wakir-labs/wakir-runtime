# SPDX-License-Identifier: BUSL-1.1
"""Tests for recovery_workflow R1..R4 (spec §3.7.4)."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from wirelang.persona_engine.lifecycle_state_machine import (
    LifecycleStateMachine,
)
from wirelang.persona_engine.recovery_workflow import (
    PHASE_SOFT_CAPS_SEC,
    RECOVERY_BUDGET_SECONDS,
    RECOVERY_WORKFLOW_PHASE_ORDER,
    RecoveryError,
    RecoveryFailureMode,
    RecoveryTrigger,
    RecoveryWorkflow,
)
from wirelang.persona_engine.state_backing import (
    InMemoryPersonaStateBacking,
    PersonaStateBackingError,
)
from wirelang.persona_engine.svid_workload_identity import SvidProbeResult


# -------------------- spec invariants --------------------


def test_phase_order_matches_spec():
    assert RECOVERY_WORKFLOW_PHASE_ORDER == ("R1", "R2", "R3", "R4")


def test_recovery_budget_seconds_30():
    assert RECOVERY_BUDGET_SECONDS == 30


def test_soft_caps_sum_to_30():
    assert sum(PHASE_SOFT_CAPS_SEC.values()) == 30


def test_recovery_trigger_enum_three_members():
    assert {t.value for t in RecoveryTrigger} == {
        "CrashDetected",
        "DespawnMidOperation",
        "StateCorruption",
    }


def test_recovery_failure_mode_enum_six_members():
    # Five §3.7.4.5 + BUDGET_EXCEEDED from §3.7.4.4.
    assert len(list(RecoveryFailureMode)) == 6


# -------------------- trigger classification --------------------


def _wf(fsm_state="uninstantiated"):
    fsm = LifecycleStateMachine(
        persona_id="tomas",
        org_id="acme",
        initial_state=fsm_state,
    )
    backing = InMemoryPersonaStateBacking()
    return RecoveryWorkflow(fsm, backing)


def test_classify_single_flag():
    wf = _wf()
    assert wf.classify_trigger(crash_detected=True) == RecoveryTrigger.CRASH_DETECTED
    assert (
        wf.classify_trigger(despawn_mid_operation=True)
        == RecoveryTrigger.DESPAWN_MID_OPERATION
    )
    assert wf.classify_trigger(state_corruption=True) == RecoveryTrigger.STATE_CORRUPTION


def test_classify_no_flags_raises_ambiguous():
    wf = _wf()
    with pytest.raises(RecoveryError) as exc:
        wf.classify_trigger()
    assert exc.value.mode == RecoveryFailureMode.TRIGGER_AMBIGUOUS


def test_classify_multiple_flags_raises_ambiguous():
    wf = _wf()
    with pytest.raises(RecoveryError) as exc:
        wf.classify_trigger(crash_detected=True, state_corruption=True)
    assert exc.value.mode == RecoveryFailureMode.TRIGGER_AMBIGUOUS


def test_force_trigger_overrides_ambiguity():
    wf = _wf()
    t = wf.classify_trigger(
        crash_detected=True,
        state_corruption=True,
        force_trigger=RecoveryTrigger.CRASH_DETECTED,
    )
    assert t == RecoveryTrigger.CRASH_DETECTED


# -------------------- end-to-end (mocked SVID probe) --------------------


def _mock_probe_ok(*args, **kwargs):
    return SvidProbeResult(
        socket_present=True,
        socket_connectable=True,
        expected_spiffe_id="spiffe://wakir.acme/persona/tomas",
        probed_at_utc="2026-05-15T15:00:00Z",
    )


def _mock_probe_fail(*args, **kwargs):
    return SvidProbeResult(
        socket_present=False,
        socket_connectable=False,
        expected_spiffe_id="spiffe://wakir.acme/persona/tomas",
        probed_at_utc="2026-05-15T15:00:00Z",
    )


def test_full_recovery_run_succeeds():
    wf = _wf()
    with patch(
        "wirelang.persona_engine.recovery_workflow.probe_workload_api_socket",
        side_effect=_mock_probe_ok,
    ):
        result = wf.run(crash_detected=True)
    assert result.success is True
    assert result.trigger == RecoveryTrigger.CRASH_DETECTED
    assert [p.phase for p in result.phases] == ["R1", "R2", "R3", "R4"]
    assert result.final_state == "running"


def test_recovery_run_with_state_corruption_trigger():
    wf = _wf()
    with patch(
        "wirelang.persona_engine.recovery_workflow.probe_workload_api_socket",
        side_effect=_mock_probe_ok,
    ):
        result = wf.run(state_corruption=True)
    assert result.trigger == RecoveryTrigger.STATE_CORRUPTION
    assert result.final_state == "running"


def test_recovery_run_svid_unreachable_raises_identity_rebind():
    wf = _wf()
    with patch(
        "wirelang.persona_engine.recovery_workflow.probe_workload_api_socket",
        side_effect=_mock_probe_fail,
    ):
        with pytest.raises(RecoveryError) as exc:
            wf.run(crash_detected=True)
    assert exc.value.mode == RecoveryFailureMode.IDENTITY_REBIND_ERROR


def test_recovery_run_backing_unreachable_raises():
    fsm = LifecycleStateMachine("tomas", "acme")
    backing = InMemoryPersonaStateBacking()

    class FlakyBacking(InMemoryPersonaStateBacking):
        def restore_latest(self, persona_id):
            raise PersonaStateBackingError("NATS down")

    wf = RecoveryWorkflow(fsm, FlakyBacking())
    with patch(
        "wirelang.persona_engine.recovery_workflow.probe_workload_api_socket",
        side_effect=_mock_probe_ok,
    ):
        with patch("wirelang.persona_engine.recovery_workflow.time.sleep"):
            with pytest.raises(RecoveryError) as exc:
                wf.run(crash_detected=True)
    assert exc.value.mode == RecoveryFailureMode.BACKING_UNREACHABLE


def test_recovery_run_idempotent_when_already_recovered():
    """A re-entered recovery on a partially-progressed FSM does not
    bounce — recovered -> running still works."""
    wf = _wf(fsm_state="recovered")
    with patch(
        "wirelang.persona_engine.recovery_workflow.probe_workload_api_socket",
        side_effect=_mock_probe_ok,
    ):
        result = wf.run(crash_detected=True)
    assert result.final_state == "running"


def test_phase_results_are_idempotent_in_terminal_status():
    wf = _wf()
    with patch(
        "wirelang.persona_engine.recovery_workflow.probe_workload_api_socket",
        side_effect=_mock_probe_ok,
    ):
        result1 = wf.run(crash_detected=True)
    # Phase terminal statuses are deterministic from the spec.
    statuses = [p.terminal_status for p in result1.phases]
    assert statuses == ["detected", "reloaded", "re_registered", "resumed"]


def test_recovery_failure_carries_mode_label():
    err = RecoveryError(RecoveryFailureMode.BUDGET_EXCEEDED, "elapsed=99")
    assert err.mode == RecoveryFailureMode.BUDGET_EXCEEDED
    assert "RecoveryBudgetExceededError" in str(err)
