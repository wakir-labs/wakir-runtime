# SPDX-License-Identifier: Apache-2.0
"""Schema-registry entry signing (Phase-2 Sprint-4 Tag-1).

This module is the canonical Ed25519 signature substrate for
schema-registry entries. It composes the Tag-1 envelope codec
(:mod:`wirelang.schemas.registry_nats_kv_backend`) with the
:mod:`wirelang.identity.aip_signing` JCS + SHA-256 + Ed25519
primitive byte-identical.

Design contract (spec §5.8):

1. **Strip** the ``signature`` slot from a deep copy of the envelope
   payload. The signature value cannot be part of its own pre-image.
2. **Canonicalise** the remaining payload with RFC 8785 JCS (resolver
   indirection: ``rfc8785`` when importable, the pure-Python fallback
   in :mod:`wirelang.identity._jcs_pure` otherwise).
3. **Hash** with SHA-256 of the JCS bytes; sign with Ed25519.

The on-the-wire envelope schema gains an OPTIONAL ``signature`` slot
on the existing ``wakir.wirelang.schema-registry-entry/1`` value
schema. No ``/2`` envelope is introduced — v0.5.0 readers see an
unknown optional field and tolerate it (M-2 additive-only).

Phase-2 Sprint-4 Tag-1 boundary (spec §5.8 Phase-2 boundary block):

- This module ships the signing primitive and the
  :class:`VerifyMode` policy surface.
- This module does NOT ship the ``kid`` → public-key resolver
  (caller-supplied 32-byte Ed25519 public key on the verify path).
- The :class:`NatsKvSchemaRegistry` backend codec is extended to
  round-trip the optional slot but does NOT validate the signature
  at read time.

Cross-Review-Zone-1 (Identity-Substrate): the signing primitive is
byte-identical to :mod:`wirelang.identity.aip_signing`. The ``kid``
field references an AIP-document ``public_keys`` entry; the
resolver belongs in ``wirelang.identity`` and is out of scope here.

References:

- Spec §5.8 (entry-signing operational contract).
- RFC 8032 Ed25519: <https://datatracker.ietf.org/doc/html/rfc8032>.
- RFC 8785 JCS: <https://datatracker.ietf.org/doc/html/rfc8785>.
- AIP draft section 2.3 (document_signature) — same block shape.
"""

from __future__ import annotations

import copy
import enum
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Union

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from wirelang.identity import _jcs_pure
from wirelang.schemas.registry_nats_kv_backend import (
    SchemaRegistryEntry,
    SchemaRegistryEnvelopeError,
    VALUE_SCHEMA,
    _dt_to_rfc3339,
    _envelope_to_entry,
    _rfc3339_to_dt,
)


# ---------------------------------------------------------------------------
# JCS resolver indirection (mirrors wirelang.identity.aip_signing).
# ---------------------------------------------------------------------------

try:  # pragma: no cover -- production path
    import rfc8785 as _rfc8785_lib

    _HAS_RFC8785 = True
except ImportError:  # pragma: no cover -- sandbox fallback path
    _rfc8785_lib = None
    _HAS_RFC8785 = False


def _jcs_canonicalize(value: object) -> bytes:
    """JCS-canonicalise ``value``.

    Production path: ``rfc8785.dumps``. Fallback path: the pure-Python
    canonicaliser in :mod:`wirelang.identity._jcs_pure`. The two paths
    produce byte-identical output for the schema-registry-entry envelope
    shape; cross-equivalence is verified by the Tag-9 identity test
    suite (the same canonicaliser is exercised there).
    """
    if _HAS_RFC8785:
        return _rfc8785_lib.dumps(value)
    return _jcs_pure.canonicalize(value)


# ---------------------------------------------------------------------------
# Typed exception (structural failure class, spec §5.8).
# ---------------------------------------------------------------------------


class SchemaRegistrySignatureError(Exception):
    """Structural signature failure.

    Raised on: missing signature slot under STRICT mode, missing
    ``alg`` / ``kid`` / ``signature`` fields, unsupported algorithm,
    malformed signature hex, wrong signature byte-length, wrong
    public-key byte-length, wrong private-key byte-length, missing
    ``kid``.

    A *cryptographic* mismatch (valid structure, signature does not
    verify) is NOT raised here — :func:`verify_entry_signature`
    returns ``False`` in that case. This split matches the
    AIP-document signing convention.
    """


# ---------------------------------------------------------------------------
# Verify-mode policy (spec §5.8).
# ---------------------------------------------------------------------------


class VerifyMode(enum.Enum):
    """Verify-mode policy for the Phase-2 transition window.

    - ``PERMISSIVE``: entries WITHOUT a ``signature`` slot verify as
      ``True`` (legacy v0.5.0 entries pass). Signed entries are
      verified end-to-end.
    - ``STRICT``: entries WITHOUT a ``signature`` slot raise
      :class:`SchemaRegistrySignatureError`. Activation is operator-
      controlled; Sprint-4 Tag-1 ships the policy surface only.
    """

    PERMISSIVE = "permissive"
    STRICT = "strict"


# ---------------------------------------------------------------------------
# Signature-block constants and helpers.
# ---------------------------------------------------------------------------


SIGNATURE_ALG: str = "Ed25519"
_SIGNATURE_HEX_LEN: int = 128  # 64 bytes Ed25519 signature = 128 hex chars
_ED25519_KEY_LEN: int = 32


def _validate_signature_block_shape(block: Mapping[str, Any]) -> None:
    """Raise :class:`SchemaRegistrySignatureError` if the block shape
    is structurally invalid.

    Required fields: ``alg`` == ``"Ed25519"``, ``kid`` non-empty string,
    ``signature`` 128-hex-char string.
    """
    if not isinstance(block, Mapping):
        raise SchemaRegistrySignatureError(
            f"signature block must be a mapping: type="
            f"{type(block).__name__}"
        )
    for required in ("alg", "kid", "signature"):
        if required not in block:
            raise SchemaRegistrySignatureError(
                f"signature block missing required field: {required!r}"
            )
    alg = block["alg"]
    if alg != SIGNATURE_ALG:
        raise SchemaRegistrySignatureError(
            f"unsupported signature alg: {alg!r}; want {SIGNATURE_ALG!r}"
        )
    kid = block["kid"]
    if not isinstance(kid, str) or kid == "":
        raise SchemaRegistrySignatureError(
            f"signature block kid must be a non-empty string: got {kid!r}"
        )
    sig_hex = block["signature"]
    if not isinstance(sig_hex, str):
        raise SchemaRegistrySignatureError(
            f"signature block signature must be a string: type="
            f"{type(sig_hex).__name__}"
        )
    if len(sig_hex) != _SIGNATURE_HEX_LEN:
        raise SchemaRegistrySignatureError(
            f"signature block signature must be {_SIGNATURE_HEX_LEN} hex "
            f"chars (64 bytes); got {len(sig_hex)}"
        )
    try:
        sig_bytes = bytes.fromhex(sig_hex)
    except ValueError as exc:
        raise SchemaRegistrySignatureError(
            f"signature block signature is not valid hex: {exc}"
        ) from exc
    if len(sig_bytes) != 64:
        raise SchemaRegistrySignatureError(
            f"Ed25519 signature must be 64 bytes; got {len(sig_bytes)}"
        )


# ---------------------------------------------------------------------------
# Wrapper dataclass (spec §5.8).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignedSchemaRegistryEntry:
    """A signed schema-registry entry.

    Wraps a :class:`SchemaRegistryEntry` together with its detached
    signature block. The pair is the canonical in-memory representation
    of a Phase-2 signed entry; the signature block is stored on the
    envelope under the optional ``signature`` slot.
    """

    entry: SchemaRegistryEntry
    signature: Mapping[str, Any] = field()

    def __post_init__(self) -> None:
        # Validate the block shape eagerly so downstream consumers can
        # trust the contract without re-validating.
        _validate_signature_block_shape(self.signature)


# ---------------------------------------------------------------------------
# Envelope codec helpers (additive over Tag-1).
# ---------------------------------------------------------------------------


def _entry_to_signing_payload(
    entry: SchemaRegistryEntry,
) -> dict[str, Any]:
    """Return the envelope payload dict WITHOUT the ``signature`` slot.

    Mirrors :func:`wirelang.schemas.registry_nats_kv_backend._entry_to_envelope`
    field-for-field so the JCS pre-image is byte-identical to the
    Tag-1 envelope minus signature.
    """
    if not isinstance(entry, SchemaRegistryEntry):
        raise TypeError("entry must be a SchemaRegistryEntry")
    payload: dict[str, Any] = {
        "schema": VALUE_SCHEMA,
        "layer": entry.layer,
        "name": entry.name,
        "version": entry.version,
        "schema_id": entry.schema_id,
        "schema_body": dict(entry.schema_body),
        "schema_body_sha256": entry.schema_body_sha256,
        "registered_at": _dt_to_rfc3339(entry.registered_at),
        "registered_by": entry.registered_by,
        "supersedes": entry.supersedes,
    }
    return payload


def _canonical_signing_payload(entry: SchemaRegistryEntry) -> bytes:
    """Compute SHA-256 of the JCS-canonicalised envelope-minus-signature.

    The signing pre-image is the byte-string returned here. Ed25519
    signing operates on this digest, mirroring the AIP-document
    convention (`wirelang.identity.aip_signing._canonical_signing_payload`).
    """
    payload = _entry_to_signing_payload(entry)
    # Defence-in-depth: even though _entry_to_signing_payload never adds
    # a signature slot, strip one defensively if a future caller routes
    # an external dict through this path.
    payload.pop("signature", None)
    canonical = _jcs_canonicalize(payload)
    return hashlib.sha256(canonical).digest()


# ---------------------------------------------------------------------------
# Public API (spec §5.8).
# ---------------------------------------------------------------------------


def sign_entry(
    entry: SchemaRegistryEntry,
    ed25519_priv_key: bytes,
    *,
    kid: str,
) -> SignedSchemaRegistryEntry:
    """Sign a schema-registry entry.

    The signing pre-image is SHA-256 of the JCS-canonicalised envelope
    payload with the ``signature`` slot stripped (deterministic,
    byte-identical to the AIP-document convention). Ed25519 then signs
    the digest.

    Args:
        entry: a :class:`SchemaRegistryEntry`. Not mutated.
        ed25519_priv_key: 32-byte raw Ed25519 private key.
        kid: key identifier to embed in the signature block. Must be a
            non-empty string. Caller's responsibility to bind this to
            an AIP-document ``public_keys`` entry identifier.

    Returns:
        :class:`SignedSchemaRegistryEntry` carrying the original entry
        and the signature block.

    Raises:
        :class:`SchemaRegistrySignatureError`: on wrong key length or
            empty kid.
    """
    if not isinstance(ed25519_priv_key, (bytes, bytearray)):
        raise SchemaRegistrySignatureError(
            f"ed25519_priv_key must be bytes; type="
            f"{type(ed25519_priv_key).__name__}"
        )
    if len(ed25519_priv_key) != _ED25519_KEY_LEN:
        raise SchemaRegistrySignatureError(
            f"ed25519_priv_key must be a 32-byte raw seed; got "
            f"{len(ed25519_priv_key)} bytes"
        )
    if not isinstance(kid, str) or kid == "":
        raise SchemaRegistrySignatureError(
            f"kid must be a non-empty string: got {kid!r}"
        )

    digest = _canonical_signing_payload(entry)
    sk = Ed25519PrivateKey.from_private_bytes(bytes(ed25519_priv_key))
    raw_sig = sk.sign(digest)
    signature_block: dict[str, Any] = {
        "alg": SIGNATURE_ALG,
        "kid": kid,
        "signature": raw_sig.hex(),
    }
    return SignedSchemaRegistryEntry(entry=entry, signature=signature_block)


def verify_entry_signature(
    signed: Union[SignedSchemaRegistryEntry, SchemaRegistryEntry],
    ed25519_pub_key: Optional[bytes] = None,
    *,
    mode: VerifyMode = VerifyMode.PERMISSIVE,
    signature_block: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Verify a schema-registry entry's signature.

    The signed/unsigned cases:

    - ``SignedSchemaRegistryEntry`` (already paired with a signature
      block): verify end-to-end with the supplied public key.
    - Bare ``SchemaRegistryEntry`` with explicit ``signature_block``:
      verify end-to-end with the supplied public key.
    - Bare ``SchemaRegistryEntry`` without ``signature_block``:
      treated as unsigned.

    Args:
        signed: the entry to verify (signed wrapper or bare entry).
        ed25519_pub_key: 32-byte raw Ed25519 public key. Required for
            signed entries; ignored for unsigned entries under
            ``PERMISSIVE`` mode.
        mode: verify-mode policy. ``PERMISSIVE`` (default) accepts
            unsigned entries as ``True``; ``STRICT`` rejects them.
        signature_block: optional explicit signature block for the
            bare-entry path. When supplied, the entry is treated as
            signed.

    Returns:
        ``True`` if the signature verifies cryptographically OR if the
        entry is unsigned under ``PERMISSIVE`` mode. ``False`` if the
        signature is well-formed but does NOT verify cryptographically.

    Raises:
        :class:`SchemaRegistrySignatureError`: on structural failures
            (missing block under ``STRICT``, malformed block, wrong
            key length).
    """
    # Resolve the (entry, block) pair from the union input.
    block: Optional[Mapping[str, Any]]
    entry: SchemaRegistryEntry
    if isinstance(signed, SignedSchemaRegistryEntry):
        entry = signed.entry
        block = signed.signature
    elif isinstance(signed, SchemaRegistryEntry):
        entry = signed
        block = signature_block
    else:
        raise SchemaRegistrySignatureError(
            f"signed must be SignedSchemaRegistryEntry or "
            f"SchemaRegistryEntry; type={type(signed).__name__}"
        )

    # Unsigned path: PERMISSIVE accepts, STRICT rejects.
    if block is None:
        if mode is VerifyMode.PERMISSIVE:
            return True
        if mode is VerifyMode.STRICT:
            raise SchemaRegistrySignatureError(
                "entry is unsigned and verify mode is STRICT"
            )
        raise SchemaRegistrySignatureError(
            f"unknown VerifyMode: {mode!r}"
        )

    # Signed path: structural validation then cryptographic verify.
    _validate_signature_block_shape(block)

    if ed25519_pub_key is None:
        raise SchemaRegistrySignatureError(
            "ed25519_pub_key is required for signed-entry verification"
        )
    if not isinstance(ed25519_pub_key, (bytes, bytearray)):
        raise SchemaRegistrySignatureError(
            f"ed25519_pub_key must be bytes; type="
            f"{type(ed25519_pub_key).__name__}"
        )
    if len(ed25519_pub_key) != _ED25519_KEY_LEN:
        raise SchemaRegistrySignatureError(
            f"ed25519_pub_key must be a 32-byte raw key; got "
            f"{len(ed25519_pub_key)} bytes"
        )

    digest = _canonical_signing_payload(entry)
    pk = Ed25519PublicKey.from_public_bytes(bytes(ed25519_pub_key))
    sig_bytes = bytes.fromhex(block["signature"])
    try:
        pk.verify(sig_bytes, digest)
        return True
    except InvalidSignature:
        return False


# ---------------------------------------------------------------------------
# Envelope helpers (round-trip the optional signature slot).
# ---------------------------------------------------------------------------


def envelope_with_signature(
    signed: SignedSchemaRegistryEntry,
) -> bytes:
    """Serialise a signed entry to canonical envelope bytes.

    The output is identical to the Tag-1 envelope codec with one
    additional optional field: ``signature``. The envelope schema URI
    remains ``wakir.wirelang.schema-registry-entry/1``.
    """
    if not isinstance(signed, SignedSchemaRegistryEntry):
        raise TypeError("signed must be a SignedSchemaRegistryEntry")
    payload = _entry_to_signing_payload(signed.entry)
    # Add the optional signature slot. Frozen mapping copied to a
    # plain dict so json.dumps serialises it via the standard path.
    payload["signature"] = dict(signed.signature)
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def envelope_to_signed_entry(
    blob: bytes,
) -> Union[SignedSchemaRegistryEntry, SchemaRegistryEntry]:
    """Inverse of :func:`envelope_with_signature` plus Tag-1 codec.

    When the envelope carries a ``signature`` slot, returns
    :class:`SignedSchemaRegistryEntry`. When the slot is absent, returns
    a plain :class:`SchemaRegistryEntry` (Tag-1 codec parity).

    Raises:
        :class:`SchemaRegistryEnvelopeError`: on shape violation of the
            base envelope (delegated to the Tag-1 codec).
        :class:`SchemaRegistrySignatureError`: on shape violation of the
            optional signature slot.
    """
    # Delegate base envelope shape check to the Tag-1 codec, then peek
    # at the signature slot if present.
    entry = _envelope_to_entry(blob)
    # The Tag-1 decoder discards unknown fields; we re-parse the JSON
    # ourselves to recover the optional slot if it exists.
    try:
        text = blob.decode("utf-8")
        payload = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        # Tag-1 codec would already have raised; this is defence-in-depth.
        raise SchemaRegistryEnvelopeError(
            f"envelope re-parse failed: {exc!r}"
        ) from exc
    if not isinstance(payload, dict):  # pragma: no cover -- Tag-1 catches
        raise SchemaRegistryEnvelopeError(
            "envelope is not a JSON object on re-parse"
        )
    if "signature" not in payload:
        return entry
    signature_block = payload["signature"]
    # Validate the optional slot eagerly so the caller can trust the
    # SignedSchemaRegistryEntry contract.
    _validate_signature_block_shape(signature_block)
    return SignedSchemaRegistryEntry(entry=entry, signature=signature_block)
