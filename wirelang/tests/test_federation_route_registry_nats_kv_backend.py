# SPDX-License-Identifier: BUSL-1.1
"""Hermetic tests for the V-908 NATS-KV-backed RouteRegistry backend.

Phase-1b Sprint-2 Tag-4 (S2-3). Tests the production-target backend
:mod:`wirelang.federation.route_registry_nats_kv_backend` against
an in-memory mock that mirrors Kai's Tag-1 mock JetStream surface
(``tests/orchestrator/test_init_nats_buckets.py``).

The mock is intentionally a thin shim over a dict so the tests
exercise the backend's envelope codec and snapshot logic without
depending on nats-py at runtime.

Test inventory (T-NKV-01..10):

- T-NKV-01: ``put`` round-trips an entry through ``get``.
- T-NKV-02: ``get`` on an unknown key returns ``None``.
- T-NKV-03: ``put`` is last-write-wins (second put overwrites).
- T-NKV-04: ``delete`` removes an entry; subsequent ``get`` is ``None``.
- T-NKV-05: ``snapshot`` materialises an
  :class:`InMemoryRouteRegistry` consumable by the N2 evaluator.
- T-NKV-06: a poisoned (non-JSON) value raises
  :class:`RouteRegistryEnvelopeError` from ``get`` and aborts the
  snapshot.
- T-NKV-07: a value with the wrong ``schema`` field is rejected.
- T-NKV-08: ``active_until=None`` round-trips as an open-ended
  window.
- T-NKV-09: snapshot result feeds the N2 evaluator and produces
  the same accept verdict as :class:`InMemoryRouteRegistry`.
- T-NKV-10: bucket-config constants match the documented inventory
  (drift-protection at the test layer; the operator-side drift
  check lives in ``scripts/init-nats-buckets.py``).

Bonus sanity:

- T-NKV-aux-empty-key: empty string and non-string keys behave
  predictably.
- T-NKV-aux-naive-datetime: naive datetimes are rejected at encode.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from wirelang.federation.n2_evaluator import (
    FederationContext,
    FederationEvaluator,
    InMemoryRouteRegistry,
    RouteRegistryEntry,
)
from wirelang.federation.route_registry_nats_kv_backend import (
    BUCKET_CONFIG,
    BUCKET_NAME,
    LiveSnapshot,
    NatsKvRouteRegistry,
    RouteRegistryBackendError,
    RouteRegistryEnvelopeError,
    VALUE_SCHEMA,
    WatchEvent,
    WatchOp,
    _entry_to_envelope,
    _envelope_to_entry,
    open_watch_stream,
)
from wirelang.identity.federation_resolver import FederatedResolveResult


# ---------------------------------------------------------------------------
# Mock KV (mirrors Kai-Tag-1 _MockKv shape from
# tests/orchestrator/test_init_nats_buckets.py)
# ---------------------------------------------------------------------------


class _MockBucketNotFoundError(Exception):
    """Mirrors nats-py's ``KeyNotFoundError`` class-name pattern so
    the backend's exception filter (`"NotFound" in cls_name`) treats
    it as a missing key.
    """


@dataclass
class _MockKvEntry:
    """Shape-equivalent of nats-py's ``KeyValue.Entry`` for the
    fields the backend reads.
    """
    value: bytes
    revision: int = 0


@dataclass
class _MockWatchUpdate:
    """Shape-equivalent of nats-py's ``KeyValue.Entry`` exposed
    through the watcher: carries an ``operation`` enum-ish field plus
    ``key`` / ``value`` / ``revision``.
    """

    operation: str  # "PUT" / "DELETE" / "PURGE"
    key: str
    value: bytes = b""
    revision: int = 0


class _MockWatcher:
    """Manually-fed mock watcher.

    Exposes the nats-py ``KeyWatcher`` shape we wrap: ``await
    updates()`` yields the next update or ``None`` for end-of-stream.
    Tests push updates onto an internal queue with :meth:`_push` and
    close the stream with :meth:`_close`.
    """

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

    The async surface mirrors what
    :class:`NatsKvRouteRegistry` calls into:
    ``await kv.get(key)``, ``await kv.put(key, value)``,
    ``await kv.delete(key)``, ``await kv.keys()``,
    ``await kv.watchall()``.
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
        self.store[key] = _MockKvEntry(value=bytes(value), revision=self.revision)
        # Surface the put on the watcher if one is open.
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


_FTD_ID = "did:web:wakir.dev:ftd:v1"
_AIP_ID = "aip:web:wakir.dev/treasury-issuer"


def _make_entry(
    route_id: str = "wakir->partner-A->treasury",
    *,
    source_ftd_id: str = _FTD_ID,
    active_from: datetime = datetime(2026, 5, 1, tzinfo=timezone.utc),
    active_until: Optional[datetime] = datetime(2026, 6, 1, tzinfo=timezone.utc),
    wat_anchor_manifest_id: Optional[str] = "wat-manifest-2026-05-07-h12",
) -> RouteRegistryEntry:
    return RouteRegistryEntry(
        route_id=route_id,
        source_ftd_id=source_ftd_id,
        active_from=active_from,
        active_until=active_until,
        wat_anchor_manifest_id=wat_anchor_manifest_id,
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if (
        # event-loop policy: pytest-asyncio is not a project dep,
        # so we use a fresh-loop per call to avoid cross-test
        # contamination.
        False
    ) else asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# T-NKV-01..04 single-key round-trip semantics
# ---------------------------------------------------------------------------


def test_t_nkv_01_put_get_round_trip():
    """T-NKV-01: ``put`` then ``get`` returns the same entry."""
    backend = NatsKvRouteRegistry(kv=_MockKv())
    entry = _make_entry()

    async def _go():
        rev = await backend.put(entry)
        got = await backend.get(entry.route_id)
        return rev, got

    rev, got = _run(_go())
    assert rev >= 1
    assert got == entry


def test_t_nkv_02_get_unknown_key_returns_none():
    """T-NKV-02: ``get`` for an absent key returns ``None``."""
    backend = NatsKvRouteRegistry(kv=_MockKv())

    async def _go():
        return await backend.get("does-not-exist")

    assert _run(_go()) is None


def test_t_nkv_03_put_last_write_wins():
    """T-NKV-03: a second ``put`` overwrites the first."""
    backend = NatsKvRouteRegistry(kv=_MockKv())
    e1 = _make_entry(active_until=datetime(2026, 6, 1, tzinfo=timezone.utc))
    e2 = _make_entry(active_until=datetime(2027, 1, 1, tzinfo=timezone.utc))

    async def _go():
        await backend.put(e1)
        await backend.put(e2)
        return await backend.get(e1.route_id)

    got = _run(_go())
    assert got == e2
    assert got != e1


def test_t_nkv_04_delete_removes_entry():
    """T-NKV-04: ``delete`` makes a previously-present key absent."""
    backend = NatsKvRouteRegistry(kv=_MockKv())
    entry = _make_entry()

    async def _go():
        await backend.put(entry)
        await backend.delete(entry.route_id)
        return await backend.get(entry.route_id)

    assert _run(_go()) is None


# ---------------------------------------------------------------------------
# T-NKV-05..09 snapshot + evaluator integration
# ---------------------------------------------------------------------------


def test_t_nkv_05_snapshot_returns_in_memory_registry():
    """T-NKV-05: ``snapshot`` materialises an in-memory registry."""
    backend = NatsKvRouteRegistry(kv=_MockKv())
    e1 = _make_entry(route_id="wakir->partner-A->treasury")
    e2 = _make_entry(route_id="wakir->partner-B->payments")

    async def _go():
        await backend.put(e1)
        await backend.put(e2)
        return await backend.snapshot()

    snap = _run(_go())
    assert isinstance(snap, InMemoryRouteRegistry)
    assert snap.lookup("wakir->partner-A->treasury") == e1
    assert snap.lookup("wakir->partner-B->payments") == e2
    assert snap.lookup("not-registered") is None


def test_t_nkv_06_poisoned_envelope_raises():
    """T-NKV-06: a non-JSON byte payload raises a clean
    :class:`RouteRegistryEnvelopeError`. The snapshot aborts.
    """
    kv = _MockKv()
    # Hand-poison the bucket with a non-JSON byte sequence.
    kv.store["poisoned-route"] = _MockKvEntry(
        value=b"\xff\xfenot-json", revision=1
    )
    backend = NatsKvRouteRegistry(kv=kv)

    async def _go_get():
        return await backend.get("poisoned-route")

    async def _go_snapshot():
        return await backend.snapshot()

    with pytest.raises(RouteRegistryEnvelopeError):
        _run(_go_get())
    with pytest.raises(RouteRegistryEnvelopeError):
        _run(_go_snapshot())


def test_t_nkv_07_wrong_schema_rejected():
    """T-NKV-07: a JSON value with a different ``schema`` field is
    rejected. This protects against accidental mixing of bucket
    contents (e.g., a copy-paste from another bucket).
    """
    kv = _MockKv()
    bogus = json.dumps(
        {"schema": "wakir.unrelated.thing/1", "route_id": "x"}
    ).encode("utf-8")
    kv.store["x"] = _MockKvEntry(value=bogus, revision=1)
    backend = NatsKvRouteRegistry(kv=kv)

    async def _go():
        return await backend.get("x")

    with pytest.raises(RouteRegistryEnvelopeError):
        _run(_go())


def test_t_nkv_08_open_ended_window_round_trip():
    """T-NKV-08: ``active_until=None`` round-trips as an open-ended
    window through the JSON envelope.
    """
    backend = NatsKvRouteRegistry(kv=_MockKv())
    entry = _make_entry(active_until=None)

    async def _go():
        await backend.put(entry)
        return await backend.get(entry.route_id)

    got = _run(_go())
    assert got == entry
    assert got.active_until is None


def test_t_nkv_09_snapshot_feeds_n2_evaluator():
    """T-NKV-09: a snapshot of the KV-backed registry feeds the N2
    evaluator and produces the same accept verdict as the in-memory
    reference. This ties the production-target backend to the
    Tag-3 evaluator's determinism contract.
    """
    backend = NatsKvRouteRegistry(kv=_MockKv())
    entry = _make_entry()

    async def _go():
        await backend.put(entry)
        return await backend.snapshot()

    snap = _run(_go())

    resolve = FederatedResolveResult(
        aip_id=_AIP_ID,
        ftd_id=_FTD_ID,
        aip_body={"id": _AIP_ID, "stub": True},
        aip_jcs_sha256="ef" * 32,
        ftd_fingerprint_sha256="12" * 32,
        biscuit_root_pubkey_hex="ab" * 32,
        matched_issuer_kid="kid-1",
        verified_at=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    ctx = FederationContext.from_resolve(resolve, snap)
    ev = FederationEvaluator(ctx)
    assert ev.evaluate_peer_org(_FTD_ID) is True
    assert ev.evaluate_federation_route(entry.route_id) is True


# ---------------------------------------------------------------------------
# T-NKV-10 bucket-config constants
# ---------------------------------------------------------------------------


def test_t_nkv_10_bucket_config_matches_documented_inventory():
    """T-NKV-10: the module-level ``BUCKET_NAME`` and ``BUCKET_CONFIG``
    constants match the documented Phase-1b inventory contract.

    This protects against accidental edits to the constants that
    would silently re-target the backend at a different bucket or
    request a different drift-policy. The orchestrator-side
    drift-check (``scripts/init-nats-buckets.py``) runs against a
    live cluster; this test runs against the source-of-truth
    constants in the wirelang module.
    """
    assert BUCKET_NAME == "wakir-federation-routes"
    assert BUCKET_CONFIG["name"] == BUCKET_NAME
    assert BUCKET_CONFIG["history"] == 5
    assert BUCKET_CONFIG["ttl_seconds"] == 0
    assert BUCKET_CONFIG["max_value_size"] == 4096
    assert BUCKET_CONFIG["storage"] == "file"
    assert BUCKET_CONFIG["replicas"] == 1
    assert VALUE_SCHEMA == "wakir.federation.route-registry-entry/1"


# ---------------------------------------------------------------------------
# Bonus sanity probes
# ---------------------------------------------------------------------------


def test_t_nkv_aux_empty_key():
    """T-NKV-aux-empty-key: empty / non-string keys behave predictably.

    ``get`` returns ``None`` for invalid input; ``delete`` raises
    ``ValueError`` because deleting an unidentified key is an
    operator-bug shape that should NOT be silently swallowed.
    """
    backend = NatsKvRouteRegistry(kv=_MockKv())

    async def _go_get_empty():
        return await backend.get("")

    async def _go_get_nonstr():
        return await backend.get(None)  # type: ignore[arg-type]

    assert _run(_go_get_empty()) is None
    assert _run(_go_get_nonstr()) is None

    async def _go_del_empty():
        return await backend.delete("")

    with pytest.raises(ValueError):
        _run(_go_del_empty())


def test_t_nkv_aux_naive_datetime_rejected_at_encode():
    """T-NKV-aux-naive-datetime: a naive (tz-less) datetime is
    rejected at the envelope-encode boundary so a poisoned envelope
    cannot reach the bucket.
    """
    naive = datetime(2026, 5, 1)  # no tzinfo
    entry = RouteRegistryEntry(
        route_id="bad",
        source_ftd_id=_FTD_ID,
        active_from=naive,
        active_until=None,
    )
    with pytest.raises(ValueError):
        _entry_to_envelope(entry)


def test_t_nkv_aux_envelope_round_trip_byte_stable():
    """Round-tripping the same entry through encode->decode->encode
    yields identical bytes (canonical envelope form).
    """
    entry = _make_entry()
    once = _entry_to_envelope(entry)
    twice = _entry_to_envelope(_envelope_to_entry(once))
    assert once == twice


# ---------------------------------------------------------------------------
# Phase-1b Sprint-2 Tag-6 (S2-5) Watch-Stream-Snapshot Layer
# ---------------------------------------------------------------------------
#
# Test inventory T-NKV-WS-01..10:
#
# - T-NKV-WS-01: ``watch()`` opens a stream and yields decoded
#   :class:`WatchEvent` PUT events.
# - T-NKV-WS-02: a DELETE on the bucket surfaces a DELETE
#   :class:`WatchEvent`; the ``entry`` is ``None``.
# - T-NKV-WS-03: ``LiveSnapshot.from_backend`` bootstraps from a
#   full snapshot; ``apply()`` of subsequent PUT events updates the
#   live state.
# - T-NKV-WS-04: ``LiveSnapshot.apply`` of DELETE removes the route
#   from the live state.
# - T-NKV-WS-05: ``LiveSnapshot.as_registry`` returns a frozen copy;
#   subsequent applies do NOT mutate the returned registry
#   (determinism contract for evaluator passes).
# - T-NKV-WS-06: a poisoned watch update (non-JSON value on PUT)
#   raises :class:`RouteRegistryEnvelopeError` and terminates the
#   iterator.
# - T-NKV-WS-07: an unknown ``operation`` kind raises
#   :class:`RouteRegistryEnvelopeError`.
# - T-NKV-WS-08: ``LiveSnapshot.last_revision`` tracks the highest
#   revision seen and is monotonic.
# - T-NKV-WS-09: a snapshot fed by watch-stream events feeds the N2
#   evaluator and produces accept verdicts (cross-reference T-NKV-09
#   for the full-snapshot path).
# - T-NKV-WS-10: ``open_watch_stream`` rejects a non-backend argument
#   with ``TypeError``.
# - T-NKV-WS-aux-async-iter: the watch handle is itself async-iter
#   compatible (Shape-1 mock path).


class _ShapeOneMockWatcher:
    """Async-iter mock that mirrors the alternative nats-py watcher
    shape (native ``__aiter__`` / ``__anext__``).
    """

    def __init__(self, items):
        self._items = list(items)
        self._stopped = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._stopped or not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)

    async def stop(self):
        self._stopped = True


def test_t_nkv_ws_01_watch_yields_put_events():
    """T-NKV-WS-01: ``watch()`` yields PUT events for each upsert."""
    kv = _MockKv()
    backend = NatsKvRouteRegistry(kv=kv)
    e1 = _make_entry(route_id="wakir->p-A->t1")
    e2 = _make_entry(route_id="wakir->p-A->t2")

    async def _go():
        stream = await backend.watch()
        # Issue puts AFTER the watcher is open so the events land.
        await backend.put(e1)
        await backend.put(e2)
        kv._watcher._close()  # type: ignore[union-attr]
        events = []
        async for ev in stream:
            events.append(ev)
        await stream.__aexit__(None, None, None)
        return events

    events = _run(_go())
    assert len(events) == 2
    assert events[0].op is WatchOp.PUT
    assert events[0].route_id == "wakir->p-A->t1"
    assert events[0].entry == e1
    assert events[0].revision == 1
    assert events[1].op is WatchOp.PUT
    assert events[1].entry == e2


def test_t_nkv_ws_02_watch_yields_delete_event():
    """T-NKV-WS-02: a DELETE surfaces a DELETE WatchEvent with
    ``entry=None``.
    """
    kv = _MockKv()
    backend = NatsKvRouteRegistry(kv=kv)
    entry = _make_entry()

    async def _go():
        await backend.put(entry)  # before watch -> not surfaced
        stream = await backend.watch()
        await backend.delete(entry.route_id)
        kv._watcher._close()  # type: ignore[union-attr]
        events = []
        async for ev in stream:
            events.append(ev)
        return events

    events = _run(_go())
    assert len(events) == 1
    assert events[0].op is WatchOp.DELETE
    assert events[0].route_id == entry.route_id
    assert events[0].entry is None
    assert events[0].revision >= 1


def test_t_nkv_ws_03_live_snapshot_bootstraps_and_applies_put():
    """T-NKV-WS-03: ``LiveSnapshot.from_backend`` bootstraps and
    subsequent ``apply(PUT)`` updates the live state.
    """
    backend = NatsKvRouteRegistry(kv=_MockKv())
    e1 = _make_entry(route_id="r-1")
    e2 = _make_entry(route_id="r-2")

    async def _go():
        await backend.put(e1)
        live = await LiveSnapshot.from_backend(backend)
        # Initial bootstrap captures e1.
        before = live.as_registry()
        # Apply a PUT delta for e2 directly (independent of the
        # watcher; tests the apply contract in isolation).
        live.apply(
            WatchEvent(
                op=WatchOp.PUT,
                route_id=e2.route_id,
                entry=e2,
                revision=2,
            )
        )
        after = live.as_registry()
        return before, after

    before, after = _run(_go())
    assert before.lookup("r-1") == e1
    assert before.lookup("r-2") is None
    assert after.lookup("r-1") == e1
    assert after.lookup("r-2") == e2


def test_t_nkv_ws_04_live_snapshot_apply_delete_removes_route():
    """T-NKV-WS-04: ``apply(DELETE)`` removes the route from the
    live state.
    """
    backend = NatsKvRouteRegistry(kv=_MockKv())
    entry = _make_entry()

    async def _go():
        await backend.put(entry)
        live = await LiveSnapshot.from_backend(backend)
        assert live.as_registry().lookup(entry.route_id) == entry
        live.apply(
            WatchEvent(
                op=WatchOp.DELETE,
                route_id=entry.route_id,
                entry=None,
                revision=2,
            )
        )
        return live.as_registry()

    after = _run(_go())
    assert after.lookup(entry.route_id) is None


def test_t_nkv_ws_05_as_registry_returns_frozen_copy():
    """T-NKV-WS-05: a registry handed out by ``as_registry`` is not
    mutated by subsequent ``apply()`` calls. This is the determinism
    contract for evaluator passes.
    """
    backend = NatsKvRouteRegistry(kv=_MockKv())
    e1 = _make_entry(route_id="r-1")
    e2 = _make_entry(route_id="r-2")

    async def _go():
        await backend.put(e1)
        live = await LiveSnapshot.from_backend(backend)
        frozen = live.as_registry()
        live.apply(
            WatchEvent(
                op=WatchOp.PUT,
                route_id=e2.route_id,
                entry=e2,
                revision=2,
            )
        )
        return frozen, live.as_registry()

    frozen_first, current = _run(_go())
    # Frozen copy still has only e1.
    assert frozen_first.lookup("r-1") == e1
    assert frozen_first.lookup("r-2") is None
    # Current copy reflects both.
    assert current.lookup("r-1") == e1
    assert current.lookup("r-2") == e2


def test_t_nkv_ws_06_poisoned_put_value_raises():
    """T-NKV-WS-06: a PUT update carrying non-JSON bytes raises a
    clean :class:`RouteRegistryEnvelopeError` from the iterator.
    """
    kv = _MockKv()
    backend = NatsKvRouteRegistry(kv=kv)

    async def _go():
        stream = await backend.watch()
        # Hand-push a poisoned update bypassing the put-helper.
        kv._watcher._push(  # type: ignore[union-attr]
            _MockWatchUpdate(
                operation="PUT",
                key="r-poison",
                value=b"\xff\xfenot-json",
                revision=99,
            )
        )
        return await stream.__anext__()

    with pytest.raises(RouteRegistryEnvelopeError):
        _run(_go())


def test_t_nkv_ws_07_unknown_operation_raises():
    """T-NKV-WS-07: an update with an unrecognised ``operation``
    kind raises :class:`RouteRegistryEnvelopeError`.
    """
    kv = _MockKv()
    backend = NatsKvRouteRegistry(kv=kv)

    async def _go():
        stream = await backend.watch()
        kv._watcher._push(  # type: ignore[union-attr]
            _MockWatchUpdate(
                operation="WAT-UNKNOWN-OP",
                key="r-unknown",
                value=b"",
                revision=1,
            )
        )
        return await stream.__anext__()

    with pytest.raises(RouteRegistryEnvelopeError):
        _run(_go())


def test_t_nkv_ws_08_last_revision_monotonic():
    """T-NKV-WS-08: ``LiveSnapshot.last_revision`` advances with each
    applied event and never regresses.
    """
    backend = NatsKvRouteRegistry(kv=_MockKv())
    e1 = _make_entry(route_id="r-1")
    e2 = _make_entry(route_id="r-2")

    async def _go():
        return await LiveSnapshot.from_backend(backend)

    live = _run(_go())
    live.apply(WatchEvent(op=WatchOp.PUT, route_id="r-1", entry=e1, revision=5))
    assert live.last_revision == 5
    live.apply(WatchEvent(op=WatchOp.PUT, route_id="r-2", entry=e2, revision=10))
    assert live.last_revision == 10
    # An earlier-revision event does not regress the counter.
    live.apply(
        WatchEvent(op=WatchOp.DELETE, route_id="r-1", entry=None, revision=3)
    )
    assert live.last_revision == 10


def test_t_nkv_ws_09_live_snapshot_feeds_n2_evaluator():
    """T-NKV-WS-09: a frozen registry from a watch-fed snapshot
    drives the N2 evaluator to the same accept verdict as the
    full-snapshot path (cross-reference T-NKV-09).
    """
    backend = NatsKvRouteRegistry(kv=_MockKv())
    entry = _make_entry()

    async def _go():
        live = await LiveSnapshot.from_backend(backend)
        live.apply(
            WatchEvent(
                op=WatchOp.PUT,
                route_id=entry.route_id,
                entry=entry,
                revision=1,
            )
        )
        return live.as_registry()

    snap = _run(_go())
    resolve = FederatedResolveResult(
        aip_id=_AIP_ID,
        ftd_id=_FTD_ID,
        aip_body={"id": _AIP_ID, "stub": True},
        aip_jcs_sha256="ef" * 32,
        ftd_fingerprint_sha256="12" * 32,
        biscuit_root_pubkey_hex="ab" * 32,
        matched_issuer_kid="kid-1",
        verified_at=datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    from wirelang.federation.n2_evaluator import (
        FederationContext,
        FederationEvaluator,
    )

    ctx = FederationContext.from_resolve(resolve, snap)
    ev = FederationEvaluator(ctx)
    assert ev.evaluate_peer_org(_FTD_ID) is True
    assert ev.evaluate_federation_route(entry.route_id) is True


def test_t_nkv_ws_10_open_watch_stream_rejects_non_backend():
    """T-NKV-WS-10: ``open_watch_stream`` rejects a non-backend
    argument with ``TypeError``.
    """

    async def _go():
        return await open_watch_stream(object())  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        _run(_go())


def test_t_nkv_ws_aux_shape_one_async_iter():
    """T-NKV-WS-aux-async-iter: the watch handle wraps a Shape-1
    (native async-iter) mock and decodes events identically.
    """
    entry = _make_entry()
    blob = _entry_to_envelope(entry)
    items = [
        _MockWatchUpdate(
            operation="PUT", key=entry.route_id, value=blob, revision=7
        ),
    ]

    class _ShapeOneKv:
        async def watchall(self):
            return _ShapeOneMockWatcher(items)

    backend = NatsKvRouteRegistry(kv=_ShapeOneKv())

    async def _go():
        stream = await backend.watch()
        events = []
        async for ev in stream:
            events.append(ev)
        return events

    events = _run(_go())
    assert len(events) == 1
    assert events[0].op is WatchOp.PUT
    assert events[0].entry == entry
    assert events[0].revision == 7


def test_t_nkv_ws_aux_apply_rejects_non_event():
    """T-NKV-WS-aux-apply-non-event: ``LiveSnapshot.apply`` rejects
    non-``WatchEvent`` arguments with ``TypeError``.
    """
    backend = NatsKvRouteRegistry(kv=_MockKv())

    async def _go():
        return await LiveSnapshot.from_backend(backend)

    live = _run(_go())
    with pytest.raises(TypeError):
        live.apply({"op": "PUT"})  # type: ignore[arg-type]


def test_t_nkv_ws_aux_put_event_requires_entry():
    """T-NKV-WS-aux-put-requires-entry: a malformed PUT event
    without an entry payload is rejected by ``apply``.
    """
    backend = NatsKvRouteRegistry(kv=_MockKv())

    async def _go():
        return await LiveSnapshot.from_backend(backend)

    live = _run(_go())
    bad = WatchEvent(op=WatchOp.PUT, route_id="r-x", entry=None, revision=1)
    with pytest.raises(RouteRegistryEnvelopeError):
        live.apply(bad)
