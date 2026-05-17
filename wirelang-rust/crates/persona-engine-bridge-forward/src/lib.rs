// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors

//! Persona-Engine Bridge-Forward -- Tag-25 Mini-Welle (10. Modul).
//!
//! Rust authority for the Mira-side Bridge-Forward-Pipe
//! canonical-frame surface. The pre-existing Python authority is
//! `wirelang/cli/bridge_forward.py` (Sprint-10 Tag-6); the Tag-25
//! sibling `wirelang/cli/bridge_forward_canonical.py` exposes the
//! higher-layer [`ForwardFrame`] wire-shape that this crate mirrors
//! byte-for-byte.
//!
//! # Cross-language posture
//!
//! Byte-identical Python sibling at
//! `wirelang/cli/bridge_forward_canonical.py` (Apache-2.0, same
//! Tag-25 bundle). Both modules emit identical JCS-canonical bytes
//! for the cross-lang fixture file
//! `tests/fixtures/bridge-forward-cross-lang/fixtures.json`.
//!
//! # Schema-parity table (Rust <-> Python)
//!
//! | Python concept                            | Rust type/const                 |
//! |-------------------------------------------|---------------------------------|
//! | `AuftragEnvelope` (dataclass)             | [`AuftragEnvelope`]             |
//! | `ForwardFrameInput` (dataclass)           | [`ForwardFrameInput`]           |
//! | `ForwardFrame` (dataclass)                | [`ForwardFrame`]                |
//! | `build_forward_frame(input)`              | [`build_forward_frame`]         |
//! | `build_subject(env, persona_slug)`        | [`build_subject`]               |
//! | `serialize_forward_frame(frame)`          | [`serialize_forward_frame`]     |
//! | `forward_frame_sha256_hex(frame)`         | [`forward_frame_sha256_hex`]    |
//! | `forward_frame_hash_prefixed(frame)`      | [`forward_frame_hash_prefixed`] |
//! | `serialize_and_hash(frame)`               | [`serialize_and_hash`]          |
//! | `BridgeForwardError`                      | [`BridgeForwardError`]          |
//! | `BRIDGE_FORWARD_FRAME_SCHEMA`             | [`BRIDGE_FORWARD_FRAME_SCHEMA`] |
//! | `AGENT_TASK_ASSIGNED_SCHEMA`              | [`AGENT_TASK_ASSIGNED_SCHEMA`]  |
//! | `HASH_PREFIX` / `SHA256_HEX_LEN`          | same constants                  |
//!
//! # Wire-shape contract
//!
//! Forward-frame: three alphabetical top-level keys
//!
//! - `envelope` : the Sprint-10 Tag-6 nine-key envelope dict.
//! - `schema`   : constant [`BRIDGE_FORWARD_FRAME_SCHEMA`].
//! - `subject`  : canonical NATS subject string built by
//!   [`build_subject`].
//!
//! Per-envelope wire-shape (ten alphabetical keys; matches
//! `wirelang.cli.bridge_forward.AuftragEnvelope.to_dict()`):
//!
//! - `auftrag_id`     : round-trip key.
//! - `event_kind`     : constant `"agent.task.assigned"`.
//! - `metadata`       : string-to-string object (alphabetised keys).
//! - `org_id`         : organisation identifier.
//! - `persona_id`     : persona identifier (same as `persona_slug`).
//! - `prompt_payload` : UTF-8 prompt text.
//! - `prompt_sha256`  : `sha256:<hex>` of the prompt payload bytes.
//! - `schema`         : constant [`AGENT_TASK_ASSIGNED_SCHEMA`].
//! - `source`         : caller-provided source identifier.
//! - `ts_utc`         : RFC-3339 second-precision UTC.
//!
//! The wire-shape uses [`serde_json::Value`] internally to keep the
//! source-level layout matching the explicit dict-construction on the
//! Python side. JCS canonicalisation re-sorts keys regardless; the
//! cross-lang fixture pin asserts byte-equality with the Python
//! `json.dumps(sort_keys=True, separators=(",", ":"),
//! ensure_ascii=False)` output.
//!
//! # ADR anchors
//!
//! - ADR-0063 §Folgeartefakte Phase-3a Item 10 (this crate).
//! - Reza PR #170 (Tag-18) -- anchor-emitter Python sibling pattern.
//! - Reza PR #177 (Tag-21) -- lifecycle-FSM canonical-trace pattern.
//! - Reza PR #183 (Tag-23) -- state-backing cross-lang parity pattern.
//! - Reza PR #188 (Tag-24) -- federation-resolver cross-lang parity pattern.

#![forbid(unsafe_code)]
#![warn(missing_docs)]
#![warn(missing_debug_implementations)]

use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fmt;

// ---------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------

/// Schema identifier for the outer forward-frame wire-shape. Mirrors
/// the Python `BRIDGE_FORWARD_FRAME_SCHEMA` constant.
pub const BRIDGE_FORWARD_FRAME_SCHEMA: &str = "wakir.bridge.forward-frame/1";

/// Schema identifier for the inner agent.task.assigned envelope.
/// Mirrors the Python `AGENT_TASK_ASSIGNED_SCHEMA` constant
/// (declared in `wirelang.cli.bridge_forward`).
pub const AGENT_TASK_ASSIGNED_SCHEMA: &str = "wakir.agent.task-assigned/1";

/// Constant `event_kind` value carried in every inner envelope.
pub const EVENT_KIND_AGENT_TASK_ASSIGNED: &str = "agent.task.assigned";

/// Prefix prepended to every `"sha256:<64hex>"` string emitted by this
/// crate. Mirrors the Python `HASH_PREFIX` constant.
pub const HASH_PREFIX: &str = "sha256:";

/// Hex-string length of a SHA-256 digest (lower-case, no prefix).
pub const SHA256_HEX_LEN: usize = 64;

/// Size envelope from Sprint-10 Tag-6 §3.3 -- `prompt_payload` cap.
pub const MAX_PROMPT_PAYLOAD_BYTES: usize = 256 * 1024;

/// Size envelope from Sprint-10 Tag-6 §3.3 -- `auftrag_id` octet cap.
pub const MAX_AUFTRAG_ID_OCTETS: usize = 64;

/// Size envelope from Sprint-10 Tag-6 §3.3 -- `metadata` JCS cap.
pub const MAX_METADATA_BYTES: usize = 8 * 1024;

/// Default `org_id` (matches the Python CLI default).
pub const DEFAULT_ORG_ID: &str = "acme";

/// Default `source` (matches the Python CLI default).
pub const DEFAULT_SOURCE: &str = "mira-sandbox";

// ---------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------

/// Error surface for [`build_forward_frame`] and friends. Mirrors the
/// Python `EnvelopeFormatError` / `SizeLimitError` split: shape errors
/// (subject regex, env enum, missing fields) surface as
/// [`BridgeForwardError::InvalidShape`]; size-limit breaches surface
/// as [`BridgeForwardError::SizeLimit`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BridgeForwardError {
    /// `env` must be one of `"dev"`, `"staging"`, `"prod"`. The
    /// payload carries the offending value for audit diagnostics.
    InvalidEnv(String),
    /// `persona_slug` must match `[a-z][a-z0-9_-]*`. The payload
    /// carries the offending value.
    InvalidPersonaSlug(String),
    /// Generic shape error (e.g. internal serialisation invariant
    /// breach); the payload is the failure reason.
    InvalidShape(String),
    /// A field exceeded the Sprint-10 Tag-6 §3.3 size envelope.
    /// Fields:
    /// - `field`: which limit fired (`"prompt_payload"`,
    ///   `"auftrag_id"`, `"metadata"`).
    /// - `actual`: actual byte size.
    /// - `limit`: the configured cap.
    SizeLimit {
        /// Name of the field whose limit fired.
        field: &'static str,
        /// Actual byte size of the field.
        actual: usize,
        /// Configured byte-size cap.
        limit: usize,
    },
    /// JCS canonicalisation surfaced an error. Should not happen for
    /// the shapes this crate emits; surfaced for forward compatibility.
    JcsFailure(String),
}

impl fmt::Display for BridgeForwardError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            BridgeForwardError::InvalidEnv(v) => {
                write!(f, "env must be one of dev/staging/prod, got {v:?}")
            }
            BridgeForwardError::InvalidPersonaSlug(v) => {
                write!(
                    f,
                    "persona_slug must match [a-z][a-z0-9_-]*, got {v:?}"
                )
            }
            BridgeForwardError::InvalidShape(s) => write!(f, "invalid shape: {s}"),
            BridgeForwardError::SizeLimit {
                field,
                actual,
                limit,
            } => {
                write!(
                    f,
                    "size-limit breach: {field} = {actual} bytes (limit {limit})"
                )
            }
            BridgeForwardError::JcsFailure(s) => {
                write!(f, "JCS canonicalisation failed: {s}")
            }
        }
    }
}

impl std::error::Error for BridgeForwardError {}

// ---------------------------------------------------------------------
// AuftragEnvelope -- inner Sprint-10 Tag-6 envelope
// ---------------------------------------------------------------------

/// Inner agent.task.assigned envelope -- mirrors the Python
/// `AuftragEnvelope` dataclass.
///
/// The wire-shape emits ten alphabetically-sorted keys (auftrag_id,
/// event_kind, metadata, org_id, persona_id, prompt_payload,
/// prompt_sha256, schema, source, ts_utc). The
/// [`AuftragEnvelope::prompt_sha256`] field is derived from the
/// `prompt_payload` bytes via SHA-256; constructors that hand-roll an
/// envelope MUST keep that invariant.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuftragEnvelope {
    /// Organisation identifier (e.g. `"acme"`).
    pub org_id: String,
    /// Persona identifier (same value as `persona_slug`).
    pub persona_id: String,
    /// Round-trip key (caller-chosen unique identifier).
    pub auftrag_id: String,
    /// RFC-3339 second-precision UTC.
    pub ts_utc: String,
    /// Source identifier (e.g. `"mira-sandbox"`).
    pub source: String,
    /// UTF-8 prompt text.
    pub prompt_payload: String,
    /// Optional string-to-string metadata bag.
    pub metadata: BTreeMap<String, String>,
}

impl AuftragEnvelope {
    /// Return the `sha256:<hex>` digest of the prompt payload bytes.
    ///
    /// Byte-identical to the Python `AuftragEnvelope.prompt_sha256`
    /// property (UTF-8 bytes of the prompt -> SHA-256 -> lower-case hex
    /// -> `"sha256:"` prefix).
    #[must_use]
    pub fn prompt_sha256(&self) -> String {
        let mut hasher = Sha256::new();
        hasher.update(self.prompt_payload.as_bytes());
        let digest = hasher.finalize();
        format!("{HASH_PREFIX}{}", hex::encode(digest))
    }

    /// Project the envelope to a [`serde_json::Value`] wire-dict.
    ///
    /// The returned `Value::Object` carries the ten canonical keys
    /// (alphabetical: `auftrag_id`, `event_kind`, `metadata`, `org_id`,
    /// `persona_id`, `prompt_payload`, `prompt_sha256`, `schema`,
    /// `source`, `ts_utc`). Key-order in the returned map is the
    /// insertion order; JCS canonicalisation re-sorts on serialisation.
    #[must_use]
    pub fn to_wire_value(&self) -> serde_json::Value {
        let mut metadata = serde_json::Map::new();
        for (k, v) in &self.metadata {
            metadata.insert(k.clone(), serde_json::Value::String(v.clone()));
        }
        let mut m = serde_json::Map::new();
        m.insert("schema".into(), AGENT_TASK_ASSIGNED_SCHEMA.into());
        m.insert("event_kind".into(), EVENT_KIND_AGENT_TASK_ASSIGNED.into());
        m.insert("org_id".into(), self.org_id.clone().into());
        m.insert("persona_id".into(), self.persona_id.clone().into());
        m.insert("auftrag_id".into(), self.auftrag_id.clone().into());
        m.insert("ts_utc".into(), self.ts_utc.clone().into());
        m.insert("source".into(), self.source.clone().into());
        m.insert("prompt_sha256".into(), self.prompt_sha256().into());
        m.insert("prompt_payload".into(), self.prompt_payload.clone().into());
        m.insert("metadata".into(), serde_json::Value::Object(metadata));
        serde_json::Value::Object(m)
    }
}

// ---------------------------------------------------------------------
// Subject builder
// ---------------------------------------------------------------------

/// Build the canonical agent.task.assigned NATS subject.
///
/// Mirrors the Python `build_subject` function. The subject pattern
/// honours the subject-mapping-v1 regex
/// `^wakir\.(dev|staging|prod)\.[a-z][a-z0-9_-]*\.[a-z][a-z0-9_.-]*(\.[a-zA-Z0-9_.-]+)?$`.
///
/// # Errors
///
/// - [`BridgeForwardError::InvalidEnv`] if `env` is not one of `"dev"`,
///   `"staging"`, `"prod"`.
/// - [`BridgeForwardError::InvalidPersonaSlug`] if `persona_slug` does
///   not match `[a-z][a-z0-9_-]*` (leading lower-case ASCII letter,
///   followed by lower-case ASCII alphanumeric / `_` / `-`).
pub fn build_subject(env: &str, persona_slug: &str) -> Result<String, BridgeForwardError> {
    match env {
        "dev" | "staging" | "prod" => {}
        _ => return Err(BridgeForwardError::InvalidEnv(env.to_string())),
    }
    if !is_valid_persona_slug(persona_slug) {
        return Err(BridgeForwardError::InvalidPersonaSlug(
            persona_slug.to_string(),
        ));
    }
    Ok(format!(
        "wakir.{env}.agent.agent.task.assigned.{persona_slug}"
    ))
}

fn is_valid_persona_slug(slug: &str) -> bool {
    let mut chars = slug.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    if !first.is_ascii_lowercase() {
        return false;
    }
    for c in chars {
        if !(c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-') {
            return false;
        }
    }
    true
}

// ---------------------------------------------------------------------
// ForwardFrameInput + ForwardFrame
// ---------------------------------------------------------------------

/// Logical input to [`build_forward_frame`]. Mirrors the Python
/// `ForwardFrameInput` dataclass.
///
/// The four required fields plus `ts_utc` and `prompt_payload` form
/// the inner [`AuftragEnvelope`]. `org_id` / `source` default to the
/// Sprint-10 Tag-6 CLI defaults [`DEFAULT_ORG_ID`] / [`DEFAULT_SOURCE`].
/// `metadata` defaults to empty.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ForwardFrameInput {
    /// Environment label: one of `"dev"`, `"staging"`, `"prod"`.
    pub env: String,
    /// Persona slug (matches `[a-z][a-z0-9_-]*`).
    pub persona_slug: String,
    /// Round-trip key (caller-chosen unique identifier).
    pub auftrag_id: String,
    /// RFC-3339 second-precision UTC.
    pub ts_utc: String,
    /// UTF-8 prompt text.
    pub prompt_payload: String,
    /// Organisation identifier (default [`DEFAULT_ORG_ID`]).
    pub org_id: String,
    /// Source identifier (default [`DEFAULT_SOURCE`]).
    pub source: String,
    /// Optional string-to-string metadata bag.
    pub metadata: BTreeMap<String, String>,
}

impl ForwardFrameInput {
    /// Build a fresh input using the Sprint-10 Tag-6 CLI defaults for
    /// `org_id` (`"acme"`) and `source` (`"mira-sandbox"`).
    #[must_use]
    pub fn new(
        env: impl Into<String>,
        persona_slug: impl Into<String>,
        auftrag_id: impl Into<String>,
        ts_utc: impl Into<String>,
        prompt_payload: impl Into<String>,
    ) -> Self {
        Self {
            env: env.into(),
            persona_slug: persona_slug.into(),
            auftrag_id: auftrag_id.into(),
            ts_utc: ts_utc.into(),
            prompt_payload: prompt_payload.into(),
            org_id: DEFAULT_ORG_ID.to_string(),
            source: DEFAULT_SOURCE.to_string(),
            metadata: BTreeMap::new(),
        }
    }

    /// Builder-style override for `org_id`.
    #[must_use]
    pub fn with_org_id(mut self, org_id: impl Into<String>) -> Self {
        self.org_id = org_id.into();
        self
    }

    /// Builder-style override for `source`.
    #[must_use]
    pub fn with_source(mut self, source: impl Into<String>) -> Self {
        self.source = source.into();
        self
    }

    /// Builder-style override for `metadata`.
    #[must_use]
    pub fn with_metadata(mut self, metadata: BTreeMap<String, String>) -> Self {
        self.metadata = metadata;
        self
    }
}

/// Canonical forward-frame -- mirrors the Python `ForwardFrame`
/// dataclass.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ForwardFrame {
    /// Canonical NATS subject string.
    pub subject: String,
    /// Inner agent.task.assigned envelope.
    pub envelope: AuftragEnvelope,
}

impl ForwardFrame {
    /// Project the forward-frame to a [`serde_json::Value`] wire-dict.
    ///
    /// The returned `Value::Object` carries the three alphabetical
    /// top-level keys (`envelope`, `schema`, `subject`).
    #[must_use]
    pub fn to_wire_value(&self) -> serde_json::Value {
        let mut m = serde_json::Map::new();
        m.insert("envelope".into(), self.envelope.to_wire_value());
        m.insert("schema".into(), BRIDGE_FORWARD_FRAME_SCHEMA.into());
        m.insert("subject".into(), self.subject.clone().into());
        serde_json::Value::Object(m)
    }
}

// ---------------------------------------------------------------------
// Pure-function frame builder / serialiser / hasher
// ---------------------------------------------------------------------

/// Construct a [`ForwardFrame`] from a [`ForwardFrameInput`].
///
/// Pure function: no IO, no clock, no network. Re-uses
/// [`build_subject`] for subject construction (which also enforces the
/// subject-mapping-v1 regex) and constructs the inner
/// [`AuftragEnvelope`] in-place. The forward-frame inherits the inner
/// envelope's size invariants (callers MUST call
/// [`validate_forward_frame`] to enforce the Sprint-10 Tag-6 §3.3 size
/// envelope).
///
/// # Errors
///
/// - [`BridgeForwardError::InvalidEnv`] for an unknown env.
/// - [`BridgeForwardError::InvalidPersonaSlug`] for a slug that fails
///   the regex.
pub fn build_forward_frame(input: &ForwardFrameInput) -> Result<ForwardFrame, BridgeForwardError> {
    let subject = build_subject(&input.env, &input.persona_slug)?;
    let envelope = AuftragEnvelope {
        org_id: input.org_id.clone(),
        persona_id: input.persona_slug.clone(),
        auftrag_id: input.auftrag_id.clone(),
        ts_utc: input.ts_utc.clone(),
        source: input.source.clone(),
        prompt_payload: input.prompt_payload.clone(),
        metadata: input.metadata.clone(),
    };
    Ok(ForwardFrame { subject, envelope })
}

/// Render `frame` as JCS-canonical UTF-8 bytes.
///
/// Delegates to `serde_jcs::to_vec`; the output is byte-identical to
/// the Python `json.dumps(sort_keys=True, separators=(",", ":"),
/// ensure_ascii=False).encode("utf-8")` convention used by
/// `wirelang.cli.bridge_forward_canonical.serialize_forward_frame`.
///
/// # Errors
///
/// Returns [`BridgeForwardError::JcsFailure`] if `serde_jcs` rejects
/// the value (in practice unreachable for well-formed input).
pub fn serialize_forward_frame(frame: &ForwardFrame) -> Result<Vec<u8>, BridgeForwardError> {
    let value = frame.to_wire_value();
    serde_jcs::to_vec(&value).map_err(|e| BridgeForwardError::JcsFailure(e.to_string()))
}

/// Return the bare lower-case-hex SHA-256 of the canonical bytes.
///
/// The returned string is exactly [`SHA256_HEX_LEN`] characters (no
/// prefix). Mirrors the Python `forward_frame_sha256_hex` helper.
///
/// # Errors
///
/// See [`serialize_forward_frame`].
pub fn forward_frame_sha256_hex(frame: &ForwardFrame) -> Result<String, BridgeForwardError> {
    let bytes = serialize_forward_frame(frame)?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    let digest = hasher.finalize();
    Ok(hex::encode(digest))
}

/// Return the `"sha256:<hex>"` prefixed SHA-256.
///
/// The return value is [`HASH_PREFIX`] + [`forward_frame_sha256_hex`].
/// Mirrors the Python `forward_frame_hash_prefixed` helper.
///
/// # Errors
///
/// See [`serialize_forward_frame`].
pub fn forward_frame_hash_prefixed(frame: &ForwardFrame) -> Result<String, BridgeForwardError> {
    Ok(format!("{HASH_PREFIX}{}", forward_frame_sha256_hex(frame)?))
}

/// Return `(canonical_bytes, prefixed_hash)` for one-shot consumers.
///
/// The two values are byte-identical to two independent calls of
/// [`serialize_forward_frame`] / [`forward_frame_hash_prefixed`] on
/// the same frame. The pair is exposed because the Rust callsites
/// typically need both -- folding them into one entry-point avoids a
/// duplicated JCS canonicalisation pass.
///
/// # Errors
///
/// See [`serialize_forward_frame`].
pub fn serialize_and_hash(frame: &ForwardFrame) -> Result<(Vec<u8>, String), BridgeForwardError> {
    let bytes = serialize_forward_frame(frame)?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    let digest = hasher.finalize();
    let prefixed = format!("{HASH_PREFIX}{}", hex::encode(digest));
    Ok((bytes, prefixed))
}

// ---------------------------------------------------------------------
// Size-envelope validation
// ---------------------------------------------------------------------

/// Apply the Sprint-10 Tag-6 §3.3 size envelope to the inner envelope
/// of `frame`. Raises a typed [`BridgeForwardError::SizeLimit`] error
/// on the first failure (in field-name alphabetical order:
/// `auftrag_id`, `metadata`, `prompt_payload`).
///
/// # Errors
///
/// - [`BridgeForwardError::SizeLimit`] if a field exceeds its cap.
/// - [`BridgeForwardError::JcsFailure`] if the metadata sub-object
///   fails JCS canonicalisation.
pub fn validate_forward_frame(frame: &ForwardFrame) -> Result<(), BridgeForwardError> {
    let aid_bytes = frame.envelope.auftrag_id.len();
    if aid_bytes > MAX_AUFTRAG_ID_OCTETS {
        return Err(BridgeForwardError::SizeLimit {
            field: "auftrag_id",
            actual: aid_bytes,
            limit: MAX_AUFTRAG_ID_OCTETS,
        });
    }
    // Metadata cap is measured in JCS-serialised bytes, matching the
    // Python helper.
    let mut metadata = serde_json::Map::new();
    for (k, v) in &frame.envelope.metadata {
        metadata.insert(k.clone(), serde_json::Value::String(v.clone()));
    }
    let meta_value = serde_json::Value::Object(metadata);
    let meta_bytes = serde_jcs::to_vec(&meta_value)
        .map_err(|e| BridgeForwardError::JcsFailure(e.to_string()))?;
    if meta_bytes.len() > MAX_METADATA_BYTES {
        return Err(BridgeForwardError::SizeLimit {
            field: "metadata",
            actual: meta_bytes.len(),
            limit: MAX_METADATA_BYTES,
        });
    }
    let prompt_bytes = frame.envelope.prompt_payload.len();
    if prompt_bytes > MAX_PROMPT_PAYLOAD_BYTES {
        return Err(BridgeForwardError::SizeLimit {
            field: "prompt_payload",
            actual: prompt_bytes,
            limit: MAX_PROMPT_PAYLOAD_BYTES,
        });
    }
    Ok(())
}

// ---------------------------------------------------------------------
// Tests (unit tests internal to the lib; smoke / cross-lang tests in
// tests/bridge_forward_cross_lang_fixture_test.rs)
// ---------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slug_validator_accepts_canonical_slugs() {
        for s in &["tomas", "reza", "kai", "selin", "agent_1", "mira-2"] {
            assert!(is_valid_persona_slug(s), "expected accept: {s}");
        }
    }

    #[test]
    fn slug_validator_rejects_bad_inputs() {
        for s in &["", "Tomas", "1tomas", "to.mas", "to mas", "tom!", "-tom"] {
            assert!(!is_valid_persona_slug(s), "expected reject: {s}");
        }
    }

    #[test]
    fn build_subject_matches_python_pattern() {
        assert_eq!(
            build_subject("dev", "tomas").unwrap(),
            "wakir.dev.agent.agent.task.assigned.tomas"
        );
    }

    #[test]
    fn auftrag_envelope_prompt_sha256_matches_sha256_of_payload() {
        let env = AuftragEnvelope {
            org_id: "acme".into(),
            persona_id: "tomas".into(),
            auftrag_id: "x".into(),
            ts_utc: "2026-05-17T00:00:00Z".into(),
            source: "mira-sandbox".into(),
            prompt_payload: "hello world".into(),
            metadata: BTreeMap::new(),
        };
        let mut hasher = Sha256::new();
        hasher.update(b"hello world");
        let expected = format!("sha256:{}", hex::encode(hasher.finalize()));
        assert_eq!(env.prompt_sha256(), expected);
    }
}
