# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""WAT-side anchor-kid reference + resolver bridge.

The WAT-domain entry point that binds a hour-manifest (or a future
manifest-level ``anchor_kid`` field) to an Ed25519 public key under
the matching ``public_keys[i].kid`` entry of an AIP document.

The resolver algorithm itself (6-step filter: mapping-shape, kid-
found, single-match, alg-Ed25519, key_hex-shape, validity-window) is
the canonical Identity-Substrate kid-resolver
(:func:`wirelang.identity.kid_resolver.resolve_kid`). This module
delegates to it under the ``require_purpose="wat-anchor"`` filter and
re-raises errors as :class:`WatAnchorKidError` so WAT-domain callers
do not have to depend on Identity-Substrate exception types directly.

DRY-consistency vs. Identity-Substrate-Sprint-4-Tag-3 (spec §5.9):

The WAT-side does NOT re-implement the resolver. The filter chain
inside :func:`resolve_wat_anchor_kid` is exactly one canonical
``resolve_kid`` call plus a WAT-domain error wrap. The
``"wat-anchor"`` purpose value is read from the AIP-document JSON-
Schema (``wirelang/schemas/aip-document.json`` §public_keys.purpose)
and re-exported here as :data:`PURPOSE_WAT_ANCHOR` so a WAT-domain
caller does not have to hard-code the string.

Cross-Review-Zone-1 boundary:

- Schema-File (``wirelang/schemas/aip-document.json``) is
  Identity-Substrate-engineering-owner-domain — NOT edited here.
- Canonical resolver (``wirelang/identity/kid_resolver.py``) is
  Identity-Substrate-engineering-owner-domain — NOT edited here, only imported.
- WAT-domain reference shape (this module) is dev-engineering-owner-
  domain. The manifest-level wire-up (adding an ``anchor_kid`` field
  to ``wat-manifest-v2.json``) is intentionally NOT done in Sprint-4
  Tag-5 — that requires Cross-Review-Zone-1 coordination with
  Identity-Substrate-engineering on the canonical reference shape
  inside the AIP-document schema.

Import strategy:

The canonical resolver lives on a sibling Identity-Substrate branch
that has not yet merged to ``main`` at Sprint-4 Tag-5 publish time.
This module uses a deferred-import pattern (``importlib`` inside the
function bodies) so that:

1. The WAT-domain reference-shape primitives (:class:`WatAnchorKidRef`,
   :class:`WatAnchorKidError`, :func:`validate_anchor_kid_ref_shape`)
   are importable and testable without the canonical resolver
   present.
2. :func:`resolve_wat_anchor_kid` raises a clear
   :class:`WatAnchorKidError` when the canonical resolver is not
   available, naming the missing module so an operator can
   diagnose the cross-branch merge gap.
3. :func:`is_kid_resolver_available` is a public probe so callers
   (or test suites) can short-circuit before invoking the resolver.
"""

from __future__ import annotations

import dataclasses
import importlib
from datetime import datetime, timezone
from typing import Any, Mapping, Optional


# ---------------------------------------------------------------------------
# Constants — purpose-tag from the AIP-document schema enum.
# ---------------------------------------------------------------------------


PURPOSE_WAT_ANCHOR: str = "wat-anchor"
"""WAT-domain ``purpose`` value used to filter AIP-document
``public_keys[]`` entries.

Source of truth: ``wirelang/schemas/aip-document.json``
``public_keys[].purpose`` enum. The schema-file enumerates four
purpose-tags (``aip-signing``, ``biscuit-root``, ``wat-anchor``,
``frame-signing``). This module pins the WAT-anchor slot and is
the only WAT-domain consumer of the enum.
"""


_CANONICAL_RESOLVER_MODULE: str = "wirelang.identity.kid_resolver"
"""Dotted-import path of the canonical Identity-Substrate kid-
resolver. Resolved lazily so that the WAT-side reference primitives
remain importable even when the resolver branch has not merged."""


# ---------------------------------------------------------------------------
# WAT-domain typed exception.
# ---------------------------------------------------------------------------


class WatAnchorKidError(Exception):
    """WAT-domain anchor-kid resolution failure.

    Raised on: malformed :class:`WatAnchorKidRef` shape, canonical
    resolver missing (cross-branch merge gap), or any structural
    failure surfaced by the canonical kid-resolver
    (:class:`wirelang.identity.kid_resolver.KidResolverError`).

    The split with :class:`KidResolverError` is deliberate: callers
    in the WAT verifier / aggregator / archive-walker stack can
    catch ``WatAnchorKidError`` without importing the Identity-
    Substrate exception type. When the canonical resolver is
    available, the original ``KidResolverError`` is chained as the
    ``__cause__`` so debugging tooling can recover the inner
    structural failure category.
    """


# ---------------------------------------------------------------------------
# Reference-shape dataclass + result dataclass.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class WatAnchorKidRef:
    """WAT-side anchor-kid reference.

    Carries the kid that a hour-manifest (or a future archive entry)
    references on its AIP-document anchor identity, plus optional
    binding metadata that callers want to fold into the resolver
    call.

    Attributes
    ----------
    kid:
        The key identifier to resolve. Must be a non-empty string —
        same constraint as the canonical resolver.
    as_of:
        Optional point-in-time for validity-window enforcement,
        forwarded to the canonical resolver. WAT manifests carry a
        ``build_time`` timestamp; the verifier should pass that as
        ``as_of`` so an expired key cannot retroactively authorise
        an older hour-anchor.
    """

    kid: str
    as_of: Optional[datetime] = None


@dataclasses.dataclass(frozen=True)
class ResolvedAnchorKey:
    """Outcome of a successful WAT-side anchor-kid resolution.

    Mirrors the canonical
    :class:`wirelang.identity.kid_resolver.ResolvedPublicKey` but
    drops the ``purpose`` field because it is constant by contract
    here (always ``"wat-anchor"``). The dataclass is a separate type
    so that WAT-domain callers do not have to import the
    Identity-Substrate result type.
    """

    kid: str
    public_key: bytes
    validafter: Optional[datetime]
    validuntil: Optional[datetime]


# ---------------------------------------------------------------------------
# Public surface — shape validation, resolver-availability probe, bridge.
# ---------------------------------------------------------------------------


def validate_anchor_kid_ref_shape(kid_ref: Any) -> None:
    """Validate the WAT-domain reference-shape without invoking the
    canonical resolver.

    Useful for early-fail in a manifest-parse path where the resolver
    is not on the import path yet (Sprint-4 Tag-5 cross-branch state)
    or where the caller wants to fail fast before hitting an AIP-
    document fetch.

    Args:
        kid_ref: candidate :class:`WatAnchorKidRef` instance.

    Raises:
        :class:`WatAnchorKidError`: when the candidate is not a
        :class:`WatAnchorKidRef`, when the kid is not a non-empty
        string, or when ``as_of`` is not ``None`` and not a
        ``datetime``.
    """
    if not isinstance(kid_ref, WatAnchorKidRef):
        raise WatAnchorKidError(
            f"kid_ref must be a WatAnchorKidRef; type="
            f"{type(kid_ref).__name__}"
        )
    if not isinstance(kid_ref.kid, str) or kid_ref.kid == "":
        raise WatAnchorKidError(
            f"kid_ref.kid must be a non-empty string; got {kid_ref.kid!r}"
        )
    if kid_ref.as_of is not None and not isinstance(kid_ref.as_of, datetime):
        raise WatAnchorKidError(
            f"kid_ref.as_of must be a datetime or None; type="
            f"{type(kid_ref.as_of).__name__}"
        )


def is_kid_resolver_available() -> bool:
    """Return True iff the canonical Identity-Substrate kid-resolver
    is importable in the current Python environment.

    Use this as a short-circuit probe in code paths that want a clean
    skip when the resolver branch has not merged yet (e.g. CI gates
    running on ``main`` before the Identity-Substrate Sprint-4 Tag-3
  branch merges).
    """
    try:
        importlib.import_module(_CANONICAL_RESOLVER_MODULE)
    except ImportError:
        return False
    return True


def resolve_wat_anchor_kid(
    aip_doc: Mapping[str, Any],
    kid_ref: WatAnchorKidRef,
) -> ResolvedAnchorKey:
    """Resolve a WAT-side anchor-kid reference against an AIP document.

    Delegates the 6-step filter (mapping-shape, kid-found, single-
    match, alg-Ed25519, key_hex-shape, validity-window) to the
    canonical Identity-Substrate kid-resolver, applies the WAT-domain
    ``purpose == "wat-anchor"`` filter, and surfaces the result as a
    WAT-domain :class:`ResolvedAnchorKey`.

    Args:
        aip_doc: an AIP document. The resolver reads
            ``aip_doc["public_keys"]`` only; other fields are
            ignored. The document does NOT need to be signature-
            verified before being passed here (caller responsibility,
            same contract as the canonical resolver).
        kid_ref: the WAT-side reference to resolve. ``kid`` selects
            the entry; ``as_of`` is forwarded to the validity-window
            check.

    Returns:
        :class:`ResolvedAnchorKey` carrying the 32-byte raw Ed25519
        public key plus the validity-window metadata.

    Raises:
        :class:`WatAnchorKidError`: on malformed reference shape, on
        canonical-resolver unavailability (cross-branch merge gap),
        or on any structural failure surfaced by the canonical
        resolver. The original ``KidResolverError`` is chained via
        ``__cause__`` when available.
    """
    validate_anchor_kid_ref_shape(kid_ref)

    try:
        kid_resolver = importlib.import_module(_CANONICAL_RESOLVER_MODULE)
    except ImportError as exc:
        raise WatAnchorKidError(
            f"canonical kid-resolver not available: "
            f"{_CANONICAL_RESOLVER_MODULE} is not importable "
            f"(cross-branch merge gap; Identity-Substrate Sprint-4 "
            f"Tag-3 must merge before WAT-Side resolution can run): "
            f"{exc}"
        ) from exc

    resolve_kid = kid_resolver.resolve_kid
    KidResolverError = kid_resolver.KidResolverError

    as_of_utc = _ensure_utc(kid_ref.as_of) if kid_ref.as_of is not None else None

    try:
        resolved = resolve_kid(
            aip_doc,
            kid=kid_ref.kid,
            as_of=as_of_utc,
            require_purpose=PURPOSE_WAT_ANCHOR,
        )
    except KidResolverError as exc:
        raise WatAnchorKidError(
            f"canonical resolver rejected kid={kid_ref.kid!r} for "
            f"purpose={PURPOSE_WAT_ANCHOR!r}: {exc}"
        ) from exc

    return ResolvedAnchorKey(
        kid=resolved.kid,
        public_key=resolved.public_key,
        validafter=resolved.validafter,
        validuntil=resolved.validuntil,
    )


# ---------------------------------------------------------------------------
# Internal helpers.
# ---------------------------------------------------------------------------


def _ensure_utc(value: datetime) -> datetime:
    """Coerce a ``datetime`` to UTC; tolerate naive datetimes as UTC.

    Mirrors the canonical resolver's :func:`_ensure_utc` semantics so
    that WAT-side ``as_of`` arguments survive the bridge byte-equal
    to a direct canonical-resolver call.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
