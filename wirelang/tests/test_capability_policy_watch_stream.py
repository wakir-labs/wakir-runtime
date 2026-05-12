# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the Wirelang capability-policy watch-stream surface.

Phase-2 Sprint-5 Tag-5 (S5-5). Tests the additive watch-stream surface
on :mod:`wirelang.schemas.capability_policy_nats_kv_backend`:

- :class:`CapabilityPolicyWatchOp` / :class:`CapabilityPolicyWatchEvent`
- :meth:`NatsKvCapabilityPolicyBackend.watch`
- :func:`open_capability_policy_watch_stream`
- :class:`LiveCapabilityPolicySnapshot` (``from_backend`` / ``apply`` /
  ``as_registry`` / ``records``)
- :func:`_decode_capability_policy_watch_update` poison-handling

The watch-stream lands the Phase-3-reserved live-tail slot for the
capability-policy backend as a Sprint-5 Tag-5 additive surface. The
Tag-2 LWW path (``put`` / ``get`` / ``snapshot`` / ``snapshot_registry``)
and the Tag-4 CAS-pin path (``put_with_revision`` /
``get_with_revision``) are unaffected; Tag-5 surfaces are purely
additive.

Pattern source: Sprint-3 Tag-4 schema-registry watch-stream in
``wirelang/tests/test_schema_registry_watch_stream.py``. The mock
shapes mirror that pattern byte-equally: a manually-fed ``_MockWatcher``
with ``await updates()`` semantics (Shape 2 of the backend's adapter
contract) plus a ``_ShapeOneMockWatcher`` for the native async-iter
shape.

Test inventory (T-CPP-WS-01..10 + 2 aux probes):

- T-CPP-WS-01: ``watch()`` opens a stream and yields decoded PUT events.
- T-CPP-WS-02: a DELETE on the bucket surfaces a DELETE
  CapabilityPolicyWatchEvent; ``record`` is None.
- T-CPP-WS-03: ``LiveCapabilityPolicySnapshot.from_backend`` bootstraps
  from a full snapshot; subsequent ``apply(PUT)`` updates the live state.
- T-CPP-WS-04: ``LiveCapabilityPolicySnapshot.apply(DELETE)`` removes
  the key from the live state.
- T-CPP-WS-05: ``LiveCapabilityPolicySnapshot.as_registry`` returns a
  frozen copy; subsequent applies do NOT mutate it (determinism
  contract for verifier passes against
  :func:`check_registered_by_capability`).
- T-CPP-WS-06: a poisoned watch update (non-JSON value on PUT) raises
  CapabilityPolicyEnvelopeError and terminates the iterator.
- T-CPP-WS-07: an unknown ``operation`` kind raises
  CapabilityPolicyEnvelopeError.
- T-CPP-WS-08: ``LiveCapabilityPolicySnapshot.last_revision`` tracks
  the highest revision seen and is monotonic.
- T-CPP-WS-09: a frozen registry from a watch-fed snapshot exposes
  ``policies_for`` / ``list_issuers`` consistent with the full-snapshot
  path (Tag-2 cross-reference) and gates byte-identically.
- T-CPP-WS-10: ``open_capability_policy_watch_stream`` rejects a
  non-backend argument with TypeError.
- T-CPP-WS-aux-async-iter: the watch handle is async-iter compatible
  with the Shape-1 (native async iterator) mock.
- T-CPP-WS-aux-purge-removes: a PURGE CapabilityPolicyWatchEvent
  removes the key from the live state identically to DELETE.
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
    CapabilityPolicyEnvelopeError,
    CapabilityPolicyRecord,
    CapabilityPolicyWatchEvent,
    CapabilityPolicyWatchOp,
    LiveCapabilityPolicySnapshot,
    NatsKvCapabilityPolicyBackend,
    VALUE_SCHEMA,
    _record_to_envelope,
    key_for_policy_pair,
    open_capability_policy_watch_stream,
)
from wirelang.schemas.registered_by_capability import (
    CapabilityPolicy,
    CapabilityPolicyRegistry,
    check_registered_by_capability,
)
from wirelang.schemas.registry_nats_kv_backend import (
    SchemaRegistryEntry,
    schema_body_sha256,
)


# ---------------------------------------------------------------------------
# Mock KV with watch surface (mirrors Sprint-3 Tag-4 schema-registry mocks)
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

    Surfaces ``await kv.get/put/delete/keys/watchall`` for the
    capability-policy backend. ``put`` / ``delete`` push corresponding
    events onto an attached watcher when one is open (so backend-driven
    test flows surface events naturally).
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
    T-CPP-WS-aux-async-iter.
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


_REGISTERED_AT = datetime(2026, 5, 11, 22, 0, 0, tzinfo=timezone.utc)
_REGISTERED_BY_PUBLISHER = "wirelang-eng"
_REGISTERED_BY = "wirelang-eng"


def _make_policy(
    *,
    registered_by: str = _REGISTERED_BY,
    allowed_kids: tuple = ("biscuit-root-1",),
    allowed_triples: tuple = (("wire", "layer-1-*"),),
    not_before: Optional[datetime] = None,
    not_after: Optional[datetime] = None,
    disabled: bool = False,
    note: Optional[str] = None,
) -> CapabilityPolicy:
    return CapabilityPolicy(
        registered_by=registered_by,
        allowed_kids=allowed_kids,
        allowed_triples=allowed_triples,
        not_before=not_before,
        not_after=not_after,
        disabled=disabled,
        note=note,
    )


def _make_record(
    *,
    policy: Optional[CapabilityPolicy] = None,
    policy_id: str = "default",
    registered_at: datetime = _REGISTERED_AT,
    registered_by_publisher: str = _REGISTERED_BY_PUBLISHER,
    registered_by: str = _REGISTERED_BY,
    marker: str = "ws",
) -> CapabilityPolicyRecord:
    if policy is None:
        # Use ``marker`` to vary ``allowed_kids`` so two records with
        # different markers are not byte-equal envelopes; useful for
        # determinism cross-checks.
        policy = _make_policy(
            registered_by=registered_by,
            allowed_kids=(f"biscuit-root-{marker}",),
        )
    return CapabilityPolicyRecord(
        policy=policy,
        policy_id=policy_id,
        registered_at=registered_at,
        registered_by_publisher=registered_by_publisher,
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# T-CPP-WS-01..04: stream open + PUT / DELETE event surfacing
# ---------------------------------------------------------------------------


def test_t_cpp_ws_01_watch_yields_put_events():
    """T-CPP-WS-01: ``watch()`` yields PUT events for each upsert."""
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    r1 = _make_record(policy_id="rotation-1", marker="r1")
    r2 = _make_record(policy_id="rotation-2", marker="r2")

    async def _go():
        stream = await backend.watch()
        # Issue puts AFTER the watcher is open so the events land.
        await backend.put(r1)
        await backend.put(r2)
        kv._watcher._close()  # type: ignore[union-attr]
        events = []
        async for ev in stream:
            events.append(ev)
        await stream.__aexit__(None, None, None)
        return events

    events = _run(_go())
    assert len(events) == 2
    assert events[0].op is CapabilityPolicyWatchOp.PUT
    assert events[0].key == r1.key
    assert events[0].record == r1
    assert events[0].revision == 1
    assert events[1].op is CapabilityPolicyWatchOp.PUT
    assert events[1].key == r2.key
    assert events[1].record == r2


def test_t_cpp_ws_02_watch_yields_delete_event():
    """T-CPP-WS-02: a DELETE surfaces a DELETE event with
    ``record=None``.
    """
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    record = _make_record()

    async def _go():
        # PUT before watch -> not surfaced (no watcher yet).
        await backend.put(record)
        stream = await backend.watch()
        await backend.delete(record.key)
        kv._watcher._close()  # type: ignore[union-attr]
        events = []
        async for ev in stream:
            events.append(ev)
        return events

    events = _run(_go())
    assert len(events) == 1
    assert events[0].op is CapabilityPolicyWatchOp.DELETE
    assert events[0].key == record.key
    assert events[0].record is None
    assert events[0].revision >= 1


def test_t_cpp_ws_03_live_snapshot_bootstraps_and_applies_put():
    """T-CPP-WS-03: ``LiveCapabilityPolicySnapshot.from_backend``
    bootstraps from a full snapshot; ``apply(PUT)`` updates the live
    state.
    """
    backend = NatsKvCapabilityPolicyBackend(kv=_MockKv())
    r1 = _make_record(policy_id="rotation-1", marker="r1")
    r2 = _make_record(policy_id="rotation-2", marker="r2")

    async def _go():
        await backend.put(r1)
        live = await LiveCapabilityPolicySnapshot.from_backend(backend)
        # Initial bootstrap captures r1.
        before_records = list(live.records())
        # Apply a PUT delta for r2 directly (independent of the
        # watcher; tests the apply contract in isolation).
        live.apply(
            CapabilityPolicyWatchEvent(
                op=CapabilityPolicyWatchOp.PUT,
                key=r2.key,
                record=r2,
                revision=2,
            )
        )
        after_records = list(live.records())
        return before_records, after_records

    before, after = _run(_go())
    before_keys = [rec.key for rec in before]
    after_keys = [rec.key for rec in after]
    assert before_keys == [r1.key]
    assert sorted(after_keys) == sorted([r1.key, r2.key])


def test_t_cpp_ws_04_live_snapshot_apply_delete_removes_key():
    """T-CPP-WS-04: ``apply(DELETE)`` removes the key from the live
    state.
    """
    backend = NatsKvCapabilityPolicyBackend(kv=_MockKv())
    record = _make_record()

    async def _go():
        await backend.put(record)
        live = await LiveCapabilityPolicySnapshot.from_backend(backend)
        keys_before = [rec.key for rec in live.records()]
        live.apply(
            CapabilityPolicyWatchEvent(
                op=CapabilityPolicyWatchOp.DELETE,
                key=record.key,
                record=None,
                revision=2,
            )
        )
        keys_after = [rec.key for rec in live.records()]
        return keys_before, keys_after

    keys_before, keys_after = _run(_go())
    assert keys_before == [record.key]
    assert keys_after == []


# ---------------------------------------------------------------------------
# T-CPP-WS-05..08: determinism + revision monotonicity + poison-handling
# ---------------------------------------------------------------------------


def test_t_cpp_ws_05_as_registry_returns_frozen_copy():
    """T-CPP-WS-05: a registry handed out by ``as_registry`` is not
    mutated by subsequent ``apply()`` calls. This is the determinism
    contract for verifier passes against
    :func:`check_registered_by_capability`.
    """
    backend = NatsKvCapabilityPolicyBackend(kv=_MockKv())
    r1 = _make_record(
        policy_id="rotation-1",
        policy=_make_policy(
            registered_by="wirelang-eng",
            allowed_kids=("biscuit-root-1",),
        ),
    )
    # Second record under a DIFFERENT issuer so ``policies_for``
    # distinguishes the two adds.
    r2 = _make_record(
        policy_id="rotation-1",
        policy=_make_policy(
            registered_by="orchestrator-eng",
            allowed_kids=("biscuit-root-2",),
        ),
    )

    async def _go():
        await backend.put(r1)
        live = await LiveCapabilityPolicySnapshot.from_backend(backend)
        frozen = live.as_registry()
        live.apply(
            CapabilityPolicyWatchEvent(
                op=CapabilityPolicyWatchOp.PUT,
                key=r2.key,
                record=r2,
                revision=2,
            )
        )
        return frozen, live.as_registry()

    frozen_first, current = _run(_go())
    # Frozen copy still has only r1's issuer.
    assert frozen_first.list_issuers() == ("wirelang-eng",)
    assert frozen_first.policies_for("orchestrator-eng") == ()
    # Current copy reflects both.
    assert current.list_issuers() == ("orchestrator-eng", "wirelang-eng")
    assert len(current.policies_for("orchestrator-eng")) == 1


def test_t_cpp_ws_06_poisoned_put_value_raises():
    """T-CPP-WS-06: a PUT update carrying non-JSON bytes raises
    :class:`CapabilityPolicyEnvelopeError` from the iterator.
    """
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)

    async def _go():
        stream = await backend.watch()
        # Hand-push a poisoned update bypassing the put-helper.
        kv._watcher._push(  # type: ignore[union-attr]
            _MockWatchUpdate(
                operation="PUT",
                key="capability-policies/wirelang-eng/poison",
                value=b"\xff\xfenot-json",
                revision=99,
            )
        )
        return await stream.__anext__()

    with pytest.raises(CapabilityPolicyEnvelopeError):
        _run(_go())


def test_t_cpp_ws_07_unknown_operation_raises():
    """T-CPP-WS-07: an update with an unrecognised ``operation`` kind
    raises :class:`CapabilityPolicyEnvelopeError`.
    """
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)

    async def _go():
        stream = await backend.watch()
        kv._watcher._push(  # type: ignore[union-attr]
            _MockWatchUpdate(
                operation="WAT-UNKNOWN-OP",
                key="capability-policies/wirelang-eng/unknown",
                value=b"",
                revision=1,
            )
        )
        return await stream.__anext__()

    with pytest.raises(CapabilityPolicyEnvelopeError):
        _run(_go())


def test_t_cpp_ws_08_last_revision_monotonic():
    """T-CPP-WS-08: ``LiveCapabilityPolicySnapshot.last_revision``
    advances with each applied event and never regresses.
    """
    backend = NatsKvCapabilityPolicyBackend(kv=_MockKv())
    r1 = _make_record(policy_id="rotation-1", marker="r1")
    r2 = _make_record(policy_id="rotation-2", marker="r2")

    async def _go():
        return await LiveCapabilityPolicySnapshot.from_backend(backend)

    live = _run(_go())
    live.apply(
        CapabilityPolicyWatchEvent(
            op=CapabilityPolicyWatchOp.PUT,
            key=r1.key,
            record=r1,
            revision=5,
        )
    )
    assert live.last_revision == 5
    live.apply(
        CapabilityPolicyWatchEvent(
            op=CapabilityPolicyWatchOp.PUT,
            key=r2.key,
            record=r2,
            revision=10,
        )
    )
    assert live.last_revision == 10
    # An earlier-revision event does not regress the counter.
    live.apply(
        CapabilityPolicyWatchEvent(
            op=CapabilityPolicyWatchOp.DELETE,
            key=r1.key,
            record=None,
            revision=3,
        )
    )
    assert live.last_revision == 10


# ---------------------------------------------------------------------------
# T-CPP-WS-09..10: cross-path consistency + arg validation
# ---------------------------------------------------------------------------


def test_t_cpp_ws_09_live_snapshot_gates_consistent_with_full_snapshot():
    """T-CPP-WS-09: a frozen registry from a watch-fed snapshot gates
    identically to the full-snapshot path against the Sprint-4 Tag-6
    :func:`check_registered_by_capability` gate. Cross-reference
    T-CPP-04 (full snapshot_registry).
    """
    backend = NatsKvCapabilityPolicyBackend(kv=_MockKv())
    record = _make_record(
        policy_id="rotation-1",
        policy=_make_policy(
            registered_by="wirelang-eng",
            allowed_kids=("biscuit-root-1",),
            allowed_triples=(("wire", "layer-1-*"),),
        ),
    )

    async def _go():
        # Watch-fed live view (apply path).
        live = await LiveCapabilityPolicySnapshot.from_backend(backend)
        live.apply(
            CapabilityPolicyWatchEvent(
                op=CapabilityPolicyWatchOp.PUT,
                key=record.key,
                record=record,
                revision=1,
            )
        )
        # Independent: take a fresh full snapshot through the backend
        # path AFTER putting the record directly so we can compare.
        await backend.put(record)
        full = await backend.snapshot_registry()
        return live.as_registry(), full

    watch_view, full_view = _run(_go())

    # Both views see the issuer under ``list_issuers``.
    assert watch_view.list_issuers() == ("wirelang-eng",)
    assert full_view.list_issuers() == ("wirelang-eng",)
    # Both views carry one policy for the issuer.
    assert len(watch_view.policies_for("wirelang-eng")) == 1
    assert len(full_view.policies_for("wirelang-eng")) == 1
    # Both views gate identically against the Sprint-4 Tag-6 gate.
    schema_body = {
        "$id": "https://wakir.dev/wirelang/schemas/wire/layer-1-wire/0.1.0",
        "type": "object",
    }
    gate_entry = SchemaRegistryEntry(
        layer="wire",
        name="layer-1-wire",
        version="0.1.0",
        schema_id=schema_body["$id"],
        schema_body=schema_body,
        schema_body_sha256=schema_body_sha256(schema_body),
        registered_at=_REGISTERED_AT,
        registered_by="wirelang-eng",
    )
    sig_block = {"kid": "biscuit-root-1"}
    decision_watch = check_registered_by_capability(
        gate_entry,
        sig_block,
        watch_view,
        as_of=_REGISTERED_AT,
    )
    decision_full = check_registered_by_capability(
        gate_entry,
        sig_block,
        full_view,
        as_of=_REGISTERED_AT,
    )
    assert decision_watch.allowed is True
    assert decision_full.allowed is True
    assert decision_watch.allowed == decision_full.allowed


def test_t_cpp_ws_10_open_watch_stream_rejects_non_backend():
    """T-CPP-WS-10: ``open_capability_policy_watch_stream`` rejects a
    non-backend argument with ``TypeError``.
    """

    class _NotABackend:
        pass

    async def _go():
        return await open_capability_policy_watch_stream(_NotABackend())  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        _run(_go())


# ---------------------------------------------------------------------------
# Auxiliary probes
# ---------------------------------------------------------------------------


def test_t_cpp_ws_aux_async_iter_shape_one():
    """T-CPP-WS-aux-async-iter: the watch handle is async-iter
    compatible with the Shape-1 (native ``__aiter__`` / ``__anext__``)
    watcher.
    """
    record = _make_record()
    blob = _record_to_envelope(record)

    @dataclass
    class _ShapeOneUpdate:
        operation: str
        key: str
        value: bytes
        revision: int

    items = [
        _ShapeOneUpdate(
            operation="PUT",
            key=record.key,
            value=blob,
            revision=1,
        ),
        # nats-py end-of-initial-replay sentinel (None) is filtered out
        # at the handle layer.
        None,
        _ShapeOneUpdate(
            operation="DELETE",
            key=record.key,
            value=b"",
            revision=2,
        ),
    ]
    kv = _MockKvShapeOne(items=items)
    backend = NatsKvCapabilityPolicyBackend(kv=kv)

    async def _go():
        stream = await backend.watch()
        events = []
        async for ev in stream:
            events.append(ev)
        return events

    events = _run(_go())
    assert len(events) == 2
    assert events[0].op is CapabilityPolicyWatchOp.PUT
    assert events[0].key == record.key
    assert events[0].record == record
    assert events[0].revision == 1
    assert events[1].op is CapabilityPolicyWatchOp.DELETE
    assert events[1].record is None
    assert events[1].revision == 2


def test_t_cpp_ws_aux_purge_removes_key_identically_to_delete():
    """T-CPP-WS-aux-purge-removes: a PURGE CapabilityPolicyWatchEvent
    removes the key from the live state identically to DELETE.
    """
    backend = NatsKvCapabilityPolicyBackend(kv=_MockKv())
    record = _make_record()

    async def _go():
        await backend.put(record)
        live = await LiveCapabilityPolicySnapshot.from_backend(backend)
        keys_before = [rec.key for rec in live.records()]
        live.apply(
            CapabilityPolicyWatchEvent(
                op=CapabilityPolicyWatchOp.PURGE,
                key=record.key,
                record=None,
                revision=2,
            )
        )
        keys_after = [rec.key for rec in live.records()]
        return keys_before, keys_after

    keys_before, keys_after = _run(_go())
    assert keys_before == [record.key]
    assert keys_after == []
