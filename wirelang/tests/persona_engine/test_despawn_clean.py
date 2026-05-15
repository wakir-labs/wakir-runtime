# SPDX-License-Identifier: BUSL-1.1
"""Tests for despawn-clean P1..P4 (spec §3.7.1)."""

from __future__ import annotations

import pytest

from wirelang.persona_engine.despawn_clean import (
    DESPAWN_CLEAN_PHASE_ORDER,
    DespawnCleanWorkflow,
    DespawnDirtyError,
    DespawnPhase,
)
from wirelang.persona_engine.lifecycle_state_machine import (
    LifecycleStateMachine,
)
from wirelang.persona_engine.state_backing import (
    InMemoryPersonaStateBacking,
)


def _wf(state="running", **overrides):
    fsm = LifecycleStateMachine(
        persona_id="tomas",
        org_id="acme",
        initial_state=state,
    )
    return DespawnCleanWorkflow(
        state_machine=fsm,
        state_backing=InMemoryPersonaStateBacking(),
        **overrides,
    )


def test_phase_order_matches_spec():
    assert DESPAWN_CLEAN_PHASE_ORDER == ("P1", "P2", "P3", "P4")


def test_despawn_phase_enum_four_members():
    assert len(list(DespawnPhase)) == 4


def test_full_despawn_run_from_running():
    wf = _wf("running")
    result = wf.run()
    assert result.success is True
    assert result.final_state == "uninstantiated"
    assert [p.phase for p in result.phases] == list(DespawnPhase)


def test_terminal_statuses_match_spec():
    wf = _wf("running")
    result = wf.run()
    statuses = [p.terminal_status for p in result.phases]
    assert statuses == ["drained", "revoked", "composed", "stopped"]


def test_despawn_from_invalid_state_raises():
    wf = _wf("uninstantiated")
    with pytest.raises(DespawnDirtyError):
        wf.run()


def test_despawn_idempotent_from_despawning_state():
    """Re-entering despawn from a stuck despawning state finishes
    cleanly (idempotence per §3.7.1.2)."""
    wf = _wf("despawning")
    result = wf.run()
    assert result.success is True


def test_phase_p1_failure_raises_dirty_error():
    wf = _wf("running", nats_drain=lambda persona_id: False)
    with pytest.raises(DespawnDirtyError) as exc:
        wf.run()
    assert exc.value.phase == DespawnPhase.P1_DRAIN_NATS_KV


def test_phase_p4_failure_raises_dirty_error():
    wf = _wf("running", container_stop=lambda persona_id: False)
    with pytest.raises(DespawnDirtyError) as exc:
        wf.run()
    assert exc.value.phase == DespawnPhase.P4_CONTAINER_STOP


def test_phase_p2_no_tokens_annotated():
    wf = _wf("running")
    result = wf.run()
    p2 = result.phases[1]
    assert p2.phase == DespawnPhase.P2_REVOKE_CAPABILITY_TOKENS
    # Default token_revoke returns empty list -> P2_NO_TOKENS annotation.
    assert p2.audit_annotation == "P2_NO_TOKENS"


def test_phase_p2_with_tokens_annotates_count():
    wf = _wf("running", token_revoke=lambda pid: ["t1", "t2", "t3"])
    result = wf.run()
    p2 = result.phases[1]
    assert p2.audit_annotation == "P2_REVOKED=3"


def test_phase_p3_carries_verdict():
    wf = _wf("running")
    result = wf.run()
    p3 = result.phases[2]
    assert "P3_VERDICT=DESPAWN_FINAL_PILOT" in p3.audit_annotation


def test_despawn_dirty_error_carries_phase_label():
    err = DespawnDirtyError(DespawnPhase.P3_FINAL_MARKER_COMPOSE, "reason-x")
    assert err.phase == DespawnPhase.P3_FINAL_MARKER_COMPOSE
    assert "reason-x" in str(err)
