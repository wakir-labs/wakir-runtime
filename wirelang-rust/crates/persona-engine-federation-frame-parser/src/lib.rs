// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Persona-engine federation-frame parser — Rust pendant.
//
// Schema-parity authority: the federation-frame envelope shape
// defined in this crate's Cargo.toml header. No Python sibling exists
// yet (2026-05-17); the cross-lang pin placeholders flag the spots
// where a future Python `wirelang/federation/federation_frame.py` must
// byte-match.

#![forbid(unsafe_code)]
#![deny(missing_docs)]
#![warn(missing_debug_implementations)]

//! Persona-Engine federation-frame parser — Phase-3a Item 9.
//!
//! Inter-runtime federation frames wrap a single payload (bridge-
//! forward Auftrag, persona task output, multi-org attestation
//! pointer, or SPIFFE trust-bundle sync notice) in a JCS-canonical
//! envelope suitable for transport between Wakir-Runtime instances
//! belonging to different operator-orgs.
//!
//! # Public surface
//!
//! - [`FederationFrame`] — the typed envelope struct.
//! - [`FrameHeader`] — schema, frame_id, source_runtime,
//!   target_runtime, ts_utc, version.
//! - [`FederationPayload`] — typed enum over the four payload kinds.
//! - [`parse_frame`] — JCS-canonical JSON bytes -> typed frame.
//! - [`serialize_frame`] — typed frame -> JCS-canonical JSON bytes.
//! - [`compute_frame_id`] — deterministic frame-id derivation
//!   (`"frame-sha256:<hex>"`) over a caller-supplied seed.
//! - [`ParseError`] — error surface.
//!
//! # Default-Lock posture
//!
//! - **A-1 Mock-Format-Baseline:** parse JCS-canonical JSON frame
//!   bytes into a typed `FederationFrame`; preserve unknown payload
//!   `data` keys verbatim (forward-compat). This crate does not
//!   verify signatures and does not fetch trust bundles.
//! - **A-2 Additiv-only:** new crate added next to existing roster;
//!   no Python file is modified.
//! - **A-3 Body out-of-hash:** the `signature` field is computed by
//!   an external signer over the JCS bytes of the `{header, payload}`
//!   subtree (see [`signing_payload_bytes`]); this crate ships the
//!   helper but never invokes a signer.
//!
//! # ADR anchors
//!
//! - ADR-0063 §Folgeartefakte Phase-3a Item 9 (this crate).
//! - ADR-0035 Errata 1 — Rust as Phase-1c language for persona-engine.
//! - Tomás Sprint-10 Tag-6 — `bridge-forward-pipe-v1.md` (task-assigned
//!   payload schema authority).
//! - Reza Sprint-7 Tag-1 — `multi_org_substrate.py`
//!   (multi-org-attestation payload schema authority).
//!
//! # Cross-language sync TODO
//!
//! The constant [`TODO_PYTHON_FRAME_PARITY_PIN`] is the marker the
//! future Python `federation_frame.py` PR must satisfy. The Sprint-
//! Federation-Frame-Python-Sync follow-up owns the Python side.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fmt;

// ---------------------------------------------------------------------
// Constants.
// ---------------------------------------------------------------------

/// Outer-envelope schema tag emitted in every frame header. Bumped on
/// any wire-shape change; consumers MUST reject unknown values.
pub const FRAME_ENVELOPE_SCHEMA: &str = "wakir.federation.frame/1";

/// Current frame-envelope wire version. Bumped in lock-step with
/// [`FRAME_ENVELOPE_SCHEMA`].
pub const FRAME_ENVELOPE_VERSION: u32 = 1;

/// Schema identifier accepted on inbound task-assigned payloads
/// (parity with Python `ACCEPTED_INBOUND_SCHEMA` in
/// `wirelang/persona_engine/nats_subscribe_loop.py`).
pub const PAYLOAD_SCHEMA_TASK_ASSIGNED: &str = "wakir.agent.task-assigned/1";

/// Schema identifier emitted on task-output payloads
/// (parity with Python `OUTBOUND_OUTPUT_SCHEMA` in
/// `wirelang/persona_engine/nats_subscribe_loop.py`).
pub const PAYLOAD_SCHEMA_TASK_OUTPUT: &str = "wakir.agent.task-output/1";

/// Schema identifier for the multi-org attestation pointer payload
/// (parity with Python `ATTESTATION_VALUE_SCHEMA` in
/// `wirelang/federation/multi_org_substrate.py`).
pub const PAYLOAD_SCHEMA_MULTI_ORG_ATTESTATION: &str =
    "wakir.federation.multi-org-attestation/1";

/// Schema identifier for the SPIFFE trust-bundle sync notice. No
/// Python counterpart exists yet; the Python side will land via
/// the Sprint-Federation-Frame-Python-Sync follow-up.
pub const PAYLOAD_SCHEMA_SPIFFE_BUNDLE_SYNC: &str =
    "wakir.federation.spiffe-bundle-sync/1";

/// Prefix prepended to the SHA-256 hex tail by [`compute_frame_id`].
pub const FRAME_ID_PREFIX: &str = "frame-sha256:";

/// Prefix prepended to the SHA-256 hex tail by a caller building a
/// WAT anchor reference. Mirrors the prefix the WAT-anchor-emitter
/// crate uses (`"sha256:"`); we re-namespace with `"wat:"` so a
/// reader can tell at a glance that the reference points to a WAT
/// Merkle leaf rather than to an arbitrary content hash.
pub const ANCHOR_REF_PREFIX: &str = "wat:";

/// Maximum size (bytes) of the JCS-canonical frame payload. Matches
/// the bridge-forward-pipe-v1 §3.3 `prompt_payload` ceiling
/// (256 KiB) plus envelope headroom (signature + header). Phase-3a
/// pilot ceiling; bumped via a follow-up ADR if multi-org workloads
/// push past it.
pub const MAX_FRAME_JCS_BYTES: usize = 320 * 1024;

/// Hex-string length of a SHA-256 digest (lower-case, no prefix).
pub const SHA256_HEX_LEN: usize = 64;

/// Cross-language sync TODO marker. The future Python
/// `wirelang/federation/federation_frame.py` MUST byte-match the
/// fixtures in `tests/federation_frame_parser_smoke_test.rs`
/// (`FRAME_FIXTURE_*` constants). Until that PR lands the
/// cross-lang pin is a placeholder.
pub const TODO_PYTHON_FRAME_PARITY_PIN: &str =
    "TODO(reza): Sprint-Federation-Frame-Python-Sync follow-up — \
     wirelang/federation/federation_frame.py must byte-match \
     FRAME_FIXTURE_TASK_ASSIGNED / FRAME_FIXTURE_TASK_OUTPUT / \
     FRAME_FIXTURE_MULTI_ORG_ATTESTATION / \
     FRAME_FIXTURE_SPIFFE_BUNDLE_SYNC.";

// ---------------------------------------------------------------------
// Errors.
// ---------------------------------------------------------------------

/// Error surface for [`parse_frame`] and [`serialize_frame`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ParseError {
    /// The supplied bytes are not valid UTF-8.
    BadUtf8(String),
    /// The supplied bytes are not valid JSON.
    BadJson(String),
    /// Required top-level field missing. Carries the field name for
    /// audit diagnostics.
    MissingField(&'static str),
    /// A schema field carried an unknown value. Carries the field
    /// path and the offending value.
    UnknownSchema {
        /// Field path (e.g. `"header.schema"` or `"payload.schema"`).
        field: &'static str,
        /// Offending value as observed in the wire bytes.
        value: String,
    },
    /// The envelope version is not [`FRAME_ENVELOPE_VERSION`]. Carries
    /// the offending version integer.
    UnsupportedVersion(u32),
    /// `ts_utc` is not in the RFC-3339 second-precision UTC shape
    /// (`YYYY-MM-DDTHH:MM:SSZ`).
    BadTimestampShape(String),
    /// `frame_id` is not in the `frame-sha256:<64-hex>` shape.
    BadFrameIdShape(String),
    /// `anchor_ref` is set but not in the `wat:<64-hex>` shape.
    BadAnchorRefShape(String),
    /// `signature` is set but not in the lower-case-hex shape.
    BadSignatureShape(String),
    /// `source_runtime` or `target_runtime` is empty or malformed.
    BadRuntimeId {
        /// Field name (`"source_runtime"` or `"target_runtime"`).
        field: &'static str,
        /// Offending value as observed in the wire bytes.
        value: String,
    },
    /// JCS canonicalisation failed.
    JcsFailure(String),
    /// The serialised frame exceeds [`MAX_FRAME_JCS_BYTES`].
    FrameTooLarge {
        /// Observed JCS byte length.
        bytes: usize,
        /// Configured ceiling ([`MAX_FRAME_JCS_BYTES`]).
        max: usize,
    },
    /// Payload `kind` is unknown (not in the closed enum).
    UnknownPayloadKind(String),
    /// Payload `data` is not a JSON object.
    PayloadDataNotObject,
}

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ParseError::BadUtf8(s) => write!(f, "frame bytes are not UTF-8: {}", s),
            ParseError::BadJson(s) => write!(f, "frame bytes are not valid JSON: {}", s),
            ParseError::MissingField(n) => write!(f, "frame missing required field {:?}", n),
            ParseError::UnknownSchema { field, value } => write!(
                f,
                "frame field {:?} carries unknown schema value {:?}",
                field, value
            ),
            ParseError::UnsupportedVersion(v) => {
                write!(f, "frame envelope version {} is not supported (want {})", v, FRAME_ENVELOPE_VERSION)
            }
            ParseError::BadTimestampShape(s) => write!(
                f,
                "frame header ts_utc {:?} is not RFC-3339 second-precision UTC \
                 (YYYY-MM-DDTHH:MM:SSZ)",
                s
            ),
            ParseError::BadFrameIdShape(s) => write!(
                f,
                "frame header frame_id {:?} is not in frame-sha256:<64-hex> shape",
                s
            ),
            ParseError::BadAnchorRefShape(s) => write!(
                f,
                "frame anchor_ref {:?} is not in wat:<64-hex> shape",
                s
            ),
            ParseError::BadSignatureShape(s) => write!(
                f,
                "frame signature {:?} is not lower-case hex",
                s
            ),
            ParseError::BadRuntimeId { field, value } => write!(
                f,
                "frame header {} {:?} is empty or malformed (expect non-empty ASCII)",
                field, value
            ),
            ParseError::JcsFailure(s) => write!(f, "JCS canonicalisation failed: {}", s),
            ParseError::FrameTooLarge { bytes, max } => write!(
                f,
                "JCS-canonical frame size {} bytes exceeds ceiling {} bytes",
                bytes, max
            ),
            ParseError::UnknownPayloadKind(k) => {
                write!(f, "payload kind {:?} is not a recognised variant", k)
            }
            ParseError::PayloadDataNotObject => {
                write!(f, "payload `data` must be a JSON object")
            }
        }
    }
}

impl std::error::Error for ParseError {}

// ---------------------------------------------------------------------
// Frame structs (typed Rust surface).
// ---------------------------------------------------------------------

/// Top-level inter-runtime federation frame.
///
/// Field order in the in-memory struct mirrors the lexical JSON key
/// order JCS emits (`anchor_ref`, `header`, `payload`, `signature`),
/// so a `serde_json::to_value` followed by [`serialize_frame`] is
/// idempotent at the byte level.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FederationFrame {
    /// Optional WAT anchor reference (`"wat:<64-hex>"`). When set,
    /// downstream WAT-spool consumers can use this pointer to fetch
    /// the Merkle leaf the frame was anchored against.
    pub anchor_ref: Option<String>,
    /// Frame header: schema, frame_id, runtimes, timestamp, version.
    pub header: FrameHeader,
    /// Typed payload (one of four kinds).
    pub payload: FederationPayload,
    /// Optional ed25519 signature, lower-case hex. The signer
    /// computes this over the JCS bytes of `{header, payload}`
    /// (use [`signing_payload_bytes`] to derive those bytes). This
    /// crate does not verify the signature.
    pub signature: Option<String>,
}

/// Frame header — the fields every frame carries regardless of
/// payload kind.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FrameHeader {
    /// Deterministic frame identifier
    /// (`"frame-sha256:<64-hex>"`). Use [`compute_frame_id`] to
    /// derive one from a caller-supplied seed.
    pub frame_id: String,
    /// Outer-envelope schema; always [`FRAME_ENVELOPE_SCHEMA`].
    pub schema: String,
    /// Source-runtime identifier. Non-empty ASCII; production
    /// deployments use `"<orgid>/<runtime>"` shape. Pilot uses
    /// `"mira-sandbox"` or `"wakir-runtime"`.
    pub source_runtime: String,
    /// Target-runtime identifier. Same shape as `source_runtime`.
    pub target_runtime: String,
    /// RFC-3339 second-precision UTC timestamp
    /// (`YYYY-MM-DDTHH:MM:SSZ`). Lexical sort == chronological sort.
    pub ts_utc: String,
    /// Envelope version; always [`FRAME_ENVELOPE_VERSION`].
    pub version: u32,
}

/// Closed enum of payload kinds the frame parser recognises.
///
/// Adding a new variant requires bumping [`FRAME_ENVELOPE_VERSION`]
/// and a coordinated Rust+Python landing (see
/// [`TODO_PYTHON_FRAME_PARITY_PIN`]).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FederationPayload {
    /// Bridge-forward Auftrag payload. Schema:
    /// [`PAYLOAD_SCHEMA_TASK_ASSIGNED`]. The inner `data` map carries
    /// the bridge-forward envelope fields per
    /// `wirelang/specs/bridge-forward-pipe-v1.md` §3.
    TaskAssigned {
        /// Payload-kind-specific JSON tree (free-form per the
        /// task-assigned schema; preserves unknown keys).
        data: BTreeMap<String, serde_json::Value>,
    },
    /// Persona task-output payload. Schema:
    /// [`PAYLOAD_SCHEMA_TASK_OUTPUT`]. Inner `data` mirrors the
    /// output-side envelope the Wakir-Runtime persona-engine emits.
    TaskOutput {
        /// Payload-kind-specific JSON tree (free-form per the
        /// task-output schema; preserves unknown keys).
        data: BTreeMap<String, serde_json::Value>,
    },
    /// Multi-org attestation pointer. Schema:
    /// [`PAYLOAD_SCHEMA_MULTI_ORG_ATTESTATION`]. Inner `data`
    /// mirrors the fields of `MultiOrgRouteAttestation` in
    /// `wirelang/federation/multi_org_substrate.py`.
    MultiOrgAttestation {
        /// Payload-kind-specific JSON tree.
        data: BTreeMap<String, serde_json::Value>,
    },
    /// SPIFFE trust-bundle sync notice. Schema:
    /// [`PAYLOAD_SCHEMA_SPIFFE_BUNDLE_SYNC`]. Carries `peer_trust_domain`,
    /// `peer_trust_bundle_url`, and a freshness timestamp.
    SpiffeBundleSync {
        /// Payload-kind-specific JSON tree.
        data: BTreeMap<String, serde_json::Value>,
    },
}

impl FederationPayload {
    /// Return the schema tag for this payload kind.
    pub fn schema(&self) -> &'static str {
        match self {
            FederationPayload::TaskAssigned { .. } => PAYLOAD_SCHEMA_TASK_ASSIGNED,
            FederationPayload::TaskOutput { .. } => PAYLOAD_SCHEMA_TASK_OUTPUT,
            FederationPayload::MultiOrgAttestation { .. } => {
                PAYLOAD_SCHEMA_MULTI_ORG_ATTESTATION
            }
            FederationPayload::SpiffeBundleSync { .. } => PAYLOAD_SCHEMA_SPIFFE_BUNDLE_SYNC,
        }
    }

    /// Return the payload-kind wire tag (`"task-assigned"` etc.).
    pub fn kind(&self) -> &'static str {
        match self {
            FederationPayload::TaskAssigned { .. } => "task-assigned",
            FederationPayload::TaskOutput { .. } => "task-output",
            FederationPayload::MultiOrgAttestation { .. } => "multi-org-attestation",
            FederationPayload::SpiffeBundleSync { .. } => "spiffe-bundle-sync",
        }
    }

    /// Borrow the inner data map for inspection.
    pub fn data(&self) -> &BTreeMap<String, serde_json::Value> {
        match self {
            FederationPayload::TaskAssigned { data }
            | FederationPayload::TaskOutput { data }
            | FederationPayload::MultiOrgAttestation { data }
            | FederationPayload::SpiffeBundleSync { data } => data,
        }
    }
}

// ---------------------------------------------------------------------
// Wire shape (serde-facing intermediate).
// ---------------------------------------------------------------------

/// Wire-side intermediate that serde maps to/from JSON. Field order
/// matches lexical JSON key order; serde_jcs will re-sort anyway, but
/// keeping the order aligned lets a reader visually verify the
/// fixture bytes without re-sorting in their head.
#[derive(Debug, Clone, Serialize, Deserialize)]
struct WireFrame {
    #[serde(skip_serializing_if = "Option::is_none")]
    anchor_ref: Option<String>,
    header: WireHeader,
    payload: WirePayload,
    #[serde(skip_serializing_if = "Option::is_none")]
    signature: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct WireHeader {
    frame_id: String,
    schema: String,
    source_runtime: String,
    target_runtime: String,
    ts_utc: String,
    version: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct WirePayload {
    /// One of: `"task-assigned"`, `"task-output"`,
    /// `"multi-org-attestation"`, `"spiffe-bundle-sync"`.
    kind: String,
    /// Payload-kind-specific JSON object. Preserved verbatim (no
    /// re-shaping inside this crate).
    data: serde_json::Value,
    /// Payload-kind schema tag (carries [`PAYLOAD_SCHEMA_*`]). Kept
    /// in the wire shape so the parser can cross-check it against
    /// the [`WirePayload::kind`] string.
    schema: String,
}

// ---------------------------------------------------------------------
// Public API — parse / serialize / helpers.
// ---------------------------------------------------------------------

/// Parse a federation frame from JCS-canonical JSON bytes.
///
/// Performs the following checks (in order):
///
/// 1. UTF-8 decode.
/// 2. JSON decode into the [`WireFrame`] intermediate.
/// 3. Envelope-schema string == [`FRAME_ENVELOPE_SCHEMA`].
/// 4. Envelope version == [`FRAME_ENVELOPE_VERSION`].
/// 5. `ts_utc` matches RFC-3339 second-precision UTC.
/// 6. `frame_id` matches `frame-sha256:<64-hex>`.
/// 7. `source_runtime` / `target_runtime` are non-empty ASCII.
/// 8. `anchor_ref` (if present) matches `wat:<64-hex>`.
/// 9. `signature` (if present) is lower-case hex.
/// 10. `payload.kind` is one of the four recognised variants and
///     `payload.schema` matches the kind-implied schema tag.
/// 11. `payload.data` is a JSON object.
/// 12. Total bytes <= [`MAX_FRAME_JCS_BYTES`].
pub fn parse_frame(bytes: &[u8]) -> Result<FederationFrame, ParseError> {
    if bytes.len() > MAX_FRAME_JCS_BYTES {
        return Err(ParseError::FrameTooLarge {
            bytes: bytes.len(),
            max: MAX_FRAME_JCS_BYTES,
        });
    }
    let _utf8 = std::str::from_utf8(bytes)
        .map_err(|e| ParseError::BadUtf8(e.to_string()))?;
    let wire: WireFrame = serde_json::from_slice(bytes)
        .map_err(|e| ParseError::BadJson(e.to_string()))?;

    if wire.header.schema != FRAME_ENVELOPE_SCHEMA {
        return Err(ParseError::UnknownSchema {
            field: "header.schema",
            value: wire.header.schema,
        });
    }
    if wire.header.version != FRAME_ENVELOPE_VERSION {
        return Err(ParseError::UnsupportedVersion(wire.header.version));
    }
    validate_timestamp_shape(&wire.header.ts_utc)?;
    validate_frame_id_shape(&wire.header.frame_id)?;
    validate_runtime_id("source_runtime", &wire.header.source_runtime)?;
    validate_runtime_id("target_runtime", &wire.header.target_runtime)?;
    if let Some(ref a) = wire.anchor_ref {
        validate_anchor_ref_shape(a)?;
    }
    if let Some(ref s) = wire.signature {
        validate_signature_shape(s)?;
    }

    let data_obj = match wire.payload.data {
        serde_json::Value::Object(map) => map,
        _ => return Err(ParseError::PayloadDataNotObject),
    };
    let data_btree: BTreeMap<String, serde_json::Value> =
        data_obj.into_iter().collect();

    let payload = match wire.payload.kind.as_str() {
        "task-assigned" => {
            if wire.payload.schema != PAYLOAD_SCHEMA_TASK_ASSIGNED {
                return Err(ParseError::UnknownSchema {
                    field: "payload.schema",
                    value: wire.payload.schema,
                });
            }
            FederationPayload::TaskAssigned { data: data_btree }
        }
        "task-output" => {
            if wire.payload.schema != PAYLOAD_SCHEMA_TASK_OUTPUT {
                return Err(ParseError::UnknownSchema {
                    field: "payload.schema",
                    value: wire.payload.schema,
                });
            }
            FederationPayload::TaskOutput { data: data_btree }
        }
        "multi-org-attestation" => {
            if wire.payload.schema != PAYLOAD_SCHEMA_MULTI_ORG_ATTESTATION {
                return Err(ParseError::UnknownSchema {
                    field: "payload.schema",
                    value: wire.payload.schema,
                });
            }
            FederationPayload::MultiOrgAttestation { data: data_btree }
        }
        "spiffe-bundle-sync" => {
            if wire.payload.schema != PAYLOAD_SCHEMA_SPIFFE_BUNDLE_SYNC {
                return Err(ParseError::UnknownSchema {
                    field: "payload.schema",
                    value: wire.payload.schema,
                });
            }
            FederationPayload::SpiffeBundleSync { data: data_btree }
        }
        other => return Err(ParseError::UnknownPayloadKind(other.to_string())),
    };

    Ok(FederationFrame {
        anchor_ref: wire.anchor_ref,
        header: FrameHeader {
            frame_id: wire.header.frame_id,
            schema: wire.header.schema,
            source_runtime: wire.header.source_runtime,
            target_runtime: wire.header.target_runtime,
            ts_utc: wire.header.ts_utc,
            version: wire.header.version,
        },
        payload,
        signature: wire.signature,
    })
}

/// Serialise a federation frame to JCS-canonical JSON bytes.
///
/// Performs the inverse of [`parse_frame`]. The output is guaranteed
/// to be RFC-8785 canonical: `serialize_frame(parse_frame(b)?) == b`
/// is the round-trip invariant the smoke-test suite pins for every
/// fixture.
pub fn serialize_frame(frame: &FederationFrame) -> Result<Vec<u8>, ParseError> {
    // Re-validate the header surface so we can never emit a frame
    // that would fail [`parse_frame`].
    if frame.header.schema != FRAME_ENVELOPE_SCHEMA {
        return Err(ParseError::UnknownSchema {
            field: "header.schema",
            value: frame.header.schema.clone(),
        });
    }
    if frame.header.version != FRAME_ENVELOPE_VERSION {
        return Err(ParseError::UnsupportedVersion(frame.header.version));
    }
    validate_timestamp_shape(&frame.header.ts_utc)?;
    validate_frame_id_shape(&frame.header.frame_id)?;
    validate_runtime_id("source_runtime", &frame.header.source_runtime)?;
    validate_runtime_id("target_runtime", &frame.header.target_runtime)?;
    if let Some(ref a) = frame.anchor_ref {
        validate_anchor_ref_shape(a)?;
    }
    if let Some(ref s) = frame.signature {
        validate_signature_shape(s)?;
    }

    let wire = WireFrame {
        anchor_ref: frame.anchor_ref.clone(),
        header: WireHeader {
            frame_id: frame.header.frame_id.clone(),
            schema: frame.header.schema.clone(),
            source_runtime: frame.header.source_runtime.clone(),
            target_runtime: frame.header.target_runtime.clone(),
            ts_utc: frame.header.ts_utc.clone(),
            version: frame.header.version,
        },
        payload: WirePayload {
            kind: frame.payload.kind().to_string(),
            data: serde_json::Value::Object(
                frame.payload.data().clone().into_iter().collect(),
            ),
            schema: frame.payload.schema().to_string(),
        },
        signature: frame.signature.clone(),
    };

    let value = serde_json::to_value(&wire)
        .map_err(|e| ParseError::JcsFailure(e.to_string()))?;
    let jcs = serde_jcs::to_vec(&value)
        .map_err(|e| ParseError::JcsFailure(e.to_string()))?;

    if jcs.len() > MAX_FRAME_JCS_BYTES {
        return Err(ParseError::FrameTooLarge {
            bytes: jcs.len(),
            max: MAX_FRAME_JCS_BYTES,
        });
    }
    Ok(jcs)
}

/// Derive a deterministic frame identifier from a caller-supplied
/// seed. The seed is canonicalised verbatim (no JCS applied) and
/// hashed with SHA-256; the hex tail is prefixed with
/// [`FRAME_ID_PREFIX`].
///
/// A typical seed is the concatenation of source_runtime + ts_utc +
/// payload-content-hash, but the choice is caller-owned. Two callers
/// that derive the seed the same way will produce the same
/// `frame_id`; that is the only invariant this function exposes.
pub fn compute_frame_id(seed: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(seed);
    let digest = hasher.finalize();
    format!("{}{}", FRAME_ID_PREFIX, hex::encode(digest))
}

/// Build the byte slice the external signer hashes when producing the
/// `signature` field. The slice is the JCS-canonical bytes of the
/// `{header, payload}` subtree (anchor_ref and signature are NOT
/// included in the signing input — they are out-of-signature side
/// channels).
///
/// Returns [`ParseError::JcsFailure`] if canonicalisation fails;
/// callers may treat that as a programmer error.
pub fn signing_payload_bytes(frame: &FederationFrame) -> Result<Vec<u8>, ParseError> {
    let signing_wire = SigningSubtree {
        header: WireHeader {
            frame_id: frame.header.frame_id.clone(),
            schema: frame.header.schema.clone(),
            source_runtime: frame.header.source_runtime.clone(),
            target_runtime: frame.header.target_runtime.clone(),
            ts_utc: frame.header.ts_utc.clone(),
            version: frame.header.version,
        },
        payload: WirePayload {
            kind: frame.payload.kind().to_string(),
            data: serde_json::Value::Object(
                frame.payload.data().clone().into_iter().collect(),
            ),
            schema: frame.payload.schema().to_string(),
        },
    };
    let value = serde_json::to_value(&signing_wire)
        .map_err(|e| ParseError::JcsFailure(e.to_string()))?;
    serde_jcs::to_vec(&value).map_err(|e| ParseError::JcsFailure(e.to_string()))
}

#[derive(Debug, Clone, Serialize)]
struct SigningSubtree {
    header: WireHeader,
    payload: WirePayload,
}

// ---------------------------------------------------------------------
// Validators.
// ---------------------------------------------------------------------

/// RFC-3339 second-precision UTC: `YYYY-MM-DDTHH:MM:SSZ` (20 chars,
/// `T` at index 10, `Z` at the end, digits/colons/dashes elsewhere).
fn validate_timestamp_shape(s: &str) -> Result<(), ParseError> {
    if s.len() != 20 {
        return Err(ParseError::BadTimestampShape(s.to_string()));
    }
    let b = s.as_bytes();
    if b[10] != b'T' || b[19] != b'Z' {
        return Err(ParseError::BadTimestampShape(s.to_string()));
    }
    let expect_digit = |i: usize| b[i].is_ascii_digit();
    // YYYY
    if !(expect_digit(0) && expect_digit(1) && expect_digit(2) && expect_digit(3)) {
        return Err(ParseError::BadTimestampShape(s.to_string()));
    }
    // -MM-
    if b[4] != b'-' || !expect_digit(5) || !expect_digit(6) || b[7] != b'-' {
        return Err(ParseError::BadTimestampShape(s.to_string()));
    }
    // DD
    if !expect_digit(8) || !expect_digit(9) {
        return Err(ParseError::BadTimestampShape(s.to_string()));
    }
    // HH:MM:SS
    if !expect_digit(11) || !expect_digit(12) || b[13] != b':' {
        return Err(ParseError::BadTimestampShape(s.to_string()));
    }
    if !expect_digit(14) || !expect_digit(15) || b[16] != b':' {
        return Err(ParseError::BadTimestampShape(s.to_string()));
    }
    if !expect_digit(17) || !expect_digit(18) {
        return Err(ParseError::BadTimestampShape(s.to_string()));
    }
    Ok(())
}

/// `frame-sha256:` + 64 lower-case hex chars.
fn validate_frame_id_shape(s: &str) -> Result<(), ParseError> {
    if !s.starts_with(FRAME_ID_PREFIX) {
        return Err(ParseError::BadFrameIdShape(s.to_string()));
    }
    let tail = &s[FRAME_ID_PREFIX.len()..];
    if tail.len() != SHA256_HEX_LEN {
        return Err(ParseError::BadFrameIdShape(s.to_string()));
    }
    if !tail.bytes().all(|c| matches!(c, b'0'..=b'9' | b'a'..=b'f')) {
        return Err(ParseError::BadFrameIdShape(s.to_string()));
    }
    Ok(())
}

/// `wat:` + 64 lower-case hex chars.
fn validate_anchor_ref_shape(s: &str) -> Result<(), ParseError> {
    if !s.starts_with(ANCHOR_REF_PREFIX) {
        return Err(ParseError::BadAnchorRefShape(s.to_string()));
    }
    let tail = &s[ANCHOR_REF_PREFIX.len()..];
    if tail.len() != SHA256_HEX_LEN {
        return Err(ParseError::BadAnchorRefShape(s.to_string()));
    }
    if !tail.bytes().all(|c| matches!(c, b'0'..=b'9' | b'a'..=b'f')) {
        return Err(ParseError::BadAnchorRefShape(s.to_string()));
    }
    Ok(())
}

/// Signature: non-empty lower-case hex string. Length is signer-
/// specific (ed25519 = 128 hex chars, but we leave that to the signer
/// crate and only enforce the hex shape here).
fn validate_signature_shape(s: &str) -> Result<(), ParseError> {
    if s.is_empty() {
        return Err(ParseError::BadSignatureShape(s.to_string()));
    }
    if !s.bytes().all(|c| matches!(c, b'0'..=b'9' | b'a'..=b'f')) {
        return Err(ParseError::BadSignatureShape(s.to_string()));
    }
    // Hex strings are always even-length.
    if s.len() % 2 != 0 {
        return Err(ParseError::BadSignatureShape(s.to_string()));
    }
    Ok(())
}

/// Runtime IDs are non-empty printable ASCII (no whitespace, no
/// control characters). The exact shape is operator-chosen
/// (`mira-sandbox`, `wakir-runtime`, `acme/wakir-runtime-eu-west`,
/// …); we enforce only the lower bound.
fn validate_runtime_id(field: &'static str, s: &str) -> Result<(), ParseError> {
    if s.is_empty() {
        return Err(ParseError::BadRuntimeId {
            field,
            value: s.to_string(),
        });
    }
    if !s.bytes().all(|c| (b'!'..=b'~').contains(&c)) {
        return Err(ParseError::BadRuntimeId {
            field,
            value: s.to_string(),
        });
    }
    Ok(())
}

// ---------------------------------------------------------------------
// In-crate unit tests (smoke surface lives in tests/ for visibility).
// ---------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture_header() -> FrameHeader {
        FrameHeader {
            frame_id: format!("{}{}", FRAME_ID_PREFIX, "0".repeat(64)),
            schema: FRAME_ENVELOPE_SCHEMA.to_string(),
            source_runtime: "mira-sandbox".to_string(),
            target_runtime: "wakir-runtime".to_string(),
            ts_utc: "2026-05-17T02:35:00Z".to_string(),
            version: FRAME_ENVELOPE_VERSION,
        }
    }

    fn fixture_data() -> BTreeMap<String, serde_json::Value> {
        let mut m = BTreeMap::new();
        m.insert(
            "auftrag_id".to_string(),
            serde_json::Value::String("sprint-tag-12-mini-9".to_string()),
        );
        m.insert(
            "persona_id".to_string(),
            serde_json::Value::String("reza".to_string()),
        );
        m
    }

    #[test]
    fn validate_timestamp_accepts_canonical_shape() {
        assert!(validate_timestamp_shape("2026-05-17T02:35:00Z").is_ok());
        assert!(validate_timestamp_shape("1970-01-01T00:00:00Z").is_ok());
    }

    #[test]
    fn validate_timestamp_rejects_subsecond() {
        assert!(matches!(
            validate_timestamp_shape("2026-05-17T02:35:00.123Z"),
            Err(ParseError::BadTimestampShape(_))
        ));
    }

    #[test]
    fn validate_timestamp_rejects_offset() {
        assert!(matches!(
            validate_timestamp_shape("2026-05-17T02:35:00+00:00"),
            Err(ParseError::BadTimestampShape(_))
        ));
    }

    #[test]
    fn validate_frame_id_accepts_canonical_shape() {
        let id = format!("{}{}", FRAME_ID_PREFIX, "a".repeat(64));
        assert!(validate_frame_id_shape(&id).is_ok());
    }

    #[test]
    fn validate_frame_id_rejects_uppercase_hex() {
        let id = format!("{}{}", FRAME_ID_PREFIX, "A".repeat(64));
        assert!(matches!(
            validate_frame_id_shape(&id),
            Err(ParseError::BadFrameIdShape(_))
        ));
    }

    #[test]
    fn validate_anchor_ref_accepts_canonical_shape() {
        let a = format!("{}{}", ANCHOR_REF_PREFIX, "f".repeat(64));
        assert!(validate_anchor_ref_shape(&a).is_ok());
    }

    #[test]
    fn validate_signature_rejects_odd_length() {
        assert!(matches!(
            validate_signature_shape("abc"),
            Err(ParseError::BadSignatureShape(_))
        ));
    }

    #[test]
    fn payload_kind_and_schema_are_in_lockstep() {
        let p = FederationPayload::TaskAssigned {
            data: fixture_data(),
        };
        assert_eq!(p.kind(), "task-assigned");
        assert_eq!(p.schema(), PAYLOAD_SCHEMA_TASK_ASSIGNED);

        let p = FederationPayload::TaskOutput {
            data: fixture_data(),
        };
        assert_eq!(p.kind(), "task-output");
        assert_eq!(p.schema(), PAYLOAD_SCHEMA_TASK_OUTPUT);

        let p = FederationPayload::MultiOrgAttestation {
            data: fixture_data(),
        };
        assert_eq!(p.kind(), "multi-org-attestation");
        assert_eq!(p.schema(), PAYLOAD_SCHEMA_MULTI_ORG_ATTESTATION);

        let p = FederationPayload::SpiffeBundleSync {
            data: fixture_data(),
        };
        assert_eq!(p.kind(), "spiffe-bundle-sync");
        assert_eq!(p.schema(), PAYLOAD_SCHEMA_SPIFFE_BUNDLE_SYNC);
    }

    #[test]
    fn compute_frame_id_is_deterministic() {
        let a = compute_frame_id(b"seed-A");
        let b = compute_frame_id(b"seed-A");
        let c = compute_frame_id(b"seed-B");
        assert_eq!(a, b);
        assert_ne!(a, c);
        assert!(a.starts_with(FRAME_ID_PREFIX));
        assert_eq!(a.len(), FRAME_ID_PREFIX.len() + SHA256_HEX_LEN);
    }

    #[test]
    fn roundtrip_task_assigned_minimal() {
        let frame = FederationFrame {
            anchor_ref: None,
            header: fixture_header(),
            payload: FederationPayload::TaskAssigned {
                data: fixture_data(),
            },
            signature: None,
        };
        let bytes = serialize_frame(&frame).unwrap();
        let parsed = parse_frame(&bytes).unwrap();
        assert_eq!(parsed, frame);
    }
}
