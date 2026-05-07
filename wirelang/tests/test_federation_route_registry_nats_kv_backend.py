# SPDX-License-Identifier: Apache-2.0
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
    NatsKvRouteRegistry,
    RouteRegistryEnvelopeError,
    VALUE_SCHEMA,
    _entry_to_envelope,
    _envelope_to_entry,
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
class _MockKv:
    """In-memory replacement for nats-py's ``KeyValue`` handle.

    The async surface mirrors what
    :class:`NatsKvRouteRegistry` calls into:
    ``await kv.get(key)``, ``await kv.put(key, value)``,
    ``await kv.delete(key)``, ``await kv.keys()``.
    """

    bucket: str = BUCKET_NAME
    store: dict = field(default_factory=dict)
    revision: int = 0

    async def get(self, key: str) -> _MockKvEntry:
        if key not in self.store:
            raise _MockBucketNotFoundError(f"key not found: {key}")
        return self.store[key]

    async def put(self, key: str, value: bytes) -> int:
        self.revision += 1
        self.store[key] = _MockKvEntry(value=bytes(value), revision=self.revision)
        return self.revision

    async def delete(self, key: str) -> None:
        if key not in self.store:
            raise _MockBucketNotFoundError(f"key not found: {key}")
        del self.store[key]

    async def keys(self) -> list:
        return list(self.store.keys())


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
