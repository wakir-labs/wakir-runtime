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
                "reports_to": "mira",
                "escalation": "mira"
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
