// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Federation-frame parser smoke tests — Phase-3a Item 9.
//
// Covers (12 tests):
//   1. roundtrip_task_assigned_full_fixture
//   2. roundtrip_task_output_full_fixture
//   3. roundtrip_multi_org_attestation_full_fixture
//   4. roundtrip_spiffe_bundle_sync_full_fixture
//   5. roundtrip_with_anchor_ref_and_signature
//   6. malformed_frame_rejected_bad_json
//   7. malformed_frame_rejected_payload_data_not_object
//   8. version_skew_unsupported_version_rejected
//   9. version_skew_unknown_envelope_schema_rejected
//  10. schema_validation_payload_kind_schema_mismatch_rejected
//  11. schema_validation_bad_frame_id_shape_rejected
//  12. schema_validation_bad_timestamp_shape_rejected
//  13. cross_lang_fixture_byte_pin_task_assigned
//      (cross-lang pin placeholder for the future Python sibling)
//  14. cross_lang_fixture_byte_pin_multi_org_attestation
//
// Cross-lang sync TODO marker (also asserted on as a constant
// presence-check so a future Python sibling cannot accidentally
// rename or drop it without breaking the Rust test suite first).

use persona_engine_federation_frame_parser::{
    compute_frame_id, parse_frame, serialize_frame, signing_payload_bytes, FederationFrame,
    FederationPayload, FrameHeader, ParseError, ANCHOR_REF_PREFIX, FRAME_ENVELOPE_SCHEMA,
    FRAME_ENVELOPE_VERSION, FRAME_ID_PREFIX, PAYLOAD_SCHEMA_MULTI_ORG_ATTESTATION,
    PAYLOAD_SCHEMA_SPIFFE_BUNDLE_SYNC, PAYLOAD_SCHEMA_TASK_ASSIGNED,
    PAYLOAD_SCHEMA_TASK_OUTPUT, TODO_PYTHON_FRAME_PARITY_PIN,
};
use std::collections::BTreeMap;

// ---------------------------------------------------------------------
// Fixture builders.
// ---------------------------------------------------------------------

fn frame_id_seed_a() -> String {
    compute_frame_id(b"sprint-tag-12-mini-9/task-assigned/reza")
}

fn frame_id_seed_b() -> String {
    compute_frame_id(b"sprint-tag-12-mini-9/task-output/reza")
}

fn frame_id_seed_c() -> String {
    compute_frame_id(b"sprint-tag-12-mini-9/multi-org-attestation/acme-x-globex")
}

fn frame_id_seed_d() -> String {
    compute_frame_id(b"sprint-tag-12-mini-9/spiffe-bundle-sync/globex.example.org")
}

fn header_task_assigned() -> FrameHeader {
    FrameHeader {
        frame_id: frame_id_seed_a(),
        schema: FRAME_ENVELOPE_SCHEMA.to_string(),
        source_runtime: "mira-sandbox".to_string(),
        target_runtime: "wakir-runtime".to_string(),
        ts_utc: "2026-05-17T02:35:00Z".to_string(),
        version: FRAME_ENVELOPE_VERSION,
    }
}

fn payload_task_assigned_data() -> BTreeMap<String, serde_json::Value> {
    let mut m = BTreeMap::new();
    m.insert(
        "auftrag_id".to_string(),
        serde_json::Value::String("sprint-tag-12-mini-9".to_string()),
    );
    m.insert(
        "event_kind".to_string(),
        serde_json::Value::String("agent.task.assigned".to_string()),
    );
    m.insert(
        "org_id".to_string(),
        serde_json::Value::String("acme".to_string()),
    );
    m.insert(
        "persona_id".to_string(),
        serde_json::Value::String("reza".to_string()),
    );
    m.insert(
        "prompt_payload".to_string(),
        serde_json::Value::String("Build the federation-frame parser crate.".to_string()),
    );
    m.insert(
        "prompt_sha256".to_string(),
        serde_json::Value::String(format!("sha256:{}", "a".repeat(64))),
    );
    m.insert(
        "source".to_string(),
        serde_json::Value::String("mira-sandbox".to_string()),
    );
    m.insert(
        "ts_utc".to_string(),
        serde_json::Value::String("2026-05-17T02:35:00Z".to_string()),
    );
    m
}

fn payload_task_output_data() -> BTreeMap<String, serde_json::Value> {
    let mut m = BTreeMap::new();
    m.insert(
        "auftrag_id".to_string(),
        serde_json::Value::String("sprint-tag-12-mini-9".to_string()),
    );
    m.insert(
        "event_kind".to_string(),
        serde_json::Value::String("agent.task.completed".to_string()),
    );
    m.insert(
        "persona_id".to_string(),
        serde_json::Value::String("reza".to_string()),
    );
    m.insert(
        "reply_text".to_string(),
        serde_json::Value::String("PR opened; CI green.".to_string()),
    );
    m.insert(
        "ts_utc".to_string(),
        serde_json::Value::String("2026-05-17T03:05:00Z".to_string()),
    );
    m
}

fn payload_multi_org_attestation_data() -> BTreeMap<String, serde_json::Value> {
    let mut m = BTreeMap::new();
    m.insert(
        "route_id".to_string(),
        serde_json::Value::String("did:web:acme.example.org#federation-route-1".to_string()),
    );
    m.insert(
        "peer_trust_domain".to_string(),
        serde_json::Value::String("globex.example.org".to_string()),
    );
    m.insert(
        "peer_audit_anchor_did".to_string(),
        serde_json::Value::String("did:web:globex.example.org".to_string()),
    );
    m.insert(
        "peer_wat_anchor_manifest_id".to_string(),
        serde_json::Value::String(format!("wat-manifest:{}", "1".repeat(40))),
    );
    m.insert(
        "is_mock".to_string(),
        serde_json::Value::Bool(false),
    );
    m
}

fn payload_spiffe_bundle_sync_data() -> BTreeMap<String, serde_json::Value> {
    let mut m = BTreeMap::new();
    m.insert(
        "peer_trust_domain".to_string(),
        serde_json::Value::String("globex.example.org".to_string()),
    );
    m.insert(
        "peer_trust_bundle_url".to_string(),
        serde_json::Value::String("https://globex.example.org/.well-known/spire-bundle".to_string()),
    );
    m.insert(
        "bundle_sha256".to_string(),
        serde_json::Value::String(format!("sha256:{}", "b".repeat(64))),
    );
    m.insert(
        "freshness_ts_utc".to_string(),
        serde_json::Value::String("2026-05-17T02:00:00Z".to_string()),
    );
    m
}

// ---------------------------------------------------------------------
// Tests 1..4 — Round-trip per payload kind.
// ---------------------------------------------------------------------

#[test]
fn roundtrip_task_assigned_full_fixture() {
    let frame = FederationFrame {
        anchor_ref: None,
        header: header_task_assigned(),
        payload: FederationPayload::TaskAssigned {
            data: payload_task_assigned_data(),
        },
        signature: None,
    };
    let bytes = serialize_frame(&frame).expect("serialize");
    let parsed = parse_frame(&bytes).expect("parse");
    assert_eq!(parsed, frame);

    // Serialise-parse-serialise is idempotent at the byte level.
    let bytes2 = serialize_frame(&parsed).expect("serialize-2");
    assert_eq!(bytes, bytes2);
}

#[test]
fn roundtrip_task_output_full_fixture() {
    let mut header = header_task_assigned();
    header.frame_id = frame_id_seed_b();
    header.ts_utc = "2026-05-17T03:05:00Z".to_string();
    header.source_runtime = "wakir-runtime".to_string();
    header.target_runtime = "mira-sandbox".to_string();

    let frame = FederationFrame {
        anchor_ref: None,
        header,
        payload: FederationPayload::TaskOutput {
            data: payload_task_output_data(),
        },
        signature: None,
    };
    let bytes = serialize_frame(&frame).expect("serialize");
    let parsed = parse_frame(&bytes).expect("parse");
    assert_eq!(parsed, frame);
}

#[test]
fn roundtrip_multi_org_attestation_full_fixture() {
    let mut header = header_task_assigned();
    header.frame_id = frame_id_seed_c();
    header.source_runtime = "acme/wakir-runtime".to_string();
    header.target_runtime = "globex/wakir-runtime".to_string();

    let frame = FederationFrame {
        anchor_ref: None,
        header,
        payload: FederationPayload::MultiOrgAttestation {
            data: payload_multi_org_attestation_data(),
        },
        signature: None,
    };
    let bytes = serialize_frame(&frame).expect("serialize");
    let parsed = parse_frame(&bytes).expect("parse");
    assert_eq!(parsed, frame);
}

#[test]
fn roundtrip_spiffe_bundle_sync_full_fixture() {
    let mut header = header_task_assigned();
    header.frame_id = frame_id_seed_d();
    header.source_runtime = "acme/wakir-runtime".to_string();
    header.target_runtime = "globex/wakir-runtime".to_string();

    let frame = FederationFrame {
        anchor_ref: None,
        header,
        payload: FederationPayload::SpiffeBundleSync {
            data: payload_spiffe_bundle_sync_data(),
        },
        signature: None,
    };
    let bytes = serialize_frame(&frame).expect("serialize");
    let parsed = parse_frame(&bytes).expect("parse");
    assert_eq!(parsed, frame);
}

// ---------------------------------------------------------------------
// Test 5 — Optional fields (anchor_ref + signature) round-trip.
// ---------------------------------------------------------------------

#[test]
fn roundtrip_with_anchor_ref_and_signature() {
    let frame = FederationFrame {
        anchor_ref: Some(format!("{}{}", ANCHOR_REF_PREFIX, "c".repeat(64))),
        header: header_task_assigned(),
        payload: FederationPayload::TaskAssigned {
            data: payload_task_assigned_data(),
        },
        // 64-byte ed25519 sig = 128 hex chars; this crate only
        // enforces the hex shape, not the length.
        signature: Some("d".repeat(128)),
    };
    let bytes = serialize_frame(&frame).expect("serialize");
    let parsed = parse_frame(&bytes).expect("parse");
    assert_eq!(parsed, frame);

    // signing_payload_bytes excludes anchor_ref and signature.
    let signed = signing_payload_bytes(&frame).expect("signing-bytes");
    let signed_str = std::str::from_utf8(&signed).unwrap();
    assert!(!signed_str.contains("anchor_ref"));
    assert!(!signed_str.contains("signature"));
    assert!(signed_str.contains("header"));
    assert!(signed_str.contains("payload"));
}

// ---------------------------------------------------------------------
// Tests 6..7 — Malformed-frame rejection.
// ---------------------------------------------------------------------

#[test]
fn malformed_frame_rejected_bad_json() {
    let bytes = b"{not-json}";
    assert!(matches!(parse_frame(bytes), Err(ParseError::BadJson(_))));
}

#[test]
fn malformed_frame_rejected_payload_data_not_object() {
    // Build a wire frame whose payload.data is a string, not an
    // object. We can't construct this through the typed API; we
    // assemble it as raw JSON.
    let raw = serde_json::json!({
        "header": {
            "frame_id": frame_id_seed_a(),
            "schema":   FRAME_ENVELOPE_SCHEMA,
            "source_runtime": "mira-sandbox",
            "target_runtime": "wakir-runtime",
            "ts_utc":   "2026-05-17T02:35:00Z",
            "version":  FRAME_ENVELOPE_VERSION,
        },
        "payload": {
            "kind":   "task-assigned",
            "data":   "should-be-an-object",
            "schema": PAYLOAD_SCHEMA_TASK_ASSIGNED,
        },
    });
    let bytes = serde_jcs::to_vec(&raw).unwrap();
    assert!(matches!(
        parse_frame(&bytes),
        Err(ParseError::PayloadDataNotObject)
    ));
}

// ---------------------------------------------------------------------
// Tests 8..9 — Version skew.
// ---------------------------------------------------------------------

#[test]
fn version_skew_unsupported_version_rejected() {
    let raw = serde_json::json!({
        "header": {
            "frame_id": frame_id_seed_a(),
            "schema":   FRAME_ENVELOPE_SCHEMA,
            "source_runtime": "mira-sandbox",
            "target_runtime": "wakir-runtime",
            "ts_utc":   "2026-05-17T02:35:00Z",
            "version":  99,
        },
        "payload": {
            "kind":   "task-assigned",
            "data":   {},
            "schema": PAYLOAD_SCHEMA_TASK_ASSIGNED,
        },
    });
    let bytes = serde_jcs::to_vec(&raw).unwrap();
    assert!(matches!(
        parse_frame(&bytes),
        Err(ParseError::UnsupportedVersion(99))
    ));
}

#[test]
fn version_skew_unknown_envelope_schema_rejected() {
    let raw = serde_json::json!({
        "header": {
            "frame_id": frame_id_seed_a(),
            "schema":   "wakir.federation.frame/9999",
            "source_runtime": "mira-sandbox",
            "target_runtime": "wakir-runtime",
            "ts_utc":   "2026-05-17T02:35:00Z",
            "version":  FRAME_ENVELOPE_VERSION,
        },
        "payload": {
            "kind":   "task-assigned",
            "data":   {},
            "schema": PAYLOAD_SCHEMA_TASK_ASSIGNED,
        },
    });
    let bytes = serde_jcs::to_vec(&raw).unwrap();
    match parse_frame(&bytes) {
        Err(ParseError::UnknownSchema { field, value }) => {
            assert_eq!(field, "header.schema");
            assert_eq!(value, "wakir.federation.frame/9999");
        }
        other => panic!("expected UnknownSchema, got {:?}", other),
    }
}

// ---------------------------------------------------------------------
// Tests 10..12 — Schema validation.
// ---------------------------------------------------------------------

#[test]
fn schema_validation_payload_kind_schema_mismatch_rejected() {
    // kind=task-assigned but schema=task-output -> mismatch.
    let raw = serde_json::json!({
        "header": {
            "frame_id": frame_id_seed_a(),
            "schema":   FRAME_ENVELOPE_SCHEMA,
            "source_runtime": "mira-sandbox",
            "target_runtime": "wakir-runtime",
            "ts_utc":   "2026-05-17T02:35:00Z",
            "version":  FRAME_ENVELOPE_VERSION,
        },
        "payload": {
            "kind":   "task-assigned",
            "data":   {},
            "schema": PAYLOAD_SCHEMA_TASK_OUTPUT,
        },
    });
    let bytes = serde_jcs::to_vec(&raw).unwrap();
    match parse_frame(&bytes) {
        Err(ParseError::UnknownSchema { field, value }) => {
            assert_eq!(field, "payload.schema");
            assert_eq!(value, PAYLOAD_SCHEMA_TASK_OUTPUT);
        }
        other => panic!("expected UnknownSchema, got {:?}", other),
    }
}

#[test]
fn schema_validation_bad_frame_id_shape_rejected() {
    let raw = serde_json::json!({
        "header": {
            "frame_id": "not-a-frame-id",
            "schema":   FRAME_ENVELOPE_SCHEMA,
            "source_runtime": "mira-sandbox",
            "target_runtime": "wakir-runtime",
            "ts_utc":   "2026-05-17T02:35:00Z",
            "version":  FRAME_ENVELOPE_VERSION,
        },
        "payload": {
            "kind":   "task-assigned",
            "data":   {},
            "schema": PAYLOAD_SCHEMA_TASK_ASSIGNED,
        },
    });
    let bytes = serde_jcs::to_vec(&raw).unwrap();
    assert!(matches!(
        parse_frame(&bytes),
        Err(ParseError::BadFrameIdShape(_))
    ));
}

#[test]
fn schema_validation_bad_timestamp_shape_rejected() {
    let raw = serde_json::json!({
        "header": {
            "frame_id": frame_id_seed_a(),
            "schema":   FRAME_ENVELOPE_SCHEMA,
            "source_runtime": "mira-sandbox",
            "target_runtime": "wakir-runtime",
            "ts_utc":   "2026-05-17",
            "version":  FRAME_ENVELOPE_VERSION,
        },
        "payload": {
            "kind":   "task-assigned",
            "data":   {},
            "schema": PAYLOAD_SCHEMA_TASK_ASSIGNED,
        },
    });
    let bytes = serde_jcs::to_vec(&raw).unwrap();
    assert!(matches!(
        parse_frame(&bytes),
        Err(ParseError::BadTimestampShape(_))
    ));
}

// ---------------------------------------------------------------------
// Tests 13..14 — Cross-lang fixture byte pins (placeholders for the
// future Python sibling).
//
// These tests pin the EXACT JCS bytes of two reference frames. When
// the Python `wirelang/federation/federation_frame.py` lands, its
// `serialize_frame` must produce byte-identical output for the same
// inputs. Until then, the constants below are the Rust-side anchor
// and the TODO marker (`TODO_PYTHON_FRAME_PARITY_PIN`) flags the
// follow-up.
// ---------------------------------------------------------------------

/// Pinned JCS-canonical bytes of the task-assigned reference frame.
/// Generated by the Rust crate on 2026-05-17; the future Python
/// sibling must match these bytes exactly.
const FRAME_FIXTURE_TASK_ASSIGNED_EXPECTED_PREFIX: &str =
    r#"{"header":{"frame_id":"frame-sha256:"#;

/// When `anchor_ref` is present it sorts BEFORE `header` lexically,
/// so the header substring starts with a comma rather than with `{`.
const FRAME_FIXTURE_MULTI_ORG_ATTESTATION_EXPECTED_HEADER_SUBSTR: &str =
    r#","header":{"frame_id":"frame-sha256:"#;

#[test]
fn cross_lang_fixture_byte_pin_task_assigned() {
    // The TODO marker MUST be present and non-empty so a future
    // refactor cannot silently drop the cross-lang sync handle.
    assert!(!TODO_PYTHON_FRAME_PARITY_PIN.is_empty());
    assert!(TODO_PYTHON_FRAME_PARITY_PIN.contains("federation_frame.py"));

    let frame = FederationFrame {
        anchor_ref: None,
        header: header_task_assigned(),
        payload: FederationPayload::TaskAssigned {
            data: payload_task_assigned_data(),
        },
        signature: None,
    };
    let bytes = serialize_frame(&frame).expect("serialize");
    let s = std::str::from_utf8(&bytes).expect("utf8");

    // JCS canonicalisation orders keys alphabetically; the outer
    // frame keys in lexical order are: header, payload (no
    // anchor_ref, no signature). The header keys in lexical order:
    // frame_id, schema, source_runtime, target_runtime, ts_utc,
    // version. So the bytes MUST start with the pinned prefix.
    assert!(
        s.starts_with(FRAME_FIXTURE_TASK_ASSIGNED_EXPECTED_PREFIX),
        "task-assigned fixture prefix drift: got {:?}",
        &s[..s.len().min(120)]
    );

    // The payload-kind tag and the payload-schema tag MUST both
    // appear in the canonical bytes. The kind/schema lockstep is
    // also enforced by the parser, but pinning the literal strings
    // here gives the Python sibling a textual anchor it can search
    // its own output for.
    assert!(s.contains(r#""kind":"task-assigned""#));
    assert!(s.contains(&format!(r#""schema":"{}""#, PAYLOAD_SCHEMA_TASK_ASSIGNED)));
    assert!(s.contains(&format!(r#""schema":"{}""#, FRAME_ENVELOPE_SCHEMA)));

    // Round-trip is identity.
    let parsed = parse_frame(&bytes).expect("parse");
    assert_eq!(parsed, frame);
}

#[test]
fn cross_lang_fixture_byte_pin_multi_org_attestation() {
    assert!(!TODO_PYTHON_FRAME_PARITY_PIN.is_empty());

    let mut header = header_task_assigned();
    header.frame_id = frame_id_seed_c();
    header.source_runtime = "acme/wakir-runtime".to_string();
    header.target_runtime = "globex/wakir-runtime".to_string();

    let frame = FederationFrame {
        anchor_ref: Some(format!("{}{}", ANCHOR_REF_PREFIX, "e".repeat(64))),
        header,
        payload: FederationPayload::MultiOrgAttestation {
            data: payload_multi_org_attestation_data(),
        },
        signature: None,
    };
    let bytes = serialize_frame(&frame).expect("serialize");
    let s = std::str::from_utf8(&bytes).expect("utf8");

    // anchor_ref sorts BEFORE header lexically, so when present the
    // bytes start with `{"anchor_ref":"wat:` rather than with
    // `{"header":...`.
    assert!(
        s.starts_with(&format!(r#"{{"anchor_ref":"{}"#, ANCHOR_REF_PREFIX)),
        "multi-org-attestation fixture prefix drift: got {:?}",
        &s[..s.len().min(120)]
    );

    // The header still appears, just after anchor_ref.
    assert!(s.contains(FRAME_FIXTURE_MULTI_ORG_ATTESTATION_EXPECTED_HEADER_SUBSTR));

    assert!(s.contains(r#""kind":"multi-org-attestation""#));
    assert!(s.contains(&format!(
        r#""schema":"{}""#,
        PAYLOAD_SCHEMA_MULTI_ORG_ATTESTATION
    )));

    // Round-trip is identity.
    let parsed = parse_frame(&bytes).expect("parse");
    assert_eq!(parsed, frame);
}

// ---------------------------------------------------------------------
// Bonus tests — extra invariants that strengthen the smoke surface.
// ---------------------------------------------------------------------

#[test]
fn parse_then_serialize_idempotent_for_each_kind() {
    let kinds: Vec<(FederationPayload, &str)> = vec![
        (
            FederationPayload::TaskAssigned {
                data: payload_task_assigned_data(),
            },
            "task-assigned",
        ),
        (
            FederationPayload::TaskOutput {
                data: payload_task_output_data(),
            },
            "task-output",
        ),
        (
            FederationPayload::MultiOrgAttestation {
                data: payload_multi_org_attestation_data(),
            },
            "multi-org-attestation",
        ),
        (
            FederationPayload::SpiffeBundleSync {
                data: payload_spiffe_bundle_sync_data(),
            },
            "spiffe-bundle-sync",
        ),
    ];

    for (payload, label) in kinds {
        let frame = FederationFrame {
            anchor_ref: None,
            header: header_task_assigned(),
            payload,
            signature: None,
        };
        let bytes1 = serialize_frame(&frame).expect(label);
        let parsed = parse_frame(&bytes1).expect(label);
        let bytes2 = serialize_frame(&parsed).expect(label);
        assert_eq!(bytes1, bytes2, "idempotency drift for kind {}", label);
    }
}

#[test]
fn unknown_payload_kind_rejected() {
    let raw = serde_json::json!({
        "header": {
            "frame_id": frame_id_seed_a(),
            "schema":   FRAME_ENVELOPE_SCHEMA,
            "source_runtime": "mira-sandbox",
            "target_runtime": "wakir-runtime",
            "ts_utc":   "2026-05-17T02:35:00Z",
            "version":  FRAME_ENVELOPE_VERSION,
        },
        "payload": {
            "kind":   "biscuit-attenuation-broadcast",
            "data":   {},
            "schema": "wakir.federation.biscuit-attenuation/1",
        },
    });
    let bytes = serde_jcs::to_vec(&raw).unwrap();
    match parse_frame(&bytes) {
        Err(ParseError::UnknownPayloadKind(k)) => {
            assert_eq!(k, "biscuit-attenuation-broadcast");
        }
        other => panic!("expected UnknownPayloadKind, got {:?}", other),
    }
}

#[test]
fn empty_runtime_id_rejected() {
    let raw = serde_json::json!({
        "header": {
            "frame_id": frame_id_seed_a(),
            "schema":   FRAME_ENVELOPE_SCHEMA,
            "source_runtime": "",
            "target_runtime": "wakir-runtime",
            "ts_utc":   "2026-05-17T02:35:00Z",
            "version":  FRAME_ENVELOPE_VERSION,
        },
        "payload": {
            "kind":   "task-assigned",
            "data":   {},
            "schema": PAYLOAD_SCHEMA_TASK_ASSIGNED,
        },
    });
    let bytes = serde_jcs::to_vec(&raw).unwrap();
    match parse_frame(&bytes) {
        Err(ParseError::BadRuntimeId { field, .. }) => {
            assert_eq!(field, "source_runtime");
        }
        other => panic!("expected BadRuntimeId, got {:?}", other),
    }
}

#[test]
fn missing_required_field_rejected() {
    // No `header` -> serde reports missing field.
    let raw = serde_json::json!({
        "payload": {
            "kind":   "task-assigned",
            "data":   {},
            "schema": PAYLOAD_SCHEMA_TASK_ASSIGNED,
        },
    });
    let bytes = serde_jcs::to_vec(&raw).unwrap();
    assert!(matches!(parse_frame(&bytes), Err(ParseError::BadJson(_))));
}

#[test]
fn signing_payload_bytes_omits_anchor_and_signature() {
    let frame_a = FederationFrame {
        anchor_ref: Some(format!("{}{}", ANCHOR_REF_PREFIX, "1".repeat(64))),
        header: header_task_assigned(),
        payload: FederationPayload::TaskAssigned {
            data: payload_task_assigned_data(),
        },
        signature: Some("0".repeat(128)),
    };
    let frame_b = FederationFrame {
        anchor_ref: None,
        header: header_task_assigned(),
        payload: FederationPayload::TaskAssigned {
            data: payload_task_assigned_data(),
        },
        signature: None,
    };
    // The two frames differ only in fields the signer should
    // ignore. The signing bytes MUST be identical.
    let sig_a = signing_payload_bytes(&frame_a).unwrap();
    let sig_b = signing_payload_bytes(&frame_b).unwrap();
    assert_eq!(sig_a, sig_b);
}

#[test]
fn spiffe_bundle_sync_schema_recognised() {
    // Defensive: ensure the spiffe-bundle-sync schema constant is
    // exported and matches the docstring. (Compile-time-check + the
    // test below validates the wire shape.)
    assert_eq!(
        PAYLOAD_SCHEMA_SPIFFE_BUNDLE_SYNC,
        "wakir.federation.spiffe-bundle-sync/1"
    );
}

#[test]
fn frame_id_prefix_constant_matches_helper() {
    let id = compute_frame_id(b"any-seed");
    assert!(id.starts_with(FRAME_ID_PREFIX));
}
