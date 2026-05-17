// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Cross-lang fixture parity tests for persona-engine-federation-resolver
// (Tag-24 Mini-Welle, Phase-3a Python-sync, 9. Modul).
//
// These tests consume the same authoritative JSON fixture file
// (`tests/fixtures/federation-resolver-cross-lang/fixtures.json` at
// the repo root) that the Python sibling test
// (`tests/identity/test_federation_resolver_cross_lang_parity.py`)
// consumes. Both sides pin the same canonical-snapshot-JCS-bytes /
// canonical-SHA-256 tuples, so any drift on either side breaks both
// test suites -- that is the intended boundary detector.
//
// The fixture file path is computed from `CARGO_MANIFEST_DIR` at
// build time and walks up to the repo root. This keeps the crate
// movable within the workspace without hard-coded paths.
//
// Test taxonomy
// -------------
// - F01 -- Fixture file loads, `schema_version` matches the
//   per-resolver-snapshot schema string, exactly 5 vectors present,
//   names + input/expected key sets match the documented contract.
//   Also pins the public-constants surface (mirrors Python T01).
// - F02 -- Empty-resolver snapshot byte-pin from the fresh
//   `InMemoryFederationResolver::new()` path.
// - F03..F07 -- Per-fixture byte-level pin: canonical JCS bytes,
//   bare-hex outer hash, prefixed outer hash, byte length. One test
//   per fixture name for fine-grained failure isolation.
// - F08 -- Inline base64 decoder sanity (the cross-lang tests trust it).
// - F09 -- Resolution-probe parity across all 5 fixtures.
// - F10 -- Insertion-order invariance: a resolver built in the
//   reverse order of the fixture file's input_entries produces the
//   same snapshot bytes as the in-order build.
//
// Base64 decoding strategy
// ------------------------
// The fixture file encodes byte fields as base64 so JSON remains
// text-only. Rather than add the `base64` crate as a dev-dependency
// we inline a small lookup-table decoder; the fixture data is
// hard-coded and base64-decoded once per test. Identical pattern to
// `persona-engine-state-backing` (Tag-23 PR #183) and
// `persona-engine-recovery` (Tag-20).

use persona_engine_federation_resolver::{
    resolver_snapshot_hash_prefixed, resolver_snapshot_sha256_hex,
    serialize_resolver_snapshot, FederationResolver, FederationResolverSnapshot,
    InMemoryFederationResolver, OperatorOrgKeyEntry, DEFAULT_ALG,
    FEDERATION_RESOLVER_SCHEMA, HASH_PREFIX, PUBLIC_KEY_HEX_LEN, SHA256_HEX_LEN,
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
    // <repo>/wirelang-rust/crates/persona-engine-federation-resolver.
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
        .join("federation-resolver-cross-lang")
        .join("fixtures.json")
}

fn load_fixtures() -> Value {
    let path = fixture_path();
    let raw = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("could not read fixture file {:?}: {}", path, e));
    serde_json::from_str(&raw)
        .unwrap_or_else(|e| panic!("could not parse fixture file as JSON: {}", e))
}

const EXPECTED_SCHEMA_VERSION: &str = "wakir.federation.resolver-snapshot/1";
const EXPECTED_FIXTURE_NAMES: [&str; 5] = [
    "f01-empty-resolver",
    "f02-single-org-multi-cluster",
    "f03-multi-org-disjoint",
    "f04-key-rotation-history",
    "f05-expired-mapping",
];

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------

fn entry_from_value(v: &Value) -> OperatorOrgKeyEntry {
    let obj = v.as_object().expect("entry is a JSON object");
    OperatorOrgKeyEntry {
        alg: obj["alg"].as_str().unwrap().to_string(),
        cluster_id: obj["cluster_id"].as_str().unwrap().to_string(),
        org_id: obj["org_id"].as_str().unwrap().to_string(),
        public_key_hex: obj["public_key_hex"].as_str().unwrap().to_string(),
        valid_from: obj["valid_from"].as_str().unwrap().to_string(),
        valid_until: obj["valid_until"].as_str().unwrap().to_string(),
    }
}

fn resolver_from_fixture(fx: &Value) -> InMemoryFederationResolver {
    let inputs = fx
        .get("input_entries")
        .and_then(|a| a.as_array())
        .expect("input_entries is a JSON array");
    let mut r = InMemoryFederationResolver::new();
    for e in inputs {
        r.register(entry_from_value(e))
            .expect("fixture entry should validate");
    }
    r
}

fn find_fixture<'a>(doc: &'a Value, name: &str) -> &'a Value {
    doc.get("fixtures")
        .and_then(|f| f.as_array())
        .unwrap()
        .iter()
        .find(|f| f.get("name").and_then(|s| s.as_str()) == Some(name))
        .unwrap_or_else(|| panic!("fixture {:?} not in fixture file", name))
}

// ---------------------------------------------------------------------
// F01 -- Fixture file structure pin + public constants pin.
// ---------------------------------------------------------------------

#[test]
fn f01_fixture_file_loads_and_constants_pin() {
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

    for fx in fixtures {
        let name = fx.get("name").and_then(|s| s.as_str()).unwrap();
        assert!(fx.get("comment").is_some(), "fixture {:?} missing comment", name);
        assert!(
            fx.get("input_entries").and_then(|a| a.as_array()).is_some(),
            "fixture {:?} missing input_entries array",
            name
        );
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
        let probe = fx.get("resolve_probe").and_then(|x| x.as_object()).unwrap();
        for k in ["org_id", "cluster_id", "now_utc", "expected_match"] {
            assert!(
                probe.contains_key(k),
                "fixture {:?} missing resolve_probe.{}",
                name,
                k
            );
        }
    }

    // Const surface pin (mirrors Python T01).
    assert_eq!(FEDERATION_RESOLVER_SCHEMA, "wakir.federation.resolver-snapshot/1");
    assert_eq!(HASH_PREFIX, "sha256:");
    assert_eq!(SHA256_HEX_LEN, 64);
    assert_eq!(PUBLIC_KEY_HEX_LEN, 64);
    assert_eq!(DEFAULT_ALG, "Ed25519");
}

// ---------------------------------------------------------------------
// F02 -- Empty-resolver snapshot byte-pin.
// ---------------------------------------------------------------------

#[test]
fn f02_empty_resolver_snapshot_byte_pin() {
    let r = InMemoryFederationResolver::new();
    let snap = r.snapshot();
    let bytes = serialize_resolver_snapshot(&snap);
    assert_eq!(
        std::str::from_utf8(&bytes).unwrap(),
        r#"{"entries":[],"schema":"wakir.federation.resolver-snapshot/1"}"#,
        "empty snapshot bytes drifted",
    );
    // Sanity: snapshot type carries the schema string verbatim.
    let typed: FederationResolverSnapshot = snap;
    assert_eq!(typed.entries.len(), 0);
    assert_eq!(typed.schema, FEDERATION_RESOLVER_SCHEMA);
}

// ---------------------------------------------------------------------
// Per-fixture byte-level pin runner.
// ---------------------------------------------------------------------

fn run_single_fixture(target_name: &str) {
    let v = load_fixtures();
    let fx = find_fixture(&v, target_name);
    let r = resolver_from_fixture(fx);
    let snap = r.snapshot();
    let bytes = serialize_resolver_snapshot(&snap);

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

    assert_eq!(
        bytes,
        exp_bytes,
        "fixture {:?}: canonical JCS bytes drifted;\n got     {:?}\n expect  {:?}",
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
    assert_eq!(
        resolver_snapshot_sha256_hex(&snap),
        exp_sha,
        "fixture {:?}: bare-hex SHA-256 drifted",
        target_name
    );
    assert_eq!(
        resolver_snapshot_hash_prefixed(&snap),
        exp_prefixed,
        "fixture {:?}: prefixed-form SHA-256 drifted",
        target_name
    );
}

// ---------------------------------------------------------------------
// F03..F07 -- Per-fixture byte-level pins.
// ---------------------------------------------------------------------

#[test]
fn f03_empty_resolver_fixture_byte_parity() {
    run_single_fixture("f01-empty-resolver");
}

#[test]
fn f04_single_org_multi_cluster_byte_parity() {
    run_single_fixture("f02-single-org-multi-cluster");
}

#[test]
fn f05_multi_org_disjoint_byte_parity() {
    run_single_fixture("f03-multi-org-disjoint");
}

#[test]
fn f06_key_rotation_history_byte_parity() {
    run_single_fixture("f04-key-rotation-history");
}

#[test]
fn f07_expired_mapping_byte_parity() {
    run_single_fixture("f05-expired-mapping");
}

// ---------------------------------------------------------------------
// F08 -- Inline base64 decoder sanity.
// ---------------------------------------------------------------------

#[test]
fn f08_base64_decoder_sanity() {
    // RFC 4648 test vectors.
    assert_eq!(b64_decode(""), b"".to_vec());
    assert_eq!(b64_decode("Zg=="), b"f".to_vec());
    assert_eq!(b64_decode("Zm8="), b"fo".to_vec());
    assert_eq!(b64_decode("Zm9v"), b"foo".to_vec());
    assert_eq!(b64_decode("Zm9vYg=="), b"foob".to_vec());
    assert_eq!(b64_decode("Zm9vYmE="), b"fooba".to_vec());
    assert_eq!(b64_decode("Zm9vYmFy"), b"foobar".to_vec());
}

// ---------------------------------------------------------------------
// F09 -- Resolution-probe parity across all 5 fixtures.
// ---------------------------------------------------------------------

#[test]
fn f09_resolve_probe_parity_all_fixtures() {
    let v = load_fixtures();
    for name in EXPECTED_FIXTURE_NAMES.iter() {
        let fx = find_fixture(&v, name);
        let r = resolver_from_fixture(fx);
        let probe = fx
            .get("resolve_probe")
            .and_then(|x| x.as_object())
            .unwrap();
        let org_id = probe.get("org_id").and_then(|s| s.as_str()).unwrap();
        let cluster_id = probe.get("cluster_id").and_then(|s| s.as_str()).unwrap();
        let now = probe.get("now_utc").and_then(|s| s.as_str()).unwrap();
        let expected = probe.get("expected_match").unwrap();

        let got = r.resolve(org_id, cluster_id, now);
        if expected.is_null() {
            assert!(
                got.is_none(),
                "fixture {:?}: resolve_probe expected None, got {:?}",
                name,
                got
            );
        } else {
            let got = got.unwrap_or_else(|| {
                panic!("fixture {:?}: resolve_probe expected match, got None", name)
            });
            let exp = expected.as_object().unwrap();
            assert_eq!(got.alg, exp.get("alg").unwrap().as_str().unwrap(), "alg drift in {}", name);
            assert_eq!(
                got.org_id,
                exp.get("org_id").unwrap().as_str().unwrap(),
                "org_id drift in {}",
                name
            );
            assert_eq!(
                got.cluster_id,
                exp.get("cluster_id").unwrap().as_str().unwrap(),
                "cluster_id drift in {}",
                name
            );
            assert_eq!(
                got.public_key_hex,
                exp.get("public_key_hex").unwrap().as_str().unwrap(),
                "public_key_hex drift in {}",
                name
            );
            assert_eq!(
                got.valid_from,
                exp.get("valid_from").unwrap().as_str().unwrap(),
                "valid_from drift in {}",
                name
            );
            assert_eq!(
                got.valid_until,
                exp.get("valid_until").unwrap().as_str().unwrap(),
                "valid_until drift in {}",
                name
            );
        }
    }
}

// ---------------------------------------------------------------------
// F10 -- Insertion-order invariance: building the resolver in
// reverse order yields the same snapshot bytes.
// ---------------------------------------------------------------------

#[test]
fn f10_insertion_order_invariance() {
    let v = load_fixtures();
    for name in EXPECTED_FIXTURE_NAMES.iter() {
        let fx = find_fixture(&v, name);
        let inputs = fx
            .get("input_entries")
            .and_then(|a| a.as_array())
            .unwrap();
        let mut r_forward = InMemoryFederationResolver::new();
        for e in inputs {
            r_forward.register(entry_from_value(e)).unwrap();
        }
        let mut r_reverse = InMemoryFederationResolver::new();
        for e in inputs.iter().rev() {
            r_reverse.register(entry_from_value(e)).unwrap();
        }
        let b_forward = serialize_resolver_snapshot(&r_forward.snapshot());
        let b_reverse = serialize_resolver_snapshot(&r_reverse.snapshot());
        assert_eq!(
            b_forward, b_reverse,
            "fixture {:?}: insertion-order MUST NOT affect snapshot bytes",
            name
        );
    }
}
