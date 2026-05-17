# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-lang parity tests for the persona-engine anchor-emitter.

The Python module under test
(:mod:`wirelang.persona_engine.anchor_emitter`) is BUSL-1.1; the
tests themselves are Apache-2.0 so downstream re-implementers can
re-use the same vectors.

Test taxonomy
-------------

- T01 — Constants pin: ``ENVELOPE_SCHEMA`` / ``HASH_PREFIX`` /
  ``SHA256_HEX_LEN`` match the Rust crate's ``pub const`` items.
- T02 — Spec invariants hold (mirror of Rust crate).
- T03 — Happy-path build: fields round-trip verbatim.
- T04 — Empty-field rejections: each required field raises
  :class:`EmptyFieldError` with the documented field name.
- T05 — Timestamp-shape rejection: all three Rust-side rejected
  shapes (space-not-T, missing-Z, sub-second) raise
  :class:`BadTimestampShapeError`.
- T06 — Determinism: two builds of the same input produce
  byte-identical canonical output.
- T07 — Hash prefix + shape: ``hash_anchor`` returns
  ``"sha256:"`` + 64 lower-case hex chars.
- T08 — Wire-shape key order: JCS canonical output has the five
  keys in lex order.
- T09 — Wire-shape embedded hash equals :func:`sha256_hex` over
  the same payload bytes (bridge to bare-hex Python form).
- T10 — :func:`serialize_and_hash` matches the individual calls
  byte-for-byte.
- T11 — Sensitivity: a payload byte change flips the outer hash.
- T12 — Sensitivity: an ``event_id`` change flips the outer hash
  but NOT the embedded ``payload_sha256``.
- T13 — Cross-lang fixture pin: all five fixture envelopes from
  ``tests/fixtures/anchor-emitter-cross-lang/fixtures.json``
  produce the pinned canonical bytes + envelope-hash +
  payload-hash; this is the authoritative byte-level
  parity check against the Rust sibling.
- T14 — Cross-lang fixture pin sweep (parametrised): same as T13
  but per-fixture for finer-grained failure isolation.

Pinning procedure
-----------------

If a wire-shape change is intentional:

1. Update the Rust crate's wire-shape (struct fields / serialiser).
2. Re-derive the fixtures by running the procedure documented at
   the top of ``tests/fixtures/anchor-emitter-cross-lang/fixtures.json``.
3. Update both Python and Rust test suites in the same PR.

If a wire-shape change is accidental, the cross-lang fixture test
(T13/T14) fires on both sides, which is the intended boundary
detector.
"""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
from typing import Any, Dict, List

import pytest

from wirelang.persona_engine.anchor_emitter import (
    AnchorEmitterInput,
    AnchorEnvelope,
    BadTimestampShapeError,
    ENVELOPE_SCHEMA,
    EmptyFieldError,
    HASH_PREFIX,
    SHA256_HEX_LEN,
    _test_only_wire_value,
    assert_spec_invariants,
    build_anchor_envelope,
    hash_anchor,
    serialize_and_hash,
    serialize_anchor,
    sha256_hex,
)


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FIXTURE_PATH = (
    _REPO_ROOT
    / "tests"
    / "fixtures"
    / "anchor-emitter-cross-lang"
    / "fixtures.json"
)


def _load_fixture_vectors() -> List[Dict[str, Any]]:
    raw = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert raw["schema_version"] == ENVELOPE_SCHEMA, (
        f"fixture schema {raw['schema_version']!r} drifted from module "
        f"constant {ENVELOPE_SCHEMA!r}"
    )
    return raw["fixtures"]


def _baseline_input() -> AnchorEmitterInput:
    """Shared in-test baseline input.

    Matches fixture f01-empty-object so unit-level tests and
    cross-lang fixture tests cross-pin each other for the
    canonical envelope.
    """
    return AnchorEmitterInput(
        event_id="evt-2026-05-17-anchor-fixture-01",
        timestamp_utc="2026-05-17T00:00:00Z",
        persona_id="reza",
        payload_jcs_bytes=b"{}",
    )


# ---------------------------------------------------------------------------
# T01 — Constants pin.
# ---------------------------------------------------------------------------


def test_t01_constants_pin():
    assert ENVELOPE_SCHEMA == "wakir.wat.anchor-envelope/1"
    assert HASH_PREFIX == "sha256:"
    assert SHA256_HEX_LEN == 64


# ---------------------------------------------------------------------------
# T02 — Spec invariants hold.
# ---------------------------------------------------------------------------


def test_t02_spec_invariants_hold():
    # Should not raise.
    assert_spec_invariants()


# ---------------------------------------------------------------------------
# T03 — Happy-path build: fields round-trip verbatim.
# ---------------------------------------------------------------------------


def test_t03_happy_path_build_round_trip():
    inp = _baseline_input()
    env = build_anchor_envelope(inp)
    assert isinstance(env, AnchorEnvelope)
    assert env.event_id == inp.event_id
    assert env.timestamp_utc == inp.timestamp_utc
    assert env.persona_id == inp.persona_id
    assert env.payload_jcs_bytes == inp.payload_jcs_bytes


# ---------------------------------------------------------------------------
# T04 — Empty-field rejections.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, value",
    [
        ("event_id", ""),
        ("event_id", "   "),
        ("persona_id", ""),
        ("persona_id", "\t\n"),
        ("timestamp_utc", ""),
    ],
)
def test_t04_empty_field_rejections(field, value):
    kwargs = dict(
        event_id="evt-x",
        timestamp_utc="2026-05-17T00:00:00Z",
        persona_id="reza",
        payload_jcs_bytes=b"{}",
    )
    kwargs[field] = value
    inp = AnchorEmitterInput(**kwargs)
    with pytest.raises(EmptyFieldError) as exc:
        build_anchor_envelope(inp)
    assert exc.value.field == field


# ---------------------------------------------------------------------------
# T05 — Timestamp-shape rejection.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ts",
    [
        "2026-05-17 00:00:00Z",   # space not T
        "2026-05-17T00:00:00",    # missing Z
        "2026-05-17T00:00:00.5Z",  # sub-second precision
        "2026-05-17T00:00:00+00:00",  # offset form, not Z
        "26-05-17T00:00:00Z",     # 2-digit year
    ],
)
def test_t05_bad_timestamp_shape_rejected(ts):
    inp = AnchorEmitterInput(
        event_id="evt-x",
        timestamp_utc=ts,
        persona_id="reza",
        payload_jcs_bytes=b"{}",
    )
    with pytest.raises(BadTimestampShapeError) as exc:
        build_anchor_envelope(inp)
    assert exc.value.value == ts


# ---------------------------------------------------------------------------
# T06 — Determinism: two builds produce byte-identical canonical
# output.
# ---------------------------------------------------------------------------


def test_t06_determinism_byte_identical():
    a = build_anchor_envelope(_baseline_input())
    b = build_anchor_envelope(_baseline_input())
    assert serialize_anchor(a) == serialize_anchor(b)
    assert hash_anchor(a) == hash_anchor(b)


# ---------------------------------------------------------------------------
# T07 — Hash prefix + shape.
# ---------------------------------------------------------------------------


def test_t07_hash_prefix_and_shape():
    env = build_anchor_envelope(_baseline_input())
    h = hash_anchor(env)
    assert h.startswith("sha256:"), f"missing prefix: {h!r}"
    tail = h[len(HASH_PREFIX):]
    assert len(tail) == SHA256_HEX_LEN, (
        f"hex tail wrong length: {tail!r}"
    )
    assert all(c in "0123456789abcdef" for c in tail), (
        f"hex tail must be lower-case ASCII hex: {tail!r}"
    )


# ---------------------------------------------------------------------------
# T08 — Wire-shape key order pinned to JCS lex order.
# ---------------------------------------------------------------------------


def test_t08_wire_shape_key_order_pinned():
    env = build_anchor_envelope(_baseline_input())
    bytes_ = serialize_anchor(env)
    text = bytes_.decode("utf-8")
    keys = [
        '"event_id"',
        '"payload_sha256"',
        '"persona_id"',
        '"schema"',
        '"timestamp_utc"',
    ]
    positions = [text.find(k) for k in keys]
    for k, p in zip(keys, positions):
        assert p >= 0, f"key {k} missing from wire output: {text!r}"
    assert positions == sorted(positions), (
        f"wire-shape keys not in lex order; got positions {positions} "
        f"in {text!r}"
    )


# ---------------------------------------------------------------------------
# T09 — Wire-shape embedded hash equals sha256_hex(payload_bytes).
# ---------------------------------------------------------------------------


def test_t09_wire_shape_embedded_payload_hash_matches_helper():
    env = build_anchor_envelope(_baseline_input())
    wire = _test_only_wire_value(env)
    embedded = wire["payload_sha256"]
    direct = sha256_hex(env.payload_jcs_bytes)
    assert embedded == direct, (
        f"embedded payload_sha256 ({embedded!r}) drifted from direct "
        f"sha256_hex(payload_bytes) ({direct!r})"
    )


# ---------------------------------------------------------------------------
# T10 — serialize_and_hash matches individual calls.
# ---------------------------------------------------------------------------


def test_t10_serialize_and_hash_matches_individual_calls():
    env = build_anchor_envelope(_baseline_input())
    bytes_combined, hash_combined = serialize_and_hash(env)
    bytes_solo = serialize_anchor(env)
    hash_solo = hash_anchor(env)
    assert bytes_combined == bytes_solo
    assert hash_combined == hash_solo


# ---------------------------------------------------------------------------
# T11 — Sensitivity: a payload byte change flips the outer hash.
# ---------------------------------------------------------------------------


def test_t11_payload_change_flips_hash():
    env_a = build_anchor_envelope(_baseline_input())
    inp_b = AnchorEmitterInput(
        event_id="evt-2026-05-17-anchor-fixture-01",
        timestamp_utc="2026-05-17T00:00:00Z",
        persona_id="reza",
        payload_jcs_bytes=b"{ }",
    )
    env_b = build_anchor_envelope(inp_b)
    assert hash_anchor(env_a) != hash_anchor(env_b), (
        "anchor hash must reflect payload changes"
    )
    assert serialize_anchor(env_a) != serialize_anchor(env_b), (
        "canonical bytes must reflect payload changes"
    )


# ---------------------------------------------------------------------------
# T12 — Sensitivity: event_id change isolates payload hash.
# ---------------------------------------------------------------------------


def test_t12_event_id_change_isolates_payload_hash():
    env_a = build_anchor_envelope(_baseline_input())
    inp_b = AnchorEmitterInput(
        event_id="evt-2026-05-17-anchor-fixture-02",
        timestamp_utc="2026-05-17T00:00:00Z",
        persona_id="reza",
        payload_jcs_bytes=b"{}",
    )
    env_b = build_anchor_envelope(inp_b)
    assert serialize_anchor(env_a) != serialize_anchor(env_b)
    assert hash_anchor(env_a) != hash_anchor(env_b)
    wa = _test_only_wire_value(env_a)
    wb = _test_only_wire_value(env_b)
    assert wa["payload_sha256"] == wb["payload_sha256"], (
        "payload_sha256 must NOT depend on event_id"
    )


# ---------------------------------------------------------------------------
# T13 — Cross-lang fixture file exists + structure pin.
# ---------------------------------------------------------------------------


def test_t13_cross_lang_fixture_file_present_and_structured():
    fixtures = _load_fixture_vectors()
    assert len(fixtures) >= 5, (
        f"expected >=5 cross-lang fixtures, got {len(fixtures)}"
    )
    seen_names = set()
    for fx in fixtures:
        assert "name" in fx and isinstance(fx["name"], str)
        assert fx["name"] not in seen_names, (
            f"duplicate fixture name {fx['name']!r}"
        )
        seen_names.add(fx["name"])
        inp = fx["input"]
        for k in ("event_id", "timestamp_utc", "persona_id",
                  "payload_jcs_bytes_b64"):
            assert k in inp, f"fixture {fx['name']!r} missing input.{k}"
        exp = fx["expected"]
        for k in ("payload_sha256_hex", "envelope_jcs_bytes_b64",
                  "envelope_jcs_bytes_len", "envelope_sha256_hex",
                  "envelope_hash_prefixed"):
            assert k in exp, f"fixture {fx['name']!r} missing expected.{k}"


# ---------------------------------------------------------------------------
# T14 — Cross-lang fixture vector parity (parametrised per fixture).
#
# This is the AUTHORITATIVE byte-level cross-lang pin. The Rust
# sibling test consumes the same JSON file and pins the same
# envelope_jcs_bytes / envelope_sha256_hex / payload_sha256_hex tuples
# against the Rust emitter's output. If this test fires on either
# side, the wire-shape has drifted.
# ---------------------------------------------------------------------------


_FIXTURE_VECTORS = _load_fixture_vectors()


@pytest.mark.parametrize(
    "fixture",
    _FIXTURE_VECTORS,
    ids=[fx["name"] for fx in _FIXTURE_VECTORS],
)
def test_t14_cross_lang_fixture_vector_pin(fixture):
    inp_blob = fixture["input"]
    exp = fixture["expected"]
    payload_bytes = base64.b64decode(inp_blob["payload_jcs_bytes_b64"])
    inp = AnchorEmitterInput(
        event_id=inp_blob["event_id"],
        timestamp_utc=inp_blob["timestamp_utc"],
        persona_id=inp_blob["persona_id"],
        payload_jcs_bytes=payload_bytes,
    )
    env = build_anchor_envelope(inp)

    # Payload hash (bare hex) pin.
    assert sha256_hex(env.payload_jcs_bytes) == exp["payload_sha256_hex"], (
        f"fixture {fixture['name']!r}: payload_sha256_hex drifted"
    )

    # Envelope canonical bytes pin (byte-for-byte against Rust output).
    expected_bytes = base64.b64decode(exp["envelope_jcs_bytes_b64"])
    actual_bytes = serialize_anchor(env)
    assert actual_bytes == expected_bytes, (
        f"fixture {fixture['name']!r}: envelope JCS bytes drifted. "
        f"expected {expected_bytes!r}, got {actual_bytes!r}"
    )
    assert len(actual_bytes) == exp["envelope_jcs_bytes_len"], (
        f"fixture {fixture['name']!r}: envelope JCS bytes length drifted"
    )

    # Outer envelope hash (bare hex) pin.
    actual_envelope_sha = hashlib.sha256(actual_bytes).hexdigest()
    assert actual_envelope_sha == exp["envelope_sha256_hex"], (
        f"fixture {fixture['name']!r}: envelope_sha256_hex drifted"
    )

    # Outer envelope hash (prefixed) pin via hash_anchor.
    assert hash_anchor(env) == exp["envelope_hash_prefixed"], (
        f"fixture {fixture['name']!r}: hash_anchor prefixed-form drifted"
    )

    # serialize_and_hash consistency on the fixture path.
    combined_bytes, combined_hash = serialize_and_hash(env)
    assert combined_bytes == actual_bytes
    assert combined_hash == exp["envelope_hash_prefixed"]


# ---------------------------------------------------------------------------
# T15 — sha256_hex helper rejects non-bytes input.
# ---------------------------------------------------------------------------


def test_t15_sha256_hex_rejects_non_bytes():
    with pytest.raises(TypeError):
        sha256_hex("not bytes")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        sha256_hex(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# T16 — build_anchor_envelope rejects non-AnchorEmitterInput.
# ---------------------------------------------------------------------------


def test_t16_build_rejects_non_input_type():
    with pytest.raises(TypeError):
        build_anchor_envelope({"event_id": "x"})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        build_anchor_envelope(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# T17 — Empty payload is legal; produces well-known empty-bytes hash.
# ---------------------------------------------------------------------------


def test_t17_empty_payload_is_legal():
    inp = AnchorEmitterInput(
        event_id="evt-x",
        timestamp_utc="2026-05-17T00:00:00Z",
        persona_id="reza",
        payload_jcs_bytes=b"",
    )
    env = build_anchor_envelope(inp)
    # SHA-256("") well-known constant.
    assert sha256_hex(env.payload_jcs_bytes) == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    # hash_anchor still produces a valid prefixed form.
    h = hash_anchor(env)
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64
