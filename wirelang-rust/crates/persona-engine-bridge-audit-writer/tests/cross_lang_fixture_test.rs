// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Cross-lang fixture parity tests for persona-engine-bridge-audit-writer
// (Tag-30 Mini-Welle / Phase-3a-Python-Sync / Welle-3 12. Modul).
//
// These tests consume the same authoritative JSON fixture file
// (`tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json` at the
// repo root) that the Python sibling test
// (`tests/persona_engine/test_bridge_audit_writer_cross_lang_parity.py`)
// consumes. Both sides drive identical scripted emission scenarios
// through the deterministic envelope-construction surface and pin the
// same JCS bytes + record hashes. Any drift on either side breaks both
// test suites -- that is the intended boundary detector for the Welle-3
// Konsistenz-Oracle self-cutover (Henrik-Audit-Caution mitigation).
//
// Test taxonomy
// -------------
// - F01 -- Fixture file loads, schema_version matches the
//   `ENGINEERING_OUTPUT_SCHEMA` constant, exactly five vectors present
//   with the expected names.
// - F02..F06 -- Per-fixture byte-level pin: replay the emission program
//   against a freshly-constructed Rust `BridgeAuditWriter`, emit one
//   `EngineeringOutputEvent` per emission, JCS-canonicalise it, compare
//   the resulting bytes against the fixture's pinned `jcs_b64` /
//   `hash_prefixed` fields.
// - F07 -- Error-rollback invariant: F04 fixture is the one with a
//   deliberately-failing emission; the Rust writer's step_counter must
//   not advance on the error, so the post-rollback record step_index
//   is 2 (not 3) byte-identically to the Python pendant.

use std::fs;
use std::path::PathBuf;

use persona_engine_bridge_audit_writer::{
    BridgeAuditWriter, EngineeringOutputEvent, ENGINEERING_OUTPUT_SCHEMA,
    OUTPUT_KIND_AUDIT_ANNOTATION, OUTPUT_KIND_REPLY, OUTPUT_KIND_TOOL_CALL,
};
use serde_json::Value;

// ---------------------------------------------------------------------
// Inline base64 decoder (RFC 4648 standard alphabet). Re-uses the same
// inline decoder pattern as the anchor-submit-worker cross-lang test
// so we don't add an extra dev-dep here.
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
    let bytes: Vec<u8> = input.bytes().filter(|b| !b.is_ascii_whitespace()).collect();
    let mut out: Vec<u8> = Vec::with_capacity(bytes.len() * 3 / 4 + 3);
    let mut buf: u32 = 0;
    let mut bits: u8 = 0;
    for &c in &bytes {
        if c == b'=' {
            break;
        }
        let v = val(c).unwrap_or_else(|| panic!("invalid b64 char: {:?}", c as char));
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
// Fixture-file path resolution.
// ---------------------------------------------------------------------

fn fixture_path() -> PathBuf {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest
        .parent() // wirelang-rust/crates
        .and_then(|p| p.parent()) // wirelang-rust
        .and_then(|p| p.parent()) // repo root
        .expect("could not resolve repo root from CARGO_MANIFEST_DIR");
    repo_root
        .join("tests")
        .join("fixtures")
        .join("bridge-audit-writer-cross-lang")
        .join("fixtures.json")
}

fn load_fixture_doc() -> Value {
    let path = fixture_path();
    let raw = fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("could not read fixture file {}: {e}", path.display()));
    serde_json::from_str(&raw).expect("fixture file is valid JSON")
}

fn find_fixture_by_name<'a>(doc: &'a Value, name: &str) -> &'a Value {
    doc.get("fixtures")
        .and_then(Value::as_array)
        .and_then(|arr| {
            arr.iter()
                .find(|f| f.get("name").and_then(Value::as_str) == Some(name))
        })
        .unwrap_or_else(|| panic!("fixture {name:?} not found in fixtures.json"))
}

// ---------------------------------------------------------------------
// Replay helper: run one fixture's emission program through a fresh
// Rust writer and return the resulting events + final step counter.
// ---------------------------------------------------------------------

struct ReplayOutcome {
    events: Vec<EngineeringOutputEvent>,
    step_counter_final: u32,
}

fn replay_fixture(fixture: &Value) -> ReplayOutcome {
    let inp = fixture.get("input").expect("input present");
    let mut w = BridgeAuditWriter::new(
        inp.get("org_id")
            .and_then(Value::as_str)
            .unwrap()
            .to_string(),
        inp.get("persona_id")
            .and_then(Value::as_str)
            .unwrap()
            .to_string(),
        inp.get("session_id")
            .and_then(Value::as_str)
            .unwrap()
            .to_string(),
        inp.get("engine_version")
            .and_then(Value::as_str)
            .unwrap()
            .to_string(),
        inp.get("v907_pin")
            .and_then(Value::as_str)
            .unwrap()
            .to_string(),
    );
    let emissions = inp
        .get("emissions")
        .and_then(Value::as_array)
        .expect("emissions array");
    let mut events: Vec<EngineeringOutputEvent> = Vec::new();
    for em in emissions {
        let kind = em.get("output_kind").and_then(Value::as_str).unwrap();
        let payload_b64 = em.get("payload_b64").and_then(Value::as_str).unwrap();
        let ts_utc = em.get("ts_utc").and_then(Value::as_str).unwrap();
        let payload = b64_decode(payload_b64);
        let expect_error = em
            .get("expect_error")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        match w.emit(kind, &payload, ts_utc) {
            Ok(evt) => {
                assert!(
                    !expect_error,
                    "expected error for kind={kind:?} but emit succeeded"
                );
                events.push(evt);
            }
            Err(e) => {
                assert!(expect_error, "unexpected emit error for kind={kind:?}: {e}");
            }
        }
    }
    ReplayOutcome {
        events,
        step_counter_final: w.step_counter(),
    }
}

// ---------------------------------------------------------------------
// F01 -- Fixture-file shape
// ---------------------------------------------------------------------

#[test]
fn f01_fixture_file_shape() {
    let doc = load_fixture_doc();
    let schema = doc
        .get("schema_version")
        .and_then(Value::as_str)
        .expect("schema_version present");
    assert_eq!(schema, ENGINEERING_OUTPUT_SCHEMA);

    let names: Vec<&str> = doc
        .get("fixtures")
        .and_then(Value::as_array)
        .expect("fixtures array")
        .iter()
        .map(|f| f.get("name").and_then(Value::as_str).unwrap())
        .collect();
    assert_eq!(
        names,
        vec![
            "f01-empty-audit-stream",
            "f02-single-record-write",
            "f03-batch-write",
            "f04-error-write-rollback",
            "f05-append-only-discipline",
        ]
    );
}

// ---------------------------------------------------------------------
// F02 -- f01 empty-audit-stream invariant
// ---------------------------------------------------------------------

#[test]
fn f02_empty_audit_stream_invariant() {
    let doc = load_fixture_doc();
    let f = find_fixture_by_name(&doc, "f01-empty-audit-stream");
    let outcome = replay_fixture(f);
    assert_eq!(outcome.events.len(), 0);
    assert_eq!(outcome.step_counter_final, 0);
    let pinned_count = f
        .get("expected")
        .and_then(|e| e.get("records"))
        .and_then(Value::as_array)
        .map(|a| a.len())
        .unwrap();
    let pinned_sc = f
        .get("expected")
        .and_then(|e| e.get("step_counter_final"))
        .and_then(Value::as_u64)
        .unwrap();
    assert_eq!(pinned_count, 0);
    assert_eq!(pinned_sc, 0);
}

// ---------------------------------------------------------------------
// F03 -- f02 single-record-write byte-pin
// ---------------------------------------------------------------------

#[test]
fn f03_single_record_write_byte_pin() {
    let doc = load_fixture_doc();
    let f = find_fixture_by_name(&doc, "f02-single-record-write");
    let outcome = replay_fixture(f);
    assert_eq!(outcome.events.len(), 1);
    assert_eq!(outcome.step_counter_final, 1);
    let pinned = &f
        .get("expected")
        .unwrap()
        .get("records")
        .unwrap()
        .as_array()
        .unwrap()[0];
    let pinned_jcs_b64 = pinned.get("jcs_b64").and_then(Value::as_str).unwrap();
    let pinned_jcs = b64_decode(pinned_jcs_b64);
    let pinned_hash = pinned.get("hash_prefixed").and_then(Value::as_str).unwrap();
    let pinned_len = pinned.get("jcs_len").and_then(Value::as_u64).unwrap() as usize;

    let evt = &outcome.events[0];
    let actual_jcs = evt.to_jcs_bytes().unwrap();
    assert_eq!(actual_jcs, pinned_jcs, "JCS-byte drift on single-record");
    assert_eq!(actual_jcs.len(), pinned_len);
    assert_eq!(evt.payload_sha256().unwrap(), pinned_hash);
    assert_eq!(evt.step_index, 0);
    assert_eq!(evt.output_kind, OUTPUT_KIND_TOOL_CALL);
}

// ---------------------------------------------------------------------
// F04 -- f03 batch-write byte-pin (three records, three kinds)
// ---------------------------------------------------------------------

#[test]
fn f04_batch_write_byte_pin() {
    let doc = load_fixture_doc();
    let f = find_fixture_by_name(&doc, "f03-batch-write");
    let outcome = replay_fixture(f);
    assert_eq!(outcome.events.len(), 3);
    assert_eq!(outcome.step_counter_final, 3);

    let kinds: Vec<&str> = outcome
        .events
        .iter()
        .map(|e| e.output_kind.as_str())
        .collect();
    assert_eq!(
        kinds,
        vec![
            OUTPUT_KIND_TOOL_CALL,
            OUTPUT_KIND_REPLY,
            OUTPUT_KIND_AUDIT_ANNOTATION,
        ]
    );
    let indices: Vec<u32> = outcome.events.iter().map(|e| e.step_index).collect();
    assert_eq!(indices, vec![0, 1, 2]);

    let pinned_records = f
        .get("expected")
        .unwrap()
        .get("records")
        .unwrap()
        .as_array()
        .unwrap();
    for (i, evt) in outcome.events.iter().enumerate() {
        let pinned = &pinned_records[i];
        let pinned_jcs = b64_decode(pinned.get("jcs_b64").and_then(Value::as_str).unwrap());
        let pinned_hash = pinned.get("hash_prefixed").and_then(Value::as_str).unwrap();
        let actual_jcs = evt.to_jcs_bytes().unwrap();
        assert_eq!(
            actual_jcs, pinned_jcs,
            "JCS-byte drift on batch step {i}: kind={}",
            evt.output_kind
        );
        assert_eq!(evt.payload_sha256().unwrap(), pinned_hash);
    }
}

// ---------------------------------------------------------------------
// F05 -- f04 error-write-rollback invariant
// ---------------------------------------------------------------------

#[test]
fn f05_error_write_rollback_invariant() {
    let doc = load_fixture_doc();
    let f = find_fixture_by_name(&doc, "f04-error-write-rollback");
    let outcome = replay_fixture(f);
    // 3 successful emissions; the garbage_kind call was caught.
    assert_eq!(outcome.events.len(), 3);
    // Post-rollback step_index is 2, not 3 -- the failed emit() did
    // NOT advance the step counter.
    let indices: Vec<u32> = outcome.events.iter().map(|e| e.step_index).collect();
    assert_eq!(indices, vec![0, 1, 2]);
    // After three successful + one rolled-back, step_counter == 3.
    assert_eq!(outcome.step_counter_final, 3);
    // Byte-pin per record.
    let pinned_records = f
        .get("expected")
        .unwrap()
        .get("records")
        .unwrap()
        .as_array()
        .unwrap();
    for (i, evt) in outcome.events.iter().enumerate() {
        let pinned = &pinned_records[i];
        let pinned_jcs = b64_decode(pinned.get("jcs_b64").and_then(Value::as_str).unwrap());
        let pinned_hash = pinned.get("hash_prefixed").and_then(Value::as_str).unwrap();
        let actual_jcs = evt.to_jcs_bytes().unwrap();
        assert_eq!(actual_jcs, pinned_jcs);
        assert_eq!(evt.payload_sha256().unwrap(), pinned_hash);
    }
}

// ---------------------------------------------------------------------
// F06 -- f05 append-only-discipline (two writers, identical results)
// ---------------------------------------------------------------------

#[test]
fn f06_append_only_discipline() {
    let doc = load_fixture_doc();
    let f = find_fixture_by_name(&doc, "f05-append-only-discipline");
    let outcome_a = replay_fixture(f);
    let outcome_b = replay_fixture(f);
    assert_eq!(outcome_a.events.len(), 2);
    assert_eq!(outcome_b.events.len(), 2);
    assert_eq!(outcome_a.step_counter_final, 2);
    assert_eq!(outcome_b.step_counter_final, 2);
    for (a, b) in outcome_a.events.iter().zip(outcome_b.events.iter()) {
        assert_eq!(a.to_jcs_bytes().unwrap(), b.to_jcs_bytes().unwrap());
    }
    let pinned_records = f
        .get("expected")
        .unwrap()
        .get("records")
        .unwrap()
        .as_array()
        .unwrap();
    for (i, evt) in outcome_a.events.iter().enumerate() {
        let pinned = &pinned_records[i];
        let pinned_jcs = b64_decode(pinned.get("jcs_b64").and_then(Value::as_str).unwrap());
        let pinned_hash = pinned.get("hash_prefixed").and_then(Value::as_str).unwrap();
        let actual_jcs = evt.to_jcs_bytes().unwrap();
        assert_eq!(actual_jcs, pinned_jcs);
        assert_eq!(evt.payload_sha256().unwrap(), pinned_hash);
    }
}

// ---------------------------------------------------------------------
// F07 -- Cross-fixture coverage: every output_kind appears at least once
// ---------------------------------------------------------------------

#[test]
fn f07_output_kind_coverage() {
    let doc = load_fixture_doc();
    let mut seen_tool_call = false;
    let mut seen_reply = false;
    let mut seen_audit_annotation = false;
    for f in doc.get("fixtures").and_then(Value::as_array).unwrap() {
        for rec in f
            .get("expected")
            .unwrap()
            .get("records")
            .unwrap()
            .as_array()
            .unwrap()
        {
            let kind = rec
                .get("envelope")
                .unwrap()
                .get("output_kind")
                .and_then(Value::as_str)
                .unwrap();
            match kind {
                OUTPUT_KIND_TOOL_CALL => seen_tool_call = true,
                OUTPUT_KIND_REPLY => seen_reply = true,
                OUTPUT_KIND_AUDIT_ANNOTATION => seen_audit_annotation = true,
                _ => panic!("unexpected output_kind in fixture: {kind:?}"),
            }
        }
    }
    assert!(seen_tool_call && seen_reply && seen_audit_annotation);
}

// ---------------------------------------------------------------------
// F08 -- Determinism sentinel: re-emit produces byte-identical JCS bytes.
// ---------------------------------------------------------------------

#[test]
fn f08_determinism_sentinel() {
    let doc = load_fixture_doc();
    let f = find_fixture_by_name(&doc, "f03-batch-write");
    let outcome_1 = replay_fixture(f);
    let outcome_2 = replay_fixture(f);
    for (a, b) in outcome_1.events.iter().zip(outcome_2.events.iter()) {
        assert_eq!(a.to_jcs_bytes().unwrap(), b.to_jcs_bytes().unwrap());
        assert_eq!(a.payload_sha256().unwrap(), b.payload_sha256().unwrap());
    }
}
