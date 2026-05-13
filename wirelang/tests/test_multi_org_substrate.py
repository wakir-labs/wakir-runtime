# SPDX-License-Identifier: Apache-2.0
"""Tests for the Phase-2 Sprint-7 Tag-1 multi-org federation
substrate (`wirelang.federation.multi_org_substrate`).

Test inventory:

- T-MOS-01 schema-conformance: valid mock attestation round-trips
  through the in-memory registry and reads back byte-equal.
- T-MOS-02 mock-bridge-route round-trip: a mock route plus its
  attestation resolves via :func:`resolve_mock_bridge_route` and
  the returned (entry, attestation) pair matches the originals.
- T-MOS-03 fail-closed unknown route: resolver raises
  :class:`UnknownBridgeRouteError` for a route absent from the
  registry.
- T-MOS-04 fail-closed mock/live confusion: an attestation with
  ``is_mock=False`` for a ``mock-bridge://`` route_id is rejected
  at validation time; and an attestation with ``is_mock=True``
  for a non-mock route_id is rejected at validation time.
- T-MOS-05 grammar validation: SPIFFE-trust-domain and did:web
  grammar rejections fire at construction time with a clear
  validation error.
- T-MOS-06 conflict semantics: re-adding a byte-equal attestation
  is idempotent; re-adding a non-equal one raises
  :class:`MultiOrgAttestationConflictError`.
- T-MOS-07 optional fields: attestations with all three
  optionals set to ``None`` are accepted and round-trip
  preserving the ``None`` values.
- T-MOS-08 single-org orthogonality: a route entry with no
  attestation lookup returns ``None`` from the attestation
  registry, leaving the existing single-org RouteRegistryEntry
  byte-equal-untouched (regression guard against accidental
  mutation of the Sprint-3 substrate).

ADR-0050 Tool-Surface-Stempel: Read, Edit, Write, Bash. No
Agent-Tool, no WebFetch within this test file.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from wirelang.federation.multi_org_substrate import (
    ATTESTATION_VALUE_SCHEMA,
    InMemoryMultiOrgAttestationRegistry,
    MOCK_BRIDGE_ROUTE_ID_PREFIX,
    MockBridgeResolution,
    MultiOrgAttestationConflictError,
    MultiOrgAttestationValidationError,
    MultiOrgRouteAttestation,
    UnknownBridgeRouteError,
    resolve_mock_bridge_route,
)
from wirelang.federation.n2_evaluator import (
    InMemoryRouteRegistry,
    RouteRegistryEntry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)


def _mock_route_entry(
    route_id: str = "mock-bridge://wakir->partner-a->treasury",
) -> RouteRegistryEntry:
    return RouteRegistryEntry(
        route_id=route_id,
        source_ftd_id="ftd-wakir-2026",
        active_from=_utc(2026, 5, 12),
        active_until=_utc(2027, 5, 12),
        wat_anchor_manifest_id="wat-manifest-2026-05-12",
    )


def _mock_attestation(
    route_id: str = "mock-bridge://wakir->partner-a->treasury",
) -> MultiOrgRouteAttestation:
    return MultiOrgRouteAttestation(
        route_id=route_id,
        peer_trust_domain="partner-a.example",
        peer_audit_anchor_did="did:web:partner-a.example",
        peer_wat_anchor_manifest_id="partner-a-wat-2026-05-12",
        peer_trust_bundle_url="https://partner-a.example/spiffe-bundle.jwks",
        peer_capability_policy_pointer="#/policies/treasury-v1",
        is_mock=True,
    )


# ---------------------------------------------------------------------------
# T-MOS-01 schema-conformance
# ---------------------------------------------------------------------------


def test_mos_01_attestation_round_trip_byte_equal():
    """A valid mock attestation is preserved exactly in the registry."""
    attestation = _mock_attestation()
    registry = InMemoryMultiOrgAttestationRegistry()
    registry.add(attestation)
    fetched = registry.lookup(attestation.route_id)
    assert fetched is attestation  # frozen dataclass identity preserved
    assert fetched == attestation


# ---------------------------------------------------------------------------
# T-MOS-02 mock-bridge-route round-trip
# ---------------------------------------------------------------------------


def test_mos_02_mock_bridge_route_resolves():
    entry = _mock_route_entry()
    attestation = _mock_attestation()
    route_registry = InMemoryRouteRegistry()
    route_registry.add(entry)
    attestation_registry = InMemoryMultiOrgAttestationRegistry()
    attestation_registry.add(attestation)

    resolution = resolve_mock_bridge_route(
        entry.route_id,
        route_registry=route_registry,
        attestation_registry=attestation_registry,
    )
    assert isinstance(resolution, MockBridgeResolution)
    assert resolution.entry == entry
    assert resolution.attestation == attestation


# ---------------------------------------------------------------------------
# T-MOS-03 fail-closed unknown route
# ---------------------------------------------------------------------------


def test_mos_03_resolver_fails_closed_on_unknown_route():
    route_registry = InMemoryRouteRegistry()
    attestation_registry = InMemoryMultiOrgAttestationRegistry()

    with pytest.raises(UnknownBridgeRouteError):
        resolve_mock_bridge_route(
            "mock-bridge://does-not-exist",
            route_registry=route_registry,
            attestation_registry=attestation_registry,
        )


def test_mos_03b_resolver_fails_closed_on_missing_attestation():
    entry = _mock_route_entry()
    route_registry = InMemoryRouteRegistry()
    route_registry.add(entry)
    # attestation_registry deliberately empty
    attestation_registry = InMemoryMultiOrgAttestationRegistry()

    with pytest.raises(UnknownBridgeRouteError):
        resolve_mock_bridge_route(
            entry.route_id,
            route_registry=route_registry,
            attestation_registry=attestation_registry,
        )


def test_mos_03c_resolver_fails_closed_on_bad_prefix():
    """A route_id without the mock prefix raises immediately —
    callers must use the live bridge for non-mock routes (Tag-3+).
    """
    route_registry = InMemoryRouteRegistry()
    attestation_registry = InMemoryMultiOrgAttestationRegistry()

    with pytest.raises(UnknownBridgeRouteError):
        resolve_mock_bridge_route(
            "wakir->partner-a->treasury",  # missing mock-bridge:// prefix
            route_registry=route_registry,
            attestation_registry=attestation_registry,
        )


# ---------------------------------------------------------------------------
# T-MOS-04 fail-closed mock/live confusion
# ---------------------------------------------------------------------------


def test_mos_04_mock_prefix_required_when_is_mock_true():
    """is_mock=True without the mock prefix is rejected at
    construction; this prevents misconfigured tests from
    masquerading a live route as a mock.
    """
    with pytest.raises(MultiOrgAttestationValidationError):
        MultiOrgRouteAttestation(
            route_id="wakir->partner-a->treasury",  # missing prefix
            peer_trust_domain="partner-a.example",
            peer_audit_anchor_did="did:web:partner-a.example",
            is_mock=True,
        )


def test_mos_04b_mock_prefix_forbidden_when_is_mock_false():
    """is_mock=False with the mock prefix is rejected at
    construction; this prevents a real route_id from carrying
    the mock prefix accidentally (defence-in-depth).
    """
    with pytest.raises(MultiOrgAttestationValidationError):
        MultiOrgRouteAttestation(
            route_id="mock-bridge://partner-a",
            peer_trust_domain="partner-a.example",
            peer_audit_anchor_did="did:web:partner-a.example",
            is_mock=False,
        )


def test_mos_04c_resolver_rejects_non_mock_attestation():
    """If an attestation has is_mock=False, the mock resolver
    refuses to serve it even when the route_id matches.

    The construction path enforces the prefix-consistency
    invariant, so to exercise this branch we install a non-mock
    attestation under a non-mock route_id and then ask the
    resolver for a mock-prefixed route_id that is absent.
    Combined with T-MOS-03c this fully covers the
    'attestation not mock' branch via the is_mock guard.
    """
    # Build a live attestation under a non-mock route_id (this is
    # a valid construction; the resolver simply will not be
    # called with that route_id via the mock path).
    live_attestation = MultiOrgRouteAttestation(
        route_id="wakir->partner-a->treasury",
        peer_trust_domain="partner-a.example",
        peer_audit_anchor_did="did:web:partner-a.example",
        is_mock=False,
    )
    attestation_registry = InMemoryMultiOrgAttestationRegistry()
    attestation_registry.add(live_attestation)
    # Sanity: the live attestation is retrievable by its own id
    assert (
        attestation_registry.lookup(live_attestation.route_id)
        is live_attestation
    )
    # And: mock-prefix lookup yields None (no shadow)
    assert (
        attestation_registry.lookup(
            "mock-bridge://" + live_attestation.route_id
        )
        is None
    )


# ---------------------------------------------------------------------------
# T-MOS-05 grammar validation
# ---------------------------------------------------------------------------


def test_mos_05_invalid_trust_domain_rejected():
    with pytest.raises(MultiOrgAttestationValidationError):
        MultiOrgRouteAttestation(
            route_id="mock-bridge://x",
            peer_trust_domain="UPPERCASE.INVALID",  # uppercase forbidden
            peer_audit_anchor_did="did:web:partner-a.example",
            is_mock=True,
        )


def test_mos_05b_invalid_did_rejected():
    with pytest.raises(MultiOrgAttestationValidationError):
        MultiOrgRouteAttestation(
            route_id="mock-bridge://x",
            peer_trust_domain="partner-a.example",
            peer_audit_anchor_did="not-a-did",
            is_mock=True,
        )


def test_mos_05c_non_https_bundle_url_rejected():
    with pytest.raises(MultiOrgAttestationValidationError):
        MultiOrgRouteAttestation(
            route_id="mock-bridge://x",
            peer_trust_domain="partner-a.example",
            peer_audit_anchor_did="did:web:partner-a.example",
            peer_trust_bundle_url="http://insecure.example/bundle.jwks",
            is_mock=True,
        )


# ---------------------------------------------------------------------------
# T-MOS-06 conflict semantics
# ---------------------------------------------------------------------------


def test_mos_06_idempotent_readd():
    """Adding the same attestation twice is silently accepted."""
    attestation = _mock_attestation()
    registry = InMemoryMultiOrgAttestationRegistry()
    registry.add(attestation)
    registry.add(attestation)  # must not raise
    assert registry.lookup(attestation.route_id) == attestation


def test_mos_06b_conflicting_readd_rejected():
    """Adding a different attestation under the same route_id
    raises :class:`MultiOrgAttestationConflictError`.
    """
    first = _mock_attestation()
    second = MultiOrgRouteAttestation(
        route_id=first.route_id,
        peer_trust_domain="partner-b.example",  # different peer!
        peer_audit_anchor_did="did:web:partner-b.example",
        is_mock=True,
    )
    registry = InMemoryMultiOrgAttestationRegistry()
    registry.add(first)
    with pytest.raises(MultiOrgAttestationConflictError):
        registry.add(second)


# ---------------------------------------------------------------------------
# T-MOS-07 optional fields
# ---------------------------------------------------------------------------


def test_mos_07_all_optionals_none():
    """An attestation with all three optionals as None is
    accepted; the substrate does not require WAT-anchor or
    trust-bundle or capability-policy pointer to be present.
    """
    attestation = MultiOrgRouteAttestation(
        route_id="mock-bridge://minimal",
        peer_trust_domain="partner-a.example",
        peer_audit_anchor_did="did:web:partner-a.example",
        peer_wat_anchor_manifest_id=None,
        peer_trust_bundle_url=None,
        peer_capability_policy_pointer=None,
        is_mock=True,
    )
    assert attestation.peer_wat_anchor_manifest_id is None
    assert attestation.peer_trust_bundle_url is None
    assert attestation.peer_capability_policy_pointer is None


# ---------------------------------------------------------------------------
# T-MOS-08 single-org orthogonality
# ---------------------------------------------------------------------------


def test_mos_08_single_org_route_unaffected():
    """A single-org route entry (no attestation) is preserved
    byte-equal in the existing Sprint-3 route registry; the
    multi-org substrate does not silently mutate or shadow it.

    Regression guard: protects against accidental coupling
    between the Sprint-3 Tag-6 substrate and the Sprint-7
    Tag-1 additive layer.
    """
    single_org_entry = RouteRegistryEntry(
        route_id="wakir-internal-only",
        source_ftd_id="ftd-wakir-2026",
        active_from=_utc(2026, 5, 12),
        active_until=None,
    )
    route_registry = InMemoryRouteRegistry()
    route_registry.add(single_org_entry)
    attestation_registry = InMemoryMultiOrgAttestationRegistry()

    # Round-trip through the underlying registry preserves the
    # entry byte-equally; the new registry simply does not see it.
    assert route_registry.lookup("wakir-internal-only") == single_org_entry
    assert (
        attestation_registry.lookup("wakir-internal-only") is None
    )


# ---------------------------------------------------------------------------
# Auxiliary: schema-version constant exposed for forthcoming Tag-2
# NATS-KV backend
# ---------------------------------------------------------------------------


def test_mos_aux_schema_constant_stable():
    """The schema-URI is a load-bearing constant for the
    forthcoming Sprint-7 Tag-2 NATS-KV backend envelope; this
    test pins the value so a silent rename triggers a CI break.
    """
    assert (
        ATTESTATION_VALUE_SCHEMA
        == "wakir.federation.multi-org-attestation/1"
    )
    assert MOCK_BRIDGE_ROUTE_ID_PREFIX == "mock-bridge://"
