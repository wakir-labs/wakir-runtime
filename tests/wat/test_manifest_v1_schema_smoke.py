# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Smoke-tests for the WAT hour-manifest v1 JSON-Schema (external-verifier substrate).

The schema under test (``wirelang/schemas/wakir-wat-manifest-v1.json``)
is the formal contract handed to third-party verifier implementers;
it is the v1 sibling of ``wat-manifest-v2.json``. Sprint-2 Tag-6 landed
the file; Sprint-2 Tag-7 acceptance-doku flagged "no externally-run
validator yet" as Sprint-3 Open-Item O-ext-validator. These tests are
the Python-side half of the cross-tool parity check (the Node.js / ajv
half lives under ``tooling/external-verifier-ajv/``; the cross-tool
parity smoke is wired in :mod:`tests.wat.test_external_verifier_parity`).

Test posture
------------

The v1 schema is *not* identical to the v2 schema:

- v1 carries ``leaves`` as either hex strings (canonical v2-spec form)
  or objects with a ``leaf_hash`` field (real-aggregator emission); the
  schema accepts both via ``oneOf`` so the verifier's normalisation
  layer has a contract, not just code.
- v1 has no ``multi_cap_events`` / ``multi_cap_summary`` sidecar; those
  are v2-only and live in the v2 schema file.
- v1 carries optional ``anchor_height`` and ``prev_hour_root``
  extensions documented in ``docs/wat-manifest-v2-spec.md`` §10.

The tests here pin five things:

1. Schema is a valid Draft-2020-12 document.
2. The real TV-3 fixture (``tests/fixtures/wat-real-manifest/manifest.json``)
   validates against the schema (this is the in-repo conformance
   vector and the third-party-verifier smoke anchor).
3. Each of the eight required top-level fields, when removed, surfaces
   as a ``ValidationError`` (negative-path coverage by field).
4. Both ``leaves`` shapes (hex strings, full-event objects) validate
   under the same schema (the ``oneOf`` branch contract).
5. The ``version`` enum reserves both v1 and v2 strings (Tag-6
   forward-compat decision for the future v2 producer).

Drift between this Python-side validation and the Node.js / ajv side
is detected by the cross-tool parity test.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")
from jsonschema import Draft202012Validator  # noqa: E402  (after importorskip)
from jsonschema.exceptions import ValidationError  # noqa: E402


# ---------------------------------------------------------------------------
# Schema fixture
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "wirelang" / "schemas" / "wakir-wat-manifest-v1.json"
TV3_FIXTURE_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "wat-real-manifest" / "manifest.json"
)


@pytest.fixture(scope="module")
def schema() -> dict:
    """Load the v1 schema once per test module."""
    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def validator(schema: dict) -> Draft202012Validator:
    """A pre-validated Draft-2020-12 validator bound to the v1 schema."""
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


# ---------------------------------------------------------------------------
# Manifest builders
# ---------------------------------------------------------------------------

_LEAF_A = "a" * 64
_LEAF_B = "b" * 64
_ROOT = "c" * 64
_PAYLOAD = "1" * 64
_CAPREF = "2" * 64


def _v1_minimal_string_leaves() -> dict:
    """Smallest valid v1 manifest with leaves as hex strings (v2-spec shape)."""
    return {
        "version": "wakir-wat-manifest/v1",
        "hour_slot": "2026-05-26T17",
        "merkle_root": _ROOT,
        "event_count": 1,
        "events": [
            {
                "event_id": "evt-1",
                "time": "2026-05-26T17:00:00.000Z",
                "payload_hash": _PAYLOAD,
                "capability_token_hash": _CAPREF,
                "leaf_hash": _LEAF_A,
            }
        ],
        "leaves": [_LEAF_A],
        "tree_levels": [[_LEAF_A]],
        "build_time": "2026-05-26T17:00:00Z",
    }


def _v1_minimal_object_leaves() -> dict:
    """Smallest valid v1 manifest with leaves as full event objects (real-aggregator shape)."""
    base = _v1_minimal_string_leaves()
    base["leaves"] = [
        {
            "event_id": "evt-1",
            "time": "2026-05-26T17:00:00.000Z",
            "payload_hash": _PAYLOAD,
            "capability_token_hash": _CAPREF,
            "leaf_hash": _LEAF_A,
        }
    ]
    return base


# ===========================================================================
# Schema sanity
# ===========================================================================


def test_schema_is_valid_draft_2020_12(schema: dict) -> None:
    """The v1 schema document parses as a Draft-2020-12 schema.

    Without this pin a malformed schema would let every manifest pass
    silently. Catches accidental edits to ``$schema`` or unknown
    keyword introductions.
    """
    Draft202012Validator.check_schema(schema)


def test_schema_id_pinned(schema: dict) -> None:
    """``$id`` matches the wakir.dev pattern at the pinned version.

    Convention: schema $id bumps when the on-wire shape changes.
    0.1.0 -> 0.2.0 on Sprint-5 Tag-5 with the additive optional
    ``signature`` top-level slot (byte-for-byte mirror of the
    wat-manifest-v2 schema 0.2.0 signature slot landed in Tag-1).
    """
    assert schema["$id"] == (
        "https://wakir.dev/wirelang/schema/wakir-wat-manifest-v1/0.2.0"
    )


def test_schema_version_enum_reserves_v2(schema: dict) -> None:
    """The ``version`` enum reserves both v1 and v2 strings.

    Tag-6 forward-compat decision: a single v1 schema accepts both
    readings so the future v2 producer (multi-cap aggregator branch)
    can emit ``wakir-wat-manifest/v2`` without a separate file split.
    """
    enum = schema["properties"]["version"]["enum"]
    assert "wakir-wat-manifest/v1" in enum
    assert "wakir-wat-manifest/v2" in enum


# ===========================================================================
# Real-fixture conformance: the in-repo TV-3 vector
# ===========================================================================


def test_tv3_fixture_validates(validator: Draft202012Validator) -> None:
    """The in-repo TV-3 real-manifest fixture validates under the v1 schema.

    This is the third-party-verifier smoke anchor: any external
    implementer can pull this fixture, run their validator against
    the schema, and expect a clean accept. Drift in either the
    aggregator emission or the schema is caught here.
    """
    with TV3_FIXTURE_PATH.open("r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    validator.validate(manifest)


# ===========================================================================
# Both leaves shapes accepted (the oneOf contract)
# ===========================================================================


def test_v1_string_leaves_validates(validator: Draft202012Validator) -> None:
    """Manifest with ``leaves`` as hex strings validates (v2-spec shape)."""
    validator.validate(_v1_minimal_string_leaves())


def test_v1_object_leaves_validates(validator: Draft202012Validator) -> None:
    """Manifest with ``leaves`` as full event objects validates.

    This is the shape the actual v1 aggregator emits today; the
    verifier's ``_normalise_real_leaves`` layer extracts ``leaf_hash``
    from each object before Merkle rebuild.
    """
    validator.validate(_v1_minimal_object_leaves())


# ===========================================================================
# Required-field coverage (eight fields)
# ===========================================================================


@pytest.mark.parametrize(
    "missing_field",
    [
        "version",
        "hour_slot",
        "merkle_root",
        "event_count",
        "events",
        "leaves",
        "tree_levels",
        "build_time",
    ],
)
def test_each_required_field_when_missing_rejected(
    validator: Draft202012Validator, missing_field: str
) -> None:
    """Each of the eight required top-level fields is covered by the schema.

    Removing any one surfaces as a ValidationError. Pins all eight at
    once so a future schema regression that drops a field from
    ``required`` is caught.
    """
    m = _v1_minimal_string_leaves()
    del m[missing_field]
    with pytest.raises(ValidationError):
        validator.validate(m)


# ===========================================================================
# Pattern / domain pins
# ===========================================================================


def test_unknown_top_level_property_rejected(validator: Draft202012Validator) -> None:
    """Unknown top-level keys are rejected (``additionalProperties: false``)."""
    m = _v1_minimal_string_leaves()
    m["future_field"] = "smuggled"
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_unknown_version_string_rejected(validator: Draft202012Validator) -> None:
    """``version`` outside the enum is rejected.

    Catches typos like ``v1``, ``wakir-wat-manifest/1``, ``wakir-wat-manifest/v3``.
    """
    m = _v1_minimal_string_leaves()
    m["version"] = "wakir-wat-manifest/v3"
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_hour_slot_pattern_pinned(validator: Draft202012Validator) -> None:
    """``hour_slot`` must match ``YYYY-MM-DDTHH``.

    Drift here would silently break the TV-1/TV-2/TV-3 driver
    harnesses, which all key on the exact shape.
    """
    m = _v1_minimal_string_leaves()
    m["hour_slot"] = "2026-05-26 17"  # space instead of T
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_merkle_root_pattern_pinned(validator: Draft202012Validator) -> None:
    """``merkle_root`` must be exactly 64 lowercase hex chars (SHA-256)."""
    m = _v1_minimal_string_leaves()
    m["merkle_root"] = "BADHEX" + "0" * 58
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_event_count_negative_rejected(validator: Draft202012Validator) -> None:
    """``event_count`` must be >= 0."""
    m = _v1_minimal_string_leaves()
    m["event_count"] = -1
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_anchor_height_zero_rejected(validator: Draft202012Validator) -> None:
    """Optional ``anchor_height`` must be >= 1 when present."""
    m = _v1_minimal_string_leaves()
    m["anchor_height"] = 0
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_anchor_height_positive_accepted(validator: Draft202012Validator) -> None:
    """Optional ``anchor_height`` integer >= 1 validates when present."""
    m = _v1_minimal_string_leaves()
    m["anchor_height"] = 800123
    validator.validate(m)


def test_prev_hour_root_null_accepted(validator: Draft202012Validator) -> None:
    """Optional ``prev_hour_root`` accepts ``null`` (first-hour case)."""
    m = _v1_minimal_string_leaves()
    m["prev_hour_root"] = None
    validator.validate(m)


def test_prev_hour_root_hex_accepted(validator: Draft202012Validator) -> None:
    """Optional ``prev_hour_root`` accepts a 64-hex-char SHA-256 hex."""
    m = _v1_minimal_string_leaves()
    m["prev_hour_root"] = _LEAF_B
    validator.validate(m)


def test_prev_hour_root_short_hex_rejected(validator: Draft202012Validator) -> None:
    """``prev_hour_root`` rejects truncated hex (32-char prefix)."""
    m = _v1_minimal_string_leaves()
    m["prev_hour_root"] = "a" * 32
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_zero_events_validates(validator: Draft202012Validator) -> None:
    """A quiet hour with ``event_count == 0`` and empty arrays validates.

    The aggregator does not skip empty hours; it pins a deterministic
    empty-tree root. Schema must accept this.
    """
    m = _v1_minimal_string_leaves()
    m["event_count"] = 0
    m["events"] = []
    m["leaves"] = []
    m["tree_levels"] = [[]]
    validator.validate(m)


def test_validator_is_pure(validator: Draft202012Validator) -> None:
    """Validation does not mutate the input document."""
    m = _v1_minimal_string_leaves()
    snapshot = copy.deepcopy(m)
    validator.validate(m)
    assert m == snapshot
