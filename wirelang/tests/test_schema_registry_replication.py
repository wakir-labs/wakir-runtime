# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the Wirelang schema-registry replication layer.

Phase-1b Sprint-3 Tag-6 (S3-6). Tests the replication layer that
composes Tag-3 CAS-pin, Tag-4 watch-stream, and Tag-1 LWW into a
single one-way (source → target) replicator:

- :class:`SchemaReplicator` (run / bootstrap / event loop)
- :func:`bootstrap_target_from_source`
- :class:`ReplicationFilter` (curated-subset replication)
- :class:`ReplicationConflictPolicy` (SOURCE_WINS vs CAS_PIN)
- :class:`ReplicationMetrics` (per-run counters)

The replication layer is the OI-7-Phase-1c-replication slot landing
for the schema-registry backend; it is the last Phase-1c slot. The
Tag-1 LWW path (``put`` / ``get`` / ``snapshot``), the Tag-3 CAS-pin
path (``put_with_revision`` / ``get_with_revision``), and the Tag-4
watch-stream path (``watch`` / ``WatchEvent`` / ``LiveSchemaSnapshot``)
are unaffected; Tag-6 surfaces are purely additive.

Pattern source: there is no V-908 replication module to mirror; Tag-6
is the canonical Wakir-internal replication template. The mock KV
shape mirrors the Tag-4 watch-stream test pattern (Shape-2 watcher
with ``await updates()`` + sentinel-None close).

Test inventory (T-SR-REP-01..12):

- T-SR-REP-01: bootstrap copies every source entry onto an empty
  target in keys-sorted order.
- T-SR-REP-02: bootstrap is idempotent (a second bootstrap on a
  byte-equal target is a no-op via the ``bootstrap_skipped_idempotent``
  counter).
- T-SR-REP-03: a ``ReplicationFilter`` skips matching entries during
  bootstrap (counter ``bootstrap_skipped_by_filter`` advances; target
  does NOT gain the skipped entry).
- T-SR-REP-04: live PUT events on the source are mirrored to the
  target via the watch-stream tail (counter ``events_applied_put``).
- T-SR-REP-05: live DELETE events on the source remove the entry
  from the target (counter ``events_applied_delete``).
- T-SR-REP-06: ``ReplicationConflictPolicy.CAS_PIN`` writes through
  ``put_with_revision`` against the target's observed revision; a
  concurrent target-side mutation surfaces as a CAS conflict (counter
  ``cas_conflicts``) and the replicator continues by default.
- T-SR-REP-07: ``halt_on_conflict=True`` re-raises on the first
  CAS conflict; metrics counter is incremented before re-raise.
- T-SR-REP-08: a poisoned envelope on the source watch-stream
  raises :class:`SchemaRegistryEnvelopeError` from ``run`` (default
  halt policy); counter ``envelope_errors`` is 1.
- T-SR-REP-09: a filter that skips a live event (PUT) does NOT
  apply it to the target; counter ``events_skipped_by_filter``
  advances.
- T-SR-REP-10: ``SchemaReplicator`` constructor rejects
  source==target with ``ValueError`` (no self-replication).
- T-SR-REP-11: a non-PUT WatchEvent that arrives with a missing
  ``entry`` is rejected as envelope poison (defence-in-depth at
  the replicator boundary, not just the decoder).
- T-SR-REP-12: ``run(bootstrap=False)`` skips the bootstrap pass;
  bootstrap counters stay 0 while live-event counters advance.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from wirelang.schemas.registry_nats_kv_backend import (
    BUCKET_NAME,
    NatsKvSchemaRegistry,
    SchemaRegistryConflictError,
    SchemaRegistryEntry,
    SchemaRegistryEnvelopeError,
    WatchEvent,
    WatchOp,
    _entry_to_envelope,
    schema_body_sha256,
)
from wirelang.schemas.replication import (
    ReplicationConflictPolicy,
    ReplicationDecision,
    ReplicationFilter,
    ReplicationMetrics,
    SchemaReplicator,
    bootstrap_target_from_source,
)


# ---------------------------------------------------------------------------
# Mock KV with watch + CAS surfaces (mirror of Tag-4 watch test pattern)
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

    Surfaces ``await kv.get/put/update/delete/keys/watchall``. Drives
    the Shape-2 watcher when one is open: ``put`` and ``delete`` push
    corresponding events.
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
        # CAS-pin: live revision must match ``last``.
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


_REGISTERED_AT = datetime(2026, 5, 7, 13, 0, 0, tzinfo=timezone.utc)
_REGISTERED_BY = "wirelang-eng"


def _make_schema_body(schema_id: str, *, marker: str = "rep") -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "title": f"replication test schema ({marker})",
        "type": "object",
        "additionalProperties": False,
        "properties": {"x": {"type": "string"}},
    }


def _make_entry(
    *,
    layer: str = "wire",
    name: str = "layer-1-wire",
    version: str = "0.1.0",
    schema_id: Optional[str] = None,
    marker: str = "rep",
    registered_at: datetime = _REGISTERED_AT,
    registered_by: str = _REGISTERED_BY,
    supersedes: Optional[str] = None,
) -> SchemaRegistryEntry:
    if schema_id is None:
        schema_id = f"https://wakir.dev/wirelang/schema/{name}/{version}"
    body = _make_schema_body(schema_id, marker=marker)
    digest = schema_body_sha256(body)
    return SchemaRegistryEntry(
        layer=layer,
        name=name,
        version=version,
        schema_id=schema_id,
        schema_body=body,
        schema_body_sha256=digest,
        registered_at=registered_at,
        registered_by=registered_by,
        supersedes=supersedes,
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# T-SR-REP-01..03: bootstrap pass
# ---------------------------------------------------------------------------


def test_t_sr_rep_01_bootstrap_copies_all_source_entries():
    """T-SR-REP-01: bootstrap copies every source entry onto an empty
    target.
    """
    source = NatsKvSchemaRegistry(kv=_MockKv())
    target = NatsKvSchemaRegistry(kv=_MockKv())
    e1 = _make_entry(name="layer-1-wire", version="0.1.0", marker="e1")
    e2 = _make_entry(name="layer-2-semantic", version="0.1.0", marker="e2")
    e3 = _make_entry(name="layer-0-transport", version="0.1.0", marker="e3")

    async def _go():
        await source.put(e1)
        await source.put(e2)
        await source.put(e3)
        metrics = await bootstrap_target_from_source(
            source=source, target=target
        )
        target_snap = await target.snapshot()
        return metrics, target_snap

    metrics, target_snap = _run(_go())
    assert metrics.bootstrap_applied == 3
    assert metrics.bootstrap_skipped_by_filter == 0
    assert metrics.bootstrap_skipped_idempotent == 0
    # All three entries landed; keysets byte-equal to source.
    assert target_snap.lookup(e1.key) == e1
    assert target_snap.lookup(e2.key) == e2
    assert target_snap.lookup(e3.key) == e3


def test_t_sr_rep_02_bootstrap_is_idempotent_on_byte_equal_target():
    """T-SR-REP-02: a second bootstrap pass on a byte-equal target
    is a no-op (``bootstrap_skipped_idempotent`` counter).
    """
    source = NatsKvSchemaRegistry(kv=_MockKv())
    target = NatsKvSchemaRegistry(kv=_MockKv())
    e1 = _make_entry(name="layer-1-wire", version="0.1.0", marker="e1")
    e2 = _make_entry(name="layer-2-semantic", version="0.1.0", marker="e2")

    async def _go():
        await source.put(e1)
        await source.put(e2)
        first = await bootstrap_target_from_source(
            source=source, target=target
        )
        second = await bootstrap_target_from_source(
            source=source, target=target
        )
        return first, second

    first, second = _run(_go())
    assert first.bootstrap_applied == 2
    assert first.bootstrap_skipped_idempotent == 0
    # Second pass: target is byte-equal everywhere, so nothing applied.
    # Each bootstrap_target_from_source(metrics=None) call gets a fresh
    # ReplicationMetrics; counters do NOT carry forward across calls.
    assert second.bootstrap_applied == 0
    assert second.bootstrap_skipped_idempotent == 2


def test_t_sr_rep_03_filter_skips_matching_entries_during_bootstrap():
    """T-SR-REP-03: a ``ReplicationFilter`` skips matching entries
    during the bootstrap pass.
    """
    source = NatsKvSchemaRegistry(kv=_MockKv())
    target = NatsKvSchemaRegistry(kv=_MockKv())
    e_wire = _make_entry(
        layer="wire", name="layer-1-wire", version="0.1.0", marker="wire"
    )
    e_fed = _make_entry(
        layer="federation",
        name="federation-trust-document",
        version="0.1.0",
        marker="fed",
    )

    def only_wire(event: WatchEvent) -> ReplicationDecision:
        if event.entry is None:
            return ReplicationDecision.SKIP
        if event.entry.layer == "wire":
            return ReplicationDecision.APPLY
        return ReplicationDecision.SKIP

    async def _go():
        await source.put(e_wire)
        await source.put(e_fed)
        metrics = await bootstrap_target_from_source(
            source=source, target=target, filter_fn=only_wire
        )
        wire_landed = await target.get(e_wire.key)
        fed_landed = await target.get(e_fed.key)
        return metrics, wire_landed, fed_landed

    metrics, wire_landed, fed_landed = _run(_go())
    assert metrics.bootstrap_applied == 1
    assert metrics.bootstrap_skipped_by_filter == 1
    assert wire_landed == e_wire
    assert fed_landed is None


# ---------------------------------------------------------------------------
# T-SR-REP-04..05: live tail via watch-stream
# ---------------------------------------------------------------------------


def test_t_sr_rep_04_live_put_events_mirrored_to_target():
    """T-SR-REP-04: live PUT events on the source land on the target
    via the watch-stream tail.
    """
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvSchemaRegistry(kv=source_kv)
    target = NatsKvSchemaRegistry(kv=target_kv)
    e1 = _make_entry(name="layer-1-wire", version="0.1.0", marker="e1")
    e2 = _make_entry(name="layer-2-semantic", version="0.1.0", marker="e2")

    replicator = SchemaReplicator(source=source, target=target)

    async def _go():
        # Pre-load source so bootstrap captures e1.
        await source.put(e1)
        # Open watcher for the source; emit a live PUT for e2 after
        # the watcher is listening so it lands on the tail.
        watcher = await source_kv.watchall()
        run_task = asyncio.create_task(replicator.run())
        # Yield once so run() opens its own watcher (uses the same
        # singleton _MockKv._watcher under the hood) and starts.
        await asyncio.sleep(0)
        # Emit live PUT for e2.
        await source.put(e2)
        # Close the stream so run() returns.
        watcher._close()
        await run_task
        return replicator.metrics, await target.snapshot()

    metrics, target_snap = _run(_go())
    assert metrics.bootstrap_applied == 1  # e1 from bootstrap
    assert metrics.events_applied_put == 1  # e2 from tail
    assert target_snap.lookup(e1.key) == e1
    assert target_snap.lookup(e2.key) == e2


def test_t_sr_rep_05_live_delete_event_removes_from_target():
    """T-SR-REP-05: live DELETE event removes the entry from target."""
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvSchemaRegistry(kv=source_kv)
    target = NatsKvSchemaRegistry(kv=target_kv)
    e1 = _make_entry(name="layer-1-wire", version="0.1.0", marker="e1")

    replicator = SchemaReplicator(source=source, target=target)

    async def _go():
        await source.put(e1)
        watcher = await source_kv.watchall()
        run_task = asyncio.create_task(replicator.run())
        await asyncio.sleep(0)
        await source.delete(e1.key)
        watcher._close()
        await run_task
        return replicator.metrics, await target.get(e1.key)

    metrics, target_entry = _run(_go())
    assert metrics.bootstrap_applied == 1
    assert metrics.events_applied_delete == 1
    assert target_entry is None


# ---------------------------------------------------------------------------
# T-SR-REP-06..07: CAS_PIN policy + halt_on_conflict
# ---------------------------------------------------------------------------


def test_t_sr_rep_06_cas_pin_observes_concurrent_target_mutation():
    """T-SR-REP-06: ``CAS_PIN`` policy surfaces a target-side
    concurrent mutation that lands between the replicator's read
    and CAS-write as a counter increment on ``cas_conflicts``; the
    replicator continues with subsequent events by default.

    The race window (read-revision → write-with-pinned-revision) is
    simulated here by wrapping the target backend so that an
    out-of-band mutation lands between the read and the write.
    """
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvSchemaRegistry(kv=source_kv)
    target = NatsKvSchemaRegistry(kv=target_kv)
    e1 = _make_entry(name="layer-1-wire", version="0.1.0", marker="src")
    e1_target_alt = _make_entry(
        name="layer-1-wire", version="0.1.0", marker="target-alt"
    )
    e2 = _make_entry(name="layer-2-semantic", version="0.1.0", marker="e2")

    # Wrap target.get_with_revision to inject an out-of-band mutation
    # between the read and the write. The first time the replicator
    # reads e1, we mutate the target out-of-band so the subsequent
    # put_with_revision call carries a stale ``last`` and the mock
    # raises KeyWrongLastSequenceError.
    original_get_with_revision = target.get_with_revision
    race_state = {"injected": False}

    async def racing_get_with_revision(key):
        result = await original_get_with_revision(key)
        if not race_state["injected"] and key == e1.key:
            race_state["injected"] = True
            # Out-of-band mutation: bump the target's live revision
            # for this key so the replicator's pinned-revision write
            # is now stale.
            await target.put(e1_target_alt)
        return result

    target.get_with_revision = racing_get_with_revision  # type: ignore[method-assign]

    replicator = SchemaReplicator(
        source=source,
        target=target,
        conflict_policy=ReplicationConflictPolicy.CAS_PIN,
    )

    async def _go():
        # Bootstrap the source with one entry; replicate to target.
        await source.put(e1)
        await replicator.bootstrap()
        # The target now holds e1 (LWW path because it was absent).
        # Replicate further events from source; the wrapper triggers
        # an out-of-band mutation between read and write.
        watcher = await source_kv.watchall()
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        await asyncio.sleep(0)
        # Source emits an updated e1: replicator reads target rev,
        # the wrapper mutates the target, the put_with_revision call
        # carries a stale ``last`` and fails.
        e1_source_v2 = _make_entry(
            name="layer-1-wire", version="0.1.0", marker="src-v2"
        )
        await source.put(e1_source_v2)
        # Source emits e2: target is absent for that key, so the
        # CAS_PIN path falls through to LWW put (no conflict).
        await source.put(e2)
        watcher._close()
        await run_task
        return replicator.metrics, await target.snapshot()

    metrics, target_snap = _run(_go())
    # 1 conflict on the e1 update; 1 successful PUT on e2.
    assert metrics.cas_conflicts == 1
    # e2 landed; e1's out-of-band mutation was preserved (replicator
    # observed conflict, did NOT overwrite).
    assert target_snap.lookup(e2.key) == e2
    assert target_snap.lookup(e1.key) == e1_target_alt


def test_t_sr_rep_07_halt_on_conflict_reraises_first_conflict():
    """T-SR-REP-07: ``halt_on_conflict=True`` re-raises on the first
    CAS conflict; metrics counter is incremented before re-raise.

    Same race-window simulation as T-SR-REP-06, but with
    ``halt_on_conflict=True`` so that the run loop terminates with
    a re-raised :class:`SchemaRegistryConflictError`.
    """
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvSchemaRegistry(kv=source_kv)
    target = NatsKvSchemaRegistry(kv=target_kv)
    e1 = _make_entry(name="layer-1-wire", version="0.1.0", marker="src")
    e1_target_alt = _make_entry(
        name="layer-1-wire", version="0.1.0", marker="target-alt"
    )

    original_get_with_revision = target.get_with_revision
    race_state = {"injected": False}

    async def racing_get_with_revision(key):
        result = await original_get_with_revision(key)
        if not race_state["injected"] and key == e1.key:
            race_state["injected"] = True
            await target.put(e1_target_alt)
        return result

    target.get_with_revision = racing_get_with_revision  # type: ignore[method-assign]

    replicator = SchemaReplicator(
        source=source,
        target=target,
        conflict_policy=ReplicationConflictPolicy.CAS_PIN,
        halt_on_conflict=True,
    )

    async def _go():
        await source.put(e1)
        await replicator.bootstrap()
        watcher = await source_kv.watchall()
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        await asyncio.sleep(0)
        e1_source_v2 = _make_entry(
            name="layer-1-wire", version="0.1.0", marker="src-v2"
        )
        await source.put(e1_source_v2)
        watcher._close()
        with pytest.raises(SchemaRegistryConflictError):
            await run_task
        return replicator.metrics

    metrics = _run(_go())
    assert metrics.cas_conflicts == 1


# ---------------------------------------------------------------------------
# T-SR-REP-08..09: envelope poison + filter on live tail
# ---------------------------------------------------------------------------


def test_t_sr_rep_08_poisoned_envelope_halts_run_with_envelope_error():
    """T-SR-REP-08: a poisoned envelope on the source watch-stream
    halts ``run`` with :class:`SchemaRegistryEnvelopeError`;
    ``envelope_errors`` counter is 1.
    """
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvSchemaRegistry(kv=source_kv)
    target = NatsKvSchemaRegistry(kv=target_kv)

    replicator = SchemaReplicator(source=source, target=target)

    async def _go():
        # Open the watcher; push a poisoned (non-JSON) PUT update.
        watcher = await source_kv.watchall()
        run_task = asyncio.create_task(replicator.run())
        await asyncio.sleep(0)
        # Push a manually-crafted update with non-JSON value bytes.
        watcher._push(
            _MockWatchUpdate(
                operation="PUT",
                key="schemas/wire/layer-1-wire/0.1.0",
                value=b"not-json-bytes",
                revision=99,
            )
        )
        # No need to close; the iterator will raise on the poisoned
        # event and the run loop terminates.
        with pytest.raises(SchemaRegistryEnvelopeError):
            await run_task
        return replicator.metrics

    metrics = _run(_go())
    assert metrics.envelope_errors == 1


def test_t_sr_rep_09_filter_skips_live_event():
    """T-SR-REP-09: a filter that returns ``SKIP`` on a live event
    increments ``events_skipped_by_filter`` and does NOT apply it to
    the target.
    """
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvSchemaRegistry(kv=source_kv)
    target = NatsKvSchemaRegistry(kv=target_kv)
    e_skip = _make_entry(
        layer="federation",
        name="federation-trust-document",
        version="0.1.0",
        marker="skip-me",
    )
    e_apply = _make_entry(
        layer="wire", name="layer-1-wire", version="0.1.0", marker="apply"
    )

    def only_wire(event: WatchEvent) -> ReplicationDecision:
        if event.entry is None:
            return ReplicationDecision.APPLY
        if event.entry.layer == "wire":
            return ReplicationDecision.APPLY
        return ReplicationDecision.SKIP

    replicator = SchemaReplicator(
        source=source, target=target, filter_fn=only_wire
    )

    async def _go():
        watcher = await source_kv.watchall()
        run_task = asyncio.create_task(replicator.run())
        await asyncio.sleep(0)
        await source.put(e_skip)
        await source.put(e_apply)
        watcher._close()
        await run_task
        return replicator.metrics, await target.snapshot()

    metrics, target_snap = _run(_go())
    assert metrics.events_skipped_by_filter == 1
    assert metrics.events_applied_put == 1
    assert target_snap.lookup(e_apply.key) == e_apply
    assert target_snap.lookup(e_skip.key) is None


# ---------------------------------------------------------------------------
# T-SR-REP-10..12: defence-in-depth + bootstrap=False
# ---------------------------------------------------------------------------


def test_t_sr_rep_10_constructor_rejects_self_replication():
    """T-SR-REP-10: source==target is rejected at construction."""
    backend = NatsKvSchemaRegistry(kv=_MockKv())
    with pytest.raises(ValueError):
        SchemaReplicator(source=backend, target=backend)


def test_t_sr_rep_11_put_event_with_missing_entry_is_envelope_poison():
    """T-SR-REP-11: a PUT event arriving with ``entry=None`` is
    rejected as envelope poison at the replicator's apply-boundary.

    This is defence-in-depth: the decoder already rejects PUT events
    without a value, but if a malformed handcrafted event slips
    through (e.g. via a custom watcher subclass), the apply path
    surfaces the same typed error.
    """
    source = NatsKvSchemaRegistry(kv=_MockKv())
    target = NatsKvSchemaRegistry(kv=_MockKv())
    replicator = SchemaReplicator(source=source, target=target)

    poisoned = WatchEvent(
        op=WatchOp.PUT,
        key="schemas/wire/layer-1-wire/0.1.0",
        entry=None,
        revision=42,
    )

    async def _go():
        with pytest.raises(SchemaRegistryEnvelopeError):
            await replicator._consume_event(poisoned)

    _run(_go())


def test_t_sr_rep_12_run_with_bootstrap_false_skips_initial_pass():
    """T-SR-REP-12: ``run(bootstrap=False)`` skips the bootstrap pass;
    bootstrap counters stay 0 while live counters advance.
    """
    source_kv = _MockKv()
    target_kv = _MockKv()
    source = NatsKvSchemaRegistry(kv=source_kv)
    target = NatsKvSchemaRegistry(kv=target_kv)
    pre_existing = _make_entry(
        name="layer-1-wire", version="0.1.0", marker="pre"
    )
    new_entry = _make_entry(
        name="layer-2-semantic", version="0.1.0", marker="new"
    )

    replicator = SchemaReplicator(source=source, target=target)

    async def _go():
        # Pre-load source; would normally bootstrap but caller skips.
        await source.put(pre_existing)
        watcher = await source_kv.watchall()
        run_task = asyncio.create_task(
            replicator.run(bootstrap=False)
        )
        await asyncio.sleep(0)
        await source.put(new_entry)
        watcher._close()
        await run_task
        return replicator.metrics, await target.snapshot()

    metrics, target_snap = _run(_go())
    # Bootstrap was skipped; pre_existing is NOT on target.
    assert metrics.bootstrap_applied == 0
    assert metrics.bootstrap_skipped_by_filter == 0
    assert metrics.bootstrap_skipped_idempotent == 0
    assert target_snap.lookup(pre_existing.key) is None
    # But the live event landed.
    assert metrics.events_applied_put == 1
    assert target_snap.lookup(new_entry.key) == new_entry
