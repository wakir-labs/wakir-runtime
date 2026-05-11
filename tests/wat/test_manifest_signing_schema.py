# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Schema-validation tests for the optional `signature` slot.

Phase-2 Sprint-5 Tag-1: the v2-aware WAT-manifest JSON-Schema
(``wirelang/schemas/wat-manifest-v2.json``) is bumped from
``…/wat-manifest-v2/0.1.0`` to ``…/wat-manifest-v2/0.2.0`` to
formalise an additive optional top-level ``signature`` slot. The
slot shape is byte-identical to the signing primitive in
``wat.identity.manifest_signing`` (Sprint-4 Tag-6); this test cohort
pins the schema-side contract so producer/verifier drift is caught
at validation time, not at signature-verify time.

Six tests, IDs T-WAT-MAN-SIG-SCHEMA-01..05 + T-WAT-MAN-SIG-SCHEMA-RT-01:

01. v1 manifest WITH a well-formed signature slot validates
    (the slot is version-agnostic — additive on v1 too; legacy
    unsigned manifests already covered by
    ``test_manifest_v2_schema_smoke.test_v1_minimal_validates``).
02. v2 manifest WITH a well-formed signature slot validates
    alongside the multi-cap sidecar.
03. signature slot with ``alg`` outside the closed enum is rejected.
04. signature slot with malformed signature hex (wrong length) is
    rejected by the ``^[0-9a-f]{128}$`` pattern.
05. signature slot with an unknown extra property is rejected
    (``additionalProperties: false`` on the slot).
RT-01. round-trip pin: a manifest signed by
    ``wat.identity.manifest_signing.sign_manifest`` followed by
    ``envelope_with_signature`` validates against the 0.2.0 schema
    on both v1 and v2 envelopes.

The schema-version bump (0.1.0 → 0.2.0) is itself pinned by the
sibling cohort's ``test_schema_id_pinned`` flipping to the bumped
URL in the same commit. The two cohorts together cover the additive
slot end-to-end without duplicating coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")
from jsonschema import Draft202012Validator  # noqa: E402  (after importorskip)
from jsonschema.exceptions import ValidationError  # noqa: E402

cryptography = pytest.importorskip("cryptography")
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey,
)

from wat.identity.manifest_signing import (  # noqa: E402
    envelope_with_signature,
    sign_manifest,
)


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
# Manifest builders (mirror test_manifest_v2_schema_smoke.py shape)
# ---------------------------------------------------------------------------

_LEAF_A = "a" * 64
_ROOT = "c" * 64
_CAPREF_A = "sha256:" + ("d" * 64)
_CAPREF_B = "sha256:" + ("e" * 64)
_CAPREFS_ROOT = "f" * 64
_SIG_HEX = "0" * 128  # well-formed 128-hex placeholder (schema-pass)


def _v1_minimal() -> dict:
    """Smallest valid v1 manifest (no signature slot)."""
    return {
        "version": "wat-manifest/1.0",
        "hour_slot": "2026-05-11T17",
        "merkle_root": _ROOT,
        "event_count": 1,
        "events": [{"event_id": "evt-1", "leaf": _LEAF_A}],
        "leaves": [_LEAF_A],
        "tree_levels": [[_LEAF_A], [_ROOT]],
        "build_time": "2026-05-11T17:00:00Z",
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


def _well_formed_signature_block() -> dict:
    """A signature block whose shape passes schema validation.

    The signature bytes are 128 hex zeros — schema-valid but NOT
    cryptographically valid. The schema layer is structural-only;
    cryptographic verification lives in
    :func:`wat.identity.manifest_signing.verify_manifest_signature`.
    """
    return {
        "alg": "Ed25519",
        "kid": "wat-anchor-2026-05-11-test",
        "signature": _SIG_HEX,
    }


# Schema ``$id`` 0.2.0 pin lives in
# ``test_manifest_v2_schema_smoke.test_schema_id_pinned`` (updated in
# the same commit). Not duplicated here.


# ===========================================================================
# T-WAT-MAN-SIG-SCHEMA-01: v1 + signature is permitted (version-agnostic slot)
# ===========================================================================


def test_v1_with_signature_slot_validates(
    validator: Draft202012Validator,
) -> None:
    """T-WAT-MAN-SIG-SCHEMA-01.

    The ``signature`` slot is version-agnostic — additive on both v1
    and v2 envelopes. A v1 manifest may carry a signature without
    triggering the v1-``not.anyOf`` clause that forbids multi-cap
    sidecar keys. This pins that the new slot is NOT accidentally
    bundled into the multi-cap-forbid set.

    Legacy unsigned v1 manifests are covered by the sibling
    ``test_v1_minimal_validates`` cohort; we do not duplicate here.
    """
    m = _v1_minimal()
    m["signature"] = _well_formed_signature_block()
    validator.validate(m)


# ===========================================================================
# T-WAT-MAN-SIG-SCHEMA-02: v2 + signature happy path
# ===========================================================================


def test_v2_with_signature_slot_validates(
    validator: Draft202012Validator,
) -> None:
    """T-WAT-MAN-SIG-SCHEMA-02.

    A v2 manifest carrying both the multi-cap sidecar and the
    signature slot validates end-to-end. This is the steady-state
    target shape post-Sprint-5 (signed v2 manifests in the WAT
    pipeline).
    """
    m = _v2_minimal()
    m["signature"] = _well_formed_signature_block()
    validator.validate(m)


# ===========================================================================
# T-WAT-MAN-SIG-SCHEMA-03: unsupported alg rejected (closed enum)
# ===========================================================================


def test_signature_alg_outside_enum_rejected(
    validator: Draft202012Validator,
) -> None:
    """T-WAT-MAN-SIG-SCHEMA-03.

    The ``alg`` field is a closed enum: only ``"Ed25519"``. A
    well-formed-looking block with ``alg == "ECDSA-P256"`` (or any
    other value) is rejected. This guards against silent algorithm
    drift; a future allowlist entry requires a coordinated additive
    schema bump *and* a parallel
    ``wat.identity.manifest_signing.SIGNATURE_ALG`` allowlist edit.
    """
    m = _v2_minimal()
    bad = _well_formed_signature_block()
    bad["alg"] = "ECDSA-P256"
    m["signature"] = bad
    with pytest.raises(ValidationError):
        validator.validate(m)


# ===========================================================================
# T-WAT-MAN-SIG-SCHEMA-04: malformed signature hex rejected
# ===========================================================================


def test_signature_hex_wrong_length_rejected(
    validator: Draft202012Validator,
) -> None:
    """T-WAT-MAN-SIG-SCHEMA-04.

    Ed25519 signatures are exactly 64 bytes = 128 hex chars. A
    127-char value is rejected by the ``^[0-9a-f]{128}$`` pattern.
    Catches truncation bugs (hex slicing typo) and over-length bugs
    (accidental trailing zero or uppercase hex from ``.upper()``
    output). The pattern also enforces strict lowercase — uppercase
    is rejected by the same regex.
    """
    m = _v2_minimal()
    bad = _well_formed_signature_block()
    bad["signature"] = "0" * 127  # truncated by one hex char
    m["signature"] = bad
    with pytest.raises(ValidationError):
        validator.validate(m)


# ===========================================================================
# T-WAT-MAN-SIG-SCHEMA-05: extra property rejected (additionalProperties=false)
# ===========================================================================


def test_signature_extra_property_rejected(
    validator: Draft202012Validator,
) -> None:
    """T-WAT-MAN-SIG-SCHEMA-05.

    ``additionalProperties: false`` on the signature slot pins the
    block shape against accidental field-creep (e.g., someone adds
    ``signed_at`` or ``signer_purpose`` without a coordinated schema
    bump). Forces the conversation to happen at review time, not
    silently in production wire-form.
    """
    m = _v2_minimal()
    bad = _well_formed_signature_block()
    bad["signed_at"] = "2026-05-11T17:00:00Z"
    m["signature"] = bad
    with pytest.raises(ValidationError):
        validator.validate(m)


# ===========================================================================
# T-WAT-MAN-SIG-SCHEMA-RT-01: round-trip pin against the signing primitive
# ===========================================================================


def test_signed_manifest_round_trip_validates_both_versions(
    validator: Draft202012Validator,
) -> None:
    """T-WAT-MAN-SIG-SCHEMA-RT-01.

    Round-trip the signing primitive on both envelope versions: for
    each of v1 and v2, sign with ``sign_manifest``, serialise via
    ``envelope_with_signature``, deserialise back to a dict, and
    assert the dict validates against the 0.2.0 schema.

    This pins the contract that the signing primitive emits exactly
    the slot shape the schema permits. If a future edit drifts
    either side (e.g., the signing primitive starts emitting
    ``signed_at`` and the schema does not allow it; or the schema
    tightens ``kid`` to a regex the primitive does not honour), this
    test fails immediately on both paths.

    The v2 sub-assertion also catches the case where the signing
    primitive accidentally drops or reorders the multi-cap sidecar
    keys during JCS canonicalisation: the round-tripped envelope
    must still carry both sidecar keys.
    """
    sk = Ed25519PrivateKey.generate()
    raw_priv = sk.private_bytes_raw()

    for label, builder, kid in (
        ("v1", _v1_minimal, "wat-anchor-rt-v1"),
        ("v2", _v2_minimal, "wat-anchor-rt-v2"),
    ):
        m = builder()
        signed = sign_manifest(m, raw_priv, kid=kid)
        blob = envelope_with_signature(signed)
        round_tripped = json.loads(blob.decode("utf-8"))

        # Sanity: the slot survives the round-trip.
        assert "signature" in round_tripped, label
        assert round_tripped["signature"]["alg"] == "Ed25519", label
        assert round_tripped["signature"]["kid"] == kid, label
        assert len(round_tripped["signature"]["signature"]) == 128, label

        # On v2, the multi-cap sidecar must survive too.
        if label == "v2":
            assert "multi_cap_events" in round_tripped
            assert "multi_cap_summary" in round_tripped

        # The load-bearing assertion: schema accepts the emitted shape.
        validator.validate(round_tripped)
