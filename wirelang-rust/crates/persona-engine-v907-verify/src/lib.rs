// SPDX-License-Identifier: Apache-2.0
//! V-907 engine-side pin-compute + verify — Rust pendant.
//!
//! Byte-for-byte Rust pendant of
//! `wirelang.persona_engine.v907_verify.compute_v907_pin` /
//! `verify_v907_pin` (Python). Mirrors the spawn-time engine-side
//! V-907 verify gate that consumes axis-A persona markdown bytes
//! (`/etc/wakir/persona/<slug>.md` or `.claude/agents/<slug>.md`) and
//! produces a `"sha256:<64hex>"` pin computed over the JCS-canonical
//! subset of the YAML front-matter.
//!
//! Layer position
//! --------------
//!
//! This crate is the *engine-side* V-907 verify. It sits ONE level
//! above [`persona-hash`] (`compute_persona_hash_from_canonical`) and
//! re-implements the lenient axis-A canonical-subset *shape* used at
//! spawn time. The strict nine-vector canonical-subset shape lives in
//! [`persona-canonical-form-yaml`] and produces the
//! `PERSONA_HASH_PIN_V1..V9` hard-frozen pin pack. The two surfaces
//! are intentionally distinct:
//!
//! | Layer                              | Shape                                                                                       | Purpose                                                  |
//! |------------------------------------|---------------------------------------------------------------------------------------------|----------------------------------------------------------|
//! | `persona-canonical-form-yaml`      | strict: `name, description, tools, schema_version, identity_pinned{zones, authority, ...}` | nine-vector pin pack (V1..V9 hard freeze)                |
//! | `persona-engine-v907-verify` (this) | lenient: `schema_version (default persona-v1)` + optional `identity_pinned, capabilities, domain, reports_to` | spawn-time verify of axis-A markdown, operator-pin compare |
//!
//! Mirrors Python's two-surface design (see
//! `wirelang/persona_engine/v907_verify.py` source comments §"Stub vs.
//! real" and §"Spec §5 anchor").
//!
//! Determinism contract
//! --------------------
//!
//! For the SAMPLE_AXIS_A axis-A fixture (sample persona used in the
//! Python test suite `wirelang/tests/persona_engine/test_v907_verify.py`),
//! [`compute_v907_pin`] must return
//! `"sha256:cf66fbc5e02ebee97726d5903460e1c3b2b20d1e10db6db1083bceb62ede6e39"`
//! byte-for-byte. The pin was captured 2026-05-16 via a local Python run
//! and is anchored in `tests/v907_verify_smoke_test.rs`.
//!
//! Default-Lock posture (mirrors sister crates)
//! --------------------------------------------
//!
//! - **A-1 Engine-Mock-Baseline:** consume axis-A markdown bytes;
//!   produce a `"sha256:<64hex>"` pin. YAML front-matter parsing,
//!   canonical-subset projection, JCS canonicalisation, and SHA-256
//!   are all in-crate (the Python pendant is a single-file module
//!   too; we mirror that boundary).
//! - **A-2 Additiv-only:** added next to existing crates; touches no
//!   other crate's `Cargo.toml` or source.
//! - **A-3 Body out-of-hash:** the markdown body after the closing
//!   `---` fence is dropped; only the front-matter reaches the JCS
//!   step.
//!
//! Public surface
//! --------------
//!
//! - [`PersonaDef`] — parsed axis-A persona-definition representation.
//! - [`PersonaHashError`] — error enum (parse, hash-compute, drift).
//! - [`VerifyResult`] — output of [`verify_v907_pin`].
//! - [`parse_persona_def`] — markdown-text → [`PersonaDef`].
//! - [`compute_v907_pin`] — axis-A bytes → `"sha256:<64hex>"`.
//! - [`verify_v907_pin`] — [`PersonaDef`] + expected pin → [`VerifyResult`].
//! - [`PERSONA_HASH_PREFIX`] — `"sha256:"`.
//! - [`PERSONA_HASH_HEX_LENGTH`] — `64`.
//!
//! NOT in scope (intentional)
//! --------------------------
//!
//! - File-path entry point. Callers read the file themselves (mirrors
//!   Python `verify_v907_pin(axis_a_path: Path)` — file IO is the
//!   caller's responsibility on the Rust side too).
//! - Observability hooks (Python `obs.record_v907_verify_duration`).
//!   The Rust spawn-time engine will wire those in a later crate.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

use serde_json::{Map, Value as JsonValue};
use serde_yaml::Value as YamlValue;
use sha2::{Digest, Sha256};

/// Prefix on every V-907 engine-side pin. Mirrors Python
/// `PERSONA_HASH_PREFIX` (`"sha256:"`).
pub const PERSONA_HASH_PREFIX: &str = "sha256:";

/// Length of the hex tail (64 hex chars for SHA-256).
pub const PERSONA_HASH_HEX_LENGTH: usize = 64;

/// Full length of `"sha256:" + 64 hex chars`.
pub const PERSONA_HASH_FULL_LENGTH: usize = PERSONA_HASH_PREFIX.len() + PERSONA_HASH_HEX_LENGTH;

/// Default `schema_version` injected when the axis-A front-matter omits
/// the key. Mirrors Python: `.claude/agents/*.md` files do not always
/// carry `schema_version`; the engine-side caller synthesises
/// `persona-v1` (see `v907_verify.py` lines ~161-167).
pub const DEFAULT_SCHEMA_VERSION: &str = "persona-v1";

/// Engine-side V-907 canonical-subset keys that are lifted from the
/// front-matter into the hash input *if present*. `schema_version` is
/// always present (defaulted to [`DEFAULT_SCHEMA_VERSION`]); the
/// remaining keys are optional and mirror the Python `for key in
/// ("identity_pinned", "capabilities", "domain", "reports_to")` loop.
pub const ENGINE_OPTIONAL_KEYS: &[&str] =
    &["identity_pinned", "capabilities", "domain", "reports_to"];

/// Parsed axis-A persona-definition representation.
///
/// Mirrors the intermediate state in Python's `compute_v907_pin`:
/// after splitting the front-matter and parsing the YAML, the lenient
/// engine-side shape stores the front-matter as a `serde_json::Value`
/// object (keys are strings; values are arbitrary JSON-compatible
/// YAML values). The markdown body is preserved separately and
/// dropped at hash time (out-of-hash by design).
#[derive(Debug, Clone)]
pub struct PersonaDef {
    /// Front-matter as a serde_json object. Type-converted from
    /// `serde_yaml::Value::Mapping` so that we can hand it directly to
    /// the JCS canonicaliser without a second pass.
    pub frontmatter: JsonValue,
    /// Markdown body after the closing `---` fence. Preserved for
    /// callers that want to display it; never reaches the JCS step.
    pub body: String,
}

/// Output of [`verify_v907_pin`].
///
/// Mirrors Python `V907VerifyResult`:
///
/// - `pin`: the freshly-computed pin (`"sha256:<64hex>"`).
/// - `mode`: `"real"` for this Rust path (matching Python's
///   real-engine mode); the Python sibling uses `"stub"` for the
///   0.1.0-pilot stub binary, but the stub mode is not in scope for
///   the Rust pendant.
/// - `matched`: `Some(true)` if `expected_pin` was supplied and
///   matched; `Some(false)` would mean mismatch, but mismatch
///   *raises* [`PersonaHashError::Drift`] before this struct is
///   constructed, so the only observable `Some(_)` value is
///   `Some(true)`. `None` if no expected pin was supplied (or the
///   supplied pin was empty after trimming).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerifyResult {
    /// The freshly-computed pin, full form `"sha256:<64hex>"`.
    pub pin: String,
    /// Verification mode. Always `"real"` for this crate (the
    /// 0.1.0-pilot stub-mode pendant is not in Rust scope).
    pub mode: &'static str,
    /// `Some(true)` if an expected pin matched; `None` if no expected
    /// pin was supplied.
    pub matched: Option<bool>,
}

/// Error class for the V-907 engine-side verify.
///
/// Variants mirror the Python error surface:
///
/// - [`Self::Compute`] ↔ `PersonaHashComputeError` (parse error,
///   missing front-matter, malformed YAML, file IO failure on the
///   caller's side).
/// - [`Self::Drift`] ↔ `PersonaHashDriftError` (expected pin did not
///   match the computed pin).
#[derive(Debug)]
pub enum PersonaHashError {
    /// Front-matter or hash computation failed. Wraps a human-readable
    /// message; mirrors Python `PersonaHashComputeError`.
    Compute(String),

    /// Expected pin did not match the computed pin. Mirrors Python
    /// `PersonaHashDriftError`.
    Drift {
        /// Persona slug supplied by the caller (used for error
        /// context only).
        persona_id: String,
        /// Operator-supplied expected pin (verbatim).
        expected: String,
        /// Freshly-computed pin (`"sha256:<64hex>"`).
        computed: String,
    },
}

impl std::fmt::Display for PersonaHashError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Compute(msg) => write!(f, "V-907 pin-compute failed: {msg}"),
            Self::Drift {
                persona_id,
                expected,
                computed,
            } => write!(
                f,
                "V-907 pin drift for persona {persona_id:?}: \
                 expected={expected} computed={computed}"
            ),
        }
    }
}

impl std::error::Error for PersonaHashError {}

// ---------------------------------------------------------------------
// Front-matter parsing
// ---------------------------------------------------------------------

/// Parse axis-A persona markdown text into a [`PersonaDef`].
///
/// Splits the YAML front-matter (delimited by `---` fences) from the
/// markdown body. The front-matter is YAML-parsed into a
/// `serde_json::Value::Object`. The markdown body is preserved as a
/// `String` but does not reach the hash.
///
/// Mirrors the prefix of Python `compute_v907_pin` up to the
/// canonical-subset construction step.
///
/// # Errors
///
/// Returns [`PersonaHashError::Compute`] if the front-matter fence is
/// missing, the YAML is malformed, or the parsed YAML is not a mapping.
pub fn parse_persona_def(md_str: &str) -> Result<PersonaDef, PersonaHashError> {
    let (fm_str, body_str) = split_frontmatter(md_str)?;
    let yaml_val: YamlValue = serde_yaml::from_str(&fm_str).map_err(|e| {
        PersonaHashError::Compute(format!("axis-A front-matter YAML parse failed: {e}"))
    })?;

    // Mirror Python `parse_frontmatter`: reject null + non-mapping.
    let json_val = match yaml_val {
        YamlValue::Null => {
            return Err(PersonaHashError::Compute(
                "persona-definition front-matter is empty".to_string(),
            ))
        }
        YamlValue::Mapping(_) => yaml_to_json(yaml_val)?,
        other => {
            return Err(PersonaHashError::Compute(format!(
                "persona-definition front-matter must be a YAML mapping, got {}",
                yaml_type_name(&other)
            )))
        }
    };

    Ok(PersonaDef {
        frontmatter: json_val,
        body: body_str,
    })
}

/// Split persona markdown text into `(frontmatter_yaml, body)`.
///
/// The text must start with a literal `---` line; the front-matter
/// runs until the next standalone `---` line. Mirrors Python
/// `split_frontmatter` and the line-ending handling of
/// `str.splitlines(keepends=True)` (recognises `\n`, `\r\n`, `\r`).
///
/// # Errors
///
/// Returns [`PersonaHashError::Compute`] if the opening or closing
/// `---` fence is missing.
fn split_frontmatter(text: &str) -> Result<(String, String), PersonaHashError> {
    if !text.starts_with("---") {
        return Err(PersonaHashError::Compute(
            "persona-definition must open with a '---' YAML front-matter fence".to_string(),
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
        return Err(PersonaHashError::Compute(
            "persona-definition front-matter has no closing '---' fence".to_string(),
        ));
    }
    Ok((fm_buf, body_buf))
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

/// Convert a `serde_yaml::Value` into a `serde_json::Value`.
///
/// Mirrors the type-mapping used by `persona-canonical-form-yaml`
/// (Crate-3) so that the two engine paths produce compatible JSON
/// intermediates. Non-string mapping keys are rejected (JCS would
/// reject them anyway).
fn yaml_to_json(value: YamlValue) -> Result<JsonValue, PersonaHashError> {
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
                        PersonaHashError::Compute("non-finite float in front-matter".to_string())
                    })
            } else {
                Err(PersonaHashError::Compute(
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
                        return Err(PersonaHashError::Compute(format!(
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
// Engine-side canonical-subset construction (lenient shape)
// ---------------------------------------------------------------------

/// Build the V-907 engine-side canonical-subset object from a parsed
/// [`PersonaDef`].
///
/// Mirrors the canonical-subset-construction block in Python
/// `compute_v907_pin` (`v907_verify.py` lines ~157-178):
///
/// 1. `schema_version` is always present; if the front-matter omits
///    the key, default to [`DEFAULT_SCHEMA_VERSION`] (`persona-v1`).
/// 2. Lift the four optional keys [`ENGINE_OPTIONAL_KEYS`] into the
///    canonical subset only if they exist in the front-matter.
/// 3. Drop every other front-matter key — `name`, `description`,
///    `tools`, and any unknown key are NOT part of the engine-side
///    canonical subset. This is intentional: the engine-side verify
///    fixates on the *identity-bearing* keys that the spawn-time gate
///    cares about, not on the full nine-vector canonical shape.
///
/// The resulting object is what `serde_jcs::to_vec` consumes to
/// produce the JCS canonical bytes for the SHA-256 step.
fn build_canonical_subset(def: &PersonaDef) -> Result<JsonValue, PersonaHashError> {
    let fm_obj = def.frontmatter.as_object().ok_or_else(|| {
        PersonaHashError::Compute(
            "PersonaDef.frontmatter must be a JSON object — \
                 parse_persona_def should have enforced this"
                .to_string(),
        )
    })?;

    // 1. schema_version (default persona-v1 if absent or falsy).
    let schema_version = match fm_obj.get("schema_version") {
        Some(JsonValue::String(s)) if !s.is_empty() => s.clone(),
        // Mirror Python `if not schema_version:` — falsy values (empty
        // string, null, missing key) all fall through to the default.
        _ => DEFAULT_SCHEMA_VERSION.to_string(),
    };

    let mut canonical = Map::new();
    canonical.insert(
        "schema_version".to_string(),
        JsonValue::String(schema_version),
    );

    // 2. Walk recognised optional keys.
    for key in ENGINE_OPTIONAL_KEYS {
        if let Some(value) = fm_obj.get(*key) {
            canonical.insert((*key).to_string(), value.clone());
        }
    }
    Ok(JsonValue::Object(canonical))
}

// ---------------------------------------------------------------------
// Public V-907 pin-compute + verify entry points
// ---------------------------------------------------------------------

/// Compute the V-907 engine-side pin for a parsed [`PersonaDef`].
///
/// Mirrors Python `compute_v907_pin(axis_a_bytes)` (return value only).
/// Callers that hold the raw axis-A bytes should use [`compute_v907_pin`]
/// (UTF-8-decodes, parses, then computes).
///
/// # Errors
///
/// Returns [`PersonaHashError::Compute`] if the canonical-subset
/// construction or JCS canonicalisation fails (the former is
/// effectively unreachable for a `PersonaDef` produced by
/// [`parse_persona_def`]).
pub fn compute_v907_pin_from_def(def: &PersonaDef) -> Result<String, PersonaHashError> {
    let canonical = build_canonical_subset(def)?;
    let jcs_bytes = serde_jcs::to_vec(&canonical)
        .map_err(|e| PersonaHashError::Compute(format!("JCS canonicalisation failed: {e}")))?;
    let mut hasher = Sha256::new();
    hasher.update(&jcs_bytes);
    let digest = hasher.finalize();
    Ok(format!("{PERSONA_HASH_PREFIX}{}", hex::encode(digest)))
}

/// Compute the V-907 engine-side pin for axis-A markdown text.
///
/// Mirrors Python `compute_v907_pin(axis_a_bytes: bytes) -> str`:
/// UTF-8 decode → split front-matter → YAML parse → build engine-side
/// canonical subset → JCS canonicalise → SHA-256 → format
/// `"sha256:<64hex>"`.
///
/// # Errors
///
/// Returns [`PersonaHashError::Compute`] if UTF-8 decoding fails, the
/// front-matter is missing or malformed, or any downstream step
/// fails.
pub fn compute_v907_pin(md_str: &str) -> Result<String, PersonaHashError> {
    let def = parse_persona_def(md_str)?;
    compute_v907_pin_from_def(&def)
}

/// Verify a V-907 engine-side pin against a [`PersonaDef`] and an
/// optional expected pin.
///
/// Mirrors Python `verify_v907_pin(persona_id, axis_a_path, expected_pin)`.
/// File IO is the caller's responsibility on the Rust side; pass a
/// parsed [`PersonaDef`] obtained from [`parse_persona_def`].
///
/// Behavioural parity with Python:
///
/// - `expected_pin = None` → compute only, `matched = None`.
/// - `expected_pin = Some("")` or whitespace-only → treated as None
///   (Python `if expected_pin is not None and expected_pin.strip()`).
/// - `expected_pin = Some(non-empty)` → compute, compare; on match
///   set `matched = Some(true)`, on mismatch return
///   [`PersonaHashError::Drift`].
///
/// # Errors
///
/// - [`PersonaHashError::Compute`] on any pin-compute failure.
/// - [`PersonaHashError::Drift`] when a non-empty `expected_pin`
///   disagrees with the computed pin.
pub fn verify_v907_pin(
    persona_id: &str,
    def: &PersonaDef,
    expected_pin: Option<&str>,
) -> Result<VerifyResult, PersonaHashError> {
    let pin = compute_v907_pin_from_def(def)?;
    let effective_expected = expected_pin.and_then(|s| {
        let trimmed = s.trim();
        if trimmed.is_empty() {
            None
        } else {
            // Python compares against the verbatim string (not the
            // trimmed one). Mirror that — return the original.
            Some(s)
        }
    });
    let matched = match effective_expected {
        None => None,
        Some(expected) => {
            if expected == pin {
                Some(true)
            } else {
                return Err(PersonaHashError::Drift {
                    persona_id: persona_id.to_string(),
                    expected: expected.to_string(),
                    computed: pin,
                });
            }
        }
    };
    Ok(VerifyResult {
        pin,
        mode: "real",
        matched,
    })
}

#[cfg(test)]
mod unit_tests {
    use super::*;

    const TRIVIAL: &str = "---\nschema_version: persona-v1\n---\n\nbody\n";

    #[test]
    fn parse_trivial_persona_def() {
        let def = parse_persona_def(TRIVIAL).expect("trivial parse");
        let obj = def.frontmatter.as_object().expect("object");
        assert_eq!(
            obj.get("schema_version"),
            Some(&JsonValue::String("persona-v1".to_string()))
        );
        assert_eq!(def.body, "\nbody\n");
    }

    #[test]
    fn compute_pin_trivial_is_well_formed() {
        let pin = compute_v907_pin(TRIVIAL).expect("trivial hash");
        assert!(pin.starts_with(PERSONA_HASH_PREFIX));
        assert_eq!(pin.len(), PERSONA_HASH_FULL_LENGTH);
    }

    #[test]
    fn missing_opening_fence_rejected() {
        let err = compute_v907_pin("no fence here\n").expect_err("must reject");
        assert!(matches!(err, PersonaHashError::Compute(_)));
    }

    #[test]
    fn missing_closing_fence_rejected() {
        let err = compute_v907_pin("---\nname: x\nno-closing-fence\n").expect_err("must reject");
        assert!(matches!(err, PersonaHashError::Compute(_)));
    }

    #[test]
    fn yaml_scalar_frontmatter_rejected() {
        // Front-matter that parses to a scalar (not a mapping).
        let text = "---\njust-a-string\n---\nbody\n";
        let err = parse_persona_def(text).expect_err("scalar must reject");
        assert!(matches!(err, PersonaHashError::Compute(_)));
    }
}
