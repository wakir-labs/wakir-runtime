// SPDX-License-Identifier: Apache-2.0
//! Deterministic Bridge-Audit stream-replay engine for the Phase-3a
//! Doppelbetrieb-Bridge consistency drill.
//!
//! Sprint-Bridge-Audit-Replay-Engine-Rust-MINI (ADR-0063 §Folgeartefakte
//! Phase-3a Item 11).
//!
//! Whereas [`persona_engine_bridge_diff`] compares ONE Python envelope
//! against ONE Rust envelope, this crate operates on ORDERED STREAMS of
//! envelopes — the audit-record sequences produced by
//! `wirelang.persona_engine.bridge_audit_writer.BridgeAuditWriter`. The
//! stream-level oracle is what Phase-2 Doppelbetrieb-Konsistenz-Drills
//! consume: replay a recorded session and validate the resulting record
//! sequence against an expected trajectory.
//!
//! Replay contract
//! ---------------
//!
//! [`ReplayEngine::replay_stream`] takes a slice of [`AuditRecord`]s and
//! an [`ExpectedTrajectory`] (the record sequence the session SHOULD
//! produce when replayed deterministically). It returns a [`ReplayReport`]
//! that:
//!
//! - Reports `success = true` iff actual records match expected records
//!   one-for-one (in order, JCS-byte-identical per record).
//! - On divergence, surfaces the FIRST drifting step index plus a list
//!   of all subsequent drift entries (so an operator sees the full
//!   trajectory delta, not just the symptom).
//! - Records `time_to_divergence_steps` — the 0-based step index at
//!   which the first drift surfaces, or `None` on full match. The metric
//!   is monotonic non-decreasing across a successively-corrected stream,
//!   which the test-suite asserts.
//! - Distinguishes three drift kinds: [`DivergenceKind::ValueMismatch`]
//!   (record present on both sides, contents drift),
//!   [`DivergenceKind::MissingInActual`] (expected step has no actual
//!   record — actual stream too short), [`DivergenceKind::ExtraInActual`]
//!   (actual stream has more records than the trajectory expects).
//!
//! Determinism contract
//! --------------------
//!
//! `replay_stream` is pure: same record-slice in -> bit-identical report
//! out. The report's `stream_hash` is `jcs_hash(records-as-array)` —
//! reuses the workspace `serde_jcs` + `sha2` pipeline so the byte-level
//! contract is the same as [`persona_engine_bridge_diff::jcs_hash`].
//! Cross-language anchor pins (see tests) are captured from the Python
//! `EngineeringOutputEvent.to_jcs_bytes()` pipeline.
//!
//! Out of scope (deliberately)
//! ---------------------------
//!
//! - Live capture of audit records from a running engine. The crate
//!   accepts pre-recorded records as input; capture is the writer's job.
//! - Persistence. The report is in-memory only; serialisation is the
//!   caller's concern.
//! - Re-execution of persona logic. "Replay" here means re-walking a
//!   recorded record sequence and validating its shape — not re-running
//!   the persona-engine itself.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use serde::Serialize;
use serde_json::{Map, Value};

use persona_engine_bridge_diff::{diff_envelopes, jcs_hash, BridgeDiffError, FieldDiff};

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/// Error class for the replay engine.
///
/// Currently narrow: any failure originates in JCS canonicalisation of
/// the upstream diff primitive. We re-export rather than re-wrap so
/// downstream `?` propagation stays clean.
#[derive(Debug)]
pub enum ReplayError {
    /// Upstream JCS / hash error from `persona-engine-bridge-diff`.
    Diff(BridgeDiffError),
}

impl std::fmt::Display for ReplayError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ReplayError::Diff(e) => write!(f, "bridge-diff error: {e}"),
        }
    }
}

impl std::error::Error for ReplayError {}

impl From<BridgeDiffError> for ReplayError {
    fn from(e: BridgeDiffError) -> Self {
        ReplayError::Diff(e)
    }
}

// ---------------------------------------------------------------------------
// AuditRecord
// ---------------------------------------------------------------------------

/// One Bridge-Audit record in a replay stream.
///
/// Mirrors `wirelang.persona_engine.bridge_audit_writer.
/// EngineeringOutputEvent` (PR #106 / Sprint-1 Tag-4) field-for-field;
/// the JCS canonical form is byte-identical to the Python pendant's
/// `EngineeringOutputEvent.to_jcs_bytes()`. The field schema is frozen
/// at `wakir.persona.engineering-output/1`.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct AuditRecord {
    /// Organisation identifier (e.g. `"wakir-labs"`).
    pub org_id: String,
    /// Persona identifier (e.g. `"mira"`).
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

/// JCS-canonical envelope schema tag pinned to the Python writer.
///
/// Single-source-of-truth: `wirelang.persona_engine.bridge_audit_writer.
/// ENGINEERING_OUTPUT_SCHEMA`.
pub const ENGINEERING_OUTPUT_SCHEMA: &str = "wakir.persona.engineering-output/1";

/// Constant event-kind tag matching the Python writer envelope.
pub const EVENT_KIND: &str = "engineering_output";

impl AuditRecord {
    /// Return the canonical envelope shape — a `serde_json::Value::Object`
    /// with the same keys (and key order in the source map) as the
    /// Python pendant's `EngineeringOutputEvent.to_jcs_bytes()` inner
    /// dict.
    ///
    /// We do NOT rely on the source map's insertion order for byte
    /// stability — `serde_jcs` re-sorts lexicographically — but emitting
    /// keys in the same order as the Python source keeps source-level
    /// reviews diff-friendly.
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

    /// Convenience: hash this record's canonical envelope (delegates to
    /// the workspace `persona-engine-bridge-diff::jcs_hash`).
    ///
    /// # Errors
    ///
    /// Surfaces [`ReplayError::Diff`] on JCS-canonicaliser failure
    /// (unreachable in practice with well-formed input).
    pub fn jcs_hash(&self) -> Result<String, ReplayError> {
        Ok(jcs_hash(&self.to_envelope())?)
    }
}

// ---------------------------------------------------------------------------
// ExpectedTrajectory
// ---------------------------------------------------------------------------

/// The expected sequence of audit records for a replay.
///
/// A trajectory is a thin newtype around `Vec<AuditRecord>` so the
/// engine can grow trajectory-level metadata (per-step assertions,
/// tolerances) without breaking the call signature.
#[derive(Debug, Clone, Default)]
pub struct ExpectedTrajectory {
    /// The ordered expected records. Index = step.
    pub records: Vec<AuditRecord>,
}

impl ExpectedTrajectory {
    /// Convenience constructor from a record slice.
    #[must_use]
    pub fn from_records(records: &[AuditRecord]) -> Self {
        Self {
            records: records.to_vec(),
        }
    }

    /// Number of expected records.
    #[must_use]
    pub fn len(&self) -> usize {
        self.records.len()
    }

    /// `true` iff the trajectory has no expected records.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.records.is_empty()
    }
}

// ---------------------------------------------------------------------------
// Divergence
// ---------------------------------------------------------------------------

/// Kind of stream-level divergence between actual and expected records.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DivergenceKind {
    /// Both streams have a record at this step but the JCS bytes differ.
    ValueMismatch,
    /// Trajectory expects a record at this step but the actual stream
    /// has no record at this index (actual stream too short).
    MissingInActual,
    /// Actual stream has a record at this step but the trajectory has
    /// no expected record at this index (actual stream too long).
    ExtraInActual,
}

impl DivergenceKind {
    /// Lower-case canonical string form for operator-readable dumps.
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            DivergenceKind::ValueMismatch => "value-mismatch",
            DivergenceKind::MissingInActual => "missing-in-actual",
            DivergenceKind::ExtraInActual => "extra-in-actual",
        }
    }
}

/// One stream-level divergence entry in a [`ReplayReport`].
#[derive(Debug, Clone, PartialEq)]
pub struct Divergence {
    /// 0-based step index at which divergence surfaced.
    pub step_index: usize,
    /// Kind of divergence at this step.
    pub kind: DivergenceKind,
    /// Expected record at this step (or `None` for `ExtraInActual`).
    pub expected: Option<AuditRecord>,
    /// Actual record at this step (or `None` for `MissingInActual`).
    pub actual: Option<AuditRecord>,
    /// JCS hash of the expected record (or `None` if absent).
    pub expected_hash: Option<String>,
    /// JCS hash of the actual record (or `None` if absent).
    pub actual_hash: Option<String>,
    /// Field-level diff entries (RFC-6901 JSON-Pointer paths) when both
    /// sides are present; empty for `Missing` / `Extra` kinds.
    pub field_diffs: Vec<FieldDiff>,
}

// ---------------------------------------------------------------------------
// ReplayReport
// ---------------------------------------------------------------------------

/// Outcome of one stream-replay run.
#[derive(Debug, Clone)]
pub struct ReplayReport {
    /// `true` iff every expected record matches the actual record at
    /// the same step (no drift, no length mismatch).
    pub success: bool,
    /// Number of records actually replayed.
    pub actual_record_count: usize,
    /// Number of records the trajectory expected.
    pub expected_record_count: usize,
    /// 0-based step index of the FIRST divergence, or `None` on
    /// success. Monotonic non-decreasing across successively-corrected
    /// streams (the smoke-test suite asserts this invariant).
    pub time_to_divergence_steps: Option<usize>,
    /// All divergence entries in step-index order. Empty iff `success`.
    pub divergences: Vec<Divergence>,
    /// `"sha256:<64hex>"` of the actual record sequence (the
    /// JCS-canonicalised record array).
    pub stream_hash_actual: String,
    /// `"sha256:<64hex>"` of the expected record sequence.
    pub stream_hash_expected: String,
}

impl ReplayReport {
    /// `true` iff at least one divergence was recorded.
    #[must_use]
    pub fn has_divergence(&self) -> bool {
        !self.success
    }

    /// One-line operator-readable summary mirroring the
    /// [`persona_engine_bridge_diff::DiffReport::summary`] convention.
    #[must_use]
    pub fn summary(&self) -> String {
        if self.success {
            format!(
                "replay-ok records={} stream_hash={}",
                self.actual_record_count, self.stream_hash_actual
            )
        } else {
            format!(
                "replay-drift first_step={} divergences={} actual_hash={} expected_hash={}",
                self.time_to_divergence_steps
                    .map(|i| i.to_string())
                    .unwrap_or_else(|| "-".to_string()),
                self.divergences.len(),
                self.stream_hash_actual,
                self.stream_hash_expected,
            )
        }
    }
}

// ---------------------------------------------------------------------------
// Stream hash helper
// ---------------------------------------------------------------------------

/// Build the canonical "stream envelope" that gets hashed for replay
/// determinism: an object with the record array and its length so the
/// hash discriminates empty-vs-empty trivially and resists silent
/// truncation.
fn build_stream_envelope(records: &[AuditRecord]) -> Value {
    let arr: Vec<Value> = records.iter().map(AuditRecord::to_envelope).collect();
    let len = arr.len();
    let mut m = Map::with_capacity(2);
    m.insert("stream".to_string(), Value::Array(arr));
    m.insert("stream_len".to_string(), Value::from(len));
    Value::Object(m)
}

/// JCS-hash a record stream.
///
/// The stream envelope wraps the records in `{"stream": [...],
/// "stream_len": <n>}` so the hash discriminates empty streams from
/// missing-stream inputs (the `stream_len` field also resists silent
/// truncation in transit). The byte form is cross-language-pinned
/// against the Python pendant in the test suite.
///
/// # Errors
///
/// Surfaces [`ReplayError::Diff`] on JCS-canonicaliser failure
/// (unreachable in practice with well-formed input).
pub fn stream_hash(records: &[AuditRecord]) -> Result<String, ReplayError> {
    Ok(jcs_hash(&build_stream_envelope(records))?)
}

// ---------------------------------------------------------------------------
// ReplayEngine
// ---------------------------------------------------------------------------

/// Deterministic stream-replay engine.
///
/// The engine is stateless — `replay_stream` is a pure function of its
/// arguments. We model it as a struct (rather than a bare fn) so future
/// configuration knobs (tolerance for clock skew, record-kind filters,
/// per-step assertion overrides) attach to a typed handle rather than
/// growing the call signature.
#[derive(Debug, Clone, Default)]
pub struct ReplayEngine;

impl ReplayEngine {
    /// Construct a default engine. No configuration knobs in 0.1.0.
    #[must_use]
    pub fn new() -> Self {
        Self
    }

    /// Replay an actual record sequence against `expected` and produce
    /// a [`ReplayReport`].
    ///
    /// The replay is deterministic: identical inputs produce
    /// bit-identical reports (modulo `Debug` formatting of `Value` which
    /// the public API does not surface).
    ///
    /// Algorithm:
    ///
    /// 1. Hash both streams (`stream_hash`).
    /// 2. If the hashes match -> early-return success (`field_diffs`
    ///    untouched, `time_to_divergence_steps = None`).
    /// 3. Walk both streams pairwise up to `max(actual.len, expected.len)`.
    ///    Per step emit a [`Divergence`] with the appropriate kind.
    /// 4. `time_to_divergence_steps` is the first divergence's step
    ///    index.
    ///
    /// # Errors
    ///
    /// Returns [`ReplayError::Diff`] if either stream fails JCS
    /// canonicalisation (unreachable in practice).
    pub fn replay_stream(
        &self,
        actual: &[AuditRecord],
        expected: &ExpectedTrajectory,
    ) -> Result<ReplayReport, ReplayError> {
        let stream_hash_actual = stream_hash(actual)?;
        let stream_hash_expected = stream_hash(&expected.records)?;

        if stream_hash_actual == stream_hash_expected {
            return Ok(ReplayReport {
                success: true,
                actual_record_count: actual.len(),
                expected_record_count: expected.len(),
                time_to_divergence_steps: None,
                divergences: Vec::new(),
                stream_hash_actual,
                stream_hash_expected,
            });
        }

        let max_len = actual.len().max(expected.records.len());
        let mut divergences: Vec<Divergence> = Vec::new();

        for i in 0..max_len {
            let act = actual.get(i);
            let exp = expected.records.get(i);

            match (act, exp) {
                (Some(a), Some(e)) => {
                    let a_hash = a.jcs_hash()?;
                    let e_hash = e.jcs_hash()?;
                    if a_hash != e_hash {
                        let a_env = a.to_envelope();
                        let e_env = e.to_envelope();
                        // diff_envelopes orientation: (a=actual, b=expected)
                        // -> only-in-a == only-in-actual; only-in-b ==
                        // only-in-expected. Caller-facing semantics
                        // documented in the README of the crate.
                        let field_diffs = diff_envelopes(&a_env, &e_env);
                        divergences.push(Divergence {
                            step_index: i,
                            kind: DivergenceKind::ValueMismatch,
                            expected: Some(e.clone()),
                            actual: Some(a.clone()),
                            expected_hash: Some(e_hash),
                            actual_hash: Some(a_hash),
                            field_diffs,
                        });
                    }
                }
                (Some(a), None) => {
                    let a_hash = a.jcs_hash()?;
                    divergences.push(Divergence {
                        step_index: i,
                        kind: DivergenceKind::ExtraInActual,
                        expected: None,
                        actual: Some(a.clone()),
                        expected_hash: None,
                        actual_hash: Some(a_hash),
                        field_diffs: Vec::new(),
                    });
                }
                (None, Some(e)) => {
                    let e_hash = e.jcs_hash()?;
                    divergences.push(Divergence {
                        step_index: i,
                        kind: DivergenceKind::MissingInActual,
                        expected: Some(e.clone()),
                        actual: None,
                        expected_hash: Some(e_hash),
                        actual_hash: None,
                        field_diffs: Vec::new(),
                    });
                }
                (None, None) => {
                    // Unreachable: loop bound is max of both lens.
                    break;
                }
            }
        }

        let time_to_divergence_steps = divergences.first().map(|d| d.step_index);
        let success = divergences.is_empty();

        Ok(ReplayReport {
            success,
            actual_record_count: actual.len(),
            expected_record_count: expected.records.len(),
            time_to_divergence_steps,
            divergences,
            stream_hash_actual,
            stream_hash_expected,
        })
    }
}

// ---------------------------------------------------------------------------
// In-crate unit tests for non-pin invariants.
// ---------------------------------------------------------------------------

#[cfg(test)]
mod inline {
    use super::*;

    fn rec(step: u32) -> AuditRecord {
        AuditRecord {
            org_id: "wakir-labs".to_string(),
            persona_id: "mira".to_string(),
            session_id: "sess-001".to_string(),
            step_index: step,
            output_kind: "tool_call".to_string(),
            output_payload_sha256: format!("sha256:{}", "a".repeat(64)),
            engine_version: "0.2.0-pilot".to_string(),
            v907_pin: format!("sha256:{}", "b".repeat(64)),
            ts_utc: format!("2026-05-17T10:00:0{step}Z"),
        }
    }

    #[test]
    fn replay_engine_is_default_constructible() {
        let _e = ReplayEngine::new();
        // Exercise both constructors through a trait-bounded fn call so
        // clippy::default-constructed-unit-structs does not fire on a
        // raw `ReplayEngine::default()` literal.
        fn via_default<T: Default>() -> T {
            Default::default()
        }
        let _e2: ReplayEngine = via_default();
    }

    #[test]
    fn divergence_kind_strings_match_diff_engine_alphabet() {
        // Parity with bridge-diff's DiffKind alphabet (lower-case-hyphen
        // form). Only `value-mismatch` is shared; the other two are
        // stream-level (the diff-engine uses only-in-a / only-in-b
        // which are FIELD-level).
        assert_eq!(DivergenceKind::ValueMismatch.as_str(), "value-mismatch");
        assert_eq!(
            DivergenceKind::MissingInActual.as_str(),
            "missing-in-actual"
        );
        assert_eq!(DivergenceKind::ExtraInActual.as_str(), "extra-in-actual");
    }

    #[test]
    fn expected_trajectory_helpers() {
        let t = ExpectedTrajectory::default();
        assert!(t.is_empty());
        assert_eq!(t.len(), 0);

        let recs = vec![rec(0), rec(1)];
        let t2 = ExpectedTrajectory::from_records(&recs);
        assert_eq!(t2.len(), 2);
        assert!(!t2.is_empty());
    }
}
