# SPDX-License-Identifier: Apache-2.0
"""Determinism tests for the V-908 N3 multi-FTD delegation-chain walker.

Phase-1b Sprint-2 Tag-5 (S2-4). Tests the chain walker for the
``peer_org`` predicate's delegation-chain-walking extension specified
in ``wirelang/specs/datalog-caveat-vocabulary-phase-2.md`` §5.7
(Phase-1b informative note added in Tag-5) and implemented in
:mod:`wirelang.federation.n3_chain_walker`.

Tests construct a :class:`FederatedResolveResult` directly (same
pattern as the Tag-3 N2 evaluator tests) and assemble an
:class:`InMemoryRouteRegistry` populated with chain-hop entries
under the canonical ``derive_chain_hop_route_id`` derivation. The
walker is exercised against both happy-path and rejection paths.

Test inventory (T-N3-01..N3-10, all deterministic; plus aux probes):

- T-N3-01: argument-shape gate rejects non-DID target / hop entries.
- T-N3-02: zero-hop walk (target == ctx FTD) accepts with empty hops.
- T-N3-03: single-hop chain (1 intermediate hop) happy-path accept.
- T-N3-04: 2-hop chain happy-path accept; verdict surfaces both hop
  verdicts and the WAT-anchor chain.
- T-N3-05: 3-hop chain happy-path accept (default max_depth=4 covers).
- T-N3-06: depth-violation rejected when chain length > max_depth.
- T-N3-07: cycle-detection rejected when an FTD id is re-visited.
- T-N3-08: missing-route hop rejected with FederationRouteUnknownError.
- T-N3-09: determinism — repeated walks over identical inputs yield
  byte-identical verdicts.
- T-N3-10: source-FTD-mismatch on a registered route rejected with
  FederationRouteUnknownError (forensics-clean distinction).

Bonus aux probes:

- T-N3-aux-expired-hop: registered route whose window does not
  include eval_now rejected with FederationRouteExpiredError.
- T-N3-aux-derive-helper: the derive_chain_hop_route_id helper
  validates argument shape and emits the canonical concatenation.
- T-N3-aux-walk-fn: the walk_delegation_chain convenience function
  yields a verdict equivalent to the class-form walker.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from wirelang.federation.n2_evaluator import (
    FederationContext,
    FederationRouteExpiredError,
    FederationRouteUnknownError,
    InMemoryRouteRegistry,
    PeerOrgMismatchError,
    RouteRegistryEntry,
)
from wirelang.federation.n3_chain_walker import (
    CHAIN_HOP_SEPARATOR,
    ChainVerdict,
    ChainWalker,
    ChainWalkerArgumentError,
    ChainWalkerCycleError,
    ChainWalkerDepthError,
    MAX_DEPTH_DEFAULT,
    derive_chain_hop_route_id,
    walk_delegation_chain,
)
from wirelang.identity.federation_resolver import FederatedResolveResult


# ---------------------------------------------------------------------------
# Fixtures (mirror the Tag-3 N2 fixture topology byte-for-byte where
# possible so cross-module determinism contracts share an anchor)
# ---------------------------------------------------------------------------


_FTD_ID = "did:web:wakir.dev:ftd:v1"
_HOP_A_FTD_ID = "did:web:processor-a.dev:ftd:v1"
_HOP_B_FTD_ID = "did:web:partner-b.dev:ftd:v1"
_HOP_C_FTD_ID = "did:web:partner-c.dev:ftd:v1"
_TARGET_FTD_ID = "did:web:end-org.dev:ftd:v1"

_AIP_ID = "aip:web:wakir.dev/treasury-issuer"
_VERIFIED_AT = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
_HEX_PK = "ab" * 32
_HEX_FP = "cd" * 32
_HEX_AIP_JCS = "ef" * 32
_HEX_FTD_FP = "12" * 32

_ROUTE_ACTIVE_FROM = datetime(2026, 5, 1, tzinfo=timezone.utc)
_ROUTE_ACTIVE_UNTIL = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _make_resolve(
    ftd_id: str = _FTD_ID,
    *,
    verified_at: datetime = _VERIFIED_AT,
) -> FederatedResolveResult:
    return FederatedResolveResult(
        aip_id=_AIP_ID,
        ftd_id=ftd_id,
        aip_body={"id": _AIP_ID, "stub": True},
        aip_jcs_sha256=_HEX_AIP_JCS,
        ftd_fingerprint_sha256=_HEX_FTD_FP,
        biscuit_root_pubkey_hex=_HEX_PK,
        matched_issuer_kid="kid-1",
        verified_at=verified_at,
    )


def _make_hop_entry(
    source_ftd_id: str,
    target_ftd_id: str,
    *,
    active_from: datetime = _ROUTE_ACTIVE_FROM,
    active_until=_ROUTE_ACTIVE_UNTIL,
    wat_anchor_manifest_id: str = "wat-manifest-2026-05-07-h12",
) -> RouteRegistryEntry:
    """Construct a chain-hop registry entry under the canonical
    ``derive_chain_hop_route_id`` route_id derivation."""
    return RouteRegistryEntry(
        route_id=derive_chain_hop_route_id(source_ftd_id, target_ftd_id),
        source_ftd_id=source_ftd_id,
        active_from=active_from,
        active_until=active_until,
        wat_anchor_manifest_id=wat_anchor_manifest_id,
    )


def _make_context(
    *,
    ftd_id: str = _FTD_ID,
    routes: list = None,
    eval_now: datetime = None,
) -> FederationContext:
    registry = InMemoryRouteRegistry()
    for entry in routes or []:
        registry.add(entry)
    return FederationContext.from_resolve(
        _make_resolve(ftd_id=ftd_id),
        registry,
        eval_now=eval_now,
    )


# ---------------------------------------------------------------------------
# T-N3-01 argument-shape gate
# ---------------------------------------------------------------------------


def test_t_n3_01_argument_shape_gate():
    """T-N3-01: malformed target / hop arguments rejected at gate."""
    ctx = _make_context()
    walker = ChainWalker(ctx)

    # Empty target.
    with pytest.raises(ChainWalkerArgumentError):
        walker.walk("")

    # Non-DID target.
    with pytest.raises(ChainWalkerArgumentError):
        walker.walk("not-a-did")

    # Non-string target.
    with pytest.raises(ChainWalkerArgumentError):
        walker.walk(None)  # type: ignore[arg-type]

    # Empty intermediate FTD id.
    with pytest.raises(ChainWalkerArgumentError):
        walker.walk(_TARGET_FTD_ID, ("",))

    # Non-DID intermediate.
    with pytest.raises(ChainWalkerArgumentError):
        walker.walk(_TARGET_FTD_ID, ("not-a-did",))

    # max_depth must be non-negative int.
    with pytest.raises(ChainWalkerArgumentError):
        ChainWalker(ctx, max_depth=-1)


# ---------------------------------------------------------------------------
# T-N3-02 zero-hop walk
# ---------------------------------------------------------------------------


def test_t_n3_02_zero_hop_walk_accepts():
    """T-N3-02: target == ctx FTD id with no intermediates -> empty hops."""
    ctx = _make_context()
    walker = ChainWalker(ctx)

    verdict = walker.walk(_FTD_ID)
    assert isinstance(verdict, ChainVerdict)
    assert verdict.target_ftd_id == _FTD_ID
    assert verdict.hops == ()
    assert verdict.wat_anchor_chain == ()
    assert verdict.depth == 0


# ---------------------------------------------------------------------------
# T-N3-03 single-hop happy path
# ---------------------------------------------------------------------------


def test_t_n3_03_single_hop_chain_accepts():
    """T-N3-03: single intermediate hop with active route -> accept."""
    # Chain: ctx (_FTD_ID) -> _HOP_A_FTD_ID (target).
    # We reach the target directly; intermediate sequence is empty
    # but target != ctx so we have one hop.
    routes = [_make_hop_entry(_FTD_ID, _HOP_A_FTD_ID)]
    ctx = _make_context(
        routes=routes,
        eval_now=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    walker = ChainWalker(ctx)

    verdict = walker.walk(_HOP_A_FTD_ID)
    assert verdict.target_ftd_id == _HOP_A_FTD_ID
    assert verdict.depth == 1
    assert len(verdict.hops) == 1
    hop = verdict.hops[0]
    assert hop.hop_index == 0
    assert hop.source_ftd_id == _FTD_ID
    assert hop.target_ftd_id == _HOP_A_FTD_ID
    assert hop.route_id == derive_chain_hop_route_id(_FTD_ID, _HOP_A_FTD_ID)
    assert hop.wat_anchor_manifest_id == "wat-manifest-2026-05-07-h12"


# ---------------------------------------------------------------------------
# T-N3-04 two-hop chain happy path
# ---------------------------------------------------------------------------


def test_t_n3_04_two_hop_chain_accepts():
    """T-N3-04: 2-hop chain (ctx -> A -> target) accepts; anchors surfaced."""
    routes = [
        _make_hop_entry(_FTD_ID, _HOP_A_FTD_ID, wat_anchor_manifest_id="wat-h1"),
        _make_hop_entry(_HOP_A_FTD_ID, _TARGET_FTD_ID, wat_anchor_manifest_id="wat-h2"),
    ]
    ctx = _make_context(
        routes=routes,
        eval_now=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    walker = ChainWalker(ctx)

    verdict = walker.walk(_TARGET_FTD_ID, (_HOP_A_FTD_ID,))
    assert verdict.target_ftd_id == _TARGET_FTD_ID
    assert verdict.depth == 2
    assert verdict.wat_anchor_chain == ("wat-h1", "wat-h2")

    h0, h1 = verdict.hops
    assert h0.source_ftd_id == _FTD_ID
    assert h0.target_ftd_id == _HOP_A_FTD_ID
    assert h0.hop_index == 0
    assert h1.source_ftd_id == _HOP_A_FTD_ID
    assert h1.target_ftd_id == _TARGET_FTD_ID
    assert h1.hop_index == 1


# ---------------------------------------------------------------------------
# T-N3-05 three-hop chain happy path
# ---------------------------------------------------------------------------


def test_t_n3_05_three_hop_chain_accepts():
    """T-N3-05: 3-hop chain (ctx -> A -> B -> target) accepts under default max_depth=4."""
    routes = [
        _make_hop_entry(_FTD_ID, _HOP_A_FTD_ID),
        _make_hop_entry(_HOP_A_FTD_ID, _HOP_B_FTD_ID),
        _make_hop_entry(_HOP_B_FTD_ID, _TARGET_FTD_ID),
    ]
    ctx = _make_context(
        routes=routes,
        eval_now=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    walker = ChainWalker(ctx)
    assert walker.max_depth == MAX_DEPTH_DEFAULT == 4

    verdict = walker.walk(
        _TARGET_FTD_ID,
        (_HOP_A_FTD_ID, _HOP_B_FTD_ID),
    )
    assert verdict.depth == 3
    assert [h.target_ftd_id for h in verdict.hops] == [
        _HOP_A_FTD_ID,
        _HOP_B_FTD_ID,
        _TARGET_FTD_ID,
    ]


# ---------------------------------------------------------------------------
# T-N3-06 depth violation
# ---------------------------------------------------------------------------


def test_t_n3_06_depth_violation_rejected():
    """T-N3-06: chain longer than max_depth -> ChainWalkerDepthError."""
    routes = [
        _make_hop_entry(_FTD_ID, _HOP_A_FTD_ID),
        _make_hop_entry(_HOP_A_FTD_ID, _HOP_B_FTD_ID),
        _make_hop_entry(_HOP_B_FTD_ID, _HOP_C_FTD_ID),
        _make_hop_entry(_HOP_C_FTD_ID, _TARGET_FTD_ID),
    ]
    ctx = _make_context(
        routes=routes,
        eval_now=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    # max_depth=2 with a 4-hop chain -> reject.
    walker = ChainWalker(ctx, max_depth=2)
    with pytest.raises(ChainWalkerDepthError):
        walker.walk(
            _TARGET_FTD_ID,
            (_HOP_A_FTD_ID, _HOP_B_FTD_ID, _HOP_C_FTD_ID),
        )


# ---------------------------------------------------------------------------
# T-N3-07 cycle detection
# ---------------------------------------------------------------------------


def test_t_n3_07_cycle_detection_rejected():
    """T-N3-07: chain re-visits an FTD id -> ChainWalkerCycleError."""
    # ctx -> A -> B -> A -> target (re-visits A).
    routes = [
        _make_hop_entry(_FTD_ID, _HOP_A_FTD_ID),
        _make_hop_entry(_HOP_A_FTD_ID, _HOP_B_FTD_ID),
        _make_hop_entry(_HOP_B_FTD_ID, _HOP_A_FTD_ID),
        _make_hop_entry(_HOP_A_FTD_ID, _TARGET_FTD_ID),
    ]
    ctx = _make_context(
        routes=routes,
        eval_now=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    walker = ChainWalker(ctx)
    with pytest.raises(ChainWalkerCycleError):
        walker.walk(
            _TARGET_FTD_ID,
            (_HOP_A_FTD_ID, _HOP_B_FTD_ID, _HOP_A_FTD_ID),
        )

    # Direct ctx-revisit cycle: target == ctx but with intermediates.
    with pytest.raises(ChainWalkerCycleError):
        walker.walk(_FTD_ID, (_HOP_A_FTD_ID,))


# ---------------------------------------------------------------------------
# T-N3-08 missing route
# ---------------------------------------------------------------------------


def test_t_n3_08_missing_route_rejected():
    """T-N3-08: a hop's canonical route_id missing from registry ->
    FederationRouteUnknownError."""
    # First hop registered, second hop not.
    routes = [
        _make_hop_entry(_FTD_ID, _HOP_A_FTD_ID),
        # Intentionally omit the A->target hop.
    ]
    ctx = _make_context(
        routes=routes,
        eval_now=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    walker = ChainWalker(ctx)
    with pytest.raises(FederationRouteUnknownError):
        walker.walk(_TARGET_FTD_ID, (_HOP_A_FTD_ID,))


# ---------------------------------------------------------------------------
# T-N3-09 determinism
# ---------------------------------------------------------------------------


def test_t_n3_09_determinism():
    """T-N3-09: two walks over identical inputs yield identical verdicts."""
    routes = [
        _make_hop_entry(_FTD_ID, _HOP_A_FTD_ID, wat_anchor_manifest_id="wat-h1"),
        _make_hop_entry(_HOP_A_FTD_ID, _TARGET_FTD_ID, wat_anchor_manifest_id="wat-h2"),
    ]
    ctx = _make_context(
        routes=routes,
        eval_now=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    walker = ChainWalker(ctx)

    v1 = walker.walk(_TARGET_FTD_ID, (_HOP_A_FTD_ID,))
    v2 = walker.walk(_TARGET_FTD_ID, (_HOP_A_FTD_ID,))
    assert v1 == v2
    assert v1.hops == v2.hops
    assert v1.wat_anchor_chain == v2.wat_anchor_chain


# ---------------------------------------------------------------------------
# T-N3-10 source-FTD mismatch
# ---------------------------------------------------------------------------


def test_t_n3_10_source_ftd_mismatch_rejected():
    """T-N3-10: registered hop with wrong source_ftd_id -> unknown-route."""
    # Construct an entry whose route_id matches the canonical
    # derivation but whose source_ftd_id field is intentionally wrong.
    bad_entry = RouteRegistryEntry(
        route_id=derive_chain_hop_route_id(_FTD_ID, _HOP_A_FTD_ID),
        source_ftd_id="did:web:imposter.dev:ftd:v1",
        active_from=_ROUTE_ACTIVE_FROM,
        active_until=_ROUTE_ACTIVE_UNTIL,
    )
    ctx = _make_context(
        routes=[bad_entry],
        eval_now=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    walker = ChainWalker(ctx)
    with pytest.raises(FederationRouteUnknownError):
        walker.walk(_HOP_A_FTD_ID)


# ---------------------------------------------------------------------------
# Aux probes
# ---------------------------------------------------------------------------


def test_t_n3_aux_expired_hop_rejected():
    """T-N3-aux-expired-hop: route registered but window does not
    include eval_now -> FederationRouteExpiredError."""
    expired_route = _make_hop_entry(
        _FTD_ID,
        _HOP_A_FTD_ID,
        active_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        active_until=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    ctx = _make_context(
        routes=[expired_route],
        eval_now=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    walker = ChainWalker(ctx)
    with pytest.raises(FederationRouteExpiredError):
        walker.walk(_HOP_A_FTD_ID)


def test_t_n3_aux_derive_helper():
    """T-N3-aux-derive-helper: helper validates and concatenates."""
    rid = derive_chain_hop_route_id(_FTD_ID, _HOP_A_FTD_ID)
    assert rid == f"{_FTD_ID}{CHAIN_HOP_SEPARATOR}{_HOP_A_FTD_ID}"
    assert CHAIN_HOP_SEPARATOR == "-|->"

    # Argument validation.
    with pytest.raises(ChainWalkerArgumentError):
        derive_chain_hop_route_id("", _HOP_A_FTD_ID)
    with pytest.raises(ChainWalkerArgumentError):
        derive_chain_hop_route_id(_FTD_ID, "")
    with pytest.raises(ChainWalkerArgumentError):
        derive_chain_hop_route_id("not-a-did", _HOP_A_FTD_ID)
    with pytest.raises(ChainWalkerArgumentError):
        derive_chain_hop_route_id(_FTD_ID, "not-a-did")


def test_t_n3_aux_walk_fn_equivalent():
    """T-N3-aux-walk-fn: convenience function yields the same verdict
    as the class-form walker."""
    routes = [
        _make_hop_entry(_FTD_ID, _HOP_A_FTD_ID),
        _make_hop_entry(_HOP_A_FTD_ID, _TARGET_FTD_ID),
    ]
    ctx = _make_context(
        routes=routes,
        eval_now=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )

    class_verdict = ChainWalker(ctx).walk(_TARGET_FTD_ID, (_HOP_A_FTD_ID,))
    fn_verdict = walk_delegation_chain(
        ctx, _TARGET_FTD_ID, (_HOP_A_FTD_ID,)
    )
    assert class_verdict == fn_verdict


def test_t_n3_aux_zero_hop_via_intermediates_only_cycle():
    """Defensive: ctx in intermediates triggers cycle even with
    distinct target."""
    ctx = _make_context()
    walker = ChainWalker(ctx)
    # Intermediate is the ctx FTD itself -> cycle.
    with pytest.raises(ChainWalkerCycleError):
        walker.walk(_HOP_A_FTD_ID, (_FTD_ID,))


def test_t_n3_aux_peer_org_mismatch_unreachable_branch_handled():
    """Defensive: zero-hop with target != ctx is impossible by
    construction (cycle detection catches it as same-FTD-twice would
    be needed). Verify the cycle path covers this case."""
    # If target != ctx and intermediates is empty, full_sequence is
    # (ctx, target), distinct entries, so no cycle and hop_count == 1.
    # Then the walker tries to look up the canonical hop route_id;
    # with empty registry it raises FederationRouteUnknownError, NOT
    # PeerOrgMismatchError. This test pins that contract: the
    # zero-hop PeerOrgMismatchError branch is defensive-only.
    ctx = _make_context()
    walker = ChainWalker(ctx)
    with pytest.raises(FederationRouteUnknownError):
        walker.walk(_HOP_A_FTD_ID)
    # Sanity: PeerOrgMismatchError remains importable but is not the
    # raised type for the empty-registry single-hop case above.
    assert PeerOrgMismatchError is not None
