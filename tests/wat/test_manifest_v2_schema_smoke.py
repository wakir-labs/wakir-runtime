# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Smoke-tests for the WAT hour-manifest v2 JSON-Schema stub.

The schema under test (``wirelang/schemas/wat-manifest-v2.json``) is an
*additive* extension of the v1 manifest. It validates **both** versions
of the manifest: a single discriminator field (``version``) selects
between ``wat-manifest/1.0`` (no multi-cap sidecar permitted) and
``wat-manifest/2.0`` (multi-cap sidecar required).

These tests exist to pin three things while the v2 spec is still in
draft (Sprint-2-prep):

1. The schema itself remains a valid JSON-Schema 2020-12 document.
2. Backwards-compatibility: every v1 manifest the existing aggregator
   already produces continues to validate against the v2-aware schema
   (cross-compat).
3. The trigger-condition (v2 iff multi-cap, v1 iff no multi-cap) is
   enforced *schema-side* via ``allOf`` / ``if-then``, not just code-
   side. That means a producer bug ("emitted multi_cap_events on a
   v1 manifest") is caught by the schema validator alone, without
   relying on a verifier code path.

The test surface is intentionally an order of magnitude wider than the
4 inline smoke-tests cited in the Tag-26 outbox: edge-cases (empty
arrays, boundary integers, additionalProperties), schema-violation per
field, and malformed JSON envelopes that should never reach the
validator at all.

The schema is not yet wired into the aggregator build path; once
Sprint-2-Tag-1 lands the wiring, these tests will graduate from "stub
acceptance substrate" to "hard CI pin against ``wat/aggregator.py``
emission". For now they protect the *spec* from accidental drift.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")
from jsonschema import Draft202012Validator  # noqa: E402  (after importorskip)
from jsonschema.exceptions import SchemaError, ValidationError  # noqa: E402


# ---------------------------------------------------------------------------
# Schema fixture
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "wirelang" / "schemas" / "wat-manifest-v2.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    """Load the v2 schema once per test module."""
    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def validator(schema: dict) -> Draft202012Validator:
    """A pre-validated Draft-2020-12 validator bound to the schema."""
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


# ---------------------------------------------------------------------------
# Manifest builders
# ---------------------------------------------------------------------------
#
# These helpers produce minimally-valid manifest envelopes so each test
# can mutate exactly the field it cares about. Hashes are 64-hex-char
# placeholders that satisfy the ``^[0-9a-f]{64}$`` pattern; their actual
# Merkle correctness is irrelevant to *schema* validation (which is the
# only contract under test here).

_LEAF_A = "a" * 64
_LEAF_B = "b" * 64
_ROOT = "c" * 64
_CAPREF_A = "sha256:" + ("d" * 64)
_CAPREF_B = "sha256:" + ("e" * 64)
_CAPREFS_ROOT = "f" * 64


def _v1_minimal() -> dict:
    """Smallest valid v1 manifest."""
    return {
        "version": "wat-manifest/1.0",
        "hour_slot": "2026-05-26T17",
        "merkle_root": _ROOT,
        "event_count": 1,
        "events": [{"event_id": "evt-1", "leaf": _LEAF_A}],
        "leaves": [_LEAF_A],
        "tree_levels": [[_LEAF_A], [_ROOT]],
        "build_time": "2026-05-26T17:00:00Z",
    }


def _v2_minimal() -> dict:
    """Smallest valid v2 manifest with one multi-cap event."""
    base = _v1_minimal()
    base["version"] = "wat-manifest/2.0"
    base["multi_cap_events"] = {
        "evt-1": {
            "caprefs_full": [_CAPREF_A, _CAPREF_B],
            "caprefs_root": _CAPREFS_ROOT,
        }
    }
    base["multi_cap_summary"] = {
        "events_with_multi_cap": 1,
        "max_caprefs_in_any_event": 2,
        "distinct_capability_token_hashes_in_hour": 2,
    }
    return base


# ===========================================================================
# Schema sanity
# ===========================================================================


def test_schema_is_valid_draft_2020_12(schema: dict) -> None:
    """The schema document itself must parse as a Draft-2020-12 schema.

    This guards against accidental edits that introduce keywords the
    validator does not understand. Without this pin, a malformed schema
    would let *every* manifest pass and we would never notice.
    """
    Draft202012Validator.check_schema(schema)


def test_schema_id_pinned(schema: dict) -> None:
    """``$id`` is the wakir.dev pattern at version 0.1.0.

    The Wirelang convention is to bump the schema version when the
    on-wire shape changes; this test makes a silent ``$id`` rewrite
    visible in CI.
    """
    assert schema["$id"] == "https://wakir.dev/wirelang/schema/wat-manifest-v2/0.1.0"


# ===========================================================================
# Cross-compat: v1 manifests must continue to validate
# ===========================================================================


def test_v1_minimal_validates(validator: Draft202012Validator) -> None:
    """A minimally-valid v1 manifest passes the v2-aware schema.

    This is the cross-compat contract: existing v1 producers do not
    need to be touched when the verifier upgrades to v2 awareness.
    """
    validator.validate(_v1_minimal())


def test_v1_zero_events_validates(validator: Draft202012Validator) -> None:
    """v1 manifests with ``event_count == 0`` and empty arrays validate.

    Edge-case: a quiet hour with no audit events still emits a manifest
    (the aggregator does not skip empty hours; it pins a deterministic
    empty-tree root). The schema must not reject this.
    """
    m = _v1_minimal()
    m["event_count"] = 0
    m["events"] = []
    m["leaves"] = []
    m["tree_levels"] = [[]]
    validator.validate(m)


def test_v1_with_multi_cap_events_rejected(validator: Draft202012Validator) -> None:
    """A v1 manifest carrying ``multi_cap_events`` is rejected.

    This is the producer-bug guard: if v1 emission code ever leaks a
    multi-cap sidecar (because the trigger-condition flag was
    miscomputed), the schema validator catches it before it lands on
    disk. The ``allOf`` / ``if-then`` branch enforces this without a
    code-side check.
    """
    m = _v1_minimal()
    m["multi_cap_events"] = {
        "evt-1": {
            "caprefs_full": [_CAPREF_A, _CAPREF_B],
            "caprefs_root": _CAPREFS_ROOT,
        }
    }
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_v1_with_multi_cap_summary_rejected(validator: Draft202012Validator) -> None:
    """A v1 manifest carrying ``multi_cap_summary`` (alone) is rejected.

    Symmetric guard to the previous test: either sidecar key on a v1
    manifest is a producer-bug instance.
    """
    m = _v1_minimal()
    m["multi_cap_summary"] = {
        "events_with_multi_cap": 1,
        "max_caprefs_in_any_event": 2,
        "distinct_capability_token_hashes_in_hour": 2,
    }
    with pytest.raises(ValidationError):
        validator.validate(m)


# ===========================================================================
# v2 happy path + missing-sidecar rejection
# ===========================================================================


def test_v2_minimal_validates(validator: Draft202012Validator) -> None:
    """A minimally-valid v2 manifest with one multi-cap event passes."""
    validator.validate(_v2_minimal())


def test_v2_missing_multi_cap_events_rejected(validator: Draft202012Validator) -> None:
    """v2 manifest without ``multi_cap_events`` is rejected.

    Trigger-condition contract: v2 iff at least one event has >1
    capref. If the aggregator picked v2 it MUST populate the sidecar.
    """
    m = _v2_minimal()
    del m["multi_cap_events"]
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_v2_missing_multi_cap_summary_rejected(validator: Draft202012Validator) -> None:
    """v2 manifest without ``multi_cap_summary`` is rejected.

    Same trigger-condition contract as ``multi_cap_events``; the two
    keys are required as a pair on v2.
    """
    m = _v2_minimal()
    del m["multi_cap_summary"]
    with pytest.raises(ValidationError):
        validator.validate(m)


# ===========================================================================
# Edge-cases on multi_cap_events
# ===========================================================================


def test_v2_caprefs_full_minitems_2(validator: Draft202012Validator) -> None:
    """``caprefs_full`` with a single entry is rejected (minItems: 2).

    By the trigger condition only events with len(caprefs) > 1 appear
    in the sidecar. A 1-entry ``caprefs_full`` is a producer bug
    (likely: copied a v1 frame's caprefs[0:1] instead of detecting
    that this frame should not be in the sidecar at all).
    """
    m = _v2_minimal()
    m["multi_cap_events"]["evt-1"]["caprefs_full"] = [_CAPREF_A]
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_v2_caprefs_full_pattern_pinned(validator: Draft202012Validator) -> None:
    """``caprefs_full`` items must match ``^sha256:[0-9a-f]{64}$``.

    A capref without the ``sha256:`` prefix is rejected. This guards
    against future hash-algorithm drift from leaking a different prefix
    (``sha512:``, ``blake3:``) without a coordinated schema bump.
    """
    m = _v2_minimal()
    m["multi_cap_events"]["evt-1"]["caprefs_full"] = [
        _CAPREF_A,
        # Correct length but missing prefix.
        ("e" * 64),
    ]
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_v2_caprefs_root_pattern_pinned(validator: Draft202012Validator) -> None:
    """``caprefs_root`` must be a 64-hex-char SHA-256 hex string."""
    m = _v2_minimal()
    m["multi_cap_events"]["evt-1"]["caprefs_root"] = "not-a-hex"
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_v2_multi_cap_event_extra_property_rejected(validator: Draft202012Validator) -> None:
    """Per-event sidecar must not carry unknown properties.

    ``additionalProperties: false`` on the sidecar inner object catches
    accidental schema-creep (someone adds ``caprefs_meta`` without a
    coordinated schema bump). Forces the conversation to happen at
    review time, not silently in production.
    """
    m = _v2_minimal()
    m["multi_cap_events"]["evt-1"]["caprefs_meta"] = "smuggled"
    with pytest.raises(ValidationError):
        validator.validate(m)


# ===========================================================================
# Edge-cases on multi_cap_summary
# ===========================================================================


def test_v2_summary_events_with_multi_cap_zero_rejected(
    validator: Draft202012Validator,
) -> None:
    """``events_with_multi_cap`` must be >= 1 on v2.

    By the trigger condition v2 manifests have at least one multi-cap
    event; a 0-count summary is therefore a producer-bug instance
    (manifest version was bumped to v2 by mistake on a single-cap hour).
    """
    m = _v2_minimal()
    m["multi_cap_summary"]["events_with_multi_cap"] = 0
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_v2_summary_max_caprefs_below_two_rejected(
    validator: Draft202012Validator,
) -> None:
    """``max_caprefs_in_any_event`` must be >= 2 on v2."""
    m = _v2_minimal()
    m["multi_cap_summary"]["max_caprefs_in_any_event"] = 1
    with pytest.raises(ValidationError):
        validator.validate(m)


# ===========================================================================
# Negative-path: malformed envelopes and field-level violations
# ===========================================================================


def test_unknown_top_level_property_rejected(validator: Draft202012Validator) -> None:
    """Unknown top-level keys are rejected.

    ``additionalProperties: false`` on the root object pins the
    envelope shape. Future fields require a coordinated schema bump.
    """
    m = _v1_minimal()
    m["future_field"] = "smuggled"
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_unknown_version_string_rejected(validator: Draft202012Validator) -> None:
    """``version`` outside the enum is rejected.

    The discriminator is closed: only ``wat-manifest/1.0`` and
    ``wat-manifest/2.0``. A typo (``wat-manifest/1``, ``v2``,
    ``wat-manifest/2.1``) fails validation.
    """
    m = _v1_minimal()
    m["version"] = "wat-manifest/2.1"
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_hour_slot_pattern_pinned(validator: Draft202012Validator) -> None:
    """``hour_slot`` must match ``YYYY-MM-DDTHH``.

    Drift in this format would silently break the TV-1/TV-2/TV-3
    driver harnesses, which all key on this exact shape.
    """
    m = _v1_minimal()
    m["hour_slot"] = "2026-05-26 17"  # space instead of T
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_event_count_negative_rejected(validator: Draft202012Validator) -> None:
    """``event_count`` must be a non-negative integer."""
    m = _v1_minimal()
    m["event_count"] = -1
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_leaves_wrong_hex_length_rejected(validator: Draft202012Validator) -> None:
    """Leaves must be exactly 64 hex chars (SHA-256).

    Catches truncation bugs (leaf written as 32-char prefix) and
    over-length bugs (leaf written as 128-char SHA-512).
    """
    m = _v1_minimal()
    m["leaves"] = ["a" * 32]  # truncated
    with pytest.raises(ValidationError):
        validator.validate(m)


def test_missing_required_top_level_field_rejected(
    validator: Draft202012Validator,
) -> None:
    """Removing a required field surfaces as a ValidationError.

    Spot-check on ``merkle_root`` because it is the field the
    Bitcoin-anchor cycle depends on; losing it is the worst silent
    failure mode.
    """
    m = _v1_minimal()
    del m["merkle_root"]
    with pytest.raises(ValidationError):
        validator.validate(m)


# ===========================================================================
# Determinism / immutability checks
# ===========================================================================


def test_validator_is_pure(validator: Draft202012Validator) -> None:
    """Validation does not mutate the input document.

    Cheap pin against future schema features that might use
    ``$ref``-resolution caches that accidentally write back into the
    instance. Aggregator code passes manifest dicts by reference; any
    mutation would be a debugging nightmare.
    """
    m = _v2_minimal()
    snapshot = copy.deepcopy(m)
    validator.validate(m)
    assert m == snapshot
