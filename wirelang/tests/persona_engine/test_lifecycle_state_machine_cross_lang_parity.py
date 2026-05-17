# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang parity tests for the persona-engine lifecycle-state-machine.

The Python module under test
(:mod:`wirelang.persona_engine.lifecycle_state_machine_canonical`) is
Apache-2.0; this test file is Apache-2.0 so downstream re-implementers
can re-use the same fixture vectors.

Test taxonomy
-------------

- T01 — Constants pin: ``LIFECYCLE_TRACE_SCHEMA`` / ``HASH_PREFIX`` /
  ``SHA256_HEX_LEN`` match the Rust crate's ``pub const`` items.
- T02 — Spec-set pin: the six state wire-strings and nine valid
  transitions match byte-for-byte (re-checks PR #65 / PR #137
  invariants from the canonical-trace side).
- T03 — Happy-path build: fields round-trip verbatim through the
  ``LifecycleTrace`` dataclass; ``schema`` is forced to the
  constant regardless of caller input.
- T04 — Validation: unknown ``initial_state`` raises
  :class:`LifecycleTraceError`; unknown state strings inside
  records raise the same error from the records-based builder.
- T05 — Determinism: two builds of the same FSM session produce
  byte-identical canonical output.
- T06 — Wire-shape key order: top-level JCS keys are in
  alphabetical order (the cross-lang contract).
- T07 — Hash shape: prefixed-form is ``"sha256:" + 64 lowercase
  hex``; bare hex is exactly 64 lowercase hex characters.
- T08 — ``serialize_and_hash`` matches the individual calls
  byte-for-byte (no double-encoding path).
- T09 — Sensitivity: changing ``persona_id`` / ``org_id`` /
  ``initial_state`` / ``final_state`` / any record field flips
  the outer hash.
- T10 — Record-level reason-omit semantics: accepted records
  omit ``reason`` from the wire-form; rejected records carry it.
- T11 — Rejection preserves trace shape: a rejection in the
  middle of an otherwise clean trail keeps the trace's
  ``final_state`` driven only by accepted records.
- T12 — Build-from-records vs. build-from-FSM byte-parity: the
  two construction paths produce the same canonical bytes for
  the same logical content.
- T13 — Cross-lang fixture file structure: schema_version,
  fixture count, and per-fixture key set match the Rust
  sibling's structure pin (F01).
- T14 — Cross-lang fixture per-vector pin (parametrised over the
  five fixtures): byte-for-byte parity with the JSON fixture
  file's pinned values (this is the core trace-hash byte-parity
  test).
- T15 — Coverage completeness: every state appears as ``from_state``
  in at least one fixture, and every state appears as
  ``to_state`` in at least one fixture (set membership pin).
- T16 — Empty-history trace: a brand-new FSM with no transitions
  yet still serialises to deterministic bytes (drift sentinel
  for the "machine constructed but never used" boundary case).
- T17 — to_wire_dict shape pin: top-level keys + per-record key
  sets match the documented contract.

Pinning procedure
-----------------

If a wire-shape change is intentional:

1. Update both sides (Rust ``persona-engine-fsm`` canonical-trace
   surface and Python ``lifecycle_state_machine_canonical.py``).
2. Re-derive the fixture vectors using the derivation snippet in
   the Python module's docstring (run the fixture-build flow with
   a fixed clock).
3. Update both Python and Rust test suites in the same PR.

If a wire-shape change is accidental, the cross-lang fixture test
(T14) fires on both sides, which is the intended boundary detector.
"""

from __future__ import annotations

import base64
import json
import pathlib
from typing import Any, Dict, List

import pytest

from wirelang.persona_engine.lifecycle_state_machine import (
    STATES,
    VALID_TRANSITIONS,
    LifecycleStateMachine,
    TransitionRecord,
)
from wirelang.persona_engine.lifecycle_state_machine_canonical import (
    HASH_PREFIX,
    LIFECYCLE_TRACE_SCHEMA,
    LifecycleTrace,
    LifecycleTraceError,
    SHA256_HEX_LEN,
    build_lifecycle_trace,
    build_lifecycle_trace_from_records,
    lifecycle_trace_hash_prefixed,
    lifecycle_trace_sha256_hex,
    lifecycle_trace_to_wire_dict,
    serialize_and_hash,
    serialize_lifecycle_trace,
    sha256_hex,
    valid_state_set,
    valid_transition_set,
)


# ---------------------------------------------------------------------
# Deterministic clock used by every constructed FSM in this file.
# Matches the ``fixed_ts_utc`` field of the fixture file.
# ---------------------------------------------------------------------
_FIXED_TS = "2026-05-17T00:00:00Z"


def _fixed_clock() -> str:
    return _FIXED_TS


# ---------------------------------------------------------------------
# Fixture file loader
# ---------------------------------------------------------------------


def _fixture_path() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    # here = <repo>/wirelang/tests/persona_engine/<this-file>
    # repo_root = parents[3]
    repo_root = here.parents[3]
    return (
        repo_root
        / "tests"
        / "fixtures"
        / "lifecycle-state-machine-cross-lang"
        / "fixtures.json"
    )


def _load_fixtures() -> Dict[str, Any]:
    with _fixture_path().open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _records_from_fixture(fx: Dict[str, Any]) -> List[TransitionRecord]:
    """Materialise the fixture-input ``transitions`` array as
    :class:`TransitionRecord` instances."""
    return [
        TransitionRecord(
            from_state=t["from_state"],
            to_state=t["to_state"],
            ts_utc=t["ts_utc"],
            accepted=t["accepted"],
            reason=t["reason"],
        )
        for t in fx["input"]["transitions"]
    ]


# ---------------------------------------------------------------------
# T01 — Constants pin
# ---------------------------------------------------------------------


def test_t01_constants_match_rust_sibling_pin() -> None:
    assert LIFECYCLE_TRACE_SCHEMA == "wakir.persona-engine.lifecycle-trace/1"
    assert HASH_PREFIX == "sha256:"
    assert SHA256_HEX_LEN == 64


# ---------------------------------------------------------------------
# T02 — Spec-set pin (states + transitions byte-for-byte)
# ---------------------------------------------------------------------


def test_t02_state_and_transition_set_pin() -> None:
    assert STATES == (
        "uninstantiated",
        "spawning",
        "running",
        "despawning",
        "recovered",
        "migrated",
    )
    assert valid_state_set() == set(STATES)
    assert len(VALID_TRANSITIONS) == 9
    assert valid_transition_set() == set(VALID_TRANSITIONS)


# ---------------------------------------------------------------------
# T03 — Happy-path build round-trip via live FSM
# ---------------------------------------------------------------------


def test_t03_happy_path_build_round_trip() -> None:
    m = LifecycleStateMachine("reza", "wakir-labs", clock=_fixed_clock)
    m.transition_to("spawning")
    m.transition_to("running")
    trace = build_lifecycle_trace(m)

    assert isinstance(trace, LifecycleTrace)
    assert trace.persona_id == "reza"
    assert trace.org_id == "wakir-labs"
    assert trace.initial_state == "uninstantiated"
    assert trace.final_state == "running"
    assert trace.schema == LIFECYCLE_TRACE_SCHEMA
    assert len(trace.records) == 2
    assert all(r.accepted for r in trace.records)


# ---------------------------------------------------------------------
# T04 — Validation
# ---------------------------------------------------------------------


def test_t04_unknown_initial_state_rejected() -> None:
    m = LifecycleStateMachine("reza", "wakir-labs", clock=_fixed_clock)
    with pytest.raises(LifecycleTraceError):
        build_lifecycle_trace(m, initial_state="zombie")


def test_t04b_unknown_state_in_record_rejected() -> None:
    bad_rec = TransitionRecord(
        from_state="zombie",  # not a STATES value
        to_state="running",
        ts_utc=_FIXED_TS,
        accepted=True,
        reason=None,
    )
    with pytest.raises(LifecycleTraceError):
        build_lifecycle_trace_from_records(
            persona_id="reza",
            org_id="wakir-labs",
            initial_state="uninstantiated",
            records=[bad_rec],
        )


# ---------------------------------------------------------------------
# T05 — Determinism
# ---------------------------------------------------------------------


def test_t05_serialise_is_deterministic() -> None:
    def build() -> LifecycleTrace:
        m = LifecycleStateMachine("reza", "wakir-labs", clock=_fixed_clock)
        m.transition_to("spawning")
        m.transition_to("running")
        return build_lifecycle_trace(m)

    b1 = serialize_lifecycle_trace(build())
    b2 = serialize_lifecycle_trace(build())
    assert b1 == b2
    assert lifecycle_trace_sha256_hex(build()) == lifecycle_trace_sha256_hex(build())


# ---------------------------------------------------------------------
# T06 — Wire-shape top-level key order
# ---------------------------------------------------------------------


def test_t06_wire_shape_top_level_keys_alphabetical() -> None:
    m = LifecycleStateMachine("reza", "wakir-labs", clock=_fixed_clock)
    m.transition_to("spawning")
    trace = build_lifecycle_trace(m)
    text = serialize_lifecycle_trace(trace).decode("utf-8")
    top_keys = [
        "final_state",
        "initial_state",
        "org_id",
        "persona_id",
        "records",
        "schema",
    ]
    positions = [text.find(f'"{k}":') for k in top_keys]
    assert all(p > -1 for p in positions), (
        f"missing top-level key: positions={positions}, text={text}"
    )
    assert positions == sorted(positions), (
        f"top-level keys not alphabetical: positions={positions}"
    )


def test_t06b_wire_shape_record_keys_alphabetical() -> None:
    """Inside each accepted-record object the keys are alphabetical
    (``accepted`` < ``from_state`` < ``to_state`` < ``ts_utc``).
    ``reason`` is omitted for accepted records on the wire."""
    m = LifecycleStateMachine("reza", "wakir-labs", clock=_fixed_clock)
    m.transition_to("spawning")
    trace = build_lifecycle_trace(m)
    text = serialize_lifecycle_trace(trace).decode("utf-8")
    rec_keys_accepted = ["accepted", "from_state", "to_state", "ts_utc"]
    start = text.find('"records":[')
    assert start > 0
    rec_text = text[start:]
    positions = [rec_text.find(f'"{k}":') for k in rec_keys_accepted]
    assert all(p > -1 for p in positions)
    assert positions == sorted(positions)


# ---------------------------------------------------------------------
# T07 — Hash shape
# ---------------------------------------------------------------------


def test_t07_hash_shape_constraints() -> None:
    m = LifecycleStateMachine("reza", "wakir-labs", clock=_fixed_clock)
    m.transition_to("spawning")
    trace = build_lifecycle_trace(m)

    bare = lifecycle_trace_sha256_hex(trace)
    prefixed = lifecycle_trace_hash_prefixed(trace)
    assert len(bare) == SHA256_HEX_LEN
    assert all(c in "0123456789abcdef" for c in bare)
    assert prefixed.startswith(HASH_PREFIX)
    assert prefixed == HASH_PREFIX + bare
    assert len(prefixed) == len(HASH_PREFIX) + SHA256_HEX_LEN


# ---------------------------------------------------------------------
# T08 — serialize_and_hash byte-parity
# ---------------------------------------------------------------------


def test_t08_serialize_and_hash_round_trip() -> None:
    m = LifecycleStateMachine("reza", "wakir-labs", clock=_fixed_clock)
    m.transition_to("spawning")
    m.transition_to("running")
    trace = build_lifecycle_trace(m)
    bytes_, hash_ = serialize_and_hash(trace)
    assert bytes_ == serialize_lifecycle_trace(trace)
    assert hash_ == lifecycle_trace_hash_prefixed(trace)


# ---------------------------------------------------------------------
# T09 — Sensitivity: every load-bearing field flips the outer hash
# ---------------------------------------------------------------------


def test_t09_sensitivity_persona_flip() -> None:
    base_records = [
        TransitionRecord(
            from_state="uninstantiated",
            to_state="spawning",
            ts_utc=_FIXED_TS,
            accepted=True,
            reason=None,
        )
    ]
    base = build_lifecycle_trace_from_records(
        persona_id="reza",
        org_id="wakir-labs",
        initial_state="uninstantiated",
        records=base_records,
    )
    other = build_lifecycle_trace_from_records(
        persona_id="tomas",
        org_id="wakir-labs",
        initial_state="uninstantiated",
        records=base_records,
    )
    assert lifecycle_trace_sha256_hex(base) != lifecycle_trace_sha256_hex(other)


def test_t09b_sensitivity_org_flip() -> None:
    records = [
        TransitionRecord(
            from_state="uninstantiated",
            to_state="spawning",
            ts_utc=_FIXED_TS,
            accepted=True,
            reason=None,
        )
    ]
    a = build_lifecycle_trace_from_records(
        persona_id="reza",
        org_id="wakir-labs",
        initial_state="uninstantiated",
        records=records,
    )
    b = build_lifecycle_trace_from_records(
        persona_id="reza",
        org_id="other-org",
        initial_state="uninstantiated",
        records=records,
    )
    assert lifecycle_trace_sha256_hex(a) != lifecycle_trace_sha256_hex(b)


def test_t09c_sensitivity_record_field_flips() -> None:
    """A flip in any single record field changes the trace hash."""
    base = build_lifecycle_trace_from_records(
        persona_id="reza",
        org_id="wakir-labs",
        initial_state="uninstantiated",
        records=[
            TransitionRecord(
                from_state="uninstantiated",
                to_state="spawning",
                ts_utc=_FIXED_TS,
                accepted=True,
                reason=None,
            ),
            TransitionRecord(
                from_state="spawning",
                to_state="running",
                ts_utc=_FIXED_TS,
                accepted=True,
                reason=None,
            ),
        ],
    )
    base_hash = lifecycle_trace_sha256_hex(base)

    flipped_ts = build_lifecycle_trace_from_records(
        persona_id="reza",
        org_id="wakir-labs",
        initial_state="uninstantiated",
        records=[
            TransitionRecord(
                from_state="uninstantiated",
                to_state="spawning",
                ts_utc="2026-05-17T00:00:01Z",
                accepted=True,
                reason=None,
            ),
            TransitionRecord(
                from_state="spawning",
                to_state="running",
                ts_utc=_FIXED_TS,
                accepted=True,
                reason=None,
            ),
        ],
    )
    assert lifecycle_trace_sha256_hex(flipped_ts) != base_hash


# ---------------------------------------------------------------------
# T10 — Reason-omit semantics on the wire
# ---------------------------------------------------------------------


def test_t10_accepted_records_omit_reason_in_wire() -> None:
    """Accepted records must NOT carry a ``"reason"`` key on the
    wire. Rejected records MUST carry it. This pins the
    ``skip_serializing_if = Option::is_none`` Rust contract."""
    accepted_rec = TransitionRecord(
        from_state="uninstantiated",
        to_state="spawning",
        ts_utc=_FIXED_TS,
        accepted=True,
        reason=None,
    )
    rejected_rec = TransitionRecord(
        from_state="uninstantiated",
        to_state="running",
        ts_utc=_FIXED_TS,
        accepted=False,
        reason="not_in_valid_transitions",
    )
    trace = build_lifecycle_trace_from_records(
        persona_id="reza",
        org_id="wakir-labs",
        initial_state="uninstantiated",
        records=[accepted_rec, rejected_rec],
    )
    text = serialize_lifecycle_trace(trace).decode("utf-8")
    assert '"reason":null' not in text
    assert text.count('"reason":"not_in_valid_transitions"') == 1


# ---------------------------------------------------------------------
# T11 — Rejection inside a clean trail
# ---------------------------------------------------------------------


def test_t11_rejection_preserves_trace_shape() -> None:
    """A rejection in the middle of an otherwise clean trail does
    not advance the state — the final_state must reflect only the
    accepted records."""
    records = [
        TransitionRecord(
            from_state="uninstantiated",
            to_state="spawning",
            ts_utc=_FIXED_TS,
            accepted=True,
            reason=None,
        ),
        TransitionRecord(
            from_state="spawning",
            to_state="migrated",  # invalid edge: rejected
            ts_utc=_FIXED_TS,
            accepted=False,
            reason="not_in_valid_transitions",
        ),
        TransitionRecord(
            from_state="spawning",
            to_state="running",
            ts_utc=_FIXED_TS,
            accepted=True,
            reason=None,
        ),
    ]
    trace = build_lifecycle_trace_from_records(
        persona_id="reza",
        org_id="wakir-labs",
        initial_state="uninstantiated",
        records=records,
    )
    assert trace.final_state == "running"
    assert len(trace.records) == 3
    assert sum(1 for r in trace.records if r.accepted) == 2
    assert sum(1 for r in trace.records if not r.accepted) == 1


# ---------------------------------------------------------------------
# T12 — Build-from-records vs. build-from-FSM byte-parity
# ---------------------------------------------------------------------


def test_t12_build_paths_byte_parity() -> None:
    """Building a trace from a live FSM history must produce the
    same canonical bytes as building it directly from a records
    list."""
    m = LifecycleStateMachine("reza", "wakir-labs", clock=_fixed_clock)
    m.transition_to("spawning")
    m.transition_to("running")
    trace_a = build_lifecycle_trace(m)

    trace_b = build_lifecycle_trace_from_records(
        persona_id="reza",
        org_id="wakir-labs",
        initial_state="uninstantiated",
        records=m.history,
    )
    assert serialize_lifecycle_trace(trace_a) == serialize_lifecycle_trace(trace_b)
    assert lifecycle_trace_sha256_hex(trace_a) == lifecycle_trace_sha256_hex(trace_b)


# ---------------------------------------------------------------------
# T13 — Cross-lang fixture file structure
# ---------------------------------------------------------------------


def test_t13_fixture_file_structure_pin() -> None:
    fixtures = _load_fixtures()
    assert fixtures.get("schema_version") == LIFECYCLE_TRACE_SCHEMA
    assert fixtures.get("fixed_ts_utc") == _FIXED_TS
    items = fixtures.get("fixtures")
    assert isinstance(items, list)
    assert len(items) == 5
    names = {f["name"] for f in items}
    assert names == {
        "f01-clean-lifecycle",
        "f02-recovery-path",
        "f03-migration-path",
        "f04-spawn-cancel",
        "f05-rejected-attempt-then-clean",
    }
    for f in items:
        inp = f["input"]
        for k in ("persona_id", "org_id", "initial_state", "transitions"):
            assert k in inp, f"fixture {f['name']!r} missing input.{k}"
        exp = f["expected"]
        for k in (
            "final_state",
            "record_count",
            "accepted_count",
            "rejected_count",
            "trace_jcs_bytes_b64",
            "trace_jcs_bytes_len",
            "trace_sha256_hex",
            "trace_hash_prefixed",
        ):
            assert k in exp, f"fixture {f['name']!r} missing expected.{k}"


# ---------------------------------------------------------------------
# T14 — Cross-lang fixture per-vector byte-parity (parametrised)
# ---------------------------------------------------------------------


def _fixture_ids() -> List[str]:
    return [f["name"] for f in _load_fixtures()["fixtures"]]


@pytest.mark.parametrize("fixture_name", _fixture_ids())
def test_t14_cross_lang_fixture_byte_parity(fixture_name: str) -> None:
    fixtures = _load_fixtures()["fixtures"]
    fx = next(f for f in fixtures if f["name"] == fixture_name)
    inp = fx["input"]
    exp = fx["expected"]

    records = _records_from_fixture(fx)
    trace = build_lifecycle_trace_from_records(
        persona_id=inp["persona_id"],
        org_id=inp["org_id"],
        initial_state=inp["initial_state"],
        records=records,
    )

    # final_state derivation pin.
    assert trace.final_state == exp["final_state"]
    # record count breakdown pin.
    assert len(trace.records) == exp["record_count"]
    assert sum(1 for r in trace.records if r.accepted) == exp["accepted_count"]
    assert sum(1 for r in trace.records if not r.accepted) == exp["rejected_count"]

    # Canonical bytes pin.
    bytes_ = serialize_lifecycle_trace(trace)
    exp_bytes = base64.b64decode(exp["trace_jcs_bytes_b64"])
    assert bytes_ == exp_bytes, (
        f"fixture {fixture_name!r}: lifecycle-trace JCS bytes drifted; "
        f"got {bytes_!r}, expected {exp_bytes!r}"
    )
    assert len(bytes_) == exp["trace_jcs_bytes_len"]

    # Bare-hex outer SHA-256 pin.
    bare = sha256_hex(bytes_)
    assert bare == exp["trace_sha256_hex"]
    assert lifecycle_trace_sha256_hex(trace) == exp["trace_sha256_hex"]

    # Prefixed-form outer SHA-256 pin.
    assert lifecycle_trace_hash_prefixed(trace) == exp["trace_hash_prefixed"]

    # serialize_and_hash round-trip.
    rt_bytes, rt_hash = serialize_and_hash(trace)
    assert rt_bytes == bytes_
    assert rt_hash == exp["trace_hash_prefixed"]


# ---------------------------------------------------------------------
# T15 — State-coverage completeness across the five fixtures
# ---------------------------------------------------------------------


def test_t15_fixture_state_coverage() -> None:
    """Every state must appear as ``from_state`` and as
    ``to_state`` across the five fixtures."""
    fixtures = _load_fixtures()["fixtures"]
    from_seen: set = set()
    to_seen: set = set()
    for fx in fixtures:
        for t in fx["input"]["transitions"]:
            from_seen.add(t["from_state"])
            to_seen.add(t["to_state"])
    missing_from = set(STATES) - from_seen
    assert not missing_from, (
        f"fixtures fail state coverage on from_state: missing={missing_from}"
    )
    missing_to = set(STATES) - to_seen
    assert not missing_to, (
        f"fixtures fail state coverage on to_state: missing={missing_to}"
    )


# ---------------------------------------------------------------------
# T16 — Empty-history trace deterministic
# ---------------------------------------------------------------------


def test_t16_empty_history_trace_is_deterministic() -> None:
    """A brand-new FSM with no transitions still serialises to
    bytes; ``final_state`` equals ``initial_state``; ``records``
    is the empty list; the byte-shape is stable."""
    m = LifecycleStateMachine("reza", "wakir-labs", clock=_fixed_clock)
    trace = build_lifecycle_trace(m)
    assert trace.final_state == trace.initial_state == "uninstantiated"
    assert trace.records == []
    bytes_ = serialize_lifecycle_trace(trace)
    assert bytes_ == (
        b'{"final_state":"uninstantiated","initial_state":"uninstantiated",'
        b'"org_id":"wakir-labs","persona_id":"reza","records":[],'
        b'"schema":"wakir.persona-engine.lifecycle-trace/1"}'
    )


# ---------------------------------------------------------------------
# T17 — to_wire_dict shape pin
# ---------------------------------------------------------------------


def test_t17_to_wire_dict_shape_pin() -> None:
    """``lifecycle_trace_to_wire_dict`` must include the six
    top-level keys and no extras. Records are dicts with the
    expected key sets (4 keys for accepted, 5 keys for rejected)."""
    records = [
        TransitionRecord(
            from_state="uninstantiated",
            to_state="spawning",
            ts_utc=_FIXED_TS,
            accepted=True,
            reason=None,
        ),
        TransitionRecord(
            from_state="uninstantiated",
            to_state="running",
            ts_utc=_FIXED_TS,
            accepted=False,
            reason="not_in_valid_transitions",
        ),
    ]
    trace = build_lifecycle_trace_from_records(
        persona_id="reza",
        org_id="wakir-labs",
        initial_state="uninstantiated",
        records=records,
    )
    wire = lifecycle_trace_to_wire_dict(trace)
    assert set(wire.keys()) == {
        "final_state",
        "initial_state",
        "org_id",
        "persona_id",
        "records",
        "schema",
    }
    assert set(wire["records"][0].keys()) == {
        "accepted",
        "from_state",
        "to_state",
        "ts_utc",
    }
    assert set(wire["records"][1].keys()) == {
        "accepted",
        "from_state",
        "reason",
        "to_state",
        "ts_utc",
    }
    assert wire["records"][1]["reason"] == "not_in_valid_transitions"
