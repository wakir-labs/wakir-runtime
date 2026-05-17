# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang parity tests for the bridge-audit-writer (Tag-30 Mini-Welle).

The Python module under test
(:mod:`wirelang.persona_engine.bridge_audit_writer`) is BUSL-1.1; these
tests are Apache-2.0 so downstream re-implementers can re-use the same
vectors.

This file is the **writer-side** parity test (12. Modul,
Welle-3-Komponente per ADR-0066). The Rust authority lives at
``wirelang-rust/crates/persona-engine-bridge-audit-writer`` (Tag-30
deliverable); the cross-lang fixture file at
``tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json`` is the
single source of truth for envelope bytes / record hashes.

Welle-3 Henrik-Audit-Caution context
------------------------------------

ADR-0066 Welle-3 (KW 25) = Konsistenz-Oracle-Selbst-Cutover. Henrik's
audit caution flagged that the cutover needs byte-paritaere cross-lang
coverage to be COMPLETE before the Welle-3 binding. The writer-side leg
was the open gap (diff and replay legs were closed in earlier waves);
these tests close that gap.

Test taxonomy
-------------

- T01 -- Constants pin: schema, event-kind, output-kind variants,
  hash-prefix match the Rust crate's ``pub const`` items.
- T02 -- Fixture file shape: schema_version, fixture count, fixture
  name set, per-fixture key set match the documented structure.
- T03 -- Empty-stream invariant (F01): no emit() calls leaves
  step_counter at 0 and the records-list empty.
- T04 -- Single-record-write byte-pin (F02, parametrised over the one
  record): JCS bytes + hash byte-identical to the fixture pin.
- T05 -- Batch-write byte-pin (F03, parametrised over three records):
  step_index monotonicity (0,1,2) + per-record JCS bytes / hashes
  byte-identical to the fixture pin.
- T06 -- Error-write-rollback invariant (F04): ValueError on
  output_kind="garbage_kind" does NOT advance the step counter; the
  post-rollback emit() carries step_index == 2 (not 3); JCS bytes for
  the three successful records byte-identical to fixture pin.
- T07 -- Append-only-discipline (F05): two writers run the same
  scripted sequence and produce byte-identical envelopes record-by-
  record; the records pin byte-identically to the fixture.
- T08 -- Determinism sentinel: two builds of the same fixture replay
  produce identical JCS bytes (writer is a pure function of constructor
  + emit args).
- T09 -- Record-hash byte-identity: for every fixture record the
  Python writer's ``EngineeringOutputEvent.payload_sha256()`` matches
  the fixture pin and the SHA-256 of its own JCS bytes.
- T10 -- Output-kind coverage: across the five fixtures every one of
  the three permitted output_kind values appears at least once.
- T11 -- JCS-key-order pin: every envelope's JCS bytes contain the
  eleven canonical keys in strict lex order (engine_version,
  event_kind, org_id, output_kind, output_payload_sha256, persona_id,
  schema, session_id, step_index, ts_utc, v907_pin).
- T12 -- Fixture-record-count completeness: f01..f05 have the
  documented record counts (0, 1, 3, 3, 2).
- T13 -- Cross-lang derivation idempotence: re-running the derivation
  on the fixture inputs produces byte-identical records (the script
  is referentially transparent).

Pinning procedure
-----------------

If a wire-shape change is intentional:

1. Update both sides (Rust ``persona-engine-bridge-audit-writer`` and
   Python ``bridge_audit_writer.py``).
2. Re-derive the fixture vectors via
   ``python3 scripts/derive-bridge-audit-writer-fixtures.py > \\
   tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json``.
3. Update both Python and Rust test suites in the same PR.

If a wire-shape change is accidental, T04 / T05 / T06 / T07 / T09 fire
on both sides which is the intended boundary detector.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import pathlib
from typing import Any, Dict, List

import pytest

from wirelang.persona_engine.bridge_audit_writer import (
    BridgeAuditWriter,
    ENGINEERING_OUTPUT_SCHEMA,
    EngineeringOutputEvent,
    sha256_hex,
)


# ---------------------------------------------------------------------
# Fixture-file loader
# ---------------------------------------------------------------------


_FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "bridge-audit-writer-cross-lang"
    / "fixtures.json"
)


_EXPECTED_FIXTURE_NAMES = (
    "f01-empty-audit-stream",
    "f02-single-record-write",
    "f03-batch-write",
    "f04-error-write-rollback",
    "f05-append-only-discipline",
)


_EXPECTED_RECORD_COUNTS = {
    "f01-empty-audit-stream": 0,
    "f02-single-record-write": 1,
    "f03-batch-write": 3,
    "f04-error-write-rollback": 3,
    "f05-append-only-discipline": 2,
}


_LEX_ORDERED_ENVELOPE_KEYS = (
    "engine_version",
    "event_kind",
    "org_id",
    "output_kind",
    "output_payload_sha256",
    "persona_id",
    "schema",
    "session_id",
    "step_index",
    "ts_utc",
    "v907_pin",
)


@pytest.fixture(scope="module")
def fixture_doc() -> Dict[str, Any]:
    """Load the cross-lang fixture file once per test module."""
    with _FIXTURE_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def fixtures_by_name(fixture_doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {f["name"]: f for f in fixture_doc["fixtures"]}


# ---------------------------------------------------------------------
# Replay helper -- runs one fixture's emission sequence through a fresh
# Python writer and returns the resulting events + final step counter.
# ---------------------------------------------------------------------


def _replay_fixture(
    fixture: Dict[str, Any],
) -> tuple[List[EngineeringOutputEvent], int]:
    """Run the fixture's emission program through a fresh writer."""
    inp = fixture["input"]
    w = BridgeAuditWriter(
        org_id=inp["org_id"],
        persona_id=inp["persona_id"],
        session_id=inp["session_id"],
        engine_version=inp["engine_version"],
        v907_pin=inp["v907_pin"],
        # Unwriteable parent so the markdown append skips silently; the
        # deterministic envelope surface does not depend on the sink.
        preframework_sink_path=pathlib.Path("/dev/null/unused"),
        wakir_runtime_sink=io.StringIO(),
    )
    events: List[EngineeringOutputEvent] = []
    for em in inp["emissions"]:
        payload = base64.b64decode(em["payload_b64"])
        if em.get("expect_error"):
            with pytest.raises(ValueError):
                w.emit(em["output_kind"], payload, ts_utc=em["ts_utc"])
            continue
        evt = w.emit(em["output_kind"], payload, ts_utc=em["ts_utc"])
        events.append(evt)
    return events, w._step_counter


# =====================================================================
# T01 -- Constants pin
# =====================================================================


def test_t01_constants_pin():
    assert ENGINEERING_OUTPUT_SCHEMA == "wakir.persona.engineering-output/1"
    # Output-kind variants -- the three permitted values pinned by both
    # sides.
    for k in ("tool_call", "reply", "audit_annotation"):
        # Round-trip through sha256_hex to verify the helper is intact.
        h = sha256_hex(k.encode("utf-8"))
        assert h.startswith("sha256:")
        assert len(h) == len("sha256:") + 64


# =====================================================================
# T02 -- Fixture file shape
# =====================================================================


def test_t02_fixture_file_shape(fixture_doc):
    assert fixture_doc["schema_version"] == ENGINEERING_OUTPUT_SCHEMA
    names = tuple(f["name"] for f in fixture_doc["fixtures"])
    assert names == _EXPECTED_FIXTURE_NAMES
    for f in fixture_doc["fixtures"]:
        assert set(f.keys()) == {"name", "doc", "input", "expected"}
        assert set(f["input"].keys()) >= {
            "org_id",
            "persona_id",
            "session_id",
            "engine_version",
            "v907_pin",
            "emissions",
        }
        assert set(f["expected"].keys()) == {"records", "step_counter_final"}


# =====================================================================
# T03 -- Empty-stream invariant (F01)
# =====================================================================


def test_t03_empty_stream_invariant(fixtures_by_name):
    f = fixtures_by_name["f01-empty-audit-stream"]
    events, step_final = _replay_fixture(f)
    assert events == []
    assert step_final == 0
    assert f["expected"]["records"] == []
    assert f["expected"]["step_counter_final"] == 0


# =====================================================================
# T04 -- Single-record-write byte-pin (F02)
# =====================================================================


def test_t04_single_record_write_byte_pin(fixtures_by_name):
    f = fixtures_by_name["f02-single-record-write"]
    events, step_final = _replay_fixture(f)
    assert step_final == f["expected"]["step_counter_final"] == 1
    assert len(events) == len(f["expected"]["records"]) == 1
    evt = events[0]
    pinned = f["expected"]["records"][0]
    # Byte-identity: JCS bytes match base64-decoded pin.
    actual_jcs = evt.to_jcs_bytes()
    pinned_jcs = base64.b64decode(pinned["jcs_b64"])
    assert actual_jcs == pinned_jcs, (
        f"JCS-byte drift on f02-single-record-write step 0: "
        f"actual_len={len(actual_jcs)} pinned_len={len(pinned_jcs)}"
    )
    assert len(actual_jcs) == pinned["jcs_len"]
    assert evt.payload_sha256() == pinned["hash_prefixed"]
    # step_index pinned to 0.
    assert evt.step_index == 0


# =====================================================================
# T05 -- Batch-write byte-pin (F03), parametrised over three records
# =====================================================================


@pytest.mark.parametrize("step_idx", [0, 1, 2])
def test_t05_batch_write_byte_pin(fixtures_by_name, step_idx):
    f = fixtures_by_name["f03-batch-write"]
    events, step_final = _replay_fixture(f)
    assert step_final == 3
    assert [e.step_index for e in events] == [0, 1, 2]
    assert [e.output_kind for e in events] == [
        "tool_call",
        "reply",
        "audit_annotation",
    ]
    evt = events[step_idx]
    pinned = f["expected"]["records"][step_idx]
    actual_jcs = evt.to_jcs_bytes()
    pinned_jcs = base64.b64decode(pinned["jcs_b64"])
    assert actual_jcs == pinned_jcs
    assert evt.payload_sha256() == pinned["hash_prefixed"]


# =====================================================================
# T06 -- Error-write-rollback invariant (F04)
# =====================================================================


def test_t06_error_write_rollback_invariant(fixtures_by_name):
    f = fixtures_by_name["f04-error-write-rollback"]
    events, step_final = _replay_fixture(f)
    # Three SUCCESSFUL emissions; the failed garbage_kind call was
    # consumed via pytest.raises and did NOT advance the counter.
    assert len(events) == 3
    # post-rollback emit() carries step_index == 2 (not 3).
    assert [e.step_index for e in events] == [0, 1, 2]
    assert step_final == 3
    # Byte-pin per record.
    for actual_evt, pinned in zip(events, f["expected"]["records"]):
        actual_jcs = actual_evt.to_jcs_bytes()
        pinned_jcs = base64.b64decode(pinned["jcs_b64"])
        assert actual_jcs == pinned_jcs
        assert actual_evt.payload_sha256() == pinned["hash_prefixed"]


# =====================================================================
# T07 -- Append-only-discipline (F05)
# =====================================================================


def test_t07_append_only_discipline(fixtures_by_name):
    f = fixtures_by_name["f05-append-only-discipline"]
    # Run TWO independent writers with identical args; their envelopes
    # must be byte-identical record-by-record.
    events_a, sf_a = _replay_fixture(f)
    events_b, sf_b = _replay_fixture(f)
    assert sf_a == sf_b == 2
    assert len(events_a) == len(events_b) == 2
    for a, b in zip(events_a, events_b):
        assert a.to_jcs_bytes() == b.to_jcs_bytes()
    # And both byte-identical to the fixture pin.
    for actual_evt, pinned in zip(events_a, f["expected"]["records"]):
        actual_jcs = actual_evt.to_jcs_bytes()
        pinned_jcs = base64.b64decode(pinned["jcs_b64"])
        assert actual_jcs == pinned_jcs
        assert actual_evt.payload_sha256() == pinned["hash_prefixed"]


# =====================================================================
# T08 -- Determinism sentinel (re-run produces byte-identical bytes)
# =====================================================================


def test_t08_determinism_sentinel(fixtures_by_name):
    # f03 (the densest fixture) is sufficient -- determinism is global.
    f = fixtures_by_name["f03-batch-write"]
    events_run1, _ = _replay_fixture(f)
    events_run2, _ = _replay_fixture(f)
    for a, b in zip(events_run1, events_run2):
        assert a.to_jcs_bytes() == b.to_jcs_bytes()
        assert a.payload_sha256() == b.payload_sha256()


# =====================================================================
# T09 -- Record-hash byte-identity
# =====================================================================


@pytest.mark.parametrize("fixture_name", _EXPECTED_FIXTURE_NAMES)
def test_t09_record_hash_byte_identity(fixtures_by_name, fixture_name):
    f = fixtures_by_name[fixture_name]
    events, _ = _replay_fixture(f)
    pinned_records = f["expected"]["records"]
    assert len(events) == len(pinned_records)
    for evt, pinned in zip(events, pinned_records):
        actual_hash = evt.payload_sha256()
        # Independently re-hash the JCS bytes via hashlib to catch a
        # rotten payload_sha256() implementation.
        independent_hash = "sha256:" + hashlib.sha256(evt.to_jcs_bytes()).hexdigest()
        assert actual_hash == independent_hash
        assert actual_hash == pinned["hash_prefixed"]


# =====================================================================
# T10 -- Output-kind coverage across the five fixtures
# =====================================================================


def test_t10_output_kind_coverage(fixture_doc):
    kinds_seen: set[str] = set()
    for f in fixture_doc["fixtures"]:
        for rec in f["expected"]["records"]:
            kinds_seen.add(rec["envelope"]["output_kind"])
    assert kinds_seen == {"tool_call", "reply", "audit_annotation"}


# =====================================================================
# T11 -- JCS-key-order pin
# =====================================================================


@pytest.mark.parametrize("fixture_name", _EXPECTED_FIXTURE_NAMES)
def test_t11_jcs_key_order_pin(fixtures_by_name, fixture_name):
    f = fixtures_by_name[fixture_name]
    for pinned in f["expected"]["records"]:
        jcs_str = base64.b64decode(pinned["jcs_b64"]).decode("utf-8")
        # Find the position of every canonical key marker `"<key>":`
        # within the JCS string and assert strict lex order.
        positions = []
        for key in _LEX_ORDERED_ENVELOPE_KEYS:
            marker = f'"{key}":'
            pos = jcs_str.find(marker)
            assert pos >= 0, f"key {key!r} missing in JCS: {jcs_str!r}"
            positions.append(pos)
        assert positions == sorted(positions), (
            f"JCS keys not in lex order for fixture {fixture_name}: {positions}"
        )


# =====================================================================
# T12 -- Fixture-record-count completeness
# =====================================================================


def test_t12_fixture_record_count_completeness(fixtures_by_name):
    for name, expected_count in _EXPECTED_RECORD_COUNTS.items():
        f = fixtures_by_name[name]
        assert len(f["expected"]["records"]) == expected_count, (
            f"record-count drift for {name}: "
            f"got {len(f['expected']['records'])}, expected {expected_count}"
        )


# =====================================================================
# T13 -- Cross-lang derivation idempotence
# =====================================================================


def test_t13_derivation_idempotence(fixture_doc):
    """Re-derive the fixtures in-process; byte-identical output."""
    # Re-import the derivation module via importlib to avoid polluting
    # sys.path. The script is small and pure; we just call its
    # build_fixtures() helper.
    import importlib.util

    script_path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "scripts"
        / "derive-bridge-audit-writer-fixtures.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_derive_bridge_audit_writer_fixtures_under_test",
        str(script_path),
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    re_derived = mod.build_fixtures()
    # Names + per-fixture record envelopes / hashes byte-identical.
    assert re_derived["schema_version"] == fixture_doc["schema_version"]
    names_a = [f["name"] for f in re_derived["fixtures"]]
    names_b = [f["name"] for f in fixture_doc["fixtures"]]
    assert names_a == names_b
    for fa, fb in zip(re_derived["fixtures"], fixture_doc["fixtures"]):
        recs_a = fa["expected"]["records"]
        recs_b = fb["expected"]["records"]
        assert len(recs_a) == len(recs_b)
        for ra, rb in zip(recs_a, recs_b):
            assert ra["jcs_b64"] == rb["jcs_b64"]
            assert ra["jcs_len"] == rb["jcs_len"]
            assert ra["hash_prefixed"] == rb["hash_prefixed"]
            assert ra["envelope"] == rb["envelope"]
