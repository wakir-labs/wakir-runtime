# SPDX-License-Identifier: BUSL-1.1
"""Sprint-Pengine-9 OI-PEFR-1 tests: async NATS-KV state-backing.

Hermetic stubs simulate the nats-py 2.6+ surface so the tests run
without a live NATS server. The stubs cover:

  - ``Client.connect`` / ``Client.close``
  - ``JetStreamContext.key_value``
  - ``KeyValue.put`` (returns Entry-like object)
  - ``KeyValue.get`` (returns Entry-like object with ``value`` + ``revision``)
  - ``KeyValue.keys`` (returns list of key strings)
  - ``KeyValue.update`` (revision-CAS)

All tests are pure-asyncio (``asyncio.run``); no threads, no
external sockets.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from wirelang.persona_engine.state_backing import (
    InMemoryPersonaStateBacking,
    LATEST_KEY,
    NEXT_OFFSET_KEY,
    NatsKvPersonaStateBacking,
    NatsKvPersonaStateBackingAsync,
    OFFSET_KEY_WIDTH,
    PINNED_KEY,
    PersonaStateBackingAsync,
    PersonaStateBackingError,
    PersonaStateSnapshot,
    STATE_PACK_KEY_PREFIX,
    offset_from_key,
    offset_key,
    snapshot_from_jcs_bytes,
    snapshot_to_jcs_bytes,
)


def _snap(seed: int = 0) -> PersonaStateSnapshot:
    return PersonaStateSnapshot(
        persona_hash="sha256:" + "0" * 64,
        audit_trace_offset=seed,
        capability_token_ids=("tok-1", "tok-2"),
        snapshot_at_utc=f"2026-05-15T{seed:02d}:00:00Z",
        workspace_state_hash="sha256:" + "1" * 64,
    )


# -------------------- key-layout helpers --------------------


def test_offset_key_zero_padded_width():
    k = offset_key(7)
    assert k == f"{STATE_PACK_KEY_PREFIX}/{'0' * (OFFSET_KEY_WIDTH - 1)}7"


def test_offset_key_negative_rejected():
    with pytest.raises(ValueError):
        offset_key(-1)


def test_offset_from_key_round_trip():
    assert offset_from_key(offset_key(42)) == 42
    assert offset_from_key(offset_key(0)) == 0
    assert offset_from_key(offset_key(99999)) == 99999


def test_offset_from_key_rejects_sentinel():
    with pytest.raises(ValueError):
        offset_from_key(PINNED_KEY)
    with pytest.raises(ValueError):
        offset_from_key(NEXT_OFFSET_KEY)
    with pytest.raises(ValueError):
        offset_from_key(LATEST_KEY)


def test_offset_from_key_rejects_non_state_pack():
    with pytest.raises(ValueError):
        offset_from_key("not-a-state-pack-key/00000000000000000001")


# -------------------- snapshot serialisation round-trip --------------------


def test_snapshot_round_trip_through_jcs_bytes():
    s = _snap(3)
    blob = snapshot_to_jcs_bytes(s)
    s2 = snapshot_from_jcs_bytes(blob)
    assert s == s2


def test_snapshot_from_jcs_bytes_rejects_missing_keys():
    import json

    bad = json.dumps({"persona_hash": "sha256:x" * 64}).encode("utf-8")
    with pytest.raises(ValueError):
        snapshot_from_jcs_bytes(bad)


def test_snapshot_from_jcs_bytes_coerces_types():
    import json

    obj = {
        "audit_trace_offset": "5",  # numeric-string OK
        "capability_token_ids": ["a", "b"],
        "persona_hash": "sha256:" + "0" * 64,
        "snapshot_at_utc": "2026-05-15T00:00:00Z",
        "workspace_state_hash": "sha256:" + "1" * 64,
    }
    blob = json.dumps(obj).encode("utf-8")
    s = snapshot_from_jcs_bytes(blob)
    assert s.audit_trace_offset == 5
    assert s.capability_token_ids == ("a", "b")


# -------------------- hermetic stub NATS-KV --------------------


class _StubEntry:
    def __init__(self, value: bytes, revision: int = 1) -> None:
        self.value = value
        self.revision = revision


class _StubKv:
    def __init__(self) -> None:
        self._store: Dict[str, _StubEntry] = {}

    async def put(self, key: str, value: bytes) -> _StubEntry:
        prev = self._store.get(key)
        rev = (prev.revision + 1) if prev else 1
        entry = _StubEntry(value=bytes(value), revision=rev)
        self._store[key] = entry
        return entry

    async def get(self, key: str) -> Optional[_StubEntry]:
        return self._store.get(key)

    async def keys(self) -> List[str]:
        return sorted(self._store.keys())

    async def update(self, key: str, value: bytes, *, last: int) -> _StubEntry:
        prev = self._store.get(key)
        if prev is not None and prev.revision != last:
            raise RuntimeError(
                f"CAS conflict on {key}: have rev={prev.revision}, last={last}"
            )
        return await self.put(key, value)


class _StubJs:
    def __init__(self) -> None:
        self._buckets: Dict[str, _StubKv] = {}

    async def key_value(self, bucket: str) -> _StubKv:
        if bucket not in self._buckets:
            self._buckets[bucket] = _StubKv()
        return self._buckets[bucket]


class _StubClient:
    def __init__(self) -> None:
        self._js = _StubJs()
        self.closed = False

    def jetstream(self) -> _StubJs:
        return self._js

    async def close(self) -> None:
        self.closed = True


async def _make_async_backing(
    org_id: str = "acme",
) -> NatsKvPersonaStateBackingAsync:
    client = _StubClient()

    async def factory(_servers: str, _timeout: float) -> _StubClient:
        return client

    async def js_factory(_client: _StubClient) -> _StubJs:
        return _client.jetstream()

    backing = NatsKvPersonaStateBackingAsync(
        nats_servers="nats://stub:4222",
        org_id=org_id,
        nats_client_factory=factory,
        js_factory=js_factory,
    )
    await backing.connect()
    return backing


# -------------------- async snapshot semantics --------------------


def test_async_snapshot_assigns_monotonic_offsets():
    async def go() -> None:
        b = await _make_async_backing()
        off1 = await b.snapshot("tomas", _snap(0))
        off2 = await b.snapshot("tomas", _snap(1))
        assert off1 == 1
        assert off2 == 2
        await b.close()

    asyncio.run(go())


def test_async_snapshot_idempotent_on_byte_equal():
    async def go() -> None:
        b = await _make_async_backing()
        s = _snap(0)
        off1 = await b.snapshot("tomas", s)
        off2 = await b.snapshot("tomas", s)
        assert off1 == off2
        await b.close()

    asyncio.run(go())


def test_async_restore_latest_round_trips_bytes():
    async def go() -> None:
        b = await _make_async_backing()
        s = _snap(7)
        await b.snapshot("tomas", s)
        restored = await b.restore_latest("tomas")
        assert restored is not None
        assert snapshot_to_jcs_bytes(restored) == snapshot_to_jcs_bytes(s)
        await b.close()

    asyncio.run(go())


def test_async_restore_latest_none_on_cold_start():
    async def go() -> None:
        b = await _make_async_backing()
        assert await b.restore_latest("tomas") is None
        await b.close()

    asyncio.run(go())


def test_async_list_snapshots_oldest_first():
    async def go() -> None:
        b = await _make_async_backing()
        await b.snapshot("tomas", _snap(0))
        await b.snapshot("tomas", _snap(1))
        await b.snapshot("tomas", _snap(2))
        offsets = await b.list_snapshots("tomas")
        assert offsets == [1, 2, 3]
        await b.close()

    asyncio.run(go())


def test_async_list_snapshots_skips_sentinel_keys():
    async def go() -> None:
        b = await _make_async_backing()
        await b.snapshot("tomas", _snap(0))
        kv = await b._kv_for("tomas")
        # Sentinel keys must be ignored by list_snapshots.
        assert (await b.list_snapshots("tomas")) == [1]
        # __next_offset__ exists; latest exists.
        keys = await kv.keys()
        assert NEXT_OFFSET_KEY in keys
        assert LATEST_KEY in keys
        await b.close()

    asyncio.run(go())


def test_async_atomic_swap_pinned_offset_first_pin():
    async def go() -> None:
        b = await _make_async_backing()
        off = await b.snapshot("tomas", _snap(0))
        await b.atomic_swap_pinned_offset(
            "tomas", from_offset=0, to_offset=off,
        )
        kv = await b._kv_for("tomas")
        entry = await kv.get(PINNED_KEY)
        assert entry is not None
        assert int(entry.value.decode("utf-8")) == off
        await b.close()

    asyncio.run(go())


def test_async_atomic_swap_rejects_mismatched_from():
    async def go() -> None:
        b = await _make_async_backing()
        off1 = await b.snapshot("tomas", _snap(0))
        off2 = await b.snapshot("tomas", _snap(1))
        await b.atomic_swap_pinned_offset(
            "tomas", from_offset=0, to_offset=off1,
        )
        with pytest.raises(PersonaStateBackingError):
            await b.atomic_swap_pinned_offset(
                "tomas", from_offset=999, to_offset=off2,
            )
        await b.close()

    asyncio.run(go())


def test_async_atomic_swap_rejects_unknown_target_offset():
    async def go() -> None:
        b = await _make_async_backing()
        await b.snapshot("tomas", _snap(0))
        with pytest.raises(PersonaStateBackingError):
            await b.atomic_swap_pinned_offset(
                "tomas", from_offset=0, to_offset=42,
            )
        await b.close()

    asyncio.run(go())


def test_async_cross_persona_isolation():
    async def go() -> None:
        b = await _make_async_backing()
        await b.snapshot("tomas", _snap(0))
        await b.snapshot("aisha", _snap(0))
        assert await b.list_snapshots("tomas") == [1]
        assert await b.list_snapshots("aisha") == [1]
        await b.close()

    asyncio.run(go())


def test_async_close_idempotent():
    async def go() -> None:
        b = await _make_async_backing()
        await b.close()
        await b.close()
        # After close, _kv_cache is cleared.
        assert b._kv_cache == {}

    asyncio.run(go())


def test_async_aenter_aexit_helpers():
    async def go() -> None:
        client = _StubClient()

        async def factory(_s: str, _t: float) -> _StubClient:
            return client

        async def js_factory(_c: _StubClient) -> _StubJs:
            return _c.jetstream()

        async with NatsKvPersonaStateBackingAsync(
            nats_servers="nats://stub:4222",
            org_id="acme",
            nats_client_factory=factory,
            js_factory=js_factory,
        ) as backing:
            await backing.snapshot("tomas", _snap(0))
        assert client.closed is True

    asyncio.run(go())


def test_async_kv_cache_reuses_kv_handle():
    async def go() -> None:
        b = await _make_async_backing()
        kv1 = await b._kv_for("tomas")
        kv2 = await b._kv_for("tomas")
        assert kv1 is kv2
        await b.close()

    asyncio.run(go())


def test_async_backing_trait_subclass_check():
    async def go() -> None:
        b = await _make_async_backing()
        assert isinstance(b, PersonaStateBackingAsync)
        await b.close()

    asyncio.run(go())


def test_async_snapshot_writes_latest_pointer():
    async def go() -> None:
        b = await _make_async_backing()
        off = await b.snapshot("tomas", _snap(0))
        kv = await b._kv_for("tomas")
        entry = await kv.get(LATEST_KEY)
        assert entry is not None
        assert int(entry.value.decode("utf-8")) == off
        await b.close()

    asyncio.run(go())


def test_async_snapshot_per_offset_key_layout():
    async def go() -> None:
        b = await _make_async_backing()
        off = await b.snapshot("tomas", _snap(0))
        kv = await b._kv_for("tomas")
        entry = await kv.get(offset_key(off))
        assert entry is not None
        assert snapshot_from_jcs_bytes(entry.value) == _snap(0)
        await b.close()

    asyncio.run(go())


def test_async_connect_idempotent_no_double_connect():
    async def go() -> None:
        connect_count = 0
        client = _StubClient()

        async def factory(_s: str, _t: float) -> _StubClient:
            nonlocal connect_count
            connect_count += 1
            return client

        async def js_factory(_c: _StubClient) -> _StubJs:
            return _c.jetstream()

        b = NatsKvPersonaStateBackingAsync(
            nats_servers="nats://stub:4222",
            org_id="acme",
            nats_client_factory=factory,
            js_factory=js_factory,
        )
        await b.connect()
        await b.connect()  # second call is a no-op.
        assert connect_count == 1
        await b.close()

    asyncio.run(go())


# -------------------- sync facade --------------------


def test_sync_facade_delegates_to_async_backing():
    """The sync NatsKvPersonaStateBacking facade must produce the
    same observable behaviour as the async binding (Sprint-Pengine-9
    closes the v0.2.0-pilot ``snapshot is deferred`` stubs)."""

    async def make_async() -> NatsKvPersonaStateBackingAsync:
        return await _make_async_backing()

    # The sync facade requires nats-py at construction (eager probe).
    # Tests that lack nats-py would skip; we inject a pre-built async
    # backing instead.
    async_backing = asyncio.run(make_async())
    sync = NatsKvPersonaStateBacking(
        nats_servers="nats://stub:4222",
        org_id="acme",
        async_backing=async_backing,
    )
    # The facade lazily ensures connection on first call; the async
    # backing is already connected so connect-call is a no-op.
    off = sync.snapshot("tomas", _snap(0))
    assert off == 1
    restored = sync.restore_latest("tomas")
    assert restored == _snap(0)
    assert sync.list_snapshots("tomas") == [1]
    sync.atomic_swap_pinned_offset(
        "tomas", from_offset=0, to_offset=off,
    )
    sync.close()


def test_sync_facade_close_idempotent():
    async_backing = asyncio.run(_make_async_backing())
    sync = NatsKvPersonaStateBacking(
        nats_servers="nats://stub:4222",
        org_id="acme",
        async_backing=async_backing,
    )
    sync.snapshot("tomas", _snap(0))
    sync.close()
    sync.close()  # no-op the second time.


def test_async_backing_raises_when_not_connected():
    async def go() -> None:
        client = _StubClient()

        async def factory(_s: str, _t: float) -> _StubClient:
            return client

        async def js_factory(_c: _StubClient) -> _StubJs:
            return _c.jetstream()

        b = NatsKvPersonaStateBackingAsync(
            nats_servers="nats://stub:4222",
            org_id="acme",
            nats_client_factory=factory,
            js_factory=js_factory,
        )
        # No connect call — _kv_for must raise PersonaStateBackingError.
        with pytest.raises(PersonaStateBackingError):
            await b._kv_for("tomas")

    asyncio.run(go())


def test_async_snapshot_uses_per_persona_lock_for_serialised_writes():
    """Two concurrent snapshot calls for the same persona must each
    allocate distinct offsets (the per-persona lock serialises CAS)."""

    async def go() -> None:
        b = await _make_async_backing()
        # Two byte-distinct snapshots — neither path can short-circuit.
        results = await asyncio.gather(
            b.snapshot("tomas", _snap(0)),
            b.snapshot("tomas", _snap(1)),
        )
        offs = sorted(results)
        assert offs == [1, 2]
        await b.close()

    asyncio.run(go())
