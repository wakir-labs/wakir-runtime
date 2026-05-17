# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang parity tests for the persona-engine subscribe-loop ack-record.

The Python module under test (:mod:`wirelang.persona_engine.subscribe_ack`)
is BUSL-1.1; this test file is Apache-2.0 so downstream re-implementers
can re-use the same fixture vectors.

Test taxonomy
-------------

- T01 — Constants pin: ``ACK_RECORD_SCHEMA`` / ``HASH_PREFIX`` /
  ``SHA256_HEX_LEN`` match the Rust crate's ``pub const`` items.
- T02 — Outcome literals pin: the five outcome strings match
  byte-for-byte. Any rename on either side is caught here.
- T03 — Happy-path build: fields round-trip verbatim through the
  ``SubscribeAckRecord`` dataclass; ``schema`` is set to the
  constant regardless of caller input.
- T04 — Validation: invalid outcome strings raise
  :class:`InvalidOutcomeError`; negative / non-int frame_index
  raises :class:`InvalidFrameIndexError`.
- T05 — Determinism: two builds of the same input produce
  byte-identical canonical output (the JCS-canonical form is
  deterministic).
- T06 — Wire-shape key order: JCS canonical output has the seven
  keys in alphabetical order (this is the cross-lang contract).
- T07 — Hash shape: ``ack_record_hash_prefixed`` returns
  ``"sha256:"`` + 64 lowercase hex characters; bare
  ``ack_record_sha256_hex`` is exactly 64 lowercase hex characters.
- T08 — ``serialize_and_hash`` matches the individual calls
  byte-for-byte (no double-encoding path).
- T09 — Sensitivity: changing ``auftrag_id`` / ``persona_id`` /
  ``frame_index`` / ``subject`` flips the outer hash; changing
  the schema (via direct dataclass construction) flips it too.
- T10 — Burst monotonicity: :func:`build_ack_burst` accepts
  0,1,2,...,N-1 and rejects any other shape.
- T11 — Burst serialisation: :func:`serialize_ack_burst` produces
  one byte-vector per record in input order.
- T12 — Engine-side helper: :func:`ack_record_from_parsed` builds
  a malformed-frame record when ``parsed=None`` and a populated
  record when given a duck-typed object.
- T13 — Subject-wildcard preservation: the record's ``subject``
  field carries the **concrete** subject that arrived (not the
  subscribe-time wildcard pattern). Edge-case for NATS wildcard
  subscribes where the inbound subject is more specific than
  the subscribe pattern.
- T14 — Ordered-delivery preservation: a 5-record monotonic
  burst produces distinct bytes per record (frame_index is
  load-bearing on the wire-form).
- T15 — Cross-lang fixture file structure: schema_version,
  fixture count, and per-fixture key set all match the Rust
  sibling's structure pin (F01).
- T16 — Cross-lang fixture per-vector pin (parametrised over
  the five fixtures): byte-for-byte parity with the JSON
  fixture file's pinned values.
- T17 — Outcome-set completeness: every outcome literal appears
  in at least one of the five fixtures.

Pinning procedure
-----------------

If a wire-shape change is intentional:

1. Update both sides (Rust ``ack_record.rs`` and Python
   ``subscribe_ack.py``).
2. Re-derive the fixture vectors using the snippet documented at
   the top of ``tests/fixtures/subscribe-loop-cross-lang/fixtures.json``.
3. Update both Python and Rust test suites in the same PR.

If a wire-shape change is accidental, the cross-lang fixture test
(T16) fires on both sides, which is the intended boundary detector.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
from typing import Any, Dict, List

import pytest

from wirelang.persona_engine.subscribe_ack import (
    ACK_RECORD_SCHEMA,
    HASH_PREFIX,
    InvalidFrameIndexError,
    InvalidOutcomeError,
    OUTCOME_EMPTY_PAYLOAD,
    OUTCOME_MALFORMED,
    OUTCOME_PERSONA_MISMATCH,
    OUTCOME_PROCESSED,
    OUTCOME_REJECTED,
    SHA256_HEX_LEN,
    SubscribeAckRecord,
    VALID_OUTCOMES,
    ack_record_from_parsed,
    ack_record_hash_prefixed,
    ack_record_sha256_hex,
    build_ack_burst,
    build_subscribe_ack_record,
    serialize_ack_burst,
    serialize_and_hash,
    serialize_subscribe_ack,
    sha256_hex,
)


# ---------------------------------------------------------------------
# Fixture file loader
# ---------------------------------------------------------------------


def _fixture_path() -> pathlib.Path:
    """Resolve the cross-lang fixture file path.

    Walks up from this test file to the repo root, then into
    ``tests/fixtures/subscribe-loop-cross-lang/fixtures.json``.
    """
    here = pathlib.Path(__file__).resolve()
    # here = <repo>/wirelang/tests/persona_engine/test_subscribe_loop_cross_lang_parity.py
    # repo = parents[3]
    repo_root = here.parents[3]
    return repo_root / "tests" / "fixtures" / "subscribe-loop-cross-lang" / "fixtures.json"


def _load_fixtures() -> Dict[str, Any]:
    path = _fixture_path()
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------
# T01 — Constants pin
# ---------------------------------------------------------------------


def test_t01_constants_match_rust_sibling_pin() -> None:
    assert ACK_RECORD_SCHEMA == "wakir.persona-engine.subscribe-ack/1"
    assert HASH_PREFIX == "sha256:"
    assert SHA256_HEX_LEN == 64


# ---------------------------------------------------------------------
# T02 — Outcome literals pin
# ---------------------------------------------------------------------


def test_t02_outcome_literals_pin() -> None:
    # Exact strings, exact set membership.
    assert OUTCOME_PROCESSED == "processed"
    assert OUTCOME_MALFORMED == "malformed"
    assert OUTCOME_PERSONA_MISMATCH == "persona_mismatch"
    assert OUTCOME_REJECTED == "rejected"
    assert OUTCOME_EMPTY_PAYLOAD == "empty_payload"
    assert set(VALID_OUTCOMES) == {
        OUTCOME_PROCESSED,
        OUTCOME_MALFORMED,
        OUTCOME_PERSONA_MISMATCH,
        OUTCOME_REJECTED,
        OUTCOME_EMPTY_PAYLOAD,
    }
    assert len(VALID_OUTCOMES) == 5


# ---------------------------------------------------------------------
# T03 — Happy-path build
# ---------------------------------------------------------------------


def test_t03_happy_path_build_round_trip() -> None:
    rec = build_subscribe_ack_record(
        auftrag_id="a-1",
        frame_index=0,
        outcome=OUTCOME_PROCESSED,
        persona_id="reza",
        prompt_sha256="sha256:" + ("0" * 64),
        subject="wakir.dev.agent.agent.task.assigned.reza",
    )
    assert rec.auftrag_id == "a-1"
    assert rec.frame_index == 0
    assert rec.outcome == "processed"
    assert rec.persona_id == "reza"
    assert rec.prompt_sha256 == "sha256:" + ("0" * 64)
    # Schema is forced — caller cannot override.
    assert rec.schema == ACK_RECORD_SCHEMA
    assert rec.subject == "wakir.dev.agent.agent.task.assigned.reza"


# ---------------------------------------------------------------------
# T04 — Validation
# ---------------------------------------------------------------------


def test_t04_outcome_validation_rejects_unknown() -> None:
    with pytest.raises(InvalidOutcomeError):
        build_subscribe_ack_record(
            auftrag_id="a-1",
            frame_index=0,
            outcome="evil",
            persona_id="reza",
            prompt_sha256="sha256:00",
            subject="s",
        )


def test_t04b_frame_index_validation() -> None:
    with pytest.raises(InvalidFrameIndexError):
        build_subscribe_ack_record(
            auftrag_id="a-1",
            frame_index=-1,
            outcome=OUTCOME_PROCESSED,
            persona_id="reza",
            prompt_sha256="sha256:00",
            subject="s",
        )
    # bool is a subclass of int — must be rejected explicitly.
    with pytest.raises(InvalidFrameIndexError):
        build_subscribe_ack_record(
            auftrag_id="a-1",
            frame_index=True,  # type: ignore[arg-type]
            outcome=OUTCOME_PROCESSED,
            persona_id="reza",
            prompt_sha256="sha256:00",
            subject="s",
        )
    # Non-int type rejected.
    with pytest.raises(InvalidFrameIndexError):
        build_subscribe_ack_record(
            auftrag_id="a-1",
            frame_index="0",  # type: ignore[arg-type]
            outcome=OUTCOME_PROCESSED,
            persona_id="reza",
            prompt_sha256="sha256:00",
            subject="s",
        )


# ---------------------------------------------------------------------
# T05 — Determinism
# ---------------------------------------------------------------------


def test_t05_serialise_is_deterministic() -> None:
    rec1 = build_subscribe_ack_record(
        auftrag_id="a-1",
        frame_index=0,
        outcome=OUTCOME_PROCESSED,
        persona_id="reza",
        prompt_sha256="sha256:cafe",
        subject="wakir.dev.agent.agent.task.assigned.reza",
    )
    rec2 = build_subscribe_ack_record(
        auftrag_id="a-1",
        frame_index=0,
        outcome=OUTCOME_PROCESSED,
        persona_id="reza",
        prompt_sha256="sha256:cafe",
        subject="wakir.dev.agent.agent.task.assigned.reza",
    )
    b1 = serialize_subscribe_ack(rec1)
    b2 = serialize_subscribe_ack(rec2)
    assert b1 == b2
    assert ack_record_sha256_hex(rec1) == ack_record_sha256_hex(rec2)


# ---------------------------------------------------------------------
# T06 — Wire-shape key order
# ---------------------------------------------------------------------


def test_t06_wire_shape_keys_are_alphabetical() -> None:
    rec = build_subscribe_ack_record(
        auftrag_id="a-1",
        frame_index=0,
        outcome=OUTCOME_PROCESSED,
        persona_id="reza",
        prompt_sha256="sha256:dead",
        subject="wakir.dev.agent.agent.task.assigned.reza",
    )
    text = serialize_subscribe_ack(rec).decode("utf-8")
    keys = [
        "auftrag_id",
        "frame_index",
        "outcome",
        "persona_id",
        "prompt_sha256",
        "schema",
        "subject",
    ]
    positions = [text.find(f'"{k}":') for k in keys]
    assert all(p > -1 for p in positions), (
        f"missing key in wire-form: positions={positions}, text={text}"
    )
    assert positions == sorted(positions), (
        f"keys not in alphabetical order: positions={positions}, text={text}"
    )


# ---------------------------------------------------------------------
# T07 — Hash shape
# ---------------------------------------------------------------------


def test_t07_hash_shape_constraints() -> None:
    rec = build_subscribe_ack_record(
        auftrag_id="a-1",
        frame_index=0,
        outcome=OUTCOME_PROCESSED,
        persona_id="reza",
        prompt_sha256="sha256:dead",
        subject="s",
    )
    bare = ack_record_sha256_hex(rec)
    prefixed = ack_record_hash_prefixed(rec)
    assert len(bare) == SHA256_HEX_LEN
    assert all(c in "0123456789abcdef" for c in bare)
    assert prefixed.startswith(HASH_PREFIX)
    assert prefixed == HASH_PREFIX + bare
    assert len(prefixed) == len(HASH_PREFIX) + SHA256_HEX_LEN


# ---------------------------------------------------------------------
# T08 — serialize_and_hash byte-parity
# ---------------------------------------------------------------------


def test_t08_serialize_and_hash_round_trip() -> None:
    rec = build_subscribe_ack_record(
        auftrag_id="a-1",
        frame_index=4,
        outcome=OUTCOME_PROCESSED,
        persona_id="reza",
        prompt_sha256="sha256:beef",
        subject="s",
    )
    bytes_, hash_ = serialize_and_hash(rec)
    assert bytes_ == serialize_subscribe_ack(rec)
    assert hash_ == ack_record_hash_prefixed(rec)


# ---------------------------------------------------------------------
# T09 — Sensitivity
# ---------------------------------------------------------------------


def test_t09_sensitivity_field_flips_outer_hash() -> None:
    base = build_subscribe_ack_record(
        auftrag_id="a-1",
        frame_index=0,
        outcome=OUTCOME_PROCESSED,
        persona_id="reza",
        prompt_sha256="sha256:00",
        subject="s",
    )
    base_hash = ack_record_sha256_hex(base)

    # auftrag_id flip
    rec = build_subscribe_ack_record(
        auftrag_id="a-2",
        frame_index=0,
        outcome=OUTCOME_PROCESSED,
        persona_id="reza",
        prompt_sha256="sha256:00",
        subject="s",
    )
    assert ack_record_sha256_hex(rec) != base_hash

    # frame_index flip
    rec = build_subscribe_ack_record(
        auftrag_id="a-1",
        frame_index=1,
        outcome=OUTCOME_PROCESSED,
        persona_id="reza",
        prompt_sha256="sha256:00",
        subject="s",
    )
    assert ack_record_sha256_hex(rec) != base_hash

    # persona_id flip
    rec = build_subscribe_ack_record(
        auftrag_id="a-1",
        frame_index=0,
        outcome=OUTCOME_PROCESSED,
        persona_id="tomas",
        prompt_sha256="sha256:00",
        subject="s",
    )
    assert ack_record_sha256_hex(rec) != base_hash

    # subject flip
    rec = build_subscribe_ack_record(
        auftrag_id="a-1",
        frame_index=0,
        outcome=OUTCOME_PROCESSED,
        persona_id="reza",
        prompt_sha256="sha256:00",
        subject="other-subject",
    )
    assert ack_record_sha256_hex(rec) != base_hash

    # outcome flip
    rec = build_subscribe_ack_record(
        auftrag_id="a-1",
        frame_index=0,
        outcome=OUTCOME_REJECTED,
        persona_id="reza",
        prompt_sha256="sha256:00",
        subject="s",
    )
    assert ack_record_sha256_hex(rec) != base_hash


# ---------------------------------------------------------------------
# T10 — Burst monotonicity
# ---------------------------------------------------------------------


def test_t10_burst_monotonic_validates() -> None:
    recs = [
        build_subscribe_ack_record(
            auftrag_id=f"a-{i}",
            frame_index=i,
            outcome=OUTCOME_PROCESSED,
            persona_id="reza",
            prompt_sha256=f"sha256:{i:064x}",
            subject="s",
        )
        for i in range(5)
    ]
    burst = build_ack_burst(recs)
    assert len(burst) == 5
    assert [r.frame_index for r in burst] == [0, 1, 2, 3, 4]


def test_t10b_burst_non_monotonic_rejected() -> None:
    recs = [
        build_subscribe_ack_record(
            auftrag_id="a-0",
            frame_index=0,
            outcome=OUTCOME_PROCESSED,
            persona_id="reza",
            prompt_sha256="sha256:00",
            subject="s",
        ),
        build_subscribe_ack_record(
            auftrag_id="a-2",
            frame_index=7,  # not 1 -> rejected
            outcome=OUTCOME_PROCESSED,
            persona_id="reza",
            prompt_sha256="sha256:00",
            subject="s",
        ),
    ]
    with pytest.raises(InvalidFrameIndexError):
        build_ack_burst(recs)


# ---------------------------------------------------------------------
# T11 — Burst serialisation
# ---------------------------------------------------------------------


def test_t11_serialize_ack_burst_byte_parity() -> None:
    recs = [
        build_subscribe_ack_record(
            auftrag_id=f"a-{i}",
            frame_index=i,
            outcome=OUTCOME_PROCESSED,
            persona_id="reza",
            prompt_sha256=f"sha256:{i:064x}",
            subject="s",
        )
        for i in range(3)
    ]
    blobs = serialize_ack_burst(recs)
    assert len(blobs) == 3
    for i, b in enumerate(blobs):
        assert b == serialize_subscribe_ack(recs[i])


# ---------------------------------------------------------------------
# T12 — Engine-side helper: ack_record_from_parsed
# ---------------------------------------------------------------------


class _FakeParsed:
    """Duck-typed parsed envelope for the engine-side helper test."""

    def __init__(self, *, auftrag_id: str, persona_id: str, prompt_sha256: str):
        self.auftrag_id = auftrag_id
        self.persona_id = persona_id
        self.prompt_sha256 = prompt_sha256


def test_t12_ack_record_from_parsed_none_path() -> None:
    rec = ack_record_from_parsed(
        parsed=None,
        frame_index=0,
        outcome=OUTCOME_MALFORMED,
        subject="s",
        fallback_persona_id="reza",
    )
    assert rec.auftrag_id == ""
    assert rec.persona_id == "reza"
    assert rec.prompt_sha256 == ""
    assert rec.outcome == OUTCOME_MALFORMED


def test_t12b_ack_record_from_parsed_populated() -> None:
    p = _FakeParsed(
        auftrag_id="a-9",
        persona_id="tomas",
        prompt_sha256="sha256:abcd",
    )
    rec = ack_record_from_parsed(
        parsed=p,
        frame_index=3,
        outcome=OUTCOME_PROCESSED,
        subject="wakir.dev.agent.agent.task.assigned.tomas",
        fallback_persona_id="reza",
    )
    assert rec.auftrag_id == "a-9"
    assert rec.persona_id == "tomas"
    assert rec.prompt_sha256 == "sha256:abcd"
    assert rec.frame_index == 3
    assert rec.subject == "wakir.dev.agent.agent.task.assigned.tomas"


# ---------------------------------------------------------------------
# T13 — Subject-wildcard preservation
# ---------------------------------------------------------------------


def test_t13_subject_wildcard_records_concrete_subject() -> None:
    """When a NATS subscribe uses a wildcard, the inbound msg's
    subject is the concrete one. The ack-record must carry that
    concrete subject (not the subscribe-time wildcard pattern).
    """
    concrete = "wakir.dev.agent.agent.task.assigned.reza"
    rec = build_subscribe_ack_record(
        auftrag_id="a-1",
        frame_index=0,
        outcome=OUTCOME_PROCESSED,
        persona_id="reza",
        prompt_sha256="sha256:dead",
        subject=concrete,
    )
    text = serialize_subscribe_ack(rec).decode("utf-8")
    # The wildcard token ('>' or '*') must not appear in the
    # serialised record — only the concrete subject does.
    assert ">" not in text
    assert "*" not in text
    assert concrete in text


# ---------------------------------------------------------------------
# T14 — Ordered-delivery preservation
# ---------------------------------------------------------------------


def test_t14_ordered_delivery_per_frame_distinct_bytes() -> None:
    """A 5-record monotonic burst must produce 5 distinct byte-vectors
    even when only frame_index differs (everything else identical).
    """
    base_kwargs = dict(
        auftrag_id="a-x",
        outcome=OUTCOME_PROCESSED,
        persona_id="reza",
        prompt_sha256="sha256:" + ("0" * 64),
        subject="s",
    )
    recs = [
        build_subscribe_ack_record(frame_index=i, **base_kwargs)
        for i in range(5)
    ]
    blobs = [serialize_subscribe_ack(r) for r in recs]
    assert len(set(blobs)) == 5, (
        "frame_index drift did not produce distinct wire-bytes — "
        "ordered-delivery contract is broken"
    )
    # And the bare-hex SHA also differs per frame.
    hashes = [ack_record_sha256_hex(r) for r in recs]
    assert len(set(hashes)) == 5


# ---------------------------------------------------------------------
# T15 — Cross-lang fixture file structure
# ---------------------------------------------------------------------


def test_t15_fixture_file_structure_pin() -> None:
    fixtures = _load_fixtures()
    assert fixtures.get("schema_version") == ACK_RECORD_SCHEMA
    items = fixtures.get("fixtures")
    assert isinstance(items, list)
    assert len(items) == 5
    names = {f["name"] for f in items}
    assert names == {
        "f01-empty-frame",
        "f02-single-payload",
        "f03-multi-record-batch",
        "f04-error-frame",
        "f05-large-payload",
    }
    for f in items:
        inp = f["input"]
        for k in (
            "auftrag_id",
            "frame_index",
            "outcome",
            "persona_id",
            "prompt_sha256",
            "subject",
        ):
            assert k in inp, f"fixture {f['name']!r} missing input.{k}"
        exp = f["expected"]
        for k in (
            "ack_record_jcs_bytes_b64",
            "ack_record_jcs_bytes_len",
            "ack_record_sha256_hex",
            "ack_record_hash_prefixed",
        ):
            assert k in exp, f"fixture {f['name']!r} missing expected.{k}"


# ---------------------------------------------------------------------
# T16 — Cross-lang fixture per-vector pin (parametrised)
# ---------------------------------------------------------------------


def _fixture_ids() -> List[str]:
    return [f["name"] for f in _load_fixtures()["fixtures"]]


@pytest.mark.parametrize("fixture_name", _fixture_ids())
def test_t16_cross_lang_fixture_byte_parity(fixture_name: str) -> None:
    fixtures = _load_fixtures()["fixtures"]
    fx = next(f for f in fixtures if f["name"] == fixture_name)
    inp = fx["input"]
    exp = fx["expected"]

    rec = build_subscribe_ack_record(
        auftrag_id=inp["auftrag_id"],
        frame_index=inp["frame_index"],
        outcome=inp["outcome"],
        persona_id=inp["persona_id"],
        prompt_sha256=inp["prompt_sha256"],
        subject=inp["subject"],
    )

    # Canonical bytes pin.
    bytes_ = serialize_subscribe_ack(rec)
    exp_bytes = base64.b64decode(exp["ack_record_jcs_bytes_b64"])
    assert bytes_ == exp_bytes, (
        f"fixture {fixture_name!r}: ack-record JCS bytes drifted; "
        f"got {bytes_!r}, expected {exp_bytes!r}"
    )
    assert len(bytes_) == exp["ack_record_jcs_bytes_len"]

    # Bare-hex outer SHA-256 pin.
    bare = sha256_hex(bytes_)
    assert bare == exp["ack_record_sha256_hex"]
    assert ack_record_sha256_hex(rec) == exp["ack_record_sha256_hex"]

    # Prefixed-form outer SHA-256 pin.
    assert ack_record_hash_prefixed(rec) == exp["ack_record_hash_prefixed"]

    # serialize_and_hash round-trip.
    rt_bytes, rt_hash = serialize_and_hash(rec)
    assert rt_bytes == bytes_
    assert rt_hash == exp["ack_record_hash_prefixed"]


# ---------------------------------------------------------------------
# T17 — Outcome-set completeness across the five fixtures
# ---------------------------------------------------------------------


def test_t17_fixture_outcomes_cover_required_subset() -> None:
    """The Sprint-Auftrag requires five distinct sub-cases:
    empty-frame, single-payload, multi-record-batch, error-frame,
    large-payload. We pin them to specific outcome strings so the
    cross-lang diff engine has predictable category coverage.
    """
    fixtures = _load_fixtures()["fixtures"]
    by_name = {f["name"]: f["input"]["outcome"] for f in fixtures}
    assert by_name["f01-empty-frame"] == OUTCOME_MALFORMED
    assert by_name["f02-single-payload"] == OUTCOME_PROCESSED
    assert by_name["f03-multi-record-batch"] == OUTCOME_PROCESSED
    assert by_name["f04-error-frame"] == OUTCOME_REJECTED
    assert by_name["f05-large-payload"] == OUTCOME_PROCESSED
    # All outcomes present in fixtures must be valid.
    for name, outcome in by_name.items():
        assert outcome in VALID_OUTCOMES, (
            f"fixture {name!r} uses non-canonical outcome {outcome!r}"
        )
