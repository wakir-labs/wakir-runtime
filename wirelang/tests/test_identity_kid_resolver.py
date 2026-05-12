# SPDX-License-Identifier: Apache-2.0
"""Determinism tests for the AIP-document kid → public-key resolver.

Phase-2 Sprint-4 Tag-3 inventory: T-KID-RES-01..12.

The tests exercise the resolver as a pure function over hand-crafted
AIP-document fragments (no transport, no signature-verify on the
document itself; the resolver intentionally trusts the caller for
document provenance). Test coverage:

- T-KID-RES-01: Happy-path single-kid resolve through the wired
  ``generate_aip_document`` factory.
- T-KID-RES-02: Multi-key resolve (two distinct kids, both Ed25519).
- T-KID-RES-03: Cross-key with the schema-registry entry-signing layer
  (``sign_entry`` + ``verify_entry_signature`` end-to-end via
  resolver).
- T-KID-RES-04: Kid-not-found structural failure.
- T-KID-RES-05: Duplicate-kid structural failure.
- T-KID-RES-06: Wrong-alg (secp256k1) filter.
- T-KID-RES-07: Validity-window enforcement (before / inside / after).
- T-KID-RES-08: Purpose-filter enforcement.
- T-KID-RES-09: Malformed key_hex shape (length / non-hex / wrong
  decoded byte count).
- T-KID-RES-10: Missing or malformed ``public_keys`` array.
- T-KID-RES-11: ``list_resolvable_kids`` filter behaviour.
- T-KID-RES-12: Resolver determinism — repeated calls on the same
  input produce byte-equal ``ResolvedPublicKey`` instances.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, Mapping

import pytest

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives import serialization

from wirelang.identity import (
    KidResolverError,
    ResolvedPublicKey,
    generate_aip_document,
    list_resolvable_kids,
    resolve_kid,
)
from wirelang.schemas.entry_signing import (
    SchemaRegistrySignatureError,
    SignedSchemaRegistryEntry,
    VerifyMode,
    sign_entry,
    verify_entry_signature,
)
from wirelang.schemas.registry_nats_kv_backend import (
    SchemaRegistryEntry,
    schema_body_sha256,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers.
# ---------------------------------------------------------------------------


_SEED_A: bytes = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)
"""RFC 8032 test-vector 1 seed."""

_SEED_B: bytes = bytes.fromhex(
    "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"
)
"""RFC 8032 test-vector 2 seed."""


def _keypair(seed: bytes) -> tuple[bytes, bytes]:
    sk = Ed25519PrivateKey.from_private_bytes(seed)
    pk = sk.public_key()
    priv = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = pk.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv, pub


def _aip_doc_with_two_keys(
    pub_a: bytes,
    pub_b: bytes,
    *,
    validafter_a: str = "2026-05-01T00:00:00Z",
    validuntil_a: str | None = None,
    validafter_b: str = "2026-05-01T00:00:00Z",
    validuntil_b: str | None = "2027-05-01T00:00:00Z",
) -> dict[str, Any]:
    """Hand-built minimal AIP doc with two Ed25519 keys."""
    return {
        "aip": "1.0",
        "id": "aip:web:wakir.dev/personas/test-resolver",
        "name": "test-resolver",
        "public_keys": [
            {
                "kid": "biscuit-root-1",
                "alg": "Ed25519",
                "key_hex": pub_a.hex(),
                "validafter": validafter_a,
                "validuntil": validuntil_a,
                "purpose": "biscuit-root",
            },
            {
                "kid": "aip-signing-1",
                "alg": "Ed25519",
                "key_hex": pub_b.hex(),
                "validafter": validafter_b,
                "validuntil": validuntil_b,
                "purpose": "aip-signing",
            },
        ],
        "delegation": {"mode": "chained"},
        "protocols": ["wirelang/0.1"],
        "expires": "2027-05-01T00:00:00Z",
        "document_signature": {
            "alg": "Ed25519",
            "kid": "biscuit-root-1",
            "signature": "00" * 64,
        },
    }


def _make_entry(
    registered_by: str = "aip:web:wakir.dev/personas/test-resolver",
) -> SchemaRegistryEntry:
    body: dict[str, Any] = {
        "$id": "wakir.wirelang.test-resolver/0.1.0",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }
    return SchemaRegistryEntry(
        layer="wire",
        name="test-resolver",
        version="0.1.0",
        schema_id="wakir.wirelang.test-resolver/0.1.0",
        schema_body=body,
        schema_body_sha256=schema_body_sha256(body),
        registered_at=dt.datetime(
            2026, 5, 11, 17, 0, 0, tzinfo=dt.timezone.utc
        ),
        registered_by=registered_by,
        supersedes=None,
    )


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_T_KID_RES_01_resolve_against_wired_generator() -> None:
    """Happy path: resolve through the actual ``generate_aip_document``."""
    _, pub = _keypair(_SEED_A)
    doc = generate_aip_document(
        persona_id="test-resolver",
        ed25519_root_pub=pub,
        did_uri="did:web:wakir.dev:personas:test-resolver",
        valid_after="2026-05-01T00:00:00Z",
    )

    resolved = resolve_kid(doc, kid="biscuit-root-1")
    assert isinstance(resolved, ResolvedPublicKey)
    assert resolved.kid == "biscuit-root-1"
    assert resolved.public_key == pub
    assert resolved.purpose == "biscuit-root"
    # Validity-window parsed via generator's RFC-3339 emitter.
    assert resolved.validafter is not None
    assert resolved.validafter.tzinfo is not None


def test_T_KID_RES_02_multi_key_resolve_both_present() -> None:
    """Two distinct kids in ``public_keys``, both Ed25519, both resolve."""
    _, pub_a = _keypair(_SEED_A)
    _, pub_b = _keypair(_SEED_B)
    doc = _aip_doc_with_two_keys(pub_a, pub_b)

    resolved_a = resolve_kid(doc, kid="biscuit-root-1")
    resolved_b = resolve_kid(doc, kid="aip-signing-1")

    assert resolved_a.public_key == pub_a
    assert resolved_b.public_key == pub_b
    assert resolved_a.purpose == "biscuit-root"
    assert resolved_b.purpose == "aip-signing"


def test_T_KID_RES_03_cross_layer_with_entry_signing() -> None:
    """End-to-end: sign a schema-registry entry, resolve via AIP doc,
    verify."""
    priv, pub = _keypair(_SEED_A)
    doc = generate_aip_document(
        persona_id="test-resolver",
        ed25519_root_pub=pub,
        did_uri="did:web:wakir.dev:personas:test-resolver",
        valid_after="2026-05-01T00:00:00Z",
    )
    entry = _make_entry()
    signed = sign_entry(entry, priv, kid="biscuit-root-1")

    # Resolve the kid from the AIP doc, then feed the resolved public
    # key into the signature verifier.
    resolved = resolve_kid(doc, kid=signed.signature["kid"])
    assert verify_entry_signature(
        signed, resolved.public_key, mode=VerifyMode.STRICT
    ) is True

    # Negative: a wrong-key resolve fails crypto-verify (not structural).
    _, pub_other = _keypair(_SEED_B)
    assert verify_entry_signature(
        signed, pub_other, mode=VerifyMode.STRICT
    ) is False


def test_T_KID_RES_04_kid_not_found_structural() -> None:
    """A kid not present in ``public_keys`` raises KidResolverError."""
    _, pub_a = _keypair(_SEED_A)
    _, pub_b = _keypair(_SEED_B)
    doc = _aip_doc_with_two_keys(pub_a, pub_b)

    with pytest.raises(KidResolverError, match="kid not found"):
        resolve_kid(doc, kid="does-not-exist")


def test_T_KID_RES_05_duplicate_kid_structural() -> None:
    """Two ``public_keys`` entries with the same kid raise."""
    _, pub_a = _keypair(_SEED_A)
    _, pub_b = _keypair(_SEED_B)
    doc = _aip_doc_with_two_keys(pub_a, pub_b)
    # Duplicate the first entry's kid onto the second.
    doc["public_keys"][1]["kid"] = "biscuit-root-1"

    with pytest.raises(KidResolverError, match="duplicate kid"):
        resolve_kid(doc, kid="biscuit-root-1")


def test_T_KID_RES_06_wrong_alg_secp256k1_filtered() -> None:
    """A secp256k1 entry under the requested kid is rejected (Z-1-K-
    Sprint-4-3 Identity-Document-layer is Ed25519-only)."""
    _, pub_a = _keypair(_SEED_A)
    _, pub_b = _keypair(_SEED_B)
    doc = _aip_doc_with_two_keys(pub_a, pub_b)
    doc["public_keys"][0]["alg"] = "secp256k1"
    # Re-shape key_hex to be a 66-hex-char compressed secp256k1 stub
    # (the resolver must reject this on the *alg* test before reaching
    # the length check).
    doc["public_keys"][0]["key_hex"] = "02" + ("ab" * 32)

    with pytest.raises(KidResolverError, match="alg is not 'Ed25519'"):
        resolve_kid(doc, kid="biscuit-root-1")


def test_T_KID_RES_07_validity_window_enforcement() -> None:
    """as_of before/inside/after the validity window."""
    _, pub_a = _keypair(_SEED_A)
    _, pub_b = _keypair(_SEED_B)
    doc = _aip_doc_with_two_keys(
        pub_a, pub_b,
        validafter_a="2026-05-01T00:00:00Z",
        validuntil_a="2026-06-01T00:00:00Z",
    )

    # Before window.
    before = dt.datetime(2026, 4, 1, tzinfo=dt.timezone.utc)
    with pytest.raises(KidResolverError, match="not yet valid"):
        resolve_kid(doc, kid="biscuit-root-1", as_of=before)

    # Inside window.
    inside = dt.datetime(2026, 5, 15, tzinfo=dt.timezone.utc)
    resolved = resolve_kid(doc, kid="biscuit-root-1", as_of=inside)
    assert resolved.public_key == pub_a

    # After window.
    after = dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc)
    with pytest.raises(KidResolverError, match="has expired"):
        resolve_kid(doc, kid="biscuit-root-1", as_of=after)

    # No as_of → no window check.
    resolved_anytime = resolve_kid(doc, kid="biscuit-root-1")
    assert resolved_anytime.public_key == pub_a


def test_T_KID_RES_08_purpose_filter_enforcement() -> None:
    """require_purpose filter rejects entries with a different
    purpose tag."""
    _, pub_a = _keypair(_SEED_A)
    _, pub_b = _keypair(_SEED_B)
    doc = _aip_doc_with_two_keys(pub_a, pub_b)

    # Matches.
    resolved = resolve_kid(
        doc, kid="biscuit-root-1", require_purpose="biscuit-root"
    )
    assert resolved.purpose == "biscuit-root"

    # Wrong purpose.
    with pytest.raises(KidResolverError, match="purpose mismatch"):
        resolve_kid(
            doc, kid="biscuit-root-1", require_purpose="aip-signing"
        )


def test_T_KID_RES_09_malformed_key_hex_structural() -> None:
    """Three sub-cases: wrong hex length, non-hex chars, wrong decoded
    byte count."""
    _, pub_a = _keypair(_SEED_A)
    _, pub_b = _keypair(_SEED_B)

    # Sub-case A: hex length wrong.
    doc = _aip_doc_with_two_keys(pub_a, pub_b)
    doc["public_keys"][0]["key_hex"] = "ab" * 31  # 62 chars (need 64)
    with pytest.raises(KidResolverError, match="must be 64 hex chars"):
        resolve_kid(doc, kid="biscuit-root-1")

    # Sub-case B: hex length correct, but non-hex character.
    doc = _aip_doc_with_two_keys(pub_a, pub_b)
    doc["public_keys"][0]["key_hex"] = ("zz" * 32)  # 64 chars, non-hex
    with pytest.raises(KidResolverError, match="not valid hex"):
        resolve_kid(doc, kid="biscuit-root-1")

    # Sub-case C: missing key_hex entirely.
    doc = _aip_doc_with_two_keys(pub_a, pub_b)
    del doc["public_keys"][0]["key_hex"]
    with pytest.raises(KidResolverError, match="missing 'key_hex'"):
        resolve_kid(doc, kid="biscuit-root-1")


def test_T_KID_RES_10_missing_or_malformed_public_keys() -> None:
    """The ``public_keys`` array must be present, non-empty, and a
    sequence."""
    # Missing field.
    with pytest.raises(KidResolverError, match="missing the 'public_keys'"):
        resolve_kid({}, kid="x")

    # Non-sequence.
    with pytest.raises(KidResolverError, match="must be a sequence"):
        resolve_kid({"public_keys": {"not": "a sequence"}}, kid="x")

    # String mistakenly placed (a string IS a sequence in Python; the
    # resolver excludes str/bytes explicitly).
    with pytest.raises(KidResolverError, match="must be a sequence"):
        resolve_kid({"public_keys": "abc"}, kid="x")

    # Empty array.
    with pytest.raises(KidResolverError, match="is empty"):
        resolve_kid({"public_keys": []}, kid="x")

    # Non-mapping aip_doc.
    with pytest.raises(KidResolverError, match="aip_doc must be a mapping"):
        resolve_kid("not a mapping", kid="x")  # type: ignore[arg-type]

    # Empty kid.
    with pytest.raises(KidResolverError, match="non-empty string"):
        resolve_kid({"public_keys": [{}]}, kid="")


def test_T_KID_RES_11_list_resolvable_kids_filtering() -> None:
    """list_resolvable_kids respects all the same filters."""
    _, pub_a = _keypair(_SEED_A)
    _, pub_b = _keypair(_SEED_B)
    doc = _aip_doc_with_two_keys(
        pub_a, pub_b,
        validafter_a="2026-05-01T00:00:00Z",
        validuntil_a="2026-06-01T00:00:00Z",
    )

    # No filters: both kids resolvable.
    assert list_resolvable_kids(doc) == ["aip-signing-1", "biscuit-root-1"]

    # Window filter excludes the expired key A.
    after = dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc)
    assert list_resolvable_kids(doc, as_of=after) == ["aip-signing-1"]

    # Purpose filter narrows to a single kid.
    assert list_resolvable_kids(
        doc, require_purpose="aip-signing"
    ) == ["aip-signing-1"]

    # Wrong-alg kid is filtered out.
    doc2 = _aip_doc_with_two_keys(pub_a, pub_b)
    doc2["public_keys"][0]["alg"] = "secp256k1"
    doc2["public_keys"][0]["key_hex"] = "02" + ("ab" * 32)
    assert list_resolvable_kids(doc2) == ["aip-signing-1"]

    # Duplicate kid filters BOTH copies out (they're unresolvable).
    doc3 = _aip_doc_with_two_keys(pub_a, pub_b)
    doc3["public_keys"][1]["kid"] = "biscuit-root-1"
    assert list_resolvable_kids(doc3) == []


def test_T_KID_RES_12_resolver_determinism() -> None:
    """Repeated resolve calls produce byte-equal ResolvedPublicKey
    instances (frozen dataclass equality)."""
    _, pub_a = _keypair(_SEED_A)
    _, pub_b = _keypair(_SEED_B)
    doc = _aip_doc_with_two_keys(pub_a, pub_b)

    r1 = resolve_kid(doc, kid="biscuit-root-1")
    r2 = resolve_kid(doc, kid="biscuit-root-1")
    assert r1 == r2  # frozen dataclass eq.
    assert r1.public_key == r2.public_key

    # Determinism survives a JSON round-trip on the document.
    doc_round_trip = json.loads(json.dumps(doc))
    r3 = resolve_kid(doc_round_trip, kid="biscuit-root-1")
    assert r1 == r3

    # list_resolvable_kids is also order-deterministic (sorted).
    assert list_resolvable_kids(doc) == list_resolvable_kids(doc_round_trip)
