// SPDX-License-Identifier: Apache-2.0
//! Read-only persona-validator — Rust pendant.
//!
//! This crate is the byte-for-byte equivalent of
//! `wirelang.persona.persona_validator.validate_persona` in the Python
//! tree. It exists so the Phase-1c Rust migration window has a
//! standalone validator that can be cross-checked against the Python
//! helper via a JCS-bytes anchor (V8 / V9 fixture pins).
//!
//! Determinism contract
//! --------------------
//!
//! Given the V8 (schema-rejected) and V9 (valid persona-v1) ground-
//! truth fixtures, this crate must produce a [`ValidationReport`] whose
//! `to_canonical_value()` JCS-serialises to UTF-8 bytes byte-identical
//! to Python `PersonaValidationReport.to_canonical_dict()` →
//! `rfc8785.dumps(...)`. The cross-check is asserted via
//! `PERSONA_VALIDATOR_REPORT_PIN_V9_HEX` / `..._V8_HEX` SHA-256 anchors
//! in the test module.
//!
//! Default-Lock posture (Sprint-6 Crate-7 box)
//! ------------------------------------------
//!
//! - **A-1 Mock-Format-Baseline:** validator consumes either a
//!   pre-parsed front-matter mapping ([`ValidatorInput::Mapping`]) or a
//!   raw Markdown text ([`ValidatorInput::MarkdownText`]). YAML parsing
//!   for the Markdown branch delegates to the sister
//!   `persona-canonical-form-yaml` crate.
//! - **A-2 Additiv-only:** Crate-7 is added next to the existing six
//!   crates; no file deletion, no existing API narrowed.
//! - **A-3 Body out-of-hash:** the validator never inspects the
//!   Markdown body; only front-matter keys are walked.
//!
//! Public surface (mirrors Python module API)
//! -----------------------------------------
//!
//! - [`PERSONA_VALIDATION_REPORT_SCHEMA_VERSION`] — `"persona-validation-v1"`.
//! - [`VALIDATION_ERROR_CODES`] — closed-set string slice mirroring the
//!   Python registry.
//! - [`ValidationErrorCode`] — Rust enum over the same closed set.
//! - [`ValidationError`] — single error record with
//!   `to_canonical_value()`.
//! - [`ValidationReport`] — outcome struct with `to_canonical_value()`.
//! - [`ValidatorInput`] — input enum (Mapping / Markdown text).
//! - [`validate_persona`] — main entry point.
//!
//! Out-of-scope for this crate
//! ---------------------------
//!
//! - No `Path` branch on the entry point: file IO is the caller's
//!   responsibility (mirror of how Crate-3 splits the YAML / Path
//!   surface; the CLI binary takes the file-IO hit).
//! - No migration (use the `persona-migration-resolver` crate).
//! - No hashing (use `persona-hash`).

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use persona_canonical_form_yaml::{
    parse_frontmatter, split_frontmatter, PersonaCanonicalFormYamlError,
};
use serde_json::{json, Map, Value as JsonValue};
use serde_yaml::Value as YamlValue;

/// Validation-report schema sentinel. Embedded in every report's
/// canonical-value form for cross-lang version discovery.
pub const PERSONA_VALIDATION_REPORT_SCHEMA_VERSION: &str = "persona-validation-v1";

/// Closed-set registry of validation error codes. The string values
/// are the cross-lang parity anchor: the Python pendant emits exactly
/// the same strings.
pub const VALIDATION_ERROR_CODES: &[&str] = &[
    "frontmatter-missing",
    "frontmatter-malformed",
    "missing-top-level-key",
    "identity-pinned-not-mapping",
    "identity-pinned-missing-key",
    "schema-version-unsupported",
    "tools-wrong-type",
];

/// Top-level canonical keys required by the V-907 mock format. Mirrors
/// `persona_canonical_form_yaml::CANONICAL_TOP_LEVEL_KEYS` verbatim,
/// repeated here so the validator's required-key list is locally
/// inspectable (and so we can drop the dependency on the extractor's
/// internal const-array if the schema set ever forks).
const REQUIRED_TOP_LEVEL_KEYS: &[&str] = &[
    "name",
    "description",
    "tools",
    "schema_version",
    "identity_pinned",
];

/// `identity_pinned` required sub-keys. Mirrors
/// `persona_canonical_form_yaml::CANONICAL_IDENTITY_PINNED_KEYS`.
const REQUIRED_IDENTITY_PINNED_KEYS: &[&str] = &["cross_review_zones", "authority", "hierarchy"];

/// Schema-versions the validator considers "supported". Mirrors
/// Python `ACCEPTED_SCHEMA_VERSIONS` (`persona-v1`, `persona-v2`).
const ACCEPTED_SCHEMA_VERSIONS: &[&str] = &["persona-v1", "persona-v2"];

/// Validation-error code enum. The string form (via
/// [`ValidationErrorCode::as_str`]) is the cross-lang parity anchor;
/// the enum form is the in-Rust ergonomic surface.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ValidationErrorCode {
    /// The persona text did not open with a `---` front-matter fence,
    /// or had no closing fence.
    FrontmatterMissing,
    /// The YAML front-matter was empty, a scalar, or otherwise not a
    /// mapping.
    FrontmatterMalformed,
    /// A required top-level key (`name`, `description`, `tools`,
    /// `schema_version`, `identity_pinned`) is missing.
    MissingTopLevelKey,
    /// `identity_pinned` is present but is not a mapping.
    IdentityPinnedNotMapping,
    /// `identity_pinned` is a mapping but is missing a required
    /// sub-key (`cross_review_zones`, `authority`, `hierarchy`).
    IdentityPinnedMissingKey,
    /// `schema_version` is present but is not in
    /// [`ACCEPTED_SCHEMA_VERSIONS`].
    SchemaVersionUnsupported,
    /// `tools` is present but is neither a list nor a string.
    ToolsWrongType,
}

impl ValidationErrorCode {
    /// Byte-stable string form (cross-lang parity anchor).
    pub fn as_str(self) -> &'static str {
        match self {
            Self::FrontmatterMissing => "frontmatter-missing",
            Self::FrontmatterMalformed => "frontmatter-malformed",
            Self::MissingTopLevelKey => "missing-top-level-key",
            Self::IdentityPinnedNotMapping => "identity-pinned-not-mapping",
            Self::IdentityPinnedMissingKey => "identity-pinned-missing-key",
            Self::SchemaVersionUnsupported => "schema-version-unsupported",
            Self::ToolsWrongType => "tools-wrong-type",
        }
    }
}

/// Single validation-failure record. Mirrors Python
/// `ValidationError` (frozen dataclass) byte-for-byte at the canonical-
/// value level.
#[derive(Debug, Clone)]
pub struct ValidationError {
    /// Closed-set error code.
    pub code: ValidationErrorCode,
    /// Human-readable message (matches Python `str(exc)` shape).
    pub message: String,
    /// Optional supplementary detail (e.g. offending value, missing
    /// key name). Empty string if not applicable.
    pub detail: String,
}

impl ValidationError {
    /// Project this error onto a JCS-stable canonical-value object.
    /// Keys appear in lexicographic order (`code`, `detail`, `message`).
    pub fn to_canonical_value(&self) -> JsonValue {
        let mut map = Map::new();
        map.insert("code".to_string(), json!(self.code.as_str()));
        map.insert("detail".to_string(), json!(self.detail));
        map.insert("message".to_string(), json!(self.message));
        JsonValue::Object(map)
    }
}

/// Structured validation outcome. Mirrors Python
/// `PersonaValidationReport` (frozen dataclass).
#[derive(Debug, Clone)]
pub struct ValidationReport {
    /// True iff `errors` is empty.
    pub is_valid: bool,
    /// Declared `schema_version` from the front-matter, or `""` if no
    /// front-matter could be parsed.
    pub schema_version: String,
    /// True iff `schema_version` is in [`ACCEPTED_SCHEMA_VERSIONS`].
    pub schema_supported: bool,
    /// Ordered list of validation-failure records. Empty when
    /// `is_valid == true`.
    pub errors: Vec<ValidationError>,
}

impl ValidationReport {
    /// Project the report onto a JCS-stable canonical-value object.
    ///
    /// The returned `serde_json::Value` is the cross-lang parity
    /// anchor: feeding it through `serde_jcs::to_vec` must produce
    /// byte-identical UTF-8 bytes to the Python
    /// `rfc8785.dumps(report.to_canonical_dict())`.
    pub fn to_canonical_value(&self) -> JsonValue {
        let mut map = Map::new();
        map.insert(
            "errors".to_string(),
            JsonValue::Array(
                self.errors
                    .iter()
                    .map(ValidationError::to_canonical_value)
                    .collect(),
            ),
        );
        map.insert("is_valid".to_string(), JsonValue::Bool(self.is_valid));
        map.insert(
            "report_schema_version".to_string(),
            json!(PERSONA_VALIDATION_REPORT_SCHEMA_VERSION),
        );
        map.insert(
            "schema_supported".to_string(),
            JsonValue::Bool(self.schema_supported),
        );
        map.insert("schema_version".to_string(), json!(self.schema_version));
        JsonValue::Object(map)
    }
}

/// Input enum for [`validate_persona`].
///
/// The Path branch from the Python pendant is intentionally not in
/// this enum: file IO is the caller's responsibility, mirroring the
/// Crate-3 / Crate-2 surface split.
pub enum ValidatorInput<'a> {
    /// Pre-parsed YAML mapping (skips fence-split and YAML parse).
    /// Equivalent to Python's `Mapping` branch.
    Mapping(&'a YamlValue),
    /// Raw Markdown text with `---` front-matter fences. Equivalent
    /// to Python's `str` branch.
    MarkdownText(&'a str),
}

/// Validate a persona definition without migrating or hashing.
///
/// Never panics on validation failure: every error is classified into
/// a [`ValidationError`] record and accumulated in the report. The
/// only `Err` variant returned at the function level is `Ok(...)`
/// regardless — the function is infallible at the Rust type level,
/// matching the Python "never raises on validation failure" contract.
pub fn validate_persona(input: ValidatorInput<'_>) -> ValidationReport {
    // 1) Resolve to a parsed YAML mapping (or short-circuit on a
    //    fence / shape pre-failure).
    let yaml_mapping: YamlValue = match input {
        ValidatorInput::Mapping(v) => v.clone(),
        ValidatorInput::MarkdownText(text) => {
            // Fence split.
            let (fm_yaml, _body) = match split_frontmatter(text) {
                Ok(parts) => parts,
                Err(e) => {
                    return empty_report(ValidationError {
                        code: ValidationErrorCode::FrontmatterMissing,
                        message: format_pre_mapping_message(&e),
                        detail: String::new(),
                    });
                }
            };
            // YAML parse.
            match parse_frontmatter(&fm_yaml) {
                Ok(v) => v,
                Err(e) => {
                    let code = match e {
                        PersonaCanonicalFormYamlError::FrontmatterMalformed(_) => {
                            ValidationErrorCode::FrontmatterMalformed
                        }
                        PersonaCanonicalFormYamlError::YamlParseError(_) => {
                            ValidationErrorCode::FrontmatterMalformed
                        }
                        // Other variants can't escape parse_frontmatter; fold to malformed.
                        _ => ValidationErrorCode::FrontmatterMalformed,
                    };
                    return empty_report(ValidationError {
                        code,
                        message: format_pre_mapping_message(&e),
                        detail: String::new(),
                    });
                }
            }
        }
    };

    // 2) Walk the mapping and collect structural errors.
    let mut errors: Vec<ValidationError> = Vec::new();
    let mut schema_version = String::new();
    let mut schema_supported = false;

    // The YamlValue must itself be a mapping for the Mapping branch
    // to make sense. If it is not, surface as FrontmatterMalformed.
    let mapping = match yaml_mapping.as_mapping() {
        Some(m) => m,
        None => {
            return empty_report(ValidationError {
                code: ValidationErrorCode::FrontmatterMalformed,
                message: format!(
                    "persona-definition front-matter must be a YAML mapping, got {}",
                    yaml_type_name(&yaml_mapping)
                ),
                detail: String::new(),
            });
        }
    };

    let get_str_key =
        |key: &str| -> Option<&YamlValue> { mapping.get(YamlValue::String(key.to_string())) };

    // Missing top-level keys.
    for key in REQUIRED_TOP_LEVEL_KEYS {
        if get_str_key(key).is_none() {
            errors.push(ValidationError {
                code: ValidationErrorCode::MissingTopLevelKey,
                message: format!("persona front-matter missing required key: {key}"),
                detail: (*key).to_string(),
            });
        }
    }

    // Schema-version check.
    if let Some(sv_node) = get_str_key("schema_version") {
        let sv_str = yaml_to_string(sv_node);
        schema_version.clone_from(&sv_str);
        schema_supported = ACCEPTED_SCHEMA_VERSIONS.contains(&sv_str.as_str());
        if !schema_supported {
            errors.push(ValidationError {
                code: ValidationErrorCode::SchemaVersionUnsupported,
                message: format!(
                    "persona schema_version='{sv_str}' is not supported; expected one of ['persona-v1', 'persona-v2']"
                ),
                detail: sv_str,
            });
        }
    }

    // tools type check.
    if let Some(tools_node) = get_str_key("tools") {
        let ok = matches!(tools_node, YamlValue::Sequence(_) | YamlValue::String(_));
        if !ok {
            let tname = yaml_type_name(tools_node);
            errors.push(ValidationError {
                code: ValidationErrorCode::ToolsWrongType,
                message: format!(
                    "persona tools must be a list or a comma-separated string, got {tname}"
                ),
                detail: tname,
            });
        }
    }

    // identity_pinned shape + sub-key check.
    if let Some(ip_node) = get_str_key("identity_pinned") {
        match ip_node.as_mapping() {
            None => {
                let tname = yaml_type_name(ip_node);
                errors.push(ValidationError {
                    code: ValidationErrorCode::IdentityPinnedNotMapping,
                    message: format!("persona identity_pinned must be a mapping, got {tname}"),
                    detail: tname,
                });
            }
            Some(ip_map) => {
                for sub in REQUIRED_IDENTITY_PINNED_KEYS {
                    if ip_map.get(YamlValue::String((*sub).to_string())).is_none() {
                        errors.push(ValidationError {
                            code: ValidationErrorCode::IdentityPinnedMissingKey,
                            message: format!("persona identity_pinned missing required key: {sub}"),
                            detail: (*sub).to_string(),
                        });
                    }
                }
            }
        }
    }

    ValidationReport {
        is_valid: errors.is_empty(),
        schema_version,
        schema_supported,
        errors,
    }
}

fn empty_report(error: ValidationError) -> ValidationReport {
    ValidationReport {
        is_valid: false,
        schema_version: String::new(),
        schema_supported: false,
        errors: vec![error],
    }
}

fn format_pre_mapping_message(err: &PersonaCanonicalFormYamlError) -> String {
    // Mirror the Python `str(exc)` form: each Python error wraps a
    // single plain-text message. The Rust error enum's Display impl
    // prepends a category prefix (e.g. "front-matter missing: ");
    // we strip that to match the Python message verbatim.
    match err {
        PersonaCanonicalFormYamlError::FrontmatterMissing(msg) => (*msg).to_string(),
        PersonaCanonicalFormYamlError::FrontmatterMalformed(msg) => msg.clone(),
        PersonaCanonicalFormYamlError::YamlParseError(msg) => msg.clone(),
        PersonaCanonicalFormYamlError::MissingKey(msg) => msg.clone(),
        PersonaCanonicalFormYamlError::UnsupportedSchemaVersion(msg) => msg.clone(),
        PersonaCanonicalFormYamlError::InvalidShape(msg) => msg.clone(),
    }
}

fn yaml_type_name(v: &YamlValue) -> String {
    // Map serde_yaml::Value variants to Python type-names so that the
    // `detail` field in the cross-lang report matches verbatim.
    // Python emits `type(x).__name__`: `int`, `float`, `str`, `bool`,
    // `list`, `dict`, `NoneType`.
    match v {
        YamlValue::Null => "NoneType".to_string(),
        YamlValue::Bool(_) => "bool".to_string(),
        YamlValue::Number(n) => {
            if n.is_i64() || n.is_u64() {
                "int".to_string()
            } else {
                "float".to_string()
            }
        }
        YamlValue::String(_) => "str".to_string(),
        YamlValue::Sequence(_) => "list".to_string(),
        YamlValue::Mapping(_) => "dict".to_string(),
        YamlValue::Tagged(t) => yaml_type_name(&t.value),
    }
}

fn yaml_to_string(v: &YamlValue) -> String {
    // Mirror Python `str(schema_version_raw)` for the schema-version
    // string read. Strings round-trip verbatim; non-strings stringify
    // via their Display impl (which serde_yaml gives us for scalars).
    match v {
        YamlValue::String(s) => s.clone(),
        YamlValue::Bool(b) => b.to_string(),
        YamlValue::Number(n) => n.to_string(),
        YamlValue::Null => "None".to_string(),
        _ => format!("{v:?}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sha2::{Digest, Sha256};

    /// V9 fixture canonical text (markdown form). Mirrors
    /// `wirelang/tests/fixtures/persona_definitions/v9-persona-framework-native.md`.
    const V9_MARKDOWN: &str = "---
name: pre-framework-agent
description: \"Pre-framework persona fixture for self-migration vector (v8, schema persona-v0-ish — flagged as unsupported).\"
tools:
  - Read
schema_version: persona-v1
identity_pinned:
  cross_review_zones: []
  authority:
    push_remote: false
    budget_cap_eur_per_month: 0
    sub_delegation: false
  hierarchy:
    reports_to: cto
    escalation: cto
---

# Framework-native test fixture (v9 — self-migration target)
";

    /// V8 fixture canonical text.
    const V8_MARKDOWN: &str = "---
name: pre-framework-agent
description: \"Pre-framework persona fixture for self-migration vector (v8, schema persona-v0-ish — flagged as unsupported).\"
tools:
  - Read
schema_version: persona-v0
identity_pinned:
  cross_review_zones: []
  authority:
    push_remote: false
    budget_cap_eur_per_month: 0
    sub_delegation: false
  hierarchy:
    reports_to: cto
    escalation: cto
---

# Pre-framework test fixture (v8 — self-migration source)
";

    /// Byte-identity anchor against Python `rfc8785.dumps(...)` over the
    /// V9 report `to_canonical_dict()`. Computed once on 2026-05-11
    /// from the Python pendant and frozen here.
    const PERSONA_VALIDATOR_REPORT_PIN_V9_HEX: &str =
        "b0d04e973fecc21a457a1a7918047c99f0de28162ae721b6c2960a132da05cd2";

    /// Byte-identity anchor against Python over the V8 report.
    const PERSONA_VALIDATOR_REPORT_PIN_V8_HEX: &str =
        "9d941991e151ab6cd75eb347b35c3ea655898a71c42b1237c5e91e9656c08b34";

    fn jcs_sha256(value: &JsonValue) -> String {
        let bytes = serde_jcs::to_vec(value).expect("JCS serialisation must succeed");
        hex::encode(Sha256::digest(&bytes))
    }

    #[test]
    fn t1_v9_markdown_is_valid() {
        let report = validate_persona(ValidatorInput::MarkdownText(V9_MARKDOWN));
        assert!(report.is_valid);
        assert_eq!(report.schema_version, "persona-v1");
        assert!(report.schema_supported);
        assert!(report.errors.is_empty());
    }

    #[test]
    fn t2_v8_markdown_is_invalid_schema_unsupported() {
        let report = validate_persona(ValidatorInput::MarkdownText(V8_MARKDOWN));
        assert!(!report.is_valid);
        assert_eq!(report.schema_version, "persona-v0");
        assert!(!report.schema_supported);
        assert_eq!(report.errors.len(), 1);
        let err = &report.errors[0];
        assert_eq!(err.code, ValidationErrorCode::SchemaVersionUnsupported);
        assert_eq!(err.detail, "persona-v0");
    }

    #[test]
    fn t3_missing_frontmatter_fence_classified() {
        let report = validate_persona(ValidatorInput::MarkdownText(
            "no frontmatter at all\njust prose\n",
        ));
        assert!(!report.is_valid);
        assert_eq!(report.schema_version, "");
        assert!(!report.schema_supported);
        assert_eq!(report.errors.len(), 1);
        assert_eq!(
            report.errors[0].code,
            ValidationErrorCode::FrontmatterMissing
        );
    }

    #[test]
    fn t4_malformed_yaml_scalar_classified() {
        let report = validate_persona(ValidatorInput::MarkdownText(
            "---\njust-a-scalar\n---\nbody\n",
        ));
        assert!(!report.is_valid);
        assert_eq!(report.errors.len(), 1);
        assert_eq!(
            report.errors[0].code,
            ValidationErrorCode::FrontmatterMalformed
        );
    }

    #[test]
    fn t5_missing_top_level_key_classified() {
        // Build a mapping that drops `description`.
        let yaml = "name: foo
tools: [Read]
schema_version: persona-v1
identity_pinned:
  cross_review_zones: []
  authority: {}
  hierarchy: {}
";
        let v: YamlValue = serde_yaml::from_str(yaml).unwrap();
        let report = validate_persona(ValidatorInput::Mapping(&v));
        assert!(!report.is_valid);
        let missing: Vec<&ValidationError> = report
            .errors
            .iter()
            .filter(|e| e.code == ValidationErrorCode::MissingTopLevelKey)
            .collect();
        assert_eq!(missing.len(), 1);
        assert_eq!(missing[0].detail, "description");
    }

    #[test]
    fn t6_identity_pinned_not_mapping_classified() {
        let yaml = "name: foo
description: bar
tools: [Read]
schema_version: persona-v1
identity_pinned: not-a-mapping
";
        let v: YamlValue = serde_yaml::from_str(yaml).unwrap();
        let report = validate_persona(ValidatorInput::Mapping(&v));
        assert!(!report.is_valid);
        let coded: Vec<&ValidationError> = report
            .errors
            .iter()
            .filter(|e| e.code == ValidationErrorCode::IdentityPinnedNotMapping)
            .collect();
        assert_eq!(coded.len(), 1);
        assert_eq!(coded[0].detail, "str");
    }

    #[test]
    fn t7_identity_pinned_missing_key_classified() {
        let yaml = "name: foo
description: bar
tools: [Read]
schema_version: persona-v1
identity_pinned:
  cross_review_zones: []
  authority: {}
";
        let v: YamlValue = serde_yaml::from_str(yaml).unwrap();
        let report = validate_persona(ValidatorInput::Mapping(&v));
        assert!(!report.is_valid);
        let coded: Vec<&ValidationError> = report
            .errors
            .iter()
            .filter(|e| e.code == ValidationErrorCode::IdentityPinnedMissingKey)
            .collect();
        assert_eq!(coded.len(), 1);
        assert_eq!(coded[0].detail, "hierarchy");
    }

    #[test]
    fn t8_tools_wrong_type_classified() {
        let yaml = "name: foo
description: bar
tools: 42
schema_version: persona-v1
identity_pinned:
  cross_review_zones: []
  authority: {}
  hierarchy: {}
";
        let v: YamlValue = serde_yaml::from_str(yaml).unwrap();
        let report = validate_persona(ValidatorInput::Mapping(&v));
        assert!(!report.is_valid);
        let coded: Vec<&ValidationError> = report
            .errors
            .iter()
            .filter(|e| e.code == ValidationErrorCode::ToolsWrongType)
            .collect();
        assert_eq!(coded.len(), 1);
        assert_eq!(coded[0].detail, "int");
    }

    #[test]
    fn t9_v9_report_jcs_sha256_matches_python_pin() {
        let report = validate_persona(ValidatorInput::MarkdownText(V9_MARKDOWN));
        let canon = report.to_canonical_value();
        let actual = jcs_sha256(&canon);
        assert_eq!(
            actual, PERSONA_VALIDATOR_REPORT_PIN_V9_HEX,
            "V9 validator-report JCS-SHA-256 must match the Python pendant"
        );
    }

    #[test]
    fn t10_v8_report_jcs_sha256_matches_python_pin() {
        let report = validate_persona(ValidatorInput::MarkdownText(V8_MARKDOWN));
        let canon = report.to_canonical_value();
        let actual = jcs_sha256(&canon);
        assert_eq!(
            actual, PERSONA_VALIDATOR_REPORT_PIN_V8_HEX,
            "V8 validator-report JCS-SHA-256 must match the Python pendant"
        );
    }

    #[test]
    fn t11_v9_report_jcs_bytes_length_matches_python_131() {
        // Python: len(rfc8785.dumps(report_v9.to_canonical_dict())) == 131
        let report = validate_persona(ValidatorInput::MarkdownText(V9_MARKDOWN));
        let bytes = serde_jcs::to_vec(&report.to_canonical_value()).unwrap();
        assert_eq!(bytes.len(), 131);
    }

    #[test]
    fn t12_v8_report_jcs_bytes_length_matches_python_303() {
        // Python: len(rfc8785.dumps(report_v8.to_canonical_dict())) == 303
        let report = validate_persona(ValidatorInput::MarkdownText(V8_MARKDOWN));
        let bytes = serde_jcs::to_vec(&report.to_canonical_value()).unwrap();
        assert_eq!(bytes.len(), 303);
    }

    #[test]
    fn t13_validation_error_codes_registry_is_closed_set() {
        // The closed-set guarantee: every enum variant must appear in
        // the string registry; the registry must not carry strings not
        // covered by an enum variant.
        let all_variants = [
            ValidationErrorCode::FrontmatterMissing,
            ValidationErrorCode::FrontmatterMalformed,
            ValidationErrorCode::MissingTopLevelKey,
            ValidationErrorCode::IdentityPinnedNotMapping,
            ValidationErrorCode::IdentityPinnedMissingKey,
            ValidationErrorCode::SchemaVersionUnsupported,
            ValidationErrorCode::ToolsWrongType,
        ];
        let enum_strs: std::collections::HashSet<&str> =
            all_variants.iter().map(|v| v.as_str()).collect();
        let registry_strs: std::collections::HashSet<&str> =
            VALIDATION_ERROR_CODES.iter().copied().collect();
        assert_eq!(enum_strs, registry_strs);
    }

    #[test]
    fn t14_report_canonical_value_keys_lexicographically_sorted() {
        let report = validate_persona(ValidatorInput::MarkdownText(V9_MARKDOWN));
        let canon = report.to_canonical_value();
        let obj = canon.as_object().unwrap();
        let keys: Vec<&str> = obj.keys().map(|k| k.as_str()).collect();
        let mut sorted = keys.clone();
        sorted.sort();
        assert_eq!(keys, sorted);
    }

    #[test]
    fn t15_determinism_stress_10_iterations_jcs_bytes_byte_identical() {
        // The Phase-1c determinism stress test, mirroring the Crate-1
        // t9 / Crate-2 t10 patterns: 10 iterations of validate +
        // to_canonical_value + JCS must yield byte-identical UTF-8
        // bytes across all iterations, for both V8 and V9 fixtures.
        for fixture in [V8_MARKDOWN, V9_MARKDOWN] {
            let mut last: Option<Vec<u8>> = None;
            for i in 0..10 {
                let report = validate_persona(ValidatorInput::MarkdownText(fixture));
                let bytes = serde_jcs::to_vec(&report.to_canonical_value()).unwrap();
                match &last {
                    None => last = Some(bytes),
                    Some(prev) => {
                        assert_eq!(
                            prev, &bytes,
                            "determinism drift on iteration {i} for fixture"
                        );
                    }
                }
            }
        }
    }
}
