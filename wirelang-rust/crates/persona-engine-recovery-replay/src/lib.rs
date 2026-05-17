// SPDX-License-Identifier: Apache-2.0
//! Deterministic Recovery-Workflow R1..R4 replay engine for the
//! Phase-3a Doppelbetrieb-Konsistenz drill.
//!
//! Sprint-Recovery-Replay-Engine-Rust-MINI (ADR-0063 §Folgeartefakte
//! Phase-3a Item 13).
//!
//! Where [`persona_engine_bridge_audit_replay`] is the stream-level
//! oracle for `EngineeringOutputEvent` envelopes (engine output side),
//! this crate is the stream-level oracle for [`PhaseResult`] sequences
//! (recovery-workflow side). The replay engine takes a recorded
//! recovery-workflow sequence (R1, R2, R3, R4 — or a subset on
//! retry/skip paths) and validates it against an expected trajectory.
//!
//! Replay contract
//! ---------------
//!
//! [`RecoveryReplayEngine::replay_workflow`] takes a slice of
//! [`PhaseResult`]s (re-exported from `persona-engine-recovery`) and
//! an [`ExpectedRecoveryTrajectory`]. It returns a
//! [`RecoveryReplayReport`] that:
//!
//! - Reports `success = true` iff actual phases match expected phases
//!   one-for-one (in order, JCS-byte-identical per phase).
//! - On divergence, surfaces every drift entry in step-index order
//!   (operator-friendly full delta, not just the first symptom).
//! - Records `time_to_divergence_steps` — the 0-based step index at
//!   which the first drift surfaces, or `None` on full match. The
//!   metric is monotonic non-decreasing across a successively-
//!   corrected stream (the test-suite asserts this invariant).
//! - Distinguishes three drift kinds: [`DivergenceKind::ValueMismatch`]
//!   (phase present on both sides, fields drift),
//!   [`DivergenceKind::MissingInActual`] (expected phase absent —
//!   actual stream too short / phase skipped),
//!   [`DivergenceKind::ExtraInActual`] (actual stream has more
//!   phases than the trajectory expects — typically R-retry).
//!
//! Determinism contract
//! --------------------
//!
//! `replay_workflow` is pure: same `PhaseResult` slice in -> bit-
//! identical report out. The report's `workflow_hash_*` fields are
//! `jcs_hash(phases-as-array-with-len)` — reuses the workspace
//! `serde_jcs` + `sha2` pipeline so the byte-level contract is the
//! same as the bridge-audit-replay engine.
//!
//! Naming note
//! -----------
//!
//! The Sprint-Auftrag refers to `RecoveryStep`. The Rust pendant of
//! the Python recovery type is `PhaseResult` (see
//! `persona-engine-recovery` PR #135 / Python `recovery_workflow.py`).
//! `PhaseResult` is the recovery step result — we re-export it as
//! [`RecoveryStep`] in this crate for Sprint-Auftrag-signature-parity
//! and to give the replay-engine API the Sprint-Auftrag-named handle.
//! The underlying type is unchanged.
//!
//! Out of scope (deliberately)
//! ---------------------------
//!
//! - Re-execution of a recovery drill from scratch. "Replay" here
//!   means re-walking a recorded `PhaseResult` sequence and
//!   validating its shape — not re-running the recovery workflow.
//! - Persistence. The report is in-memory only.
//! - Soft-cap evaluation. The expected trajectory carries the
//!   expected `soft_cap_exceeded` flag; we compare structurally.
//!   The recovery-workflow itself is the authority on soft-cap
//!   semantics.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use serde::Serialize;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

pub use persona_engine_recovery::PhaseResult;

/// Sprint-Auftrag-signature-parity alias for [`PhaseResult`]. The
/// underlying type lives in `persona-engine-recovery` (PR #135). We
/// re-export under the Sprint-Auftrag name so the replay-engine API
/// reads `replay_workflow(steps: &[RecoveryStep])` rather than
/// `replay_workflow(steps: &[PhaseResult])`.
pub type RecoveryStep = PhaseResult;

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/// Error class for the replay engine.
///
/// Narrow surface: the only failure source is JCS canonicalisation
/// of the in-memory `serde_json::Value` envelope. Unreachable in
/// practice with well-formed [`PhaseResult`] inputs (the Rust type
/// constrains the shape to ASCII-clean strings + finite f64s).
#[derive(Debug)]
pub enum RecoveryReplayError {
    /// JCS canonicaliser surfaced an error.
    Jcs(String),
}

impl std::fmt::Display for RecoveryReplayError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RecoveryReplayError::Jcs(e) => write!(f, "jcs canonicalisation error: {e}"),
        }
    }
}

impl std::error::Error for RecoveryReplayError {}

// ---------------------------------------------------------------------------
// Canonical envelope + hash helpers.
// ---------------------------------------------------------------------------

/// JCS-canonical envelope schema tag for a recovery phase. Single
/// source-of-truth for the recovery side; pairs with the bridge-audit
/// equivalent `wakir.persona.engineering-output/1`.
pub const RECOVERY_PHASE_SCHEMA: &str = "wakir.persona.recovery-phase/1";

/// Project one [`PhaseResult`] onto its JCS-canonical envelope shape.
///
/// Field set matches the Python `PhaseResult` JSON projection (PR #65
/// `recovery_workflow.audit_record_json`'s per-phase block) plus the
/// `schema` tag. Key insertion order is alphabetised for source-level
/// review hygiene; `serde_jcs` re-sorts byte-identically.
#[must_use]
pub fn phase_to_envelope(p: &PhaseResult) -> Value {
    let mut m = Map::with_capacity(6);
    m.insert(
        "audit_annotation".to_string(),
        Value::String(p.audit_annotation.clone()),
    );
    m.insert("elapsed_sec".to_string(), Value::from(p.elapsed_sec));
    m.insert("phase".to_string(), Value::String(p.phase.clone()));
    m.insert(
        "schema".to_string(),
        Value::String(RECOVERY_PHASE_SCHEMA.to_string()),
    );
    m.insert(
        "soft_cap_exceeded".to_string(),
        Value::Bool(p.soft_cap_exceeded),
    );
    m.insert(
        "terminal_status".to_string(),
        Value::String(p.terminal_status.clone()),
    );
    Value::Object(m)
}

fn jcs_canonicalise(v: &Value) -> Result<Vec<u8>, RecoveryReplayError> {
    serde_jcs::to_vec(v).map_err(|e| RecoveryReplayError::Jcs(e.to_string()))
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    let digest = h.finalize();
    hex::encode(digest)
}

/// JCS-hash a single phase. Returns `"sha256:<64-lower-hex>"`.
///
/// # Errors
///
/// Surfaces [`RecoveryReplayError::Jcs`] on canonicaliser failure.
pub fn phase_hash(p: &PhaseResult) -> Result<String, RecoveryReplayError> {
    let bytes = jcs_canonicalise(&phase_to_envelope(p))?;
    Ok(format!("sha256:{}", sha256_hex(&bytes)))
}

/// Build the canonical workflow envelope (`{"phases": [...],
/// "phases_len": <n>, "schema": "wakir.persona.recovery-workflow/1"}`).
fn build_workflow_envelope(steps: &[PhaseResult]) -> Value {
    let arr: Vec<Value> = steps.iter().map(phase_to_envelope).collect();
    let len = arr.len();
    let mut m = Map::with_capacity(3);
    m.insert("phases".to_string(), Value::Array(arr));
    m.insert("phases_len".to_string(), Value::from(len));
    m.insert(
        "schema".to_string(),
        Value::String("wakir.persona.recovery-workflow/1".to_string()),
    );
    Value::Object(m)
}

/// JCS-hash a recovery-workflow step sequence.
///
/// The envelope wraps the phases in `{"phases": [...], "phases_len":
/// <n>, "schema": "wakir.persona.recovery-workflow/1"}` so the hash
/// discriminates empty workflows from missing-workflow inputs and
/// resists silent truncation.
///
/// # Errors
///
/// Surfaces [`RecoveryReplayError::Jcs`] on canonicaliser failure.
pub fn workflow_hash(steps: &[PhaseResult]) -> Result<String, RecoveryReplayError> {
    let bytes = jcs_canonicalise(&build_workflow_envelope(steps))?;
    Ok(format!("sha256:{}", sha256_hex(&bytes)))
}

// ---------------------------------------------------------------------------
// Field-level diff (RFC 6901 JSON-Pointer paths).
// ---------------------------------------------------------------------------

/// One field-level diff entry between two phase envelopes.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct PhaseFieldDiff {
    /// RFC 6901 JSON-Pointer path of the differing field (e.g.
    /// `/terminal_status`).
    pub path: String,
    /// Lower-case alphabet (`value-mismatch` | `only-in-actual` |
    /// `only-in-expected`). Parity with the bridge-diff alphabet.
    pub kind: String,
    /// Stringified actual value (or empty string when absent).
    pub actual: String,
    /// Stringified expected value (or empty string when absent).
    pub expected: String,
}

fn value_to_display(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

/// Diff two phase envelopes at the field level.
///
/// Keys present in both sides with differing values produce a
/// `value-mismatch` entry. Keys only on the actual side produce
/// `only-in-actual`; keys only on the expected side produce
/// `only-in-expected`. Output is sorted by path so the diff is
/// deterministic.
#[must_use]
pub fn diff_phase_envelopes(actual: &Value, expected: &Value) -> Vec<PhaseFieldDiff> {
    let mut out: Vec<PhaseFieldDiff> = Vec::new();
    let a_obj = actual.as_object();
    let e_obj = expected.as_object();
    let (a_obj, e_obj) = match (a_obj, e_obj) {
        (Some(a), Some(e)) => (a, e),
        // If either side is not an object, surface a synthetic root-
        // level mismatch. Should not occur with well-formed phases.
        _ => {
            return vec![PhaseFieldDiff {
                path: "/".to_string(),
                kind: "value-mismatch".to_string(),
                actual: actual.to_string(),
                expected: expected.to_string(),
            }];
        }
    };
    let mut all_keys: Vec<&String> = a_obj.keys().chain(e_obj.keys()).collect();
    all_keys.sort();
    all_keys.dedup();
    for k in all_keys {
        let path = format!("/{k}");
        match (a_obj.get(k), e_obj.get(k)) {
            (Some(av), Some(ev)) => {
                if av != ev {
                    out.push(PhaseFieldDiff {
                        path,
                        kind: "value-mismatch".to_string(),
                        actual: value_to_display(av),
                        expected: value_to_display(ev),
                    });
                }
            }
            (Some(av), None) => out.push(PhaseFieldDiff {
                path,
                kind: "only-in-actual".to_string(),
                actual: value_to_display(av),
                expected: String::new(),
            }),
            (None, Some(ev)) => out.push(PhaseFieldDiff {
                path,
                kind: "only-in-expected".to_string(),
                actual: String::new(),
                expected: value_to_display(ev),
            }),
            (None, None) => {}
        }
    }
    out
}

// ---------------------------------------------------------------------------
// Divergence + Report types.
// ---------------------------------------------------------------------------

/// Kind of stream-level divergence between actual and expected steps.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DivergenceKind {
    /// Both streams have a step at this index but the JCS bytes differ.
    ValueMismatch,
    /// Trajectory expects a step at this index but the actual stream
    /// has none (actual stream too short / phase skipped).
    MissingInActual,
    /// Actual stream has a step at this index but the trajectory has
    /// no expected step (actual stream too long / phase retried).
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

/// One stream-level divergence entry in a [`RecoveryReplayReport`].
#[derive(Debug, Clone, PartialEq)]
pub struct Divergence {
    /// 0-based step index at which divergence surfaced.
    pub step_index: usize,
    /// Phase label at this index: from the actual phase if present,
    /// otherwise from the expected phase. Empty string only if both
    /// sides are absent (unreachable in practice).
    pub step_name: String,
    /// Kind of divergence at this step.
    pub kind: DivergenceKind,
    /// Expected step at this index (or `None` for `ExtraInActual`).
    pub expected: Option<PhaseResult>,
    /// Actual step at this index (or `None` for `MissingInActual`).
    pub actual: Option<PhaseResult>,
    /// JCS hash of the expected step (or `None` if absent).
    pub expected_hash: Option<String>,
    /// JCS hash of the actual step (or `None` if absent).
    pub actual_hash: Option<String>,
    /// Field-level diff entries when both sides are present; empty
    /// for `MissingInActual` / `ExtraInActual`.
    pub field_diffs: Vec<PhaseFieldDiff>,
}

/// Expected sequence of recovery-workflow phases for a replay.
#[derive(Debug, Clone, Default)]
pub struct ExpectedRecoveryTrajectory {
    /// Ordered expected steps. Index = step.
    pub steps: Vec<PhaseResult>,
}

impl ExpectedRecoveryTrajectory {
    /// Convenience constructor from a step slice.
    #[must_use]
    pub fn from_steps(steps: &[PhaseResult]) -> Self {
        Self {
            steps: steps.to_vec(),
        }
    }

    /// Number of expected steps.
    #[must_use]
    pub fn len(&self) -> usize {
        self.steps.len()
    }

    /// `true` iff no expected steps.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.steps.is_empty()
    }
}

/// Outcome of one recovery-replay run.
#[derive(Debug, Clone)]
pub struct RecoveryReplayReport {
    /// `true` iff every expected step matches the actual step at the
    /// same index (no drift, no length mismatch).
    pub success: bool,
    /// Number of steps actually replayed.
    pub actual_step_count: usize,
    /// Number of steps the trajectory expected.
    pub expected_step_count: usize,
    /// 0-based step index of the FIRST divergence, or `None` on
    /// success. Monotonic non-decreasing across successively-
    /// corrected streams (smoke-test invariant).
    pub time_to_divergence_steps: Option<usize>,
    /// All divergence entries in step-index order. Empty iff `success`.
    pub divergences: Vec<Divergence>,
    /// `"sha256:<64hex>"` of the actual phase sequence.
    pub workflow_hash_actual: String,
    /// `"sha256:<64hex>"` of the expected phase sequence.
    pub workflow_hash_expected: String,
}

impl RecoveryReplayReport {
    /// `true` iff at least one divergence was recorded.
    #[must_use]
    pub fn has_divergence(&self) -> bool {
        !self.success
    }

    /// One-line operator-readable summary mirroring the
    /// bridge-audit-replay summary convention.
    #[must_use]
    pub fn summary(&self) -> String {
        if self.success {
            format!(
                "recovery-replay-ok phases={} workflow_hash={}",
                self.actual_step_count, self.workflow_hash_actual
            )
        } else {
            format!(
                "recovery-replay-drift first_step={} divergences={} actual_hash={} expected_hash={}",
                self.time_to_divergence_steps
                    .map(|i| i.to_string())
                    .unwrap_or_else(|| "-".to_string()),
                self.divergences.len(),
                self.workflow_hash_actual,
                self.workflow_hash_expected,
            )
        }
    }
}

// ---------------------------------------------------------------------------
// RecoveryReplayEngine.
// ---------------------------------------------------------------------------

/// Deterministic recovery-workflow replay engine.
///
/// Stateless — `replay_workflow` is a pure function of its
/// arguments. We model it as a struct rather than a bare fn so future
/// configuration knobs (per-phase tolerances, soft-cap-ignore flags)
/// attach to a typed handle.
#[derive(Debug, Clone, Default)]
pub struct RecoveryReplayEngine;

impl RecoveryReplayEngine {
    /// Construct a default engine. No configuration knobs in 0.1.0.
    #[must_use]
    pub fn new() -> Self {
        Self
    }

    /// Replay an actual recovery-workflow step sequence against
    /// `expected` and produce a [`RecoveryReplayReport`].
    ///
    /// Sprint-Auftrag signature: takes `&[RecoveryStep]` (alias for
    /// `&[PhaseResult]`) and an [`ExpectedRecoveryTrajectory`].
    ///
    /// The replay is deterministic: identical inputs produce bit-
    /// identical reports (modulo non-public `Debug` formatting).
    ///
    /// # Errors
    ///
    /// Returns [`RecoveryReplayError::Jcs`] if either step sequence
    /// fails JCS canonicalisation (unreachable in practice).
    pub fn replay_workflow(
        &self,
        steps: &[RecoveryStep],
        expected: &ExpectedRecoveryTrajectory,
    ) -> Result<RecoveryReplayReport, RecoveryReplayError> {
        let workflow_hash_actual = workflow_hash(steps)?;
        let workflow_hash_expected = workflow_hash(&expected.steps)?;

        if workflow_hash_actual == workflow_hash_expected {
            return Ok(RecoveryReplayReport {
                success: true,
                actual_step_count: steps.len(),
                expected_step_count: expected.len(),
                time_to_divergence_steps: None,
                divergences: Vec::new(),
                workflow_hash_actual,
                workflow_hash_expected,
            });
        }

        let max_len = steps.len().max(expected.steps.len());
        let mut divergences: Vec<Divergence> = Vec::new();

        for i in 0..max_len {
            let act = steps.get(i);
            let exp = expected.steps.get(i);

            match (act, exp) {
                (Some(a), Some(e)) => {
                    let a_hash = phase_hash(a)?;
                    let e_hash = phase_hash(e)?;
                    if a_hash != e_hash {
                        let a_env = phase_to_envelope(a);
                        let e_env = phase_to_envelope(e);
                        let field_diffs = diff_phase_envelopes(&a_env, &e_env);
                        divergences.push(Divergence {
                            step_index: i,
                            step_name: a.phase.clone(),
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
                    let a_hash = phase_hash(a)?;
                    divergences.push(Divergence {
                        step_index: i,
                        step_name: a.phase.clone(),
                        kind: DivergenceKind::ExtraInActual,
                        expected: None,
                        actual: Some(a.clone()),
                        expected_hash: None,
                        actual_hash: Some(a_hash),
                        field_diffs: Vec::new(),
                    });
                }
                (None, Some(e)) => {
                    let e_hash = phase_hash(e)?;
                    divergences.push(Divergence {
                        step_index: i,
                        step_name: e.phase.clone(),
                        kind: DivergenceKind::MissingInActual,
                        expected: Some(e.clone()),
                        actual: None,
                        expected_hash: Some(e_hash),
                        actual_hash: None,
                        field_diffs: Vec::new(),
                    });
                }
                (None, None) => break,
            }
        }

        let time_to_divergence_steps = divergences.first().map(|d| d.step_index);
        let success = divergences.is_empty();

        Ok(RecoveryReplayReport {
            success,
            actual_step_count: steps.len(),
            expected_step_count: expected.steps.len(),
            time_to_divergence_steps,
            divergences,
            workflow_hash_actual,
            workflow_hash_expected,
        })
    }
}

// ---------------------------------------------------------------------------
// In-crate unit tests for non-pin invariants.
// ---------------------------------------------------------------------------

#[cfg(test)]
mod inline {
    use super::*;

    fn mk_phase(label: &str, status: &str, elapsed: f64) -> PhaseResult {
        PhaseResult {
            phase: label.to_string(),
            terminal_status: status.to_string(),
            elapsed_sec: elapsed,
            soft_cap_exceeded: false,
            audit_annotation: format!("{label}-ann"),
        }
    }

    #[test]
    fn engine_is_default_constructible() {
        let _e = RecoveryReplayEngine::new();
        fn via_default<T: Default>() -> T {
            Default::default()
        }
        let _e2: RecoveryReplayEngine = via_default();
    }

    #[test]
    fn divergence_kind_alphabet() {
        assert_eq!(DivergenceKind::ValueMismatch.as_str(), "value-mismatch");
        assert_eq!(
            DivergenceKind::MissingInActual.as_str(),
            "missing-in-actual"
        );
        assert_eq!(DivergenceKind::ExtraInActual.as_str(), "extra-in-actual");
    }

    #[test]
    fn expected_trajectory_helpers() {
        let t = ExpectedRecoveryTrajectory::default();
        assert!(t.is_empty());
        assert_eq!(t.len(), 0);

        let steps = vec![mk_phase("R1", "detected", 0.01)];
        let t2 = ExpectedRecoveryTrajectory::from_steps(&steps);
        assert_eq!(t2.len(), 1);
        assert!(!t2.is_empty());
    }

    #[test]
    fn phase_envelope_has_six_keys_with_schema_tag() {
        let p = mk_phase("R1", "detected", 0.0);
        let env = phase_to_envelope(&p);
        let obj = env.as_object().expect("object");
        assert_eq!(obj.len(), 6);
        assert_eq!(
            obj.get("schema").unwrap().as_str().unwrap(),
            RECOVERY_PHASE_SCHEMA
        );
    }

    #[test]
    fn phase_hash_changes_when_any_field_changes() {
        let h0 = phase_hash(&mk_phase("R1", "detected", 0.0)).unwrap();
        let h1 = phase_hash(&mk_phase("R2", "detected", 0.0)).unwrap();
        let h2 = phase_hash(&mk_phase("R1", "reloaded", 0.0)).unwrap();
        let h3 = phase_hash(&mk_phase("R1", "detected", 0.1)).unwrap();
        assert_ne!(h0, h1);
        assert_ne!(h0, h2);
        assert_ne!(h0, h3);
    }
}
