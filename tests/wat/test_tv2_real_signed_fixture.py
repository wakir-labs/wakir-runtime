# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Pre-baked Aggregator-signed TV-2 sub-cohort regression pins.

Sprint-6-Tag-5 Item 1: the Aggregator-signed sub-cohort under
``tests/fixtures/wat-tv2-real-signed/`` is the test-vereinfachung
follow-up to Sprint-6-Tag-3 Folge-Item 1. Verifier tests no longer
need to hand-sign manifest copies on the hot path; they consume the
checked-in signed manifests directly. This module pins the new
substrate end-to-end so it does not silently regress.

What is being asserted
----------------------

Per signed TV-2 hour-receipt (4 of them, 2026-05-27T00..T03):

1. The pre-baked signed manifest exists on disk under
   ``tests/fixtures/wat-tv2-real-signed/<hour>/manifest.json`` with
   a well-formed ``signature`` slot (Ed25519, doc-pinned kid,
   hex-128 signature shape).

2. ``verify_real_manifest_file(verify_signature=True, mode=STRICT,
   verify_signature_public_key=<demo-pub>, ...)`` returns
   ``signature_status="verified"`` and ``ok=True`` end-to-end.

3. The signed manifest's ``merkle_root`` equals the stock cohort's
   ``merkle_root`` for the same hour (Aggregator deterministic-sort
   contract). The byte-identical ``root.bin`` / ``root.bin.ots``
   side-files cross-cohort confirm this from the OTS-anchor side.

4. The signed cohort's ``kid`` matches the demo-key kid documented
   in the sub-cohort README. The README is the trust substrate: any
   auditor can re-derive the public key from the published demo seed
   and re-verify the cohort without consulting the test code.

This module is intentionally separate from
``test_tv2_real_manifest_sig_verify.py``: that module exercises the
hand-signing path and pins the unsigned-strict / default-off /
tampering / wrong-pubkey gates. This module pins the pre-baked
on-disk Aggregator-signed substrate.

Pre-baked rather than hand-signed
---------------------------------

The Sprint-5-Tag-5 module hand-signed deep-copies of each TV-2 hour
to ``tmp_path`` to exercise the verifier-side signature wire-up. That
substrate was the right level of indirection at the time (the
Production aggregator did not yet sign on the writer side). Tag-3 of
Sprint-6 landed the Aggregator-side ``--sign-key`` / ``--sign-kid``;
Tag-5 here closes the test-substrate loop by checking in the
Aggregator-signed manifests directly, so the verifier-side
regression pins read straight from disk.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SIGNED_FIXTURE_ROOT = (
    REPO_ROOT / "tests" / "fixtures" / "wat-tv2-real-signed"
)
STOCK_FIXTURE_ROOT = (
    REPO_ROOT / "tests" / "fixtures" / "wat-tv2-real"
)
TV2_HOUR_SLOTS: tuple[str, ...] = (
    "2026-05-27T00",
    "2026-05-27T01",
    "2026-05-27T02",
    "2026-05-27T03",
)

# Mirror the doc-pinned values from
# ``scripts/wat-tv2-fixture-regenerate-signed.py``. The README in the
# sub-cohort root documents the same values; if the regeneration
# script ever rotates the demo seed, both the test pin below and the
# README must be regenerated together (the README is rewritten by the
# regeneration script automatically).
DEMO_SEED_HEX = (
    "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
)
DEMO_KID = "wat-tv2-fixture-demo-key"


def _fixtures_present() -> bool:
    return SIGNED_FIXTURE_ROOT.is_dir() and any(SIGNED_FIXTURE_ROOT.iterdir())


pytestmark = pytest.mark.skipif(
    not _fixtures_present(),
    reason=(
        "wat-tv2-real-signed sub-cohort not present in this checkout; "
        "run scripts/wat-tv2-fixture-regenerate-signed.py to bake it."
    ),
)


@pytest.fixture(scope="module")
def demo_public_key() -> bytes:
    """Derive the Ed25519 public key for the doc-pinned demo seed.

    The seed is published in the sub-cohort README; we derive the
    public key in-test rather than hardcoding it so a future seed
    rotation only has to touch the regeneration script and the
    DEMO_SEED_HEX constant above.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    seed = bytes.fromhex(DEMO_SEED_HEX)
    priv = Ed25519PrivateKey.from_private_bytes(seed)
    return priv.public_key().public_bytes_raw()


def _load_signed_manifest(slot: str) -> dict:
    with (SIGNED_FIXTURE_ROOT / slot / "manifest.json").open(
        "r", encoding="utf-8"
    ) as fh:
        return json.load(fh)


def _load_stock_manifest(slot: str) -> dict:
    with (STOCK_FIXTURE_ROOT / slot / "manifest.json").open(
        "r", encoding="utf-8"
    ) as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Per-hour positive: pre-baked signed manifest verifies end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slot", TV2_HOUR_SLOTS)
def test_tv2_signed_subcohort_hour_verifies_end_to_end(
    slot: str,
    demo_public_key: bytes,
) -> None:
    """T-WAT-TV2-SIGFIX-01..04: pre-baked signed hour verifies green.

    Per hour-slot: read the on-disk signed manifest from
    ``tests/fixtures/wat-tv2-real-signed/<hour>/`` and run
    ``verify_real_manifest_file(verify_signature=True, mode=STRICT,
    verify_signature_public_key=<demo-pub>, ...)``. The signed
    manifest carries the doc-pinned demo signature; the verifier
    returns ``signature_status="verified"`` end-to-end (schema +
    integrity + OTS-anchor + signature all green).
    """
    from wat.verify.manifest_v2 import VerifyMode, verify_real_manifest_file

    signed_path = SIGNED_FIXTURE_ROOT / slot / "manifest.json"

    result = verify_real_manifest_file(
        signed_path,
        use_schema_file=True,
        check_ots_anchor=True,
        verify_signature=True,
        verify_signature_public_key=demo_public_key,
        verify_signature_mode=VerifyMode.STRICT,
    )

    assert result.fields_ok, (
        f"fields_ok=False for {slot}: {result.failure_reason}"
    )
    assert result.integrity_ok, (
        f"integrity_ok=False for {slot}: {result.failure_reason}"
    )
    assert result.ots_anchor.ok, (
        f"ots_anchor failed for {slot}: "
        f"{result.ots_anchor.failure_reason}"
    )
    assert result.signature_status == "verified", (
        f"{slot}: signature_status={result.signature_status!r} "
        f"failure={result.failure_reason!r}"
    )
    assert result.ok, (
        f"{slot}: end-to-end ok=False; failure={result.failure_reason!r}"
    )


# ---------------------------------------------------------------------------
# Signature-slot shape pin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slot", TV2_HOUR_SLOTS)
def test_tv2_signed_subcohort_signature_slot_well_formed(
    slot: str,
) -> None:
    """T-WAT-TV2-SIGFIX-05..08: signature slot has the documented shape.

    Pins the on-disk signature shape for the Aggregator-signed
    cohort:

    * ``alg == "Ed25519"`` (closed enum per manifest-v2 spec).
    * ``kid == DEMO_KID`` (doc-pinned demo kid; rotation requires
      regeneration + README update + this test edit, all visible in
      one diff).
    * ``signature`` is 128 hex chars (64 raw bytes Ed25519, RFC 8032
      fixed length).

    Drift on any of these signals a fixture-regeneration mismatch and
    must be caught at CI before the cohort is consumed downstream.
    """
    manifest = _load_signed_manifest(slot)
    assert "signature" in manifest, f"{slot}: signature slot missing"
    sig = manifest["signature"]
    assert sig["alg"] == "Ed25519", (
        f"{slot}: alg={sig['alg']!r} (expected 'Ed25519')"
    )
    assert sig["kid"] == DEMO_KID, (
        f"{slot}: kid={sig['kid']!r} (expected {DEMO_KID!r})"
    )
    assert re.fullmatch(r"[0-9a-f]{128}", sig["signature"]), (
        f"{slot}: signature shape drift: {sig['signature']!r}"
    )


# ---------------------------------------------------------------------------
# Cross-cohort: signed merkle_root matches stock merkle_root
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slot", TV2_HOUR_SLOTS)
def test_tv2_signed_subcohort_merkle_root_matches_stock(slot: str) -> None:
    """T-WAT-TV2-SIGFIX-09..12: signed and stock merkle_root agree.

    Aggregator deterministic-sort contract: signing is additive on
    top of the unsigned manifest body; the Merkle root in the signed
    sub-cohort must equal the stock cohort's root for the same hour.
    This is the cross-cohort consistency pin -- if the signed cohort
    drifts from the stock cohort on merkle_root, the OTS-anchor
    side-files (byte-copied from stock) would not verify against the
    signed manifest, and the substrate would silently corrupt the
    audit trail.
    """
    signed = _load_signed_manifest(slot)
    stock = _load_stock_manifest(slot)
    assert signed["merkle_root"] == stock["merkle_root"], (
        f"{slot}: signed merkle_root={signed['merkle_root']!r} "
        f"!= stock merkle_root={stock['merkle_root']!r}"
    )
    assert signed["event_count"] == stock["event_count"], (
        f"{slot}: event_count drift"
    )


# ---------------------------------------------------------------------------
# Sub-cohort README pins the same demo material the regen script uses
# ---------------------------------------------------------------------------


def test_tv2_signed_subcohort_readme_pins_demo_material() -> None:
    """T-WAT-TV2-SIGFIX-13: sub-cohort README documents demo seed + kid.

    The README is the audit-trail substrate for the sub-cohort: it
    pins the demo seed, the derived public key, and the kid so any
    party can re-derive and re-verify without trusting the
    regeneration script. The pin below makes sure a regeneration
    that rotates the seed cannot silently desync the README.
    """
    readme_path = SIGNED_FIXTURE_ROOT / "README.md"
    assert readme_path.is_file(), (
        "wat-tv2-real-signed/README.md missing; "
        "regenerate the sub-cohort to recreate it."
    )
    body = readme_path.read_text(encoding="utf-8")
    assert DEMO_SEED_HEX in body, (
        "README must pin the demo seed in hex"
    )
    assert DEMO_KID in body, (
        f"README must pin the demo kid {DEMO_KID!r}"
    )
    assert "Ed25519" in body, (
        "README must name the signature algorithm"
    )
