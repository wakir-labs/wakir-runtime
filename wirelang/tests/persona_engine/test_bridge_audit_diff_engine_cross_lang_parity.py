# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang parity tests for the persona-engine bridge-audit-diff-engine
canonical-trace (Tag-36 Mini-Welle Phase-3a Python-sync, 13. Modul).

This file is the Python half of the cross-lang fixture pin pair.  The
Rust half lives at
``wirelang-rust/crates/persona-engine-bridge-diff/tests/cross_lang_diff_trace_fixture_test.rs``
and consumes the same authoritative fixture file at
``tests/fixtures/bridge-audit-diff-engine-cross-lang/fixtures.json``.

Test taxonomy
-------------

- T01 — Constants pin: ``BRIDGE_DIFF_TRACE_SCHEMA`` / ``HASH_PREFIX`` /
  ``SHA256_HEX_LEN`` / summary separators / DiffKind alphabet match
  the Rust crate's ``pub const`` items.
- T02 — Determinism: two trace builds of the same envelope pair produce
  byte-identical canonical output.
- T03 — Wire-shape key order: top-level JCS keys are in alphabetical
  order (the cross-lang contract); 8 keys expected.
- T04 — Hash shape: prefixed-form is ``"sha256:" + 64 lowercase hex``;
  bare hex is exactly 64 lowercase hex characters.
- T05 — Cross-lang fixture file structure: schema_version, fixture
  count (6), and per-fixture key set match the Rust sibling's
  structure pin.
- T06 — Cross-lang fixture per-vector pin (parametrised over all six
  fixtures): byte-for-byte parity with the JSON fixture file's
  pinned values (this is the core trace-hash byte-parity test).
- T07 — Byte-identical fast-path invariants on the fixture: score_milli
  == 1000 iff byte_identical, drift_count == 0 iff byte_identical,
  field_diffs_summary == "" iff byte_identical.
- T08 — ``build_trace_from_report`` byte-identical to
  ``build_bridge_diff_trace`` on the same envelope pair.
- T09 — Live-engine cross-check: trace fields agree with the live
  :func:`compare_implementations` ``DiffReport`` projection
  (jcs_hash_a, jcs_hash_b, drift_count match).
- T10 — Score-milli boundary cases pin: score_milli == 1000 (byte-
  identical), 0 (total drift), and a mid-range integer.

Pinning procedure
-----------------

If a wire-shape change is intentional:

1. Update both sides (Rust crate ``persona-engine-bridge-diff``
   canonical sub-module and Python
   ``bridge_audit_diff_engine_canonical.py``).
2. Re-derive the fixture vectors using the inline derivation block
   in the fixture-generation script (see this file's ``__main__``
   block for the derivation recipe).
3. Update both Python and Rust test suites in the same PR.
"""

from __future__ import annotations

import base64
import json
import pathlib
from typing import Any, Dict

import pytest

# Cross-lang parity needs rfc8785 (the live diff-engine uses pure-Python
# `_jcs_pure` which has no extra deps, but the trace serialiser itself
# uses rfc8785 to match the existing Phase-3a cross-lang-trace pattern).
# The shadow-CI lane runs without the wheel; skip the entire suite on
# that lane via the same importorskip pattern already established in
# the Tag-35 / Tag-34 sibling tests.
pytest.importorskip("rfc8785")

from wirelang.persona_engine.bridge_audit_diff_engine import (
    DiffInput,
    compare_implementations,
)
from wirelang.persona_engine.bridge_audit_diff_engine_canonical import (
    BRIDGE_DIFF_TRACE_SCHEMA,
    BridgeDiffTrace,
    DIFF_KIND_VALUES,
    HASH_PREFIX,
    KIND_ONLY_IN_A,
    KIND_ONLY_IN_B,
    KIND_TYPE_MISMATCH,
    KIND_VALUE_MISMATCH,
    SHA256_HEX_LEN,
    SUMMARY_ENTRY_SEP,
    SUMMARY_PATH_KIND_SEP,
    bridge_diff_trace_hash_prefixed,
    bridge_diff_trace_sha256_hex,
    build_bridge_diff_trace,
    build_trace_from_report,
    serialize_bridge_diff_trace,
)


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[3]


def _fixture_path() -> pathlib.Path:
    return (
        _repo_root()
        / "tests"
        / "fixtures"
        / "bridge-audit-diff-engine-cross-lang"
        / "fixtures.json"
    )


def _load_fixtures() -> Dict[str, Any]:
    return json.loads(_fixture_path().read_text(encoding="utf-8"))


# ---------------------------------------------------------------------
# T01 — constants pin.
# ---------------------------------------------------------------------


def test_t01_constants_pin() -> None:
    assert (
        BRIDGE_DIFF_TRACE_SCHEMA
        == "wakir.persona-engine.bridge-audit-diff-canonical/1"
    )
    assert HASH_PREFIX == "sha256:"
    assert SHA256_HEX_LEN == 64
    assert SUMMARY_ENTRY_SEP == ";"
    assert SUMMARY_PATH_KIND_SEP == "|"
    assert KIND_VALUE_MISMATCH == "value-mismatch"
    assert KIND_ONLY_IN_A == "only-in-a"
    assert KIND_ONLY_IN_B == "only-in-b"
    assert KIND_TYPE_MISMATCH == "type-mismatch"
    assert DIFF_KIND_VALUES == (
        KIND_VALUE_MISMATCH,
        KIND_ONLY_IN_A,
        KIND_ONLY_IN_B,
        KIND_TYPE_MISMATCH,
    )


# ---------------------------------------------------------------------
# T02 — determinism: two builds of the same input -> identical bytes.
# ---------------------------------------------------------------------


def test_t02_build_is_deterministic() -> None:
    env_a = {"schema": "s", "x": [1, 2, {"nested": True}]}
    env_b = {"schema": "s", "x": [1, 2, {"nested": False}]}
    t1 = build_bridge_diff_trace(env_a, env_b)
    t2 = build_bridge_diff_trace(env_a, env_b)
    assert t1 == t2
    assert serialize_bridge_diff_trace(t1) == serialize_bridge_diff_trace(t2)
    assert (
        bridge_diff_trace_sha256_hex(t1)
        == bridge_diff_trace_sha256_hex(t2)
    )


# ---------------------------------------------------------------------
# T03 — wire-shape key order is alphabetical.
# ---------------------------------------------------------------------


def test_t03_wire_keys_alphabetical() -> None:
    trace = build_bridge_diff_trace({"a": 1}, {"a": 2})
    jcs = serialize_bridge_diff_trace(trace)
    parsed = json.loads(jcs.decode("utf-8"))
    keys = list(parsed.keys())
    assert keys == sorted(keys)
    expected = {
        "byte_identical",
        "drift_count",
        "field_diffs_summary",
        "jcs_hash_a",
        "jcs_hash_b",
        "leaves_total",
        "schema",
        "score_milli",
    }
    assert set(keys) == expected


# ---------------------------------------------------------------------
# T04 — hash-shape pin.
# ---------------------------------------------------------------------


def test_t04_hash_shape_pin() -> None:
    trace = build_bridge_diff_trace({"x": "y"}, {"x": "y"})
    bare = bridge_diff_trace_sha256_hex(trace)
    prefixed = bridge_diff_trace_hash_prefixed(trace)
    assert len(bare) == SHA256_HEX_LEN
    assert bare == bare.lower()
    assert all(c in "0123456789abcdef" for c in bare)
    assert prefixed == HASH_PREFIX + bare


# ---------------------------------------------------------------------
# T05 — fixture file structure pin.
# ---------------------------------------------------------------------


def test_t05_fixture_file_structure_pin() -> None:
    doc = _load_fixtures()
    assert doc["schema_version"] == BRIDGE_DIFF_TRACE_SCHEMA
    fixtures = doc["fixtures"]
    assert len(fixtures) == 6, (
        "Tag-36 cross-lang vector count is 6 (1 byte-identical + 5 drift paths)"
    )
    required_top_keys = {
        "name",
        "input_envelope_a_json",
        "input_envelope_b_json",
        "expected",
    }
    required_expected_keys = {
        "byte_identical",
        "drift_count",
        "field_diffs_summary",
        "jcs_hash_a",
        "jcs_hash_b",
        "leaves_total",
        "score_milli",
        "trace_jcs_bytes_b64",
        "trace_jcs_bytes_len",
        "trace_sha256_hex",
        "trace_hash_prefixed",
    }
    for f in fixtures:
        assert required_top_keys <= set(f.keys()), f["name"]
        assert required_expected_keys <= set(f["expected"].keys()), f["name"]


# ---------------------------------------------------------------------
# T06 — per-vector byte-parity pin.
# ---------------------------------------------------------------------


@pytest.mark.parametrize("vector_idx", range(6))
def test_t06_per_vector_byte_parity(vector_idx: int) -> None:
    doc = _load_fixtures()
    vec = doc["fixtures"][vector_idx]
    env_a = json.loads(vec["input_envelope_a_json"])
    env_b = json.loads(vec["input_envelope_b_json"])
    expected = vec["expected"]

    trace = build_bridge_diff_trace(env_a, env_b)

    # Structured fields.
    assert trace.byte_identical == expected["byte_identical"], vec["name"]
    assert trace.drift_count == expected["drift_count"], vec["name"]
    assert (
        trace.field_diffs_summary == expected["field_diffs_summary"]
    ), vec["name"]
    assert trace.jcs_hash_a == expected["jcs_hash_a"], vec["name"]
    assert trace.jcs_hash_b == expected["jcs_hash_b"], vec["name"]
    assert trace.leaves_total == expected["leaves_total"], vec["name"]
    assert trace.score_milli == expected["score_milli"], vec["name"]

    # Byte-level.
    jcs_actual = serialize_bridge_diff_trace(trace)
    jcs_expected = base64.b64decode(expected["trace_jcs_bytes_b64"])
    assert jcs_actual == jcs_expected, vec["name"]
    assert len(jcs_actual) == expected["trace_jcs_bytes_len"], vec["name"]
    assert (
        bridge_diff_trace_sha256_hex(trace) == expected["trace_sha256_hex"]
    ), vec["name"]
    assert (
        bridge_diff_trace_hash_prefixed(trace)
        == expected["trace_hash_prefixed"]
    ), vec["name"]


# ---------------------------------------------------------------------
# T07 — byte-identical fast-path invariants.
# ---------------------------------------------------------------------


def test_t07_byte_identical_fast_path_invariants() -> None:
    doc = _load_fixtures()
    identical_seen = 0
    drift_seen = 0
    for f in doc["fixtures"]:
        e = f["expected"]
        if e["byte_identical"]:
            identical_seen += 1
            assert e["drift_count"] == 0, f["name"]
            assert e["score_milli"] == 1000, f["name"]
            assert e["field_diffs_summary"] == "", f["name"]
        else:
            drift_seen += 1
            assert e["drift_count"] >= 1, f["name"]
            assert e["score_milli"] < 1000, f["name"]
            assert e["field_diffs_summary"], f["name"]
    assert identical_seen >= 1, "expected at least 1 byte-identical fixture"
    assert drift_seen >= 4, "expected at least 4 drift-path fixtures"


# ---------------------------------------------------------------------
# T08 — build_trace_from_report byte-identical to build_bridge_diff_trace.
# ---------------------------------------------------------------------


def test_t08_from_report_matches_direct_build() -> None:
    env_a = {"schema": "s", "step_index": 5, "payload": "alpha"}
    env_b = {"schema": "s", "step_index": 5, "payload": "beta"}

    # Direct path.
    direct = build_bridge_diff_trace(env_a, env_b)

    # Indirect via live DiffReport.
    impl_a = lambda _inp: env_a  # noqa: E731 - test adapter
    impl_b = lambda _inp: env_b  # noqa: E731 - test adapter
    report = compare_implementations(
        DiffInput(
            org_id="wakir-labs",
            persona_id="reza",
            session_id="tag-36",
            step_index=5,
            output_kind="tool_call",
            payload=b"",
            ts_utc="2026-05-18T00:00:00Z",
        ),
        impl_a,
        impl_b,
    )
    from_report = build_trace_from_report(report)
    assert direct == from_report
    assert serialize_bridge_diff_trace(direct) == serialize_bridge_diff_trace(
        from_report
    )


# ---------------------------------------------------------------------
# T09 — live-engine cross-check: trace fields agree with DiffReport.
# ---------------------------------------------------------------------


def test_t09_trace_agrees_with_live_compare_implementations() -> None:
    doc = _load_fixtures()
    for f in doc["fixtures"]:
        env_a = json.loads(f["input_envelope_a_json"])
        env_b = json.loads(f["input_envelope_b_json"])
        impl_a = lambda _inp, a=env_a: a  # noqa: E731 - test adapter
        impl_b = lambda _inp, b=env_b: b  # noqa: E731 - test adapter
        report = compare_implementations(
            DiffInput(
                org_id="wakir-labs",
                persona_id="reza",
                session_id="t09",
                step_index=0,
                output_kind="tool_call",
                payload=b"",
                ts_utc="2026-05-18T00:00:00Z",
            ),
            impl_a,
            impl_b,
        )
        trace = build_trace_from_report(report)
        # Cross-check that the trace pins agree with the report.
        assert trace.jcs_hash_a == report.jcs_hash_a, f["name"]
        assert trace.jcs_hash_b == report.jcs_hash_b, f["name"]
        assert trace.byte_identical == report.byte_identical, f["name"]
        assert trace.drift_count == len(report.field_diffs), f["name"]
        # And that the fixture pin agrees with the trace.
        assert trace.jcs_hash_a == f["expected"]["jcs_hash_a"], f["name"]
        assert trace.jcs_hash_b == f["expected"]["jcs_hash_b"], f["name"]


# ---------------------------------------------------------------------
# T10 — score-milli boundary cases pin.
# ---------------------------------------------------------------------


def test_t10_score_milli_boundary_cases() -> None:
    # Byte-identical: score_milli must be 1000.
    t_id = build_bridge_diff_trace({"a": 1}, {"a": 1})
    assert t_id.byte_identical is True
    assert t_id.score_milli == 1000

    # Single-leaf drift, max(leaves_a, leaves_b) == 1 -> drifted/total == 1 -> 0.
    t_total = build_bridge_diff_trace({"a": 1}, {"a": 2})
    assert t_total.byte_identical is False
    assert t_total.drift_count == 1
    assert t_total.leaves_total == 1
    assert t_total.score_milli == 0

    # Three-leaf object, one drift -> score == 1 - 1/3 == 0.6666... -> 666.
    t_mid = build_bridge_diff_trace(
        {"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 2, "c": 99}
    )
    assert t_mid.byte_identical is False
    assert t_mid.drift_count == 1
    assert t_mid.leaves_total == 3
    assert t_mid.score_milli == 666  # floor(0.6666... * 1000)


# ---------------------------------------------------------------------
# Optional fixture-regeneration entry point (manual only).
# ---------------------------------------------------------------------


def _emit_fixture_file() -> pathlib.Path:  # pragma: no cover - manual tool
    """Regenerate the cross-lang fixture file.

    Not executed in the normal pytest run. Call via:

        python -c 'from wirelang.tests.persona_engine.\
test_bridge_audit_diff_engine_cross_lang_parity import _emit_fixture_file; \
print(_emit_fixture_file())'

    The fixture vectors are mirrored from the inline generation script
    ``/tmp/gen_bridge_diff_fixtures.py`` (Tag-36 derivation source).
    """
    raise NotImplementedError(
        "manual regeneration goes through /tmp/gen_bridge_diff_fixtures.py"
    )
