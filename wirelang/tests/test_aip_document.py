# SPDX-License-Identifier: Apache-2.0
"""Schema-compliance tests for the AIP document schema (draft-prakash-aip-00 conformance)."""

from __future__ import annotations

import copy


_ED25519_PK = "abababababababababababababababababababababababababababababababab"
_ED25519_PK_B = "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd"
_ED25519_SIG = (
    "3333333333333333333333333333333333333333333333333333333333333333"
    "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
)
_SECP256K1_PK = "02" + ("a" * 64)  # 33 bytes compressed = 66 hex


def _base_doc() -> dict:
    return {
        "aip": "1.0",
        "id": "aip:web:wakir.dev/treasury-issuer",
        "name": "treasury-issuer",
        "public_keys": [
            {
                "kid": "key-1",
                "alg": "Ed25519",
                "key_hex": _ED25519_PK,
                "validafter": "2026-05-06T00:00:00Z",
                "validuntil": None,
                "purpose": "aip-signing",
            }
        ],
        "delegation": {"mode": "chained", "max_depth": 3},
        "protocols": ["wirelang/0.1"],
        "expires": "2027-05-06T00:00:00Z",
        "document_signature": {
            "alg": "Ed25519",
            "kid": "key-1",
            "signature": _ED25519_SIG,
        },
    }


# ---- positive cases ----


def test_positive_minimal_aip_web_doc(aip_document_validator):
    assert aip_document_validator.is_valid(_base_doc())


def test_positive_aip_key_self_certifying(aip_document_validator):
    doc = _base_doc()
    doc["id"] = "aip:key:ed25519:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK"
    assert aip_document_validator.is_valid(doc)


def test_positive_two_curve_stack_keys(aip_document_validator):
    """Wakir Phase-1a two-curve stack: Ed25519 + secp256k1 keys coexist."""
    doc = _base_doc()
    doc["public_keys"].append(
        {
            "kid": "secp-1",
            "alg": "secp256k1",
            "key_hex": _SECP256K1_PK,
            "validafter": "2026-05-06T00:00:00Z",
            "validuntil": None,
        }
    )
    assert aip_document_validator.is_valid(doc)


def test_positive_with_biscuit_root_pubkey_extension(aip_document_validator):
    doc = _base_doc()
    doc["biscuit_root_pubkey"] = _ED25519_PK_B
    assert aip_document_validator.is_valid(doc)


def test_positive_with_verification_methods_extension(aip_document_validator):
    doc = _base_doc()
    doc["verification_methods"] = [
        {
            "id": "#vm-1",
            "type": "Ed25519VerificationKey2020",
            "controller": "aip:web:wakir.dev/treasury-issuer",
            "publicKeyHex": _ED25519_PK,
        }
    ]
    assert aip_document_validator.is_valid(doc)


def test_positive_with_service_endpoints_extension(aip_document_validator):
    doc = _base_doc()
    doc["service_endpoints"] = [
        {
            "id": "#wirelang",
            "type": "WirelangIngest",
            "serviceEndpoint": "https://wakir.dev/wirelang/ingest",
        }
    ]
    assert aip_document_validator.is_valid(doc)


def test_positive_example_doc_validates(aip_document_validator, example_aip_document):
    assert aip_document_validator.is_valid(example_aip_document)


# ---- negative cases ----


def test_negative_wrong_aip_version(aip_document_validator):
    doc = _base_doc()
    doc["aip"] = "0.9"
    assert not aip_document_validator.is_valid(doc)


def test_negative_id_invalid_scheme(aip_document_validator):
    doc = _base_doc()
    doc["id"] = "https://wakir.dev/issuer"
    assert not aip_document_validator.is_valid(doc)


def test_negative_empty_public_keys(aip_document_validator):
    doc = _base_doc()
    doc["public_keys"] = []
    assert not aip_document_validator.is_valid(doc)


def test_negative_unknown_key_alg(aip_document_validator):
    doc = _base_doc()
    doc["public_keys"][0]["alg"] = "RSA"
    assert not aip_document_validator.is_valid(doc)


def test_negative_signature_wrong_length(aip_document_validator):
    doc = _base_doc()
    doc["document_signature"]["signature"] = "deadbeef"
    assert not aip_document_validator.is_valid(doc)


def test_negative_unknown_delegation_mode(aip_document_validator):
    doc = _base_doc()
    doc["delegation"]["mode"] = "anarchy"
    assert not aip_document_validator.is_valid(doc)


def test_negative_missing_protocols(aip_document_validator):
    doc = _base_doc()
    del doc["protocols"]
    assert not aip_document_validator.is_valid(doc)


def test_negative_extra_property_at_root(aip_document_validator):
    doc = _base_doc()
    doc["bonus"] = "x"
    assert not aip_document_validator.is_valid(doc)


def test_negative_biscuit_root_pubkey_wrong_length(aip_document_validator):
    doc = _base_doc()
    doc["biscuit_root_pubkey"] = "abcd"
    assert not aip_document_validator.is_valid(doc)


def test_negative_doc_sig_alg_not_ed25519(aip_document_validator):
    doc = _base_doc()
    doc["document_signature"]["alg"] = "RS256"
    assert not aip_document_validator.is_valid(doc)
