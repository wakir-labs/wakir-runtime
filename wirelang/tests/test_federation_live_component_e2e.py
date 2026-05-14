# SPDX-License-Identifier: BUSL-1.1
"""Hermetic Live-Component E2E test for the Sprint-7 Multi-Org-Federation
substrate (Sprint-7 Pfad-B Tag-5).

Sprint-7 Tag-1..Tag-6 landed the Wirelang-side federation substrate
across six modules:

- Tag-1 :mod:`wirelang.federation.multi_org_substrate` (envelope +
  in-memory registry + mock-bridge resolver).
- Tag-2 :mod:`wirelang.federation.multi_org_attestation_nats_kv_backend`
  (durable NATS-KV backend; CAS-pin; authority-gesture monotonic
  invariant; watch-stream; bootstrap helper).
- Tag-3 :mod:`wirelang.federation.spiffe_cross_trust_domain_bridge`
  (live cross-trust-domain bridge composing fetcher + verifier +
  local-workload adapter).
- Tag-4 :mod:`wirelang.federation.capability_attenuation_chain_verifier`
  (cross-org capability-attenuation-chain verifier).
- Tag-5 (Sprint-7 pre-pfad-B; now lives in
  :mod:`wirelang.federation.unrevoke_audit_marker_cross_org_export`)
  not exercised here — orthogonal Cross-Org export-surface.
- Tag-6 :mod:`wirelang.federation.multi_org_attestation_live_tail_replicator`
  (continuous-stream source -> target replicator).

This Pfad-B Tag-5 test deliverable adds the *live-component*
acceptance: a hermetic E2E roundtrip wiring all of the above with
the Sprint-8 Tag-1
``infra/spire/federation/bin/spire_fed_bundle`` hermetic-mode CLI
through the new
:mod:`wirelang.federation.spire_fed_bundle_peer_fetcher` adapter.

E2E Roundtrip
=============

The test simulates two organisations:

- **Org-A** (``wakir.test`` trust-domain): the route source. Writes
  a :class:`MultiOrgRouteAttestation` into its
  ``wakir-multi-org-attestations`` NATS-KV bucket (the test uses the
  Tag-2 backend against an in-memory ``_MockKv`` so no live NATS
  server is required).
- **Org-B** (``partner.test`` trust-domain): the route target. Has
  its own ``wakir-multi-org-attestations`` bucket. The Tag-6 live-
  tail replicator forwards every Org-A write into Org-B.

After the replicator runs:

1. The :class:`SpiffeCrossTrustDomainBridge` on Org-B's side resolves
   the route. The bridge consumes the new
   :class:`SpireFedBundlePeerTrustBundleFetcher` adapter, which
   in turn calls into the Sprint-8 Tag-1 hermetic-mode
   ``spire_fed_bundle.export_bundle`` to obtain the Org-A trust-
   bundle JWKS.
2. The bridge verifies a peer-JWT-SVID supplied by Org-A through a
   stub verifier (the hermetic JWKS fixture lacks real EC keys; a
   live-mode verifier replacement is a Phase-2c follow-up).
3. The :class:`CapabilityAttenuationChainVerifier` walks a two-hop
   delegation chain (one local hop on Org-B + one cross-org hop
   that resolves against Org-A's capability-policy via a stub
   peer-resolver). The verifier emits a
   :class:`VerifiedAttenuationChain` whose
   :attr:`chain_hash` is anchorable into the WAT-Audit-Federation-
   Annex (Tomás D-1 follow-up consumer).

The roundtrip is asserted in three orthogonal ways:

- **Replication parity**: the Org-A attestation appears in Org-B's
  registry byte-equal.
- **Bridge resolution**: the bridge returns a
  :class:`LiveBridgeResolution` whose ``trust_bundle.bundle_bytes``
  contains the deterministic Org-A JWKS fixture, and whose
  ``peer_svid.spiffe_id`` carries the expected SPIFFE-ID.
- **Capability chain**: the verifier returns a
  :class:`VerifiedAttenuationChain` whose
  ``attestation_route_id`` matches the bridged route and whose
  cross-org hop is correctly flagged ``is_cross_org=True``.

Sandbox-boundary
================

The test is **hermetic-only**. It does NOT start a SPIRE-Server, does
NOT call podman, does NOT touch the network. The
``spire_fed_bundle`` CLI is consumed as an in-process Python module
through the Tag-5 adapter; the JWKS bytes the adapter returns are
the deterministic hermetic fixture per
``infra/spire/federation/bin/spire_fed_bundle.py`` documentation.

ADR-0050 Tool-Surface-Stempel
=============================

This file was authored using Read, Edit, Write, Bash. No
Agent-Tool, no WebFetch within this test module.

ADR-0049 Pre-Box-Worktree
=========================

Pre-Box-Worktree ``/tmp/reza-sprint-7-pfad-b-tag-5-runtime`` (suffix
``-runtime`` per Cross-Agent-Worktree-Collision policy), forked
from ``origin/main`` tip ``a2647ba``.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple

import pytest

from wirelang.federation.capability_attenuation_chain_verifier import (
    AttenuationLink,
    CapabilityAttenuationChainVerifier,
    VerifiedAttenuationChain,
)
from wirelang.federation.multi_org_attestation_live_tail_replicator import (
    MultiOrgAttestationReplicator,
    MultiOrgAttestationReplicationConflictPolicy,
)
from wirelang.federation.multi_org_attestation_nats_kv_backend import (
    BUCKET_NAME as MOA_BUCKET_NAME,
    MultiOrgAttestationWatchEvent,
    MultiOrgAttestationWatchOp,
    NatsKvMultiOrgAttestationRegistry,
    bootstrap_multi_org_attestation_target_from_source,
    open_watch_stream,
)
from wirelang.federation.multi_org_substrate import (
    InMemoryMultiOrgAttestationRegistry,
    MultiOrgRouteAttestation,
)
from wirelang.federation.n2_evaluator import (
    InMemoryRouteRegistry,
    RouteRegistryEntry,
)
from wirelang.federation.spiffe_cross_trust_domain_bridge import (
    FetchedTrustBundle,
    LiveBridgeResolution,
    PeerTrustBundleFetchError,
    SpiffeCrossTrustDomainBridge,
    VerifiedPeerSvid,
)
from wirelang.federation.spire_fed_bundle_peer_fetcher import (
    SPIRE_FED_BUNDLE_PEER_FETCHER_SCHEMA,
    SpireFedBundlePeerTrustBundleFetcher,
    UnpinnedTrustDomainError,
    UrlTrustDomainMismatchError,
)
from wirelang.schemas.registered_by_capability import (
    CapabilityPolicy,
    CapabilityPolicyRegistry,
)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


_T0 = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)


def _utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)


def _fixed_clock(now: datetime):
    def _now() -> datetime:
        return now

    return _now


# ---------------------------------------------------------------------------
# Mock KV (mirrors the Tag-2 backend test pattern; in-process, no NATS)
# ---------------------------------------------------------------------------


class _MockBucketNotFoundError(Exception):
    """Mirrors nats-py's ``KeyNotFoundError`` class-name pattern."""


@dataclass
class _MockKvEntry:
    value: bytes
    revision: int = 0


@dataclass
class _MockWatchUpdate:
    operation: str
    key: str
    value: bytes = b""
    revision: int = 0


class _MockWatcher:
    def __init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self._stopped = False

    def _push(self, update: Any) -> None:
        self._queue.put_nowait(update)

    def _close(self) -> None:
        self._queue.put_nowait(None)

    async def updates(self) -> Any:
        if self._stopped:
            return None
        return await self._queue.get()

    async def stop(self) -> None:
        self._stopped = True


@dataclass
class _MockKv:
    """In-memory KV with PUT / GET / keys() / watchall().

    Mirrors the Sprint-7 Tag-2 backend test's ``_MockKv`` minus the
    CAS-pin path (the live-tail replicator uses SOURCE_WINS in this
    test, which does not exercise put_with_revision).
    """

    bucket: str = MOA_BUCKET_NAME
    store: dict = field(default_factory=dict)
    revision: int = 0
    _watcher: Optional[_MockWatcher] = None

    async def get(self, key: str) -> _MockKvEntry:
        if key not in self.store:
            raise _MockBucketNotFoundError(f"key not found: {key}")
        return self.store[key]

    async def put(self, key: str, value: bytes) -> int:
        self.revision += 1
        self.store[key] = _MockKvEntry(
            value=bytes(value), revision=self.revision
        )
        if self._watcher is not None:
            self._watcher._push(
                _MockWatchUpdate(
                    operation="PUT",
                    key=key,
                    value=bytes(value),
                    revision=self.revision,
                )
            )
        return self.revision

    async def keys(self) -> list:
        return list(self.store.keys())

    def watchall(self) -> _MockWatcher:
        w = _MockWatcher()
        self._watcher = w
        return w


# ---------------------------------------------------------------------------
# Stub peer-SVID verifier (accepts a pinned (token, trust-domain) pair)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PinnedAcceptingVerifier:
    """Hermetic verifier: returns a VerifiedPeerSvid for the pinned
    token; rejects any other token. The verifier does NOT parse the
    JWKS bytes (the hermetic fixture lacks real EC-P-256 keys); it
    asserts the bridge passed the expected (token, trust_domain)
    pair, which is sufficient for the E2E composition test.
    """

    pinned_token: str
    pinned_trust_domain: str
    pinned_spiffe_id: str
    pinned_expires_at: datetime
    clock_now: datetime

    async def verify(
        self,
        *,
        peer_svid_token: str,
        trust_bundle: FetchedTrustBundle,
        expected_trust_domain: str,
        expected_audience: Optional[str] = None,
    ) -> VerifiedPeerSvid:
        if peer_svid_token != self.pinned_token:
            raise ValueError(
                f"verifier: unexpected token {peer_svid_token!r}; "
                f"pinned={self.pinned_token!r}"
            )
        if expected_trust_domain != self.pinned_trust_domain:
            raise ValueError(
                f"verifier: unexpected trust_domain "
                f"{expected_trust_domain!r}; pinned="
                f"{self.pinned_trust_domain!r}"
            )
        # The fixture JWKS embeds _wakir_trust_domain in the JWK; we
        # sanity-check the bytes look like the right fixture so the
        # composition path is asserted.
        doc = json.loads(trust_bundle.bundle_bytes.decode("utf-8"))
        jwk = doc["keys"][0]
        if jwk["_wakir_trust_domain"] != expected_trust_domain:
            raise ValueError(
                f"verifier: trust-bundle JWK trust-domain "
                f"{jwk['_wakir_trust_domain']!r} does not match "
                f"expected {expected_trust_domain!r}"
            )
        return VerifiedPeerSvid(
            spiffe_id=self.pinned_spiffe_id,
            token=peer_svid_token,
            audiences=(expected_audience,) if expected_audience else (),
            expires_at=self.pinned_expires_at,
            verified_at=self.clock_now,
        )


# ---------------------------------------------------------------------------
# Stub peer capability-policy resolver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PinnedPeerCapabilityPolicyResolver:
    """Hermetic peer-capability-policy resolver: returns a pinned
    :class:`CapabilityPolicy` for the (pointer, route_id) pair.
    """

    pinned_pointer: str
    pinned_route_id: str
    pinned_policy: CapabilityPolicy

    def resolve(
        self, *, pointer: str, route_id: str
    ) -> Optional[CapabilityPolicy]:
        if pointer != self.pinned_pointer:
            return None
        if route_id != self.pinned_route_id:
            return None
        return self.pinned_policy


# ---------------------------------------------------------------------------
# Test fixtures (constants used across the multi-test orchestration)
# ---------------------------------------------------------------------------


ROUTE_ID = "wakir->partner-A->treasury"
SOURCE_FTD_ID = "wakir-ftd-001"
PEER_TRUST_DOMAIN = "partner.test"  # Org-A SPIFFE trust-domain
WAKIR_TRUST_DOMAIN = "wakir.test"  # Org-B SPIFFE trust-domain
PEER_AUDIT_ANCHOR_DID = "did:web:partner-a.example.com"
PEER_TRUST_BUNDLE_URL = (
    "https://spire-server-partner:8443/spiffe/bundle"
)
WAKIR_TRUST_BUNDLE_URL = (
    "https://spire-server-wakir:8443/spiffe/bundle"
)
PEER_CAPABILITY_POLICY_POINTER = "partner-a::policy-treasury-v1"
PEER_SPIFFE_ID = "spiffe://partner.test/workload/treasury-edge"
PEER_SVID_TOKEN = "FAKE-PEER-SVID-TOKEN-FOR-HERMETIC-E2E"
LOCAL_REGISTERED_BY = "wakir-internal-prime"
LOCAL_POLICY_POINTER = "wakir-internal-prime::policy-edge-v1"


# ---------------------------------------------------------------------------
# Orchestration helpers (build the wired Org-A + Org-B substrate)
# ---------------------------------------------------------------------------


def _build_route_entry() -> RouteRegistryEntry:
    return RouteRegistryEntry(
        route_id=ROUTE_ID,
        source_ftd_id=SOURCE_FTD_ID,
        active_from=_utc(2026, 1, 1),
        active_until=_utc(2027, 1, 1),
        wat_anchor_manifest_id="wat-manifest-2026-q2",
    )


def _build_attestation() -> MultiOrgRouteAttestation:
    return MultiOrgRouteAttestation(
        route_id=ROUTE_ID,
        peer_trust_domain=PEER_TRUST_DOMAIN,
        peer_audit_anchor_did=PEER_AUDIT_ANCHOR_DID,
        peer_wat_anchor_manifest_id="partner-wat-2026-q2",
        peer_trust_bundle_url=PEER_TRUST_BUNDLE_URL,
        peer_capability_policy_pointer=PEER_CAPABILITY_POLICY_POINTER,
        is_mock=False,
    )


def _build_local_policy() -> CapabilityPolicy:
    return CapabilityPolicy(
        registered_by=LOCAL_REGISTERED_BY,
        allowed_kids=("wakir-prime-kid-1",),
        allowed_triples=(("edge", "treasury-*"),),
        not_before=_utc(2026, 1, 1),
        not_after=_utc(2027, 1, 1),
    )


def _build_peer_policy() -> CapabilityPolicy:
    return CapabilityPolicy(
        registered_by="partner-a-treasury",
        allowed_kids=("partner-a-kid-1",),
        allowed_triples=(("treasury", "outbound-*"),),
        not_before=_utc(2026, 1, 1),
        not_after=_utc(2027, 1, 1),
    )


def _build_adapter(clock_now: datetime) -> SpireFedBundlePeerTrustBundleFetcher:
    return SpireFedBundlePeerTrustBundleFetcher(
        trust_domain_to_url={
            PEER_TRUST_DOMAIN: PEER_TRUST_BUNDLE_URL,
            WAKIR_TRUST_DOMAIN: WAKIR_TRUST_BUNDLE_URL,
        },
        clock=_fixed_clock(clock_now),
    )


# ---------------------------------------------------------------------------
# T-LIVE-E2E-01: adapter happy-path fetch produces a JWKS bundle whose
#                _wakir_trust_domain marker matches the request.
# ---------------------------------------------------------------------------


def test_adapter_export_partner_jwks_matches_trust_domain_marker() -> None:
    adapter = _build_adapter(_T0)
    bundle = asyncio.run(
        adapter.fetch(
            url=PEER_TRUST_BUNDLE_URL,
            trust_domain=PEER_TRUST_DOMAIN,
        )
    )
    assert isinstance(bundle, FetchedTrustBundle)
    assert bundle.trust_domain == PEER_TRUST_DOMAIN
    assert bundle.url == PEER_TRUST_BUNDLE_URL
    assert bundle.fetched_at == _T0
    doc = json.loads(bundle.bundle_bytes.decode("utf-8"))
    assert isinstance(doc, dict)
    assert "keys" in doc and len(doc["keys"]) == 1
    jwk = doc["keys"][0]
    assert jwk["kty"] == "EC"
    assert jwk["crv"] == "P-256"
    assert jwk["_wakir_trust_domain"] == PEER_TRUST_DOMAIN
    assert (
        jwk["kid"] == f"spiffe://{PEER_TRUST_DOMAIN}/spire/server/fixture-key"
    )


# ---------------------------------------------------------------------------
# T-LIVE-E2E-02: adapter rejects unpinned trust-domain.
# ---------------------------------------------------------------------------


def test_adapter_rejects_unpinned_trust_domain() -> None:
    adapter = _build_adapter(_T0)
    with pytest.raises(UnpinnedTrustDomainError) as excinfo:
        asyncio.run(
            adapter.fetch(
                url="https://example.test:8443/bundle",
                trust_domain="rogue.test",
            )
        )
    assert excinfo.value.trust_domain == "rogue.test"
    assert PEER_TRUST_DOMAIN in excinfo.value.pinned


# ---------------------------------------------------------------------------
# T-LIVE-E2E-03: adapter rejects URL/trust-domain mismatch.
# ---------------------------------------------------------------------------


def test_adapter_rejects_url_trust_domain_mismatch() -> None:
    adapter = _build_adapter(_T0)
    with pytest.raises(UrlTrustDomainMismatchError) as excinfo:
        asyncio.run(
            adapter.fetch(
                url="https://wrong-host:9999/bundle",
                trust_domain=PEER_TRUST_DOMAIN,
            )
        )
    assert excinfo.value.trust_domain == PEER_TRUST_DOMAIN
    assert excinfo.value.requested_url == "https://wrong-host:9999/bundle"
    assert excinfo.value.pinned_url == PEER_TRUST_BUNDLE_URL


# ---------------------------------------------------------------------------
# T-LIVE-E2E-04: bridge resolves end-to-end using the adapter +
#                in-memory registries (no replicator yet).
# ---------------------------------------------------------------------------


def test_bridge_resolves_endtoend_with_adapter() -> None:
    route_registry = InMemoryRouteRegistry({ROUTE_ID: _build_route_entry()})
    attestation_registry = InMemoryMultiOrgAttestationRegistry(attestations={})
    attestation_registry.add(_build_attestation())

    clock_now = _T0
    adapter = _build_adapter(clock_now)
    verifier = _PinnedAcceptingVerifier(
        pinned_token=PEER_SVID_TOKEN,
        pinned_trust_domain=PEER_TRUST_DOMAIN,
        pinned_spiffe_id=PEER_SPIFFE_ID,
        pinned_expires_at=clock_now + timedelta(hours=1),
        clock_now=clock_now,
    )
    bridge = SpiffeCrossTrustDomainBridge(
        route_registry=route_registry,
        attestation_registry=attestation_registry,
        trust_bundle_fetcher=adapter,
        peer_svid_verifier=verifier,
        clock=_fixed_clock(clock_now),
    )
    resolution = asyncio.run(
        bridge.resolve(
            ROUTE_ID,
            peer_svid_token=PEER_SVID_TOKEN,
            peer_svid_audience=WAKIR_TRUST_DOMAIN,
        )
    )
    assert isinstance(resolution, LiveBridgeResolution)
    assert resolution.entry.route_id == ROUTE_ID
    assert resolution.attestation.route_id == ROUTE_ID
    assert resolution.trust_bundle.trust_domain == PEER_TRUST_DOMAIN
    assert resolution.trust_bundle.url == PEER_TRUST_BUNDLE_URL
    assert resolution.peer_svid is not None
    assert resolution.peer_svid.spiffe_id == PEER_SPIFFE_ID
    assert resolution.peer_svid.token == PEER_SVID_TOKEN
    # Trust-bundle bytes carry the expected fixture marker.
    doc = json.loads(resolution.trust_bundle.bundle_bytes.decode("utf-8"))
    assert doc["keys"][0]["_wakir_trust_domain"] == PEER_TRUST_DOMAIN


# ---------------------------------------------------------------------------
# T-LIVE-E2E-05: bridge wraps adapter UrlTrustDomainMismatch as
#                PeerTrustBundleFetchError (fail-closed semantics).
# ---------------------------------------------------------------------------


def test_bridge_wraps_adapter_url_mismatch_as_fetch_error() -> None:
    route_registry = InMemoryRouteRegistry({ROUTE_ID: _build_route_entry()})
    bad_attestation = MultiOrgRouteAttestation(
        route_id=ROUTE_ID,
        peer_trust_domain=PEER_TRUST_DOMAIN,
        peer_audit_anchor_did=PEER_AUDIT_ANCHOR_DID,
        peer_trust_bundle_url="https://wrong-host:9999/bundle",
        is_mock=False,
    )
    attestation_registry = InMemoryMultiOrgAttestationRegistry(attestations={})
    attestation_registry.add(bad_attestation)

    clock_now = _T0
    adapter = _build_adapter(clock_now)
    verifier = _PinnedAcceptingVerifier(
        pinned_token=PEER_SVID_TOKEN,
        pinned_trust_domain=PEER_TRUST_DOMAIN,
        pinned_spiffe_id=PEER_SPIFFE_ID,
        pinned_expires_at=clock_now + timedelta(hours=1),
        clock_now=clock_now,
    )
    bridge = SpiffeCrossTrustDomainBridge(
        route_registry=route_registry,
        attestation_registry=attestation_registry,
        trust_bundle_fetcher=adapter,
        peer_svid_verifier=verifier,
        clock=_fixed_clock(clock_now),
    )
    with pytest.raises(PeerTrustBundleFetchError) as excinfo:
        asyncio.run(
            bridge.resolve(
                ROUTE_ID,
                peer_svid_token=PEER_SVID_TOKEN,
                peer_svid_audience=WAKIR_TRUST_DOMAIN,
            )
        )
    assert excinfo.value.url == "https://wrong-host:9999/bundle"
    assert isinstance(excinfo.value.cause, UrlTrustDomainMismatchError)


# ---------------------------------------------------------------------------
# T-LIVE-E2E-06: bootstrap replicator copies Org-A attestation to Org-B
#                bucket byte-equally; the bridge on Org-B's side then
#                resolves successfully.
# ---------------------------------------------------------------------------


def test_bootstrap_then_bridge_resolves_on_target() -> None:
    async def _runner() -> None:
        # Build Org-A (source) and Org-B (target) backends.
        source_kv = _MockKv(bucket=MOA_BUCKET_NAME)
        target_kv = _MockKv(bucket=MOA_BUCKET_NAME)
        source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
        target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)
        # Org-A writes the attestation.
        att = _build_attestation()
        await source.put(att)
        # Bootstrap from source -> target.
        metrics = await bootstrap_multi_org_attestation_target_from_source(
            source=source,
            target=target,
        )
        # Bootstrap should have replicated exactly one record.
        assert metrics.bootstrap_applied == 1
        # Org-B reads the record byte-equal.
        copied = await target.get(ROUTE_ID)
        assert copied is not None
        assert copied == att

        # Build the route-registry side (Org-B has its own copy).
        route_registry = InMemoryRouteRegistry(
            {ROUTE_ID: _build_route_entry()}
        )
        # Snapshot the target backend into an in-memory registry the
        # bridge accepts as ``_AttestationRegistryLike``.
        attestation_snapshot = await target.snapshot()

        clock_now = _T0
        adapter = _build_adapter(clock_now)
        verifier = _PinnedAcceptingVerifier(
            pinned_token=PEER_SVID_TOKEN,
            pinned_trust_domain=PEER_TRUST_DOMAIN,
            pinned_spiffe_id=PEER_SPIFFE_ID,
            pinned_expires_at=clock_now + timedelta(hours=1),
            clock_now=clock_now,
        )
        bridge = SpiffeCrossTrustDomainBridge(
            route_registry=route_registry,
            attestation_registry=attestation_snapshot,
            trust_bundle_fetcher=adapter,
            peer_svid_verifier=verifier,
            clock=_fixed_clock(clock_now),
        )
        resolution = await bridge.resolve(
            ROUTE_ID,
            peer_svid_token=PEER_SVID_TOKEN,
            peer_svid_audience=WAKIR_TRUST_DOMAIN,
        )
        assert resolution.attestation == att
        assert resolution.peer_svid.spiffe_id == PEER_SPIFFE_ID

    asyncio.run(_runner())


# ---------------------------------------------------------------------------
# T-LIVE-E2E-07: live-tail replicator forwards a *post-bootstrap* Org-A
#                write into Org-B's bucket; the bridge then resolves
#                the new route on Org-B's side.
# ---------------------------------------------------------------------------


def test_live_tail_replicator_then_bridge_resolves() -> None:
    async def _runner() -> None:
        source_kv = _MockKv(bucket=MOA_BUCKET_NAME)
        target_kv = _MockKv(bucket=MOA_BUCKET_NAME)
        source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
        target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)

        # Seed Org-A with a different attestation BEFORE the live-tail
        # replicator runs (bootstrap pass picks it up).
        seed_route_id = "wakir->partner-A->seed"
        seed_att = MultiOrgRouteAttestation(
            route_id=seed_route_id,
            peer_trust_domain=PEER_TRUST_DOMAIN,
            peer_audit_anchor_did=PEER_AUDIT_ANCHOR_DID,
            peer_trust_bundle_url=PEER_TRUST_BUNDLE_URL,
            is_mock=False,
        )
        await source.put(seed_att)

        # Construct the replicator. SOURCE_WINS is the default policy
        # and the most straightforward roundtrip target.
        replicator = MultiOrgAttestationReplicator(
            source=source,
            target=target,
            conflict_policy=MultiOrgAttestationReplicationConflictPolicy.SOURCE_WINS,
        )

        # Step 1: run the bootstrap pass synchronously (no live-tail
        # consumption yet — we drive that explicitly below to isolate
        # the post-bootstrap PUT into the test's control-flow).
        boot_metrics = await replicator.bootstrap()
        # The bootstrap helper returns metrics with bootstrap_applied
        # counting the records replicated source -> target.
        assert boot_metrics.bootstrap_applied == 1
        copied_seed = await target.get(seed_route_id)
        assert copied_seed == seed_att

        # Step 2: open a watch-stream on the source via the bucket's
        # underlying MockKv watcher; the replicator can be exercised
        # by hand for the *one* post-bootstrap PUT we care about.
        watcher = source_kv.watchall()  # registers the watcher on the kv
        # Re-issue the put AFTER attaching the watcher so the event is
        # observed by us. (The bootstrap pass above does not consume
        # the watcher — the replicator's bootstrap path uses snapshot,
        # not watch.)
        live_att = _build_attestation()
        await source.put(live_att)

        # Drain one event from the source watcher and apply it to the
        # target backend manually — this mirrors what the replicator
        # would do in its live-tail loop, without needing to spin up a
        # long-running task in the test.
        update = await watcher.updates()
        assert update is not None
        assert update.operation == "PUT"
        assert update.key == live_att.route_id
        # Apply to target (mirroring the SOURCE_WINS path).
        decoded_att_on_target = await source.get(live_att.route_id)
        assert decoded_att_on_target == live_att
        await target.put(decoded_att_on_target)
        copied_live = await target.get(live_att.route_id)
        assert copied_live == live_att

        # Step 3: bridge resolves on Org-B's side.
        route_registry = InMemoryRouteRegistry(
            {ROUTE_ID: _build_route_entry()}
        )
        attestation_snapshot = await target.snapshot()
        clock_now = _T0
        adapter = _build_adapter(clock_now)
        verifier = _PinnedAcceptingVerifier(
            pinned_token=PEER_SVID_TOKEN,
            pinned_trust_domain=PEER_TRUST_DOMAIN,
            pinned_spiffe_id=PEER_SPIFFE_ID,
            pinned_expires_at=clock_now + timedelta(hours=1),
            clock_now=clock_now,
        )
        bridge = SpiffeCrossTrustDomainBridge(
            route_registry=route_registry,
            attestation_registry=attestation_snapshot,
            trust_bundle_fetcher=adapter,
            peer_svid_verifier=verifier,
            clock=_fixed_clock(clock_now),
        )
        resolution = await bridge.resolve(
            ROUTE_ID,
            peer_svid_token=PEER_SVID_TOKEN,
            peer_svid_audience=WAKIR_TRUST_DOMAIN,
        )
        assert resolution.attestation == live_att

        await watcher.stop()

    asyncio.run(_runner())


# ---------------------------------------------------------------------------
# T-LIVE-E2E-08: full cross-module E2E roundtrip — bootstrap +
#                bridge resolve + capability-attenuation-chain verify
#                with a cross-org hop that consumes the attestation's
#                peer_capability_policy_pointer.
# ---------------------------------------------------------------------------


def test_full_cross_module_e2e_roundtrip() -> None:
    async def _runner() -> None:
        # Org-A backend writes the attestation.
        source_kv = _MockKv(bucket=MOA_BUCKET_NAME)
        target_kv = _MockKv(bucket=MOA_BUCKET_NAME)
        source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
        target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)
        att = _build_attestation()
        await source.put(att)
        # Bootstrap to target.
        await bootstrap_multi_org_attestation_target_from_source(
            source=source, target=target,
        )

        # Build Org-B route-registry and pull the attestation snapshot.
        route_registry = InMemoryRouteRegistry(
            {ROUTE_ID: _build_route_entry()}
        )
        attestation_snapshot = await target.snapshot()

        # Bridge resolution (Org-B side).
        clock_now = _T0
        adapter = _build_adapter(clock_now)
        verifier = _PinnedAcceptingVerifier(
            pinned_token=PEER_SVID_TOKEN,
            pinned_trust_domain=PEER_TRUST_DOMAIN,
            pinned_spiffe_id=PEER_SPIFFE_ID,
            pinned_expires_at=clock_now + timedelta(hours=1),
            clock_now=clock_now,
        )
        bridge = SpiffeCrossTrustDomainBridge(
            route_registry=route_registry,
            attestation_registry=attestation_snapshot,
            trust_bundle_fetcher=adapter,
            peer_svid_verifier=verifier,
            clock=_fixed_clock(clock_now),
        )
        resolution = await bridge.resolve(
            ROUTE_ID,
            peer_svid_token=PEER_SVID_TOKEN,
            peer_svid_audience=WAKIR_TRUST_DOMAIN,
        )
        assert isinstance(resolution, LiveBridgeResolution)

        # Capability-attenuation-chain verifier: two-hop chain with one
        # local hop and one cross-org hop (the cross-org hop resolves
        # against the peer-resolver via the attestation's pinned
        # peer_capability_policy_pointer).
        source_registry = CapabilityPolicyRegistry()
        source_registry.add_policy(_build_local_policy())
        peer_resolver = _PinnedPeerCapabilityPolicyResolver(
            pinned_pointer=PEER_CAPABILITY_POLICY_POINTER,
            pinned_route_id=ROUTE_ID,
            pinned_policy=_build_peer_policy(),
        )
        chain_verifier = CapabilityAttenuationChainVerifier(
            source_registry=source_registry,
            peer_resolver=peer_resolver,
            clock=_fixed_clock(clock_now),
        )
        # Build a two-link attenuation chain (local hop -> cross-org hop).
        local_link = AttenuationLink(
            attenuation_index=0,
            policy_pointer=LOCAL_POLICY_POINTER,
            issued_at=clock_now - timedelta(minutes=15),
            expires_at=clock_now + timedelta(minutes=45),
            registered_by=LOCAL_REGISTERED_BY,
        )
        cross_org_link = AttenuationLink(
            attenuation_index=1,
            policy_pointer=PEER_CAPABILITY_POLICY_POINTER,
            issued_at=clock_now - timedelta(minutes=10),
            expires_at=clock_now + timedelta(minutes=30),
        )
        chain = (local_link, cross_org_link)
        verified = chain_verifier.verify(
            entry=resolution.entry,
            attestation=resolution.attestation,
            chain=chain,
        )
        assert isinstance(verified, VerifiedAttenuationChain)
        assert verified.attestation_route_id == ROUTE_ID
        assert len(verified.resolved_links) == 2
        assert verified.resolved_links[0].is_cross_org is False
        assert verified.resolved_links[1].is_cross_org is True
        # The chain_hash is deterministic; re-verify byte-equally to
        # assert the WAT-Audit-Federation-Annex anchor surface.
        verified2 = chain_verifier.verify(
            entry=resolution.entry,
            attestation=resolution.attestation,
            chain=chain,
        )
        assert verified2.chain_hash == verified.chain_hash

    asyncio.run(_runner())


# ---------------------------------------------------------------------------
# T-LIVE-E2E-09: schema-pin stability — the adapter advertises a stable
#                schema-URI string.
# ---------------------------------------------------------------------------


def test_adapter_schema_pin_is_stable() -> None:
    adapter = _build_adapter(_T0)
    assert (
        adapter.adapter_schema
        == SPIRE_FED_BUNDLE_PEER_FETCHER_SCHEMA
        == "wakir.federation.spire-fed-bundle-peer-fetcher/1"
    )


# ---------------------------------------------------------------------------
# T-LIVE-E2E-10: cross-trust-domain bidirectional roundtrip — adapter
#                fetches BOTH trust-domains successfully.
# ---------------------------------------------------------------------------


def test_adapter_fetches_both_trust_domains_distinct_jwks() -> None:
    adapter = _build_adapter(_T0)
    partner_bundle = asyncio.run(
        adapter.fetch(
            url=PEER_TRUST_BUNDLE_URL,
            trust_domain=PEER_TRUST_DOMAIN,
        )
    )
    wakir_bundle = asyncio.run(
        adapter.fetch(
            url=WAKIR_TRUST_BUNDLE_URL,
            trust_domain=WAKIR_TRUST_DOMAIN,
        )
    )
    partner_jwk = json.loads(
        partner_bundle.bundle_bytes.decode("utf-8")
    )["keys"][0]
    wakir_jwk = json.loads(
        wakir_bundle.bundle_bytes.decode("utf-8")
    )["keys"][0]
    assert partner_jwk["_wakir_trust_domain"] == PEER_TRUST_DOMAIN
    assert wakir_jwk["_wakir_trust_domain"] == WAKIR_TRUST_DOMAIN
    # Cross-trust-domain distinguishability per spire_fed_bundle
    # deterministic-fixture contract.
    assert partner_jwk["x"] != wakir_jwk["x"]
    assert partner_jwk["y"] != wakir_jwk["y"]
    assert partner_jwk["kid"] != wakir_jwk["kid"]
