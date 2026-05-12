# SPDX-License-Identifier: Apache-2.0
"""AIP-document ``kid`` → Ed25519 public-key resolver (Phase-2 Sprint-4 Tag-3).

This module is the Identity-Substrate kid-resolver for the Phase-2
schema-registry-entry-signing layer (Sprint-4 Tag-1,
:mod:`wirelang.schemas.entry_signing`). It binds a free-form ``kid``
string carried on a signature block to the 32-byte raw Ed25519 public
key stored under the matching ``public_keys`` entry of an AIP document.

Design contract (spec §5.9):

1. **Lookup target:** the resolver iterates ``aip_doc["public_keys"]``
   and matches on the ``kid`` field of each entry. The AIP-document
   JSON-Schema (``wirelang/schemas/aip-document.json``) defines this
   field as ``kid`` (not ``id``); the Z-1-K-Sprint-4-1 consensus marker
   captures the resolver contract under the placeholder phrasing
   "public_keys[i].id", which refers byte-accurately to the same
   ``kid``-typed identifier on each ``public_keys`` entry. See spec
   §5.9 "Phase-2 Sprint-4 Tag-3 byte-accuracy note".
2. **Algorithm filter:** only ``alg == "Ed25519"`` entries are
   considered (the two-curve-stack consensus marker Z-1-K-Sprint-4-3
   reserves secp256k1 for Biscuit-capability-token-burst-layer). An
   entry with ``alg == "secp256k1"`` is invisible to this resolver.
3. **Validity-window filter:** if the entry carries a ``validafter`` /
   ``validuntil`` window and the caller supplies an ``as_of`` timestamp
   the window is enforced (out-of-window matches raise
   :class:`KidResolverError`). The ``as_of`` default is *no window
   check* so callers can resolve historical signatures without time
   coupling; production verifier paths SHOULD supply ``as_of``.
4. **Duplicate ``kid`` policy:** a duplicate ``kid`` within
   ``public_keys`` is a structural-failure of the AIP document and
   raises :class:`KidResolverError`. The AIP-document JSON-Schema does
   not forbid duplicates at write time; the resolver enforces
   single-match at read time.

Phase-2 Sprint-4 Tag-3 boundary (spec §5.9 boundary block):

- This module ships the pure resolver function only. It does NOT
  fetch the AIP document from a transport (``did:web`` / ``aip:web``);
  the caller supplies the document.
- This module does NOT bind ``kid`` to the schema-registry
  ``registered_by`` field. Capability-token gating on ``registered_by``
  remains a future Phase-2 slot.
- This module does NOT validate the AIP-document signature; the
  caller is responsible for AIP-document trust establishment
  (``wirelang.identity.verify_aip_signature``).

Cross-Review-Zone-1 (Identity-Substrate) closure:

- Z-1-K-Sprint-4-1 (kid-Resolver-Shape) is closed by this module.
- Z-1-K-Sprint-4-2 (JCS-Resolver-Lock) is non-touched here (resolver
  does not canonicalise).
- Z-1-K-Sprint-4-3 (Curve-Choice = Ed25519 for Identity-Document
  layer) is reinforced: secp256k1 entries are filtered out.
- Z-1-K-Sprint-4-4 (STRICT-Mode-Activation-Owner) is non-touched here
  (resolver is policy-agnostic; the caller drives ``VerifyMode``).

References:

- Spec §5.9 (kid-resolver operational contract).
- AIP draft section 2.3 (``public_keys`` field shape):
  <https://datatracker.ietf.org/doc/html/draft-prakash-aip-00>.
- Schema-registry spec §5.8 (entry-signing layer).
- Z-1-Sprint-4-Anhang consensus marker
  (``agents-workspaces/hr/outbox/2026-05-11-cross-review-zone-1-konsens-marker-final.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# Typed exception (structural failure class).
# ---------------------------------------------------------------------------


class KidResolverError(Exception):
    """Structural resolver failure.

    Raised on: missing ``aip_doc["public_keys"]`` array, malformed
    ``public_keys`` entry shape, kid not found, duplicate kid within
    ``public_keys``, wrong public-key byte length, malformed
    ``key_hex``, out-of-window match (when ``as_of`` is supplied),
    unsupported ``alg`` filter combination.

    The split with :class:`SchemaRegistrySignatureError` is deliberate:
    structural failures of an AIP-document live here; structural
    failures of a signature block live in entry_signing. Callers can
    distinguish "the AIP document is broken" from "the signature
    block is broken".
    """


# ---------------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------------


SUPPORTED_ALG: str = "Ed25519"
"""Identity-document layer curve per Z-1-K-Sprint-4-3 consensus."""

_ED25519_KEY_LEN: int = 32
_ED25519_KEY_HEX_LEN: int = 64  # 32 bytes = 64 hex chars


# ---------------------------------------------------------------------------
# Public surface (dataclass result + pure functions).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedPublicKey:
    """A resolved ``public_keys`` entry.

    Carries the raw 32-byte Ed25519 public key plus the validity-window
    metadata that the resolver consulted, so the caller can re-bind the
    resolution to logging / audit trails without re-walking the AIP
    document.
    """

    kid: str
    """The kid that was matched."""

    public_key: bytes
    """32-byte raw Ed25519 public key, ready for
    :class:`Ed25519PublicKey.from_public_bytes`."""

    validafter: Optional[datetime]
    """RFC 3339 timestamp parsed to ``datetime`` (UTC). ``None`` when
    the source entry omits ``validafter`` (forbidden by the AIP schema
    but tolerated here for robustness)."""

    validuntil: Optional[datetime]
    """RFC 3339 timestamp parsed to ``datetime`` (UTC), or ``None`` for
    an open-ended window."""

    purpose: Optional[str]
    """Wakir-scoped ``purpose`` tag, when present on the source entry
    (e.g. ``"aip-signing"``, ``"biscuit-root"``)."""


def resolve_kid(
    aip_doc: Mapping[str, Any],
    kid: str,
    *,
    as_of: Optional[datetime] = None,
    require_purpose: Optional[str] = None,
) -> ResolvedPublicKey:
    """Resolve a ``kid`` to the matching AIP-document public-key entry.

    Args:
        aip_doc: an AIP document. The resolver reads
            ``aip_doc["public_keys"]`` only; other fields are ignored.
            The document does NOT need to be signature-verified before
            being passed here (caller responsibility).
        kid: the key identifier to resolve. Must be a non-empty string.
            Matched byte-equal against the ``kid`` field of each
            ``public_keys`` entry.
        as_of: optional point-in-time for validity-window checks. When
            supplied, an entry is only matched if
            ``validafter <= as_of`` and (``validuntil is None`` or
            ``as_of < validuntil``). Production verifier paths SHOULD
            supply this. Naive datetimes are assumed UTC.
        require_purpose: optional Wakir-scoped purpose filter. When
            supplied, an entry only matches if its ``purpose`` field
            is byte-equal to this argument. Entries without a
            ``purpose`` field do NOT match.

    Returns:
        A :class:`ResolvedPublicKey` carrying the 32-byte raw Ed25519
        public key plus the validity-window metadata.

    Raises:
        :class:`KidResolverError`: on any structural failure (see class
        docstring for the inventory).
    """
    if not isinstance(aip_doc, Mapping):
        raise KidResolverError(
            f"aip_doc must be a mapping; type={type(aip_doc).__name__}"
        )
    if not isinstance(kid, str) or kid == "":
        raise KidResolverError(
            f"kid must be a non-empty string; got {kid!r}"
        )
    if "public_keys" not in aip_doc:
        raise KidResolverError(
            "aip_doc is missing the 'public_keys' field"
        )
    public_keys = aip_doc["public_keys"]
    if not isinstance(public_keys, Sequence) or isinstance(public_keys, (str, bytes)):
        raise KidResolverError(
            f"aip_doc['public_keys'] must be a sequence; type="
            f"{type(public_keys).__name__}"
        )
    if len(public_keys) == 0:
        raise KidResolverError(
            "aip_doc['public_keys'] is empty (AIP-schema minItems=1)"
        )

    # Walk the array, collecting matches. Duplicate-kid is a structural
    # failure of the AIP document; we surface that explicitly rather
    # than silently picking the first match.
    matches: list[tuple[int, Mapping[str, Any]]] = []
    for idx, entry in enumerate(public_keys):
        if not isinstance(entry, Mapping):
            raise KidResolverError(
                f"public_keys[{idx}] must be a mapping; type="
                f"{type(entry).__name__}"
            )
        if entry.get("kid") == kid:
            matches.append((idx, entry))

    if len(matches) == 0:
        raise KidResolverError(
            f"kid not found in public_keys: kid={kid!r}, "
            f"candidates={[e.get('kid') for e in public_keys]!r}"
        )
    if len(matches) > 1:
        raise KidResolverError(
            f"duplicate kid in public_keys: kid={kid!r}, "
            f"indices={[i for i, _ in matches]!r}"
        )

    idx, entry = matches[0]

    # Algorithm filter — Z-1-K-Sprint-4-3 (Identity-Document layer is
    # Ed25519-only; secp256k1 entries belong to the capability-token
    # burst layer).
    alg = entry.get("alg")
    if alg != SUPPORTED_ALG:
        raise KidResolverError(
            f"public_keys[{idx}] alg is not {SUPPORTED_ALG!r}: "
            f"alg={alg!r}; resolver is Identity-Document-layer "
            f"(Z-1-K-Sprint-4-3 two-curve-stack)"
        )

    # Required field: key_hex.
    if "key_hex" not in entry:
        raise KidResolverError(
            f"public_keys[{idx}] is missing 'key_hex' (kid={kid!r})"
        )
    key_hex = entry["key_hex"]
    if not isinstance(key_hex, str):
        raise KidResolverError(
            f"public_keys[{idx}] key_hex must be a string; type="
            f"{type(key_hex).__name__} (kid={kid!r})"
        )
    if len(key_hex) != _ED25519_KEY_HEX_LEN:
        raise KidResolverError(
            f"public_keys[{idx}] key_hex must be {_ED25519_KEY_HEX_LEN} "
            f"hex chars (32 bytes Ed25519); got {len(key_hex)} (kid={kid!r})"
        )
    try:
        public_key = bytes.fromhex(key_hex)
    except ValueError as exc:
        raise KidResolverError(
            f"public_keys[{idx}] key_hex is not valid hex: {exc} "
            f"(kid={kid!r})"
        ) from exc
    if len(public_key) != _ED25519_KEY_LEN:
        raise KidResolverError(
            f"public_keys[{idx}] key_hex decoded to {len(public_key)} "
            f"bytes; want {_ED25519_KEY_LEN} (kid={kid!r})"
        )

    # Validity-window parse (always parse so the result is well-formed).
    validafter_raw = entry.get("validafter")
    validuntil_raw = entry.get("validuntil")
    validafter = _parse_rfc3339(validafter_raw, idx, kid, "validafter") \
        if validafter_raw is not None else None
    validuntil = _parse_rfc3339(validuntil_raw, idx, kid, "validuntil") \
        if validuntil_raw is not None else None

    # Validity-window check (only when as_of is supplied).
    if as_of is not None:
        as_of_utc = _ensure_utc(as_of)
        if validafter is not None and as_of_utc < validafter:
            raise KidResolverError(
                f"public_keys[{idx}] is not yet valid: validafter="
                f"{validafter.isoformat()} > as_of={as_of_utc.isoformat()} "
                f"(kid={kid!r})"
            )
        if validuntil is not None and as_of_utc >= validuntil:
            raise KidResolverError(
                f"public_keys[{idx}] has expired: validuntil="
                f"{validuntil.isoformat()} <= as_of={as_of_utc.isoformat()} "
                f"(kid={kid!r})"
            )

    # Purpose filter (only when require_purpose is supplied).
    purpose = entry.get("purpose")
    if require_purpose is not None:
        if purpose != require_purpose:
            raise KidResolverError(
                f"public_keys[{idx}] purpose mismatch: have={purpose!r}, "
                f"want={require_purpose!r} (kid={kid!r})"
            )

    return ResolvedPublicKey(
        kid=kid,
        public_key=public_key,
        validafter=validafter,
        validuntil=validuntil,
        purpose=purpose if isinstance(purpose, str) else None,
    )


def list_resolvable_kids(
    aip_doc: Mapping[str, Any],
    *,
    as_of: Optional[datetime] = None,
    require_purpose: Optional[str] = None,
) -> list[str]:
    """Enumerate the kids that :func:`resolve_kid` would succeed on.

    Useful for verifier-side audit logging ("which kids would I have
    accepted at time T?") and for operator dry-runs before flipping
    a registry to :class:`VerifyMode.STRICT`.

    Filters: ``alg == Ed25519`` only; window check when ``as_of`` is
    supplied; purpose filter when supplied; duplicate-kid entries are
    excluded from the list (a duplicate is a structural failure that
    :func:`resolve_kid` would raise on).

    Args:
        aip_doc: an AIP document.
        as_of: optional point-in-time for validity-window checks.
        require_purpose: optional purpose filter.

    Returns:
        Sorted list of kids that would resolve. Returns an empty list
        when no ``public_keys`` entry matches the filters (this is not
        a structural failure).

    Raises:
        :class:`KidResolverError`: on a structurally-broken AIP
        document (missing ``public_keys``, non-sequence, etc.). Per-
        entry malformation (wrong alg, missing key_hex) is silently
        filtered out — this is a *list* operation, not a *resolve*
        operation.
    """
    if not isinstance(aip_doc, Mapping):
        raise KidResolverError(
            f"aip_doc must be a mapping; type={type(aip_doc).__name__}"
        )
    if "public_keys" not in aip_doc:
        raise KidResolverError(
            "aip_doc is missing the 'public_keys' field"
        )
    public_keys = aip_doc["public_keys"]
    if not isinstance(public_keys, Sequence) or isinstance(public_keys, (str, bytes)):
        raise KidResolverError(
            f"aip_doc['public_keys'] must be a sequence; type="
            f"{type(public_keys).__name__}"
        )

    # First pass: collect kids and detect duplicates.
    kid_counts: dict[str, int] = {}
    for entry in public_keys:
        if not isinstance(entry, Mapping):
            continue
        k = entry.get("kid")
        if not isinstance(k, str) or k == "":
            continue
        kid_counts[k] = kid_counts.get(k, 0) + 1

    # Second pass: filter on alg / window / purpose.
    resolvable: list[str] = []
    as_of_utc = _ensure_utc(as_of) if as_of is not None else None
    for entry in public_keys:
        if not isinstance(entry, Mapping):
            continue
        k = entry.get("kid")
        if not isinstance(k, str) or k == "":
            continue
        if kid_counts.get(k, 0) != 1:
            # Duplicate-kid is unresolvable.
            continue
        if entry.get("alg") != SUPPORTED_ALG:
            continue
        key_hex = entry.get("key_hex")
        if not isinstance(key_hex, str) or len(key_hex) != _ED25519_KEY_HEX_LEN:
            continue
        try:
            decoded = bytes.fromhex(key_hex)
        except ValueError:
            continue
        if len(decoded) != _ED25519_KEY_LEN:
            continue
        if as_of_utc is not None:
            va_raw = entry.get("validafter")
            vu_raw = entry.get("validuntil")
            try:
                va = _parse_rfc3339(va_raw, -1, k, "validafter") \
                    if va_raw is not None else None
                vu = _parse_rfc3339(vu_raw, -1, k, "validuntil") \
                    if vu_raw is not None else None
            except KidResolverError:
                continue
            if va is not None and as_of_utc < va:
                continue
            if vu is not None and as_of_utc >= vu:
                continue
        if require_purpose is not None:
            if entry.get("purpose") != require_purpose:
                continue
        resolvable.append(k)

    return sorted(resolvable)


# ---------------------------------------------------------------------------
# Internal helpers.
# ---------------------------------------------------------------------------


def _parse_rfc3339(
    value: Any,
    idx: int,
    kid: str,
    field_name: str,
) -> datetime:
    """Parse an RFC 3339 timestamp; raise :class:`KidResolverError` on
    failure."""
    if not isinstance(value, str):
        raise KidResolverError(
            f"public_keys[{idx}] {field_name} must be a string; type="
            f"{type(value).__name__} (kid={kid!r})"
        )
    # Accept both ``Z`` and ``+00:00`` UTC suffixes; the AIP-document
    # generator emits ``Z``-suffixed timestamps via _utc_now_iso.
    text = value
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise KidResolverError(
            f"public_keys[{idx}] {field_name} is not valid RFC 3339: "
            f"{value!r} ({exc}) (kid={kid!r})"
        ) from exc
    if parsed.tzinfo is None:
        # Naive timestamps are assumed UTC for backward tolerance with
        # legacy AIP-document generators that omitted the zone.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    """Promote a naive datetime to UTC; convert aware datetimes to UTC."""
    if not isinstance(value, datetime):
        raise KidResolverError(
            f"as_of must be a datetime; type={type(value).__name__}"
        )
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
