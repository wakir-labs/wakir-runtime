# SPDX-License-Identifier: Apache-2.0
"""Schema-compliance tests for Wirelang Layer 3 — Capability Token (Biscuit v3 wrapper)."""

from __future__ import annotations

import copy


_HEX_SIG_128 = (
    "1111111111111111111111111111111111111111111111111111111111111111"
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)
_HEX_SIG_128_B = (
    "2222222222222222222222222222222222222222222222222222222222222222"
    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
)
_HEX_SIG_128_C = (
    "3333333333333333333333333333333333333333333333333333333333333333"
    "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
)
_HEX_PK_64 = "abababababababababababababababababababababababababababababababab"
_HEX_PK_64_B = "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd"


def _base_token() -> dict:
    return {
        "version": "biscuit-v3",
        "biscuit_format_version": 6,
        "aip_document_ref": "https://wakir.dev/.well-known/aip/treasury-issuer.json",
        "authority_block": {
            "issuer_did": "aip:web:wakir.dev/treasury-issuer",
            "audience_pattern": "role=treasury-agent",
            "caveats": [
                "check if action(\"read.balance\")",
                "check if env(\"prod\")",
            ],
            "not_before": "2026-05-06T00:00:00Z",
            "not_after": "2026-05-13T00:00:00Z",
            "nonce": "9f2b1c4a7d8e3f60a1b2c3d4e5f60718",
            "signature": _HEX_SIG_128,
            "next_pubkey": _HEX_PK_64,
        },
        "append_blocks": [],
    }


# ---- positive cases ----


def test_positive_minimal_authority_no_attenuation(layer_3_capability_token_validator):
    assert layer_3_capability_token_validator.is_valid(_base_token())


def test_positive_with_one_attenuation_block(layer_3_capability_token_validator):
    token = _base_token()
    token["append_blocks"].append(
        {
            "audience_pattern": "role=treasury-agent,scope=read-only",
            "caveats": ["check if rate_limit($n), $n <= 100"],
            "signature": _HEX_SIG_128_B,
            "next_pubkey": _HEX_PK_64_B,
        }
    )
    assert layer_3_capability_token_validator.is_valid(token)


def test_positive_sealed_with_proof_block(layer_3_capability_token_validator):
    token = _base_token()
    token["proof_block"] = {
        "final_signature": _HEX_SIG_128_C,
        "sealed_at": "2026-05-06T13:45:00Z",
    }
    assert layer_3_capability_token_validator.is_valid(token)


def test_positive_aip_key_issuer_self_certifying(layer_3_capability_token_validator):
    token = _base_token()
    token["authority_block"]["issuer_did"] = (
        "aip:key:ed25519:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK"
    )
    assert layer_3_capability_token_validator.is_valid(token)


def test_positive_did_web_issuer_crosscompat(layer_3_capability_token_validator):
    token = _base_token()
    token["authority_block"]["issuer_did"] = "did:web:wakir.dev:treasury-issuer"
    assert layer_3_capability_token_validator.is_valid(token)


def test_positive_third_party_external_signature_on_append_block(
    layer_3_capability_token_validator,
):
    token = _base_token()
    token["append_blocks"].append(
        {
            "audience_pattern": "role=auditor",
            "caveats": ["check if read_only(true)"],
            "signature": _HEX_SIG_128_B,
            "next_pubkey": _HEX_PK_64_B,
            "external_signature": {
                "signer_pubkey": _HEX_PK_64,
                "signature": _HEX_SIG_128,
            },
        }
    )
    assert layer_3_capability_token_validator.is_valid(token)


def test_positive_example_token_validates(
    layer_3_capability_token_validator, example_capability_token
):
    assert layer_3_capability_token_validator.is_valid(example_capability_token)


# ---- negative cases ----


def test_negative_wrong_version_const(layer_3_capability_token_validator):
    token = _base_token()
    token["version"] = "biscuit-v2"
    assert not layer_3_capability_token_validator.is_valid(token)


def test_negative_signature_wrong_length(layer_3_capability_token_validator):
    token = _base_token()
    token["authority_block"]["signature"] = "deadbeef"
    assert not layer_3_capability_token_validator.is_valid(token)


def test_negative_signature_non_hex(layer_3_capability_token_validator):
    token = _base_token()
    token["authority_block"]["signature"] = "Z" * 128
    assert not layer_3_capability_token_validator.is_valid(token)


def test_negative_nonce_too_short(layer_3_capability_token_validator):
    token = _base_token()
    token["authority_block"]["nonce"] = "abcd"
    assert not layer_3_capability_token_validator.is_valid(token)


def test_negative_invalid_issuer_scheme(layer_3_capability_token_validator):
    token = _base_token()
    token["authority_block"]["issuer_did"] = "https://wakir.dev/issuer"
    assert not layer_3_capability_token_validator.is_valid(token)


def test_negative_missing_authority_block(layer_3_capability_token_validator):
    token = _base_token()
    del token["authority_block"]
    assert not layer_3_capability_token_validator.is_valid(token)


def test_negative_extra_property_at_root(layer_3_capability_token_validator):
    token = _base_token()
    token["unknown"] = "x"
    assert not layer_3_capability_token_validator.is_valid(token)


def test_negative_biscuit_format_version_out_of_range(
    layer_3_capability_token_validator,
):
    token = _base_token()
    token["biscuit_format_version"] = 99
    assert not layer_3_capability_token_validator.is_valid(token)


def test_negative_append_block_missing_next_pubkey(layer_3_capability_token_validator):
    token = _base_token()
    token["append_blocks"].append(
        {
            "audience_pattern": "role=auditor",
            "caveats": [],
            "signature": _HEX_SIG_128_B,
        }
    )
    assert not layer_3_capability_token_validator.is_valid(token)


def test_negative_proof_block_missing_final_signature(
    layer_3_capability_token_validator,
):
    token = _base_token()
    token["proof_block"] = {"sealed_at": "2026-05-06T13:45:00Z"}
    assert not layer_3_capability_token_validator.is_valid(token)
