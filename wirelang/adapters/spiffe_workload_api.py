# SPDX-License-Identifier: Apache-2.0
"""SPIFFE Workload API adapter — wirelang-side surface stub.

Phase: Phase-2 Sprint-6 Tag-4 (skeleton — surface stub only, NO
functional implementation).
Status: surface contract, type annotations, docstrings. Functional
implementation deferred to Sprint-6 Tag-5+ / Phase-2c (paired with the
DevOps-track SPIRE-server integration on Kai's track).

Purpose
=======

Persona-container code MUST NOT import the upstream ``spiffe`` PyPI
package (``spiffe.workload_api``, etc.) directly. All SPIFFE Workload
API access goes through this wirelang-owned adapter module. The
adapter is the wirelang-side **stable surface boundary** over the
upstream library.

Three reasons motivate the indirection (see
``wirelang/specs/identity-substrate.md`` §5.5):

1. **PyPI package-name correction.** The actual PyPI package name is
   ``spiffe`` (NOT ``py-spiffe``); the GitHub repository is
   ``HewlettPackard/py-spiffe``. Pinning persona-container imports to
   the upstream module path would couple wirelang to upstream library
   maintenance risk. The adapter absorbs that coupling.

2. **Library-maintenance-drop resilience.** If upstream ``spiffe``
   maintenance drops (a Phase-3 risk item), the adapter-layer
   indirection lets wirelang substitute its own Workload-API client
   implementation while keeping persona-container code byte-unchanged.

3. **Upstream-breaking-change containment.** A breaking API change in
   ``spiffe`` is a **Z-A re-consensus trigger**; any wirelang PR
   touching this module for an upstream-API-change reason is a Z-A
   re-coordination signal. The adapter makes the trigger explicit and
   localised.

Surface contract (Sprint-6 Tag-4)
=================================

This skeleton defines:

- The :class:`JwtSvid` value object the adapter returns (frozen
  dataclass — wirelang-owned shape, NOT a re-export of any upstream
  ``spiffe.JwtSvid`` type).
- The :class:`X509Svid` value object (analogous shape for the X509-SVID
  path; Phase-2c surface, not Phase-2 path).
- The :class:`SpiffeWorkloadApiAdapter` abstract surface with
  ``fetch_jwt_svid(audience: str) -> JwtSvid`` and the X509-SVID
  symmetric method.
- The :class:`SpiffeAdapterError` family (substrate errors mapped onto
  wirelang-side error types so persona-container code does NOT see
  upstream exception types).

Functional implementation (the wrap-and-delegate over ``spiffe``) is
deferred. The skeleton is sufficient for downstream consumers to
import-pin against and for downstream type-checkers to verify against;
the actual ``await`` paths will raise :class:`NotImplementedError` from
the concrete implementation slot until Sprint-6 Tag-5+ / Phase-2c lands
it.

Implementation cross-references
===============================

- ``wirelang/specs/identity-substrate.md`` §5 — SPIFFE-ID-Binding spec.
- ``wirelang/specs/identity-substrate.md`` §5.5 — adapter-layer
  indirection constraint.
- ``wirelang/specs/identity-substrate.md`` §5.6 — capability-mint
  surface authority (per Component-Type).
- Z-A-Ack 2026-05-11 §3 + §7 — PyPI-package-name correction and
  adapter-layer agreement.
- Kai DevOps-track items (Sprint-6 Tag-5+ / Phase-2c):
  SPIRE-server topology, workload-attestation policy, NATS-JWT
  ``user_jwt_cb`` callback pattern.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol


# ---------------------------------------------------------------------------
# Value objects (wirelang-owned shapes; NOT re-exports of upstream types)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JwtSvid:
    """A wirelang-owned representation of a JWT-SVID returned by the
    SPIFFE Workload API.

    Fields:

    - ``spiffe_id``: the SPIFFE-ID URI (``spiffe://<trust-domain>/...``)
      that identifies the workload this SVID was issued to. Must match
      one of the two patterns in ``identity-substrate.md`` §5.1:
      ``/agent/<persona-slug>/<persona-hash-12>`` (persona-mint
      workload) or ``/service/<service-name>`` (service-only workload).
    - ``token``: the encoded JWT-SVID token (compact JWS form, RFC-7519
      payload + RFC-7515 signature). Treated as an opaque string by
      this adapter; verification is the consumer's responsibility (the
      Workload API does not pre-verify the token shape against
      audience).
    - ``audiences``: the JWT ``aud`` claim values the SVID was minted
      against. The adapter caller passes ``audience: str``; the
      adapter surfaces the full audience list returned by the Workload
      API (the upstream API may return additional audiences).
    - ``expires_at``: the JWT ``exp`` claim as a timezone-aware UTC
      datetime. The Workload API typically issues short-lived SVIDs
      (minutes); ``user_jwt_cb`` refresh-on-expiry is the standard
      NATS-JWT consumption pattern (Kai-track).

    Frozen: callers can put :class:`JwtSvid` instances into sets and
    use them as dict keys without surprise.

    Note: this is NOT a re-export of ``spiffe.JwtSvid`` or any upstream
    type. Wirelang owns this shape; the adapter implementation maps
    upstream returns onto this value object.
    """

    spiffe_id: str
    token: str
    audiences: tuple
    expires_at: datetime


@dataclass(frozen=True)
class X509Svid:
    """A wirelang-owned representation of an X509-SVID returned by the
    SPIFFE Workload API.

    Phase-2c surface; the Phase-2 path uses JWT-SVID exclusively
    (NATS-JWT consumption pattern). The X509-SVID shape is sketched
    here so the adapter surface is symmetric; the
    :meth:`SpiffeWorkloadApiAdapter.fetch_x509_svid` slot lands a
    :class:`NotImplementedError` until Phase-2c.

    Fields:

    - ``spiffe_id``: the SPIFFE-ID URI (same pattern as
      :class:`JwtSvid`).
    - ``cert_chain``: the X.509 certificate chain (DER bytes,
      leaf-first). Verification against the trust bundle is the
      consumer's responsibility.
    - ``private_key``: the leaf certificate's private key (DER bytes,
      PKCS#8). Secret material: the consumer MUST treat this as
      sensitive (zero on drop, avoid logging, etc.).
    - ``trust_bundle``: the trust-bundle bytes (concatenated DER-encoded
      CA certificates) for the SPIFFE trust domain.
    - ``expires_at``: the leaf certificate's ``notAfter`` instant
      (timezone-aware UTC).
    """

    spiffe_id: str
    cert_chain: bytes
    private_key: bytes
    trust_bundle: bytes
    expires_at: datetime


# ---------------------------------------------------------------------------
# Error hierarchy (substrate errors mapped onto wirelang-side types)
# ---------------------------------------------------------------------------


class SpiffeAdapterError(Exception):
    """Base class for all wirelang-side SPIFFE-adapter errors.

    Persona-container code SHOULD NOT see upstream exception types from
    the ``spiffe`` PyPI package. The adapter wraps upstream errors and
    re-raises as :class:`SpiffeAdapterError` (or a subclass) so
    consumers have a stable error surface.
    """


class SpiffeAdapterUnavailable(SpiffeAdapterError):
    """The Workload API endpoint is not reachable.

    Typical causes: the SPIRE-agent is not running, the Unix domain
    socket path is wrong, or the agent is unreachable on the network
    path (rare; the Workload API is a UDS surface by default).

    Consumers should treat this as a transient error and retry with
    backoff; long-term unavailability is an operational issue for the
    DevOps track (Kai).
    """


class SpiffeAdapterAttestationFailed(SpiffeAdapterError):
    """The Workload API responded but workload-attestation failed.

    The SPIRE-agent could not attest the calling workload against any
    registration entry. Typical causes: the workload selectors do not
    match a registration entry, the SPIRE-server is not configured for
    this workload, or the workload is calling from outside its
    expected attestation context.

    Distinct from :class:`SpiffeAdapterUnavailable`: the Workload API
    answered, but rejected the attestation.
    """


class SpiffeAdapterAudienceRejected(SpiffeAdapterError):
    """The Workload API rejected the requested audience.

    The SPIRE-server's registration entry does not permit minting a
    JWT-SVID with the requested ``audience`` value. This is a
    configuration-side error (the audience set is registered per-entry
    on the SPIRE-server) and is NOT a transient condition; retrying
    with the same audience will fail identically.
    """


# ---------------------------------------------------------------------------
# Adapter surface (Protocol; concrete impl deferred)
# ---------------------------------------------------------------------------


class SpiffeWorkloadApiAdapter(Protocol):
    """Wirelang-side SPIFFE Workload API surface.

    Concrete implementation deferred to Sprint-6 Tag-5+ / Phase-2c. The
    surface is defined as a :class:`Protocol` so callers can type-pin
    against it without forcing a concrete dependency on the upstream
    ``spiffe`` package at the persona-container layer.

    Concurrency: implementations MUST be safe for concurrent use from
    multiple asyncio tasks (the Workload API supports concurrent
    streaming subscriptions; the adapter is expected to multiplex).

    Lifecycle: implementations expose a constructor taking the
    Workload-API endpoint path (e.g.
    ``unix:///run/spire/sockets/agent.sock``) and any required
    timeout / retry configuration. An ``async``-context-manager
    protocol (``__aenter__`` / ``__aexit__``) is recommended for
    resource cleanup; the Protocol here does NOT mandate it (concrete
    implementations may choose).

    Error semantics: all method failures raise
    :class:`SpiffeAdapterError` (or a subclass). Upstream
    ``spiffe``-package exceptions MUST be mapped by the implementation
    to wirelang-side error types; consumers SHOULD NOT need to import
    from ``spiffe`` to catch errors.
    """

    async def fetch_jwt_svid(
        self,
        audience: str,
        *,
        spiffe_id: Optional[str] = None,
    ) -> JwtSvid:
        """Fetch a JWT-SVID for the calling workload, minted against
        ``audience``.

        Parameters:

        - ``audience``: the JWT ``aud`` claim value to request. Typical
          values are NATS-server identifiers or upstream-service
          SPIFFE-IDs. The Workload API rejects audiences the
          registration entry does not permit (raises
          :class:`SpiffeAdapterAudienceRejected`).
        - ``spiffe_id``: optional explicit SPIFFE-ID to mint under.
          ``None`` means "use the default SVID for this workload"
          (the typical case). Workloads with multiple registered
          SPIFFE-IDs use this to disambiguate.

        Returns: a :class:`JwtSvid` instance.

        Raises:

        - :class:`SpiffeAdapterUnavailable` — Workload API endpoint not
          reachable.
        - :class:`SpiffeAdapterAttestationFailed` — workload-attestation
          rejected.
        - :class:`SpiffeAdapterAudienceRejected` — audience not
          permitted by the registration entry.
        - :class:`SpiffeAdapterError` — generic catch-all for other
          Workload API errors.
        """
        ...

    async def fetch_x509_svid(
        self,
        *,
        spiffe_id: Optional[str] = None,
    ) -> X509Svid:
        """Fetch an X509-SVID for the calling workload.

        Phase-2c surface; the Phase-2 path does NOT use this method
        (NATS-JWT consumption is JWT-SVID-only). Phase-2c+ workload
        topologies that need mTLS substrate (e.g. orchestrator-internal
        gRPC) consume X509-SVID through this path.

        Parameters:

        - ``spiffe_id``: optional explicit SPIFFE-ID to mint under
          (same semantics as :meth:`fetch_jwt_svid`).

        Returns: an :class:`X509Svid` instance.

        Raises: see :meth:`fetch_jwt_svid`.
        """
        ...


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = [
    "JwtSvid",
    "SpiffeAdapterAttestationFailed",
    "SpiffeAdapterAudienceRejected",
    "SpiffeAdapterError",
    "SpiffeAdapterUnavailable",
    "SpiffeWorkloadApiAdapter",
    "X509Svid",
]
