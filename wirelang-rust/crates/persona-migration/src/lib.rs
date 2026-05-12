// SPDX-License-Identifier: Apache-2.0
//! Self-migration step registry — Rust pendant.
//!
//! This crate mirrors `wirelang.persona._internal.migration_steps`
//! (the `V0ToV1Step` / `V1ToV2Step` classes and the flat
//! `REGISTERED_STEPS` tuple). Each step captures one schema-version
//! transition `v_n -> v_{n+1}`. Multi-step chains are exercised in the
//! test layer here by direct composition; the full chain-resolver
//! (Python `_resolve_chain` in `wirelang.persona.persona_migration`)
//! is a separate Phase-1c follow-up crate.
//!
//! Determinism contract
//! --------------------
//!
//! For the V9 ground-truth canonical subset (Phase-1b Sprint-3 Tag-3
//! pin pack):
//!
//! - `V0ToV1Step::apply(v8_canonical)` produces a dict whose
//!   `sha256(canonical_jcs_bytes(...))` equals
//!   `PERSONA_HASH_PIN_V8_MIGRATED_TO_V1` (= `PERSONA_HASH_PIN_V9` by
//!   construction: v8 and v9 share every canonical-subset key except
//!   `schema_version`, and the step lifts exactly that key).
//! - `V1ToV2Step::apply(v9_canonical)` produces a dict whose
//!   `sha256(canonical_jcs_bytes(...))` equals
//!   `PERSONA_HASH_PIN_V9_MIGRATED_TO_V2`.
//! - The composed chain `V1ToV2Step::apply(V0ToV1Step::apply(v8))`
//!   produces a dict whose hash equals
//!   `PERSONA_HASH_PIN_V8_MIGRATED_TO_V2` (= `PERSONA_HASH_PIN_V9_MIGRATED_TO_V2`
//!   by construction; this is the **M-1 linear-chain direct-anchor**
//!   that Sprint-2 flagged as currently indirect).
//!
//! All three byte-identities are asserted in the test suite below.
//!
//! Default-Lock posture (mirrors Python `migration_steps.py`)
//! ----------------------------------------------------------
//!
//! - **A-1 Mock-Format-Baseline:** steps operate on the V-907 mock
//!   canonical subset (a `serde_json::Value::Object`), never on raw
//!   markdown. YAML front-matter parsing lives upstream in
//!   `persona-canonical-form-yaml`.
//! - **A-2 Additiv-only, linear-chain:** every step is additive on
//!   the `v_{n+1}` side. Removing a key in `v_{n+1}` is forbidden
//!   (forward-compat regression).
//! - **A-3 Body out-of-hash:** body-edits are not the converter's
//!   concern. Steps operate on the canonical subset only.
//! - **D-2 mitigation:** every default value the step injects is
//!   written *explicitly* in code, never via JSON-Schema default
//!   inference (Tag-4 Skizze §2.3). Sprint-4 Tag-4 V0->V1 and V1->V2
//!   are pure `schema_version` const flips with no other default
//!   injection — the strictest possible D-2-explicit posture.
//!
//! Public surface
//! --------------
//!
//! - [`PersonaMigrationStepError`] — error enum (input shape,
//!   schema-version mismatch).
//! - [`MigrationStep`] — trait modelling a single step.
//! - [`V0ToV1Step`] / [`V1ToV2Step`] — concrete steps.
//! - [`registered_steps`] — flat ordered registry mirror of Python
//!   `REGISTERED_STEPS`.
//! - Pin-pack mirror constants:
//!   - [`PERSONA_HASH_PIN_V9`]
//!   - [`PERSONA_HASH_PIN_V8_MIGRATED_TO_V1`]
//!   - [`PERSONA_HASH_PIN_V9_MIGRATED_TO_V2`]
//!   - [`PERSONA_HASH_PIN_V8_MIGRATED_TO_V2`]

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use serde_json::{Map, Value};

// ---------------------------------------------------------------------
// Pin-pack mirror constants
// ---------------------------------------------------------------------
//
// Verbatim mirrors of the values frozen in
// `wirelang/persona/_internal/pin_pack_constants.py` (Phase-1b
// Sprint-1 Tag-2 for V9, Sprint-2 Tag-1 for V8_MIGRATED_TO_V1,
// Sprint-3 Tag-3 for V9_MIGRATED_TO_V2 / V8_MIGRATED_TO_V2). Any drift
// in JCS canonicalisation, in the canonical-subset shape, or in the
// step output trips the cross-check tests below.

/// V9 ground-truth pin (Sprint-1 Tag-2 baseline).
///
/// Equal to Python `wirelang.persona._internal.pin_pack_constants.PERSONA_HASH_PIN_V9`.
pub const PERSONA_HASH_PIN_V9: &str =
    "sha256:0f298894204e6117e42ad7073b7a3af8ada1851de74d585fc5cb4c4d70e1d793";

/// Self-migration target pin: hash of the canonical subset produced
/// by `V0ToV1Step::apply` on the V8 canonical subset.
///
/// Equal to [`PERSONA_HASH_PIN_V9`] by construction — V8 and V9 share
/// every canonical-subset key except `schema_version`, and the step
/// lifts exactly that key. Mirrors Python
/// `PERSONA_HASH_PIN_V8_MIGRATED_TO_V1`.
pub const PERSONA_HASH_PIN_V8_MIGRATED_TO_V1: &str = PERSONA_HASH_PIN_V9;

/// Self-migration target pin: hash of the canonical subset produced
/// by `V1ToV2Step::apply` on the V9 canonical subset.
///
/// **Not** equal to [`PERSONA_HASH_PIN_V9`] (Tag-1-Sketch §3 explicit
/// design choice — the canonical subset *includes* `schema_version`,
/// so lifting v1 to v2 yields a new hash). Mirrors Python
/// `PERSONA_HASH_PIN_V9_MIGRATED_TO_V2`.
pub const PERSONA_HASH_PIN_V9_MIGRATED_TO_V2: &str =
    "sha256:f719fce4bedd8522874ae214ec2f982ef87964b535ca368134b3636207eb6669";

/// Self-migration target pin: hash of the canonical subset produced
/// by chaining `[V0ToV1Step, V1ToV2Step]` on the V8 canonical subset.
///
/// Equal to [`PERSONA_HASH_PIN_V9_MIGRATED_TO_V2`] by construction —
/// the chain endpoint sets `schema_version=persona-v2` either way.
/// This is the **M-1 (linear-chain) direct-anchor** test vector.
/// Mirrors Python `PERSONA_HASH_PIN_V8_MIGRATED_TO_V2`.
pub const PERSONA_HASH_PIN_V8_MIGRATED_TO_V2: &str = PERSONA_HASH_PIN_V9_MIGRATED_TO_V2;

// ---------------------------------------------------------------------
// Error surface
// ---------------------------------------------------------------------

/// Error class for a single migration step.
///
/// Variants mirror the Python step error surface: `TypeError`
/// (non-dict input) → [`PersonaMigrationStepError::NotAnObject`] and
/// `ValueError` (wrong `schema_version`) →
/// [`PersonaMigrationStepError::SourceVersionMismatch`].
#[derive(Debug, PartialEq, Eq)]
pub enum PersonaMigrationStepError {
    /// Input is not a JSON object. The canonical subset is by spec a
    /// top-level object; arrays / scalars are rejected. The Rust type
    /// system is stricter than the Python duck-typing, but we keep an
    /// explicit guard so the trait contract surfaces a single uniform
    /// error type to upstream callers.
    NotAnObject,

    /// Input dict has no `schema_version` key, or the value is not a
    /// string. The Python step raises `ValueError` with the same
    /// semantics.
    MissingOrInvalidSchemaVersion,

    /// Input dict's `schema_version` does not match this step's
    /// declared `source_version()`. Mirrors Python `ValueError` with
    /// the same message shape.
    SourceVersionMismatch {
        /// What the step expected (its `source_version()`).
        expected: &'static str,
        /// What was actually present in the input dict.
        actual: String,
    },
}

impl std::fmt::Display for PersonaMigrationStepError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PersonaMigrationStepError::NotAnObject => {
                f.write_str("migration step input must be a JSON object")
            }
            PersonaMigrationStepError::MissingOrInvalidSchemaVersion => {
                f.write_str("migration step input has no schema_version key, or it is not a string")
            }
            PersonaMigrationStepError::SourceVersionMismatch { expected, actual } => {
                write!(
                    f,
                    "migration step expected schema_version={expected:?}, got {actual:?}"
                )
            }
        }
    }
}

impl std::error::Error for PersonaMigrationStepError {}

// ---------------------------------------------------------------------
// MigrationStep trait
// ---------------------------------------------------------------------

/// Single-step migration `v_n -> v_{n+1}`.
///
/// Trait pendant of the Python `MigrationStep` Protocol. Concrete
/// implementations must be deterministic: `apply(d)` called twice with
/// byte-identical input must produce byte-identical output (the V-907
/// pin pillar depends on this).
///
/// The input `Value` is **not** mutated; implementations clone the
/// object before editing (Rust ownership makes this a non-issue at the
/// type level, but the rule is named here so the contract maps 1:1
/// onto Python's `copy.deepcopy` discipline).
pub trait MigrationStep {
    /// The `schema_version` value this step expects on input.
    fn source_version(&self) -> &'static str;

    /// The `schema_version` value this step writes on output.
    fn target_version(&self) -> &'static str;

    /// Apply the step to a canonical-subset object.
    ///
    /// Returns a new `Value::Object` whose `schema_version` equals
    /// `target_version()`. Other keys pass through unchanged.
    fn apply(&self, definition: &Value) -> Result<Value, PersonaMigrationStepError>;
}

// Shared helper: clone the input object, verify the source version,
// flip the schema_version key. Used by both V0->V1 and V1->V2 because
// in Sprint-4 Tag-4 they are *both* pure schema_version const flips
// per the Default-Lock D-2-explicit-default-only posture.
fn apply_const_flip(
    definition: &Value,
    expected_source: &'static str,
    target: &'static str,
) -> Result<Value, PersonaMigrationStepError> {
    let Some(obj) = definition.as_object() else {
        return Err(PersonaMigrationStepError::NotAnObject);
    };
    let actual_source = match obj.get("schema_version") {
        Some(Value::String(s)) => s.as_str(),
        Some(_) | None => {
            return Err(PersonaMigrationStepError::MissingOrInvalidSchemaVersion);
        }
    };
    if actual_source != expected_source {
        return Err(PersonaMigrationStepError::SourceVersionMismatch {
            expected: expected_source,
            actual: actual_source.to_owned(),
        });
    }
    // Deep-clone the object and overwrite schema_version. Cloning a
    // serde_json::Value performs a recursive copy; the input remains
    // untouched.
    let mut out: Map<String, Value> = obj.clone();
    out.insert(
        "schema_version".to_owned(),
        Value::String(target.to_owned()),
    );
    Ok(Value::Object(out))
}

// ---------------------------------------------------------------------
// V0ToV1Step
// ---------------------------------------------------------------------

/// `persona-v0 -> persona-v1` schema-version lift.
///
/// Mirrors Python `wirelang.persona._internal.migration_steps.V0ToV1Step`.
/// Per Tag-4 Skizze §3.2 R1-R4 and Default-Lock A-1/A-2/A-3, the v0
/// to v1 transition is a schema-version edit only. All other top-level
/// keys, the full `identity_pinned` block, and the markdown body
/// (out-of-hash per A-3) pass through unchanged.
#[derive(Debug, Default, Clone, Copy)]
pub struct V0ToV1Step;

impl MigrationStep for V0ToV1Step {
    fn source_version(&self) -> &'static str {
        "persona-v0"
    }

    fn target_version(&self) -> &'static str {
        "persona-v1"
    }

    fn apply(&self, definition: &Value) -> Result<Value, PersonaMigrationStepError> {
        apply_const_flip(definition, self.source_version(), self.target_version())
    }
}

// ---------------------------------------------------------------------
// V1ToV2Step
// ---------------------------------------------------------------------

/// `persona-v1 -> persona-v2` schema-version lift.
///
/// Mirrors Python `wirelang.persona._internal.migration_steps.V1ToV2Step`.
/// Per Tag-1-Sketch §3 (Phase-1b Sprint-3 Tag-1, V10-Migration-
/// Vorbereitung) and Default-Lock A-1/A-2/A-3, the v1 to v2 transition
/// is a schema-version edit only. The persona-v2 schema authored at
/// Sprint-3 Tag-2 (`wirelang/schemas/persona-v2.json`) opens a closed
/// allow-list of additive optional fields and three reserved top-level
/// keys; none of those are injected by this step (D-2-explicit
/// posture, Tag-4 Skizze §2.3).
///
/// Pin-pack consequence: the canonical subset *includes* `schema_version`,
/// so the V9-migrated-to-V2 hash is **not** equal to the V9 hash. See
/// [`PERSONA_HASH_PIN_V9_MIGRATED_TO_V2`].
#[derive(Debug, Default, Clone, Copy)]
pub struct V1ToV2Step;

impl MigrationStep for V1ToV2Step {
    fn source_version(&self) -> &'static str {
        "persona-v1"
    }

    fn target_version(&self) -> &'static str {
        "persona-v2"
    }

    fn apply(&self, definition: &Value) -> Result<Value, PersonaMigrationStepError> {
        apply_const_flip(definition, self.source_version(), self.target_version())
    }
}

// ---------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------

/// Flat, ordered registry of migration steps.
///
/// Mirrors Python `REGISTERED_STEPS = (V0ToV1Step(), V1ToV2Step())`.
/// The trait-object boxing is the Rust idiom for "list of
/// heterogeneous concrete types behind one Protocol"; the steps
/// themselves are zero-sized, so this allocation is incidental, not
/// semantic.
///
/// The full chain resolver (Python `_resolve_chain`) is a Phase-1c
/// follow-up crate; Sprint-4 Tag-4 keeps the resolver Python-side and
/// exercises the chain here via direct composition.
pub fn registered_steps() -> Vec<Box<dyn MigrationStep>> {
    vec![Box::new(V0ToV1Step), Box::new(V1ToV2Step)]
}

#[cfg(test)]
mod tests {
    use super::*;
    use persona_canonical_form::canonical_jcs_bytes;
    use serde_json::json;
    use sha2::{Digest, Sha256};

    // -------------------------------------------------------------------
    // Test fixtures: hand-built canonical subsets matching the Python
    // V8 / V9 fixtures. Verified against Python on 2026-05-11 by:
    //
    //   sha256(canonical_jcs_bytes(v9)) == PERSONA_HASH_PIN_V9
    //
    // V8 and V9 share every canonical-subset key except schema_version.
    // -------------------------------------------------------------------

    /// V8 canonical subset (schema_version=persona-v0).
    fn v8_canonical_subset() -> Value {
        json!({
            "description": "Pre-framework persona fixture for self-migration vector (v8, schema persona-v0-ish \u{2014} flagged as unsupported).",
            "identity_pinned": {
                "authority": {
                    "budget_cap_eur_per_month": 0,
                    "push_remote": false,
                    "sub_delegation": false
                },
                "cross_review_zones": [],
                "hierarchy": {
                    "escalation": "cto",
                    "reports_to": "cto"
                }
            },
            "name": "pre-framework-agent",
            "schema_version": "persona-v0",
            "tools": ["Read"]
        })
    }

    /// V9 canonical subset (schema_version=persona-v1). Identical to
    /// the V9 fixture in `persona-canonical-form/src/lib.rs` tests.
    fn v9_canonical_subset() -> Value {
        json!({
            "description": "Pre-framework persona fixture for self-migration vector (v8, schema persona-v0-ish \u{2014} flagged as unsupported).",
            "identity_pinned": {
                "authority": {
                    "budget_cap_eur_per_month": 0,
                    "push_remote": false,
                    "sub_delegation": false
                },
                "cross_review_zones": [],
                "hierarchy": {
                    "escalation": "cto",
                    "reports_to": "cto"
                }
            },
            "name": "pre-framework-agent",
            "schema_version": "persona-v1",
            "tools": ["Read"]
        })
    }

    fn sha256_hex(bytes: &[u8]) -> String {
        let mut hasher = Sha256::new();
        hasher.update(bytes);
        let digest = hasher.finalize();
        let mut s = String::with_capacity(64);
        for byte in digest {
            use std::fmt::Write;
            write!(s, "{byte:02x}").expect("hex write");
        }
        s
    }

    /// Compute the full `"sha256:<64hex>"` pin string for a canonical
    /// subset Value. Equivalent in shape to Python
    /// `compute_persona_hash_from_canonical` minus the schema-version
    /// guard (the steps themselves enforce the version contract).
    fn pin_of(canon: &Value) -> String {
        let blob = canonical_jcs_bytes(canon).expect("canonicalise");
        format!("sha256:{}", sha256_hex(&blob))
    }

    // -------------------------------------------------------------------
    // 1 / V0->V1 byte-identity — V8 migrated to V1 must match the
    //     V8_MIGRATED_TO_V1 pin (= V9 pin by construction). Mirrors
    //     Python test_persona_migration::test_v8_to_v1_pin_match.
    // -------------------------------------------------------------------

    #[test]
    fn t1_v0_to_v1_pin_match_v8_to_v1() {
        let step = V0ToV1Step;
        assert_eq!(step.source_version(), "persona-v0");
        assert_eq!(step.target_version(), "persona-v1");

        let v8 = v8_canonical_subset();
        let migrated = step.apply(&v8).expect("V8 must migrate to V1");
        assert_eq!(
            migrated["schema_version"], "persona-v1",
            "post-migration schema_version must be persona-v1"
        );

        let got_pin = pin_of(&migrated);
        assert_eq!(
            got_pin, PERSONA_HASH_PIN_V8_MIGRATED_TO_V1,
            "V8-migrated-to-V1 pin must match Python PERSONA_HASH_PIN_V8_MIGRATED_TO_V1"
        );
        assert_eq!(
            got_pin, PERSONA_HASH_PIN_V9,
            "V8-migrated-to-V1 pin must equal V9 pin by construction"
        );
    }

    // -------------------------------------------------------------------
    // 2 / V1->V2 byte-identity — V9 migrated to V2 must match the
    //     V9_MIGRATED_TO_V2 pin. Mirrors Python
    //     test_persona_migration_v1_to_v2::test_v1_to_v2_pin_match.
    // -------------------------------------------------------------------

    #[test]
    fn t2_v1_to_v2_pin_match_v9_to_v2() {
        let step = V1ToV2Step;
        assert_eq!(step.source_version(), "persona-v1");
        assert_eq!(step.target_version(), "persona-v2");

        let v9 = v9_canonical_subset();
        let migrated = step.apply(&v9).expect("V9 must migrate to V2");
        assert_eq!(
            migrated["schema_version"], "persona-v2",
            "post-migration schema_version must be persona-v2"
        );

        let got_pin = pin_of(&migrated);
        assert_eq!(
            got_pin, PERSONA_HASH_PIN_V9_MIGRATED_TO_V2,
            "V9-migrated-to-V2 pin must match Python PERSONA_HASH_PIN_V9_MIGRATED_TO_V2"
        );
        assert_ne!(
            got_pin, PERSONA_HASH_PIN_V9,
            "V9-migrated-to-V2 pin must DIFFER from V9 pin (schema_version is in-hash)"
        );
    }

    // -------------------------------------------------------------------
    // 3 / Multi-step chain V8 -> V0 -> V1 -> V2. M-1 linear-chain
    //     direct-anchor. Mirrors Python
    //     test_persona_migration_v1_to_v2::test_v0_to_v2_full_chain_pin_match.
    // -------------------------------------------------------------------

    #[test]
    fn t3_v8_via_chain_to_v2_m1_direct_anchor() {
        let v8 = v8_canonical_subset();
        let after_v0_v1 = V0ToV1Step.apply(&v8).expect("V0->V1");
        assert_eq!(after_v0_v1["schema_version"], "persona-v1");

        let after_v1_v2 = V1ToV2Step.apply(&after_v0_v1).expect("V1->V2");
        assert_eq!(after_v1_v2["schema_version"], "persona-v2");

        let got_pin = pin_of(&after_v1_v2);
        assert_eq!(
            got_pin, PERSONA_HASH_PIN_V8_MIGRATED_TO_V2,
            "V8-chain-to-V2 pin must match Python PERSONA_HASH_PIN_V8_MIGRATED_TO_V2"
        );
        assert_eq!(
            got_pin, PERSONA_HASH_PIN_V9_MIGRATED_TO_V2,
            "V8-chain-to-V2 pin must equal V9-migrated-to-V2 by construction"
        );
    }

    // -------------------------------------------------------------------
    // 4 / Input not mutated — Python step-rule-2 deep-copy discipline.
    //     The Rust type system already prevents mutation through &Value,
    //     but we assert that the *output* is a fresh Object and the
    //     input retains its original schema_version.
    // -------------------------------------------------------------------

    #[test]
    fn t4_apply_does_not_mutate_input() {
        let v8 = v8_canonical_subset();
        let original_schema_version = v8["schema_version"].clone();

        let _migrated = V0ToV1Step.apply(&v8).expect("V0->V1");
        assert_eq!(
            v8["schema_version"], original_schema_version,
            "input dict's schema_version must remain persona-v0 after step"
        );

        let v9 = v9_canonical_subset();
        let original_v1 = v9["schema_version"].clone();
        let _ = V1ToV2Step.apply(&v9).expect("V1->V2");
        assert_eq!(
            v9["schema_version"], original_v1,
            "input dict's schema_version must remain persona-v1 after step"
        );
    }

    // -------------------------------------------------------------------
    // 5 / Run-to-run determinism — repeated apply on the same input
    //     yields byte-identical JCS output. Mirrors Python
    //     test_v1_to_v2_is_run_to_run_deterministic.
    // -------------------------------------------------------------------

    #[test]
    fn t5_apply_is_run_to_run_deterministic() {
        let v9 = v9_canonical_subset();
        let a = V1ToV2Step.apply(&v9).expect("first apply");
        let b = V1ToV2Step.apply(&v9).expect("second apply");
        let blob_a = canonical_jcs_bytes(&a).expect("JCS a");
        let blob_b = canonical_jcs_bytes(&b).expect("JCS b");
        assert_eq!(
            blob_a, blob_b,
            "two applies on the same input must produce byte-identical JCS output"
        );
    }

    // -------------------------------------------------------------------
    // 6 / Wrong source rejected — V0ToV1Step applied to a V1 input
    //     must return SourceVersionMismatch. Mirrors Python ValueError.
    // -------------------------------------------------------------------

    #[test]
    fn t6_wrong_source_version_rejected() {
        let v9 = v9_canonical_subset(); // schema_version=persona-v1
        let err = V0ToV1Step
            .apply(&v9)
            .expect_err("V0->V1 must reject persona-v1 input");
        match err {
            PersonaMigrationStepError::SourceVersionMismatch { expected, actual } => {
                assert_eq!(expected, "persona-v0");
                assert_eq!(actual, "persona-v1");
            }
            other => panic!("expected SourceVersionMismatch, got {other:?}"),
        }

        let v8 = v8_canonical_subset(); // schema_version=persona-v0
        let err2 = V1ToV2Step
            .apply(&v8)
            .expect_err("V1->V2 must reject persona-v0 input");
        match err2 {
            PersonaMigrationStepError::SourceVersionMismatch { expected, actual } => {
                assert_eq!(expected, "persona-v1");
                assert_eq!(actual, "persona-v0");
            }
            other => panic!("expected SourceVersionMismatch, got {other:?}"),
        }
    }

    // -------------------------------------------------------------------
    // 7 / Non-object input rejected — array and scalar.
    // -------------------------------------------------------------------

    #[test]
    fn t7_non_object_input_rejected() {
        let array = json!([1, 2, 3]);
        let err = V0ToV1Step.apply(&array).expect_err("array must error");
        assert_eq!(err, PersonaMigrationStepError::NotAnObject);

        let scalar = json!("just-a-string");
        let err2 = V1ToV2Step.apply(&scalar).expect_err("scalar must error");
        assert_eq!(err2, PersonaMigrationStepError::NotAnObject);
    }

    // -------------------------------------------------------------------
    // 8 / Missing or non-string schema_version rejected. Mirrors
    //     Python ValueError on `definition_dict.get("schema_version")
    //     != self.source_version`.
    // -------------------------------------------------------------------

    #[test]
    fn t8_missing_or_non_string_schema_version_rejected() {
        let no_sv = json!({"name": "x"});
        let err = V0ToV1Step
            .apply(&no_sv)
            .expect_err("missing schema_version must error");
        assert_eq!(
            err,
            PersonaMigrationStepError::MissingOrInvalidSchemaVersion
        );

        let non_string = json!({"schema_version": 42});
        let err2 = V0ToV1Step
            .apply(&non_string)
            .expect_err("non-string schema_version must error");
        assert_eq!(
            err2,
            PersonaMigrationStepError::MissingOrInvalidSchemaVersion
        );
    }

    // -------------------------------------------------------------------
    // 9 / Registry shape — `registered_steps()` returns exactly
    //     [V0ToV1Step, V1ToV2Step] in that order. Mirrors Python
    //     REGISTERED_STEPS sanity in
    //     test_v0_to_v2_full_chain_pin_match.
    // -------------------------------------------------------------------

    #[test]
    fn t9_registered_steps_shape() {
        let steps = registered_steps();
        assert_eq!(steps.len(), 2, "registry must hold exactly 2 steps");
        assert_eq!(steps[0].source_version(), "persona-v0");
        assert_eq!(steps[0].target_version(), "persona-v1");
        assert_eq!(steps[1].source_version(), "persona-v1");
        assert_eq!(steps[1].target_version(), "persona-v2");

        // Linear-chain integrity: each step's target equals the next
        // step's source (no holes, no DAG branching). Phase-1b
        // Default-Lock A-2 structural anchor.
        for w in steps.windows(2) {
            assert_eq!(
                w[0].target_version(),
                w[1].source_version(),
                "registry chain must be linear (step.target == next.source)"
            );
        }
    }

    // -------------------------------------------------------------------
    // 10 / Pin constants self-consistency. Two by-construction
    //      identities that the Python pin pack asserts in code, mirrored
    //      here so a Rust-side drift surfaces at unit-test granularity.
    // -------------------------------------------------------------------

    #[test]
    fn t10_pin_constants_self_consistency() {
        assert_eq!(
            PERSONA_HASH_PIN_V8_MIGRATED_TO_V1, PERSONA_HASH_PIN_V9,
            "V8_MIGRATED_TO_V1 must equal V9 pin (by construction)"
        );
        assert_eq!(
            PERSONA_HASH_PIN_V8_MIGRATED_TO_V2, PERSONA_HASH_PIN_V9_MIGRATED_TO_V2,
            "V8_MIGRATED_TO_V2 must equal V9_MIGRATED_TO_V2 (by construction)"
        );
        assert_ne!(
            PERSONA_HASH_PIN_V9, PERSONA_HASH_PIN_V9_MIGRATED_TO_V2,
            "V9 and V9_MIGRATED_TO_V2 must differ (schema_version is in-hash)"
        );
    }

    // -------------------------------------------------------------------
    // 11 / 10-iteration determinism stress on V0->V1 apply (Phase-1b
    //      Sprint-6 Tag-5 pin-pack coverage extension). Pattern mirror
    //      of Crate-1 t10 / Crate-2 t10. Goal: any non-determinism in
    //      `step.apply(d)` (e.g. dict-insertion-order leak, schema_version
    //      string allocation drift) would surface as cross-iteration
    //      drift here without needing the full chain resolver.
    // -------------------------------------------------------------------

    #[test]
    fn t11_v0_to_v1_apply_determinism_stress_10_iter() {
        let v8 = v8_canonical_subset();
        let baseline = V0ToV1Step.apply(&v8).expect("baseline apply");
        let baseline_blob = canonical_jcs_bytes(&baseline).expect("baseline JCS");
        let baseline_hex = sha256_hex(&baseline_blob);

        for i in 0..10 {
            let again = V0ToV1Step.apply(&v8).expect("iter apply");
            let blob = canonical_jcs_bytes(&again).expect("iter JCS");
            let hex = sha256_hex(&blob);
            assert_eq!(
                blob, baseline_blob,
                "iter {i}: JCS bytes drifted from baseline (V0->V1 must be byte-stable across applies)"
            );
            assert_eq!(
                hex, baseline_hex,
                "iter {i}: sha256 drifted from baseline (V0->V1 must hash-stable across applies)"
            );
        }

        // Baseline must equal V8_MIGRATED_TO_V1 pin (which equals
        // V9 pin by construction). Cross-anchor at the end of the
        // stress loop to catch a baseline-itself-drift across full
        // crate rebuilds.
        let baseline_pin = format!("sha256:{baseline_hex}");
        assert_eq!(baseline_pin, PERSONA_HASH_PIN_V8_MIGRATED_TO_V1);
        assert_eq!(baseline_pin, PERSONA_HASH_PIN_V9);
    }

    // -------------------------------------------------------------------
    // 12 / 10-iteration determinism stress on V1->V2 apply. Sister of
    //      t11; same posture, V1->V2 step.
    // -------------------------------------------------------------------

    #[test]
    fn t12_v1_to_v2_apply_determinism_stress_10_iter() {
        let v9 = v9_canonical_subset();
        let baseline = V1ToV2Step.apply(&v9).expect("baseline apply");
        let baseline_blob = canonical_jcs_bytes(&baseline).expect("baseline JCS");
        let baseline_hex = sha256_hex(&baseline_blob);

        for i in 0..10 {
            let again = V1ToV2Step.apply(&v9).expect("iter apply");
            let blob = canonical_jcs_bytes(&again).expect("iter JCS");
            let hex = sha256_hex(&blob);
            assert_eq!(
                blob, baseline_blob,
                "iter {i}: JCS bytes drifted from baseline (V1->V2 must be byte-stable across applies)"
            );
            assert_eq!(
                hex, baseline_hex,
                "iter {i}: sha256 drifted from baseline (V1->V2 must hash-stable across applies)"
            );
        }

        let baseline_pin = format!("sha256:{baseline_hex}");
        assert_eq!(baseline_pin, PERSONA_HASH_PIN_V9_MIGRATED_TO_V2);
    }

    // -------------------------------------------------------------------
    // 13 / V8-hex-pin hard-freeze on the POST-MIGRATION V0->V1 output.
    //      Mirror of Crate-1 t11 / Crate-2 t11 but on the migration
    //      output layer (not the input layer).
    //
    //      Pinning the raw hex tail here adds a second anchor that
    //      catches drift in the V0ToV1Step apply() logic that happens
    //      to produce a different but still pin-shaped output. The
    //      existing t1 anchor uses PERSONA_HASH_PIN_V8_MIGRATED_TO_V1
    //      ("sha256:..." form); the hex-tail variant here lets a
    //      future Python-side V8_MIGRATED_TO_V1_HEX constant cross-
    //      check without needing the full "sha256:" prefix re-derive.
    //
    //      Rust-only Sprint-6 Tag-5 addition. No Python pendant needed
    //      because Python's pin-pack ships full "sha256:<64hex>"
    //      constants and tests anchor against those directly.
    // -------------------------------------------------------------------

    /// V0->V1 migration output hex pin (Rust-only Sprint-6 Tag-5).
    /// Equals the 64-hex tail of [`PERSONA_HASH_PIN_V8_MIGRATED_TO_V1`]
    /// (= [`PERSONA_HASH_PIN_V9`] by construction). Pinning the hex
    /// form separately catches a regression where a malformed prefix
    /// would still match the full-form check.
    const V8_MIGRATED_TO_V1_HEX_RUST_ONLY: &str =
        "0f298894204e6117e42ad7073b7a3af8ada1851de74d585fc5cb4c4d70e1d793";

    #[test]
    fn t13_v0_to_v1_apply_output_hex_pin_hard_freeze() {
        // Hex pin computed from the actual V0->V1 step output to keep
        // this anchor self-consistent. If the constant ever drifts
        // from PERSONA_HASH_PIN_V9, both the equality assertion AND
        // the t1 / t11 baselines would surface the regression.
        let v8 = v8_canonical_subset();
        let migrated = V0ToV1Step.apply(&v8).expect("V0->V1 apply");
        let blob = canonical_jcs_bytes(&migrated).expect("JCS");
        let got_hex = sha256_hex(&blob);
        assert_eq!(
            got_hex, V8_MIGRATED_TO_V1_HEX_RUST_ONLY,
            "V0->V1 output hex must match V8_MIGRATED_TO_V1_HEX_RUST_ONLY hard-freeze"
        );
        // Cross-anchor: the hex constant must equal the 64-hex tail
        // of the canonical PERSONA_HASH_PIN_V9 constant.
        assert!(
            PERSONA_HASH_PIN_V9.ends_with(V8_MIGRATED_TO_V1_HEX_RUST_ONLY),
            "V8_MIGRATED_TO_V1_HEX_RUST_ONLY must be the tail of PERSONA_HASH_PIN_V9"
        );
    }

    /// V1->V2 migration output hex pin (Rust-only Sprint-6 Tag-5).
    /// Equals the 64-hex tail of [`PERSONA_HASH_PIN_V9_MIGRATED_TO_V2`].
    const V9_MIGRATED_TO_V2_HEX_RUST_ONLY: &str =
        "f719fce4bedd8522874ae214ec2f982ef87964b535ca368134b3636207eb6669";

    #[test]
    fn t14_v1_to_v2_apply_output_hex_pin_hard_freeze() {
        let v9 = v9_canonical_subset();
        let migrated = V1ToV2Step.apply(&v9).expect("V1->V2 apply");
        let blob = canonical_jcs_bytes(&migrated).expect("JCS");
        let got_hex = sha256_hex(&blob);
        assert_eq!(
            got_hex, V9_MIGRATED_TO_V2_HEX_RUST_ONLY,
            "V1->V2 output hex must match V9_MIGRATED_TO_V2_HEX_RUST_ONLY hard-freeze"
        );
        assert!(
            PERSONA_HASH_PIN_V9_MIGRATED_TO_V2.ends_with(V9_MIGRATED_TO_V2_HEX_RUST_ONLY),
            "V9_MIGRATED_TO_V2_HEX_RUST_ONLY must be the tail of PERSONA_HASH_PIN_V9_MIGRATED_TO_V2"
        );
    }

    // -------------------------------------------------------------------
    // 15 / Re-derivation roundtrip via registered_steps() iteration.
    //
    //      Walk the registry programmatically (not by hard-coded
    //      V0ToV1Step / V1ToV2Step references) and run V8 through the
    //      full chain. The final pin must match V8_MIGRATED_TO_V2.
    //
    //      Catches a regression where someone adds a new step to the
    //      registry but forgets to wire it into the chain resolver
    //      (Phase-1c follow-up crate); the registry order is the
    //      single source of truth for the chain shape.
    // -------------------------------------------------------------------

    #[test]
    fn t15_re_derivation_via_registered_steps_iteration() {
        let v8 = v8_canonical_subset();
        let mut current = v8;
        for step in registered_steps() {
            let expected_source = step.source_version();
            assert_eq!(
                current["schema_version"], expected_source,
                "registry-chain pre-step source mismatch"
            );
            current = step.apply(&current).expect("registry step apply");
            assert_eq!(
                current["schema_version"],
                step.target_version(),
                "registry-chain post-step target mismatch"
            );
        }
        let final_blob = canonical_jcs_bytes(&current).expect("final JCS");
        let final_pin = format!("sha256:{}", sha256_hex(&final_blob));
        assert_eq!(
            final_pin, PERSONA_HASH_PIN_V8_MIGRATED_TO_V2,
            "registry-iteration chain must reach V8_MIGRATED_TO_V2"
        );
        assert_eq!(
            final_pin, PERSONA_HASH_PIN_V9_MIGRATED_TO_V2,
            "registry-iteration chain pin equals V9_MIGRATED_TO_V2 by construction"
        );
    }
}
