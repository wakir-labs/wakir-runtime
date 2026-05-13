# SPDX-License-Identifier: BUSL-1.1
"""Tests for the Phase-2 Sprint-7 Tag-3 SPIFFE Cross-Trust-Domain
Bridge (``wirelang.federation.spiffe_cross_trust_domain_bridge``).

Test inventory (T-SCTDB-01..10):

- T-SCTDB-01 happy-path resolve (peer-SVID + local-SVID).
- T-SCTDB-02 unknown route_id in route-registry -> UnknownBridgeRouteError.
- T-SCTDB-03 missing attestation -> UnknownBridgeRouteError.
- T-SCTDB-04 mock attestation rejected -> UnknownBridgeRouteError
  (symmetric reject; the mock resolver remains the entry-point for
  is_mock=True attestations).
- T-SCTDB-05 attestation without peer_trust_bundle_url ->
  PeerTrustBundleFetchError.
- T-SCTDB-06 fetcher exception -> PeerTrustBundleFetchError with
  cause attached.
- T-SCTDB-07 fetched-bundle trust-domain mismatch ->
  PeerTrustBundleFetchError.
- T-SCTDB-08 stale bundle (older than bundle_max_age) ->
  PeerTrustBundleExpiredError.
- T-SCTDB-09 verifier rejection -> PeerSvidSignatureError with
  cause attached.
- T-SCTDB-10 SPIFFE-ID trust-domain prefix double-check ->
  PeerSvidSignatureError (verifier returned a SVID whose trust-
  domain segment does not match the attestation).

All tests are hermetic: no network, no FS. The bridge consumes
Protocol fakes built locally from the test-fixture classes
(``_FixedBundleFetcher`` etc.) exposed by the production module.

ADR-0050 Tool-Surface-Stempel: Read, Edit, Write, Bash. No
Agent-Tool, no WebFetch within this test file.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from wirelang.adapters.spiffe_workload_api import (
    JwtSvid,
    MockSpiffeWorkloadApiAdapter,
    MockSvidRecord,
    SpiffeAdapterError,
)
from wirelang.federation.multi_org_substrate import (
    InMemoryMultiOrgAttestationRegistry,
    MultiOrgRouteAttestation,
    UnknownBridgeRouteError,
)
from wirelang.federation.n2_evaluator import (
    InMemoryRouteRegistry,
    RouteRegistryEntry,
)
from wirelang.federation.spiffe_cross_trust_domain_bridge import (
    DEFAULT_BUNDLE_MAX_AGE_SECONDS,
    FetchedTrustBundle,
    LiveBridgeResolution,
    PeerSvidSignatureError,
    PeerTrustBundleExpiredError,
    PeerTrustBundleFetchError,
    SpiffeCrossTrustDomainBridge,
    VerifiedPeerSvid,
    _AcceptingVerifier,
    _FixedBundleFetcher,
    _RejectingVerifier,
)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)


_NOW = _utc(2026, 5, 12, 22)


def _fixed_clock(now: datetime = _NOW):
    def _clock() -> datetime:
        return now

    return _clock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_LIVE_ROUTE_ID = "wakir->partner-a->treasury-bridge-2026-05"
_PEER_TRUST_DOMAIN = "partner-a.example"
_PEER_DID = "did:web:partner-a.example"
_PEER_BUNDLE_URL = "https://partner-a.example/.well-known/spiffe-bundle"
_PEER_SPIFFE_ID = "spiffe://partner-a.example/service/treasury-bridge"


def _route_entry(route_id: str = _LIVE_ROUTE_ID) -> RouteRegistryEntry:
    return RouteRegistryEntry(
        route_id=route_id,
        source_ftd_id="ftd-wakir-2026",
        active_from=_utc(2026, 5, 12),
        active_until=_utc(2027, 5, 12),
        wat_anchor_manifest_id="wat-manifest-2026-05-12",
    )


def _live_attestation(
    route_id: str = _LIVE_ROUTE_ID,
    *,
    bundle_url: Optional[str] = _PEER_BUNDLE_URL,
    trust_domain: str = _PEER_TRUST_DOMAIN,
) -> MultiOrgRouteAttestation:
    return MultiOrgRouteAttestation(
        route_id=route_id,
        peer_trust_domain=trust_domain,
        peer_audit_anchor_did=_PEER_DID,
        peer_wat_anchor_manifest_id="peer-wat-manifest-2026-05-12",
        peer_trust_bundle_url=bundle_url,
        peer_capability_policy_pointer=None,
        is_mock=False,
    )


def _mock_attestation() -> MultiOrgRouteAttestation:
    return MultiOrgRouteAttestation(
        route_id="mock-bridge://wakir->partner-a->demo",
        peer_trust_domain=_PEER_TRUST_DOMAIN,
        peer_audit_anchor_did=_PEER_DID,
        is_mock=True,
    )


def _fresh_bundle(
    *,
    url: str = _PEER_BUNDLE_URL,
    trust_domain: str = _PEER_TRUST_DOMAIN,
    fetched_at: Optional[datetime] = None,
) -> FetchedTrustBundle:
    return FetchedTrustBundle(
        trust_domain=trust_domain,
        url=url,
        bundle_bytes=b'{"keys":[]}',
        fetched_at=fetched_at or (_NOW - timedelta(hours=1)),
    )


def _seed_registries(
    *,
    routes: list = None,
    attestations: list = None,
):
    route_registry = InMemoryRouteRegistry()
    for entry in routes or []:
        route_registry.add(entry)
    attestation_registry = InMemoryMultiOrgAttestationRegistry()
    for att in attestations or []:
        attestation_registry.add(att)
    return route_registry, attestation_registry


def _build_bridge(
    *,
    routes: list = None,
    attestations: list = None,
    bundles: Optional[dict] = None,
    verifier=None,
    local_adapter=None,
    bundle_max_age_seconds: int = DEFAULT_BUNDLE_MAX_AGE_SECONDS,
    clock=None,
) -> SpiffeCrossTrustDomainBridge:
    route_registry, attestation_registry = _seed_registries(
        routes=routes, attestations=attestations
    )
    fetcher = _FixedBundleFetcher(
        bundles=bundles if bundles is not None else {}
    )
    if verifier is None:
        verifier = _AcceptingVerifier(
            spiffe_id=_PEER_SPIFFE_ID,
            expires_at=_NOW + timedelta(minutes=10),
            clock_now=_NOW,
        )
    return SpiffeCrossTrustDomainBridge(
        route_registry=route_registry,
        attestation_registry=attestation_registry,
        trust_bundle_fetcher=fetcher,
        peer_svid_verifier=verifier,
        local_workload_adapter=local_adapter,
        bundle_max_age_seconds=bundle_max_age_seconds,
        clock=clock or _fixed_clock(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_t_sctdb_01_happy_path_peer_and_local_svid() -> None:
    """Bridge yields a complete :class:`LiveBridgeResolution` for a
    well-formed live attestation, with peer-SVID verified and a
    local-SVID fetched from the mock workload adapter.
    """
    bundle = _fresh_bundle()
    local_adapter = MockSpiffeWorkloadApiAdapter(
        records=(
            MockSvidRecord(
                spiffe_id="spiffe://wakir.local/service/treasury-bridge",
                token="local.svid.token",
            ),
        ),
    )
    bridge = _build_bridge(
        routes=[_route_entry()],
        attestations=[_live_attestation()],
        bundles={_PEER_BUNDLE_URL: bundle},
        local_adapter=local_adapter,
    )
    result = asyncio.run(
        bridge.resolve(
            _LIVE_ROUTE_ID,
            peer_svid_token="peer.svid.token",
            peer_svid_audience="spiffe://wakir.local/service/orchestrator",
        )
    )
    assert isinstance(result, LiveBridgeResolution)
    assert result.entry.route_id == _LIVE_ROUTE_ID
    assert result.attestation.is_mock is False
    assert result.trust_bundle is bundle
    assert isinstance(result.peer_svid, VerifiedPeerSvid)
    assert result.peer_svid.spiffe_id == _PEER_SPIFFE_ID
    assert result.peer_svid.token == "peer.svid.token"
    assert result.peer_svid.verified_at == _NOW
    assert isinstance(result.local_svid, JwtSvid)
    assert result.local_svid.spiffe_id == (
        "spiffe://wakir.local/service/treasury-bridge"
    )
    # The bridge requests the local SVID with the peer trust-domain
    # as audience; verify the audience surfaces correctly.
    assert _PEER_TRUST_DOMAIN in result.local_svid.audiences


def test_t_sctdb_02_unknown_route_id_in_route_registry() -> None:
    """An unknown ``route_id`` in the route registry surfaces as
    :class:`UnknownBridgeRouteError` from step 1.
    """
    bridge = _build_bridge(
        routes=[],
        attestations=[_live_attestation()],
        bundles={_PEER_BUNDLE_URL: _fresh_bundle()},
    )
    with pytest.raises(UnknownBridgeRouteError) as excinfo:
        asyncio.run(bridge.resolve(_LIVE_ROUTE_ID))
    assert "not in route registry" in str(excinfo.value)


def test_t_sctdb_03_missing_attestation() -> None:
    """A route present in the route-registry but absent from the
    attestation-registry surfaces as
    :class:`UnknownBridgeRouteError` from step 2.
    """
    bridge = _build_bridge(
        routes=[_route_entry()],
        attestations=[],
        bundles={_PEER_BUNDLE_URL: _fresh_bundle()},
    )
    with pytest.raises(UnknownBridgeRouteError) as excinfo:
        asyncio.run(bridge.resolve(_LIVE_ROUTE_ID))
    assert "no multi-org attestation" in str(excinfo.value)


def test_t_sctdb_04_mock_attestation_rejected() -> None:
    """A mock attestation surfaces as
    :class:`UnknownBridgeRouteError` from step 3 (symmetric reject
    with :func:`resolve_mock_bridge_route`).
    """
    mock_att = _mock_attestation()
    mock_route = _route_entry(route_id=mock_att.route_id)
    bridge = _build_bridge(
        routes=[mock_route],
        attestations=[mock_att],
        bundles={},  # mock path should reject before any fetch
    )
    with pytest.raises(UnknownBridgeRouteError) as excinfo:
        asyncio.run(bridge.resolve(mock_att.route_id))
    assert "attestation is a mock" in str(excinfo.value)
    assert "resolve_mock_bridge_route" in str(excinfo.value)


def test_t_sctdb_05_missing_peer_trust_bundle_url() -> None:
    """An attestation with ``peer_trust_bundle_url=None`` cannot be
    resolved live; surfaces as :class:`PeerTrustBundleFetchError`
    from step 4 with a clear message.
    """
    no_url_attestation = _live_attestation(bundle_url=None)
    bridge = _build_bridge(
        routes=[_route_entry()],
        attestations=[no_url_attestation],
        bundles={},
    )
    with pytest.raises(PeerTrustBundleFetchError) as excinfo:
        asyncio.run(bridge.resolve(_LIVE_ROUTE_ID))
    assert "no peer_trust_bundle_url" in str(excinfo.value)
    assert excinfo.value.url is None


def test_t_sctdb_06_fetcher_exception_propagates_as_fetch_error() -> None:
    """A fetcher exception is wrapped as
    :class:`PeerTrustBundleFetchError` with the original exception
    surfaced on :attr:`PeerTrustBundleFetchError.cause`.
    """
    # No bundles in the fetcher's canned dict -> KeyError on lookup.
    bridge = _build_bridge(
        routes=[_route_entry()],
        attestations=[_live_attestation()],
        bundles={},
    )
    with pytest.raises(PeerTrustBundleFetchError) as excinfo:
        asyncio.run(bridge.resolve(_LIVE_ROUTE_ID))
    assert excinfo.value.url == _PEER_BUNDLE_URL
    assert isinstance(excinfo.value.cause, KeyError)


def test_t_sctdb_07_fetched_bundle_trust_domain_mismatch() -> None:
    """A bundle whose trust-domain does not match the attestation
    is rejected as :class:`PeerTrustBundleFetchError`.
    """
    wrong_bundle = _fresh_bundle(trust_domain="attacker.example")
    bridge = _build_bridge(
        routes=[_route_entry()],
        attestations=[_live_attestation()],
        bundles={_PEER_BUNDLE_URL: wrong_bundle},
    )
    with pytest.raises(PeerTrustBundleFetchError) as excinfo:
        asyncio.run(bridge.resolve(_LIVE_ROUTE_ID))
    assert "does not match attestation trust_domain" in str(excinfo.value)


def test_t_sctdb_08_stale_bundle_rejected() -> None:
    """A bundle older than ``bundle_max_age_seconds`` surfaces as
    :class:`PeerTrustBundleExpiredError`. Test uses a 1-h ceiling
    and a bundle fetched 2 h ago.
    """
    stale = _fresh_bundle(
        fetched_at=_NOW - timedelta(hours=2),
    )
    bridge = _build_bridge(
        routes=[_route_entry()],
        attestations=[_live_attestation()],
        bundles={_PEER_BUNDLE_URL: stale},
        bundle_max_age_seconds=60 * 60,  # 1 hour
    )
    with pytest.raises(PeerTrustBundleExpiredError) as excinfo:
        asyncio.run(bridge.resolve(_LIVE_ROUTE_ID))
    assert excinfo.value.url == _PEER_BUNDLE_URL
    assert excinfo.value.max_age_seconds == 60 * 60


def test_t_sctdb_09_verifier_rejection_wrapped() -> None:
    """A verifier exception is wrapped as
    :class:`PeerSvidSignatureError` with the original exception on
    :attr:`PeerSvidSignatureError.cause`.
    """
    bridge = _build_bridge(
        routes=[_route_entry()],
        attestations=[_live_attestation()],
        bundles={_PEER_BUNDLE_URL: _fresh_bundle()},
        verifier=_RejectingVerifier(reason="bad sig"),
    )
    with pytest.raises(PeerSvidSignatureError) as excinfo:
        asyncio.run(
            bridge.resolve(
                _LIVE_ROUTE_ID, peer_svid_token="any.token"
            )
        )
    assert excinfo.value.trust_domain == _PEER_TRUST_DOMAIN
    # The original PeerSvidSignatureError from the verifier becomes
    # the cause of the outer (bridge-wrapped) PeerSvidSignatureError.
    assert isinstance(excinfo.value.cause, PeerSvidSignatureError)


def test_t_sctdb_10_spiffe_id_trust_domain_prefix_doublecheck() -> None:
    """A verifier that returns a SPIFFE-ID outside the expected
    trust-domain prefix is rejected. The bridge double-checks the
    verifier's result.
    """

    @dataclass(frozen=True)
    class _CrossDomainVerifier:
        async def verify(
            self,
            *,
            peer_svid_token: str,
            trust_bundle: FetchedTrustBundle,
            expected_trust_domain: str,
            expected_audience: Optional[str] = None,
        ) -> VerifiedPeerSvid:
            # Verifier claims success but returns a SPIFFE-ID from a
            # *different* trust-domain; the bridge MUST reject.
            return VerifiedPeerSvid(
                spiffe_id="spiffe://attacker.example/service/evil",
                token=peer_svid_token,
                audiences=(),
                expires_at=_NOW + timedelta(minutes=10),
                verified_at=_NOW,
            )

    bridge = _build_bridge(
        routes=[_route_entry()],
        attestations=[_live_attestation()],
        bundles={_PEER_BUNDLE_URL: _fresh_bundle()},
        verifier=_CrossDomainVerifier(),
    )
    with pytest.raises(PeerSvidSignatureError) as excinfo:
        asyncio.run(
            bridge.resolve(
                _LIVE_ROUTE_ID, peer_svid_token="any.token"
            )
        )
    assert "does not start with expected trust-domain prefix" in str(
        excinfo.value
    )
    assert excinfo.value.spiffe_id == (
        "spiffe://attacker.example/service/evil"
    )
    assert excinfo.value.trust_domain == _PEER_TRUST_DOMAIN
