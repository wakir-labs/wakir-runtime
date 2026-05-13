# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the multi-org-attestation live-tail replicator.

Phase-2 Sprint-7 Tag-6. Pattern-mirror on the Sprint-6 Tag-6
capability-policy replication test suite at
``test_capability_policy_replication.py`` and the Sprint-7 Tag-2
multi-org-attestation backend test suite at
``test_federation_multi_org_attestation_nats_kv_backend.py``.

Surfaces under test:

- :class:`MultiOrgAttestationReplicator` (full bootstrap +
  watch-stream composition, via :meth:`run`)
- watch-stream-only run (``bootstrap=False``)
- filter on the live tail (``events_skipped_by_filter``)
- conflict policies (SOURCE_WINS / CAS_PIN) and per-policy
  monotonic-invariant breach + CAS conflict surfacing
- resume cursor (``last_revision`` monotonic-tracking)
- envelope-error halt policy

Test inventory (T-MOA-LTR-01..07):

- T-MOA-LTR-01: bootstrap + live-tail PUT propagates a fresh
  attestation onto the target; ``events_applied_put`` advances;
  ``last_revision`` reflects the live tail.
- T-MOA-LTR-02: live-tail DELETE removes the entry on the target;
  ``events_applied_delete`` advances.
- T-MOA-LTR-03: ``run(bootstrap=False)`` skips the bootstrap pass;
  only live-tail counters advance.
- T-MOA-LTR-04: filter ``only_partner_a`` skips a partner-b event;
  ``events_skipped_by_filter`` advances; target retains its
  pre-replicator state for partner-b.
- T-MOA-LTR-05: monotonic-invariant breach under ``SOURCE_WINS``
  is counted (``monotonic_breaches`` advances) and the target's
  live record is preserved byte-equal.
- T-MOA-LTR-06: CAS_PIN policy + concurrent target-side
  out-of-band put → ``cas_conflicts`` advances; replicator
  continues; subsequent unrelated event lands cleanly.
- T-MOA-LTR-07: resume-from-revision signal — after a run,
  ``last_revision`` equals the highest revision observed on the
  live tail (monotonic-only, never regresses on a re-issue).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

from wirelang.federation.multi_org_substrate import (
    MultiOrgRouteAttestation,
)
from wirelang.federation.multi_org_attestation_nats_kv_backend import (
    BUCKET_NAME,
    MultiOrgAttestationCasConflict,
    MultiOrgAttestationMonotonicConflict,
    MultiOrgAttestationReplicationConflictPolicy,
    MultiOrgAttestationReplicationDecision,
    MultiOrgAttestationReplicationMetrics,
    MultiOrgAttestationWatchEvent,
    NatsKvMultiOrgAttestationRegistry,
)
from wirelang.federation.multi_org_attestation_live_tail_replicator import (
    MultiOrgAttestationReplicator,
)


# ---------------------------------------------------------------------------
# Mock KV (mirrors the Sprint-7 Tag-2 backend-test mock + Sprint-6 Tag-6
# capability-policy-replication-test mock — watch + CAS + delete + keys)
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
    """Shape-2 mock watcher: ``await updates()`` returns one item
    or ``None`` sentinel on close."""

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
        """CAS-pinned write; raises a class-name-marked exception on
        revision mismatch. ``last=0`` is create-if-absent.
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


_TD_A = "partner-a.example"
_TD_B = "partner-b.example"
_DID_A = "did:web:partner-a.example"
_DID_B = "did:web:partner-b.example"


def _make_att(
    *,
    route_id: str,
    peer_trust_domain: str = _TD_A,
    peer_audit_anchor_did: str = _DID_A,
    peer_wat_anchor_manifest_id: Optional[str] = None,
) -> MultiOrgRouteAttestation:
    return MultiOrgRouteAttestation(
        route_id=route_id,
        peer_trust_domain=peer_trust_domain,
        peer_audit_anchor_did=peer_audit_anchor_did,
        peer_wat_anchor_manifest_id=peer_wat_anchor_manifest_id,
        is_mock=False,
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# T-MOA-LTR-01..07
# ---------------------------------------------------------------------------


def test_t_moa_ltr_01_bootstrap_plus_live_put_replicates():
    """T-MOA-LTR-01: bootstrap copies the seed; a live PUT lands on
    the target; ``events_applied_put`` advances; ``last_revision``
    reflects the live event."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
    target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)
    seed = _make_att(route_id="r-seed")
    live = _make_att(route_id="r-live")

    replicator = MultiOrgAttestationReplicator(
        source=source, target=target
    )

    async def _drive():
        await source.put(seed)
        run_task = asyncio.create_task(replicator.run())
        # Wait for bootstrap + watcher to settle.
        for _ in range(20):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        assert source_kv._watcher is not None
        await source.put(live)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    # Bootstrap: seed landed on target.
    assert replicator.metrics.bootstrap_applied == 1
    # Live tail: live event applied.
    assert replicator.metrics.events_applied_put == 1
    assert replicator.metrics.events_applied_delete == 0
    # Resume cursor reflects the live revision (source bumped twice:
    # seed @1 and live @2; live tail observes only revision >= 2).
    assert replicator.last_revision >= 2

    seed_on_target = _run(target.get("r-seed"))
    live_on_target = _run(target.get("r-live"))
    assert seed_on_target == seed
    assert live_on_target == live


def test_t_moa_ltr_02_live_delete_replicates():
    """T-MOA-LTR-02: a DELETE on the source removes the entry from
    the target via the live-tail; ``events_applied_delete`` advances.
    """
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
    target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)
    att = _make_att(route_id="r-1")

    replicator = MultiOrgAttestationReplicator(
        source=source, target=target
    )

    async def _drive():
        await source.put(att)
        run_task = asyncio.create_task(replicator.run())
        for _ in range(20):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        await source.delete(att.route_id)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    assert replicator.metrics.bootstrap_applied == 1
    assert replicator.metrics.events_applied_delete == 1
    assert _run(target.get(att.route_id)) is None


def test_t_moa_ltr_03_run_bootstrap_false_skips_bootstrap():
    """T-MOA-LTR-03: ``run(bootstrap=False)`` does NOT run the
    bootstrap pass; only the watch-stream tail applies."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
    target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)
    # Pre-seed the source ONLY; target stays empty.
    seed = _make_att(route_id="r-seed")
    live = _make_att(route_id="r-live")

    replicator = MultiOrgAttestationReplicator(
        source=source, target=target
    )

    async def _drive():
        await source.put(seed)
        # Open run with bootstrap=False — seed is NOT propagated.
        run_task = asyncio.create_task(replicator.run(bootstrap=False))
        for _ in range(20):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        await source.put(live)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    # No bootstrap-counter advance.
    assert replicator.metrics.bootstrap_applied == 0
    assert replicator.metrics.bootstrap_skipped_idempotent == 0
    # Live-tail: only the post-open live event lands.
    assert replicator.metrics.events_applied_put == 1
    # Seed is NOT on the target.
    assert _run(target.get("r-seed")) is None
    # Live IS on the target.
    assert _run(target.get("r-live")) == live


def test_t_moa_ltr_04_filter_skips_non_matching_events():
    """T-MOA-LTR-04: a filter that rejects partner-b events skips a
    partner-b PUT on the live tail; ``events_skipped_by_filter``
    advances; the target's pre-replicator state for the rejected
    key is preserved."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
    target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)

    only_partner_a = (
        lambda event: MultiOrgAttestationReplicationDecision.APPLY
        if (
            event.attestation is not None
            and event.attestation.peer_trust_domain == _TD_A
        )
        else MultiOrgAttestationReplicationDecision.SKIP
    )

    replicator = MultiOrgAttestationReplicator(
        source=source,
        target=target,
        filter_fn=only_partner_a,
    )

    a_att = _make_att(
        route_id="r-a", peer_trust_domain=_TD_A, peer_audit_anchor_did=_DID_A
    )
    b_att = _make_att(
        route_id="r-b", peer_trust_domain=_TD_B, peer_audit_anchor_did=_DID_B
    )

    async def _drive():
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        for _ in range(20):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        await source.put(a_att)
        await asyncio.sleep(0)
        await source.put(b_att)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    assert replicator.metrics.events_applied_put == 1
    assert replicator.metrics.events_skipped_by_filter == 1
    # Target carries partner-a, NOT partner-b.
    assert _run(target.get("r-a")) == a_att
    assert _run(target.get("r-b")) is None


def test_t_moa_ltr_05_source_wins_monotonic_breach_counted():
    """T-MOA-LTR-05: under SOURCE_WINS, a live event that would
    mutate a load-bearing authority anchor on the target is
    refused by the Tag-2 backend monotonic gate; the counter
    advances and the target's live record is preserved byte-equal.
    """
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
    target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)

    target_live = _make_att(
        route_id="r-1",
        peer_trust_domain=_TD_A,
        peer_audit_anchor_did=_DID_A,
    )
    source_conflicting = _make_att(
        route_id="r-1",
        peer_trust_domain=_TD_B,
        peer_audit_anchor_did=_DID_B,
    )

    replicator = MultiOrgAttestationReplicator(
        source=source, target=target
    )

    async def _drive():
        await target.put(target_live)
        # NB: bootstrap=False so the bootstrap pass does NOT counter-
        # advance the monotonic breach here (we count it on the live
        # tail).
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        for _ in range(20):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        await source.put(source_conflicting)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    assert replicator.metrics.monotonic_breaches == 1
    assert replicator.metrics.events_applied_put == 0
    # Target's record is unchanged.
    snap = _run(target.snapshot())
    assert snap.lookup("r-1") == target_live


def test_t_moa_ltr_06_cas_pin_conflict_counted_continues():
    """T-MOA-LTR-06: under CAS_PIN, an out-of-band target-side put
    between the replicator's ``get_with_revision`` and its
    ``put_with_revision`` advances ``cas_conflicts``; the replicator
    continues; a subsequent unrelated event lands cleanly via the
    same CAS path."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
    target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)

    # Seed both backends so the CAS path engages on r-cas.
    seed = _make_att(route_id="r-cas")
    _run(source.put(seed))
    _run(target.put(seed))

    replicator = MultiOrgAttestationReplicator(
        source=source,
        target=target,
        conflict_policy=(
            MultiOrgAttestationReplicationConflictPolicy.CAS_PIN
        ),
    )

    # Wrap target.get_with_revision so an out-of-band put bumps the
    # live revision AFTER the read but BEFORE the CAS write. The
    # bump is a byte-equal idempotent re-put of the same seed: the
    # monotonic gate passes (no field change), but the KV revision
    # counter advances — so the replicator's subsequent CAS-pin
    # against the pre-bump revision is now stale and collides.
    original_gwr = target.get_with_revision
    racing = {"injected": False}

    async def racing_gwr(route_id: str):
        result = await original_gwr(route_id)
        if (
            not racing["injected"]
            and result is not None
            and route_id == "r-cas"
        ):
            racing["injected"] = True
            await target.put(seed)
        return result

    target.get_with_revision = racing_gwr  # type: ignore

    async def _drive():
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        for _ in range(20):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        # e1: source emits an additive-monotonic update on r-cas;
        # the racing wrapper bumps the target between read and
        # CAS-write so this CAS attempt collides.
        e1 = MultiOrgRouteAttestation(
            route_id="r-cas",
            peer_trust_domain=_TD_A,
            peer_audit_anchor_did=_DID_A,
            peer_wat_anchor_manifest_id="src-update-wat",
            is_mock=False,
        )
        await source.put(e1)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # e2: a fresh key — CAS path is straight create-if-absent;
        # the racing wrapper does not fire (key != r-cas).
        e2 = _make_att(route_id="r-clean")
        await source.put(e2)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    assert replicator.metrics.cas_conflicts == 1
    # e2 landed cleanly under the CAS-create-if-absent path.
    assert replicator.metrics.events_applied_put == 1
    # r-cas on the target carries the OOB-bumped seed (byte-equal to
    # the pre-existing seed); the source's e1 update lost the CAS
    # race and is NOT on the target.
    r_cas = _run(target.get("r-cas"))
    assert r_cas == seed
    assert r_cas.peer_wat_anchor_manifest_id is None
    # r-clean is on the target via the replicator.
    r_clean = _run(target.get("r-clean"))
    assert r_clean is not None
    assert r_clean.route_id == "r-clean"


def test_t_moa_ltr_07_last_revision_monotonic_resume_cursor():
    """T-MOA-LTR-07: ``last_revision`` tracks the highest revision
    observed on the live tail; it advances monotonically with every
    event (apply OR filter-skip) and never regresses on a re-issue.

    This is the operator-side resume-cursor contract: persist the
    cursor between runs, re-bake it into a Phase-3 ``resume_from``
    watch-stream open call. Tag-6 itself does NOT wire the cursor
    into the open call; this test exercises the tracking contract."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
    target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)

    a1 = _make_att(route_id="r-1")
    a2 = _make_att(route_id="r-2")
    a3 = _make_att(route_id="r-3")

    # Filter that rejects r-2 so the skipped-event still advances
    # the cursor.
    def reject_r2(event):
        if event.route_id == "r-2":
            return MultiOrgAttestationReplicationDecision.SKIP
        return MultiOrgAttestationReplicationDecision.APPLY

    replicator = MultiOrgAttestationReplicator(
        source=source,
        target=target,
        filter_fn=reject_r2,
    )

    async def _drive():
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        for _ in range(20):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        # Three events: r-1 applied @rev=1, r-2 filtered @rev=2,
        # r-3 applied @rev=3. Cursor must reach 3.
        await source.put(a1)
        await asyncio.sleep(0)
        await source.put(a2)
        await asyncio.sleep(0)
        await source.put(a3)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    assert replicator.metrics.events_applied_put == 2
    assert replicator.metrics.events_skipped_by_filter == 1
    # last_revision reflects the highest event revision regardless
    # of filter-skip.
    assert replicator.last_revision == 3

    # Monotonic-only contract: feeding an event with a lower
    # revision must NOT regress the cursor. We exercise the
    # private path directly with a synthetic event to keep the
    # test hermetic (no second watch-stream / no second run).
    from wirelang.federation.multi_org_attestation_nats_kv_backend import (
        MultiOrgAttestationWatchOp as _Op,
    )
    synthetic_low = MultiOrgAttestationWatchEvent(
        op=_Op.DELETE,
        route_id="r-1",
        attestation=None,
        revision=1,
    )

    async def _replay_low():
        await replicator._consume_event(synthetic_low)

    _run(_replay_low())
    # Cursor stayed at 3 (never regresses on a lower-revision event).
    assert replicator.last_revision == 3


# ---------------------------------------------------------------------------
# T-MOA-LTR-RPL-01..06 — Sprint-9 Tag-3 Teil B detect_replay-callsite-mirror
# ---------------------------------------------------------------------------


def test_t_moa_ltr_rpl_01_default_pass_through_byte_identical_to_tag_6():
    """T-MOA-LTR-RPL-01: with the default no-op replay detector,
    the replicator's behaviour is byte-identical to Sprint-7
    Tag-6. A simple put is applied; no replay-drop counters fire.
    """
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
    target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)
    att = _make_att(route_id="r-1")

    replicator = MultiOrgAttestationReplicator(
        source=source, target=target
    )

    async def _drive():
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        for _ in range(20):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        await source.put(att)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    assert replicator.metrics.events_applied_put == 1
    # No replay drops with the default detector.
    assert replicator.replay_drops_per_org == {}
    assert replicator.total_replay_drops == 0


def test_t_moa_ltr_rpl_02_replay_decision_drops_event_advances_counter():
    """T-MOA-LTR-RPL-02: a replay-detector that returns REPLAY for
    a synthetic-marked event drops the event (no target write) and
    advances the per-org counter under the peer's trust-domain key.
    """
    from wirelang.federation.multi_org_attestation_live_tail_replicator import (
        ReplayDetectorDecision,
    )

    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
    target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)

    # Mark r-replay as a "replay" via the route_id; every other
    # event passes through. The detector inspects the event surface
    # (route_id is the cross-org key); a production detector would
    # extract route_id/chain_hash/sequence and delegate to a
    # NatsKvSequenceNumberLedger.
    def detector(event):
        if event.route_id == "r-replay":
            return ReplayDetectorDecision.REPLAY
        return ReplayDetectorDecision.PASS_THROUGH

    replicator = MultiOrgAttestationReplicator(
        source=source,
        target=target,
        replay_detector_fn=detector,
    )

    clean = _make_att(
        route_id="r-clean",
        peer_trust_domain=_TD_A,
        peer_audit_anchor_did=_DID_A,
    )
    replay = _make_att(
        route_id="r-replay",
        peer_trust_domain=_TD_A,
        peer_audit_anchor_did=_DID_A,
    )

    async def _drive():
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        for _ in range(20):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        await source.put(clean)
        await asyncio.sleep(0)
        await source.put(replay)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    # Clean event landed on target.
    assert _run(target.get("r-clean")) == clean
    # Replay event was DROPPED — no target-side write.
    assert _run(target.get("r-replay")) is None
    assert replicator.metrics.events_applied_put == 1
    # Per-org counter increments under partner-a's trust domain.
    assert replicator.replay_drops_per_org == {_TD_A: 1}
    assert replicator.total_replay_drops == 1


def test_t_moa_ltr_rpl_03_pass_through_non_replays_unchanged():
    """T-MOA-LTR-RPL-03: a sequence of clean events with a
    detector that always returns PASS_THROUGH is replicated
    byte-identical to the default-detector path. The
    replay-drop counter stays at zero across multiple events.
    """
    from wirelang.federation.multi_org_attestation_live_tail_replicator import (
        ReplayDetectorDecision,
    )

    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
    target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)

    pass_count = {"calls": 0}

    def detector(event):
        pass_count["calls"] += 1
        return ReplayDetectorDecision.PASS_THROUGH

    replicator = MultiOrgAttestationReplicator(
        source=source,
        target=target,
        replay_detector_fn=detector,
    )

    a1 = _make_att(route_id="r-1")
    a2 = _make_att(route_id="r-2")
    a3 = _make_att(route_id="r-3")

    async def _drive():
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        for _ in range(20):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        for att in (a1, a2, a3):
            await source.put(att)
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    # Three events, all applied, detector called three times.
    assert replicator.metrics.events_applied_put == 3
    assert pass_count["calls"] == 3
    assert replicator.replay_drops_per_org == {}
    assert replicator.total_replay_drops == 0
    # All three on target.
    for route_id, expected in zip(("r-1", "r-2", "r-3"), (a1, a2, a3)):
        assert _run(target.get(route_id)) == expected


def test_t_moa_ltr_rpl_04_per_org_drop_counter_buckets_by_peer():
    """T-MOA-LTR-RPL-04: drop counts are tracked per peer-trust-
    domain. A detector that drops events from two distinct peers
    surfaces two separate counters; the global ``total_replay_drops``
    is their sum.
    """
    from wirelang.federation.multi_org_attestation_live_tail_replicator import (
        ReplayDetectorDecision,
    )

    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
    target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)

    def detector(event):
        # Drop everything (synthetic — every event is "replay").
        return ReplayDetectorDecision.REPLAY

    replicator = MultiOrgAttestationReplicator(
        source=source,
        target=target,
        replay_detector_fn=detector,
    )

    a_event = _make_att(
        route_id="r-a-1",
        peer_trust_domain=_TD_A,
        peer_audit_anchor_did=_DID_A,
    )
    a_event_2 = _make_att(
        route_id="r-a-2",
        peer_trust_domain=_TD_A,
        peer_audit_anchor_did=_DID_A,
    )
    b_event = _make_att(
        route_id="r-b-1",
        peer_trust_domain=_TD_B,
        peer_audit_anchor_did=_DID_B,
    )

    async def _drive():
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        for _ in range(20):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        for att in (a_event, a_event_2, b_event):
            await source.put(att)
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    # Nothing landed on target.
    assert _run(target.get("r-a-1")) is None
    assert _run(target.get("r-a-2")) is None
    assert _run(target.get("r-b-1")) is None
    assert replicator.metrics.events_applied_put == 0
    # Two counters: partner-a observed twice, partner-b observed once.
    assert replicator.replay_drops_per_org == {
        _TD_A: 2,
        _TD_B: 1,
    }
    assert replicator.total_replay_drops == 3


def test_t_moa_ltr_rpl_05_detector_invoked_after_filter():
    """T-MOA-LTR-RPL-05: the replay detector is invoked AFTER the
    filter. A filter that rejects partner-b means the replay
    detector never sees partner-b events; the partner-b counter
    stays at zero even though the detector would have dropped them.
    """
    from wirelang.federation.multi_org_attestation_live_tail_replicator import (
        ReplayDetectorDecision,
    )

    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
    target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)

    only_partner_a = (
        lambda event: MultiOrgAttestationReplicationDecision.APPLY
        if (
            event.attestation is not None
            and event.attestation.peer_trust_domain == _TD_A
        )
        else MultiOrgAttestationReplicationDecision.SKIP
    )

    detector_calls = []

    def detector(event):
        detector_calls.append(event.route_id)
        return ReplayDetectorDecision.REPLAY

    replicator = MultiOrgAttestationReplicator(
        source=source,
        target=target,
        filter_fn=only_partner_a,
        replay_detector_fn=detector,
    )

    a_event = _make_att(
        route_id="r-a",
        peer_trust_domain=_TD_A,
        peer_audit_anchor_did=_DID_A,
    )
    b_event = _make_att(
        route_id="r-b",
        peer_trust_domain=_TD_B,
        peer_audit_anchor_did=_DID_B,
    )

    async def _drive():
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        for _ in range(20):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        await source.put(a_event)
        await asyncio.sleep(0)
        await source.put(b_event)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    # Detector saw only the partner-a event.
    assert detector_calls == ["r-a"]
    # Partner-b skipped by filter (not by replay).
    assert replicator.metrics.events_skipped_by_filter == 1
    # Partner-a dropped by replay detector.
    assert replicator.replay_drops_per_org == {_TD_A: 1}
    # No target writes at all.
    assert _run(target.get("r-a")) is None
    assert _run(target.get("r-b")) is None


def test_t_moa_ltr_rpl_06_invalid_detector_return_raises_typeerror():
    """T-MOA-LTR-RPL-06: a detector that returns the wrong type
    raises ``TypeError`` from the consume path. This is the
    loud-failure contract: a misconfigured detector must not
    silently corrupt replay-protection guarantees.
    """
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvMultiOrgAttestationRegistry(kv=source_kv)
    target = NatsKvMultiOrgAttestationRegistry(kv=target_kv)

    def bad_detector(event):
        return "not-a-decision"  # type: ignore[return-value]

    replicator = MultiOrgAttestationReplicator(
        source=source,
        target=target,
        replay_detector_fn=bad_detector,
    )

    att = _make_att(route_id="r-1")

    async def _drive():
        await source.put(att)
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        for _ in range(20):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        await source.put(_make_att(route_id="r-2"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        try:
            await asyncio.wait_for(run_task, timeout=2.0)
        except TypeError:
            return "raised"
        return "no-raise"

    # The replicator's default halt_on_envelope_error doesn't catch
    # TypeError; we exercise the private path directly to keep the
    # test hermetic and the assertion crisp.
    synthetic = MultiOrgAttestationWatchEvent(
        op=__import__(
            "wirelang.federation.multi_org_attestation_nats_kv_backend",
            fromlist=["MultiOrgAttestationWatchOp"],
        ).MultiOrgAttestationWatchOp.PUT,
        route_id="r-1",
        attestation=att,
        revision=1,
    )

    async def _raise():
        await replicator._consume_event(synthetic)

    with pytest.raises(TypeError, match="replay_detector_fn"):
        _run(_raise())
