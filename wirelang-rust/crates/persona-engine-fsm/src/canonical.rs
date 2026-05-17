// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Tag-21 canonical-trace surface for the persona-engine FSM.
//
// This module is the Rust authority for the JCS-canonical lifecycle
// trace wire-shape; the Python sibling lives at
// `wirelang/persona_engine/lifecycle_state_machine_canonical.py` and
// matches this module byte-for-byte for the five fixture vectors in
// `tests/fixtures/lifecycle-state-machine-cross-lang/fixtures.json`.
//
// Wire-shape contract (six top-level alphabetical keys)
// ------------------------------------------------------
//
//   - `final_state`   : lower-case state wire-string of the FSM
//                       after the last accepted transition (or
//                       `initial_state` if no accepted record).
//   - `initial_state` : lower-case state wire-string of the FSM
//                       at the start of the recorded session.
//   - `org_id`        : owned string.
//   - `persona_id`    : owned string.
//   - `records`       : ordered array of record objects (see below).
//   - `schema`        : constant `LIFECYCLE_TRACE_SCHEMA`.
//
// Record-wire-shape (four keys for accepted records, five for
// rejected, alphabetical):
//
//   - `accepted`   : bool.
//   - `from_state` : wire-string.
//   - `reason`     : string. Omitted when `None` / accepted records
//                    (`#[serde(skip_serializing_if = "Option::is_none")]`).
//   - `to_state`   : wire-string.
//   - `ts_utc`     : RFC-3339 second-precision UTC string.
//
// Note: this module deliberately uses `TransitionRecordWire` (a wire
// projection) instead of the existing `TransitionRecord` from lib.rs
// for the canonical-trace serialisation. The existing
// `TransitionRecord` already serialises with the same field set, but
// the wire projection lets us pin the field-order explicitly
// (`accepted, from_state, reason, to_state, ts_utc`) so a future
// reordering of `TransitionRecord` struct-fields does not leak into
// the cross-lang wire form. `serde_jcs` would re-sort regardless,
// but pinning the wire struct keeps the source-level layout
// readable and matches the explicit dict construction on the
// Python side.

use crate::{FsmState, PersonaFsm, TransitionRecord, STATES};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

// ---------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------

/// Schema identifier emitted on every lifecycle-trace canonical form.
/// Byte-for-byte equal to the Python `LIFECYCLE_TRACE_SCHEMA`
/// constant. Bump only when a wire-shape change is intentional.
pub const LIFECYCLE_TRACE_SCHEMA: &str = "wakir.persona-engine.lifecycle-trace/1";

/// Hash prefix string (matches the sibling pattern from
/// `subscribe_ack` / `anchor_emitter`).
pub const HASH_PREFIX: &str = "sha256:";

/// Length of a bare-hex SHA-256 digest (no prefix).
pub const SHA256_HEX_LEN: usize = 64;

// ---------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------

/// Error surface for caller-supplied input that fails the Tag-21
/// shape pre-conditions. Mirrors `LifecycleTraceError` on the
/// Python side.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LifecycleTraceError {
    /// `initial_state` was a string outside [`STATES`].
    UnknownInitialState(String),
}

impl std::fmt::Display for LifecycleTraceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LifecycleTraceError::UnknownInitialState(s) => write!(
                f,
                "unknown initial_state {:?}; valid: {:?}",
                s,
                STATES
                    .iter()
                    .map(|s| s.as_wire_str())
                    .collect::<Vec<_>>()
            ),
        }
    }
}

impl std::error::Error for LifecycleTraceError {}

// ---------------------------------------------------------------------
// Wire structs (deliberately public so callers can build & inspect
// in-process; the canonical bytes are produced by `serialize_trace`)
// ---------------------------------------------------------------------

/// Wire-projection of a single [`TransitionRecord`]. Mirrors the
/// Python `_record_to_wire_dict` output exactly.
///
/// Field order is alphabetical to keep the source-level layout
/// matching the JCS-canonical key order even though `serde_jcs` will
/// re-sort regardless. `reason` is `#[serde(skip_serializing_if =
/// "Option::is_none")]` to match the Python `if reason is not None`
/// guard.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TransitionRecordWire {
    /// `true` if the transition was applied, `false` if rejected.
    pub accepted: bool,
    /// State the machine was in when the attempt happened
    /// (wire-string form).
    pub from_state: String,
    /// Free-form rejection reason. Omitted from the wire for
    /// accepted records (matches Python `Optional[str] = None`
    /// default-omit semantics).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    /// Target state the caller requested (wire-string form).
    pub to_state: String,
    /// RFC 3339 UTC second-precision timestamp of the attempt.
    pub ts_utc: String,
}

impl TransitionRecordWire {
    /// Project a typed [`TransitionRecord`] onto its wire form.
    pub fn from_record(rec: &TransitionRecord) -> Self {
        Self {
            accepted: rec.accepted,
            from_state: rec.from_state.as_wire_str().to_string(),
            reason: rec.reason.clone(),
            to_state: rec.to_state.as_wire_str().to_string(),
            ts_utc: rec.ts_utc.clone(),
        }
    }
}

/// The Tag-21 canonical-trace wire-shape. Six alphabetically-ordered
/// fields. Construct via [`LifecycleTrace::from_fsm`] /
/// [`LifecycleTrace::from_records`] (or the free-standing
/// [`build_lifecycle_trace_from_records`] for fixture builders).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LifecycleTrace {
    /// Wire-string of the FSM state after the last accepted
    /// transition (or `initial_state` if no record is accepted).
    pub final_state: String,
    /// Wire-string of the FSM state at the start of the recorded
    /// session.
    pub initial_state: String,
    /// Org identifier the machine tracks.
    pub org_id: String,
    /// Persona identifier the machine tracks.
    pub persona_id: String,
    /// Ordered list of transition record wire-projections.
    pub records: Vec<TransitionRecordWire>,
    /// Schema identifier; constant [`LIFECYCLE_TRACE_SCHEMA`].
    pub schema: String,
}

impl LifecycleTrace {
    /// Build a trace from a live [`PersonaFsm`]. The `initial_state`
    /// defaults to [`FsmState::Uninstantiated`] when `None`; callers
    /// that constructed the FSM with [`PersonaFsm::with_initial_state`]
    /// SHOULD pass the actual session start so the trace's
    /// `initial_state` field reflects it.
    pub fn from_fsm(
        machine: &PersonaFsm,
        initial_state: Option<FsmState>,
    ) -> Self {
        let initial = initial_state.unwrap_or(FsmState::Uninstantiated);
        Self {
            final_state: machine.state().as_wire_str().to_string(),
            initial_state: initial.as_wire_str().to_string(),
            org_id: machine.org_id().to_string(),
            persona_id: machine.persona_id().to_string(),
            records: machine
                .history_ref()
                .iter()
                .map(TransitionRecordWire::from_record)
                .collect(),
            schema: LIFECYCLE_TRACE_SCHEMA.to_string(),
        }
    }

    /// Build a trace from an explicit records list. Lenient: does
    /// NOT re-validate the records against [`crate::VALID_TRANSITIONS`]
    /// so fixture builders can pin synthetic corrupted-trail cases.
    /// Use [`PersonaFsm::replay`] first if you want the replay
    /// guards. Returns
    /// [`LifecycleTraceError::UnknownInitialState`] when
    /// `initial_state` is outside [`STATES`].
    pub fn from_records(
        persona_id: impl Into<String>,
        org_id: impl Into<String>,
        initial_state: &str,
        records: &[TransitionRecord],
    ) -> Result<Self, LifecycleTraceError> {
        // Validate initial_state.
        if FsmState::from_wire_str(initial_state).is_err() {
            return Err(LifecycleTraceError::UnknownInitialState(
                initial_state.to_string(),
            ));
        }
        // Walk records to derive final_state. Rejected records do
        // not advance.
        let mut state = initial_state.to_string();
        let mut wire_records = Vec::with_capacity(records.len());
        for rec in records {
            if rec.accepted {
                state = rec.to_state.as_wire_str().to_string();
            }
            wire_records.push(TransitionRecordWire::from_record(rec));
        }
        Ok(Self {
            final_state: state,
            initial_state: initial_state.to_string(),
            org_id: org_id.into(),
            persona_id: persona_id.into(),
            records: wire_records,
            schema: LIFECYCLE_TRACE_SCHEMA.to_string(),
        })
    }
}

// ---------------------------------------------------------------------
// Free-standing helpers (mirroring the Python module surface)
// ---------------------------------------------------------------------

/// Build a [`LifecycleTrace`] from a live FSM. Convenience wrapper
/// around [`LifecycleTrace::from_fsm`].
pub fn build_lifecycle_trace(
    machine: &PersonaFsm,
    initial_state: Option<FsmState>,
) -> LifecycleTrace {
    LifecycleTrace::from_fsm(machine, initial_state)
}

/// Build a [`LifecycleTrace`] from an explicit records list.
/// Convenience wrapper around [`LifecycleTrace::from_records`].
pub fn build_lifecycle_trace_from_records(
    persona_id: impl Into<String>,
    org_id: impl Into<String>,
    initial_state: &str,
    records: &[TransitionRecord],
) -> Result<LifecycleTrace, LifecycleTraceError> {
    LifecycleTrace::from_records(persona_id, org_id, initial_state, records)
}

// ---------------------------------------------------------------------
// Serialisation + hashing
// ---------------------------------------------------------------------

/// Serialise a [`LifecycleTrace`] to RFC 8785 JCS-canonical bytes.
/// Byte-for-byte equal to the Python `serialize_lifecycle_trace`
/// output for the same logical input.
pub fn serialize_trace(trace: &LifecycleTrace) -> Vec<u8> {
    // serde_jcs::to_vec returns canonical bytes per RFC 8785. The
    // only failure mode is a serialisation error in serde itself,
    // which cannot happen for our flat LifecycleTrace + flat
    // TransitionRecordWire structs (all owned strings, bool, vec).
    serde_jcs::to_vec(trace).expect(
        "LifecycleTrace is a flat owned-string struct; \
         serde_jcs::to_vec cannot fail here",
    )
}

/// Lower-case hex SHA-256 digest of `payload`.
pub fn sha256_hex(payload: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(payload);
    let digest = hasher.finalize();
    hex::encode(digest)
}

/// Bare lower-case hex SHA-256 of the JCS-canonical bytes of a
/// trace.
pub fn trace_sha256_hex(trace: &LifecycleTrace) -> String {
    sha256_hex(&serialize_trace(trace))
}

/// Prefixed-form SHA-256 (`"sha256:" + bare_hex`) of the
/// JCS-canonical bytes of a trace.
pub fn trace_hash_prefixed(trace: &LifecycleTrace) -> String {
    let bare = trace_sha256_hex(trace);
    let mut out = String::with_capacity(HASH_PREFIX.len() + SHA256_HEX_LEN);
    out.push_str(HASH_PREFIX);
    out.push_str(&bare);
    out
}

/// One-shot helper: return `(canonical_bytes, prefixed_hash)` in a
/// single canonicalisation pass.
pub fn serialize_and_hash(trace: &LifecycleTrace) -> (Vec<u8>, String) {
    let bytes = serialize_trace(trace);
    let mut prefixed = String::with_capacity(HASH_PREFIX.len() + SHA256_HEX_LEN);
    prefixed.push_str(HASH_PREFIX);
    prefixed.push_str(&sha256_hex(&bytes));
    (bytes, prefixed)
}

// ---------------------------------------------------------------------
// Library-internal unit tests for the canonical-trace surface
// ---------------------------------------------------------------------

#[cfg(test)]
mod canonical_tests {
    use super::*;
    use crate::PersonaFsm;

    fn fixed_clock() -> String {
        "2026-05-17T00:00:00Z".to_string()
    }

    #[test]
    fn schema_constant_pin() {
        assert_eq!(
            LIFECYCLE_TRACE_SCHEMA,
            "wakir.persona-engine.lifecycle-trace/1"
        );
        assert_eq!(HASH_PREFIX, "sha256:");
        assert_eq!(SHA256_HEX_LEN, 64);
    }

    #[test]
    fn empty_trace_is_deterministic() {
        let m = PersonaFsm::new("reza", "wakir-labs").with_clock(fixed_clock);
        let t = LifecycleTrace::from_fsm(&m, None);
        let bytes = serialize_trace(&t);
        // Same byte-string the Python sibling pins in T16.
        assert_eq!(
            std::str::from_utf8(&bytes).unwrap(),
            r#"{"final_state":"uninstantiated","initial_state":"uninstantiated","org_id":"wakir-labs","persona_id":"reza","records":[],"schema":"wakir.persona-engine.lifecycle-trace/1"}"#
        );
    }

    #[test]
    fn unknown_initial_state_is_rejected() {
        let err = LifecycleTrace::from_records(
            "reza",
            "wakir-labs",
            "zombie",
            &[],
        )
        .expect_err("unknown state must be rejected");
        match err {
            LifecycleTraceError::UnknownInitialState(s) => assert_eq!(s, "zombie"),
        }
    }

    #[test]
    fn record_wire_omits_reason_for_accepted() {
        let m = PersonaFsm::new("reza", "wakir-labs").with_clock(fixed_clock);
        let mut m = m;
        m.transition(FsmState::Spawning).unwrap();
        let t = LifecycleTrace::from_fsm(&m, None);
        let text = std::str::from_utf8(&serialize_trace(&t)).unwrap().to_string();
        assert!(!text.contains("\"reason\":null"));
    }

    #[test]
    fn record_wire_keeps_reason_for_rejected() {
        let m = PersonaFsm::new("reza", "wakir-labs").with_clock(fixed_clock);
        let mut m = m;
        let _ = m.transition(FsmState::Running); // rejected
        let t = LifecycleTrace::from_fsm(&m, None);
        let text = std::str::from_utf8(&serialize_trace(&t)).unwrap().to_string();
        assert!(text.contains("\"reason\":\"not_in_valid_transitions\""));
    }
}
