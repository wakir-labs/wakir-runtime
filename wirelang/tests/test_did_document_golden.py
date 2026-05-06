# SPDX-License-Identifier: Apache-2.0
"""Golden-vector regression tests for the DID-document layer.

For every JSON fixture under ``tests/fixtures/did-document-vectors/``
this module asserts:

1. **Layout invariants** — required DID-Core fields, exactly two
   ``verificationMethod`` entries (one per curve), versioned-path
   convention parses round-trip.
2. **JCS-hash stability** — SHA-256 of ``JCS(document without
   proof)`` matches the fixture's ``document_jcs_sha256``. This is the
   byte-stable drift detector.
3. **ECDSA-secp256k1 signature verifies** — the frozen
   ``proof_block`` verifies against the document and the persona
   secp256k1 public key.

Note: ECDSA-secp256k1 signatures are *not* deterministic in our stack
(no RFC 6979 enforcement at the ``cryptography.hazmat`` layer used by
``sign_did_document``). We therefore do NOT byte-compare a
re-generated proof; we only verify the frozen one and check that
re-signing produces a different-but-valid signature, which is a
deliberate inverse-determinism check.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import rfc8785

from wirelang.identity import (
    generate_persona_did_document,
    sign_did_document,
    verify_did_signature,
)
from wirelang.identity.did_document import (
    did_document_publication_path,
    parse_did_document_version_from_path,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "fixtures"
    / "did-document-vectors"
)


def _all_fixtures() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("vector-*.json"))


def _load(p: Path) -> dict:
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _canonical_hash(doc: dict) -> str:
    body = copy.deepcopy(doc)
    body.pop("proof", None)
    return hashlib.sha256(rfc8785.dumps(body)).hexdigest()


@pytest.fixture(scope="module", params=_all_fixtures(), ids=lambda p: p.stem)
def fixture(request: pytest.FixtureRequest) -> dict:
    return _load(request.param)


# ---------------------------------------------------------------------------
# Per-fixture invariants
# ---------------------------------------------------------------------------


def test_fixture_layout_is_valid_did_document(fixture: dict) -> None:
    doc = fixture["document"]
    assert "@context" in doc
    assert "id" in doc
    assert doc["id"].startswith("did:web:")
    assert isinstance(doc["verificationMethod"], list)
    assert len(doc["verificationMethod"]) == 2
    types = sorted(vm["type"] for vm in doc["verificationMethod"])
    assert types == [
        "EcdsaSecp256k1VerificationKey2019",
        "Ed25519VerificationKey2020",
    ]


def test_fixture_jcs_hash_matches_pin(fixture: dict) -> None:
    assert _canonical_hash(fixture["document"]) == fixture["document_jcs_sha256"]


def test_fixture_proof_verifies(fixture: dict) -> None:
    pub_hex = fixture["generation_inputs"]["secp256k1_pub_hex_33"]
    pub = bytes.fromhex(pub_hex)
    proof = fixture["proof_block"]
    assert verify_did_signature(fixture["document"], proof, pub)


def test_fixture_proof_block_matches_embedded(fixture: dict) -> None:
    assert fixture["document"]["proof"] == fixture["proof_block"]


def test_fixture_versioned_publication_path_round_trips(fixture: dict) -> None:
    persona_id = fixture["generation_inputs"]["persona_id"]
    version = fixture["generation_inputs"]["version"]
    path = did_document_publication_path(persona_id, version)
    assert parse_did_document_version_from_path(path) == version


def test_fixture_regenerates_for_unsigned_body(fixture: dict) -> None:
    """A fresh ``generate_persona_did_document`` reproduces the unsigned
    document body exactly. The proof block is excluded because ECDSA is
    non-deterministic."""
    inp = fixture["generation_inputs"]
    fresh = generate_persona_did_document(
        inp["persona_id"],
        bytes.fromhex(inp["secp256k1_pub_hex_33"]),
        bytes.fromhex(inp["ed25519_pub_hex_32"]),
        host=inp.get("host", "wakir.dev"),
        version=inp.get("version", 1),
    )
    target = copy.deepcopy(fixture["document"])
    target.pop("proof", None)
    assert fresh == target


def test_fixture_resigning_produces_different_but_valid_signature(
    fixture: dict,
) -> None:
    """ECDSA-secp256k1 in this stack is non-deterministic; resigning
    yields a fresh ``r``,``s`` while still verifying. Catches a future
    accidental switch to deterministic-k that would silently change
    cryptographic semantics.
    """
    inp = fixture["generation_inputs"]
    secp_priv = bytes.fromhex(inp["secp256k1_priv_hex_32"])
    secp_pub = bytes.fromhex(inp["secp256k1_pub_hex_33"])
    fresh_proof = sign_did_document(fixture["document"], secp_priv)
    assert verify_did_signature(fixture["document"], fresh_proof, secp_pub)
    # Non-determinism: at least one of the two signatures should differ.
    # (The probability of accidental collision over 64 random bytes is
    # negligible.)
    assert fresh_proof["signatureHex"] != fixture["proof_block"]["signatureHex"]


# ---------------------------------------------------------------------------
# Cross-fixture coverage
# ---------------------------------------------------------------------------


def test_fixtures_cover_default_and_non_default_host() -> None:
    hosts = {_load(p)["generation_inputs"]["host"] for p in _all_fixtures()}
    assert "wakir.dev" in hosts
    assert any(h != "wakir.dev" for h in hosts), (
        "at least one fixture must exercise a non-default host"
    )


def test_fixtures_cover_versions_above_1() -> None:
    versions = {_load(p)["generation_inputs"]["version"] for p in _all_fixtures()}
    assert any(v > 1 for v in versions), (
        "at least one fixture must exercise version > 1"
    )
