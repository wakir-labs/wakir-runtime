// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Cross-lang fixture parity tests for persona-engine-anchor-emitter.
//
// These tests consume the same authoritative JSON fixture file
// (`tests/fixtures/anchor-emitter-cross-lang/fixtures.json` at the
// repo root) that the Python sibling test
// (`tests/wat/test_anchor_emitter_cross_lang_parity.py`) consumes.
// Both sides pin the same envelope-JCS-bytes / envelope-SHA-256-hex
// / payload-SHA-256-hex tuples, so any drift on either side breaks
// both test suites — that is the intended boundary detector.
//
// The fixture file path is computed from the `CARGO_MANIFEST_DIR`
// env-var at build time and walks up to the repo root. This keeps
// the crate movable within the workspace without hard-coded paths.
//
// Test taxonomy
// -------------
// - F01 — Fixture file loads, schema_version matches the
//   `ENVELOPE_SCHEMA` constant, >=5 vectors are present.
// - F02..F06 — Per-fixture byte-level pin: envelope JCS bytes,
//   bare-hex outer hash, prefixed outer hash, payload hash, length.
//   One test per fixture name for fine-grained failure isolation.
//
// Base64 decoding strategy
// ------------------------
// The fixture file encodes byte fields as base64 (b64) so JSON
// remains text-only. Rather than add the `base64` crate as a
// dev-dependency we inline a small lookup-table decoder; the
// fixture data is hard-coded and base64-decoded once per test.

use persona_engine_anchor_emitter::{
    build_anchor_envelope, hash_anchor, serialize_anchor, serialize_and_hash, sha256_hex,
    AnchorEmitterInput, ENVELOPE_SCHEMA,
};
use serde_json::Value;
use std::path::PathBuf;

// ---------------------------------------------------------------------
// Inline base64 decoder (RFC 4648 standard alphabet, no line breaks).
// ---------------------------------------------------------------------

fn b64_decode(input: &str) -> Vec<u8> {
    // Lookup table: 'A'-'Z' = 0..25, 'a'-'z' = 26..51, '0'-'9' = 52..61,
    // '+' = 62, '/' = 63, '=' = padding sentinel, other = invalid.
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
    // CARGO_MANIFEST_DIR is
    // <repo>/wirelang-rust/crates/persona-engine-anchor-emitter.
    // Walk up four levels to reach <repo>, then into tests/fixtures/.
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest
        .parent() // wirelang-rust/crates
        .and_then(|p| p.parent()) // wirelang-rust
        .and_then(|p| p.parent()) // repo root
        .expect("could not resolve repo root from CARGO_MANIFEST_DIR");
    repo_root
        .join("tests")
        .join("fixtures")
        .join("anchor-emitter-cross-lang")
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
        schema, ENVELOPE_SCHEMA,
        "fixture schema_version {:?} drifted from crate ENVELOPE_SCHEMA {:?}",
        schema, ENVELOPE_SCHEMA
    );

    let fixtures = v
        .get("fixtures")
        .and_then(|f| f.as_array())
        .expect("fixture file must carry a 'fixtures' array");
    assert!(
        fixtures.len() >= 5,
        "expected >=5 cross-lang fixtures, got {}",
        fixtures.len()
    );

    // Every fixture has the documented input + expected fields.
    for fx in fixtures {
        let name = fx
            .get("name")
            .and_then(|s| s.as_str())
            .expect("fixture missing 'name' field");
        let inp = fx.get("input").and_then(|x| x.as_object()).unwrap();
        for k in [
            "event_id",
            "timestamp_utc",
            "persona_id",
            "payload_jcs_bytes_b64",
        ] {
            assert!(
                inp.contains_key(k),
                "fixture {:?} missing input.{}",
                name,
                k
            );
        }
        let exp = fx.get("expected").and_then(|x| x.as_object()).unwrap();
        for k in [
            "payload_sha256_hex",
            "envelope_jcs_bytes_b64",
            "envelope_jcs_bytes_len",
            "envelope_sha256_hex",
            "envelope_hash_prefixed",
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
        .unwrap_or_else(|| panic!("fixture {:?} not found in fixture file", target_name));

    let inp_obj = fx.get("input").and_then(|x| x.as_object()).unwrap();
    let event_id = inp_obj.get("event_id").and_then(|s| s.as_str()).unwrap();
    let timestamp_utc = inp_obj
        .get("timestamp_utc")
        .and_then(|s| s.as_str())
        .unwrap();
    let persona_id = inp_obj.get("persona_id").and_then(|s| s.as_str()).unwrap();
    let payload_b64 = inp_obj
        .get("payload_jcs_bytes_b64")
        .and_then(|s| s.as_str())
        .unwrap();
    let payload_bytes = b64_decode(payload_b64);

    let exp_obj = fx.get("expected").and_then(|x| x.as_object()).unwrap();
    let exp_payload_hex = exp_obj
        .get("payload_sha256_hex")
        .and_then(|s| s.as_str())
        .unwrap();
    let exp_envelope_bytes = b64_decode(
        exp_obj
            .get("envelope_jcs_bytes_b64")
            .and_then(|s| s.as_str())
            .unwrap(),
    );
    let exp_envelope_len = exp_obj
        .get("envelope_jcs_bytes_len")
        .and_then(|n| n.as_u64())
        .unwrap() as usize;
    let exp_envelope_hex = exp_obj
        .get("envelope_sha256_hex")
        .and_then(|s| s.as_str())
        .unwrap();
    let exp_envelope_prefixed = exp_obj
        .get("envelope_hash_prefixed")
        .and_then(|s| s.as_str())
        .unwrap();

    let input = AnchorEmitterInput {
        event_id: event_id.to_string(),
        timestamp_utc: timestamp_utc.to_string(),
        persona_id: persona_id.to_string(),
        payload_jcs_bytes: payload_bytes.clone(),
    };
    let env = build_anchor_envelope(input).expect("build_anchor_envelope must succeed");

    // Payload SHA-256 (bare hex) pin.
    assert_eq!(
        sha256_hex(&env.payload_jcs_bytes),
        exp_payload_hex,
        "fixture {:?}: payload_sha256_hex drifted",
        target_name,
    );

    // Envelope canonical bytes pin (byte-for-byte).
    let bytes = serialize_anchor(&env);
    assert_eq!(
        bytes, exp_envelope_bytes,
        "fixture {:?}: envelope JCS bytes drifted",
        target_name,
    );
    assert_eq!(
        bytes.len(),
        exp_envelope_len,
        "fixture {:?}: envelope JCS bytes length drifted",
        target_name,
    );

    // Outer envelope hash (bare hex) pin.
    assert_eq!(
        sha256_hex(&bytes),
        exp_envelope_hex,
        "fixture {:?}: envelope_sha256_hex drifted",
        target_name,
    );

    // Outer envelope hash (prefixed) pin.
    assert_eq!(
        hash_anchor(&env),
        exp_envelope_prefixed,
        "fixture {:?}: hash_anchor prefixed-form drifted",
        target_name,
    );

    // serialize_and_hash consistency on the fixture path.
    let (combined_bytes, combined_hash) = serialize_and_hash(&env);
    assert_eq!(combined_bytes, bytes);
    assert_eq!(combined_hash, exp_envelope_prefixed);
}

// ---------------------------------------------------------------------
// F02..F06 — Per-fixture byte-level cross-lang pins.
// ---------------------------------------------------------------------

#[test]
fn f02_fixture_f01_empty_object() {
    run_single_fixture("f01-empty-object");
}

#[test]
fn f03_fixture_f02_small_flat_object() {
    run_single_fixture("f02-small-flat-object");
}

#[test]
fn f04_fixture_f03_array_payload() {
    run_single_fixture("f03-array-payload");
}

#[test]
fn f05_fixture_f04_unicode_payload() {
    run_single_fixture("f04-unicode-payload");
}

#[test]
fn f06_fixture_f05_empty_array() {
    run_single_fixture("f05-empty-array");
}

// ---------------------------------------------------------------------
// F07 — Inline base64 decoder sanity (the cross-lang test trusts it).
// ---------------------------------------------------------------------

#[test]
fn f07_inline_base64_decoder_sanity() {
    assert_eq!(b64_decode("e30="), b"{}".to_vec());
    assert_eq!(b64_decode("W10="), b"[]".to_vec());
    assert_eq!(b64_decode(""), Vec::<u8>::new());
    // Length-3 plaintext = length-4 base64 with no padding.
    assert_eq!(b64_decode("YWJj"), b"abc".to_vec());
}
