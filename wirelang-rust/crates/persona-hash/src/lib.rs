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
pub const PERSONA_HASH_FULL_LENGTH: usize =
    PERSONA_HASH_PREFIX.len() + PERSONA_HASH_HEX_LENGTH;

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
            PersonaHashError::NotAnObject => {
                f.write_str("canonical subset must be a JSON object")
            }
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
    const V9_PIN: &str =
        "sha256:0f298894204e6117e42ad7073b7a3af8ada1851de74d585fc5cb4c4d70e1d793";

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
        let err = compute_persona_hash_from_canonical(&canon, Some(bad))
            .expect_err("drift must error");
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
        let err = compute_persona_hash_from_canonical(&array, None)
            .expect_err("array input must error");
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
}
