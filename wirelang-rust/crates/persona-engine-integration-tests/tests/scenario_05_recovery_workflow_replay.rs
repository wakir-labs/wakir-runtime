// SPDX-License-Identifier: Apache-2.0
//! Scenario 5 — Recovery Workflow Replay.
//!
//! Three R1..R3 PhaseResult records are produced via the
//! `persona-engine-recovery` crate's `PhaseResult` constructor, then
//! handed to the `persona-engine-recovery-replay` engine for validation
//! against an expected trajectory.
//!
//! Four tests cover:
//!
//!   1. Three-phase R1->R2->R3 happy-path: actual matches expected
//!      one-for-one -> success, zero divergences, workflow_hash equal.
//!   2. Value-mismatch detection: actual differs at R2.terminal_status
//!      -> divergence list non-empty, time_to_divergence_steps == 1
//!      (0-based: R1 OK, R2 drifts).
//!   3. Missing-in-actual: actual is two phases (R1, R2), expected has
//!      three (R1, R2, R3) -> divergence at index 2 with kind
//!      MissingInActual.
//!   4. Extra-in-actual: actual is four phases, expected three -> the
//!      extra phase is flagged ExtraInActual.

use persona_engine_recovery::PhaseResult;
use persona_engine_recovery_replay::{
    DivergenceKind, ExpectedRecoveryTrajectory, RecoveryReplayEngine,
};

fn phase(p: &str, status: &str, elapsed: f64, annotation: &str) -> PhaseResult {
    PhaseResult {
        phase: p.to_string(),
        terminal_status: status.to_string(),
        elapsed_sec: elapsed,
        soft_cap_exceeded: false,
        audit_annotation: annotation.to_string(),
    }
}

fn expected_r1_r2_r3() -> Vec<PhaseResult> {
    vec![
        phase("R1", "detected", 0.40, "R1 detected via Scenario-05"),
        phase("R2", "reloaded", 1.20, "R2 reloaded via Scenario-05"),
        phase("R3", "re_registered", 0.60, "R3 re_registered via Scenario-05"),
    ]
}

#[test]
fn t01_happy_path_three_phase_replay() {
    let actual = expected_r1_r2_r3();
    let expected = ExpectedRecoveryTrajectory::from_steps(&actual);
    let engine = RecoveryReplayEngine::new();
    let report = engine.replay_workflow(&actual, &expected).expect("replay ok");
    assert!(report.success, "happy-path replay must succeed");
    assert!(
        report.divergences.is_empty(),
        "happy-path replay must have zero divergences, got {:?}",
        report.divergences,
    );
    assert_eq!(report.actual_step_count, 3);
    assert_eq!(report.expected_step_count, 3);
    assert_eq!(report.time_to_divergence_steps, None);
    assert_eq!(report.workflow_hash_actual, report.workflow_hash_expected);
}

#[test]
fn t02_value_mismatch_at_r2_yields_first_divergence_at_index_1() {
    let mut actual = expected_r1_r2_r3();
    // Drift terminal_status at index 1.
    actual[1].terminal_status = "DRIFT-RELOADED".to_string();
    let expected = ExpectedRecoveryTrajectory::from_steps(&expected_r1_r2_r3());

    let engine = RecoveryReplayEngine::new();
    let report = engine.replay_workflow(&actual, &expected).expect("replay ok");

    assert!(!report.success, "value-mismatch must not be success");
    assert!(
        !report.divergences.is_empty(),
        "value-mismatch must produce at least one divergence",
    );
    assert_eq!(
        report.time_to_divergence_steps,
        Some(1),
        "first divergence index must be 1 (R2 row)",
    );
    // The replay-engine's per-step kind for a value-mismatch is
    // DivergenceKind::ValueMismatch. The first divergence is the R2
    // hash drift.
    let first = report.divergences.first().expect("at least one divergence");
    assert_eq!(first.step_index, 1);
    assert!(matches!(first.kind, DivergenceKind::ValueMismatch));
    assert_ne!(report.workflow_hash_actual, report.workflow_hash_expected);
}

#[test]
fn t03_missing_in_actual_flagged_at_trailing_index() {
    let actual: Vec<PhaseResult> = expected_r1_r2_r3().into_iter().take(2).collect();
    let expected = ExpectedRecoveryTrajectory::from_steps(&expected_r1_r2_r3());

    let engine = RecoveryReplayEngine::new();
    let report = engine.replay_workflow(&actual, &expected).expect("replay ok");

    assert!(!report.success);
    assert_eq!(report.actual_step_count, 2);
    assert_eq!(report.expected_step_count, 3);
    // First divergence must be at index 2 — the missing R3 row.
    assert_eq!(report.time_to_divergence_steps, Some(2));
    let first = report.divergences.first().expect("missing-in-actual divergence");
    assert_eq!(first.step_index, 2);
    assert!(
        matches!(first.kind, DivergenceKind::MissingInActual),
        "first divergence on truncated-actual must be MissingInActual, got {:?}",
        first.kind,
    );
}

#[test]
fn t04_extra_in_actual_flagged_at_trailing_index() {
    let mut actual = expected_r1_r2_r3();
    // Append a fourth phase R4 that the expected trajectory does not have.
    actual.push(phase(
        "R4",
        "resumed",
        0.30,
        "R4 resumed unexpectedly",
    ));
    let expected = ExpectedRecoveryTrajectory::from_steps(&expected_r1_r2_r3());

    let engine = RecoveryReplayEngine::new();
    let report = engine.replay_workflow(&actual, &expected).expect("replay ok");
    assert!(!report.success);
    assert_eq!(report.actual_step_count, 4);
    assert_eq!(report.expected_step_count, 3);
    assert_eq!(report.time_to_divergence_steps, Some(3));
    let first = report.divergences.first().expect("extra-in-actual divergence");
    assert_eq!(first.step_index, 3);
    assert!(
        matches!(first.kind, DivergenceKind::ExtraInActual),
        "first divergence on extra-actual must be ExtraInActual, got {:?}",
        first.kind,
    );
}
