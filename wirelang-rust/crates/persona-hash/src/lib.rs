// SPDX-License-Identifier: Apache-2.0
//! V-907 persona-hash primitive — Rust pendant.
//!
//! This crate is the byte-for-byte equivalent of
//! `wirelang.persona.persona_hash.compute_persona_hash_from_canonical`
//! in the Python tree. It exists so Phase-1c can migrate the hash
//! producer from Python to Rust without moving the V-907 pin pack.
//!
//! Determinism contract
//! --------------------
//!
//! Given a canonical-subset object (the dict produced by
//! `wirelang.persona.persona_canonical_form.extract_canonical_subset`),
//! this crate must emit the EXACT same `"sha256:<64hex>"` string as
//! the Python module. The pin pack in
//! `wirelang/persona/_internal/pin_pack_constants.py` is the
//! cross-language test oracle.
//!
//! Anchors:
//!
//! - V9 ground truth (frozen 2026-05-07):
//!   `sha256:0f298894204e6117e42ad7073b7a3af8ada1851de74d585fc5cb4c4d70e1d793`
//! - JCS (RFC 8785) is the canonicalisation; we use `serde_jcs`.
//! - SHA-256 via `sha2` 0.10.x; lower-case hex via `hex` 0.4.x.
//!
//! Default-Lock posture
//! --------------------
//!
//! - A-1 Mock-Format-Baseline: this crate sees a `serde_json::Value`
//!   (already-extracted canonical subset). YAML parsing is out-of-scope.
//! - A-3 Body out-of-hash: the Markdown body never reaches this crate;
//!   we hash only the JCS-serialised canonical subset.
//!
//! Public surface
//! --------------
//!
//! - [`PERSONA_HASH_PREFIX`] — `"sha256:"`.
//! - [`PERSONA_HASH_HEX_LENGTH`] — `64`.
//! - [`PERSONA_EMPTY_REF_SENTINEL`] — `""` (V-908 federation stub).
//! - [`PersonaHashError`] — error enum (input shape, mismatch).
//! - [`compute_persona_hash_from_canonical`] — main entry point.
//!
//! NOT yet implemented in Rust (Phase-1c follow-up boxes):
//!
//! - YAML front-matter parsing (Python: `persona_canonical_form.py`).
//! - Schema-version checking (Python: `persona_hash.py` line ~178).
//! - File-path entry point (`compute_persona_hash`).

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use serde_json::Value;
use sha2::{Digest, Sha256};

/// Prefix on every persona-hash string. Mirrors Python
/// `PERSONA_HASH_PREFIX`.
pub const PERSONA_HASH_PREFIX: &str = "sha256:";

/// Length of the hex tail. Mirrors Python `PERSONA_HASH_HEX_LENGTH`.
pub const PERSONA_HASH_HEX_LENGTH: usize = 64;

/// Total length of `"sha256:" + 64 hex chars`.
pub const PERSONA_HASH_FULL_LENGTH: usize = PERSONA_HASH_PREFIX.len() + PERSONA_HASH_HEX_LENGTH;

/// V-908 federation-stub sentinel: empty string when no persona is
/// pinned. Mirrors Python `PERSONA_EMPTY_REF_SENTINEL`.
pub const PERSONA_EMPTY_REF_SENTINEL: &str = "";

/// Error class for the persona-hash primitive.
///
/// Variants mirror the Python error classes that THIS layer is
/// responsible for. Schema-version errors and YAML-parse errors live
/// in upstream layers (future crates) and are therefore not modelled
/// here.
#[derive(Debug)]
pub enum PersonaHashError {
    /// The input is not a JSON object. The canonical subset is always
    /// a top-level object; arrays / scalars are rejected.
    NotAnObject,

    /// JCS canonicalisation failed. With well-formed
    /// `serde_json::Value` input this is unreachable in practice; we
    /// still surface the error rather than panic.
    CanonicaliseError(String),

    /// Caller-supplied pin disagrees with the freshly-computed hash.
    /// Mirrors Python `PersonaHashMismatchError`. Both forms (full
    /// `"sha256:<64hex>"` and bare `<64hex>`) are accepted on input;
    /// the message reports the full form.
    Mismatch {
        /// Full-form expected hash (always `"sha256:<64hex>"` here).
        expected: String,
        /// Full-form computed hash (`"sha256:<64hex>"`).
        computed: String,
    },
}

impl std::fmt::Display for PersonaHashError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PersonaHashError::NotAnObject => f.write_str("canonical subset must be a JSON object"),
            PersonaHashError::CanonicaliseError(msg) => {
                write!(f, "JCS canonicalisation failed: {msg}")
            }
            PersonaHashError::Mismatch { expected, computed } => write!(
                f,
                "persona-hash drift: expected {expected}, computed {computed}"
            ),
        }
    }
}

impl std::error::Error for PersonaHashError {}

/// Compute `"sha256:<64hex>"` over JCS-canonical-JSON of the canonical
/// subset.
///
/// # Arguments
///
/// * `canonical_subset` — the canonical-subset object. Must be a
///   `serde_json::Value::Object`. Other shapes return
///   [`PersonaHashError::NotAnObject`].
/// * `expected` — optional caller-pin. Accepts either the full
///   `"sha256:<64hex>"` form or the bare 64-char hex tail (matching
///   Python's tolerance). On drift, returns
///   [`PersonaHashError::Mismatch`].
///
/// # Determinism
///
/// JCS sorts keys lexicographically by UTF-16 code-unit ordering and
/// canonicalises numbers per ECMA-262. The Rust `serde_jcs` crate and
/// the Python `rfc8785` package implement the same RFC; the V9
/// cross-check test asserts byte-equality of the digest over the
/// reference vector.
///
/// # Errors
///
/// See [`PersonaHashError`].
pub fn compute_persona_hash_from_canonical(
    canonical_subset: &Value,
    expected: Option<&str>,
) -> Result<String, PersonaHashError> {
    if !canonical_subset.is_object() {
        return Err(PersonaHashError::NotAnObject);
    }

    let jcs_bytes = serde_jcs::to_vec(canonical_subset)
        .map_err(|e| PersonaHashError::CanonicaliseError(e.to_string()))?;

    let mut hasher = Sha256::new();
    hasher.update(&jcs_bytes);
    let digest = hasher.finalize();
    let hex_tail = hex::encode(digest);
    let full = format!("{PERSONA_HASH_PREFIX}{hex_tail}");

    if let Some(pin) = expected {
        let (expected_full, expected_hex) =
            if let Some(stripped) = pin.strip_prefix(PERSONA_HASH_PREFIX) {
                (pin.to_string(), stripped.to_string())
            } else {
                (format!("{PERSONA_HASH_PREFIX}{pin}"), pin.to_string())
            };
        if expected_hex != hex_tail {
            return Err(PersonaHashError::Mismatch {
                expected: expected_full,
                computed: full,
            });
        }
    }

    Ok(full)
}

/// Convenience: compute the JCS canonicalisation as bytes (without
/// hashing). Exposed for the cross-language fixture test, which
/// asserts the JCS bytes byte-for-byte against the Python output.
///
/// # Errors
///
/// Returns [`PersonaHashError::NotAnObject`] if the input is not a
/// JSON object, or [`PersonaHashError::CanonicaliseError`] if JCS
/// fails on a malformed value.
pub fn jcs_canonicalise(canonical_subset: &Value) -> Result<Vec<u8>, PersonaHashError> {
    if !canonical_subset.is_object() {
        return Err(PersonaHashError::NotAnObject);
    }
    serde_jcs::to_vec(canonical_subset)
        .map_err(|e| PersonaHashError::CanonicaliseError(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// V9 fixture as a hand-built canonical subset. Bytes verified
    /// against the Python `rfc8785.dumps` output for
    /// `wirelang/tests/fixtures/persona_definitions/v9-persona-framework-native.md`
    /// on 2026-05-07T11:59 UTC.
    fn v9_canonical_subset() -> Value {
        json!({
            "description": "Pre-framework persona fixture for self-migration vector (v8, schema persona-v0-ish \u{2014} flagged as unsupported).",
            "identity_pinned": {
                "authority": {
                    "budget_cap_eur_per_month": 0,
                    "push_remote": false,
                    "sub_delegation": false
                },
                "cross_review_zones": [],
                "hierarchy": {
                    "escalation": "cto",
                    "reports_to": "cto"
                }
            },
            "name": "pre-framework-agent",
            "schema_version": "persona-v1",
            "tools": ["Read"]
        })
    }

    /// V9 ground-truth pin (lifted from `pin_pack_constants.py`,
    /// `PERSONA_HASH_PIN_V9`, captured 2026-05-07).
    const V9_PIN: &str = "sha256:0f298894204e6117e42ad7073b7a3af8ada1851de74d585fc5cb4c4d70e1d793";

    /// V9 JCS canonical bytes (UTF-8) — captured from Python
    /// `rfc8785.dumps(canon)` on 2026-05-07T11:59 UTC. 387 bytes.
    const V9_JCS_BYTES_LEN: usize = 387;

    #[test]
    fn t1_v9_hash_matches_python_pin_byte_for_byte() {
        let canon = v9_canonical_subset();
        let got = compute_persona_hash_from_canonical(&canon, None)
            .expect("v9 canonical subset must hash");
        assert_eq!(got, V9_PIN, "Rust digest must equal Python V9 pin");
    }

    #[test]
    fn t2_v9_jcs_bytes_length_matches_python() {
        let canon = v9_canonical_subset();
        let bytes = jcs_canonicalise(&canon).expect("v9 must canonicalise");
        assert_eq!(
            bytes.len(),
            V9_JCS_BYTES_LEN,
            "JCS byte length must match Python rfc8785 output"
        );
    }

    #[test]
    fn t3_expect_pin_full_form_passes_then_drift_detected() {
        let canon = v9_canonical_subset();
        // Full form passes.
        compute_persona_hash_from_canonical(&canon, Some(V9_PIN))
            .expect("full-form pin match must succeed");

        // Bare hex form passes (Python tolerates both).
        let bare_hex = &V9_PIN[PERSONA_HASH_PREFIX.len()..];
        compute_persona_hash_from_canonical(&canon, Some(bare_hex))
            .expect("bare-hex pin match must succeed");

        // Drift -> Mismatch.
        let bad = "sha256:dead000000000000000000000000000000000000000000000000000000000000";
        let err =
            compute_persona_hash_from_canonical(&canon, Some(bad)).expect_err("drift must error");
        match err {
            PersonaHashError::Mismatch { expected, computed } => {
                assert_eq!(expected, bad);
                assert_eq!(computed, V9_PIN);
            }
            other => panic!("expected Mismatch, got {other:?}"),
        }
    }

    #[test]
    fn t4_non_object_input_rejected() {
        let array = json!([1, 2, 3]);
        let err =
            compute_persona_hash_from_canonical(&array, None).expect_err("array input must error");
        assert!(matches!(err, PersonaHashError::NotAnObject));

        let scalar = json!("just-a-string");
        let err2 = compute_persona_hash_from_canonical(&scalar, None)
            .expect_err("string input must error");
        assert!(matches!(err2, PersonaHashError::NotAnObject));
    }

    #[test]
    fn t5_jcs_is_key_order_invariant_for_v9() {
        // Build the same canonical subset with keys inserted in the
        // OPPOSITE order. JCS must produce the same bytes -> the same
        // hash. This guards against a serde_json `preserve_order`
        // behavioural surprise.
        let canon_reordered = json!({
            "tools": ["Read"],
            "schema_version": "persona-v1",
            "name": "pre-framework-agent",
            "identity_pinned": {
                "hierarchy": {
                    "reports_to": "cto",
                    "escalation": "cto"
                },
                "cross_review_zones": [],
                "authority": {
                    "sub_delegation": false,
                    "push_remote": false,
                    "budget_cap_eur_per_month": 0
                }
            },
            "description": "Pre-framework persona fixture for self-migration vector (v8, schema persona-v0-ish \u{2014} flagged as unsupported)."
        });

        let h1 = compute_persona_hash_from_canonical(&v9_canonical_subset(), None)
            .expect("forward order must hash");
        let h2 = compute_persona_hash_from_canonical(&canon_reordered, None)
            .expect("reverse order must hash");
        assert_eq!(
            h1, h2,
            "JCS canonicalisation must be insertion-order invariant"
        );
        assert_eq!(h1, V9_PIN);
    }

    // -------------------------------------------------------------------
    // Sprint-5 Tag-3 Pin-Pack-Test-Coverage extension
    // (Sprint-4-Closeout §539-541 Selin-recommendation).
    //
    // Adds:
    //   - V8 canonical-subset (schema_version=persona-v0) hash-stability
    //   - V0/V8 -> V1 schema-flip roundtrip anchor (V8 -> V9 pin equality)
    //   - V9 -> V2 schema-flip roundtrip anchor (V9-migrated-to-V2 pin)
    //   - Determinism stress: 10-iteration byte-identical re-hash sweep
    //   - Re-derivation roundtrip: sha256(jcs_canonicalise(canon)) parity
    //
    // V8 fixture has no own hex pin (it is the REJECTED schema-v0 input
    // that must be migrated). The roundtrip tests therefore anchor the
    // V8-as-input -> V1/V2-as-output identity: byte-identical to the
    // V9 / V9-migrated-to-V2 pins respectively. This catches a future
    // regression where the canonical-subset extractor or the JCS
    // serialiser silently drops/reorders the schema_version key.
    // -------------------------------------------------------------------

    /// V8 canonical subset (schema_version=persona-v0). Identical to
    /// `v9_canonical_subset()` except for `schema_version`. Mirrors the
    /// V8 fixture in `persona-migration/src/lib.rs` tests.
    fn v8_canonical_subset() -> Value {
        json!({
            "description": "Pre-framework persona fixture for self-migration vector (v8, schema persona-v0-ish \u{2014} flagged as unsupported).",
            "identity_pinned": {
                "authority": {
                    "budget_cap_eur_per_month": 0,
                    "push_remote": false,
                    "sub_delegation": false
                },
                "cross_review_zones": [],
                "hierarchy": {
                    "escalation": "cto",
                    "reports_to": "cto"
                }
            },
            "name": "pre-framework-agent",
            "schema_version": "persona-v0",
            "tools": ["Read"]
        })
    }

    /// V9 canonical subset migrated to V2 (schema_version=persona-v2).
    /// Mirrors the Python `V1ToV2Step.apply(v9)` output.
    fn v9_migrated_to_v2_canonical_subset() -> Value {
        json!({
            "description": "Pre-framework persona fixture for self-migration vector (v8, schema persona-v0-ish \u{2014} flagged as unsupported).",
            "identity_pinned": {
                "authority": {
                    "budget_cap_eur_per_month": 0,
                    "push_remote": false,
                    "sub_delegation": false
                },
                "cross_review_zones": [],
                "hierarchy": {
                    "escalation": "cto",
                    "reports_to": "cto"
                }
            },
            "name": "pre-framework-agent",
            "schema_version": "persona-v2",
            "tools": ["Read"]
        })
    }

    /// V9-migrated-to-V2 pin from Python `pin_pack_constants.py`,
    /// `PERSONA_HASH_PIN_V9_MIGRATED_TO_V2`. Captured 2026-05-11.
    const V9_MIGRATED_TO_V2_PIN: &str =
        "sha256:f719fce4bedd8522874ae214ec2f982ef87964b535ca368134b3636207eb6669";

    // -------------------------------------------------------------------
    // 6 / V8 canonical-subset hashes deterministically. V8 has no
    //     frozen hex pin (it is the REJECTED self-migration input);
    //     anchor here is hash-stability + non-equality to V9 (because
    //     `schema_version` IS in-hash).
    // -------------------------------------------------------------------

    #[test]
    fn t6_v8_canonical_subset_hashes_deterministically_and_differs_from_v9() {
        let v8 = v8_canonical_subset();
        let h_v8_first =
            compute_persona_hash_from_canonical(&v8, None).expect("v8 canonical subset must hash");
        let h_v8_second = compute_persona_hash_from_canonical(&v8, None)
            .expect("v8 canonical subset must hash on second call");
        assert_eq!(
            h_v8_first, h_v8_second,
            "V8 hash must be deterministic across repeated calls"
        );
        assert_ne!(
            h_v8_first, V9_PIN,
            "V8 hash MUST differ from V9 hash (schema_version is in-hash)"
        );
        // Sanity: V8 hash must still be a well-formed full-form pin.
        assert!(h_v8_first.starts_with(PERSONA_HASH_PREFIX));
        assert_eq!(h_v8_first.len(), PERSONA_HASH_FULL_LENGTH);
    }

    // -------------------------------------------------------------------
    // 7 / V0/V8 -> V1 roundtrip anchor. The V8 canonical-subset with
    //     `schema_version` flipped from persona-v0 to persona-v1 must
    //     hash to PERSONA_HASH_PIN_V9 (= PERSONA_HASH_PIN_V8_MIGRATED_TO_V1
    //     by construction). This is the cross-language anchor for the
    //     V0ToV1Step migration's hash semantics, exercised here
    //     standalone in the persona-hash crate without depending on
    //     persona-migration.
    // -------------------------------------------------------------------

    #[test]
    fn t7_v8_with_v1_schema_flip_matches_v9_pin() {
        let mut v8_to_v1 = v8_canonical_subset();
        v8_to_v1["schema_version"] = json!("persona-v1");
        let got = compute_persona_hash_from_canonical(&v8_to_v1, None)
            .expect("v8-migrated-to-v1 canonical subset must hash");
        assert_eq!(
            got, V9_PIN,
            "V8 + schema_version=persona-v1 must hash to V9 pin (V8_MIGRATED_TO_V1 anchor)"
        );
    }

    // -------------------------------------------------------------------
    // 8 / V9 -> V2 roundtrip anchor. V9 canonical-subset with
    //     schema_version flipped to persona-v2 must hash to
    //     PERSONA_HASH_PIN_V9_MIGRATED_TO_V2. Cross-language anchor
    //     for the V1ToV2Step migration's hash semantics.
    // -------------------------------------------------------------------

    #[test]
    fn t8_v9_with_v2_schema_flip_matches_v9_migrated_to_v2_pin() {
        let v9_to_v2 = v9_migrated_to_v2_canonical_subset();
        let got = compute_persona_hash_from_canonical(&v9_to_v2, None)
            .expect("v9-migrated-to-v2 canonical subset must hash");
        assert_eq!(
            got, V9_MIGRATED_TO_V2_PIN,
            "V9 + schema_version=persona-v2 must hash to V9_MIGRATED_TO_V2 pin"
        );
        assert_ne!(
            got, V9_PIN,
            "V9 -> V2 migrated pin must DIFFER from V9 pin (schema_version is in-hash)"
        );
    }

    // -------------------------------------------------------------------
    // 9 / Determinism stress: 10-iteration byte-identical re-hash
    //     sweep across V8, V9, V9->V2 subsets. Guards against any
    //     hidden non-determinism in serde_jcs / serde_json / sha2 stack
    //     (e.g. HashMap-iteration leakage, accidental random padding,
    //     allocator-order-dependent canonicalisation).
    // -------------------------------------------------------------------

    #[test]
    #[allow(clippy::type_complexity)]
    fn t9_determinism_stress_10_iterations_byte_identical() {
        // Build each subset fresh on each iteration to also cover
        // parser-construction determinism (not just intra-call stability).
        let fixtures: [(&str, fn() -> Value, Option<&str>); 3] = [
            ("v8", v8_canonical_subset, None),
            ("v9", v9_canonical_subset, Some(V9_PIN)),
            (
                "v9_to_v2",
                v9_migrated_to_v2_canonical_subset,
                Some(V9_MIGRATED_TO_V2_PIN),
            ),
        ];

        for (label, builder, expected_pin) in fixtures {
            let mut seen: Vec<String> = Vec::with_capacity(10);
            for i in 0..10 {
                let canon = builder();
                let h = compute_persona_hash_from_canonical(&canon, None)
                    .unwrap_or_else(|e| panic!("{label} iter {i} hash failed: {e}"));
                seen.push(h);
            }
            // All 10 iterations must produce byte-identical hash strings.
            for (i, h) in seen.iter().enumerate().skip(1) {
                assert_eq!(
                    &seen[0], h,
                    "{label} iter {i} drifted from iter 0 (non-deterministic hash)"
                );
            }
            if let Some(pin) = expected_pin {
                assert_eq!(
                    seen[0], pin,
                    "{label} iter-0 hash must match pinned reference"
                );
            }
        }
    }

    // -------------------------------------------------------------------
    // 10 / Roundtrip: hash -> jcs_canonicalise -> sha256 (re-derive) must
    //      reproduce the same hash tail. This is the bytes <-> hash
    //      bijection anchor: it locks the contract that
    //      `compute_persona_hash_from_canonical` is exactly
    //      `format!("sha256:{}", hex(sha256(jcs_canonicalise(canon))))`
    //      with no hidden post-processing. Mirrors Python
    //      `canonical_jcs_bytes` -> hashlib.sha256 roundtrip.
    // -------------------------------------------------------------------

    #[test]
    fn t10_hash_equals_sha256_of_jcs_canonicalise_roundtrip() {
        for (label, builder, expected_pin) in [
            ("v8", v8_canonical_subset as fn() -> Value, None),
            ("v9", v9_canonical_subset as fn() -> Value, Some(V9_PIN)),
            (
                "v9_to_v2",
                v9_migrated_to_v2_canonical_subset as fn() -> Value,
                Some(V9_MIGRATED_TO_V2_PIN),
            ),
        ] {
            let canon = builder();
            let bytes = jcs_canonicalise(&canon)
                .unwrap_or_else(|e| panic!("{label} jcs_canonicalise failed: {e}"));
            let mut hasher = Sha256::new();
            hasher.update(&bytes);
            let digest = hasher.finalize();
            let re_derived = format!("{}{}", PERSONA_HASH_PREFIX, hex::encode(digest));
            let via_api = compute_persona_hash_from_canonical(&canon, None)
                .unwrap_or_else(|e| panic!("{label} api-hash failed: {e}"));
            assert_eq!(
                via_api, re_derived,
                "{label}: api hash must equal sha256(jcs_canonicalise(canon)) re-derivation"
            );
            if let Some(pin) = expected_pin {
                assert_eq!(via_api, pin, "{label}: re-derived hash must match pin");
            }
        }
    }
}
