# SPDX-License-Identifier: BUSL-1.1
"""Sprint-Pengine-9 OI-PEFR-4 tests: scheduled R1..R4 drills.

DrillScheduler invocation paths:

  - Single drill against a healthy engine (SUCCESS).
  - Single drill against a not-running FSM (SKIPPED_FSM_NOT_READY).
  - Single drill against a backing that always raises (FAILED).
  - Circuit-breaker engages after N consecutive failures.
  - Audit-sink receives drill-run-begin / drill-run-completed pairs.
  - asyncio task path cancels cleanly.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, List, Optional

import pytest

from wirelang.persona_engine.drill_scheduler import (
    DEFAULT_DRILL_INTERVAL_SEC,
    DEFAULT_DRILL_TRIGGER,
    DEFAULT_FAILURE_CIRCUIT_BREAKER,
    DrillRunRecord,
    DrillScheduler,
    DrillStatus,
)
from wirelang.persona_engine.lifecycle_state_machine import (
    LifecycleStateMachine,
)
from wirelang.persona_engine.recovery_workflow import (
    PHASE_SOFT_CAPS_SEC,
    RECOVERY_BUDGET_SECONDS,
    PhaseResult,
    RecoveryError,
    RecoveryFailureMode,
    RecoveryResult,
    RecoveryTrigger,
    RecoveryWorkflow,
)
from wirelang.persona_engine.state_backing import (
    InMemoryPersonaStateBacking,
    PersonaStateBackingError,
)


class _StubRecoveryWorkflow(RecoveryWorkflow):
    """Drill-test stub: always-succeeds recovery (no real R3 probe).

    The hermetic test environment lacks a SPIRE socket, so the real
    R3 phase would always fail. The stub returns a synthetic
    RecoveryResult so DrillScheduler can be exercised end-to-end.
    """

    def run(self, **kwargs) -> RecoveryResult:
        trigger = (
            kwargs.get("force_trigger")
            or (
                RecoveryTrigger.CRASH_DETECTED
                if kwargs.get("crash_detected")
                else (
                    RecoveryTrigger.DESPAWN_MID_OPERATION
                    if kwargs.get("despawn_mid_operation")
                    else RecoveryTrigger.STATE_CORRUPTION
                )
            )
        )
        phases = tuple(
            PhaseResult(
                phase=p,
                terminal_status=status,
                elapsed_sec=0.001,
                soft_cap_exceeded=False,
                audit_annotation="stub",
            )
            for p, status in (
                ("R1", "detected"),
                ("R2", "reloaded"),
                ("R3", "re_registered"),
                ("R4", "resumed"),
            )
        )
        return RecoveryResult(
            trigger=trigger,
            phases=phases,
            total_elapsed_sec=0.004,
            final_state=self.fsm.state,
            success=True,
        )


def _make_healthy_fsm() -> LifecycleStateMachine:
    fsm = LifecycleStateMachine(persona_id="tomas", org_id="acme")
    fsm.transition_to("spawning")
    fsm.transition_to("running")
    return fsm


def _make_uninstantiated_fsm() -> LifecycleStateMachine:
    return LifecycleStateMachine(persona_id="tomas", org_id="acme")


# -------------------- constants --------------------


def test_default_interval_is_weekly():
    assert DEFAULT_DRILL_INTERVAL_SEC == 7 * 24 * 3600


def test_default_trigger_is_state_corruption():
    assert DEFAULT_DRILL_TRIGGER == RecoveryTrigger.STATE_CORRUPTION


def test_default_circuit_breaker_three():
    assert DEFAULT_FAILURE_CIRCUIT_BREAKER == 3


# -------------------- single-drill execution --------------------


def _stub_sched(fsm: LifecycleStateMachine, **kwargs) -> DrillScheduler:
    backing = InMemoryPersonaStateBacking()
    return DrillScheduler(
        state_machine=fsm,
        state_backing=backing,
        recovery_workflow=_StubRecoveryWorkflow(
            state_machine=fsm, state_backing=backing,
        ),
        **kwargs,
    )


def test_run_one_drill_success_against_healthy_engine():
    fsm = _make_healthy_fsm()
    captured_audit: List[dict] = []
    sched = _stub_sched(fsm, audit_sink=captured_audit.append)
    record = sched.run_one_drill()
    assert record.status == DrillStatus.SUCCESS
    assert record.trigger == RecoveryTrigger.STATE_CORRUPTION
    assert record.recovery_result is not None
    assert record.recovery_result.final_state == "running"


def test_run_one_drill_skipped_when_fsm_not_running():
    fsm = _make_uninstantiated_fsm()
    backing = InMemoryPersonaStateBacking()
    captured: List[dict] = []

    sched = DrillScheduler(
        state_machine=fsm,
        state_backing=backing,
        audit_sink=captured.append,
    )
    record = sched.run_one_drill()
    assert record.status == DrillStatus.SKIPPED_FSM_NOT_READY
    assert record.recovery_result is None


def test_run_one_drill_audit_begin_and_completed_emitted():
    fsm = _make_healthy_fsm()
    captured: List[dict] = []
    sched = _stub_sched(fsm, audit_sink=captured.append)
    sched.run_one_drill()
    msgs = [c["msg"] for c in captured]
    assert "drill-run-begin" in msgs
    assert "drill-run-completed" in msgs


def test_run_one_drill_audit_skipped_when_fsm_not_running():
    fsm = _make_uninstantiated_fsm()
    backing = InMemoryPersonaStateBacking()
    captured: List[dict] = []

    sched = DrillScheduler(
        state_machine=fsm,
        state_backing=backing,
        audit_sink=captured.append,
    )
    sched.run_one_drill()
    msgs = [c["msg"] for c in captured]
    assert "drill-run-skipped" in msgs


def test_run_one_drill_records_consecutive_failures():
    fsm = _make_healthy_fsm()
    backing = InMemoryPersonaStateBacking()

    class _AlwaysFailRecovery(RecoveryWorkflow):
        def run(self, **kwargs) -> Any:
            raise RecoveryError(
                RecoveryFailureMode.RESUME_ERROR, "test-injected"
            )

    failing = _AlwaysFailRecovery(state_machine=fsm, state_backing=backing)
    sched = DrillScheduler(
        state_machine=fsm,
        state_backing=backing,
        recovery_workflow=failing,
    )
    rec = sched.run_one_drill()
    assert rec.status == DrillStatus.FAILED
    assert sched.consecutive_failures == 1
    sched.run_one_drill()
    assert sched.consecutive_failures == 2


def test_run_one_drill_failure_resets_on_next_success():
    fsm = _make_healthy_fsm()
    backing = InMemoryPersonaStateBacking()

    fail_first = {"flag": True}

    class _OnceFailRecovery(RecoveryWorkflow):
        def run(self, **kwargs):
            if fail_first["flag"]:
                fail_first["flag"] = False
                raise RecoveryError(
                    RecoveryFailureMode.RESUME_ERROR, "test-injected"
                )
            return super().run(**kwargs)

    rec_wf = _OnceFailRecovery(state_machine=fsm, state_backing=backing)
    sched = DrillScheduler(
        state_machine=fsm, state_backing=backing, recovery_workflow=rec_wf,
    )
    r1 = sched.run_one_drill()
    assert r1.status == DrillStatus.FAILED
    assert sched.consecutive_failures == 1
    r2 = sched.run_one_drill()
    assert r2.status == DrillStatus.SUCCESS
    assert sched.consecutive_failures == 0


def test_run_one_drill_records_appended_in_order():
    fsm = _make_healthy_fsm()
    sched = _stub_sched(fsm)
    r1 = sched.run_one_drill()
    r2 = sched.run_one_drill()
    r3 = sched.run_one_drill()
    records = sched.records
    assert records == [r1, r2, r3]


def test_run_one_drill_elapsed_sec_positive():
    fsm = _make_healthy_fsm()
    sched = _stub_sched(fsm)
    rec = sched.run_one_drill()
    assert rec.elapsed_sec >= 0.0


def test_run_one_drill_trigger_alt_crash_detected():
    fsm = _make_healthy_fsm()
    sched = _stub_sched(fsm, trigger=RecoveryTrigger.CRASH_DETECTED)
    rec = sched.run_one_drill()
    assert rec.trigger == RecoveryTrigger.CRASH_DETECTED
    assert rec.status == DrillStatus.SUCCESS


def test_run_one_drill_trigger_despawn_mid_operation():
    fsm = _make_healthy_fsm()
    sched = _stub_sched(fsm, trigger=RecoveryTrigger.DESPAWN_MID_OPERATION)
    rec = sched.run_one_drill()
    assert rec.trigger == RecoveryTrigger.DESPAWN_MID_OPERATION


# -------------------- thread-based scheduler --------------------


def test_thread_scheduler_starts_and_stops_cleanly():
    fsm = _make_healthy_fsm()
    backing = InMemoryPersonaStateBacking()
    sleep_calls: List[float] = []

    def fake_sleep(t: float) -> None:
        sleep_calls.append(t)

    sched = DrillScheduler(
        state_machine=fsm,
        state_backing=backing,
        interval_sec=1,
        sleep=fake_sleep,
    )
    sched.start()
    # Idempotent start: second call is a no-op.
    sched.start()
    # Stop immediately (the thread may have done 0..N drills).
    sched.stop()


def test_thread_scheduler_circuit_breaker_engages():
    fsm = _make_healthy_fsm()
    backing = InMemoryPersonaStateBacking()

    class _AlwaysFailRecovery(RecoveryWorkflow):
        def run(self, **kwargs):
            raise RecoveryError(
                RecoveryFailureMode.RESUME_ERROR, "test-injected"
            )

    captured: List[dict] = []
    sched = DrillScheduler(
        state_machine=fsm,
        state_backing=backing,
        interval_sec=1,
        sleep=lambda _t: None,
        recovery_workflow=_AlwaysFailRecovery(
            state_machine=fsm, state_backing=backing,
        ),
        failure_circuit_breaker=2,
        audit_sink=captured.append,
    )
    sched.start()
    # Give the thread time to hit the circuit breaker.
    import time as _t

    deadline = _t.monotonic() + 2.0
    while _t.monotonic() < deadline:
        if any(c.get("msg") == "drill-scheduler-circuit-broken" for c in captured):
            break
        _t.sleep(0.05)
    sched.stop()
    msgs = [c.get("msg") for c in captured]
    assert "drill-scheduler-circuit-broken" in msgs


# -------------------- asyncio task path --------------------


def test_asyncio_task_runs_drill_then_cancellable():
    fsm = _make_healthy_fsm()
    backing = InMemoryPersonaStateBacking()
    sched = DrillScheduler(
        state_machine=fsm, state_backing=backing, interval_sec=1,
    )

    async def go():
        task = asyncio.create_task(sched.asyncio_task())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(go())
    assert len(sched.records) >= 1


def test_asyncio_task_circuit_breaker_engages():
    fsm = _make_healthy_fsm()
    backing = InMemoryPersonaStateBacking()

    class _AlwaysFailRecovery(RecoveryWorkflow):
        def run(self, **kwargs):
            raise RecoveryError(
                RecoveryFailureMode.RESUME_ERROR, "test-injected"
            )

    captured: List[dict] = []
    sched = DrillScheduler(
        state_machine=fsm,
        state_backing=backing,
        interval_sec=1,
        recovery_workflow=_AlwaysFailRecovery(
            state_machine=fsm, state_backing=backing,
        ),
        failure_circuit_breaker=2,
        audit_sink=captured.append,
    )

    async def go():
        await sched.asyncio_task()

    asyncio.run(go())
    msgs = [c.get("msg") for c in captured]
    assert "drill-scheduler-circuit-broken-async" in msgs


def test_record_dataclass_fields():
    rec = DrillRunRecord(
        started_at_utc="2026-05-15T00:00:00Z",
        finished_at_utc="2026-05-15T00:00:05Z",
        elapsed_sec=5.0,
        status=DrillStatus.SUCCESS,
        trigger=RecoveryTrigger.STATE_CORRUPTION,
    )
    assert rec.elapsed_sec == 5.0
    assert rec.recovery_result is None
    assert rec.error_detail is None


def test_drill_status_enum_values():
    assert DrillStatus.SUCCESS.value == "success"
    assert DrillStatus.FAILED.value == "failed"
    assert DrillStatus.SKIPPED_FSM_NOT_READY.value == "skipped_fsm_not_ready"


def test_interval_sec_floor_one():
    """Passing interval_sec=0 must be coerced to 1 (min)."""
    fsm = _make_healthy_fsm()
    backing = InMemoryPersonaStateBacking()
    sched = DrillScheduler(
        state_machine=fsm,
        state_backing=backing,
        interval_sec=0,
    )
    assert sched.interval_sec == 1


def test_circuit_breaker_floor_one():
    fsm = _make_healthy_fsm()
    backing = InMemoryPersonaStateBacking()
    sched = DrillScheduler(
        state_machine=fsm,
        state_backing=backing,
        failure_circuit_breaker=0,
    )
    assert sched.circuit_breaker == 1
