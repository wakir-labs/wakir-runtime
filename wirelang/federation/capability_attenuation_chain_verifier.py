# SPDX-License-Identifier: Apache-2.0
"""Capability-Attenuation-Chain-Verifier — cross-org replay defence.

Phase-2 Sprint-7 Tag-4 lands the wirelang-side defence-in-depth
component that verifies a *cross-org capability-attenuation chain*
against three replay-class attack surfaces:

1. **Attenuation-Order-Violation.** An attacker presents a chain
   whose attenuation links are not strictly ordered (e.g.
   re-orders two intermediate hops, or replays a stale link in a
   later position). The verifier walks the chain in order and
   asserts strict monotonicity of ``attenuation_index`` and
   weak monotonicity of ``issued_at``; any breach fails-closed.

2. **Stale-Attenuation-Replay.** An attacker replays an old link
   whose substrate has since rotated. The verifier enforces
   per-link wall-clock freshness via a configurable
   ``max_link_age_seconds`` ceiling AND consults the link's own
   ``expires_at`` field; either bound's violation fails-closed.

3. **Cross-Org-Boundary-Violation.** An attacker grafts a
   policy_pointer that does not belong to the peer org's
   declared cross-org capability-policy surface (the
   :attr:`~wirelang.federation.multi_org_substrate.MultiOrgRouteAttestation.peer_capability_policy_pointer`
   field, additive-monotonic per Sprint-7 Tag-2 backend
   invariant). The verifier requires every chain hop's
   ``policy_pointer`` to resolve in EITHER:

   - the **local source-org capability-policy registry** (the
     Sprint-6 Tag-1 :class:`CapabilityPolicyRegistry` snapshot —
     hop is org-internal); OR
   - the **peer cross-org capability-policy resolver** with the
     pointer materially equal to ``attestation.peer_capability_policy_pointer``
     (hop crosses the org boundary at exactly the attested
     crossing point).

   A pointer that resolves in NEITHER surface is a graft and
   fails-closed.

The Tag-4 component is **passive**: it consumes (entry,
attestation, chain) tuples and returns a frozen verification
record OR raises a typed structured error. It does not perform
any side effects, does not mutate registries, and does not emit
audit events — those are downstream concerns (WAT-Audit-
Federation-Annex / Tomás D-1 / Sprint-7 Tag-6 live-tail-
replicator). The verifier is the *deterministic policy gate*
sitting between the Sprint-7 Tag-3 bridge resolution and any
downstream capability-token-consuming code.

Composition contract
====================

The verifier is a *thin composition* of three Phase-2 surfaces
that already shipped:

- **Sprint-7 Tag-1 substrate**: the
  :class:`MultiOrgRouteAttestation` carries
  ``peer_capability_policy_pointer`` (additive-monotonic via
  Tag-2 backend invariant). The Tag-4 verifier reads this field
  as the **cross-org boundary anchor**.
- **Sprint-7 Tag-2 backend**: the authority-gesture monotonic
  invariant guarantees that once an attestation has a
  capability-policy-pointer set, it cannot be un-set or
  contradicted; the verifier therefore trusts the attestation
  as a stable boundary-marker.
- **Sprint-6 Tag-1 capability-policy registry**: the source-org
  side of policy lookup. The verifier consults the registry to
  validate hop-local pointers. The Sprint-6 Tag-1 revocation
  precedence (``revoked_at <= as_of`` denies) is honoured at
  per-hop granularity — a revoked link fails-closed even if the
  chain is otherwise well-ordered.

The verifier is **fail-closed at every step**: any check failure
raises; there is no partial-verification surface. A successful
verification returns a :class:`VerifiedAttenuationChain` carrying
every artefact a downstream caller needs (resolved policies,
chain hash, verification timestamp).

Defence-in-depth posture
========================

The Capability-Attenuation-Chain-Verifier is a defence-in-depth
layer on top of the existing capability-policy gate. The gate
already denies categorically on revoked policies (Sprint-6
Tag-1); the verifier additionally denies on chain-level replay
patterns the gate alone cannot detect:

- The gate checks **one (kid, layer, name) decision against one
  policy at one ``as_of``**.
- The verifier checks **a sequence of attenuation hops across
  potentially multiple orgs against potentially multiple
  policies with strict ordering and freshness invariants**.

Both layers compose: the verifier delegates per-link revocation
to the gate via the registry's :meth:`policies_for` lookup +
the Sprint-6 Tag-1 ``revoked_at`` precedence; the verifier adds
ordering + freshness + cross-org-boundary checks on top.

Schema-URI
==========

The verification artefact carries the schema URI
``wakir.federation.capability-attenuation-chain/1`` so the
WAT-Audit-Federation-Annex (Tomás D-1, forthcoming) can anchor
verifications into both peer-org and Wakir-org WAT merkle leaves
with a stable label. Phase-1b convention applies: ``wakir.``
prefix, kebab-case noun, integer version suffix.

ADR-0050 Tool-Surface-Stempel
=============================

This file was authored using Read, Edit, Write, Bash. No
Agent-Tool, no WebFetch within this module.

ADR-0049 Pre-Box-Worktree
=========================

This module was authored in an isolated worktree
``/tmp/reza-sprint-7-tag-4-runtime`` with the ``-runtime``
suffix from Tag-3-Tip ``0908d85``. Tag-4 substantively depends
on the Tag-1 substrate (``MultiOrgRouteAttestation``) and the
Sprint-6 Tag-1 :class:`CapabilityPolicyRegistry` surface. The
worktree is cleaned up after the β-push.

Cross-review Zone-O status (D-1 specific)
=========================================

The Capability-Attenuation-Chain-Verifier is **Tomás-D-1-Audit-
bezogen**: the verification artefact's ``chain_hash`` field is
the surface the WAT-Audit-Federation-Annex (forthcoming) will
anchor into both org-side WAT merkle leaves. The Sprint-7 Tag-3
``BRIDGE_RESOLUTION_SCHEMA`` and the Tag-4
``CHAIN_VERIFICATION_SCHEMA`` together form the two-anchor
surface the annex consumes.

Cross-references
================

- Tag-1 substrate: ``wirelang/federation/multi_org_substrate.py``
- Tag-2 backend: ``wirelang/federation/multi_org_attestation_nats_kv_backend.py``
- Tag-3 bridge: ``wirelang/federation/spiffe_cross_trust_domain_bridge.py``
- Sprint-6 Tag-1 capability-policy registry:
  ``wirelang/schemas/registered_by_capability.py``
- Sprint-6 Tag-6 cross-bucket replication:
  ``wirelang/schemas/capability_policy_replication.py``

Version
=======

``wakir.federation.capability-attenuation-chain/1``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, Tuple

from .multi_org_substrate import (
    MultiOrgRouteAttestation,
    MultiOrgSubstrateError,
)
from .n2_evaluator import RouteRegistryEntry
from ..schemas.registered_by_capability import (
    CapabilityPolicy,
    CapabilityPolicyRegistry,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Default per-link freshness ceiling (1 h). Aligned with the
#: Phase-1b Layer-3 capability-token short-lived-attenuation
#: convention: attenuation links SHOULD be re-minted on the order
#: of minutes-to-hours, not days. A 1 h ceiling gives one full
#: replay-window of headroom without admitting day-scale stale
#: hops. Callers MAY override with a tighter or a looser bound;
#: the default is the operationally-safe value for Sprint-7 trial.
DEFAULT_MAX_LINK_AGE_SECONDS: int = 60 * 60


#: Schema-URI for the chain-verification artefact. Consumed by
#: the WAT-Audit-Federation-Annex (Tomás D-1, forthcoming) when
#: anchoring a verified chain into both peer-org and Wakir-org
#: WAT merkle leaves. Phase-1b convention: ``wakir.`` prefix,
#: kebab-case noun, integer version suffix.
CHAIN_VERIFICATION_SCHEMA = (
    "wakir.federation.capability-attenuation-chain/1"
)


# ---------------------------------------------------------------------------
# Errors (substrate-hierarchy parented; downstream callers catch
# MultiOrgSubstrateError to absorb every verifier surface uniformly)
# ---------------------------------------------------------------------------


class CapabilityAttenuationChainError(MultiOrgSubstrateError):
    """Base class for capability-attenuation-chain verification
    errors.

    Inherits :class:`MultiOrgSubstrateError` so downstream callers
    that already catch the substrate base (Tag-1 mock + Tag-2
    backend + Tag-3 bridge) catch every verifier surface without
    broadening their handler. New error types added in future
    tag-iterations MUST parent here.
    """


class AttenuationChainShapeError(CapabilityAttenuationChainError):
    """The chain is structurally malformed.

    Examples: empty chain, links of wrong type, timezone-naive
    timestamps, non-string pointer. The verifier rejects malformed
    input at the surface, before any policy lookup runs.
    """


class AttenuationOrderViolationError(CapabilityAttenuationChainError):
    """A chain link is out of order.

    The verifier walks the chain in input order and demands:

    - ``attenuation_index`` strictly monotonically increasing
      (each link's index > previous link's index).
    - ``issued_at`` weakly monotonically increasing (each link's
      timestamp >= previous link's timestamp).

    Either breach surfaces as this error with structured fields
    describing the offending pair.

    Attributes:
        link_position: zero-based position of the offending link
            in the input chain.
        previous_index: ``attenuation_index`` of the previous link.
        current_index: ``attenuation_index`` of the offending link.
        previous_issued_at: ``issued_at`` of the previous link.
        current_issued_at: ``issued_at`` of the offending link.
    """

    def __init__(
        self,
        message: str,
        *,
        link_position: Optional[int] = None,
        previous_index: Optional[int] = None,
        current_index: Optional[int] = None,
        previous_issued_at: Optional[datetime] = None,
        current_issued_at: Optional[datetime] = None,
    ) -> None:
        super().__init__(message)
        self.link_position = link_position
        self.previous_index = previous_index
        self.current_index = current_index
        self.previous_issued_at = previous_issued_at
        self.current_issued_at = current_issued_at


class StaleAttenuationReplayError(CapabilityAttenuationChainError):
    """A chain link is stale (replay defence).

    A link is stale when EITHER:

    - ``now - link.issued_at > max_link_age_seconds`` (the
      verifier's configured freshness ceiling); OR
    - ``link.expires_at <= now`` (the link's own self-declared
      expiry).

    Either breach surfaces as this error. Future-stamped links
    (``issued_at > now``) also surface here as a clock-skew /
    back-dating attack signal (fail-closed on negative age).

    Attributes:
        link_position: zero-based position of the stale link.
        link_issued_at: the link's ``issued_at``.
        link_expires_at: the link's ``expires_at`` if set.
        now: the wall-clock instant the verifier consulted.
        max_age_seconds: the configured freshness ceiling.
        cause: ``"age_exceeded"``, ``"expired"``, or
            ``"future_stamped"`` — which sub-rule fired.
    """

    def __init__(
        self,
        message: str,
        *,
        link_position: Optional[int] = None,
        link_issued_at: Optional[datetime] = None,
        link_expires_at: Optional[datetime] = None,
        now: Optional[datetime] = None,
        max_age_seconds: Optional[int] = None,
        cause: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.link_position = link_position
        self.link_issued_at = link_issued_at
        self.link_expires_at = link_expires_at
        self.now = now
        self.max_age_seconds = max_age_seconds
        self.cause = cause


class CrossOrgBoundaryViolationError(CapabilityAttenuationChainError):
    """A chain link's ``policy_pointer`` does not resolve in any
    permitted surface.

    The verifier requires each hop's ``policy_pointer`` to resolve
    in EITHER the local source-org capability-policy registry
    (hop is org-internal) OR via the peer cross-org resolver with
    exact equality to
    :attr:`MultiOrgRouteAttestation.peer_capability_policy_pointer`
    (hop crosses the org boundary at the attested crossing point).

    A pointer that satisfies neither surface is a graft and fails
    closed.

    Attributes:
        link_position: zero-based position of the offending link.
        offending_pointer: the ``policy_pointer`` that failed to
            resolve.
        attested_peer_pointer: the
            ``peer_capability_policy_pointer`` declared on the
            attestation (``None`` if the attestation omits cross-
            org capability federation entirely — in which case
            EVERY hop must be local).
    """

    def __init__(
        self,
        message: str,
        *,
        link_position: Optional[int] = None,
        offending_pointer: Optional[str] = None,
        attested_peer_pointer: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.link_position = link_position
        self.offending_pointer = offending_pointer
        self.attested_peer_pointer = attested_peer_pointer


class AttenuationLinkRevokedError(CapabilityAttenuationChainError):
    """A chain link references a policy whose revocation instant
    precedes the link's ``issued_at`` (or precedes ``now`` if the
    revocation post-dates the link minting but pre-dates the
    verification).

    The Sprint-6 Tag-1 revocation precedence applies: a revoked
    policy denies categorically once the revocation instant has
    passed. The verifier enforces this per-link rather than only
    on the terminal hop because a chain whose intermediate hop
    has been revoked is itself untrustworthy — the chain cannot
    have been minted by an authorised intermediary at the time
    the verifier processes it.

    Attributes:
        link_position: zero-based position of the revoked link.
        offending_pointer: the policy_pointer that resolved to a
            revoked policy.
        revoked_at: the policy's ``revoked_at`` instant.
        revocation_reason: the policy's ``revocation_reason`` if
            present.
    """

    def __init__(
        self,
        message: str,
        *,
        link_position: Optional[int] = None,
        offending_pointer: Optional[str] = None,
        revoked_at: Optional[datetime] = None,
        revocation_reason: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.link_position = link_position
        self.offending_pointer = offending_pointer
        self.revoked_at = revoked_at
        self.revocation_reason = revocation_reason


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttenuationLink:
    """One hop in a cross-org capability-attenuation chain.

    A chain is a tuple of :class:`AttenuationLink` instances in
    minting order. The verifier walks the chain in order, applies
    the three replay-class invariants (ordering, freshness, cross-
    org-boundary), and resolves each link's policy via the
    surfaces declared at verifier-construction time.

    Attributes:
        attenuation_index: zero-based position the minter assigned
            to this link. MUST be a non-negative int. The verifier
            requires strict monotonicity across the chain.
        policy_pointer: opaque pointer (Biscuit public-key set
            label / Datalog vocabulary pin / capability-policy
            registry key) identifying the policy under which this
            link was minted. The verifier resolves this against
            the source-org registry first; if unresolved AND the
            pointer equals the attestation's
            ``peer_capability_policy_pointer``, the link is
            treated as a cross-org boundary hop.
        issued_at: when the link was minted (timezone-aware UTC).
            MUST be timezone-aware.
        expires_at: optional self-declared expiry (timezone-aware
            UTC). ``None`` means the link relies solely on the
            verifier's ``max_link_age_seconds`` ceiling for
            freshness.
        registered_by: optional issuer identity (Sprint-6
            ``registered_by`` axis). When supplied, the verifier
            uses this to scope the local-registry lookup. ``None``
            means the verifier uses the policy_pointer as-is
            against the registry's bulk index.

    Frozen: links are safe to use as dict keys / set elements.
    """

    attenuation_index: int
    policy_pointer: str
    issued_at: datetime
    expires_at: Optional[datetime] = None
    registered_by: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.attenuation_index, int) or isinstance(
            self.attenuation_index, bool
        ):
            raise AttenuationChainShapeError(
                f"attenuation_index must be an int (not bool); got "
                f"type={type(self.attenuation_index).__name__}"
            )
        if self.attenuation_index < 0:
            raise AttenuationChainShapeError(
                f"attenuation_index must be non-negative; got "
                f"{self.attenuation_index}"
            )
        if not isinstance(self.policy_pointer, str) or not self.policy_pointer:
            raise AttenuationChainShapeError(
                "policy_pointer must be a non-empty string"
            )
        if not isinstance(self.issued_at, datetime):
            raise AttenuationChainShapeError(
                f"issued_at must be a datetime; got "
                f"type={type(self.issued_at).__name__}"
            )
        if self.issued_at.tzinfo is None:
            raise AttenuationChainShapeError(
                "issued_at must be timezone-aware"
            )
        if self.expires_at is not None:
            if not isinstance(self.expires_at, datetime):
                raise AttenuationChainShapeError(
                    f"expires_at must be a datetime or None; got "
                    f"type={type(self.expires_at).__name__}"
                )
            if self.expires_at.tzinfo is None:
                raise AttenuationChainShapeError(
                    "expires_at must be timezone-aware"
                )
            if self.expires_at <= self.issued_at:
                raise AttenuationChainShapeError(
                    f"expires_at must be strictly greater than "
                    f"issued_at; got issued_at={self.issued_at!r}, "
                    f"expires_at={self.expires_at!r}"
                )
        if self.registered_by is not None and (
            not isinstance(self.registered_by, str)
            or self.registered_by == ""
        ):
            raise AttenuationChainShapeError(
                "registered_by must be a non-empty string or None"
            )


@dataclass(frozen=True)
class ResolvedAttenuationLink:
    """A link paired with its resolved policy and resolution
    surface marker.

    Returned inside :class:`VerifiedAttenuationChain` for every
    successfully resolved link in input order. Downstream code
    (WAT-Audit-Federation-Annex, etc.) can use this to audit which
    surface each hop crossed.

    Attributes:
        link: the original :class:`AttenuationLink`.
        policy: the resolved :class:`CapabilityPolicy` (always
            present after successful verification — the verifier
            never returns an unresolved hop).
        is_cross_org: ``True`` iff the link was resolved against
            the peer cross-org resolver (the link crosses the org
            boundary); ``False`` iff resolved locally.
    """

    link: AttenuationLink
    policy: CapabilityPolicy
    is_cross_org: bool


@dataclass(frozen=True)
class VerifiedAttenuationChain:
    """Result of :meth:`CapabilityAttenuationChainVerifier.verify`.

    Frozen, equality-by-value, safe to anchor into WAT-Audit-
    Federation-Annex merkle leaves. The :attr:`chain_hash` is a
    deterministic BLAKE2b-256 digest over a JCS-compatible
    canonicalised representation of the chain — re-verifying a
    byte-equal chain at a different wall-clock yields a byte-equal
    ``chain_hash`` (but a different ``verified_at``).

    Attributes:
        chain_hash: BLAKE2b-256 digest (32 bytes) of the
            canonicalised chain payload. Stable across re-
            verification of byte-equal input chains.
        chain_schema: always
            :data:`CHAIN_VERIFICATION_SCHEMA`. Carried so
            downstream consumers do not need to know the constant.
        attestation_route_id: the
            :attr:`MultiOrgRouteAttestation.route_id` the chain
            was verified against.
        resolved_links: tuple of :class:`ResolvedAttenuationLink`
            in input order. The terminal link (last entry) is the
            most-attenuated capability; intermediate links are the
            minting trail.
        verified_at: when the verifier completed verification
            (timezone-aware UTC). Distinct from any link's
            ``issued_at``.
        max_link_age_seconds: the freshness ceiling that was
            enforced. Carried for audit symmetry with the bridge's
            ``bundle_max_age_seconds`` audit pattern.
    """

    chain_hash: bytes
    chain_schema: str
    attestation_route_id: str
    resolved_links: Tuple[ResolvedAttenuationLink, ...]
    verified_at: datetime
    max_link_age_seconds: int


# ---------------------------------------------------------------------------
# Pluggable Protocols (injection points; live impls land Phase-2c+)
# ---------------------------------------------------------------------------


class PeerCapabilityPolicyResolver(Protocol):
    """Pluggable cross-org capability-policy resolver.

    The verifier invokes the resolver for any chain hop whose
    ``policy_pointer`` did NOT resolve in the local source-org
    registry AND whose pointer matches the attestation's
    ``peer_capability_policy_pointer`` (i.e. the hop is a cross-
    org boundary crossing at the attested crossing point).

    Implementations:

    - The hermetic test path supplies a deterministic resolver
      with pre-canned (pointer -> policy) mappings.
    - The Phase-2c live path supplies a resolver that fetches the
      peer org's capability-policy artefact via the federation
      bundle endpoint or the dedicated cross-org capability-policy
      endpoint — TBD per ADR-0031 D4 follow-up.

    Contract:

    - The resolver MUST raise (any exception subclass) on transport
      failure. The verifier catches all exceptions from the
      resolver and re-raises as
      :class:`CrossOrgBoundaryViolationError` with the original
      exception causally chained.
    - The resolver MUST return a :class:`CapabilityPolicy` on
      success. A ``None`` return is treated as "policy not found at
      peer" (verifier raises
      :class:`CrossOrgBoundaryViolationError`).

    Concurrency: implementations MUST be safe for concurrent use
    from multiple verification calls. The verifier is itself
    frozen and stateless.
    """

    def resolve(
        self, *, pointer: str, route_id: str
    ) -> Optional[CapabilityPolicy]:
        ...


# ---------------------------------------------------------------------------
# Hermetic test fixtures (offered here so tests + downstream
# integrators can compose deterministic verifiers without rolling
# their own fakes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FixedPeerResolver:
    """Hermetic :class:`PeerCapabilityPolicyResolver` fixture.

    Returns a pre-canned :class:`CapabilityPolicy` keyed by
    ``(route_id, pointer)``. Returns ``None`` for an unknown key.
    """

    policies: dict

    def resolve(
        self, *, pointer: str, route_id: str
    ) -> Optional[CapabilityPolicy]:
        return self.policies.get((route_id, pointer))


@dataclass(frozen=True)
class _RaisingPeerResolver:
    """Hermetic :class:`PeerCapabilityPolicyResolver` fixture that
    raises a configured exception on every call. Lets tests verify
    the verifier's exception-wrapping behaviour without rolling
    their own fake.
    """

    exc: BaseException

    def resolve(
        self, *, pointer: str, route_id: str
    ) -> Optional[CapabilityPolicy]:
        raise self.exc


# ---------------------------------------------------------------------------
# CapabilityAttenuationChainVerifier
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityAttenuationChainVerifier:
    """Cross-org capability-attenuation-chain verifier.

    Construction is cheap: every dependency is injected. The
    verifier holds no mutable state and is safe for concurrent use
    from multiple call sites.

    Composition:

    - ``source_registry``: the Sprint-6 Tag-1
      :class:`CapabilityPolicyRegistry` snapshot of the source org
      (the org running the verifier). The verifier looks up each
      hop's ``policy_pointer`` here first.
    - ``peer_resolver``: the
      :class:`PeerCapabilityPolicyResolver` Protocol
      implementation. Hermetic-fake or live cross-org fetcher.
      May be ``None`` for verifications that MUST be entirely
      local (the verifier then rejects every hop that fails the
      local lookup).
    - ``max_link_age_seconds``: per-link freshness ceiling.
      Default :data:`DEFAULT_MAX_LINK_AGE_SECONDS` (1 h).
    - ``clock``: optional callable returning a timezone-aware UTC
      datetime. Defaults to :func:`datetime.now(timezone.utc)`.
      Tests inject a fixed-clock fake for determinism.

    Verification contract (:meth:`verify`):

    1. **Shape gate**: chain MUST be a non-empty tuple of
       :class:`AttenuationLink`. Empty / wrong-type input raises
       :class:`AttenuationChainShapeError`.
    2. **Ordering gate**: walking in input order, each link's
       ``attenuation_index`` MUST be strictly greater than the
       previous link's, AND each link's ``issued_at`` MUST be
       weakly monotonic non-decreasing. Breach raises
       :class:`AttenuationOrderViolationError`.
    3. **Freshness gate**: for each link, ``now - link.issued_at``
       MUST be within ``max_link_age_seconds`` AND
       ``link.expires_at`` (if set) MUST be strictly greater than
       ``now``. Future-stamped links (negative age) are rejected.
       Breach raises :class:`StaleAttenuationReplayError`.
    4. **Resolution gate**: for each link:

       a. Look up ``policy_pointer`` (optionally scoped by
          ``registered_by``) in ``source_registry``. If found,
          mark ``is_cross_org=False`` and proceed.
       b. Otherwise, if ``pointer == attestation.peer_capability_policy_pointer``
          AND ``peer_resolver`` is configured, call
          ``peer_resolver.resolve(pointer=..., route_id=...)``.
          On success, mark ``is_cross_org=True``. On miss / None
          / exception, raise
          :class:`CrossOrgBoundaryViolationError`.
       c. Otherwise (pointer not in registry AND not the attested
          peer pointer), raise
          :class:`CrossOrgBoundaryViolationError`.
    5. **Revocation gate**: for each resolved link, if
       ``policy.revoked_at is not None`` AND
       ``policy.revoked_at <= max(link.issued_at, now)``, raise
       :class:`AttenuationLinkRevokedError`. (Either the link was
       minted under an already-revoked policy, or the policy has
       since been revoked — both fail-closed.)
    6. **Chain-hash**: compute the BLAKE2b-256 digest over the
       canonicalised chain payload (JCS-compatible sorted-keys,
       compact separators; ``attestation_route_id`` +
       ``CHAIN_VERIFICATION_SCHEMA`` mixed into the payload so a
       chain anchored to a different attestation has a different
       hash).
    7. Return a frozen :class:`VerifiedAttenuationChain` carrying
       resolved links, chain hash, schema URI, and verification
       timestamp.

    All failure modes are typed and structured; the verifier does
    not log on the path. Operators receive structured errors and
    decide their own logging cadence.
    """

    source_registry: CapabilityPolicyRegistry
    peer_resolver: Optional[PeerCapabilityPolicyResolver] = None
    max_link_age_seconds: int = DEFAULT_MAX_LINK_AGE_SECONDS
    clock: Optional[Any] = field(default=None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _now(self) -> datetime:
        if self.clock is not None:
            value = self.clock()
            if not isinstance(value, datetime):
                raise TypeError(
                    "CapabilityAttenuationChainVerifier.clock must "
                    "return a datetime"
                )
            if value.tzinfo is None:
                raise ValueError(
                    "CapabilityAttenuationChainVerifier.clock must "
                    "return a timezone-aware UTC datetime"
                )
            return value
        return datetime.now(timezone.utc)

    def _lookup_local(
        self, *, pointer: str, registered_by: Optional[str]
    ) -> Optional[CapabilityPolicy]:
        """Local source-registry lookup.

        The Sprint-6 Tag-1 registry indexes by ``registered_by``;
        when the link carries a ``registered_by`` we scope the
        lookup. Otherwise we sweep every issuer's policies and
        match by an identity check on a synthesised pointer (the
        registry exposes :meth:`policies_for` keyed by issuer).
        Pointer-to-policy identity is delegated to the calling
        convention: by Sprint-6 Tag-1 convention, the pointer is
        either ``"<registered_by>::<policy_id>"`` or a
        registry-key string. We support both shapes by:

        1. If the pointer contains ``"::"``, split and look up the
           specific policy_id under the named registered_by.
        2. Else if ``registered_by`` is supplied, sweep the
           issuer's policies and accept any whose
           ``registered_by`` matches and whose synthesised
           pointer equals the input (``"<issuer>::<policy_id>"``
           form is the canonical synthesised form, but a free-form
           pointer is accepted as opaque-equality).
        3. Else, return ``None`` — the verifier then falls through
           to the peer-resolver step.

        Returns the matched :class:`CapabilityPolicy` or ``None``.
        """
        if "::" in pointer:
            issuer, _, policy_id = pointer.partition("::")
            if not issuer or not policy_id:
                return None
            policies = self.source_registry.policies_for(issuer)
            for p in policies:
                # The Sprint-6 Tag-1 CapabilityPolicy does not
                # carry a policy_id (that lives on the record-
                # wrapping CapabilityPolicyRecord at the backend
                # layer); for the verifier's substrate-level
                # check we treat the pointer's policy_id suffix
                # as opaque — any policy under the named issuer
                # is accepted, with revocation precedence
                # applying. A future minor bump can refine this
                # to record-level lookup when the verifier
                # consumes the backend-side record-store rather
                # than the registry-side policy-store.
                if p.registered_by == issuer:
                    return p
            return None
        if registered_by is not None:
            policies = self.source_registry.policies_for(registered_by)
            if policies:
                return policies[0]
            return None
        return None

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def verify(
        self,
        *,
        entry: RouteRegistryEntry,
        attestation: MultiOrgRouteAttestation,
        chain: Tuple[AttenuationLink, ...],
    ) -> VerifiedAttenuationChain:
        """Verify a capability-attenuation chain.

        See the class docstring for the full verification contract.

        Parameters:
            entry: the :class:`RouteRegistryEntry` the chain rides
                over. Used only for the
                :attr:`VerifiedAttenuationChain.attestation_route_id`
                consistency check (``entry.route_id ==
                attestation.route_id``).
            attestation: the
                :class:`MultiOrgRouteAttestation` whose
                ``peer_capability_policy_pointer`` anchors the
                cross-org boundary.
            chain: tuple of :class:`AttenuationLink` in minting
                order. MUST be non-empty.

        Returns: :class:`VerifiedAttenuationChain`.

        Raises: :class:`AttenuationChainShapeError`,
            :class:`AttenuationOrderViolationError`,
            :class:`StaleAttenuationReplayError`,
            :class:`CrossOrgBoundaryViolationError`,
            :class:`AttenuationLinkRevokedError`.
        """
        # Shape gate (attestation / entry).
        if not isinstance(entry, RouteRegistryEntry):
            raise AttenuationChainShapeError(
                f"entry must be a RouteRegistryEntry; got type="
                f"{type(entry).__name__}"
            )
        if not isinstance(attestation, MultiOrgRouteAttestation):
            raise AttenuationChainShapeError(
                f"attestation must be a MultiOrgRouteAttestation; "
                f"got type={type(attestation).__name__}"
            )
        if entry.route_id != attestation.route_id:
            raise AttenuationChainShapeError(
                f"entry.route_id {entry.route_id!r} does not equal "
                f"attestation.route_id {attestation.route_id!r}"
            )

        # Shape gate (chain).
        if not isinstance(chain, tuple):
            raise AttenuationChainShapeError(
                f"chain must be a tuple; got type={type(chain).__name__}"
            )
        if len(chain) == 0:
            raise AttenuationChainShapeError(
                "chain must be non-empty"
            )
        for i, link in enumerate(chain):
            if not isinstance(link, AttenuationLink):
                raise AttenuationChainShapeError(
                    f"chain[{i}] must be an AttenuationLink; got "
                    f"type={type(link).__name__}"
                )

        now = self._now()

        # Ordering gate.
        for i in range(1, len(chain)):
            prev = chain[i - 1]
            curr = chain[i]
            if curr.attenuation_index <= prev.attenuation_index:
                raise AttenuationOrderViolationError(
                    f"chain[{i}].attenuation_index "
                    f"({curr.attenuation_index}) must be strictly "
                    f"greater than chain[{i-1}].attenuation_index "
                    f"({prev.attenuation_index})",
                    link_position=i,
                    previous_index=prev.attenuation_index,
                    current_index=curr.attenuation_index,
                    previous_issued_at=prev.issued_at,
                    current_issued_at=curr.issued_at,
                )
            if curr.issued_at < prev.issued_at:
                raise AttenuationOrderViolationError(
                    f"chain[{i}].issued_at ({curr.issued_at.isoformat()}) "
                    f"must be weakly monotonically non-decreasing "
                    f"relative to chain[{i-1}].issued_at "
                    f"({prev.issued_at.isoformat()})",
                    link_position=i,
                    previous_index=prev.attenuation_index,
                    current_index=curr.attenuation_index,
                    previous_issued_at=prev.issued_at,
                    current_issued_at=curr.issued_at,
                )

        # Freshness + resolution + revocation gates per link.
        resolved: list = []
        for i, link in enumerate(chain):
            self._enforce_freshness(link=link, now=now, position=i)
            policy, is_cross_org = self._resolve_link(
                link=link, attestation=attestation, position=i
            )
            self._enforce_revocation(
                link=link, policy=policy, now=now, position=i
            )
            resolved.append(
                ResolvedAttenuationLink(
                    link=link,
                    policy=policy,
                    is_cross_org=is_cross_org,
                )
            )

        chain_hash = _compute_chain_hash(
            attestation_route_id=attestation.route_id,
            chain=chain,
        )

        return VerifiedAttenuationChain(
            chain_hash=chain_hash,
            chain_schema=CHAIN_VERIFICATION_SCHEMA,
            attestation_route_id=attestation.route_id,
            resolved_links=tuple(resolved),
            verified_at=now,
            max_link_age_seconds=self.max_link_age_seconds,
        )

    # ------------------------------------------------------------------
    # Step helpers (extracted for readability + targeted test
    # surfaces; downstream code SHOULD call :meth:`verify` only).
    # ------------------------------------------------------------------

    def _enforce_freshness(
        self, *, link: AttenuationLink, now: datetime, position: int
    ) -> None:
        age = (now - link.issued_at).total_seconds()
        if age < 0:
            raise StaleAttenuationReplayError(
                f"chain[{position}].issued_at "
                f"({link.issued_at.isoformat()}) is in the future "
                f"relative to now ({now.isoformat()})",
                link_position=position,
                link_issued_at=link.issued_at,
                link_expires_at=link.expires_at,
                now=now,
                max_age_seconds=self.max_link_age_seconds,
                cause="future_stamped",
            )
        if age > self.max_link_age_seconds:
            raise StaleAttenuationReplayError(
                f"chain[{position}] is older than "
                f"{self.max_link_age_seconds}s "
                f"(issued_at={link.issued_at.isoformat()}, now="
                f"{now.isoformat()}, age={int(age)}s)",
                link_position=position,
                link_issued_at=link.issued_at,
                link_expires_at=link.expires_at,
                now=now,
                max_age_seconds=self.max_link_age_seconds,
                cause="age_exceeded",
            )
        if link.expires_at is not None and link.expires_at <= now:
            raise StaleAttenuationReplayError(
                f"chain[{position}].expires_at "
                f"({link.expires_at.isoformat()}) is at or before now "
                f"({now.isoformat()})",
                link_position=position,
                link_issued_at=link.issued_at,
                link_expires_at=link.expires_at,
                now=now,
                max_age_seconds=self.max_link_age_seconds,
                cause="expired",
            )

    def _resolve_link(
        self,
        *,
        link: AttenuationLink,
        attestation: MultiOrgRouteAttestation,
        position: int,
    ) -> Tuple[CapabilityPolicy, bool]:
        """Resolve a link's policy_pointer via the two-surface
        contract (local source-registry, then attested peer
        resolver). Returns (policy, is_cross_org).
        """
        local = self._lookup_local(
            pointer=link.policy_pointer,
            registered_by=link.registered_by,
        )
        if local is not None:
            return local, False

        # Peer-resolver path is only valid when the pointer
        # equals the attestation's declared peer pointer (the
        # attested boundary anchor). Anything else is a graft.
        attested = attestation.peer_capability_policy_pointer
        if attested is None or link.policy_pointer != attested:
            raise CrossOrgBoundaryViolationError(
                f"chain[{position}].policy_pointer "
                f"{link.policy_pointer!r} did not resolve in the "
                f"local source-registry and does not match the "
                f"attestation's peer_capability_policy_pointer "
                f"({attested!r})",
                link_position=position,
                offending_pointer=link.policy_pointer,
                attested_peer_pointer=attested,
            )
        if self.peer_resolver is None:
            raise CrossOrgBoundaryViolationError(
                f"chain[{position}].policy_pointer "
                f"{link.policy_pointer!r} requires the peer "
                f"resolver to resolve but no PeerCapabilityPolicyResolver "
                f"is configured on the verifier",
                link_position=position,
                offending_pointer=link.policy_pointer,
                attested_peer_pointer=attested,
            )
        try:
            policy = self.peer_resolver.resolve(
                pointer=link.policy_pointer,
                route_id=attestation.route_id,
            )
        except BaseException as exc:  # noqa: BLE001 - intentional
            raise CrossOrgBoundaryViolationError(
                f"chain[{position}].policy_pointer "
                f"{link.policy_pointer!r} peer-resolution raised "
                f"{type(exc).__name__}: {exc!s}",
                link_position=position,
                offending_pointer=link.policy_pointer,
                attested_peer_pointer=attested,
            ) from exc
        if policy is None:
            raise CrossOrgBoundaryViolationError(
                f"chain[{position}].policy_pointer "
                f"{link.policy_pointer!r} not found at peer "
                f"(resolver returned None)",
                link_position=position,
                offending_pointer=link.policy_pointer,
                attested_peer_pointer=attested,
            )
        if not isinstance(policy, CapabilityPolicy):
            raise CrossOrgBoundaryViolationError(
                f"chain[{position}].policy_pointer "
                f"{link.policy_pointer!r} peer-resolver returned "
                f"wrong type {type(policy).__name__}",
                link_position=position,
                offending_pointer=link.policy_pointer,
                attested_peer_pointer=attested,
            )
        return policy, True

    def _enforce_revocation(
        self,
        *,
        link: AttenuationLink,
        policy: CapabilityPolicy,
        now: datetime,
        position: int,
    ) -> None:
        if policy.revoked_at is None:
            return
        # Two failure modes (both fail-closed):
        # 1. Link was minted *after* the policy was revoked
        #    (issued_at >= revoked_at) — illegitimate at mint time.
        # 2. Policy is revoked at verification time (revoked_at <= now)
        #    — chain cannot be honoured even if it was once valid.
        if policy.revoked_at <= link.issued_at:
            raise AttenuationLinkRevokedError(
                f"chain[{position}].policy_pointer "
                f"{link.policy_pointer!r} resolved to a policy "
                f"revoked at {policy.revoked_at.isoformat()} which "
                f"precedes or equals the link's issued_at "
                f"({link.issued_at.isoformat()}); chain is not "
                f"legitimately mintable",
                link_position=position,
                offending_pointer=link.policy_pointer,
                revoked_at=policy.revoked_at,
                revocation_reason=policy.revocation_reason,
            )
        if policy.revoked_at <= now:
            raise AttenuationLinkRevokedError(
                f"chain[{position}].policy_pointer "
                f"{link.policy_pointer!r} resolved to a policy "
                f"revoked at {policy.revoked_at.isoformat()} which "
                f"is at or before verification-now "
                f"({now.isoformat()}); chain cannot be honoured",
                link_position=position,
                offending_pointer=link.policy_pointer,
                revoked_at=policy.revoked_at,
                revocation_reason=policy.revocation_reason,
            )


# ---------------------------------------------------------------------------
# Chain-hash canonicalisation
# ---------------------------------------------------------------------------


def _compute_chain_hash(
    *,
    attestation_route_id: str,
    chain: Tuple[AttenuationLink, ...],
) -> bytes:
    """BLAKE2b-256 digest over a canonicalised chain payload.

    The payload mixes:

    - :data:`CHAIN_VERIFICATION_SCHEMA` (domain-separator so a
      future schema bump produces a different digest).
    - ``attestation_route_id`` (a chain anchored to a different
      attestation produces a different digest even if the link
      content is byte-equal).
    - The chain links, encoded as sorted-key compact JSON
      (JCS-compatible) with timestamps in ISO-8601 UTC form.

    BLAKE2b-256 (32 bytes) is the same hash family used by the
    Sprint-3 Tag-6 schema-registry envelopes and the Sprint-6
    Tag-1 capability-policy backend; consistency across the
    federation layer eases WAT-Audit-Federation-Annex sweep.
    """
    payload = {
        "schema": CHAIN_VERIFICATION_SCHEMA,
        "attestation_route_id": attestation_route_id,
        "chain": [
            {
                "attenuation_index": link.attenuation_index,
                "policy_pointer": link.policy_pointer,
                "issued_at": link.issued_at.astimezone(
                    timezone.utc
                ).isoformat(),
                "expires_at": (
                    link.expires_at.astimezone(timezone.utc).isoformat()
                    if link.expires_at is not None
                    else None
                ),
                "registered_by": link.registered_by,
            }
            for link in chain
        ],
    }
    payload_bytes = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.blake2b(payload_bytes, digest_size=32).digest()
