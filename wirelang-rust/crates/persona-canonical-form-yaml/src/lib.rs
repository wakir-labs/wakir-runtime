// SPDX-License-Identifier: Apache-2.0
//! YAML front-matter parser + canonical-subset extractor — Rust pendant.
//!
//! This crate is the byte-for-byte Rust pendant of the YAML-parser-and-
//! extractor surface of `wirelang.persona.persona_canonical_form`
//! (Python). It produces the canonical-subset `serde_json::Value` that
//! `persona-canonical-form` (Crate-2) then turns into RFC 8785 JCS
//! bytes, which in turn `persona-hash` (Crate-1) feeds into SHA-256.
//!
//! Persona-definition file shape (V-907 mock format, Phase-1b Sprint-1):
//!
//! - Persona definitions are markdown files with a YAML front-matter
//!   block delimited by `---` lines (Jekyll/Hugo-style).
//! - Front-matter keys covered by the canonical subset:
//!   `name`, `description`, `tools`, `schema_version`, `identity_pinned`.
//! - Markdown body **after** the closing `---` is *out-of-hash*.
//! - Unknown front-matter keys are *ignored* by the canonical extractor
//!   (forward-compat posture; matches the Python contract).
//!
//! Determinism contract
//! --------------------
//!
//! For the V9 ground-truth fixture
//! `wirelang/tests/fixtures/persona_definitions/v9-persona-framework-native.md`
//! (copied into this crate's `tests/fixtures/` so the cross-check stays
//! hermetic), the canonical subset returned by [`read_canonical_subset`]
//! must JCS-serialise (via Crate-2 `persona-canonical-form`) to a byte
//! string of length 387 whose SHA-256 equals `PERSONA_HASH_PIN_V9`
//! (`0f298894...e1d793`). This binds Crate-3 + Crate-2 + Crate-1 into
//! the same V-907 pin-pack as the Python tree.
//!
//! Default-Lock posture (Sprint-4 Crate-3 box, mirrors Crate-1 + Crate-2)
//! ----------------------------------------------------------------------
//!
//! - **A-1 Mock-Format-Baseline:** parse YAML front-matter from a
//!   markdown text; produce a `serde_json::Value::Object` canonical
//!   subset. The next stage (Crate-2 `canonical_jcs_bytes`) handles
//!   the JCS step; this crate does not hash.
//! - **A-2 Additiv-only:** this crate is added next to `persona-hash`
//!   and `persona-canonical-form`; does not delete or move any
//!   existing Rust or Python file.
//! - **A-3 Body out-of-hash:** the markdown body after the closing
//!   `---` fence is dropped from the canonical subset; only the
//!   front-matter keys reach Crate-2.
//!
//! Public surface (mirrors Python four-function pipeline)
//! -----------------------------------------------------
//!
//! - [`PersonaCanonicalFormYamlError`] — error enum (front-matter
//!   missing, malformed, extraction failures).
//! - [`split_frontmatter`] — split markdown text into
//!   `(frontmatter_yaml, body)`.
//! - [`parse_frontmatter`] — parse YAML front-matter into a
//!   `serde_yaml::Value` (must be a mapping).
//! - [`extract_canonical_subset`] — project a parsed YAML mapping onto
//!   the V-907 canonical subset as a `serde_json::Value::Object`.
//! - [`read_canonical_subset`] — end-to-end helper: markdown text →
//!   canonical-subset `serde_json::Value`.
//!
//! Mira-Decision (Sprint-3-Closeout-Stempel, ratified 2026-05-07
//! ~18:15 CEST): `serde_yaml = 0.9.34` is the default YAML parser.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use serde_json::{Map, Value as JsonValue};
use serde_yaml::Value as YamlValue;

/// Supported persona-definition schema_version (V-907 mock format,
/// Phase-1b Sprint-1).
pub const SUPPORTED_SCHEMA_VERSION: &str = "persona-v1";

/// Front-matter keys preserved in the canonical subset, in *insertion*
/// order. JCS will sort them lexicographically anyway, but listing
/// them explicitly here documents the contract.
pub const CANONICAL_TOP_LEVEL_KEYS: &[&str] = &[
    "name",
    "description",
    "tools",
    "schema_version",
    "identity_pinned",
];

/// Required keys inside `identity_pinned`.
pub const CANONICAL_IDENTITY_PINNED_KEYS: &[&str] =
    &["cross_review_zones", "authority", "hierarchy"];

/// Error class for the YAML front-matter parser + canonical-subset
/// extractor.
///
/// Variants mirror the Python error surface:
/// - [`Self::FrontmatterMissing`] ↔ `PersonaFrontmatterMissingError`
/// - [`Self::FrontmatterMalformed`] ↔ `PersonaFrontmatterMalformedError`
/// - [`Self::MissingKey`], [`Self::UnsupportedSchemaVersion`],
///   [`Self::InvalidShape`] cover the `extract_canonical_subset`
///   error surface (Python raises `KeyError` / `ValueError`).
/// - [`Self::YamlParseError`] surfaces the underlying `serde_yaml`
///   error message for diagnostics.
#[derive(Debug)]
pub enum PersonaCanonicalFormYamlError {
    /// The text does not open with `---` or has no closing `---`
    /// fence. Mirrors Python `PersonaFrontmatterMissingError`.
    FrontmatterMissing(&'static str),

    /// The YAML front-matter is empty or not a mapping. Mirrors
    /// Python `PersonaFrontmatterMalformedError`.
    FrontmatterMalformed(String),

    /// The underlying YAML parser failed. Mirrors Python
    /// `yaml.YAMLError` surfaced through `parse_frontmatter`.
    YamlParseError(String),

    /// A required top-level or `identity_pinned` key is missing.
    /// Mirrors Python `KeyError`.
    MissingKey(String),

    /// The `schema_version` is not [`SUPPORTED_SCHEMA_VERSION`].
    /// Mirrors Python `ValueError` from `extract_canonical_subset`.
    UnsupportedSchemaVersion(String),

    /// A canonical field has an invalid shape (e.g. `identity_pinned`
    /// not a mapping, `tools` neither a list nor a string). Mirrors
    /// Python `ValueError` from `extract_canonical_subset`.
    InvalidShape(String),
}

impl std::fmt::Display for PersonaCanonicalFormYamlError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::FrontmatterMissing(msg) => write!(f, "front-matter missing: {msg}"),
            Self::FrontmatterMalformed(msg) => write!(f, "front-matter malformed: {msg}"),
            Self::YamlParseError(msg) => write!(f, "YAML parse error: {msg}"),
            Self::MissingKey(msg) => write!(f, "missing key: {msg}"),
            Self::UnsupportedSchemaVersion(msg) => {
                write!(f, "unsupported schema_version: {msg}")
            }
            Self::InvalidShape(msg) => write!(f, "invalid shape: {msg}"),
        }
    }
}

impl std::error::Error for PersonaCanonicalFormYamlError {}

/// Split a persona markdown file into `(frontmatter_yaml, body)`.
///
/// The front-matter block must start at byte 0 with a literal `---`
/// line and end at the next standalone `---` line. Anything after the
/// closing fence is the body and is **not** returned in the canonical
/// subset.
///
/// Mirrors Python `split_frontmatter`. Line-ending handling matches
/// Python's `str.splitlines(keepends=True)`: `\n`, `\r\n`, and `\r`
/// are all recognised as line terminators; a closing-fence line
/// containing only `---` (after stripping trailing CR/LF) ends the
/// front-matter block.
///
/// # Errors
///
/// Returns [`PersonaCanonicalFormYamlError::FrontmatterMissing`] if
/// the file does not start with `---` or has no closing fence.
pub fn split_frontmatter(text: &str) -> Result<(String, String), PersonaCanonicalFormYamlError> {
    if !text.starts_with("---") {
        return Err(PersonaCanonicalFormYamlError::FrontmatterMissing(
            "persona-definition must open with a '---' YAML front-matter fence",
        ));
    }
    // Strip the opening fence and the immediate line terminator.
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

    // Walk lines (keep terminators, like Python's splitlines(keepends=True))
    // until we hit a standalone "---" line.
    let mut fm_buf = String::new();
    let mut body_buf = String::new();
    let mut found_closing = false;
    let mut in_body = false;

    let mut remaining = rest;
    while !remaining.is_empty() {
        // Find the next line terminator.
        let (line_with_term, next): (&str, &str) = match remaining.find(['\n', '\r']) {
            Some(idx) => {
                // Detect \r\n vs \n vs \r.
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
            // Strip trailing \r\n / \n / \r for the closing-fence check.
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
        return Err(PersonaCanonicalFormYamlError::FrontmatterMissing(
            "persona-definition front-matter has no closing '---' fence",
        ));
    }

    Ok((fm_buf, body_buf))
}

/// Parse the YAML front-matter into a `serde_yaml::Value` mapping.
///
/// Mirrors Python `parse_frontmatter`. Empty documents and non-mapping
/// documents are rejected.
///
/// # Errors
///
/// - [`PersonaCanonicalFormYamlError::FrontmatterMalformed`] if the
///   YAML parses to null (empty document) or to a non-mapping value
///   (scalar, sequence).
/// - [`PersonaCanonicalFormYamlError::YamlParseError`] if the
///   underlying `serde_yaml` parser fails.
pub fn parse_frontmatter(
    frontmatter_yaml: &str,
) -> Result<YamlValue, PersonaCanonicalFormYamlError> {
    let parsed: YamlValue = serde_yaml::from_str(frontmatter_yaml)
        .map_err(|e| PersonaCanonicalFormYamlError::YamlParseError(e.to_string()))?;
    match &parsed {
        YamlValue::Null => Err(PersonaCanonicalFormYamlError::FrontmatterMalformed(
            "persona-definition front-matter is empty".to_string(),
        )),
        YamlValue::Mapping(_) => Ok(parsed),
        other => Err(PersonaCanonicalFormYamlError::FrontmatterMalformed(
            format!(
                "persona-definition front-matter must be a YAML mapping, got {}",
                yaml_type_name(other)
            ),
        )),
    }
}

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

/// Convert a `serde_yaml::Value` to a `serde_json::Value`, recursively.
///
/// This is the type-boundary between the YAML parser (Crate-3) and the
/// JCS canonicaliser (Crate-2). YAML values are mapped to their JSON
/// counterparts:
/// - Null → Null
/// - Bool → Bool
/// - Number → Number (i64 / u64 / f64; YAML integers stay integers,
///   matching Python's `yaml.safe_load`)
/// - String → String
/// - Sequence → Array
/// - Mapping → Object (keys must be strings; non-string keys are
///   rejected as InvalidShape — JCS would reject them anyway)
/// - Tagged → unwrap and recurse (drops the tag, matching
///   `yaml.safe_load`'s behaviour for unknown tags after our use of
///   `serde_yaml::from_str` on a non-tagged document)
fn yaml_to_json(value: YamlValue) -> Result<JsonValue, PersonaCanonicalFormYamlError> {
    match value {
        YamlValue::Null => Ok(JsonValue::Null),
        YamlValue::Bool(b) => Ok(JsonValue::Bool(b)),
        YamlValue::Number(n) => {
            // serde_yaml::Number → serde_json::Number conversion.
            if let Some(i) = n.as_i64() {
                Ok(JsonValue::Number(i.into()))
            } else if let Some(u) = n.as_u64() {
                Ok(JsonValue::Number(u.into()))
            } else if let Some(f) = n.as_f64() {
                serde_json::Number::from_f64(f)
                    .map(JsonValue::Number)
                    .ok_or_else(|| {
                        PersonaCanonicalFormYamlError::InvalidShape(
                            "non-finite float in front-matter".to_string(),
                        )
                    })
            } else {
                Err(PersonaCanonicalFormYamlError::InvalidShape(
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
                        return Err(PersonaCanonicalFormYamlError::InvalidShape(format!(
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

/// Project a parsed YAML front-matter mapping onto the V-907 canonical
/// subset.
///
/// Keys not in [`CANONICAL_TOP_LEVEL_KEYS`] are dropped. The
/// `identity_pinned` block is recursively narrowed to its canonical
/// sub-keys ([`CANONICAL_IDENTITY_PINNED_KEYS`]).
///
/// Returns a [`serde_json::Value::Object`] ready to be passed into
/// [`persona-canonical-form`'s `canonical_jcs_bytes`](https://github.com/wakir-labs/wakir-runtime).
/// Keys appear in [`CANONICAL_TOP_LEVEL_KEYS`] order in the returned
/// object; JCS will re-sort them lexicographically before hashing, so
/// the order has no effect on the resulting hash but is preserved for
/// human inspection of the intermediate object.
///
/// # Errors
///
/// - [`PersonaCanonicalFormYamlError::MissingKey`] if a required
///   top-level or `identity_pinned` key is missing.
/// - [`PersonaCanonicalFormYamlError::UnsupportedSchemaVersion`] if
///   `schema_version` is not [`SUPPORTED_SCHEMA_VERSION`].
/// - [`PersonaCanonicalFormYamlError::InvalidShape`] if a field has
///   the wrong type (e.g. `identity_pinned` not a mapping, `tools`
///   neither list nor string).
pub fn extract_canonical_subset(
    frontmatter: YamlValue,
) -> Result<JsonValue, PersonaCanonicalFormYamlError> {
    let YamlValue::Mapping(fm) = frontmatter else {
        return Err(PersonaCanonicalFormYamlError::FrontmatterMalformed(
            "extract_canonical_subset expected a YAML mapping".to_string(),
        ));
    };

    // Helper: look up a string key in a serde_yaml::Mapping.
    let get =
        |key: &str| -> Option<YamlValue> { fm.get(YamlValue::String(key.to_string())).cloned() };

    // 1. Required keys present?
    let missing: Vec<&str> = CANONICAL_TOP_LEVEL_KEYS
        .iter()
        .copied()
        .filter(|k| get(k).is_none())
        .collect();
    if !missing.is_empty() {
        return Err(PersonaCanonicalFormYamlError::MissingKey(format!(
            "persona front-matter missing required keys: {missing:?}"
        )));
    }

    // 2. schema_version supported?
    let schema_version_raw = get("schema_version").expect("checked above");
    let schema_version = match &schema_version_raw {
        YamlValue::String(s) => s.clone(),
        other => {
            return Err(PersonaCanonicalFormYamlError::InvalidShape(format!(
                "schema_version must be a string, got {}",
                yaml_type_name(other)
            )))
        }
    };
    if schema_version != SUPPORTED_SCHEMA_VERSION {
        return Err(PersonaCanonicalFormYamlError::UnsupportedSchemaVersion(
            format!(
                "persona schema_version={schema_version:?} is not supported; expected {SUPPORTED_SCHEMA_VERSION:?}"
            ),
        ));
    }

    // 3. identity_pinned shape + sub-key projection.
    let identity_pinned_raw = get("identity_pinned").expect("checked above");
    let YamlValue::Mapping(ip_map) = identity_pinned_raw else {
        return Err(PersonaCanonicalFormYamlError::InvalidShape(
            "persona identity_pinned must be a mapping".to_string(),
        ));
    };
    let missing_ip: Vec<&str> = CANONICAL_IDENTITY_PINNED_KEYS
        .iter()
        .copied()
        .filter(|k| ip_map.get(YamlValue::String((*k).to_string())).is_none())
        .collect();
    if !missing_ip.is_empty() {
        return Err(PersonaCanonicalFormYamlError::InvalidShape(format!(
            "persona identity_pinned missing required keys: {missing_ip:?}"
        )));
    }
    let mut identity_pinned_canon = Map::with_capacity(CANONICAL_IDENTITY_PINNED_KEYS.len());
    for k in CANONICAL_IDENTITY_PINNED_KEYS {
        let v = ip_map
            .get(YamlValue::String((*k).to_string()))
            .cloned()
            .expect("checked above");
        identity_pinned_canon.insert((*k).to_string(), yaml_to_json(v)?);
    }

    // 4. tools — list or comma-separated string (Python-parity).
    let tools_raw = get("tools").expect("checked above");
    let tools_canon: Vec<JsonValue> = match tools_raw {
        YamlValue::String(s) => s
            .split(',')
            .map(str::trim)
            .filter(|t| !t.is_empty())
            .map(|t| JsonValue::String(t.to_string()))
            .collect(),
        YamlValue::Sequence(seq) => {
            let mut out = Vec::with_capacity(seq.len());
            for item in seq {
                // str(t) in Python; here we accept strings directly,
                // and stringify scalar non-strings via Display.
                let s = match item {
                    YamlValue::String(s) => s,
                    YamlValue::Bool(b) => b.to_string(),
                    YamlValue::Number(n) => n.to_string(),
                    YamlValue::Null => "None".to_string(),
                    other => {
                        return Err(PersonaCanonicalFormYamlError::InvalidShape(format!(
                            "tools list item must be a scalar, got {}",
                            yaml_type_name(&other)
                        )))
                    }
                };
                out.push(JsonValue::String(s));
            }
            out
        }
        other => {
            return Err(PersonaCanonicalFormYamlError::InvalidShape(format!(
                "persona tools must be a list or a comma-separated string, got {}",
                yaml_type_name(&other)
            )))
        }
    };

    // 5. name + description — stringified.
    let name_raw = get("name").expect("checked above");
    let name = stringify_scalar(&name_raw)?;
    let description_raw = get("description").expect("checked above");
    let description = stringify_scalar(&description_raw)?;

    // 6. Assemble in CANONICAL_TOP_LEVEL_KEYS order (JCS will resort,
    //    but the documented intermediate order matches Python).
    let mut canonical = Map::with_capacity(CANONICAL_TOP_LEVEL_KEYS.len());
    canonical.insert("name".to_string(), JsonValue::String(name));
    canonical.insert("description".to_string(), JsonValue::String(description));
    canonical.insert("tools".to_string(), JsonValue::Array(tools_canon));
    canonical.insert(
        "schema_version".to_string(),
        JsonValue::String(schema_version),
    );
    canonical.insert(
        "identity_pinned".to_string(),
        JsonValue::Object(identity_pinned_canon),
    );
    Ok(JsonValue::Object(canonical))
}

fn stringify_scalar(v: &YamlValue) -> Result<String, PersonaCanonicalFormYamlError> {
    match v {
        YamlValue::String(s) => Ok(s.clone()),
        YamlValue::Bool(b) => Ok(b.to_string()),
        YamlValue::Number(n) => Ok(n.to_string()),
        YamlValue::Null => Ok("None".to_string()),
        other => Err(PersonaCanonicalFormYamlError::InvalidShape(format!(
            "expected scalar, got {}",
            yaml_type_name(other)
        ))),
    }
}

/// End-to-end helper: markdown text → canonical-subset
/// `serde_json::Value::Object`.
///
/// Equivalent to:
///
/// ```ignore
/// let (fm, _body) = split_frontmatter(text)?;
/// extract_canonical_subset(parse_frontmatter(&fm)?)
/// ```
///
/// Mirrors Python `read_canonical_subset`.
///
/// # Errors
///
/// See [`PersonaCanonicalFormYamlError`].
pub fn read_canonical_subset(
    persona_definition_text: &str,
) -> Result<JsonValue, PersonaCanonicalFormYamlError> {
    let (fm, _body) = split_frontmatter(persona_definition_text)?;
    let parsed = parse_frontmatter(&fm)?;
    extract_canonical_subset(parsed)
}

#[cfg(test)]
mod tests {
    use super::*;
    use sha2::{Digest, Sha256};

    /// V9 fixture text — copied verbatim from the wirelang test-fixture
    /// tree so the cross-check stays hermetic to this crate.
    const V9_FIXTURE: &str = include_str!("../tests/fixtures/v9-persona-framework-native.md");

    /// V9 ground-truth pin (lifted from `pin_pack_constants.py`,
    /// `PERSONA_HASH_PIN_V9`, captured 2026-05-07). Cross-language
    /// anchor: `sha256(jcs_bytes(read_canonical_subset(V9_FIXTURE)))`
    /// must equal this constant.
    const V9_PIN_HEX: &str = "0f298894204e6117e42ad7073b7a3af8ada1851de74d585fc5cb4c4d70e1d793";

    /// V9 JCS canonical bytes (UTF-8) length — captured from Python
    /// `rfc8785.dumps(canon)` on 2026-05-07T11:59 UTC. 387 bytes.
    const V9_JCS_BYTES_LEN: usize = 387;

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

    // -------------------------------------------------------------------
    // 1 / split_frontmatter — V9 fixture round-trips cleanly: front-matter
    //     contains the YAML keys, body starts with the markdown heading.
    // -------------------------------------------------------------------

    #[test]
    fn t1_split_frontmatter_v9_roundtrip() {
        let (fm, body) = split_frontmatter(V9_FIXTURE).expect("v9 must split");
        assert!(
            fm.contains("name: pre-framework-agent"),
            "front-matter must contain name key"
        );
        assert!(
            fm.contains("schema_version: persona-v1"),
            "front-matter must contain schema_version"
        );
        assert!(
            fm.contains("identity_pinned:"),
            "front-matter must contain identity_pinned block"
        );
        assert!(
            !fm.contains("---"),
            "front-matter must not include the fences themselves"
        );
        assert!(
            body.contains("# Framework-native test fixture"),
            "body must start with the markdown heading"
        );
    }

    // -------------------------------------------------------------------
    // 2 / End-to-end V9 cross-check — read_canonical_subset → JCS bytes
    //     of length 387 whose SHA-256 equals the V9 pin. This is the
    //     byte-identical Python↔Rust anchor for Crate-3 (and indirectly
    //     binds Crate-3 into the V-907 pin-pack with Crate-2 + Crate-1).
    // -------------------------------------------------------------------

    #[test]
    fn t2_v9_end_to_end_byte_parity_with_python() {
        let canon = read_canonical_subset(V9_FIXTURE).expect("v9 must extract");
        // JCS bytes via serde_jcs directly (dev-dep). Same canonicaliser
        // as Crate-2 uses; this test is intentionally independent of
        // the sister crate.
        let blob = serde_jcs::to_vec(&canon).expect("v9 must canonicalise");
        assert_eq!(
            blob.len(),
            V9_JCS_BYTES_LEN,
            "v9 JCS-bytes length must be 387 (Python cross-lang anchor)"
        );
        assert_eq!(
            sha256_hex(&blob),
            V9_PIN_HEX,
            "sha256(jcs_bytes(read_canonical_subset(V9))) must equal V9 pin"
        );
    }

    // -------------------------------------------------------------------
    // 3 / split_frontmatter — missing opening fence rejected. Mirrors
    //     Python `PersonaFrontmatterMissingError`.
    // -------------------------------------------------------------------

    #[test]
    fn t3_split_frontmatter_missing_opening_fence_rejected() {
        let text = "name: foo\n---\nbody\n";
        let err = split_frontmatter(text).expect_err("missing opening fence must error");
        assert!(matches!(
            err,
            PersonaCanonicalFormYamlError::FrontmatterMissing(_)
        ));

        let text2 = "---\nname: foo\nno-closing-fence-here\n";
        let err2 = split_frontmatter(text2).expect_err("missing closing fence must error");
        assert!(matches!(
            err2,
            PersonaCanonicalFormYamlError::FrontmatterMissing(_)
        ));
    }

    // -------------------------------------------------------------------
    // 4 / extract_canonical_subset — missing required key rejected with
    //     MissingKey variant.
    // -------------------------------------------------------------------

    #[test]
    fn t4_extract_missing_top_level_key_rejected() {
        // Front-matter without `tools`.
        let yaml_text = "\
name: x
description: d
schema_version: persona-v1
identity_pinned:
  cross_review_zones: []
  authority: {push_remote: false, budget_cap_eur_per_month: 0, sub_delegation: false}
  hierarchy: {reports_to: cto, escalation: cto}
";
        let parsed = parse_frontmatter(yaml_text).expect("must parse");
        let err = extract_canonical_subset(parsed).expect_err("missing tools key must error");
        match err {
            PersonaCanonicalFormYamlError::MissingKey(msg) => {
                assert!(
                    msg.contains("tools"),
                    "error must name the missing key: {msg}"
                );
            }
            other => panic!("expected MissingKey, got {other:?}"),
        }
    }

    // -------------------------------------------------------------------
    // 5 / extract_canonical_subset — unsupported schema_version rejected
    //     with UnsupportedSchemaVersion variant.
    // -------------------------------------------------------------------

    #[test]
    fn t5_extract_unsupported_schema_version_rejected() {
        let yaml_text = "\
name: x
description: d
tools: [Read]
schema_version: persona-v0
identity_pinned:
  cross_review_zones: []
  authority: {push_remote: false, budget_cap_eur_per_month: 0, sub_delegation: false}
  hierarchy: {reports_to: cto, escalation: cto}
";
        let parsed = parse_frontmatter(yaml_text).expect("must parse");
        let err =
            extract_canonical_subset(parsed).expect_err("unsupported schema_version must error");
        match err {
            PersonaCanonicalFormYamlError::UnsupportedSchemaVersion(msg) => {
                assert!(
                    msg.contains("persona-v0"),
                    "error must name the version: {msg}"
                );
                assert!(
                    msg.contains("persona-v1"),
                    "error must name the expected version: {msg}"
                );
            }
            other => panic!("expected UnsupportedSchemaVersion, got {other:?}"),
        }
    }

    // -------------------------------------------------------------------
    // 6 / extract_canonical_subset — tools as comma-separated string is
    //     tolerated (Python-parity, see `extract_canonical_subset`
    //     `isinstance(tools_raw, str)` branch).
    // -------------------------------------------------------------------

    #[test]
    fn t6_extract_tools_as_comma_separated_string() {
        let yaml_text = "\
name: x
description: d
tools: \"Read, Write, Edit\"
schema_version: persona-v1
identity_pinned:
  cross_review_zones: []
  authority: {push_remote: false, budget_cap_eur_per_month: 0, sub_delegation: false}
  hierarchy: {reports_to: cto, escalation: cto}
";
        let parsed = parse_frontmatter(yaml_text).expect("must parse");
        let canon = extract_canonical_subset(parsed).expect("must extract");
        let JsonValue::Object(obj) = &canon else {
            panic!("canonical subset must be an object");
        };
        let tools = obj.get("tools").expect("tools key present");
        let JsonValue::Array(arr) = tools else {
            panic!("tools must be an array");
        };
        assert_eq!(arr.len(), 3, "tools list must have 3 entries");
        assert_eq!(arr[0], JsonValue::String("Read".to_string()));
        assert_eq!(arr[1], JsonValue::String("Write".to_string()));
        assert_eq!(arr[2], JsonValue::String("Edit".to_string()));
    }
}
