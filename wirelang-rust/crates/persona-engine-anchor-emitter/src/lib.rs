// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Persona-engine anchor-envelope emitter — Rust pendant.
//
// Schema-parity authority: `envelope_jcs_bytes` /
// `envelope_payload_hash` in
// `wirelang/persona/recovery_drill_anchor.py` (Selin / Reza
// Sprint-Pengine-7 Tag-5 OI-PILOT-4 + OI-PEF-11). Downstream
// consumer: `wat.anchor.bridge_audit_writer.write_bridge_audit`
// (Tomás / WAT-team) — that boundary keys on the SHA-256 of the
// JCS-canonical bytes that this crate emits.
//
// Design notes
// ------------
// - `AnchorEnvelope` carries the four Sprint-Auftrag fields
//   (`event_id`, `timestamp_utc`, `persona_id`, `payload_jcs_bytes`).
//   The first three are RFC-3339-shaped strings / opaque IDs; the
//   fourth is the already-canonicalised payload byte string. This
//   shape lets a caller pass in a payload that was canonicalised
//   anywhere — by the Python sibling, by an upstream Rust crate,
//   or by an out-of-process JCS canonicaliser — without
//   re-canonicalising and risking drift.
// - `serialize_anchor` produces the **outer** envelope JCS bytes.
//   The inner `payload_jcs_bytes` is embedded as a JSON string
//   carrying the lower-case hex of its SHA-256. This avoids two
//   embedding traps:
//     (a) embedding raw payload bytes inside JSON would force
//         base64 + a second canonicalisation pass and split the
//         hash domain between Python and Rust;
//     (b) embedding the payload as a JSON value would re-open the
//         "what is the JCS-canonical form of *this* tree?" question
//         that the caller already answered.
//   The Python helper hashes the dict-form of the envelope; the
//   Rust pendant hashes the envelope-shape that this crate emits.
//   The cross-lang smoke test pins the Rust output bytes and the
//   Python-side equivalent shape so any drift on either side is
//   caught.
// - `hash_anchor` returns the string `"sha256:<lower-case-64-hex>"`
//   per Sprint-Auftrag. The hash domain is the outer envelope JCS
//   bytes; the cross-lang smoke test also pins the bare-hex form
//   so consumers that compare against the Python
//   `envelope_payload_hash` (which returns bare hex) can do so
//   without prefix stripping on the test side.
// - No clock; the timestamp is a caller-supplied input. The
//   emitter is a pure function. Determinism is a smoke-test
//   invariant.

#![forbid(unsafe_code)]
#![warn(missing_docs)]
#![warn(missing_debug_implementations)]

//! Persona-engine anchor-envelope emitter — Rust pendant.
//!
//! See the crate-level Cargo.toml comment for schema-parity table
//! and ADR anchors. Public surface: [`AnchorEnvelope`],
//! [`AnchorEmitterInput`], [`build_anchor_envelope`],
//! [`serialize_anchor`], [`hash_anchor`], [`AnchorEmitterError`].

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fmt;

// ---------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------

/// Schema-version tag embedded in every emitted envelope. Bumped on
/// any wire-shape change; consumers MUST reject unknown values.
pub const ENVELOPE_SCHEMA: &str = "wakir.wat.anchor-envelope/1";

/// Hex-string length of a SHA-256 digest (lower-case, no prefix).
pub const SHA256_HEX_LEN: usize = 64;

/// Prefix prepended to the SHA-256 hex tail by [`hash_anchor`].
pub const HASH_PREFIX: &str = "sha256:";

// ---------------------------------------------------------------------
// Errors.
// ---------------------------------------------------------------------

/// Error surface for [`build_anchor_envelope`] and [`serialize_anchor`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AnchorEmitterError {
    /// A required field was empty (whitespace-only counts as empty
    /// for the three string fields). The variant carries the field
    /// name for audit diagnostics.
    EmptyField(&'static str),
    /// The supplied `timestamp_utc` does not match the RFC-3339
    /// second-precision UTC shape `YYYY-MM-DDTHH:MM:SSZ`. The
    /// emitter does not parse calendar dates; it only verifies the
    /// surface so downstream tooling can rely on lexical sort
    /// equalling chronological sort.
    BadTimestampShape(String),
    /// Internal JCS canonicalisation failure. Should not happen for
    /// the shapes this crate emits; surfaced for forward
    /// compatibility.
    JcsFailure(String),
}

impl fmt::Display for AnchorEmitterError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AnchorEmitterError::EmptyField(name) => {
                write!(f, "anchor-envelope field {:?} must be non-empty", name)
            }
            AnchorEmitterError::BadTimestampShape(s) => write!(
                f,
                "anchor-envelope timestamp_utc {:?} is not in RFC-3339 \
                 second-precision UTC shape (YYYY-MM-DDTHH:MM:SSZ)",
                s
            ),
            AnchorEmitterError::JcsFailure(s) => {
                write!(f, "anchor-envelope JCS canonicalisation failed: {}", s)
            }
        }
    }
}

impl std::error::Error for AnchorEmitterError {}

// ---------------------------------------------------------------------
// Input record.
// ---------------------------------------------------------------------

/// Caller-supplied input to [`build_anchor_envelope`]. Mirrors the
/// four Sprint-Auftrag fields verbatim.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnchorEmitterInput {
    /// Unique identifier of the event being anchored. Caller-owned;
    /// no shape enforcement beyond non-emptiness.
    pub event_id: String,
    /// RFC-3339 second-precision UTC timestamp of the event
    /// (`YYYY-MM-DDTHH:MM:SSZ`). The emitter does not parse the date
    /// but does enforce the surface shape so lexical sort matches
    /// chronological sort.
    pub timestamp_utc: String,
    /// Persona identifier the event is attributed to. Caller-owned.
    pub persona_id: String,
    /// Already-canonicalised payload bytes. The caller is
    /// responsible for canonicalisation; this crate hashes these
    /// bytes verbatim and embeds the hex tail in the outer envelope.
    pub payload_jcs_bytes: Vec<u8>,
}

// ---------------------------------------------------------------------
// AnchorEnvelope — the emitter output.
// ---------------------------------------------------------------------

/// The emitter's output record. Carries the four input fields verbatim
/// and is the input to both [`serialize_anchor`] and [`hash_anchor`].
///
/// `payload_jcs_bytes` is kept as raw bytes on the Rust side but is
/// embedded in the canonical envelope as its SHA-256 hex tail (see
/// crate-level docs for rationale).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnchorEnvelope {
    /// Event identifier (mirrors [`AnchorEmitterInput::event_id`]).
    pub event_id: String,
    /// RFC-3339 second-precision UTC timestamp.
    pub timestamp_utc: String,
    /// Persona identifier.
    pub persona_id: String,
    /// Caller-supplied canonical payload bytes.
    pub payload_jcs_bytes: Vec<u8>,
}

/// Serde-facing view of [`AnchorEnvelope`] in the shape that goes on
/// the wire. The `payload_sha256` field carries the lower-case hex
/// tail of `SHA-256(payload_jcs_bytes)`; the raw payload bytes are
/// not embedded (see crate-level docs).
///
/// Field order in this struct matches the lexical order of the JSON
/// keys after JCS canonicalisation; that order is also the one the
/// cross-lang smoke test pins.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct WireEnvelope {
    /// Event identifier.
    pub event_id: String,
    /// SHA-256 hex tail of the caller-supplied canonical payload.
    pub payload_sha256: String,
    /// Persona identifier.
    pub persona_id: String,
    /// Schema-version tag (constant [`ENVELOPE_SCHEMA`]).
    pub schema: String,
    /// RFC-3339 second-precision UTC timestamp.
    pub timestamp_utc: String,
}

impl AnchorEnvelope {
    /// Build the wire-shape view of this envelope. Pure function; no
    /// I/O. Used internally by [`serialize_anchor`] and exposed to
    /// the cross-lang smoke test so the embedded `payload_sha256`
    /// can be cross-checked against the bare-hex Python form.
    fn to_wire(&self) -> WireEnvelope {
        let payload_sha = sha256_hex(&self.payload_jcs_bytes);
        WireEnvelope {
            event_id: self.event_id.clone(),
            payload_sha256: payload_sha,
            persona_id: self.persona_id.clone(),
            schema: ENVELOPE_SCHEMA.to_string(),
            timestamp_utc: self.timestamp_utc.clone(),
        }
    }
}

// ---------------------------------------------------------------------
// Hash primitive.
// ---------------------------------------------------------------------

/// Lower-case hex tail of `SHA-256(bytes)`. Matches the Python
/// `hashlib.sha256(...).hexdigest()` shape that the cross-lang test
/// pins against.
pub fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    let digest = hasher.finalize();
    hex::encode(digest)
}

// ---------------------------------------------------------------------
// Timestamp surface check.
// ---------------------------------------------------------------------

/// Return `true` iff `s` matches the RFC-3339 second-precision UTC
/// shape `YYYY-MM-DDTHH:MM:SSZ`. Surface check only; does not
/// validate that the calendar date is real. Used by
/// [`build_anchor_envelope`] to fail fast on caller-side typos.
fn is_rfc3339_second_utc(s: &str) -> bool {
    // Shape: 20 ASCII chars, fixed punctuation at indices 4 / 7 / 10
    // / 13 / 16 / 19. ASCII digits everywhere else. Matches the
    // Python `_utc_now_rfc3339` output and the WAT spool-time pin.
    let bytes = s.as_bytes();
    if bytes.len() != 20 {
        return false;
    }
    for (i, b) in bytes.iter().enumerate() {
        let ok = match i {
            4 | 7 => *b == b'-',
            10 => *b == b'T',
            13 | 16 => *b == b':',
            19 => *b == b'Z',
            _ => b.is_ascii_digit(),
        };
        if !ok {
            return false;
        }
    }
    true
}

// ---------------------------------------------------------------------
// Public builder.
// ---------------------------------------------------------------------

/// Build an [`AnchorEnvelope`] from caller-supplied input. Mirrors the
/// Python `envelope_jcs_bytes` precondition: every string field
/// non-empty (trimmed), timestamp shape pinned. Pure function.
pub fn build_anchor_envelope(
    input: AnchorEmitterInput,
) -> Result<AnchorEnvelope, AnchorEmitterError> {
    if input.event_id.trim().is_empty() {
        return Err(AnchorEmitterError::EmptyField("event_id"));
    }
    if input.persona_id.trim().is_empty() {
        return Err(AnchorEmitterError::EmptyField("persona_id"));
    }
    if input.timestamp_utc.trim().is_empty() {
        return Err(AnchorEmitterError::EmptyField("timestamp_utc"));
    }
    if !is_rfc3339_second_utc(&input.timestamp_utc) {
        return Err(AnchorEmitterError::BadTimestampShape(input.timestamp_utc));
    }
    // Empty payload IS legal (anchoring a "this event happened, no
    // payload of consequence" marker); the Python sibling allows it
    // too (an empty dict canonicalises to "{}"). Sha256 of an empty
    // byte slice is the well-known constant
    // e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855.
    Ok(AnchorEnvelope {
        event_id: input.event_id,
        timestamp_utc: input.timestamp_utc,
        persona_id: input.persona_id,
        payload_jcs_bytes: input.payload_jcs_bytes,
    })
}

// ---------------------------------------------------------------------
// Serialisation + hashing.
// ---------------------------------------------------------------------

/// Serialise an [`AnchorEnvelope`] to RFC 8785 JCS-canonical bytes.
/// The output is deterministic for a given semantic envelope; the
/// cross-lang smoke test pins the byte sequence against a fixture.
pub fn serialize_anchor(env: &AnchorEnvelope) -> Vec<u8> {
    let wire = env.to_wire();
    // serde_jcs::to_vec returns canonical bytes per RFC 8785. The
    // only failure mode is a serialisation error in serde itself,
    // which cannot happen for our flat WireEnvelope (all owned
    // strings, no custom serialisers). We unwrap with a defensive
    // panic in case future field-shape changes break that
    // assumption — the smoke tests would catch it first.
    serde_jcs::to_vec(&wire).expect(
        "WireEnvelope is a flat owned-string struct; \
         serde_jcs::to_vec cannot fail here",
    )
}

/// Compute the `"sha256:<hex>"` payload-hash string for an envelope.
/// Mirrors the Python `envelope_payload_hash` shape with the
/// Sprint-Auftrag-mandated `sha256:` prefix.
///
/// Implementation: SHA-256 of the [`serialize_anchor`] output. The
/// bare-hex form (matching Python) is available via the helper
/// [`sha256_hex`] over the same bytes.
pub fn hash_anchor(env: &AnchorEnvelope) -> String {
    let canonical = serialize_anchor(env);
    let mut out = String::with_capacity(HASH_PREFIX.len() + SHA256_HEX_LEN);
    out.push_str(HASH_PREFIX);
    out.push_str(&sha256_hex(&canonical));
    out
}

/// Convenience: return both the canonical bytes and the prefixed hash
/// in a single call. Saves a re-canonicalisation pass for callers
/// that need both (the WAT spool writer wants the bytes for the spool
/// file and the hash for the bridge-audit row).
pub fn serialize_and_hash(env: &AnchorEnvelope) -> (Vec<u8>, String) {
    let bytes = serialize_anchor(env);
    let hash = {
        let mut out = String::with_capacity(HASH_PREFIX.len() + SHA256_HEX_LEN);
        out.push_str(HASH_PREFIX);
        out.push_str(&sha256_hex(&bytes));
        out
    };
    (bytes, hash)
}

// ---------------------------------------------------------------------
// Cross-lang fixture exposure (consumed by tests/).
// ---------------------------------------------------------------------

/// Test-only helper: return the wire-shape JSON object for an
/// envelope as a `serde_json::Value`. Hidden from docs; the
/// cross-lang smoke test uses it to assert that the embedded
/// `payload_sha256` matches the bare-hex SHA-256 of the input
/// payload bytes.
#[doc(hidden)]
pub fn _test_only_wire_value(env: &AnchorEnvelope) -> serde_json::Value {
    serde_json::to_value(env.to_wire()).expect(
        "WireEnvelope serialises to a JSON object by construction; \
         to_value cannot fail",
    )
}

// ---------------------------------------------------------------------
// Spec-invariant self-check.
// ---------------------------------------------------------------------

/// Module-internal invariant check used by unit tests. Mirrors the
/// posture of the FSM crate's `assert_spec_invariants` guard.
///
/// - `ENVELOPE_SCHEMA` has the documented Wakir-namespace prefix.
/// - The hash-prefix and hex-length constants are mutually consistent.
pub fn assert_spec_invariants() -> Result<(), &'static str> {
    if !ENVELOPE_SCHEMA.starts_with("wakir.") {
        return Err("ENVELOPE_SCHEMA must live in the wakir.* namespace");
    }
    if !ENVELOPE_SCHEMA.contains("/1") {
        return Err("ENVELOPE_SCHEMA must carry an explicit /<version> tag");
    }
    if HASH_PREFIX != "sha256:" {
        return Err("HASH_PREFIX drifted from Sprint-Auftrag-pinned value");
    }
    if SHA256_HEX_LEN != 64 {
        return Err("SHA256_HEX_LEN must equal 64 (256 bits / 4)");
    }
    Ok(())
}

// ---------------------------------------------------------------------
// Library-internal smoke tests (module-import-time invariants).
// ---------------------------------------------------------------------

#[cfg(test)]
mod lib_tests {
    use super::*;

    #[test]
    fn spec_invariants_hold() {
        assert_spec_invariants().expect("spec invariants must hold at build time");
    }

    #[test]
    fn sha256_hex_of_empty_input_matches_well_known_constant() {
        // SHA-256("") = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        assert_eq!(
            sha256_hex(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        );
    }

    #[test]
    fn rfc3339_second_utc_surface_accepts_canonical_shape() {
        assert!(is_rfc3339_second_utc("2026-05-17T00:00:00Z"));
        assert!(is_rfc3339_second_utc("1970-01-01T00:00:00Z"));
    }

    #[test]
    fn rfc3339_second_utc_surface_rejects_drift() {
        assert!(!is_rfc3339_second_utc("2026-05-17T00:00:00"));
        assert!(!is_rfc3339_second_utc("2026-05-17 00:00:00Z"));
        assert!(!is_rfc3339_second_utc("2026-05-17T00:00:00.5Z"));
        assert!(!is_rfc3339_second_utc(""));
    }
}
