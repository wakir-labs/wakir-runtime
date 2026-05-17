// SPDX-License-Identifier: Apache-2.0
//! Smoke tests for `persona-engine-frontmatter-parser`.
//!
//! Covers:
//! 1. `split_frontmatter` round-trip on the V9 ground-truth fixture.
//! 2. `parse_persona_markdown` typed-extraction on V9.
//! 3. `split_frontmatter` rejects missing opening fence.
//! 4. `split_frontmatter` rejects missing closing fence.
//! 5. `parse_persona_markdown` rejects empty front-matter.
//! 6. `parse_persona_markdown` rejects non-mapping front-matter.
//! 7. `ToolsField` accepts list-of-strings shape.
//! 8. `ToolsField` accepts comma-separated-string shape and normalises.
//! 9. `PersonaDef::extra` preserves unknown top-level keys.
//! 10. `PersonaDef::to_canonical_subset` rejects unsupported
//!     schema_version.
//! 11. `PersonaDef::to_canonical_subset` rejects missing
//!     identity_pinned.
//! 12. **Cross-language round-trip** — SHA-256 of JCS-bytes of
//!     `PersonaDef::to_canonical_subset` for V9 fixture equals
//!     `PERSONA_HASH_PIN_V9` (Python parity anchor).

use persona_engine_frontmatter_parser::{
    parse_persona_markdown, split_frontmatter, FrontmatterParserError, ToolsField,
};
use serde_json::Value as JsonValue;
use sha2::{Digest, Sha256};

const V9_FIXTURE: &str = include_str!("fixtures/v9-persona-framework-native.md");

/// V9 ground-truth pin (lifted from `pin_pack_constants.py`,
/// `PERSONA_HASH_PIN_V9`, captured 2026-05-07). Same constant the
/// `persona-canonical-form-yaml` crate uses for its V9 cross-check.
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

// ---------------------------------------------------------------------------
// 1. split_frontmatter — V9 fixture round-trips cleanly.
// ---------------------------------------------------------------------------

#[test]
fn t01_split_frontmatter_v9_roundtrip() {
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

// ---------------------------------------------------------------------------
// 2. parse_persona_markdown — typed extraction on V9.
// ---------------------------------------------------------------------------

#[test]
fn t02_parse_persona_markdown_v9_typed() {
    let (persona, body) = parse_persona_markdown(V9_FIXTURE).expect("v9 must parse");
    assert_eq!(persona.name, "pre-framework-agent");
    assert!(persona.description.contains("Pre-framework persona fixture"));
    assert_eq!(persona.schema_version, "persona-v1");
    let tools = persona.tools_list();
    assert_eq!(tools, vec!["Read".to_string()]);

    let ip = persona
        .identity_pinned
        .as_ref()
        .expect("v9 must have identity_pinned");
    assert!(ip.cross_review_zones.is_empty(), "v9 has no zones");
    assert!(!ip.authority.push_remote);
    assert_eq!(ip.authority.budget_cap_eur_per_month, 0);
    assert!(!ip.authority.sub_delegation);
    assert_eq!(ip.hierarchy.reports_to, "cto");
    assert_eq!(ip.hierarchy.escalation, "cto");

    assert!(
        body.contains("# Framework-native test fixture"),
        "typed parser must still expose the body"
    );
}

// ---------------------------------------------------------------------------
// 3. split_frontmatter — missing opening fence rejected.
// ---------------------------------------------------------------------------

#[test]
fn t03_split_frontmatter_missing_opening_fence_rejected() {
    let text = "name: foo\n---\nbody\n";
    let err = split_frontmatter(text).expect_err("missing opening fence must error");
    assert!(matches!(err, FrontmatterParserError::FrontmatterMissing(_)));
}

// ---------------------------------------------------------------------------
// 4. split_frontmatter — missing closing fence rejected.
// ---------------------------------------------------------------------------

#[test]
fn t04_split_frontmatter_missing_closing_fence_rejected() {
    let text = "---\nname: foo\nno-closing-fence-here\n";
    let err = split_frontmatter(text).expect_err("missing closing fence must error");
    assert!(matches!(err, FrontmatterParserError::FrontmatterMissing(_)));
}

// ---------------------------------------------------------------------------
// 5. parse_persona_markdown — empty front-matter rejected.
// ---------------------------------------------------------------------------

#[test]
fn t05_parse_empty_frontmatter_rejected() {
    let text = "---\n---\nbody\n";
    let err = parse_persona_markdown(text).expect_err("empty front-matter must error");
    match err {
        FrontmatterParserError::FrontmatterMalformed(msg) => {
            assert!(msg.contains("empty"), "error must mention emptiness: {msg}");
        }
        other => panic!("expected FrontmatterMalformed, got {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// 6. parse_persona_markdown — non-mapping front-matter rejected.
// ---------------------------------------------------------------------------

#[test]
fn t06_parse_non_mapping_frontmatter_rejected() {
    let text = "---\n- not\n- a\n- mapping\n---\nbody\n";
    let err = parse_persona_markdown(text).expect_err("sequence front-matter must error");
    match err {
        FrontmatterParserError::FrontmatterMalformed(msg) => {
            assert!(
                msg.contains("mapping"),
                "error must mention mapping requirement: {msg}"
            );
        }
        other => panic!("expected FrontmatterMalformed, got {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// 7. ToolsField — list-of-strings shape parses.
// ---------------------------------------------------------------------------

#[test]
fn t07_tools_field_list_shape() {
    let text = "\
---
name: x
description: d
tools:
  - Read
  - Write
  - Edit
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
body
";
    let (persona, _body) = parse_persona_markdown(text).expect("must parse");
    assert!(matches!(persona.tools, ToolsField::List(_)));
    assert_eq!(persona.tools_list(), vec!["Read", "Write", "Edit"]);
}

// ---------------------------------------------------------------------------
// 8. ToolsField — comma-separated-string shape normalises.
// ---------------------------------------------------------------------------

#[test]
fn t08_tools_field_comma_string_shape_normalises() {
    let text = "\
---
name: x
description: d
tools: \"Read, Write, Edit\"
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
body
";
    let (persona, _body) = parse_persona_markdown(text).expect("must parse");
    assert!(matches!(persona.tools, ToolsField::CommaString(_)));
    assert_eq!(persona.tools_list(), vec!["Read", "Write", "Edit"]);
}

// ---------------------------------------------------------------------------
// 9. PersonaDef::extra — unknown top-level keys preserved.
// ---------------------------------------------------------------------------

#[test]
fn t09_extra_preserves_unknown_keys() {
    let text = "\
---
name: x
description: d
tools: [Read]
schema_version: persona-v1
persona_slug: pengine
capabilities: [rust, yaml-parsing]
domain: engineering
reports_to: cto
unknown_future_key: some-value
another_unknown: 42
identity_pinned:
  cross_review_zones: []
  authority:
    push_remote: false
    budget_cap_eur_per_month: 10
    sub_delegation: false
  hierarchy:
    reports_to: cto
    escalation: cto
---
body
";
    let (persona, _body) = parse_persona_markdown(text).expect("must parse");
    assert_eq!(persona.persona_slug.as_deref(), Some("pengine"));
    assert_eq!(
        persona.capabilities.as_ref().expect("capabilities present"),
        &vec!["rust".to_string(), "yaml-parsing".to_string()]
    );
    assert_eq!(persona.domain.as_deref(), Some("engineering"));
    assert_eq!(persona.reports_to.as_deref(), Some("cto"));
    assert!(
        persona.extra.contains_key("unknown_future_key"),
        "extra must preserve unknown_future_key"
    );
    assert!(
        persona.extra.contains_key("another_unknown"),
        "extra must preserve another_unknown"
    );
    assert_eq!(
        persona.extra.get("another_unknown"),
        Some(&JsonValue::Number(42.into()))
    );
}

// ---------------------------------------------------------------------------
// 10. to_canonical_subset — unsupported schema_version rejected.
// ---------------------------------------------------------------------------

#[test]
fn t10_to_canonical_subset_unsupported_schema_version_rejected() {
    let text = "\
---
name: x
description: d
tools: [Read]
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
body
";
    let (persona, _body) = parse_persona_markdown(text).expect("must parse");
    let err = persona
        .to_canonical_subset()
        .expect_err("persona-v0 must be rejected by canonical-subset extractor");
    match err {
        FrontmatterParserError::InvalidShape(msg) => {
            assert!(msg.contains("persona-v0"), "error must name the version: {msg}");
        }
        other => panic!("expected InvalidShape, got {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// 11. to_canonical_subset — missing identity_pinned rejected.
// ---------------------------------------------------------------------------

#[test]
fn t11_to_canonical_subset_missing_identity_pinned_rejected() {
    let text = "\
---
name: x
description: d
tools: [Read]
schema_version: persona-v1
---
body
";
    let (persona, _body) = parse_persona_markdown(text).expect("must parse");
    assert!(
        persona.identity_pinned.is_none(),
        "typed parser tolerates missing identity_pinned"
    );
    let err = persona
        .to_canonical_subset()
        .expect_err("canonical-subset extractor must require identity_pinned");
    match err {
        FrontmatterParserError::InvalidShape(msg) => {
            assert!(
                msg.contains("identity_pinned"),
                "error must mention identity_pinned: {msg}"
            );
        }
        other => panic!("expected InvalidShape, got {other:?}"),
    }
}

// ---------------------------------------------------------------------------
// 12. CROSS-LANGUAGE ROUND-TRIP — V9 fixture: SHA-256 of JCS bytes of
//     typed `to_canonical_subset` must equal `PERSONA_HASH_PIN_V9`.
//     This binds the typed parser into the V-907 pin pack and proves
//     byte-identical parity with both the Python pipeline and the
//     `persona-canonical-form-yaml` Rust crate.
// ---------------------------------------------------------------------------

#[test]
fn t12_v9_cross_lang_round_trip_python_byte_identical() {
    let (persona, _body) = parse_persona_markdown(V9_FIXTURE).expect("v9 must parse");
    let canon = persona
        .to_canonical_subset()
        .expect("v9 must canonicalise");
    let blob = serde_jcs::to_vec(&canon).expect("v9 must JCS-canonicalise");
    assert_eq!(
        blob.len(),
        V9_JCS_BYTES_LEN,
        "v9 JCS-bytes length must be 387 (Python cross-lang anchor)"
    );
    assert_eq!(
        sha256_hex(&blob),
        V9_PIN_HEX,
        "sha256(jcs_bytes(typed_to_canonical_subset(V9))) must equal V9 pin"
    );
}
