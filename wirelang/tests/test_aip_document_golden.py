# SPDX-License-Identifier: Apache-2.0
"""Golden-vector regression tests for the AIP-document layer.

For every JSON fixture under ``tests/fixtures/aip-document-vectors/``
this module asserts:

1. **Schema conformance** — the frozen ``document`` body validates
   against ``wirelang/schemas/aip-document.json``.
2. **JCS-hash stability** — the SHA-256 of ``JCS(document without
   document_signature)`` matches the fixture's ``document_jcs_sha256``.
   Any change in the JCS canonicalisation, in the document layout, or
   in field naming will break this assertion at byte granularity.
3. **Ed25519 signature verifies** — the frozen ``signature_block``
   verifies against the document and the publishing public key. Ed25519
   is deterministic per RFC 8032, so a re-signing under the same key
   produces an identical byte-string; this is asserted as well.
4. **Re-generation determinism** — re-running
   :func:`wirelang.identity.generate_aip_document` with the same
   ``generation_inputs`` reproduces the document modulo the documented
   ``post_generation_mutations``.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

# Sandbox-CI: skip the entire module when rfc8785 is not installed.
# This module recomputes JCS-SHA-256 directly via rfc8785.dumps for
# golden-vector parity with the production-anchor manifests. The
# pure-Python JCS path (test_pure_python_fallback.py #29) anchors
# byte-equivalence to rfc8785, so the fallback CI lane is still
# covered for the JCS-canonicalisation invariants.
rfc8785 = pytest.importorskip("rfc8785")

from wirelang.identity import (
    generate_aip_document,
    sign_aip_document,
    verify_aip_signature,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "fixtures"
    / "aip-document-vectors"
)


def _all_fixtures() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("vector-*.json"))


def _load(p: Path) -> dict:
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _canonical_hash(doc: dict) -> str:
    body = copy.deepcopy(doc)
    body.pop("document_signature", None)
    return hashlib.sha256(rfc8785.dumps(body)).hexdigest()


@pytest.fixture(scope="module", params=_all_fixtures(), ids=lambda p: p.stem)
def fixture(request: pytest.FixtureRequest) -> dict:
    return _load(request.param)


# ---------------------------------------------------------------------------
# Per-fixture assertions
# ---------------------------------------------------------------------------


def test_fixture_validates_against_schema(
    fixture: dict, aip_document_validator
) -> None:
    aip_document_validator.validate(fixture["document"])


def test_fixture_jcs_hash_matches_pin(fixture: dict) -> None:
    assert _canonical_hash(fixture["document"]) == fixture["document_jcs_sha256"]


def test_fixture_signature_verifies(fixture: dict) -> None:
    pub_hex = fixture["generation_inputs"]["ed25519_pub_hex_32"]
    pub = bytes.fromhex(pub_hex)
    sig_block = fixture["signature_block"]
    assert verify_aip_signature(fixture["document"], sig_block, pub)


def test_fixture_signature_block_matches_embedded(fixture: dict) -> None:
    """``document.document_signature`` and the top-level ``signature_block``
    must point to the same bytes; otherwise the fixture is internally
    inconsistent.
    """
    assert fixture["document"]["document_signature"] == fixture["signature_block"]


def test_fixture_signature_is_ed25519_deterministic(fixture: dict) -> None:
    """Re-signing with the same Ed25519 private key MUST produce the same
    signature bytes (RFC 8032 determinism)."""
    priv = bytes.fromhex(fixture["generation_inputs"]["ed25519_priv_hex_32"])
    sig_block = sign_aip_document(
        fixture["document"], priv, kid=fixture["signature_block"]["kid"]
    )
    assert sig_block["signature"] == fixture["signature_block"]["signature"]


def test_fixture_regenerates_modulo_documented_mutations(fixture: dict) -> None:
    """A fresh ``generate_aip_document`` call with the same inputs must
    reproduce the document fields that the generator owns. We compare the
    schema-required fields directly; ``post_generation_mutations`` are
    documented in the fixture and excluded from this check.
    """
    inp = fixture["generation_inputs"]
    fresh = generate_aip_document(
        inp["persona_id"],
        bytes.fromhex(inp["ed25519_pub_hex_32"]),
        inp["did_uri"],
        valid_after=inp.get("valid_after"),
        valid_until=inp.get("valid_until"),
        expires=inp.get("expires"),
        delegation_mode=inp.get("delegation_mode", "chained"),
        protocols=tuple(inp.get("protocols", ("wirelang/0.1",))),
    )
    # Strip mutation-affected slots before comparison.
    target = copy.deepcopy(fixture["document"])
    target.pop("document_signature", None)
    fresh.pop("document_signature", None)
    if inp.get("post_generation_mutations"):
        # Aggressive bypass: only compare the fields the generator owns
        # at synth time. We assert the generator output is a subset-match
        # of the fixture for the un-mutated keys.
        for key in ("aip", "id", "name", "delegation", "protocols", "expires"):
            if key in fresh:
                if key == "delegation":
                    # Mutations may add max_depth / allowed_audiences;
                    # baseline 'mode' must still match.
                    assert fresh[key]["mode"] == target[key]["mode"]
                else:
                    assert fresh[key] == target[key], (
                        f"regeneration drift on key '{key}'"
                    )
    else:
        assert fresh == target, "regenerated document differs from fixture"


# ---------------------------------------------------------------------------
# Cross-fixture invariants
# ---------------------------------------------------------------------------


def test_fixture_set_covers_all_delegation_modes() -> None:
    modes = {
        _load(p)["document"]["delegation"]["mode"] for p in _all_fixtures()
    }
    assert "chained" in modes
    assert "both" in modes


def test_fixture_set_covers_edge_no_extensions_case() -> None:
    """At least one fixture must exercise the strict-AIP edge case
    (no Wakir-only extensions: ``service_endpoints``,
    ``verification_methods``, ``biscuit_root_pubkey``)."""
    found = False
    for p in _all_fixtures():
        d = _load(p)["document"]
        if (
            "service_endpoints" not in d
            and "verification_methods" not in d
            and "biscuit_root_pubkey" not in d
        ):
            found = True
            break
    assert found, "no edge-case fixture without Wakir extensions present"


def test_fixture_set_covers_multi_cap_keys() -> None:
    """At least one fixture must exercise multiple ``public_keys`` with
    distinct ``purpose`` values across the two-curve stack."""
    for p in _all_fixtures():
        d = _load(p)["document"]
        if len(d["public_keys"]) >= 3:
            algs = {k["alg"] for k in d["public_keys"]}
            purposes = {k.get("purpose") for k in d["public_keys"]}
            if "Ed25519" in algs and "secp256k1" in algs and len(purposes) >= 3:
                return
    pytest.fail("no multi-cap (Ed25519+secp256k1, three purposes) fixture")
