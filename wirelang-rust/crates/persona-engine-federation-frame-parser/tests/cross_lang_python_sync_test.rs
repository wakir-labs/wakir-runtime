// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Cross-language byte-pin test — Rust <-> Python parity for
// `persona-engine-federation-frame-parser` / `wirelang.federation.
// federation_frame`.
//
// This test reads the fixture file
// `tests/federation/fixtures/federation_frame_cross_lang_pins.json`
// (committed at the repository root, two levels above the Cargo
// workspace root), reconstructs each fixture's input as a typed
// `FederationFrame`, runs `serialize_frame`, and asserts byte
// equality against the pinned bytes. The Python suite at
// `wirelang/tests/test_federation_frame_parser.py` runs the
// equivalent assertion. Byte-drift in either direction breaks both
// lanes simultaneously — that is the cross-lang contract.
//
// Tag-14 Mini-Welle Phase-3a-Folge: closes the
// `TODO_PYTHON_FRAME_PARITY_PIN` placeholder shipped with PR #148
// (Rust crate ship-day). The placeholder is now deprecated and the
// real pin lives in this file plus the fixture JSON.

use persona_engine_federation_frame_parser::{
    parse_frame, serialize_frame, FederationFrame, FederationPayload, FrameHeader,
    CROSS_LANG_PYTHON_FRAME_PARITY_PIN,
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
/// Crate manifest:  `<repo>/wirelang-rust/crates/persona-engine-federation-frame-parser`
/// Fixture file:    `<repo>/tests/federation/fixtures/federation_frame_cross_lang_pins.json`
/// Hops up:         `../../..` (parser-crate -> crates -> wirelang-rust -> repo root).
fn fixture_path() -> PathBuf {
    let manifest_dir =
        env!("CARGO_MANIFEST_DIR", "CARGO_MANIFEST_DIR must be set by cargo");
    let mut p = PathBuf::from(manifest_dir);
    for _ in 0..3 {
        p.pop();
    }
    p.push("tests");
    p.push("federation");
    p.push("fixtures");
    p.push("federation_frame_cross_lang_pins.json");
    p
}

#[derive(Debug)]
struct Fixture {
    label: String,
    input: FixtureInput,
    expected_canonical_utf8: String,
    expected_canonical_sha256: String,
    expected_canonical_byte_length: usize,
}

#[derive(Debug)]
struct FixtureInput {
    header: FrameHeader,
    payload_kind: String,
    payload_data: BTreeMap<String, Value>,
    anchor_ref: Option<String>,
    signature: Option<String>,
}

fn load_fixtures() -> Vec<Fixture> {
    let path = fixture_path();
    let raw = fs::read_to_string(&path).unwrap_or_else(|e| {
        panic!(
            "cross-lang fixture file missing or unreadable at {}: {}. \
             This file is the byte-level contract anchor between the \
             Rust crate and the Python sibling \
             `wirelang.federation.federation_frame`. The Python suite \
             at `wirelang/tests/test_federation_frame_parser.py` \
             generates / verifies it. If it is missing, see the \
             docstring of `wirelang/federation/federation_frame.py` \
             for the regeneration procedure.",
            path.display(),
            e
        )
    });
    let parsed: Value = serde_json::from_str(&raw).expect("fixture JSON parse");
    let version = parsed
        .get("fixture_set_version")
        .and_then(|v| v.as_u64())
        .expect("fixture_set_version field present");
    assert_eq!(
        version, 1,
        "fixture-set version drift; Rust cross-lang test expects \
         fixture_set_version == 1"
    );

    let fixtures = parsed
        .get("fixtures")
        .and_then(|v| v.as_array())
        .expect("fixtures array present");

    let mut out = Vec::new();
    for fixture in fixtures {
        let label = fixture
            .get("label")
            .and_then(|v| v.as_str())
            .expect("label string")
            .to_string();
        let input_obj = fixture.get("input").expect("input object");

        let header_obj = input_obj.get("header").expect("header object");
        let header = FrameHeader {
            frame_id: header_obj["frame_id"].as_str().unwrap().to_string(),
            schema: header_obj["schema"].as_str().unwrap().to_string(),
            source_runtime: header_obj["source_runtime"].as_str().unwrap().to_string(),
            target_runtime: header_obj["target_runtime"].as_str().unwrap().to_string(),
            ts_utc: header_obj["ts_utc"].as_str().unwrap().to_string(),
            version: header_obj["version"].as_u64().unwrap() as u32,
        };
        let payload_kind = input_obj["payload_kind"].as_str().unwrap().to_string();
        let payload_data_val = input_obj["payload_data"].clone();
        let payload_data: BTreeMap<String, Value> = match payload_data_val {
            Value::Object(map) => map.into_iter().collect(),
            _ => panic!("payload_data must be an object"),
        };
        let anchor_ref = input_obj
            .get("anchor_ref")
            .and_then(|v| if v.is_null() { None } else { v.as_str().map(String::from) });
        let signature = input_obj
            .get("signature")
            .and_then(|v| if v.is_null() { None } else { v.as_str().map(String::from) });

        let expected_canonical_utf8 = fixture
            .get("expected_canonical_utf8")
            .and_then(|v| v.as_str())
            .expect("expected_canonical_utf8 string")
            .to_string();
        let expected_canonical_sha256 = fixture
            .get("expected_canonical_sha256")
            .and_then(|v| v.as_str())
            .expect("expected_canonical_sha256 string")
            .to_string();
        let expected_canonical_byte_length = fixture
            .get("expected_canonical_byte_length")
            .and_then(|v| v.as_u64())
            .expect("expected_canonical_byte_length integer")
            as usize;

        out.push(Fixture {
            label,
            input: FixtureInput {
                header,
                payload_kind,
                payload_data,
                anchor_ref,
                signature,
            },
            expected_canonical_utf8,
            expected_canonical_sha256,
            expected_canonical_byte_length,
        });
    }
    out
}

fn build_frame(input: &FixtureInput) -> FederationFrame {
    let payload = match input.payload_kind.as_str() {
        "task-assigned" => FederationPayload::TaskAssigned {
            data: input.payload_data.clone(),
        },
        "task-output" => FederationPayload::TaskOutput {
            data: input.payload_data.clone(),
        },
        "multi-org-attestation" => FederationPayload::MultiOrgAttestation {
            data: input.payload_data.clone(),
        },
        "spiffe-bundle-sync" => FederationPayload::SpiffeBundleSync {
            data: input.payload_data.clone(),
        },
        other => panic!("unknown payload kind in fixture: {}", other),
    };
    FederationFrame {
        anchor_ref: input.anchor_ref.clone(),
        header: input.header.clone(),
        payload,
        signature: input.signature.clone(),
    }
}

// ---------------------------------------------------------------------
// The actual cross-lang byte-pin test.
// ---------------------------------------------------------------------

#[test]
fn cross_lang_python_sync_pin_constant_points_at_fixture() {
    // Sanity-check the public pin constant points at the file this
    // test reads. Drift between the two would silently allow the
    // cross-lang contract to detach from the constant.
    assert!(CROSS_LANG_PYTHON_FRAME_PARITY_PIN
        .ends_with("federation_frame_cross_lang_pins.json"));
}

#[test]
fn cross_lang_python_sync_rust_emits_byte_identical_pins() {
    let fixtures = load_fixtures();
    assert!(
        fixtures.len() >= 3,
        "Auftrag requires 3-5 fixtures; only {} found",
        fixtures.len()
    );
    assert!(
        fixtures.len() <= 5,
        "Auftrag caps at 5 fixtures; {} found — re-baseline before \
         adding more (each new fixture grows the cross-lang surface).",
        fixtures.len()
    );

    let mut sha = sha2::Sha256::default();
    use sha2::Digest;

    for fixture in &fixtures {
        let frame = build_frame(&fixture.input);
        let by = serialize_frame(&frame)
            .unwrap_or_else(|e| panic!("serialize_frame failed for {}: {}", fixture.label, e));

        // Byte-identical UTF-8.
        let text = std::str::from_utf8(&by).expect("utf-8");
        assert_eq!(
            text, fixture.expected_canonical_utf8,
            "Rust serialize_frame byte-drift for {}; check that the \
             Python sibling has not been regenerated without updating \
             this Rust crate.",
            fixture.label
        );

        // Byte-length pin (defensive cross-check).
        assert_eq!(
            by.len(),
            fixture.expected_canonical_byte_length,
            "byte-length mismatch for {}",
            fixture.label
        );

        // SHA-256 pin (defensive cross-check; the UTF-8 assertion
        // already implies this but we surface a clean diff if a
        // fixture file is hand-edited away from its sha256).
        sha.reset();
        sha.update(&by);
        let pin_sha = hex::encode(sha.finalize_reset());
        assert_eq!(
            pin_sha, fixture.expected_canonical_sha256,
            "sha256 pin drift for {}",
            fixture.label
        );

        // Round-trip is identity.
        let reparsed = parse_frame(&by)
            .unwrap_or_else(|e| panic!("parse_frame failed for {}: {}", fixture.label, e));
        let by2 = serialize_frame(&reparsed)
            .unwrap_or_else(|e| panic!("re-serialize failed for {}: {}", fixture.label, e));
        assert_eq!(by, by2, "idempotency drift for {}", fixture.label);
    }
}

#[test]
fn cross_lang_python_sync_fixture_file_has_expected_keys() {
    // Defensive shape check: the fixture file structure is part of
    // the cross-lang contract. If a future Python-side regenerator
    // changes the top-level shape, this test should fail loudly
    // before any byte-pin test gives a confusing diff.
    let raw = fs::read_to_string(fixture_path()).expect("fixture file");
    let parsed: Value = serde_json::from_str(&raw).expect("fixture JSON parse");
    let obj = parsed.as_object().expect("top-level object");
    for required in [
        "fixture_set_version",
        "generated_by",
        "generated_on",
        "cross_lang_contract",
        "fixtures",
    ] {
        assert!(
            obj.contains_key(required),
            "fixture file missing required top-level key {:?}",
            required
        );
    }
    for fixture in obj["fixtures"].as_array().expect("fixtures array") {
        let f = fixture.as_object().expect("fixture object");
        for required in [
            "label",
            "input",
            "expected_canonical_utf8",
            "expected_canonical_sha256",
            "expected_canonical_byte_length",
        ] {
            assert!(
                f.contains_key(required),
                "fixture {:?} missing key {:?}",
                f.get("label"),
                required
            );
        }
        let input = f["input"].as_object().expect("input object");
        for required in [
            "header",
            "payload_kind",
            "payload_data",
            "anchor_ref",
            "signature",
        ] {
            assert!(
                input.contains_key(required),
                "fixture input missing key {:?}",
                required
            );
        }
    }
}
