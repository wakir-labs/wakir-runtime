// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Smoke and invariant tests for persona-engine-anchor-emitter.
//
// Test taxonomy
// -------------
// - WIRE-SHAPE PINS (T01..T02): pin the constants and the JCS-
//   canonical wire-shape against fixture envelopes.
// - HAPPY-PATH BUILD (T03): build_anchor_envelope round-trips its
//   inputs verbatim.
// - VALIDATION REJECTIONS (T04..T05): empty fields and malformed
//   timestamps fail fast with a typed error.
// - DETERMINISM (T06): two builds of the same logical envelope
//   produce byte-identical canonical output.
// - HASH PREFIX + SHAPE (T07): hash_anchor returns "sha256:<hex>"
//   with the exact prefix and 64 lower-case hex chars.
// - CROSS-LANG HASH PIN (T08): SHA-256 of a documented payload
//   fixture matches the bare-hex string the Python
//   `envelope_payload_hash` would produce for the same input (the
//   payload is the canonical bytes themselves; the cross-lang
//   contract is "Rust sha256_hex(payload) == Python
//   hashlib.sha256(payload).hexdigest()").
// - WIRE-SHAPE EMBEDDED HASH PIN (T09): the `payload_sha256` field
//   inside the serialised envelope equals sha256_hex(payload_bytes);
//   this is the bridge between the prefixed Rust hash_anchor and
//   the bare-hex Python helper.
// - SERIALIZE+HASH CONSISTENCY (T10): serialize_and_hash returns
//   the same bytes/hash that the individual functions return.

use persona_engine_anchor_emitter::{
    assert_spec_invariants, build_anchor_envelope, hash_anchor, serialize_and_hash,
    serialize_anchor, sha256_hex, AnchorEmitterError, AnchorEmitterInput, ENVELOPE_SCHEMA,
    HASH_PREFIX, SHA256_HEX_LEN,
};

/// Fixture envelope input. Pinned in T08 / T09 cross-lang vectors;
/// any field-shape change here must be paired with a Python-side pin
/// update in `wirelang/persona/recovery_drill_anchor.py`'s sibling
/// test (Reza will land the matching Python pin in the next sweep).
fn fixture_input() -> AnchorEmitterInput {
    AnchorEmitterInput {
        event_id: "evt-2026-05-17-anchor-fixture-01".to_string(),
        timestamp_utc: "2026-05-17T00:00:00Z".to_string(),
        persona_id: "reza".to_string(),
        // Canonical bytes for the JCS-form of `{}` per RFC 8785 —
        // the well-known JCS empty-object encoding. Reusing the
        // empty-object bytes makes the cross-lang pin trivially
        // re-derivable on either side.
        payload_jcs_bytes: b"{}".to_vec(),
    }
}

// ---------------------------------------------------------------------
// T01 — Constants pin.
// ---------------------------------------------------------------------
#[test]
fn t01_constants_pin() {
    assert_eq!(ENVELOPE_SCHEMA, "wakir.wat.anchor-envelope/1");
    assert_eq!(HASH_PREFIX, "sha256:");
    assert_eq!(SHA256_HEX_LEN, 64);
    assert_spec_invariants().expect("invariants must hold");
}

// ---------------------------------------------------------------------
// T02 — Canonical wire-shape JSON keys are sorted lexicographically.
//
// JCS sorts object keys lexicographically; the cross-lang test pins
// the key order so any field rename on either side is caught.
// ---------------------------------------------------------------------
#[test]
fn t02_wire_shape_key_order_pinned() {
    let env = build_anchor_envelope(fixture_input()).expect("build");
    let bytes = serialize_anchor(&env);
    let text = std::str::from_utf8(&bytes).expect("JCS output is valid UTF-8");
    // JCS canonical output for our flat envelope shape: one object,
    // five fields, keys sorted lex (event_id < payload_sha256 <
    // persona_id < schema < timestamp_utc).
    let key_positions = [
        text.find("\"event_id\""),
        text.find("\"payload_sha256\""),
        text.find("\"persona_id\""),
        text.find("\"schema\""),
        text.find("\"timestamp_utc\""),
    ];
    for (i, p) in key_positions.iter().enumerate() {
        assert!(p.is_some(), "key #{} missing from wire output: {:?}", i, text);
    }
    let positions: Vec<usize> = key_positions.iter().map(|p| p.unwrap()).collect();
    let mut sorted = positions.clone();
    sorted.sort();
    assert_eq!(
        positions, sorted,
        "wire-shape keys not in lex order; got positions {:?} in {:?}",
        positions, text
    );
}

// ---------------------------------------------------------------------
// T03 — Happy-path build: fields round-trip verbatim.
// ---------------------------------------------------------------------
#[test]
fn t03_happy_path_build_round_trip() {
    let input = fixture_input();
    let env = build_anchor_envelope(input.clone()).expect("build");
    assert_eq!(env.event_id, input.event_id);
    assert_eq!(env.timestamp_utc, input.timestamp_utc);
    assert_eq!(env.persona_id, input.persona_id);
    assert_eq!(env.payload_jcs_bytes, input.payload_jcs_bytes);
}

// ---------------------------------------------------------------------
// T04 — Empty field rejections.
// ---------------------------------------------------------------------
#[test]
fn t04_empty_field_rejections() {
    let mut input = fixture_input();
    input.event_id = "".to_string();
    assert_eq!(
        build_anchor_envelope(input),
        Err(AnchorEmitterError::EmptyField("event_id"))
    );

    let mut input = fixture_input();
    input.persona_id = "   ".to_string();
    assert_eq!(
        build_anchor_envelope(input),
        Err(AnchorEmitterError::EmptyField("persona_id"))
    );

    let mut input = fixture_input();
    input.timestamp_utc = "".to_string();
    assert_eq!(
        build_anchor_envelope(input),
        Err(AnchorEmitterError::EmptyField("timestamp_utc"))
    );
}

// ---------------------------------------------------------------------
// T05 — Timestamp shape rejection.
// ---------------------------------------------------------------------
#[test]
fn t05_bad_timestamp_shape_rejected() {
    let mut input = fixture_input();
    input.timestamp_utc = "2026-05-17 00:00:00Z".to_string(); // space, not T
    let err = build_anchor_envelope(input).unwrap_err();
    assert!(
        matches!(err, AnchorEmitterError::BadTimestampShape(_)),
        "expected BadTimestampShape, got {:?}",
        err
    );

    let mut input = fixture_input();
    input.timestamp_utc = "2026-05-17T00:00:00".to_string(); // missing Z
    let err = build_anchor_envelope(input).unwrap_err();
    assert!(
        matches!(err, AnchorEmitterError::BadTimestampShape(_)),
        "expected BadTimestampShape, got {:?}",
        err
    );

    let mut input = fixture_input();
    input.timestamp_utc = "2026-05-17T00:00:00.123Z".to_string(); // sub-sec
    let err = build_anchor_envelope(input).unwrap_err();
    assert!(
        matches!(err, AnchorEmitterError::BadTimestampShape(_)),
        "expected BadTimestampShape, got {:?}",
        err
    );
}

// ---------------------------------------------------------------------
// T06 — Determinism: two builds of the same input produce identical
// canonical bytes.
// ---------------------------------------------------------------------
#[test]
fn t06_determinism_byte_identical() {
    let a = build_anchor_envelope(fixture_input()).unwrap();
    let b = build_anchor_envelope(fixture_input()).unwrap();
    assert_eq!(serialize_anchor(&a), serialize_anchor(&b));
    assert_eq!(hash_anchor(&a), hash_anchor(&b));
}

// ---------------------------------------------------------------------
// T07 — Hash prefix + shape: "sha256:" + 64 lower-case hex chars.
// ---------------------------------------------------------------------
#[test]
fn t07_hash_prefix_and_shape() {
    let env = build_anchor_envelope(fixture_input()).unwrap();
    let h = hash_anchor(&env);
    assert!(h.starts_with("sha256:"), "missing prefix: {}", h);
    let tail = &h[HASH_PREFIX.len()..];
    assert_eq!(
        tail.len(),
        SHA256_HEX_LEN,
        "hex tail wrong length: {:?}",
        tail
    );
    assert!(
        tail.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()),
        "hex tail must be lower-case ASCII hex: {:?}",
        tail
    );
}

// ---------------------------------------------------------------------
// T08 — CROSS-LANG HASH PIN.
//
// The payload bytes for the fixture envelope are `b"{}"` (the JCS
// canonical form of an empty JSON object). The bare-hex SHA-256 of
// `b"{}"` is the well-known constant below. Python sibling test
// computes:
//   hashlib.sha256(b"{}").hexdigest()
// and must produce the same hex tail. Any drift breaks Rust here.
//
// Pinned value derivation: echo -n '{}' | sha256sum -> the value
// below. Cross-checked on 2026-05-17 ~02:20 CEST.
// ---------------------------------------------------------------------
#[test]
fn t08_cross_lang_sha256_pin_of_payload() {
    let env = build_anchor_envelope(fixture_input()).unwrap();
    let payload_hash = sha256_hex(&env.payload_jcs_bytes);
    assert_eq!(
        payload_hash,
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        "Rust SHA-256 of payload bytes drifted from Python pin \
         (hashlib.sha256(b'{{}}').hexdigest())"
    );
}

// ---------------------------------------------------------------------
// T09 — Wire-shape embedded hash equals sha256_hex(payload_bytes).
//
// This is the bridge between the prefixed Rust hash_anchor (which
// hashes the OUTER envelope) and the bare-hex Python
// envelope_payload_hash helper. The Rust envelope embeds the bare
// hex of the payload SHA-256 in the wire object so any Python-side
// consumer can read the same value without re-canonicalising.
// ---------------------------------------------------------------------
#[test]
fn t09_wire_shape_embedded_payload_hash_matches_helper() {
    use persona_engine_anchor_emitter::_test_only_wire_value;
    let env = build_anchor_envelope(fixture_input()).unwrap();
    let wire = _test_only_wire_value(&env);
    let embedded = wire
        .get("payload_sha256")
        .and_then(|v| v.as_str())
        .expect("payload_sha256 must be a string field in the wire shape");
    let direct = sha256_hex(&env.payload_jcs_bytes);
    assert_eq!(
        embedded, direct,
        "embedded payload_sha256 drifted from direct sha256_hex(payload_bytes)"
    );
}

// ---------------------------------------------------------------------
// T10 — serialize_and_hash convenience returns identical (bytes, hash)
// to the individual functions.
// ---------------------------------------------------------------------
#[test]
fn t10_serialize_and_hash_matches_individual_calls() {
    let env = build_anchor_envelope(fixture_input()).unwrap();
    let (bytes_combined, hash_combined) = serialize_and_hash(&env);
    let bytes_solo = serialize_anchor(&env);
    let hash_solo = hash_anchor(&env);
    assert_eq!(bytes_combined, bytes_solo);
    assert_eq!(hash_combined, hash_solo);
}

// ---------------------------------------------------------------------
// T11 — Sensitivity: a one-byte payload change flips the hash.
//
// Avalanche / collision-resistance is a SHA-256 property, but the
// crate-level smoke test ensures we do not accidentally hash a
// fixed constant.
// ---------------------------------------------------------------------
#[test]
fn t11_payload_change_flips_hash() {
    let env_a = build_anchor_envelope(fixture_input()).unwrap();
    let mut input_b = fixture_input();
    input_b.payload_jcs_bytes = b"{ }".to_vec();
    let env_b = build_anchor_envelope(input_b).unwrap();
    assert_ne!(
        hash_anchor(&env_a),
        hash_anchor(&env_b),
        "anchor hash must reflect payload changes"
    );
    assert_ne!(
        serialize_anchor(&env_a),
        serialize_anchor(&env_b),
        "canonical bytes must reflect payload changes"
    );
}

// ---------------------------------------------------------------------
// T12 — Sensitivity: changing event_id flips the canonical bytes
// and the outer hash, but does NOT change the embedded
// `payload_sha256`.
// ---------------------------------------------------------------------
#[test]
fn t12_event_id_change_isolates_payload_hash() {
    use persona_engine_anchor_emitter::_test_only_wire_value;
    let env_a = build_anchor_envelope(fixture_input()).unwrap();
    let mut input_b = fixture_input();
    input_b.event_id = "evt-2026-05-17-anchor-fixture-02".to_string();
    let env_b = build_anchor_envelope(input_b).unwrap();

    assert_ne!(serialize_anchor(&env_a), serialize_anchor(&env_b));
    assert_ne!(hash_anchor(&env_a), hash_anchor(&env_b));

    let wa = _test_only_wire_value(&env_a);
    let wb = _test_only_wire_value(&env_b);
    assert_eq!(
        wa.get("payload_sha256"),
        wb.get("payload_sha256"),
        "payload_sha256 must NOT depend on event_id"
    );
}
