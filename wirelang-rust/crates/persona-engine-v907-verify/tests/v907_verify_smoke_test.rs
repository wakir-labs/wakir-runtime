// SPDX-License-Identifier: Apache-2.0
//! Smoke + cross-language anchor tests for `persona-engine-v907-verify`.
//!
//! Cross-language anchor pins were captured 2026-05-16 via a local
//! Python run of `wirelang.persona_engine.v907_verify.compute_v907_pin`
//! over each fixture. Any drift in JCS canonicalisation, in the
//! engine-side canonical-subset shape, or in the YAML-to-JSON type
//! mapping will break a pin assertion at byte granularity.
//!
//! Mirrors the test pattern of `persona-hash` (workspace sister crate):
//! - ground-truth pin equality
//! - body out-of-hash invariant
//! - front-matter mutation drifts the hash
//! - schema_version default behaviour
//! - verify-success / verify-drift mechanics
//! - empty-expected-pin treated as None (Python parity)

use persona_engine_v907_verify::{
    compute_v907_pin, parse_persona_def, verify_v907_pin, PersonaHashError, VerifyResult,
    PERSONA_HASH_FULL_LENGTH, PERSONA_HASH_PREFIX,
};

// ---------------------------------------------------------------------
// Fixtures + cross-language anchor pins (captured from Python, see
// `tests/README` and the Cargo.toml module comment for the capture
// procedure).
// ---------------------------------------------------------------------

/// SAMPLE_AXIS_A — mirrors the SAMPLE_AXIS_A constant in Python
/// `wirelang/tests/persona_engine/test_v907_verify.py`. The trailing
/// newline structure matches exactly so JCS canonical bytes are
/// byte-identical to the Python compute output.
const SAMPLE_AXIS_A_MIN: &str = "---
name: tomas
description: Sample test persona for V-907 hashing
schema_version: persona-v1
identity_pinned:
  email: tomas@example.com
domain: dev-engineering
---

Body content here.
";

/// Cross-language anchor pin for SAMPLE_AXIS_A_MIN (captured
/// 2026-05-16 via `python3 -c 'compute_v907_pin(SAMPLE_AXIS_A_MIN)'`).
const PIN_AXIS_A_MIN: &str =
    "sha256:cf66fbc5e02ebee97726d5903460e1c3b2b20d1e10db6db1083bceb62ede6e39";

/// Minimal axis-A with no `schema_version` key — engine must default
/// to `persona-v1` per Python `v907_verify.py` lines 161-167.
const SAMPLE_AXIS_A_NO_SCHEMA: &str = "---
name: minimal
description: minimal without schema_version - should default to persona-v1
identity_pinned:
  email: noschema@example.com
---

body
";

/// Cross-language anchor pin for SAMPLE_AXIS_A_NO_SCHEMA.
const PIN_AXIS_A_NO_SCHEMA: &str =
    "sha256:7d010ae80cb5265274633b5ee0f97ff7e91e939d7811af3f491acc34e2e5dc72";

/// Full axis-A with all four optional keys (`identity_pinned`,
/// `capabilities`, `domain`, `reports_to`) populated — exercises the
/// optional-key lift path in `build_canonical_subset`.
const SAMPLE_AXIS_A_CAPS: &str = "---
name: full
description: persona with capabilities + reports_to
schema_version: persona-v1
identity_pinned:
  email: full@example.com
capabilities:
  - read
  - write
domain: dev-engineering
reports_to: cto
---

body
";

/// Cross-language anchor pin for SAMPLE_AXIS_A_CAPS.
const PIN_AXIS_A_CAPS: &str =
    "sha256:a54726d2d39c438b4052e709fcf683caba7b1c34d01b2d59c7a0f9f876e07b8f";

/// SAMPLE_AXIS_A_MIN with the body replaced — must hash IDENTICALLY
/// to PIN_AXIS_A_MIN (body out-of-hash invariant).
const SAMPLE_AXIS_A_BODY_VARIANT: &str = "---
name: tomas
description: Sample test persona for V-907 hashing
schema_version: persona-v1
identity_pinned:
  email: tomas@example.com
domain: dev-engineering
---

TOTALLY DIFFERENT BODY content with more lines

and paragraphs.
";

/// SAMPLE_AXIS_A_MIN with `domain` flipped to a different value — must
/// hash DIFFERENTLY from PIN_AXIS_A_MIN (front-matter is in-hash).
const SAMPLE_AXIS_A_DOMAIN_HR: &str = "---
name: tomas
description: Sample test persona for V-907 hashing
schema_version: persona-v1
identity_pinned:
  email: tomas@example.com
domain: hr
---

Body content here.
";

/// Cross-language anchor pin for SAMPLE_AXIS_A_DOMAIN_HR — used as the
/// hard freeze for the front-matter-mutation drift test (asserts both
/// drift from MIN and equality to the new captured value).
const PIN_AXIS_A_DOMAIN_HR: &str =
    "sha256:72f51e64a410b6368230a200a09f0f3679e858bda59cbb7bb6c02b8d821fc0cb";

// ---------------------------------------------------------------------
// Smoke + anchor tests (≥8 required per spec; this file contains 12).
// ---------------------------------------------------------------------

/// 1 / Ground-truth: SAMPLE_AXIS_A_MIN hashes to the Python-captured
/// pin byte-for-byte. This is the primary cross-language parity
/// anchor; the other anchor tests reuse the same canonicalisation
/// stack and therefore inherit byte-identity once t1 passes.
#[test]
fn t1_sample_axis_a_min_hashes_to_python_anchor_pin() {
    let got = compute_v907_pin(SAMPLE_AXIS_A_MIN).expect("MIN must hash");
    assert_eq!(
        got, PIN_AXIS_A_MIN,
        "Rust engine-side V-907 pin must equal Python cross-lang anchor"
    );
}

/// 2 / Pin is well-formed: prefix + 64-hex-char tail + correct total
/// length. Mirrors Python `test_compute_v907_pin_returns_sha256_prefix`.
#[test]
fn t2_pin_format_is_sha256_colon_64hex() {
    let pin = compute_v907_pin(SAMPLE_AXIS_A_MIN).expect("must hash");
    assert!(
        pin.starts_with(PERSONA_HASH_PREFIX),
        "pin must start with sha256:"
    );
    assert_eq!(
        pin.len(),
        PERSONA_HASH_FULL_LENGTH,
        "pin must be exactly prefix + 64 hex chars long"
    );
    // Hex-tail is lower-case ASCII hex.
    let tail = &pin[PERSONA_HASH_PREFIX.len()..];
    assert!(
        tail.chars()
            .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()),
        "pin hex tail must be lower-case ascii hex"
    );
}

/// 3 / Determinism: re-hashing the same input twice in the same
/// process returns byte-identical pins. Mirrors Python
/// `test_compute_v907_pin_byte_deterministic`.
#[test]
fn t3_pin_is_byte_deterministic_across_repeated_calls() {
    let p1 = compute_v907_pin(SAMPLE_AXIS_A_MIN).expect("first hash");
    let p2 = compute_v907_pin(SAMPLE_AXIS_A_MIN).expect("second hash");
    let p3 = compute_v907_pin(SAMPLE_AXIS_A_MIN).expect("third hash");
    assert_eq!(p1, p2);
    assert_eq!(p2, p3);
}

/// 4 / Body out-of-hash: same front-matter, completely different
/// markdown body. Hash MUST be identical. Mirrors Python
/// `test_compute_v907_pin_body_does_not_affect_hash`.
#[test]
fn t4_body_changes_do_not_affect_hash() {
    let p_min = compute_v907_pin(SAMPLE_AXIS_A_MIN).expect("MIN hash");
    let p_body = compute_v907_pin(SAMPLE_AXIS_A_BODY_VARIANT).expect("body-variant hash");
    assert_eq!(
        p_min, p_body,
        "body edits must NOT change the V-907 pin (body out-of-hash invariant)"
    );
    // Both must equal the cross-lang anchor.
    assert_eq!(p_min, PIN_AXIS_A_MIN);
}

/// 5 / Front-matter mutation drifts the hash AND lands on the
/// Python-captured DOMAIN_HR pin. This combines drift-detection with
/// a second cross-lang anchor — catches a regression where the optional-
/// key lift loop accidentally normalises or drops a recognised key.
#[test]
fn t5_frontmatter_mutation_drifts_and_matches_anchor() {
    let p_min = compute_v907_pin(SAMPLE_AXIS_A_MIN).expect("MIN hash");
    let p_hr = compute_v907_pin(SAMPLE_AXIS_A_DOMAIN_HR).expect("HR hash");
    assert_ne!(p_min, p_hr, "domain change must drift the pin");
    assert_eq!(
        p_hr, PIN_AXIS_A_DOMAIN_HR,
        "DOMAIN_HR pin must match Python cross-lang anchor"
    );
}

/// 6 / Default `schema_version` injection. When the axis-A
/// front-matter omits the key, the engine must inject the
/// `persona-v1` default (Python `v907_verify.py` lines 161-167) so
/// that `.claude/agents/*.md` files which do not carry the key still
/// hash deterministically. Anchored against the Python NO_SCHEMA pin.
#[test]
fn t6_missing_schema_version_defaults_to_persona_v1() {
    let pin = compute_v907_pin(SAMPLE_AXIS_A_NO_SCHEMA).expect("NO_SCHEMA hash");
    assert_eq!(
        pin, PIN_AXIS_A_NO_SCHEMA,
        "missing schema_version must default to persona-v1 (Python parity)"
    );
}

/// 7 / Capabilities + reports_to optional keys. When the front-matter
/// carries the full set of recognised optional keys
/// (`identity_pinned`, `capabilities`, `domain`, `reports_to`), each
/// must be lifted into the canonical subset and the pin must match
/// the Python CAPS anchor.
#[test]
fn t7_capabilities_and_reports_to_are_lifted_into_canonical_subset() {
    let pin = compute_v907_pin(SAMPLE_AXIS_A_CAPS).expect("CAPS hash");
    assert_eq!(
        pin, PIN_AXIS_A_CAPS,
        "full optional-key axis-A must match Python CAPS anchor"
    );
    // And: CAPS pin must differ from MIN pin (different shape).
    assert_ne!(pin, PIN_AXIS_A_MIN);
}

/// 8 / verify_v907_pin success path: parse → verify with the
/// freshly-computed pin → `matched = Some(true)`, mode = "real".
/// Mirrors Python `test_verify_v907_pin_match`.
#[test]
fn t8_verify_v907_pin_match_returns_some_true() {
    let def = parse_persona_def(SAMPLE_AXIS_A_MIN).expect("parse");
    let result =
        verify_v907_pin("tomas", &def, Some(PIN_AXIS_A_MIN)).expect("matching pin must succeed");
    assert_eq!(
        result,
        VerifyResult {
            pin: PIN_AXIS_A_MIN.to_string(),
            mode: "real",
            matched: Some(true),
        }
    );
}

/// 9 / verify_v907_pin drift path: pin mismatch returns
/// `PersonaHashError::Drift` with full context (persona_id, expected,
/// computed). Mirrors Python `test_verify_v907_pin_drift_raises`.
#[test]
fn t9_verify_v907_pin_drift_returns_drift_error_with_context() {
    let def = parse_persona_def(SAMPLE_AXIS_A_MIN).expect("parse");
    let bogus = "sha256:0000000000000000000000000000000000000000000000000000000000000000";
    let err = verify_v907_pin("tomas", &def, Some(bogus)).expect_err("drift must error");
    match err {
        PersonaHashError::Drift {
            persona_id,
            expected,
            computed,
        } => {
            assert_eq!(persona_id, "tomas", "drift error must carry persona_id");
            assert_eq!(expected, bogus, "drift error must carry verbatim expected");
            assert_eq!(
                computed, PIN_AXIS_A_MIN,
                "drift error must carry the freshly-computed pin"
            );
        }
        other => panic!("expected Drift, got {other:?}"),
    }
}

/// 10 / verify_v907_pin without expected pin: `matched = None`,
/// mode = "real". Mirrors Python
/// `test_verify_v907_pin_no_expected_returns_unmatched_none`.
#[test]
fn t10_verify_v907_pin_no_expected_returns_matched_none() {
    let def = parse_persona_def(SAMPLE_AXIS_A_MIN).expect("parse");
    let result = verify_v907_pin("tomas", &def, None).expect("no-expected must succeed");
    assert_eq!(result.matched, None);
    assert_eq!(result.mode, "real");
    assert_eq!(result.pin, PIN_AXIS_A_MIN);
}

/// 11 / verify_v907_pin with empty / whitespace-only expected: treated
/// as None per Python `if expected_pin is not None and
/// expected_pin.strip()`. Mirrors Python
/// `test_verify_v907_pin_empty_expected_treated_as_none`.
#[test]
fn t11_verify_v907_pin_empty_or_whitespace_expected_treated_as_none() {
    let def = parse_persona_def(SAMPLE_AXIS_A_MIN).expect("parse");
    for empty in ["", "   ", "\t", "\n"] {
        let result = verify_v907_pin("tomas", &def, Some(empty))
            .unwrap_or_else(|e| panic!("empty {empty:?} must succeed: {e}"));
        assert_eq!(
            result.matched, None,
            "empty/whitespace expected pin {empty:?} must be treated as None"
        );
    }
}

/// 12 / Engine-side pin is byte-distinct from a hypothetical
/// stub-mode hash (sha256 of raw markdown bytes). The Python
/// `v907_verify.py` source explicitly contrasts the real-mode and
/// stub-mode pin shapes; this test locks the byte-distinctness on
/// the Rust side so a future merge of a "raw-bytes" code-path can
/// never silently produce a colliding pin. Mirrors Python
/// `test_compute_v907_pin_distinct_from_stub_format`.
#[test]
fn t12_engine_pin_is_distinct_from_raw_markdown_sha256() {
    use sha2::{Digest, Sha256};
    let pin = compute_v907_pin(SAMPLE_AXIS_A_MIN).expect("MIN hash");
    let mut hasher = Sha256::new();
    hasher.update(SAMPLE_AXIS_A_MIN.as_bytes());
    let raw_digest = hasher.finalize();
    let raw_pin = format!("{PERSONA_HASH_PREFIX}{}", hex::encode(raw_digest));
    assert_ne!(
        pin, raw_pin,
        "real-mode V-907 pin must NOT equal sha256(raw markdown bytes)"
    );
}
