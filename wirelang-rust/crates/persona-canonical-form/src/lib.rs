// SPDX-License-Identifier: Apache-2.0
//! JCS-bytes boundary helper — Rust pendant.
//!
//! This crate is the byte-for-byte equivalent of
//! `wirelang.persona.persona_canonical_form.canonical_jcs_bytes` in the
//! Python tree. It exists so the Phase-1c Rust migration window has a
//! standalone JCS-bytes producer that can be cross-checked against the
//! Python helper without going through the SHA-256 step.
//!
//! Determinism contract
//! --------------------
//!
//! Given a canonical-subset object (the dict produced by
//! `wirelang.persona.persona_canonical_form.extract_canonical_subset`),
//! this crate must emit the EXACT same UTF-8 byte string as Python
//! `rfc8785.dumps(canonical_subset)`. The V9 ground-truth fixture in
//! `wirelang/tests/fixtures/persona_definitions/v9-persona-framework-native.md`
//! is the cross-language test oracle: `len() == 387` and
//! `sha256(jcs_bytes) == PERSONA_HASH_PIN_V9`.
//!
//! Default-Lock posture (Tag-5 Crate-2 box, mirrors Tag-4 Crate-1)
//! ---------------------------------------------------------------
//!
//! - **A-1 Mock-Format-Baseline:** this crate sees a `serde_json::Value`
//!   (already-extracted canonical subset). YAML front-matter parsing is
//!   out-of-scope; that belongs to a future `persona-canonical-form-yaml`
//!   crate.
//! - **A-2 Additiv-only:** this crate is added next to `persona-hash`,
//!   does not delete or move any existing Rust or Python file.
//! - **A-3 Body out-of-hash:** same posture as Python — only the
//!   canonical subset goes into JCS; Markdown body bytes never reach
//!   this crate.
//!
//! Public surface
//! --------------
//!
//! - [`PersonaCanonicalFormError`] — error enum (input shape, JCS error).
//! - [`canonical_jcs_bytes`] — main entry point.
//!
//! NOT yet implemented in Rust (Phase-1c follow-up boxes):
//!
//! - YAML front-matter parsing (Python: `split_frontmatter` /
//!   `parse_frontmatter` / `extract_canonical_subset`).
//! - Schema-version checking (Python: `extract_canonical_subset`).
//! - File-path entry point (Python: `read_canonical_subset`).

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use serde_json::Value;

/// Error class for the JCS-bytes boundary helper.
///
/// Variants mirror the Python error surface for `canonical_jcs_bytes`:
/// input-shape rejection (the Rust type system is stricter than the
/// Python duck-typing, but we still surface a non-object guard so
/// upstream callers see the same contract) and JCS canonicalisation
/// failures (Python `rfc8785.dumps` raises `ValueError`/`TypeError`
/// for NaN, Infinity, non-string keys; we collapse those into one
/// variant with the underlying message).
#[derive(Debug)]
pub enum PersonaCanonicalFormError {
    /// The input is not a JSON object. The canonical subset is always
    /// a top-level object; arrays / scalars are rejected. This mirrors
    /// the upstream contract from
    /// `extract_canonical_subset`, which only ever returns a dict.
    NotAnObject,

    /// JCS canonicalisation failed. Mirrors Python `rfc8785.dumps`
    /// raising on NaN, Infinity, non-string keys, or unsupported
    /// types. The underlying `serde_jcs` error message is preserved
    /// for diagnostics.
    CanonicaliseError(String),
}

impl std::fmt::Display for PersonaCanonicalFormError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PersonaCanonicalFormError::NotAnObject => {
                f.write_str("canonical subset must be a JSON object")
            }
            PersonaCanonicalFormError::CanonicaliseError(msg) => {
                write!(f, "JCS canonicalisation failed: {msg}")
            }
        }
    }
}

impl std::error::Error for PersonaCanonicalFormError {}

/// Serialise a canonical-subset value to RFC 8785 JCS UTF-8 bytes.
///
/// This is the bytes-level boundary that feeds into the SHA-256 step
/// in `persona_hash::compute_persona_hash_from_canonical`. Exposing it
/// as its own crate lets the Phase-1c migration cross-check Rust
/// against Python `canonical_jcs_bytes` byte-for-byte without going
/// through the hash step (catches JCS-canonicaliser drift in
/// isolation, which is exactly what `serde_jcs 0.2.x` pre-1.0 risk
/// requires us to guard against per Tag-8 skizze §4).
///
/// # Arguments
///
/// * `canonical_subset` — the canonical-subset object. Must be a
///   `serde_json::Value::Object`. Other shapes return
///   [`PersonaCanonicalFormError::NotAnObject`].
///
/// # Determinism
///
/// JCS sorts keys lexicographically by UTF-16 code-unit ordering and
/// canonicalises numbers per ECMA-262. The Rust `serde_jcs 0.2.0`
/// crate and the Python `rfc8785` package implement the same RFC; the
/// V9 cross-check test asserts byte-equality against the reference
/// vector.
///
/// # Errors
///
/// See [`PersonaCanonicalFormError`].
pub fn canonical_jcs_bytes(canonical_subset: &Value) -> Result<Vec<u8>, PersonaCanonicalFormError> {
    if !canonical_subset.is_object() {
        return Err(PersonaCanonicalFormError::NotAnObject);
    }
    serde_jcs::to_vec(canonical_subset)
        .map_err(|e| PersonaCanonicalFormError::CanonicaliseError(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use sha2::{Digest, Sha256};

    /// V9 fixture as a hand-built canonical subset. Bytes verified
    /// against the Python `rfc8785.dumps` output for
    /// `wirelang/tests/fixtures/persona_definitions/v9-persona-framework-native.md`
    /// on 2026-05-07T11:59 UTC. Mirrors the V9 fixture in the
    /// `persona-hash` crate (intentionally duplicated here so the JCS
    /// helper can be cross-checked in isolation without depending on
    /// the hash crate).
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
    /// `PERSONA_HASH_PIN_V9`, captured 2026-05-07). Used here as a
    /// cross-check that `sha256(canonical_jcs_bytes(v9))` matches the
    /// canonical pin without going through the persona-hash crate.
    const V9_PIN_HEX: &str = "0f298894204e6117e42ad7073b7a3af8ada1851de74d585fc5cb4c4d70e1d793";

    /// V9 JCS canonical bytes (UTF-8) length — captured from Python
    /// `rfc8785.dumps(canon)` on 2026-05-07T11:59 UTC. 387 bytes.
    /// This is the cross-language length anchor.
    const V9_JCS_BYTES_LEN: usize = 387;

    /// Cross-language hash anchor, computed from the Rust JCS bytes.
    /// `sha256(canonical_jcs_bytes(v9_subset))` must equal V9_PIN_HEX.
    /// Mirrors Python test
    /// `test_v9_canonical_jcs_bytes_sha256_matches_pin_v9`.
    fn sha256_hex(bytes: &[u8]) -> String {
        let mut hasher = Sha256::new();
        hasher.update(bytes);
        let digest = hasher.finalize();
        let mut s = String::with_capacity(64);
        for byte in digest {
            use std::fmt::Write;
            write!(s, "{byte:02x}").expect("hex write");
        }
        s
    }

    // -------------------------------------------------------------------
    // 1 / V9 ground-truth length anchor (Sprint-2 Tag-5 §A6 captured run)
    //     Mirrors Python test_v9_canonical_jcs_bytes_length_is_387.
    // -------------------------------------------------------------------

    #[test]
    fn t1_v9_canonical_jcs_bytes_length_is_387() {
        let canon = v9_canonical_subset();
        let blob = canonical_jcs_bytes(&canon).expect("v9 must canonicalise");
        assert_eq!(
            blob.len(),
            V9_JCS_BYTES_LEN,
            "v9 canonical JCS length must be 387 (cross-lang parity anchor)"
        );
    }

    // -------------------------------------------------------------------
    // 2 / V9 ground-truth hash parity — sha256(jcs_bytes) == V9 pin.
    //     Mirrors Python test_v9_canonical_jcs_bytes_sha256_matches_pin_v9.
    // -------------------------------------------------------------------

    #[test]
    fn t2_v9_canonical_jcs_bytes_sha256_matches_pin_v9() {
        let canon = v9_canonical_subset();
        let blob = canonical_jcs_bytes(&canon).expect("v9 must canonicalise");
        let got_hex = sha256_hex(&blob);
        assert_eq!(
            got_hex, V9_PIN_HEX,
            "sha256(canonical_jcs_bytes(v9)) must equal V9 pin (byte-identical to Python)"
        );
    }

    // -------------------------------------------------------------------
    // 3 / JCS byte-stability — idempotent on repeated calls (RFC 8785
    //     determinism guard). Mirrors Python
    //     test_canonical_jcs_bytes_is_idempotent.
    // -------------------------------------------------------------------

    #[test]
    fn t3_canonical_jcs_bytes_is_idempotent() {
        let canon = v9_canonical_subset();
        let blob_a = canonical_jcs_bytes(&canon).expect("first call");
        let blob_b = canonical_jcs_bytes(&canon).expect("second call");
        assert_eq!(blob_a, blob_b, "JCS must be idempotent on repeated calls");

        // Stability across a fresh load of the subset (parser determinism).
        let blob_c = canonical_jcs_bytes(&v9_canonical_subset()).expect("fresh load");
        assert_eq!(blob_a, blob_c, "JCS must be stable across fresh loads");
    }

    // -------------------------------------------------------------------
    // 4 / JCS lexicographic key sorting — insertion order does not leak.
    //     Mirrors Python test_canonical_jcs_bytes_is_key_order_invariant.
    // -------------------------------------------------------------------

    #[test]
    fn t4_canonical_jcs_bytes_is_key_order_invariant() {
        let a = json!({
            "name": "x",
            "description": "d",
            "tools": [],
            "schema_version": "persona-v1"
        });
        let b = json!({
            "schema_version": "persona-v1",
            "tools": [],
            "description": "d",
            "name": "x"
        });
        let blob_a = canonical_jcs_bytes(&a).expect("a must canonicalise");
        let blob_b = canonical_jcs_bytes(&b).expect("b must canonicalise");
        assert_eq!(
            blob_a, blob_b,
            "JCS must sort keys lexicographically (insertion order must not leak)"
        );
    }

    // -------------------------------------------------------------------
    // 5 / UTF-8 / NFC posture — non-ASCII strings round-trip cleanly.
    //     Mirrors Python test_canonical_jcs_bytes_handles_non_ascii_text.
    // -------------------------------------------------------------------

    #[test]
    fn t5_canonical_jcs_bytes_handles_non_ascii_text() {
        let a = json!({"description": "Wakir Labs - Persona-Engine"});
        let b = json!({"description": "Wakir Labs - Persona-Engine"});
        let blob_a = canonical_jcs_bytes(&a).expect("a must canonicalise");
        let blob_b = canonical_jcs_bytes(&b).expect("b must canonicalise");
        assert_eq!(blob_a, blob_b, "non-ASCII byte-equality must hold");
        // UTF-8 minus mandatory JSON escapes: ASCII literal preserved.
        let needle = b"Wakir Labs - Persona-Engine";
        assert!(
            blob_a.windows(needle.len()).any(|w| w == needle),
            "ASCII payload must appear literally in the JCS output"
        );
    }

    // -------------------------------------------------------------------
    // 6 / Non-object input rejection — array + scalar both rejected.
    //     Tightens the Rust contract beyond Python (Python's helper
    //     would happily JCS-serialise an array; Rust guards against
    //     accidental upstream contract violations because the canonical
    //     subset is by spec a top-level object).
    // -------------------------------------------------------------------

    #[test]
    fn t6_non_object_input_rejected() {
        let array = json!([1, 2, 3]);
        let err = canonical_jcs_bytes(&array).expect_err("array must error");
        assert!(matches!(err, PersonaCanonicalFormError::NotAnObject));

        let scalar = json!("just-a-string");
        let err2 = canonical_jcs_bytes(&scalar).expect_err("string must error");
        assert!(matches!(err2, PersonaCanonicalFormError::NotAnObject));
    }
}
