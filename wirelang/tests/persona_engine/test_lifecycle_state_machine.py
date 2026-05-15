# SPDX-License-Identifier: BUSL-1.1
"""Tests for the lifecycle state machine (spec §3.3)."""

from __future__ import annotations

import pytest

from wirelang.persona_engine.lifecycle_state_machine import (
    STATES,
    VALID_TRANSITIONS,
    InvalidTransitionError,
    LifecycleStateMachine,
    TransitionRecord,
    UnknownStateError,
    _utc_now_rfc3339,
)


# -------------------- spec invariants --------------------


def test_states_match_spec_six_states():
    assert STATES == (
        "uninstantiated",
        "spawning",
        "running",
        "despawning",
        "recovered",
        "migrated",
    )


def test_valid_transitions_count_matches_spec_nine():
    assert len(VALID_TRANSITIONS) == 9


def test_valid_transitions_set_matches_spec():
    expected = {
        ("uninstantiated", "spawning"),
        ("spawning", "running"),
        ("spawning", "uninstantiated"),
        ("running", "despawning"),
        ("despawning", "uninstantiated"),
        ("uninstantiated", "recovered"),
        ("recovered", "running"),
        ("running", "migrated"),
        ("migrated", "uninstantiated"),
    }
    assert set(VALID_TRANSITIONS) == expected


# -------------------- construction --------------------


def test_default_initial_state_is_uninstantiated():
    m = LifecycleStateMachine("tomas", "acme")
    assert m.state == "uninstantiated"


def test_explicit_initial_state():
    m = LifecycleStateMachine("tomas", "acme", initial_state="running")
    assert m.state == "running"


def test_unknown_initial_state_raises():
    with pytest.raises(UnknownStateError):
        LifecycleStateMachine("tomas", "acme", initial_state="bogus")


# -------------------- transitions --------------------


def test_can_transition_to_valid_edge():
    m = LifecycleStateMachine("tomas", "acme")
    assert m.can_transition_to("spawning") is True


def test_cannot_transition_to_invalid_edge():
    m = LifecycleStateMachine("tomas", "acme")
    # uninstantiated -> running is NOT valid (must go through spawning
    # or recovered).
    assert m.can_transition_to("running") is False


def test_cannot_transition_to_unknown_state():
    m = LifecycleStateMachine("tomas", "acme")
    assert m.can_transition_to("bogus") is False


def test_transition_to_valid_changes_state():
    m = LifecycleStateMachine("tomas", "acme")
    m.transition_to("spawning")
    assert m.state == "spawning"


def test_transition_to_invalid_raises_and_does_not_change():
    m = LifecycleStateMachine("tomas", "acme")
    with pytest.raises(InvalidTransitionError):
        m.transition_to("running")  # uninstantiated -> running invalid
    assert m.state == "uninstantiated"


def test_transition_to_unknown_state_raises():
    m = LifecycleStateMachine("tomas", "acme")
    with pytest.raises(UnknownStateError):
        m.transition_to("bogus")


def test_full_spawn_to_despawn_cycle():
    m = LifecycleStateMachine("tomas", "acme")
    m.transition_to("spawning")
    m.transition_to("running")
    m.transition_to("despawning")
    m.transition_to("uninstantiated")
    assert m.state == "uninstantiated"


def test_recovery_path_two_hop():
    m = LifecycleStateMachine("tomas", "acme")
    m.transition_to("recovered")  # uninstantiated -> recovered
    m.transition_to("running")  # recovered -> running
    assert m.state == "running"


def test_migration_path():
    m = LifecycleStateMachine("tomas", "acme")
    m.transition_to("spawning")
    m.transition_to("running")
    m.transition_to("migrated")
    m.transition_to("uninstantiated")
    assert m.state == "uninstantiated"


def test_spawning_aborts_to_uninstantiated():
    m = LifecycleStateMachine("tomas", "acme")
    m.transition_to("spawning")
    m.transition_to("uninstantiated")  # spawn aborted before running
    assert m.state == "uninstantiated"


# -------------------- audit history --------------------


def test_history_records_accepted_transitions():
    m = LifecycleStateMachine("tomas", "acme")
    m.transition_to("spawning")
    m.transition_to("running")
    h = m.history
    assert len(h) == 2
    assert all(r.accepted for r in h)
    assert h[0].from_state == "uninstantiated"
    assert h[0].to_state == "spawning"
    assert h[1].from_state == "spawning"
    assert h[1].to_state == "running"


def test_history_records_rejected_transitions():
    m = LifecycleStateMachine("tomas", "acme")
    with pytest.raises(InvalidTransitionError):
        m.transition_to("running")
    h = m.history
    assert len(h) == 1
    assert h[0].accepted is False
    assert h[0].reason == "not_in_valid_transitions"


def test_history_is_defensive_copy():
    m = LifecycleStateMachine("tomas", "acme")
    m.transition_to("spawning")
    h = m.history
    h.append("garbage")
    assert len(m.history) == 1


# -------------------- replay --------------------


def test_replay_rebuilds_state_from_records():
    m = LifecycleStateMachine("tomas", "acme")
    m.transition_to("spawning")
    m.transition_to("running")
    records = m.history

    m2 = LifecycleStateMachine.replay("tomas", "acme", records)
    assert m2.state == "running"
    assert len(m2.history) == 2


def test_replay_skips_rejected_records():
    rec_accept = TransitionRecord(
        from_state="uninstantiated",
        to_state="spawning",
        ts_utc=_utc_now_rfc3339(),
        accepted=True,
    )
    rec_reject = TransitionRecord(
        from_state="spawning",
        to_state="recovered",
        ts_utc=_utc_now_rfc3339(),
        accepted=False,
        reason="not_in_valid_transitions",
    )
    m = LifecycleStateMachine.replay("tomas", "acme", [rec_accept, rec_reject])
    # Replay keeps the rejection in the audit log but does not apply it.
    assert m.state == "spawning"
    assert len(m.history) == 2


def test_replay_detects_corrupted_records():
    # A recorded "accepted" record with an invalid edge is data
    # corruption; replay raises.
    bad = TransitionRecord(
        from_state="uninstantiated",
        to_state="running",  # not a valid edge
        ts_utc=_utc_now_rfc3339(),
        accepted=True,
    )
    with pytest.raises(InvalidTransitionError):
        LifecycleStateMachine.replay("tomas", "acme", [bad])


# -------------------- exhaustive invalid-edge sanity --------------------


def test_all_non_valid_pairs_rejected():
    """Cross-product of states minus VALID_TRANSITIONS must all reject."""
    valid_set = set(VALID_TRANSITIONS)
    for from_s in STATES:
        for to_s in STATES:
            if from_s == to_s:
                continue
            if (from_s, to_s) in valid_set:
                continue
            m = LifecycleStateMachine("tomas", "acme", initial_state=from_s)
            with pytest.raises(InvalidTransitionError):
                m.transition_to(to_s)
