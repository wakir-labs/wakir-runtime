# SPDX-License-Identifier: Apache-2.0
"""Tests for the AIP-document generator.

Verifies:

- Generated documents validate against the day-2 AIP JSON Schema
  (``wirelang/schemas/aip-document.json``).
- The ``biscuit_root_pubkey`` Wakir extension is populated and matches
  the supplied Ed25519 public key.
- Required AIP-draft-section-2.3 fields are present.
- Defensive checks (key length, persona id shape, delegation-mode
  enum) raise.
"""

from __future__ import annotations

import re

import pytest

from wirelang.identity import generate_aip_document


ED_PUB_32 = bytes.fromhex(
    "a4b2856bfec510abab89753fac1ac0e1112364e7d250545963f135f2a33188ed"
)


def test_aip_document_validates_against_day2_schema(
    aip_document_validator,
) -> None:
    doc = generate_aip_document(
        "treasury-issuer",
        ED_PUB_32,
        "did:web:wakir.dev:personas:treasury-issuer",
    )
    aip_document_validator.validate(doc)


def test_aip_document_required_aip_fields_present() -> None:
    doc = generate_aip_document(
        "treasury-issuer",
        ED_PUB_32,
        "did:web:wakir.dev:personas:treasury-issuer",
    )
    for field in (
        "aip",
        "id",
        "name",
        "public_keys",
        "delegation",
        "protocols",
        "expires",
        "document_signature",
    ):
        assert field in doc, f"required AIP field missing: {field}"
    assert doc["aip"] == "1.0"


def test_aip_document_biscuit_root_pubkey_matches_input() -> None:
    doc = generate_aip_document(
        "treasury-issuer",
        ED_PUB_32,
        "did:web:wakir.dev:personas:treasury-issuer",
    )
    assert doc["biscuit_root_pubkey"] == ED_PUB_32.hex()
    # Public key entry mirrors it under purpose="biscuit-root".
    bk = next(pk for pk in doc["public_keys"] if pk["purpose"] == "biscuit-root")
    assert bk["key_hex"] == ED_PUB_32.hex()
    assert bk["alg"] == "Ed25519"


def test_aip_document_id_default_is_aip_web_form() -> None:
    doc = generate_aip_document(
        "treasury-issuer",
        ED_PUB_32,
        "did:web:wakir.dev:personas:treasury-issuer",
    )
    assert doc["id"].startswith("aip:web:wakir.dev/personas/")
    assert doc["id"].endswith("/treasury-issuer")


def test_aip_document_delegation_default_is_chained() -> None:
    doc = generate_aip_document(
        "treasury-issuer",
        ED_PUB_32,
        "did:web:wakir.dev:personas:treasury-issuer",
    )
    assert doc["delegation"]["mode"] == "chained"


def test_aip_document_supports_compact_and_both_modes(
    aip_document_validator,
) -> None:
    for mode in ("compact", "chained", "both"):
        doc = generate_aip_document(
            "treasury-issuer",
            ED_PUB_32,
            "did:web:wakir.dev:personas:treasury-issuer",
            delegation_mode=mode,
        )
        aip_document_validator.validate(doc)
        assert doc["delegation"]["mode"] == mode


def test_aip_document_rejects_unknown_delegation_mode() -> None:
    with pytest.raises(ValueError, match="delegation_mode"):
        generate_aip_document(
            "treasury-issuer",
            ED_PUB_32,
            "did:web:wakir.dev:personas:treasury-issuer",
            delegation_mode="hyper-mode",
        )


def test_aip_document_rejects_wrong_ed25519_key_length() -> None:
    with pytest.raises(ValueError, match="32-byte"):
        generate_aip_document(
            "treasury-issuer",
            b"\x00" * 31,
            "did:web:wakir.dev:personas:treasury-issuer",
        )


def test_aip_document_signature_is_placeholder_caller_must_replace() -> None:
    doc = generate_aip_document(
        "treasury-issuer",
        ED_PUB_32,
        "did:web:wakir.dev:personas:treasury-issuer",
    )
    sig = doc["document_signature"]
    assert sig["alg"] == "Ed25519"
    assert sig["signature"] == "00" * 64
    assert re.fullmatch(r"[0-9a-f]{128}", sig["signature"])


def test_aip_document_rejects_persona_id_with_colons() -> None:
    with pytest.raises(ValueError, match="bare role-string"):
        generate_aip_document(
            "treasury:issuer",
            ED_PUB_32,
            "did:web:wakir.dev:personas:treasury-issuer",
        )


def test_aip_document_uses_overridden_aip_id_when_given(
    aip_document_validator,
) -> None:
    custom_id = "aip:web:wakir.dev/special-persona-path"
    doc = generate_aip_document(
        "treasury-issuer",
        ED_PUB_32,
        "did:web:wakir.dev:personas:treasury-issuer",
        aip_id=custom_id,
    )
    aip_document_validator.validate(doc)
    assert doc["id"] == custom_id
