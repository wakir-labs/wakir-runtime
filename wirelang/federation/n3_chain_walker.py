# SPDX-License-Identifier: Apache-2.0
"""V-908 N3 multi-FTD delegation-chain walker.

This module is the Phase-1b Sprint-2 Tag-5 production-form of the
delegation-chain walker. It is the third iteration after N1 (Sprint-1
stub: vocabulary reservation only) and N2 (Sprint-2 Tag-3 live
evaluator: single-hop ``peer_org`` and ``federation_route``).

The N3 walker answers a strictly-stronger version of the ``peer_org``
predicate: a token may be accepted not only when the invoking
persona's federation context's FTD id equals the ``peer_org``
argument, but also when there exists a delegation chain of FTDs
that connects the context's FTD to the predicate argument's FTD,
where each hop is witnessed by an active federation-route entry
in the caller-supplied :class:`RouteRegistry`.

This is the formal ``peer_org`` extension that Phase-2 spec §5.1
already reserved as the Phase-2 evolution path
("delegation-chain walking, V-908 spec §6, out of scope here") and
that Phase-2 spec §5.5 N2-implementation-note marked as the next
iteration after the single-hop FTD-id-equality match. The N3 walker
is the concrete implementation of that path.

Design notes
------------

The walker is **stateless** with respect to time: the freshness of
each hop's federation-route window is checked against the
evaluator-pinned ``eval_now`` from the supplied
:class:`FederationContext` (Tag-3 N2 contract preserved). The
walker does NOT consult the wall-clock independently. Determinism
across re-runs is therefore an invariant of construction (T-N3-09).

The walker is **pure**: it does not consult the network, the
filesystem, or any state outside the supplied chain spec, the
registry handle, and the evaluator context. The :class:`RouteRegistry`
Protocol contract (see :mod:`wirelang.federation.n2_evaluator`) is
the only external surface.

The walker assumes routes are stored under a route_id convention
that encodes the source-and-target FTDs explicitly. Phase-1b uses
the canonical form ``"<source_ftd_id>->|->>|<target_ftd_id>"`` —
i.e. each hop's route_id is the deterministic concatenation of the
source FTD id, a fixed separator ``"-|->"``, and the target FTD id.
This is a convention contract: the walker computes the route_id
deterministically from the (source, target) FTD pair and does NOT
fall back to scanning the registry. This keeps the walker
deterministic and avoids ordering-dependent verdicts under
last-write-wins semantics.

The separator ``"-|->"`` is chosen to be ASCII, distinct from any
``did:`` syntax token, and unlikely to collide with operator-defined
``route_id`` strings (which are typically arrow-style human-readable
labels like ``"wakir->partner-A->treasury"``). Phase-2 spec §5.7
informative note ratifies the convention.

Cycle detection: the walker maintains a visited set of FTD ids and
rejects any chain that re-visits an FTD id. This protects against
malicious or buggy chain inputs that would otherwise loop indefinitely.

Depth bound: the walker rejects chains longer than
``max_depth`` hops. The Phase-1b default is ``MAX_DEPTH_DEFAULT = 4``
(i.e. up to 4 inter-FTD hops between the context FTD and the target
FTD). This is informed by the typical multi-org capability flow
(issuer -> processor -> partner -> end-org) plus one slack hop.
Operators may tighten the bound at construction time.

Cross-review hooks
------------------

This module touches Cross-Review Zone 1 (Identity-Substrate) at
substantially deeper substance than the N2 evaluator: every hop
in the chain is an FTD-doc cross-check anchor. The walker itself
does NOT re-verify FTD docs (that is upstream
:mod:`wirelang.identity.federation_resolver`'s job for the
evaluator's own FTD); for intermediate FTDs in the chain, the
walker relies on the route-registry entry's
``source_ftd_id`` field to assert the hop's identity binding.
A Phase-2 hardening will likely require per-hop FTD-doc resolution;
the current Phase-1b form is the minimum viable contract.

Cross-Review Zone 2 (WAT × Wirelang): each hop's route entry may
carry a ``wat_anchor_manifest_id``; the walker surfaces the chain
of anchors unchanged so a downstream WAT-leaf consumer can record
the multi-hop snapshot. The walker itself does NOT anchor.

References (URL-stamped 2026-05-07 by wirelang-eng):

- V-908 spec §6 "delegation chains" sketch:
  ``wirelang/specs/datalog-caveat-vocabulary-phase-2-skizze.md``
  §3.2 (peer_org semantics across delegation chain).
- Phase-2 spec §5.1 / §5.5 N2 boundary:
  ``wirelang/specs/datalog-caveat-vocabulary-phase-2.md``
  §5.1 "rooted at, or be reachable via a delegation chain that
  includes" / §5.5 "Phase-2 will extend this to delegation-chain
  walking".
- Phase-2 spec §5.7 (this Tag-5 module's informative anchor).
- N2 evaluator surface:
  ``wirelang/federation/n2_evaluator.py`` (Tag-3, commit a8b08ae).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple

from .n2_evaluator import (
    FederationContext,
    FederationPredicateArgumentError,
    FederationPredicateError,
    FederationRouteExpiredError,
    FederationRouteUnknownError,
    PeerOrgMismatchError,
    RouteRegistry,
    RouteRegistryEntry,
)


# ---------------------------------------------------------------------------
# Public surface constants
# ---------------------------------------------------------------------------


MAX_DEPTH_DEFAULT = 4
"""Default maximum number of inter-FTD hops a chain may traverse.

A chain of length 0 is an FTD-id-equality match (degenerate; same as
N2 ``peer_org`` exact match). A chain of length 1 traverses one
intermediate hop. The Phase-1b default of 4 covers issuer ->
processor -> partner -> end-org plus one slack hop. Operators may
tighten the bound at :class:`ChainWalker` construction time.
"""


CHAIN_HOP_SEPARATOR = "-|->"
"""Canonical separator for chain-hop ``route_id`` derivation.

Each inter-FTD hop's route_id is the concatenation
``"<source_ftd_id>" + CHAIN_HOP_SEPARATOR + "<target_ftd_id>"``.
ASCII, distinct from DID URI tokens, and chosen to not collide with
operator-defined arrow-style human-readable labels.
"""


# DID URI shape (mirrors n2_evaluator._DID_RE; intentionally
# duplicated locally so the walker is import-safe even if the N2
# module is later split out).
_DID_RE = re.compile(r"^did:[a-z0-9]+:[A-Za-z0-9._:%-]+$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ChainWalkerError(FederationPredicateError):
    """Base class for N3 chain-walker failures.

    Inherits from :class:`FederationPredicateError` so callers that
    already short-circuit on N2 evaluator errors uniformly handle N3
    failures without surface widening.
    """


class ChainWalkerArgumentError(ChainWalkerError):
    """Raised when a chain spec argument fails the syntactic shape contract.

    Distinct from :class:`FederationPredicateArgumentError` so the
    forensic origin of the error (predicate-evaluator vs chain-walker)
    is unambiguous in logs.
    """


class ChainWalkerCycleError(ChainWalkerError):
    """Raised when the chain spec re-visits an FTD id.

    A well-formed delegation chain is acyclic by construction. A
    cycle indicates either a malicious chain input or a registry
    integrity bug. Either way, the walker rejects fail-closed.
    """


class ChainWalkerDepthError(ChainWalkerError):
    """Raised when the chain spec exceeds the configured ``max_depth``."""


class ChainWalkerSchemaError(ChainWalkerError):
    """Raised when a chain hop's route entry fails a schema-level
    cross-check (e.g. the route's ``source_ftd_id`` does not equal
    the previous hop's FTD id).
    """


# ---------------------------------------------------------------------------
# Verdict surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainHopVerdict:
    """Per-hop verdict from a successful chain walk.

    Surfaces the hop's identity binding and WAT-anchor for downstream
    Z2 consumers. The walker constructs one of these per hop on
    accept; on reject, the walker raises a typed error and produces
    no verdict.

    Attributes:
        hop_index: zero-based index of this hop in the chain (0 is
            the first hop after the context FTD; ``len(hops)-1`` is
            the final hop into the target FTD).
        source_ftd_id: the FTD id at the start of this hop.
        target_ftd_id: the FTD id at the end of this hop.
        route_id: the route_id consulted for this hop.
        wat_anchor_manifest_id: optional Z2 surface, unchanged from
            the registry entry.
    """

    hop_index: int
    source_ftd_id: str
    target_ftd_id: str
    route_id: str
    wat_anchor_manifest_id: Optional[str] = None


@dataclass(frozen=True)
class ChainVerdict:
    """Aggregate verdict for a full chain walk.

    Returned on accept. The caller can use ``hops`` for forensics or
    audit-log emission and ``wat_anchor_chain`` for the WAT-leaf
    snapshot manifest.

    Attributes:
        target_ftd_id: the terminal FTD id the chain reaches.
        hops: the ordered tuple of per-hop verdicts. The first hop's
            ``source_ftd_id`` equals the context's FTD id; the last
            hop's ``target_ftd_id`` equals ``target_ftd_id``. A chain
            of length zero (degenerate FTD-id-equality match)
            produces ``hops=()``.
        wat_anchor_chain: ordered tuple of WAT manifest ids
            collected from each hop's registry entry. ``None``
            entries indicate the hop's route had no WAT anchor; the
            tuple length equals ``len(hops)``.
        depth: convenience integer alias for ``len(hops)``.
    """

    target_ftd_id: str
    hops: Tuple[ChainHopVerdict, ...]
    wat_anchor_chain: Tuple[Optional[str], ...]
    depth: int = field(init=False)

    def __post_init__(self) -> None:
        # ``depth`` is derived from ``hops`` so the dataclass remains
        # frozen but the convenience field stays consistent.
        object.__setattr__(self, "depth", len(self.hops))


# ---------------------------------------------------------------------------
# Walker
# ---------------------------------------------------------------------------


def derive_chain_hop_route_id(source_ftd_id: str, target_ftd_id: str) -> str:
    """Return the canonical chain-hop route_id for a (source, target) FTD pair.

    The Phase-1b convention is
    ``"<source_ftd_id>" + CHAIN_HOP_SEPARATOR + "<target_ftd_id>"``.
    Operators emitting registry entries that are intended to witness
    chain hops MUST use this exact derivation; the walker does NOT
    fall back to scanning the registry for a matching pair.

    Both arguments are validated as DID URIs (Phase-1b Wakir
    convention, identical to N2 evaluator surface). Empty / non-DID
    arguments raise :class:`ChainWalkerArgumentError`.
    """
    if not isinstance(source_ftd_id, str) or not source_ftd_id:
        raise ChainWalkerArgumentError(
            "source_ftd_id must be a non-empty string"
        )
    if not isinstance(target_ftd_id, str) or not target_ftd_id:
        raise ChainWalkerArgumentError(
            "target_ftd_id must be a non-empty string"
        )
    if not _DID_RE.match(source_ftd_id):
        raise ChainWalkerArgumentError(
            f"source_ftd_id {source_ftd_id!r} is not a valid DID URI"
        )
    if not _DID_RE.match(target_ftd_id):
        raise ChainWalkerArgumentError(
            f"target_ftd_id {target_ftd_id!r} is not a valid DID URI"
        )
    return f"{source_ftd_id}{CHAIN_HOP_SEPARATOR}{target_ftd_id}"


class ChainWalker:
    """N3 multi-FTD delegation-chain walker.

    The walker takes a :class:`FederationContext` (the same object
    the N2 evaluator consumes) plus a target FTD id and an explicit
    chain spec (the ordered list of intermediate FTD ids the caller
    asserts the chain traverses). It then verifies, hop by hop, that:

    1. each hop is acyclic (no FTD id is visited twice);
    2. the total chain depth does not exceed ``max_depth``;
    3. each hop's canonical route_id is registered in the
       :class:`RouteRegistry`;
    4. each hop's registry entry's ``source_ftd_id`` equals the
       expected hop source (chain integrity);
    5. each hop's registry entry's window includes
       ``context.eval_now`` (freshness).

    Determinism contract (T-N3-09): two invocations of
    :meth:`walk` with the same context, target, and chain spec MUST
    produce the same verdict (or the same typed error).

    The walker is pure-Python and has no external dependencies
    beyond the Tag-3 N2 evaluator surface (``RouteRegistry`` Protocol,
    ``RouteRegistryEntry`` dataclass).
    """

    def __init__(
        self,
        context: FederationContext,
        *,
        max_depth: int = MAX_DEPTH_DEFAULT,
    ) -> None:
        if not isinstance(context, FederationContext):
            raise TypeError("context must be a FederationContext")
        if not isinstance(max_depth, int) or max_depth < 0:
            raise ChainWalkerArgumentError(
                "max_depth must be a non-negative int"
            )
        self._ctx = context
        self._max_depth = max_depth

    @property
    def max_depth(self) -> int:
        return self._max_depth

    @property
    def context(self) -> FederationContext:
        return self._ctx

    # ----- core walk ------------------------------------------------------

    def walk(
        self,
        target_ftd_id: str,
        intermediate_ftd_ids: Optional[Tuple[str, ...]] = None,
    ) -> ChainVerdict:
        """Walk a delegation chain from the context FTD to ``target_ftd_id``.

        The full chain is::

            ctx_ftd_id -> intermediate_ftd_ids[0] -> ... -> intermediate_ftd_ids[-1] -> target_ftd_id

        The walker derives one hop per arrow. A chain with no
        intermediate FTDs (``intermediate_ftd_ids in (None, ())``)
        and ``target_ftd_id == ctx_ftd_id`` is the degenerate
        zero-hop chain (FTD-id-equality match, same verdict as N2
        ``peer_org`` exact match).

        Args:
            target_ftd_id: the terminal FTD id the chain must reach.
                Required, must be a syntactically-valid DID URI.
            intermediate_ftd_ids: ordered tuple of intermediate FTD
                ids, each a syntactically-valid DID URI. May be
                ``None`` or empty for a single-hop or zero-hop walk.

        Returns:
            :class:`ChainVerdict` on accept.

        Raises:
            :class:`ChainWalkerArgumentError`: malformed argument.
            :class:`ChainWalkerCycleError`: chain re-visits an FTD id.
            :class:`ChainWalkerDepthError`: chain longer than
                ``max_depth``.
            :class:`PeerOrgMismatchError`: zero-hop walk where
                ``target_ftd_id != ctx.federated_resolve.ftd_id``.
            :class:`FederationRouteUnknownError`: a hop's canonical
                route_id is missing from the registry, or its
                ``source_ftd_id`` does not match the hop source.
            :class:`FederationRouteExpiredError`: a hop's route is
                registered but its window does not include
                ``context.eval_now``.
            :class:`ChainWalkerSchemaError`: a hop's registry entry
                fails a structural cross-check unrelated to
                source-FTD or window (reserved for future use; not
                raised by Phase-1b walker).
        """
        # 1. Argument-shape gate.
        if not isinstance(target_ftd_id, str) or not target_ftd_id:
            raise ChainWalkerArgumentError(
                "target_ftd_id must be a non-empty string"
            )
        if not _DID_RE.match(target_ftd_id):
            raise ChainWalkerArgumentError(
                f"target_ftd_id {target_ftd_id!r} is not a valid DID URI"
            )

        if intermediate_ftd_ids is None:
            intermediate_ftd_ids = ()
        if not isinstance(intermediate_ftd_ids, tuple):
            # Accept any sequence-like but normalise to tuple for
            # frozen dataclass compatibility.
            try:
                intermediate_ftd_ids = tuple(intermediate_ftd_ids)
            except TypeError as exc:
                raise ChainWalkerArgumentError(
                    "intermediate_ftd_ids must be a sequence of strings"
                ) from exc

        for idx, fid in enumerate(intermediate_ftd_ids):
            if not isinstance(fid, str) or not fid:
                raise ChainWalkerArgumentError(
                    f"intermediate_ftd_ids[{idx}] must be a non-empty string"
                )
            if not _DID_RE.match(fid):
                raise ChainWalkerArgumentError(
                    f"intermediate_ftd_ids[{idx}] = {fid!r} is not a valid DID URI"
                )

        ctx_ftd_id = self._ctx.federated_resolve.ftd_id

        # 2. Zero-hop degenerate case: no intermediates and
        #    target == ctx FTD id. Handled before the full-sequence
        #    cycle scan because that scan would otherwise treat the
        #    (ctx, target) pair as a re-visit when target == ctx,
        #    which is the legitimate zero-hop FTD-id-equality case
        #    (same verdict as N2 ``peer_org`` exact match).
        if len(intermediate_ftd_ids) == 0 and target_ftd_id == ctx_ftd_id:
            return ChainVerdict(
                target_ftd_id=target_ftd_id,
                hops=(),
                wat_anchor_chain=(),
            )

        # 3. Build the ordered FTD-id sequence: ctx, *intermediate, target.
        full_sequence: Tuple[str, ...] = (ctx_ftd_id,) + intermediate_ftd_ids + (target_ftd_id,)

        # 4. Cycle detection: a well-formed delegation chain visits
        #    each FTD id at most once.
        seen = set()
        for fid in full_sequence:
            if fid in seen:
                raise ChainWalkerCycleError(
                    f"delegation chain re-visits FTD id {fid!r}; "
                    f"chains must be acyclic"
                )
            seen.add(fid)

        # 5. Depth check. The hop count is len(full_sequence) - 1.
        hop_count = len(full_sequence) - 1
        if hop_count > self._max_depth:
            raise ChainWalkerDepthError(
                f"chain depth {hop_count} exceeds max_depth "
                f"{self._max_depth}"
            )

        # Defensive: ``hop_count == 0`` is impossible here because
        # the zero-hop case is handled in step 2 above (a chain with
        # no intermediates and target == ctx). If a future refactor
        # ever lets control reach this point with hop_count == 0,
        # surface a forensic error rather than silently returning an
        # empty verdict.
        if hop_count == 0:  # pragma: no cover
            raise PeerOrgMismatchError(
                f"zero-hop walk: target_ftd_id {target_ftd_id!r} "
                f"does not match context FTD id {ctx_ftd_id!r}"
            )

        # 6. Walk each hop.
        hops_acc: list = []
        anchors_acc: list = []
        for hop_idx in range(hop_count):
            src = full_sequence[hop_idx]
            tgt = full_sequence[hop_idx + 1]
            route_id = derive_chain_hop_route_id(src, tgt)

            entry = self._ctx.route_registry.lookup(route_id)
            if entry is None:
                raise FederationRouteUnknownError(
                    f"chain hop {hop_idx} ({src!r} -> {tgt!r}): "
                    f"canonical route_id {route_id!r} is not registered"
                )
            if not isinstance(entry, RouteRegistryEntry):
                # Schema-level cross-check: the registry MUST return
                # a RouteRegistryEntry instance. Defensive against
                # custom registry implementations that violate the
                # Protocol contract.
                raise ChainWalkerSchemaError(
                    f"chain hop {hop_idx}: registry returned non-entry "
                    f"object for route_id {route_id!r}"
                )
            if entry.source_ftd_id != src:
                # The entry's source_ftd_id field MUST agree with the
                # hop source FTD id derived from the chain spec. A
                # mismatch indicates either a malformed registry or a
                # malicious chain spec; surface as an unknown-route
                # error to keep forensics consistent with N2 §6
                # source-FTD mismatch handling.
                raise FederationRouteUnknownError(
                    f"chain hop {hop_idx}: registry entry for "
                    f"{route_id!r} has source_ftd_id "
                    f"{entry.source_ftd_id!r}, expected {src!r}"
                )
            if not entry.is_active_at(self._ctx.eval_now):
                raise FederationRouteExpiredError(
                    f"chain hop {hop_idx}: route {route_id!r} is not "
                    f"active at {self._ctx.eval_now.isoformat()} "
                    f"(window {entry.active_from.isoformat()} -> "
                    f"{entry.active_until.isoformat() if entry.active_until else 'open'})"
                )
            hops_acc.append(
                ChainHopVerdict(
                    hop_index=hop_idx,
                    source_ftd_id=src,
                    target_ftd_id=tgt,
                    route_id=route_id,
                    wat_anchor_manifest_id=entry.wat_anchor_manifest_id,
                )
            )
            anchors_acc.append(entry.wat_anchor_manifest_id)

        return ChainVerdict(
            target_ftd_id=target_ftd_id,
            hops=tuple(hops_acc),
            wat_anchor_chain=tuple(anchors_acc),
        )


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def walk_delegation_chain(
    context: FederationContext,
    target_ftd_id: str,
    intermediate_ftd_ids: Optional[Tuple[str, ...]] = None,
    *,
    max_depth: int = MAX_DEPTH_DEFAULT,
) -> ChainVerdict:
    """Convenience wrapper around :class:`ChainWalker`.

    Equivalent to ``ChainWalker(context, max_depth=max_depth).walk(
    target_ftd_id, intermediate_ftd_ids)``. Provided so callers that
    use the walker exactly once need not instantiate the class
    explicitly.
    """
    walker = ChainWalker(context, max_depth=max_depth)
    return walker.walk(target_ftd_id, intermediate_ftd_ids)


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


__all__ = [
    "CHAIN_HOP_SEPARATOR",
    "ChainHopVerdict",
    "ChainVerdict",
    "ChainWalker",
    "ChainWalkerArgumentError",
    "ChainWalkerCycleError",
    "ChainWalkerDepthError",
    "ChainWalkerError",
    "ChainWalkerSchemaError",
    "MAX_DEPTH_DEFAULT",
    "derive_chain_hop_route_id",
    "walk_delegation_chain",
]
