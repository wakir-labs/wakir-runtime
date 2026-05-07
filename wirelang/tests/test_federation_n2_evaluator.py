# SPDX-License-Identifier: Apache-2.0
"""Determinism tests for the V-908 N2 federation predicate evaluator.

Phase-1b Sprint-2 Tag-3 (S2-2). Tests the live evaluator for
``peer_org`` and ``federation_route`` Datalog caveat predicates
specified in
``wirelang/specs/datalog-caveat-vocabulary-phase-2-skizze.md``
section 3.2 and implemented in
:mod:`wirelang.federation.n2_evaluator`.

The tests construct a :class:`FederatedResolveResult` directly
rather than running the full FTD/AIP pipeline, because:

1. The N2 evaluator is a pure layer over an already-verified
   resolve result (the freshness invariants are an upstream
   concern); and
2. The Phase-1b federation pipeline is exercised end-to-end by
   :mod:`wirelang.tests.test_dns_anchor` and the Tag-6 / Tag-7
   tests; this test module concentrates on the N2 evaluator's
   own determinism contract.

Test inventory (T-N2-01..10, all deterministic):

- T-N2-01: ``peer_org`` exact-match accept.
- T-N2-02: ``peer_org`` mismatch rejected (PeerOrgMismatchError).
- T-N2-03: ``peer_org`` malformed argument rejected
  (FederationPredicateArgumentError).
- T-N2-04: ``peer_org`` evaluator does NOT consult wall-clock
  (replay invariant).
- T-N2-05: ``federation_route`` known + active + matched
  source-FTD accepted.
- T-N2-06: ``federation_route`` unknown route rejected
  (FederationRouteUnknownError).
- T-N2-07: ``federation_route`` expired route rejected
  (FederationRouteExpiredError).
- T-N2-08: ``federation_route`` registry-pluggability via
  Protocol (custom registry honoured).
- T-N2-09: ``evaluate_all`` short-circuits on first failure.
- T-N2-10: re-running the same evaluator over the same context
  yields the same verdict (T-N2-10 determinism invariant).

Bonus sanity:

- T-N2-aux-route-source-mismatch: route registered under a
  different FTD is treated as unknown, not as a separate error
  type (forensics-clean distinction).
- T-N2-aux-empty-arg: empty-string predicates fail with the
  argument-error type, not with a registry miss.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from wirelang.federation.n2_evaluator import (
    FederationContext,
    FederationEvaluator,
    FederationPredicateArgumentError,
    FederationRouteExpiredError,
    FederationRouteUnknownError,
    InMemoryRouteRegistry,
    PeerOrgMismatchError,
    RouteRegistry,
    RouteRegistryEntry,
)
from wirelang.identity.federation_resolver import FederatedResolveResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_FTD_ID = "did:web:wakir.dev:ftd:v1"
_PEER_FTD_ID = "did:web:partner-a.dev:ftd:v1"
_AIP_ID = "aip:web:wakir.dev/treasury-issuer"
_VERIFIED_AT = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
_HEX_PK = "ab" * 32
_HEX_FP = "cd" * 32
_HEX_AIP_JCS = "ef" * 32
_HEX_FTD_FP = "12" * 32


def _make_resolve(ftd_id: str = _FTD_ID, *, verified_at: datetime = _VERIFIED_AT) -> FederatedResolveResult:
    """Construct a :class:`FederatedResolveResult` directly for tests."""
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


def _make_active_route(
    route_id: str = "wakir->partner-A->treasury",
    *,
    source_ftd_id: str = _FTD_ID,
    active_from: datetime = datetime(2026, 5, 1, tzinfo=timezone.utc),
    active_until: datetime = datetime(2026, 6, 1, tzinfo=timezone.utc),
) -> RouteRegistryEntry:
    return RouteRegistryEntry(
        route_id=route_id,
        source_ftd_id=source_ftd_id,
        active_from=active_from,
        active_until=active_until,
        wat_anchor_manifest_id="wat-manifest-2026-05-07-h12",
    )


def _make_evaluator(
    *,
    ftd_id: str = _FTD_ID,
    routes: list = None,
    eval_now: datetime = None,
) -> FederationEvaluator:
    registry = InMemoryRouteRegistry()
    for entry in routes or []:
        registry.add(entry)
    ctx = FederationContext.from_resolve(
        _make_resolve(ftd_id=ftd_id),
        registry,
        eval_now=eval_now,
    )
    return FederationEvaluator(ctx)


# ---------------------------------------------------------------------------
# T-N2-01..04 peer_org
# ---------------------------------------------------------------------------


def test_t_n2_01_peer_org_exact_match_accept():
    """T-N2-01: ``peer_org`` argument equals FTD id -> accept."""
    ev = _make_evaluator(routes=[_make_active_route()])
    assert ev.evaluate_peer_org(_FTD_ID) is True


def test_t_n2_02_peer_org_mismatch_rejected():
    """T-N2-02: ``peer_org`` argument != FTD id -> PeerOrgMismatchError."""
    ev = _make_evaluator()
    with pytest.raises(PeerOrgMismatchError):
        ev.evaluate_peer_org(_PEER_FTD_ID)


def test_t_n2_03_peer_org_malformed_rejected():
    """T-N2-03: malformed argument fails at argument-shape gate."""
    ev = _make_evaluator()
    # not a DID URI at all
    with pytest.raises(FederationPredicateArgumentError):
        ev.evaluate_peer_org("not-a-did")
    # empty string
    with pytest.raises(FederationPredicateArgumentError):
        ev.evaluate_peer_org("")
    # wrong type
    with pytest.raises(FederationPredicateArgumentError):
        ev.evaluate_peer_org(None)  # type: ignore[arg-type]


def test_t_n2_04_peer_org_no_wall_clock_consultation():
    """T-N2-04: ``peer_org`` is independent of ``eval_now``.

    Replay invariant: the verdict on ``peer_org`` MUST be the
    same across two evaluators that share the same context but
    differ in ``eval_now``. The predicate is windowed by FTD
    verify, not by the evaluator clock.
    """
    early = datetime(2026, 4, 1, tzinfo=timezone.utc)
    late = datetime(2026, 7, 1, tzinfo=timezone.utc)

    ev_early = _make_evaluator(eval_now=early)
    ev_late = _make_evaluator(eval_now=late)
    assert ev_early.evaluate_peer_org(_FTD_ID) is True
    assert ev_late.evaluate_peer_org(_FTD_ID) is True


# ---------------------------------------------------------------------------
# T-N2-05..08 federation_route
# ---------------------------------------------------------------------------


def test_t_n2_05_federation_route_known_active_accepted():
    """T-N2-05: known + active + same-FTD -> accept."""
    route = _make_active_route()
    ev = _make_evaluator(
        routes=[route],
        eval_now=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert ev.evaluate_federation_route(route.route_id) is True


def test_t_n2_06_federation_route_unknown_rejected():
    """T-N2-06: registry miss -> FederationRouteUnknownError."""
    ev = _make_evaluator(routes=[])
    with pytest.raises(FederationRouteUnknownError):
        ev.evaluate_federation_route("wakir->unknown->somewhere")


def test_t_n2_07_federation_route_expired_rejected():
    """T-N2-07: registry hit but window in the past -> expired."""
    expired = _make_active_route(
        route_id="wakir->expired->retired",
        active_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
        active_until=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    ev = _make_evaluator(
        routes=[expired],
        eval_now=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(FederationRouteExpiredError):
        ev.evaluate_federation_route(expired.route_id)


def test_t_n2_08_federation_route_registry_protocol_pluggability():
    """T-N2-08: a custom :class:`RouteRegistry` impl is honoured.

    Demonstrates the Protocol contract: any object with a
    ``lookup(str) -> Optional[RouteRegistryEntry]`` method works,
    not just :class:`InMemoryRouteRegistry`.
    """

    class _CustomRegistry:
        def __init__(self, entry: RouteRegistryEntry) -> None:
            self._entry = entry

        def lookup(self, route_id: str):
            if route_id == self._entry.route_id:
                return self._entry
            return None

    route = _make_active_route(route_id="custom->route->path")
    custom = _CustomRegistry(route)
    assert isinstance(custom, RouteRegistry)  # runtime_checkable contract
    ctx = FederationContext.from_resolve(
        _make_resolve(),
        custom,
        eval_now=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    ev = FederationEvaluator(ctx)
    assert ev.evaluate_federation_route("custom->route->path") is True
    with pytest.raises(FederationRouteUnknownError):
        ev.evaluate_federation_route("not->in->custom")


# ---------------------------------------------------------------------------
# T-N2-09 evaluate_all short-circuit
# ---------------------------------------------------------------------------


def test_t_n2_09_evaluate_all_short_circuits_on_first_failure():
    """T-N2-09: ``evaluate_all`` raises on first failure (Biscuit-Datalog
    abort-on-failed-caveat semantics).
    """
    route = _make_active_route()
    ev = _make_evaluator(routes=[route])
    # both succeed: returns the verdict tuple
    verdicts = ev.evaluate_all(
        peer_org_arg=_FTD_ID,
        federation_route_arg=route.route_id,
    )
    assert verdicts == (True, True)

    # peer_org fails: federation_route is NOT evaluated
    with pytest.raises(PeerOrgMismatchError):
        ev.evaluate_all(
            peer_org_arg=_PEER_FTD_ID,
            federation_route_arg="wakir->never->reached",
        )

    # peer_org omitted: only federation_route runs
    verdicts = ev.evaluate_all(federation_route_arg=route.route_id)
    assert verdicts == (True,)


# ---------------------------------------------------------------------------
# T-N2-10 re-run determinism
# ---------------------------------------------------------------------------


def test_t_n2_10_re_run_determinism():
    """T-N2-10: two re-runs over the same context yield identical
    verdicts. This is the structural determinism invariant the
    N2 evaluator promises.
    """
    route = _make_active_route()
    ev = _make_evaluator(
        routes=[route],
        eval_now=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    first = ev.evaluate_all(peer_org_arg=_FTD_ID, federation_route_arg=route.route_id)
    second = ev.evaluate_all(peer_org_arg=_FTD_ID, federation_route_arg=route.route_id)
    third = ev.evaluate_all(peer_org_arg=_FTD_ID, federation_route_arg=route.route_id)
    assert first == second == third == (True, True)


# ---------------------------------------------------------------------------
# Bonus sanity probes
# ---------------------------------------------------------------------------


def test_t_n2_aux_route_source_mismatch_treated_as_unknown():
    """Route registered under a different FTD is unknown from this
    context's vantage point. Sanity-probe of the forensics-clean
    distinction in the spec.
    """
    foreign = _make_active_route(
        route_id="wakir->partner-A->treasury",
        source_ftd_id=_PEER_FTD_ID,
    )
    ev = _make_evaluator(routes=[foreign])
    with pytest.raises(FederationRouteUnknownError):
        ev.evaluate_federation_route(foreign.route_id)


def test_t_n2_aux_empty_arg_argument_error_not_unknown():
    """Empty / non-string argument fails at the argument-shape gate,
    NOT as a registry-unknown failure. This is the typed-error
    ladder the spec promises.
    """
    ev = _make_evaluator()
    with pytest.raises(FederationPredicateArgumentError):
        ev.evaluate_federation_route("")
    with pytest.raises(FederationPredicateArgumentError):
        ev.evaluate_federation_route(None)  # type: ignore[arg-type]


def test_t_n2_aux_route_window_boundary_lower_inclusive():
    """``is_active_at`` is inclusive at ``active_from`` boundary."""
    boundary = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
    route = _make_active_route(
        route_id="wakir->boundary->lower",
        active_from=boundary,
        active_until=boundary + timedelta(days=30),
    )
    ev = _make_evaluator(routes=[route], eval_now=boundary)
    assert ev.evaluate_federation_route(route.route_id) is True


def test_t_n2_aux_route_window_boundary_upper_exclusive():
    """``is_active_at`` is exclusive at ``active_until`` boundary."""
    upper = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    route = _make_active_route(
        route_id="wakir->boundary->upper",
        active_from=upper - timedelta(days=30),
        active_until=upper,
    )
    ev = _make_evaluator(routes=[route], eval_now=upper)
    with pytest.raises(FederationRouteExpiredError):
        ev.evaluate_federation_route(route.route_id)
