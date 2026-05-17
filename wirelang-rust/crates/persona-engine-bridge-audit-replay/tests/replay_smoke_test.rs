// SPDX-License-Identifier: Apache-2.0
//! Bridge-Audit-Replay-Engine smoke-tests with cross-language anchor pins.
//!
//! Sprint-Bridge-Audit-Replay-Engine-Rust-MINI smoke suite (ADR-0063
//! §Folgeartefakte Phase-3a Item 11). Each cross-language pin in this
//! file was captured 2026-05-17 from the Python pendant
//! (`wirelang.persona_engine.bridge_audit_writer.EngineeringOutputEvent`
//! plus `wirelang.persona_engine.bridge_audit_diff_engine.jcs_hash`)
//! running against the SAME fixture in the same source tree.
//!
//! Coverage matrix:
//!
//! 1.  AuditRecord.to_envelope() emits the schema-tagged 11-field shape.
//! 2.  Per-record JCS hash matches the Python `jcs_hash` pin (record 0).
//! 3.  Per-record JCS hash matches the Python pin (record 1).
//! 4.  Per-record JCS hash matches the Python pin (record 2).
//! 5.  Cross-lang stream-hash pin: empty stream.
//! 6.  Cross-lang stream-hash pin: single record (F2 fixture).
//! 7.  Cross-lang stream-hash pin: 3-record session (F3 fixture).
//! 8.  Replay-deterministic: identical streams -> success, no divergence.
//! 9.  Single-step value-mismatch detection at expected index.
//! 10. Missing-record detection (actual stream too short).
//! 11. Extra-record detection (actual stream too long).
//! 12. time_to_divergence_steps monotonic non-decreasing across a
//!     successively-corrected stream (fix-step-0 -> divergence moves
//!     to step-1).
//! 13. Replay determinism: re-running with the same input yields the
//!     same stream_hash + same time_to_divergence + same kind.
//! 14. summary() formatting parity (success and drift branches).

use persona_engine_bridge_audit_replay::{
    stream_hash, AuditRecord, DivergenceKind, ExpectedTrajectory, ReplayEngine,
    ENGINEERING_OUTPUT_SCHEMA, EVENT_KIND,
};

// ---------------------------------------------------------------------------
// Cross-language anchor pins (captured 2026-05-17 from Python).
// ---------------------------------------------------------------------------

/// Python `jcs_hash` of the 3-record F3 fixture's record-0 envelope.
const F3_REC_0_PIN: &str =
    "sha256:0c501a322a4ae2634ccf923d1df95468735003c391e6730a8c744e1ea148dc99";

/// Python `jcs_hash` of the 3-record F3 fixture's record-1 envelope.
const F3_REC_1_PIN: &str =
    "sha256:ecaf97ab0725976ca4809617f0a61eaf617c0ad11220282cab915fced3c41e79";

/// Python `jcs_hash` of the 3-record F3 fixture's record-2 envelope.
const F3_REC_2_PIN: &str =
    "sha256:f611d948be451fdf61068d77a164fedf47fd1a12cd5af0e0dbbb96964d1be686";

/// Python `jcs_hash({"stream": [], "stream_len": 0})` on 2026-05-17.
const F1_STREAM_PIN: &str =
    "sha256:64d11dbb5fe0c2c5e807d22438aedf3912852d81717e532f5c9d2750afa15469";

/// Python `jcs_hash({"stream": [<rec-0>], "stream_len": 1})` (F2 fixture).
const F2_STREAM_PIN: &str =
    "sha256:5d259cab58d5d75772f230ac86d18b6a61fd228829cea7aa1887e98cea3cc770";

/// Python `jcs_hash` of the 3-record F3 fixture's `stream` envelope.
const F3_STREAM_PIN: &str =
    "sha256:fca1381878f461ea00520d9ee87d3e8c5b536e028e368c002f8de56d8b643bd4";

// ---------------------------------------------------------------------------
// Fixture builders (mirror the Python builder in pin-capture script).
// ---------------------------------------------------------------------------

fn mk_record(step: u32, output_kind: &str, payload_hex_char: char) -> AuditRecord {
    AuditRecord {
        org_id: "wakir-labs".to_string(),
        persona_id: "mira".to_string(),
        session_id: "sess-001".to_string(),
        step_index: step,
        output_kind: output_kind.to_string(),
        output_payload_sha256: format!("sha256:{}", payload_hex_char.to_string().repeat(64)),
        engine_version: "0.2.0-pilot".to_string(),
        v907_pin: format!("sha256:{}", "b".repeat(64)),
        ts_utc: format!("2026-05-17T10:00:0{step}Z"),
    }
}

/// F2 fixture: a single-record stream — record-0 of the F3 session.
fn f2_stream() -> Vec<AuditRecord> {
    // Python: step_index=0, output_kind='tool_call', payload='a'*64.
    vec![mk_record(0, "tool_call", 'a')]
}

/// F3 fixture: 3-record stream — step 0 tool_call, step 1 reply, step 2
/// tool_call — payloads 'a'/'b'/'c' to ensure each record's hash is
/// distinct.
fn f3_stream() -> Vec<AuditRecord> {
    vec![
        mk_record(0, "tool_call", 'a'),
        mk_record(1, "reply", 'b'),
        mk_record(2, "tool_call", 'c'),
    ]
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[test]
fn test_01_to_envelope_emits_schema_tagged_11_field_shape() {
    let r = mk_record(0, "tool_call", 'a');
    let env = r.to_envelope();
    let obj = env.as_object().expect("envelope is Object");
    assert_eq!(obj.len(), 11, "11 keys per the writer pin");
    assert_eq!(
        obj.get("schema").unwrap().as_str().unwrap(),
        ENGINEERING_OUTPUT_SCHEMA
    );
    assert_eq!(obj.get("event_kind").unwrap().as_str().unwrap(), EVENT_KIND);
    assert_eq!(obj.get("persona_id").unwrap().as_str().unwrap(), "mira");
    assert_eq!(obj.get("step_index").unwrap().as_u64().unwrap(), 0);
}

#[test]
fn test_02_per_record_hash_matches_python_pin_record_0() {
    let r = mk_record(0, "tool_call", 'a');
    let h = r.jcs_hash().expect("hash");
    assert_eq!(h, F3_REC_0_PIN, "record-0 cross-language pin");
}

#[test]
fn test_03_per_record_hash_matches_python_pin_record_1() {
    let r = mk_record(1, "reply", 'b');
    let h = r.jcs_hash().expect("hash");
    assert_eq!(h, F3_REC_1_PIN, "record-1 cross-language pin");
}

#[test]
fn test_04_per_record_hash_matches_python_pin_record_2() {
    let r = mk_record(2, "tool_call", 'c');
    let h = r.jcs_hash().expect("hash");
    assert_eq!(h, F3_REC_2_PIN, "record-2 cross-language pin");
}

#[test]
fn test_05_stream_hash_empty_matches_python_pin() {
    let h = stream_hash(&[]).expect("hash");
    assert_eq!(h, F1_STREAM_PIN, "empty-stream cross-language pin");
}

#[test]
fn test_06_stream_hash_single_record_matches_python_pin() {
    let h = stream_hash(&f2_stream()).expect("hash");
    assert_eq!(h, F2_STREAM_PIN, "single-record stream cross-language pin");
}

#[test]
fn test_07_stream_hash_three_record_session_matches_python_pin() {
    let h = stream_hash(&f3_stream()).expect("hash");
    assert_eq!(h, F3_STREAM_PIN, "3-record session cross-language pin");
}

#[test]
fn test_08_identical_streams_match_success_no_divergence() {
    let engine = ReplayEngine::new();
    let actual = f3_stream();
    let expected = ExpectedTrajectory::from_records(&actual);
    let report = engine.replay_stream(&actual, &expected).expect("replay");
    assert!(report.success, "identical streams should match");
    assert!(report.divergences.is_empty());
    assert_eq!(report.time_to_divergence_steps, None);
    assert_eq!(report.stream_hash_actual, F3_STREAM_PIN);
    assert_eq!(report.stream_hash_expected, F3_STREAM_PIN);
}

#[test]
fn test_09_single_step_value_mismatch_detected_at_expected_index() {
    let engine = ReplayEngine::new();
    let expected_records = f3_stream();
    let expected = ExpectedTrajectory::from_records(&expected_records);

    // Drift step-1's output_kind from "reply" to "tool_call".
    let mut actual = expected_records.clone();
    actual[1].output_kind = "tool_call".to_string();

    let report = engine.replay_stream(&actual, &expected).expect("replay");
    assert!(!report.success, "drift should surface");
    assert_eq!(report.divergences.len(), 1);
    assert_eq!(report.time_to_divergence_steps, Some(1));
    let d = &report.divergences[0];
    assert_eq!(d.step_index, 1);
    assert_eq!(d.kind, DivergenceKind::ValueMismatch);
    assert!(d.expected.is_some() && d.actual.is_some());
    assert!(
        !d.field_diffs.is_empty(),
        "field_diffs should pinpoint output_kind"
    );
    // The output_kind field should be in the field_diffs (RFC-6901 path
    // is "/output_kind" at the envelope root).
    assert!(d.field_diffs.iter().any(|fd| fd.path == "/output_kind"));
}

#[test]
fn test_10_missing_record_detection_actual_too_short() {
    let engine = ReplayEngine::new();
    let expected = ExpectedTrajectory::from_records(&f3_stream());
    let actual = vec![f3_stream()[0].clone()]; // 1 of 3
    let report = engine.replay_stream(&actual, &expected).expect("replay");
    assert!(!report.success);
    assert_eq!(report.divergences.len(), 2, "step-1 + step-2 missing");
    assert_eq!(report.time_to_divergence_steps, Some(1));
    for (i, d) in report.divergences.iter().enumerate() {
        let step = i + 1;
        assert_eq!(d.step_index, step);
        assert_eq!(d.kind, DivergenceKind::MissingInActual);
        assert!(d.expected.is_some());
        assert!(d.actual.is_none());
    }
}

#[test]
fn test_11_extra_record_detection_actual_too_long() {
    let engine = ReplayEngine::new();
    let expected_records = vec![f3_stream()[0].clone()]; // 1 expected
    let expected = ExpectedTrajectory::from_records(&expected_records);
    let actual = f3_stream(); // 3 actual
    let report = engine.replay_stream(&actual, &expected).expect("replay");
    assert!(!report.success);
    assert_eq!(report.divergences.len(), 2, "step-1 + step-2 extra");
    assert_eq!(report.time_to_divergence_steps, Some(1));
    for (i, d) in report.divergences.iter().enumerate() {
        let step = i + 1;
        assert_eq!(d.step_index, step);
        assert_eq!(d.kind, DivergenceKind::ExtraInActual);
        assert!(d.expected.is_none());
        assert!(d.actual.is_some());
    }
}

#[test]
fn test_12_time_to_divergence_monotonic_when_earlier_step_corrected() {
    let engine = ReplayEngine::new();
    let expected = ExpectedTrajectory::from_records(&f3_stream());

    // Stream A: drift at step 0 -> ttd = 0.
    let mut a = f3_stream();
    a[0].output_kind = "audit_annotation".to_string();
    a[1].output_kind = "audit_annotation".to_string();
    let r_a = engine.replay_stream(&a, &expected).expect("replay");
    assert_eq!(r_a.time_to_divergence_steps, Some(0));

    // Stream B: step 0 corrected, drift now starts at step 1 -> ttd = 1.
    let mut b = f3_stream();
    b[1].output_kind = "audit_annotation".to_string();
    let r_b = engine.replay_stream(&b, &expected).expect("replay");
    assert_eq!(r_b.time_to_divergence_steps, Some(1));

    // Stream C: step 0 + 1 corrected, drift only at step 2 -> ttd = 2.
    let mut c = f3_stream();
    c[2].output_kind = "audit_annotation".to_string();
    let r_c = engine.replay_stream(&c, &expected).expect("replay");
    assert_eq!(r_c.time_to_divergence_steps, Some(2));

    // Monotonic non-decreasing across the correction sequence.
    let seq = [
        r_a.time_to_divergence_steps.unwrap(),
        r_b.time_to_divergence_steps.unwrap(),
        r_c.time_to_divergence_steps.unwrap(),
    ];
    assert!(seq.windows(2).all(|w| w[0] <= w[1]), "ttd monotonic");
}

#[test]
fn test_13_replay_determinism_repeated_runs_bit_identical() {
    // Same input -> same stream_hash, same divergence set, same ttd.
    let engine = ReplayEngine::new();
    let expected = ExpectedTrajectory::from_records(&f3_stream());
    let mut actual = f3_stream();
    actual[1].ts_utc = "2026-05-17T10:00:99Z".to_string();

    let r1 = engine.replay_stream(&actual, &expected).expect("replay-1");
    let r2 = engine.replay_stream(&actual, &expected).expect("replay-2");
    let r3 = engine.replay_stream(&actual, &expected).expect("replay-3");

    assert_eq!(r1.stream_hash_actual, r2.stream_hash_actual);
    assert_eq!(r2.stream_hash_actual, r3.stream_hash_actual);
    assert_eq!(r1.stream_hash_expected, r2.stream_hash_expected);
    assert_eq!(r1.time_to_divergence_steps, r2.time_to_divergence_steps);
    assert_eq!(r2.time_to_divergence_steps, r3.time_to_divergence_steps);
    assert_eq!(r1.divergences.len(), r2.divergences.len());
    assert_eq!(r2.divergences.len(), r3.divergences.len());
    assert_eq!(r1.divergences[0].kind, r2.divergences[0].kind);
}

#[test]
fn test_14_summary_formatting_parity() {
    let engine = ReplayEngine::new();
    let expected = ExpectedTrajectory::from_records(&f3_stream());

    // Success branch.
    let r_ok = engine
        .replay_stream(&f3_stream(), &expected)
        .expect("replay");
    let s_ok = r_ok.summary();
    assert!(s_ok.starts_with("replay-ok"));
    assert!(s_ok.contains("records=3"));
    assert!(s_ok.contains("stream_hash=sha256:"));

    // Drift branch.
    let mut actual = f3_stream();
    actual[0].output_kind = "audit_annotation".to_string();
    let r_drift = engine.replay_stream(&actual, &expected).expect("replay");
    let s_drift = r_drift.summary();
    assert!(s_drift.starts_with("replay-drift"));
    assert!(s_drift.contains("first_step=0"));
    assert!(s_drift.contains("divergences=1"));
}
