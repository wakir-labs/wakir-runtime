// SPDX-License-Identifier: Apache-2.0
//! Recovery-Replay-Engine smoke-tests.
//!
//! Sprint-Recovery-Replay-Engine-Rust-MINI (ADR-0063 §Folgeartefakte
//! Phase-3a Item 13).
//!
//! Three Recovery-Fixtures cover the Sprint-Auftrag matrix:
//!
//! - F1 (clean R1->R4): full 4-phase happy-path drill.
//! - F2 (R2-fail-retry): 5-phase trajectory with R2 retried after a
//!   transient failure (R1, R2-fail, R2-retry, R3, R4). The replay
//!   engine treats the retry as a structurally-valid trajectory entry
//!   so the operator can compare against the expected retry shape.
//! - F3 (R3-skip): 3-phase trajectory where the operator's recovery
//!   policy skips R3 (R1, R2, R4). Validates the replay-engine's
//!   missing-step detection against a deliberately-shorter actual.
//!
//! Coverage matrix:
//!
//! 1.  PhaseResult re-export accessible as `RecoveryStep` alias.
//! 2.  phase_to_envelope emits the schema-tagged 6-field shape.
//! 3.  phase_hash is deterministic and field-sensitive.
//! 4.  workflow_hash distinguishes empty / single / multi.
//! 5.  Cross-fixture pin: F1 phase-hashes are stable across runs.
//! 6.  Cross-fixture pin: F2 (retry) workflow-hash differs from F1.
//! 7.  Cross-fixture pin: F3 (skip) workflow-hash differs from F1.
//! 8.  Identical-workflows match -> success, no divergence.
//! 9.  Single-step value-mismatch detection at expected index +
//!     field_diffs surface the differing field (RFC-6901 path).
//! 10. Missing-step detection (R3-skip vs. full R1..R4).
//! 11. Extra-step detection (R2-retry vs. clean R1..R4).
//! 12. time_to_divergence monotonic non-decreasing across a
//!     successively-corrected stream.
//! 13. Replay determinism: same input -> same hash + same ttd +
//!     same divergence count.
//! 14. summary() formatting parity (success and drift branches).
//! 15. step_name in Divergence carries the phase label (R1..R4).

use persona_engine_recovery_replay::{
    diff_phase_envelopes, phase_hash, phase_to_envelope, workflow_hash, DivergenceKind,
    ExpectedRecoveryTrajectory, PhaseResult, RecoveryReplayEngine, RecoveryStep,
    RECOVERY_PHASE_SCHEMA,
};

// ---------------------------------------------------------------------------
// Fixture builders — mirror the Python `PhaseResult` shape exactly.
// ---------------------------------------------------------------------------

fn mk_phase(label: &str, status: &str, elapsed: f64, ann: &str) -> PhaseResult {
    PhaseResult {
        phase: label.to_string(),
        terminal_status: status.to_string(),
        elapsed_sec: elapsed,
        soft_cap_exceeded: false,
        audit_annotation: ann.to_string(),
    }
}

/// F1 fixture: clean R1 -> R4 happy-path.
fn f1_clean_workflow() -> Vec<PhaseResult> {
    vec![
        mk_phase(
            "R1",
            "detected",
            0.0,
            "recovery_trigger_classified=CrashDetected",
        ),
        mk_phase("R2", "reloaded", 0.01, "snapshot-restored"),
        mk_phase(
            "R3",
            "re_registered",
            0.02,
            "recovery_svid_refreshed=spiffe://wakir.local/wakir-labs/persona/selin",
        ),
        mk_phase("R4", "resumed", 0.03, "container-active"),
    ]
}

/// F2 fixture: R2-fail-retry. Trajectory contains the expected retry
/// shape: R1, R2 (failed terminal_status="reload_retry"), R2 (retry
/// success), R3, R4.
fn f2_retry_workflow() -> Vec<PhaseResult> {
    vec![
        mk_phase(
            "R1",
            "detected",
            0.0,
            "recovery_trigger_classified=CrashDetected",
        ),
        mk_phase("R2", "reload_retry", 0.5, "snapshot-restore-retried"),
        mk_phase("R2", "reloaded", 0.6, "snapshot-restored"),
        mk_phase(
            "R3",
            "re_registered",
            0.7,
            "recovery_svid_refreshed=spiffe://wakir.local/wakir-labs/persona/selin",
        ),
        mk_phase("R4", "resumed", 0.8, "container-active"),
    ]
}

/// F3 fixture: R3-skip policy. Trajectory: R1, R2, R4 (no R3).
fn f3_skip_workflow() -> Vec<PhaseResult> {
    vec![
        mk_phase(
            "R1",
            "detected",
            0.0,
            "recovery_trigger_classified=CrashDetected",
        ),
        mk_phase("R2", "reloaded", 0.01, "snapshot-restored"),
        mk_phase("R4", "resumed", 0.02, "container-active"),
    ]
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[test]
fn test_01_recovery_step_alias_resolves_to_phase_result() {
    // Sprint-Auftrag-signature: RecoveryStep is a type alias for
    // PhaseResult. The two types must be assignment-compatible.
    let p: PhaseResult = mk_phase("R1", "detected", 0.0, "ann");
    let s: RecoveryStep = p.clone();
    assert_eq!(p.phase, s.phase);
    assert_eq!(p.terminal_status, s.terminal_status);
}

#[test]
fn test_02_phase_envelope_emits_schema_tagged_6_field_shape() {
    let p = mk_phase("R1", "detected", 0.0, "trigger=CrashDetected");
    let env = phase_to_envelope(&p);
    let obj = env.as_object().expect("envelope is Object");
    assert_eq!(obj.len(), 6, "6 keys per the phase envelope contract");
    assert_eq!(
        obj.get("schema").unwrap().as_str().unwrap(),
        RECOVERY_PHASE_SCHEMA
    );
    assert_eq!(obj.get("phase").unwrap().as_str().unwrap(), "R1");
    assert_eq!(
        obj.get("terminal_status").unwrap().as_str().unwrap(),
        "detected"
    );
    assert_eq!(obj.get("elapsed_sec").unwrap().as_f64().unwrap(), 0.0);
    assert!(!obj.get("soft_cap_exceeded").unwrap().as_bool().unwrap());
    assert_eq!(
        obj.get("audit_annotation").unwrap().as_str().unwrap(),
        "trigger=CrashDetected"
    );
}

#[test]
fn test_03_phase_hash_is_deterministic_and_field_sensitive() {
    let p = mk_phase("R1", "detected", 0.0, "ann");
    let h1 = phase_hash(&p).unwrap();
    let h2 = phase_hash(&p).unwrap();
    assert_eq!(h1, h2, "deterministic");
    assert!(h1.starts_with("sha256:"));
    assert_eq!(h1.len(), "sha256:".len() + 64);

    // Sensitive to phase label change.
    let p2 = mk_phase("R2", "detected", 0.0, "ann");
    assert_ne!(phase_hash(&p2).unwrap(), h1);
    // Sensitive to terminal_status change.
    let p3 = mk_phase("R1", "reloaded", 0.0, "ann");
    assert_ne!(phase_hash(&p3).unwrap(), h1);
    // Sensitive to elapsed change.
    let p4 = mk_phase("R1", "detected", 0.1, "ann");
    assert_ne!(phase_hash(&p4).unwrap(), h1);
    // Sensitive to audit_annotation change.
    let p5 = mk_phase("R1", "detected", 0.0, "ann2");
    assert_ne!(phase_hash(&p5).unwrap(), h1);
}

#[test]
fn test_04_workflow_hash_distinguishes_empty_single_multi() {
    let empty: Vec<PhaseResult> = Vec::new();
    let single = vec![mk_phase("R1", "detected", 0.0, "a")];
    let multi = f1_clean_workflow();
    let h_empty = workflow_hash(&empty).unwrap();
    let h_single = workflow_hash(&single).unwrap();
    let h_multi = workflow_hash(&multi).unwrap();
    assert_ne!(h_empty, h_single);
    assert_ne!(h_single, h_multi);
    assert_ne!(h_empty, h_multi);
    // Empty stream is reproducible.
    let h_empty_again = workflow_hash(&empty).unwrap();
    assert_eq!(h_empty, h_empty_again);
}

#[test]
fn test_05_f1_phase_hashes_are_stable_across_runs() {
    // Stability pin: re-running phase_hash on the F1 fixture phases
    // must yield bit-identical results. This protects against any
    // future canonicalisation regression that would break the
    // Doppelbetrieb-Konsistenz contract.
    let w1 = f1_clean_workflow();
    let w2 = f1_clean_workflow();
    for (a, b) in w1.iter().zip(w2.iter()) {
        assert_eq!(phase_hash(a).unwrap(), phase_hash(b).unwrap());
    }
    // The four hashes must all differ from each other (the phases
    // differ in label / status / elapsed / annotation).
    let h: Vec<String> = w1.iter().map(|p| phase_hash(p).unwrap()).collect();
    assert_eq!(h[0].len(), "sha256:".len() + 64);
    for i in 0..h.len() {
        for j in (i + 1)..h.len() {
            assert_ne!(h[i], h[j], "phase {i} vs {j} must hash differently");
        }
    }
}

#[test]
fn test_06_f2_retry_workflow_hash_differs_from_f1() {
    // F2 has 5 phases vs F1's 4; the workflow envelope's `phases_len`
    // field alone ensures the hash differs even if every shared phase
    // were identical.
    let h_f1 = workflow_hash(&f1_clean_workflow()).unwrap();
    let h_f2 = workflow_hash(&f2_retry_workflow()).unwrap();
    assert_ne!(h_f1, h_f2);
}

#[test]
fn test_07_f3_skip_workflow_hash_differs_from_f1() {
    let h_f1 = workflow_hash(&f1_clean_workflow()).unwrap();
    let h_f3 = workflow_hash(&f3_skip_workflow()).unwrap();
    assert_ne!(h_f1, h_f3);
}

#[test]
fn test_08_identical_workflows_match_success_no_divergence() {
    let engine = RecoveryReplayEngine::new();
    let actual = f1_clean_workflow();
    let expected = ExpectedRecoveryTrajectory::from_steps(&actual);
    let report = engine.replay_workflow(&actual, &expected).expect("replay");
    assert!(report.success, "identical workflows should match");
    assert!(report.divergences.is_empty());
    assert_eq!(report.time_to_divergence_steps, None);
    assert_eq!(report.actual_step_count, 4);
    assert_eq!(report.expected_step_count, 4);
    assert_eq!(report.workflow_hash_actual, report.workflow_hash_expected);
}

#[test]
fn test_09_single_step_value_mismatch_detected_at_expected_index() {
    let engine = RecoveryReplayEngine::new();
    let expected_steps = f1_clean_workflow();
    let expected = ExpectedRecoveryTrajectory::from_steps(&expected_steps);

    // Drift R3's terminal_status from "re_registered" to
    // "re_registration_failed".
    let mut actual = expected_steps.clone();
    actual[2].terminal_status = "re_registration_failed".to_string();

    let report = engine.replay_workflow(&actual, &expected).expect("replay");
    assert!(!report.success);
    assert_eq!(report.divergences.len(), 1);
    assert_eq!(report.time_to_divergence_steps, Some(2));
    let d = &report.divergences[0];
    assert_eq!(d.step_index, 2);
    assert_eq!(d.kind, DivergenceKind::ValueMismatch);
    assert_eq!(d.step_name, "R3");
    assert!(d.expected.is_some() && d.actual.is_some());
    assert!(
        !d.field_diffs.is_empty(),
        "field_diffs should pinpoint terminal_status"
    );
    assert!(
        d.field_diffs.iter().any(|fd| fd.path == "/terminal_status"),
        "field_diff path must surface /terminal_status"
    );
    let fd = d
        .field_diffs
        .iter()
        .find(|fd| fd.path == "/terminal_status")
        .unwrap();
    assert_eq!(fd.kind, "value-mismatch");
    assert_eq!(fd.actual, "re_registration_failed");
    assert_eq!(fd.expected, "re_registered");
}

#[test]
fn test_10_missing_step_detection_r3_skip_against_full_r1_r4() {
    // Expected: full F1 (4 steps R1..R4).
    // Actual: F3-skip (3 steps R1, R2, R4).
    // At index 2 the actual has "R4" but expected has "R3" -> the
    // engine surfaces a value-mismatch at idx 2 (different `phase`
    // field) AND a missing-in-actual at idx 3.
    let engine = RecoveryReplayEngine::new();
    let expected = ExpectedRecoveryTrajectory::from_steps(&f1_clean_workflow());
    let actual = f3_skip_workflow();
    let report = engine.replay_workflow(&actual, &expected).expect("replay");
    assert!(!report.success);
    assert_eq!(report.actual_step_count, 3);
    assert_eq!(report.expected_step_count, 4);
    assert_eq!(report.time_to_divergence_steps, Some(2));
    // Two divergences: idx-2 value-mismatch (R4 vs R3) and idx-3
    // missing-in-actual.
    assert_eq!(report.divergences.len(), 2);
    assert_eq!(report.divergences[0].step_index, 2);
    assert_eq!(report.divergences[0].kind, DivergenceKind::ValueMismatch);
    assert_eq!(report.divergences[1].step_index, 3);
    assert_eq!(report.divergences[1].kind, DivergenceKind::MissingInActual);
    assert!(report.divergences[1].expected.is_some());
    assert!(report.divergences[1].actual.is_none());
    assert_eq!(report.divergences[1].step_name, "R4");
}

#[test]
fn test_11_extra_step_detection_r2_retry_against_clean_r1_r4() {
    // Expected: clean F1 (4 steps).
    // Actual: F2 retry (5 steps — R2 appears twice).
    // The first divergence surfaces at idx 1: actual is "R2 retry"
    // (terminal_status=reload_retry, elapsed=0.5) vs expected
    // "R2 reloaded" (elapsed=0.01).
    let engine = RecoveryReplayEngine::new();
    let expected = ExpectedRecoveryTrajectory::from_steps(&f1_clean_workflow());
    let actual = f2_retry_workflow();
    let report = engine.replay_workflow(&actual, &expected).expect("replay");
    assert!(!report.success);
    assert_eq!(report.actual_step_count, 5);
    assert_eq!(report.expected_step_count, 4);
    assert_eq!(report.time_to_divergence_steps, Some(1));
    // Expected divergences: idx-1 mismatch, idx-2 mismatch (R2 vs R3),
    // idx-3 mismatch (R3 vs R4), idx-4 extra-in-actual.
    assert_eq!(report.divergences.len(), 4);
    let kinds: Vec<DivergenceKind> = report.divergences.iter().map(|d| d.kind).collect();
    assert_eq!(
        kinds,
        vec![
            DivergenceKind::ValueMismatch,
            DivergenceKind::ValueMismatch,
            DivergenceKind::ValueMismatch,
            DivergenceKind::ExtraInActual,
        ]
    );
    // The extra-in-actual entry must have the actual phase label.
    assert_eq!(report.divergences[3].step_name, "R4");
    assert!(report.divergences[3].expected.is_none());
    assert!(report.divergences[3].actual.is_some());
}

#[test]
fn test_12_time_to_divergence_monotonic_when_earlier_step_corrected() {
    let engine = RecoveryReplayEngine::new();
    let expected = ExpectedRecoveryTrajectory::from_steps(&f1_clean_workflow());

    // Stream A: drift at step 0 -> ttd = 0.
    let mut a = f1_clean_workflow();
    a[0].audit_annotation = "trigger=DespawnMidOperation".to_string();
    a[1].audit_annotation = "snapshot-restored-drift".to_string();
    let r_a = engine.replay_workflow(&a, &expected).expect("replay");
    assert_eq!(r_a.time_to_divergence_steps, Some(0));

    // Stream B: step 0 corrected, drift now at step 1 -> ttd = 1.
    let mut b = f1_clean_workflow();
    b[1].audit_annotation = "snapshot-restored-drift".to_string();
    let r_b = engine.replay_workflow(&b, &expected).expect("replay");
    assert_eq!(r_b.time_to_divergence_steps, Some(1));

    // Stream C: 0 + 1 corrected, drift only at step 2 -> ttd = 2.
    let mut c = f1_clean_workflow();
    c[2].audit_annotation =
        "recovery_svid_refreshed=spiffe://wakir.local/wakir-labs/persona/drift".to_string();
    let r_c = engine.replay_workflow(&c, &expected).expect("replay");
    assert_eq!(r_c.time_to_divergence_steps, Some(2));

    // Stream D: 0/1/2 corrected, drift only at step 3 -> ttd = 3.
    let mut d = f1_clean_workflow();
    d[3].audit_annotation = "container-drift".to_string();
    let r_d = engine.replay_workflow(&d, &expected).expect("replay");
    assert_eq!(r_d.time_to_divergence_steps, Some(3));

    let seq = [
        r_a.time_to_divergence_steps.unwrap(),
        r_b.time_to_divergence_steps.unwrap(),
        r_c.time_to_divergence_steps.unwrap(),
        r_d.time_to_divergence_steps.unwrap(),
    ];
    assert!(
        seq.windows(2).all(|w| w[0] <= w[1]),
        "ttd monotonic non-decreasing across corrected sequence"
    );
}

#[test]
fn test_13_replay_determinism_repeated_runs_bit_identical() {
    let engine = RecoveryReplayEngine::new();
    let expected = ExpectedRecoveryTrajectory::from_steps(&f1_clean_workflow());
    let mut actual = f1_clean_workflow();
    actual[1].elapsed_sec = 0.99;

    let r1 = engine.replay_workflow(&actual, &expected).expect("r1");
    let r2 = engine.replay_workflow(&actual, &expected).expect("r2");
    let r3 = engine.replay_workflow(&actual, &expected).expect("r3");

    assert_eq!(r1.workflow_hash_actual, r2.workflow_hash_actual);
    assert_eq!(r2.workflow_hash_actual, r3.workflow_hash_actual);
    assert_eq!(r1.workflow_hash_expected, r2.workflow_hash_expected);
    assert_eq!(r1.time_to_divergence_steps, r2.time_to_divergence_steps);
    assert_eq!(r2.time_to_divergence_steps, r3.time_to_divergence_steps);
    assert_eq!(r1.divergences.len(), r2.divergences.len());
    assert_eq!(r2.divergences.len(), r3.divergences.len());
    assert_eq!(r1.divergences[0].kind, r2.divergences[0].kind);
    assert_eq!(r1.divergences[0].step_index, r2.divergences[0].step_index);
    assert_eq!(r1.divergences[0].step_name, r2.divergences[0].step_name);
}

#[test]
fn test_14_summary_formatting_parity() {
    let engine = RecoveryReplayEngine::new();
    let expected = ExpectedRecoveryTrajectory::from_steps(&f1_clean_workflow());

    // Success branch.
    let r_ok = engine
        .replay_workflow(&f1_clean_workflow(), &expected)
        .expect("ok");
    let s_ok = r_ok.summary();
    assert!(s_ok.starts_with("recovery-replay-ok"));
    assert!(s_ok.contains("phases=4"));
    assert!(s_ok.contains("workflow_hash=sha256:"));

    // Drift branch.
    let mut actual = f1_clean_workflow();
    actual[0].terminal_status = "drift".to_string();
    let r_drift = engine.replay_workflow(&actual, &expected).expect("drift");
    let s_drift = r_drift.summary();
    assert!(s_drift.starts_with("recovery-replay-drift"));
    assert!(s_drift.contains("first_step=0"));
    assert!(s_drift.contains("divergences=1"));
    assert!(s_drift.contains("actual_hash=sha256:"));
    assert!(s_drift.contains("expected_hash=sha256:"));
}

#[test]
fn test_15_step_name_carries_phase_label_for_each_kind() {
    let engine = RecoveryReplayEngine::new();

    // ValueMismatch path: step_name from the actual (== expected) phase label.
    let expected = ExpectedRecoveryTrajectory::from_steps(&f1_clean_workflow());
    let mut actual = f1_clean_workflow();
    actual[1].terminal_status = "drift".to_string();
    let r = engine.replay_workflow(&actual, &expected).expect("replay");
    assert_eq!(r.divergences[0].step_name, "R2");

    // MissingInActual path: step_name from the expected phase label.
    let expected_long = ExpectedRecoveryTrajectory::from_steps(&f1_clean_workflow());
    let actual_short = f3_skip_workflow();
    let r2 = engine
        .replay_workflow(&actual_short, &expected_long)
        .expect("replay");
    // The missing entry is the R4 expected at idx 3.
    let missing = r2
        .divergences
        .iter()
        .find(|d| d.kind == DivergenceKind::MissingInActual)
        .expect("missing entry");
    assert_eq!(missing.step_name, "R4");

    // ExtraInActual path: step_name from the actual phase label.
    let expected_short = ExpectedRecoveryTrajectory::from_steps(&f1_clean_workflow());
    let actual_long = f2_retry_workflow();
    let r3 = engine
        .replay_workflow(&actual_long, &expected_short)
        .expect("replay");
    let extra = r3
        .divergences
        .iter()
        .find(|d| d.kind == DivergenceKind::ExtraInActual)
        .expect("extra entry");
    assert_eq!(extra.step_name, "R4");
}

// ---------------------------------------------------------------------------
// Bonus: confirm diff_phase_envelopes is callable as a public helper
// (covers all three kinds of field-level diff entries).
// ---------------------------------------------------------------------------

#[test]
fn test_16_diff_phase_envelopes_emits_all_three_kinds() {
    let a = serde_json::json!({"a": 1, "shared": "x", "only_a": true});
    let b = serde_json::json!({"a": 2, "shared": "x", "only_b": false});
    let diffs = diff_phase_envelopes(&a, &b);
    let kinds: Vec<&str> = diffs.iter().map(|d| d.kind.as_str()).collect();
    assert!(kinds.contains(&"value-mismatch"));
    assert!(kinds.contains(&"only-in-actual"));
    assert!(kinds.contains(&"only-in-expected"));
    // Output sorted by path.
    let mut paths: Vec<String> = diffs.iter().map(|d| d.path.clone()).collect();
    let sorted = {
        let mut s = paths.clone();
        s.sort();
        s
    };
    paths.sort();
    assert_eq!(paths, sorted);
}
