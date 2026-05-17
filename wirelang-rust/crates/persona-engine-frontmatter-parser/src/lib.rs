// SPDX-License-Identifier: Apache-2.0
//! Typed YAML front-matter parser for persona-definition markdown files.
//!
//! This crate sits **above** [`persona-canonical-form-yaml`][pcfy] and
//! **beside** [`persona-engine-v907-verify`][pev907]. Where the former
//! produces the strict 5-key V-907 canonical subset as an untyped
//! `serde_json::Value`, this crate produces a strongly-typed
//! [`PersonaDef`] struct that exposes ALL front-matter fields — both
//! the canonical-subset keys (`name`, `description`, `tools`,
//! `schema_version`, `identity_pinned`) AND extension keys outside the
//! V-907 canonical subset (`persona_slug`, `capabilities`,
//! `befugnis_rahmen`, `llm`, `domain`, `reports_to`, …). Any further
//! unknown keys are preserved in [`PersonaDef::extra`] for forward
//! compatibility.
//!
//! [pcfy]: ../persona_canonical_form_yaml/index.html
//! [pev907]: ../persona_engine_v907_verify/index.html
//!
//! # Why a typed surface?
//!
//! The untyped `serde_json::Value` surface in `persona-canonical-form-
//! yaml` is the right shape for the JCS canonicaliser (which only cares
//! about JSON values), but it is awkward for consumers that need to
//! reason about specific fields:
//!
//! - The persona-engine CLI needs `persona_slug` and `llm.model` to
//!   build a spawn invocation.
//! - The self-migration converter needs `schema_version` and
//!   `identity_pinned.authority` to decide whether a definition is
//!   schema-compatible.
//! - The bridge-diff tool needs `tools` as a typed list to compare
//!   tool-set deltas.
//!
//! This crate gives those consumers a typed Rust API and keeps the
//! untyped JSON surface available for V-907 hashing.
//!
//! # Schema-parity contract (vs. Python `persona_canonical_form.py`)
//!
//! - [`split_frontmatter`] mirrors the Python function of the same name
//!   byte-for-byte, including the `\r\n` / `\n` / `\r` line-terminator
//!   handling and the standalone-`---` closing-fence rule.
//! - [`parse_persona_markdown`] is the typed end-to-end entry point.
//!   It composes [`split_frontmatter`] with
//!   `serde_yaml::from_str::<PersonaDef>` and returns
//!   `Ok((PersonaDef, body))`.
//! - [`PersonaDef::to_canonical_subset`] produces the V-907 canonical
//!   subset as a `serde_json::Value::Object` — the shape compatible
//!   with `persona-canonical-form` (Crate-2) for JCS canonicalisation
//!   and with `persona-canonical-form-yaml` (Crate-3) for byte-
//!   identical cross-language parity.
//!
//! # Default-Lock posture (Sprint-Rust-Frontmatter-Parser-MINI)
//!
//! - **A-1 Mock-Format-Baseline:** parse YAML front-matter from a
//!   markdown text into a typed [`PersonaDef`]; preserve unknown keys
//!   in [`PersonaDef::extra`].
//! - **A-2 Additiv-only:** this crate is added next to the existing
//!   roster; Python `persona_canonical_form.py` is UNCHANGED.
//! - **A-3 Body out-of-hash:** the markdown body after the closing
//!   `---` fence is returned as the second tuple element of
//!   [`parse_persona_markdown`]; it is NEVER part of any V-907 hash
//!   input.
//!
//! # Cross-language round-trip
//!
//! `tests/frontmatter_parser_smoke_test.rs` includes a cross-language
//! anchor test against the V9 ground-truth fixture: the SHA-256 of the
//! JCS bytes of [`PersonaDef::to_canonical_subset`] must equal
//! `PERSONA_HASH_PIN_V9` (`0f298894…e1d793`). This binds this crate
//! into the V-907 pin pack alongside `persona-canonical-form-yaml`.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value as JsonValue};

/// Supported persona-definition schema versions.
///
/// Mirrors `ACCEPTED_SCHEMA_VERSIONS` in
/// `wirelang.persona.persona_canonical_form` (Python). Listed in
/// chronological order of introduction.
pub const ACCEPTED_SCHEMA_VERSIONS: &[&str] = &["persona-v1", "persona-v2"];

/// Front-matter keys that participate in the V-907 canonical subset.
/// Mirrors `CANONICAL_TOP_LEVEL_KEYS` in the Python module.
pub const CANONICAL_TOP_LEVEL_KEYS: &[&str] = &[
    "name",
    "description",
    "tools",
    "schema_version",
    "identity_pinned",
];

/// Required keys inside `identity_pinned`. Mirrors
/// `CANONICAL_IDENTITY_PINNED_KEYS` in the Python module.
pub const CANONICAL_IDENTITY_PINNED_KEYS: &[&str] =
    &["cross_review_zones", "authority", "hierarchy"];

// ============================================================================
// Error surface
// ============================================================================

/// Error class for the typed front-matter parser.
///
/// Variants mirror the Python error surface (where applicable) plus the
/// additional shape-error cases that arise from typed parsing.
#[derive(Debug)]
pub enum FrontmatterParserError {
    /// The text does not open with `---` or has no closing `---` fence.
    /// Mirrors Python `PersonaFrontmatterMissingError`.
    FrontmatterMissing(&'static str),

    /// The YAML front-matter is empty or not a mapping. Mirrors Python
    /// `PersonaFrontmatterMalformedError`.
    FrontmatterMalformed(String),

    /// The underlying YAML parser failed. Mirrors Python
    /// `yaml.YAMLError` surfaced through `parse_frontmatter`.
    YamlParseError(String),

    /// A required canonical-subset key is missing or malformed. Mirrors
    /// Python `KeyError` / `ValueError` from `extract_canonical_subset`.
    InvalidShape(String),
}

impl std::fmt::Display for FrontmatterParserError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::FrontmatterMissing(msg) => write!(f, "front-matter missing: {msg}"),
            Self::FrontmatterMalformed(msg) => write!(f, "front-matter malformed: {msg}"),
            Self::YamlParseError(msg) => write!(f, "YAML parse error: {msg}"),
            Self::InvalidShape(msg) => write!(f, "invalid shape: {msg}"),
        }
    }
}

impl std::error::Error for FrontmatterParserError {}

// ============================================================================
// Typed PersonaDef + nested structs
// ============================================================================

/// Strongly-typed persona-definition front-matter.
///
/// Covers every key the persona-engine roster has emitted across
/// schema-versions persona-v1 and persona-v2:
///
/// - V-907 canonical-subset keys (always typed):
///   - [`PersonaDef::name`]
///   - [`PersonaDef::description`]
///   - [`PersonaDef::tools`]
///   - [`PersonaDef::schema_version`]
///   - [`PersonaDef::identity_pinned`] (when present)
/// - Extension keys outside the canonical subset (typed if recognised):
///   - [`PersonaDef::persona_slug`]
///   - [`PersonaDef::capabilities`]
///   - [`PersonaDef::befugnis_rahmen`]
///   - [`PersonaDef::llm`]
///   - [`PersonaDef::domain`]
///   - [`PersonaDef::reports_to`]
/// - Any further unrecognised top-level keys are preserved in
///   [`PersonaDef::extra`] as `serde_json::Value` for forward
///   compatibility (mirrors the Python "unknown keys are ignored"
///   posture, but keeps the raw values reachable for inspection).
///
/// # Deserialisation
///
/// `serde_yaml::from_str::<PersonaDef>` accepts the standard YAML
/// front-matter shape produced by HR's persona-definition format. The
/// `tools` field accepts both the canonical list-of-strings shape AND
/// the comma-separated-string tolerance the Python `extract_canonical_
/// subset` extends (see [`ToolsField`] for details).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PersonaDef {
    /// Persona name (free-form, often the Claude-Code framework slug).
    pub name: String,

    /// One-line persona description (free-form). Quoted strings are
    /// accepted by the YAML parser as plain strings.
    pub description: String,

    /// Tool roster. Either a list of strings or a comma-separated
    /// string (Python-parity tolerance). The [`PersonaDef::tools_list`]
    /// helper always returns a normalised `Vec<String>`.
    pub tools: ToolsField,

    /// Schema version. Must be one of [`ACCEPTED_SCHEMA_VERSIONS`].
    /// Default `persona-v1` when absent (engine-side framework-native
    /// markdown files do not always carry the key explicitly).
    #[serde(default = "default_schema_version")]
    pub schema_version: String,

    /// V-907 identity-pinned block (canonical-subset nested object).
    /// Optional at the typed-API layer because engine-side
    /// framework-native files may omit it; the V-907 canonical-subset
    /// extractor still rejects definitions without it via
    /// [`PersonaDef::to_canonical_subset`].
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub identity_pinned: Option<IdentityPinned>,

    /// Short persona slug used by the framework spawn-machinery
    /// (`subagent_type=<slug>`). Outside the V-907 canonical subset.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub persona_slug: Option<String>,

    /// Free-form capability tags (e.g. "rust", "yaml-parsing"). Outside
    /// the V-907 canonical subset.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub capabilities: Option<Vec<String>>,

    /// Authority/scope block — free-form mapping (mirrors the German-
    /// language "Befugnis-Rahmen" section in persona definitions).
    /// Outside the V-907 canonical subset.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub befugnis_rahmen: Option<JsonValue>,

    /// LLM-pin block (model name + provider, etc.). Outside the V-907
    /// canonical subset. Free-form mapping at the typed-API layer; a
    /// future stricter [`LlmPin`] struct can replace [`JsonValue`]
    /// additively.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub llm: Option<JsonValue>,

    /// Persona functional domain (e.g. "engineering", "operations").
    /// Outside the V-907 canonical subset.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub domain: Option<String>,

    /// Reporting line (organisational supervisor). Outside the V-907
    /// canonical subset.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reports_to: Option<String>,

    /// Unknown / unrecognised top-level front-matter keys. Forward-
    /// compat slot: HR can add new keys without forcing a parser
    /// release. The BTreeMap ordering keeps printing deterministic.
    #[serde(flatten)]
    pub extra: BTreeMap<String, JsonValue>,
}

fn default_schema_version() -> String {
    "persona-v1".to_string()
}

/// Tools-field shape (list-of-strings or comma-separated string).
///
/// The Python `extract_canonical_subset` tolerates `tools: "Read, Write"`
/// alongside `tools: [Read, Write]`. This enum captures both shapes at
/// the typed layer; [`PersonaDef::tools_list`] normalises to
/// `Vec<String>` regardless.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(untagged)]
pub enum ToolsField {
    /// List-of-strings shape (preferred).
    List(Vec<String>),
    /// Comma-separated-string shape (Python-parity tolerance).
    CommaString(String),
}

impl ToolsField {
    /// Normalise to `Vec<String>`. Comma-separated entries are split
    /// on `,`, trimmed, and empty entries are dropped (matches the
    /// Python `extract_canonical_subset` `isinstance(tools_raw, str)`
    /// branch).
    pub fn to_vec(&self) -> Vec<String> {
        match self {
            Self::List(v) => v.clone(),
            Self::CommaString(s) => s
                .split(',')
                .map(str::trim)
                .filter(|t| !t.is_empty())
                .map(str::to_string)
                .collect(),
        }
    }
}

/// V-907 identity-pinned block — strongly-typed nested object.
///
/// Mirrors the canonical-subset `identity_pinned` shape from
/// `persona_canonical_form.py` line 28–43. The `cross_review_zones`
/// list is left as `Vec<JsonValue>` because HR has not yet frozen the
/// per-zone schema (Sprint-Pengine-7 §spec open-item OI-IPS-2).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct IdentityPinned {
    /// Cross-review zones the persona participates in (e.g. K, J, L).
    /// Per-entry shape is left untyped pending HR schema freeze.
    pub cross_review_zones: Vec<JsonValue>,
    /// Authority block (push_remote, budget_cap_eur_per_month,
    /// sub_delegation, …).
    pub authority: Authority,
    /// Reporting hierarchy block.
    pub hierarchy: Hierarchy,
    /// Forward-compat slot for additional identity-pinned keys.
    #[serde(flatten)]
    pub extra: BTreeMap<String, JsonValue>,
}

/// Authority sub-block of [`IdentityPinned`].
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Authority {
    /// Whether the persona may push to remote git repositories.
    pub push_remote: bool,
    /// Monthly budget cap in EUR (0 = no budget).
    pub budget_cap_eur_per_month: i64,
    /// Whether the persona may spawn sub-agents.
    pub sub_delegation: bool,
    /// Forward-compat slot for additional authority keys.
    #[serde(flatten)]
    pub extra: BTreeMap<String, JsonValue>,
}

/// Hierarchy sub-block of [`IdentityPinned`].
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Hierarchy {
    /// Direct supervisor (e.g. `cto`, `ceo`, `aufsichtsrat`).
    pub reports_to: String,
    /// Escalation target (typically same as `reports_to`).
    pub escalation: String,
    /// Forward-compat slot for additional hierarchy keys.
    #[serde(flatten)]
    pub extra: BTreeMap<String, JsonValue>,
}

// ============================================================================
// PersonaDef — methods
// ============================================================================

impl PersonaDef {
    /// Return the normalised tools list (always a `Vec<String>`).
    /// Convenience wrapper around [`ToolsField::to_vec`].
    pub fn tools_list(&self) -> Vec<String> {
        self.tools.to_vec()
    }

    /// Project this typed PersonaDef onto the V-907 canonical subset
    /// (a `serde_json::Value::Object` matching the shape produced by
    /// `persona-canonical-form-yaml::extract_canonical_subset`).
    ///
    /// The resulting object is suitable for direct hand-off to
    /// `persona-canonical-form::canonical_jcs_bytes` (Crate-2) and
    /// produces a SHA-256 byte-identical to the Python pipeline for
    /// the same input.
    ///
    /// # Errors
    ///
    /// - [`FrontmatterParserError::InvalidShape`] if `schema_version`
    ///   is not in [`ACCEPTED_SCHEMA_VERSIONS`] or if `identity_pinned`
    ///   is absent (the typed layer allows it absent for engine-side
    ///   lenient files; the canonical-subset extraction requires it).
    pub fn to_canonical_subset(&self) -> Result<JsonValue, FrontmatterParserError> {
        if !ACCEPTED_SCHEMA_VERSIONS.contains(&self.schema_version.as_str()) {
            return Err(FrontmatterParserError::InvalidShape(format!(
                "persona schema_version={:?} is not supported; expected one of {:?}",
                self.schema_version, ACCEPTED_SCHEMA_VERSIONS
            )));
        }
        let identity_pinned = self.identity_pinned.as_ref().ok_or_else(|| {
            FrontmatterParserError::InvalidShape(
                "persona identity_pinned is required for V-907 canonical subset".to_string(),
            )
        })?;

        // Canonical-subset shape: tools as Vec<String> (normalised).
        let tools_canon: Vec<JsonValue> = self
            .tools_list()
            .into_iter()
            .map(JsonValue::String)
            .collect();

        // identity_pinned -> serde_json::Value::Object, narrowed to the
        // three canonical sub-keys (cross_review_zones, authority,
        // hierarchy). Extra keys in identity_pinned are dropped (matches
        // persona-canonical-form-yaml).
        let mut ip_obj = Map::with_capacity(CANONICAL_IDENTITY_PINNED_KEYS.len());
        ip_obj.insert(
            "cross_review_zones".to_string(),
            JsonValue::Array(identity_pinned.cross_review_zones.clone()),
        );
        ip_obj.insert(
            "authority".to_string(),
            authority_to_json(&identity_pinned.authority),
        );
        ip_obj.insert(
            "hierarchy".to_string(),
            hierarchy_to_json(&identity_pinned.hierarchy),
        );

        // Top-level canonical object, in CANONICAL_TOP_LEVEL_KEYS order
        // (JCS will re-sort lexicographically; order documents intent).
        let mut canonical = Map::with_capacity(CANONICAL_TOP_LEVEL_KEYS.len());
        canonical.insert("name".to_string(), JsonValue::String(self.name.clone()));
        canonical.insert(
            "description".to_string(),
            JsonValue::String(self.description.clone()),
        );
        canonical.insert("tools".to_string(), JsonValue::Array(tools_canon));
        canonical.insert(
            "schema_version".to_string(),
            JsonValue::String(self.schema_version.clone()),
        );
        canonical.insert(
            "identity_pinned".to_string(),
            JsonValue::Object(ip_obj),
        );
        Ok(JsonValue::Object(canonical))
    }
}

fn authority_to_json(a: &Authority) -> JsonValue {
    let mut obj = Map::new();
    obj.insert(
        "push_remote".to_string(),
        JsonValue::Bool(a.push_remote),
    );
    obj.insert(
        "budget_cap_eur_per_month".to_string(),
        JsonValue::Number(a.budget_cap_eur_per_month.into()),
    );
    obj.insert(
        "sub_delegation".to_string(),
        JsonValue::Bool(a.sub_delegation),
    );
    // Extra keys preserved (matches persona-canonical-form-yaml's
    // identity-pinned-recursive narrowing behaviour: it actually
    // preserves the FULL identity_pinned[k] value, not just the
    // canonical sub-keys of authority/hierarchy).
    for (k, v) in &a.extra {
        obj.insert(k.clone(), v.clone());
    }
    JsonValue::Object(obj)
}

fn hierarchy_to_json(h: &Hierarchy) -> JsonValue {
    let mut obj = Map::new();
    obj.insert(
        "reports_to".to_string(),
        JsonValue::String(h.reports_to.clone()),
    );
    obj.insert(
        "escalation".to_string(),
        JsonValue::String(h.escalation.clone()),
    );
    for (k, v) in &h.extra {
        obj.insert(k.clone(), v.clone());
    }
    JsonValue::Object(obj)
}

// ============================================================================
// Public functions — split_frontmatter + parse_persona_markdown
// ============================================================================

/// Split a persona markdown file into `(frontmatter_yaml, body)`.
///
/// The front-matter block must start at byte 0 with a literal `---`
/// line and end at the next standalone `---` line. Anything after the
/// closing fence is the body.
///
/// Mirrors Python `split_frontmatter` byte-for-byte:
///
/// - Opening fence at byte 0; trailing `\r\n` / `\n` / `\r` accepted.
/// - Closing fence is a line containing only `---` (after stripping
///   trailing CR/LF).
/// - Body bytes are returned verbatim (including their original line
///   terminators).
///
/// # Errors
///
/// Returns [`FrontmatterParserError::FrontmatterMissing`] if the file
/// does not start with `---` or has no closing fence.
pub fn split_frontmatter(text: &str) -> Result<(String, String), FrontmatterParserError> {
    if !text.starts_with("---") {
        return Err(FrontmatterParserError::FrontmatterMissing(
            "persona-definition must open with a '---' YAML front-matter fence",
        ));
    }
    let after_open = &text[3..];
    let rest = if let Some(stripped) = after_open.strip_prefix("\r\n") {
        stripped
    } else if let Some(stripped) = after_open.strip_prefix('\n') {
        stripped
    } else if let Some(stripped) = after_open.strip_prefix('\r') {
        stripped
    } else {
        after_open
    };

    let mut fm_buf = String::new();
    let mut body_buf = String::new();
    let mut found_closing = false;
    let mut in_body = false;

    let mut remaining = rest;
    while !remaining.is_empty() {
        let (line_with_term, next): (&str, &str) = match remaining.find(['\n', '\r']) {
            Some(idx) => {
                let bytes = remaining.as_bytes();
                let term_len =
                    if bytes[idx] == b'\r' && idx + 1 < bytes.len() && bytes[idx + 1] == b'\n' {
                        2
                    } else {
                        1
                    };
                let end = idx + term_len;
                (&remaining[..end], &remaining[end..])
            }
            None => (remaining, ""),
        };

        if in_body {
            body_buf.push_str(line_with_term);
        } else {
            let trimmed = line_with_term.trim_end_matches('\n').trim_end_matches('\r');
            if trimmed == "---" {
                in_body = true;
                found_closing = true;
            } else {
                fm_buf.push_str(line_with_term);
            }
        }

        remaining = next;
    }

    if !found_closing {
        return Err(FrontmatterParserError::FrontmatterMissing(
            "persona-definition front-matter has no closing '---' fence",
        ));
    }

    Ok((fm_buf, body_buf))
}

/// Parse a persona-definition markdown text into a typed
/// `(PersonaDef, body)` tuple.
///
/// Composes [`split_frontmatter`] + `serde_yaml::from_str::<PersonaDef>`
/// + a post-parse check that the front-matter is a mapping (not a
///   scalar / list / empty document).
///
/// # Errors
///
/// See [`FrontmatterParserError`]:
/// - [`FrontmatterParserError::FrontmatterMissing`] from
///   [`split_frontmatter`].
/// - [`FrontmatterParserError::FrontmatterMalformed`] for empty / non-
///   mapping front-matter.
/// - [`FrontmatterParserError::YamlParseError`] for syntactic YAML
///   errors.
/// - [`FrontmatterParserError::InvalidShape`] for typed-field shape
///   errors (e.g. `tools` is neither list nor string).
pub fn parse_persona_markdown(
    md_str: &str,
) -> Result<(PersonaDef, String), FrontmatterParserError> {
    let (fm, body) = split_frontmatter(md_str)?;

    // Pre-check: empty / non-mapping document rejected before typed
    // deserialisation so we can raise the same error variants the
    // Python pipeline raises.
    let raw: serde_yaml::Value = serde_yaml::from_str(&fm)
        .map_err(|e| FrontmatterParserError::YamlParseError(e.to_string()))?;
    match &raw {
        serde_yaml::Value::Null => {
            return Err(FrontmatterParserError::FrontmatterMalformed(
                "persona-definition front-matter is empty".to_string(),
            ));
        }
        serde_yaml::Value::Mapping(_) => {}
        other => {
            return Err(FrontmatterParserError::FrontmatterMalformed(format!(
                "persona-definition front-matter must be a YAML mapping, got {}",
                yaml_type_name(other)
            )));
        }
    }

    // Typed deserialisation. serde_yaml's error covers shape errors
    // (e.g. tools as a bool, identity_pinned as a string).
    let persona: PersonaDef = serde_yaml::from_value(raw)
        .map_err(|e| FrontmatterParserError::InvalidShape(e.to_string()))?;

    Ok((persona, body))
}

fn yaml_type_name(v: &serde_yaml::Value) -> &'static str {
    match v {
        serde_yaml::Value::Null => "null",
        serde_yaml::Value::Bool(_) => "bool",
        serde_yaml::Value::Number(_) => "number",
        serde_yaml::Value::String(_) => "string",
        serde_yaml::Value::Sequence(_) => "sequence",
        serde_yaml::Value::Mapping(_) => "mapping",
        serde_yaml::Value::Tagged(_) => "tagged",
    }
}
