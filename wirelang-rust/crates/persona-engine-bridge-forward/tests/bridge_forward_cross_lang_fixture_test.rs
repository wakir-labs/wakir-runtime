// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Cross-lang fixture parity tests for persona-engine-bridge-forward
// (Tag-25 Mini-Welle, Phase-3a Python-sync, 10. Modul).
//
// These tests consume the same authoritative JSON fixture file
// (`tests/fixtures/bridge-forward-cross-lang/fixtures.json` at the
// repo root) that the Python sibling test
// (`tests/cli/test_bridge_forward_cross_lang_parity.py`) consumes.
// Both sides pin the same canonical-frame-JCS-bytes / canonical-
// SHA-256 tuples, so any drift on either side breaks both test
// suites -- that is the intended boundary detector.
//
// The fixture file path is computed from `CARGO_MANIFEST_DIR` at
// build time and walks up to the repo root, keeping the crate
// movable within the workspace without hard-coded paths.
//
// Test taxonomy
// -------------
// - F01 -- Fixture file loads, `schema_version` matches the
//   per-frame schema string, exactly 5 vectors present, names +
//   input/expected key sets match the documented contract. Also
//   pins the public-constants surface (mirrors Python T01).
// - F02 -- Empty-payload (f01) byte-pin: minimum-shape frame.
// - F03..F07 -- Per-fixture byte-level pin: canonical JCS bytes,
//   bare-hex outer hash, prefixed outer hash, byte length, subject
//   string. One test per fixture name for fine-grained failure
//   isolation.
// - F08 -- Inline base64 decoder sanity.
// - F09 -- Subject regex parity: all 5 fixtures' expected_subject
//   match the layer-0-transport regex shape.
// - F10 -- Determinism: building the same fixture twice produces
//   byte-identical canonical output.
// - F11 -- Size-limit validation: error-frame (f04) auftrag_id is
//   exactly at the boundary AND passes validate_forward_frame;
//   one byte over rejects.
//
// Base64 decoding strategy
// ------------------------
// The fixture file encodes byte fields as base64 so JSON remains
// text-only. Rather than add the `base64` crate as a dev-dependency
// we inline a small lookup-table decoder; identical pattern to
// `persona-engine-federation-resolver` (Tag-24 PR #188) and
// `persona-engine-state-backing` (Tag-23 PR #183).

use persona_engine_bridge_forward::{
    build_forward_frame, build_subject, forward_frame_hash_prefixed, forward_frame_sha256_hex,
    serialize_and_hash, serialize_forward_frame, validate_forward_frame, AuftragEnvelope,
    BridgeForwardError, ForwardFrameInput, AGENT_TASK_ASSIGNED_SCHEMA,
    BRIDGE_FORWARD_FRAME_SCHEMA, DEFAULT_ORG_ID, DEFAULT_SOURCE, EVENT_KIND_AGENT_TASK_ASSIGNED,
    HASH_PREFIX, MAX_AUFTRAG_ID_OCTETS, MAX_METADATA_BYTES, MAX_PROMPT_PAYLOAD_BYTES,
    SHA256_HEX_LEN,
};
use serde_json::Value;
use std::collections::BTreeMap;
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
// Fixture file path resolution
// ---------------------------------------------------------------------

fn fixture_path() -> PathBuf {
    // CARGO_MANIFEST_DIR is
    // <repo>/wirelang-rust/crates/persona-engine-bridge-forward.
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
        .join("bridge-forward-cross-lang")
        .join("fixtures.json")
}

fn load_fixtures() -> Value {
    let path = fixture_path();
    let raw = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("could not read fixture file {:?}: {}", path, e));
    serde_json::from_str(&raw)
        .unwrap_or_else(|e| panic!("could not parse fixture file as JSON: {}", e))
}

const EXPECTED_SCHEMA_VERSION: &str = "wakir.bridge.forward-frame/1";
const EXPECTED_FIXTURE_NAMES: [&str; 5] = [
    "f01-empty-payload",
    "f02-single-record",
    "f03-multi-record-batch",
    "f04-error-frame",
    "f05-large-payload",
];

// ---------------------------------------------------------------------
// Fixture-to-input helpers
// ---------------------------------------------------------------------

fn input_from_fixture(fx: &Value) -> ForwardFrameInput {
    let inp = fx
        .get("input")
        .and_then(|x| x.as_object())
        .expect("fixture has 'input' object");
    let mut metadata: BTreeMap<String, String> = BTreeMap::new();
    if let Some(m) = inp.get("metadata").and_then(|x| x.as_object()) {
        for (k, v) in m {
            let v = v.as_str().expect("metadata values are strings");
            metadata.insert(k.clone(), v.to_string());
        }
    }
    ForwardFrameInput {
        env: inp.get("env").and_then(|x| x.as_str()).unwrap().to_string(),
        persona_slug: inp
            .get("persona_slug")
            .and_then(|x| x.as_str())
            .unwrap()
            .to_string(),
        auftrag_id: inp
            .get("auftrag_id")
            .and_then(|x| x.as_str())
            .unwrap()
            .to_string(),
        ts_utc: inp
            .get("ts_utc")
            .and_then(|x| x.as_str())
            .unwrap()
            .to_string(),
        prompt_payload: inp
            .get("prompt_payload")
            .and_then(|x| x.as_str())
            .unwrap()
            .to_string(),
        org_id: inp
            .get("org_id")
            .and_then(|x| x.as_str())
            .unwrap()
            .to_string(),
        source: inp
            .get("source")
            .and_then(|x| x.as_str())
            .unwrap()
            .to_string(),
        metadata,
    }
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
        assert!(
            fx.get("comment").is_some(),
            "fixture {:?} missing comment",
            name
        );
        let inp = fx
            .get("input")
            .and_then(|x| x.as_object())
            .unwrap_or_else(|| panic!("fixture {:?} missing input", name));
        for k in [
            "env",
            "persona_slug",
            "auftrag_id",
            "ts_utc",
            "prompt_payload",
            "org_id",
            "source",
            "metadata",
        ] {
            assert!(
                inp.contains_key(k),
                "fixture {:?} input missing {}",
                name,
                k
            );
        }
        assert!(
            fx.get("expected_subject").is_some(),
            "fixture {:?} missing expected_subject",
            name
        );
        let exp = fx.get("expected").and_then(|x| x.as_object()).unwrap();
        for k in [
            "frame_jcs_bytes_b64",
            "frame_jcs_bytes_len",
            "frame_sha256_hex",
            "frame_hash_prefixed",
        ] {
            assert!(exp.contains_key(k), "fixture {:?} missing expected.{}", name, k);
        }
    }

    // Const surface pin (mirrors Python T01).
    assert_eq!(BRIDGE_FORWARD_FRAME_SCHEMA, "wakir.bridge.forward-frame/1");
    assert_eq!(AGENT_TASK_ASSIGNED_SCHEMA, "wakir.agent.task-assigned/1");
    assert_eq!(EVENT_KIND_AGENT_TASK_ASSIGNED, "agent.task.assigned");
    assert_eq!(HASH_PREFIX, "sha256:");
    assert_eq!(SHA256_HEX_LEN, 64);
    assert_eq!(MAX_PROMPT_PAYLOAD_BYTES, 256 * 1024);
    assert_eq!(MAX_AUFTRAG_ID_OCTETS, 64);
    assert_eq!(MAX_METADATA_BYTES, 8 * 1024);
    assert_eq!(DEFAULT_ORG_ID, "acme");
    assert_eq!(DEFAULT_SOURCE, "mira-sandbox");
}

// ---------------------------------------------------------------------
// F02 -- Empty-payload (f01) explicit byte-pin.
// ---------------------------------------------------------------------

#[test]
fn f02_empty_payload_explicit_byte_pin() {
    // Independent re-derivation of the f01 vector via the explicit
    // ForwardFrameInput::new path (no metadata, default org_id +
    // source). The result MUST byte-match the fixture pin.
    let input = ForwardFrameInput::new(
        "dev",
        "tomas",
        "empty-1",
        "2026-05-17T00:00:00Z",
        "",
    );
    let frame = build_forward_frame(&input).expect("frame builds");
    let (bytes, prefixed) = serialize_and_hash(&frame).expect("serialise+hash");
    let hex_only = forward_frame_sha256_hex(&frame).expect("hex");
    assert_eq!(frame.subject, "wakir.dev.agent.agent.task.assigned.tomas");
    assert_eq!(bytes.len(), 422, "f01 canonical bytes length pinned");
    assert_eq!(
        hex_only,
        "f21370daf9ff92f52a2d56e29869fa922220907e03fd44467b6c3bedf43fc24c",
        "f01 bare-hex hash pinned"
    );
    assert_eq!(
        prefixed,
        "sha256:f21370daf9ff92f52a2d56e29869fa922220907e03fd44467b6c3bedf43fc24c",
        "f01 prefixed hash pinned"
    );
}

// ---------------------------------------------------------------------
// Per-fixture byte-level pin runner
// ---------------------------------------------------------------------

fn run_single_fixture(target_name: &str) {
    let v = load_fixtures();
    let fx = find_fixture(&v, target_name);
    let input = input_from_fixture(fx);
    let frame = build_forward_frame(&input).expect("frame builds");
    let bytes = serialize_forward_frame(&frame).expect("serialise");
    let hex_only = forward_frame_sha256_hex(&frame).expect("hex");
    let prefixed = forward_frame_hash_prefixed(&frame).expect("prefixed");

    let exp_subject = fx
        .get("expected_subject")
        .and_then(|s| s.as_str())
        .unwrap();
    assert_eq!(
        frame.subject, exp_subject,
        "{}: subject drifted vs pin",
        target_name
    );

    let exp = fx.get("expected").and_then(|x| x.as_object()).unwrap();
    let exp_bytes_b64 = exp
        .get("frame_jcs_bytes_b64")
        .and_then(|s| s.as_str())
        .unwrap();
    let exp_bytes = b64_decode(exp_bytes_b64);
    let exp_len = exp
        .get("frame_jcs_bytes_len")
        .and_then(|n| n.as_u64())
        .unwrap() as usize;
    let exp_sha = exp
        .get("frame_sha256_hex")
        .and_then(|s| s.as_str())
        .unwrap();
    let exp_prefixed = exp
        .get("frame_hash_prefixed")
        .and_then(|s| s.as_str())
        .unwrap();

    assert_eq!(
        bytes.len(),
        exp_len,
        "{}: canonical-bytes length drifted vs pin",
        target_name
    );
    assert_eq!(
        bytes, exp_bytes,
        "{}: canonical-bytes drifted vs pin (b64-decoded)",
        target_name
    );
    assert_eq!(
        hex_only, exp_sha,
        "{}: bare-hex SHA-256 drifted vs pin",
        target_name
    );
    assert_eq!(
        prefixed, exp_prefixed,
        "{}: prefixed SHA-256 drifted vs pin",
        target_name
    );

    // Sanity: prefixed-hash exposes HASH_PREFIX + bare-hex.
    assert!(prefixed.starts_with(HASH_PREFIX));
    assert_eq!(prefixed.len(), HASH_PREFIX.len() + SHA256_HEX_LEN);

    // serialize_and_hash returns the same pair as the individual
    // helpers (no double-canonicalisation drift).
    let (bytes2, prefixed2) = serialize_and_hash(&frame).expect("serialize_and_hash");
    assert_eq!(bytes2, bytes, "{}: serialize_and_hash bytes drift", target_name);
    assert_eq!(
        prefixed2, prefixed,
        "{}: serialize_and_hash prefixed drift",
        target_name
    );
}

// ---------------------------------------------------------------------
// F03..F07 -- One test per fixture for fine-grained failure isolation.
// ---------------------------------------------------------------------

#[test]
fn f03_fixture_f01_empty_payload_byte_pin() {
    run_single_fixture("f01-empty-payload");
}

#[test]
fn f04_fixture_f02_single_record_byte_pin() {
    run_single_fixture("f02-single-record");
}

#[test]
fn f05_fixture_f03_multi_record_batch_byte_pin() {
    run_single_fixture("f03-multi-record-batch");
}

#[test]
fn f06_fixture_f04_error_frame_byte_pin() {
    run_single_fixture("f04-error-frame");
}

#[test]
fn f07_fixture_f05_large_payload_byte_pin() {
    run_single_fixture("f05-large-payload");
}

// ---------------------------------------------------------------------
// F08 -- Inline base64 decoder sanity (cross-checked against the
//        expected base64 / byte-len tuple from f01).
// ---------------------------------------------------------------------

#[test]
fn f08_inline_base64_decoder_sanity() {
    assert_eq!(b64_decode(""), Vec::<u8>::new());
    assert_eq!(b64_decode("YQ=="), b"a".to_vec());
    assert_eq!(b64_decode("YWI="), b"ab".to_vec());
    assert_eq!(b64_decode("YWJj"), b"abc".to_vec());
    assert_eq!(b64_decode("YWJjZA=="), b"abcd".to_vec());
    // Cross-check: a JCS-canonical empty object decodes to "{}".
    assert_eq!(b64_decode("e30="), b"{}".to_vec());
}

// ---------------------------------------------------------------------
// F09 -- Subject regex parity: every fixture's expected_subject must
//        match the layer-0-transport regex shape.
// ---------------------------------------------------------------------

#[test]
fn f09_subject_regex_parity_across_fixtures() {
    let v = load_fixtures();
    let fixtures = v.get("fixtures").and_then(|f| f.as_array()).unwrap();
    for fx in fixtures {
        let name = fx.get("name").and_then(|s| s.as_str()).unwrap();
        let exp_subject = fx
            .get("expected_subject")
            .and_then(|s| s.as_str())
            .unwrap();
        // Shape: `wakir.<env>.agent.agent.task.assigned.<persona_slug>`
        // - env is one of dev/staging/prod.
        // - persona_slug matches [a-z][a-z0-9_-]*.
        assert!(
            exp_subject.starts_with("wakir."),
            "{}: subject must start with 'wakir.'",
            name
        );
        let parts: Vec<&str> = exp_subject.split('.').collect();
        assert!(
            parts.len() == 7,
            "{}: subject must split into 7 dot-segments, got {} (subject={:?})",
            name,
            parts.len(),
            exp_subject
        );
        assert_eq!(parts[0], "wakir");
        let env = parts[1];
        assert!(
            env == "dev" || env == "staging" || env == "prod",
            "{}: subject env segment must be dev/staging/prod, got {:?}",
            name,
            env
        );
        assert_eq!(parts[2], "agent");
        assert_eq!(parts[3], "agent");
        assert_eq!(parts[4], "task");
        assert_eq!(parts[5], "assigned");
        let slug = parts[6];
        let first = slug.chars().next().unwrap();
        assert!(
            first.is_ascii_lowercase(),
            "{}: slug must start with lower-case letter, got {:?}",
            name,
            slug
        );

        // Independently rebuild the subject via build_subject; pin parity
        // with the fixture-pinned value.
        let inp = fx.get("input").and_then(|x| x.as_object()).unwrap();
        let env_inp = inp.get("env").and_then(|x| x.as_str()).unwrap();
        let slug_inp = inp.get("persona_slug").and_then(|x| x.as_str()).unwrap();
        assert_eq!(
            build_subject(env_inp, slug_inp).unwrap(),
            exp_subject,
            "{}: build_subject drift vs fixture-pinned subject",
            name
        );
    }
}

// ---------------------------------------------------------------------
// F10 -- Determinism: building the same fixture twice produces
//        byte-identical canonical output.
// ---------------------------------------------------------------------

#[test]
fn f10_determinism_across_repeats() {
    let v = load_fixtures();
    for name in EXPECTED_FIXTURE_NAMES {
        let fx = find_fixture(&v, name);
        let input = input_from_fixture(fx);
        let f1 = build_forward_frame(&input).expect("build f1");
        let f2 = build_forward_frame(&input).expect("build f2");
        let b1 = serialize_forward_frame(&f1).expect("ser f1");
        let b2 = serialize_forward_frame(&f2).expect("ser f2");
        assert_eq!(b1, b2, "{}: determinism breach", name);
        let h1 = forward_frame_hash_prefixed(&f1).expect("hash f1");
        let h2 = forward_frame_hash_prefixed(&f2).expect("hash f2");
        assert_eq!(h1, h2, "{}: hash determinism breach", name);
    }
}

// ---------------------------------------------------------------------
// F11 -- Size-limit validation: error-frame auftrag_id boundary +
//        rejection one-byte over the cap.
// ---------------------------------------------------------------------

#[test]
fn f11_size_limit_validation_boundary_and_over() {
    // f04 carries a 64-octet auftrag_id (the exact boundary).
    let v = load_fixtures();
    let fx = find_fixture(&v, "f04-error-frame");
    let input = input_from_fixture(fx);
    assert_eq!(
        input.auftrag_id.len(),
        MAX_AUFTRAG_ID_OCTETS,
        "f04 auftrag_id must be exactly at the 64-octet boundary"
    );
    let frame = build_forward_frame(&input).expect("frame builds");
    validate_forward_frame(&frame).expect("boundary frame validates");

    // One byte over the cap must reject.
    let mut over_input = input.clone();
    over_input.auftrag_id.push('z');
    let over_frame = build_forward_frame(&over_input).expect("frame still builds");
    let err = validate_forward_frame(&over_frame).expect_err("over-cap must reject");
    match err {
        BridgeForwardError::SizeLimit {
            field,
            actual,
            limit,
        } => {
            assert_eq!(field, "auftrag_id", "wrong field surfaced");
            assert_eq!(actual, MAX_AUFTRAG_ID_OCTETS + 1);
            assert_eq!(limit, MAX_AUFTRAG_ID_OCTETS);
        }
        other => panic!("expected SizeLimit, got {other:?}"),
    }

    // Bad-env / bad-slug rejection via build_subject.
    assert!(matches!(
        build_subject("production", "tomas"),
        Err(BridgeForwardError::InvalidEnv(_))
    ));
    assert!(matches!(
        build_subject("dev", "Tomas"),
        Err(BridgeForwardError::InvalidPersonaSlug(_))
    ));
    assert!(matches!(
        build_subject("dev", "1tomas"),
        Err(BridgeForwardError::InvalidPersonaSlug(_))
    ));
    assert!(matches!(
        build_subject("dev", "to.mas"),
        Err(BridgeForwardError::InvalidPersonaSlug(_))
    ));
}

// ---------------------------------------------------------------------
// F12 -- envelope.to_wire_value() emits the ten canonical keys, all
//        alphabetised after JCS canonicalisation.
// ---------------------------------------------------------------------

#[test]
fn f12_envelope_wire_shape_has_ten_canonical_keys() {
    let env = AuftragEnvelope {
        org_id: "acme".into(),
        persona_id: "tomas".into(),
        auftrag_id: "x".into(),
        ts_utc: "2026-05-17T00:00:00Z".into(),
        source: "mira-sandbox".into(),
        prompt_payload: "hi".into(),
        metadata: BTreeMap::new(),
    };
    let v = env.to_wire_value();
    let obj = v.as_object().expect("wire value is object");
    let mut keys: Vec<&String> = obj.keys().collect();
    keys.sort();
    let keys_sorted: Vec<&str> = keys.iter().map(|s| s.as_str()).collect();
    assert_eq!(
        keys_sorted,
        vec![
            "auftrag_id",
            "event_kind",
            "metadata",
            "org_id",
            "persona_id",
            "prompt_payload",
            "prompt_sha256",
            "schema",
            "source",
            "ts_utc",
        ]
    );
    assert_eq!(obj["schema"], AGENT_TASK_ASSIGNED_SCHEMA);
    assert_eq!(obj["event_kind"], EVENT_KIND_AGENT_TASK_ASSIGNED);
}

// ---------------------------------------------------------------------
// F13 -- ForwardFrame wire-value has exactly three alphabetical keys:
//        envelope, schema, subject.
// ---------------------------------------------------------------------

#[test]
fn f13_frame_wire_shape_has_three_alphabetical_keys() {
    let inp = ForwardFrameInput::new("dev", "reza", "x", "2026-05-17T00:00:00Z", "hi");
    let f = build_forward_frame(&inp).expect("frame");
    let v = f.to_wire_value();
    let obj = v.as_object().unwrap();
    let mut keys: Vec<&String> = obj.keys().collect();
    keys.sort();
    let keys_sorted: Vec<&str> = keys.iter().map(|s| s.as_str()).collect();
    assert_eq!(keys_sorted, vec!["envelope", "schema", "subject"]);
    assert_eq!(obj["schema"], BRIDGE_FORWARD_FRAME_SCHEMA);
    assert_eq!(obj["subject"], "wakir.dev.agent.agent.task.assigned.reza");
}

// ---------------------------------------------------------------------
// F14 -- Frame builder + serialiser are pure: re-building from the
//        same input twice yields ForwardFrame instances that produce
//        byte-equal canonical bytes (struct may differ on Drop order,
//        but bytes must match).
// ---------------------------------------------------------------------

#[test]
fn f14_purity_smoke() {
    let inp = ForwardFrameInput::new(
        "staging",
        "kai",
        "purity",
        "2026-05-17T00:00:00Z",
        "test",
    )
    .with_org_id("wakir-labs")
    .with_source("mira-test");
    let f1 = build_forward_frame(&inp).expect("f1");
    let f2 = build_forward_frame(&inp).expect("f2");
    assert_eq!(f1, f2);
    assert_eq!(
        serialize_forward_frame(&f1).unwrap(),
        serialize_forward_frame(&f2).unwrap()
    );
}
