// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Cross-lang fixture parity tests for persona-engine-recovery
// (Tag-20 Mini-Welle, Phase-3a Python-sync, Item 6).
//
// These tests consume the same authoritative JSON fixture file
// (`tests/fixtures/recovery-workflow-cross-lang/fixtures.json` at the
// repo root) that the Python sibling test
// (`wirelang/tests/persona_engine/test_recovery_workflow_cross_lang_parity.py`)
// consumes. Both sides pin the same canonical-outcome-JCS-bytes /
// canonical-SHA-256 tuples, so any drift on either side breaks both
// test suites — that is the intended boundary detector.
//
// The fixture file path is computed from the `CARGO_MANIFEST_DIR`
// env-var at build time and walks up to the repo root. This keeps
// the crate movable within the workspace without hard-coded paths.
//
// Test taxonomy
// -------------
// - F01 — Fixture file loads, schema_version matches the
//   `RECOVERY_OUTCOME_SCHEMA` constant, exactly 5 vectors present.
// - F02..F06 — Per-fixture byte-level pin: canonical JCS bytes,
//   bare-hex outer hash, prefixed outer hash, byte length.
//   One test per fixture name for fine-grained failure isolation.
// - F07 — Inline base64 decoder sanity (the cross-lang test
//   trusts it).
// - F08 — Trigger wire-string round-trip: every trigger that
//   appears in the fixtures parses back to a `RecoveryTrigger`.
//
// Base64 decoding strategy
// ------------------------
// The fixture file encodes byte fields as base64 (b64) so JSON
// remains text-only. Rather than add the `base64` crate as a
// dev-dependency we inline a small lookup-table decoder; the
// fixture data is hard-coded and base64-decoded once per test.
// Identical pattern to the `persona-engine-subscribe-loop` Tag-19
// PR #172 fixture test.

use persona_engine_recovery::{
    recovery_outcome_canonical_value, recovery_outcome_hash_prefixed, recovery_outcome_jcs_bytes,
    recovery_outcome_sha256_hex, PhaseResult, RecoveryOutcome, RecoveryTrigger, HASH_PREFIX,
    RECOVERY_OUTCOME_SCHEMA, SHA256_HEX_LEN,
};
use serde_json::Value;
use std::path::PathBuf;

// ---------------------------------------------------------------------
// Inline base64 decoder (RFC 4648 standard alphabet, no line breaks).
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
    // CARGO_MANIFEST_DIR is
    // <repo>/wirelang-rust/crates/persona-engine-recovery.
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
        .join("recovery-workflow-cross-lang")
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
// Helper: construct a RecoveryOutcome from a fixture's input block.
// ---------------------------------------------------------------------

fn trigger_from_str(s: &str) -> RecoveryTrigger {
    match s {
        "CrashDetected" => RecoveryTrigger::CrashDetected,
        "DespawnMidOperation" => RecoveryTrigger::DespawnMidOperation,
        "StateCorruption" => RecoveryTrigger::StateCorruption,
        other => panic!("unknown trigger wire-string {:?}", other),
    }
}

fn build_outcome_from_fixture_input(input: &serde_json::Map<String, Value>) -> RecoveryOutcome {
    let trigger = trigger_from_str(input.get("trigger").and_then(|s| s.as_str()).unwrap());
    let final_state = input
        .get("final_state")
        .and_then(|s| s.as_str())
        .unwrap()
        .to_owned();
    let success = input.get("success").and_then(|b| b.as_bool()).unwrap();

    let phases_in = input.get("phases").and_then(|p| p.as_array()).unwrap();
    let phases: Vec<PhaseResult> = phases_in
        .iter()
        .map(|ph| {
            let ph_obj = ph.as_object().unwrap();
            PhaseResult {
                phase: ph_obj
                    .get("phase")
                    .and_then(|s| s.as_str())
                    .unwrap()
                    .to_owned(),
                terminal_status: ph_obj
                    .get("terminal_status")
                    .and_then(|s| s.as_str())
                    .unwrap()
                    .to_owned(),
                // Timing fields are zeroed in the canonical projection
                // regardless of input — use non-zero here to confirm
                // the projection drops them.
                elapsed_sec: 0.42_f64,
                soft_cap_exceeded: false,
                audit_annotation: ph_obj
                    .get("audit_annotation")
                    .and_then(|s| s.as_str())
                    .unwrap()
                    .to_owned(),
            }
        })
        .collect();

    RecoveryOutcome {
        trigger,
        phases,
        // Non-zero on purpose: canonical projection must drop this.
        total_elapsed_sec: 1.5_f64,
        final_state,
        success,
    }
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
        schema, RECOVERY_OUTCOME_SCHEMA,
        "fixture schema_version {:?} drifted from crate RECOVERY_OUTCOME_SCHEMA {:?}",
        schema, RECOVERY_OUTCOME_SCHEMA
    );

    let fixtures = v
        .get("fixtures")
        .and_then(|f| f.as_array())
        .expect("fixture file must carry a 'fixtures' array");
    assert_eq!(
        fixtures.len(),
        5,
        "expected exactly 5 cross-lang fixtures, got {}",
        fixtures.len()
    );

    let names: Vec<&str> = fixtures
        .iter()
        .map(|f| f.get("name").and_then(|s| s.as_str()).unwrap())
        .collect();
    assert_eq!(
        names,
        vec![
            "f01-clean-r1-r4",
            "f02-r2-fail-retry",
            "f03-r3-skip",
            "f04-r1-error-immediate",
            "f05-r4-timeout",
        ]
    );

    // Every fixture has the documented input + expected fields.
    for fx in fixtures {
        let name = fx.get("name").and_then(|s| s.as_str()).unwrap();
        let inp = fx.get("input").and_then(|x| x.as_object()).unwrap();
        for k in ["trigger", "final_state", "success", "phases"] {
            assert!(
                inp.contains_key(k),
                "fixture {:?} missing input.{}",
                name,
                k
            );
        }
        let exp = fx.get("expected").and_then(|x| x.as_object()).unwrap();
        for k in [
            "outcome_jcs_bytes_b64",
            "outcome_jcs_bytes_len",
            "outcome_sha256_hex",
            "outcome_hash_prefixed",
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

    let inp = fx.get("input").and_then(|x| x.as_object()).unwrap();
    let outcome = build_outcome_from_fixture_input(inp);

    let exp = fx.get("expected").and_then(|x| x.as_object()).unwrap();
    let exp_bytes_b64 = exp
        .get("outcome_jcs_bytes_b64")
        .and_then(|s| s.as_str())
        .unwrap();
    let exp_bytes = b64_decode(exp_bytes_b64);
    let exp_len = exp
        .get("outcome_jcs_bytes_len")
        .and_then(|n| n.as_u64())
        .unwrap() as usize;
    let exp_sha = exp
        .get("outcome_sha256_hex")
        .and_then(|s| s.as_str())
        .unwrap();
    let exp_prefixed = exp
        .get("outcome_hash_prefixed")
        .and_then(|s| s.as_str())
        .unwrap();

    // JCS bytes pin.
    let bytes = recovery_outcome_jcs_bytes(&outcome);
    assert_eq!(
        bytes,
        exp_bytes,
        "fixture {:?}: canonical JCS bytes drifted; got {:?}, expected {:?}",
        target_name,
        String::from_utf8_lossy(&bytes),
        String::from_utf8_lossy(&exp_bytes),
    );
    assert_eq!(
        bytes.len(),
        exp_len,
        "fixture {:?}: byte length drift, got {}, expected {}",
        target_name,
        bytes.len(),
        exp_len
    );

    // Bare-hex outer SHA-256 pin.
    let bare = recovery_outcome_sha256_hex(&outcome);
    assert_eq!(
        bare, exp_sha,
        "fixture {:?}: bare SHA-256 drift",
        target_name
    );
    assert_eq!(bare.len(), SHA256_HEX_LEN);

    // Prefixed-form outer SHA-256 pin.
    let prefixed = recovery_outcome_hash_prefixed(&outcome);
    assert_eq!(
        prefixed, exp_prefixed,
        "fixture {:?}: prefixed SHA-256 drift",
        target_name
    );
    assert!(prefixed.starts_with(HASH_PREFIX));

    // Canonical-projection sanity: keys must be alphabetical in the
    // produced bytes (JCS guarantee, exercised end-to-end here).
    let text = std::str::from_utf8(&bytes).unwrap();
    let key_positions = [
        text.find("\"final_state\":").unwrap(),
        text.find("\"phases\":").unwrap(),
        text.find("\"schema\":").unwrap(),
        text.find("\"success\":").unwrap(),
        text.find("\"total_elapsed_sec\":").unwrap(),
        text.find("\"trigger\":").unwrap(),
    ];
    let mut sorted = key_positions.to_vec();
    sorted.sort();
    assert_eq!(
        key_positions.to_vec(),
        sorted,
        "fixture {:?}: top-level keys are not alphabetical in the JCS output",
        target_name
    );
}

#[test]
fn f02_fixture_f01_clean_r1_r4_byte_parity() {
    run_single_fixture("f01-clean-r1-r4");
}

#[test]
fn f03_fixture_f02_r2_fail_retry_byte_parity() {
    run_single_fixture("f02-r2-fail-retry");
}

#[test]
fn f04_fixture_f03_r3_skip_byte_parity() {
    run_single_fixture("f03-r3-skip");
}

#[test]
fn f05_fixture_f04_r1_error_immediate_byte_parity() {
    run_single_fixture("f04-r1-error-immediate");
}

#[test]
fn f06_fixture_f05_r4_timeout_byte_parity() {
    run_single_fixture("f05-r4-timeout");
}

// ---------------------------------------------------------------------
// F07 — Inline base64 decoder sanity.
// ---------------------------------------------------------------------

#[test]
fn f07_inline_b64_decoder_sanity() {
    // Standard RFC 4648 vector triples.
    assert_eq!(b64_decode("Zg=="), b"f");
    assert_eq!(b64_decode("Zm8="), b"fo");
    assert_eq!(b64_decode("Zm9v"), b"foo");
    assert_eq!(b64_decode("Zm9vYg=="), b"foob");
    assert_eq!(b64_decode("Zm9vYmE="), b"fooba");
    assert_eq!(b64_decode("Zm9vYmFy"), b"foobar");
}

// ---------------------------------------------------------------------
// F08 — Trigger wire-string round-trip across the five fixtures.
// ---------------------------------------------------------------------

#[test]
fn f08_trigger_wire_strings_round_trip_across_fixtures() {
    let v = load_fixtures();
    let fixtures = v.get("fixtures").and_then(|f| f.as_array()).unwrap();
    for fx in fixtures {
        let name = fx.get("name").and_then(|s| s.as_str()).unwrap();
        let trig_str = fx
            .get("input")
            .and_then(|i| i.get("trigger"))
            .and_then(|s| s.as_str())
            .unwrap();
        let trig = trigger_from_str(trig_str);
        assert_eq!(
            trig.as_str(),
            trig_str,
            "fixture {:?} trigger round-trip drift",
            name
        );
    }
}

// ---------------------------------------------------------------------
// F09 — Canonical-projection drops non-zero timing input.
// ---------------------------------------------------------------------

#[test]
fn f09_canonical_projection_zeroes_timing_regardless_of_input() {
    // The helper accepts a RecoveryOutcome with non-zero timing fields
    // and zeroes them in the projection. The cross-lang fixture relies
    // on this property so the pin is run-independent.
    let outcome = RecoveryOutcome {
        trigger: RecoveryTrigger::CrashDetected,
        phases: vec![PhaseResult {
            phase: "R1".to_owned(),
            terminal_status: "detected".to_owned(),
            elapsed_sec: 9999.99,
            soft_cap_exceeded: true,
            audit_annotation: "recovery_trigger_classified=CrashDetected".to_owned(),
        }],
        total_elapsed_sec: 9999.99,
        final_state: "running".to_owned(),
        success: true,
    };
    let value = recovery_outcome_canonical_value(&outcome);
    let obj = value.as_object().unwrap();
    assert_eq!(obj.get("total_elapsed_sec").unwrap().as_f64().unwrap(), 0.0);
    let phases = obj.get("phases").and_then(|a| a.as_array()).unwrap();
    let ph = phases[0].as_object().unwrap();
    assert_eq!(ph.get("elapsed_sec").unwrap().as_f64().unwrap(), 0.0);
    assert_eq!(
        ph.get("soft_cap_exceeded").unwrap().as_bool().unwrap(),
        false
    );
}
