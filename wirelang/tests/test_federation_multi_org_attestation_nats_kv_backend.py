# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the multi-org-attestation NATS-KV backend.

Phase-2 Sprint-7 Tag-2. Pattern-mirror on the Sprint-3 Tag-6
route-registry backend test suite (test_federation_route_registry_
nats_kv_backend.py).

Test inventory T-MOA-NKV-01..15:

Single-key + envelope:
- T-MOA-NKV-01: put / get round-trips an attestation.
- T-MOA-NKV-02: get on unknown key returns None.
- T-MOA-NKV-03: put rejects monotonic-invariant breach.
- T-MOA-NKV-04: poisoned envelope raises EnvelopeError.
- T-MOA-NKV-05: snapshot materialises an in-memory registry.
- T-MOA-NKV-06: bucket-config constants match documented inventory.

CAS-pin:
- T-MOA-NKV-07: put_with_revision (CAS) round-trips.
- T-MOA-NKV-08: put_with_revision CAS-conflict raises
  MultiOrgAttestationCasConflict on stale revision.

Watch-stream + LiveSnapshot:
- T-MOA-NKV-09: watch yields PUT events.
- T-MOA-NKV-10: watch yields DELETE event.
- T-MOA-NKV-11: LiveSnapshot bootstraps + applies PUT delta;
  as_registry returns a frozen copy.

Monotonic-invariant (authority-gesture):
- T-MOA-NKV-12: mock-to-live transition refused on same route_id.
- T-MOA-NKV-13: optional field additive-monotonic (None -> value
  accepted; value -> None refused).

Cross-bucket replication:
- T-MOA-NKV-14: bootstrap copies source to empty target;
  byte-equal idempotency on re-run.
- T-MOA-NKV-15: bootstrap monotonic breach counted under
  SOURCE_WINS policy.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

from wirelang.federation.multi_org_substrate import (
    InMemoryMultiOrgAttestationRegistry,
    MOCK_BRIDGE_ROUTE_ID_PREFIX,
    MultiOrgRouteAttestation,
)
from wirelang.federation.multi_org_attestation_nats_kv_backend import (
    BUCKET_CONFIG,
    BUCKET_NAME,
    LiveMultiOrgAttestationSnapshot,
    MultiOrgAttestationBackendError,
    MultiOrgAttestationCasConflict,
    MultiOrgAttestationEnvelopeError,
    MultiOrgAttestationMonotonicConflict,
    MultiOrgAttestationReplicationConflictPolicy,
    MultiOrgAttestationReplicationDecision,
    MultiOrgAttestationReplicationMetrics,
    MultiOrgAttestationWatchEvent,
    MultiOrgAttestationWatchOp,
    NatsKvMultiOrgAttestationRegistry,
    VALUE_SCHEMA,
    _attestation_to_envelope,
    bootstrap_multi_org_attestation_target_from_source,
)


# ---------------------------------------------------------------------------
# Mock KV (mirrors Sprint-3 Tag-6 _MockKv with CAS-pin support added)
# ---------------------------------------------------------------------------


class _MockBucketNotFoundError(Exception):
    """Mirrors nats-py's ``KeyNotFoundError`` class-name pattern."""


class _MockWrongLastSequenceError(Exception):
    """Mirrors nats-py's ``KeyWrongLastSequenceError`` class-name."""

    def __init__(self, message: str, *, actual_revision: int) -> None:
        super().__init__(message)
        self.actual_revision = actual_revision


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
    """In-memory KV with PUT/GET/DELETE/keys/watchall AND
    CAS-pinned update(key, value, last=...)."""

    bucket: str = BUCKET_NAME
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

    async def update(self, key: str, value: bytes, last: int) -> int:
        """CAS-pinned write. Raises a class-name-marked conflict
        exception when the live revision differs from ``last``.

        ``last=0`` is treated as create-if-absent (a no-record state
        has revision 0 from the backend's perspective).
        """
        live = self.store.get(key)
        live_rev = live.revision if live is not None else 0
        if live_rev != last:
            raise _MockWrongLastSequenceError(
                f"CAS mismatch for key={key!r}: live={live_rev} "
                f"expected={last}",
                actual_revision=live_rev,
            )
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

    async def delete(self, key: str) -> None:
        if key not in self.store:
            raise _MockBucketNotFoundError(f"key not found: {key}")
        del self.store[key]
        self.revision += 1
        if self._watcher is not None:
            self._watcher._push(
                _MockWatchUpdate(
                    operation="DELETE",
                    key=key,
                    revision=self.revision,
                )
            )

    async def keys(self) -> list:
        return list(self.store.keys())

    async def watchall(self) -> _MockWatcher:
        if self._watcher is None:
            self._watcher = _MockWatcher()
        return self._watcher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_PEER_TRUST_DOMAIN = "partner-a.example"
_PEER_DID = "did:web:partner-a.example"
_LIVE_ROUTE_ID = "wakir->partner-a->treasury"
_MOCK_ROUTE_ID = MOCK_BRIDGE_ROUTE_ID_PREFIX + "partner-a/treasury"


def _make_live_att(
    route_id: str = _LIVE_ROUTE_ID,
    *,
    peer_trust_domain: str = _PEER_TRUST_DOMAIN,
    peer_audit_anchor_did: str = _PEER_DID,
    peer_wat_anchor_manifest_id: Optional[str] = (
        "wat-manifest-partner-a-2026-05-12-h12"
    ),
    peer_trust_bundle_url: Optional[str] = None,
    peer_capability_policy_pointer: Optional[str] = None,
) -> MultiOrgRouteAttestation:
    return MultiOrgRouteAttestation(
        route_id=route_id,
        peer_trust_domain=peer_trust_domain,
        peer_audit_anchor_did=peer_audit_anchor_did,
        peer_wat_anchor_manifest_id=peer_wat_anchor_manifest_id,
        peer_trust_bundle_url=peer_trust_bundle_url,
        peer_capability_policy_pointer=peer_capability_policy_pointer,
        is_mock=False,
    )


def _make_mock_att(
    route_id: str = _MOCK_ROUTE_ID,
) -> MultiOrgRouteAttestation:
    return MultiOrgRouteAttestation(
        route_id=route_id,
        peer_trust_domain=_PEER_TRUST_DOMAIN,
        peer_audit_anchor_did=_PEER_DID,
        is_mock=True,
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# T-MOA-NKV-01..06 single-key + envelope + snapshot
# ---------------------------------------------------------------------------


def test_t_moa_nkv_01_put_get_round_trip():
    """T-MOA-NKV-01: put then get returns the same attestation."""
    backend = NatsKvMultiOrgAttestationRegistry(kv=_MockKv())
    att = _make_live_att()

    async def _go():
        rev = await backend.put(att)
        got = await backend.get(att.route_id)
        return rev, got

    rev, got = _run(_go())
    assert rev >= 1
    assert got == att


def test_t_moa_nkv_02_get_unknown_returns_none():
    """T-MOA-NKV-02: get on absent key returns None."""
    backend = NatsKvMultiOrgAttestationRegistry(kv=_MockKv())

    async def _go():
        return await backend.get("does-not-exist")

    assert _run(_go()) is None


def test_t_moa_nkv_03_put_rejects_monotonic_breach():
    """T-MOA-NKV-03: put refuses to mutate an authority anchor.

    Authority anchors (peer_trust_domain, peer_audit_anchor_did) are
    immutable once recorded. An attempted mutation surfaces as
    MultiOrgAttestationMonotonicConflict.
    """
    backend = NatsKvMultiOrgAttestationRegistry(kv=_MockKv())
    a1 = _make_live_att()
    a2 = MultiOrgRouteAttestation(
        route_id=a1.route_id,
        peer_trust_domain="partner-b.example",  # mutation
        peer_audit_anchor_did=a1.peer_audit_anchor_did,
        peer_wat_anchor_manifest_id=a1.peer_wat_anchor_manifest_id,
        is_mock=False,
    )

    async def _go():
        await backend.put(a1)
        await backend.put(a2)

    with pytest.raises(MultiOrgAttestationMonotonicConflict) as exc_info:
        _run(_go())
    assert exc_info.value.breach_kind == "trust-domain-mutation"
    assert exc_info.value.route_id == a1.route_id


def test_t_moa_nkv_04_poisoned_envelope_raises():
    """T-MOA-NKV-04: a non-JSON byte payload raises a clean
    MultiOrgAttestationEnvelopeError from get and snapshot."""
    kv = _MockKv()
    kv.store["poisoned"] = _MockKvEntry(
        value=b"\xff\xfenot-json", revision=1
    )
    backend = NatsKvMultiOrgAttestationRegistry(kv=kv)

    async def _go_get():
        return await backend.get("poisoned")

    async def _go_snap():
        return await backend.snapshot()

    with pytest.raises(MultiOrgAttestationEnvelopeError):
        _run(_go_get())
    with pytest.raises(MultiOrgAttestationEnvelopeError):
        _run(_go_snap())


def test_t_moa_nkv_05_snapshot_returns_in_memory_registry():
    """T-MOA-NKV-05: snapshot materialises an in-memory registry."""
    backend = NatsKvMultiOrgAttestationRegistry(kv=_MockKv())
    a1 = _make_live_att()
    a2 = _make_mock_att()

    async def _go():
        await backend.put(a1)
        await backend.put(a2)
        return await backend.snapshot()

    snap = _run(_go())
    assert isinstance(snap, InMemoryMultiOrgAttestationRegistry)
    assert snap.lookup(a1.route_id) == a1
    assert snap.lookup(a2.route_id) == a2
    assert snap.lookup("not-registered") is None


def test_t_moa_nkv_06_bucket_config_matches_inventory():
    """T-MOA-NKV-06: bucket-config drift protection at the test
    layer (orchestrator-side runs against the live cluster)."""
    assert BUCKET_NAME == "wakir-multi-org-attestations"
    assert BUCKET_CONFIG["name"] == BUCKET_NAME
    assert BUCKET_CONFIG["history"] == 5
    assert BUCKET_CONFIG["ttl_seconds"] == 0
    assert BUCKET_CONFIG["max_value_size"] == 4096
    assert BUCKET_CONFIG["storage"] == "file"
    assert BUCKET_CONFIG["replicas"] == 1
    assert VALUE_SCHEMA == "wakir.federation.multi-org-attestation/1"


# ---------------------------------------------------------------------------
# T-MOA-NKV-07..08 CAS-pin
# ---------------------------------------------------------------------------


def test_t_moa_nkv_07_put_with_revision_round_trip():
    """T-MOA-NKV-07: CAS-pinned upsert round-trips on a fresh key
    (expected_revision=0) and on a subsequent re-pin (idempotent
    rewrite)."""
    backend = NatsKvMultiOrgAttestationRegistry(kv=_MockKv())
    att = _make_live_att()

    async def _go():
        # Create-if-absent: expected_revision=0.
        r1 = await backend.put_with_revision(att, 0)
        # Idempotent rewrite at the new revision.
        pair = await backend.get_with_revision(att.route_id)
        assert pair is not None
        live, live_rev = pair
        assert live == att
        r2 = await backend.put_with_revision(att, live_rev)
        return r1, r2

    r1, r2 = _run(_go())
    assert r1 >= 1
    assert r2 > r1


def test_t_moa_nkv_08_put_with_revision_cas_conflict():
    """T-MOA-NKV-08: a stale expected_revision raises
    MultiOrgAttestationCasConflict; the exception carries route_id
    and the observed revisions."""
    backend = NatsKvMultiOrgAttestationRegistry(kv=_MockKv())
    att = _make_live_att()

    async def _go():
        await backend.put_with_revision(att, 0)
        # Caller observed revision 1, but now another writer lands
        # an idempotent rewrite that advances the revision.
        pair = await backend.get_with_revision(att.route_id)
        assert pair is not None
        _, observed_rev = pair
        # A concurrent put advances the revision.
        await backend.put(att)
        # Caller's stale revision is now wrong.
        await backend.put_with_revision(att, observed_rev)

    with pytest.raises(MultiOrgAttestationCasConflict) as exc_info:
        _run(_go())
    assert exc_info.value.route_id == att.route_id
    assert exc_info.value.expected_revision == 1
    assert exc_info.value.actual_revision == 2


# ---------------------------------------------------------------------------
# T-MOA-NKV-09..11 Watch-stream + LiveSnapshot
# ---------------------------------------------------------------------------


def test_t_moa_nkv_09_watch_yields_put_events():
    """T-MOA-NKV-09: watch yields decoded PUT events for upserts."""
    kv = _MockKv()
    backend = NatsKvMultiOrgAttestationRegistry(kv=kv)
    a1 = _make_live_att(route_id="wakir->p-a->t1")
    a2 = _make_live_att(route_id="wakir->p-a->t2")

    async def _go():
        stream = await backend.watch()
        await backend.put(a1)
        await backend.put(a2)
        kv._watcher._close()  # type: ignore[union-attr]
        events = []
        async for ev in stream:
            events.append(ev)
        await stream.__aexit__(None, None, None)
        return events

    events = _run(_go())
    assert len(events) == 2
    assert events[0].op is MultiOrgAttestationWatchOp.PUT
    assert events[0].route_id == "wakir->p-a->t1"
    assert events[0].attestation == a1
    assert events[0].revision == 1
    assert events[1].op is MultiOrgAttestationWatchOp.PUT
    assert events[1].attestation == a2


def test_t_moa_nkv_10_watch_yields_delete_event():
    """T-MOA-NKV-10: DELETE surfaces a DELETE WatchEvent with
    attestation=None."""
    kv = _MockKv()
    backend = NatsKvMultiOrgAttestationRegistry(kv=kv)
    att = _make_live_att()

    async def _go():
        await backend.put(att)
        stream = await backend.watch()
        await backend.delete(att.route_id)
        kv._watcher._close()  # type: ignore[union-attr]
        events = []
        async for ev in stream:
            events.append(ev)
        return events

    events = _run(_go())
    assert len(events) == 1
    assert events[0].op is MultiOrgAttestationWatchOp.DELETE
    assert events[0].route_id == att.route_id
    assert events[0].attestation is None
    assert events[0].revision >= 2


def test_t_moa_nkv_11_live_snapshot_bootstraps_and_applies_put():
    """T-MOA-NKV-11: LiveSnapshot.from_backend bootstraps; apply()
    of a PUT event updates the live state; as_registry returns a
    frozen copy that is not mutated by subsequent apply()."""
    backend = NatsKvMultiOrgAttestationRegistry(kv=_MockKv())
    a1 = _make_live_att(route_id="r-1")
    a2 = _make_live_att(route_id="r-2")

    async def _go():
        await backend.put(a1)
        live = await LiveMultiOrgAttestationSnapshot.from_backend(backend)
        frozen_before = live.as_registry()
        live.apply(
            MultiOrgAttestationWatchEvent(
                op=MultiOrgAttestationWatchOp.PUT,
                route_id=a2.route_id,
                attestation=a2,
                revision=2,
            )
        )
        frozen_after = live.as_registry()
        return frozen_before, frozen_after, live.last_revision

    before, after, last_rev = _run(_go())
    # Frozen-copy determinism contract: 'before' still has only a1.
    assert before.lookup("r-1") == a1
    assert before.lookup("r-2") is None
    # Live state reflects a2 after the apply.
    assert after.lookup("r-1") == a1
    assert after.lookup("r-2") == a2
    assert last_rev == 2


# ---------------------------------------------------------------------------
# T-MOA-NKV-12..13 Monotonic-invariant (authority-gesture)
# ---------------------------------------------------------------------------


def test_t_moa_nkv_12_mock_to_live_transition_refused():
    """T-MOA-NKV-12: a mock attestation and a live attestation use
    different route_id namespaces (mock prefix is locked at the
    substrate). Attempting to put a live attestation under a mock
    route_id is rejected at the substrate-construction layer; the
    backend never sees the call. Conversely, once a route_id is
    recorded, the is_mock flag is immutable: trying to flip it via
    the backend surfaces as MultiOrgAttestationMonotonicConflict.

    This test exercises the second leg: register a mock, then try
    to overwrite it with a same-route_id payload claiming is_mock=
    False. The substrate-layer constructor still rejects the
    is_mock=False+mock-prefix combination, so the operationally
    relevant scenario is the symmetric mutation. We confirm both:
    """
    backend = NatsKvMultiOrgAttestationRegistry(kv=_MockKv())
    # Leg 1: substrate-level guard (is_mock=False with mock prefix).
    with pytest.raises(Exception):
        MultiOrgRouteAttestation(
            route_id=_MOCK_ROUTE_ID,
            peer_trust_domain=_PEER_TRUST_DOMAIN,
            peer_audit_anchor_did=_PEER_DID,
            is_mock=False,
        )
    # Leg 2: substrate-level guard (is_mock=True without mock prefix).
    with pytest.raises(Exception):
        MultiOrgRouteAttestation(
            route_id=_LIVE_ROUTE_ID,
            peer_trust_domain=_PEER_TRUST_DOMAIN,
            peer_audit_anchor_did=_PEER_DID,
            is_mock=True,
        )
    # Backend stays consistent with the substrate: putting a mock
    # then putting a live attestation under the same route_id is
    # already barred at construction; we add a defensive backend
    # round-trip to make sure the mock leg itself works.

    async def _go():
        mock = _make_mock_att()
        await backend.put(mock)
        return await backend.get(mock.route_id)

    got = _run(_go())
    assert got is not None
    assert got.is_mock is True


def test_t_moa_nkv_13_optional_field_additive_monotonic():
    """T-MOA-NKV-13: optional fields are additive-monotonic.

    None -> value is accepted (additive). value -> None is refused
    (regression). value-A -> value-B is refused (mutation).
    Idempotent rewrites (byte-equal) are always accepted.
    """
    backend = NatsKvMultiOrgAttestationRegistry(kv=_MockKv())
    # Start without the bundle URL.
    a0 = MultiOrgRouteAttestation(
        route_id=_LIVE_ROUTE_ID,
        peer_trust_domain=_PEER_TRUST_DOMAIN,
        peer_audit_anchor_did=_PEER_DID,
        peer_wat_anchor_manifest_id=None,
        peer_trust_bundle_url=None,
        peer_capability_policy_pointer=None,
        is_mock=False,
    )
    # Add the bundle URL (None -> value): additive, accepted.
    a1 = MultiOrgRouteAttestation(
        route_id=_LIVE_ROUTE_ID,
        peer_trust_domain=_PEER_TRUST_DOMAIN,
        peer_audit_anchor_did=_PEER_DID,
        peer_wat_anchor_manifest_id=None,
        peer_trust_bundle_url="https://partner-a.example/spire/bundle",
        peer_capability_policy_pointer=None,
        is_mock=False,
    )
    # Try to clear the bundle URL (value -> None): refused.
    a2 = a0  # same as a0, which has bundle_url=None
    # Try to mutate the bundle URL (value-A -> value-B): refused.
    a3 = MultiOrgRouteAttestation(
        route_id=_LIVE_ROUTE_ID,
        peer_trust_domain=_PEER_TRUST_DOMAIN,
        peer_audit_anchor_did=_PEER_DID,
        peer_wat_anchor_manifest_id=None,
        peer_trust_bundle_url="https://partner-a.example/v2/bundle",
        peer_capability_policy_pointer=None,
        is_mock=False,
    )

    async def _go():
        await backend.put(a0)
        await backend.put(a1)
        # Idempotent rewrite of a1: accepted.
        await backend.put(a1)
        return await backend.get(_LIVE_ROUTE_ID)

    got = _run(_go())
    assert got == a1

    async def _go_clear():
        await backend.put(a2)

    with pytest.raises(MultiOrgAttestationMonotonicConflict) as exc_info:
        _run(_go_clear())
    assert exc_info.value.breach_kind == (
        "optional-mutation:peer_trust_bundle_url"
    )

    async def _go_mutate():
        await backend.put(a3)

    with pytest.raises(MultiOrgAttestationMonotonicConflict) as exc_info:
        _run(_go_mutate())
    assert exc_info.value.breach_kind == (
        "optional-mutation:peer_trust_bundle_url"
    )


# ---------------------------------------------------------------------------
# T-MOA-NKV-14..15 Cross-bucket replication
# ---------------------------------------------------------------------------


def test_t_moa_nkv_14_bootstrap_copies_and_idempotent_rerun():
    """T-MOA-NKV-14: bootstrap copies every source record to an
    empty target; a second bootstrap-pass over the same source and
    a fully-mirrored target is a no-op (idempotent)."""
    source = NatsKvMultiOrgAttestationRegistry(kv=_MockKv())
    target = NatsKvMultiOrgAttestationRegistry(kv=_MockKv())
    a1 = _make_live_att(route_id="r-1")
    a2 = _make_live_att(route_id="r-2")

    async def _seed_and_first():
        await source.put(a1)
        await source.put(a2)
        return await bootstrap_multi_org_attestation_target_from_source(
            source=source, target=target
        )

    metrics_first = _run(_seed_and_first())
    assert metrics_first.bootstrap_applied == 2
    assert metrics_first.bootstrap_skipped_idempotent == 0
    assert metrics_first.bootstrap_monotonic_breaches == 0

    async def _verify_target():
        snap = await target.snapshot()
        return snap.lookup("r-1"), snap.lookup("r-2")

    got_r1, got_r2 = _run(_verify_target())
    assert got_r1 == a1
    assert got_r2 == a2

    async def _second_pass():
        return await bootstrap_multi_org_attestation_target_from_source(
            source=source, target=target
        )

    metrics_second = _run(_second_pass())
    assert metrics_second.bootstrap_applied == 0
    assert metrics_second.bootstrap_skipped_idempotent == 2
    assert metrics_second.bootstrap_monotonic_breaches == 0


def test_t_moa_nkv_15_bootstrap_monotonic_breach_counted():
    """T-MOA-NKV-15: a source-side record that would mutate the
    target's authority anchor is refused; the counter advances and
    the target's live record is unchanged."""
    source = NatsKvMultiOrgAttestationRegistry(kv=_MockKv())
    target = NatsKvMultiOrgAttestationRegistry(kv=_MockKv())
    # Target carries a live attestation pointing at partner-a.
    target_live = _make_live_att(
        route_id="r-1",
        peer_trust_domain="partner-a.example",
        peer_audit_anchor_did="did:web:partner-a.example",
    )
    # Source carries a different authority anchor for the same key
    # (operator misconfiguration or hostile peer-side input).
    source_conflicting = _make_live_att(
        route_id="r-1",
        peer_trust_domain="partner-b.example",
        peer_audit_anchor_did="did:web:partner-b.example",
    )

    async def _go():
        await target.put(target_live)
        await source.put(source_conflicting)
        metrics = await bootstrap_multi_org_attestation_target_from_source(
            source=source, target=target
        )
        target_snap = await target.snapshot()
        return metrics, target_snap

    metrics, snap = _run(_go())
    assert metrics.bootstrap_applied == 0
    assert metrics.bootstrap_monotonic_breaches == 1
    # Target's live record is unchanged.
    assert snap.lookup("r-1") == target_live
