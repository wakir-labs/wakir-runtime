// SPDX-License-Identifier: Apache-2.0
//! Multi-input `migrate_persona` dispatcher and linear chain resolver.
//!
//! This crate mirrors `wirelang.persona.persona_migration` (the
//! top-level `migrate_persona` function, the `_resolve_chain` helper,
//! the `_find_step_by_source` helper, and the
//! `expected_post_migration_hash` re-hash assertion). The step
//! registry itself lives in the sister `persona-migration` crate; this
//! crate consumes that registry and adds three things on top:
//!
//! 1. Multi-input dispatch: callers pass either a
//!    `serde_json::Value::Object` (already-parsed front-matter), a raw
//!    markdown `&str` (starting with `---`), or a filesystem `&Path`.
//!    `&str` / `&Path` inputs are routed through
//!    `persona-canonical-form-yaml`'s `split_frontmatter` +
//!    `parse_frontmatter` and the resulting YAML mapping is converted
//!    into a `serde_json::Value::Object` for the migration chain.
//! 2. Linear chain resolution: [`resolve_chain`] walks the registered
//!    steps from `source_version` to `target_version`, following each
//!    step's `target_version()` to the next step's `source_version()`,
//!    and surfaces a single [`PersonaMigrationError`] for unknown
//!    versions, dead-end heads, and suspected cycles
//!    (`_MAX_CHAIN_LENGTH = 32`, identical to Python).
//! 3. Optional post-migration re-hash assertion: when the caller
//!    supplies an `expected_post_migration_hash` (either full
//!    `"sha256:<64hex>"` or bare 64-hex), the migrated dict is
//!    projected onto the V-907 canonical subset, fed through
//!    JCS + SHA-256, and compared. A drift raises
//!    [`PersonaMigrationDeterminismError`].
//!
//! Determinism contract
//! --------------------
//!
//! For the three pin vectors frozen in
//! `wirelang.persona._internal.pin_pack_constants`:
//!
//! - V8 (`schema_version=persona-v0`) → V1: hash equals
//!   [`PERSONA_HASH_PIN_V8_MIGRATED_TO_V1`] (= [`PERSONA_HASH_PIN_V9`]
//!   by construction).
//! - V9 (`schema_version=persona-v1`) → V2: hash equals
//!   [`PERSONA_HASH_PIN_V9_MIGRATED_TO_V2`].
//! - V8 → chain → V2: hash equals [`PERSONA_HASH_PIN_V8_MIGRATED_TO_V2`]
//!   (= [`PERSONA_HASH_PIN_V9_MIGRATED_TO_V2`] by construction; **M-1
//!   linear-chain direct-anchor**).
//!
//! All three byte-identities are asserted in the test suite below and
//! cross-checked against the verbatim Python pins re-exported here
//! from `persona-migration`.
//!
//! Default-Lock posture (mirrors Python `persona_migration.py`)
//! -----------------------------------------------------------
//!
//! - **A-1 Mock-Format-Baseline:** the resolver operates on the same
//!   front-matter shape Python expects (a dict with `schema_version` +
//!   the canonical-subset top-level keys). YAML parsing is reused
//!   verbatim from `persona-canonical-form-yaml`.
//! - **A-2 Additiv-only, linear-chain:** the resolver walks one step
//!   at a time, `step.target_version() == next.source_version()`. No
//!   branching DAG. The 32-step guard is a cycle-detection backstop,
//!   not a feature; with two registered steps a real chain never
//!   exceeds length 2.
//! - **A-3 Body out-of-hash:** markdown body bytes are dropped by
//!   `split_frontmatter` and never reach this crate's hash path.
//!
//! Scope cut (Phase-1c Sprint-4 Tag-5)
//! -----------------------------------
//!
//! - **Persona-CLI (`wakir-persona migrate`):** Rust pendant lives in
//!   a separate `persona-cli` crate (Sprint-5/6 candidate).
//! - **WAT-leaf migration-audit-trail (Phase-2 P2-01):** Cross-Review
//!   Zone K, wat-eng owns; this crate emits the pre/post hash pair
//!   on request but does not produce a WAT-frame.
//! - **Branching DAG resolver (Phase-2):** linear chain only.
//!
//! Public surface
//! --------------
//!
//! - [`migrate_persona`] — multi-input dispatcher.
//! - [`MigrationInput`] — input enum (`Dict | Markdown | Path`).
//! - [`resolve_chain`] — linear chain resolver.
//! - [`find_step_by_source`] — single-step lookup helper.
//! - [`PersonaMigrationError`] — chain-not-resolvable error.
//! - [`PersonaMigrationDeterminismError`] — post-hash drift error.
//! - [`PERSONA_SCHEMA_VERSION_LATEST`] / [`PERSONA_SCHEMA_VERSION_LIST`]
//!   — schema-version constants.
//! - [`MAX_CHAIN_LENGTH`] — cycle-detection guard, mirror of Python
//!   `_MAX_CHAIN_LENGTH`.
//! - Re-exports from `persona-migration`: [`PERSONA_HASH_PIN_V9`],
//!   [`PERSONA_HASH_PIN_V8_MIGRATED_TO_V1`],
//!   [`PERSONA_HASH_PIN_V9_MIGRATED_TO_V2`],
//!   [`PERSONA_HASH_PIN_V8_MIGRATED_TO_V2`].

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use std::path::Path;

use persona_canonical_form_yaml::{
    parse_frontmatter, split_frontmatter, PersonaCanonicalFormYamlError,
};
use persona_migration::{
    registered_steps, MigrationStep, PersonaMigrationStepError, V0ToV1Step, V1ToV2Step,
};
use serde_json::{Map, Value};

// ---------------------------------------------------------------------
// Re-exported pin constants (Python pin-pack mirrors, verbatim from
// `persona-migration`). Re-exposed here so call-sites that only depend
// on `persona-migration-resolver` for the dispatcher API can still
// assert against the pins without a direct `persona-migration` dep.
// ---------------------------------------------------------------------

pub use persona_migration::{
    PERSONA_HASH_PIN_V8_MIGRATED_TO_V1, PERSONA_HASH_PIN_V8_MIGRATED_TO_V2, PERSONA_HASH_PIN_V9,
    PERSONA_HASH_PIN_V9_MIGRATED_TO_V2,
};

// ---------------------------------------------------------------------
// Schema-version constants (mirror of Python
// `wirelang.persona.persona_migration`)
// ---------------------------------------------------------------------

/// The engine's current hash-input schema version.
///
/// Mirrors Python `PERSONA_SCHEMA_VERSION_LATEST`. Stays at
/// `"persona-v1"` until the HR-slot ratifies persona-v2 content
/// (ADR-0029-Annex) or the Default-Lock window lifts the
/// engine-default-mock — neither has happened on Sprint-4 Tag-5, so a
/// bare `migrate_persona(definition, None, None)` call still targets
/// v1 by default.
pub const PERSONA_SCHEMA_VERSION_LATEST: &str = "persona-v1";

/// Ordered list of all schema-versions known to this build.
///
/// Mirror of Python `PERSONA_SCHEMA_VERSION_LIST`. The resolver
/// rejects sources or targets outside this list with
/// [`PersonaMigrationError::UnknownSchemaVersion`].
pub const PERSONA_SCHEMA_VERSION_LIST: &[&str] = &["persona-v0", "persona-v1", "persona-v2"];

/// Safety guard against cycles in the step registry.
///
/// The Phase-1b linear-chain assumption means a real chain never
/// exceeds the number of registered steps; anything larger indicates a
/// bug in step registration. Mirror of Python `_MAX_CHAIN_LENGTH = 32`.
pub const MAX_CHAIN_LENGTH: usize = 32;

// ---------------------------------------------------------------------
// Error surface
// ---------------------------------------------------------------------

/// A migration chain cannot be resolved, or the input shape is invalid.
///
/// Mirrors Python `PersonaMigrationError` plus the `TypeError` branch
/// that Python uses for "raw-markdown without `---` fence". The Rust
/// type system rules out "not a dict | str | Path" at compile time
/// (the [`MigrationInput`] enum is closed), so the Rust enum has no
/// direct pendant of Python's `TypeError`.
#[derive(Debug)]
pub enum PersonaMigrationError {
    /// Source or target `schema_version` is not in
    /// [`PERSONA_SCHEMA_VERSION_LIST`].
    UnknownSchemaVersion {
        /// The offending version string (source or target).
        version: String,
        /// Whether this is a source or target failure.
        role: SchemaVersionRole,
    },

    /// The chain resolver hit a head from which no registered step
    /// continues. Mirrors Python "no migration step registered from
    /// {cur!r} towards {target_version!r}".
    NoStepFromHead {
        /// The chain head at the point of failure.
        head: String,
        /// The target the resolver was walking towards.
        target: String,
    },

    /// The chain exceeded [`MAX_CHAIN_LENGTH`]. Indicates a cycle in
    /// the step registry. Mirror of Python
    /// "migration chain length exceeded {_MAX_CHAIN_LENGTH} steps".
    CycleSuspected,

    /// The front-matter dict has no `schema_version` key. Mirror of
    /// Python "persona front-matter has no schema_version key".
    MissingSchemaVersion,

    /// The front-matter `schema_version` is not a string. Mirror of
    /// Python "persona schema_version must be a string".
    SchemaVersionNotString {
        /// `serde_json` type-name of the wrong-typed value.
        got_type: &'static str,
    },

    /// The input is not a JSON object. The full front-matter is by
    /// spec a top-level object; arrays / scalars are rejected.
    NotAnObject,

    /// Raw-markdown input does not start with `---`. Mirror of Python
    /// "raw-markdown input must start with a '---' YAML front-matter
    /// fence".
    RawMarkdownMissingFence,

    /// YAML front-matter parse failed (missing/closing fence, malformed
    /// mapping, or YAML parser error). Mirror of Python wrapping of
    /// `PersonaFrontmatterMissingError` / `PersonaFrontmatterMalformedError`
    /// into `PersonaMigrationError` with `__cause__` chained.
    FrontmatterParse(PersonaCanonicalFormYamlError),

    /// A registered step rejected the current head dict (wrong shape
    /// or wrong source_version). Mirror of Python letting the
    /// step-level error bubble through.
    StepFailed(PersonaMigrationStepError),

    /// Filesystem error reading a [`Path`] input.
    Io(std::io::ErrorKind, String),
}

/// Role of a schema-version in a [`PersonaMigrationError::UnknownSchemaVersion`].
#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub enum SchemaVersionRole {
    /// The source (input) version is unknown.
    Source,
    /// The target (requested) version is unknown.
    Target,
}

impl std::fmt::Display for PersonaMigrationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::UnknownSchemaVersion { version, role } => {
                let label = match role {
                    SchemaVersionRole::Source => "source",
                    SchemaVersionRole::Target => "target",
                };
                write!(
                    f,
                    "unknown {label} schema_version={version:?}; known versions: {:?}",
                    PERSONA_SCHEMA_VERSION_LIST
                )
            }
            Self::NoStepFromHead { head, target } => write!(
                f,
                "no migration step registered from {head:?} towards {target:?}"
            ),
            Self::CycleSuspected => write!(
                f,
                "migration chain length exceeded {MAX_CHAIN_LENGTH} steps; suspect a cycle in registered_steps()"
            ),
            Self::MissingSchemaVersion => f.write_str(
                "persona front-matter has no schema_version key; cannot resolve migration source",
            ),
            Self::SchemaVersionNotString { got_type } => {
                write!(f, "persona schema_version must be a string, got {got_type}")
            }
            Self::NotAnObject => f.write_str("migrate_persona input must be a JSON object"),
            Self::RawMarkdownMissingFence => f.write_str(
                "raw-markdown input must start with a '---' YAML front-matter fence; pass a Path or a Value otherwise",
            ),
            Self::FrontmatterParse(e) => write!(f, "persona-definition is irreparable: {e}"),
            Self::StepFailed(e) => write!(f, "migration step failed: {e}"),
            Self::Io(kind, msg) => write!(f, "filesystem error ({kind:?}): {msg}"),
        }
    }
}

impl std::error::Error for PersonaMigrationError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::FrontmatterParse(e) => Some(e),
            Self::StepFailed(e) => Some(e),
            _ => None,
        }
    }
}

impl From<PersonaCanonicalFormYamlError> for PersonaMigrationError {
    fn from(e: PersonaCanonicalFormYamlError) -> Self {
        Self::FrontmatterParse(e)
    }
}

impl From<PersonaMigrationStepError> for PersonaMigrationError {
    fn from(e: PersonaMigrationStepError) -> Self {
        Self::StepFailed(e)
    }
}

/// Post-migration hash drift.
///
/// Mirror of Python `PersonaMigrationDeterminismError`. Raised by
/// [`migrate_persona`] when `expected_post_migration_hash` is supplied
/// and disagrees with the freshly-computed hash of the projected
/// canonical subset of the migration output.
#[derive(Debug)]
pub struct PersonaMigrationDeterminismError {
    /// The pin the caller supplied, normalised to full
    /// `"sha256:<64hex>"` form.
    pub expected: String,
    /// The pin the resolver actually computed, in full
    /// `"sha256:<64hex>"` form.
    pub computed: String,
}

impl std::fmt::Display for PersonaMigrationDeterminismError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "post-migration hash drift: expected {}, computed {}",
            self.expected, self.computed
        )
    }
}

impl std::error::Error for PersonaMigrationDeterminismError {}

// ---------------------------------------------------------------------
// Multi-input dispatch
// ---------------------------------------------------------------------

/// Multi-input wrapper for [`migrate_persona`].
///
/// Mirror of Python `dict | str | Path` polymorphism. The Rust type
/// system requires the variant to be named explicitly at the call
/// site; this is a deliberate trade-off versus a duck-typed dispatch.
pub enum MigrationInput<'a> {
    /// Already-parsed front-matter as a `serde_json::Value::Object`.
    /// Cloned by the dispatcher to avoid mutating caller state
    /// (mirror of Python `copy.deepcopy(definition)`).
    Dict(&'a Value),

    /// Raw markdown text. Must start with a `---` YAML front-matter
    /// fence.
    Markdown(&'a str),

    /// Filesystem path to a persona markdown file. Read as UTF-8.
    Path(&'a Path),
}

// ---------------------------------------------------------------------
// Chain resolver
// ---------------------------------------------------------------------

/// Look up the registered step whose `source_version` equals
/// `source_version`.
///
/// Mirror of Python `_find_step_by_source`. Returns `None` when no
/// step matches (chain dead-end at this head).
pub fn find_step_by_source(source_version: &str) -> Option<Box<dyn MigrationStep>> {
    registered_steps()
        .into_iter()
        .find(|step| step.source_version() == source_version)
}

/// Resolve the linear chain from `source_version` to `target_version`.
///
/// Returns an empty `Vec` when `source_version == target_version`
/// (no-op migration).
///
/// Mirror of Python `_resolve_chain`. Both `source_version` and
/// `target_version` must be in [`PERSONA_SCHEMA_VERSION_LIST`]; the
/// chain follows the registered steps' `target_version()` → next
/// step's `source_version()` discipline (linear-chain Default-Lock
/// A-2). The 32-step guard catches cycles in the registry.
///
/// # Errors
///
/// - [`PersonaMigrationError::UnknownSchemaVersion`] for unknown
///   source or target.
/// - [`PersonaMigrationError::NoStepFromHead`] when the chain head
///   has no registered next step.
/// - [`PersonaMigrationError::CycleSuspected`] when the walk exceeds
///   [`MAX_CHAIN_LENGTH`].
pub fn resolve_chain(
    source_version: &str,
    target_version: &str,
) -> Result<Vec<Box<dyn MigrationStep>>, PersonaMigrationError> {
    if !PERSONA_SCHEMA_VERSION_LIST.contains(&source_version) {
        return Err(PersonaMigrationError::UnknownSchemaVersion {
            version: source_version.to_owned(),
            role: SchemaVersionRole::Source,
        });
    }
    if !PERSONA_SCHEMA_VERSION_LIST.contains(&target_version) {
        return Err(PersonaMigrationError::UnknownSchemaVersion {
            version: target_version.to_owned(),
            role: SchemaVersionRole::Target,
        });
    }
    if source_version == target_version {
        return Ok(Vec::new());
    }

    let mut chain: Vec<Box<dyn MigrationStep>> = Vec::new();
    let mut cur = source_version.to_owned();
    while cur != target_version {
        let Some(step) = find_step_by_source(&cur) else {
            return Err(PersonaMigrationError::NoStepFromHead {
                head: cur,
                target: target_version.to_owned(),
            });
        };
        let next = step.target_version().to_owned();
        chain.push(step);
        cur = next;
        if chain.len() > MAX_CHAIN_LENGTH {
            return Err(PersonaMigrationError::CycleSuspected);
        }
    }
    Ok(chain)
}

// ---------------------------------------------------------------------
// Input coercion (`_coerce_to_dict` pendant)
// ---------------------------------------------------------------------

/// Convert a `serde_yaml::Value` mapping into a `serde_json::Value`.
///
/// Recursive; preserves the YAML mapping's iteration order via
/// `serde_json::Map` (insertion-order preserving with the
/// `preserve_order` feature). Used by [`coerce_to_dict`] to bridge
/// the YAML parse output into the migration chain's JSON-native data
/// model.
///
/// The exhaustive YAML → JSON mapping is intentionally permissive:
/// non-string mapping keys are rejected; YAML tagged values are
/// unwrapped. The same shape constraints that Python's `yaml.safe_load`
/// applies (followed by dict-coercion) are enforced here at conversion
/// time, so the migration chain only ever sees a JSON object.
fn yaml_value_to_json(v: serde_yaml::Value) -> Result<Value, PersonaMigrationError> {
    Ok(match v {
        serde_yaml::Value::Null => Value::Null,
        serde_yaml::Value::Bool(b) => Value::Bool(b),
        serde_yaml::Value::Number(n) => {
            // serde_yaml::Number → serde_json::Number via serde_json's
            // parsing (handles i64 / u64 / f64 representations
            // uniformly).
            if let Some(i) = n.as_i64() {
                Value::Number(i.into())
            } else if let Some(u) = n.as_u64() {
                Value::Number(u.into())
            } else if let Some(f) = n.as_f64() {
                // serde_json forbids NaN/Inf in Number; fall back to
                // a string repr in that case (Python's str() on a YAML
                // float produces the same intent for downstream
                // canonicalisation, though that path is exercised by
                // no fixture in the V-907 pin pack).
                match serde_json::Number::from_f64(f) {
                    Some(num) => Value::Number(num),
                    None => Value::String(f.to_string()),
                }
            } else {
                Value::String(n.to_string())
            }
        }
        serde_yaml::Value::String(s) => Value::String(s),
        serde_yaml::Value::Sequence(seq) => {
            let mut out = Vec::with_capacity(seq.len());
            for item in seq {
                out.push(yaml_value_to_json(item)?);
            }
            Value::Array(out)
        }
        serde_yaml::Value::Mapping(m) => {
            let mut out = Map::with_capacity(m.len());
            for (k, v) in m {
                let key = match k {
                    serde_yaml::Value::String(s) => s,
                    other => {
                        return Err(PersonaMigrationError::FrontmatterParse(
                            PersonaCanonicalFormYamlError::InvalidShape(format!(
                                "non-string mapping key {other:?} not supported in persona front-matter"
                            )),
                        ))
                    }
                };
                out.insert(key, yaml_value_to_json(v)?);
            }
            Value::Object(out)
        }
        serde_yaml::Value::Tagged(t) => yaml_value_to_json(t.value)?,
    })
}

/// Normalise a [`MigrationInput`] into a front-matter `Value::Object`.
///
/// Mirror of Python `_coerce_to_dict`. Performs a deep clone of dict
/// inputs (so caller state is not mutated by the chain), routes raw
/// markdown / file-path inputs through `split_frontmatter` +
/// `parse_frontmatter` from `persona-canonical-form-yaml`, and
/// converts the resulting YAML mapping into a JSON object.
///
/// Exposed at the crate boundary as `pub(crate)` indirectly through
/// [`migrate_persona`]; left private here because the public API
/// surface is the dispatcher, not the coercion step.
fn coerce_to_dict(input: MigrationInput<'_>) -> Result<Value, PersonaMigrationError> {
    match input {
        MigrationInput::Dict(v) => {
            if !v.is_object() {
                return Err(PersonaMigrationError::NotAnObject);
            }
            // serde_json::Value::clone() performs a recursive copy
            // (mirror of Python `copy.deepcopy`).
            Ok(v.clone())
        }
        MigrationInput::Markdown(text) => {
            if !text.starts_with("---") {
                return Err(PersonaMigrationError::RawMarkdownMissingFence);
            }
            let (fm, _body) = split_frontmatter(text)?;
            let parsed = parse_frontmatter(&fm)?;
            yaml_value_to_json(parsed)
        }
        MigrationInput::Path(path) => {
            let text = std::fs::read_to_string(path).map_err(|e| {
                PersonaMigrationError::Io(e.kind(), format!("{}: {e}", path.display()))
            })?;
            let (fm, _body) = split_frontmatter(&text)?;
            let parsed = parse_frontmatter(&fm)?;
            yaml_value_to_json(parsed)
        }
    }
}

// ---------------------------------------------------------------------
// Canonical-subset projection (re-hash path only)
// ---------------------------------------------------------------------

/// Project a migrated front-matter `Value::Object` onto the V-907
/// canonical subset, in JSON shape.
///
/// Mirror of Python `_project_canonical_subset` (= a thin wrapper over
/// `extract_canonical_subset` that runs after the chain). The Python
/// counterpart calls `extract_canonical_subset` on the YAML-parsed
/// dict; here we re-implement the same projection on a JSON `Value`
/// because the migration chain operates on JSON, and converting back
/// to YAML purely for the canonicaliser would be a round-trip with no
/// behavioural benefit.
///
/// The projection follows the contract that
/// `persona-canonical-form-yaml::extract_canonical_subset` documents:
///
/// - Required top-level keys: `name`, `description`, `tools`,
///   `schema_version`, `identity_pinned`.
/// - `tools`: list or comma-separated string; canonical form is
///   always a `Vec<String>`.
/// - `name` / `description`: stringified (mirror of Python `str(...)`).
/// - `identity_pinned`: narrowed to `cross_review_zones`, `authority`,
///   `hierarchy` in that order.
///
/// Unlike `extract_canonical_subset`, this function accepts **any**
/// `schema_version` in [`PERSONA_SCHEMA_VERSION_LIST`] (including
/// `persona-v2`); the resolver has already guaranteed the migration
/// reached the requested target, so the canonical-subset projection
/// must accept the target version even when it is beyond
/// `SUPPORTED_SCHEMA_VERSION` of the yaml-crate.
fn project_canonical_subset(fm: &Value) -> Result<Value, PersonaMigrationError> {
    let obj = fm.as_object().ok_or(PersonaMigrationError::NotAnObject)?;

    // Required top-level keys (mirror of CANONICAL_TOP_LEVEL_KEYS).
    const REQUIRED: &[&str] = &[
        "name",
        "description",
        "tools",
        "schema_version",
        "identity_pinned",
    ];
    let missing: Vec<&str> = REQUIRED
        .iter()
        .copied()
        .filter(|k| !obj.contains_key(*k))
        .collect();
    if !missing.is_empty() {
        return Err(PersonaMigrationError::FrontmatterParse(
            PersonaCanonicalFormYamlError::MissingKey(format!(
                "persona front-matter missing required keys: {missing:?}"
            )),
        ));
    }

    // schema_version: must be a string in the known list.
    let schema_version = match obj.get("schema_version") {
        Some(Value::String(s)) => s.clone(),
        Some(_) | None => {
            return Err(PersonaMigrationError::SchemaVersionNotString {
                got_type: type_name_of(obj.get("schema_version").unwrap_or(&Value::Null)),
            })
        }
    };
    if !PERSONA_SCHEMA_VERSION_LIST.contains(&schema_version.as_str()) {
        return Err(PersonaMigrationError::UnknownSchemaVersion {
            version: schema_version,
            role: SchemaVersionRole::Target,
        });
    }

    // identity_pinned: must be an object with the canonical sub-keys.
    const REQUIRED_IP: &[&str] = &["cross_review_zones", "authority", "hierarchy"];
    let ip = match obj.get("identity_pinned") {
        Some(Value::Object(m)) => m,
        Some(_) | None => {
            return Err(PersonaMigrationError::FrontmatterParse(
                PersonaCanonicalFormYamlError::InvalidShape(
                    "persona identity_pinned must be a mapping".to_string(),
                ),
            ))
        }
    };
    let missing_ip: Vec<&str> = REQUIRED_IP
        .iter()
        .copied()
        .filter(|k| !ip.contains_key(*k))
        .collect();
    if !missing_ip.is_empty() {
        return Err(PersonaMigrationError::FrontmatterParse(
            PersonaCanonicalFormYamlError::InvalidShape(format!(
                "persona identity_pinned missing required keys: {missing_ip:?}"
            )),
        ));
    }
    let mut ip_canon = Map::with_capacity(REQUIRED_IP.len());
    for k in REQUIRED_IP {
        ip_canon.insert((*k).to_string(), ip.get(*k).expect("checked above").clone());
    }

    // tools: list or comma-separated string.
    let tools_canon: Vec<Value> = match obj.get("tools").expect("checked above") {
        Value::String(s) => s
            .split(',')
            .map(str::trim)
            .filter(|t| !t.is_empty())
            .map(|t| Value::String(t.to_string()))
            .collect(),
        Value::Array(arr) => {
            let mut out = Vec::with_capacity(arr.len());
            for item in arr {
                let s = stringify_scalar_json(item)?;
                out.push(Value::String(s));
            }
            out
        }
        other => {
            return Err(PersonaMigrationError::FrontmatterParse(
                PersonaCanonicalFormYamlError::InvalidShape(format!(
                    "persona tools must be a list or a comma-separated string, got {}",
                    type_name_of(other)
                )),
            ))
        }
    };

    // name / description: stringified scalars.
    let name = stringify_scalar_json(obj.get("name").expect("checked above"))?;
    let description = stringify_scalar_json(obj.get("description").expect("checked above"))?;

    // Assemble in CANONICAL_TOP_LEVEL_KEYS order (JCS will resort, but
    // the documented intermediate order matches Python).
    let mut canonical = Map::with_capacity(REQUIRED.len());
    canonical.insert("name".to_string(), Value::String(name));
    canonical.insert("description".to_string(), Value::String(description));
    canonical.insert("tools".to_string(), Value::Array(tools_canon));
    canonical.insert("schema_version".to_string(), Value::String(schema_version));
    canonical.insert("identity_pinned".to_string(), Value::Object(ip_canon));
    Ok(Value::Object(canonical))
}

fn stringify_scalar_json(v: &Value) -> Result<String, PersonaMigrationError> {
    match v {
        Value::String(s) => Ok(s.clone()),
        Value::Bool(b) => Ok(b.to_string()),
        Value::Number(n) => Ok(n.to_string()),
        Value::Null => Ok("None".to_string()),
        other => Err(PersonaMigrationError::FrontmatterParse(
            PersonaCanonicalFormYamlError::InvalidShape(format!(
                "expected scalar, got {}",
                type_name_of(other)
            )),
        )),
    }
}

fn type_name_of(v: &Value) -> &'static str {
    match v {
        Value::Null => "null",
        Value::Bool(_) => "bool",
        Value::Number(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}

// ---------------------------------------------------------------------
// `migrate_persona` dispatcher
// ---------------------------------------------------------------------

/// Run the registered migration chain on `input`.
///
/// Mirror of Python `migrate_persona`. Accepts a [`MigrationInput`]
/// (dict / raw markdown / filesystem path), resolves the chain from
/// the input's `schema_version` to `target_schema_version`, applies
/// every step in order, and optionally re-hashes the projected
/// canonical subset of the output and compares against
/// `expected_post_migration_hash`.
///
/// # Arguments
///
/// * `input` — see [`MigrationInput`].
/// * `target_schema_version` — chain target. `None` defaults to
///   [`PERSONA_SCHEMA_VERSION_LATEST`] (= `persona-v1`).
/// * `expected_post_migration_hash` — optional pin in either bare
///   64-hex form or full `"sha256:<64hex>"` form. When supplied, the
///   post-migration canonical-subset dict is re-hashed and compared;
///   a mismatch returns [`PersonaMigrationDeterminismError`].
///
/// # Returns
///
/// On success, the migrated **full front-matter** as a
/// `serde_json::Value::Object`. The canonical-subset projection is
/// computed internally for the hash check but **not** returned; the
/// caller can extract it via the sister `persona-canonical-form-yaml`
/// crate if needed for downstream pipelines, or call this crate's
/// internal projection (kept private to keep the public surface
/// narrow — request via a follow-up box if needed).
///
/// # Errors
///
/// - [`PersonaMigrationError`] for chain-resolution failures, input
///   shape failures, YAML parse failures, or step rejections.
/// - [`PersonaMigrationDeterminismError`] for post-hash drift (wrapped
///   in `Result<_, MigratePersonaError>` below for ergonomic dispatch).
pub fn migrate_persona(
    input: MigrationInput<'_>,
    target_schema_version: Option<&str>,
    expected_post_migration_hash: Option<&str>,
) -> Result<Value, MigratePersonaError> {
    let target = target_schema_version.unwrap_or(PERSONA_SCHEMA_VERSION_LATEST);

    let mut fm = coerce_to_dict(input).map_err(MigratePersonaError::Migration)?;

    let source_version = {
        let obj = fm.as_object().ok_or(MigratePersonaError::Migration(
            PersonaMigrationError::NotAnObject,
        ))?;
        match obj.get("schema_version") {
            None => {
                return Err(MigratePersonaError::Migration(
                    PersonaMigrationError::MissingSchemaVersion,
                ))
            }
            Some(Value::String(s)) => s.clone(),
            Some(other) => {
                return Err(MigratePersonaError::Migration(
                    PersonaMigrationError::SchemaVersionNotString {
                        got_type: type_name_of(other),
                    },
                ))
            }
        }
    };

    let chain = resolve_chain(&source_version, target).map_err(MigratePersonaError::Migration)?;
    for step in &chain {
        fm = step
            .apply(&fm)
            .map_err(|e| MigratePersonaError::Migration(PersonaMigrationError::StepFailed(e)))?;
    }

    if let Some(pin) = expected_post_migration_hash {
        let canonical = project_canonical_subset(&fm).map_err(MigratePersonaError::Migration)?;
        let computed = sha256_pin_of(&canonical)?;
        if !pin_matches(pin, &computed) {
            return Err(MigratePersonaError::Determinism(
                PersonaMigrationDeterminismError {
                    expected: normalise_pin(pin),
                    computed,
                },
            ));
        }
    }

    Ok(fm)
}

/// Top-level dispatcher error.
///
/// Combines the two Python error classes returned by
/// `migrate_persona`: chain-resolution / input-shape failures
/// ([`PersonaMigrationError`]) and post-hash drift
/// ([`PersonaMigrationDeterminismError`]).
#[derive(Debug)]
pub enum MigratePersonaError {
    /// Chain resolution or input shape failure.
    Migration(PersonaMigrationError),
    /// Post-migration hash drift.
    Determinism(PersonaMigrationDeterminismError),
}

impl std::fmt::Display for MigratePersonaError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Migration(e) => write!(f, "{e}"),
            Self::Determinism(e) => write!(f, "{e}"),
        }
    }
}

impl std::error::Error for MigratePersonaError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Migration(e) => Some(e),
            Self::Determinism(e) => Some(e),
        }
    }
}

// ---------------------------------------------------------------------
// Hash helpers (re-hash path)
// ---------------------------------------------------------------------

fn sha256_pin_of(canonical: &Value) -> Result<String, MigratePersonaError> {
    use sha2::{Digest, Sha256};
    let blob = persona_canonical_form::canonical_jcs_bytes(canonical).map_err(|e| {
        MigratePersonaError::Migration(PersonaMigrationError::FrontmatterParse(
            PersonaCanonicalFormYamlError::InvalidShape(format!(
                "JCS canonicalisation failed: {e}"
            )),
        ))
    })?;
    let mut hasher = Sha256::new();
    hasher.update(&blob);
    let digest = hasher.finalize();
    let mut hex_tail = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write;
        write!(hex_tail, "{byte:02x}").expect("hex write");
    }
    Ok(format!("sha256:{hex_tail}"))
}

fn pin_matches(pin: &str, computed_full: &str) -> bool {
    let expected_hex = pin.strip_prefix("sha256:").unwrap_or(pin);
    let computed_hex = computed_full
        .strip_prefix("sha256:")
        .expect("internally-computed pin is always full-form");
    expected_hex == computed_hex
}

fn normalise_pin(pin: &str) -> String {
    if pin.starts_with("sha256:") {
        pin.to_owned()
    } else {
        format!("sha256:{pin}")
    }
}

// ---------------------------------------------------------------------
// Sanity: the registered_steps surface anchored at compile time
// ---------------------------------------------------------------------
//
// The resolver depends on the step types existing as concrete imports
// so that a Cargo.lock-level removal of one would break the build.
// These markers are zero-cost.
const _: V0ToV1Step = V0ToV1Step;
const _: V1ToV2Step = V1ToV2Step;

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use sha2::{Digest, Sha256};

    // -------------------------------------------------------------------
    // Test fixtures: hand-built front-matter dicts matching the V8 / V9
    // canonical-subset shapes used by the sister `persona-migration`
    // crate's tests. Hashing path verified byte-identical against
    // Python pins on 2026-05-11 (Sprint-4 Tag-4).
    // -------------------------------------------------------------------

    /// V8 front-matter (schema_version=persona-v0).
    fn v8_dict() -> Value {
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

    /// V9 front-matter (schema_version=persona-v1).
    fn v9_dict() -> Value {
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

    const V9_FIXTURE: &str = include_str!("../tests/fixtures/v9-persona-framework-native.md");

    // -------------------------------------------------------------------
    // 1 / Chain resolver: V0→V1 yields exactly one step (V0ToV1Step).
    // -------------------------------------------------------------------

    #[test]
    fn t1_resolve_chain_v0_to_v1_one_step() {
        let chain = resolve_chain("persona-v0", "persona-v1").expect("v0→v1 resolvable");
        assert_eq!(chain.len(), 1);
        assert_eq!(chain[0].source_version(), "persona-v0");
        assert_eq!(chain[0].target_version(), "persona-v1");
    }

    // -------------------------------------------------------------------
    // 2 / Chain resolver: V0→V2 yields two steps in order.
    // -------------------------------------------------------------------

    #[test]
    fn t2_resolve_chain_v0_to_v2_two_steps() {
        let chain = resolve_chain("persona-v0", "persona-v2").expect("v0→v2 resolvable");
        assert_eq!(chain.len(), 2);
        assert_eq!(chain[0].source_version(), "persona-v0");
        assert_eq!(chain[0].target_version(), "persona-v1");
        assert_eq!(chain[1].source_version(), "persona-v1");
        assert_eq!(chain[1].target_version(), "persona-v2");
    }

    // -------------------------------------------------------------------
    // 3 / Chain resolver: same source==target → empty chain (no-op).
    // -------------------------------------------------------------------

    #[test]
    fn t3_resolve_chain_noop_when_source_equals_target() {
        let chain = resolve_chain("persona-v1", "persona-v1").expect("noop ok");
        assert!(chain.is_empty(), "source==target must yield empty chain");
    }

    // -------------------------------------------------------------------
    // 4 / Chain resolver: unknown source version is surfaced as
    //     UnknownSchemaVersion(Source).
    // -------------------------------------------------------------------

    #[test]
    fn t4_resolve_chain_unknown_source() {
        // `expect_err` needs Debug on Ok; the chain Vec holds trait
        // objects without Debug, so match on the Result manually.
        match resolve_chain("persona-v99", "persona-v1") {
            Err(PersonaMigrationError::UnknownSchemaVersion { version, role }) => {
                assert_eq!(version, "persona-v99");
                assert_eq!(role, SchemaVersionRole::Source);
            }
            Err(other) => panic!("expected UnknownSchemaVersion(Source), got {other:?}"),
            Ok(_) => panic!("expected error for unknown source"),
        }

        match resolve_chain("persona-v0", "persona-v42") {
            Err(PersonaMigrationError::UnknownSchemaVersion { version, role }) => {
                assert_eq!(version, "persona-v42");
                assert_eq!(role, SchemaVersionRole::Target);
            }
            Err(other) => panic!("expected UnknownSchemaVersion(Target), got {other:?}"),
            Ok(_) => panic!("expected error for unknown target"),
        }
    }

    // -------------------------------------------------------------------
    // 5 / find_step_by_source: returns V0ToV1Step for "persona-v0",
    //     None for an unknown source.
    // -------------------------------------------------------------------

    #[test]
    fn t5_find_step_by_source_lookup() {
        let s0 = find_step_by_source("persona-v0").expect("step for v0 exists");
        assert_eq!(s0.source_version(), "persona-v0");
        assert_eq!(s0.target_version(), "persona-v1");

        let s1 = find_step_by_source("persona-v1").expect("step for v1 exists");
        assert_eq!(s1.source_version(), "persona-v1");
        assert_eq!(s1.target_version(), "persona-v2");

        // persona-v2 is the terminal — no step starts from it.
        assert!(find_step_by_source("persona-v2").is_none());
        assert!(find_step_by_source("persona-bogus").is_none());
    }

    // -------------------------------------------------------------------
    // 6 / migrate_persona / Dict input / V8→V1 pin match
    //     (PERSONA_HASH_PIN_V8_MIGRATED_TO_V1).
    // -------------------------------------------------------------------

    #[test]
    fn t6_migrate_dict_v8_to_v1_pin_match() {
        let v8 = v8_dict();
        let migrated = migrate_persona(
            MigrationInput::Dict(&v8),
            Some("persona-v1"),
            Some(PERSONA_HASH_PIN_V8_MIGRATED_TO_V1),
        )
        .expect("V8 → V1 must migrate and re-hash match");
        assert_eq!(migrated["schema_version"], "persona-v1");
        // By construction the migrated hash equals the V9 pin.
        let canonical = project_canonical_subset(&migrated).expect("project");
        let pin = sha256_pin_of(&canonical).expect("hash");
        assert_eq!(pin, PERSONA_HASH_PIN_V9);
    }

    // -------------------------------------------------------------------
    // 7 / migrate_persona / Dict input / V8→V2 chain
    //     (PERSONA_HASH_PIN_V8_MIGRATED_TO_V2).
    //     M-1 linear-chain direct-anchor via the dispatcher.
    // -------------------------------------------------------------------

    #[test]
    fn t7_migrate_dict_v8_chain_to_v2_pin_match() {
        let v8 = v8_dict();
        let migrated = migrate_persona(
            MigrationInput::Dict(&v8),
            Some("persona-v2"),
            Some(PERSONA_HASH_PIN_V8_MIGRATED_TO_V2),
        )
        .expect("V8 → chain → V2 must migrate and re-hash match");
        assert_eq!(migrated["schema_version"], "persona-v2");
        let canonical = project_canonical_subset(&migrated).expect("project");
        let pin = sha256_pin_of(&canonical).expect("hash");
        assert_eq!(pin, PERSONA_HASH_PIN_V9_MIGRATED_TO_V2);
    }

    // -------------------------------------------------------------------
    // 8 / migrate_persona / Markdown input / V9 fixture → V2 pin match
    //     (PERSONA_HASH_PIN_V9_MIGRATED_TO_V2). Exercises the YAML
    //     front-matter parse-reuse path.
    // -------------------------------------------------------------------

    #[test]
    fn t8_migrate_markdown_v9_fixture_to_v2_pin_match() {
        let migrated = migrate_persona(
            MigrationInput::Markdown(V9_FIXTURE),
            Some("persona-v2"),
            Some(PERSONA_HASH_PIN_V9_MIGRATED_TO_V2),
        )
        .expect("V9-fixture → V2 must migrate and re-hash match");
        assert_eq!(migrated["schema_version"], "persona-v2");
    }

    // -------------------------------------------------------------------
    // 9 / migrate_persona / wrong pin → PersonaMigrationDeterminismError.
    // -------------------------------------------------------------------

    #[test]
    fn t9_migrate_wrong_pin_surfaces_determinism_error() {
        let v9 = v9_dict();
        // Wrong pin: use V9 pin where V9_MIGRATED_TO_V2 is expected.
        let err = migrate_persona(
            MigrationInput::Dict(&v9),
            Some("persona-v2"),
            Some(PERSONA_HASH_PIN_V9),
        )
        .expect_err("wrong pin must surface determinism error");
        match err {
            MigratePersonaError::Determinism(de) => {
                assert_eq!(de.expected, PERSONA_HASH_PIN_V9);
                assert_eq!(de.computed, PERSONA_HASH_PIN_V9_MIGRATED_TO_V2);
            }
            other => panic!("expected Determinism error, got {other:?}"),
        }
    }

    // -------------------------------------------------------------------
    // 10 / migrate_persona / missing schema_version → MissingSchemaVersion.
    // -------------------------------------------------------------------

    #[test]
    fn t10_migrate_missing_schema_version_rejected() {
        let bad = json!({"name": "x", "description": "y", "tools": [], "identity_pinned": {}});
        let err = migrate_persona(MigrationInput::Dict(&bad), Some("persona-v1"), None)
            .expect_err("missing schema_version must error");
        match err {
            MigratePersonaError::Migration(PersonaMigrationError::MissingSchemaVersion) => {}
            other => panic!("expected MissingSchemaVersion, got {other:?}"),
        }
    }

    // -------------------------------------------------------------------
    // 11 / migrate_persona / raw-markdown without `---` fence →
    //      RawMarkdownMissingFence.
    // -------------------------------------------------------------------

    #[test]
    fn t11_migrate_raw_markdown_missing_fence_rejected() {
        let err = migrate_persona(
            MigrationInput::Markdown("no fence here"),
            Some("persona-v1"),
            None,
        )
        .expect_err("raw markdown without fence must error");
        match err {
            MigratePersonaError::Migration(PersonaMigrationError::RawMarkdownMissingFence) => {}
            other => panic!("expected RawMarkdownMissingFence, got {other:?}"),
        }
    }

    // -------------------------------------------------------------------
    // 12 / Pin bare-hex tolerance — caller pin without "sha256:" prefix
    //      still matches. Mirrors Python tolerance.
    // -------------------------------------------------------------------

    #[test]
    fn t12_migrate_bare_hex_pin_accepted() {
        let v9 = v9_dict();
        let bare = PERSONA_HASH_PIN_V9_MIGRATED_TO_V2
            .strip_prefix("sha256:")
            .expect("constant has prefix");
        let migrated = migrate_persona(MigrationInput::Dict(&v9), Some("persona-v2"), Some(bare))
            .expect("bare-hex pin must be accepted");
        assert_eq!(migrated["schema_version"], "persona-v2");
    }

    // -------------------------------------------------------------------
    // 13 / 10-iteration determinism stress on `migrate_persona` dispatcher
    //      (Dict input, full V8 → V2 chain). Phase-1b Sprint-6 Tag-5
    //      pin-pack coverage extension — mirror of Crate-4 t11 / t12 and
    //      Crate-1+2 Tag-3 patterns at the dispatcher layer rather than
    //      the per-step layer.
    //
    //      Goal: a hash-evaluation non-determinism that lurks across the
    //      dispatcher's split_frontmatter → parse_frontmatter →
    //      yaml-to-json → resolve_chain → apply-each-step →
    //      canonical_jcs_bytes → sha256 pipeline would surface as
    //      cross-iteration drift here.
    // -------------------------------------------------------------------

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

    /// Recompute the canonical-subset post-migration pin for a fully
    /// migrated dict. Mirrors the `expected_post_migration_hash`
    /// internal path without the assertion side-effect — useful for
    /// the stress-loop's cross-iteration comparison and the
    /// re-derivation roundtrip.
    fn pin_of_migrated_dict(d: &Value) -> String {
        // Project to canonical-subset (mirror what `extract_canonical_subset`
        // does in Python — pick the canonical-subset keys; on a
        // step-output dict the subset already equals the dict).
        let subset = serde_json::json!({
            "name": d["name"],
            "description": d["description"],
            "tools": d["tools"],
            "schema_version": d["schema_version"],
            "identity_pinned": d["identity_pinned"],
        });
        let blob = persona_canonical_form::canonical_jcs_bytes(&subset).expect("JCS");
        format!("sha256:{}", sha256_hex(&blob))
    }

    #[test]
    fn t13_migrate_persona_dict_v8_to_v2_determinism_stress_10_iter() {
        let v8 = v8_dict();
        // Baseline pin via the dispatcher's own re-hash path (using a
        // pin that we know matches the V2 target). The baseline pin
        // is then compared across 10 iterations.
        let baseline = migrate_persona(
            MigrationInput::Dict(&v8),
            Some("persona-v2"),
            Some(PERSONA_HASH_PIN_V8_MIGRATED_TO_V2),
        )
        .expect("baseline V8→V2 must migrate");
        let baseline_pin = pin_of_migrated_dict(&baseline);
        assert_eq!(baseline_pin, PERSONA_HASH_PIN_V8_MIGRATED_TO_V2);

        for i in 0..10 {
            let again = migrate_persona(
                MigrationInput::Dict(&v8),
                Some("persona-v2"),
                Some(PERSONA_HASH_PIN_V8_MIGRATED_TO_V2),
            )
            .expect("iter V8→V2 must migrate");
            let pin = pin_of_migrated_dict(&again);
            assert_eq!(
                pin, baseline_pin,
                "iter {i}: dispatcher V8→V2 pin drifted from baseline"
            );
        }
    }

    // -------------------------------------------------------------------
    // 14 / 10-iteration determinism stress on `migrate_persona`
    //      Markdown-input path (V9 fixture → V2). Sister of t13; this
    //      time exercising the YAML-parse path additionally.
    // -------------------------------------------------------------------

    #[test]
    fn t14_migrate_persona_markdown_v9_to_v2_determinism_stress_10_iter() {
        let baseline = migrate_persona(
            MigrationInput::Markdown(V9_FIXTURE),
            Some("persona-v2"),
            Some(PERSONA_HASH_PIN_V9_MIGRATED_TO_V2),
        )
        .expect("baseline V9-markdown→V2 must migrate");
        let baseline_pin = pin_of_migrated_dict(&baseline);
        assert_eq!(baseline_pin, PERSONA_HASH_PIN_V9_MIGRATED_TO_V2);

        for i in 0..10 {
            let again = migrate_persona(
                MigrationInput::Markdown(V9_FIXTURE),
                Some("persona-v2"),
                Some(PERSONA_HASH_PIN_V9_MIGRATED_TO_V2),
            )
            .expect("iter V9-markdown→V2 must migrate");
            let pin = pin_of_migrated_dict(&again);
            assert_eq!(
                pin, baseline_pin,
                "iter {i}: dispatcher V9-markdown→V2 pin drifted from baseline"
            );
        }
    }

    // -------------------------------------------------------------------
    // 15 / V8-chain-to-V2 hex-pin hard-freeze (Rust-only Sprint-6 Tag-5).
    //
    //      Mirrors Crate-4 t13 / t14 hard-freeze pattern at the
    //      dispatcher layer. Pins the 64-hex tail of the
    //      PERSONA_HASH_PIN_V8_MIGRATED_TO_V2 constant; catches a
    //      regression where the dispatcher pipeline produces a
    //      different but still pin-shaped output.
    //
    //      Rust-only: no Python pendant (Python anchors via the full
    //      "sha256:<64hex>" constant directly).
    // -------------------------------------------------------------------

    const V8_CHAIN_TO_V2_HEX_RUST_ONLY: &str =
        "f719fce4bedd8522874ae214ec2f982ef87964b535ca368134b3636207eb6669";

    #[test]
    fn t15_migrate_persona_v8_chain_to_v2_hex_pin_hard_freeze() {
        let v8 = v8_dict();
        let migrated = migrate_persona(
            MigrationInput::Dict(&v8),
            Some("persona-v2"),
            None, // no expected-pin gate; we anchor on the hex tail manually
        )
        .expect("V8→V2 dispatcher must migrate");
        let pin = pin_of_migrated_dict(&migrated);
        let hex_tail = pin
            .strip_prefix("sha256:")
            .expect("pin must have sha256: prefix");
        assert_eq!(
            hex_tail, V8_CHAIN_TO_V2_HEX_RUST_ONLY,
            "V8→V2 chain hex must match V8_CHAIN_TO_V2_HEX_RUST_ONLY hard-freeze"
        );
        assert!(
            PERSONA_HASH_PIN_V8_MIGRATED_TO_V2.ends_with(V8_CHAIN_TO_V2_HEX_RUST_ONLY),
            "V8_CHAIN_TO_V2_HEX_RUST_ONLY must equal the tail of PERSONA_HASH_PIN_V8_MIGRATED_TO_V2"
        );
        assert!(
            PERSONA_HASH_PIN_V9_MIGRATED_TO_V2.ends_with(V8_CHAIN_TO_V2_HEX_RUST_ONLY),
            "V8_CHAIN_TO_V2_HEX_RUST_ONLY must equal the tail of PERSONA_HASH_PIN_V9_MIGRATED_TO_V2 (by construction)"
        );
    }

    // -------------------------------------------------------------------
    // 16 / Re-derivation roundtrip: chain V8 → V1 (one step) and the
    //      pin must match PERSONA_HASH_PIN_V8_MIGRATED_TO_V1 (= V9 pin
    //      by construction). Mirrors Crate-4 t15 but at the dispatcher
    //      layer.
    // -------------------------------------------------------------------

    #[test]
    fn t16_migrate_persona_v8_to_v1_re_derivation_roundtrip() {
        let v8 = v8_dict();
        let migrated = migrate_persona(MigrationInput::Dict(&v8), Some("persona-v1"), None)
            .expect("V8→V1 dispatcher must migrate");
        assert_eq!(migrated["schema_version"], "persona-v1");
        let pin = pin_of_migrated_dict(&migrated);
        assert_eq!(
            pin, PERSONA_HASH_PIN_V8_MIGRATED_TO_V1,
            "dispatcher V8→V1 pin must equal PERSONA_HASH_PIN_V8_MIGRATED_TO_V1"
        );
        assert_eq!(
            pin, PERSONA_HASH_PIN_V9,
            "V8_MIGRATED_TO_V1 pin equals V9 pin by construction"
        );
    }
}
