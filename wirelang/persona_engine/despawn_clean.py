# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Despawn-clean P1..P4 protocol (spec §3.7.1).

Implements the four phase-sequential despawn operations:

- **P1 drain_nats_kv** — stop accepting new state events.
- **P2 revoke_capability_tokens** — emit revoke events for outstanding
  tokens.
- **P3 final_marker_compose** — reduce the marker stack to a terminal
  CompositionVerdict.
- **P4 container_stop** — signal the Quadlet supervisor to stop the
  container.

Each phase is **idempotent on retry** (§3.7.1.2). Any phase failure
raises :class:`DespawnDirtyError`; the engine MUST NOT silently
transition to ``uninstantiated`` on a dirty despawn (§3.7.1.3 last
paragraph).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional, Tuple

from .lifecycle_state_machine import LifecycleStateMachine
from .state_backing import PersonaStateBacking

# ---------------------------------------------------------------------------
# Spec §3.7.1.1 — canonical phase order.
# ---------------------------------------------------------------------------

DESPAWN_CLEAN_PHASE_ORDER: Tuple[str, ...] = ("P1", "P2", "P3", "P4")


class DespawnPhase(str, Enum):
    P1_DRAIN_NATS_KV = "P1_drain_nats_kv"
    P2_REVOKE_CAPABILITY_TOKENS = "P2_revoke_capability_tokens"
    P3_FINAL_MARKER_COMPOSE = "P3_final_marker_compose"
    P4_CONTAINER_STOP = "P4_container_stop"


class DespawnDirtyError(RuntimeError):
    """Raised when any phase fails to reach its terminal status.

    Engine MUST surface this to the operator; do NOT silently
    transition to ``uninstantiated``.
    """

    def __init__(self, phase: DespawnPhase, reason: str) -> None:
        self.phase = phase
        self.reason = reason
        super().__init__(f"DespawnDirtyError(phase={phase.value}, reason={reason})")


# ---------------------------------------------------------------------------
# Result envelope.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DespawnPhaseResult:
    phase: DespawnPhase
    terminal_status: str  # "drained" | "revoked" | "composed" | "stopped"
    elapsed_sec: float
    audit_annotation: str


@dataclass(frozen=True)
class DespawnCleanResult:
    phases: Tuple[DespawnPhaseResult, ...]
    total_elapsed_sec: float
    final_state: str  # expected: "uninstantiated"
    success: bool


# ---------------------------------------------------------------------------
# Driver.
# ---------------------------------------------------------------------------


class DespawnCleanWorkflow:
    """P1..P4 orchestrator."""

    def __init__(
        self,
        state_machine: LifecycleStateMachine,
        state_backing: PersonaStateBacking,
        *,
        nats_drain: Optional[Callable[[str], bool]] = None,
        token_revoke: Optional[Callable[[str], List[str]]] = None,
        marker_compose: Optional[Callable[[str], str]] = None,
        container_stop: Optional[Callable[[str], bool]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.fsm = state_machine
        self.backing = state_backing
        self._nats_drain = nats_drain or _default_nats_drain
        self._token_revoke = token_revoke or _default_token_revoke
        self._marker_compose = marker_compose or _default_marker_compose
        self._container_stop = container_stop or _default_container_stop
        self._clock = clock

    def _p1(self) -> DespawnPhaseResult:
        start = self._clock()
        ok = self._nats_drain(self.fsm.persona_id)
        elapsed = self._clock() - start
        if not ok:
            raise DespawnDirtyError(
                DespawnPhase.P1_DRAIN_NATS_KV,
                "nats_drain returned False",
            )
        return DespawnPhaseResult(
            phase=DespawnPhase.P1_DRAIN_NATS_KV,
            terminal_status="drained",
            elapsed_sec=elapsed,
            audit_annotation="P1_OK",
        )

    def _p2(self) -> DespawnPhaseResult:
        start = self._clock()
        revoked = self._token_revoke(self.fsm.persona_id)
        elapsed = self._clock() - start
        annotation = (
            "P2_NO_TOKENS" if not revoked else f"P2_REVOKED={len(revoked)}"
        )
        return DespawnPhaseResult(
            phase=DespawnPhase.P2_REVOKE_CAPABILITY_TOKENS,
            terminal_status="revoked",
            elapsed_sec=elapsed,
            audit_annotation=annotation,
        )

    def _p3(self) -> DespawnPhaseResult:
        start = self._clock()
        verdict = self._marker_compose(self.fsm.persona_id)
        elapsed = self._clock() - start
        return DespawnPhaseResult(
            phase=DespawnPhase.P3_FINAL_MARKER_COMPOSE,
            terminal_status="composed",
            elapsed_sec=elapsed,
            audit_annotation=f"P3_VERDICT={verdict}",
        )

    def _p4(self) -> DespawnPhaseResult:
        start = self._clock()
        ok = self._container_stop(self.fsm.persona_id)
        elapsed = self._clock() - start
        if not ok:
            raise DespawnDirtyError(
                DespawnPhase.P4_CONTAINER_STOP,
                "container_stop returned False",
            )
        return DespawnPhaseResult(
            phase=DespawnPhase.P4_CONTAINER_STOP,
            terminal_status="stopped",
            elapsed_sec=elapsed,
            audit_annotation="P4_OK",
        )

    def run(self) -> DespawnCleanResult:
        """Run P1 -> P2 -> P3 -> P4 end-to-end."""
        global_start = self._clock()
        # Spec §3.3 valid_transitions: running -> despawning is the
        # entry edge. Despawn from any non-running state is undefined.
        if self.fsm.state == "running":
            self.fsm.transition_to("despawning")
        elif self.fsm.state == "despawning":
            # Idempotent retry path — already despawning.
            pass
        else:
            raise DespawnDirtyError(
                DespawnPhase.P1_DRAIN_NATS_KV,
                f"despawn entry from state {self.fsm.state!r} not allowed",
            )
        phases: List[DespawnPhaseResult] = []
        phases.append(self._p1())
        phases.append(self._p2())
        phases.append(self._p3())
        phases.append(self._p4())

        # Final FSM transition despawning -> uninstantiated.
        self.fsm.transition_to("uninstantiated")
        total = self._clock() - global_start
        return DespawnCleanResult(
            phases=tuple(phases),
            total_elapsed_sec=total,
            final_state=self.fsm.state,
            success=True,
        )


# ---------------------------------------------------------------------------
# Default phase implementations (callable injection points).
# ---------------------------------------------------------------------------


def _default_nats_drain(persona_id: str) -> bool:
    """Default P1: log-only.

    Production binding emits the ``marker-stack-final-compose`` event
    and closes the per-persona put-stream. v0.2.0-pilot defers the
    NATS-write to the Sprint-Pengine-9 axis (parity with state_backing).
    """
    return True


def _default_token_revoke(persona_id: str) -> List[str]:
    """Default P2: returns empty list (no tokens to revoke).

    Production binding enumerates the persona's capability-token set
    from the marker-stack-kv backend. v0.2.0-pilot returns empty for
    the Doppelbetrieb-Shadow phase (no tokens were minted under the
    pilot engine).
    """
    return []


def _default_marker_compose(persona_id: str) -> str:
    """Default P3: returns a stub composition verdict.

    Production binding runs ``reduce_marker_stack`` over the frozen
    event log; v0.2.0-pilot returns ``DESPAWN_FINAL_PILOT`` so the
    audit substrate can distinguish stub-period verdicts from real
    ones.
    """
    return "DESPAWN_FINAL_PILOT"


def _default_container_stop(persona_id: str) -> bool:
    """Default P4: True (engine cannot stop its own container).

    Production binding sends ``systemctl stop`` to the Quadlet
    supervisor; from inside the container this is a logical no-op
    (the supervisor will receive the SIGTERM via the Quadlet
    healthcheck failing). The callable injection lets hermetic tests
    assert P4 was reached.
    """
    return True
