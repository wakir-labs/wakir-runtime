// SPDX-License-Identifier: Apache-2.0
//! Integration tests for `persona-engine-format` (Sprint-Pengine-7 Tag-1).
//!
//! Anchor: `wirelang/specs/persona-engine-format-spec.md` v1.0 §6.
//!
//! Test inventory:
//! - 13 × per-persona schema-validation + idempotence + hash-stability
//!   (T-PEF-{slug}-A/B/C/D). Implemented as one parameterised loop
//!   per axis (A/B/C/D) over the 13 fixtures so the test count stays
//!   proportional to the fixture count.
//! - Aggregate determinism tests (T-PEF-DET-01..02).
//! - Edge cases (T-PEF-EDGE-01..03).
//! - V-907 integration anchor (T-PEF-V907-01).
//! - Mapping byte-determinism cross-pass (T-PEF-DET-03).
//!
//! Total: 12 named tests (the 4 per-persona axes are batched per
//! axis-level test, yielding 4 + 2 + 3 + 1 + 1 + 1 = 12).

use persona_engine_format::{
    jcs_canonicalise_wakir_persona_v1, map_claude_native_to_wakir_v1, wakir_persona_hash,
    WAKIR_PERSONA_SCHEMA_VERSION,
};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::HashSet;

// ---------------------------------------------------------------------
// Fixture inventory — 13 active personae, copied from /var/home/fred/
// AI-Corp/.claude/agents/ via the crate-build harness.
// ---------------------------------------------------------------------

const PERSONA_FIXTURES: &[(&str, &str)] = &[
    ("mira", include_str!("fixtures/claude-agents/mira.md")),
    ("cto", include_str!("fixtures/claude-agents/cto.md")),
    ("hr", include_str!("fixtures/claude-agents/hr.md")),
    ("cfo", include_str!("fixtures/claude-agents/cfo.md")),
    ("comms", include_str!("fixtures/claude-agents/comms.md")),
    (
        "internal-audit",
        include_str!("fixtures/claude-agents/internal-audit.md"),
    ),
    (
        "dev-engineering",
        include_str!("fixtures/claude-agents/dev-engineering.md"),
    ),
    ("reza", include_str!("fixtures/claude-agents/reza.md")),
    ("kai", include_str!("fixtures/claude-agents/kai.md")),
    ("pengine", include_str!("fixtures/claude-agents/pengine.md")),
    (
        "frontend",
        include_str!("fixtures/claude-agents/frontend.md"),
    ),
    ("qa", include_str!("fixtures/claude-agents/qa.md")),
    ("sre", include_str!("fixtures/claude-agents/sre.md")),
];

// ---------------------------------------------------------------------
// Helper — minimal hand-rolled validator for the wakir-persona-v1 shape
// (so we do not introduce a new schema-validation dependency at the
// test layer). The check covers the required-keys + key-type
// surface mandated by `wirelang/schemas/wakir-persona-v1.json`.
// ---------------------------------------------------------------------

fn assert_wakir_persona_v1_shape(doc: &Value, persona_id: &str) {
    let obj = doc
        .as_object()
        .unwrap_or_else(|| panic!("[{persona_id}] doc must be an object"));

    // schema_version: const "wakir-persona-v1"
    assert_eq!(
        obj.get("schema_version").and_then(|v| v.as_str()),
        Some(WAKIR_PERSONA_SCHEMA_VERSION),
        "[{persona_id}] schema_version"
    );

    // persona_id: equal to canonical_subset.name
    let pid = obj
        .get("persona_id")
        .and_then(|v| v.as_str())
        .unwrap_or_else(|| panic!("[{persona_id}] persona_id"));
    assert_eq!(pid, persona_id, "[{persona_id}] persona_id matches slug");

    // canonical_subset
    let cs = obj
        .get("canonical_subset")
        .and_then(|v| v.as_object())
        .unwrap_or_else(|| panic!("[{persona_id}] canonical_subset"));
    for k in [
        "name",
        "description",
        "tools",
        "schema_version",
        "identity_pinned",
    ] {
        assert!(cs.contains_key(k), "[{persona_id}] canonical_subset.{k}");
    }
    assert_eq!(
        cs.get("schema_version").and_then(|v| v.as_str()),
        Some("persona-v1"),
        "[{persona_id}] canonical_subset.schema_version"
    );
    assert_eq!(
        cs.get("name").and_then(|v| v.as_str()),
        Some(persona_id),
        "[{persona_id}] canonical_subset.name matches"
    );

    // identity_pinned shape
    let ip = cs
        .get("identity_pinned")
        .and_then(|v| v.as_object())
        .unwrap_or_else(|| panic!("[{persona_id}] identity_pinned"));
    for k in ["cross_review_zones", "authority", "hierarchy"] {
        assert!(ip.contains_key(k), "[{persona_id}] identity_pinned.{k}");
    }
    let auth = ip
        .get("authority")
        .and_then(|v| v.as_object())
        .unwrap_or_else(|| panic!("[{persona_id}] authority"));
    for k in ["push_remote", "budget_cap_eur_per_month", "sub_delegation"] {
        assert!(auth.contains_key(k), "[{persona_id}] authority.{k}");
    }
    let hier = ip
        .get("hierarchy")
        .and_then(|v| v.as_object())
        .unwrap_or_else(|| panic!("[{persona_id}] hierarchy"));
    for k in ["reports_to", "escalation"] {
        assert!(hier.contains_key(k), "[{persona_id}] hierarchy.{k}");
    }

    // claude_native_source — preserves at minimum name+description
    let src = obj
        .get("claude_native_source")
        .and_then(|v| v.as_object())
        .unwrap_or_else(|| panic!("[{persona_id}] claude_native_source"));
    assert_eq!(
        src.get("name").and_then(|v| v.as_str()),
        Some(persona_id),
        "[{persona_id}] claude_native_source.name"
    );
    assert!(
        src.get("description").is_some(),
        "[{persona_id}] claude_native_source.description"
    );

    // spawn_lifecycle
    let sl = obj
        .get("spawn_lifecycle")
        .and_then(|v| v.as_object())
        .unwrap_or_else(|| panic!("[{persona_id}] spawn_lifecycle"));
    for k in [
        "states",
        "valid_transitions",
        "recovery_policy",
        "max_concurrent_instances",
    ] {
        assert!(sl.contains_key(k), "[{persona_id}] spawn_lifecycle.{k}");
    }
    let rp = sl
        .get("recovery_policy")
        .and_then(|v| v.as_object())
        .unwrap_or_else(|| panic!("[{persona_id}] recovery_policy"));
    assert_eq!(
        rp.get("kind").and_then(|v| v.as_str()),
        Some("event-replay"),
        "[{persona_id}] recovery_policy.kind"
    );

    // state_persistence — bucket template embeds persona_id
    let sp = obj
        .get("state_persistence")
        .and_then(|v| v.as_object())
        .unwrap_or_else(|| panic!("[{persona_id}] state_persistence"));
    let expected_bucket = format!("wakir-persona-state-{persona_id}");
    assert_eq!(
        sp.get("bucket_template").and_then(|v| v.as_str()),
        Some(expected_bucket.as_str()),
        "[{persona_id}] state_persistence.bucket_template"
    );

    // container_bridge — Zone J
    let cb = obj
        .get("container_bridge")
        .and_then(|v| v.as_object())
        .unwrap_or_else(|| panic!("[{persona_id}] container_bridge"));
    assert_eq!(
        cb.get("cross_review_zone").and_then(|v| v.as_str()),
        Some("J"),
        "[{persona_id}] container_bridge.cross_review_zone"
    );

    // migration_metadata
    let mm = obj
        .get("migration_metadata")
        .and_then(|v| v.as_object())
        .unwrap_or_else(|| panic!("[{persona_id}] migration_metadata"));
    assert_eq!(
        mm.get("source_axis").and_then(|v| v.as_str()),
        Some("persona-claude-native"),
        "[{persona_id}] migration_metadata.source_axis"
    );
    assert_eq!(
        mm.get("target_axis_version").and_then(|v| v.as_str()),
        Some("v1"),
        "[{persona_id}] migration_metadata.target_axis_version"
    );

    // model_override: null or string
    let mo = obj
        .get("model_override")
        .unwrap_or_else(|| panic!("[{persona_id}] model_override key"));
    assert!(
        mo.is_null() || mo.is_string(),
        "[{persona_id}] model_override must be null or string"
    );
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    let digest = hasher.finalize();
    hex::encode(digest)
}

// ---------------------------------------------------------------------
// T-PEF-AXIS-A — all 13 personae parse + map without error.
// (This rolls up T-PEF-{slug}-A for each of the 13.)
// ---------------------------------------------------------------------

#[test]
fn t_pef_axis_a_all_13_personae_parse_and_map() {
    for (slug, text) in PERSONA_FIXTURES {
        let result = map_claude_native_to_wakir_v1(text);
        assert!(
            result.is_ok(),
            "[{slug}] map_claude_native_to_wakir_v1 failed: {result:?}"
        );
    }
}

// ---------------------------------------------------------------------
// T-PEF-AXIS-B — all 13 outputs validate against wakir-persona-v1 shape.
// (This rolls up T-PEF-{slug}-B for each of the 13.)
// ---------------------------------------------------------------------

#[test]
fn t_pef_axis_b_all_13_outputs_validate_wakir_persona_v1_shape() {
    for (slug, text) in PERSONA_FIXTURES {
        let doc = map_claude_native_to_wakir_v1(text)
            .unwrap_or_else(|e| panic!("[{slug}] map failed: {e}"));
        assert_wakir_persona_v1_shape(&doc, slug);
    }
}

// ---------------------------------------------------------------------
// T-PEF-AXIS-C — JCS byte-determinism: two back-to-back maps + JCS
// produce identical bytes for every persona.
// (This rolls up T-PEF-{slug}-C for each of the 13.)
// ---------------------------------------------------------------------

#[test]
fn t_pef_axis_c_jcs_byte_determinism_two_passes() {
    for (slug, text) in PERSONA_FIXTURES {
        let doc_a = map_claude_native_to_wakir_v1(text)
            .unwrap_or_else(|e| panic!("[{slug}] map A failed: {e}"));
        let doc_b = map_claude_native_to_wakir_v1(text)
            .unwrap_or_else(|e| panic!("[{slug}] map B failed: {e}"));
        let bytes_a = jcs_canonicalise_wakir_persona_v1(&doc_a).expect("jcs A");
        let bytes_b = jcs_canonicalise_wakir_persona_v1(&doc_b).expect("jcs B");
        assert_eq!(
            bytes_a, bytes_b,
            "[{slug}] JCS byte-determinism across two passes"
        );
    }
}

// ---------------------------------------------------------------------
// T-PEF-AXIS-D — V-907 hash is byte-stable and well-formed per persona.
// (This rolls up T-PEF-{slug}-D for each of the 13.)
// ---------------------------------------------------------------------

#[test]
fn t_pef_axis_d_v907_persona_hash_stable_and_wellformed() {
    for (slug, text) in PERSONA_FIXTURES {
        let doc = map_claude_native_to_wakir_v1(text)
            .unwrap_or_else(|e| panic!("[{slug}] map failed: {e}"));
        let h1 = wakir_persona_hash(&doc).expect("hash A");
        let h2 = wakir_persona_hash(&doc).expect("hash B");
        assert_eq!(h1, h2, "[{slug}] persona-hash determinism");
        assert!(h1.starts_with("sha256:"), "[{slug}] hash prefix: {h1}");
        assert_eq!(h1.len(), "sha256:".len() + 64, "[{slug}] hash length");
        // Hex-tail must decode.
        let tail = &h1["sha256:".len()..];
        let _ = hex::decode(tail).unwrap_or_else(|e| panic!("[{slug}] hash hex-tail decode: {e}"));
    }
}

// ---------------------------------------------------------------------
// T-PEF-DET-01 — JCS round-trip stability across all 13 (the on-disk
// bytes round-trip through serde_json::from_slice and re-JCS to the
// same bytes).
// ---------------------------------------------------------------------

#[test]
fn t_pef_det_01_jcs_round_trip_stability() {
    for (slug, text) in PERSONA_FIXTURES {
        let doc = map_claude_native_to_wakir_v1(text)
            .unwrap_or_else(|e| panic!("[{slug}] map failed: {e}"));
        let bytes_1 = jcs_canonicalise_wakir_persona_v1(&doc).expect("jcs 1");
        // Round-trip: parse the JCS bytes back into a Value and re-JCS.
        let parsed: Value =
            serde_json::from_slice(&bytes_1).unwrap_or_else(|e| panic!("[{slug}] parse: {e}"));
        let bytes_2 = jcs_canonicalise_wakir_persona_v1(&parsed).expect("jcs 2");
        assert_eq!(bytes_1, bytes_2, "[{slug}] JCS round-trip stability");
    }
}

// ---------------------------------------------------------------------
// T-PEF-DET-02 — hash-set cardinality equals 13 (no collisions across
// the 13 distinct personae).
// ---------------------------------------------------------------------

#[test]
fn t_pef_det_02_hash_set_cardinality_13() {
    let mut hashes: HashSet<String> = HashSet::new();
    for (slug, text) in PERSONA_FIXTURES {
        let doc = map_claude_native_to_wakir_v1(text)
            .unwrap_or_else(|e| panic!("[{slug}] map failed: {e}"));
        let h = wakir_persona_hash(&doc).expect("hash");
        assert!(
            hashes.insert(h.clone()),
            "[{slug}] persona-hash collision: {h}"
        );
    }
    assert_eq!(hashes.len(), 13, "13 distinct persona-hashes");
}

// ---------------------------------------------------------------------
// T-PEF-EDGE-01 — hr.md edge case: model: sonnet, no tools: key,
// yields model_override="sonnet" and tools=[].
// ---------------------------------------------------------------------

#[test]
fn t_pef_edge_01_hr_model_override_no_tools() {
    let hr_text = include_str!("fixtures/claude-agents/hr.md");
    let doc = map_claude_native_to_wakir_v1(hr_text).expect("hr.md must map");
    let obj = doc.as_object().expect("object");

    // model_override = "sonnet"
    let mo = obj.get("model_override").expect("model_override");
    assert_eq!(mo.as_str(), Some("sonnet"));

    // canonical_subset.tools = []
    let tools = obj
        .get("canonical_subset")
        .and_then(|v| v.as_object())
        .and_then(|o| o.get("tools"))
        .and_then(|v| v.as_array())
        .expect("tools array");
    assert_eq!(tools.len(), 0, "tools array must be empty");

    // claude_native_source.model = "sonnet"
    let src_model = obj
        .get("claude_native_source")
        .and_then(|v| v.as_object())
        .and_then(|o| o.get("model"))
        .and_then(|v| v.as_str());
    assert_eq!(src_model, Some("sonnet"));
}

// ---------------------------------------------------------------------
// T-PEF-EDGE-02 — synthetic fixture missing `description` is rejected.
// ---------------------------------------------------------------------

#[test]
fn t_pef_edge_02_missing_description_rejected() {
    let synth = "---\nname: foo\ntools: Read\n---\n\n# body\n";
    let result = map_claude_native_to_wakir_v1(synth);
    assert!(result.is_err(), "missing description must fail");
    let err_msg = format!("{}", result.unwrap_err());
    assert!(
        err_msg.contains("description"),
        "error must mention description: {err_msg}"
    );
}

// ---------------------------------------------------------------------
// T-PEF-EDGE-03 — unknown front-matter keys are preserved in
// claude_native_source and dropped from canonical_subset.
// ---------------------------------------------------------------------

#[test]
fn t_pef_edge_03_unknown_keys_preserved_in_source_dropped_from_subset() {
    let synth = "---\n\
        name: foo\n\
        description: synthetic\n\
        tools: Read\n\
        custom_key: custom_value\n\
        another_one: 42\n\
        ---\n\n# body\n";
    let doc = map_claude_native_to_wakir_v1(synth).expect("synthetic must map");
    let obj = doc.as_object().expect("object");

    // claude_native_source preserves the unknown keys.
    let src = obj
        .get("claude_native_source")
        .and_then(|v| v.as_object())
        .expect("source object");
    assert_eq!(
        src.get("custom_key").and_then(|v| v.as_str()),
        Some("custom_value"),
        "custom_key preserved"
    );
    assert_eq!(
        src.get("another_one").and_then(|v| v.as_i64()),
        Some(42),
        "another_one preserved"
    );

    // canonical_subset must NOT contain the unknown keys.
    let cs = obj
        .get("canonical_subset")
        .and_then(|v| v.as_object())
        .expect("subset object");
    assert!(!cs.contains_key("custom_key"));
    assert!(!cs.contains_key("another_one"));
}

// ---------------------------------------------------------------------
// T-PEF-V907-01 — V-907 byte-determinism anchor: the embedded
// canonical_subset MUST hash to the same value as if it were hashed
// in isolation through `persona_hash::compute_persona_hash_from_
// canonical`. (Sanity check that wakir_persona_hash is doing exactly
// what §5 of the spec says it does.)
// ---------------------------------------------------------------------

#[test]
fn t_pef_v907_01_hash_function_unchanged() {
    for (slug, text) in PERSONA_FIXTURES {
        let doc = map_claude_native_to_wakir_v1(text)
            .unwrap_or_else(|e| panic!("[{slug}] map failed: {e}"));

        // Wrapper-hash via the public surface.
        let h_wrapper = wakir_persona_hash(&doc).expect("wrapper hash");

        // Direct-hash on the embedded canonical_subset.
        let cs = doc
            .as_object()
            .and_then(|o| o.get("canonical_subset"))
            .expect("canonical_subset");
        let h_direct =
            persona_hash::compute_persona_hash_from_canonical(cs, None).expect("direct hash");

        assert_eq!(
            h_wrapper, h_direct,
            "[{slug}] V-907 hash function unchanged at the byte level"
        );
    }
}

// ---------------------------------------------------------------------
// T-PEF-DET-03 — mapping cross-pass: serialising the wakir-persona-v1
// document to bytes, parsing back, and remapping the embedded
// claude_native_source through the converter again would NOT be the
// identity in the general case (the converter consumes axis-A markdown
// and we have only the front-matter mapping in JSON form), but the
// SHA-256 of the JCS bytes is byte-stable across the parse-roundtrip
// (covered by T-PEF-DET-01) and the persona-hash is stable across the
// round-trip (this test). This is the operator-side pin-pack derivation
// surface (§5.2).
// ---------------------------------------------------------------------

#[test]
fn t_pef_det_03_persona_hash_stable_across_json_roundtrip() {
    for (slug, text) in PERSONA_FIXTURES {
        let doc = map_claude_native_to_wakir_v1(text)
            .unwrap_or_else(|e| panic!("[{slug}] map failed: {e}"));
        let h_pre = wakir_persona_hash(&doc).expect("hash pre");

        let bytes = jcs_canonicalise_wakir_persona_v1(&doc).expect("jcs");
        let bytes_digest = sha256_hex(&bytes);
        // Sanity: the bytes hash differs from the persona-hash
        // (different inputs); we only assert both are deterministic.
        assert_eq!(bytes_digest.len(), 64);

        let parsed: Value =
            serde_json::from_slice(&bytes).unwrap_or_else(|e| panic!("[{slug}] parse: {e}"));
        let h_post = wakir_persona_hash(&parsed).expect("hash post");

        assert_eq!(
            h_pre, h_post,
            "[{slug}] persona-hash stable across JSON round-trip"
        );
    }
}
