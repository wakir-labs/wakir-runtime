# SPDX-License-Identifier: Apache-2.0
"""V-908 N2 live evaluator for the ``peer_org`` and
``federation_route`` Datalog caveat predicates.

This module is the Phase-1b Sprint-2 Tag-3 production-form of the
federation predicate evaluator. Sprint-1 reserved the predicate
names in ``wirelang/specs/datalog-caveat-vocabulary-phase-2-skizze.md``
section 3.2 (V-908 / ADR-0031 D2); the Phase-1b federation substrate
(``wirelang.identity.dns_anchor`` + ``ftd_verifier`` +
``federation_resolver``) supplies the FTD-doc verify pipeline. This
module is the live evaluator on top of those primitives: given an
already-verified :class:`~wirelang.identity.federation_resolver.FederatedResolveResult`
plus a caller-supplied :class:`RouteRegistry`, it answers Datalog
predicate evaluation questions with a deterministic accept/reject
verdict.

Design notes
------------

The evaluator is **stateless** with respect to time: the freshness
of the FTD-doc and its issuer-key window were already enforced by
:func:`wirelang.identity.federation_resolver.resolve_federated_aip`
at the moment the :class:`FederationContext` was constructed. The
evaluator does NOT consult the wall-clock again for ``peer_org``;
it operates on the windowed result object. This keeps the
predicate evaluation deterministic across re-runs over the same
context (T-N2-10 invariant).

Route freshness is delegated to the :class:`RouteRegistry`
backend. The registry is responsible for returning only entries
that are currently active; the evaluator surfaces the registry's
verdict via :class:`FederationRouteExpiredError` and
:class:`FederationRouteUnknownError`. The Phase-1b reference
implementation is :class:`InMemoryRouteRegistry`; production
deployments will plug in a NATS-KV-backed registry without
changing the evaluator surface.

Predicate semantics (V-908 spec section 4.6 federated rows):

- ``peer_org(aip_id: did)``: the invoking persona's AIP document
  MUST be resolvable under the federation-trust-domain identified
  by ``aip_id`` (the FTD ``id`` from the caller's
  :class:`FederationContext`). The evaluator re-checks the
  FTD-id-equality and the AIP-host-vs-FTD-domain binding.
- ``federation_route(route_id: string)``: the token is valid only
  if ``route_id`` is registered as an active route in the
  caller-supplied :class:`RouteRegistry`. Registry hit + active +
  matched-source-org-FTD MUST hold; any failure raises a typed
  evaluator error.

Cross-review hooks
------------------

This module touches Cross-Review Zone 1 (Identity-Substrate) via
the FTD/AIP cross-check and Zone 2 (WAT × Wirelang) via the route
registry's WAT-anchor field. Phase-1b boundary: the evaluator
does NOT itself anchor route-registry versions to WAT; it surfaces
the anchor field unchanged so a downstream WAT-leaf consumer can
record the snapshot version.

References (URL-stamped 2026-05-07 by wirelang-eng):

- V-908 spec: ``wirelang/specs/datalog-caveat-vocabulary-phase-2-skizze.md``
  sections 3.2 (predicates) and 5 (reserved-name registry).
- ADR-0031 D2: cross-org federation route registry decision.
- Federation resolver: ``wirelang/identity/federation_resolver.py``.
- FTD verifier: ``wirelang/identity/ftd_verifier.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Protocol, Tuple, runtime_checkable

from ..identity.federation_resolver import FederatedResolveResult


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederationPredicateError(Exception):
    """Base class for live evaluator failures."""


class PeerOrgMismatchError(FederationPredicateError):
    """Raised when ``peer_org(aip_id)`` argument does not match the
    federation context's FTD ``id`` (V-908 section 4.1 step 7
    federated row, predicate-evaluator surface).
    """


class FederationRouteUnknownError(FederationPredicateError):
    """Raised when ``federation_route(route_id)`` references a
    route that is not present in the caller's
    :class:`RouteRegistry` (V-908 section 4.6 federated row
    "route registry miss").
    """


class FederationRouteExpiredError(FederationPredicateError):
    """Raised when a route is registered but no longer active at
    the moment of evaluation (V-908 section 4.6 federated row
    "route window violation").
    """


class FederationPredicateArgumentError(FederationPredicateError):
    """Raised when a predicate argument fails the syntactic shape
    contract (DID-form for ``peer_org``, non-empty string for
    ``federation_route``).
    """


# ---------------------------------------------------------------------------
# Route registry surface
# ---------------------------------------------------------------------------


# DID URI shape (Phase-1b Wakir convention, matches the
# federation-trust-document.json $id pattern's host-and-segment
# fragment, but extended to be permissive about arbitrary DID
# methods so the evaluator does not silently constrain the
# argument space below the spec).
_DID_RE = re.compile(r"^did:[a-z0-9]+:[A-Za-z0-9._:%-]+$")


@dataclass(frozen=True)
class RouteRegistryEntry:
    """A single route registry entry (V-908 section 4.6 federated row).

    Attributes:
        route_id: opaque caller-defined route identifier
            (V-908 spec section 3.2 example: ``"wakir->partner-A->treasury"``).
        source_ftd_id: the FTD ``id`` that issued / owns this route.
            The evaluator binds the route to its source-org's FTD
            so a token cannot reference a route registered by some
            unrelated peer.
        active_from: RFC 3339 wall-clock at which this route entry
            became active.
        active_until: RFC 3339 wall-clock at which this route entry
            ceases to be active. ``None`` denotes an open-ended
            window.
        wat_anchor_manifest_id: optional Phase-1b WAT manifest id
            anchoring this registry version. Surfaced unchanged for
            downstream WAT-leaf consumers (Z2 cross-review hook).
    """

    route_id: str
    source_ftd_id: str
    active_from: datetime
    active_until: Optional[datetime]
    wat_anchor_manifest_id: Optional[str] = None

    def is_active_at(self, now: datetime) -> bool:
        """Return whether ``now`` lies inside this entry's window."""
        if now < self.active_from:
            return False
        if self.active_until is not None and now >= self.active_until:
            return False
        return True


@runtime_checkable
class RouteRegistry(Protocol):
    """Caller-pluggable route registry contract.

    The Phase-1b reference implementation is
    :class:`InMemoryRouteRegistry`. A NATS-KV-backed registry is the
    Phase-2 production target (item I-11 vocabulary); the contract
    is intentionally minimal so the swap is mechanical.

    Implementations MUST be deterministic across calls within a
    single evaluator invocation: re-querying the same ``route_id``
    on the same registry instance MUST produce the same result.
    """

    def lookup(self, route_id: str) -> Optional[RouteRegistryEntry]:
        """Return the registry entry, or ``None`` if not registered.

        The evaluator distinguishes "unknown" (returns ``None``) from
        "expired" (returns an entry whose ``is_active_at`` is False)
        so callers receive typed errors that aid forensics.
        """
        ...


@dataclass
class InMemoryRouteRegistry:
    """Phase-1b reference :class:`RouteRegistry` implementation.

    Backed by an in-process dict keyed by ``route_id``. Production
    code SHOULD plug a NATS-KV-backed registry (Phase-2); this
    in-memory variant is for tests and Phase-1b smoke runs.

    The class is intentionally a plain dataclass so the test suite
    can construct, mutate, and inspect entries without reaching
    through a private API.
    """

    entries: dict

    def __init__(self, entries: Optional[dict] = None) -> None:
        self.entries = dict(entries) if entries else {}

    def add(self, entry: RouteRegistryEntry) -> None:
        """Add or overwrite an entry. Last-write-wins semantics."""
        if not isinstance(entry, RouteRegistryEntry):
            raise TypeError("entry must be a RouteRegistryEntry")
        self.entries[entry.route_id] = entry

    def lookup(self, route_id: str) -> Optional[RouteRegistryEntry]:
        if not isinstance(route_id, str):
            return None
        return self.entries.get(route_id)


# ---------------------------------------------------------------------------
# Federation context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FederationContext:
    """Inputs the evaluator needs to answer V-908 predicates.

    The caller assembles this object after running
    :func:`~wirelang.identity.federation_resolver.resolve_federated_aip`
    successfully. The resulting :class:`FederatedResolveResult` is
    the byte-anchor for ``peer_org`` and the route-registry handle
    is the byte-anchor for ``federation_route``.

    Attributes:
        federated_resolve: the verified FTD/AIP cross-check result
            for the invoking persona's token. Anchors the
            ``peer_org`` predicate.
        route_registry: caller-supplied :class:`RouteRegistry` the
            evaluator queries for the ``federation_route``
            predicate.
        eval_now: wall-clock the evaluator pins for route-window
            checks. Defaulted to ``verified_at`` from the federated
            resolve so a single context is fully deterministic
            across re-runs.
    """

    federated_resolve: FederatedResolveResult
    route_registry: RouteRegistry
    eval_now: datetime

    @classmethod
    def from_resolve(
        cls,
        federated_resolve: FederatedResolveResult,
        route_registry: RouteRegistry,
        *,
        eval_now: Optional[datetime] = None,
    ) -> "FederationContext":
        """Convenience constructor.

        If ``eval_now`` is omitted, the context pins it to the
        ``verified_at`` of the federated-resolve result. This is
        the deterministic default: re-evaluating the same token
        against the same context (and registry instance) MUST yield
        the same verdict.
        """
        if eval_now is None:
            eval_now = federated_resolve.verified_at
        if eval_now.tzinfo is None:
            raise ValueError("eval_now must be timezone-aware (UTC)")
        return cls(
            federated_resolve=federated_resolve,
            route_registry=route_registry,
            eval_now=eval_now,
        )


# ---------------------------------------------------------------------------
# Live evaluator
# ---------------------------------------------------------------------------


class FederationEvaluator:
    """Live evaluator for V-908 federation Datalog predicates.

    Phase-1b Sprint-2 Tag-3 implementation. The evaluator is a
    thin layer that turns predicate calls into deterministic
    accept/reject verdicts against a :class:`FederationContext`.

    The evaluator is **pure**: it does not consult the network,
    the wall-clock, or any state outside the supplied context.
    All freshness checks rely on ``context.eval_now`` and the
    pre-windowed ``federated_resolve``. Determinism across re-runs
    is therefore an invariant of construction (T-N2-10).

    Two predicates are supported in N2:

    - ``peer_org(aip_id: did)``: see :meth:`evaluate_peer_org`.
    - ``federation_route(route_id: string)``: see
      :meth:`evaluate_federation_route`.

    Future predicates (e.g. ``cross_org_quota``) will be added in
    later iterations; the surface is intentionally conservative
    so reserved-name producers do not accidentally activate
    unimplemented evaluators.
    """

    def __init__(self, context: FederationContext) -> None:
        if not isinstance(context, FederationContext):
            raise TypeError("context must be a FederationContext")
        self._ctx = context

    # ----- peer_org -------------------------------------------------------

    def evaluate_peer_org(self, aip_id_arg: str) -> bool:
        """Evaluate ``peer_org(aip_id_arg)``.

        Accept iff ``aip_id_arg`` equals the
        ``federated_resolve.ftd_id`` (V-908 spec section 3.2: the
        AIP document MUST be rooted at, or delegated through, the
        AIP id). In Phase-1b the AIP-side delegation chain is the
        FTD trust domain identified by ``ftd_id``; the predicate
        argument therefore matches the FTD ``id`` in the
        currently-verified context. Phase-2 will extend this to
        delegation chains spanning multiple FTDs (V-908 spec
        section 6, out of scope).

        The argument is required to be a syntactically-valid DID
        URI per V-908 spec section 3.1 (``did:web:<host>:ftd:v<N>``);
        non-DID arguments raise
        :class:`FederationPredicateArgumentError` so a malformed
        token is rejected at predicate-evaluator time, not at FTD
        cross-check time.

        Returns:
            ``True`` on accept.

        Raises:
            :class:`FederationPredicateArgumentError`: when
                ``aip_id_arg`` is not a syntactically-valid DID URI
                or is empty / non-string.
            :class:`PeerOrgMismatchError`: when the argument is a
                valid DID but does not equal the context's
                ``ftd_id``.
        """
        if not isinstance(aip_id_arg, str) or not aip_id_arg:
            raise FederationPredicateArgumentError(
                "peer_org argument must be a non-empty string"
            )
        if not _DID_RE.match(aip_id_arg):
            raise FederationPredicateArgumentError(
                f"peer_org argument {aip_id_arg!r} is not a valid DID URI"
            )

        ftd_id = self._ctx.federated_resolve.ftd_id
        if aip_id_arg != ftd_id:
            raise PeerOrgMismatchError(
                f"peer_org argument {aip_id_arg!r} does not match "
                f"federation context FTD id {ftd_id!r}"
            )
        return True

    # ----- federation_route -----------------------------------------------

    def evaluate_federation_route(self, route_id_arg: str) -> bool:
        """Evaluate ``federation_route(route_id_arg)``.

        Accept iff:

        1. ``route_id_arg`` is a non-empty string;
        2. the registry ``lookup`` returns a
           :class:`RouteRegistryEntry`;
        3. the entry's ``source_ftd_id`` equals the federation
           context's ``ftd_id`` (a token cannot use a route
           registered by an unrelated peer);
        4. the entry's window includes ``context.eval_now``.

        Returns:
            ``True`` on accept.

        Raises:
            :class:`FederationPredicateArgumentError`: empty /
                non-string ``route_id_arg``.
            :class:`FederationRouteUnknownError`: registry miss or
                source-FTD mismatch.
            :class:`FederationRouteExpiredError`: registry hit
                but the entry's window does not include
                ``eval_now``.
        """
        if not isinstance(route_id_arg, str) or not route_id_arg:
            raise FederationPredicateArgumentError(
                "federation_route argument must be a non-empty string"
            )

        entry = self._ctx.route_registry.lookup(route_id_arg)
        if entry is None:
            raise FederationRouteUnknownError(
                f"federation_route {route_id_arg!r} is not registered"
            )

        ctx_ftd_id = self._ctx.federated_resolve.ftd_id
        if entry.source_ftd_id != ctx_ftd_id:
            # Treat as unknown from the evaluator's vantage point: a
            # route registered by some other peer is "not visible"
            # under this federation context. Distinct from an
            # expired-window failure to keep forensics clean.
            raise FederationRouteUnknownError(
                f"federation_route {route_id_arg!r} is registered under "
                f"FTD {entry.source_ftd_id!r}; current context FTD is "
                f"{ctx_ftd_id!r}"
            )

        if not entry.is_active_at(self._ctx.eval_now):
            raise FederationRouteExpiredError(
                f"federation_route {route_id_arg!r} is not active at "
                f"{self._ctx.eval_now.isoformat()} "
                f"(window {entry.active_from.isoformat()} -> "
                f"{entry.active_until.isoformat() if entry.active_until else 'open'})"
            )
        return True

    # ----- combined evaluation -------------------------------------------

    def evaluate_all(
        self,
        peer_org_arg: Optional[str] = None,
        federation_route_arg: Optional[str] = None,
    ) -> Tuple[bool, ...]:
        """Evaluate both predicates in a single call.

        Order is fixed: ``peer_org`` first, ``federation_route``
        second. The first failure raises; subsequent predicates are
        not evaluated (short-circuit). This matches Biscuit-Datalog
        verifier semantics where a failed caveat aborts the rest of
        the block.

        Returns:
            A tuple of booleans, one per non-``None`` argument, in
            the order ``(peer_org, federation_route)``.
        """
        verdicts: list = []
        if peer_org_arg is not None:
            verdicts.append(self.evaluate_peer_org(peer_org_arg))
        if federation_route_arg is not None:
            verdicts.append(self.evaluate_federation_route(federation_route_arg))
        return tuple(verdicts)


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


__all__ = [
    "FederationContext",
    "FederationEvaluator",
    "FederationPredicateArgumentError",
    "FederationPredicateError",
    "FederationRouteExpiredError",
    "FederationRouteUnknownError",
    "InMemoryRouteRegistry",
    "PeerOrgMismatchError",
    "RouteRegistry",
    "RouteRegistryEntry",
]
