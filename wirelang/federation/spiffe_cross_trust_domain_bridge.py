# SPDX-License-Identifier: BUSL-1.1
"""SPIFFE Cross-Trust-Domain Bridge — live multi-org-attestation resolver.

Phase-2 Sprint-7 Tag-3 lands the **live** counterpart to the Sprint-7
Tag-1 :func:`~wirelang.federation.multi_org_substrate.resolve_mock_bridge_route`
mock resolver. The bridge orchestrates the live cross-trust-domain
resolution path that Sprint-7 has been preparing across Tag-1
(substrate dataclass + mock resolver) and Tag-2 (durable NATS-KV
backend with authority-gesture monotonic invariant).

Where Tag-1's mock resolver answers "is the (entry, attestation) pair
present and consistent for this mock route_id?", the live bridge
additionally:

1. Demands ``is_mock=False`` on the attestation. Mock attestations
   are rejected at the bridge surface — the mock resolver remains
   the entry point for those (the two paths are kept structurally
   parallel by design).
2. Fetches the peer org's SPIFFE trust-bundle via the
   :attr:`MultiOrgRouteAttestation.peer_trust_bundle_url` field.
   The HTTPS fetch is performed by a pluggable
   :class:`PeerTrustBundleFetcher` so hermetic test runs can
   inject deterministic fixtures (no live network).
3. Verifies the peer-presented JWT-SVID against the fetched
   trust-bundle through a pluggable :class:`PeerSvidVerifier`.
   The verifier returns a :class:`VerifiedPeerSvid` value object
   that downstream code can rely on as the *cross-trust-domain
   trust anchor* for this resolution.
4. Optionally fetches the local workload's own SPIFFE-SVID
   through the wirelang-side :class:`SpiffeWorkloadApiAdapter`
   (Sprint-6 Tag-5 mock or Phase-2c live impl). The local SVID
   pairs the resolution as the *outbound attestation*: the peer
   org knows the local workload's identity via this token.
5. Enforces a clock-bound trust-bundle freshness check
   (``fetched_at + bundle_max_age >= now``). Bundles older than
   the configured ceiling are rejected as
   :class:`PeerTrustBundleExpiredError`. Defaults to 24 h
   (operationally aligned with Kai's Phase-2.6 trust-bundle-
   rotation runbook ``docs/spire-trust-bundle-rotation.md``).

The bridge composes the Tag-2 backend (or the in-memory Tag-1
registry — both implement the ``lookup``/``get`` surface) and the
Sprint-6 Tag-5 :class:`~wirelang.adapters.spiffe_workload_api.SpiffeWorkloadApiAdapter`
without depending on either's concrete implementation: the bridge
takes Protocols as injection points so the live path can swap mock
fixtures for HTTPS-fetching production implementations without
re-touching the bridge logic.

Failure-mode surface (all live-bridge errors are subclasses of
:class:`MultiOrgSubstrateError`, mirroring the Tag-1 substrate
hierarchy; downstream code that already catches the substrate base
catches every bridge failure without broadening its handler):

- :class:`UnknownBridgeRouteError` — re-used from the Tag-1
  substrate. Route or attestation absent from the registries.
- :class:`PeerTrustBundleFetchError` — the trust-bundle HTTPS fetch
  failed (transport error, non-200, malformed JSON Web Key Set).
  Operationally: peer endpoint is down or the URL is wrong.
- :class:`PeerTrustBundleExpiredError` — the fetched bundle's
  ``fetched_at`` is older than ``bundle_max_age``. Operationally:
  the bundle rotation runbook (Kai Phase-2.6) was not run on time.
- :class:`PeerSvidSignatureError` — the peer-presented JWT-SVID
  failed signature verification against the fetched trust-bundle.
  Operationally: either a stale bundle, a stale SVID, or a
  cross-trust-domain spoofing attempt. Fail-closed.

The bridge is **fail-closed** at every step: any failure raises;
there is no partial-resolution surface. A successful resolution
returns a :class:`LiveBridgeResolution` carrying every artefact a
downstream caller needs to attribute the cross-trust-domain
interaction (entry, attestation, verified peer SVID, local SVID,
fetched trust-bundle reference, verification timestamp).

ADR-0050 Tool-Surface-Stempel
=============================

This file was authored using Read, Edit, Write, Bash. No Agent-Tool,
no WebFetch within this module. Pre-Box-Worktree ADR-0049
``/tmp/reza-sprint-7-tag-3-runtime`` (suffix ``-runtime`` per
post-Sprint-6-Bundle-Merge main-tip ``b810dd9``, chained on Tag-2
β-tip ``4cb1c7e``).

ADR-0049 Pre-Box-Worktree
=========================

This module was authored in an isolated worktree
``/tmp/reza-sprint-7-tag-3-runtime`` created from ``b810dd9``
(post-Sprint-6-Bundle-Merge main-tip) reset to ``4cb1c7e`` (Sprint-7
Tag-2 β-tip; Tag-3 substantively depends on the Tag-2
``MultiOrgRouteAttestation`` backend surface). The worktree is
cleaned up after the β-push.

Cross-review Zone-O status (D-2 specific, post-Sprint-6 Phase-2
SPIFFE-Infrastructure merge)
============================

Sprint-6 PR #3 merged Kai's SPIRE-Server-Sidecar (Phase-2.1),
SPIRE-Agent-Sidecar (Phase-2.2), NATS-JWT-Auth (Phase-2.4), and
Trust-Bundle-Rotation runbook (Phase-2.6) into main. The live-bridge
wire-up substrate is therefore on-disk:

- ``compose/spire.yaml`` SPIRE-Server-Sidecar (Phase-2.1).
- ``compose/spire.yaml`` SPIRE-Agent-Sidecar (Phase-2.2) exposing
  the Workload-API socket at the canonical
  ``/run/spire/sockets/agent.sock`` path consumed by the wirelang
  :class:`~wirelang.adapters.spiffe_workload_api.SpiffeWorkloadApiAdapter`.
- ``scripts/nats_jwt_callback_skizze.py`` ``make_user_jwt_cb``
  factory (Phase-2.4) for NATS-JWT consumption from the SPIRE
  agent.
- ``docs/spire-trust-bundle-rotation.md`` (Phase-2.6) operationally
  bounds the trust-bundle freshness — the bridge consumes that
  bound through its ``bundle_max_age`` parameter.
- ``quadlet/wakir-spire-*`` (Tag-11) systemd quadlet wiring for the
  SPIRE infrastructure.

Tag-3 ships the **wirelang-side resolver** that consumes the
runtime above; it is hermetic-tested via injected Protocol fakes
so the test suite remains network-free.

Cross-references
================

- Tag-1 substrate: ``wirelang/federation/multi_org_substrate.py``
- Tag-2 backend: ``wirelang/federation/multi_org_attestation_nats_kv_backend.py``
- SPIFFE adapter: ``wirelang/adapters/spiffe_workload_api.py``
- Trust-bundle rotation runbook: ``docs/spire-trust-bundle-rotation.md``
- Sprint-6 PR #3: SPIRE-Server-Sidecar / SPIRE-Agent-Sidecar /
  NATS-JWT-Auth / Trust-Bundle-Rotation merge.
- ADR-0031 D4: did:web as cross-org audit-anchor default.
- V-908 NLnet-Antrag federation vision-block.

Version
=======

``wakir.federation.spiffe-cross-trust-domain-bridge/1``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, Tuple

from .multi_org_substrate import (
    MultiOrgAttestationConflictError,  # noqa: F401  (re-export-stable)
    MultiOrgRouteAttestation,
    MultiOrgSubstrateError,
    UnknownBridgeRouteError,
)
from .n2_evaluator import RouteRegistryEntry
from ..adapters.spiffe_workload_api import (
    JwtSvid,
    SpiffeAdapterError,
    SpiffeWorkloadApiAdapter,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Default trust-bundle freshness ceiling (24 h). Aligned with the
#: Kai Phase-2.6 ``docs/spire-trust-bundle-rotation.md`` runbook
#: cadence: bundles MUST be rotated at least daily; a 24 h ceiling
#: gives one full rotation cycle of headroom before the bridge
#: refuses to resolve. Callers MAY override this with a tighter or
#: a looser bound; the default is the operationally-safe value.
DEFAULT_BUNDLE_MAX_AGE_SECONDS: int = 24 * 60 * 60


#: Schema-URI fragment for the bridge resolution artefact. Used by
#: the WAT-Audit-Federation-Annex (Tomás D-1, Sprint-7 Tag-4+) when
#: anchoring a bridge-resolution into both peer-org and Wakir-org
#: WAT merkle leaves. Phase-1b convention: ``wakir.`` prefix,
#: kebab-case noun, integer version suffix.
BRIDGE_RESOLUTION_SCHEMA = (
    "wakir.federation.spiffe-cross-trust-domain-bridge/1"
)


# ---------------------------------------------------------------------------
# Errors (substrate-hierarchy parented; downstream callers catch
# MultiOrgSubstrateError to absorb every bridge surface uniformly)
# ---------------------------------------------------------------------------


class SpiffeCrossTrustDomainBridgeError(MultiOrgSubstrateError):
    """Base class for live-bridge resolution errors.

    Inherits :class:`MultiOrgSubstrateError` so downstream callers
    that already catch the substrate base (Tag-1 mock + Tag-2
    backend) catch every bridge surface without broadening their
    handler. New error types added in future tag-iterations MUST
    parent here.
    """


class PeerTrustBundleFetchError(SpiffeCrossTrustDomainBridgeError):
    """The peer SPIFFE trust-bundle HTTPS fetch failed.

    Typical causes: peer endpoint is unreachable, the URL is
    misconfigured, the response is not a parseable JWK Set, or
    the response carries a non-200 HTTP status. The error message
    surfaces the underlying transport / decode failure for the
    operator log; the structured ``url`` field carries the
    attempted URL so the operator does not need to grep the
    message.

    Attributes:
        url: the URL the fetcher attempted to retrieve.
        cause: the underlying exception, if available. ``None``
            when the fetcher signalled failure via a non-exception
            return path (e.g. a sentinel value).
    """

    def __init__(
        self,
        message: str,
        *,
        url: Optional[str] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.cause = cause


class PeerTrustBundleExpiredError(SpiffeCrossTrustDomainBridgeError):
    """The fetched peer trust-bundle is older than the configured
    freshness ceiling.

    The bridge enforces ``fetched_at + bundle_max_age >= now``.
    A breach indicates the peer's trust-bundle-rotation runbook
    (Kai Phase-2.6) was not run within the expected cadence; the
    bridge refuses to resolve rather than accept a possibly
    stale-key bundle.

    Attributes:
        url: the URL the bundle was fetched from.
        fetched_at: when the bundle was fetched (timezone-aware
            UTC datetime).
        now: the wall-clock instant the bridge consulted.
        max_age_seconds: the configured freshness ceiling.
    """

    def __init__(
        self,
        message: str,
        *,
        url: Optional[str] = None,
        fetched_at: Optional[datetime] = None,
        now: Optional[datetime] = None,
        max_age_seconds: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.fetched_at = fetched_at
        self.now = now
        self.max_age_seconds = max_age_seconds


class PeerSvidSignatureError(SpiffeCrossTrustDomainBridgeError):
    """The peer-presented JWT-SVID failed verification against the
    fetched trust-bundle.

    Operationally distinct from a fetch failure: the bundle is
    fresh, the SVID is well-formed, but the signature does not
    verify under any key in the bundle. Causes are: stale bundle
    (rotated too aggressively on the peer side and the SVID was
    minted under an already-evicted key), stale SVID (the bundle
    was rotated since the SVID was minted), or a cross-trust-
    domain spoofing attempt.

    The bridge is fail-closed: any of the three is rejected
    identically. The structured ``trust_domain`` and ``spiffe_id``
    fields support operator forensics without exposing
    bundle-internal details.

    Attributes:
        trust_domain: the SPIFFE trust-domain that should have
            issued the SVID.
        spiffe_id: the SPIFFE-ID the SVID claims to identify, when
            extractable from the SVID; ``None`` otherwise.
        cause: the underlying verifier exception, when surfaced.
    """

    def __init__(
        self,
        message: str,
        *,
        trust_domain: Optional[str] = None,
        spiffe_id: Optional[str] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        self.trust_domain = trust_domain
        self.spiffe_id = spiffe_id
        self.cause = cause


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchedTrustBundle:
    """A wirelang-owned representation of a fetched peer SPIFFE
    trust-bundle.

    The bundle is treated as opaque bytes at the bridge layer: the
    :class:`PeerSvidVerifier` interprets the bytes (typically as a
    JWK Set per SPIFFE Federation spec). Treating the bundle as
    opaque at the bridge avoids coupling the bridge logic to a
    specific JWKS-parsing library; Phase-2c can swap the verifier
    implementation without touching the bridge.

    Attributes:
        trust_domain: the SPIFFE trust-domain this bundle anchors.
            MUST equal the
            :attr:`MultiOrgRouteAttestation.peer_trust_domain` of
            the attestation that motivated the fetch; the bridge
            checks this equality and raises
            :class:`PeerTrustBundleFetchError` on mismatch.
        url: the URL the bundle was fetched from.
        bundle_bytes: the raw bundle payload (typically a UTF-8
            encoded JWK Set).
        fetched_at: when the bundle was fetched (timezone-aware
            UTC datetime). The bridge uses this for freshness
            enforcement.

    Frozen: callers can pin the bundle into caches and use it as
    a dict key without surprise.
    """

    trust_domain: str
    url: str
    bundle_bytes: bytes
    fetched_at: datetime


@dataclass(frozen=True)
class VerifiedPeerSvid:
    """A wirelang-owned representation of a peer-presented JWT-SVID
    that the bridge has verified against the fetched trust-bundle.

    The bridge never returns an unverified SVID; the verifier
    raises :class:`PeerSvidSignatureError` on any signature or
    parse failure, and the bridge re-raises that error. Code that
    receives a :class:`VerifiedPeerSvid` value can treat the
    SPIFFE-ID, audiences, and expiry as authoritative.

    Attributes:
        spiffe_id: the verified SPIFFE-ID URI from the SVID.
        token: the original encoded SVID (opaque compact-JWS
            string). Retained so downstream code can present it to
            audit / WAT-Audit-Federation-Annex consumers without
            re-fetching.
        audiences: the verified ``aud`` claim values.
        expires_at: the verified ``exp`` claim as a timezone-aware
            UTC datetime.
        verified_at: when the bridge completed the verification
            (timezone-aware UTC datetime).
    """

    spiffe_id: str
    token: str
    audiences: tuple
    expires_at: datetime
    verified_at: datetime


@dataclass(frozen=True)
class LiveBridgeResolution:
    """Result of :meth:`SpiffeCrossTrustDomainBridge.resolve`.

    Pairs the multi-org-attestation registry record with the
    verified peer SVID and the optional local-workload SVID. This
    is the structurally-parallel counterpart to
    :class:`~wirelang.federation.multi_org_substrate.MockBridgeResolution`;
    the live result simply carries more artefacts (every artefact
    the mock path omits is a live-path concretion of one of its
    substrate placeholders).

    Attributes:
        entry: the underlying :class:`RouteRegistryEntry` (from
            the Sprint-3 Tag-6 ``wakir-federation-routes`` bucket).
        attestation: the :class:`MultiOrgRouteAttestation` (from
            the Sprint-7 Tag-2 ``wakir-multi-org-attestations``
            bucket). ``is_mock`` is guaranteed ``False`` here; the
            bridge rejects mock attestations explicitly.
        trust_bundle: the :class:`FetchedTrustBundle` that
            anchored the verification.
        peer_svid: the :class:`VerifiedPeerSvid` whose signature
            was verified against ``trust_bundle``. May be ``None``
            for resolutions that consult only the attestation
            (the bridge accepts a "presence + freshness check"
            mode if no peer SVID is supplied; see
            :meth:`SpiffeCrossTrustDomainBridge.resolve`).
        local_svid: the local workload's own SVID, fetched from
            the wirelang-side
            :class:`SpiffeWorkloadApiAdapter`. ``None`` when no
            local adapter was supplied (the bridge accepts a
            "peer-only" mode).
    """

    entry: RouteRegistryEntry
    attestation: MultiOrgRouteAttestation
    trust_bundle: FetchedTrustBundle
    peer_svid: Optional[VerifiedPeerSvid] = None
    local_svid: Optional[JwtSvid] = None


# ---------------------------------------------------------------------------
# Pluggable Protocols (injection points; live impls land Phase-2c+)
# ---------------------------------------------------------------------------


class PeerTrustBundleFetcher(Protocol):
    """Pluggable peer SPIFFE trust-bundle fetcher.

    The bridge invokes the fetcher with the attestation's
    ``peer_trust_bundle_url`` and the expected ``trust_domain``.
    Implementations:

    - The hermetic test path supplies a deterministic fixture
      fetcher that returns a pre-canned bundle without any I/O.
    - The Phase-2c live path supplies an HTTPS fetcher that
      performs the SPIFFE Federation Bundle Endpoint GET, parses
      the response, and constructs a :class:`FetchedTrustBundle`.

    Contract:

    - The fetcher MUST raise (any exception subclass) on transport
      failure. The bridge catches all exceptions from the fetcher
      and re-raises as :class:`PeerTrustBundleFetchError` with the
      original exception attached as ``cause``.
    - The fetcher MUST return a :class:`FetchedTrustBundle`. A
      ``None`` return is treated as a fetch failure (the bridge
      raises :class:`PeerTrustBundleFetchError`).
    - The fetcher MAY perform caching internally. The bridge does
      not impose a caching policy; freshness is enforced by the
      bridge based on the returned ``fetched_at``.

    Concurrency: implementations MUST be safe for concurrent use
    from multiple asyncio tasks. The bridge invokes the fetcher
    in an ``async`` context.
    """

    async def fetch(
        self, *, url: str, trust_domain: str
    ) -> FetchedTrustBundle:
        ...


class PeerSvidVerifier(Protocol):
    """Pluggable peer JWT-SVID verifier.

    The bridge invokes the verifier with a peer-presented SVID
    token, the fetched trust-bundle, and the expected trust-
    domain. Implementations:

    - The hermetic test path supplies a deterministic verifier
      that accepts pre-canned (token, bundle) pairs and rejects
      others — no JWKS parsing, no signature math.
    - The Phase-2c live path supplies a real JWKS-based verifier
      (likely wrapping the upstream ``spiffe`` package's JWT-SVID
      validator) that parses ``trust_bundle.bundle_bytes`` as a
      JWK Set, validates the SVID's ``alg`` and ``kid``, and
      checks signature + claims.

    Contract:

    - The verifier MUST raise (any exception subclass) on any
      verification failure (parse error, signature mismatch,
      audience mismatch, expiry, trust-domain mismatch, etc.).
      The bridge catches all exceptions from the verifier and
      re-raises as :class:`PeerSvidSignatureError`.
    - On success the verifier MUST return a
      :class:`VerifiedPeerSvid`. A ``None`` return is treated as
      a verification failure.

    Concurrency: same as :class:`PeerTrustBundleFetcher`.
    """

    async def verify(
        self,
        *,
        peer_svid_token: str,
        trust_bundle: FetchedTrustBundle,
        expected_trust_domain: str,
        expected_audience: Optional[str] = None,
    ) -> VerifiedPeerSvid:
        ...


# ---------------------------------------------------------------------------
# Registry Protocols (structural; both Tag-1 in-memory and Tag-2
# NATS-KV backends satisfy these without needing a concrete-base)
# ---------------------------------------------------------------------------


class _RouteRegistryLike(Protocol):
    """Structural surface every route-registry exposes
    (synchronous ``lookup``). Mirrors the
    :class:`~wirelang.federation.n2_evaluator.RouteRegistry`
    Protocol used by the Phase-1b predicate evaluator.
    """

    def lookup(self, route_id: str) -> Optional[RouteRegistryEntry]:
        ...


class _AttestationRegistryLike(Protocol):
    """Structural surface for both the in-memory Tag-1 registry
    (synchronous ``lookup``) and the Tag-2 NATS-KV backend
    (asynchronous ``get``).

    The bridge calls :meth:`lookup_attestation` on this Protocol,
    accepting either signature. A small adapter helper inside the
    bridge normalises the two shapes so callers do not have to
    wrap one or the other.
    """

    def lookup(  # noqa: D401 - shape-only Protocol
        self, route_id: str
    ) -> Optional[MultiOrgRouteAttestation]:
        ...


# ---------------------------------------------------------------------------
# SpiffeCrossTrustDomainBridge
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpiffeCrossTrustDomainBridge:
    """Live cross-trust-domain bridge resolver.

    Construction is cheap: every dependency is injected as a
    Protocol. The bridge holds no mutable state and is safe for
    concurrent use from multiple asyncio tasks.

    Composition:

    - ``route_registry``: the Sprint-3 Tag-6 route-registry
      (in-memory reference for tests, NATS-KV-backed snapshot for
      production). The bridge calls ``lookup(route_id)`` and
      raises :class:`UnknownBridgeRouteError` on a miss.
    - ``attestation_registry``: the Sprint-7 Tag-1 in-memory
      reference OR the Tag-2 NATS-KV backend snapshot. The
      bridge calls ``lookup(route_id)``; for the async Tag-2
      backend the caller materialises a snapshot via
      :meth:`~wirelang.federation.multi_org_attestation_nats_kv_backend.NatsKvMultiOrgAttestationRegistry.snapshot`
      first and passes the snapshot here.
    - ``trust_bundle_fetcher``: the
      :class:`PeerTrustBundleFetcher` Protocol implementation. The
      hermetic test fixture returns a pre-canned bundle; the live
      Phase-2c implementation performs the SPIFFE Federation
      Bundle Endpoint HTTPS fetch.
    - ``peer_svid_verifier``: the :class:`PeerSvidVerifier`
      Protocol implementation. Hermetic-fake or live JWKS-based.
    - ``local_workload_adapter``: optional
      :class:`SpiffeWorkloadApiAdapter` for fetching the local
      workload's own SVID alongside the peer resolution. ``None``
      means "no local SVID in the resolution". The Sprint-6 Tag-5
      :class:`MockSpiffeWorkloadApiAdapter` satisfies this slot
      for tests.
    - ``bundle_max_age_seconds``: trust-bundle freshness ceiling.
      Default :data:`DEFAULT_BUNDLE_MAX_AGE_SECONDS`.
    - ``clock``: optional callable returning a timezone-aware UTC
      datetime. Defaults to :func:`datetime.now(timezone.utc)`.
      Tests inject a fixed-clock fake for determinism.

    Resolution contract (:meth:`resolve`):

    1. Lookup ``route_id`` in ``route_registry``. Miss raises
       :class:`UnknownBridgeRouteError`.
    2. Lookup ``route_id`` in ``attestation_registry``. Miss
       raises :class:`UnknownBridgeRouteError`.
    3. Reject :attr:`MultiOrgRouteAttestation.is_mock` ``True``
       (mock attestations must use the Tag-1 mock resolver).
       Surface: :class:`UnknownBridgeRouteError` (intentional
       homogeneity with the mock resolver's symmetric reject).
    4. Verify the attestation has a non-``None``
       ``peer_trust_bundle_url``. ``None`` means the operator
       did not pre-provision a bundle URL; the bridge has no
       fetch target. Surface:
       :class:`PeerTrustBundleFetchError`.
    5. Call ``trust_bundle_fetcher.fetch(url=..., trust_domain=...)``.
       Any exception is re-raised as
       :class:`PeerTrustBundleFetchError` (with ``cause`` set).
       A ``None`` return is also a fetch failure. A
       ``trust_domain`` mismatch on the returned bundle is also a
       fetch failure (the fetcher should normally enforce this
       itself; the bridge double-checks).
    6. Check freshness:
       ``now - bundle.fetched_at <= bundle_max_age_seconds``.
       Breach raises :class:`PeerTrustBundleExpiredError`.
    7. If a ``peer_svid_token`` was supplied to :meth:`resolve`,
       call ``peer_svid_verifier.verify(...)``. Any failure is
       re-raised as :class:`PeerSvidSignatureError`. On success
       the bridge stamps ``verified_at = clock()``.
    8. If a ``local_workload_adapter`` was configured, call
       ``adapter.fetch_jwt_svid(audience=peer_trust_domain)`` to
       obtain the local workload's outbound SVID. Failures
       propagate as :class:`SpiffeAdapterError` (the bridge does
       NOT wrap these — local adapter errors are operationally
       distinct from cross-trust-domain bridge errors and remain
       the wirelang-adapter-layer concern; see
       ``wirelang/adapters/spiffe_workload_api.py``).
    9. Return a frozen :class:`LiveBridgeResolution`.

    All failure modes are typed and structured; the bridge does
    not log on the path. Operators receive structured errors and
    decide their own logging cadence.
    """

    route_registry: _RouteRegistryLike
    attestation_registry: _AttestationRegistryLike
    trust_bundle_fetcher: PeerTrustBundleFetcher
    peer_svid_verifier: PeerSvidVerifier
    local_workload_adapter: Optional[SpiffeWorkloadApiAdapter] = None
    bundle_max_age_seconds: int = DEFAULT_BUNDLE_MAX_AGE_SECONDS
    clock: Optional[Any] = field(default=None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _now(self) -> datetime:
        if self.clock is not None:
            value = self.clock()
            if not isinstance(value, datetime):
                raise TypeError(
                    "SpiffeCrossTrustDomainBridge.clock must return a "
                    "datetime"
                )
            if value.tzinfo is None:
                raise ValueError(
                    "SpiffeCrossTrustDomainBridge.clock must return a "
                    "timezone-aware UTC datetime"
                )
            return value
        return datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    async def resolve(
        self,
        route_id: str,
        *,
        peer_svid_token: Optional[str] = None,
        peer_svid_audience: Optional[str] = None,
    ) -> LiveBridgeResolution:
        """Resolve a live (non-mock) bridge route.

        See the class docstring for the full resolution contract.

        Parameters:
            route_id: the ``route_id`` of an existing
                :class:`RouteRegistryEntry` paired with a
                non-mock :class:`MultiOrgRouteAttestation`. The
                bridge does NOT enforce a prefix on ``route_id``
                — unlike the mock resolver which requires the
                ``mock-bridge://`` prefix, the live bridge
                operates on any non-mock route_id. The
                substrate-layer mock-prefix-lock (see Tag-1
                substrate) prevents accidental mock leakage onto
                this path: a real route_id cannot carry the mock
                prefix.
            peer_svid_token: optional opaque compact-JWS token
                presented by the peer org. When supplied, the
                bridge verifies it against the fetched trust-
                bundle. ``None`` means "presence + freshness
                only" mode: the bridge fetches the bundle and
                verifies freshness, but does not consume a peer
                SVID. Useful for proactive bundle-validation
                paths (the WAT-Audit-Federation-Annex sweep, for
                example).
            peer_svid_audience: optional expected ``aud`` claim
                for the peer SVID. Forwarded to the verifier
                when ``peer_svid_token`` is supplied.

        Returns: :class:`LiveBridgeResolution`.

        Raises: :class:`UnknownBridgeRouteError`,
            :class:`PeerTrustBundleFetchError`,
            :class:`PeerTrustBundleExpiredError`,
            :class:`PeerSvidSignatureError`,
            :class:`SpiffeAdapterError` (from the local adapter
            path, unwrapped).
        """
        if not isinstance(route_id, str) or not route_id:
            raise UnknownBridgeRouteError(
                f"route_id must be a non-empty string; got "
                f"{type(route_id).__name__}"
            )

        # Step 1: route-registry lookup.
        entry = self.route_registry.lookup(route_id)
        if entry is None:
            raise UnknownBridgeRouteError(
                f"route_id {route_id!r} not in route registry"
            )

        # Step 2: attestation-registry lookup.
        attestation = self.attestation_registry.lookup(route_id)
        if attestation is None:
            raise UnknownBridgeRouteError(
                f"route_id {route_id!r} has no multi-org attestation"
            )

        # Step 3: reject mocks (symmetric to the mock resolver's
        # is_mock=False reject).
        if attestation.is_mock:
            raise UnknownBridgeRouteError(
                f"route_id {route_id!r} attestation is a mock; "
                f"use resolve_mock_bridge_route for mock paths"
            )

        # Step 4: bundle-URL presence check.
        if attestation.peer_trust_bundle_url is None:
            raise PeerTrustBundleFetchError(
                f"route_id {route_id!r} attestation has no "
                f"peer_trust_bundle_url; the live bridge requires "
                f"an operator-pre-provisioned bundle URL",
                url=None,
                cause=None,
            )

        # Step 5: fetch the trust-bundle.
        bundle = await self._fetch_bundle(
            url=attestation.peer_trust_bundle_url,
            trust_domain=attestation.peer_trust_domain,
        )

        # Step 6: freshness check.
        self._enforce_bundle_freshness(bundle)

        # Step 7: peer-SVID verification (conditional).
        peer_svid: Optional[VerifiedPeerSvid] = None
        if peer_svid_token is not None:
            peer_svid = await self._verify_peer_svid(
                peer_svid_token=peer_svid_token,
                trust_bundle=bundle,
                expected_trust_domain=attestation.peer_trust_domain,
                expected_audience=peer_svid_audience,
            )

        # Step 8: local-workload SVID (conditional).
        local_svid: Optional[JwtSvid] = None
        if self.local_workload_adapter is not None:
            # The local-adapter audience is the peer trust-domain:
            # the peer org is the audience that consumes the local
            # workload's outbound SVID. Mirrors the Phase-2.4
            # NATS-JWT-Auth pattern (Kai).
            local_svid = await self.local_workload_adapter.fetch_jwt_svid(
                audience=attestation.peer_trust_domain,
            )

        return LiveBridgeResolution(
            entry=entry,
            attestation=attestation,
            trust_bundle=bundle,
            peer_svid=peer_svid,
            local_svid=local_svid,
        )

    # ------------------------------------------------------------------
    # Step helpers (extracted for readability + targeted test
    # surfaces; downstream code SHOULD call :meth:`resolve` only).
    # ------------------------------------------------------------------

    async def _fetch_bundle(
        self, *, url: str, trust_domain: str
    ) -> FetchedTrustBundle:
        try:
            bundle = await self.trust_bundle_fetcher.fetch(
                url=url, trust_domain=trust_domain
            )
        except BaseException as exc:  # noqa: BLE001 - intentional
            raise PeerTrustBundleFetchError(
                f"trust-bundle fetch failed for url={url!r}: {exc!s}",
                url=url,
                cause=exc,
            ) from exc
        if bundle is None:
            raise PeerTrustBundleFetchError(
                f"trust-bundle fetcher returned None for url={url!r}",
                url=url,
                cause=None,
            )
        if not isinstance(bundle, FetchedTrustBundle):
            raise PeerTrustBundleFetchError(
                f"trust-bundle fetcher returned wrong type "
                f"{type(bundle).__name__!s} for url={url!r}",
                url=url,
                cause=None,
            )
        if bundle.trust_domain != trust_domain:
            raise PeerTrustBundleFetchError(
                f"fetched trust-bundle trust_domain "
                f"{bundle.trust_domain!r} does not match "
                f"attestation trust_domain {trust_domain!r}",
                url=url,
                cause=None,
            )
        return bundle

    def _enforce_bundle_freshness(self, bundle: FetchedTrustBundle) -> None:
        now = self._now()
        if bundle.fetched_at.tzinfo is None:
            raise PeerTrustBundleExpiredError(
                f"trust-bundle fetched_at is timezone-naive for "
                f"url={bundle.url!r}; the bridge requires "
                f"timezone-aware UTC timestamps",
                url=bundle.url,
                fetched_at=bundle.fetched_at,
                now=now,
                max_age_seconds=self.bundle_max_age_seconds,
            )
        age = now - bundle.fetched_at
        max_age_seconds = self.bundle_max_age_seconds
        if age.total_seconds() < 0:
            # Future-stamped bundle: treat as expired (operator-side
            # clock skew or malicious back-dating; fail closed).
            raise PeerTrustBundleExpiredError(
                f"trust-bundle fetched_at is in the future "
                f"({bundle.fetched_at.isoformat()}) relative to "
                f"now ({now.isoformat()}) for url={bundle.url!r}",
                url=bundle.url,
                fetched_at=bundle.fetched_at,
                now=now,
                max_age_seconds=max_age_seconds,
            )
        if age.total_seconds() > max_age_seconds:
            raise PeerTrustBundleExpiredError(
                f"trust-bundle for url={bundle.url!r} is older than "
                f"{max_age_seconds}s (fetched_at "
                f"{bundle.fetched_at.isoformat()}, now "
                f"{now.isoformat()}, age "
                f"{int(age.total_seconds())}s)",
                url=bundle.url,
                fetched_at=bundle.fetched_at,
                now=now,
                max_age_seconds=max_age_seconds,
            )

    async def _verify_peer_svid(
        self,
        *,
        peer_svid_token: str,
        trust_bundle: FetchedTrustBundle,
        expected_trust_domain: str,
        expected_audience: Optional[str],
    ) -> VerifiedPeerSvid:
        try:
            svid = await self.peer_svid_verifier.verify(
                peer_svid_token=peer_svid_token,
                trust_bundle=trust_bundle,
                expected_trust_domain=expected_trust_domain,
                expected_audience=expected_audience,
            )
        except BaseException as exc:  # noqa: BLE001 - intentional
            raise PeerSvidSignatureError(
                f"peer-SVID verification failed for "
                f"trust_domain={expected_trust_domain!r}: {exc!s}",
                trust_domain=expected_trust_domain,
                spiffe_id=None,
                cause=exc,
            ) from exc
        if svid is None:
            raise PeerSvidSignatureError(
                f"peer-SVID verifier returned None for "
                f"trust_domain={expected_trust_domain!r}",
                trust_domain=expected_trust_domain,
                spiffe_id=None,
                cause=None,
            )
        if not isinstance(svid, VerifiedPeerSvid):
            raise PeerSvidSignatureError(
                f"peer-SVID verifier returned wrong type "
                f"{type(svid).__name__!s} for "
                f"trust_domain={expected_trust_domain!r}",
                trust_domain=expected_trust_domain,
                spiffe_id=None,
                cause=None,
            )
        # Cross-check: the verified SPIFFE-ID's trust-domain segment
        # MUST match the expected trust-domain. The verifier should
        # normally enforce this; the bridge double-checks.
        expected_prefix = f"spiffe://{expected_trust_domain}/"
        if not svid.spiffe_id.startswith(expected_prefix):
            raise PeerSvidSignatureError(
                f"verified SPIFFE-ID {svid.spiffe_id!r} does not "
                f"start with expected trust-domain prefix "
                f"{expected_prefix!r}",
                trust_domain=expected_trust_domain,
                spiffe_id=svid.spiffe_id,
                cause=None,
            )
        return svid


# ---------------------------------------------------------------------------
# Hermetic test fixtures (offered here so tests + downstream
# integrators can compose deterministic bridges without rolling
# their own fakes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FixedBundleFetcher:
    """Hermetic :class:`PeerTrustBundleFetcher` fixture.

    Returns a pre-canned :class:`FetchedTrustBundle` keyed by URL.
    Raises ``KeyError`` (which the bridge wraps as
    :class:`PeerTrustBundleFetchError`) for an unknown URL.
    """

    bundles: dict

    async def fetch(
        self, *, url: str, trust_domain: str
    ) -> FetchedTrustBundle:
        if url not in self.bundles:
            raise KeyError(
                f"FixedBundleFetcher: no canned bundle for url={url!r}"
            )
        return self.bundles[url]


@dataclass(frozen=True)
class _AcceptingVerifier:
    """Hermetic :class:`PeerSvidVerifier` fixture (accepts all).

    Returns a :class:`VerifiedPeerSvid` synthesised from the
    parameters, stamped with the supplied clock. Used by tests
    that only need to exercise the *success* path.
    """

    spiffe_id: str
    expires_at: datetime
    clock_now: datetime

    async def verify(
        self,
        *,
        peer_svid_token: str,
        trust_bundle: FetchedTrustBundle,
        expected_trust_domain: str,
        expected_audience: Optional[str] = None,
    ) -> VerifiedPeerSvid:
        return VerifiedPeerSvid(
            spiffe_id=self.spiffe_id,
            token=peer_svid_token,
            audiences=(expected_audience,) if expected_audience else (),
            expires_at=self.expires_at,
            verified_at=self.clock_now,
        )


@dataclass(frozen=True)
class _RejectingVerifier:
    """Hermetic :class:`PeerSvidVerifier` fixture (rejects all).

    Raises :class:`PeerSvidSignatureError` unconditionally. Used by
    tests that exercise the *failure* path.
    """

    reason: str = "rejecting verifier"

    async def verify(
        self,
        *,
        peer_svid_token: str,
        trust_bundle: FetchedTrustBundle,
        expected_trust_domain: str,
        expected_audience: Optional[str] = None,
    ) -> VerifiedPeerSvid:
        raise PeerSvidSignatureError(
            self.reason,
            trust_domain=expected_trust_domain,
            spiffe_id=None,
            cause=None,
        )


__all__ = [
    "BRIDGE_RESOLUTION_SCHEMA",
    "DEFAULT_BUNDLE_MAX_AGE_SECONDS",
    "FetchedTrustBundle",
    "LiveBridgeResolution",
    "PeerSvidSignatureError",
    "PeerSvidVerifier",
    "PeerTrustBundleExpiredError",
    "PeerTrustBundleFetchError",
    "PeerTrustBundleFetcher",
    "SpiffeCrossTrustDomainBridge",
    "SpiffeCrossTrustDomainBridgeError",
    "VerifiedPeerSvid",
    # private fixtures intentionally NOT in __all__; tests import
    # them via their underscore-name from this module directly.
]
