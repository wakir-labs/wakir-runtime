# SPDX-License-Identifier: Apache-2.0
"""Persona DID-document generator (did:web with two-curve verification methods).

Generates W3C DID-Core conformant ``did:web`` documents that carry both a
``EcdsaSecp256k1VerificationKey2019`` and an ``Ed25519VerificationKey2020``
verification method. The two methods are bound to a single Wakir persona;
this is the public face of the Phase-1a two-curve stack (consensus marker
§1.2.4).

References (URL-200-verified 2026-05-06):

- W3C DID-Core: <https://www.w3.org/TR/did-core/>
- did:web method: <https://w3c-ccg.github.io/did-method-web/>
- DID specification registries (verification method types are registered
  externally to DID-Core, per the spec): the two types used here
  (``EcdsaSecp256k1VerificationKey2019``, ``Ed25519VerificationKey2020``)
  are widely deployed in production DID stacks.

Versioned-path convention (consensus marker B2):

- DID documents are published under
  ``https://<host>/.well-known/did/<persona-id>/v<N>.json`` where ``<N>``
  is a monotonically increasing version integer (1, 2, ...).
- The ``did:web`` identifier itself is host- and persona-id-bound and
  does *not* carry the version segment; the well-known fetch is a
  versioned alias and the ``id`` field of the returned document is
  required to match the un-versioned DID URI.
- Generators here surface the version via the ``version`` argument so
  the caller can construct the matching publication path.
"""

from __future__ import annotations

from typing import Optional


def _did_web_id(host: str, persona_id: str) -> str:
    """Build the un-versioned ``did:web`` identifier for a persona."""
    if "/" in host or ":" in host:
        raise ValueError(
            "host must be a bare DNS name (no scheme, no port, no path); "
            "received: " + repr(host)
        )
    if "/" in persona_id or ":" in persona_id:
        raise ValueError(
            "persona_id must be a bare role-string (no slashes, no colons); "
            "received: " + repr(persona_id)
        )
    # did:web encodes path segments after the host with colons.
    return f"did:web:{host}:personas:{persona_id}"


def generate_persona_did_document(
    persona_id: str,
    secp256k1_pub: bytes,
    ed25519_pub: bytes,
    *,
    host: str = "wakir.dev",
    version: int = 1,
) -> dict:
    """Build a did:web DID document for a Wakir persona.

    Args:
        persona_id: bare persona role-string (e.g. ``"treasury-issuer"``).
            MUST NOT contain slashes or colons. Per Wakir Brand-Guide §9
            this is always a role-string, never a clear personal name.
        secp256k1_pub: compressed secp256k1 public key, 33 bytes.
        ed25519_pub: raw Ed25519 public key, 32 bytes.
        host: DNS host owning the DID (default ``wakir.dev``).
        version: document-version integer (>= 1). Used by the caller to
            construct the publication path ``v<version>.json`` (see
            module docstring for the path convention).

    Returns:
        A dict ready to be serialised as JSON. Keys follow the DID-Core
        ordering convention (``@context`` first).

    Raises:
        ValueError: if ``persona_id``/``host`` contain forbidden
            characters, key lengths are wrong, or ``version < 1``.
    """
    if version < 1:
        raise ValueError("version must be >= 1")
    if len(secp256k1_pub) != 33:
        raise ValueError(
            "secp256k1_pub must be a 33-byte compressed point; "
            f"got {len(secp256k1_pub)} bytes"
        )
    if len(ed25519_pub) != 32:
        raise ValueError(
            "ed25519_pub must be a 32-byte raw key; "
            f"got {len(ed25519_pub)} bytes"
        )

    did = _did_web_id(host, persona_id)
    secp_kid = f"{did}#keys-secp256k1-1"
    ed_kid = f"{did}#keys-ed25519-1"

    document: dict = {
        "@context": [
            "https://www.w3.org/ns/did/v1",
            "https://w3id.org/security/suites/secp256k1-2019/v1",
            "https://w3id.org/security/suites/ed25519-2020/v1",
        ],
        "id": did,
        "verificationMethod": [
            {
                "id": secp_kid,
                "type": "EcdsaSecp256k1VerificationKey2019",
                "controller": did,
                "publicKeyHex": secp256k1_pub.hex(),
            },
            {
                "id": ed_kid,
                "type": "Ed25519VerificationKey2020",
                "controller": did,
                "publicKeyHex": ed25519_pub.hex(),
            },
        ],
        "authentication": [secp_kid, ed_kid],
        "assertionMethod": [secp_kid, ed_kid],
        "wakirVersion": version,
    }
    return document


def did_document_publication_path(persona_id: str, version: int) -> str:
    """Return the well-known publication path for a versioned DID document.

    The full publication URL is ``https://<host>/{this path}``. Caller
    is responsible for prepending host + scheme.

    Example:
        >>> did_document_publication_path("treasury-issuer", 1)
        '.well-known/did/treasury-issuer/v1.json'
    """
    if "/" in persona_id or ":" in persona_id:
        raise ValueError(
            "persona_id must be a bare role-string (no slashes, no colons)"
        )
    if version < 1:
        raise ValueError("version must be >= 1")
    return f".well-known/did/{persona_id}/v{version}.json"


def parse_did_document_version_from_path(path: str) -> Optional[int]:
    """Extract the version integer from a publication path, if present.

    Returns ``None`` if the path is not a versioned DID-document path.
    """
    # Path shape: .well-known/did/<persona-id>/v<N>.json
    parts = path.strip("/").split("/")
    if len(parts) != 4 or parts[0] != ".well-known" or parts[1] != "did":
        return None
    leaf = parts[3]
    if not leaf.startswith("v") or not leaf.endswith(".json"):
        return None
    try:
        return int(leaf[1:-5])
    except ValueError:
        return None
