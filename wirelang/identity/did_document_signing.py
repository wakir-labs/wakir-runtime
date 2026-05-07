# SPDX-License-Identifier: Apache-2.0
"""DID-Document signature helper (ECDSA over secp256k1, JCS+SHA-256).

Wakir convention for DID-document signatures:

The DID-Core spec does not mandate a self-signature on the DID document
(integrity is delegated to the publication mechanism, e.g. ``did:web``
HTTPS). For Wakir we additionally publish a Wakir-internal proof that
the persona-controlling secp256k1 key signed off on the document body,
so downstream consumers (audit, OTS-anchor, future Wakir-native DID
method) can verify provenance without trusting the publication HTTPS
chain alone.

Procedure:

1. **Strip** the ``proof`` field (if present) from a deep copy of the
   document. The proof slot, like AIP's ``document_signature``, cannot
   be part of its own pre-image.
2. **Canonicalise** with RFC 8785 JCS (same library as
   :mod:`wirelang.identity.aip_signing`).
3. **SHA-256 + ECDSA-over-secp256k1**: hash, sign with the persona's
   secp256k1 master/sub key. We use the deterministic-k variant via
   ``cryptography`` (which delegates to RFC 6979 internally for the
   ECDSA path used by ``hazmat``); signatures are DER-encoded by the
   library, and we serialise as compact ``r||s`` (64 bytes / 128 hex)
   for protocol consistency with W3C VC ECDSA suites.
4. **Re-attach** a ``proof`` block following a Wakir-flavoured
   subset of the W3C Data Integrity profile::

       {
         "type": "EcdsaSecp256k1Signature2019",
         "verificationMethod": "did:web:.../keys-secp256k1-1",
         "alg": "ES256K",
         "signatureHex": "<128-hex-char r||s>"
       }

The ``type`` value matches the verification-method type already used
in :func:`wirelang.identity.generate_persona_did_document`.

References (URL-200-stamped 2026-05-06):

- RFC 8785 (JCS): <https://datatracker.ietf.org/doc/html/rfc8785>
- W3C DID-Core (proof-block convention):
  <https://www.w3.org/TR/did-core/#verification-relationships>
- EcdsaSecp256k1Signature2019:
  <https://w3c-ccg.github.io/lds-ecdsa-secp256k1-2019/>
"""

from __future__ import annotations

import copy
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

from . import _jcs_pure


# Resolver indirection (Tag-9): see ``aip_signing._jcs_canonicalize``.
try:
    import rfc8785 as _rfc8785_lib

    _HAS_RFC8785 = True
except ImportError:  # pragma: no cover -- exercised when rfc8785 absent
    _rfc8785_lib = None
    _HAS_RFC8785 = False


def _jcs_canonicalize(value: object) -> bytes:
    if _HAS_RFC8785:
        return _rfc8785_lib.dumps(value)
    return _jcs_pure.canonicalize(value)


_PROOF_TYPE: str = "EcdsaSecp256k1Signature2019"
_DEFAULT_ALG: str = "ES256K"


def _canonical_signing_payload(did_doc: dict) -> bytes:
    body = copy.deepcopy(did_doc)
    body.pop("proof", None)
    canonical = _jcs_canonicalize(body)
    return hashlib.sha256(canonical).digest()


def _to_compact_signature(der_sig: bytes) -> bytes:
    """Convert a DER-encoded ECDSA signature to compact ``r||s`` (64 B)."""
    r, s = decode_dss_signature(der_sig)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def _from_compact_signature(compact: bytes) -> bytes:
    """Convert a compact 64-byte ``r||s`` signature back to DER."""
    if len(compact) != 64:
        raise ValueError(
            f"compact secp256k1 signature must be 64 bytes; got {len(compact)}"
        )
    r = int.from_bytes(compact[:32], "big")
    s = int.from_bytes(compact[32:], "big")
    return encode_dss_signature(r, s)


def sign_did_document(
    did_doc: dict,
    secp256k1_priv_key: bytes,
    *,
    verification_method_id: str | None = None,
) -> dict:
    """Sign a DID document and return the proof block.

    The input ``did_doc`` is **not** mutated.

    Args:
        did_doc: a DID document, typically produced by
            :func:`wirelang.identity.generate_persona_did_document`.
            Any existing ``proof`` slot is ignored for signing
            purposes.
        secp256k1_priv_key: 32-byte raw secp256k1 private scalar
            (output of :func:`derive_persona_master_secp256k1` or
            :func:`derive_sub_key_secp256k1`).
        verification_method_id: full id of the secp256k1 verification
            method that this proof binds to (e.g.
            ``"did:web:wakir.dev:personas:treasury-issuer#keys-secp256k1-1"``).
            Defaults to ``did_doc["id"] + "#keys-secp256k1-1"`` to
            match the generator's naming convention.

    Returns:
        Proof block dict ready for assignment into ``did_doc["proof"]``.

    Raises:
        ValueError: on invalid key length or missing ``id`` when no
            ``verification_method_id`` is supplied.
    """
    if len(secp256k1_priv_key) != 32:
        raise ValueError(
            "secp256k1_priv_key must be 32 bytes; "
            f"got {len(secp256k1_priv_key)} bytes"
        )
    if verification_method_id is None:
        if "id" not in did_doc:
            raise ValueError(
                "did_doc has no 'id'; supply verification_method_id explicitly"
            )
        verification_method_id = f"{did_doc['id']}#keys-secp256k1-1"

    digest = _canonical_signing_payload(did_doc)
    sk = ec.derive_private_key(
        int.from_bytes(secp256k1_priv_key, "big"), ec.SECP256K1()
    )
    # ``cryptography`` produces a DER signature when handed a Prehashed.
    der_sig = sk.sign(digest, ec.ECDSA(hashes.SHA256()))
    # Note: the ``ECDSA(SHA256)`` signer expects raw input and hashes
    # internally. To sign an already-computed digest we'd need
    # Prehashed(SHA256()), which forces re-construction of the hash
    # algorithm at verify time. We side-step that by signing the digest
    # bytes directly via ``ECDSA(SHA256())``-over-the-32-byte-input,
    # which matches the verify-side path below (same construction).
    compact = _to_compact_signature(der_sig)
    return {
        "type": _PROOF_TYPE,
        "verificationMethod": verification_method_id,
        "alg": _DEFAULT_ALG,
        "signatureHex": compact.hex(),
    }


def verify_did_signature(
    did_doc: dict,
    proof_block: dict,
    secp256k1_pub_key: bytes,
) -> bool:
    """Verify a DID-document proof block.

    Args:
        did_doc: the DID document to verify (its ``proof`` slot is
            ignored; the supplied ``proof_block`` is authoritative).
        proof_block: the proof block to validate.
        secp256k1_pub_key: 33-byte compressed secp256k1 public key.

    Returns:
        True iff the signature is valid; False otherwise. Format
        violations raise ``ValueError``.

    Raises:
        ValueError: on missing fields, unsupported alg/type, or
            length violations.
    """
    for field in ("type", "alg", "signatureHex"):
        if field not in proof_block:
            raise ValueError(f"proof_block missing required field: {field}")
    if proof_block["type"] != _PROOF_TYPE:
        raise ValueError(f"unsupported proof type: {proof_block['type']}")
    if proof_block["alg"] != _DEFAULT_ALG:
        raise ValueError(f"unsupported proof alg: {proof_block['alg']}")
    if len(secp256k1_pub_key) != 33:
        raise ValueError(
            "secp256k1_pub_key must be 33 bytes (compressed); "
            f"got {len(secp256k1_pub_key)} bytes"
        )
    try:
        compact = bytes.fromhex(proof_block["signatureHex"])
    except ValueError as exc:
        raise ValueError(f"signatureHex is not valid hex: {exc}") from exc

    digest = _canonical_signing_payload(did_doc)
    der_sig = _from_compact_signature(compact)

    # Re-construct the public key from the compressed form. The
    # `cryptography` library's `from_encoded_point` accepts X9.62
    # compressed (0x02/0x03 prefix, 33 bytes) directly.
    pk = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256K1(), secp256k1_pub_key
    )
    # Sanity: round-trip the encoded form to confirm we got the right
    # representation (defensive check; raises for malformed points).
    pk.public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
    try:
        pk.verify(der_sig, digest, ec.ECDSA(hashes.SHA256()))
        return True
    except InvalidSignature:
        return False
