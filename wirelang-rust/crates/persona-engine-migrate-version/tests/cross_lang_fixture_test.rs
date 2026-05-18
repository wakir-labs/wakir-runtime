// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Cross-language byte-pin test — Rust <-> Python parity for
// `persona-engine-migrate-version` <->
// `wirelang.persona_engine.migrate_version_canonical`.
//
// This test reads the fixture file
// `tests/fixtures/migrate-version-cross-lang/fixtures.json`
// (committed at the repository root, two levels above the Cargo
// workspace root), reconstructs each fixture's input as a typed
// `(from_version, to_version, allow_major_bump)` tuple, calls
// `build_migrate_version_decision_trace`, JCS-serialises the
// resulting trace, hashes it, and asserts byte equality against
// the pinned fields.
//
// The Python suite at
// `wirelang/tests/persona_engine/test_migrate_version_cross_lang_parity.py`
// runs the equivalent assertion. Byte-drift in either direction
// breaks both lanes simultaneously — that is the cross-lang
// contract.
//
// Tag-38 Phase-3a-Foundation 15. Modul.

use persona_engine_migrate_version::{
    build_migrate_version_decision_trace, serialize_trace, trace_hash_prefixed,
    trace_sha256_hex, trace_to_wire_dict, FAILURE_MODE_MAJOR_VERSION_BUMP_DISALLOWED,
    FAILURE_MODE_UNKNOWN_FROM_VERSION, FAILURE_MODE_UNKNOWN_TO_VERSION, HASH_PREFIX,
    KNOWN_ENGINE_VERSIONS, MIGRATE_VERSION_DECISION_TRACE_SCHEMA,
    SHA256_HEX_LEN, STATUS_OK, STATUS_REJECTED,
};
use serde_json::Value;
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

// ---------------------------------------------------------------------
// Fixture file path resolution.
// ---------------------------------------------------------------------

/// Resolve the fixture file from the crate's `CARGO_MANIFEST_DIR`
/// rather than from the current working directory. `cargo test`
/// invocations under different shells / CI runners use different
/// cwds; the manifest-dir-relative path is the only stable anchor.
///
/// Crate manifest: `<repo>/wirelang-rust/crates/persona-engine-migrate-version`
/// Fixture file:   `<repo>/tests/fixtures/migrate-version-cross-lang/fixtures.json`
/// Hops up:        `../../..` (parser-crate -> crates -> wirelang-rust -> repo root).
fn fixture_path() -> PathBuf {
    let manifest_dir = env!(
        "CARGO_MANIFEST_DIR",
        "CARGO_MANIFEST_DIR must be set by cargo"
    );
    let mut p = PathBuf::from(manifest_dir);
    for _ in 0..3 {
        p.pop();
    }
    p.push("tests");
    p.push("fixtures");
    p.push("migrate-version-cross-lang");
    p.push("fixtures.json");
    p
}

fn load_fixtures() -> Value {
    let path = fixture_path();
    let text = fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("read fixture {path:?}: {e}"));
    serde_json::from_str(&text)
        .unwrap_or_else(|e| panic!("parse fixture {path:?}: {e}"))
}

// ---------------------------------------------------------------------
// T01 — Fixture file structure.
// ---------------------------------------------------------------------

#[test]
fn t01_fixture_file_structure() {
    let f = load_fixtures();
    assert_eq!(
        f["schema_version"].as_str().unwrap(),
        MIGRATE_VERSION_DECISION_TRACE_SCHEMA
    );
    let kev = f["known_engine_versions"].as_array().unwrap();
    let kev_strs: Vec<&str> =
        kev.iter().map(|v| v.as_str().unwrap()).collect();
    assert_eq!(kev_strs.as_slice(), KNOWN_ENGINE_VERSIONS);

    let fixtures = f["fixtures"].as_array().unwrap();
    assert_eq!(fixtures.len(), 6);

    let expected_keys: std::collections::BTreeSet<&str> = [
        "name",
        "comment",
        "input",
        "trace",
        "trace_jcs_bytes_b64",
        "trace_jcs_bytes_len",
        "trace_sha256_hex",
        "trace_hash_prefixed",
    ]
    .iter()
    .copied()
    .collect();

    for fx in fixtures {
        let obj = fx.as_object().unwrap();
        let got_keys: std::collections::BTreeSet<&str> =
            obj.keys().map(String::as_str).collect();
        assert_eq!(
            got_keys, expected_keys,
            "fixture {:?} key set drift",
            fx["name"]
        );
    }
}

// ---------------------------------------------------------------------
// T02 — Per-vector byte-parity pin (six fixtures).
// ---------------------------------------------------------------------

#[test]
fn t02_per_vector_byte_parity() {
    let f = load_fixtures();
    let fixtures = f["fixtures"].as_array().unwrap();

    for (i, fx) in fixtures.iter().enumerate() {
        let name = fx["name"].as_str().unwrap();
        let from_v = fx["input"]["from_version"].as_str().unwrap();
        let to_v = fx["input"]["to_version"].as_str().unwrap();
        let bump = fx["input"]["allow_major_bump"].as_bool().unwrap();

        let trace =
            build_migrate_version_decision_trace(from_v, to_v, bump);

        // Trace dict parity.
        let got_wire = trace_to_wire_dict(&trace);
        let want_wire = fx["trace"].clone();
        assert_eq!(
            got_wire, want_wire,
            "[{i}] {name}: wire-dict drift"
        );

        // JCS bytes parity.
        let got_bytes = serialize_trace(&trace);
        let want_bytes = base64_decode(
            fx["trace_jcs_bytes_b64"].as_str().unwrap(),
        );
        assert_eq!(
            got_bytes, want_bytes,
            "[{i}] {name}: JCS bytes drift"
        );
        let want_len = fx["trace_jcs_bytes_len"].as_u64().unwrap() as usize;
        assert_eq!(
            got_bytes.len(),
            want_len,
            "[{i}] {name}: JCS bytes length drift"
        );

        // Hash parity.
        let got_hex = trace_sha256_hex(&trace);
        let want_hex = fx["trace_sha256_hex"].as_str().unwrap();
        assert_eq!(
            got_hex, want_hex,
            "[{i}] {name}: trace_sha256_hex drift"
        );
        let got_prefixed = trace_hash_prefixed(&trace);
        let want_prefixed = fx["trace_hash_prefixed"].as_str().unwrap();
        assert_eq!(
            got_prefixed, want_prefixed,
            "[{i}] {name}: trace_hash_prefixed drift"
        );
    }
}

// ---------------------------------------------------------------------
// T03 — Per-fixture failure-mode pin (semantic spot-check).
// ---------------------------------------------------------------------

#[test]
fn t03_failure_mode_semantic_pin() {
    let f = load_fixtures();
    let fixtures = f["fixtures"].as_array().unwrap();

    // Expected (name, accepted_status, failure_mode) tuples.
    let expected: BTreeMap<&str, (&str, &str)> = [
        ("f01-known-pair-no-bump", (STATUS_OK, "")),
        ("f02-known-pair-allow-bump-flag-on", (STATUS_OK, "")),
        ("f03-known-pair-earliest-to-latest", (STATUS_OK, "")),
        (
            "f04-unknown-from-version",
            (STATUS_REJECTED, FAILURE_MODE_UNKNOWN_FROM_VERSION),
        ),
        (
            "f05-unknown-to-version",
            (STATUS_REJECTED, FAILURE_MODE_UNKNOWN_TO_VERSION),
        ),
        (
            "f06-unparseable-from-version",
            (STATUS_REJECTED, FAILURE_MODE_UNKNOWN_FROM_VERSION),
        ),
    ]
    .iter()
    .copied()
    .collect();

    for fx in fixtures {
        let name = fx["name"].as_str().unwrap();
        let (want_status, want_failure_mode) = expected
            .get(name)
            .copied()
            .unwrap_or_else(|| panic!("unexpected fixture name: {name}"));

        assert_eq!(
            fx["trace"]["accepted_status"].as_str().unwrap(),
            want_status,
            "{name}: accepted_status drift"
        );
        assert_eq!(
            fx["trace"]["failure_mode"].as_str().unwrap(),
            want_failure_mode,
            "{name}: failure_mode drift"
        );
    }

    // Sentinel: the MajorVersionBumpDisallowed wire-string is pinned
    // even though no fixture exercises it (structurally unreachable
    // from the current closed KNOWN_ENGINE_VERSIONS set).
    assert_eq!(
        FAILURE_MODE_MAJOR_VERSION_BUMP_DISALLOWED,
        "MajorVersionBumpDisallowed"
    );
}

// ---------------------------------------------------------------------
// T04 — Wire-shape key order (11 keys, alphabetic).
// ---------------------------------------------------------------------

#[test]
fn t04_wire_shape_key_order_eleven_keys() {
    let t = build_migrate_version_decision_trace(
        "0.3.0-pilot",
        "0.4.0-pilot",
        false,
    );
    let bytes = serialize_trace(&t);
    let s = std::str::from_utf8(&bytes).expect("JCS bytes are UTF-8");
    // JCS canonical bytes are an object literal; the keys appear in
    // alphabetic order. We re-decode into a serde_json::Map and
    // assert the iteration order matches the pin.
    let decoded: serde_json::Map<String, Value> =
        serde_json::from_str(s).expect("re-decode JCS bytes");
    // serde_json with preserve_order keeps insertion order; for a
    // freshly-parsed JCS payload that IS the key order on the wire.
    let got: Vec<&str> = decoded.keys().map(String::as_str).collect();
    let expected = [
        "accepted_status",
        "allow_major_bump",
        "failure_mode",
        "from_major",
        "from_minor",
        "from_version",
        "major_bump_required",
        "schema",
        "to_major",
        "to_minor",
        "to_version",
    ];
    assert_eq!(got, expected);
    assert_eq!(got.len(), 11);
}

// ---------------------------------------------------------------------
// T05 — Hash shape pin.
// ---------------------------------------------------------------------

#[test]
fn t05_hash_shape_pin() {
    let t = build_migrate_version_decision_trace(
        "0.3.0-pilot",
        "0.4.0-pilot",
        false,
    );
    let bare = trace_sha256_hex(&t);
    let prefixed = trace_hash_prefixed(&t);
    assert_eq!(bare.len(), SHA256_HEX_LEN);
    assert!(
        bare.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()),
        "hex must be lower-case ASCII"
    );
    assert!(prefixed.starts_with(HASH_PREFIX));
    assert_eq!(prefixed, format!("{HASH_PREFIX}{bare}"));
}

// ---------------------------------------------------------------------
// Inline base64 decoder (avoid new dev-dependency).
// ---------------------------------------------------------------------
//
// Minimal RFC 4648 base64 decoder for ASCII input with padding.
// Same posture as the inline decoder in the bridge-audit-replay
// cross-lang test suite (PR #246, Tag-37).
fn base64_decode(input: &str) -> Vec<u8> {
    fn idx(c: u8) -> Option<u8> {
        match c {
            b'A'..=b'Z' => Some(c - b'A'),
            b'a'..=b'z' => Some(c - b'a' + 26),
            b'0'..=b'9' => Some(c - b'0' + 52),
            b'+' => Some(62),
            b'/' => Some(63),
            _ => None,
        }
    }
    let bytes = input.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(bytes.len() * 3 / 4);
    let mut buf: u32 = 0;
    let mut bits: u32 = 0;
    for &b in bytes {
        if b == b'=' {
            break;
        }
        if let Some(v) = idx(b) {
            buf = (buf << 6) | (v as u32);
            bits += 6;
            if bits >= 8 {
                bits -= 8;
                out.push(((buf >> bits) & 0xff) as u8);
            }
        }
    }
    out
}
