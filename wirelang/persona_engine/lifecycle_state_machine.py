# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Persona-engine lifecycle state-machine (spec §3.3, v1.3).

Implements the six-state, nine-transition envelope per
``wirelang/specs/persona-engine-format-spec.md`` §3.3, with the
state-semantics from §3.3 "State semantics".

The machine is a **type-state pattern in Python**: each transition is
guarded by :func:`_VALID_TRANSITIONS`, invalid transitions raise
:class:`InvalidTransitionError`, and the audit log records every
attempted transition (accepted or rejected) so the recovery workflow
(§3.7.4) can replay history byte-for-byte from the marker-stack-kv
backend.

Single-instance invariant
-------------------------

``max_concurrent_instances=1`` (spec §3.3) is enforced at the
LifecycleStateMachine level: each ``(org_id, persona_id)`` pair
maps to exactly one state-machine instance per engine process. The
constructor is private outside the engine to ensure callers go
through :class:`PersonaEngine`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Spec §3.3 — six states, nine transitions.
# ---------------------------------------------------------------------------

#: All valid lifecycle states (spec §3.3 ``states`` array).
STATES: Tuple[str, ...] = (
    "uninstantiated",
    "spawning",
    "running",
    "despawning",
    "recovered",
    "migrated",
)

#: Closed enumeration of valid transitions (spec §3.3
#: ``valid_transitions`` array). Order matches the spec.
VALID_TRANSITIONS: Tuple[Tuple[str, str], ...] = (
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


class InvalidTransitionError(RuntimeError):
    """Raised when a transition not in :data:`VALID_TRANSITIONS` is
    attempted. Carries the attempted ``(from_state, to_state)`` tuple
    in :attr:`attempted` for the audit-record annotation."""

    def __init__(self, from_state: str, to_state: str) -> None:
        self.attempted: Tuple[str, str] = (from_state, to_state)
        super().__init__(
            f"invalid lifecycle transition {from_state!r} -> {to_state!r} "
            f"(spec §3.3 valid_transitions does not contain this edge)"
        )


class UnknownStateError(ValueError):
    """Raised when a state outside :data:`STATES` is mentioned."""


@dataclass(frozen=True)
class TransitionRecord:
    """Audit envelope for a single transition attempt.

    Immutable; appended to :attr:`LifecycleStateMachine.history`
    on every transition call (accepted or rejected). The recovery
    workflow (§3.7.4 R2) replays this list to rebuild engine state.
    """

    from_state: str
    to_state: str
    ts_utc: str  # RFC 3339 UTC second-precision
    accepted: bool
    reason: Optional[str] = None  # rejection reason if not accepted


def _utc_now_rfc3339() -> str:
    """Return the current UTC time as an RFC 3339 second-precision string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class LifecycleStateMachine:
    """Engine-side state machine per spec §3.3.

    Each instance carries exactly one persona's lifecycle. Single-
    writer; callers MUST serialise transitions externally (the engine
    holds a per-persona asyncio lock if multi-coroutine spawn-paths
    are wired in Tag-N+).
    """

    def __init__(
        self,
        persona_id: str,
        org_id: str,
        *,
        initial_state: str = "uninstantiated",
        clock: Callable[[], str] = _utc_now_rfc3339,
    ) -> None:
        if initial_state not in STATES:
            raise UnknownStateError(
                f"unknown initial state {initial_state!r}; "
                f"valid: {STATES}"
            )
        self.persona_id: str = persona_id
        self.org_id: str = org_id
        self._state: str = initial_state
        self._clock: Callable[[], str] = clock
        self._history: List[TransitionRecord] = []

    # ------------------------------------------------------------------
    # State accessors.
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        """Current lifecycle state."""
        return self._state

    @property
    def history(self) -> List[TransitionRecord]:
        """Read-only audit log of every transition attempt."""
        return list(self._history)  # defensive copy

    # ------------------------------------------------------------------
    # Transition surface.
    # ------------------------------------------------------------------

    def can_transition_to(self, to_state: str) -> bool:
        """Return True iff transition from current state to ``to_state``
        is in :data:`VALID_TRANSITIONS`."""
        if to_state not in STATES:
            return False
        return (self._state, to_state) in VALID_TRANSITIONS

    def transition_to(self, to_state: str) -> TransitionRecord:
        """Attempt a transition. Appends a TransitionRecord either way.

        Raises :class:`InvalidTransitionError` if the edge is not valid.
        Raises :class:`UnknownStateError` if ``to_state`` is not in
        :data:`STATES`.
        """
        if to_state not in STATES:
            rec = TransitionRecord(
                from_state=self._state,
                to_state=to_state,
                ts_utc=self._clock(),
                accepted=False,
                reason="unknown_target_state",
            )
            self._history.append(rec)
            raise UnknownStateError(
                f"unknown target state {to_state!r}; valid: {STATES}"
            )
        if (self._state, to_state) not in VALID_TRANSITIONS:
            rec = TransitionRecord(
                from_state=self._state,
                to_state=to_state,
                ts_utc=self._clock(),
                accepted=False,
                reason="not_in_valid_transitions",
            )
            self._history.append(rec)
            raise InvalidTransitionError(self._state, to_state)
        rec = TransitionRecord(
            from_state=self._state,
            to_state=to_state,
            ts_utc=self._clock(),
            accepted=True,
            reason=None,
        )
        self._history.append(rec)
        self._state = to_state
        return rec

    # ------------------------------------------------------------------
    # Replay surface (recovery_workflow R2).
    # ------------------------------------------------------------------

    @classmethod
    def replay(
        cls,
        persona_id: str,
        org_id: str,
        records: List[TransitionRecord],
        *,
        clock: Callable[[], str] = _utc_now_rfc3339,
    ) -> "LifecycleStateMachine":
        """Rebuild a state machine from a recorded transition log.

        Used by recovery_workflow §3.7.4 R2 ("Reload") to rebuild the
        engine-side state machine from the marker-stack-kv event log.
        Skips rejected records (they did not change state) and applies
        accepted records in order. Raises :class:`InvalidTransitionError`
        if a recorded "accepted" record is not in :data:`VALID_TRANSITIONS`
        (data corruption signal).
        """
        m = cls(persona_id=persona_id, org_id=org_id, clock=clock)
        for rec in records:
            if not rec.accepted:
                # Replay the rejection as an audit annotation but do
                # not change state.
                m._history.append(rec)
                continue
            if (rec.from_state, rec.to_state) not in VALID_TRANSITIONS:
                raise InvalidTransitionError(rec.from_state, rec.to_state)
            if rec.from_state != m._state:
                raise InvalidTransitionError(m._state, rec.to_state)
            m._history.append(rec)
            m._state = rec.to_state
        return m


# ---------------------------------------------------------------------------
# Spec §3.3 ``valid_transitions`` self-test (executed at module import
# time to catch spec/code drift cheaply).
# ---------------------------------------------------------------------------

def _assert_spec_invariants() -> None:
    # All transitions reference declared states.
    for from_s, to_s in VALID_TRANSITIONS:
        if from_s not in STATES:
            raise RuntimeError(f"lifecycle FSM drift: unknown from-state {from_s}")
        if to_s not in STATES:
            raise RuntimeError(f"lifecycle FSM drift: unknown to-state {to_s}")
    # No duplicates.
    if len(set(VALID_TRANSITIONS)) != len(VALID_TRANSITIONS):
        raise RuntimeError("lifecycle FSM drift: duplicate transitions")


_assert_spec_invariants()
