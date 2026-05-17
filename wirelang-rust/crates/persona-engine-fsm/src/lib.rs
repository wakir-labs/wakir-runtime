// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Callandor GmbH and contributors
//
// Persona-engine lifecycle state-machine — Rust pendant.
//
// Schema-parity authority: `wirelang/persona_engine/lifecycle_state_machine.py`
// (Selin Sprint-Pengine-8 PR #65). Spec authority:
// `wirelang/specs/persona-engine-format-spec.md` §3.3
// "Lifecycle states and transitions".
//
// Design notes
// ------------
// - The state set and transition set are *closed enumerations*. Any
//   edge not present in [`VALID_TRANSITIONS`] is an error.
// - Every transition attempt (accepted or rejected) is appended to the
//   audit history. The recovery-workflow (§3.7.4 R2 "Reload") replays
//   this list byte-for-byte to rebuild engine state.
// - The Rust API mirrors the Python surface deliberately: state-set
//   strings, transition strings, error semantics, and the
//   "every-attempt-leaves-an-audit-trace" invariant all match.
// - The cross-lang wire-string smoke test (see `tests/`) pins every
//   wire string so any rename on either side fails both ports in the
//   same CI cycle.

#![forbid(unsafe_code)]
#![warn(missing_docs)]
#![warn(missing_debug_implementations)]

//! Persona-engine lifecycle state-machine — Rust pendant.
//!
//! See the crate-level Cargo.toml comment for schema-parity table and
//! ADR anchors. Public surface: [`FsmState`], [`FsmTransition`],
//! [`TransitionRecord`], [`PersonaFsm`], [`FsmError`].
//!
//! Tag-21 Mini-Welle adds the canonical-trace cross-lang surface in
//! the [`canonical`] module: [`canonical::LifecycleTrace`],
//! [`canonical::serialize_trace`], [`canonical::trace_sha256_hex`],
//! [`canonical::trace_hash_prefixed`]. Byte-for-byte parity with
//! the Python sibling
//! `wirelang.persona_engine.lifecycle_state_machine_canonical` is
//! pinned by the cross-lang fixture vectors under
//! `tests/fixtures/lifecycle-state-machine-cross-lang/fixtures.json`.

/// Tag-21 canonical-trace cross-lang surface (see module docs).
pub mod canonical;

use serde::{Deserialize, Serialize};
use std::fmt;

// ---------------------------------------------------------------------
// Spec §3.3 — six states.
// ---------------------------------------------------------------------

/// The six lifecycle states per spec §3.3 `states` array.
///
/// Wire-string representation is the lowercase Python label returned by
/// [`FsmState::as_wire_str`] and pinned in the cross-lang smoke test.
#[derive(
    Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize,
)]
#[serde(rename_all = "lowercase")]
pub enum FsmState {
    /// `uninstantiated` — initial state, no engine instance yet.
    Uninstantiated,
    /// `spawning` — engine creation in progress.
    Spawning,
    /// `running` — engine alive and serving traffic.
    Running,
    /// `despawning` — engine shutdown in progress.
    Despawning,
    /// `recovered` — engine reloaded from marker-stack-kv audit log
    /// (recovery_workflow §3.7.4 R2).
    Recovered,
    /// `migrated` — engine moved across host / version boundary.
    Migrated,
}

impl FsmState {
    /// Return the wire-string form of the state (matches the lowercase
    /// Python `STATES` tuple entries).
    pub const fn as_wire_str(self) -> &'static str {
        match self {
            FsmState::Uninstantiated => "uninstantiated",
            FsmState::Spawning => "spawning",
            FsmState::Running => "running",
            FsmState::Despawning => "despawning",
            FsmState::Recovered => "recovered",
            FsmState::Migrated => "migrated",
        }
    }

    /// Parse a wire-string back to its [`FsmState`]. Returns
    /// [`FsmError::UnknownState`] for any unknown label.
    pub fn from_wire_str(s: &str) -> Result<Self, FsmError> {
        match s {
            "uninstantiated" => Ok(FsmState::Uninstantiated),
            "spawning" => Ok(FsmState::Spawning),
            "running" => Ok(FsmState::Running),
            "despawning" => Ok(FsmState::Despawning),
            "recovered" => Ok(FsmState::Recovered),
            "migrated" => Ok(FsmState::Migrated),
            other => Err(FsmError::UnknownState(other.to_string())),
        }
    }
}

impl fmt::Display for FsmState {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_wire_str())
    }
}

/// All six lifecycle states, in spec-declaration order. Used by
/// invariant tests and any caller that needs to iterate the state set.
pub const STATES: &[FsmState] = &[
    FsmState::Uninstantiated,
    FsmState::Spawning,
    FsmState::Running,
    FsmState::Despawning,
    FsmState::Recovered,
    FsmState::Migrated,
];

// ---------------------------------------------------------------------
// Spec §3.3 — nine valid transitions.
// ---------------------------------------------------------------------

/// A single transition edge per spec §3.3 `valid_transitions` array.
///
/// The struct form (rather than a 9-variant enum) keeps the table
/// authoritative — adding or removing a row in [`VALID_TRANSITIONS`]
/// changes the entire surface without an enum rename. The wire-pair
/// `(from.as_wire_str(), to.as_wire_str())` is the cross-lang anchor.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct FsmTransition {
    /// The state the machine must be in for the transition to fire.
    pub from: FsmState,
    /// The state the machine ends up in after a successful transition.
    pub to: FsmState,
}

impl FsmTransition {
    /// Construct a transition. `const` so the table below can be
    /// initialised at compile time.
    pub const fn new(from: FsmState, to: FsmState) -> Self {
        Self { from, to }
    }
}

impl fmt::Display for FsmTransition {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} -> {}", self.from, self.to)
    }
}

/// The closed enumeration of valid lifecycle transitions per spec
/// §3.3 `valid_transitions` array. Order matches the spec and the
/// Python [`VALID_TRANSITIONS`] tuple. Any edge not present here is
/// rejected by [`PersonaFsm::transition`].
pub const VALID_TRANSITIONS: &[FsmTransition] = &[
    FsmTransition::new(FsmState::Uninstantiated, FsmState::Spawning),
    FsmTransition::new(FsmState::Spawning, FsmState::Running),
    FsmTransition::new(FsmState::Spawning, FsmState::Uninstantiated),
    FsmTransition::new(FsmState::Running, FsmState::Despawning),
    FsmTransition::new(FsmState::Despawning, FsmState::Uninstantiated),
    FsmTransition::new(FsmState::Uninstantiated, FsmState::Recovered),
    FsmTransition::new(FsmState::Recovered, FsmState::Running),
    FsmTransition::new(FsmState::Running, FsmState::Migrated),
    FsmTransition::new(FsmState::Migrated, FsmState::Uninstantiated),
];

/// Return `true` iff `(from, to)` is one of [`VALID_TRANSITIONS`].
pub fn is_valid_transition(from: FsmState, to: FsmState) -> bool {
    VALID_TRANSITIONS
        .iter()
        .any(|t| t.from == from && t.to == to)
}

// ---------------------------------------------------------------------
// Errors.
// ---------------------------------------------------------------------

/// Error surface for [`PersonaFsm::transition`] and related calls.
///
/// Mirrors the two Python exception types from PR #65:
/// `InvalidTransitionError` and `UnknownStateError`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FsmError {
    /// The attempted `(from, to)` edge is not in
    /// [`VALID_TRANSITIONS`]. Carries the attempted pair so the
    /// caller can produce an audit-friendly diagnostic.
    InvalidTransition {
        /// The state the machine was in when the transition was
        /// attempted.
        from: FsmState,
        /// The target state the caller asked for.
        to: FsmState,
    },
    /// A wire-string outside the closed state set was supplied (only
    /// reachable via [`FsmState::from_wire_str`] today — kept distinct
    /// from `InvalidTransition` to match the Python `UnknownStateError`
    /// surface).
    UnknownState(String),
    /// A replay record claims an edge whose `from` state does not
    /// match the machine's current state. Signals audit-log corruption.
    ReplayDrift {
        /// The state the machine had reached during replay.
        expected_from: FsmState,
        /// The `from` state recorded in the corrupted record.
        recorded_from: FsmState,
        /// The `to` state recorded in the corrupted record.
        recorded_to: FsmState,
    },
}

impl fmt::Display for FsmError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            FsmError::InvalidTransition { from, to } => write!(
                f,
                "invalid lifecycle transition {} -> {} \
                 (spec §3.3 valid_transitions does not contain this edge)",
                from, to
            ),
            FsmError::UnknownState(s) => write!(
                f,
                "unknown lifecycle state {:?}; valid: {:?}",
                s,
                STATES.iter().map(|s| s.as_wire_str()).collect::<Vec<_>>()
            ),
            FsmError::ReplayDrift {
                expected_from,
                recorded_from,
                recorded_to,
            } => write!(
                f,
                "replay drift: machine in state {} but record claims \
                 from-state {} for transition {} -> {}",
                expected_from, recorded_from, recorded_from, recorded_to
            ),
        }
    }
}

impl std::error::Error for FsmError {}

// ---------------------------------------------------------------------
// Audit envelope.
// ---------------------------------------------------------------------

/// Audit envelope for a single transition attempt. Mirrors the Python
/// `TransitionRecord` dataclass field-for-field.
///
/// Field order is deliberately preserved so the cross-lang JSON parity
/// test compares maps with identical key sets (serde respects struct
/// field declaration order for the JSON object key order when paired
/// with `serde_json` and no `#[serde(rename_all)]`).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TransitionRecord {
    /// State the machine was in when the attempt happened.
    pub from_state: FsmState,
    /// Target state the caller requested.
    pub to_state: FsmState,
    /// RFC 3339 UTC second-precision timestamp of the attempt.
    pub ts_utc: String,
    /// `true` if the transition was applied, `false` if rejected.
    pub accepted: bool,
    /// Free-form rejection reason. `None` for accepted records and
    /// for the Python sentinel `null` value.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

// ---------------------------------------------------------------------
// PersonaFsm — the state machine itself.
// ---------------------------------------------------------------------

/// Engine-side persona lifecycle state machine.
///
/// Mirrors `LifecycleStateMachine` from PR #65. Single-writer; callers
/// must serialise transitions externally (Python uses a per-persona
/// asyncio lock for the multi-coroutine spawn path; Rust callers can
/// wrap the struct in a `tokio::sync::Mutex` or similar).
///
/// The `state`, `persona_id`, `org_id`, and `history` fields are
/// exposed via accessors rather than as public struct fields so the
/// invariant "every state change goes through `transition`" remains
/// enforceable.
#[derive(Debug, Clone)]
pub struct PersonaFsm {
    state: FsmState,
    persona_id: String,
    org_id: String,
    history: Vec<TransitionRecord>,
    /// Clock function — pluggable so deterministic tests can pin
    /// timestamps. Defaults to a closure that returns a fixed sentinel
    /// in `new`; production callers should set it via [`with_clock`].
    clock: ClockFn,
}

/// Type alias for the pluggable RFC-3339 UTC clock function.
pub type ClockFn = fn() -> String;

/// Default clock: returns the current UTC time as an RFC-3339
/// second-precision string. Test-friendly default lives in the struct
/// constructor.
pub fn default_clock() -> String {
    // chrono is intentionally NOT a dependency of this crate (keeps
    // the dependency footprint at serde + serde_json). The crate
    // formats `SystemTime` manually for second-precision RFC-3339.
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("system clock predates UNIX epoch")
        .as_secs() as i64;
    format_rfc3339_utc(secs)
}

/// Format a UNIX-epoch second count as an RFC-3339 UTC string
/// (`YYYY-MM-DDTHH:MM:SSZ`). Pure function — used by [`default_clock`]
/// and exposed so test fixtures can build pinned timestamps without
/// re-implementing date arithmetic.
pub fn format_rfc3339_utc(unix_secs: i64) -> String {
    // Civil-from-days algorithm by Howard Hinnant (public domain,
    // widely cross-checked). Handles the full proleptic Gregorian
    // range; we only need 1970+ in practice.
    let secs_per_day: i64 = 86_400;
    let days = unix_secs.div_euclid(secs_per_day);
    let secs_of_day = unix_secs.rem_euclid(secs_per_day);
    let hour = secs_of_day / 3600;
    let minute = (secs_of_day % 3600) / 60;
    let second = secs_of_day % 60;

    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097; // [0, 146096]
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365; // [0, 399]
    let mut y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let d = doy - (153 * mp + 2) / 5 + 1; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 }; // [1, 12]
    if m <= 2 {
        y += 1;
    }

    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        y, m, d, hour, minute, second
    )
}

impl PersonaFsm {
    /// Construct a new state machine for `(org_id, persona_id)` in the
    /// `Uninstantiated` initial state. Uses [`default_clock`] for
    /// timestamps; tests should call [`with_clock`] to pin.
    pub fn new(persona_id: impl Into<String>, org_id: impl Into<String>) -> Self {
        Self {
            state: FsmState::Uninstantiated,
            persona_id: persona_id.into(),
            org_id: org_id.into(),
            history: Vec::new(),
            clock: default_clock,
        }
    }

    /// Construct in an explicit initial state. Mirrors the Python
    /// `initial_state` constructor kwarg. Rejects unknown states
    /// (cannot happen via the enum surface — kept for symmetry).
    pub fn with_initial_state(
        persona_id: impl Into<String>,
        org_id: impl Into<String>,
        initial_state: FsmState,
    ) -> Self {
        Self {
            state: initial_state,
            persona_id: persona_id.into(),
            org_id: org_id.into(),
            history: Vec::new(),
            clock: default_clock,
        }
    }

    /// Replace the clock function. Returns `self` for fluent
    /// construction in tests.
    pub fn with_clock(mut self, clock: ClockFn) -> Self {
        self.clock = clock;
        self
    }

    /// Current lifecycle state.
    pub fn state(&self) -> FsmState {
        self.state
    }

    /// Persona identifier this machine tracks.
    pub fn persona_id(&self) -> &str {
        &self.persona_id
    }

    /// Org identifier this machine tracks.
    pub fn org_id(&self) -> &str {
        &self.org_id
    }

    /// Defensive read-only snapshot of the audit history.
    pub fn history(&self) -> Vec<TransitionRecord> {
        self.history.clone()
    }

    /// Borrow the audit history without cloning.
    pub fn history_ref(&self) -> &[TransitionRecord] {
        &self.history
    }

    /// Return `true` iff the machine can currently transition to
    /// `to_state` (the edge is in [`VALID_TRANSITIONS`]).
    pub fn can_transition_to(&self, to_state: FsmState) -> bool {
        is_valid_transition(self.state, to_state)
    }

    /// Attempt a transition.
    ///
    /// Appends a [`TransitionRecord`] in both the accepted and
    /// rejected case. Returns the accepted record on success, or
    /// [`FsmError::InvalidTransition`] on failure.
    pub fn transition(&mut self, to_state: FsmState) -> Result<TransitionRecord, FsmError> {
        if !is_valid_transition(self.state, to_state) {
            let rec = TransitionRecord {
                from_state: self.state,
                to_state,
                ts_utc: (self.clock)(),
                accepted: false,
                reason: Some("not_in_valid_transitions".to_string()),
            };
            self.history.push(rec);
            return Err(FsmError::InvalidTransition {
                from: self.state,
                to: to_state,
            });
        }
        let rec = TransitionRecord {
            from_state: self.state,
            to_state,
            ts_utc: (self.clock)(),
            accepted: true,
            reason: None,
        };
        self.history.push(rec.clone());
        self.state = to_state;
        Ok(rec)
    }

    /// Apply a pre-built transition struct. Convenience wrapper around
    /// [`transition`] that asserts the record's `from` field matches
    /// the current state.
    pub fn apply_transition(
        &mut self,
        transition: FsmTransition,
    ) -> Result<TransitionRecord, FsmError> {
        if transition.from != self.state {
            return Err(FsmError::InvalidTransition {
                from: self.state,
                to: transition.to,
            });
        }
        self.transition(transition.to)
    }

    /// Replay a transition log to rebuild a state machine. Mirrors
    /// Python `LifecycleStateMachine.replay` (recovery_workflow §3.7.4
    /// R2 "Reload").
    ///
    /// Rejected records are preserved in the rebuilt history (matches
    /// Python semantics: rejected attempts are audit-visible but do
    /// not change state). Accepted records are validated against
    /// [`VALID_TRANSITIONS`] and against the current replay state;
    /// any drift raises [`FsmError`].
    pub fn replay(
        persona_id: impl Into<String>,
        org_id: impl Into<String>,
        records: impl IntoIterator<Item = TransitionRecord>,
    ) -> Result<Self, FsmError> {
        let mut m = Self::new(persona_id, org_id);
        for rec in records {
            if !rec.accepted {
                m.history.push(rec);
                continue;
            }
            if !is_valid_transition(rec.from_state, rec.to_state) {
                return Err(FsmError::InvalidTransition {
                    from: rec.from_state,
                    to: rec.to_state,
                });
            }
            if rec.from_state != m.state {
                return Err(FsmError::ReplayDrift {
                    expected_from: m.state,
                    recorded_from: rec.from_state,
                    recorded_to: rec.to_state,
                });
            }
            m.state = rec.to_state;
            m.history.push(rec);
        }
        Ok(m)
    }
}

// ---------------------------------------------------------------------
// Spec-invariant self-check.
// ---------------------------------------------------------------------

/// Module-internal invariant check used by unit tests. Mirrors the
/// Python `_assert_spec_invariants` import-time guard.
///
/// - All transition endpoints reference declared states (trivially true
///   in Rust because the enum surface enforces it, but kept for
///   symmetry with the Python check).
/// - The transition table contains no duplicates.
pub fn assert_spec_invariants() -> Result<(), &'static str> {
    let mut seen: Vec<(FsmState, FsmState)> = Vec::with_capacity(VALID_TRANSITIONS.len());
    for t in VALID_TRANSITIONS {
        if seen.contains(&(t.from, t.to)) {
            return Err("lifecycle FSM drift: duplicate transitions");
        }
        seen.push((t.from, t.to));
    }
    Ok(())
}

// ---------------------------------------------------------------------
// Library-internal unit tests (smoke for module-import-time invariants).
// ---------------------------------------------------------------------

#[cfg(test)]
mod lib_tests {
    use super::*;

    #[test]
    fn spec_invariants_hold() {
        assert_spec_invariants().expect("spec invariants must hold at build time");
    }

    #[test]
    fn nine_transitions_exactly() {
        // Spec §3.3 says nine — drift sentinel.
        assert_eq!(VALID_TRANSITIONS.len(), 9);
    }

    #[test]
    fn six_states_exactly() {
        assert_eq!(STATES.len(), 6);
    }

    #[test]
    fn rfc3339_format_smoke() {
        // 2026-05-17T00:00:00Z corresponds to the well-known UNIX
        // value below (cross-checked against `date -u -d
        // '2026-05-17T00:00:00Z' +%s`).
        assert_eq!(format_rfc3339_utc(1_778_976_000), "2026-05-17T00:00:00Z");
        assert_eq!(format_rfc3339_utc(0), "1970-01-01T00:00:00Z");
    }
}
