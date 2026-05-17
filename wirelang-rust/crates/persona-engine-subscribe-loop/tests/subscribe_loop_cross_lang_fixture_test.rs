// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Cross-lang fixture parity tests for persona-engine-subscribe-loop
// ack-records (Tag-19 Mini-Welle, Phase-3a Python-sync).
//
// These tests consume the same authoritative JSON fixture file
// (`tests/fixtures/subscribe-loop-cross-lang/fixtures.json` at the
// repo root) that the Python sibling test
// (`wirelang/tests/persona_engine/test_subscribe_loop_cross_lang_parity.py`)
// consumes. Both sides pin the same record-JCS-bytes / record-SHA-256
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
//   `ACK_RECORD_SCHEMA` constant, exactly 5 vectors present.
// - F02..F06 — Per-fixture byte-level pin: ack-record JCS bytes,
//   bare-hex outer hash, prefixed outer hash, byte length.
// - F07 — Inline base64 decoder sanity (the cross-lang test
//   trusts it).
// - F08 — Burst-monotonic helper accepts the multi-record-batch
//   shape implied by f03 (frame_index=2 only valid in a 0,1,2
//   burst).
//
// Base64 decoding strategy
// ------------------------
// The fixture file encodes byte fields as base64 (b64) so JSON
// remains text-only. Rather than add the `base64` crate as a
// dev-dependency we inline a small lookup-table decoder; the
// fixture data is hard-coded and base64-decoded once per test.
// Identical pattern to the `persona-engine-anchor-emitter` Tag-18
// PR #170 fixture test.

use persona_engine_subscribe_loop::{
    ack_record_hash_prefixed, ack_record_sha256_hex, build_ack_burst, build_ack_record,
    serialize_ack, serialize_and_hash, sha256_hex, ACK_RECORD_SCHEMA, HASH_PREFIX,
    OUTCOME_PROCESSED,
};
use serde_json::Value;
use std::path::PathBuf;

// ---------------------------------------------------------------------
// Inline base64 decoder (RFC 4648 standard alphabet, no line breaks).
// Identical to the anchor-emitter sibling fixture test.
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
        .expect("could not resolve repo root from CARGO_MANIFEST_DIR");
    repo_root
        .join("tests")
        .join("fixtures")
        .join("subscribe-loop-cross-lang")
        .join("fixtures.json")
}

fn load_fixtures() -> Value {
    let path = fixture_path();
    let raw = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("could not read fixture file {:?}: {}", path, e));
    serde_json::from_str(&raw)
        .unwrap_or_else(|e| panic!("could not parse fixture file as JSON: {}", e))
}

// ---------------------------------------------------------------------
// F01 — Fixture file structure pin.
// ---------------------------------------------------------------------

#[test]
fn f01_fixture_file_loads_and_schema_matches_crate_constant() {
    let v = load_fixtures();
    let schema = v
        .get("schema_version")
        .and_then(|s| s.as_str())
        .expect("fixture file must carry a 'schema_version' string field");
    assert_eq!(
        schema, ACK_RECORD_SCHEMA,
        "fixture schema_version {:?} drifted from crate ACK_RECORD_SCHEMA {:?}",
        schema, ACK_RECORD_SCHEMA
    );

    let fixtures = v
        .get("fixtures")
        .and_then(|f| f.as_array())
        .expect("fixture file must carry a 'fixtures' array");
    assert_eq!(
        fixtures.len(),
        5,
        "Tag-19 pins exactly 5 cross-lang fixtures, got {}",
        fixtures.len()
    );

    // Every fixture has the documented input + expected fields.
    for fx in fixtures {
        let name = fx
            .get("name")
            .and_then(|s| s.as_str())
            .expect("fixture missing 'name' field");
        let inp = fx
            .get("input")
            .and_then(|x| x.as_object())
            .unwrap_or_else(|| panic!("fixture {:?} missing 'input' object", name));
        for k in [
            "auftrag_id",
            "frame_index",
            "outcome",
            "persona_id",
            "prompt_sha256",
            "subject",
        ] {
            assert!(
                inp.contains_key(k),
                "fixture {:?} missing input.{}",
                name,
                k
            );
        }
        let exp = fx
            .get("expected")
            .and_then(|x| x.as_object())
            .unwrap_or_else(|| panic!("fixture {:?} missing 'expected' object", name));
        for k in [
            "ack_record_jcs_bytes_b64",
            "ack_record_jcs_bytes_len",
            "ack_record_sha256_hex",
            "ack_record_hash_prefixed",
        ] {
            assert!(
                exp.contains_key(k),
                "fixture {:?} missing expected.{}",
                name,
                k
            );
        }
    }
}

// ---------------------------------------------------------------------
// Helper: one-pin run against one fixture.
// ---------------------------------------------------------------------

fn run_single_fixture(target_name: &str) {
    let v = load_fixtures();
    let fixtures = v.get("fixtures").and_then(|f| f.as_array()).unwrap();
    let fx = fixtures
        .iter()
        .find(|f| f.get("name").and_then(|s| s.as_str()) == Some(target_name))
        .unwrap_or_else(|| panic!("fixture {:?} not found", target_name));

    let inp = fx.get("input").and_then(|x| x.as_object()).unwrap();
    let auftrag_id = inp.get("auftrag_id").and_then(|s| s.as_str()).unwrap();
    let frame_index = inp.get("frame_index").and_then(|n| n.as_u64()).unwrap();
    let outcome = inp.get("outcome").and_then(|s| s.as_str()).unwrap();
    let persona_id = inp.get("persona_id").and_then(|s| s.as_str()).unwrap();
    let prompt_sha256 = inp.get("prompt_sha256").and_then(|s| s.as_str()).unwrap();
    let subject = inp.get("subject").and_then(|s| s.as_str()).unwrap();

    let exp = fx.get("expected").and_then(|x| x.as_object()).unwrap();
    let exp_bytes = b64_decode(
        exp.get("ack_record_jcs_bytes_b64")
            .and_then(|s| s.as_str())
            .unwrap(),
    );
    let exp_len = exp
        .get("ack_record_jcs_bytes_len")
        .and_then(|n| n.as_u64())
        .unwrap() as usize;
    let exp_hex = exp
        .get("ack_record_sha256_hex")
        .and_then(|s| s.as_str())
        .unwrap();
    let exp_prefixed = exp
        .get("ack_record_hash_prefixed")
        .and_then(|s| s.as_str())
        .unwrap();

    let rec = build_ack_record(
        auftrag_id,
        frame_index,
        outcome,
        persona_id,
        prompt_sha256,
        subject,
    )
    .unwrap_or_else(|e| panic!("fixture {:?} build_ack_record failed: {}", target_name, e));

    // Canonical bytes pin (byte-for-byte).
    let bytes = serialize_ack(&rec);
    assert_eq!(
        bytes, exp_bytes,
        "fixture {:?}: ack-record JCS bytes drifted",
        target_name,
    );
    assert_eq!(
        bytes.len(),
        exp_len,
        "fixture {:?}: ack-record JCS bytes length drifted",
        target_name,
    );

    // Outer hash (bare hex) pin.
    assert_eq!(
        sha256_hex(&bytes),
        exp_hex,
        "fixture {:?}: ack_record_sha256_hex drifted",
        target_name,
    );
    assert_eq!(
        ack_record_sha256_hex(&rec),
        exp_hex,
        "fixture {:?}: ack_record_sha256_hex helper drifted",
        target_name,
    );

    // Outer hash (prefixed) pin.
    assert_eq!(
        ack_record_hash_prefixed(&rec),
        exp_prefixed,
        "fixture {:?}: ack_record_hash_prefixed drifted",
        target_name,
    );

    // serialize_and_hash consistency.
    let (combined_bytes, combined_hash) = serialize_and_hash(&rec);
    assert_eq!(combined_bytes, bytes);
    assert_eq!(combined_hash, exp_prefixed);

    // Schema field hard-pin.
    assert_eq!(rec.schema, ACK_RECORD_SCHEMA);
    // Prefixed-form starts with the documented prefix.
    assert!(exp_prefixed.starts_with(HASH_PREFIX));
}

// ---------------------------------------------------------------------
// F02..F06 — Per-fixture byte-level cross-lang pins.
// ---------------------------------------------------------------------

#[test]
fn f02_fixture_f01_empty_frame() {
    run_single_fixture("f01-empty-frame");
}

#[test]
fn f03_fixture_f02_single_payload() {
    run_single_fixture("f02-single-payload");
}

#[test]
fn f04_fixture_f03_multi_record_batch() {
    run_single_fixture("f03-multi-record-batch");
}

#[test]
fn f05_fixture_f04_error_frame() {
    run_single_fixture("f04-error-frame");
}

#[test]
fn f06_fixture_f05_large_payload() {
    run_single_fixture("f05-large-payload");
}

// ---------------------------------------------------------------------
// F07 — Inline base64 decoder sanity (the cross-lang test trusts it).
// ---------------------------------------------------------------------

#[test]
fn f07_inline_base64_decoder_sanity() {
    assert_eq!(b64_decode("e30="), b"{}".to_vec());
    assert_eq!(b64_decode("W10="), b"[]".to_vec());
    assert_eq!(b64_decode(""), Vec::<u8>::new());
    assert_eq!(b64_decode("YWJj"), b"abc".to_vec());
}

// ---------------------------------------------------------------------
// F08 — Burst-monotonic helper accepts a 0,1,2 sequence implied by f03.
// ---------------------------------------------------------------------

#[test]
fn f08_burst_helper_accepts_multi_record_batch_shape() {
    // Re-build the three records that would precede the f03 vector
    // in an ordered-delivery batch: frame_index 0, 1, 2 with the
    // f03 record as the last entry.
    let r0 = build_ack_record(
        "auftrag-pengine-batch-1",
        0,
        OUTCOME_PROCESSED,
        "reza",
        "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        "wakir.dev.agent.agent.task.assigned.reza",
    )
    .unwrap();
    let r1 = build_ack_record(
        "auftrag-pengine-batch-2",
        1,
        OUTCOME_PROCESSED,
        "reza",
        "sha256:1111111111111111111111111111111111111111111111111111111111111111",
        "wakir.dev.agent.agent.task.assigned.reza",
    )
    .unwrap();
    let r2 = build_ack_record(
        "auftrag-pengine-batch-3",
        2,
        OUTCOME_PROCESSED,
        "reza",
        "sha256:936885d9ae186b59e4835722bb54897edfe580c18c57e8c124168e12fa93e324",
        "wakir.dev.agent.agent.task.assigned.reza",
    )
    .unwrap();
    let burst = build_ack_burst([r0, r1, r2.clone()])
        .expect("monotonic burst must validate");
    assert_eq!(burst.len(), 3);
    assert_eq!(burst[2], r2);
}
