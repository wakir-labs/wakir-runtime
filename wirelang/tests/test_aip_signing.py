# SPDX-License-Identifier: Apache-2.0
"""Tests for AIP-document and DID-document signature helpers.

Verifies, for both the Ed25519 (AIP) and secp256k1 (DID) paths:

- Sign + verify round-trip on a generator-produced document.
- Tamper detection: any field change invalidates the signature.
- Algorithm and key-length defensive checks.
- Signing input excludes the signature/proof slot itself.
- The signed document still validates against its JSON schema.
"""

from __future__ import annotations

import copy

import pytest

from wirelang.identity import (
    derive_persona_master_ed25519,
    derive_persona_master_secp256k1,
    generate_aip_document,
    generate_persona_did_document,
)
from wirelang.identity.aip_signing import (
    sign_aip_document,
    verify_aip_signature,
)
from wirelang.identity.did_document_signing import (
    sign_did_document,
    verify_did_signature,
)
from wirelang.identity.key_derivation import (
    ed25519_public_from_private,
    secp256k1_public_from_private,
)


SEED = bytes.fromhex("000102030405060708090a0b0c0d0e0f")


# ---------------------------------------------------------------------------
# AIP / Ed25519 signing
# ---------------------------------------------------------------------------


def _make_aip_doc():
    ed_priv = derive_persona_master_ed25519(SEED)
    ed_pub = ed25519_public_from_private(ed_priv)
    doc = generate_aip_document(
        "treasury-issuer",
        ed_pub,
        "did:web:wakir.dev:personas:treasury-issuer",
    )
    return ed_priv, ed_pub, doc


def test_aip_sign_verify_round_trip() -> None:
    ed_priv, ed_pub, doc = _make_aip_doc()
    sig = sign_aip_document(doc, ed_priv)
    doc["document_signature"] = sig
    assert verify_aip_signature(doc, sig, ed_pub) is True


def test_aip_signature_block_has_required_fields() -> None:
    ed_priv, _, doc = _make_aip_doc()
    sig = sign_aip_document(doc, ed_priv)
    assert sig["alg"] == "Ed25519"
    assert sig["kid"] == "biscuit-root-1"
    assert isinstance(sig["signature"], str)
    assert len(sig["signature"]) == 128  # 64 bytes hex
    int(sig["signature"], 16)  # parses as hex


def test_aip_tamper_changes_invalidate_signature() -> None:
    ed_priv, ed_pub, doc = _make_aip_doc()
    sig = sign_aip_document(doc, ed_priv)
    doc["document_signature"] = sig
    tampered = copy.deepcopy(doc)
    tampered["name"] = "evil-persona"
    assert verify_aip_signature(tampered, sig, ed_pub) is False


def test_aip_signature_excludes_signature_field_from_payload() -> None:
    """Signing twice with different placeholder signatures must agree.

    Because the signature slot is stripped before canonicalisation,
    the placeholder content must not influence the produced signature.
    """
    ed_priv, _, doc = _make_aip_doc()
    sig_a = sign_aip_document(doc, ed_priv)
    doc_b = copy.deepcopy(doc)
    doc_b["document_signature"] = {
        "alg": "Ed25519",
        "kid": "biscuit-root-1",
        "signature": "ff" * 64,
    }
    sig_b = sign_aip_document(doc_b, ed_priv)
    assert sig_a["signature"] == sig_b["signature"]


def test_aip_verify_rejects_unsupported_algorithm() -> None:
    _, ed_pub, doc = _make_aip_doc()
    bad_sig = {"alg": "RS256", "signature": "00" * 64}
    with pytest.raises(ValueError, match="alg"):
        verify_aip_signature(doc, bad_sig, ed_pub)


def test_aip_verify_rejects_wrong_signature_length() -> None:
    _, ed_pub, doc = _make_aip_doc()
    bad_sig = {"alg": "Ed25519", "signature": "00" * 32}
    with pytest.raises(ValueError, match="64 bytes"):
        verify_aip_signature(doc, bad_sig, ed_pub)


def test_aip_sign_rejects_wrong_private_key_length() -> None:
    _, _, doc = _make_aip_doc()
    with pytest.raises(ValueError, match="32-byte"):
        sign_aip_document(doc, b"\x00" * 31)


def test_aip_verify_rejects_wrong_public_key_length() -> None:
    ed_priv, _, doc = _make_aip_doc()
    sig = sign_aip_document(doc, ed_priv)
    with pytest.raises(ValueError, match="32-byte"):
        verify_aip_signature(doc, sig, b"\x00" * 31)


def test_aip_verify_returns_false_on_wrong_public_key() -> None:
    """Cryptographic mismatch (right format, wrong key) returns False."""
    ed_priv, _, doc = _make_aip_doc()
    sig = sign_aip_document(doc, ed_priv)
    other_priv = derive_persona_master_ed25519(b"\x01" * 16)
    other_pub = ed25519_public_from_private(other_priv)
    assert verify_aip_signature(doc, sig, other_pub) is False


def test_aip_signed_document_still_validates_against_schema(
    aip_document_validator,
) -> None:
    """Attaching the signature must not break the AIP JSON schema."""
    ed_priv, _, doc = _make_aip_doc()
    sig = sign_aip_document(doc, ed_priv)
    doc["document_signature"] = sig
    aip_document_validator.validate(doc)


# ---------------------------------------------------------------------------
# DID / secp256k1 signing
# ---------------------------------------------------------------------------


def _make_did_doc():
    sk_priv = derive_persona_master_secp256k1(SEED)
    sk_pub = secp256k1_public_from_private(sk_priv, compressed=True)
    ed_priv = derive_persona_master_ed25519(SEED)
    ed_pub = ed25519_public_from_private(ed_priv)
    doc = generate_persona_did_document("treasury-issuer", sk_pub, ed_pub)
    return sk_priv, sk_pub, doc


def test_did_sign_verify_round_trip() -> None:
    sk_priv, sk_pub, doc = _make_did_doc()
    proof = sign_did_document(doc, sk_priv)
    doc["proof"] = proof
    assert verify_did_signature(doc, proof, sk_pub) is True


def test_did_proof_block_has_required_fields() -> None:
    sk_priv, _, doc = _make_did_doc()
    proof = sign_did_document(doc, sk_priv)
    assert proof["type"] == "EcdsaSecp256k1Signature2019"
    assert proof["alg"] == "ES256K"
    assert proof["verificationMethod"].endswith("#keys-secp256k1-1")
    assert len(proof["signatureHex"]) == 128


def test_did_tamper_changes_invalidate_signature() -> None:
    sk_priv, sk_pub, doc = _make_did_doc()
    proof = sign_did_document(doc, sk_priv)
    doc["proof"] = proof
    tampered = copy.deepcopy(doc)
    tampered["wakirVersion"] = 99
    assert verify_did_signature(tampered, proof, sk_pub) is False


def test_did_signature_excludes_proof_field_from_payload() -> None:
    """Signing with vs. without a proof slot must produce verifiably
    equivalent payload-bound signatures.

    ECDSA over secp256k1 in ``cryptography`` uses a random nonce, so
    two signatures over the same digest will differ byte-for-byte. We
    therefore assert payload-equivalence by *cross-verifying*: each
    signature MUST validate against the un-tampered base document
    regardless of whether a placeholder proof slot was present at
    signing time.
    """
    sk_priv, sk_pub, doc = _make_did_doc()
    proof_a = sign_did_document(doc, sk_priv)
    doc_b = copy.deepcopy(doc)
    doc_b["proof"] = {
        "type": "EcdsaSecp256k1Signature2019",
        "alg": "ES256K",
        "signatureHex": "ff" * 64,
        "verificationMethod": "did:example:placeholder",
    }
    proof_b = sign_did_document(doc_b, sk_priv)
    # Both signatures bind the same payload (proof slot stripped on
    # both sides); both must verify against the un-modified document.
    assert verify_did_signature(doc, proof_a, sk_pub) is True
    assert verify_did_signature(doc, proof_b, sk_pub) is True


def test_did_verify_rejects_wrong_proof_type() -> None:
    sk_priv, sk_pub, doc = _make_did_doc()
    proof = sign_did_document(doc, sk_priv)
    proof["type"] = "Ed25519Signature2020"
    with pytest.raises(ValueError, match="proof type"):
        verify_did_signature(doc, proof, sk_pub)


def test_did_verify_rejects_wrong_alg() -> None:
    sk_priv, sk_pub, doc = _make_did_doc()
    proof = sign_did_document(doc, sk_priv)
    proof["alg"] = "ES256"
    with pytest.raises(ValueError, match="proof alg"):
        verify_did_signature(doc, proof, sk_pub)


def test_did_sign_rejects_wrong_private_key_length() -> None:
    _, _, doc = _make_did_doc()
    with pytest.raises(ValueError, match="32 bytes"):
        sign_did_document(doc, b"\x00" * 31)


def test_did_verify_rejects_wrong_public_key_length() -> None:
    sk_priv, _, doc = _make_did_doc()
    proof = sign_did_document(doc, sk_priv)
    with pytest.raises(ValueError, match="33 bytes"):
        verify_did_signature(doc, proof, b"\x02" + b"\x00" * 31)


def test_did_verify_returns_false_on_wrong_public_key() -> None:
    sk_priv, _, doc = _make_did_doc()
    proof = sign_did_document(doc, sk_priv)
    other_priv = derive_persona_master_secp256k1(b"\x02" * 16)
    other_pub = secp256k1_public_from_private(other_priv, compressed=True)
    assert verify_did_signature(doc, proof, other_pub) is False


def test_did_sign_uses_default_verification_method_id() -> None:
    sk_priv, _, doc = _make_did_doc()
    proof = sign_did_document(doc, sk_priv)
    expected_vm_id = f"{doc['id']}#keys-secp256k1-1"
    assert proof["verificationMethod"] == expected_vm_id
