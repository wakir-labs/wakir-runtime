# SPDX-License-Identifier: Apache-2.0
"""AIP-document signature helper (Ed25519 over JCS-canonicalised body).

Wakir convention for AIP-document signatures (used by
:func:`wirelang.identity.generate_aip_document`):

1. **Strip** the ``document_signature`` field from the document body.
   The signature value cannot be part of its own pre-image; the signed
   payload is the document *minus* this slot.
2. **Canonicalise** the remaining document with RFC 8785 JCS. JCS gives
   us a deterministic byte-string regardless of key ordering or
   whitespace introduced by upstream serialisers; the same library
   (``rfc8785``) is already a project dependency for WAT-Merkle.
3. **Hash + sign**: SHA-256 of the JCS bytes, signed with Ed25519.
   (We sign the SHA-256 digest rather than the JCS bytes directly to
   keep signature input length bounded for very large documents and to
   match the convention already used by the WAT-Merkle leaf builder.)
4. **Re-attach** a ``document_signature`` block of shape::

       {
         "alg": "Ed25519",
         "kid": "biscuit-root-1",
         "signature": "<128-hex-char>"
       }

Verification is the same procedure run in reverse, verifying the
signature byte-string with the supplied Ed25519 public key.

References (URL-200-stamped 2026-05-06):

- RFC 8785 (JCS): <https://datatracker.ietf.org/doc/html/rfc8785>
- AIP draft section 2.3 (document_signature):
  <https://datatracker.ietf.org/doc/html/draft-prakash-aip-00>
"""

from __future__ import annotations

import copy
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from . import _jcs_pure


# Resolver indirection (Tag-9 Phase-1b): production deployments
# install the ``rfc8785`` PyPI package and we delegate to it; sandbox
# environments that lack the package fall back to the pure-Python
# canonicaliser in :mod:`wirelang.identity._jcs_pure`. The two paths
# produce byte-identical output for the Phase-1b document shape;
# cross-equivalence is verified by the Tag-9 test suite.
try:
    import rfc8785 as _rfc8785_lib

    _HAS_RFC8785 = True
except ImportError:  # pragma: no cover -- exercised when rfc8785 absent
    _rfc8785_lib = None
    _HAS_RFC8785 = False


def _jcs_canonicalize(value: object) -> bytes:
    """JCS-canonicalise ``value``.

    Production path: ``rfc8785.dumps``. Fallback path: the pure-Python
    canonicaliser. See module docstring on resolver indirection.
    """
    if _HAS_RFC8785:
        return _rfc8785_lib.dumps(value)
    return _jcs_pure.canonicalize(value)


_DEFAULT_KID: str = "biscuit-root-1"


def _canonical_signing_payload(aip_doc: dict) -> bytes:
    """Strip the signature slot and return the SHA-256 of the JCS bytes.

    The ``document_signature`` field is removed from a deep copy of
    the input so the caller's document is not mutated. JCS canonical
    form is computed via the resolver indirection (``rfc8785`` when
    available, the pure-Python fallback otherwise); SHA-256 of that
    byte-string is the signing input.
    """
    body = copy.deepcopy(aip_doc)
    body.pop("document_signature", None)
    canonical = _jcs_canonicalize(body)
    return hashlib.sha256(canonical).digest()


def sign_aip_document(
    aip_doc: dict,
    ed25519_priv_key: bytes,
    *,
    kid: str = _DEFAULT_KID,
) -> dict:
    """Sign an AIP document and return the signature block.

    The input ``aip_doc`` is **not** mutated; the caller is responsible
    for placing the returned signature block under
    ``aip_doc["document_signature"]``.

    Args:
        aip_doc: an AIP document, typically produced by
            :func:`wirelang.identity.generate_aip_document`. Any
            existing ``document_signature`` slot is ignored for
            signing-input purposes.
        ed25519_priv_key: 32-byte raw Ed25519 private key (the
            ``derive_persona_master_ed25519`` output, or a sub-key).
        kid: key identifier to embed in the signature block. Defaults
            to ``"biscuit-root-1"`` to match the Wakir AIP-document
            generator's first ``public_keys`` entry.

    Returns:
        Signature block dict ready for assignment into
        ``aip_doc["document_signature"]``.

    Raises:
        ValueError: on invalid key length.
    """
    if len(ed25519_priv_key) != 32:
        raise ValueError(
            "ed25519_priv_key must be a 32-byte raw seed; "
            f"got {len(ed25519_priv_key)} bytes"
        )
    digest = _canonical_signing_payload(aip_doc)
    sk = Ed25519PrivateKey.from_private_bytes(ed25519_priv_key)
    signature = sk.sign(digest)
    return {
        "alg": "Ed25519",
        "kid": kid,
        "signature": signature.hex(),
    }


def verify_aip_signature(
    aip_doc: dict,
    signature_block: dict,
    ed25519_pub_key: bytes,
) -> bool:
    """Verify an AIP-document signature block.

    Args:
        aip_doc: the document to verify. Its existing
            ``document_signature`` slot is ignored (the supplied
            ``signature_block`` is authoritative); this matches
            production flows where the verifier may receive the
            document and signature out of band.
        signature_block: the signature block to validate. MUST contain
            ``alg`` (== ``"Ed25519"``) and ``signature`` (128 hex
            chars, i.e. 64 bytes).
        ed25519_pub_key: 32-byte raw Ed25519 public key.

    Returns:
        True iff the signature is valid; False otherwise. Format
        violations (wrong algorithm, malformed signature hex, wrong
        key length) raise ``ValueError`` so the caller can distinguish
        "structurally broken" from "cryptographically wrong".

    Raises:
        ValueError: on missing fields, wrong algorithm or length
            violations.
    """
    if "alg" not in signature_block or "signature" not in signature_block:
        raise ValueError("signature_block missing alg or signature")
    if signature_block["alg"] != "Ed25519":
        raise ValueError(
            f"unsupported signature alg: {signature_block['alg']}"
        )
    if len(ed25519_pub_key) != 32:
        raise ValueError(
            "ed25519_pub_key must be a 32-byte raw key; "
            f"got {len(ed25519_pub_key)} bytes"
        )
    try:
        signature = bytes.fromhex(signature_block["signature"])
    except ValueError as exc:
        raise ValueError(f"signature is not valid hex: {exc}") from exc
    if len(signature) != 64:
        raise ValueError(
            "Ed25519 signature must be 64 bytes (128 hex chars); "
            f"got {len(signature)} bytes"
        )

    digest = _canonical_signing_payload(aip_doc)
    pk = Ed25519PublicKey.from_public_bytes(ed25519_pub_key)
    try:
        pk.verify(signature, digest)
        return True
    except InvalidSignature:
        return False
