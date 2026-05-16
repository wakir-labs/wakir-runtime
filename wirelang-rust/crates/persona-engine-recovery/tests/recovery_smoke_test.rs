// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors

//! Smoke-tests for the persona-engine R1..R4 Recovery-Workflow
//! Rust substrate.
//!
//! These tests use the [`RecoveryHooks`] injection point as the
//! external-dependency mock — no live container supervisor, no live
//! SPIFFE workload-API, no live state-backing. The tests assert the
//! substrate contract:
//!
//! 1. R1 individual trigger — `fence_active` (CrashDetected).
//! 2. R2 individual trigger — `subscribe_failure` (DespawnMidOperation).
//! 3. R3 individual trigger — `pin_drift` (StateCorruption).
//! 4. R4 trigger — `force_trigger` override path.
//! 5. Budget-timeout-handling — a slow hook trips the deadline.
//! 6. Trigger-ambiguity — two flags asserted yields the failure mode.
//! 7. Cross-lang-output-parity-pin — JSON audit-record key set and
//!    enum wire-strings match the Python reference.
//! 8. Phase-order invariant — the four phases run in R1..R4 order
//!    and the `RECOVERY_WORKFLOW_PHASE_ORDER` constant matches.
//! 9. Hook-failure path — a failing `svid_refetch` aborts at R3 and
//!    the operator-escalation hook fires exactly once.

use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;
use std::time::Duration;

use persona_engine_recovery::{
    audit_record_json, classify_trigger, escalate_to_operator, phase_soft_cap_sec,
    run_recovery_drill, run_recovery_drill_with_hooks, utc_now_rfc3339, HookFuture,
    PhaseResult, RecoveryContext, RecoveryError, RecoveryFailureMode, RecoveryHooks,
    RecoveryTrigger, RECOVERY_BUDGET_SECONDS, RECOVERY_WORKFLOW_PHASE_ORDER,
};

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

fn fresh_context() -> RecoveryContext {
    RecoveryContext {
        persona_id: "selin".to_owned(),
        org_id: "wakir-labs".to_owned(),
        ..Default::default()
    }
}

fn slow_hook(
    millis: u64,
) -> Arc<dyn for<'a> Fn(&'a RecoveryContext) -> HookFuture<'a> + Send + Sync> {
    Arc::new(move |_ctx: &RecoveryContext| -> HookFuture<'_> {
        let d = Duration::from_millis(millis);
        Box::pin(async move {
            tokio::time::sleep(d).await;
            Ok(())
        })
    })
}

fn failing_hook(
    mode: RecoveryFailureMode,
    detail: &'static str,
) -> Arc<dyn for<'a> Fn(&'a RecoveryContext) -> HookFuture<'a> + Send + Sync> {
    Arc::new(move |_ctx: &RecoveryContext| -> HookFuture<'_> {
        Box::pin(async move { Err(RecoveryError::new(mode, detail.to_owned())) })
    })
}

fn counting_escalation_hook(
    counter: Arc<AtomicU32>,
) -> Arc<
    dyn for<'a> Fn(&'a RecoveryContext, &'a RecoveryError) -> HookFuture<'a>
        + Send
        + Sync,
> {
    Arc::new(move |_ctx: &RecoveryContext, _err: &RecoveryError| -> HookFuture<'_> {
        let c = counter.clone();
        Box::pin(async move {
            c.fetch_add(1, Ordering::SeqCst);
            Ok(())
        })
    })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[tokio::test]
async fn t1_r1_trigger_fence_active_classifies_as_crash_detected() {
    // Sprint-Auftrag flag `fence_active` maps onto the Python
    // CrashDetected trigger. The drill runs end-to-end with the
    // default no-op hooks and the four phases must all complete.
    let mut ctx = fresh_context();
    ctx.fence_active = true;

    let outcome = run_recovery_drill(ctx, 0).await;
    assert!(outcome.success, "drill should succeed with no-op hooks");
    assert_eq!(outcome.trigger, RecoveryTrigger::CrashDetected);
    assert_eq!(outcome.phases.len(), 4);
    assert_eq!(outcome.final_state, "running");
    assert!(
        outcome.total_elapsed_sec < RECOVERY_BUDGET_SECONDS as f64,
        "elapsed {} must stay below 30s budget",
        outcome.total_elapsed_sec
    );
}

#[tokio::test]
async fn t2_r2_trigger_subscribe_failure_classifies_as_despawn_mid_operation() {
    // Sprint-Auftrag flag `subscribe_failure` maps onto
    // DespawnMidOperation. R2 phase annotation must be the
    // snapshot-restored audit string.
    let mut ctx = fresh_context();
    ctx.subscribe_failure = true;

    let outcome = run_recovery_drill(ctx, 0).await;
    assert!(outcome.success);
    assert_eq!(outcome.trigger, RecoveryTrigger::DespawnMidOperation);
    let r2: &PhaseResult = outcome
        .phases
        .iter()
        .find(|p| p.phase == "R2")
        .expect("R2 phase present");
    assert_eq!(r2.terminal_status, "reloaded");
    assert_eq!(r2.audit_annotation, "snapshot-restored");
}

#[tokio::test]
async fn t3_r3_trigger_pin_drift_classifies_as_state_corruption() {
    // Sprint-Auftrag flag `pin_drift` maps onto StateCorruption.
    // R3 audit annotation must contain the SPIFFE ID for the persona.
    let mut ctx = fresh_context();
    ctx.pin_drift = true;

    let outcome = run_recovery_drill(ctx, 0).await;
    assert!(outcome.success);
    assert_eq!(outcome.trigger, RecoveryTrigger::StateCorruption);
    let r3 = outcome
        .phases
        .iter()
        .find(|p| p.phase == "R3")
        .expect("R3 phase present");
    assert!(
        r3.audit_annotation.starts_with("recovery_svid_refreshed=spiffe://"),
        "R3 annotation must start with the spiffe-id prefix, got {:?}",
        r3.audit_annotation
    );
    assert!(r3.audit_annotation.contains("/persona/selin"));
}

#[tokio::test]
async fn t4_force_trigger_override_drives_state_corruption() {
    // The `force_trigger` override mirrors the Python
    // `--force-trigger=<label>` OI-PEF-10 path. The drill must use
    // the forced value even when no flag is asserted.
    let mut ctx = fresh_context();
    ctx.force_trigger = Some(RecoveryTrigger::StateCorruption);

    let outcome = run_recovery_drill(ctx, 0).await;
    assert!(outcome.success);
    assert_eq!(outcome.trigger, RecoveryTrigger::StateCorruption);
    // R1 annotation must reflect the forced trigger label.
    let r1 = outcome
        .phases
        .iter()
        .find(|p| p.phase == "R1")
        .expect("R1 phase present");
    assert_eq!(
        r1.audit_annotation,
        "recovery_trigger_classified=StateCorruption"
    );
}

#[tokio::test]
async fn t5_budget_timeout_handling_trips_deadline() {
    // A 200-ms hook with a 0-second budget (i.e. default 30s) should
    // not trip. A 200-ms hook with a 1-second budget should also not
    // trip. But when we pile slow hooks together against a tight
    // budget, the tokio-timeout fires and we get a failed outcome.
    let mut ctx = fresh_context();
    ctx.fence_active = true;

    let hooks = RecoveryHooks {
        svid_refetch: slow_hook(800),
        nats_resubscribe: slow_hook(800),
        fsm_restart: slow_hook(800),
        operator_escalation: RecoveryHooks::default().operator_escalation,
    };

    // 1-second budget vs. ~2.4-seconds-of-sleep => budget exceeded.
    let outcome = run_recovery_drill_with_hooks(ctx, 1, hooks).await;
    assert!(!outcome.success, "drill should fail when budget exceeded");
    assert!(
        outcome.final_state.starts_with("failed:RecoveryBudgetExceededError"),
        "final_state should mark BudgetExceeded, got {:?}",
        outcome.final_state
    );
}

#[tokio::test]
async fn t6_trigger_ambiguity_with_two_flags_yields_failure_mode() {
    // Python `classify_trigger` raises TriggerAmbiguous when more
    // than one flag is asserted. The Rust substrate must surface the
    // same failure mode at the `classify_trigger` boundary.
    let mut ctx = fresh_context();
    ctx.fence_active = true;
    ctx.pin_drift = true;

    let err = classify_trigger(&ctx).expect_err("ambiguous flags must fail");
    assert_eq!(err.mode, RecoveryFailureMode::TriggerAmbiguous);
    assert!(
        err.detail.contains("multiple triggers asserted"),
        "ambiguity detail must mention multiple-triggers, got {:?}",
        err.detail
    );
    // Zero flags also fails the same way.
    let zero = RecoveryContext::default();
    let err2 = classify_trigger(&zero).expect_err("zero flags must fail");
    assert_eq!(err2.mode, RecoveryFailureMode::TriggerAmbiguous);
    assert!(err2.detail.contains("no trigger flag asserted"));
}

#[tokio::test]
async fn t7_cross_lang_output_parity_pin_to_python_recovery_workflow() {
    // Parity-snapshot: enum wire-strings, phase-soft-caps, the
    // RECOVERY_BUDGET_SECONDS constant, and the JSON audit-record
    // key set must not drift from the Python reference without an
    // explicit cross-review checkpoint.
    assert_eq!(RECOVERY_BUDGET_SECONDS, 30);
    assert_eq!(RECOVERY_WORKFLOW_PHASE_ORDER, ["R1", "R2", "R3", "R4"]);

    // Soft caps mirror Python `PHASE_SOFT_CAPS_SEC`.
    assert_eq!(phase_soft_cap_sec("R1"), Some(1));
    assert_eq!(phase_soft_cap_sec("R2"), Some(15));
    assert_eq!(phase_soft_cap_sec("R3"), Some(5));
    assert_eq!(phase_soft_cap_sec("R4"), Some(9));
    assert_eq!(phase_soft_cap_sec("R5"), None);

    // Trigger wire-strings.
    assert_eq!(RecoveryTrigger::CrashDetected.as_str(), "CrashDetected");
    assert_eq!(
        RecoveryTrigger::DespawnMidOperation.as_str(),
        "DespawnMidOperation"
    );
    assert_eq!(RecoveryTrigger::StateCorruption.as_str(), "StateCorruption");

    // Failure-mode wire-strings.
    assert_eq!(
        RecoveryFailureMode::TriggerAmbiguous.as_str(),
        "RecoveryTriggerAmbiguousError"
    );
    assert_eq!(
        RecoveryFailureMode::BackingUnreachable.as_str(),
        "RecoveryBackingUnreachableError"
    );
    assert_eq!(
        RecoveryFailureMode::SnapshotCorrupt.as_str(),
        "RecoverySnapshotCorruptError"
    );
    assert_eq!(
        RecoveryFailureMode::IdentityRebindError.as_str(),
        "RecoveryIdentityRebindError"
    );
    assert_eq!(
        RecoveryFailureMode::ResumeError.as_str(),
        "RecoveryResumeError"
    );
    assert_eq!(
        RecoveryFailureMode::BudgetExceeded.as_str(),
        "RecoveryBudgetExceededError"
    );

    // Audit-record JSON key shape (parity with Python
    // `json.dumps(asdict(result))`).
    let mut ctx = fresh_context();
    ctx.fence_active = true;
    let outcome = run_recovery_drill(ctx, 0).await;
    let json_str = audit_record_json(&outcome);
    let parsed: serde_json::Value =
        serde_json::from_str(&json_str).expect("audit record must parse");
    let obj = parsed.as_object().expect("audit record is object");
    for required in &[
        "final_state",
        "phases",
        "success",
        "total_elapsed_sec",
        "trigger",
    ] {
        assert!(
            obj.contains_key(*required),
            "audit record missing required key {:?}",
            required
        );
    }
    let phases = obj.get("phases").and_then(|v| v.as_array()).expect("phases array");
    assert_eq!(phases.len(), 4);
    for ph in phases {
        let ph_obj = ph.as_object().expect("phase is object");
        for required in &[
            "audit_annotation",
            "elapsed_sec",
            "phase",
            "soft_cap_exceeded",
            "terminal_status",
        ] {
            assert!(
                ph_obj.contains_key(*required),
                "phase record missing required key {:?}",
                required
            );
        }
    }
}

#[tokio::test]
async fn t8_phase_order_invariant_r1_r2_r3_r4() {
    // The phases must run in canonical order (§3.7.4.2 last
    // paragraph). Re-ordering would violate the audit invariants.
    let mut ctx = fresh_context();
    ctx.fence_active = true;
    let outcome = run_recovery_drill(ctx, 0).await;
    let observed: Vec<&str> =
        outcome.phases.iter().map(|p| p.phase.as_str()).collect();
    assert_eq!(observed, vec!["R1", "R2", "R3", "R4"]);
}

#[tokio::test]
async fn t9_hook_failure_path_aborts_and_escalates_once() {
    // A failing `svid_refetch` aborts the drill at R3. The phases
    // captured must be R1 + R2 (R3 fails before producing a
    // PhaseResult). The escalation hook must fire exactly once.
    let counter = Arc::new(AtomicU32::new(0));
    let mut ctx = fresh_context();
    ctx.fence_active = true;
    let hooks = RecoveryHooks {
        svid_refetch: failing_hook(
            RecoveryFailureMode::IdentityRebindError,
            "smoke-test forced failure",
        ),
        nats_resubscribe: RecoveryHooks::default().nats_resubscribe,
        fsm_restart: RecoveryHooks::default().fsm_restart,
        operator_escalation: counting_escalation_hook(counter.clone()),
    };
    let outcome = run_recovery_drill_with_hooks(ctx, 0, hooks).await;
    assert!(!outcome.success);
    assert_eq!(outcome.phases.len(), 2, "R1+R2 only before R3 failure");
    assert_eq!(outcome.phases[0].phase, "R1");
    assert_eq!(outcome.phases[1].phase, "R2");
    assert_eq!(
        outcome.final_state,
        "failed:RecoveryIdentityRebindError",
        "final_state must include the failure mode wire-string"
    );
    assert_eq!(
        counter.load(Ordering::SeqCst),
        1,
        "escalation hook must fire exactly once"
    );
}

#[tokio::test]
async fn t10_utc_now_rfc3339_shape_parity_with_python_strftime() {
    // The UTC helper must produce the `YYYY-MM-DDTHH:MM:SSZ` shape
    // (parity with Python `time.strftime("%Y-%m-%dT%H:%M:%SZ")`).
    let stamp = utc_now_rfc3339();
    assert_eq!(stamp.len(), 20, "RFC-3339 seconds-Z shape is 20 chars");
    assert!(stamp.ends_with('Z'), "stamp must end with Z");
    assert_eq!(&stamp[4..5], "-");
    assert_eq!(&stamp[7..8], "-");
    assert_eq!(&stamp[10..11], "T");
    assert_eq!(&stamp[13..14], ":");
    assert_eq!(&stamp[16..17], ":");
}

#[tokio::test]
async fn t11_escalate_to_operator_direct_invocation() {
    // The `escalate_to_operator` helper invokes the escalation hook
    // out-of-band (used by the supervisor when an after-the-fact
    // budget-exceeded event must surface to the operator without
    // re-running the drill).
    let counter = Arc::new(AtomicU32::new(0));
    let ctx = fresh_context();
    let hooks = RecoveryHooks {
        svid_refetch: RecoveryHooks::default().svid_refetch,
        nats_resubscribe: RecoveryHooks::default().nats_resubscribe,
        fsm_restart: RecoveryHooks::default().fsm_restart,
        operator_escalation: counting_escalation_hook(counter.clone()),
    };
    let err = RecoveryError::new(
        RecoveryFailureMode::BudgetExceeded,
        "post-hoc supervisor escalation",
    );
    let result = escalate_to_operator(&ctx, &hooks, &err).await;
    assert!(result.is_ok());
    assert_eq!(counter.load(Ordering::SeqCst), 1);
}
