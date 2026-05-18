# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang parity tests for the persona-engine bridge-audit-replay
canonical-trace (Tag-37 Mini-Welle Phase-3a Python-sync, 14. Modul).

This file is the Python half of the cross-lang fixture pin pair.  The
Rust half lives at
``wirelang-rust/crates/persona-engine-bridge-audit-replay/tests/cross_lang_replay_trace_fixture_test.rs``
and consumes the same authoritative fixture file at
``tests/fixtures/bridge-audit-replay-cross-lang/fixtures.json``.

Test taxonomy
-------------

- T01 — Constants pin: ``REPLAY_TRACE_SCHEMA`` / ``HASH_PREFIX`` /
  ``SHA256_HEX_LEN`` / ``DIVERGENCE_NONE_SENTINEL`` / summary
  separators / divergence-kind alphabet match the Rust crate's
  ``pub const`` items.
- T02 — Determinism: two trace builds of the same actual/expected
  pair produce byte-identical canonical output.
- T03 — Wire-shape key order: top-level JCS keys are in alphabetical
  order (the cross-lang contract); 9 keys expected.
- T04 — Hash shape: prefixed-form is ``"sha256:" + 64 lowercase hex``;
  bare hex is exactly 64 lowercase hex characters.
- T05 — Cross-lang fixture file structure: schema_version, fixture
  count (6), and per-fixture key set match the Rust sibling's
  structure pin.
- T06 — Cross-lang fixture per-vector pin (parametrised over all six
  fixtures): byte-for-byte parity with the JSON fixture file's
  pinned values (this is the core trace-hash byte-parity test).
- T07 — Success-path invariants on the fixture: ``success`` iff
  ``divergence_first_step == -1`` iff ``divergence_first_kind == ""``
  iff ``divergences_summary == ""``.
- T08 — ``build_trace_from_report`` byte-identical to
  ``build_replay_trace`` on the same input.
- T09 — Live-engine cross-check: trace fields agree with the live
  :class:`ReplayReport` projection (stream_hash_actual,
  stream_hash_expected, success).
- T10 — Divergence-kind boundary pin: each of the three kinds
  (value-mismatch / missing-in-actual / extra-in-actual) appears
  in exactly one fixture vector and the per-vector
  ``divergence_first_kind`` matches.

Pinning procedure
-----------------

If a wire-shape change is intentional:

1. Update both sides (Rust crate ``persona-engine-bridge-audit-replay``
   canonical sub-module and Python
   ``bridge_audit_replay_canonical.py``).
2. Re-derive the fixture vectors using
   ``scripts/derive-bridge-audit-replay-fixtures.py``.
3. Update both Python and Rust test suites in the same PR.
"""

from __future__ import annotations

import base64
import json
import pathlib
from typing import Any, Dict

import pytest

# Cross-lang parity needs rfc8785 (the live replay engine uses pure-Python
# `_jcs_pure` for record hashes, but the trace serialiser uses rfc8785 to
# match the existing Phase-3a cross-lang-trace pattern).  The shadow-CI
# lane runs without the wheel; skip the entire suite on that lane via the
# same importorskip pattern already established in Tag-35 / Tag-36
# sibling tests.
pytest.importorskip("rfc8785")

from wirelang.persona_engine.bridge_audit_replay import (
    AuditRecord,
    ExpectedTrajectory,
    ReplayEngine,
    stream_hash,
)
from wirelang.persona_engine.bridge_audit_replay_canonical import (
    DIVERGENCE_KIND_VALUES,
    DIVERGENCE_NONE_SENTINEL,
    HASH_PREFIX,
    KIND_EXTRA_IN_ACTUAL,
    KIND_MISSING_IN_ACTUAL,
    KIND_VALUE_MISMATCH,
    REPLAY_TRACE_SCHEMA,
    ReplayTrace,
    SHA256_HEX_LEN,
    SUMMARY_ENTRY_SEP,
    SUMMARY_STEP_KIND_SEP,
    build_replay_trace,
    build_trace_from_report,
    replay_trace_hash_prefixed,
    replay_trace_sha256_hex,
    serialize_replay_trace,
)

# ---------------------------------------------------------------------------
# Fixture file load.
# ---------------------------------------------------------------------------


FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "bridge-audit-replay-cross-lang"
    / "fixtures.json"
)


@pytest.fixture(scope="module")
def fixture_doc() -> Dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decode_stream(b64: str) -> list[AuditRecord]:
    """Decode a base64-JCS-encoded record stream from the fixture file.

    The wire format is ``{"stream": [<envelope>, ...], "stream_len": N}``;
    each envelope is the 11-field canonical envelope shape and we
    re-hydrate it back into an :class:`AuditRecord`.
    """
    raw = json.loads(base64.standard_b64decode(b64.encode("ascii")).decode("utf-8"))
    out: list[AuditRecord] = []
    for env in raw["stream"]:
        out.append(
            AuditRecord(
                org_id=env["org_id"],
                persona_id=env["persona_id"],
                session_id=env["session_id"],
                step_index=int(env["step_index"]),
                output_kind=env["output_kind"],
                output_payload_sha256=env["output_payload_sha256"],
                engine_version=env["engine_version"],
                v907_pin=env["v907_pin"],
                ts_utc=env["ts_utc"],
            )
        )
    return out


# ---------------------------------------------------------------------------
# T01 — Constants pin.
# ---------------------------------------------------------------------------


def test_t01_schema_constant_value():
    """REPLAY_TRACE_SCHEMA pinned to the cross-lang wire string."""
    assert REPLAY_TRACE_SCHEMA == "wakir.persona-engine.bridge-audit-replay-canonical/1"


def test_t01_hash_prefix_constant():
    """HASH_PREFIX pinned to ``"sha256:"`` cross-lang."""
    assert HASH_PREFIX == "sha256:"


def test_t01_sha256_hex_len_constant():
    """SHA256_HEX_LEN pinned to 64 (32 bytes, 64 hex chars)."""
    assert SHA256_HEX_LEN == 64


def test_t01_divergence_none_sentinel():
    """Success-path sentinel pinned to -1 cross-lang."""
    assert DIVERGENCE_NONE_SENTINEL == -1


def test_t01_summary_separators_distinct():
    """Summary separators distinct + not in DivergenceKind alphabet."""
    assert SUMMARY_ENTRY_SEP == ";"
    assert SUMMARY_STEP_KIND_SEP == "|"
    assert SUMMARY_ENTRY_SEP != SUMMARY_STEP_KIND_SEP
    for kind in DIVERGENCE_KIND_VALUES:
        assert SUMMARY_ENTRY_SEP not in kind
        assert SUMMARY_STEP_KIND_SEP not in kind


def test_t01_divergence_kind_alphabet():
    """DivergenceKind wire strings pinned: 3 entries, lower-case-hyphen."""
    assert DIVERGENCE_KIND_VALUES == (
        "value-mismatch",
        "missing-in-actual",
        "extra-in-actual",
    )
    assert KIND_VALUE_MISMATCH == "value-mismatch"
    assert KIND_MISSING_IN_ACTUAL == "missing-in-actual"
    assert KIND_EXTRA_IN_ACTUAL == "extra-in-actual"


# ---------------------------------------------------------------------------
# T02 — Determinism.
# ---------------------------------------------------------------------------


def _record(step: int, kind: str = "tool_call", c: str = "a") -> AuditRecord:
    return AuditRecord(
        org_id="wakir-labs",
        persona_id="mira",
        session_id="t02",
        step_index=step,
        output_kind=kind,
        output_payload_sha256="sha256:" + c * 64,
        engine_version="0.2.0-pilot",
        v907_pin="sha256:" + "b" * 64,
        ts_utc=f"2026-05-18T10:00:0{step}Z",
    )


def test_t02_determinism_two_builds_byte_identical():
    """Two trace builds of the same input -> byte-identical JCS bytes."""
    actual = [_record(0), _record(1, "reply", "c"), _record(2, "audit_annotation", "d")]
    expected = ExpectedTrajectory.from_records(actual)
    t1 = build_replay_trace(actual, expected)
    t2 = build_replay_trace(actual, expected)
    assert serialize_replay_trace(t1) == serialize_replay_trace(t2)
    assert replay_trace_sha256_hex(t1) == replay_trace_sha256_hex(t2)


# ---------------------------------------------------------------------------
# T03 — Wire-shape key order.
# ---------------------------------------------------------------------------


def test_t03_wire_shape_keys_alphabetical_and_count_9():
    """9 top-level keys, alphabetical order."""
    actual = [_record(0)]
    expected = ExpectedTrajectory.from_records(actual)
    trace = build_replay_trace(actual, expected)
    bytes_ = serialize_replay_trace(trace)
    obj = json.loads(bytes_.decode("utf-8"))
    keys = list(obj.keys())
    assert keys == sorted(keys)
    assert len(keys) == 9
    assert keys == [
        "actual_record_count",
        "divergence_first_kind",
        "divergence_first_step",
        "divergences_summary",
        "expected_record_count",
        "schema",
        "stream_hash_actual",
        "stream_hash_expected",
        "success",
    ]


# ---------------------------------------------------------------------------
# T04 — Hash shape.
# ---------------------------------------------------------------------------


def test_t04_hash_shape_prefixed_and_bare():
    """Hash shape pin: prefixed = "sha256:" + 64 lowercase hex."""
    trace = build_replay_trace([_record(0)], ExpectedTrajectory.from_records([_record(0)]))
    bare = replay_trace_sha256_hex(trace)
    prefixed = replay_trace_hash_prefixed(trace)
    assert prefixed == HASH_PREFIX + bare
    assert len(bare) == SHA256_HEX_LEN
    assert bare == bare.lower()
    assert all(c in "0123456789abcdef" for c in bare)


# ---------------------------------------------------------------------------
# T05 — Fixture file structure.
# ---------------------------------------------------------------------------


def test_t05_fixture_schema_version_matches(fixture_doc):
    assert fixture_doc["schema_version"] == REPLAY_TRACE_SCHEMA


def test_t05_fixture_count_six(fixture_doc):
    assert len(fixture_doc["fixtures"]) == 6


def test_t05_fixture_keys_per_vector(fixture_doc):
    expected_outer = {"name", "input_actual_b64", "input_expected_b64", "expected"}
    expected_inner = {
        "actual_record_count",
        "divergence_first_kind",
        "divergence_first_step",
        "divergences_summary",
        "expected_record_count",
        "stream_hash_actual",
        "stream_hash_expected",
        "success",
        "trace_jcs_bytes_b64",
        "trace_jcs_bytes_len",
        "trace_sha256_hex",
        "trace_hash_prefixed",
        "live_report_summary",
    }
    for f in fixture_doc["fixtures"]:
        assert set(f.keys()) == expected_outer, f["name"]
        assert set(f["expected"].keys()) == expected_inner, f["name"]


# ---------------------------------------------------------------------------
# T06 — Per-vector cross-lang byte-parity pin (parametrised).
# ---------------------------------------------------------------------------


@pytest.fixture(
    scope="module",
    params=[
        "f01-empty-streams-success",
        "f02-single-record-success",
        "f03-three-record-success",
        "f04-value-mismatch-at-step-1",
        "f05-missing-in-actual-at-step-2",
        "f06-extra-in-actual-at-step-3",
    ],
)
def vector(request, fixture_doc):
    name = request.param
    for f in fixture_doc["fixtures"]:
        if f["name"] == name:
            return f
    raise AssertionError(f"fixture {name!r} not present")


def test_t06_per_vector_trace_byte_parity(vector):
    """Authoritative cross-lang byte-parity pin per vector."""
    actual = _decode_stream(vector["input_actual_b64"])
    expected_recs = _decode_stream(vector["input_expected_b64"])
    expected = ExpectedTrajectory.from_records(expected_recs)
    trace = build_replay_trace(actual, expected)
    pinned = vector["expected"]

    # Trace-field pins
    assert int(trace.actual_record_count) == pinned["actual_record_count"]
    assert trace.divergence_first_kind == pinned["divergence_first_kind"]
    assert int(trace.divergence_first_step) == pinned["divergence_first_step"]
    assert trace.divergences_summary == pinned["divergences_summary"]
    assert int(trace.expected_record_count) == pinned["expected_record_count"]
    assert trace.stream_hash_actual == pinned["stream_hash_actual"]
    assert trace.stream_hash_expected == pinned["stream_hash_expected"]
    assert bool(trace.success) == pinned["success"]

    # JCS bytes pin (the core cross-lang anchor)
    bytes_actual = serialize_replay_trace(trace)
    bytes_pinned = base64.standard_b64decode(pinned["trace_jcs_bytes_b64"].encode("ascii"))
    assert bytes_actual == bytes_pinned, vector["name"]
    assert len(bytes_actual) == pinned["trace_jcs_bytes_len"]

    # Hash pins
    assert replay_trace_sha256_hex(trace) == pinned["trace_sha256_hex"]
    assert replay_trace_hash_prefixed(trace) == pinned["trace_hash_prefixed"]


# ---------------------------------------------------------------------------
# T07 — Success-path invariants on the fixture set.
# ---------------------------------------------------------------------------


def test_t07_success_iff_sentinels(fixture_doc):
    """success iff first_step == -1 iff first_kind == "" iff summary == ""."""
    for f in fixture_doc["fixtures"]:
        e = f["expected"]
        s = bool(e["success"])
        first_step = int(e["divergence_first_step"])
        first_kind = e["divergence_first_kind"]
        summary = e["divergences_summary"]
        assert s == (first_step == -1), f["name"]
        assert s == (first_kind == ""), f["name"]
        assert s == (summary == ""), f["name"]


# ---------------------------------------------------------------------------
# T08 — build_trace_from_report byte-identical to build_replay_trace.
# ---------------------------------------------------------------------------


def test_t08_build_trace_from_report_byte_identical(fixture_doc):
    for f in fixture_doc["fixtures"]:
        actual = _decode_stream(f["input_actual_b64"])
        expected = ExpectedTrajectory.from_records(
            _decode_stream(f["input_expected_b64"])
        )
        trace_direct = build_replay_trace(actual, expected)
        # Route 2: run the engine separately, project to a trace.
        report = ReplayEngine().replay_stream(actual, expected)
        trace_from_report = build_trace_from_report(report)
        assert serialize_replay_trace(trace_direct) == serialize_replay_trace(
            trace_from_report
        ), f["name"]


# ---------------------------------------------------------------------------
# T09 — Live-engine cross-check.
# ---------------------------------------------------------------------------


def test_t09_live_engine_stream_hash_agreement(fixture_doc):
    """Trace's stream-hash fields == live-engine's stream-hash output."""
    for f in fixture_doc["fixtures"]:
        actual = _decode_stream(f["input_actual_b64"])
        expected_recs = _decode_stream(f["input_expected_b64"])
        expected = ExpectedTrajectory.from_records(expected_recs)

        trace = build_replay_trace(actual, expected)
        live_actual_hash = stream_hash(actual)
        live_expected_hash = stream_hash(expected_recs)

        assert trace.stream_hash_actual == live_actual_hash, f["name"]
        assert trace.stream_hash_expected == live_expected_hash, f["name"]

        # Live ReplayReport.success == trace.success
        report = ReplayEngine().replay_stream(actual, expected)
        assert bool(report.success) == bool(trace.success), f["name"]


# ---------------------------------------------------------------------------
# T10 — Divergence-kind boundary coverage.
# ---------------------------------------------------------------------------


def test_t10_kind_coverage(fixture_doc):
    """All three DivergenceKind values surface in the fixture set."""
    kinds_seen: set[str] = set()
    for f in fixture_doc["fixtures"]:
        e = f["expected"]
        if not e["success"]:
            kinds_seen.add(e["divergence_first_kind"])
    assert kinds_seen == {
        KIND_VALUE_MISMATCH,
        KIND_MISSING_IN_ACTUAL,
        KIND_EXTRA_IN_ACTUAL,
    }


def test_t10_first_kind_matches_summary_first_entry(fixture_doc):
    """divergence_first_kind == kind portion of first divergences_summary entry."""
    for f in fixture_doc["fixtures"]:
        e = f["expected"]
        if e["success"]:
            assert e["divergences_summary"] == ""
            assert e["divergence_first_kind"] == ""
        else:
            first_entry = e["divergences_summary"].split(SUMMARY_ENTRY_SEP)[0]
            step_str, kind_str = first_entry.split(SUMMARY_STEP_KIND_SEP)
            assert kind_str == e["divergence_first_kind"], f["name"]
            assert int(step_str) == int(e["divergence_first_step"]), f["name"]
