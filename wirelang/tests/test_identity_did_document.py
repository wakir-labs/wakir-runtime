# SPDX-License-Identifier: Apache-2.0
"""Tests for the persona did:web document generator.

The DID-Core specification does not bake the verification-method types
into the core spec; instead the types are registered separately. We
test for structural conformance: required keys, two verification
methods (one per curve), key-length sanity, and the versioned
publication-path convention from consensus marker B2.
"""

from __future__ import annotations

import pytest

from wirelang.identity import generate_persona_did_document
from wirelang.identity.did_document import (
    did_document_publication_path,
    parse_did_document_version_from_path,
)


SECP_PUB_33 = bytes.fromhex(
    "0339a36013301597daef41fbe593a02cc513d0b55527ec2df1050e2e8ff49c85c2"
)
ED_PUB_32 = bytes.fromhex(
    "a4b2856bfec510abab89753fac1ac0e1112364e7d250545963f135f2a33188ed"
)


def test_did_document_minimal_shape() -> None:
    doc = generate_persona_did_document(
        "treasury-issuer", SECP_PUB_33, ED_PUB_32
    )
    assert doc["id"] == "did:web:wakir.dev:personas:treasury-issuer"
    assert "@context" in doc
    assert isinstance(doc["@context"], list)
    assert "https://www.w3.org/ns/did/v1" in doc["@context"]
    assert isinstance(doc["verificationMethod"], list)
    assert len(doc["verificationMethod"]) == 2


def test_did_document_two_curve_verification_methods_present() -> None:
    doc = generate_persona_did_document(
        "treasury-issuer", SECP_PUB_33, ED_PUB_32
    )
    types = sorted(vm["type"] for vm in doc["verificationMethod"])
    assert types == [
        "EcdsaSecp256k1VerificationKey2019",
        "Ed25519VerificationKey2020",
    ]


def test_did_document_keys_are_lowercase_hex_and_correct_length() -> None:
    doc = generate_persona_did_document(
        "treasury-issuer", SECP_PUB_33, ED_PUB_32
    )
    secp_vm = next(
        vm
        for vm in doc["verificationMethod"]
        if vm["type"].startswith("EcdsaSecp256k1")
    )
    ed_vm = next(
        vm
        for vm in doc["verificationMethod"]
        if vm["type"].startswith("Ed25519")
    )
    assert len(secp_vm["publicKeyHex"]) == 66  # 33 bytes compressed
    assert len(ed_vm["publicKeyHex"]) == 64  # 32 bytes raw
    assert secp_vm["publicKeyHex"] == secp_vm["publicKeyHex"].lower()
    assert ed_vm["publicKeyHex"] == ed_vm["publicKeyHex"].lower()


def test_did_document_authentication_lists_both_keys() -> None:
    doc = generate_persona_did_document(
        "treasury-issuer", SECP_PUB_33, ED_PUB_32
    )
    assert len(doc["authentication"]) == 2
    assert len(doc["assertionMethod"]) == 2


def test_did_document_rejects_wrong_secp_key_length() -> None:
    bad = b"\x00" * 32  # wrong: 32, not 33
    with pytest.raises(ValueError, match="33-byte"):
        generate_persona_did_document("treasury-issuer", bad, ED_PUB_32)


def test_did_document_rejects_wrong_ed25519_key_length() -> None:
    bad = b"\x00" * 31  # wrong: 31, not 32
    with pytest.raises(ValueError, match="32-byte"):
        generate_persona_did_document("treasury-issuer", SECP_PUB_33, bad)


def test_did_document_rejects_persona_id_with_slash() -> None:
    with pytest.raises(ValueError, match="bare role-string"):
        generate_persona_did_document(
            "treasury/issuer", SECP_PUB_33, ED_PUB_32
        )


def test_did_document_rejects_host_with_scheme() -> None:
    with pytest.raises(ValueError, match="bare DNS name"):
        generate_persona_did_document(
            "treasury-issuer",
            SECP_PUB_33,
            ED_PUB_32,
            host="https://wakir.dev",
        )


def test_did_document_version_default_is_1() -> None:
    doc = generate_persona_did_document(
        "treasury-issuer", SECP_PUB_33, ED_PUB_32
    )
    assert doc["wakirVersion"] == 1


def test_did_document_rejects_version_below_1() -> None:
    with pytest.raises(ValueError, match="version"):
        generate_persona_did_document(
            "treasury-issuer", SECP_PUB_33, ED_PUB_32, version=0
        )


def test_publication_path_versioned_layout() -> None:
    assert did_document_publication_path("treasury-issuer", 1) == (
        ".well-known/did/treasury-issuer/v1.json"
    )
    assert did_document_publication_path("cfo-agent", 17) == (
        ".well-known/did/cfo-agent/v17.json"
    )


def test_publication_path_round_trip_with_parser() -> None:
    path = did_document_publication_path("treasury-issuer", 7)
    assert parse_did_document_version_from_path(path) == 7


def test_parser_returns_none_for_non_did_path() -> None:
    assert parse_did_document_version_from_path(
        ".well-known/openid-configuration"
    ) is None
    assert parse_did_document_version_from_path("/some/random/file.json") is None
