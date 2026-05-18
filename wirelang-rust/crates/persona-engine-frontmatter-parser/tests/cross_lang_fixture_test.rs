// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Cross-lang fixture parity tests for persona-engine-frontmatter-parser
// canonical-trace (Tag-34 Mini-Welle, Phase-3a Python-sync — 11th module).
//
// These tests consume the same authoritative JSON fixture file
// (`tests/fixtures/frontmatter-parser-cross-lang/fixtures.json`
// at the repo root) that the Python sibling test
// (`wirelang/tests/persona/test_frontmatter_parser_cross_lang_parity.py`)
// consumes. Both sides pin the same trace-JCS-bytes / trace-SHA-256
// tuples, so any drift on either side breaks both test suites — that
// is the intended boundary detector.
//
// The fixture file path is computed from the `CARGO_MANIFEST_DIR`
// env-var at build time and walks up to the repo root.
//
// Test taxonomy
// -------------
// - F01 — Fixture file loads, schema_version matches the
//   `FRONTMATTER_TRACE_SCHEMA` constant, exactly 7 vectors present.
// - F02 — Per-vector trace-build pin (parametrised loop): byte-level
//   parity for input decode, status enum, error_class, persona_name,
//   persona_slug, schema_version, tools_count, canonical-subset SHA,
//   trace JCS bytes, trace JCS bytes length, bare hex hash,
//   prefixed hash.
// - F03 — Inline base64 decoder sanity.
// - F04 — Wire-shape key order (alphabetical), tested on a
//   trace-build outcome.
// - F05 — Hash-shape pin (length, lowercase, hex alphabet, prefix).
// - F06 — Error-path canonical SHA is empty string (schema-symmetry).
// - F07 — V-907 pin pack anchor: f01 canonical subset SHA equals
//   PERSONA_HASH_PIN_V9.
// - F08 — Status enum constants match Python on all five wire-strings.

use persona_engine_frontmatter_parser::canonical::{
    build_frontmatter_trace, serialize_trace, trace_hash_prefixed, trace_sha256_hex,
    FrontmatterParseTrace, FRONTMATTER_TRACE_SCHEMA, HASH_PREFIX, SHA256_HEX_LEN,
    STATUS_INVALID_SHAPE, STATUS_MALFORMED, STATUS_MISSING_FENCE, STATUS_OK,
    STATUS_YAML_PARSE_ERROR,
};
use serde_json::Value;
use std::path::PathBuf;

const PERSONA_HASH_PIN_V9: &str =
    "0f298894204e6117e42ad7073b7a3af8ada1851de74d585fc5cb4c4d70e1d793";

// ---------------------------------------------------------------------
// Inline base64 decoder (RFC 4648 standard alphabet, no line breaks).
// Identical pattern to the lifecycle-fsm sibling fixture test.
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

fn fixture_path() -> PathBuf {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest
        .parent() // wirelang-rust/crates
        .and_then(|p| p.parent()) // wirelang-rust
        .and_then(|p| p.parent()) // repo root
        .expect("CARGO_MANIFEST_DIR walks up to repo root");
    repo_root
        .join("tests")
        .join("fixtures")
        .join("frontmatter-parser-cross-lang")
        .join("fixtures.json")
}

fn load_fixtures() -> Value {
    let bytes = std::fs::read(fixture_path()).expect("fixtures.json must be present");
    serde_json::from_slice(&bytes).expect("fixtures.json must be valid JSON")
}

// ---------------------------------------------------------------------
// F01 — fixture file structure.
// ---------------------------------------------------------------------

#[test]
fn f01_fixture_file_loads_with_expected_structure() {
    let doc = load_fixtures();
    assert_eq!(
        doc["schema_version"].as_str().unwrap(),
        FRONTMATTER_TRACE_SCHEMA
    );
    let fixtures = doc["fixtures"].as_array().expect("fixtures is an array");
    assert_eq!(fixtures.len(), 7, "Tag-34 cross-lang vector count is 7");
    for f in fixtures {
        for key in &["name", "input_md_b64", "expected"] {
            assert!(
                f.get(*key).is_some(),
                "fixture missing key {} in {:?}",
                key,
                f.get("name")
            );
        }
        let expected = f["expected"].as_object().expect("expected is an object");
        for key in &[
            "accepted_status",
            "error_class",
            "persona_name",
            "persona_slug",
            "schema_version",
            "tools_count",
            "canonical_subset_jcs_sha256_hex",
            "trace_jcs_bytes_b64",
            "trace_jcs_bytes_len",
            "trace_sha256_hex",
            "trace_hash_prefixed",
        ] {
            assert!(
                expected.contains_key(*key),
                "expected missing key {} in {:?}",
                key,
                f.get("name")
            );
        }
    }
}

// ---------------------------------------------------------------------
// F02 — per-vector byte-parity pin.
// ---------------------------------------------------------------------

#[test]
fn f02_per_vector_byte_parity() {
    let doc = load_fixtures();
    let fixtures = doc["fixtures"].as_array().unwrap();
    assert_eq!(fixtures.len(), 7);
    for f in fixtures {
        let name = f["name"].as_str().unwrap();
        let md_bytes = b64_decode(f["input_md_b64"].as_str().unwrap());
        let md = std::str::from_utf8(&md_bytes).expect("md input is UTF-8");
        let expected = &f["expected"];

        let trace = build_frontmatter_trace(md);

        // Structured-field equality.
        assert_eq!(
            trace.accepted_status,
            expected["accepted_status"].as_str().unwrap(),
            "{}: accepted_status",
            name
        );
        assert_eq!(
            trace.error_class,
            expected["error_class"].as_str().unwrap(),
            "{}: error_class",
            name
        );
        assert_eq!(
            trace.persona_name,
            expected["persona_name"].as_str().unwrap(),
            "{}: persona_name",
            name
        );
        assert_eq!(
            trace.persona_slug,
            expected["persona_slug"].as_str().unwrap(),
            "{}: persona_slug",
            name
        );
        assert_eq!(
            trace.schema_version,
            expected["schema_version"].as_str().unwrap(),
            "{}: schema_version",
            name
        );
        assert_eq!(
            trace.tools_count,
            expected["tools_count"].as_u64().unwrap(),
            "{}: tools_count",
            name
        );
        assert_eq!(
            trace.canonical_subset_jcs_sha256_hex,
            expected["canonical_subset_jcs_sha256_hex"].as_str().unwrap(),
            "{}: canonical_subset_jcs_sha256_hex",
            name
        );

        // Byte-level parity.
        let jcs_actual = serialize_trace(&trace);
        let jcs_expected = b64_decode(expected["trace_jcs_bytes_b64"].as_str().unwrap());
        assert_eq!(jcs_actual, jcs_expected, "{}: trace JCS bytes", name);
        assert_eq!(
            jcs_actual.len(),
            expected["trace_jcs_bytes_len"].as_u64().unwrap() as usize,
            "{}: trace JCS byte-length",
            name
        );
        assert_eq!(
            trace_sha256_hex(&trace),
            expected["trace_sha256_hex"].as_str().unwrap(),
            "{}: trace SHA-256 hex",
            name
        );
        assert_eq!(
            trace_hash_prefixed(&trace),
            expected["trace_hash_prefixed"].as_str().unwrap(),
            "{}: trace prefixed hash",
            name
        );
    }
}

// ---------------------------------------------------------------------
// F03 — base64 decoder sanity.
// ---------------------------------------------------------------------

#[test]
fn f03_b64_decoder_sanity() {
    assert_eq!(b64_decode(""), Vec::<u8>::new());
    assert_eq!(b64_decode("Zg=="), b"f");
    assert_eq!(b64_decode("Zm8="), b"fo");
    assert_eq!(b64_decode("Zm9v"), b"foo");
    assert_eq!(b64_decode("Zm9vYg=="), b"foob");
    assert_eq!(b64_decode("Zm9vYmFy"), b"foobar");
}

// ---------------------------------------------------------------------
// F04 — wire-shape key order is alphabetical.
// ---------------------------------------------------------------------

#[test]
fn f04_wire_keys_alphabetical() {
    let md = "---\n\
              name: order\n\
              description: alpha-order pin\n\
              tools: [Read]\n\
              schema_version: persona-v1\n\
              identity_pinned:\n  \
                cross_review_zones: []\n  \
                authority: {push_remote: false, budget_cap_eur_per_month: 0, sub_delegation: false}\n  \
                hierarchy: {reports_to: cto, escalation: cto}\n\
              ---\nbody\n";
    let trace = build_frontmatter_trace(md);
    assert_eq!(trace.accepted_status, STATUS_OK);
    let jcs = serialize_trace(&trace);
    // Parse back. serde_json::Map preserves insertion order, and JCS
    // inserts keys in sorted order, so iterating Map yields a sorted
    // sequence.
    let parsed: serde_json::Map<String, Value> =
        serde_json::from_slice(&jcs).expect("trace JCS bytes parse back as JSON");
    let keys: Vec<&str> = parsed.keys().map(|s| s.as_str()).collect();
    let mut sorted = keys.clone();
    sorted.sort();
    assert_eq!(
        keys, sorted,
        "trace wire-form keys must appear in alphabetical order"
    );
    let expected_keys = vec![
        "accepted_status",
        "canonical_subset_jcs_sha256_hex",
        "error_class",
        "persona_name",
        "persona_slug",
        "schema",
        "schema_version",
        "tools_count",
    ];
    assert_eq!(keys, expected_keys);
}

// ---------------------------------------------------------------------
// F05 — hash-shape pin.
// ---------------------------------------------------------------------

#[test]
fn f05_hash_shape_pin() {
    let md = "---\n\
              name: hash-shape\n\
              description: pin\n\
              tools: [Read]\n\
              schema_version: persona-v1\n\
              identity_pinned:\n  \
                cross_review_zones: []\n  \
                authority: {push_remote: false, budget_cap_eur_per_month: 0, sub_delegation: false}\n  \
                hierarchy: {reports_to: cto, escalation: cto}\n\
              ---\nbody\n";
    let trace = build_frontmatter_trace(md);
    let bare = trace_sha256_hex(&trace);
    let prefixed = trace_hash_prefixed(&trace);
    assert_eq!(bare.len(), SHA256_HEX_LEN);
    assert_eq!(bare, bare.to_lowercase());
    assert!(bare.chars().all(|c| c.is_ascii_hexdigit() && (c.is_ascii_digit() || c.is_ascii_lowercase())));
    assert!(prefixed.starts_with(HASH_PREFIX));
    assert_eq!(&prefixed[HASH_PREFIX.len()..], bare);
}

// ---------------------------------------------------------------------
// F06 — error-path canonical SHA is empty.
// ---------------------------------------------------------------------

#[test]
fn f06_error_paths_have_empty_canonical_sha() {
    let doc = load_fixtures();
    let mut error_paths_seen = 0;
    for f in doc["fixtures"].as_array().unwrap() {
        if f["expected"]["accepted_status"].as_str().unwrap() == STATUS_OK {
            continue;
        }
        error_paths_seen += 1;
        let md_bytes = b64_decode(f["input_md_b64"].as_str().unwrap());
        let md = std::str::from_utf8(&md_bytes).unwrap();
        let trace = build_frontmatter_trace(md);
        assert_eq!(
            trace.canonical_subset_jcs_sha256_hex, "",
            "{} (error path): canonical_subset_jcs_sha256_hex must be empty string",
            f["name"].as_str().unwrap()
        );
        assert_eq!(
            f["expected"]["canonical_subset_jcs_sha256_hex"]
                .as_str()
                .unwrap(),
            ""
        );
    }
    assert!(
        error_paths_seen >= 4,
        "at least 4 error-path fixtures expected, saw {}",
        error_paths_seen
    );
}

// ---------------------------------------------------------------------
// F07 — V-907 pin pack anchor: f01 canonical-subset SHA matches V9 pin.
// ---------------------------------------------------------------------

#[test]
fn f07_v907_pin_pack_anchor() {
    let doc = load_fixtures();
    let f01 = doc["fixtures"]
        .as_array()
        .unwrap()
        .iter()
        .find(|f| f["name"].as_str().unwrap() == "f01-full-v9-persona")
        .expect("f01 fixture present");
    let canonical_sha = f01["expected"]["canonical_subset_jcs_sha256_hex"]
        .as_str()
        .unwrap();
    assert_eq!(
        canonical_sha, PERSONA_HASH_PIN_V9,
        "f01 must anchor into the V-907 pin pack"
    );

    // Re-derive via the Rust trace path.
    let md_bytes = b64_decode(f01["input_md_b64"].as_str().unwrap());
    let md = std::str::from_utf8(&md_bytes).unwrap();
    let trace = build_frontmatter_trace(md);
    assert_eq!(trace.canonical_subset_jcs_sha256_hex, PERSONA_HASH_PIN_V9);
    assert_eq!(trace.accepted_status, STATUS_OK);
}

// ---------------------------------------------------------------------
// F08 — status enum constants pin.
// ---------------------------------------------------------------------

#[test]
fn f08_status_enum_constants_pin() {
    assert_eq!(STATUS_OK, "ok");
    assert_eq!(STATUS_MISSING_FENCE, "missing_fence");
    assert_eq!(STATUS_MALFORMED, "malformed");
    assert_eq!(STATUS_YAML_PARSE_ERROR, "yaml_parse_error");
    assert_eq!(STATUS_INVALID_SHAPE, "invalid_shape");
}

// ---------------------------------------------------------------------
// F09 — determinism: two builds of the same input -> identical traces.
// ---------------------------------------------------------------------

#[test]
fn f09_build_is_deterministic() {
    let md = "---\n\
              name: dup\n\
              description: determinism\n\
              tools: [Read]\n\
              schema_version: persona-v1\n\
              identity_pinned:\n  \
                cross_review_zones: []\n  \
                authority: {push_remote: false, budget_cap_eur_per_month: 0, sub_delegation: false}\n  \
                hierarchy: {reports_to: cto, escalation: cto}\n\
              ---\nbody\n";
    let t1: FrontmatterParseTrace = build_frontmatter_trace(md);
    let t2: FrontmatterParseTrace = build_frontmatter_trace(md);
    assert_eq!(t1, t2);
    assert_eq!(serialize_trace(&t1), serialize_trace(&t2));
    assert_eq!(trace_sha256_hex(&t1), trace_sha256_hex(&t2));
}
