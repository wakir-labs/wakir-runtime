# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../../wat/LICENSE-BSL.md.

"""Tests for wat.identity.manifest_signing (Phase-1b Sprint-4 Tag-6).

WAT-manifest signing layer parallel to the Identity-Substrate-
engineering schema-registry-entry-signing layer
(``wirelang.schemas.entry_signing``, Phase-2 Sprint-4 Tag-1). The
signing primitive is shape-byte-identical to AIP-document signing
and schema-registry-entry signing: JCS + SHA-256 + Ed25519 over the
manifest payload minus the ``signature`` slot.

Test inventory (8 hermetic determinism tests):

- T-WAT-MAN-SIG-01 sign-verify happy path (v1 manifest)
- T-WAT-MAN-SIG-02 sign-verify happy path (v2 manifest with sidecar)
- T-WAT-MAN-SIG-03 signature is deterministic across runs
- T-WAT-MAN-SIG-04 tamper-detection (cryptographic mismatch returns False)
- T-WAT-MAN-SIG-05 STRICT-mode rejects unsigned manifest
- T-WAT-MAN-SIG-06 PERMISSIVE-mode accepts unsigned manifest
- T-WAT-MAN-SIG-07 structural-error matrix (block shape failures raise)
- T-WAT-MAN-SIG-08 envelope round-trip (signed and unsigned paths)
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from wat.identity.manifest_signing import (
    SIGNATURE_ALG,
    SIGNATURE_FIELD,
    SignedWatManifest,
    VerifyMode,
    WatManifestSignatureError,
    _canonical_signing_payload,
    envelope_to_signed_manifest,
    envelope_with_signature,
    sign_manifest,
    verify_manifest_signature,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_FIXED_SEED_HEX: str = (
    "5cbd7fdeefb8a25b85aaf80be58fd3da26d31a99318ef6cd28fd06f3fbb4b3a8"
)


def _fixed_keypair() -> tuple[bytes, bytes]:
    """Deterministic Ed25519 keypair from a fixed seed.

    The seed is a hex-encoded 32-byte random constant pinned in this
    file so the public key is byte-stable across runs. Tests that
    need a *second* keypair derive it from a different seed.
    """
    seed = bytes.fromhex(_FIXED_SEED_HEX)
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    pk = sk.public_key()
    from cryptography.hazmat.primitives import serialization

    pub_bytes = pk.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return seed, pub_bytes


def _other_pubkey() -> bytes:
    """A different Ed25519 public key for tamper-detection tests."""
    other_seed = hashlib.sha256(b"other-anchor-key").digest()
    sk = Ed25519PrivateKey.from_private_bytes(other_seed)
    from cryptography.hazmat.primitives import serialization

    return sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _v1_manifest() -> dict:
    """Minimal wat-manifest/1.0 fixture (shape-realistic)."""
    return {
        "version": "wat-manifest/1.0",
        "hour_slot": "2026-05-11T17",
        "merkle_root": "0" * 64,
        "event_count": 0,
        "events": [],
        "leaves": [],
        "tree_levels": [[]],
        "build_time": "2026-05-11T17:30:00Z",
    }


def _v2_manifest() -> dict:
    """Minimal wat-manifest/2.0 fixture with multi-cap sidecar."""
    return {
        "version": "wat-manifest/2.0",
        "hour_slot": "2026-05-11T18",
        "merkle_root": "a" * 64,
        "event_count": 1,
        "events": [{"event_id": "evt-1", "leaf": "b" * 64}],
        "leaves": ["b" * 64],
        "tree_levels": [["b" * 64]],
        "build_time": "2026-05-11T18:30:00Z",
        "multi_cap_events": {
            "evt-1": {
                "caprefs_full": [
                    "sha256:" + "c" * 64,
                    "sha256:" + "d" * 64,
                ],
                "caprefs_root": "e" * 64,
            },
        },
        "multi_cap_summary": {
            "events_with_multi_cap": 1,
            "max_caprefs_in_any_event": 2,
            "distinct_capability_token_hashes_in_hour": 2,
        },
    }


_KID = "wat-anchor-2026-05"


# ---------------------------------------------------------------------------
# T-WAT-MAN-SIG-01 sign-verify happy path (v1 manifest)
# ---------------------------------------------------------------------------


def test_t_wat_man_sig_01_sign_verify_happy_path_v1():
    """v1 manifest signs and verifies end-to-end."""
    priv, pub = _fixed_keypair()
    manifest = _v1_manifest()

    signed = sign_manifest(manifest, priv, kid=_KID)

    # Shape contracts.
    assert isinstance(signed, SignedWatManifest)
    assert signed.signature["alg"] == SIGNATURE_ALG
    assert signed.signature["kid"] == _KID
    assert len(signed.signature["signature"]) == 128
    # The signed.manifest is the pre-image -- no signature slot.
    assert SIGNATURE_FIELD not in signed.manifest

    # Caller's manifest is not mutated.
    assert SIGNATURE_FIELD not in manifest

    # Verify path.
    assert verify_manifest_signature(signed, pub) is True


# ---------------------------------------------------------------------------
# T-WAT-MAN-SIG-02 sign-verify happy path (v2 with multi-cap sidecar)
# ---------------------------------------------------------------------------


def test_t_wat_man_sig_02_sign_verify_happy_path_v2():
    """v2 manifest with multi-cap sidecar signs and verifies."""
    priv, pub = _fixed_keypair()
    manifest = _v2_manifest()

    signed = sign_manifest(manifest, priv, kid=_KID)
    assert verify_manifest_signature(signed, pub) is True

    # The pre-image includes the multi_cap_* fields verbatim.
    assert "multi_cap_events" in signed.manifest
    assert "multi_cap_summary" in signed.manifest
    assert (
        signed.manifest["multi_cap_summary"]["events_with_multi_cap"] == 1
    )


# ---------------------------------------------------------------------------
# T-WAT-MAN-SIG-03 signature is deterministic across runs
# ---------------------------------------------------------------------------


def test_t_wat_man_sig_03_signature_is_deterministic():
    """Signing the same manifest with the same key yields the same
    signature byte-string. Ed25519 is deterministic per RFC 8032."""
    priv, _ = _fixed_keypair()
    manifest = _v2_manifest()

    sig_a = sign_manifest(manifest, priv, kid=_KID).signature["signature"]
    sig_b = sign_manifest(manifest, priv, kid=_KID).signature["signature"]
    assert sig_a == sig_b

    # JCS pre-image is also deterministic; this catches accidental
    # dict-ordering leaks via a re-canonicalisation cross-check.
    digest_a = _canonical_signing_payload(manifest)
    digest_b = _canonical_signing_payload(manifest)
    assert digest_a == digest_b


# ---------------------------------------------------------------------------
# T-WAT-MAN-SIG-04 tamper-detection (cryptographic mismatch returns False)
# ---------------------------------------------------------------------------


def test_t_wat_man_sig_04_tamper_detection_returns_false():
    """A tampered manifest verifies as False (not raises). Likewise a
    signature verified against the wrong public key returns False."""
    priv, pub = _fixed_keypair()
    manifest = _v1_manifest()
    signed = sign_manifest(manifest, priv, kid=_KID)

    # Case A: caller hands the verifier a tampered manifest along with
    # the original signature block. We build the bare-manifest path
    # by passing the tampered dict and the original block.
    tampered = copy.deepcopy(dict(signed.manifest))
    tampered["event_count"] = 999  # was 0
    assert (
        verify_manifest_signature(
            tampered, pub, signature_block=signed.signature
        )
        is False
    )

    # Case B: original manifest, wrong public key.
    other_pub = _other_pubkey()
    assert verify_manifest_signature(signed, other_pub) is False


# ---------------------------------------------------------------------------
# T-WAT-MAN-SIG-05 STRICT-mode rejects unsigned manifest
# ---------------------------------------------------------------------------


def test_t_wat_man_sig_05_strict_rejects_unsigned():
    """STRICT mode raises on an unsigned manifest. PERMISSIVE (default)
    accepts it."""
    manifest = _v1_manifest()
    # PERMISSIVE accepts (no pub key needed because path is unsigned).
    assert (
        verify_manifest_signature(manifest, mode=VerifyMode.PERMISSIVE)
        is True
    )
    # STRICT rejects.
    with pytest.raises(WatManifestSignatureError, match="STRICT"):
        verify_manifest_signature(manifest, mode=VerifyMode.STRICT)


# ---------------------------------------------------------------------------
# T-WAT-MAN-SIG-06 PERMISSIVE-mode happy path on signed manifest
# ---------------------------------------------------------------------------


def test_t_wat_man_sig_06_permissive_verifies_signed_manifest():
    """PERMISSIVE mode does NOT short-circuit a signed manifest -- when
    a signature is present, it is verified end-to-end. (Regression
    contract: a buggy PERMISSIVE that always returned True for any
    manifest carrying a slot would slip a wrong-key signature through;
    this test pins the correct behaviour.)"""
    priv, pub = _fixed_keypair()
    manifest = _v1_manifest()
    signed = sign_manifest(manifest, priv, kid=_KID)

    # Correct key under PERMISSIVE: passes.
    assert (
        verify_manifest_signature(signed, pub, mode=VerifyMode.PERMISSIVE)
        is True
    )
    # Wrong key under PERMISSIVE: still rejected (returns False).
    other_pub = _other_pubkey()
    assert (
        verify_manifest_signature(
            signed, other_pub, mode=VerifyMode.PERMISSIVE
        )
        is False
    )


# ---------------------------------------------------------------------------
# T-WAT-MAN-SIG-07 structural-error matrix
# ---------------------------------------------------------------------------


def test_t_wat_man_sig_07_structural_error_matrix():
    """Block shape failures raise WatManifestSignatureError. A
    cryptographically-wrong but well-formed signature returns False
    (already covered in T-04); this test pins the *structural* error
    path so the split is not collapsed."""
    priv, pub = _fixed_keypair()
    manifest = _v1_manifest()

    # Wrong private-key length.
    with pytest.raises(WatManifestSignatureError, match="32-byte"):
        sign_manifest(manifest, b"\x00" * 31, kid=_KID)

    # Empty kid.
    with pytest.raises(WatManifestSignatureError, match="kid"):
        sign_manifest(manifest, priv, kid="")

    # Missing version.
    bad = dict(manifest)
    del bad["version"]
    with pytest.raises(WatManifestSignatureError, match="version"):
        sign_manifest(bad, priv, kid=_KID)

    # Unrecognised version.
    bad = dict(manifest)
    bad["version"] = "wat-manifest/9.9"
    with pytest.raises(WatManifestSignatureError, match="not signable"):
        sign_manifest(bad, priv, kid=_KID)

    # Build a well-formed signed manifest, then break the block.
    signed = sign_manifest(manifest, priv, kid=_KID)
    good_block = dict(signed.signature)

    # Wrong alg.
    bad_block = dict(good_block)
    bad_block["alg"] = "RSA"
    with pytest.raises(WatManifestSignatureError, match="unsupported"):
        verify_manifest_signature(
            signed.manifest, pub, signature_block=bad_block
        )

    # Malformed signature hex (right length, not hex).
    bad_block = dict(good_block)
    bad_block["signature"] = "zz" * 64
    with pytest.raises(WatManifestSignatureError, match="not valid hex"):
        verify_manifest_signature(
            signed.manifest, pub, signature_block=bad_block
        )

    # Wrong public-key length (signed-path, structural failure).
    with pytest.raises(WatManifestSignatureError, match="32-byte"):
        verify_manifest_signature(signed, b"\x00" * 31)


# ---------------------------------------------------------------------------
# T-WAT-MAN-SIG-08 envelope round-trip (signed and unsigned paths)
# ---------------------------------------------------------------------------


def test_t_wat_man_sig_08_envelope_round_trip():
    """Signed envelope round-trips back to a SignedWatManifest that
    verifies. Unsigned envelope round-trips back to a raw dict (no
    SignedWatManifest)."""
    priv, pub = _fixed_keypair()
    manifest = _v2_manifest()

    # Signed path.
    signed = sign_manifest(manifest, priv, kid=_KID)
    blob = envelope_with_signature(signed)
    assert isinstance(blob, bytes)
    # Wire form is canonical JSON; sanity-check it parses.
    parsed = json.loads(blob.decode("utf-8"))
    assert SIGNATURE_FIELD in parsed
    assert parsed[SIGNATURE_FIELD]["kid"] == _KID

    re_signed = envelope_to_signed_manifest(blob)
    assert isinstance(re_signed, SignedWatManifest)
    assert verify_manifest_signature(re_signed, pub) is True

    # Cross-deterministic check: the round-trip yields the same
    # signature bytes (no re-signing in transit).
    assert re_signed.signature["signature"] == signed.signature["signature"]

    # Unsigned path.
    unsigned_blob = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    back = envelope_to_signed_manifest(unsigned_blob)
    assert not isinstance(back, SignedWatManifest)
    assert back["version"] == "wat-manifest/2.0"
