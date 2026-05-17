// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Cross-lang fixture parity tests for persona-engine-fsm canonical-trace
// (Tag-21 Mini-Welle, Phase-3a Python-sync — 7th module).
//
// These tests consume the same authoritative JSON fixture file
// (`tests/fixtures/lifecycle-state-machine-cross-lang/fixtures.json`
// at the repo root) that the Python sibling test
// (`wirelang/tests/persona_engine/test_lifecycle_state_machine_cross_lang_parity.py`)
// consumes. Both sides pin the same trace-JCS-bytes / trace-SHA-256
// tuples, so any drift on either side breaks both test suites — that
// is the intended boundary detector.
//
// The fixture file path is computed from the `CARGO_MANIFEST_DIR`
// env-var at build time and walks up to the repo root. This keeps
// the crate movable within the workspace without hard-coded paths.
//
// Test taxonomy
// -------------
// - F01 — Fixture file loads, schema_version matches the
//   `LIFECYCLE_TRACE_SCHEMA` constant, exactly 5 vectors present.
// - F02..F06 — Per-fixture byte-level pin: trace JCS bytes, bare-hex
//   outer hash, prefixed outer hash, byte length, derived
//   `final_state`, and the accepted/rejected record counts.
// - F07 — Inline base64 decoder sanity (the cross-lang test trusts
//   it).
// - F08 — Empty-history smoke (matches Python T16).
// - F09 — Accepted-record `reason` omission on the wire (mirrors
//   the `#[serde(skip_serializing_if = "Option::is_none")]` Python
//   contract).
//
// Base64 decoding strategy
// ------------------------
// The fixture file encodes byte fields as base64 (b64) so JSON
// remains text-only. Rather than add the `base64` crate as a
// dev-dependency we inline a small lookup-table decoder; identical
// pattern to the `persona-engine-subscribe-loop` Tag-19 PR #172
// fixture test.

use persona_engine_fsm::canonical::{
    build_lifecycle_trace_from_records, serialize_and_hash, serialize_trace,
    trace_hash_prefixed, trace_sha256_hex, LifecycleTrace, HASH_PREFIX,
    LIFECYCLE_TRACE_SCHEMA, SHA256_HEX_LEN,
};
use persona_engine_fsm::{FsmState, PersonaFsm, TransitionRecord};
use serde_json::Value;
use std::path::PathBuf;

// ---------------------------------------------------------------------
// Inline base64 decoder (RFC 4648 standard alphabet, no line breaks).
// Identical to the subscribe-loop sibling fixture test.
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
        buf = (buf << 6) | v as u32;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push(((buf >> bits) & 0xff) as u8);
        }
    }
    out
}

// ---------------------------------------------------------------------
// Fixture file path resolution.
// ---------------------------------------------------------------------

fn fixture_path() -> PathBuf {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest
        .parent() // wirelang-rust/crates
        .and_then(|p| p.parent()) // wirelang-rust
        .and_then(|p| p.parent()) // repo root
        .expect("CARGO_MANIFEST_DIR has the expected ancestor chain")
        .to_path_buf();
    repo_root
        .join("tests")
        .join("fixtures")
        .join("lifecycle-state-machine-cross-lang")
        .join("fixtures.json")
}

fn load_fixtures() -> Value {
    let path = fixture_path();
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("failed to read {:?}: {}", path, e));
    serde_json::from_str(&text).expect("fixture file is valid JSON")
}

// ---------------------------------------------------------------------
// Helper: materialise a fixture's transitions array as TransitionRecord
// instances. Mirrors the Python `_records_from_fixture` helper.
// ---------------------------------------------------------------------

fn records_from_fixture(fx: &Value) -> Vec<TransitionRecord> {
    let arr = fx["input"]["transitions"]
        .as_array()
        .expect("fixture.input.transitions is an array");
    arr.iter()
        .map(|t| {
            let from = t["from_state"].as_str().expect("from_state is string");
            let to = t["to_state"].as_str().expect("to_state is string");
            let accepted = t["accepted"].as_bool().expect("accepted is bool");
            let reason = match &t["reason"] {
                Value::Null => None,
                Value::String(s) => Some(s.clone()),
                other => panic!("reason must be null or string, got {:?}", other),
            };
            let ts_utc = t["ts_utc"].as_str().expect("ts_utc is string").to_string();
            TransitionRecord {
                from_state: FsmState::from_wire_str(from)
                    .expect("fixture from_state is a valid wire-string"),
                to_state: FsmState::from_wire_str(to)
                    .expect("fixture to_state is a valid wire-string"),
                ts_utc,
                accepted,
                reason,
            }
        })
        .collect()
}

// ---------------------------------------------------------------------
// F01 — Fixture file structure.
// ---------------------------------------------------------------------

#[test]
fn f01_fixture_file_structure_pin() {
    let fixtures = load_fixtures();
    assert_eq!(
        fixtures["schema_version"].as_str(),
        Some(LIFECYCLE_TRACE_SCHEMA)
    );
    assert_eq!(fixtures["fixed_ts_utc"].as_str(), Some("2026-05-17T00:00:00Z"));
    let items = fixtures["fixtures"]
        .as_array()
        .expect("fixtures is an array");
    assert_eq!(items.len(), 5);
    let names: Vec<&str> = items
        .iter()
        .map(|f| f["name"].as_str().unwrap())
        .collect();
    let expected = [
        "f01-clean-lifecycle",
        "f02-recovery-path",
        "f03-migration-path",
        "f04-spawn-cancel",
        "f05-rejected-attempt-then-clean",
    ];
    for e in &expected {
        assert!(
            names.contains(e),
            "fixture {:?} missing from file (got {:?})",
            e,
            names
        );
    }
    // Per-fixture key set pin.
    for f in items {
        let inp = &f["input"];
        for k in ["persona_id", "org_id", "initial_state", "transitions"] {
            assert!(
                inp.get(k).is_some(),
                "fixture {} missing input.{}",
                f["name"],
                k
            );
        }
        let exp = &f["expected"];
        for k in [
            "final_state",
            "record_count",
            "accepted_count",
            "rejected_count",
            "trace_jcs_bytes_b64",
            "trace_jcs_bytes_len",
            "trace_sha256_hex",
            "trace_hash_prefixed",
        ] {
            assert!(
                exp.get(k).is_some(),
                "fixture {} missing expected.{}",
                f["name"],
                k
            );
        }
    }
}

// ---------------------------------------------------------------------
// F02..F06 — Per-fixture byte-level pin. One #[test] per fixture so
// failures surface independently in the cargo-test output.
// ---------------------------------------------------------------------

fn run_fixture_byte_parity(fixture_name: &str) {
    let fixtures = load_fixtures();
    let items = fixtures["fixtures"].as_array().unwrap();
    let fx = items
        .iter()
        .find(|f| f["name"].as_str() == Some(fixture_name))
        .unwrap_or_else(|| panic!("fixture {:?} not found", fixture_name));

    let inp = &fx["input"];
    let exp = &fx["expected"];

    let persona_id = inp["persona_id"].as_str().unwrap();
    let org_id = inp["org_id"].as_str().unwrap();
    let initial_state = inp["initial_state"].as_str().unwrap();
    let records = records_from_fixture(fx);

    let trace =
        build_lifecycle_trace_from_records(persona_id, org_id, initial_state, &records)
            .expect("fixture inputs must build cleanly");

    // final_state derivation pin.
    assert_eq!(
        trace.final_state,
        exp["final_state"].as_str().unwrap(),
        "fixture {}: final_state drift",
        fixture_name
    );

    // record count breakdown pin.
    assert_eq!(
        trace.records.len() as u64,
        exp["record_count"].as_u64().unwrap(),
        "fixture {}: record_count drift",
        fixture_name
    );
    let accepted_n = trace.records.iter().filter(|r| r.accepted).count();
    let rejected_n = trace.records.iter().filter(|r| !r.accepted).count();
    assert_eq!(
        accepted_n as u64,
        exp["accepted_count"].as_u64().unwrap(),
        "fixture {}: accepted_count drift",
        fixture_name
    );
    assert_eq!(
        rejected_n as u64,
        exp["rejected_count"].as_u64().unwrap(),
        "fixture {}: rejected_count drift",
        fixture_name
    );

    // Canonical bytes pin.
    let bytes = serialize_trace(&trace);
    let exp_bytes = b64_decode(exp["trace_jcs_bytes_b64"].as_str().unwrap());
    assert_eq!(
        bytes,
        exp_bytes,
        "fixture {}: lifecycle-trace JCS bytes drifted (got {} bytes vs expected {})",
        fixture_name,
        bytes.len(),
        exp_bytes.len()
    );
    assert_eq!(
        bytes.len() as u64,
        exp["trace_jcs_bytes_len"].as_u64().unwrap(),
        "fixture {}: byte-length drift",
        fixture_name
    );

    // Bare-hex outer SHA-256 pin.
    let bare = trace_sha256_hex(&trace);
    assert_eq!(
        bare,
        exp["trace_sha256_hex"].as_str().unwrap(),
        "fixture {}: bare-hex outer SHA drift",
        fixture_name
    );

    // Prefixed-form outer SHA-256 pin.
    let prefixed = trace_hash_prefixed(&trace);
    assert_eq!(
        prefixed,
        exp["trace_hash_prefixed"].as_str().unwrap(),
        "fixture {}: prefixed-form outer SHA drift",
        fixture_name
    );

    // serialize_and_hash round-trip.
    let (rt_bytes, rt_hash) = serialize_and_hash(&trace);
    assert_eq!(rt_bytes, bytes);
    assert_eq!(rt_hash, prefixed);
}

#[test]
fn f02_clean_lifecycle_byte_parity() {
    run_fixture_byte_parity("f01-clean-lifecycle");
}

#[test]
fn f03_recovery_path_byte_parity() {
    run_fixture_byte_parity("f02-recovery-path");
}

#[test]
fn f04_migration_path_byte_parity() {
    run_fixture_byte_parity("f03-migration-path");
}

#[test]
fn f05_spawn_cancel_byte_parity() {
    run_fixture_byte_parity("f04-spawn-cancel");
}

#[test]
fn f06_rejected_attempt_then_clean_byte_parity() {
    run_fixture_byte_parity("f05-rejected-attempt-then-clean");
}

// ---------------------------------------------------------------------
// F07 — Inline base64 decoder smoke.
// ---------------------------------------------------------------------

#[test]
fn f07_inline_base64_decoder_smoke() {
    // `{}` -> `e30=`. `e3` `0=` -> `0x7b 0x7d`.
    assert_eq!(b64_decode("e30="), b"{}");
    // Empty input -> empty output.
    assert_eq!(b64_decode(""), Vec::<u8>::new());
    // `abc` -> `YWJj`.
    assert_eq!(b64_decode("YWJj"), b"abc");
}

// ---------------------------------------------------------------------
// F08 — Empty-history trace deterministic (mirrors Python T16).
// ---------------------------------------------------------------------

#[test]
fn f08_empty_history_trace_is_deterministic() {
    fn fixed_clock() -> String {
        "2026-05-17T00:00:00Z".to_string()
    }
    let m = PersonaFsm::new("reza", "wakir-labs").with_clock(fixed_clock);
    let trace = LifecycleTrace::from_fsm(&m, None);
    assert_eq!(trace.final_state, "uninstantiated");
    assert_eq!(trace.initial_state, "uninstantiated");
    assert!(trace.records.is_empty());
    let bytes = serialize_trace(&trace);
    assert_eq!(
        std::str::from_utf8(&bytes).unwrap(),
        r#"{"final_state":"uninstantiated","initial_state":"uninstantiated","org_id":"wakir-labs","persona_id":"reza","records":[],"schema":"wakir.persona-engine.lifecycle-trace/1"}"#
    );
}

// ---------------------------------------------------------------------
// F09 — Accepted-record reason omitted; rejected-record reason kept.
// ---------------------------------------------------------------------

#[test]
fn f09_reason_omit_pin() {
    fn fixed_clock() -> String {
        "2026-05-17T00:00:00Z".to_string()
    }
    let mut m = PersonaFsm::new("reza", "wakir-labs").with_clock(fixed_clock);
    // Attempt an invalid edge: uninstantiated -> running (rejected),
    // then the canonical clean path uninstantiated -> spawning.
    let _ = m.transition(FsmState::Running);
    m.transition(FsmState::Spawning).unwrap();
    let trace = LifecycleTrace::from_fsm(&m, None);
    let text = String::from_utf8(serialize_trace(&trace)).unwrap();
    // Accepted record must NOT carry "reason":null on the wire.
    assert!(
        !text.contains("\"reason\":null"),
        "reason=null leaked into wire-form: {}",
        text
    );
    // Rejected record MUST carry the canonical reason string.
    assert!(
        text.contains("\"reason\":\"not_in_valid_transitions\""),
        "rejected-record reason missing from wire-form: {}",
        text
    );
}

// ---------------------------------------------------------------------
// F10 — Hash shape constraints.
// ---------------------------------------------------------------------

#[test]
fn f10_hash_shape_constraints() {
    fn fixed_clock() -> String {
        "2026-05-17T00:00:00Z".to_string()
    }
    let mut m = PersonaFsm::new("reza", "wakir-labs").with_clock(fixed_clock);
    m.transition(FsmState::Spawning).unwrap();
    let trace = LifecycleTrace::from_fsm(&m, None);
    let bare = trace_sha256_hex(&trace);
    let prefixed = trace_hash_prefixed(&trace);
    assert_eq!(bare.len(), SHA256_HEX_LEN);
    assert!(bare.chars().all(|c| c.is_ascii_hexdigit() && (c.is_ascii_digit() || c.is_ascii_lowercase())));
    assert!(prefixed.starts_with(HASH_PREFIX));
    assert_eq!(prefixed.len(), HASH_PREFIX.len() + SHA256_HEX_LEN);
}
