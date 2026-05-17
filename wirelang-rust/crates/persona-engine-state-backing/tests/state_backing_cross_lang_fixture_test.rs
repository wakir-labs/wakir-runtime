// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Cross-lang fixture parity tests for persona-engine-state-backing
// (Tag-23 Mini-Welle, Phase-3a Python-sync, 8. Modul).
//
// These tests consume the same authoritative JSON fixture file
// (`tests/fixtures/state-backing-cross-lang/fixtures.json` at the
// repo root) that the Python sibling test
// (`wirelang/tests/persona_engine/test_state_backing_cross_lang_parity.py`)
// consumes. Both sides pin the same canonical-snapshot-JCS-bytes /
// canonical-SHA-256 tuples, so any drift on either side breaks both
// test suites — that is the intended boundary detector.
//
// The fixture file path is computed from the `CARGO_MANIFEST_DIR`
// env-var at build time and walks up to the repo root. This keeps
// the crate movable within the workspace without hard-coded paths.
//
// Test taxonomy
// -------------
// - F01 — Fixture file loads, `schema_version` matches the
//   per-state-snapshot schema string, exactly 5 vectors present,
//   names + input/expected key sets match the documented contract.
// - F02..F06 — Per-fixture byte-level pin: canonical JCS bytes,
//   bare-hex outer hash, prefixed outer hash, byte length. One test
//   per fixture name for fine-grained failure isolation.
// - F07 — Inline base64 decoder sanity (the cross-lang tests trust it).
// - F08 — Snapshot envelope round-trip across the five fixtures
//   (`snapshot_from_jcs_bytes(snapshot_to_jcs_bytes(snap)) == snap`).
// - F09 — InMemoryStateBacking replays each fixture: first snapshot
//   for a fresh persona-id lands at offset 1, `restore_latest`
//   round-trips byte-identical content. Idempotent re-snapshot
//   returns the same offset (no new write).
// - F10 — Empty-token-list drift sentinel: f01-empty-state and
//   f05-delete-then-get must contain the literal
//   `"capability_token_ids":[]` segment (not a `null` re-serialisation).
//
// Base64 decoding strategy
// ------------------------
// The fixture file encodes byte fields as base64 so JSON remains
// text-only. Rather than add the `base64` crate as a dev-dependency
// we inline a small lookup-table decoder; the fixture data is
// hard-coded and base64-decoded once per test. Identical pattern to
// the `persona-engine-recovery` Tag-20 PR cross-lang fixture test.

use persona_engine_state_backing::{
    snapshot_from_jcs_bytes, snapshot_payload_sha256, snapshot_to_jcs_bytes, InMemoryStateBacking,
    PersonaStateSnapshot, StateBacking, LATEST_KEY, NEXT_OFFSET_KEY, OFFSET_KEY_WIDTH, PINNED_KEY,
    STATE_PACK_KEY_PREFIX,
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
    // <repo>/wirelang-rust/crates/persona-engine-state-backing.
    // Walk up three levels to reach <repo>, then into tests/fixtures/.
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest
        .parent() // wirelang-rust/crates
        .and_then(|p| p.parent()) // wirelang-rust
        .and_then(|p| p.parent()) // repo root
        .expect("could not resolve repo root from CARGO_MANIFEST_DIR");
    repo_root
        .join("tests")
        .join("fixtures")
        .join("state-backing-cross-lang")
        .join("fixtures.json")
}

fn load_fixtures() -> Value {
    let path = fixture_path();
    let raw = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("could not read fixture file {:?}: {}", path, e));
    serde_json::from_str(&raw)
        .unwrap_or_else(|e| panic!("could not parse fixture file as JSON: {}", e))
}

const EXPECTED_SCHEMA_VERSION: &str = "wakir.persona-engine.persona-state-snapshot/1";
const EXPECTED_FIXTURE_NAMES: [&str; 5] = [
    "f01-empty-state",
    "f02-single-key",
    "f03-multi-key",
    "f04-overwrite-existing",
    "f05-delete-then-get",
];

// ---------------------------------------------------------------------
// Helper: construct a PersonaStateSnapshot from a fixture input block.
// ---------------------------------------------------------------------

fn snapshot_from_fixture_input(inp: &serde_json::Map<String, Value>) -> PersonaStateSnapshot {
    let persona_hash = inp
        .get("persona_hash")
        .and_then(|s| s.as_str())
        .unwrap()
        .to_owned();
    let audit_trace_offset = inp
        .get("audit_trace_offset")
        .and_then(|n| n.as_u64())
        .unwrap();
    let capability_token_ids: Vec<String> = inp
        .get("capability_token_ids")
        .and_then(|a| a.as_array())
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_owned())
        .collect();
    let snapshot_at_utc = inp
        .get("snapshot_at_utc")
        .and_then(|s| s.as_str())
        .unwrap()
        .to_owned();
    let workspace_state_hash = inp
        .get("workspace_state_hash")
        .and_then(|s| s.as_str())
        .unwrap()
        .to_owned();
    PersonaStateSnapshot {
        persona_hash,
        audit_trace_offset,
        capability_token_ids,
        snapshot_at_utc,
        workspace_state_hash,
    }
}

// ---------------------------------------------------------------------
// F01 — Fixture file structure pin.
// ---------------------------------------------------------------------

#[test]
fn f01_fixture_file_loads_and_schema_matches_pin() {
    let v = load_fixtures();
    let schema = v
        .get("schema_version")
        .and_then(|s| s.as_str())
        .expect("fixture file must carry a 'schema_version' string field");
    assert_eq!(
        schema, EXPECTED_SCHEMA_VERSION,
        "fixture schema_version {:?} drifted from expected {:?}",
        schema, EXPECTED_SCHEMA_VERSION
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
    assert_eq!(names, EXPECTED_FIXTURE_NAMES.to_vec());

    // Every fixture has the documented input + expected fields.
    for fx in fixtures {
        let name = fx.get("name").and_then(|s| s.as_str()).unwrap();
        let inp = fx.get("input").and_then(|x| x.as_object()).unwrap();
        for k in [
            "persona_hash",
            "audit_trace_offset",
            "capability_token_ids",
            "snapshot_at_utc",
            "workspace_state_hash",
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
            "snapshot_jcs_bytes_b64",
            "snapshot_jcs_bytes_len",
            "snapshot_sha256_hex",
            "snapshot_hash_prefixed",
        ] {
            assert!(
                exp.contains_key(k),
                "fixture {:?} missing expected.{}",
                name,
                k
            );
        }
    }

    // Const surface pin (mirrors Python T01).
    assert_eq!(STATE_PACK_KEY_PREFIX, "state-pack");
    assert_eq!(OFFSET_KEY_WIDTH, 20);
    assert_eq!(PINNED_KEY, "state-pack/__pinned__");
    assert_eq!(NEXT_OFFSET_KEY, "state-pack/__next_offset__");
    assert_eq!(LATEST_KEY, "state-pack/latest");
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
    let snap = snapshot_from_fixture_input(inp);

    let exp = fx.get("expected").and_then(|x| x.as_object()).unwrap();
    let exp_bytes_b64 = exp
        .get("snapshot_jcs_bytes_b64")
        .and_then(|s| s.as_str())
        .unwrap();
    let exp_bytes = b64_decode(exp_bytes_b64);
    let exp_len = exp
        .get("snapshot_jcs_bytes_len")
        .and_then(|n| n.as_u64())
        .unwrap() as usize;
    let exp_sha = exp
        .get("snapshot_sha256_hex")
        .and_then(|s| s.as_str())
        .unwrap();
    let exp_prefixed = exp
        .get("snapshot_hash_prefixed")
        .and_then(|s| s.as_str())
        .unwrap();

    // JCS bytes pin.
    let bytes = snapshot_to_jcs_bytes(&snap);
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

    // Prefixed-form outer SHA-256 pin.
    let prefixed = snapshot_payload_sha256(&snap);
    assert_eq!(
        prefixed, exp_prefixed,
        "fixture {:?}: prefixed SHA-256 drift",
        target_name
    );
    assert!(prefixed.starts_with("sha256:"));

    // Bare-hex outer SHA-256 pin (alternate derivation path via the
    // prefixed form — must equal the fixture-pinned bare value).
    let bare = &prefixed[("sha256:".len())..];
    assert_eq!(
        bare, exp_sha,
        "fixture {:?}: bare SHA-256 drift",
        target_name
    );
    assert_eq!(bare.len(), 64);

    // Canonical-projection sanity: top-level keys are alphabetical.
    let text = std::str::from_utf8(&bytes).unwrap();
    let positions = [
        text.find("\"audit_trace_offset\":").unwrap(),
        text.find("\"capability_token_ids\":").unwrap(),
        text.find("\"persona_hash\":").unwrap(),
        text.find("\"snapshot_at_utc\":").unwrap(),
        text.find("\"workspace_state_hash\":").unwrap(),
    ];
    let mut sorted = positions.to_vec();
    sorted.sort();
    assert_eq!(
        positions.to_vec(),
        sorted,
        "fixture {:?}: top-level keys are not alphabetical in the JCS output",
        target_name
    );
}

#[test]
fn f02_fixture_f01_empty_state_byte_parity() {
    run_single_fixture("f01-empty-state");
}

#[test]
fn f03_fixture_f02_single_key_byte_parity() {
    run_single_fixture("f02-single-key");
}

#[test]
fn f04_fixture_f03_multi_key_byte_parity() {
    run_single_fixture("f03-multi-key");
}

#[test]
fn f05_fixture_f04_overwrite_existing_byte_parity() {
    run_single_fixture("f04-overwrite-existing");
}

#[test]
fn f06_fixture_f05_delete_then_get_byte_parity() {
    run_single_fixture("f05-delete-then-get");
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
// F08 — Snapshot envelope round-trip across the five fixtures.
// ---------------------------------------------------------------------

#[test]
fn f08_snapshot_envelope_round_trip_across_fixtures() {
    let v = load_fixtures();
    let fixtures = v.get("fixtures").and_then(|f| f.as_array()).unwrap();
    for fx in fixtures {
        let name = fx.get("name").and_then(|s| s.as_str()).unwrap();
        let inp = fx.get("input").and_then(|x| x.as_object()).unwrap();
        let snap = snapshot_from_fixture_input(inp);
        let blob = snapshot_to_jcs_bytes(&snap);
        let parsed = snapshot_from_jcs_bytes(&blob).unwrap_or_else(|e| {
            panic!("fixture {:?}: round-trip parse failed: {}", name, e)
        });
        assert_eq!(
            parsed, snap,
            "fixture {:?}: envelope round-trip drift",
            name
        );
    }
}

// ---------------------------------------------------------------------
// F09 — InMemoryStateBacking replays each fixture (offset + idempotence).
// ---------------------------------------------------------------------

#[tokio::test]
async fn f09_inmemory_backing_replays_all_fixtures_offset_and_idempotence() {
    let v = load_fixtures();
    let backing = InMemoryStateBacking::new();
    let fixtures = v.get("fixtures").and_then(|f| f.as_array()).unwrap();
    for fx in fixtures {
        let name = fx.get("name").and_then(|s| s.as_str()).unwrap();
        let inp = fx.get("input").and_then(|x| x.as_object()).unwrap();
        let snap = snapshot_from_fixture_input(inp);
        let persona_id = format!("persona-{}", name);
        let off = backing
            .snapshot(&persona_id, snap.clone())
            .await
            .unwrap_or_else(|e| panic!("fixture {:?}: snapshot failed: {}", name, e));
        assert_eq!(
            off, 1,
            "fixture {:?}: first snapshot offset != 1 for a fresh persona-id",
            name
        );
        // restore_latest must echo byte-equal content.
        let restored = backing
            .restore_latest(&persona_id)
            .await
            .unwrap()
            .unwrap_or_else(|| panic!("fixture {:?}: restore_latest returned None", name));
        assert_eq!(
            snapshot_to_jcs_bytes(&restored),
            snapshot_to_jcs_bytes(&snap),
            "fixture {:?}: restore_latest produced byte-drift",
            name
        );
        // Idempotence: re-snapshotting a byte-equal payload returns the existing offset.
        let off_again = backing
            .snapshot(&persona_id, snap.clone())
            .await
            .unwrap_or_else(|e| panic!("fixture {:?}: idempotent re-snapshot failed: {}", name, e));
        assert_eq!(
            off, off_again,
            "fixture {:?}: idempotent re-snapshot must return existing offset",
            name
        );
        // Only one offset entry should be present.
        let offsets = backing.list_snapshots(&persona_id).await.unwrap();
        assert_eq!(
            offsets,
            vec![off],
            "fixture {:?}: idempotent re-snapshot must not append a new entry",
            name
        );
    }
}

// ---------------------------------------------------------------------
// F10 — Empty-token-list drift sentinel.
// ---------------------------------------------------------------------

#[test]
fn f10_empty_token_list_emits_empty_array_literal() {
    let v = load_fixtures();
    for target in ["f01-empty-state", "f05-delete-then-get"] {
        let fx = v
            .get("fixtures")
            .and_then(|f| f.as_array())
            .unwrap()
            .iter()
            .find(|f| f.get("name").and_then(|s| s.as_str()) == Some(target))
            .unwrap();
        let inp = fx.get("input").and_then(|x| x.as_object()).unwrap();
        let snap = snapshot_from_fixture_input(inp);
        let text = String::from_utf8(snapshot_to_jcs_bytes(&snap)).unwrap();
        assert!(
            text.contains("\"capability_token_ids\":[]"),
            "fixture {:?}: empty-list drift; expected literal \
             \"capability_token_ids\":[] in {:?}",
            target,
            text
        );
    }
}
