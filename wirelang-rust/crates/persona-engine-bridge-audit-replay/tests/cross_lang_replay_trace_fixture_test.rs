// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Cross-lang fixture parity tests for persona-engine-bridge-audit-replay
// canonical-trace (Tag-37 Mini-Welle Phase-3a Python-sync, 14. Modul).
//
// These tests consume the same authoritative JSON fixture file
// (`tests/fixtures/bridge-audit-replay-cross-lang/fixtures.json` at the
// repo root) that the Python sibling test
// (`wirelang/tests/persona_engine/test_bridge_audit_replay_cross_lang_parity.py`)
// consumes.  Both sides pin the same trace-JCS-bytes / trace-SHA-256
// tuples, so any drift on either side breaks both test suites — that
// is the intended boundary detector.
//
// The fixture file path is computed from the `CARGO_MANIFEST_DIR`
// env-var at build time and walks up to the repo root.
//
// Test taxonomy
// -------------
// - F01 — Constants pin: `REPLAY_TRACE_SCHEMA`, `HASH_PREFIX`,
//   `SHA256_HEX_LEN`, `DIVERGENCE_NONE_SENTINEL`, summary separators,
//   DivergenceKind alphabet.
// - F02 — Fixture file loads, schema_version matches the
//   `REPLAY_TRACE_SCHEMA` constant, exactly 6 vectors present, and
//   per-vector keys are present.
// - F03 — Per-vector trace-build pin: byte-level parity for stream
//   decode, success-flag, actual/expected counts,
//   divergence_first_step, divergence_first_kind, divergences_summary,
//   stream_hash_actual, stream_hash_expected, trace JCS bytes, trace
//   JCS bytes length, bare hex hash, prefixed hash.
// - F04 — Wire-shape key order (alphabetical, 9 keys).
// - F05 — Hash-shape pin (length, lowercase, hex alphabet, prefix).
// - F06 — Determinism: two builds of the same input produce
//   byte-identical traces.
// - F07 — Success-path invariants: success iff
//   `divergence_first_step == DIVERGENCE_NONE_SENTINEL` iff
//   `divergence_first_kind == ""` iff `divergences_summary == ""`.
// - F08 — `build_trace_from_report` byte-identical to
//   `build_replay_trace` on the same input.
// - F09 — Live-engine cross-check: trace's stream-hash fields ==
//   live `stream_hash(records)` output for both actual and expected.
// - F10 — Divergence-kind coverage: all three kinds surface across
//   the fixture set.

use persona_engine_bridge_audit_replay::canonical::{
    build_replay_trace, build_trace_from_report, serialize_trace, trace_hash_prefixed,
    trace_sha256_hex, ReplayTrace, DIVERGENCE_NONE_SENTINEL, HASH_PREFIX,
    KIND_EXTRA_IN_ACTUAL, KIND_MISSING_IN_ACTUAL, KIND_VALUE_MISMATCH,
    REPLAY_TRACE_SCHEMA, SHA256_HEX_LEN, SUMMARY_ENTRY_SEP, SUMMARY_STEP_KIND_SEP,
};
use persona_engine_bridge_audit_replay::{
    stream_hash, AuditRecord, ExpectedTrajectory, ReplayEngine,
};
use serde_json::Value;
use std::path::PathBuf;

// ---------------------------------------------------------------------
// Inline base64 decoder (RFC 4648 standard alphabet, no line breaks).
// Identical pattern to the Tag-36 / Tag-35 sibling fixture tests so
// the test suite has no extra deps beyond what the workspace already
// pulls in.
// ---------------------------------------------------------------------

fn b64_decode(input: &str) -> Vec<u8> {
    fn val(c: u8) -> Option<u8> {
        match c {
            b'A'..=b'Z' => Some(c - b'A'),
            b'a'..=b'z' => Some(c - b'a' + 26),
            b'0'..=b'9' => Some(c - b'0' + 52),
            b'+' => Some(62),
            b'/' => Some(63),
            _ => None,
        }
    }
    let bytes: Vec<u8> = input
        .bytes()
        .filter(|&b| !b.is_ascii_whitespace())
        .collect();
    let mut out: Vec<u8> = Vec::with_capacity(bytes.len() * 3 / 4 + 3);
    let mut buf: u32 = 0;
    let mut bits: u8 = 0;
    for &c in &bytes {
        if c == b'=' {
            break;
        }
        let v = val(c).unwrap_or_else(|| {
            panic!(
                "invalid base64 character: {:?} in input {:?}",
                c as char, input
            )
        });
        buf = (buf << 6) | u32::from(v);
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push(((buf >> bits) & 0xff) as u8);
        }
    }
    out
}

fn fixture_path() -> PathBuf {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest
        .parent() // wirelang-rust/crates
        .and_then(|p| p.parent()) // wirelang-rust
        .and_then(|p| p.parent()) // repo root
        .expect("walk from crate dir to repo root succeeds");
    repo_root
        .join("tests")
        .join("fixtures")
        .join("bridge-audit-replay-cross-lang")
        .join("fixtures.json")
}

fn load_fixtures() -> Value {
    let p = fixture_path();
    let body = std::fs::read_to_string(&p).unwrap_or_else(|e| {
        panic!(
            "failed to read cross-lang fixture file at {}: {e}; \
             run the Python emitter \
             `python3 scripts/derive-bridge-audit-replay-fixtures.py` \
             from the repo root to rebuild it",
            p.display()
        )
    });
    serde_json::from_str(&body).expect("fixture file MUST parse as JSON")
}

fn decode_stream(b64: &str) -> Vec<AuditRecord> {
    let bytes = b64_decode(b64);
    let v: Value = serde_json::from_slice(&bytes).expect("stream JSON parses");
    let arr = v["stream"].as_array().expect("stream key must be array");
    arr.iter()
        .map(|env| AuditRecord {
            org_id: env["org_id"].as_str().unwrap().to_string(),
            persona_id: env["persona_id"].as_str().unwrap().to_string(),
            session_id: env["session_id"].as_str().unwrap().to_string(),
            step_index: env["step_index"].as_u64().unwrap() as u32,
            output_kind: env["output_kind"].as_str().unwrap().to_string(),
            output_payload_sha256: env["output_payload_sha256"]
                .as_str()
                .unwrap()
                .to_string(),
            engine_version: env["engine_version"].as_str().unwrap().to_string(),
            v907_pin: env["v907_pin"].as_str().unwrap().to_string(),
            ts_utc: env["ts_utc"].as_str().unwrap().to_string(),
        })
        .collect()
}

// ---------------------------------------------------------------------
// F01 — constants pin.
// ---------------------------------------------------------------------

#[test]
fn f01_constants_pin() {
    assert_eq!(
        REPLAY_TRACE_SCHEMA,
        "wakir.persona-engine.bridge-audit-replay-canonical/1"
    );
    assert_eq!(HASH_PREFIX, "sha256:");
    assert_eq!(SHA256_HEX_LEN, 64);
    assert_eq!(DIVERGENCE_NONE_SENTINEL, -1);
    assert_eq!(SUMMARY_ENTRY_SEP, ";");
    assert_eq!(SUMMARY_STEP_KIND_SEP, "|");
    assert_eq!(KIND_VALUE_MISMATCH, "value-mismatch");
    assert_eq!(KIND_MISSING_IN_ACTUAL, "missing-in-actual");
    assert_eq!(KIND_EXTRA_IN_ACTUAL, "extra-in-actual");
}

// ---------------------------------------------------------------------
// F02 — fixture file structure pin.
// ---------------------------------------------------------------------

#[test]
fn f02_fixture_file_structure_pin() {
    let doc = load_fixtures();
    assert_eq!(
        doc["schema_version"].as_str(),
        Some(REPLAY_TRACE_SCHEMA),
        "fixture schema_version must match canonical schema id"
    );
    let fixtures = doc["fixtures"]
        .as_array()
        .expect("fixtures must be an array");
    assert_eq!(
        fixtures.len(),
        6,
        "Tag-37 cross-lang vector count is 6 (3 success-paths + 3 drift-kinds)"
    );
    for f in fixtures {
        let f_obj = f.as_object().expect("fixture entry must be object");
        for key in ["name", "input_actual_b64", "input_expected_b64", "expected"] {
            assert!(
                f_obj.contains_key(key),
                "fixture {:?} missing top-level key {key:?}",
                f_obj.get("name")
            );
        }
        let expected = f["expected"].as_object().expect("expected object");
        for key in [
            "actual_record_count",
            "divergence_first_kind",
            "divergence_first_step",
            "divergences_summary",
            "expected_record_count",
            "stream_hash_actual",
            "stream_hash_expected",
            "success",
            "trace_jcs_bytes_b64",
            "trace_jcs_bytes_len",
            "trace_sha256_hex",
            "trace_hash_prefixed",
        ] {
            assert!(
                expected.contains_key(key),
                "fixture {:?} expected missing key {key:?}",
                f_obj.get("name")
            );
        }
    }
}

// ---------------------------------------------------------------------
// F03 — per-vector byte-parity pin (the core cross-lang anchor).
// ---------------------------------------------------------------------

fn run_vector(idx: usize) {
    let doc = load_fixtures();
    let fixtures = doc["fixtures"].as_array().unwrap();
    let vec_ = &fixtures[idx];
    let name = vec_["name"].as_str().unwrap();

    let actual = decode_stream(vec_["input_actual_b64"].as_str().unwrap());
    let expected_recs = decode_stream(vec_["input_expected_b64"].as_str().unwrap());
    let expected = ExpectedTrajectory::from_records(&expected_recs);
    let pinned = &vec_["expected"];

    let trace =
        build_replay_trace(&actual, &expected).unwrap_or_else(|e| panic!("{name}: {e}"));

    // Structured fields.
    assert_eq!(
        trace.actual_record_count,
        pinned["actual_record_count"].as_u64().unwrap(),
        "{name}: actual_record_count drift"
    );
    assert_eq!(
        trace.divergence_first_kind,
        pinned["divergence_first_kind"].as_str().unwrap(),
        "{name}: divergence_first_kind drift"
    );
    assert_eq!(
        trace.divergence_first_step,
        pinned["divergence_first_step"].as_i64().unwrap(),
        "{name}: divergence_first_step drift"
    );
    assert_eq!(
        trace.divergences_summary,
        pinned["divergences_summary"].as_str().unwrap(),
        "{name}: divergences_summary drift"
    );
    assert_eq!(
        trace.expected_record_count,
        pinned["expected_record_count"].as_u64().unwrap(),
        "{name}: expected_record_count drift"
    );
    assert_eq!(
        trace.stream_hash_actual,
        pinned["stream_hash_actual"].as_str().unwrap(),
        "{name}: stream_hash_actual drift"
    );
    assert_eq!(
        trace.stream_hash_expected,
        pinned["stream_hash_expected"].as_str().unwrap(),
        "{name}: stream_hash_expected drift"
    );
    assert_eq!(
        trace.success,
        pinned["success"].as_bool().unwrap(),
        "{name}: success drift"
    );

    // JCS bytes pin (the core cross-lang anchor).
    let bytes_actual = serialize_trace(&trace).expect("serialize_trace ok");
    let bytes_pinned = b64_decode(pinned["trace_jcs_bytes_b64"].as_str().unwrap());
    assert_eq!(
        bytes_actual, bytes_pinned,
        "{name}: trace JCS bytes drift"
    );
    assert_eq!(
        bytes_actual.len(),
        pinned["trace_jcs_bytes_len"].as_u64().unwrap() as usize,
        "{name}: trace JCS bytes length drift"
    );

    // Hash pins.
    let bare = trace_sha256_hex(&trace).unwrap();
    let prefixed = trace_hash_prefixed(&trace).unwrap();
    assert_eq!(
        bare,
        pinned["trace_sha256_hex"].as_str().unwrap(),
        "{name}: trace_sha256_hex drift"
    );
    assert_eq!(
        prefixed,
        pinned["trace_hash_prefixed"].as_str().unwrap(),
        "{name}: trace_hash_prefixed drift"
    );
}

#[test]
fn f03_v0_empty_streams_success() {
    run_vector(0);
}

#[test]
fn f03_v1_single_record_success() {
    run_vector(1);
}

#[test]
fn f03_v2_three_record_success() {
    run_vector(2);
}

#[test]
fn f03_v3_value_mismatch_at_step_1() {
    run_vector(3);
}

#[test]
fn f03_v4_missing_in_actual_at_step_2() {
    run_vector(4);
}

#[test]
fn f03_v5_extra_in_actual_at_step_3() {
    run_vector(5);
}

// ---------------------------------------------------------------------
// F04 — wire-shape key order pin.
// ---------------------------------------------------------------------

#[test]
fn f04_wire_shape_key_order_alphabetical_nine_keys() {
    // Build a trivial trace and dump its JCS bytes back to JSON; check
    // top-level key alphabetical order + key count.
    let rec = AuditRecord {
        org_id: "wakir-labs".into(),
        persona_id: "mira".into(),
        session_id: "f04".into(),
        step_index: 0,
        output_kind: "tool_call".into(),
        output_payload_sha256: format!("sha256:{}", "a".repeat(64)),
        engine_version: "0.2.0-pilot".into(),
        v907_pin: format!("sha256:{}", "b".repeat(64)),
        ts_utc: "2026-05-18T10:00:00Z".into(),
    };
    let actual = vec![rec.clone()];
    let expected = ExpectedTrajectory::from_records(&[rec]);
    let trace = build_replay_trace(&actual, &expected).unwrap();
    let bytes = serialize_trace(&trace).unwrap();
    let v: Value = serde_json::from_slice(&bytes).unwrap();
    let obj = v.as_object().expect("top-level object");
    let keys: Vec<&str> = obj.keys().map(String::as_str).collect();
    let mut sorted = keys.clone();
    sorted.sort();
    assert_eq!(keys, sorted, "top-level keys must be alphabetically sorted");
    assert_eq!(keys.len(), 9, "trace wire shape has exactly 9 keys");
    assert_eq!(
        keys,
        vec![
            "actual_record_count",
            "divergence_first_kind",
            "divergence_first_step",
            "divergences_summary",
            "expected_record_count",
            "schema",
            "stream_hash_actual",
            "stream_hash_expected",
            "success",
        ]
    );
}

// ---------------------------------------------------------------------
// F05 — hash-shape pin.
// ---------------------------------------------------------------------

#[test]
fn f05_hash_shape_prefixed_and_bare() {
    let rec = AuditRecord {
        org_id: "wakir-labs".into(),
        persona_id: "mira".into(),
        session_id: "f05".into(),
        step_index: 0,
        output_kind: "tool_call".into(),
        output_payload_sha256: format!("sha256:{}", "a".repeat(64)),
        engine_version: "0.2.0-pilot".into(),
        v907_pin: format!("sha256:{}", "b".repeat(64)),
        ts_utc: "2026-05-18T10:00:00Z".into(),
    };
    let actual = vec![rec.clone()];
    let expected = ExpectedTrajectory::from_records(&[rec]);
    let trace = build_replay_trace(&actual, &expected).unwrap();
    let bare = trace_sha256_hex(&trace).unwrap();
    let prefixed = trace_hash_prefixed(&trace).unwrap();
    assert_eq!(prefixed, format!("{HASH_PREFIX}{bare}"));
    assert_eq!(bare.len(), SHA256_HEX_LEN);
    assert!(bare.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit()));
    assert!(bare.chars().all(|c| "0123456789abcdef".contains(c)));
}

// ---------------------------------------------------------------------
// F06 — determinism.
// ---------------------------------------------------------------------

#[test]
fn f06_determinism_two_builds_byte_identical() {
    let rec0 = AuditRecord {
        org_id: "wakir-labs".into(),
        persona_id: "mira".into(),
        session_id: "f06".into(),
        step_index: 0,
        output_kind: "tool_call".into(),
        output_payload_sha256: format!("sha256:{}", "a".repeat(64)),
        engine_version: "0.2.0-pilot".into(),
        v907_pin: format!("sha256:{}", "b".repeat(64)),
        ts_utc: "2026-05-18T10:00:00Z".into(),
    };
    let rec1 = AuditRecord {
        step_index: 1,
        output_kind: "reply".into(),
        output_payload_sha256: format!("sha256:{}", "c".repeat(64)),
        ..rec0.clone()
    };
    let actual = vec![rec0.clone(), rec1.clone()];
    let expected = ExpectedTrajectory::from_records(&[rec0, rec1]);
    let t1 = build_replay_trace(&actual, &expected).unwrap();
    let t2 = build_replay_trace(&actual, &expected).unwrap();
    assert_eq!(serialize_trace(&t1).unwrap(), serialize_trace(&t2).unwrap());
    assert_eq!(trace_sha256_hex(&t1).unwrap(), trace_sha256_hex(&t2).unwrap());
}

// ---------------------------------------------------------------------
// F07 — success-path invariants on the fixture set.
// ---------------------------------------------------------------------

#[test]
fn f07_success_iff_sentinels_fixture_set() {
    let doc = load_fixtures();
    let fixtures = doc["fixtures"].as_array().unwrap();
    for f in fixtures {
        let name = f["name"].as_str().unwrap();
        let e = &f["expected"];
        let s = e["success"].as_bool().unwrap();
        let first_step = e["divergence_first_step"].as_i64().unwrap();
        let first_kind = e["divergence_first_kind"].as_str().unwrap();
        let summary = e["divergences_summary"].as_str().unwrap();
        assert_eq!(
            s,
            first_step == DIVERGENCE_NONE_SENTINEL,
            "{name}: success vs first_step sentinel"
        );
        assert_eq!(s, first_kind.is_empty(), "{name}: success vs first_kind");
        assert_eq!(s, summary.is_empty(), "{name}: success vs summary");
    }
}

// ---------------------------------------------------------------------
// F08 — build_trace_from_report byte-identical to build_replay_trace.
// ---------------------------------------------------------------------

#[test]
fn f08_build_trace_from_report_byte_identical() {
    let doc = load_fixtures();
    let fixtures = doc["fixtures"].as_array().unwrap();
    for f in fixtures {
        let name = f["name"].as_str().unwrap();
        let actual = decode_stream(f["input_actual_b64"].as_str().unwrap());
        let expected_recs = decode_stream(f["input_expected_b64"].as_str().unwrap());
        let expected = ExpectedTrajectory::from_records(&expected_recs);
        let direct =
            build_replay_trace(&actual, &expected).expect("build_replay_trace ok");
        let report = ReplayEngine::new()
            .replay_stream(&actual, &expected)
            .expect("replay_stream ok");
        let from_report = build_trace_from_report(&report);
        assert_eq!(
            serialize_trace(&direct).unwrap(),
            serialize_trace(&from_report).unwrap(),
            "{name}: build_trace_from_report drift"
        );
    }
}

// ---------------------------------------------------------------------
// F09 — Live-engine stream-hash agreement.
// ---------------------------------------------------------------------

#[test]
fn f09_live_engine_stream_hash_agreement() {
    let doc = load_fixtures();
    let fixtures = doc["fixtures"].as_array().unwrap();
    for f in fixtures {
        let name = f["name"].as_str().unwrap();
        let actual = decode_stream(f["input_actual_b64"].as_str().unwrap());
        let expected_recs = decode_stream(f["input_expected_b64"].as_str().unwrap());
        let expected = ExpectedTrajectory::from_records(&expected_recs);
        let trace = build_replay_trace(&actual, &expected).unwrap();
        let live_actual = stream_hash(&actual).unwrap();
        let live_expected = stream_hash(&expected_recs).unwrap();
        assert_eq!(trace.stream_hash_actual, live_actual, "{name}: actual");
        assert_eq!(trace.stream_hash_expected, live_expected, "{name}: expected");
        let report = ReplayEngine::new()
            .replay_stream(&actual, &expected)
            .unwrap();
        assert_eq!(report.success, trace.success, "{name}: success agreement");
    }
}

// ---------------------------------------------------------------------
// F10 — Divergence-kind coverage.
// ---------------------------------------------------------------------

#[test]
fn f10_divergence_kind_coverage() {
    let doc = load_fixtures();
    let fixtures = doc["fixtures"].as_array().unwrap();
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    for f in fixtures {
        let e = &f["expected"];
        if !e["success"].as_bool().unwrap() {
            seen.insert(e["divergence_first_kind"].as_str().unwrap().to_string());
        }
    }
    let expected: std::collections::HashSet<String> = [
        KIND_VALUE_MISMATCH.to_string(),
        KIND_MISSING_IN_ACTUAL.to_string(),
        KIND_EXTRA_IN_ACTUAL.to_string(),
    ]
    .into_iter()
    .collect();
    assert_eq!(
        seen, expected,
        "fixture set must cover all 3 DivergenceKind values"
    );
}

#[test]
fn f10_first_kind_matches_summary_first_entry() {
    let doc = load_fixtures();
    let fixtures = doc["fixtures"].as_array().unwrap();
    for f in fixtures {
        let name = f["name"].as_str().unwrap();
        let e = &f["expected"];
        if e["success"].as_bool().unwrap() {
            assert_eq!(e["divergences_summary"].as_str().unwrap(), "");
            assert_eq!(e["divergence_first_kind"].as_str().unwrap(), "");
        } else {
            let summary = e["divergences_summary"].as_str().unwrap();
            let first_entry = summary.split(SUMMARY_ENTRY_SEP).next().unwrap();
            let mut parts = first_entry.split(SUMMARY_STEP_KIND_SEP);
            let step_str = parts.next().unwrap();
            let kind_str = parts.next().unwrap();
            assert_eq!(
                kind_str,
                e["divergence_first_kind"].as_str().unwrap(),
                "{name}: kind parity"
            );
            let parsed: i64 = step_str.parse().unwrap();
            assert_eq!(
                parsed,
                e["divergence_first_step"].as_i64().unwrap(),
                "{name}: step parity"
            );
        }
    }
}

// ---------------------------------------------------------------------
// Compile-time guard: ReplayTrace fields visible (signature pin).
// ---------------------------------------------------------------------

#[test]
fn compile_time_guard_replay_trace_field_visibility() {
    let t = ReplayTrace {
        actual_record_count: 1,
        divergence_first_kind: String::new(),
        divergence_first_step: DIVERGENCE_NONE_SENTINEL,
        divergences_summary: String::new(),
        expected_record_count: 1,
        stream_hash_actual: format!("{HASH_PREFIX}{}", "0".repeat(64)),
        stream_hash_expected: format!("{HASH_PREFIX}{}", "0".repeat(64)),
        success: true,
    };
    assert!(t.success);
}
