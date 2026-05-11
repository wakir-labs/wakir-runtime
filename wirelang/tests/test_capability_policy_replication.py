# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the Wirelang capability-policy replication layer.

Phase-2 Sprint-6 Tag-6 (S6-6). Tests the cross-bucket replication
layer for the capability-policy backend that composes:

- Sprint-5 Tag-2 LWW (``put`` / ``get`` / ``snapshot``)
- Sprint-5 Tag-4 CAS-pin (``put_with_revision`` /
  ``get_with_revision`` / :class:`CapabilityPolicyConflictError`)
- Sprint-5 Tag-5 watch-stream (``watch`` /
  :class:`CapabilityPolicyWatchEvent` /
  :class:`CapabilityPolicyWatchOp`)
- Sprint-6 Tag-1 revocation-monotonic invariant
  (:class:`CapabilityPolicyRevocationConflict`)

Surfaces under test:

- :class:`CapabilityPolicyReplicator` (run / bootstrap / event loop)
- :func:`bootstrap_capability_policy_target_from_source`
- :class:`CapabilityPolicyReplicationFilter`
- :class:`CapabilityPolicyReplicationConflictPolicy`
- :class:`CapabilityPolicyReplicationMetrics` (per-run counters,
  including ``revocation_breaches`` and
  ``bootstrap_revocation_breaches``)

Pattern source: the Phase-1b Sprint-3 Tag-6 schema-registry
replication tests (``test_schema_registry_replication.py``).
Tag-6 extends the pattern with revocation-monotonic-invariant
preservation across the cross-bucket boundary; the schema-
registry path has no equivalent invariant because schema-registry
entries are append-only at the ``(layer, name, version)`` triple
and do NOT carry a one-way authority gesture.

Test inventory (T-CPP-REP-01..14):

- T-CPP-REP-01: bootstrap copies every source record onto an
  empty target in keys-sorted order.
- T-CPP-REP-02: bootstrap is idempotent (second pass on a
  byte-equal target advances ``bootstrap_skipped_idempotent``).
- T-CPP-REP-03: a filter (``only_registered_by_alpha``) skips
  non-matching records during bootstrap; counter
  ``bootstrap_skipped_by_filter`` advances; the rejected record
  is NOT on the target.
- T-CPP-REP-04: live PUT events on the source land on the target
  via watch-stream tail; ``events_applied_put`` advances.
- T-CPP-REP-05: live DELETE events on the source remove the entry
  from the target; ``events_applied_delete`` advances.
- T-CPP-REP-06: ``CAS_PIN`` policy + race-window simulation —
  ``target.get_with_revision`` is wrapped to inject an
  out-of-band ``target.put`` between read and CAS-write;
  ``cas_conflicts`` advances, replicator continues.
- T-CPP-REP-07: ``halt_on_conflict=True`` re-raises on first
  CAS conflict.
- T-CPP-REP-08: a poisoned envelope on the source watch-stream
  raises :class:`CapabilityPolicyEnvelopeError` from ``run``;
  ``envelope_errors`` advances.
- T-CPP-REP-09: a filter that skips a live event does NOT apply
  it to the target; ``events_skipped_by_filter`` advances.
- T-CPP-REP-10: source==target rejected with ``ValueError`` at
  construction.
- T-CPP-REP-11: a PUT WatchEvent with a missing ``record`` is
  rejected as envelope poison at the replicator boundary.
- T-CPP-REP-12: ``run(bootstrap=False)`` skips the bootstrap pass.
- **T-CPP-REP-13:** revocation-monotonic preservation under
  ``SOURCE_WINS`` — the target holds a revoked record; the
  source emits a stale unrevoked record for the same key; the
  replicator refuses the write, ``revocation_breaches``
  advances, and the target's revoked record is preserved
  byte-equal.
- **T-CPP-REP-14:** revocation-monotonic preservation under
  ``CAS_PIN`` — the target's server-side Sprint-6 Tag-1 gate
  raises :class:`CapabilityPolicyRevocationConflict`; the
  replicator catches it, advances ``revocation_breaches``, and
  continues by default.

Auxiliary probes:

- aux-bootstrap-revocation-breach: bootstrap-time
  revocation-breach refusal advances
  ``bootstrap_revocation_breaches`` and does NOT corrupt the
  target.
- aux-revocation-reason-refresh: an equal-instant rewrite with a
  refreshed ``revocation_reason`` replicates cleanly (not a
  breach).
- aux-halt-on-revocation-breach: ``halt_on_revocation_breach=True``
  re-raises a :class:`CapabilityPolicyRevocationConflict` from
  ``run`` under either policy.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from wirelang.schemas.capability_policy_nats_kv_backend import (
    BUCKET_NAME,
    CapabilityPolicyConflictError,
    CapabilityPolicyEnvelopeError,
    CapabilityPolicyRecord,
    CapabilityPolicyRevocationConflict,
    CapabilityPolicyWatchEvent,
    CapabilityPolicyWatchOp,
    NatsKvCapabilityPolicyBackend,
    VALUE_SCHEMA,
    _record_to_envelope,
    key_for_policy_pair,
)
from wirelang.schemas.capability_policy_replication import (
    CapabilityPolicyReplicationConflictPolicy,
    CapabilityPolicyReplicationDecision,
    CapabilityPolicyReplicationFilter,
    CapabilityPolicyReplicationMetrics,
    CapabilityPolicyReplicator,
    bootstrap_capability_policy_target_from_source,
)
from wirelang.schemas.registered_by_capability import (
    CapabilityPolicy,
)


# ---------------------------------------------------------------------------
# Mock KV with watch + CAS surfaces (mirrors the Sprint-5 Tag-5 test pattern)
# ---------------------------------------------------------------------------


class _MockBucketNotFoundError(Exception):
    """Mirrors nats-py's ``KeyNotFoundError`` class-name pattern."""


class _MockKeyWrongLastSequenceError(Exception):
    """Mirrors nats-py's ``KeyWrongLastSequenceError`` class-name pattern."""


@dataclass
class _MockKvEntry:
    """Shape-equivalent of nats-py's ``KeyValue.Entry``."""

    value: bytes
    revision: int = 0


@dataclass
class _MockWatchUpdate:
    """Shape-equivalent of nats-py's ``KeyValue.Entry`` exposed
    through the watcher.
    """

    operation: str
    key: str
    value: bytes = b""
    revision: int = 0


class _MockWatcher:
    """Manually-fed Shape-2 mock watcher."""

    def __init__(self):
        self._queue = asyncio.Queue()
        self._stopped = False

    def _push(self, update):
        self._queue.put_nowait(update)

    def _close(self):
        # Sentinel ``None`` per nats-py end-of-stream contract.
        self._queue.put_nowait(None)

    async def updates(self):
        if self._stopped:
            return None
        return await self._queue.get()

    async def stop(self):
        self._stopped = True


@dataclass
class _MockKv:
    """In-memory replacement for nats-py's ``KeyValue`` handle.

    Surfaces ``await kv.get/put/update/delete/keys/watchall``.
    """

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
        existing = self.store.get(key)
        live = existing.revision if existing is not None else 0
        if last != live:
            raise _MockKeyWrongLastSequenceError(
                f"expected revision {last} but live is {live}"
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


_REGISTERED_AT = datetime(2026, 5, 12, 13, 0, 0, tzinfo=timezone.utc)
_REGISTERED_BY_ALPHA = "alpha-issuer"
_REGISTERED_BY_BETA = "beta-issuer"


_DEFAULT_ALLOWED_KIDS = ("kid-rep-1",)
_DEFAULT_ALLOWED_TRIPLES = (("wire", "*"),)


def _make_record(
    *,
    registered_by: str = _REGISTERED_BY_ALPHA,
    policy_id: str = "policy-a",
    allowed_kids: tuple = _DEFAULT_ALLOWED_KIDS,
    allowed_triples: tuple = _DEFAULT_ALLOWED_TRIPLES,
    disabled: bool = False,
    note: Optional[str] = None,
    revoked_at: Optional[datetime] = None,
    revocation_reason: Optional[str] = None,
    registered_at: datetime = _REGISTERED_AT,
    registered_by_publisher: str = "wirelang-eng",
) -> CapabilityPolicyRecord:
    policy = CapabilityPolicy(
        registered_by=registered_by,
        allowed_kids=allowed_kids,
        allowed_triples=allowed_triples,
        disabled=disabled,
        note=note,
        revoked_at=revoked_at,
        revocation_reason=revocation_reason,
    )
    return CapabilityPolicyRecord(
        policy=policy,
        policy_id=policy_id,
        registered_at=registered_at,
        registered_by_publisher=registered_by_publisher,
    )


def _envelope_watch_update(
    record: CapabilityPolicyRecord, revision: int
) -> _MockWatchUpdate:
    return _MockWatchUpdate(
        operation="PUT",
        key=record.key,
        value=_record_to_envelope(record),
        revision=revision,
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_t_cpp_rep_01_bootstrap_copies_all_entries_in_sorted_order():
    """T-CPP-REP-01."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    r1 = _make_record(policy_id="alpha-1")
    r2 = _make_record(
        registered_by=_REGISTERED_BY_BETA, policy_id="beta-1"
    )
    r3 = _make_record(policy_id="alpha-2")

    async def _prepare():
        await source.put(r1)
        await source.put(r2)
        await source.put(r3)

    _run(_prepare())

    metrics = _run(
        bootstrap_capability_policy_target_from_source(
            source=source, target=target
        )
    )

    assert metrics.bootstrap_applied == 3
    assert metrics.bootstrap_skipped_idempotent == 0
    assert metrics.bootstrap_skipped_by_filter == 0
    assert metrics.bootstrap_revocation_breaches == 0
    # Target byte-equal to source.
    for record in (r1, r2, r3):
        target_entry = _run(target.get(record.key))
        assert target_entry is not None
        assert _record_to_envelope(record) == _record_to_envelope(
            target_entry
        )


def test_t_cpp_rep_02_bootstrap_idempotent():
    """T-CPP-REP-02."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    r = _make_record(policy_id="idem-1")
    _run(source.put(r))

    m1 = _run(
        bootstrap_capability_policy_target_from_source(
            source=source, target=target
        )
    )
    m2 = _run(
        bootstrap_capability_policy_target_from_source(
            source=source, target=target
        )
    )
    assert m1.bootstrap_applied == 1
    assert m2.bootstrap_applied == 0
    assert m2.bootstrap_skipped_idempotent == 1


def test_t_cpp_rep_03_bootstrap_filter_skips_non_matching():
    """T-CPP-REP-03."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    r_alpha = _make_record(
        registered_by=_REGISTERED_BY_ALPHA, policy_id="alpha-1"
    )
    r_beta = _make_record(
        registered_by=_REGISTERED_BY_BETA, policy_id="beta-1"
    )

    async def _prepare():
        await source.put(r_alpha)
        await source.put(r_beta)

    _run(_prepare())

    def only_alpha(
        event: CapabilityPolicyWatchEvent,
    ) -> CapabilityPolicyReplicationDecision:
        if (
            event.record is not None
            and event.record.policy.registered_by
            == _REGISTERED_BY_ALPHA
        ):
            return CapabilityPolicyReplicationDecision.APPLY
        return CapabilityPolicyReplicationDecision.SKIP

    metrics = _run(
        bootstrap_capability_policy_target_from_source(
            source=source, target=target, filter_fn=only_alpha
        )
    )

    assert metrics.bootstrap_applied == 1
    assert metrics.bootstrap_skipped_by_filter == 1
    assert _run(target.get(r_alpha.key)) is not None
    assert _run(target.get(r_beta.key)) is None


def test_t_cpp_rep_04_live_put_replicates():
    """T-CPP-REP-04."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    r_bootstrap = _make_record(policy_id="boot")
    _run(source.put(r_bootstrap))

    replicator = CapabilityPolicyReplicator(
        source=source, target=target
    )

    async def _drive():
        run_task = asyncio.create_task(replicator.run())
        # Wait for bootstrap to settle.
        await asyncio.sleep(0)
        # Open the watcher BEFORE emitting the live PUT, so the
        # event is captured. The replicator creates the watcher on
        # source.kv via _open_capability_policy_watcher; once
        # the run task awaits the watcher, source_kv._watcher is
        # set.
        for _ in range(10):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        assert source_kv._watcher is not None

        r_live = _make_record(policy_id="live-1")
        await source.put(r_live)
        # Allow event loop to deliver the event.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        try:
            await asyncio.wait_for(run_task, timeout=2.0)
        except asyncio.TimeoutError:
            run_task.cancel()
            raise

    _run(_drive())

    assert replicator.metrics.bootstrap_applied == 1
    assert replicator.metrics.events_applied_put == 1
    r_live = _make_record(policy_id="live-1")
    assert _record_to_envelope(
        _run(target.get(r_live.key))
    ) == _record_to_envelope(r_live)


def test_t_cpp_rep_05_live_delete_replicates():
    """T-CPP-REP-05."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    r = _make_record(policy_id="to-delete")
    _run(source.put(r))

    replicator = CapabilityPolicyReplicator(
        source=source, target=target
    )

    async def _drive():
        run_task = asyncio.create_task(replicator.run())
        await asyncio.sleep(0)
        for _ in range(10):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        await source.delete(r.key)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    assert replicator.metrics.bootstrap_applied == 1
    assert replicator.metrics.events_applied_delete == 1
    assert _run(target.get(r.key)) is None


def test_t_cpp_rep_06_cas_pin_conflict_continues():
    """T-CPP-REP-06."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    # Bootstrap target with a record so CAS-pin path engages.
    r_seed = _make_record(policy_id="cas-1", note="seed")
    _run(source.put(r_seed))
    _run(target.put(r_seed))

    replicator = CapabilityPolicyReplicator(
        source=source,
        target=target,
        conflict_policy=(
            CapabilityPolicyReplicationConflictPolicy.CAS_PIN
        ),
    )

    # Wrap target's get_with_revision so that AFTER it returns,
    # an out-of-band put bumps the live revision; the subsequent
    # CAS-pin write must then fail.
    original_gwr = target.get_with_revision

    racing = {"injected": False}

    async def racing_get_with_revision(key: str):
        result = await original_gwr(key)
        if (
            not racing["injected"]
            and result is not None
            and key == r_seed.key
        ):
            racing["injected"] = True
            # Bump the live revision out of band.
            await target.put(
                _make_record(policy_id="cas-1", note="oob-bump")
            )
        return result

    target.get_with_revision = racing_get_with_revision  # type: ignore

    async def _drive():
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        await asyncio.sleep(0)
        for _ in range(10):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        # Emit two source events: e1 trips CAS, e2 lands cleanly.
        r_e1 = _make_record(policy_id="cas-1", note="e1")
        await source.put(r_e1)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        r_e2 = _make_record(policy_id="cas-2", note="e2")
        await source.put(r_e2)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    assert replicator.metrics.cas_conflicts == 1
    assert replicator.metrics.events_applied_put == 1
    # The target's record at cas-1 reflects the out-of-band put,
    # not the source's e1.
    cas1 = _run(target.get(r_seed.key))
    assert cas1.policy.note == "oob-bump"


def test_t_cpp_rep_07_halt_on_conflict_re_raises():
    """T-CPP-REP-07."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    r_seed = _make_record(policy_id="halt-cas")
    _run(source.put(r_seed))
    _run(target.put(r_seed))

    replicator = CapabilityPolicyReplicator(
        source=source,
        target=target,
        conflict_policy=(
            CapabilityPolicyReplicationConflictPolicy.CAS_PIN
        ),
        halt_on_conflict=True,
    )

    original_gwr = target.get_with_revision
    injected = {"x": False}

    async def racing_gwr(key: str):
        result = await original_gwr(key)
        if not injected["x"] and result is not None:
            injected["x"] = True
            await target.put(
                _make_record(policy_id="halt-cas", note="oob")
            )
        return result

    target.get_with_revision = racing_gwr  # type: ignore

    async def _drive():
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        await asyncio.sleep(0)
        for _ in range(10):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        await source.put(_make_record(policy_id="halt-cas", note="e1"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        with pytest.raises(CapabilityPolicyConflictError):
            await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    assert replicator.metrics.cas_conflicts == 1


def test_t_cpp_rep_08_poisoned_envelope_halts():
    """T-CPP-REP-08."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    replicator = CapabilityPolicyReplicator(
        source=source, target=target
    )

    async def _drive():
        run_task = asyncio.create_task(replicator.run())
        await asyncio.sleep(0)
        for _ in range(10):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        # Inject a poisoned PUT directly onto the watcher (bypasses
        # the source.put path's envelope round-trip).
        source_kv._watcher._push(
            _MockWatchUpdate(
                operation="PUT",
                key="capability-policies/alpha-issuer/poison",
                value=b"not-json",
                revision=99,
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        with pytest.raises(CapabilityPolicyEnvelopeError):
            await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    assert replicator.metrics.envelope_errors == 1


def test_t_cpp_rep_09_live_event_filter_skips():
    """T-CPP-REP-09."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    def only_alpha(
        event: CapabilityPolicyWatchEvent,
    ) -> CapabilityPolicyReplicationDecision:
        if event.record is None:
            return CapabilityPolicyReplicationDecision.APPLY
        if (
            event.record.policy.registered_by
            == _REGISTERED_BY_ALPHA
        ):
            return CapabilityPolicyReplicationDecision.APPLY
        return CapabilityPolicyReplicationDecision.SKIP

    replicator = CapabilityPolicyReplicator(
        source=source, target=target, filter_fn=only_alpha
    )

    async def _drive():
        run_task = asyncio.create_task(replicator.run())
        await asyncio.sleep(0)
        for _ in range(10):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        r_apply = _make_record(
            registered_by=_REGISTERED_BY_ALPHA, policy_id="a-1"
        )
        r_skip = _make_record(
            registered_by=_REGISTERED_BY_BETA, policy_id="b-1"
        )
        await source.put(r_apply)
        await asyncio.sleep(0)
        await source.put(r_skip)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    assert replicator.metrics.events_applied_put == 1
    assert replicator.metrics.events_skipped_by_filter == 1
    assert _run(
        target.get(
            key_for_policy_pair(_REGISTERED_BY_BETA, "b-1")
        )
    ) is None


def test_t_cpp_rep_10_source_eq_target_rejected():
    """T-CPP-REP-10."""
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    with pytest.raises(ValueError):
        CapabilityPolicyReplicator(
            source=backend, target=backend
        )


def test_t_cpp_rep_11_put_with_none_record_rejected():
    """T-CPP-REP-11."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    replicator = CapabilityPolicyReplicator(
        source=source, target=target
    )

    bad_event = CapabilityPolicyWatchEvent(
        op=CapabilityPolicyWatchOp.PUT,
        key="capability-policies/alpha-issuer/bad",
        record=None,
        revision=1,
    )

    with pytest.raises(CapabilityPolicyEnvelopeError):
        _run(replicator._apply_put(bad_event))


def test_t_cpp_rep_12_run_without_bootstrap_skips_initial_pass():
    """T-CPP-REP-12."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    r_pre = _make_record(policy_id="pre-existing")
    _run(source.put(r_pre))

    replicator = CapabilityPolicyReplicator(
        source=source, target=target
    )

    async def _drive():
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        await asyncio.sleep(0)
        for _ in range(10):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        r_live = _make_record(policy_id="live-only")
        await source.put(r_live)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    assert replicator.metrics.bootstrap_applied == 0
    assert replicator.metrics.events_applied_put == 1
    # pre-existing source record was NOT bootstrapped.
    assert _run(target.get(r_pre.key)) is None


# ---------------------------------------------------------------------------
# Revocation-monotonic preservation tests (Tag-6 core deliverable)
# ---------------------------------------------------------------------------


def test_t_cpp_rep_13_revocation_preserved_under_source_wins():
    """T-CPP-REP-13: SOURCE_WINS in-band refusal of un-revoke."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    revoked_at = datetime(
        2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc
    )
    r_revoked = _make_record(
        policy_id="r-1",
        revoked_at=revoked_at,
        revocation_reason="key compromise",
    )
    # Target holds the revoked record.
    _run(target.put(r_revoked))
    # Source emits a STALE unrevoked record for the same key.
    r_stale_unrevoked = _make_record(
        policy_id="r-1", revoked_at=None
    )
    _run(source.put(r_stale_unrevoked))

    replicator = CapabilityPolicyReplicator(
        source=source, target=target
    )

    async def _drive():
        run_task = asyncio.create_task(replicator.run())
        await asyncio.sleep(0)
        for _ in range(10):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    # Bootstrap pass: the source's stale unrevoked record would
    # un-revoke the target's revoked record. Refused.
    assert replicator.metrics.bootstrap_revocation_breaches == 1
    assert replicator.metrics.bootstrap_applied == 0
    # Target's revoked record is preserved byte-equal.
    target_record = _run(target.get(r_revoked.key))
    assert target_record is not None
    assert target_record.policy.revoked_at == revoked_at
    assert _record_to_envelope(
        target_record
    ) == _record_to_envelope(r_revoked)


def test_t_cpp_rep_14_revocation_preserved_under_cas_pin():
    """T-CPP-REP-14: CAS_PIN server-side refusal of un-revoke."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    revoked_at = datetime(
        2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc
    )
    r_revoked = _make_record(
        policy_id="r-cas",
        revoked_at=revoked_at,
        revocation_reason="key compromise",
    )
    # Target and source both hold the revoked record initially.
    _run(target.put(r_revoked))
    _run(source.put(r_revoked))

    replicator = CapabilityPolicyReplicator(
        source=source,
        target=target,
        conflict_policy=(
            CapabilityPolicyReplicationConflictPolicy.CAS_PIN
        ),
    )

    async def _drive():
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        await asyncio.sleep(0)
        for _ in range(10):
            if source_kv._watcher is not None:
                break
            await asyncio.sleep(0)
        # Source emits a STALE unrevoked record for the same key.
        # Source-side LWW path tolerates this (operator-
        # deliberate); the resulting watch-event flows to the
        # replicator's CAS-pin path on the target, which raises
        # CapabilityPolicyRevocationConflict.
        r_stale_unrevoked = _make_record(
            policy_id="r-cas", revoked_at=None
        )
        await source.put(r_stale_unrevoked)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        source_kv._watcher._close()
        await asyncio.wait_for(run_task, timeout=2.0)

    _run(_drive())

    assert replicator.metrics.revocation_breaches == 1
    assert replicator.metrics.cas_conflicts == 0
    # Target's revoked record is preserved byte-equal.
    target_record = _run(target.get(r_revoked.key))
    assert target_record is not None
    assert target_record.policy.revoked_at == revoked_at


# ---------------------------------------------------------------------------
# Auxiliary probes
# ---------------------------------------------------------------------------


def test_aux_bootstrap_revocation_breach_advances_counter():
    """Aux: bootstrap-time revocation breach advances counter
    and preserves target.
    """
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    revoked_at = datetime(
        2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc
    )
    r_revoked = _make_record(
        policy_id="r-boot", revoked_at=revoked_at
    )
    _run(target.put(r_revoked))
    r_advance = _make_record(
        policy_id="r-boot",
        revoked_at=datetime(
            2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc
        ),  # strictly later
    )
    _run(source.put(r_advance))

    metrics = _run(
        bootstrap_capability_policy_target_from_source(
            source=source, target=target
        )
    )

    assert metrics.bootstrap_revocation_breaches == 1
    assert metrics.bootstrap_applied == 0
    # Target still byte-equal to the original revoked record.
    assert _record_to_envelope(
        _run(target.get(r_revoked.key))
    ) == _record_to_envelope(r_revoked)


def test_aux_revocation_reason_refresh_replicates_cleanly():
    """Aux: equal-instant rewrite with a refreshed
    ``revocation_reason`` is NOT a breach.
    """
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    revoked_at = datetime(
        2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc
    )
    r_target = _make_record(
        policy_id="r-refresh",
        revoked_at=revoked_at,
        revocation_reason="initial reason",
    )
    r_source = _make_record(
        policy_id="r-refresh",
        revoked_at=revoked_at,
        revocation_reason="refreshed reason after incident review",
    )
    _run(target.put(r_target))
    _run(source.put(r_source))

    metrics = _run(
        bootstrap_capability_policy_target_from_source(
            source=source, target=target
        )
    )

    assert metrics.bootstrap_revocation_breaches == 0
    assert metrics.bootstrap_applied == 1
    target_record = _run(target.get(r_target.key))
    assert (
        target_record.policy.revocation_reason
        == "refreshed reason after incident review"
    )


def test_aux_halt_on_revocation_breach_re_raises_under_source_wins():
    """Aux: halt_on_revocation_breach=True re-raises under
    SOURCE_WINS.
    """
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvCapabilityPolicyBackend(kv=source_kv)
    target = NatsKvCapabilityPolicyBackend(kv=target_kv)

    revoked_at = datetime(
        2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc
    )
    r_revoked = _make_record(
        policy_id="r-halt", revoked_at=revoked_at
    )
    _run(target.put(r_revoked))

    replicator = CapabilityPolicyReplicator(
        source=source,
        target=target,
        halt_on_revocation_breach=True,
    )

    bad_event = CapabilityPolicyWatchEvent(
        op=CapabilityPolicyWatchOp.PUT,
        key=r_revoked.key,
        record=_make_record(
            policy_id="r-halt", revoked_at=None
        ),
        revision=99,
    )

    with pytest.raises(CapabilityPolicyRevocationConflict):
        _run(replicator._apply_put(bad_event))
    assert replicator.metrics.revocation_breaches == 1
