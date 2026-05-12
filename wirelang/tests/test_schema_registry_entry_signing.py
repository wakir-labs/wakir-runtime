# SPDX-License-Identifier: Apache-2.0
"""Determinism tests for the schema-registry entry-signing layer.

Phase-2 Sprint-4 Tag-1 inventory: T-SR-SIG-01..12.

The tests exercise the signing primitive in isolation (no NATS-KV
backend, no live cluster) using ``cryptography``'s in-memory Ed25519
key generator. The signing primitive must be byte-deterministic over
JCS-canonicalised envelope bytes; the tests pin the byte-equality
contract, the verify-mode policy, the structural failure modes and
the optional-slot backward compatibility.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from typing import Any, Mapping

import pytest

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives import serialization

from wirelang.schemas.entry_signing import (
    SchemaRegistrySignatureError,
    SignedSchemaRegistryEntry,
    VerifyMode,
    _canonical_signing_payload,
    envelope_to_signed_entry,
    envelope_with_signature,
    sign_entry,
    verify_entry_signature,
)
from wirelang.schemas.registry_nats_kv_backend import (
    SchemaRegistryEntry,
    _entry_to_envelope,
    _envelope_to_entry,
    schema_body_sha256,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers.
# ---------------------------------------------------------------------------


_FIXED_SEED_A: bytes = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)
"""RFC 8032 Ed25519 test-vector 1 seed.

Used as a deterministic 32-byte key seed across tests; the public key
derived from this seed is a known-answer vector. We only rely on
determinism here (signing is deterministic per RFC 8032, so identical
inputs produce identical signatures).
"""

_FIXED_SEED_B: bytes = bytes.fromhex(
    "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"
)
"""RFC 8032 Ed25519 test-vector 2 seed (used for cross-key tests)."""


def _ed25519_keypair(seed: bytes) -> tuple[bytes, bytes]:
    """Derive the (priv32, pub32) raw byte pair from a 32-byte seed."""
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    pk = sk.public_key()
    priv_raw = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_raw = pk.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv_raw, pub_raw


def _make_entry(
    *,
    layer: str = "wire",
    name: str = "layer-1-wire",
    version: str = "0.1.0",
    registered_by: str = "reza-dev2-aip-id",
) -> SchemaRegistryEntry:
    """Build a representative schema-registry entry for signing tests."""
    schema_body: dict[str, Any] = {
        "$id": f"wakir.wirelang.{name}/{version}",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"foo": {"type": "string"}},
        "required": ["foo"],
    }
    digest = schema_body_sha256(schema_body)
    return SchemaRegistryEntry(
        layer=layer,
        name=name,
        version=version,
        schema_id=schema_body["$id"],
        schema_body=schema_body,
        schema_body_sha256=digest,
        registered_at=dt.datetime(
            2026, 5, 11, 18, 0, 0, tzinfo=dt.timezone.utc
        ),
        registered_by=registered_by,
    )


# ---------------------------------------------------------------------------
# T-SR-SIG-01: sign → verify round-trip on a freshly-generated key-pair.
# ---------------------------------------------------------------------------


def test_t_sr_sig_01_sign_verify_roundtrip() -> None:
    priv, pub = _ed25519_keypair(_FIXED_SEED_A)
    entry = _make_entry()

    signed = sign_entry(entry, priv, kid="biscuit-root-1")

    assert isinstance(signed, SignedSchemaRegistryEntry)
    assert signed.entry == entry
    assert signed.signature["alg"] == "Ed25519"
    assert signed.signature["kid"] == "biscuit-root-1"
    assert len(signed.signature["signature"]) == 128
    assert verify_entry_signature(signed, pub) is True


# ---------------------------------------------------------------------------
# T-SR-SIG-02: signing pre-image is deterministic over JCS-canonical form.
# ---------------------------------------------------------------------------


def test_t_sr_sig_02_signing_payload_deterministic() -> None:
    entry_a = _make_entry()
    # Build a byte-equal twin via the envelope round-trip — proves that
    # JCS canonicalisation is field-order-independent.
    blob = _entry_to_envelope(entry_a)
    entry_b = _envelope_to_entry(blob)

    digest_a = _canonical_signing_payload(entry_a)
    digest_b = _canonical_signing_payload(entry_b)
    assert digest_a == digest_b
    # And the envelope bytes are byte-equal too (Tag-1 invariant).
    assert _entry_to_envelope(entry_a) == _entry_to_envelope(entry_b)


# ---------------------------------------------------------------------------
# T-SR-SIG-03: signature block structural failures raise typed exception.
# ---------------------------------------------------------------------------


def test_t_sr_sig_03_signature_block_structural_failures() -> None:
    priv, pub = _ed25519_keypair(_FIXED_SEED_A)
    entry = _make_entry()
    signed = sign_entry(entry, priv, kid="biscuit-root-1")

    # Missing field.
    bad_missing_alg: dict[str, Any] = {
        "kid": "biscuit-root-1",
        "signature": signed.signature["signature"],
    }
    with pytest.raises(SchemaRegistrySignatureError):
        verify_entry_signature(
            entry, pub, signature_block=bad_missing_alg
        )

    # Wrong alg.
    bad_alg = dict(signed.signature)
    bad_alg["alg"] = "RSA-PSS"
    with pytest.raises(SchemaRegistrySignatureError):
        verify_entry_signature(entry, pub, signature_block=bad_alg)

    # Empty kid.
    bad_kid = dict(signed.signature)
    bad_kid["kid"] = ""
    with pytest.raises(SchemaRegistrySignatureError):
        verify_entry_signature(entry, pub, signature_block=bad_kid)

    # Malformed hex.
    bad_hex = dict(signed.signature)
    bad_hex["signature"] = "z" * 128
    with pytest.raises(SchemaRegistrySignatureError):
        verify_entry_signature(entry, pub, signature_block=bad_hex)

    # Wrong length.
    bad_len = dict(signed.signature)
    bad_len["signature"] = "ab" * 60  # 120 hex chars, not 128
    with pytest.raises(SchemaRegistrySignatureError):
        verify_entry_signature(entry, pub, signature_block=bad_len)


# ---------------------------------------------------------------------------
# T-SR-SIG-04: tamper detection on each envelope field.
# ---------------------------------------------------------------------------


def test_t_sr_sig_04_tamper_detection() -> None:
    priv, pub = _ed25519_keypair(_FIXED_SEED_A)
    entry = _make_entry()
    signed = sign_entry(entry, priv, kid="biscuit-root-1")

    # Tamper layer.
    tampered = SchemaRegistryEntry(
        layer="federation",  # changed
        name=entry.name,
        version=entry.version,
        schema_id=entry.schema_id,
        schema_body=entry.schema_body,
        schema_body_sha256=entry.schema_body_sha256,
        registered_at=entry.registered_at,
        registered_by=entry.registered_by,
        supersedes=entry.supersedes,
    )
    assert (
        verify_entry_signature(
            tampered, pub, signature_block=signed.signature
        )
        is False
    )

    # Tamper registered_by (common identity-substrate attack vector).
    tampered2 = SchemaRegistryEntry(
        layer=entry.layer,
        name=entry.name,
        version=entry.version,
        schema_id=entry.schema_id,
        schema_body=entry.schema_body,
        schema_body_sha256=entry.schema_body_sha256,
        registered_at=entry.registered_at,
        registered_by="mallory-spoof-aip-id",  # changed
        supersedes=entry.supersedes,
    )
    assert (
        verify_entry_signature(
            tampered2, pub, signature_block=signed.signature
        )
        is False
    )

    # Tamper schema_body (whose hash is in schema_body_sha256 — but we
    # tamper the body only, leaving the hash field stale; signature is
    # over the WHOLE envelope minus signature, so the discrepancy is
    # cryptographically detected even though the gate-level digest
    # gate would also catch it independently).
    tampered_body = dict(entry.schema_body)
    tampered_body["properties"] = {"foo": {"type": "integer"}}
    tampered3 = SchemaRegistryEntry(
        layer=entry.layer,
        name=entry.name,
        version=entry.version,
        schema_id=entry.schema_id,
        schema_body=tampered_body,
        schema_body_sha256=entry.schema_body_sha256,  # stale; OK for sig test
        registered_at=entry.registered_at,
        registered_by=entry.registered_by,
        supersedes=entry.supersedes,
    )
    assert (
        verify_entry_signature(
            tampered3, pub, signature_block=signed.signature
        )
        is False
    )


# ---------------------------------------------------------------------------
# T-SR-SIG-05: self-reference exclusion (signature slot stripped before
# canonicalisation).
# ---------------------------------------------------------------------------


def test_t_sr_sig_05_signature_self_reference_exclusion() -> None:
    priv, pub = _ed25519_keypair(_FIXED_SEED_A)
    entry = _make_entry()
    signed = sign_entry(entry, priv, kid="biscuit-root-1")

    # The signing pre-image is computed over the entry alone (the
    # SignedSchemaRegistryEntry's signature block is not in the
    # _canonical_signing_payload input). Modifying the signature block
    # (kid only — keep the signature bytes valid) does not affect the
    # pre-image; verification still succeeds with the modified kid as
    # long as the signature itself is the original Ed25519-signed
    # digest.
    alt_block = dict(signed.signature)
    alt_block["kid"] = "biscuit-root-2"
    # The signing pre-image is identical (kid is NOT part of the
    # canonicalised envelope payload — it lives only in the signature
    # block, which is stripped).
    digest_orig = _canonical_signing_payload(signed.entry)
    digest_alt = _canonical_signing_payload(signed.entry)
    assert digest_orig == digest_alt
    # And verification still passes with the alt block (because the
    # alt block's signature bytes still cryptographically verify over
    # the same digest).
    assert (
        verify_entry_signature(entry, pub, signature_block=alt_block)
        is True
    )


# ---------------------------------------------------------------------------
# T-SR-SIG-06: envelope_with_signature ↔ envelope_to_signed_entry round-trip.
# ---------------------------------------------------------------------------


def test_t_sr_sig_06_envelope_helpers_roundtrip() -> None:
    priv, _ = _ed25519_keypair(_FIXED_SEED_A)
    entry = _make_entry()
    signed = sign_entry(entry, priv, kid="biscuit-root-1")

    blob = envelope_with_signature(signed)
    assert isinstance(blob, bytes)

    decoded = envelope_to_signed_entry(blob)
    assert isinstance(decoded, SignedSchemaRegistryEntry)
    assert decoded.entry == entry
    assert dict(decoded.signature) == dict(signed.signature)


# ---------------------------------------------------------------------------
# T-SR-SIG-07: backward compatibility — v0.5.0 envelope (no signature)
# round-trips through envelope_to_signed_entry as plain SchemaRegistryEntry.
# ---------------------------------------------------------------------------


def test_t_sr_sig_07_backward_compat_unsigned_envelope() -> None:
    entry = _make_entry()
    blob = _entry_to_envelope(entry)  # Tag-1 codec output, no signature

    decoded = envelope_to_signed_entry(blob)
    assert not isinstance(decoded, SignedSchemaRegistryEntry)
    assert isinstance(decoded, SchemaRegistryEntry)
    assert decoded == entry


# ---------------------------------------------------------------------------
# T-SR-SIG-08: PERMISSIVE mode accepts unsigned entries.
# ---------------------------------------------------------------------------


def test_t_sr_sig_08_permissive_mode_accepts_unsigned() -> None:
    priv, pub = _ed25519_keypair(_FIXED_SEED_A)
    entry = _make_entry()

    # Bare entry, no signature block: PERMISSIVE returns True.
    assert (
        verify_entry_signature(entry, mode=VerifyMode.PERMISSIVE) is True
    )
    # Same default behaviour.
    assert verify_entry_signature(entry) is True

    # Signed entry under PERMISSIVE is verified end-to-end.
    signed = sign_entry(entry, priv, kid="biscuit-root-1")
    assert (
        verify_entry_signature(signed, pub, mode=VerifyMode.PERMISSIVE)
        is True
    )


# ---------------------------------------------------------------------------
# T-SR-SIG-09: STRICT mode rejects unsigned entries.
# ---------------------------------------------------------------------------


def test_t_sr_sig_09_strict_mode_rejects_unsigned() -> None:
    priv, pub = _ed25519_keypair(_FIXED_SEED_A)
    entry = _make_entry()

    with pytest.raises(SchemaRegistrySignatureError) as exc:
        verify_entry_signature(entry, mode=VerifyMode.STRICT)
    assert "unsigned" in str(exc.value).lower()

    # STRICT on a signed entry verifies end-to-end normally.
    signed = sign_entry(entry, priv, kid="biscuit-root-1")
    assert (
        verify_entry_signature(signed, pub, mode=VerifyMode.STRICT)
        is True
    )


# ---------------------------------------------------------------------------
# T-SR-SIG-10: wrong public key returns False (cryptographic failure,
# not structural).
# ---------------------------------------------------------------------------


def test_t_sr_sig_10_wrong_public_key_returns_false() -> None:
    priv_a, _ = _ed25519_keypair(_FIXED_SEED_A)
    _, pub_b = _ed25519_keypair(_FIXED_SEED_B)
    entry = _make_entry()
    signed = sign_entry(entry, priv_a, kid="biscuit-root-1")

    # Verify with the WRONG public key: returns False, does NOT raise.
    assert verify_entry_signature(signed, pub_b) is False


# ---------------------------------------------------------------------------
# T-SR-SIG-11: wrong key length raises structural failure.
# ---------------------------------------------------------------------------


def test_t_sr_sig_11_wrong_key_length() -> None:
    entry = _make_entry()

    # Wrong private-key length.
    with pytest.raises(SchemaRegistrySignatureError):
        sign_entry(entry, b"\x00" * 31, kid="biscuit-root-1")
    with pytest.raises(SchemaRegistrySignatureError):
        sign_entry(entry, b"\x00" * 33, kid="biscuit-root-1")

    # Wrong public-key length on verify.
    priv, _ = _ed25519_keypair(_FIXED_SEED_A)
    signed = sign_entry(entry, priv, kid="biscuit-root-1")
    with pytest.raises(SchemaRegistrySignatureError):
        verify_entry_signature(signed, b"\x00" * 31)
    with pytest.raises(SchemaRegistrySignatureError):
        verify_entry_signature(signed, b"\x00" * 33)

    # Empty kid.
    priv2, _ = _ed25519_keypair(_FIXED_SEED_A)
    with pytest.raises(SchemaRegistrySignatureError):
        sign_entry(entry, priv2, kid="")


# ---------------------------------------------------------------------------
# T-SR-SIG-12: Tag-1 codec parity — signed envelope differs from Tag-1
# only by the optional signature slot.
# ---------------------------------------------------------------------------


def test_t_sr_sig_12_tag1_codec_parity() -> None:
    priv, _ = _ed25519_keypair(_FIXED_SEED_A)
    entry = _make_entry()
    signed = sign_entry(entry, priv, kid="biscuit-root-1")

    tag1_blob = _entry_to_envelope(entry)
    signed_blob = envelope_with_signature(signed)

    tag1_payload = json.loads(tag1_blob.decode("utf-8"))
    signed_payload = json.loads(signed_blob.decode("utf-8"))

    # Stripping the signature slot from the signed envelope MUST yield
    # exactly the Tag-1 envelope.
    stripped = dict(signed_payload)
    assert "signature" in stripped
    stripped.pop("signature")
    assert stripped == tag1_payload

    # Round-tripping the stripped payload through the Tag-1 decoder
    # recovers the original entry byte-equal.
    stripped_blob = json.dumps(
        stripped, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    decoded = _envelope_to_entry(stripped_blob)
    assert decoded == entry
