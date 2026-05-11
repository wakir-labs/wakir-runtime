# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""WAT-manifest signing layer (Phase-1b Sprint-4 Tag-6).

This module is the WAT-side parallel to the Identity-Substrate-
engineering schema-registry-entry-signing layer
(``wirelang.schemas.entry_signing``, Phase-2 Sprint-4 Tag-1). It
ships an Ed25519 signing primitive for WAT hour-manifests
(``wat-manifest/1.0`` and ``wat-manifest/2.0``) that is *byte-
identical in shape* to the AIP-document and schema-registry-entry
signing primitives:

1. **Strip** the ``signature`` slot from a deep copy of the manifest
   payload. The signature value cannot be part of its own pre-image.
2. **Canonicalise** the remaining payload with RFC 8785 JCS
   (``rfc8785.dumps``).
3. **Hash** with SHA-256 of the JCS bytes; sign with Ed25519.

The on-the-wire manifest envelope gains an OPTIONAL top-level
``signature`` field. The hour-manifest schema URI is NOT bumped
(no v3); v2 readers that pre-date this slot ignore an unknown
optional top-level key (forward-compatible additive-only convention).

Phase-1b Sprint-4 Tag-6 boundary:

- This module ships the signing primitive, the
  :class:`WatManifestSignatureError` typed exception, the
  :class:`SignedWatManifest` wrapper, and the
  :class:`VerifyMode` policy surface (``PERMISSIVE`` / ``STRICT``).
- This module does NOT edit ``wirelang/schemas/wat-manifest-v2.json``
  to formalise the optional ``signature`` slot. That schema-file
  is on the Identity-Substrate-engineering Cross-Review-Zone-1
  boundary (the manifest schema lives under ``wirelang/schemas/``,
  the canonical schema-registry root). Schema-formalisation of the
  optional slot is a follow-up coordination item; today the slot
  round-trips through the verifier without schema-validation entry.
- This module does NOT wire the signing helpers into the existing
  hour-manifest verifier (``wat/verify/manifest_v2.py``). Verifier
  wire-up is a Tag-7+ item that would gate the signature check on a
  caller-supplied public key or a kid-resolver hit (the resolver
  lives in :mod:`wat.identity.anchor_kid` per Sprint-4 Tag-5).
- This module does NOT ship the ``kid`` -> public-key resolver path.
  Callers supply the 32-byte raw Ed25519 public key directly on
  :func:`verify_manifest_signature`. The kid value is captured in
  the signature block for downstream auditing and to bind to an
  AIP-document ``public_keys`` entry under
  :data:`wat.identity.anchor_kid.PURPOSE_WAT_ANCHOR`. The bridge
  from kid to public key is :func:`wat.identity.resolve_wat_anchor_kid`.

Cross-Review-Zone-1 (Identity-Substrate): the signing primitive is
byte-identical in shape to ``wirelang.identity.aip_signing`` and
``wirelang.schemas.entry_signing``. The hash / canonicaliser /
algorithm choices match line-for-line. The ``kid`` field references
an AIP-document ``public_keys`` entry; the resolver belongs in
``wirelang.identity.kid_resolver`` and is out of scope here.

References:

- ``wirelang.identity.aip_signing`` (AIP-document signing convention).
- ``wirelang.schemas.entry_signing`` (Identity-Substrate-engineering
  Phase-2 Sprint-4 Tag-1, structural ancestor of this module).
- :mod:`wat.identity.anchor_kid` (Sprint-4 Tag-5, kid-resolver bridge).
- RFC 8032 Ed25519: https://datatracker.ietf.org/doc/html/rfc8032
- RFC 8785 JCS: https://datatracker.ietf.org/doc/html/rfc8785
"""

from __future__ import annotations

import copy
import enum
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Union

import rfc8785

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


# ---------------------------------------------------------------------------
# Typed exception (structural failure class).
# ---------------------------------------------------------------------------


class WatManifestSignatureError(Exception):
    """Structural manifest-signature failure.

    Raised on: missing signature slot under STRICT mode, missing
    ``alg`` / ``kid`` / ``signature`` fields, unsupported algorithm,
    malformed signature hex, wrong signature byte-length, wrong
    public-key byte-length, wrong private-key byte-length, missing
    or empty ``kid``, non-mapping manifest, missing manifest
    ``version`` field.

    A *cryptographic* mismatch (valid structure, signature does not
    verify) is NOT raised here -- :func:`verify_manifest_signature`
    returns ``False`` in that case. This split matches the AIP-
    document and schema-registry-entry signing conventions.
    """


# ---------------------------------------------------------------------------
# Verify-mode policy.
# ---------------------------------------------------------------------------


class VerifyMode(enum.Enum):
    """Verify-mode policy for the Phase-1b -> Phase-1c transition.

    - ``PERMISSIVE``: manifests WITHOUT a ``signature`` slot verify
      as ``True``. Legacy unsigned hour-manifests continue to pass.
      Signed manifests are verified end-to-end.
    - ``STRICT``: manifests WITHOUT a ``signature`` slot raise
      :class:`WatManifestSignatureError`. Activation is operator-
      controlled; Tag-6 ships only the policy surface.
    """

    PERMISSIVE = "permissive"
    STRICT = "strict"


# ---------------------------------------------------------------------------
# Signature-block constants and helpers.
# ---------------------------------------------------------------------------


SIGNATURE_ALG: str = "Ed25519"
SIGNATURE_FIELD: str = "signature"
_SIGNATURE_HEX_LEN: int = 128  # 64 bytes Ed25519 signature = 128 hex chars
_ED25519_KEY_LEN: int = 32

# Manifest versions this module is willing to sign / verify. v1 and v2
# share the canonical signing payload (everything-except-signature);
# the slot is additive on both. v3+ would need an explicit additive
# allowlist entry here -- intentional.
_SIGNABLE_VERSIONS: frozenset[str] = frozenset(
    {"wat-manifest/1.0", "wat-manifest/2.0"}
)


def _validate_signature_block_shape(block: Mapping[str, Any]) -> None:
    """Raise :class:`WatManifestSignatureError` if the block shape is
    structurally invalid.

    Required fields: ``alg`` == ``"Ed25519"``, ``kid`` non-empty
    string, ``signature`` 128-hex-char string. Shape constraints are
    line-for-line identical to
    :func:`wirelang.schemas.entry_signing._validate_signature_block_shape`.
    """
    if not isinstance(block, Mapping):
        raise WatManifestSignatureError(
            f"signature block must be a mapping: type="
            f"{type(block).__name__}"
        )
    for required in ("alg", "kid", "signature"):
        if required not in block:
            raise WatManifestSignatureError(
                f"signature block missing required field: {required!r}"
            )
    alg = block["alg"]
    if alg != SIGNATURE_ALG:
        raise WatManifestSignatureError(
            f"unsupported signature alg: {alg!r}; want {SIGNATURE_ALG!r}"
        )
    kid = block["kid"]
    if not isinstance(kid, str) or kid == "":
        raise WatManifestSignatureError(
            f"signature block kid must be a non-empty string: got {kid!r}"
        )
    sig_hex = block["signature"]
    if not isinstance(sig_hex, str):
        raise WatManifestSignatureError(
            f"signature block signature must be a string: type="
            f"{type(sig_hex).__name__}"
        )
    if len(sig_hex) != _SIGNATURE_HEX_LEN:
        raise WatManifestSignatureError(
            f"signature block signature must be {_SIGNATURE_HEX_LEN} hex "
            f"chars (64 bytes); got {len(sig_hex)}"
        )
    try:
        sig_bytes = bytes.fromhex(sig_hex)
    except ValueError as exc:
        raise WatManifestSignatureError(
            f"signature block signature is not valid hex: {exc}"
        ) from exc
    if len(sig_bytes) != 64:
        raise WatManifestSignatureError(
            f"Ed25519 signature must be 64 bytes; got {len(sig_bytes)}"
        )


def _validate_manifest_shape(manifest: Mapping[str, Any]) -> None:
    """Validate the minimum manifest shape required for signing.

    The signing primitive does NOT re-implement the full JSON-Schema
    validation in :func:`wat.verify.manifest_v2._validate_schema`; it
    only enforces the structural minimum needed to compute a
    deterministic pre-image:

    1. The manifest must be a mapping.
    2. It must carry a recognised ``version`` discriminator.

    A v1 or v2 manifest that fails the full schema check will still
    sign deterministically; the signer is intentionally permissive on
    structural detail and leaves schema-conformance to the verifier.
    """
    if not isinstance(manifest, Mapping):
        raise WatManifestSignatureError(
            f"manifest must be a mapping: type={type(manifest).__name__}"
        )
    if "version" not in manifest:
        raise WatManifestSignatureError(
            "manifest missing required field: 'version'"
        )
    version = manifest["version"]
    if version not in _SIGNABLE_VERSIONS:
        raise WatManifestSignatureError(
            f"manifest version not signable: {version!r}; want one of "
            f"{sorted(_SIGNABLE_VERSIONS)!r}"
        )


# ---------------------------------------------------------------------------
# Wrapper dataclass.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignedWatManifest:
    """A signed WAT hour-manifest.

    Wraps an unsigned manifest dict together with its detached
    signature block. The pair is the canonical in-memory representation
    of a signed manifest; the signature block is serialised back onto
    the envelope under the optional top-level ``signature`` slot by
    :func:`envelope_with_signature`.

    The ``manifest`` field is the manifest body WITHOUT the
    ``signature`` slot (the pre-image). Mutations after construction
    are the caller's responsibility -- the dataclass is ``frozen=True``
    on its slot bindings but does NOT deep-freeze the manifest dict.
    """

    manifest: Mapping[str, Any]
    signature: Mapping[str, Any] = field()

    def __post_init__(self) -> None:
        # Validate eagerly so downstream consumers can trust the
        # contract without re-validating. Shape errors here are
        # structural failures (programmer error path), not
        # cryptographic-mismatch errors.
        _validate_manifest_shape(self.manifest)
        _validate_signature_block_shape(self.signature)


# ---------------------------------------------------------------------------
# Canonical pre-image computation.
# ---------------------------------------------------------------------------


def _canonical_signing_payload(manifest: Mapping[str, Any]) -> bytes:
    """Strip the signature slot and return SHA-256 of the JCS bytes.

    The ``signature`` field is removed from a deep copy of the input
    so the caller's manifest is not mutated. JCS canonical form is
    computed with ``rfc8785``; SHA-256 of that byte-string is the
    signing input. Mirrors
    :func:`wirelang.identity.aip_signing._canonical_signing_payload`
    and :func:`wirelang.schemas.entry_signing._canonical_signing_payload`
    field-for-field; the *only* difference is the strip-set: this
    module strips ``signature`` (matching schema-registry-entry
    convention), the AIP module strips ``document_signature``.
    """
    body = copy.deepcopy(dict(manifest))
    body.pop(SIGNATURE_FIELD, None)
    canonical = rfc8785.dumps(body)
    return hashlib.sha256(canonical).digest()


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def sign_manifest(
    manifest: Mapping[str, Any],
    ed25519_priv_key: bytes,
    *,
    kid: str,
) -> SignedWatManifest:
    """Sign a WAT hour-manifest.

    The signing pre-image is SHA-256 of the JCS-canonicalised manifest
    payload with the ``signature`` slot stripped (deterministic,
    byte-identical in shape to the AIP-document and schema-registry-
    entry conventions). Ed25519 then signs the digest.

    Args:
        manifest: a WAT hour-manifest dict. Must carry a recognised
            ``version`` field (``wat-manifest/1.0`` or
            ``wat-manifest/2.0``). Not mutated.
        ed25519_priv_key: 32-byte raw Ed25519 private key.
        kid: key identifier to embed in the signature block. Must be
            a non-empty string. Caller's responsibility to bind this
            to an AIP-document ``public_keys`` entry identifier under
            :data:`wat.identity.anchor_kid.PURPOSE_WAT_ANCHOR`.

    Returns:
        :class:`SignedWatManifest` carrying the unsigned manifest body
        (without the ``signature`` slot) and the signature block.

    Raises:
        :class:`WatManifestSignatureError`: on wrong key length, empty
            kid, missing or unrecognised manifest ``version``,
            non-mapping manifest.
    """
    if not isinstance(ed25519_priv_key, (bytes, bytearray)):
        raise WatManifestSignatureError(
            f"ed25519_priv_key must be bytes; type="
            f"{type(ed25519_priv_key).__name__}"
        )
    if len(ed25519_priv_key) != _ED25519_KEY_LEN:
        raise WatManifestSignatureError(
            f"ed25519_priv_key must be a 32-byte raw seed; got "
            f"{len(ed25519_priv_key)} bytes"
        )
    if not isinstance(kid, str) or kid == "":
        raise WatManifestSignatureError(
            f"kid must be a non-empty string: got {kid!r}"
        )

    _validate_manifest_shape(manifest)

    # Construct the unsigned body explicitly so SignedWatManifest
    # carries the pre-image, not the original (which may already have
    # a signature slot we are about to overwrite).
    unsigned_body: dict[str, Any] = copy.deepcopy(dict(manifest))
    unsigned_body.pop(SIGNATURE_FIELD, None)

    digest = _canonical_signing_payload(unsigned_body)
    sk = Ed25519PrivateKey.from_private_bytes(bytes(ed25519_priv_key))
    raw_sig = sk.sign(digest)
    signature_block: dict[str, Any] = {
        "alg": SIGNATURE_ALG,
        "kid": kid,
        "signature": raw_sig.hex(),
    }
    return SignedWatManifest(
        manifest=unsigned_body,
        signature=signature_block,
    )


def verify_manifest_signature(
    signed: Union[SignedWatManifest, Mapping[str, Any]],
    ed25519_pub_key: Optional[bytes] = None,
    *,
    mode: VerifyMode = VerifyMode.PERMISSIVE,
    signature_block: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Verify a WAT-manifest signature.

    The signed / unsigned cases:

    - :class:`SignedWatManifest`: verify end-to-end with the supplied
      public key.
    - Bare manifest mapping carrying its own ``signature`` slot:
      verify end-to-end with the supplied public key. The slot is
      stripped from the pre-image and validated as the signature
      block.
    - Bare manifest mapping WITHOUT a ``signature`` slot, with explicit
      ``signature_block``: verify end-to-end against the supplied
      block.
    - Bare manifest mapping WITHOUT a ``signature`` slot AND no
      ``signature_block``: treated as unsigned.

    Args:
        signed: the manifest to verify. Accepts the
            :class:`SignedWatManifest` wrapper or a raw manifest dict
            (which may or may not carry an embedded ``signature``
            slot).
        ed25519_pub_key: 32-byte raw Ed25519 public key. Required for
            signed manifests; ignored for unsigned manifests under
            ``PERMISSIVE`` mode.
        mode: verify-mode policy. ``PERMISSIVE`` (default) accepts
            unsigned manifests as ``True``; ``STRICT`` rejects them.
        signature_block: optional explicit signature block for the
            bare-manifest path. When supplied AND the manifest does
            not already carry an embedded ``signature`` slot, the
            manifest is treated as signed against this block.

    Returns:
        ``True`` if the signature verifies cryptographically OR if the
        manifest is unsigned under ``PERMISSIVE`` mode. ``False`` if
        the signature is well-formed but does NOT verify
        cryptographically.

    Raises:
        :class:`WatManifestSignatureError`: on structural failures
            (missing block under ``STRICT``, malformed block, wrong
            key length, missing or unrecognised manifest ``version``).
    """
    # Resolve the (manifest, block) pair from the union input.
    block: Optional[Mapping[str, Any]]
    manifest: Mapping[str, Any]
    if isinstance(signed, SignedWatManifest):
        manifest = signed.manifest
        block = signed.signature
    elif isinstance(signed, Mapping):
        # A raw manifest dict; peek at its embedded signature slot.
        if SIGNATURE_FIELD in signed and signature_block is None:
            # Strip a deep copy to keep the caller's manifest pristine.
            stripped = copy.deepcopy(dict(signed))
            block = stripped.pop(SIGNATURE_FIELD)
            manifest = stripped
        else:
            manifest = signed
            block = signature_block
    else:
        raise WatManifestSignatureError(
            f"signed must be SignedWatManifest or Mapping; type="
            f"{type(signed).__name__}"
        )

    _validate_manifest_shape(manifest)

    # Unsigned path: PERMISSIVE accepts, STRICT rejects.
    if block is None:
        if mode is VerifyMode.PERMISSIVE:
            return True
        if mode is VerifyMode.STRICT:
            raise WatManifestSignatureError(
                "manifest is unsigned and verify mode is STRICT"
            )
        raise WatManifestSignatureError(f"unknown VerifyMode: {mode!r}")

    # Signed path: structural validation then cryptographic verify.
    _validate_signature_block_shape(block)

    if ed25519_pub_key is None:
        raise WatManifestSignatureError(
            "ed25519_pub_key is required for signed-manifest verification"
        )
    if not isinstance(ed25519_pub_key, (bytes, bytearray)):
        raise WatManifestSignatureError(
            f"ed25519_pub_key must be bytes; type="
            f"{type(ed25519_pub_key).__name__}"
        )
    if len(ed25519_pub_key) != _ED25519_KEY_LEN:
        raise WatManifestSignatureError(
            f"ed25519_pub_key must be a 32-byte raw key; got "
            f"{len(ed25519_pub_key)} bytes"
        )

    digest = _canonical_signing_payload(manifest)
    pk = Ed25519PublicKey.from_public_bytes(bytes(ed25519_pub_key))
    sig_bytes = bytes.fromhex(block["signature"])
    try:
        pk.verify(sig_bytes, digest)
        return True
    except InvalidSignature:
        return False


# ---------------------------------------------------------------------------
# Envelope codec helpers (round-trip the optional signature slot).
# ---------------------------------------------------------------------------


def envelope_with_signature(signed: SignedWatManifest) -> bytes:
    """Serialise a signed manifest to canonical envelope bytes.

    The output is the manifest dict with the ``signature`` slot
    re-attached, serialised as canonical JSON (sorted keys, compact
    separators, UTF-8). The schema URI is unchanged; this is an
    additive optional field on the existing manifest envelope.

    The serialiser is the simple ``json.dumps`` canonical form, NOT
    RFC 8785 JCS. This is intentional: the signed pre-image is
    JCS-canonicalised (cryptographic determinism) but the wire form
    is plain canonical JSON (operator-readable). Verifiers re-strip
    the slot and JCS-canonicalise on their side; round-trip
    determinism is guaranteed by the JCS step, not by the wire form.
    """
    if not isinstance(signed, SignedWatManifest):
        raise TypeError("signed must be a SignedWatManifest")
    payload = copy.deepcopy(dict(signed.manifest))
    payload[SIGNATURE_FIELD] = dict(signed.signature)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def envelope_to_signed_manifest(
    blob: bytes,
) -> Union[SignedWatManifest, dict[str, Any]]:
    """Inverse of :func:`envelope_with_signature`.

    When the envelope carries a ``signature`` slot, returns a
    :class:`SignedWatManifest`. When the slot is absent, returns the
    raw manifest dict (unsigned).

    Raises:
        :class:`WatManifestSignatureError`: on JSON decode failure,
            non-mapping envelope, missing or unrecognised manifest
            ``version``, or malformed signature slot.
    """
    if not isinstance(blob, (bytes, bytearray)):
        raise WatManifestSignatureError(
            f"blob must be bytes; type={type(blob).__name__}"
        )
    try:
        text = bytes(blob).decode("utf-8")
        payload = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WatManifestSignatureError(
            f"envelope decode failed: {exc!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise WatManifestSignatureError(
            "envelope is not a JSON object"
        )

    if SIGNATURE_FIELD not in payload:
        # Unsigned path: validate shape eagerly so unsigned-path
        # callers also benefit from structural diagnostics.
        _validate_manifest_shape(payload)
        return payload

    signature_block = payload.pop(SIGNATURE_FIELD)
    _validate_manifest_shape(payload)
    _validate_signature_block_shape(signature_block)
    return SignedWatManifest(manifest=payload, signature=signature_block)
