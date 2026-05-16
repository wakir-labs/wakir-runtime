// SPDX-License-Identifier: Apache-2.0
//! Bridge-Diff-Engine smoke-tests with cross-language anchor pins.
//!
//! Sprint-Bridge-Diff-Engine-Rust-MINI smoke suite. Each cross-language
//! pin in this file was captured on 2026-05-16 from the Python pendant
//! (`wirelang/persona_engine/bridge_audit_diff_engine.py`, PR #106)
//! running against the SAME fixture in the same source tree. A future
//! drift in the Rust serde_jcs / serde_json / sha2 stack — or in the
//! Python rfc8785 / hashlib stack — surfaces as a test failure here.
//!
//! Coverage matrix:
//!
//! 1.  Empty envelope `{}` -> frozen sha256 pin (cross-lang anchor).
//! 2.  CloudEvent envelope (306 JCS bytes) -> frozen sha256 pin.
//! 3.  JCS field-order invariance: same envelope, keys inserted in
//!     forward and reverse order -> identical hash.
//! 4.  Single-field value drift: `value-mismatch`, RFC-6901 path,
//!     consistency_score == 10/11.
//! 5.  Only-in-A / only-in-B branches: total drift, score 0.0.
//! 6.  Array element drift: index-token path `/arr/2`.
//! 7.  Array length mismatch: `only-in-b` at tail index.
//! 8.  RFC-6901 escape rules: `~` -> `~0`, `/` -> `~1` in object keys.
//! 9.  TYPE_MISMATCH branch: serde_json int (`1`) vs float (`1.0`).
//! 10. Byte-identical fast-path through `compare_implementations`.
//! 11. Drift surfaced through `compare_implementations` (closure adapters).
//! 12. consistency_score corner cases: identical (1.0), total-drift (0.0),
//!     mid-range (0.5).
//! 13. summary() formatting parity with the Python `.summary()`.

use persona_engine_bridge_diff::{
    canonicalize_envelope, compare_implementations, consistency_score, diff_envelopes, jcs_hash,
    DiffInput, DiffKind, FieldDiff,
};
use serde_json::{json, Value};

// ---------------------------------------------------------------------------
// Cross-language anchor pins (captured 2026-05-16 from Python jcs_hash)
// ---------------------------------------------------------------------------

/// Python anchor: `jcs_hash({})` on 2026-05-16.
const EMPTY_ENVELOPE_PIN: &str =
    "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a";

/// Python anchor: `jcs_hash(F2_ENVELOPE)` on 2026-05-16. The fixture
/// is a CloudEvent-shaped envelope with a 5-field `data` payload;
/// the JCS bytes total 306.
const F2_ENVELOPE_PIN: &str =
    "sha256:8c8acdc31862de3c051a054d8f3688096ff05636ea3d8af1f33e98a1b592e608";

/// Length of `canonicalize_envelope(F2_ENVELOPE)` in bytes — pinned
/// against Python `len(canonicalize_envelope(env2))` = 306.
const F2_ENVELOPE_JCS_LEN: usize = 306;

/// Length of `canonicalize_envelope({})` in bytes — Python gives `{}`
/// = 2 bytes.
const EMPTY_ENVELOPE_JCS_LEN: usize = 2;

fn f2_envelope() -> Value {
    json!({
        "specversion": "1.0",
        "type": "wakir.persona.tool_call",
        "source": "/wakir/persona-engine/v1",
        "id": "evt-001",
        "time": "2026-05-16T20:00:00Z",
        "datacontenttype": "application/json",
        "data": {
            "persona_id": "mira",
            "session_id": "sess-abc",
            "step_index": 0,
            "output_kind": "tool_call",
            "output_payload_sha256": "sha256:abc123"
        }
    })
}

/// Same logical content as `f2_envelope()` but every key inserted in
/// reverse order. JCS canonicalisation must be insertion-order
/// invariant -> the hash MUST equal `F2_ENVELOPE_PIN`.
fn f2_envelope_reordered() -> Value {
    json!({
        "data": {
            "output_payload_sha256": "sha256:abc123",
            "output_kind": "tool_call",
            "step_index": 0,
            "session_id": "sess-abc",
            "persona_id": "mira"
        },
        "datacontenttype": "application/json",
        "time": "2026-05-16T20:00:00Z",
        "id": "evt-001",
        "source": "/wakir/persona-engine/v1",
        "type": "wakir.persona.tool_call",
        "specversion": "1.0"
    })
}

fn dummy_input() -> DiffInput {
    DiffInput {
        org_id: "wakir-labs".to_string(),
        persona_id: "mira".to_string(),
        session_id: "sess-abc".to_string(),
        step_index: 0,
        output_kind: "tool_call".to_string(),
        payload: b"hello".to_vec(),
        ts_utc: "2026-05-16T20:00:00Z".to_string(),
    }
}

// ---------------------------------------------------------------------------
// 1 / Empty envelope cross-lang anchor.
// ---------------------------------------------------------------------------

#[test]
fn t1_empty_envelope_matches_python_pin() {
    let env = json!({});
    let bytes = canonicalize_envelope(&env).expect("empty envelope canonicalises");
    assert_eq!(
        bytes.len(),
        EMPTY_ENVELOPE_JCS_LEN,
        "empty-envelope JCS bytes must be `{{}}` = 2 bytes (Python parity)"
    );
    assert_eq!(bytes, b"{}", "JCS empty-object must be the literal `{{}}`");
    let h = jcs_hash(&env).expect("empty envelope hashes");
    assert_eq!(
        h, EMPTY_ENVELOPE_PIN,
        "Rust jcs_hash({{}}) must match Python jcs_hash({{}}) byte-for-byte"
    );
}

// ---------------------------------------------------------------------------
// 2 / 306-byte CloudEvent envelope cross-lang anchor.
// ---------------------------------------------------------------------------

#[test]
fn t2_cloudevent_envelope_matches_python_pin_byte_for_byte() {
    let env = f2_envelope();
    let bytes = canonicalize_envelope(&env).expect("f2 envelope canonicalises");
    assert_eq!(
        bytes.len(),
        F2_ENVELOPE_JCS_LEN,
        "F2 envelope JCS byte length must match Python (306)"
    );
    let h = jcs_hash(&env).expect("f2 envelope hashes");
    assert_eq!(
        h, F2_ENVELOPE_PIN,
        "Rust jcs_hash(f2) must match Python jcs_hash(f2) byte-for-byte"
    );
}

// ---------------------------------------------------------------------------
// 3 / JCS field-order invariance: forward vs reverse insertion order.
// ---------------------------------------------------------------------------

#[test]
fn t3_jcs_field_order_invariance() {
    let h_fwd = jcs_hash(&f2_envelope()).expect("forward hashes");
    let h_rev = jcs_hash(&f2_envelope_reordered()).expect("reverse hashes");
    assert_eq!(
        h_fwd, h_rev,
        "JCS must be insertion-order invariant (cross-lang anchor)"
    );
    assert_eq!(h_fwd, F2_ENVELOPE_PIN);
}

// ---------------------------------------------------------------------------
// 4 / Single-field value drift inside nested `data` object.
//      RFC-6901 path: `/data/output_payload_sha256`.
//      consistency_score == 10/11 (10 unchanged leaves out of 11 total).
// ---------------------------------------------------------------------------

#[test]
fn t4_value_mismatch_rfc6901_path_and_score() {
    let mut env_b = f2_envelope();
    env_b["data"]["output_payload_sha256"] = json!("sha256:def456");

    let diffs = diff_envelopes(&f2_envelope(), &env_b);
    assert_eq!(diffs.len(), 1, "single field changed -> one diff entry");
    let d = &diffs[0];
    assert_eq!(
        d.path, "/data/output_payload_sha256",
        "path must be RFC-6901 JSON-Pointer to the changed leaf"
    );
    assert_eq!(d.kind, DiffKind::ValueMismatch);
    assert_eq!(d.value_a, json!("sha256:abc123"));
    assert_eq!(d.value_b, json!("sha256:def456"));

    // 11 leaves total (6 top-level scalars + 5 data scalars). One drifted.
    // Python pin: 0.9090909090909091.
    let score = consistency_score(&f2_envelope(), &env_b, &diffs);
    let expected = 10.0 / 11.0;
    assert!(
        (score - expected).abs() < 1e-12,
        "score {score} must equal 10/11 = {expected} (Python parity)"
    );
}

// ---------------------------------------------------------------------------
// 5 / Only-in-A / Only-in-B + total-drift score 0.0.
// ---------------------------------------------------------------------------

#[test]
fn t5_only_in_a_and_only_in_b_total_drift() {
    let a = json!({"a": 1, "b": 2});
    let b = json!({"a": 1, "c": 3});
    let diffs = diff_envelopes(&a, &b);
    assert_eq!(
        diffs.len(),
        2,
        "two drift entries (b only-in-a, c only-in-b)"
    );

    // Sorted by path: "/b" then "/c".
    assert_eq!(diffs[0].path, "/b");
    assert_eq!(diffs[0].kind, DiffKind::OnlyInA);
    assert_eq!(diffs[0].value_a, json!(2));
    assert_eq!(diffs[0].value_b, Value::Null);

    assert_eq!(diffs[1].path, "/c");
    assert_eq!(diffs[1].kind, DiffKind::OnlyInB);
    assert_eq!(diffs[1].value_a, Value::Null);
    assert_eq!(diffs[1].value_b, json!(3));

    // total_leaves = max(2, 2) = 2; drifted = 2; score = 0.0.
    let score = consistency_score(&a, &b, &diffs);
    assert_eq!(
        score, 0.0,
        "drifted >= total_leaves -> score floors at 0.0 (Python parity)"
    );
}

// ---------------------------------------------------------------------------
// 6 / Array element drift: index-token path `/arr/2`.
//      consistency_score = 2/3 (Python parity).
// ---------------------------------------------------------------------------

#[test]
fn t6_array_element_drift_index_token_path() {
    let a = json!({"arr": [1, 2, 3]});
    let b = json!({"arr": [1, 2, 4]});
    let diffs = diff_envelopes(&a, &b);
    assert_eq!(diffs.len(), 1);
    assert_eq!(diffs[0].path, "/arr/2");
    assert_eq!(diffs[0].kind, DiffKind::ValueMismatch);
    assert_eq!(diffs[0].value_a, json!(3));
    assert_eq!(diffs[0].value_b, json!(4));

    let score = consistency_score(&a, &b, &diffs);
    let expected = 2.0 / 3.0;
    assert!(
        (score - expected).abs() < 1e-12,
        "score {score} must equal 2/3 = {expected}"
    );
}

// ---------------------------------------------------------------------------
// 7 / Array length mismatch -> `only-in-b` at tail index.
// ---------------------------------------------------------------------------

#[test]
fn t7_array_length_mismatch_tail_only_in_b() {
    let a = json!({"arr": [1, 2, 3]});
    let b = json!({"arr": [1, 2, 3, 4]});
    let diffs = diff_envelopes(&a, &b);
    assert_eq!(diffs.len(), 1);
    assert_eq!(diffs[0].path, "/arr/3");
    assert_eq!(diffs[0].kind, DiffKind::OnlyInB);
    assert_eq!(diffs[0].value_a, Value::Null);
    assert_eq!(diffs[0].value_b, json!(4));
}

// ---------------------------------------------------------------------------
// 8 / RFC-6901 escape rules: `~` -> `~0`, `/` -> `~1` in object keys.
//      Order matters: `~` MUST be escaped first.
// ---------------------------------------------------------------------------

#[test]
fn t8_rfc6901_token_escaping_in_object_keys() {
    let a = json!({"a/b": 1, "c~d": 2});
    let b = json!({"a/b": 99, "c~d": 88});
    let diffs = diff_envelopes(&a, &b);
    assert_eq!(diffs.len(), 2);
    // Sorted by path: "/a~1b" then "/c~0d".
    assert_eq!(diffs[0].path, "/a~1b", "`/` in key must be escaped to `~1`");
    assert_eq!(diffs[1].path, "/c~0d", "`~` in key must be escaped to `~0`");
}

// ---------------------------------------------------------------------------
// 9 / TYPE_MISMATCH branch: serde_json::Number int vs float at same path.
//      serde_json::Value treats Number(1) == Number(1.0) as PartialEq-true;
//      we override that to emit a TYPE_MISMATCH so operators see the
//      implementation-side type drift.
// ---------------------------------------------------------------------------

#[test]
fn t9_type_mismatch_int_vs_float_same_value() {
    let a = json!({"n": 1});
    let b = json!({"n": 1.0});
    let diffs = diff_envelopes(&a, &b);
    assert_eq!(
        diffs.len(),
        1,
        "int-vs-float at same value MUST surface as TYPE_MISMATCH"
    );
    assert_eq!(diffs[0].path, "/n");
    assert_eq!(diffs[0].kind, DiffKind::TypeMismatch);
}

// ---------------------------------------------------------------------------
// 10 / compare_implementations fast-path: byte_identical = true.
// ---------------------------------------------------------------------------

#[test]
fn t10_compare_implementations_byte_identical_fast_path() {
    let impl_a = |_input: &DiffInput| -> Value { f2_envelope() };
    let impl_b = |_input: &DiffInput| -> Value { f2_envelope_reordered() };

    let report = compare_implementations(&dummy_input(), &impl_a, &impl_b)
        .expect("compare_implementations succeeds on byte-identical envelopes");
    assert!(
        report.byte_identical,
        "JCS-equal envelopes -> byte_identical"
    );
    assert_eq!(report.jcs_hash_a, F2_ENVELOPE_PIN);
    assert_eq!(report.jcs_hash_b, F2_ENVELOPE_PIN);
    assert!(
        report.field_diffs.is_empty(),
        "no drift entries on fast path"
    );
    assert!(
        (report.consistency_score - 1.0).abs() < 1e-12,
        "byte-identical -> consistency_score = 1.0"
    );
    assert!(!report.has_drift());
}

// ---------------------------------------------------------------------------
// 11 / compare_implementations drift path through closure adapters.
// ---------------------------------------------------------------------------

#[test]
fn t11_compare_implementations_drift_path_through_closures() {
    let impl_a = |_input: &DiffInput| -> Value { f2_envelope() };
    let impl_b = |_input: &DiffInput| -> Value {
        let mut env = f2_envelope();
        env["data"]["output_payload_sha256"] = json!("sha256:def456");
        env
    };

    let report = compare_implementations(&dummy_input(), &impl_a, &impl_b)
        .expect("compare_implementations succeeds on drifting envelopes");
    assert!(report.has_drift(), "envelopes diverge -> has_drift");
    assert_eq!(report.field_diffs.len(), 1);
    assert_eq!(
        report.field_diffs[0].path, "/data/output_payload_sha256",
        "drift path must be the RFC-6901 JSON-Pointer to the drifted leaf"
    );
    assert_eq!(report.field_diffs[0].kind, DiffKind::ValueMismatch);
    assert_ne!(
        report.jcs_hash_a, report.jcs_hash_b,
        "diverging envelopes -> different jcs hashes"
    );
}

// ---------------------------------------------------------------------------
// 12 / consistency_score corner cases: 1.0 / 0.0 / 0.5.
// ---------------------------------------------------------------------------

#[test]
fn t12_consistency_score_corner_cases() {
    // 12.a — identical envelopes -> 1.0
    let a = json!({"x": 1});
    let diffs = diff_envelopes(&a, &a);
    assert!(diffs.is_empty(), "identical envelopes -> no diffs");
    assert_eq!(consistency_score(&a, &a, &diffs), 1.0);

    // 12.b — disjoint envelopes -> 0.0
    let a = json!({"x": 1});
    let b = json!({"y": 2});
    let diffs = diff_envelopes(&a, &b);
    assert_eq!(diffs.len(), 2);
    assert_eq!(consistency_score(&a, &b, &diffs), 0.0);

    // 12.c — exactly half-drift -> 0.5 (1 drifted of 2 leaves)
    let a = json!({"x": 1, "y": 2});
    let b = json!({"x": 1, "y": 99});
    let diffs = diff_envelopes(&a, &b);
    assert_eq!(diffs.len(), 1);
    let score = consistency_score(&a, &b, &diffs);
    assert!(
        (score - 0.5).abs() < 1e-12,
        "1 drifted of 2 leaves -> score = 0.5 (got {score})"
    );
}

// ---------------------------------------------------------------------------
// 13 / summary() output shape — operator-readable, Python-parity wording.
// ---------------------------------------------------------------------------

#[test]
fn t13_summary_format_parity() {
    // 13.a — byte-identical summary
    let impl_a = |_input: &DiffInput| -> Value { f2_envelope() };
    let report =
        compare_implementations(&dummy_input(), &impl_a, &impl_a).expect("byte-identical compare");
    let s = report.summary();
    assert!(s.starts_with("byte-identical jcs=sha256:"), "got: {s}");
    assert!(s.contains("score=1.0000"), "got: {s}");

    // 13.b — drift summary
    let impl_b = |_input: &DiffInput| -> Value {
        let mut env = f2_envelope();
        env["data"]["output_payload_sha256"] = json!("sha256:def456");
        env
    };
    let report = compare_implementations(&dummy_input(), &impl_a, &impl_b).expect("drift compare");
    let s = report.summary();
    assert!(s.starts_with("drift fields=1 "), "got: {s}");
    assert!(s.contains("hash_a=sha256:"), "got: {s}");
    assert!(s.contains("hash_b=sha256:"), "got: {s}");
}

// ---------------------------------------------------------------------------
// 14 / DiffKind.as_str() string-values match the Python enum `.value`.
// ---------------------------------------------------------------------------

#[test]
fn t14_diffkind_as_str_python_enum_parity() {
    assert_eq!(DiffKind::ValueMismatch.as_str(), "value-mismatch");
    assert_eq!(DiffKind::OnlyInA.as_str(), "only-in-a");
    assert_eq!(DiffKind::OnlyInB.as_str(), "only-in-b");
    assert_eq!(DiffKind::TypeMismatch.as_str(), "type-mismatch");
}

// ---------------------------------------------------------------------------
// 15 / FieldDiff struct surface — operator can construct/compare entries
//      directly (smoke for the public API shape).
// ---------------------------------------------------------------------------

#[test]
fn t15_field_diff_public_struct_surface() {
    let fd = FieldDiff {
        path: "/foo".to_string(),
        kind: DiffKind::ValueMismatch,
        value_a: json!("a"),
        value_b: json!("b"),
    };
    assert_eq!(fd.path, "/foo");
    assert_eq!(fd.kind, DiffKind::ValueMismatch);
    assert_eq!(fd.value_a, json!("a"));
    assert_eq!(fd.value_b, json!("b"));
}
