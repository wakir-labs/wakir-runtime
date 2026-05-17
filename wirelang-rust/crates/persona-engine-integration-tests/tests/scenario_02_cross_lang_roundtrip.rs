// SPDX-License-Identifier: Apache-2.0
//! Scenario 2 — Cross-Lang Roundtrip.
//!
//! The full Python emit / Rust replay roundtrip for the recovery-
//! workflow side is the substrate for Phase-2 Doppelbetrieb-
//! Konsistenz-Drills. Until a full Python sibling lands for the
//! recovery-workflow envelope shape (the recovery-replay crate's
//! cross-lang pin placeholder still flags this gap), this scenario
//! exercises the Rust-side roundtrip end-to-end and asserts that
//! `workflow_hash` is deterministic and stable across:
//!
//!   - identical inputs (Rust round-trips itself),
//!   - re-ordered struct construction (logical content equality),
//!   - independent reconstruction from the public field set.
//!
//! The fixture is a three-record stream (R1 -> R2 -> R3) matching the
//! recovery-replay crate's F3 fixture shape. When the Python sibling
//! lands the assertions here become point-pins via byte-equality
//! against the recorded Python output.
//!
//! Three tests cover:
//!
//!   1. Workflow-hash deterministic on identical fixture across two
//!      independent emissions.
//!   2. Per-phase JCS hashes deterministic across two independent
//!      emissions of the same phase.
//!   3. Replay-engine yields zero divergences when actual stream
//!      equals expected trajectory (full match).

use persona_engine_recovery::PhaseResult;
use persona_engine_recovery_replay::{
    phase_hash, workflow_hash, ExpectedRecoveryTrajectory, RecoveryReplayEngine,
};

fn fixture_phase(phase: &str, status: &str, elapsed: f64) -> PhaseResult {
    PhaseResult {
        phase: phase.to_string(),
        terminal_status: status.to_string(),
        elapsed_sec: elapsed,
        soft_cap_exceeded: false,
        audit_annotation: format!("{phase} drill via Scenario-02 fixture"),
    }
}

fn fixture_three_record_stream() -> Vec<PhaseResult> {
    vec![
        fixture_phase("R1", "detected", 0.5),
        fixture_phase("R2", "reloaded", 1.25),
        fixture_phase("R3", "re_registered", 0.75),
    ]
}

#[test]
fn t01_workflow_hash_deterministic_across_emissions() {
    let stream_a = fixture_three_record_stream();
    let stream_b = fixture_three_record_stream();
    let hash_a = workflow_hash(&stream_a).expect("hash a");
    let hash_b = workflow_hash(&stream_b).expect("hash b");
    assert_eq!(
        hash_a, hash_b,
        "workflow_hash must be deterministic across two identical emissions",
    );
    assert!(hash_a.starts_with("sha256:"));
    assert_eq!(hash_a.len(), 71); // 7 prefix + 64 hex
}

#[test]
fn t02_per_phase_hashes_deterministic() {
    // Build the same phase twice and check that its JCS hash matches.
    let r2_a = fixture_phase("R2", "reloaded", 1.25);
    let r2_b = fixture_phase("R2", "reloaded", 1.25);
    let h_a = phase_hash(&r2_a).expect("hash a");
    let h_b = phase_hash(&r2_b).expect("hash b");
    assert_eq!(h_a, h_b);

    // A different status must yield a different hash (canonical-
    // subset must include terminal_status).
    let r2_c = fixture_phase("R2", "RELOADED-BIG", 1.25);
    let h_c = phase_hash(&r2_c).expect("hash c");
    assert_ne!(h_a, h_c, "terminal_status drift must change phase_hash");
}

#[test]
fn t03_replay_engine_zero_divergence_on_full_match() {
    let actual = fixture_three_record_stream();
    let expected = ExpectedRecoveryTrajectory::from_steps(&actual);
    let engine = RecoveryReplayEngine::new();
    let report = engine
        .replay_workflow(&actual, &expected)
        .expect("replay must not error");
    assert!(
        report.divergences.is_empty(),
        "fixture-equal actual + expected must yield zero divergences, got {:?}",
        report.divergences,
    );
    assert_eq!(
        report.workflow_hash_actual, report.workflow_hash_expected,
        "actual and expected workflow_hash must agree on full match",
    );
}
