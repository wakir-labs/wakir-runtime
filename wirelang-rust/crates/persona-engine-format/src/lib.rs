// SPDX-License-Identifier: Apache-2.0
//! persona-engine-format — Sprint-Pengine-7 Tag-1, Crate-8.
//!
//! Byte-deterministic mapping from `.claude/agents/<slug>.md`
//! (axis-A `persona-claude-native`) to `wakir.persona/<slug>.json`
//! (axis-C `wakir-persona-v1`).
//!
//! Spec anchor: `wirelang/specs/persona-engine-format-spec.md` v1.0.
//!
//! Pipeline (§4.2 of the spec):
//!
//! 1. Read axis-A markdown text.
//! 2. Split front-matter and body (`persona-canonical-form-yaml`).
//! 3. Parse YAML front-matter into a mapping.
//! 4. Validate against the `persona-claude-native` shape (§2.1).
//! 5. Extract `claude_native_source` (lossless front-matter echo).
//! 6. Synthesise `canonical_subset` (persona-v1 shape, §4.3 safe
//!    defaults for `identity_pinned`).
//! 7. Assemble `wakir-persona-v1` document (§3.1 fields).
//!
//! V-907 integration (§5): the `wakir_persona_hash` function delegates
//! to the unchanged persona-hash function on the embedded
//! canonical_subset block. No new hash function is introduced.
//!
//! Default-Lock posture mirrors Crate-1..7:
//! - A-1 Mock-Format-Baseline: consumes markdown text bytes.
//! - A-2 Additiv-only: adds Crate-8 next to the existing seven.
//! - A-3 Body out-of-hash: Markdown body is dropped entirely.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use persona_canonical_form_yaml::{
    parse_frontmatter, split_frontmatter, PersonaCanonicalFormYamlError,
};
use serde_json::{json, Map, Value as JsonValue};
use serde_yaml::Value as YamlValue;

// ---------------------------------------------------------------------
// Public constants
// ---------------------------------------------------------------------

/// Target schema-version string (axis C, this spec).
pub const WAKIR_PERSONA_SCHEMA_VERSION: &str = "wakir-persona-v1";

/// V-907 mock canonical subset schema-version embedded inside
/// `canonical_subset`.
pub const EMBEDDED_PERSONA_SCHEMA_VERSION: &str = "persona-v1";

/// Source axis identifier recorded in `migration_metadata`.
pub const SOURCE_AXIS: &str = "persona-claude-native";

/// Source axis version recorded in `migration_metadata`.
pub const SOURCE_AXIS_VERSION: &str = "v0";

/// Target axis identifier recorded in `migration_metadata`.
pub const TARGET_AXIS: &str = "wakir-persona";

/// Target axis version recorded in `migration_metadata`.
pub const TARGET_AXIS_VERSION: &str = "v1";

/// Converter module identifier recorded in `migration_metadata`.
pub const CONVERTER_MODULE: &str =
    "wirelang_rust::persona_engine_format::map_claude_native_to_wakir_v1";

/// Byte-determinism statement recorded in `migration_metadata`.
pub const CONVERTER_BYTE_DETERMINISM: &str = "JCS-stable; same input bytes -> same output bytes";

/// V-907 hash integration statement recorded in `migration_metadata`.
pub const V907_HASH_INTEGRATION: &str = "embedded canonical_subset; hash function unchanged";

/// Closed-set of accepted top-level keys in axis-A front-matter.
/// Unknown keys are preserved through `claude_native_source` but
/// dropped from `canonical_subset`.
pub const CLAUDE_NATIVE_RECOGNISED_KEYS: &[&str] = &["name", "description", "tools", "model"];

/// Required top-level keys in axis-A front-matter.
pub const CLAUDE_NATIVE_REQUIRED_KEYS: &[&str] = &["name", "description"];

// ---------------------------------------------------------------------
// Synthesis-default exceptions (§4.3.1 of the spec, v1.1)
// ---------------------------------------------------------------------
//
// Aisha-HR Counter-Vorschlag 1 (2026-05-13 bedingt-ack): the safe
// defaults `reports_to: "mira"` / `escalation: "mira"` are inhaltlich
// incorrect for two personae whose .claude/agents/<slug>.md body
// explicitly carries an Aufsichtsrat-direct reporting line.
//
// This table is the load-bearing pre-Tag-3 (OI-PEF-1 Markdown-body-
// parser) hard-coded override surface. Once OI-PEF-1 lands, the body
// parser can extract the same information from the persona-files
// themselves; until then, this table is the authoritative source.

/// One row of the synthesis-default exceptions table (§4.3.1).
#[derive(Debug, Clone, Copy)]
pub struct SynthesisDefaultException {
    /// Persona slug (matches the `name` field of the persona-claude-native front-matter).
    pub persona_slug: &'static str,
    /// Override value for `identity_pinned.hierarchy.reports_to`.
    pub reports_to: &'static str,
    /// Override value for `identity_pinned.hierarchy.escalation`.
    pub escalation: &'static str,
    /// Audit-trail rationale (anchors the override to a persona-file body section).
    pub rationale: &'static str,
}

/// Hard-coded synthesis-default exceptions, ratified by Aisha-HR
/// 2026-05-13 bedingt-ack on spec v1.1 §4.3.1.
///
/// **MUST** be consulted by `synthesise_canonical_subset` before the
/// safe defaults of §4.3 take effect.
pub const SYNTHESIS_DEFAULT_EXCEPTIONS: &[SynthesisDefaultException] = &[
    SynthesisDefaultException {
        persona_slug: "cfo",
        reports_to: "aufsichtsrat",
        escalation: "aufsichtsrat",
        rationale: "cfo.md §3 Hierarchie: Top-Management gleichrangig zur CEO; AR-direkt für Strategy-ADRs und Hard-Stop.",
    },
    SynthesisDefaultException {
        persona_slug: "internal-audit",
        reports_to: "aufsichtsrat",
        escalation: "aufsichtsrat",
        rationale: "internal-audit.md §2: Berichtet direkt an den Aufsichtsrat. Nicht an die CEO.",
    },
];

/// Lookup helper for the exceptions table (§4.3.1). Returns `Some(row)`
/// when the persona slug appears in
/// [`SYNTHESIS_DEFAULT_EXCEPTIONS`], else `None`.
#[must_use]
pub fn lookup_synthesis_default_exception(
    slug: &str,
) -> Option<&'static SynthesisDefaultException> {
    SYNTHESIS_DEFAULT_EXCEPTIONS
        .iter()
        .find(|row| row.persona_slug == slug)
}

// ---------------------------------------------------------------------
// Error surface
// ---------------------------------------------------------------------

/// Error class for the persona-engine-format mapping pipeline.
#[derive(Debug)]
pub enum PersonaEngineFormatError {
    /// YAML front-matter parse / shape failure (delegated from
    /// `persona-canonical-form-yaml`).
    FrontmatterError(PersonaCanonicalFormYamlError),

    /// A required axis-A key (`name` or `description`) is missing or
    /// has the wrong shape.
    MissingRequiredKey(String),

    /// A field has an invalid shape (e.g. `name` not a string,
    /// `tools` neither string nor array, `model` not a string).
    InvalidShape(String),

    /// JCS canonicalisation failed.
    CanonicaliseError(String),

    /// V-907 hash function failed.
    HashError(String),
}

impl std::fmt::Display for PersonaEngineFormatError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::FrontmatterError(e) => write!(f, "front-matter error: {e}"),
            Self::MissingRequiredKey(k) => write!(f, "missing required key: {k}"),
            Self::InvalidShape(m) => write!(f, "invalid shape: {m}"),
            Self::CanonicaliseError(m) => write!(f, "JCS canonicalisation failed: {m}"),
            Self::HashError(m) => write!(f, "V-907 hash error: {m}"),
        }
    }
}

impl std::error::Error for PersonaEngineFormatError {}

impl From<PersonaCanonicalFormYamlError> for PersonaEngineFormatError {
    fn from(e: PersonaCanonicalFormYamlError) -> Self {
        Self::FrontmatterError(e)
    }
}

// ---------------------------------------------------------------------
// YAML → JSON value conversion
//
// Mirrors the conversion in persona-canonical-form-yaml::yaml_to_json
// but is implemented locally here because that helper is private to
// the sister crate and we need to walk arbitrary front-matter (not
// only the canonical-subset projection).
// ---------------------------------------------------------------------

fn yaml_type_name(v: &YamlValue) -> &'static str {
    match v {
        YamlValue::Null => "null",
        YamlValue::Bool(_) => "bool",
        YamlValue::Number(_) => "number",
        YamlValue::String(_) => "string",
        YamlValue::Sequence(_) => "sequence",
        YamlValue::Mapping(_) => "mapping",
        YamlValue::Tagged(_) => "tagged",
    }
}

fn yaml_to_json(value: YamlValue) -> Result<JsonValue, PersonaEngineFormatError> {
    match value {
        YamlValue::Null => Ok(JsonValue::Null),
        YamlValue::Bool(b) => Ok(JsonValue::Bool(b)),
        YamlValue::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(JsonValue::Number(i.into()))
            } else if let Some(u) = n.as_u64() {
                Ok(JsonValue::Number(u.into()))
            } else if let Some(f) = n.as_f64() {
                serde_json::Number::from_f64(f)
                    .map(JsonValue::Number)
                    .ok_or_else(|| {
                        PersonaEngineFormatError::InvalidShape(
                            "non-finite float in front-matter".to_string(),
                        )
                    })
            } else {
                Err(PersonaEngineFormatError::InvalidShape(
                    "unrepresentable YAML number".to_string(),
                ))
            }
        }
        YamlValue::String(s) => Ok(JsonValue::String(s)),
        YamlValue::Sequence(seq) => {
            let mut out = Vec::with_capacity(seq.len());
            for item in seq {
                out.push(yaml_to_json(item)?);
            }
            Ok(JsonValue::Array(out))
        }
        YamlValue::Mapping(map) => {
            let mut obj = Map::with_capacity(map.len());
            for (k, v) in map {
                let key = match k {
                    YamlValue::String(s) => s,
                    other => {
                        return Err(PersonaEngineFormatError::InvalidShape(format!(
                            "YAML mapping key must be a string, got {}",
                            yaml_type_name(&other)
                        )))
                    }
                };
                obj.insert(key, yaml_to_json(v)?);
            }
            Ok(JsonValue::Object(obj))
        }
        YamlValue::Tagged(tagged) => yaml_to_json(tagged.value),
    }
}

// ---------------------------------------------------------------------
// claude_native_source — lossless front-matter echo
// ---------------------------------------------------------------------

fn build_claude_native_source(fm: &YamlValue) -> Result<JsonValue, PersonaEngineFormatError> {
    yaml_to_json(fm.clone())
}

// ---------------------------------------------------------------------
// tools / model extraction
// ---------------------------------------------------------------------

/// Parsed axis-A `tools` field. Empty when absent.
fn extract_tools_list(fm: &YamlValue) -> Result<Vec<String>, PersonaEngineFormatError> {
    let YamlValue::Mapping(map) = fm else {
        return Err(PersonaEngineFormatError::InvalidShape(
            "front-matter must be a YAML mapping".to_string(),
        ));
    };
    let raw = map.get(YamlValue::String("tools".to_string()));
    let Some(raw) = raw else {
        return Ok(Vec::new());
    };
    match raw {
        YamlValue::String(s) => Ok(s
            .split(',')
            .map(str::trim)
            .filter(|t| !t.is_empty())
            .map(String::from)
            .collect()),
        YamlValue::Sequence(seq) => {
            let mut out = Vec::with_capacity(seq.len());
            for item in seq {
                let s = match item {
                    YamlValue::String(s) => s.clone(),
                    YamlValue::Bool(b) => b.to_string(),
                    YamlValue::Number(n) => n.to_string(),
                    YamlValue::Null => "None".to_string(),
                    other => {
                        return Err(PersonaEngineFormatError::InvalidShape(format!(
                            "tools list item must be scalar, got {}",
                            yaml_type_name(other)
                        )))
                    }
                };
                out.push(s);
            }
            Ok(out)
        }
        other => Err(PersonaEngineFormatError::InvalidShape(format!(
            "tools must be string or array, got {}",
            yaml_type_name(other)
        ))),
    }
}

/// Parsed axis-A `model` field. `None` when absent.
fn extract_model_override(fm: &YamlValue) -> Result<Option<String>, PersonaEngineFormatError> {
    let YamlValue::Mapping(map) = fm else {
        return Err(PersonaEngineFormatError::InvalidShape(
            "front-matter must be a YAML mapping".to_string(),
        ));
    };
    let raw = map.get(YamlValue::String("model".to_string()));
    let Some(raw) = raw else {
        return Ok(None);
    };
    match raw {
        YamlValue::String(s) => Ok(Some(s.clone())),
        other => Err(PersonaEngineFormatError::InvalidShape(format!(
            "model must be string, got {}",
            yaml_type_name(other)
        ))),
    }
}

fn extract_required_string(fm: &YamlValue, key: &str) -> Result<String, PersonaEngineFormatError> {
    let YamlValue::Mapping(map) = fm else {
        return Err(PersonaEngineFormatError::InvalidShape(
            "front-matter must be a YAML mapping".to_string(),
        ));
    };
    let raw = map
        .get(YamlValue::String(key.to_string()))
        .ok_or_else(|| PersonaEngineFormatError::MissingRequiredKey(key.to_string()))?;
    match raw {
        YamlValue::String(s) => Ok(s.clone()),
        other => Err(PersonaEngineFormatError::InvalidShape(format!(
            "{key} must be a string, got {}",
            yaml_type_name(other)
        ))),
    }
}

// ---------------------------------------------------------------------
// canonical_subset synthesis (§4.3 of the spec)
// ---------------------------------------------------------------------

fn synthesise_canonical_subset(name: &str, description: &str, tools: &[String]) -> JsonValue {
    let tools_arr: Vec<JsonValue> = tools.iter().map(|t| JsonValue::String(t.clone())).collect();

    // §4.3.1 (v1.1) — synthesis-default-exceptions table.
    // Aisha-HR Counter-Vorschlag 1 (2026-05-13 bedingt-ack).
    let (reports_to, escalation) = match lookup_synthesis_default_exception(name) {
        Some(row) => (row.reports_to, row.escalation),
        None => ("mira", "mira"),
    };

    json!({
        "name": name,
        "description": description,
        "tools": tools_arr,
        "schema_version": EMBEDDED_PERSONA_SCHEMA_VERSION,
        "identity_pinned": {
            "cross_review_zones": [],
            "authority": {
                "push_remote": false,
                "budget_cap_eur_per_month": 10,
                "sub_delegation": false
            },
            "hierarchy": {
                "reports_to": reports_to,
                "escalation": escalation
            }
        }
    })
}

// ---------------------------------------------------------------------
// spawn_lifecycle, state_persistence, container_bridge,
// migration_metadata — Sprint-Pengine-7 Tag-1 fixed shapes
// ---------------------------------------------------------------------

fn spawn_lifecycle_block() -> JsonValue {
    json!({
        "states": [
            "uninstantiated",
            "spawning",
            "running",
            "despawning",
            "recovered",
            "migrated"
        ],
        "valid_transitions": [
            ["uninstantiated", "spawning"],
            ["spawning", "running"],
            ["spawning", "uninstantiated"],
            ["running", "despawning"],
            ["despawning", "uninstantiated"],
            ["uninstantiated", "recovered"],
            ["recovered", "running"],
            ["running", "migrated"],
            ["migrated", "uninstantiated"]
        ],
        "recovery_policy": {
            "kind": "event-replay",
            "source": "marker-stack-kv-bridge"
        },
        "max_concurrent_instances": 1
    })
}

fn state_persistence_block(persona_id: &str) -> JsonValue {
    json!({
        "bucket_template": format!("wakir-persona-state-{persona_id}"),
        "value_envelope_schema": "wakir.persona.state-event/1",
        "history": 10,
        "max_value_size_bytes": 65536,
        "storage": "file",
        "replicas": 1,
        "ttl_seconds": 0
    })
}

fn container_bridge_block(persona_id: &str) -> JsonValue {
    json!({
        "image_template": format!("wakir-persona-{persona_id}:{{persona_hash_short}}"),
        "metadata_labels": {
            "wakir.persona.id": persona_id,
            "wakir.persona.hash": "{persona_hash}",
            "wakir.persona.schema_version": WAKIR_PERSONA_SCHEMA_VERSION
        },
        "env_injection": {
            "WAKIR_PERSONA_ID": persona_id,
            "WAKIR_PERSONA_HASH": "{persona_hash}"
        },
        "cross_review_zone": "J"
    })
}

fn migration_metadata_block() -> JsonValue {
    json!({
        "source_axis": SOURCE_AXIS,
        "source_axis_version": SOURCE_AXIS_VERSION,
        "target_axis": TARGET_AXIS,
        "target_axis_version": TARGET_AXIS_VERSION,
        "converter_module": CONVERTER_MODULE,
        "converter_byte_determinism": CONVERTER_BYTE_DETERMINISM,
        "v907_hash_integration": V907_HASH_INTEGRATION
    })
}

// ---------------------------------------------------------------------
// Public mapping entry-point
// ---------------------------------------------------------------------

/// Map a `persona-claude-native` markdown text to a
/// `wakir-persona-v1` JSON document (`serde_json::Value::Object`).
///
/// The returned object can be passed directly to `serde_jcs::to_vec`
/// to obtain the byte-deterministic on-disk form.
///
/// # Errors
///
/// See [`PersonaEngineFormatError`].
pub fn map_claude_native_to_wakir_v1(
    persona_definition_text: &str,
) -> Result<JsonValue, PersonaEngineFormatError> {
    // 1. Split front-matter and body. We discard the body entirely
    //    (A-3 body out-of-hash).
    let (fm_text, _body) = split_frontmatter(persona_definition_text)?;

    // 2. Parse YAML front-matter into a mapping.
    let fm = parse_frontmatter(&fm_text)?;

    // 3. Required keys.
    let name = extract_required_string(&fm, "name")?;
    if !is_valid_slug(&name) {
        return Err(PersonaEngineFormatError::InvalidShape(format!(
            "name {name:?} does not match ^[a-z0-9][a-z0-9-]*$"
        )));
    }
    let description = extract_required_string(&fm, "description")?;

    // 4. Optional keys.
    let tools = extract_tools_list(&fm)?;
    let model_override = extract_model_override(&fm)?;

    // 5. claude_native_source — lossless front-matter echo.
    let claude_native_source = build_claude_native_source(&fm)?;

    // 6. canonical_subset — synthesised persona-v1 shape.
    let canonical_subset = synthesise_canonical_subset(&name, &description, &tools);

    // 7. Assemble wakir-persona-v1 document.
    let mut doc = Map::new();
    doc.insert(
        "schema_version".to_string(),
        JsonValue::String(WAKIR_PERSONA_SCHEMA_VERSION.to_string()),
    );
    doc.insert("persona_id".to_string(), JsonValue::String(name.clone()));
    doc.insert("canonical_subset".to_string(), canonical_subset);
    doc.insert("claude_native_source".to_string(), claude_native_source);
    doc.insert("spawn_lifecycle".to_string(), spawn_lifecycle_block());
    doc.insert(
        "state_persistence".to_string(),
        state_persistence_block(&name),
    );
    doc.insert(
        "container_bridge".to_string(),
        container_bridge_block(&name),
    );
    doc.insert("migration_metadata".to_string(), migration_metadata_block());
    doc.insert(
        "model_override".to_string(),
        match model_override {
            None => JsonValue::Null,
            Some(s) => JsonValue::String(s),
        },
    );

    Ok(JsonValue::Object(doc))
}

/// Lightweight slug-pattern check (mirrors persona-v1 schema `name`
/// pattern `^[a-z0-9][a-z0-9-]*$`). No regex dependency.
fn is_valid_slug(s: &str) -> bool {
    if s.is_empty() {
        return false;
    }
    let bytes = s.as_bytes();
    let first = bytes[0];
    if !(first.is_ascii_lowercase() || first.is_ascii_digit()) {
        return false;
    }
    for &b in &bytes[1..] {
        let ok = b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-';
        if !ok {
            return false;
        }
    }
    true
}

// ---------------------------------------------------------------------
// V-907 hash integration (§5 of the spec)
// ---------------------------------------------------------------------

/// Compute the V-907 persona-hash of a `wakir-persona-v1` document
/// by delegating to the unchanged hash function on the embedded
/// `canonical_subset`.
///
/// # Errors
///
/// Returns [`PersonaEngineFormatError::HashError`] if the input is
/// missing `canonical_subset` or the V-907 hash function fails.
pub fn wakir_persona_hash(doc: &JsonValue) -> Result<String, PersonaEngineFormatError> {
    let obj = doc.as_object().ok_or_else(|| {
        PersonaEngineFormatError::HashError(
            "wakir_persona_hash input must be a JSON object".to_string(),
        )
    })?;
    let canonical_subset = obj.get("canonical_subset").ok_or_else(|| {
        PersonaEngineFormatError::HashError(
            "wakir-persona-v1 document missing canonical_subset".to_string(),
        )
    })?;
    persona_hash::compute_persona_hash_from_canonical(canonical_subset, None)
        .map_err(|e| PersonaEngineFormatError::HashError(e.to_string()))
}

/// Convenience: JCS-canonicalise a `wakir-persona-v1` document to
/// the byte-deterministic on-disk form.
///
/// # Errors
///
/// Returns [`PersonaEngineFormatError::CanonicaliseError`] on JCS
/// failure.
pub fn jcs_canonicalise_wakir_persona_v1(
    doc: &JsonValue,
) -> Result<Vec<u8>, PersonaEngineFormatError> {
    serde_jcs::to_vec(doc).map_err(|e| PersonaEngineFormatError::CanonicaliseError(e.to_string()))
}

// ---------------------------------------------------------------------
// Sprint-Pengine-7 Tag-3 — Lifecycle Protocols (§3.7 of spec v1.2)
// ---------------------------------------------------------------------
//
// Pure-data surface for the three operational protocols layered over
// the §3.3 `spawn_lifecycle` state machine:
//
// - §3.7.1 `despawn_clean` — four phase-sequential operations P1..P4.
// - §3.7.2 `recovery_drill` — three failure classes + four acceptance
//   criteria.
// - §3.7.3 `migrate_version` — trigger conditions + backward-compat.
//
// The JSON envelope (§3.3 / §3.4 / §3.5 / §3.6) is BYTE-UNCHANGED
// from v1.1. Tag-3 only adds spec-level operator protocols; the
// `map_claude_native_to_wakir_v1` output remains byte-identical.

/// Sprint-Pengine-7 Tag-3 lifecycle-protocols surface (§3.7).
pub mod lifecycle_protocols {
    /// The four canonical phases of a clean despawn, in execution order
    /// (§3.7.1.1). Re-ordering is a protocol violation — the audit-trail
    /// invariant in §3.7.1 holds **only** under this fixed phase order.
    #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
    pub enum DespawnCleanPhase {
        /// P1 — drain `wakir-persona-state-{persona_id}` NATS-KV bucket.
        P1DrainNatsKv,
        /// P2 — revoke all outstanding capability tokens for this persona.
        P2RevokeCapabilityTokens,
        /// P3 — run marker-stack final compose; emit WAT-frame.
        P3FinalMarkerCompose,
        /// P4 — stop the Quadlet persona container.
        P4ContainerStop,
    }

    /// Canonical phase order (§3.7.1.1).
    pub const DESPAWN_CLEAN_PHASE_ORDER: &[DespawnCleanPhase] = &[
        DespawnCleanPhase::P1DrainNatsKv,
        DespawnCleanPhase::P2RevokeCapabilityTokens,
        DespawnCleanPhase::P3FinalMarkerCompose,
        DespawnCleanPhase::P4ContainerStop,
    ];

    /// Terminal status string per phase (§3.7.1.1 "Terminal status"
    /// column). A phase that does not reach this status surfaces a
    /// `DespawnDirtyError{phase, reason}`.
    pub const fn despawn_phase_terminal_status(phase: DespawnCleanPhase) -> &'static str {
        match phase {
            DespawnCleanPhase::P1DrainNatsKv => "drained",
            DespawnCleanPhase::P2RevokeCapabilityTokens => "revoked",
            DespawnCleanPhase::P3FinalMarkerCompose => "composed",
            DespawnCleanPhase::P4ContainerStop => "stopped",
        }
    }

    /// Cross-review zone for the phase (§3.7.1.1 "Cross-review zone"
    /// column). Used by the engine-side audit-trail emitter so each
    /// phase's audit annotation carries the canonical zone identifier.
    pub const fn despawn_phase_cross_review_zone(phase: DespawnCleanPhase) -> &'static str {
        match phase {
            DespawnCleanPhase::P1DrainNatsKv => "B",
            DespawnCleanPhase::P2RevokeCapabilityTokens => "L",
            DespawnCleanPhase::P3FinalMarkerCompose => "K",
            DespawnCleanPhase::P4ContainerStop => "J",
        }
    }

    /// The three recovery-drill classes (§3.7.2.1).
    #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
    pub enum RecoveryDrillClass {
        /// Container `SIGKILL` mid-run; replay from marker-stack-kv.
        ContainerCrash,
        /// Per-persona bucket deleted; restore from WAT-anchored snapshot.
        NatsBucketLost,
        /// SPIFFE workload-API returns expired SVID; re-attestation flow.
        SpireSvidExpired,
    }

    /// Closed enumeration of all three drill classes (§3.7.2.1).
    pub const ALL_RECOVERY_DRILL_CLASSES: &[RecoveryDrillClass] = &[
        RecoveryDrillClass::ContainerCrash,
        RecoveryDrillClass::NatsBucketLost,
        RecoveryDrillClass::SpireSvidExpired,
    ];

    /// Drill cadence in days (§3.7.2.1 "Frequency" column).
    /// `ContainerCrash` is weekly (7d); `NatsBucketLost` and
    /// `SpireSvidExpired` are monthly (30d). The cadence is a contract
    /// surface for the operator-side scheduler (OI-PEF-9 Quadlet
    /// `OnCalendar=` template, out of Tag-3 scope).
    pub const fn recovery_drill_cadence_days(class: RecoveryDrillClass) -> u32 {
        match class {
            RecoveryDrillClass::ContainerCrash => 7,
            RecoveryDrillClass::NatsBucketLost => 30,
            RecoveryDrillClass::SpireSvidExpired => 30,
        }
    }

    /// Substrate-layer label per drill class (§3.7.2.1 stratification).
    pub const fn recovery_drill_substrate_layer(class: RecoveryDrillClass) -> &'static str {
        match class {
            RecoveryDrillClass::ContainerCrash => "engine-runtime",
            RecoveryDrillClass::NatsBucketLost => "storage-substrate",
            RecoveryDrillClass::SpireSvidExpired => "identity",
        }
    }

    /// The four invariants a drill MUST satisfy to be PASSED
    /// (§3.7.2.2). Drift in any invariant raises
    /// `RecoveryDrillFailedError`.
    #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
    pub enum RecoveryDrillAcceptanceInvariant {
        /// V-907 persona-hash MUST byte-equal pre-drill operator pin-pack hash.
        HashPrePostIdentical,
        /// Post-recovery audit-trace length MUST equal pre-drill length (no event lost).
        AuditTrailGapZero,
        /// All non-revoked capability tokens MUST verify against post-recovery N3 walker.
        CapabilityTokenContinuity,
        /// `recovered → running` MUST complete within 30s.
        ContainerStateConvergenceWithinBudget,
    }

    /// Closed enumeration of all four acceptance invariants (§3.7.2.2).
    pub const ALL_RECOVERY_DRILL_ACCEPTANCE_INVARIANTS: &[RecoveryDrillAcceptanceInvariant] = &[
        RecoveryDrillAcceptanceInvariant::HashPrePostIdentical,
        RecoveryDrillAcceptanceInvariant::AuditTrailGapZero,
        RecoveryDrillAcceptanceInvariant::CapabilityTokenContinuity,
        RecoveryDrillAcceptanceInvariant::ContainerStateConvergenceWithinBudget,
    ];

    /// Recovery budget in seconds (§3.7.2.2 invariant 4).
    pub const RECOVERY_BUDGET_SECONDS: u32 = 30;

    /// Migrate-version trigger condition (§3.7.3.1). All three MUST
    /// hold for a `wakir-persona-vN` → `wakir-persona-v(N+1)`
    /// transition to fire.
    #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
    pub enum MigrateVersionTriggerCondition {
        /// (1) The spec bump is **major** (v1.x → v2.0), not minor.
        SpecBumpMajor,
        /// (2) The `canonical_subset` block shape changes (hash drift).
        HashInputShapeChanges,
        /// (3) HR-slot governance ratification is in place.
        HrSlotGovernanceRatification,
    }

    /// Closed enumeration of all three trigger conditions (§3.7.3.1).
    pub const ALL_MIGRATE_VERSION_TRIGGER_CONDITIONS: &[MigrateVersionTriggerCondition] = &[
        MigrateVersionTriggerCondition::SpecBumpMajor,
        MigrateVersionTriggerCondition::HashInputShapeChanges,
        MigrateVersionTriggerCondition::HrSlotGovernanceRatification,
    ];

    /// Decide whether a migrate-version transition is permitted given
    /// the three trigger conditions (§3.7.3.1).
    ///
    /// Returns `Ok(())` iff conditions (1), (2), AND (3) ALL hold.
    /// Returns `Err(missing_condition)` naming the specific missing
    /// condition for forensics. When (1) AND (2) hold but (3) is
    /// missing, the runtime SHALL emit a
    /// `MigrateVersionGovernanceGateError` (OI-PEF-12 future surface).
    pub fn check_migrate_version_trigger(
        spec_bump_major: bool,
        hash_input_shape_changes: bool,
        hr_slot_governance_ratification: bool,
    ) -> Result<(), MigrateVersionTriggerCondition> {
        if !spec_bump_major {
            return Err(MigrateVersionTriggerCondition::SpecBumpMajor);
        }
        if !hash_input_shape_changes {
            return Err(MigrateVersionTriggerCondition::HashInputShapeChanges);
        }
        if !hr_slot_governance_ratification {
            return Err(MigrateVersionTriggerCondition::HrSlotGovernanceRatification);
        }
        Ok(())
    }

    /// Hash-pin-drift outcome (§3.7.3.3). The engine startup path
    /// dispatches on this surface to decide whether to halt
    /// (`UnexpectedDriftBug`), pass-through (`NoDrift`), or trigger
    /// the Self-Migration-Konverter chain (`ExpectedMajorBumpDrift`).
    #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
    pub enum HashPinDriftOutcome {
        /// Hashes match — no migration triggered, normal startup.
        NoDrift,
        /// Hashes differ within the same v1.x family — startup halt
        /// (`PersonaHashDriftError`); drift is a bug, not a migration.
        UnexpectedDriftBug,
        /// Hashes differ across a major spec bump — expected;
        /// trigger Self-Migration-Konverter chain.
        ExpectedMajorBumpDrift,
    }

    /// Classify a hash-pin-drift event (§3.7.3.3).
    ///
    /// Args:
    /// - `computed_hash` — V-907 persona-hash freshly computed at startup.
    /// - `pinned_hash` — V-907 persona-hash recorded in the operator pin-pack.
    /// - `spec_version_axis_crossed_major_bump` — `true` iff the
    ///   pinned hash was produced under a spec major-version axis
    ///   that the current engine no longer matches.
    pub fn classify_hash_pin_drift(
        computed_hash: &str,
        pinned_hash: &str,
        spec_version_axis_crossed_major_bump: bool,
    ) -> HashPinDriftOutcome {
        if computed_hash == pinned_hash {
            HashPinDriftOutcome::NoDrift
        } else if spec_version_axis_crossed_major_bump {
            HashPinDriftOutcome::ExpectedMajorBumpDrift
        } else {
            HashPinDriftOutcome::UnexpectedDriftBug
        }
    }

    /// Per-instance migrate-version sequence (§3.7.3.4) — the ordered
    /// state transitions for a single persona under a major bump.
    ///
    /// Each element is `(from_state, to_state)` from §3.3
    /// `valid_transitions`. The sequence preserves a rollback window:
    /// the `migrated → uninstantiated` transition fires only after
    /// v2 reaches `running`.
    pub const MIGRATE_VERSION_TRANSITION_SEQUENCE: &[(&str, &str)] = &[
        ("running", "migrated"),
        ("migrated", "uninstantiated"),
        ("uninstantiated", "spawning"),
        ("spawning", "running"),
    ];
}
