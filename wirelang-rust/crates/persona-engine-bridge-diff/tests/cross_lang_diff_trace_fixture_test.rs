// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Cross-lang fixture parity tests for persona-engine-bridge-diff
// canonical-trace (Tag-36 Mini-Welle Phase-3a Python-sync, 13. Modul).
//
// These tests consume the same authoritative JSON fixture file
// (`tests/fixtures/bridge-audit-diff-engine-cross-lang/fixtures.json`
// at the repo root) that the Python sibling test
// (`wirelang/tests/persona_engine/test_bridge_audit_diff_engine_cross_lang_parity.py`)
// consumes. Both sides pin the same trace-JCS-bytes / trace-SHA-256
// tuples, so any drift on either side breaks both test suites — that
// is the intended boundary detector.
//
// The fixture file path is computed from the `CARGO_MANIFEST_DIR`
// env-var at build time and walks up to the repo root.
//
// Test taxonomy
// -------------
// - F01 — Constants pin: `BRIDGE_DIFF_TRACE_SCHEMA`, `HASH_PREFIX`,
//   `SHA256_HEX_LEN`, summary separators, DiffKind alphabet.
// - F02 — Fixture file loads, schema_version matches the
//   `BRIDGE_DIFF_TRACE_SCHEMA` constant, exactly 6 vectors present.
// - F03 — Per-vector trace-build pin: byte-level parity for envelope
//   JSON decode, byte_identical flag, drift_count, field_diffs_summary,
//   jcs_hash_a, jcs_hash_b, leaves_total, score_milli, trace JCS bytes,
//   trace JCS bytes length, bare hex hash, prefixed hash.
// - F04 — Wire-shape key order (alphabetical, 8 keys), tested on a
//   trace-build outcome.
// - F05 — Hash-shape pin (length, lowercase, hex alphabet, prefix).
// - F06 — Determinism: two builds of the same envelope pair produce
//   byte-identical traces.
// - F07 — Byte-identical fast-path: score_milli == 1000 iff
//   byte_identical, drift_count == 0 iff byte_identical, summary == ""
//   iff byte_identical.
// - F08 — `build_trace_from_report` byte-identical to
//   `build_bridge_diff_trace` on the same envelope pair.

use persona_engine_bridge_diff::canonical::{
    build_bridge_diff_trace, build_trace_from_report, serialize_trace, trace_hash_prefixed,
    trace_sha256_hex, BRIDGE_DIFF_TRACE_SCHEMA, HASH_PREFIX, KIND_ONLY_IN_A, KIND_ONLY_IN_B,
    KIND_TYPE_MISMATCH, KIND_VALUE_MISMATCH, SHA256_HEX_LEN, SUMMARY_ENTRY_SEP,
    SUMMARY_PATH_KIND_SEP,
};
use persona_engine_bridge_diff::{compare_implementations, DiffInput};
use serde_json::Value;
use std::path::PathBuf;

// ---------------------------------------------------------------------
// Inline base64 decoder (RFC 4648 standard alphabet, no line breaks).
// Identical pattern to the v907-verify / frontmatter-parser sibling
// fixture tests.
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
        .join("bridge-audit-diff-engine-cross-lang")
        .join("fixtures.json")
}

fn load_fixtures() -> Value {
    let p = fixture_path();
    let body = std::fs::read_to_string(&p).unwrap_or_else(|e| {
        panic!(
            "failed to read cross-lang fixture file at {}: {e}; \
             run the Python emitter `python3 /tmp/gen_bridge_diff_fixtures.py` \
             (or the Phase-3a fixture regeneration script) to rebuild it",
            p.display()
        )
    });
    serde_json::from_str(&body).expect("fixture file MUST parse as JSON")
}

// ---------------------------------------------------------------------
// F01 — constants pin.
// ---------------------------------------------------------------------

#[test]
fn f01_constants_pin() {
    assert_eq!(
        BRIDGE_DIFF_TRACE_SCHEMA,
        "wakir.persona-engine.bridge-audit-diff-canonical/1"
    );
    assert_eq!(HASH_PREFIX, "sha256:");
    assert_eq!(SHA256_HEX_LEN, 64);
    assert_eq!(SUMMARY_ENTRY_SEP, ';');
    assert_eq!(SUMMARY_PATH_KIND_SEP, '|');
    assert_eq!(KIND_VALUE_MISMATCH, "value-mismatch");
    assert_eq!(KIND_ONLY_IN_A, "only-in-a");
    assert_eq!(KIND_ONLY_IN_B, "only-in-b");
    assert_eq!(KIND_TYPE_MISMATCH, "type-mismatch");
}

// ---------------------------------------------------------------------
// F02 — fixture file structure pin.
// ---------------------------------------------------------------------

#[test]
fn f02_fixture_file_structure_pin() {
    let doc = load_fixtures();
    assert_eq!(
        doc["schema_version"].as_str(),
        Some(BRIDGE_DIFF_TRACE_SCHEMA),
        "fixture schema_version must match canonical schema id"
    );
    let fixtures = doc["fixtures"]
        .as_array()
        .expect("fixtures must be an array");
    assert_eq!(
        fixtures.len(),
        6,
        "Tag-36 cross-lang vector count is 6 (1 byte-identical + 5 drift paths)"
    );
    for f in fixtures {
        let f_obj = f.as_object().expect("fixture entry must be object");
        for key in ["name", "input_envelope_a_json", "input_envelope_b_json", "expected"] {
            assert!(
                f_obj.contains_key(key),
                "fixture {:?} missing top-level key {key:?}",
                f_obj.get("name")
            );
        }
        let expected = f["expected"].as_object().expect("expected object");
        for key in [
            "byte_identical",
            "drift_count",
            "field_diffs_summary",
            "jcs_hash_a",
            "jcs_hash_b",
            "leaves_total",
            "score_milli",
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
// F03 — per-vector byte-parity pin.
// ---------------------------------------------------------------------

fn parse_envelope(s: &str) -> Value {
    serde_json::from_str(s).expect("envelope JSON must parse")
}

fn run_vector(idx: usize) {
    let doc = load_fixtures();
    let fixtures = doc["fixtures"].as_array().unwrap();
    let vec_ = &fixtures[idx];
    let name = vec_["name"].as_str().unwrap();
    let env_a = parse_envelope(vec_["input_envelope_a_json"].as_str().unwrap());
    let env_b = parse_envelope(vec_["input_envelope_b_json"].as_str().unwrap());
    let expected = &vec_["expected"];

    let trace = build_bridge_diff_trace(&env_a, &env_b)
        .unwrap_or_else(|e| panic!("{name}: build_bridge_diff_trace failed: {e}"));

    // Structured fields.
    assert_eq!(
        trace.byte_identical,
        expected["byte_identical"].as_bool().unwrap(),
        "{name}: byte_identical drift"
    );
    assert_eq!(
        u64::from(trace.drift_count),
        expected["drift_count"].as_u64().unwrap(),
        "{name}: drift_count drift"
    );
    assert_eq!(
        trace.field_diffs_summary,
        expected["field_diffs_summary"].as_str().unwrap(),
        "{name}: field_diffs_summary drift"
    );
    assert_eq!(
        trace.jcs_hash_a,
        expected["jcs_hash_a"].as_str().unwrap(),
        "{name}: jcs_hash_a drift"
    );
    assert_eq!(
        trace.jcs_hash_b,
        expected["jcs_hash_b"].as_str().unwrap(),
        "{name}: jcs_hash_b drift"
    );
    assert_eq!(
        u64::from(trace.leaves_total),
        expected["leaves_total"].as_u64().unwrap(),
        "{name}: leaves_total drift"
    );
    assert_eq!(
        u64::from(trace.score_milli),
        expected["score_milli"].as_u64().unwrap(),
        "{name}: score_milli drift"
    );

    // Byte-level.
    let jcs_actual = serialize_trace(&trace).expect("serialize trace");
    let jcs_expected = b64_decode(expected["trace_jcs_bytes_b64"].as_str().unwrap());
    assert_eq!(jcs_actual, jcs_expected, "{name}: JCS bytes drift");
    assert_eq!(
        jcs_actual.len() as u64,
        expected["trace_jcs_bytes_len"].as_u64().unwrap(),
        "{name}: JCS bytes length drift"
    );
    assert_eq!(
        trace_sha256_hex(&trace).unwrap(),
        expected["trace_sha256_hex"].as_str().unwrap(),
        "{name}: trace SHA-256 hex drift"
    );
    assert_eq!(
        trace_hash_prefixed(&trace).unwrap(),
        expected["trace_hash_prefixed"].as_str().unwrap(),
        "{name}: trace prefixed hash drift"
    );
}

#[test]
fn f03_vector_00_byte_identical() {
    run_vector(0);
}

#[test]
fn f03_vector_01_value_mismatch() {
    run_vector(1);
}

#[test]
fn f03_vector_02_only_in_a() {
    run_vector(2);
}

#[test]
fn f03_vector_03_only_in_b() {
    run_vector(3);
}

#[test]
fn f03_vector_04_type_mismatch() {
    run_vector(4);
}

#[test]
fn f03_vector_05_multi_field_rfc6901() {
    run_vector(5);
}

// ---------------------------------------------------------------------
// F04 — wire-shape key order pin.
// ---------------------------------------------------------------------

#[test]
fn f04_wire_keys_alphabetical() {
    let env_a = serde_json::json!({"a": 1});
    let env_b = serde_json::json!({"a": 2});
    let trace = build_bridge_diff_trace(&env_a, &env_b).unwrap();
    let jcs = serialize_trace(&trace).unwrap();
    let parsed: Value = serde_json::from_slice(&jcs).expect("JCS bytes must parse back as JSON");
    let obj = parsed.as_object().expect("top-level must be object");
    let keys: Vec<&String> = obj.keys().collect();
    let mut sorted_keys = keys.clone();
    sorted_keys.sort();
    assert_eq!(keys, sorted_keys, "JCS keys must be alphabetical");
    let expected_keys: std::collections::BTreeSet<&str> = [
        "byte_identical",
        "drift_count",
        "field_diffs_summary",
        "jcs_hash_a",
        "jcs_hash_b",
        "leaves_total",
        "schema",
        "score_milli",
    ]
    .into_iter()
    .collect();
    let actual_keys: std::collections::BTreeSet<&str> = obj.keys().map(String::as_str).collect();
    assert_eq!(actual_keys, expected_keys, "wire key set drifted");
}

// ---------------------------------------------------------------------
// F05 — hash-shape pin.
// ---------------------------------------------------------------------

#[test]
fn f05_hash_shape_pin() {
    let env = serde_json::json!({"x": "y"});
    let trace = build_bridge_diff_trace(&env, &env).unwrap();
    let bare = trace_sha256_hex(&trace).unwrap();
    let prefixed = trace_hash_prefixed(&trace).unwrap();
    assert_eq!(bare.len(), SHA256_HEX_LEN);
    assert_eq!(bare, bare.to_lowercase());
    assert!(bare.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()));
    assert_eq!(prefixed, format!("{HASH_PREFIX}{bare}"));
}

// ---------------------------------------------------------------------
// F06 — determinism.
// ---------------------------------------------------------------------

#[test]
fn f06_build_is_deterministic() {
    let env_a = serde_json::json!({"k": [1, 2, {"nested": true}]});
    let env_b = serde_json::json!({"k": [1, 2, {"nested": false}]});
    let t1 = build_bridge_diff_trace(&env_a, &env_b).unwrap();
    let t2 = build_bridge_diff_trace(&env_a, &env_b).unwrap();
    assert_eq!(t1, t2);
    assert_eq!(serialize_trace(&t1).unwrap(), serialize_trace(&t2).unwrap());
    assert_eq!(trace_sha256_hex(&t1).unwrap(), trace_sha256_hex(&t2).unwrap());
}

// ---------------------------------------------------------------------
// F07 — byte-identical fast-path invariants.
// ---------------------------------------------------------------------

#[test]
fn f07_byte_identical_fast_path_invariants() {
    let doc = load_fixtures();
    let fixtures = doc["fixtures"].as_array().unwrap();
    let mut identical_seen = 0;
    let mut drift_seen = 0;
    for f in fixtures {
        let expected = &f["expected"];
        let byte_id = expected["byte_identical"].as_bool().unwrap();
        let drift = expected["drift_count"].as_u64().unwrap();
        let score = expected["score_milli"].as_u64().unwrap();
        let summary = expected["field_diffs_summary"].as_str().unwrap();
        if byte_id {
            identical_seen += 1;
            assert_eq!(drift, 0, "{}: drift_count must be 0 on byte-identical", f["name"]);
            assert_eq!(score, 1000, "{}: score_milli must be 1000 on byte-identical", f["name"]);
            assert_eq!(summary, "", "{}: summary must be empty on byte-identical", f["name"]);
        } else {
            drift_seen += 1;
            assert!(drift >= 1, "{}: drift_count must be >= 1 on drift path", f["name"]);
            assert!(score < 1000, "{}: score_milli must be < 1000 on drift path", f["name"]);
            assert!(!summary.is_empty(), "{}: summary must be non-empty on drift path", f["name"]);
        }
    }
    assert!(identical_seen >= 1, "expected at least 1 byte-identical fixture");
    assert!(drift_seen >= 4, "expected at least 4 drift-path fixtures");
}

// ---------------------------------------------------------------------
// F08 — build_trace_from_report byte-identical to build_bridge_diff_trace.
// ---------------------------------------------------------------------

#[test]
fn f08_from_report_matches_direct_build() {
    let env_a = serde_json::json!({
        "schema": "wakir.persona-engine.engineering-output/1",
        "step_index": 5,
        "payload": "alpha"
    });
    let env_b = serde_json::json!({
        "schema": "wakir.persona-engine.engineering-output/1",
        "step_index": 5,
        "payload": "beta"
    });

    // build_bridge_diff_trace direct path.
    let direct = build_bridge_diff_trace(&env_a, &env_b).unwrap();

    // build_trace_from_report via the live DiffReport. We use closure
    // adapters that ignore the DiffInput and return the fixed envelopes.
    let env_a_owned = env_a.clone();
    let env_b_owned = env_b.clone();
    let impl_a = move |_: &DiffInput| env_a_owned.clone();
    let impl_b = move |_: &DiffInput| env_b_owned.clone();
    let report = compare_implementations(
        &DiffInput {
            org_id: "wakir-labs".to_string(),
            persona_id: "reza".to_string(),
            session_id: "tag-36".to_string(),
            step_index: 5,
            output_kind: "tool_call".to_string(),
            payload: Vec::new(),
            ts_utc: "2026-05-18T00:00:00Z".to_string(),
        },
        &impl_a,
        &impl_b,
    )
    .expect("compare succeeds");

    let from_report = build_trace_from_report(&report);
    assert_eq!(direct, from_report);
    assert_eq!(
        serialize_trace(&direct).unwrap(),
        serialize_trace(&from_report).unwrap()
    );
}
