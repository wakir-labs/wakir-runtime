# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Scheduled R1..R4 recovery drills (Sprint-Pengine-9 OI-PEFR-4).

Spec §3.7.4 declares the R1..R4 recovery workflow, and §3.7.2.2
invariant 4 enforces the 30-second end-to-end budget. The hermetic
test suite already covers per-phase semantics + budget enforcement
(``test_recovery_workflow.py``), but the workflow has never run on
a schedule — operator-Hand has been the only way to trigger it.

Sprint-Pengine-9 OI-PEFR-4 adds :class:`DrillScheduler`:

  - Periodic trigger (timer-thread, default 1 week interval).
  - Per-run :class:`RecoveryWorkflow.run()` invocation in
    ``StateCorruption`` mode (safe trigger; no real state mutation
    expected since the engine state is intact).
  - Audit annotations on every drill start (``drill-run-begin``) and
    every drill finish (``drill-run-completed`` / ``drill-run-failed``).
  - Idempotent: a re-entered scheduler picks up the next slot, never
    runs two drills concurrently.

Posture
-------

The scheduler is **thread-based** for the sync engine and offers an
``asyncio_task()`` helper for the async engine
(:class:`wirelang.persona_engine.engine_async.AsyncPersonaEngine`).
Both surfaces share the same drill execution path so the
Doppelbetrieb-Vergleichs-Clock measures the same workflow regardless
of which engine variant runs the drill.

The drill is a **dry-run**: the recovery workflow runs end-to-end
against the engine's live FSM + state-backing, but the trigger
classification is ``StateCorruption`` (not a real failure mode for
a healthy engine). The audit trail records this so the
External-Verifier can distinguish drill-runs from real-failure
recovery in the trace stream.

Test posture
------------

Hermetic tests inject a ``clock`` callable (returning monotonic
floats) and a ``sleep`` callable (returning None) so we can drive
the scheduler through N intervals in zero real-world seconds. The
production path uses ``time.monotonic`` + ``time.sleep`` (or
``asyncio.sleep`` for the async path).
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional, TextIO

from .lifecycle_state_machine import LifecycleStateMachine
from .recovery_workflow import (
    PHASE_SOFT_CAPS_SEC,
    RECOVERY_BUDGET_SECONDS,
    RecoveryError,
    RecoveryResult,
    RecoveryTrigger,
    RecoveryWorkflow,
)
from .state_backing import PersonaStateBacking

# ---------------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------------

#: Default drill interval — weekly (Spec §3.7.4.4 operational guidance).
DEFAULT_DRILL_INTERVAL_SEC: int = 7 * 24 * 3600

#: Default drill trigger — ``StateCorruption`` is the safest dry-run
#: classification for a healthy engine: it exercises the R2 reload
#: path but the snapshot is intact, so the engine returns to running
#: with no real state mutation.
DEFAULT_DRILL_TRIGGER: RecoveryTrigger = RecoveryTrigger.STATE_CORRUPTION

#: Maximum number of consecutive drill failures before the scheduler
#: stops itself. The operator must manually re-arm via the CLI.
DEFAULT_FAILURE_CIRCUIT_BREAKER: int = 3


class DrillStatus(str, Enum):
    """Closed enumeration of per-drill terminal status."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED_FSM_NOT_READY = "skipped_fsm_not_ready"


@dataclass(frozen=True)
class DrillRunRecord:
    """Audit envelope for a single drill execution."""

    started_at_utc: str
    finished_at_utc: str
    elapsed_sec: float
    status: DrillStatus
    trigger: RecoveryTrigger
    recovery_result: Optional[RecoveryResult] = None
    error_detail: Optional[str] = None


def _utc_now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Scheduler.
# ---------------------------------------------------------------------------


class DrillScheduler:
    """Cron-style scheduler for R1..R4 drills.

    Hermetic-test posture: pass ``clock`` (returns monotonic float)
    and ``sleep`` (async-compat) overrides; the scheduler will use
    them instead of ``time.monotonic`` / ``time.sleep``.
    """

    def __init__(
        self,
        state_machine: LifecycleStateMachine,
        state_backing: PersonaStateBacking,
        *,
        interval_sec: int = DEFAULT_DRILL_INTERVAL_SEC,
        trigger: RecoveryTrigger = DEFAULT_DRILL_TRIGGER,
        failure_circuit_breaker: int = DEFAULT_FAILURE_CIRCUIT_BREAKER,
        recovery_workflow: Optional[RecoveryWorkflow] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Optional[Callable[[float], Any]] = None,
        audit_sink: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.fsm = state_machine
        self.backing = state_backing
        self.interval_sec = max(1, int(interval_sec))
        self.trigger = trigger
        self.circuit_breaker = max(1, int(failure_circuit_breaker))
        self._recovery = recovery_workflow or RecoveryWorkflow(
            state_machine=state_machine,
            state_backing=state_backing,
        )
        self._clock = clock
        self._sleep = sleep if sleep is not None else time.sleep
        self._audit_sink = audit_sink or (lambda _p: None)
        self._records: List[DrillRunRecord] = []
        self._consecutive_failures: int = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Read accessors.
    # ------------------------------------------------------------------

    @property
    def records(self) -> List[DrillRunRecord]:
        """Read-only audit log of every drill run."""
        return list(self._records)

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    # ------------------------------------------------------------------
    # Single-drill execution.
    # ------------------------------------------------------------------

    def run_one_drill(self) -> DrillRunRecord:
        """Execute exactly one drill (R1..R4) end-to-end.

        Pre-condition: FSM must be in ``running`` state (engine is up).
        If the FSM is not ready the drill is skipped with status
        :data:`DrillStatus.SKIPPED_FSM_NOT_READY`.

        The drill is idempotent on retry: re-running over a healthy
        engine returns the same byte-stable RecoveryResult.
        """
        started_at = _utc_now_rfc3339()
        start_mono = self._clock()
        self._audit_sink({
            "level": "INFO",
            "msg": "drill-run-begin",
            "trigger": self.trigger.value,
            "started_at_utc": started_at,
        })
        if self.fsm.state != "running":
            elapsed = self._clock() - start_mono
            record = DrillRunRecord(
                started_at_utc=started_at,
                finished_at_utc=_utc_now_rfc3339(),
                elapsed_sec=elapsed,
                status=DrillStatus.SKIPPED_FSM_NOT_READY,
                trigger=self.trigger,
                error_detail=f"fsm.state={self.fsm.state!r}, expected running",
            )
            self._records.append(record)
            self._audit_sink({
                "level": "WARN",
                "msg": "drill-run-skipped",
                "reason": "fsm-not-running",
                "fsm_state": self.fsm.state,
            })
            return record

        # Run R1..R4. Trigger flags map: STATE_CORRUPTION -> state_corruption=True.
        kwargs = {
            "crash_detected": self.trigger == RecoveryTrigger.CRASH_DETECTED,
            "despawn_mid_operation": self.trigger == RecoveryTrigger.DESPAWN_MID_OPERATION,
            "state_corruption": self.trigger == RecoveryTrigger.STATE_CORRUPTION,
        }
        try:
            result = self._recovery.run(**kwargs)
            elapsed = self._clock() - start_mono
            record = DrillRunRecord(
                started_at_utc=started_at,
                finished_at_utc=_utc_now_rfc3339(),
                elapsed_sec=elapsed,
                status=DrillStatus.SUCCESS,
                trigger=self.trigger,
                recovery_result=result,
            )
            self._records.append(record)
            self._consecutive_failures = 0
            self._audit_sink({
                "level": "INFO",
                "msg": "drill-run-completed",
                "trigger": self.trigger.value,
                "elapsed_sec": elapsed,
                "phases": [p.phase for p in result.phases],
                "final_state": result.final_state,
            })
            return record
        except RecoveryError as exc:
            elapsed = self._clock() - start_mono
            record = DrillRunRecord(
                started_at_utc=started_at,
                finished_at_utc=_utc_now_rfc3339(),
                elapsed_sec=elapsed,
                status=DrillStatus.FAILED,
                trigger=self.trigger,
                error_detail=f"{exc.mode.value}: {exc}",
            )
            self._records.append(record)
            self._consecutive_failures += 1
            self._audit_sink({
                "level": "ERROR",
                "msg": "drill-run-failed",
                "trigger": self.trigger.value,
                "elapsed_sec": elapsed,
                "failure_mode": exc.mode.value,
                "detail": str(exc),
                "consecutive_failures": self._consecutive_failures,
            })
            return record

    # ------------------------------------------------------------------
    # Thread-based scheduler.
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Spawn the scheduler thread. Idempotent: a second call is a
        no-op while the thread is alive."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._thread_loop,
            name="wakir-persona-engine-drill-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_sec: float = 5.0) -> None:
        """Signal the scheduler to halt; wait for the thread to join."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_sec)
            self._thread = None

    def _thread_loop(self) -> None:
        while not self._stop.is_set():
            if self._consecutive_failures >= self.circuit_breaker:
                self._audit_sink({
                    "level": "ERROR",
                    "msg": "drill-scheduler-circuit-broken",
                    "consecutive_failures": self._consecutive_failures,
                    "circuit_breaker": self.circuit_breaker,
                })
                return
            self.run_one_drill()
            # Responsive sleep — wake every 1s to check stop flag.
            slept = 0
            while slept < self.interval_sec and not self._stop.is_set():
                step = min(1, self.interval_sec - slept)
                self._sleep(step)
                slept += step

    # ------------------------------------------------------------------
    # Async-engine helper.
    # ------------------------------------------------------------------

    async def asyncio_task(self) -> None:
        """Run the scheduler as an asyncio coroutine.

        Used by :class:`AsyncPersonaEngine` to drive the scheduler on
        the engine's existing event loop instead of a private thread.
        Stops cleanly when the coroutine is cancelled.
        """
        try:
            while True:
                if self._consecutive_failures >= self.circuit_breaker:
                    self._audit_sink({
                        "level": "ERROR",
                        "msg": "drill-scheduler-circuit-broken-async",
                        "consecutive_failures": self._consecutive_failures,
                        "circuit_breaker": self.circuit_breaker,
                    })
                    return
                self.run_one_drill()
                await asyncio.sleep(self.interval_sec)
        except asyncio.CancelledError:
            return
