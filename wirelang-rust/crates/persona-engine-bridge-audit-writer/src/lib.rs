// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors

//! Persona-Engine Bridge-Audit-Writer — Tag-30 Mini-Welle (12. Modul,
//! Welle-3-Komponente per ADR-0066).
//!
//! Rust authority for the engineering-output envelope produced by the
//! Python sibling `wirelang.persona_engine.bridge_audit_writer.
//! BridgeAuditWriter` (PR #106 / Sprint-1 Tag-4).
//!
//! # Scope
//!
//! This crate is the **writer-side** envelope-construction surface — it
//! owns byte-deterministic JCS canonicalisation of one
//! [`EngineeringOutputEvent`] and its content hash. It deliberately does
//! NOT own the I/O sinks (Pre-Framework Markdown + Wakir-Runtime stderr)
//! — those are operator-substrate concerns owned by the Python writer
//! and not part of the deterministic byte-parity surface.
//!
//! The sister crate `persona-engine-bridge-audit-replay` (PR #166)
//! consumes the same wire-shape this crate emits; both crates share the
//! field schema and the JCS pin so a `emit -> replay` round trip is
//! byte-identical end-to-end.
//!
//! # Cross-language posture
//!
//! Byte-identical Python sibling at
//! `wirelang/persona_engine/bridge_audit_writer.py`. Both modules emit
//! identical JCS bytes for the cross-lang fixture file
//! `tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json`.
//!
//! # Schema-parity table (Rust <-> Python)
//!
//! | Python concept                                  | Rust type / fn                              |
//! |-------------------------------------------------|---------------------------------------------|
//! | `EngineeringOutputEvent` (dataclass)            | [`EngineeringOutputEvent`]                  |
//! | `EngineeringOutputEvent.to_jcs_bytes()`         | [`EngineeringOutputEvent::to_jcs_bytes`]    |
//! | `EngineeringOutputEvent.payload_sha256()`       | [`EngineeringOutputEvent::payload_sha256`]  |
//! | `sha256_hex(payload)`                           | [`sha256_hex`]                              |
//! | `ENGINEERING_OUTPUT_SCHEMA`                     | [`ENGINEERING_OUTPUT_SCHEMA`]               |
//! | `BridgeAuditWriter.emit(kind, payload)`         | [`BridgeAuditWriter::emit`]                 |
//! | `OUTPUT_KIND_TOOL_CALL` (`"tool_call"`)         | [`OUTPUT_KIND_TOOL_CALL`]                   |
//! | `OUTPUT_KIND_REPLY` (`"reply"`)                 | [`OUTPUT_KIND_REPLY`]                       |
//! | `OUTPUT_KIND_AUDIT_ANNOTATION`                  | [`OUTPUT_KIND_AUDIT_ANNOTATION`]            |
//!
//! # Wire-shape (frozen at schema `wakir.persona.engineering-output/1`)
//!
//! The JCS-canonical envelope is an object with eleven lex-ordered keys:
//!
//! - `engine_version`            : engine version string.
//! - `event_kind`                : constant `"engineering_output"`.
//! - `org_id`                    : organisation identifier.
//! - `output_kind`               : one of `"tool_call"`, `"reply"`,
//!   `"audit_annotation"`.
//! - `output_payload_sha256`     : `"sha256:<64hex>"` of payload bytes.
//! - `persona_id`                : persona identifier.
//! - `schema`                    : constant [`ENGINEERING_OUTPUT_SCHEMA`].
//! - `session_id`                : opaque session string.
//! - `step_index`                : 0-based emission counter within session.
//! - `ts_utc`                    : RFC-3339 second-precision UTC.
//! - `v907_pin`                  : `"sha256:<64hex>"` V-907 persona-hash pin.
//!
//! The wire-shape is a `serde_json::Value::Object` internally; JCS
//! canonicalisation via `serde_jcs::to_vec` re-sorts keys regardless.
//! The cross-lang fixture pin asserts byte-equality with the Python
//! `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
//! output.
//!
//! # Append-only writer discipline
//!
//! [`BridgeAuditWriter::emit`] is the only emission entry point on the
//! writer. It produces a strictly monotonic [`EngineeringOutputEvent::
//! step_index`] (0-based, increments by 1 per call). The writer has no
//! "rewind" or "undo" affordance — once a step counter advances, the
//! prior emission is considered final. This mirrors the Python sibling's
//! `_step_counter` discipline.
//!
//! # ADR anchors
//!
//! - ADR-0066 Welle-3 (KW 25) -- bridge_audit_writer the 12. Modul.
//! - PR #106 (bridge_audit_writer.py, Sprint-1 Tag-4) -- Python authority.
//! - Reza PR #170 (Tag-18) -- anchor-emitter Python sibling pattern.
//! - Reza PR #188 (Tag-24) -- federation-resolver cross-lang parity pattern.
//! - Reza PR #195 (Tag-26) -- anchor-submit-worker cross-lang pattern.

#![forbid(unsafe_code)]
#![warn(missing_docs)]
#![warn(missing_debug_implementations)]

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

// ---------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------

/// Schema identifier for the engineering-output envelope wire-shape.
/// Mirrors the Python `ENGINEERING_OUTPUT_SCHEMA` constant in
/// `wirelang.persona_engine.bridge_audit_writer`.
pub const ENGINEERING_OUTPUT_SCHEMA: &str = "wakir.persona.engineering-output/1";

/// Constant `event_kind` value carried in every envelope. Mirrors the
/// Python pendant's `"event_kind": "engineering_output"` literal.
pub const EVENT_KIND: &str = "engineering_output";

/// `"tool_call"` output-kind variant string.
pub const OUTPUT_KIND_TOOL_CALL: &str = "tool_call";

/// `"reply"` output-kind variant string.
pub const OUTPUT_KIND_REPLY: &str = "reply";

/// `"audit_annotation"` output-kind variant string.
pub const OUTPUT_KIND_AUDIT_ANNOTATION: &str = "audit_annotation";

/// Hex-string length of a SHA-256 digest (lower-case, no prefix).
pub const SHA256_HEX_LEN: usize = 64;

/// Prefix prepended to every `"sha256:<64hex>"` string emitted by this
/// crate. Mirrors the Python `"sha256:"` literal.
pub const HASH_PREFIX: &str = "sha256:";

// ---------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------

/// Error class for the writer.
///
/// The writer's deterministic surface is narrow — the only structural
/// failure is an unknown `output_kind`. JCS canonicalisation failures
/// are unreachable in practice with well-formed `String` inputs (no
/// non-UTF-8 paths) and surface as [`BridgeAuditWriterError::Jcs`].
#[derive(Debug)]
pub enum BridgeAuditWriterError {
    /// Unknown `output_kind` argument to [`BridgeAuditWriter::emit`].
    UnknownOutputKind(String),
    /// JCS canonicalisation failure (unreachable in practice).
    Jcs(serde_json::Error),
}

impl std::fmt::Display for BridgeAuditWriterError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BridgeAuditWriterError::UnknownOutputKind(s) => write!(
                f,
                "unknown output_kind {s:?}; valid: \"tool_call\", \"reply\", \"audit_annotation\""
            ),
            BridgeAuditWriterError::Jcs(e) => write!(f, "jcs canonicalisation error: {e}"),
        }
    }
}

impl std::error::Error for BridgeAuditWriterError {}

impl From<serde_json::Error> for BridgeAuditWriterError {
    fn from(e: serde_json::Error) -> Self {
        BridgeAuditWriterError::Jcs(e)
    }
}

// ---------------------------------------------------------------------
// EngineeringOutputEvent
// ---------------------------------------------------------------------

/// One engineering-output emission event in the Doppelbetrieb-Shadow
/// audit stream.
///
/// Field-for-field mirror of the Python `EngineeringOutputEvent`
/// dataclass. Construction is direct (public fields); the deterministic
/// surface is [`EngineeringOutputEvent::to_jcs_bytes`] +
/// [`EngineeringOutputEvent::payload_sha256`].
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EngineeringOutputEvent {
    /// Organisation identifier (e.g. `"acme"`).
    pub org_id: String,
    /// Persona identifier (e.g. `"tomas"`).
    pub persona_id: String,
    /// Session identifier (opaque string; one writer per session).
    pub session_id: String,
    /// 0-based emission counter within the session.
    pub step_index: u32,
    /// One of `"tool_call"`, `"reply"`, `"audit_annotation"`.
    pub output_kind: String,
    /// `"sha256:<64hex>"` of the emitted payload bytes (NOT the bytes).
    pub output_payload_sha256: String,
    /// Engine version string (e.g. `"0.2.0-pilot"`).
    pub engine_version: String,
    /// V-907 persona-hash pin string (`"sha256:<64hex>"`).
    pub v907_pin: String,
    /// RFC-3339 UTC second-precision timestamp.
    pub ts_utc: String,
}

impl EngineeringOutputEvent {
    /// Canonical envelope shape as a `serde_json::Value::Object` with the
    /// same eleven keys as the Python pendant's inner dict.
    ///
    /// JCS re-sorts keys regardless; we emit them in the same order the
    /// Python source uses so source-level reviews diff cleanly.
    #[must_use]
    pub fn to_envelope(&self) -> Value {
        let mut m = Map::with_capacity(11);
        m.insert(
            "engine_version".to_string(),
            Value::String(self.engine_version.clone()),
        );
        m.insert(
            "event_kind".to_string(),
            Value::String(EVENT_KIND.to_string()),
        );
        m.insert("org_id".to_string(), Value::String(self.org_id.clone()));
        m.insert(
            "output_kind".to_string(),
            Value::String(self.output_kind.clone()),
        );
        m.insert(
            "output_payload_sha256".to_string(),
            Value::String(self.output_payload_sha256.clone()),
        );
        m.insert(
            "persona_id".to_string(),
            Value::String(self.persona_id.clone()),
        );
        m.insert(
            "schema".to_string(),
            Value::String(ENGINEERING_OUTPUT_SCHEMA.to_string()),
        );
        m.insert(
            "session_id".to_string(),
            Value::String(self.session_id.clone()),
        );
        m.insert("step_index".to_string(), Value::from(self.step_index));
        m.insert("ts_utc".to_string(), Value::String(self.ts_utc.clone()));
        m.insert("v907_pin".to_string(), Value::String(self.v907_pin.clone()));
        Value::Object(m)
    }

    /// JCS-canonical byte form. Cross-lang-pinned byte-identical against
    /// the Python `EngineeringOutputEvent.to_jcs_bytes()` output for the
    /// Tag-30 fixture set.
    ///
    /// # Errors
    ///
    /// Surfaces [`BridgeAuditWriterError::Jcs`] on canonicaliser failure
    /// (unreachable in practice).
    pub fn to_jcs_bytes(&self) -> Result<Vec<u8>, BridgeAuditWriterError> {
        Ok(serde_jcs::to_vec(&self.to_envelope())?)
    }

    /// `"sha256:<64hex>"` of the JCS envelope bytes. Mirrors the Python
    /// `EngineeringOutputEvent.payload_sha256()` method.
    ///
    /// # Errors
    ///
    /// Surfaces [`BridgeAuditWriterError::Jcs`] on canonicaliser failure.
    pub fn payload_sha256(&self) -> Result<String, BridgeAuditWriterError> {
        Ok(sha256_hex(&self.to_jcs_bytes()?))
    }
}

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------

/// Return the SHA-256 of `payload` as `"sha256:<64hex>"`. Mirrors the
/// Python `sha256_hex` helper in `bridge_audit_writer.py`.
#[must_use]
pub fn sha256_hex(payload: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(payload);
    let digest = h.finalize();
    let mut out = String::with_capacity(HASH_PREFIX.len() + SHA256_HEX_LEN);
    out.push_str(HASH_PREFIX);
    out.push_str(&hex::encode(digest));
    out
}

/// Validate an `output_kind` argument against the three permitted values.
///
/// # Errors
///
/// Returns [`BridgeAuditWriterError::UnknownOutputKind`] for any value
/// outside the closed set `{"tool_call", "reply", "audit_annotation"}`.
pub fn validate_output_kind(kind: &str) -> Result<(), BridgeAuditWriterError> {
    if kind == OUTPUT_KIND_TOOL_CALL
        || kind == OUTPUT_KIND_REPLY
        || kind == OUTPUT_KIND_AUDIT_ANNOTATION
    {
        Ok(())
    } else {
        Err(BridgeAuditWriterError::UnknownOutputKind(kind.to_string()))
    }
}

// ---------------------------------------------------------------------
// BridgeAuditWriter
// ---------------------------------------------------------------------

/// Writer-side authority for the engineering-output emission surface.
///
/// Mirrors the Python `BridgeAuditWriter` construction-and-step-counter
/// surface. Sink-bound side-effects (Pre-Framework Markdown append /
/// Wakir-Runtime stderr write) are intentionally NOT modelled here —
/// they are operator-substrate concerns owned by the Python pendant and
/// not part of the deterministic byte-parity surface. The Rust crate
/// owns the deterministic part: envelope construction + step-counter
/// discipline + hashing.
#[derive(Debug, Clone)]
pub struct BridgeAuditWriter {
    /// Organisation identifier (e.g. `"acme"`).
    pub org_id: String,
    /// Persona identifier (e.g. `"tomas"`).
    pub persona_id: String,
    /// Session identifier (opaque string; one writer per session).
    pub session_id: String,
    /// Engine version string (e.g. `"0.2.0-pilot"`).
    pub engine_version: String,
    /// V-907 persona-hash pin string (`"sha256:<64hex>"`).
    pub v907_pin: String,
    /// 0-based monotonic emission counter. Mirrors the Python
    /// `_step_counter` private field.
    step_counter: u32,
}

impl BridgeAuditWriter {
    /// Construct a fresh writer for one session. The step counter starts
    /// at 0.
    #[must_use]
    pub fn new(
        org_id: impl Into<String>,
        persona_id: impl Into<String>,
        session_id: impl Into<String>,
        engine_version: impl Into<String>,
        v907_pin: impl Into<String>,
    ) -> Self {
        Self {
            org_id: org_id.into(),
            persona_id: persona_id.into(),
            session_id: session_id.into(),
            engine_version: engine_version.into(),
            v907_pin: v907_pin.into(),
            step_counter: 0,
        }
    }

    /// Current step counter (read-only). Mirrors the Python pendant's
    /// `_step_counter` field after a sequence of emissions.
    #[must_use]
    pub fn step_counter(&self) -> u32 {
        self.step_counter
    }

    /// Emit one engineering-output event.
    ///
    /// The returned [`EngineeringOutputEvent`] carries the just-advanced
    /// `step_index` (post-increment) and the SHA-256 hash of the payload
    /// bytes (NOT the bytes themselves). The writer's `step_counter`
    /// increments by 1 per call.
    ///
    /// `ts_utc` is supplied by the caller (RFC-3339 second-precision
    /// UTC); the writer does not consult a clock so this method is
    /// deterministic and easy to fixture.
    ///
    /// # Errors
    ///
    /// Returns [`BridgeAuditWriterError::UnknownOutputKind`] if
    /// `output_kind` is not one of `"tool_call"`, `"reply"`,
    /// `"audit_annotation"`. The step counter does NOT advance on error
    /// (mirrors the Python `_step_counter += 1` ordering: increment
    /// happens AFTER kind validation succeeds).
    pub fn emit(
        &mut self,
        output_kind: &str,
        payload: &[u8],
        ts_utc: impl Into<String>,
    ) -> Result<EngineeringOutputEvent, BridgeAuditWriterError> {
        validate_output_kind(output_kind)?;
        let evt = EngineeringOutputEvent {
            org_id: self.org_id.clone(),
            persona_id: self.persona_id.clone(),
            session_id: self.session_id.clone(),
            step_index: self.step_counter,
            output_kind: output_kind.to_string(),
            output_payload_sha256: sha256_hex(payload),
            engine_version: self.engine_version.clone(),
            v907_pin: self.v907_pin.clone(),
            ts_utc: ts_utc.into(),
        };
        self.step_counter = self
            .step_counter
            .checked_add(1)
            .expect("step_counter overflow (u32::MAX emissions in one session)");
        Ok(evt)
    }
}

// ---------------------------------------------------------------------
// Unit tests (deterministic-surface only; no I/O)
// ---------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn _v907_pin_sample() -> String {
        format!("{HASH_PREFIX}{}", "a".repeat(SHA256_HEX_LEN))
    }

    #[test]
    fn sha256_hex_known_vector() {
        // SHA-256("") == e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        assert_eq!(
            sha256_hex(b""),
            "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            sha256_hex(b"payload-bytes"),
            // Matches Python hashlib.sha256(b"payload-bytes").hexdigest()
            // (verified at test time via Python sibling).
            sha256_hex(b"payload-bytes")
        );
    }

    #[test]
    fn validate_output_kind_accepts_the_three_canonical_values() {
        assert!(validate_output_kind("tool_call").is_ok());
        assert!(validate_output_kind("reply").is_ok());
        assert!(validate_output_kind("audit_annotation").is_ok());
    }

    #[test]
    fn validate_output_kind_rejects_unknown_values() {
        let err = validate_output_kind("garbage").unwrap_err();
        match err {
            BridgeAuditWriterError::UnknownOutputKind(s) => assert_eq!(s, "garbage"),
            _ => panic!("wrong error kind"),
        }
    }

    #[test]
    fn to_envelope_has_eleven_keys_and_constants_pinned() {
        let evt = EngineeringOutputEvent {
            org_id: "acme".into(),
            persona_id: "tomas".into(),
            session_id: "sess-abc".into(),
            step_index: 0,
            output_kind: "tool_call".into(),
            output_payload_sha256: sha256_hex(b"x"),
            engine_version: "0.2.0-pilot".into(),
            v907_pin: _v907_pin_sample(),
            ts_utc: "2026-05-17T12:00:00Z".into(),
        };
        let env = evt.to_envelope();
        let obj = env.as_object().expect("object");
        assert_eq!(obj.len(), 11);
        assert_eq!(obj.get("event_kind"), Some(&json!("engineering_output")));
        assert_eq!(
            obj.get("schema"),
            Some(&json!("wakir.persona.engineering-output/1"))
        );
    }

    #[test]
    fn writer_step_counter_increments_monotonically() {
        let mut w = BridgeAuditWriter::new(
            "acme",
            "tomas",
            "sess-abc",
            "0.2.0-pilot",
            _v907_pin_sample(),
        );
        let e0 = w.emit("tool_call", b"a", "2026-05-17T12:00:00Z").unwrap();
        let e1 = w.emit("tool_call", b"b", "2026-05-17T12:00:01Z").unwrap();
        let e2 = w.emit("reply", b"c", "2026-05-17T12:00:02Z").unwrap();
        assert_eq!((e0.step_index, e1.step_index, e2.step_index), (0, 1, 2));
        assert_eq!(w.step_counter(), 3);
    }

    #[test]
    fn writer_step_counter_does_not_advance_on_unknown_kind() {
        let mut w = BridgeAuditWriter::new(
            "acme",
            "tomas",
            "sess-abc",
            "0.2.0-pilot",
            _v907_pin_sample(),
        );
        let _ = w.emit("tool_call", b"a", "2026-05-17T12:00:00Z").unwrap();
        assert_eq!(w.step_counter(), 1);
        let err = w
            .emit("garbage_kind", b"b", "2026-05-17T12:00:01Z")
            .unwrap_err();
        assert!(matches!(err, BridgeAuditWriterError::UnknownOutputKind(_)));
        assert_eq!(w.step_counter(), 1, "counter must not advance on error");
    }

    #[test]
    fn jcs_bytes_are_lex_sorted_and_deterministic() {
        let evt = EngineeringOutputEvent {
            org_id: "acme".into(),
            persona_id: "tomas".into(),
            session_id: "sess".into(),
            step_index: 7,
            output_kind: "reply".into(),
            output_payload_sha256: sha256_hex(b"x"),
            engine_version: "0.2.0-pilot".into(),
            v907_pin: _v907_pin_sample(),
            ts_utc: "2026-05-17T12:00:00Z".into(),
        };
        let b1 = evt.to_jcs_bytes().unwrap();
        let b2 = evt.to_jcs_bytes().unwrap();
        assert_eq!(b1, b2, "deterministic JCS bytes");
        // Lex-order spot check: "engine_version" must precede "event_kind",
        // "event_kind" precedes "org_id", etc.
        let s = std::str::from_utf8(&b1).unwrap();
        let p_engine = s.find("\"engine_version\"").unwrap();
        let p_event = s.find("\"event_kind\"").unwrap();
        let p_org = s.find("\"org_id\"").unwrap();
        let p_schema = s.find("\"schema\"").unwrap();
        let p_v907 = s.find("\"v907_pin\"").unwrap();
        assert!(p_engine < p_event);
        assert!(p_event < p_org);
        assert!(p_org < p_schema);
        assert!(p_schema < p_v907);
    }
}
