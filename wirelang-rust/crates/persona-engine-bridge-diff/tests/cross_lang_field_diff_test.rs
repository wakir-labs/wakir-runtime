// SPDX-License-Identifier: Apache-2.0
//! Cross-language Field-Level Diff parity tests against Python pins.
//!
//! Tag-17 Mini-Welle, Phase-3a-Python-Sync-Erweiterung — sister to the
//! Python-side cross-language test ``wirelang/tests/persona_engine/
//! test_bridge_diff_field_level_parity.py``.
//!
//! What this exercises
//! -------------------
//!
//! The Python-side test emits a static fixture file
//! ``tests/cross_lang_field_diff_fixtures.json`` (this directory)
//! holding a frozen pin-table of ``(envelope_a, envelope_b)`` pairs
//! together with the EXACT expected ``diff_envelopes()`` output for
//! each pair: an ordered list of ``(path, kind, value_a, value_b)``
//! tuples sorted by path. This test loads that file and asserts that
//! the Rust ``persona_engine_bridge_diff::diff_envelopes()`` produces
//! the same output entry-for-entry.
//!
//! It is the per-field-level-diff cross-language pin set sister to
//! the JCS-hash cross-language pins already frozen in
//! ``bridge_diff_smoke_test.rs`` (t1 / t2).
//!
//! Coverage
//! --------
//!
//! 6 pins, exercising:
//!
//! - Pin-0: identical records (baseline: empty diff, byte_identical=true).
//! - Pin-1: nested-object value drift at ``/a/b/c``.
//! - Pin-2: array with index-pinning, middle-element drift.
//! - Pin-3: null-vs-missing distinction (``None`` value vs absent key).
//! - Pin-4: empty-array vs absent-key.
//! - Pin-5: RFC-6901 escapes (``~`` -> ``~0``, ``/`` -> ``~1``) plus
//!   multi-field drift; tests the sort-by-path ordering.
//!
//! Drift surface
//! -------------
//!
//! Any drift in the Rust walker (path emission, sort order, DiffKind
//! alphabet, RFC-6901 escape sequence), the JCS canonicaliser, or the
//! SHA-256 hash surfaces as a fixture-mismatch failure here. If the
//! Python pin-table is intentionally updated, the Python emitter test
//! rewrites this JSON file and the developer commits both sides
//! together.

use persona_engine_bridge_diff::{diff_envelopes, jcs_hash, DiffKind};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

// ---------------------------------------------------------------------------
// Fixture loader
// ---------------------------------------------------------------------------

fn fixture_path() -> PathBuf {
    let manifest_dir =
        std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR set by cargo at test time");
    PathBuf::from(manifest_dir).join("tests/cross_lang_field_diff_fixtures.json")
}

fn load_fixtures() -> Value {
    let p = fixture_path();
    let body = fs::read_to_string(&p).unwrap_or_else(|e| {
        panic!(
            "failed to read cross-lang fixture file at {}: {e}; \
             run the Python emitter test \
             `pytest wirelang/tests/persona_engine/test_bridge_diff_field_level_parity.py`",
            p.display()
        )
    });
    serde_json::from_str(&body).expect("fixture file MUST parse as JSON")
}

fn diffkind_from_str(s: &str) -> DiffKind {
    match s {
        "value-mismatch" => DiffKind::ValueMismatch,
        "only-in-a" => DiffKind::OnlyInA,
        "only-in-b" => DiffKind::OnlyInB,
        "type-mismatch" => DiffKind::TypeMismatch,
        other => panic!(
            "unknown DiffKind string {other:?} in fixture file; \
             alphabet drift between Python and Rust?"
        ),
    }
}

// ---------------------------------------------------------------------------
// 1 / format_version is the one we know.
// ---------------------------------------------------------------------------

#[test]
fn t1_fixture_format_version_is_one() {
    let fx = load_fixtures();
    let v = fx["format_version"].as_u64().expect("format_version u64");
    assert_eq!(
        v, 1,
        "fixture format_version drifted; update this test if you change the schema"
    );
    let pins = fx["pins"].as_array().expect("pins array");
    assert_eq!(
        pins.len(),
        6,
        "expected exactly 6 cross-lang pins (pin-0 baseline + pin-1..5 field-level)"
    );
}

// ---------------------------------------------------------------------------
// 2 / Each pin's diff output matches the Rust walker entry-for-entry.
// ---------------------------------------------------------------------------

#[test]
fn t2_each_pin_diff_output_matches_python_pin() {
    let fx = load_fixtures();
    let pins = fx["pins"].as_array().expect("pins array");
    for pin in pins {
        let pin_id = pin["pin_id"].as_str().expect("pin_id string").to_string();
        let envelope_a = pin["envelope_a"].clone();
        let envelope_b = pin["envelope_b"].clone();
        let expected = pin["expected_diff_entries"]
            .as_array()
            .expect("expected_diff_entries array");

        let got = diff_envelopes(&envelope_a, &envelope_b);

        assert_eq!(
            got.len(),
            expected.len(),
            "{pin_id}: drift count mismatch (Rust got {}, Python pinned {})",
            got.len(),
            expected.len(),
        );

        for (i, (g, w)) in got.iter().zip(expected.iter()).enumerate() {
            let want_path = w["path"].as_str().expect("path string").to_string();
            let want_kind = w["kind"].as_str().expect("kind string").to_string();
            let want_kind_enum = diffkind_from_str(&want_kind);
            assert_eq!(
                g.path, want_path,
                "{pin_id} entry {i}: path drift (got {:?}, expected {:?})",
                g.path, want_path,
            );
            assert_eq!(
                g.kind,
                want_kind_enum,
                "{pin_id} entry {i}: kind drift (got {:?}, expected {:?})",
                g.kind.as_str(),
                want_kind,
            );
            assert_eq!(g.value_a, w["value_a"], "{pin_id} entry {i}: value_a drift",);
            assert_eq!(g.value_b, w["value_b"], "{pin_id} entry {i}: value_b drift",);
        }
    }
}

// ---------------------------------------------------------------------------
// 3 / JCS hashes match the Python pin for each fixture envelope.
// ---------------------------------------------------------------------------

#[test]
fn t3_jcs_hashes_match_python_pins() {
    let fx = load_fixtures();
    let pins = fx["pins"].as_array().expect("pins array");
    for pin in pins {
        let pin_id = pin["pin_id"].as_str().unwrap().to_string();
        let envelope_a = pin["envelope_a"].clone();
        let envelope_b = pin["envelope_b"].clone();
        let want_hash_a = pin["expected_hash_a"].as_str().unwrap().to_string();
        let want_hash_b = pin["expected_hash_b"].as_str().unwrap().to_string();
        let want_byte_identical = pin["byte_identical"].as_bool().unwrap();

        let got_hash_a = jcs_hash(&envelope_a).expect("hash a");
        let got_hash_b = jcs_hash(&envelope_b).expect("hash b");

        assert_eq!(
            got_hash_a, want_hash_a,
            "{pin_id}: hash_a drift (Rust got {got_hash_a}, Python pinned {want_hash_a})",
        );
        assert_eq!(
            got_hash_b, want_hash_b,
            "{pin_id}: hash_b drift (Rust got {got_hash_b}, Python pinned {want_hash_b})",
        );
        assert_eq!(
            got_hash_a == got_hash_b,
            want_byte_identical,
            "{pin_id}: byte_identical flag mismatch",
        );
    }
}

// ---------------------------------------------------------------------------
// 4 / Sort order is lexicographic by path across every pin.
// ---------------------------------------------------------------------------

#[test]
fn t4_diff_entries_sorted_by_path_lexicographically() {
    let fx = load_fixtures();
    let pins = fx["pins"].as_array().expect("pins array");
    for pin in pins {
        let pin_id = pin["pin_id"].as_str().unwrap().to_string();
        let envelope_a = pin["envelope_a"].clone();
        let envelope_b = pin["envelope_b"].clone();
        let diffs = diff_envelopes(&envelope_a, &envelope_b);
        let paths: Vec<&str> = diffs.iter().map(|d| d.path.as_str()).collect();
        let mut sorted = paths.clone();
        sorted.sort();
        assert_eq!(
            paths, sorted,
            "{pin_id}: paths not lexicographically sorted: {paths:?}"
        );
    }
}

// ---------------------------------------------------------------------------
// 5 / The DiffKind alphabet exposed by the fixture matches our enum.
// ---------------------------------------------------------------------------

#[test]
fn t5_diffkind_alphabet_round_trip() {
    // Sanity: every DiffKind variant produces a stable string the
    // fixture loader can parse back.
    for k in [
        DiffKind::ValueMismatch,
        DiffKind::OnlyInA,
        DiffKind::OnlyInB,
        DiffKind::TypeMismatch,
    ] {
        let s = k.as_str();
        let parsed = diffkind_from_str(s);
        assert_eq!(
            parsed, k,
            "DiffKind round-trip drift: {s:?} re-parsed to a different variant"
        );
    }
}

// ---------------------------------------------------------------------------
// 6 / Pin-by-pin coverage anchor (so a future drop of one pin in the
//      JSON file surfaces here as a "missing pin_id" failure rather
//      than silently weakening the gate).
// ---------------------------------------------------------------------------

#[test]
fn t6_all_expected_pin_ids_present() {
    let fx = load_fixtures();
    let pins = fx["pins"].as_array().expect("pins array");
    let got_ids: Vec<String> = pins
        .iter()
        .map(|p| p["pin_id"].as_str().unwrap().to_string())
        .collect();

    for expected in [
        "pin-0-identical",
        "pin-1-nested-value-drift",
        "pin-2-array-index-middle-drift",
        "pin-3-null-vs-missing",
        "pin-4-empty-vs-absent",
        "pin-5-rfc6901-escapes-plus-multi-field",
    ] {
        assert!(
            got_ids.iter().any(|s| s == expected),
            "missing expected cross-lang pin {expected:?}; got {got_ids:?}"
        );
    }
}

// ---------------------------------------------------------------------------
// 7 / Pin-0 short-circuit: identical envelopes produce empty diff AND
//      byte-identical hash.
// ---------------------------------------------------------------------------

#[test]
fn t7_pin0_identical_records_empty_diff_byte_identical() {
    let fx = load_fixtures();
    let pin = fx["pins"]
        .as_array()
        .unwrap()
        .iter()
        .find(|p| p["pin_id"] == "pin-0-identical")
        .expect("pin-0 present");

    let envelope_a = pin["envelope_a"].clone();
    let envelope_b = pin["envelope_b"].clone();
    let diffs = diff_envelopes(&envelope_a, &envelope_b);
    assert!(diffs.is_empty(), "pin-0 must produce empty diff");
    let h_a = jcs_hash(&envelope_a).unwrap();
    let h_b = jcs_hash(&envelope_b).unwrap();
    assert_eq!(h_a, h_b, "pin-0 must be byte-identical");
}

// ---------------------------------------------------------------------------
// 8 / Pin-3 / Pin-4 null-vs-missing and empty-vs-absent are surfaced
//      with the SAME DiffKind (only-in-a) so operators see a uniform
//      surfacing alphabet for "present on one side only".
// ---------------------------------------------------------------------------

#[test]
fn t8_pin3_and_pin4_use_only_in_a_uniformly() {
    let fx = load_fixtures();
    for pin_id in ["pin-3-null-vs-missing", "pin-4-empty-vs-absent"] {
        let pin = fx["pins"]
            .as_array()
            .unwrap()
            .iter()
            .find(|p| p["pin_id"] == pin_id)
            .unwrap_or_else(|| panic!("{pin_id} present"));
        let envelope_a = pin["envelope_a"].clone();
        let envelope_b = pin["envelope_b"].clone();
        let diffs = diff_envelopes(&envelope_a, &envelope_b);
        assert_eq!(diffs.len(), 1, "{pin_id}: expected exactly one drift entry");
        assert_eq!(
            diffs[0].kind,
            DiffKind::OnlyInA,
            "{pin_id}: must surface as only-in-a (uniform surfacing alphabet)"
        );
    }
}

// ---------------------------------------------------------------------------
// 9 / Pin-5 RFC-6901 escapes: `~` -> `~0` before `/` -> `~1`.
// ---------------------------------------------------------------------------

#[test]
fn t9_pin5_rfc6901_escape_order() {
    let fx = load_fixtures();
    let pin = fx["pins"]
        .as_array()
        .unwrap()
        .iter()
        .find(|p| p["pin_id"] == "pin-5-rfc6901-escapes-plus-multi-field")
        .expect("pin-5 present");
    let envelope_a = pin["envelope_a"].clone();
    let envelope_b = pin["envelope_b"].clone();
    let diffs = diff_envelopes(&envelope_a, &envelope_b);
    assert_eq!(diffs.len(), 2, "pin-5 must surface two drift entries");

    // Sorted by path lexicographically: "/normal" < "/p~0q/a~1b/1".
    assert_eq!(diffs[0].path, "/normal");
    assert_eq!(
        diffs[1].path, "/p~0q/a~1b/1",
        "RFC-6901: `~` -> `~0` AND `/` -> `~1` in object keys"
    );
}

// ---------------------------------------------------------------------------
// 10 / Pin-2 array index-pinning: middle-element drift surfaces at
//       `/items/1/id`, not at the array root.
// ---------------------------------------------------------------------------

#[test]
fn t10_pin2_array_index_pinning_middle_drift() {
    let fx = load_fixtures();
    let pin = fx["pins"]
        .as_array()
        .unwrap()
        .iter()
        .find(|p| p["pin_id"] == "pin-2-array-index-middle-drift")
        .expect("pin-2 present");
    let envelope_a = pin["envelope_a"].clone();
    let envelope_b = pin["envelope_b"].clone();
    let diffs = diff_envelopes(&envelope_a, &envelope_b);
    assert_eq!(diffs.len(), 1, "pin-2 must surface one drift entry");
    assert_eq!(
        diffs[0].path, "/items/1/id",
        "array index-pinning: drift in element[1].id must surface at /items/1/id"
    );
    assert_eq!(diffs[0].kind, DiffKind::ValueMismatch);
}
