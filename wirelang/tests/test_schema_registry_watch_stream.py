# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the Wirelang schema-registry watch-stream surface.

Phase-1b Sprint-3 Tag-4 (S3-4). Tests the additive watch-stream
surface on :mod:`wirelang.schemas.registry_nats_kv_backend`:

- :class:`WatchOp` / :class:`WatchEvent`
- :meth:`NatsKvSchemaRegistry.watch`
- :func:`open_watch_stream`
- :class:`LiveSchemaSnapshot` (``from_backend`` / ``apply`` /
  ``as_registry``)
- :func:`_decode_watch_update` poison-handling

The watch-stream is the OI-7-Phase-1c-watch slot landing for the
schema-registry backend. The Tag-1 LWW path
(``put`` / ``get`` / ``snapshot``) and the Tag-3 CAS-pin path
(``put_with_revision`` / ``get_with_revision``) are unaffected;
Tag-4 surfaces are purely additive.

Pattern source: V-908 Tag-6 watch-stream-snapshot layer in
``wirelang/federation/route_registry_nats_kv_backend.py``. The mock
shapes mirror the V-908 mock pattern: a manually-fed ``_MockWatcher``
with ``await updates()`` semantics (Shape 2 of the backend's adapter
contract) plus a ``_ShapeOneMockWatcher`` for the native async-iter
shape.

Test inventory (T-SR-WS-01..10 + 2 aux probes):

- T-SR-WS-01: ``watch()`` opens a stream and yields decoded PUT events.
- T-SR-WS-02: a DELETE on the bucket surfaces a DELETE WatchEvent;
  ``entry`` is None.
- T-SR-WS-03: ``LiveSchemaSnapshot.from_backend`` bootstraps from a
  full snapshot; subsequent ``apply(PUT)`` updates the live state.
- T-SR-WS-04: ``LiveSchemaSnapshot.apply(DELETE)`` removes the key
  from the live state.
- T-SR-WS-05: ``LiveSchemaSnapshot.as_registry`` returns a frozen
  copy; subsequent applies do NOT mutate it (determinism contract
  for verifier passes).
- T-SR-WS-06: a poisoned watch update (non-JSON value on PUT) raises
  SchemaRegistryEnvelopeError and terminates the iterator.
- T-SR-WS-07: an unknown ``operation`` kind raises
  SchemaRegistryEnvelopeError.
- T-SR-WS-08: ``LiveSchemaSnapshot.last_revision`` tracks the highest
  revision seen and is monotonic.
- T-SR-WS-09: a frozen registry from a watch-fed snapshot exposes
  ``lookup`` / ``lookup_by_triple`` consistent with the full-snapshot
  path (Tag-1 cross-reference).
- T-SR-WS-10: ``open_watch_stream`` rejects a non-backend argument
  with TypeError.
- T-SR-WS-aux-async-iter: the watch handle is async-iter compatible
  with the Shape-1 (native async iterator) mock.
- T-SR-WS-aux-purge-removes: a PURGE WatchEvent removes the key
  identically to DELETE.
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
    InMemorySchemaRegistry,
    LiveSchemaSnapshot,
    NatsKvSchemaRegistry,
    SchemaRegistryEnvelopeError,
    SchemaRegistryEntry,
    VALUE_SCHEMA,
    WatchEvent,
    WatchOp,
    _entry_to_envelope,
    key_for_triple,
    open_watch_stream,
    schema_body_sha256,
)


# ---------------------------------------------------------------------------
# Mock KV with watch surface (mirrors V-908 Tag-6 mock pattern)
# ---------------------------------------------------------------------------


class _MockBucketNotFoundError(Exception):
    """Mirrors nats-py's ``KeyNotFoundError`` class-name pattern."""


@dataclass
class _MockKvEntry:
    """Shape-equivalent of nats-py's ``KeyValue.Entry``."""

    value: bytes
    revision: int = 0


@dataclass
class _MockWatchUpdate:
    """Shape-equivalent of nats-py's ``KeyValue.Entry`` exposed
    through the watcher: carries ``operation`` (string), ``key``,
    ``value``, ``revision``.
    """

    operation: str  # "PUT" / "DELETE" / "PURGE"
    key: str
    value: bytes = b""
    revision: int = 0


class _MockWatcher:
    """Manually-fed Shape-2 mock watcher (``await updates()`` returns
    next or None for end-of-stream).
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


@dataclass
class _MockKv:
    """In-memory replacement for nats-py's ``KeyValue`` handle.

    Surfaces ``await kv.get/put/delete/keys/watchall`` for the schema
    registry backend. ``put`` / ``delete`` push corresponding events
    onto an attached watcher when one is open (so backend-driven test
    flows surface events naturally).
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


@dataclass
class _MockKvShapeOne:
    """KV that exposes ``watch()`` returning a Shape-1 async-iter
    watcher pre-loaded with the supplied items. Used by
    T-SR-WS-aux-async-iter.
    """

    items: list
    store: dict = field(default_factory=dict)

    async def keys(self) -> list:
        return list(self.store.keys())

    async def get(self, key: str):
        if key not in self.store:
            raise _MockBucketNotFoundError(f"key not found: {key}")
        return self.store[key]

    async def watch(self) -> _ShapeOneMockWatcher:
        return _ShapeOneMockWatcher(self.items)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_REGISTERED_AT = datetime(2026, 5, 7, 13, 0, 0, tzinfo=timezone.utc)
_REGISTERED_BY = "wirelang-eng"


def _make_schema_body(schema_id: str, *, marker: str = "watch") -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "title": f"watch-stream test schema ({marker})",
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
    marker: str = "watch",
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
# T-SR-WS-01..04: stream open + PUT / DELETE event surfacing
# ---------------------------------------------------------------------------


def test_t_sr_ws_01_watch_yields_put_events():
    """T-SR-WS-01: ``watch()`` yields PUT events for each upsert."""
    kv = _MockKv()
    backend = NatsKvSchemaRegistry(kv=kv)
    e1 = _make_entry(name="layer-1-wire", version="0.1.0", marker="e1")
    e2 = _make_entry(name="layer-2-semantic", version="0.1.0", marker="e2")

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
    assert events[0].key == e1.key
    assert events[0].entry == e1
    assert events[0].revision == 1
    assert events[1].op is WatchOp.PUT
    assert events[1].key == e2.key
    assert events[1].entry == e2


def test_t_sr_ws_02_watch_yields_delete_event():
    """T-SR-WS-02: a DELETE surfaces a DELETE WatchEvent with
    ``entry=None``.
    """
    kv = _MockKv()
    backend = NatsKvSchemaRegistry(kv=kv)
    entry = _make_entry()

    async def _go():
        # PUT before watch -> not surfaced (no watcher yet).
        await backend.put(entry)
        stream = await backend.watch()
        await backend.delete(entry.key)
        kv._watcher._close()  # type: ignore[union-attr]
        events = []
        async for ev in stream:
            events.append(ev)
        return events

    events = _run(_go())
    assert len(events) == 1
    assert events[0].op is WatchOp.DELETE
    assert events[0].key == entry.key
    assert events[0].entry is None
    assert events[0].revision >= 1


def test_t_sr_ws_03_live_snapshot_bootstraps_and_applies_put():
    """T-SR-WS-03: ``LiveSchemaSnapshot.from_backend`` bootstraps from
    a full snapshot; ``apply(PUT)`` updates the live state.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKv())
    e1 = _make_entry(name="layer-1-wire", version="0.1.0", marker="e1")
    e2 = _make_entry(name="layer-2-semantic", version="0.1.0", marker="e2")

    async def _go():
        await backend.put(e1)
        live = await LiveSchemaSnapshot.from_backend(backend)
        # Initial bootstrap captures e1.
        before = live.as_registry()
        # Apply a PUT delta for e2 directly (independent of the
        # watcher; tests the apply contract in isolation).
        live.apply(
            WatchEvent(
                op=WatchOp.PUT,
                key=e2.key,
                entry=e2,
                revision=2,
            )
        )
        after = live.as_registry()
        return before, after

    before, after = _run(_go())
    assert before.lookup(e1.key) == e1
    assert before.lookup(e2.key) is None
    assert after.lookup(e1.key) == e1
    assert after.lookup(e2.key) == e2


def test_t_sr_ws_04_live_snapshot_apply_delete_removes_key():
    """T-SR-WS-04: ``apply(DELETE)`` removes the key from the live
    state.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKv())
    entry = _make_entry()

    async def _go():
        await backend.put(entry)
        live = await LiveSchemaSnapshot.from_backend(backend)
        assert live.as_registry().lookup(entry.key) == entry
        live.apply(
            WatchEvent(
                op=WatchOp.DELETE,
                key=entry.key,
                entry=None,
                revision=2,
            )
        )
        return live.as_registry()

    after = _run(_go())
    assert after.lookup(entry.key) is None


# ---------------------------------------------------------------------------
# T-SR-WS-05..08: determinism + revision monotonicity + poison-handling
# ---------------------------------------------------------------------------


def test_t_sr_ws_05_as_registry_returns_frozen_copy():
    """T-SR-WS-05: a registry handed out by ``as_registry`` is not
    mutated by subsequent ``apply()`` calls. This is the determinism
    contract for verifier passes.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKv())
    e1 = _make_entry(name="layer-1-wire", version="0.1.0", marker="e1")
    e2 = _make_entry(name="layer-2-semantic", version="0.1.0", marker="e2")

    async def _go():
        await backend.put(e1)
        live = await LiveSchemaSnapshot.from_backend(backend)
        frozen = live.as_registry()
        live.apply(
            WatchEvent(
                op=WatchOp.PUT,
                key=e2.key,
                entry=e2,
                revision=2,
            )
        )
        return frozen, live.as_registry()

    frozen_first, current = _run(_go())
    # Frozen copy still has only e1.
    assert frozen_first.lookup(e1.key) == e1
    assert frozen_first.lookup(e2.key) is None
    # Current copy reflects both.
    assert current.lookup(e1.key) == e1
    assert current.lookup(e2.key) == e2


def test_t_sr_ws_06_poisoned_put_value_raises():
    """T-SR-WS-06: a PUT update carrying non-JSON bytes raises
    :class:`SchemaRegistryEnvelopeError` from the iterator.
    """
    kv = _MockKv()
    backend = NatsKvSchemaRegistry(kv=kv)

    async def _go():
        stream = await backend.watch()
        # Hand-push a poisoned update bypassing the put-helper.
        kv._watcher._push(  # type: ignore[union-attr]
            _MockWatchUpdate(
                operation="PUT",
                key="schemas/wire/poison/0.0.0",
                value=b"\xff\xfenot-json",
                revision=99,
            )
        )
        return await stream.__anext__()

    with pytest.raises(SchemaRegistryEnvelopeError):
        _run(_go())


def test_t_sr_ws_07_unknown_operation_raises():
    """T-SR-WS-07: an update with an unrecognised ``operation`` kind
    raises :class:`SchemaRegistryEnvelopeError`.
    """
    kv = _MockKv()
    backend = NatsKvSchemaRegistry(kv=kv)

    async def _go():
        stream = await backend.watch()
        kv._watcher._push(  # type: ignore[union-attr]
            _MockWatchUpdate(
                operation="WAT-UNKNOWN-OP",
                key="schemas/wire/unknown/0.0.0",
                value=b"",
                revision=1,
            )
        )
        return await stream.__anext__()

    with pytest.raises(SchemaRegistryEnvelopeError):
        _run(_go())


def test_t_sr_ws_08_last_revision_monotonic():
    """T-SR-WS-08: ``LiveSchemaSnapshot.last_revision`` advances with
    each applied event and never regresses.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKv())
    e1 = _make_entry(name="layer-1-wire", version="0.1.0", marker="e1")
    e2 = _make_entry(name="layer-2-semantic", version="0.1.0", marker="e2")

    async def _go():
        return await LiveSchemaSnapshot.from_backend(backend)

    live = _run(_go())
    live.apply(WatchEvent(op=WatchOp.PUT, key=e1.key, entry=e1, revision=5))
    assert live.last_revision == 5
    live.apply(WatchEvent(op=WatchOp.PUT, key=e2.key, entry=e2, revision=10))
    assert live.last_revision == 10
    # An earlier-revision event does not regress the counter.
    live.apply(
        WatchEvent(op=WatchOp.DELETE, key=e1.key, entry=None, revision=3)
    )
    assert live.last_revision == 10


# ---------------------------------------------------------------------------
# T-SR-WS-09..10: cross-path consistency + arg validation
# ---------------------------------------------------------------------------


def test_t_sr_ws_09_live_snapshot_lookup_consistent_with_full_snapshot():
    """T-SR-WS-09: a frozen registry from a watch-fed snapshot exposes
    ``lookup`` / ``lookup_by_triple`` results consistent with the
    full-snapshot path. Cross-reference T-SR-05 (full snapshot).
    """
    backend = NatsKvSchemaRegistry(kv=_MockKv())
    entry = _make_entry()

    async def _go():
        live = await LiveSchemaSnapshot.from_backend(backend)
        live.apply(
            WatchEvent(
                op=WatchOp.PUT,
                key=entry.key,
                entry=entry,
                revision=1,
            )
        )
        # Independent: take a fresh full snapshot through the backend
        # path AFTER putting the entry directly so we can compare.
        await backend.put(entry)
        full = await backend.snapshot()
        return live.as_registry(), full

    watch_view, full_view = _run(_go())

    # Both views see the entry under both lookup styles.
    assert watch_view.lookup(entry.key) == entry
    assert (
        watch_view.lookup_by_triple(entry.layer, entry.name, entry.version)
        == entry
    )
    assert full_view.lookup(entry.key) == entry
    assert (
        full_view.lookup_by_triple(entry.layer, entry.name, entry.version)
        == entry
    )
    # Sorted-key contract holds across both.
    assert watch_view.keys_sorted() == full_view.keys_sorted()


def test_t_sr_ws_10_open_watch_stream_rejects_non_backend():
    """T-SR-WS-10: ``open_watch_stream`` rejects a non-backend
    argument with ``TypeError``.
    """

    class _NotABackend:
        pass

    async def _go():
        return await open_watch_stream(_NotABackend())  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        _run(_go())


# ---------------------------------------------------------------------------
# Auxiliary probes
# ---------------------------------------------------------------------------


def test_t_sr_ws_aux_async_iter_shape_one():
    """T-SR-WS-aux-async-iter: the watch handle is async-iter
    compatible with the Shape-1 (native ``__aiter__`` / ``__anext__``)
    watcher.
    """
    entry = _make_entry()
    blob = _entry_to_envelope(entry)

    @dataclass
    class _ShapeOneUpdate:
        operation: str
        key: str
        value: bytes
        revision: int

    items = [
        _ShapeOneUpdate(
            operation="PUT",
            key=entry.key,
            value=blob,
            revision=1,
        ),
        # nats-py end-of-initial-replay sentinel (None) is filtered out
        # at the handle layer.
        None,
        _ShapeOneUpdate(
            operation="DELETE",
            key=entry.key,
            value=b"",
            revision=2,
        ),
    ]
    kv = _MockKvShapeOne(items=items)
    backend = NatsKvSchemaRegistry(kv=kv)

    async def _go():
        stream = await backend.watch()
        events = []
        async for ev in stream:
            events.append(ev)
        return events

    events = _run(_go())
    assert len(events) == 2
    assert events[0].op is WatchOp.PUT
    assert events[0].key == entry.key
    assert events[0].entry == entry
    assert events[0].revision == 1
    assert events[1].op is WatchOp.DELETE
    assert events[1].entry is None
    assert events[1].revision == 2


def test_t_sr_ws_aux_purge_removes_key_identically_to_delete():
    """T-SR-WS-aux-purge-removes: a PURGE WatchEvent removes the key
    from the live state identically to DELETE.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKv())
    entry = _make_entry()

    async def _go():
        await backend.put(entry)
        live = await LiveSchemaSnapshot.from_backend(backend)
        assert live.as_registry().lookup(entry.key) == entry
        live.apply(
            WatchEvent(
                op=WatchOp.PURGE,
                key=entry.key,
                entry=None,
                revision=2,
            )
        )
        return live.as_registry()

    after = _run(_go())
    assert after.lookup(entry.key) is None
