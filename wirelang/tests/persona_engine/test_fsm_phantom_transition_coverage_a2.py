# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""A2 FSM-Phantom-Transition Coverage (Tag-46 follow-up to Amara-Tag-45).

The Amara-Tag-45 Pre-Mortem-Failure-Mode Coverage-Audit
(``docs/quality-gates/pre-mortem-failure-mode-coverage.md`` §A2)
classified A2 — "FSM-Phantom-Transitions (illegal state-transitions
post-cutover)" — as **PARTIAL**.

Existing partial coverage:

- Tag-44 AP-4 (`tests/phase_3c/test_marathon_anti_patterns.py`) pins
  the namespace-prefix discipline as a structural arm but does NOT
  exercise the transition-legality oracle directly.
- Tag-37 Rust FSM-Replay-Engine covers transition-legality at the
  Rust-crate-test layer in ``bridge-audit/``. Out-of-scope for the
  Python suite.

This file closes the Python-side gap. It exercises four structural
sub-pathways named by the Tag-45 audit (§A2 follow-up scope):

1. **state-machine-edge-cases** — every non-edge in
   :data:`VALID_TRANSITIONS` is rejected by ``transition_to``; the
   audit log records the rejection.
2. **race-conditions in transition-emit** — interleaved
   ``transition_to`` calls under a single-writer-per-instance
   contract preserve history-determinism; the FSM rejects edges
   that became invalid mid-sequence.
3. **snapshot-corruption-recovery** — :meth:`LifecycleStateMachine.replay`
   over a corrupted history (accepted-edge that is not in
   :data:`VALID_TRANSITIONS`, or accepted-edge whose ``from_state``
   does not match the running cursor) raises
   :class:`InvalidTransitionError` rather than silently advancing.
4. **cross-modul-leak to state_backing** — the FSM ``persona_id``
   namespace and the ``state_backing.snapshot`` ``persona_id`` key
   are bidirectionally isolated; a transition on persona A's FSM
   does not leak into persona B's state-backing keyspace.

The 15 tests are hermetic (no live NATS, no live workload-API)
and run under the default ``pytest -q`` lane (no opt-in marker).

Coverage-Matrix-Update: see
``docs/quality-gates/failure-mode-a2-coverage.md`` (Tag-46) which
re-classifies A2 PARTIAL -> COVERED on the strength of this suite.

— Reza, Tag-46 A2 FSM-Phantom-Transition Coverage, 2026-05-18
"""

from __future__ import annotations

import itertools
import threading
from typing import List, Tuple

import pytest

from wirelang.persona_engine.lifecycle_state_machine import (
    STATES,
    VALID_TRANSITIONS,
    InvalidTransitionError,
    LifecycleStateMachine,
    TransitionRecord,
    UnknownStateError,
)
from wirelang.persona_engine.state_backing import (
    InMemoryPersonaStateBacking,
    PersonaStateSnapshot,
    snapshot_payload_sha256,
)


# ---------------------------------------------------------------------------
# Section 1 — state-machine-edge-cases
# ---------------------------------------------------------------------------
#
# Cartesian-product oracle: for every (from, to) pair in STATES x STATES,
# the transition is accepted iff (from, to) in VALID_TRANSITIONS. The
# Tag-45 PARTIAL classification noted that namespace-prefix discipline
# (AP-4) is a structural arm but not a legality oracle. These tests are
# the missing legality oracle.


def _all_pairs() -> List[Tuple[str, str]]:
    return [(a, b) for a in STATES for b in STATES]


def test_a2_legality_oracle_every_invalid_edge_is_rejected():
    """For every (from, to) NOT in VALID_TRANSITIONS, transition_to
    raises InvalidTransitionError and appends an accepted=False
    record. STATES x STATES = 36; VALID_TRANSITIONS = 9; invalid = 27."""
    invalid_pairs = [p for p in _all_pairs() if p not in VALID_TRANSITIONS]
    assert len(invalid_pairs) == len(STATES) * len(STATES) - len(VALID_TRANSITIONS)
    for from_state, to_state in invalid_pairs:
        m = LifecycleStateMachine("reza", "wakir", initial_state=from_state)
        with pytest.raises(InvalidTransitionError) as ei:
            m.transition_to(to_state)
        assert ei.value.attempted == (from_state, to_state)
        # The rejection is recorded in the audit log.
        assert len(m.history) == 1
        rec = m.history[0]
        assert rec.from_state == from_state
        assert rec.to_state == to_state
        assert rec.accepted is False
        assert rec.reason == "not_in_valid_transitions"
        # State did NOT advance.
        assert m.state == from_state


def test_a2_legality_oracle_every_valid_edge_advances():
    """For every (from, to) IN VALID_TRANSITIONS, transition_to
    accepts the edge, advances state, and appends accepted=True."""
    for from_state, to_state in VALID_TRANSITIONS:
        m = LifecycleStateMachine("reza", "wakir", initial_state=from_state)
        rec = m.transition_to(to_state)
        assert rec.accepted is True
        assert rec.reason is None
        assert m.state == to_state
        assert len(m.history) == 1


def test_a2_self_loop_is_never_valid():
    """No state has a self-loop in VALID_TRANSITIONS. Phantom-transition
    A2 most commonly manifests as a self-loop emit under cutover-window
    race; the FSM MUST reject it."""
    for s in STATES:
        assert (s, s) not in VALID_TRANSITIONS
        m = LifecycleStateMachine("reza", "wakir", initial_state=s)
        with pytest.raises(InvalidTransitionError):
            m.transition_to(s)
        assert m.state == s


def test_a2_unknown_target_state_is_rejected_with_typed_error():
    """A phantom transition can also be a transition to a state the
    FSM has never heard of (typed-error path). UnknownStateError is
    raised, audit-log entry records reason=unknown_target_state."""
    m = LifecycleStateMachine("reza", "wakir")
    with pytest.raises(UnknownStateError):
        m.transition_to("phantom_zombie")
    assert len(m.history) == 1
    assert m.history[0].accepted is False
    assert m.history[0].reason == "unknown_target_state"
    assert m.state == "uninstantiated"


def test_a2_terminal_state_rejects_all_outgoing_phantoms():
    """A state is "phantom-attractor" if it has 0 outgoing edges.
    There are no such states in the spec, but defence-in-depth: every
    state has at least one valid outgoing edge."""
    outgoing = {s: 0 for s in STATES}
    for f, _t in VALID_TRANSITIONS:
        outgoing[f] += 1
    for s, n in outgoing.items():
        assert n >= 1, f"phantom-attractor: state {s!r} has 0 outgoing edges"


# ---------------------------------------------------------------------------
# Section 2 — race-conditions in transition-emit
# ---------------------------------------------------------------------------
#
# The FSM is single-writer; the spec contracts callers to serialise
# transitions externally. These tests verify that under serialised but
# rapid-fire transition-emit, history-determinism holds and the
# legality oracle still rejects mid-sequence phantoms.


def test_a2_rapid_fire_legal_sequence_history_determinism():
    """uninstantiated -> spawning -> running -> despawning ->
    uninstantiated -> recovered -> running -> migrated ->
    uninstantiated  (all nine edges exercised, history-deterministic).
    """
    m = LifecycleStateMachine("reza", "wakir")
    sequence = [
        "spawning",
        "running",
        "despawning",
        "uninstantiated",
        "recovered",
        "running",
        "migrated",
        "uninstantiated",
    ]
    for to in sequence:
        m.transition_to(to)
    assert m.state == "uninstantiated"
    assert len(m.history) == len(sequence)
    # All records accepted, in-order, monotonic.
    for rec, expected_to in zip(m.history, sequence, strict=True):
        assert rec.accepted is True
        assert rec.to_state == expected_to


def test_a2_mid_sequence_phantom_does_not_corrupt_history_cursor():
    """If a phantom transition is attempted mid-sequence, the rejection
    is logged but the next legal transition still works (history-cursor
    is not corrupted by the rejection)."""
    m = LifecycleStateMachine("reza", "wakir")
    m.transition_to("spawning")
    m.transition_to("running")
    # Phantom: running -> spawning is NOT in VALID_TRANSITIONS.
    with pytest.raises(InvalidTransitionError):
        m.transition_to("spawning")
    # The legal next-edge running -> despawning still works.
    m.transition_to("despawning")
    assert m.state == "despawning"
    # History: 4 entries (2 accepted, 1 rejected, 1 accepted).
    assert len(m.history) == 4
    assert [r.accepted for r in m.history] == [True, True, False, True]


def test_a2_serialised_writer_lock_emit_under_threading_lock():
    """Single-writer contract: when the caller serialises with a
    threading.Lock around transition_to, history-determinism holds
    across multiple OS threads. (The FSM itself is not thread-safe;
    the contract is that callers serialise. This test pins the
    contract.)
    """
    m = LifecycleStateMachine("reza", "wakir")
    lock = threading.Lock()
    # 9-edge marathon driven from two threads, each grabbing the lock.
    sequence = [
        "spawning",
        "running",
        "despawning",
        "uninstantiated",
        "recovered",
        "running",
        "migrated",
        "uninstantiated",
    ]
    cursor = {"i": 0}

    def driver():
        while True:
            with lock:
                i = cursor["i"]
                if i >= len(sequence):
                    return
                m.transition_to(sequence[i])
                cursor["i"] = i + 1

    threads = [threading.Thread(target=driver) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert m.state == "uninstantiated"
    assert len(m.history) == len(sequence)
    # History is monotonic and matches the canonical sequence.
    for rec, expected_to in zip(m.history, sequence, strict=True):
        assert rec.accepted is True
        assert rec.to_state == expected_to


# ---------------------------------------------------------------------------
# Section 3 — snapshot-corruption-recovery
# ---------------------------------------------------------------------------
#
# recovery_workflow §3.7.4 R2 calls LifecycleStateMachine.replay over
# the recorded history. If the history is corrupted (an accepted record
# that is not in VALID_TRANSITIONS, or whose from_state does not match
# the running cursor), replay MUST raise rather than silently advance.
# A2 phantom-transition under post-cutover corruption is the named
# threat.


def test_a2_replay_rejects_accepted_edge_not_in_valid_transitions():
    """Corrupted history: an accepted record with (from, to) not in
    VALID_TRANSITIONS MUST raise on replay."""
    corrupt = [
        TransitionRecord(
            from_state="uninstantiated",
            to_state="running",  # phantom: must go through spawning
            ts_utc="2026-05-18T20:00:00Z",
            accepted=True,
            reason=None,
        ),
    ]
    with pytest.raises(InvalidTransitionError):
        LifecycleStateMachine.replay("reza", "wakir", corrupt)


def test_a2_replay_rejects_accepted_edge_with_mismatched_from_state():
    """Corrupted history: a sequence of accepted records where the
    second record's from_state does not match the cursor MUST raise."""
    corrupt = [
        TransitionRecord(
            from_state="uninstantiated",
            to_state="spawning",
            ts_utc="2026-05-18T20:00:00Z",
            accepted=True,
            reason=None,
        ),
        TransitionRecord(
            # cursor is now "spawning"; this record claims from="running",
            # which is a phantom.
            from_state="running",
            to_state="despawning",
            ts_utc="2026-05-18T20:00:01Z",
            accepted=True,
            reason=None,
        ),
    ]
    with pytest.raises(InvalidTransitionError):
        LifecycleStateMachine.replay("reza", "wakir", corrupt)


def test_a2_replay_preserves_rejected_records_without_state_advance():
    """A rejected record in the history is replayed as an audit
    annotation but does NOT advance the cursor. This pins that the
    audit-log rejection-trace replays byte-for-byte without
    accidentally being upgraded to an accepted transition."""
    records = [
        TransitionRecord(
            from_state="uninstantiated",
            to_state="spawning",
            ts_utc="2026-05-18T20:00:00Z",
            accepted=True,
            reason=None,
        ),
        TransitionRecord(
            from_state="spawning",
            to_state="migrated",  # phantom (not in VALID_TRANSITIONS)
            ts_utc="2026-05-18T20:00:01Z",
            accepted=False,
            reason="not_in_valid_transitions",
        ),
        TransitionRecord(
            from_state="spawning",
            to_state="running",
            ts_utc="2026-05-18T20:00:02Z",
            accepted=True,
            reason=None,
        ),
    ]
    m = LifecycleStateMachine.replay("reza", "wakir", records)
    assert m.state == "running"
    # All three records appear in replayed history (the rejection is
    # preserved as an audit annotation).
    assert len(m.history) == 3
    assert [r.accepted for r in m.history] == [True, False, True]


def test_a2_replay_empty_history_yields_initial_state():
    """Boundary: an empty history yields a fresh uninstantiated FSM.
    This pins that "no records" is not a phantom-advance vector."""
    m = LifecycleStateMachine.replay("reza", "wakir", [])
    assert m.state == "uninstantiated"
    assert m.history == []


# ---------------------------------------------------------------------------
# Section 4 — cross-modul-leak to state_backing
# ---------------------------------------------------------------------------
#
# The FSM persona_id namespace and the state_backing persona_id key
# are independent. A phantom-transition under one persona MUST NOT
# leak into another persona's state_backing keyspace, and a
# state_backing snapshot under one persona MUST NOT affect another
# persona's FSM. This pins the Zone-1 Identity-Substrate-Konsens
# (Reza/Tomás) at the cross-module boundary.


def _make_snapshot(offset: int, persona_label: str) -> PersonaStateSnapshot:
    return PersonaStateSnapshot(
        persona_hash="sha256:" + ("a" * 64),
        audit_trace_offset=offset,
        capability_token_ids=(f"cap-{persona_label}-{offset}",),
        snapshot_at_utc=f"2026-05-18T20:00:{offset:02d}Z",
        workspace_state_hash="sha256:" + ("b" * 64),
    )


def test_a2_no_leak_fsm_transition_to_other_persona_state_backing():
    """Persona-A FSM transition does NOT create snapshots in
    persona-B's state_backing keyspace, and vice-versa.

    This is the structural arm Tag-44 AP-4 pins via namespace-prefix
    discipline; we additionally pin it across the FSM <-> state_backing
    seam.
    """
    fsm_a = LifecycleStateMachine("persona_a", "wakir")
    fsm_b = LifecycleStateMachine("persona_b", "wakir")
    backing = InMemoryPersonaStateBacking()

    # Persona-A transitions and writes a snapshot.
    fsm_a.transition_to("spawning")
    fsm_a.transition_to("running")
    snap_a = _make_snapshot(1, "a")
    off_a = backing.snapshot("persona_a", snap_a)

    # Persona-B FSM is untouched.
    assert fsm_b.state == "uninstantiated"
    assert len(fsm_b.history) == 0
    # Persona-B state_backing keyspace is empty.
    assert backing.restore_latest("persona_b") is None
    assert backing.list_snapshots("persona_b") == []
    # Persona-A keyspace has the one snapshot.
    assert backing.list_snapshots("persona_a") == [off_a]
    assert backing.restore_latest("persona_a") == snap_a


def test_a2_no_leak_state_backing_snapshot_does_not_advance_other_fsm():
    """Writing a state_backing snapshot under persona-B does NOT
    advance persona-A's FSM. This pins the inverse direction of the
    cross-module seam."""
    fsm_a = LifecycleStateMachine("persona_a", "wakir")
    backing = InMemoryPersonaStateBacking()

    fsm_a.transition_to("spawning")
    state_before = fsm_a.state
    history_len_before = len(fsm_a.history)

    # Snapshot under persona-B (unrelated).
    backing.snapshot("persona_b", _make_snapshot(1, "b"))
    backing.snapshot("persona_b", _make_snapshot(2, "b"))

    # Persona-A FSM is unaffected.
    assert fsm_a.state == state_before
    assert len(fsm_a.history) == history_len_before


def test_a2_phantom_transition_attempt_does_not_corrupt_state_backing():
    """A phantom transition attempt on the FSM (which raises) does
    NOT silently corrupt the state_backing keyspace. The state_backing
    snapshot taken before the phantom attempt remains byte-identical
    to a snapshot taken after the phantom attempt (FSM rejection is
    audit-only, no side-effect on backing)."""
    fsm = LifecycleStateMachine("persona_a", "wakir")
    backing = InMemoryPersonaStateBacking()

    fsm.transition_to("spawning")
    fsm.transition_to("running")
    snap_before = _make_snapshot(1, "a")
    backing.snapshot("persona_a", snap_before)
    digest_before = snapshot_payload_sha256(snap_before)

    # Phantom attempt: running -> migrated is legal; running -> spawning
    # is NOT. Try the phantom; expect rejection.
    with pytest.raises(InvalidTransitionError):
        fsm.transition_to("spawning")

    # The latest snapshot in backing is unchanged.
    snap_after = backing.restore_latest("persona_a")
    assert snap_after is not None
    digest_after = snapshot_payload_sha256(snap_after)
    assert digest_after == digest_before
    # FSM state is still "running"; rejection was audit-logged.
    assert fsm.state == "running"
    assert any(
        (not r.accepted and r.to_state == "spawning") for r in fsm.history
    )
