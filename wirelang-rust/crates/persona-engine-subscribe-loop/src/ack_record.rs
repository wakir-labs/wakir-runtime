// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors

//! Subscribe-Loop ack-record substrate (Tag-19 Mini-Welle).
//!
//! This module is the Rust pendant of the Python sibling
//! `wirelang.persona_engine.subscribe_ack` (PR shipped with this
//! commit). Both sides emit a byte-identical JCS-canonical
//! `SubscribeAckRecord` per inbound NATS frame so the Phase-3a
//! 3-way-triangle (Doppelbetrieb-Vergleich) can diff Python-side and
//! Rust-side subscribe-acks byte-for-byte.
//!
//! # Why a separate module?
//!
//! The `run_subscribe_loop` driver in this crate produces a
//! `SubscribeLoopState` snapshot (lag, processed-count,
//! last-message-at). That snapshot is **per-loop**, not **per-frame**.
//! The Tag-19 cross-lang parity contract is **per-frame**: one
//! deterministic ack-record per inbound frame, regardless of whether
//! the engine ran in core-callback, iterator, or JetStream-pull mode.
//! Keeping the ack-record substrate in its own module preserves the
//! existing loop's contract while adding the new per-frame surface
//! cleanly.
//!
//! # Schema
//!
//! The record carries exactly seven fields (alphabetically sorted in
//! the canonical form):
//!
//! - `auftrag_id` — Bridge-Forward-Pipe envelope auftrag_id, or `""`
//!   for malformed/unparsable frames.
//! - `frame_index` — Monotonic 0-based index within the ack-burst.
//! - `outcome` — One of: `"processed"`, `"malformed"`,
//!   `"persona_mismatch"`, `"rejected"`, `"empty_payload"`.
//! - `persona_id` — Envelope persona_id, or `""` for malformed.
//! - `prompt_sha256` — Envelope prompt_sha256 (with `sha256:` prefix).
//! - `schema` — Constant `"wakir.persona-engine.subscribe-ack/1"`.
//! - `subject` — Inbound NATS subject the frame arrived on.
//!
//! # Serialization
//!
//! The canonical form is JSON with sorted keys, no whitespace, UTF-8.
//! The implementation uses `serde_json::Map` with explicit insertion
//! in alphabetical order to match the Python `json.dumps(sort_keys=True,
//! separators=(",",":"), ensure_ascii=False)` byte-for-byte. The five
//! fixture vectors in `tests/fixtures/subscribe-loop-cross-lang/
//! fixtures.json` pin this contract.
//!
//! # ADR anchors
//!
//! - ADR-0063 §Folgeartefakte Phase-3a Item 4 + Tag-19 Python-sync.
//! - Selin PR #79  (Python subscribe-loop schema authority).
//! - Selin PR #113 (3-way-triangle Doppelbetrieb).
//! - Reza  PR #132 (Rust subscribe-loop scaffold; this crate).
//! - Reza  PR #170 (Tag-18 anchor-emitter Python-sync pattern).

use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

/// Schema identifier emitted on every subscribe-ack record.
/// Parity with Python `ACK_RECORD_SCHEMA`.
pub const ACK_RECORD_SCHEMA: &str = "wakir.persona-engine.subscribe-ack/1";

/// Prefix used by the prefixed-form hash (matches BridgeAuditWriter
/// and `persona-engine-anchor-emitter`).
pub const HASH_PREFIX: &str = "sha256:";

/// Length of a bare-hex SHA-256 digest (no prefix).
pub const SHA256_HEX_LEN: usize = 64;

/// Outcome literal: frame was parsed, handler returned Ok.
pub const OUTCOME_PROCESSED: &str = "processed";

/// Outcome literal: frame failed envelope parsing.
pub const OUTCOME_MALFORMED: &str = "malformed";

/// Outcome literal: envelope persona_id did not match the
/// configured persona_slug.
pub const OUTCOME_PERSONA_MISMATCH: &str = "persona_mismatch";

/// Outcome literal: handler returned Err.
pub const OUTCOME_REJECTED: &str = "rejected";

/// Outcome literal: inbound payload was empty.
pub const OUTCOME_EMPTY_PAYLOAD: &str = "empty_payload";

/// All five valid outcome literals.
pub const VALID_OUTCOMES: [&str; 5] = [
    OUTCOME_PROCESSED,
    OUTCOME_MALFORMED,
    OUTCOME_PERSONA_MISMATCH,
    OUTCOME_REJECTED,
    OUTCOME_EMPTY_PAYLOAD,
];

// ---------------------------------------------------------------------
// Record + constructor
// ---------------------------------------------------------------------

/// Immutable per-frame subscribe-ack record (Rust pendant of the
/// Python `SubscribeAckRecord` dataclass).
///
/// All fields are public for easy fixture-test construction; the
/// canonical serialisation is done via [`serialize_ack`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SubscribeAckRecord {
    pub auftrag_id: String,
    pub frame_index: u64,
    pub outcome: String,
    pub persona_id: String,
    pub prompt_sha256: String,
    pub schema: String,
    pub subject: String,
}

/// Validation errors raised by [`build_ack_record`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AckRecordError {
    /// The `outcome` string is not one of [`VALID_OUTCOMES`].
    InvalidOutcome(String),
}

impl std::fmt::Display for AckRecordError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AckRecordError::InvalidOutcome(o) => {
                write!(f, "outcome must be one of {:?}, got {:?}", VALID_OUTCOMES, o)
            }
        }
    }
}

impl std::error::Error for AckRecordError {}

/// Construct an ack-record with strict validation.
///
/// Parity with Python `build_subscribe_ack_record`:
///
/// - `frame_index` is typed as `u64`, so the negativity check is
///   compile-time-enforced (the Python sibling validates at runtime).
/// - `outcome` is validated against [`VALID_OUTCOMES`]; an
///   [`AckRecordError::InvalidOutcome`] is returned for any other
///   string. This mirrors the Python `InvalidOutcomeError`.
/// - The `schema` field is set to [`ACK_RECORD_SCHEMA`] and cannot
///   be overridden by callers.
pub fn build_ack_record(
    auftrag_id: &str,
    frame_index: u64,
    outcome: &str,
    persona_id: &str,
    prompt_sha256: &str,
    subject: &str,
) -> Result<SubscribeAckRecord, AckRecordError> {
    if !VALID_OUTCOMES.contains(&outcome) {
        return Err(AckRecordError::InvalidOutcome(outcome.to_string()));
    }
    Ok(SubscribeAckRecord {
        auftrag_id: auftrag_id.to_string(),
        frame_index,
        outcome: outcome.to_string(),
        persona_id: persona_id.to_string(),
        prompt_sha256: prompt_sha256.to_string(),
        schema: ACK_RECORD_SCHEMA.to_string(),
        subject: subject.to_string(),
    })
}

// ---------------------------------------------------------------------
// JCS-canonical serialisation
// ---------------------------------------------------------------------

/// Serialise an ack-record to JCS-canonical UTF-8 bytes.
///
/// The canonical form is:
///
/// - Keys alphabetically sorted (insertion order in the Map below
///   is explicit alphabetical).
/// - No whitespace (`,` / `:` separators only).
/// - Unicode pass-through (no `\\uXXXX` escaping).
/// - UTF-8 encoded.
///
/// Parity with the Python sibling: the byte output of this function
/// must equal the byte output of the Python
/// `serialize_subscribe_ack(record)` for every fixture in the
/// cross-lang JSON file.
///
/// Implementation note: `serde_json::to_vec` preserves the
/// insertion order of a `Map<String, Value>`. We insert in
/// alphabetical order explicitly so we do not depend on a
/// `BTreeMap`-style auto-sort feature.
pub fn serialize_ack(record: &SubscribeAckRecord) -> Vec<u8> {
    let mut map: Map<String, Value> = Map::new();
    map.insert(
        "auftrag_id".to_string(),
        Value::String(record.auftrag_id.clone()),
    );
    map.insert(
        "frame_index".to_string(),
        Value::Number(record.frame_index.into()),
    );
    map.insert(
        "outcome".to_string(),
        Value::String(record.outcome.clone()),
    );
    map.insert(
        "persona_id".to_string(),
        Value::String(record.persona_id.clone()),
    );
    map.insert(
        "prompt_sha256".to_string(),
        Value::String(record.prompt_sha256.clone()),
    );
    map.insert(
        "schema".to_string(),
        Value::String(record.schema.clone()),
    );
    map.insert(
        "subject".to_string(),
        Value::String(record.subject.clone()),
    );
    let obj = Value::Object(map);
    // serde_json::to_vec preserves insertion order for Object Values
    // and emits compact separators by default — matches Python
    // `json.dumps(sort_keys=True, separators=(",",":"),
    // ensure_ascii=False)` byte-for-byte for the seven-string-and-int
    // shape this record uses.
    serde_json::to_vec(&obj)
        .expect("ack-record fields are all primitives; serialisation cannot fail")
}

/// Bare-hex SHA-256 digest of the supplied bytes (lowercase, 64 chars).
pub fn sha256_hex(data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data);
    let digest = hasher.finalize();
    let mut hex = String::with_capacity(SHA256_HEX_LEN);
    for b in digest {
        hex.push_str(&format!("{:02x}", b));
    }
    hex
}

/// Bare-hex SHA-256 of the canonical bytes of `record`.
pub fn ack_record_sha256_hex(record: &SubscribeAckRecord) -> String {
    sha256_hex(&serialize_ack(record))
}

/// Prefixed-form (`sha256:<hex>`) SHA-256 of the record bytes.
pub fn ack_record_hash_prefixed(record: &SubscribeAckRecord) -> String {
    let mut out = String::with_capacity(HASH_PREFIX.len() + SHA256_HEX_LEN);
    out.push_str(HASH_PREFIX);
    out.push_str(&ack_record_sha256_hex(record));
    out
}

/// Convenience: return both the canonical bytes and the prefixed
/// hash from a single serialise-pass.
pub fn serialize_and_hash(record: &SubscribeAckRecord) -> (Vec<u8>, String) {
    let bytes = serialize_ack(record);
    let hash = format!("{}{}", HASH_PREFIX, sha256_hex(&bytes));
    (bytes, hash)
}

// ---------------------------------------------------------------------
// Burst helpers (ordered-delivery preservation)
// ---------------------------------------------------------------------

/// Burst-validation errors raised by [`build_ack_burst`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BurstError {
    /// frame_index at position `i` is not equal to `i`.
    NonMonotonicFrameIndex { position: usize, frame_index: u64 },
}

impl std::fmt::Display for BurstError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BurstError::NonMonotonicFrameIndex {
                position,
                frame_index,
            } => write!(
                f,
                "frame_index must be strictly monotonic 0..N-1; \
                 position {} has frame_index={}",
                position, frame_index
            ),
        }
    }
}

impl std::error::Error for BurstError {}

/// Validate that an iterator of records carries strictly monotonic
/// 0-based `frame_index` values; return them as a `Vec`.
///
/// Parity with Python `build_ack_burst`. The burst-list itself is
/// not serialised — the per-record bytes are the cross-lang unit.
pub fn build_ack_burst(
    records: impl IntoIterator<Item = SubscribeAckRecord>,
) -> Result<Vec<SubscribeAckRecord>, BurstError> {
    let mut out: Vec<SubscribeAckRecord> = Vec::new();
    for (i, rec) in records.into_iter().enumerate() {
        if rec.frame_index != i as u64 {
            return Err(BurstError::NonMonotonicFrameIndex {
                position: i,
                frame_index: rec.frame_index,
            });
        }
        out.push(rec);
    }
    Ok(out)
}

/// Serialise each record in iteration order; returns list of byte-vecs.
///
/// Does NOT validate monotonicity (use [`build_ack_burst`] first if
/// monotonicity is part of the contract). Parity with Python
/// `serialize_ack_burst`.
pub fn serialize_ack_burst(
    records: impl IntoIterator<Item = SubscribeAckRecord>,
) -> Vec<Vec<u8>> {
    records.into_iter().map(|r| serialize_ack(&r)).collect()
}

// ---------------------------------------------------------------------
// Engine-side convenience: derive ack-record from parsed envelope
// ---------------------------------------------------------------------

/// Build an ack-record from a parsed envelope (or `None` for malformed).
///
/// Parity with Python `ack_record_from_parsed`. The
/// [`super::ParsedEnvelope`] type lives in the parent module; this
/// helper reads `auftrag_id` / `persona_id` / `prompt_sha256` and
/// fills the empty string for malformed frames.
pub fn ack_record_from_parsed(
    parsed: Option<&super::ParsedEnvelope>,
    frame_index: u64,
    outcome: &str,
    subject: &str,
    fallback_persona_id: &str,
) -> Result<SubscribeAckRecord, AckRecordError> {
    match parsed {
        None => build_ack_record(
            "",
            frame_index,
            outcome,
            fallback_persona_id,
            "",
            subject,
        ),
        Some(p) => build_ack_record(
            &p.auftrag_id,
            frame_index,
            outcome,
            if p.persona_id.is_empty() {
                fallback_persona_id
            } else {
                &p.persona_id
            },
            &p.prompt_sha256,
            subject,
        ),
    }
}

// ---------------------------------------------------------------------
// Inline unit tests (kept tight; cross-lang fixture tests live in
// tests/subscribe_loop_cross_lang_fixture_test.rs).
// ---------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn schema_constants_pin() {
        assert_eq!(ACK_RECORD_SCHEMA, "wakir.persona-engine.subscribe-ack/1");
        assert_eq!(HASH_PREFIX, "sha256:");
        assert_eq!(SHA256_HEX_LEN, 64);
    }

    #[test]
    fn build_validates_outcome() {
        let r = build_ack_record("", 0, "evil", "", "", "subj");
        assert!(matches!(r, Err(AckRecordError::InvalidOutcome(_))));
    }

    #[test]
    fn build_accepts_all_valid_outcomes() {
        for o in VALID_OUTCOMES.iter() {
            let r = build_ack_record("", 0, o, "", "", "subj").expect("valid outcome");
            assert_eq!(r.outcome, *o);
            assert_eq!(r.schema, ACK_RECORD_SCHEMA);
        }
    }

    #[test]
    fn serialise_produces_alphabetical_keys() {
        let rec = build_ack_record(
            "a-1",
            0,
            OUTCOME_PROCESSED,
            "reza",
            "sha256:dead",
            "wakir.dev.agent.agent.task.assigned.reza",
        )
        .unwrap();
        let bytes = serialize_ack(&rec);
        let text = std::str::from_utf8(&bytes).unwrap();
        // Find each key's position and check alphabetical order.
        let keys = [
            "auftrag_id",
            "frame_index",
            "outcome",
            "persona_id",
            "prompt_sha256",
            "schema",
            "subject",
        ];
        let positions: Vec<usize> = keys
            .iter()
            .map(|k| {
                text.find(&format!("\"{}\":", k))
                    .unwrap_or_else(|| panic!("key {} not found in {}", k, text))
            })
            .collect();
        for w in positions.windows(2) {
            assert!(
                w[0] < w[1],
                "keys not alphabetical in JCS output: {:?} -> {}",
                positions,
                text
            );
        }
    }

    #[test]
    fn sha256_hex_known_vector() {
        // Empty input.
        assert_eq!(
            sha256_hex(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        // "abc".
        assert_eq!(
            sha256_hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn ack_record_hash_prefixed_round_trip() {
        let rec = build_ack_record(
            "a-1",
            0,
            OUTCOME_PROCESSED,
            "reza",
            "sha256:dead",
            "subj",
        )
        .unwrap();
        let bare = ack_record_sha256_hex(&rec);
        let prefixed = ack_record_hash_prefixed(&rec);
        assert_eq!(prefixed, format!("sha256:{}", bare));
        let (bytes, hash) = serialize_and_hash(&rec);
        assert_eq!(bytes, serialize_ack(&rec));
        assert_eq!(hash, prefixed);
    }

    #[test]
    fn burst_monotonic_validates() {
        let r0 = build_ack_record("a", 0, OUTCOME_PROCESSED, "reza", "sha256:0", "s").unwrap();
        let r1 = build_ack_record("b", 1, OUTCOME_PROCESSED, "reza", "sha256:1", "s").unwrap();
        let r2 = build_ack_record("c", 2, OUTCOME_PROCESSED, "reza", "sha256:2", "s").unwrap();
        let ok = build_ack_burst([r0.clone(), r1.clone(), r2.clone()]);
        assert!(ok.is_ok());

        // Out-of-order.
        let bad = build_ack_record("z", 7, OUTCOME_PROCESSED, "reza", "sha256:7", "s").unwrap();
        let err = build_ack_burst([r0.clone(), bad]).unwrap_err();
        assert!(matches!(
            err,
            BurstError::NonMonotonicFrameIndex { .. }
        ));
    }

    #[test]
    fn ack_record_from_parsed_malformed_path() {
        let r =
            ack_record_from_parsed(None, 0, OUTCOME_MALFORMED, "subj", "reza")
                .unwrap();
        assert_eq!(r.auftrag_id, "");
        assert_eq!(r.persona_id, "reza");
        assert_eq!(r.prompt_sha256, "");
        assert_eq!(r.outcome, OUTCOME_MALFORMED);
    }
}
