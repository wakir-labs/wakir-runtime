// SPDX-License-Identifier: Apache-2.0
//! Deterministic-diff oracle for the Phase-3a Doppelbetrieb-Shadow bridge.
//!
//! Sprint-Bridge-Diff-Engine-Rust-MINI (ADR-0063 §Folgeartefakte Item 4).
//!
//! Rust port of `wirelang.persona_engine.bridge_audit_diff_engine`
//! (PR #106, the Python pendant of this crate). During the Phase-3a
//! Doppelbetrieb-Bridge window the Python persona-engine and the Rust
//! persona-engine run in parallel; both implementations MUST produce
//! byte-identical CloudEvent envelopes for the same logical input.
//! This crate is the surfacing tool that proves they do — or pins
//! exactly where they diverge.
//!
//! Determinism contract
//! --------------------
//!
//! The Rust [`jcs_hash`] is required to return the EXACT same
//! `"sha256:<64hex>"` string as the Python `jcs_hash` helper for any
//! given envelope. The smoke-test suite freezes two cross-language
//! anchor pins (empty envelope `{}` and a 306-byte CloudEvent envelope);
//! a future regression in `serde_jcs` / `serde_json` / `sha2` would
//! surface as a test failure.
//!
//! Comparison contract
//! -------------------
//!
//! [`compare_implementations`] takes a logical input descriptor
//! ([`DiffInput`]) and a pair of implementation adapters ([`Implementation`]).
//! It runs both implementations, JCS-canonicalises their resulting
//! envelopes, hashes the canonical bytes, and produces a [`DiffReport`]
//! with:
//!
//! - `byte_identical` — short-circuit boolean: `true` iff both JCS
//!   hashes match. The common-case fast path.
//! - `field_diffs` — list of structured [`FieldDiff`] entries when
//!   bytes diverge. Each entry pins a JSON-Pointer-style field path
//!   (RFC 6901; e.g. `"/data/output_payload_sha256"`) and the two
//!   values.
//! - `consistency_score` — float in `[0.0, 1.0]`. `1.0` = byte-
//!   identical; `0.0` = total drift (no shared fields). Computed as
//!   `1 - (drifted_leaves / total_leaves)` over the maximum of both
//!   envelopes' leaf counts.
//! - `jcs_hash_a` / `jcs_hash_b` — `"sha256:<64hex>"` of each
//!   implementation's canonical bytes.
//!
//! JSON-Pointer escaping
//! ---------------------
//!
//! Object keys are escaped per RFC 6901 § 4: `~` -> `~0`, `/` -> `~1`,
//! in that order. Array indices are decimal strings. The root envelope
//! path is the empty string `""`.
//!
//! Layering vs. persona-hash
//! -------------------------
//!
//! `persona-hash` operates on a hand-extracted canonical subset (the
//! V-907 hashable view of a persona definition). `persona-engine-bridge-
//! diff` operates on full CloudEvent envelopes (arbitrarily nested JSON
//! mappings, including implementation-private fields). Both crates
//! share the same canonicalisation primitive (`serde_jcs`) and the
//! same digest (`sha2::Sha256`); they differ in the shape and scope
//! of the inputs they accept.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

/// Prefix on every `"sha256:<64hex>"` string emitted by this crate.
/// Matches `persona_hash::PERSONA_HASH_PREFIX` and the Python
/// `bridge_audit_diff_engine.jcs_hash` output.
pub const HASH_PREFIX: &str = "sha256:";

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/// Error class for the diff engine.
///
/// Variants are intentionally narrow: with well-formed
/// `serde_json::Value` input the canonicaliser is total. We still
/// surface the error rather than panic, mirroring the Python module's
/// "raise rather than crash on programmer error" stance.
#[derive(Debug)]
pub enum BridgeDiffError {
    /// JCS canonicalisation failed. With well-formed
    /// `serde_json::Value` input this is unreachable in practice; we
    /// still surface the error rather than panic.
    CanonicaliseError(String),
}

impl std::fmt::Display for BridgeDiffError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BridgeDiffError::CanonicaliseError(msg) => {
                write!(f, "JCS canonicalisation failed: {msg}")
            }
        }
    }
}

impl std::error::Error for BridgeDiffError {}

// ---------------------------------------------------------------------------
// Public dataclasses
// ---------------------------------------------------------------------------

/// Logical input fed identically to both implementations.
///
/// Mirrors the Python `DiffInput` dataclass. The diff-engine does not
/// care how each implementation translates these fields into envelope
/// bytes; that is the comparison's whole point.
///
/// Fields:
///
/// - `org_id` / `persona_id` / `session_id`: identity tuple.
/// - `step_index`: 0-based emission counter within the session.
/// - `output_kind`: one of `"tool_call"`, `"reply"`,
///   `"audit_annotation"` — mirrors the persona-engine alphabet.
///   Implementations that use a different alphabet (e.g. the WAT-
///   anchor `action_type`) are expected to translate.
/// - `payload`: opaque bytes the implementation will hash.
/// - `ts_utc`: RFC-3339 UTC, second-precision; identical for both
///   implementations to remove clock-skew as a drift source.
#[derive(Debug, Clone, Serialize)]
pub struct DiffInput {
    /// Organisation identifier (e.g. `"wakir-labs"`).
    pub org_id: String,
    /// Persona identifier (e.g. `"mira"`).
    pub persona_id: String,
    /// Session identifier (opaque string).
    pub session_id: String,
    /// 0-based emission counter within the session.
    pub step_index: u32,
    /// Output kind alphabet member.
    pub output_kind: String,
    /// Opaque payload bytes the implementation will hash.
    pub payload: Vec<u8>,
    /// RFC-3339 UTC second-precision timestamp.
    pub ts_utc: String,
}

/// Adapter contract: run an implementation against a [`DiffInput`].
///
/// The diff-engine is intentionally generic over adapters so the same
/// machinery serves Python-engine-vs-WAT-anchor today AND Python-
/// engine-vs-Rust-engine in Phase-3a. The adapter is responsible for
/// translating [`DiffInput`] to its native call signature and
/// returning the resulting envelope as a `serde_json::Value`.
pub trait Implementation {
    /// Run the implementation on `input` and return its CloudEvent
    /// envelope as a [`serde_json::Value`] (must be `Value::Object`).
    fn run(&self, input: &DiffInput) -> Value;
}

// Blanket impl so closures and bare fns may be used as Implementation
// adapters without a newtype wrapper.
impl<F> Implementation for F
where
    F: Fn(&DiffInput) -> Value,
{
    fn run(&self, input: &DiffInput) -> Value {
        (self)(input)
    }
}

/// Kind of field-level divergence between two envelopes.
///
/// Mirrors the Python `DiffKind` enum.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DiffKind {
    /// Field present in both envelopes but values differ.
    ValueMismatch,
    /// Field present only in implementation A.
    OnlyInA,
    /// Field present only in implementation B.
    OnlyInB,
    /// Field present in both envelopes with structurally-equal value
    /// but different JSON number type (integer vs float).
    ///
    /// `serde_json` distinguishes integer and float number variants;
    /// a `1` (int) and a `1.0` (float) are equal-valued but produce
    /// different JCS bytes (`"1"` vs `"1"` — JCS normalises both to
    /// the same ECMA-262 string, but the round-trip via the
    /// `serde_json::Number` variant tag still differs). We surface this
    /// as drift so operators see implementation type-system differences.
    TypeMismatch,
}

impl DiffKind {
    /// Lower-case canonical string form, matching the Python enum's
    /// `.value` (e.g. `"value-mismatch"`). Used for operator-readable
    /// diff dumps and the cross-language test cross-check.
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            DiffKind::ValueMismatch => "value-mismatch",
            DiffKind::OnlyInA => "only-in-a",
            DiffKind::OnlyInB => "only-in-b",
            DiffKind::TypeMismatch => "type-mismatch",
        }
    }
}

/// One field-level drift entry in a [`DiffReport`].
///
/// The `path` is JSON-Pointer-style (RFC 6901): leading slash,
/// member tokens joined by `/`, array indices as decimal strings.
/// The root envelope is `""`.
#[derive(Debug, Clone, PartialEq)]
pub struct FieldDiff {
    /// RFC-6901 JSON-Pointer path (e.g. `"/data/output_payload_sha256"`).
    pub path: String,
    /// Kind of divergence at `path`.
    pub kind: DiffKind,
    /// Value at `path` in envelope A (or `Null` if absent).
    pub value_a: Value,
    /// Value at `path` in envelope B (or `Null` if absent).
    pub value_b: Value,
}

/// Outcome of a single diff-engine comparison.
///
/// Mirrors the Python `DiffReport` dataclass.
#[derive(Debug, Clone)]
pub struct DiffReport {
    /// `true` iff `jcs_hash_a == jcs_hash_b`. Fast-path indicator.
    pub byte_identical: bool,
    /// `"sha256:<64hex>"` of the implementation-A canonical bytes.
    pub jcs_hash_a: String,
    /// `"sha256:<64hex>"` of the implementation-B canonical bytes.
    pub jcs_hash_b: String,
    /// Ordered list of [`FieldDiff`] entries. Empty iff `byte_identical`.
    /// Order is deterministic (sorted by `path`).
    pub field_diffs: Vec<FieldDiff>,
    /// Float in `[0.0, 1.0]`. See module-level docstring.
    pub consistency_score: f64,
    /// Echo of implementation A's raw envelope for caller inspection.
    pub envelope_a: Value,
    /// Echo of implementation B's raw envelope for caller inspection.
    pub envelope_b: Value,
}

impl DiffReport {
    /// `true` iff the two envelopes drifted (i.e. not byte-identical).
    #[must_use]
    pub fn has_drift(&self) -> bool {
        !self.byte_identical
    }

    /// One-line operator-readable summary.
    #[must_use]
    pub fn summary(&self) -> String {
        if self.byte_identical {
            format!(
                "byte-identical jcs={} score={:.4}",
                self.jcs_hash_a, self.consistency_score
            )
        } else {
            format!(
                "drift fields={} score={:.4} hash_a={} hash_b={}",
                self.field_diffs.len(),
                self.consistency_score,
                self.jcs_hash_a,
                self.jcs_hash_b,
            )
        }
    }
}

// ---------------------------------------------------------------------------
// JCS canonicalisation + hash
// ---------------------------------------------------------------------------

/// JCS-canonicalise `envelope` to its RFC 8785 byte form.
///
/// Delegates to `serde_jcs::to_vec` so the diff-engine shares its
/// canonicaliser with the V-907 hash primitive (`persona-hash`).
/// Byte-identical to the Python `rfc8785` package for the JSON
/// subset Wakir envelopes use; the cross-language test suite
/// asserts this byte-for-byte against frozen anchor pins.
///
/// # Errors
///
/// Returns [`BridgeDiffError::CanonicaliseError`] if `serde_jcs`
/// rejects the value (in practice unreachable for well-formed
/// `serde_json::Value` input).
pub fn canonicalize_envelope(envelope: &Value) -> Result<Vec<u8>, BridgeDiffError> {
    serde_jcs::to_vec(envelope).map_err(|e| BridgeDiffError::CanonicaliseError(e.to_string()))
}

/// Return `"sha256:<64hex>"` of the envelope's JCS bytes.
///
/// Byte-identical to the Python `jcs_hash` helper. The hex tail is
/// lower-case to match `hashlib.sha256().hexdigest()`.
///
/// # Errors
///
/// See [`canonicalize_envelope`].
pub fn jcs_hash(envelope: &Value) -> Result<String, BridgeDiffError> {
    let bytes = canonicalize_envelope(envelope)?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    let digest = hasher.finalize();
    Ok(format!("{HASH_PREFIX}{}", hex::encode(digest)))
}

// ---------------------------------------------------------------------------
// Field-path diff (JSON-Pointer-style)
// ---------------------------------------------------------------------------

/// Escape a JSON-Pointer reference token per RFC 6901 § 4.
///
/// The order matters: `~` MUST be escaped to `~0` BEFORE `/` is
/// escaped to `~1`, otherwise a literal `~1` in the key would be
/// double-escaped.
fn escape_jp_token(token: &str) -> String {
    token.replace('~', "~0").replace('/', "~1")
}

/// Distinguishes a missing-key sentinel from a real `Value::Null`.
///
/// Mirrors the Python `_SENTINEL` constant. We cannot use
/// `Option<Value>` for the same purpose because the walker needs to
/// distinguish "key absent" from "key present with `null` value" —
/// `Option::None` for "absent" plus `Some(Value::Null)` for "present
/// null" works, and that is exactly what we do internally below.
#[derive(Debug, Clone, Copy)]
enum SidePresence<'v> {
    Absent,
    Present(&'v Value),
}

/// Recursively collect field-level diffs starting at `path`.
///
/// Comparison rules (mirror the Python `_walk`):
///
/// - If both values are plain mappings, recurse on the union of keys.
/// - If both values are lists, compare element-by-element. Length
///   mismatch surfaces an `OnlyInA` / `OnlyInB` entry per orphan index.
/// - Otherwise compare by value; `TypeMismatch` is emitted when the
///   `serde_json::Value` discriminants disagree but the values are
///   structurally equal (covers the int-vs-float numeric-precision-
///   drift case).
fn walk(path: &str, a: SidePresence<'_>, b: SidePresence<'_>, out: &mut Vec<FieldDiff>) {
    use SidePresence::{Absent, Present};

    match (a, b) {
        (Absent, Absent) => {
            // Cannot happen on a real walk (we never recurse into a key
            // that is absent on both sides), but the match is exhaustive
            // for clarity.
        }
        (Absent, Present(bv)) => {
            out.push(FieldDiff {
                path: path.to_string(),
                kind: DiffKind::OnlyInB,
                value_a: Value::Null,
                value_b: bv.clone(),
            });
        }
        (Present(av), Absent) => {
            out.push(FieldDiff {
                path: path.to_string(),
                kind: DiffKind::OnlyInA,
                value_a: av.clone(),
                value_b: Value::Null,
            });
        }
        (Present(av), Present(bv)) => walk_present(path, av, bv, out),
    }
}

fn walk_present(path: &str, av: &Value, bv: &Value, out: &mut Vec<FieldDiff>) {
    use SidePresence::{Absent, Present};

    // Both are objects -> recurse on union of keys.
    if let (Value::Object(am), Value::Object(bm)) = (av, bv) {
        let mut keys: Vec<&String> = am.keys().chain(bm.keys()).collect();
        keys.sort();
        keys.dedup();
        for k in keys {
            let child_path = format!("{path}/{}", escape_jp_token(k));
            let a_side = am.get(k).map_or(Absent, Present);
            let b_side = bm.get(k).map_or(Absent, Present);
            walk(&child_path, a_side, b_side, out);
        }
        return;
    }

    // Both are arrays -> index-by-index walk.
    if let (Value::Array(aa), Value::Array(ba)) = (av, bv) {
        let max_len = aa.len().max(ba.len());
        for i in 0..max_len {
            let child_path = format!("{path}/{i}");
            let a_side = aa.get(i).map_or(Absent, Present);
            let b_side = ba.get(i).map_or(Absent, Present);
            walk(&child_path, a_side, b_side, out);
        }
        return;
    }

    // Leaf comparison.
    //
    // serde_json discriminants: Null, Bool, Number, String, Array,
    // Object. We have already handled Object/Array above; the cases
    // here are Null, Bool, Number, String — plus the asymmetric case
    // where ONE side is a container and the other is a scalar.
    if av == bv {
        // Structural equality. Detect int-vs-float TYPE_MISMATCH for
        // numbers: serde_json treats `1` (Number::is_i64) and `1.0`
        // (Number::is_f64) as PartialEq-equal (the JSON spec sees both
        // as 1) — but the canonicaliser keeps the variant tag, so we
        // surface the type-mismatch.
        if let (Value::Number(an), Value::Number(bn)) = (av, bv) {
            let a_is_int = an.is_i64() || an.is_u64();
            let b_is_int = bn.is_i64() || bn.is_u64();
            if a_is_int != b_is_int {
                out.push(FieldDiff {
                    path: path.to_string(),
                    kind: DiffKind::TypeMismatch,
                    value_a: av.clone(),
                    value_b: bv.clone(),
                });
            }
        }
        // Otherwise fully equal -> no diff entry.
        return;
    }

    // Different values. If the JSON discriminants also differ
    // (e.g. Bool vs String, Number vs String, Object vs scalar),
    // prefer TYPE_MISMATCH so operators see the structural divergence.
    //
    // Special-case for numbers: serde_json::Value's PartialEq considers
    // `1` (int) and `1.0` (float) UNEQUAL — opposite of Python where
    // `1 == 1.0` is `True`. To preserve the Python `bridge_audit_diff_
    // engine`-parity for the operator-readable diff alphabet, we also
    // flag int-vs-float at-the-same-numeric-value as TYPE_MISMATCH here
    // (not just at PartialEq-equal in `walk_present`'s equal-branch).
    if value_discriminant(av) != value_discriminant(bv) {
        out.push(FieldDiff {
            path: path.to_string(),
            kind: DiffKind::TypeMismatch,
            value_a: av.clone(),
            value_b: bv.clone(),
        });
        return;
    }
    if let (Value::Number(an), Value::Number(bn)) = (av, bv) {
        let a_is_int = an.is_i64() || an.is_u64();
        let b_is_int = bn.is_i64() || bn.is_u64();
        if a_is_int != b_is_int {
            out.push(FieldDiff {
                path: path.to_string(),
                kind: DiffKind::TypeMismatch,
                value_a: av.clone(),
                value_b: bv.clone(),
            });
            return;
        }
    }
    out.push(FieldDiff {
        path: path.to_string(),
        kind: DiffKind::ValueMismatch,
        value_a: av.clone(),
        value_b: bv.clone(),
    });
}

/// Numeric discriminant for the JSON-type comparison. Matches the
/// Python `type(...)` check granularity at the JSON-type layer.
fn value_discriminant(v: &Value) -> u8 {
    match v {
        Value::Null => 0,
        Value::Bool(_) => 1,
        Value::Number(_) => 2,
        Value::String(_) => 3,
        Value::Array(_) => 4,
        Value::Object(_) => 5,
    }
}

/// Return field-level diff entries between two envelopes.
///
/// The result is sorted by `path` for deterministic comparison
/// across runs. Empty list iff the envelopes are structurally equal
/// (which implies byte-identical JCS output).
#[must_use]
pub fn diff_envelopes(envelope_a: &Value, envelope_b: &Value) -> Vec<FieldDiff> {
    let mut out: Vec<FieldDiff> = Vec::new();
    walk(
        "",
        SidePresence::Present(envelope_a),
        SidePresence::Present(envelope_b),
        &mut out,
    );
    out.sort_by(|x, y| x.path.cmp(&y.path));
    out
}

// ---------------------------------------------------------------------------
// Consistency score
// ---------------------------------------------------------------------------

/// Count leaf positions (non-container values) in a JSON tree.
///
/// Leaves are non-Object, non-Array values. Empty Object / empty Array
/// counts as a single leaf to keep the score well-defined for edge
/// cases.
fn count_leaves(value: &Value) -> usize {
    match value {
        Value::Object(m) => {
            if m.is_empty() {
                1
            } else {
                m.values().map(count_leaves).sum()
            }
        }
        Value::Array(a) => {
            if a.is_empty() {
                1
            } else {
                a.iter().map(count_leaves).sum()
            }
        }
        _ => 1,
    }
}

/// Compute the consistency score in `[0.0, 1.0]`.
///
/// Definition: `1 - (drifted_leaves / total_leaves)` where
/// `total_leaves` is `max(count_leaves(a), count_leaves(b))`. `1.0`
/// when `diffs` is empty (byte-identical); `0.0` when the drift count
/// meets or exceeds the leaf-count bound.
#[must_use]
pub fn consistency_score(envelope_a: &Value, envelope_b: &Value, diffs: &[FieldDiff]) -> f64 {
    if diffs.is_empty() {
        return 1.0;
    }
    let total_a = count_leaves(envelope_a);
    let total_b = count_leaves(envelope_b);
    let total = total_a.max(total_b);
    if total == 0 {
        return 1.0;
    }
    let drifted = diffs.len();
    if drifted >= total {
        return 0.0;
    }
    1.0 - (drifted as f64 / total as f64)
}

// ---------------------------------------------------------------------------
// Top-level compare
// ---------------------------------------------------------------------------

/// Run both implementations against `input` and produce a [`DiffReport`].
///
/// The function is pure with respect to its arguments: it does not
/// mutate `input`, and it does not touch the filesystem or network on
/// its own. Side-effects (if any) come from the implementation
/// adapters.
///
/// # Errors
///
/// Returns [`BridgeDiffError::CanonicaliseError`] if either envelope
/// fails JCS canonicalisation (unreachable in practice with
/// well-formed `serde_json::Value` input).
pub fn compare_implementations<A, B>(
    input: &DiffInput,
    impl_a: &A,
    impl_b: &B,
) -> Result<DiffReport, BridgeDiffError>
where
    A: Implementation,
    B: Implementation,
{
    let envelope_a = impl_a.run(input);
    let envelope_b = impl_b.run(input);
    let hash_a = jcs_hash(&envelope_a)?;
    let hash_b = jcs_hash(&envelope_b)?;
    if hash_a == hash_b {
        return Ok(DiffReport {
            byte_identical: true,
            jcs_hash_a: hash_a,
            jcs_hash_b: hash_b,
            field_diffs: Vec::new(),
            consistency_score: 1.0,
            envelope_a,
            envelope_b,
        });
    }
    let diffs = diff_envelopes(&envelope_a, &envelope_b);
    let score = consistency_score(&envelope_a, &envelope_b, &diffs);
    Ok(DiffReport {
        byte_identical: false,
        jcs_hash_a: hash_a,
        jcs_hash_b: hash_b,
        field_diffs: diffs,
        consistency_score: score,
        envelope_a,
        envelope_b,
    })
}
