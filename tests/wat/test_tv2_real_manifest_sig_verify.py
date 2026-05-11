# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""TV-2 real-manifest live-run + optional signature-verification.

Sprint-5 Tag-5 substance: extend the Sprint-3 Tag-2 TV-2 real-manifest
live-run validation cohort with the Sprint-5 Tag-2 verifier-side
signature wire-up. The production aggregator
(``wat/cmd/aggregator_cli.py`` v1) does not emit signed manifests
today, so this module hand-signs deep-copies of each TV-2 hour-
receipt and writes them to a pytest ``tmp_path`` directory; the
verifier then consumes the signed real-manifest through
``verify_real_manifest_file(verify_signature=True, ...)``.

What this module checks
-----------------------

Per real TV-2 hour-receipt (4 of them, 2026-05-27T00..T03):

1. ``verify_real_manifest_file(verify_signature=True,
   verify_signature_public_key=<pubkey>,
   verify_signature_mode=PERMISSIVE)`` against a hand-signed copy
   returns ``signature_status="verified"``, ``ok=True``.

2. Same call with ``verify_signature=False`` (default) ignores any
   signature slot and leaves ``signature_status=""`` — backward-
   compat pin for pre-Tag-5 callers.

3. Same call with ``verify_signature_mode=STRICT`` against an
   unsigned (stock) TV-2 manifest returns
   ``signature_status="unsigned-strict"``, ``ok=False``.

Negative-path against tampered signed copies of T00:

4. Tampered ``merkle_root`` (after signing) -> first the
   integrity-rebuild rejects (``integrity_ok=False``) before the
   signature check runs. The signature check is the LAST gate, so
   tampering that breaks integrity surfaces as an integrity-failure
   not a signature-failure. This pin is the phase-order assertion.

5. Wrong public key -> ``signature_status="mismatch"``,
   ``ok=False``.

6. Missing public key (``verify_signature=True``,
   ``verify_signature_public_key=None``, signed manifest) ->
   ``signature_status="structural-error"``, ``ok=False``.

Why this is hard substance for Phase-2 Sprint-5
-----------------------------------------------

Sprint-3 Tag-2 pinned the real-manifest live-run pipeline against
real Bitcoin-anchored production output (schema-file accept +
in-code-validator accept + OTS-anchor-side-file well-formedness).
Sprint-5 Tag-2 wired the optional signature-slot consumer into the
synthetic v2 path. Tag-5 closes the loop: the same pipeline now
accepts a signed real on-disk manifest end-to-end (schema +
integrity + multi-cap-root + OTS-anchor + signature), exercised
against the same TV-2 cohort the Brand-Demo card publishes. When
the signing-aggregator branch lands in Phase-2+, the only delta
is that the manifests on disk will carry the signature slot by
default; the verifier pipeline already accepts them.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Tuple

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from wat.identity.manifest_signing import (
    SIGNATURE_FIELD,
    sign_manifest,
)
from wat.verify.manifest_v2 import (
    VerifyMode,
    verify_real_manifest_file,
)


# ---------------------------------------------------------------------------
# Fixture roots
# ---------------------------------------------------------------------------

#: Repository-relative path to the TV-2 real-manifest fixture cohort.
TV2_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "wat-tv2-real"
)

#: The four hour-slots that comprise the TV-2 run, in chronological
#: order. Each carries manifest.json + root.bin + root.bin.ots.
TV2_HOUR_SLOTS: tuple[str, ...] = (
    "2026-05-27T00",
    "2026-05-27T01",
    "2026-05-27T02",
    "2026-05-27T03",
)

#: Test-only kid value. Hand-authored signing; the kid does not
#: resolve through the AIP-document anchor-kid path here (that is
#: covered separately by Sprint-5 Tag-3 cross-review-zone-1).
TEST_KID = "kid-tv2-sig-verify-tag5"


def _hour_src_dir(slot: str) -> Path:
    return TV2_FIXTURE_ROOT / slot


def _load_manifest(slot: str) -> dict:
    with (_hour_src_dir(slot) / "manifest.json").open(
        "r", encoding="utf-8"
    ) as fh:
        return json.load(fh)


def _signing_keypair() -> Tuple[bytes, bytes]:
    """Deterministic-but-private Ed25519 keypair for the test module.

    Generated fresh per pytest session so we never embed a real key
    on disk. Returns ``(private_seed_bytes, public_key_bytes)``.
    """
    priv = Ed25519PrivateKey.generate()
    return priv.private_bytes_raw(), priv.public_key().public_bytes_raw()


def _stage_signed_hour(
    slot: str,
    *,
    priv_key: bytes,
    out_root: Path,
) -> Path:
    """Stage a signed copy of ``slot`` under ``out_root``.

    Copies manifest.json + root.bin + root.bin.ots, then embeds a
    signature slot into the manifest.json copy. The original repo
    fixture is NOT mutated. Returns the path to the staged
    manifest.json.
    """
    src_dir = _hour_src_dir(slot)
    dst_dir = out_root / slot
    dst_dir.mkdir(parents=True, exist_ok=True)

    manifest = _load_manifest(slot)
    signed = sign_manifest(manifest, priv_key, kid=TEST_KID)
    signed_manifest = dict(signed.manifest)
    signed_manifest[SIGNATURE_FIELD] = signed.signature

    (dst_dir / "manifest.json").write_text(
        json.dumps(signed_manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    # Copy the OTS-side-files byte-for-byte so the OTS-anchor check
    # still passes against the same root.bin bytes.
    (dst_dir / "root.bin").write_bytes((src_dir / "root.bin").read_bytes())
    (dst_dir / "root.bin.ots").write_bytes(
        (src_dir / "root.bin.ots").read_bytes()
    )
    return dst_dir / "manifest.json"


# ---------------------------------------------------------------------------
# Per-hour positive: signed real manifest verifies end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slot", TV2_HOUR_SLOTS)
def test_tv2_signed_real_manifest_verifies_end_to_end(slot, tmp_path):
    """T-WAT-TV2-SIG-01..04: signed TV-2 hour-receipt verifies green.

    Per hour-slot: hand-sign the stock manifest, write the signed
    copy + OTS side-files to ``tmp_path``, run
    ``verify_real_manifest_file(verify_signature=True, ...)`` with
    the matching public key, expect
    ``signature_status="verified"`` and ``ok=True`` end-to-end
    (schema + integrity + OTS-anchor + signature all green).
    """
    priv, pub = _signing_keypair()
    signed_path = _stage_signed_hour(slot, priv_key=priv, out_root=tmp_path)

    result = verify_real_manifest_file(
        signed_path,
        use_schema_file=True,
        check_ots_anchor=True,
        verify_signature=True,
        verify_signature_public_key=pub,
        verify_signature_mode=VerifyMode.PERMISSIVE,
    )

    assert result.fields_ok, f"schema/fields failed: {result.failure_reason}"
    assert result.integrity_ok, f"integrity failed: {result.failure_reason}"
    assert result.ots_anchor.ok, (
        f"ots-anchor failed: {result.failure_reason}"
    )
    assert result.signature_status == "verified", (
        f"signature_status expected 'verified' got "
        f"{result.signature_status!r}; failure={result.failure_reason!r}"
    )
    assert result.ok, f"end-to-end ok=False; failure={result.failure_reason!r}"
    assert result.failure_reason == ""


# ---------------------------------------------------------------------------
# Backward-compat: default off ignores signature slot
# ---------------------------------------------------------------------------


def test_tv2_default_off_ignores_signature_slot(tmp_path):
    """T-WAT-TV2-SIG-05: signed manifest, verify_signature=False
    (default) ignores the slot.

    The signed real-manifest with a signature slot is still accepted
    by the default (Tag-2-and-earlier-callers) pipeline; the
    signature_status field stays empty. This is the backward-compat
    pin that protects every pre-Tag-5 caller of
    ``verify_real_manifest_file``.
    """
    priv, _pub = _signing_keypair()
    signed_path = _stage_signed_hour(
        TV2_HOUR_SLOTS[0], priv_key=priv, out_root=tmp_path
    )

    result = verify_real_manifest_file(
        signed_path,
        use_schema_file=True,
        check_ots_anchor=True,
        # verify_signature omitted -> default False.
    )

    assert result.ok, (
        f"backward-compat path must accept signed real manifests; "
        f"failure={result.failure_reason!r}"
    )
    assert result.signature_status == "", (
        f"signature_status must remain empty when verify_signature=False; "
        f"got {result.signature_status!r}"
    )


# ---------------------------------------------------------------------------
# STRICT on unsigned real manifest rejects
# ---------------------------------------------------------------------------


def test_tv2_strict_rejects_stock_unsigned_real_manifest():
    """T-WAT-TV2-SIG-06: STRICT on stock TV-2 (unsigned) rejects.

    The Production-aggregator emits unsigned manifests today; under
    ``VerifyMode.STRICT`` with verify_signature=True the verifier
    must surface that as ``unsigned-strict``, ``ok=False``,
    ``failure_reason="signature: ..."``. This is what a STRICT-mode
    CI gate would see if it were run against the current
    Production output unchanged.
    """
    stock_path = _hour_src_dir(TV2_HOUR_SLOTS[0]) / "manifest.json"

    result = verify_real_manifest_file(
        stock_path,
        use_schema_file=True,
        check_ots_anchor=True,
        verify_signature=True,
        verify_signature_mode=VerifyMode.STRICT,
    )

    assert not result.ok
    assert result.fields_ok
    assert result.integrity_ok
    assert result.ots_anchor.ok, (
        "ots-anchor must still pass; STRICT only flips the signature gate"
    )
    assert result.signature_status == "unsigned-strict"
    assert result.failure_reason.startswith("signature:")


# ---------------------------------------------------------------------------
# Negative-path: tampered merkle_root surfaces as integrity, not signature
# ---------------------------------------------------------------------------


def test_tv2_tampered_merkle_root_surfaces_before_signature_gate(tmp_path):
    """T-WAT-TV2-SIG-07: tamper on merkle_root is caught by integrity.

    Phase-ordering pin: signature is the LAST gate
    (schema -> fields -> integrity -> multi-cap-root -> OTS -> sig).
    A manifest whose merkle_root has been flipped (after signing)
    must surface as ``integrity_ok=False`` BEFORE the signature
    check runs. The signature_status stays empty because we never
    reach the sig phase.
    """
    priv, pub = _signing_keypair()
    signed_path = _stage_signed_hour(
        TV2_HOUR_SLOTS[0], priv_key=priv, out_root=tmp_path
    )

    # Flip last hex digit of merkle_root post-signing.
    with signed_path.open("r", encoding="utf-8") as fh:
        m = json.load(fh)
    old_root = m["merkle_root"]
    flipped = "0" if old_root[-1] != "0" else "1"
    m["merkle_root"] = old_root[:-1] + flipped
    signed_path.write_text(json.dumps(m), encoding="utf-8")

    result = verify_real_manifest_file(
        signed_path,
        use_schema_file=True,
        check_ots_anchor=True,
        verify_signature=True,
        verify_signature_public_key=pub,
        verify_signature_mode=VerifyMode.PERMISSIVE,
    )

    assert not result.ok
    assert result.fields_ok, "schema accepts: merkle_root is still 64 hex"
    assert not result.integrity_ok, (
        "integrity must reject the merkle_root tamper"
    )
    assert result.signature_status == "", (
        "signature gate must not run; got "
        f"{result.signature_status!r}"
    )


# ---------------------------------------------------------------------------
# Negative-path: wrong public key surfaces as signature mismatch
# ---------------------------------------------------------------------------


def test_tv2_wrong_public_key_returns_mismatch(tmp_path):
    """T-WAT-TV2-SIG-08: wrong pubkey -> signature_status=mismatch.

    Sign with priv-A, verify with pub-B. The integrity + OTS gates
    still pass; signature gate surfaces ``mismatch``, ``ok=False``.
    """
    priv_a, _pub_a = _signing_keypair()
    _priv_b, pub_b = _signing_keypair()
    signed_path = _stage_signed_hour(
        TV2_HOUR_SLOTS[0], priv_key=priv_a, out_root=tmp_path
    )

    result = verify_real_manifest_file(
        signed_path,
        use_schema_file=True,
        check_ots_anchor=True,
        verify_signature=True,
        verify_signature_public_key=pub_b,
        verify_signature_mode=VerifyMode.PERMISSIVE,
    )

    assert not result.ok
    assert result.integrity_ok
    assert result.ots_anchor.ok
    assert result.signature_status == "mismatch"
    assert result.failure_reason.startswith("signature:")


# ---------------------------------------------------------------------------
# Negative-path: missing public key on signed manifest -> structural-error
# ---------------------------------------------------------------------------


def test_tv2_missing_public_key_on_signed_manifest_is_structural_error(
    tmp_path,
):
    """T-WAT-TV2-SIG-09: verify_signature=True + signed + pubkey=None.

    Caller asks for sig verification on a signed manifest but
    provides no public key. The verifier must surface
    ``structural-error``, not skip or accept silently. The other
    gates still pass; the signature gate is the one rejecting.
    """
    priv, _pub = _signing_keypair()
    signed_path = _stage_signed_hour(
        TV2_HOUR_SLOTS[0], priv_key=priv, out_root=tmp_path
    )

    result = verify_real_manifest_file(
        signed_path,
        use_schema_file=True,
        check_ots_anchor=True,
        verify_signature=True,
        verify_signature_public_key=None,
        verify_signature_mode=VerifyMode.PERMISSIVE,
    )

    assert not result.ok
    assert result.integrity_ok
    assert result.ots_anchor.ok
    assert result.signature_status == "structural-error"
    assert result.failure_reason.startswith("signature:")
    assert "ed25519_pub_key" in result.failure_reason


# ---------------------------------------------------------------------------
# Sanity: stock-cohort signature_status pin under default OFF path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("slot", TV2_HOUR_SLOTS)
def test_tv2_stock_cohort_signature_status_empty_under_default(slot):
    """T-WAT-TV2-SIG-10..13: stock TV-2 default path -> sig_status="".

    Regression-pin: the Sprint-3 Tag-2 stock-cohort live-run path
    keeps ``signature_status=""`` after the Tag-5 additive field.
    This guards against an accidental flip of the default behaviour
    in any subsequent refactor of ``verify_real_manifest_file``.
    """
    stock_path = _hour_src_dir(slot) / "manifest.json"

    result = verify_real_manifest_file(
        stock_path,
        use_schema_file=True,
        check_ots_anchor=True,
    )

    assert result.ok, f"stock cohort regression for {slot}"
    assert result.signature_status == ""
