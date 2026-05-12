# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the Wirelang persistent marker-stack NATS-KV
backend (Sprint-8 Tag-4).

Tests the persistent tier
:mod:`wirelang.federation.marker_stack_kv` against an in-memory
mock that mirrors the Sprint-5 Tag-2 ``_MockKv`` shape with an
additional ``create`` contract for append-only semantics.

Test inventory (15 tests):

- T-MSK-01: ``put_marker_stack`` + ``get_marker_stack`` round-trip
  re-constitutes the byte-identical :class:`MarkerStack`.
- T-MSK-02: ``get_marker_stack`` on an unknown token-id returns
  ``None``.
- T-MSK-03: append-only invariant — two writers attempting the
  same sequence raise :class:`MarkerStackConcurrencyConflictError`.
- T-MSK-04: ``expected_next_sequence`` mismatch raises
  :class:`MarkerStackConcurrencyConflictError` without bucket I/O.
- T-MSK-05: cross-org boundary — Org-A backend refuses reads /
  writes / lists / watches against Org-B's ``org_id``.
- T-MSK-06: stack-context conflict — second append for a token-id
  with a different ``minted_at`` raises
  :class:`MarkerStackContextConflictError`.
- T-MSK-07: ``list_marker_stacks`` returns sorted distinct
  token-ids; ``prefix=`` filter narrows the result.
- T-MSK-08: ``watch_marker_stack`` yields events filtered to the
  requested token-id only.
- T-MSK-09: reducer-integration — a stack read from the bucket
  feeds :func:`reduce_marker_stack` to a byte-identical
  ``CompositionVerdict`` as the in-memory Tag-3 path.
- T-MSK-10: poisoned envelope raises
  :class:`MarkerStackEnvelopeError` from ``get_marker_stack``.
- T-MSK-11: per-org bucket isolation — two backends with
  separate KV handles bound to different ``org_id`` cannot see
  each other's data.
- T-MSK-12: ``reduce_persistent_marker_stack`` convenience
  matches manual ``get`` + ``reduce``.
- T-MSK-13: bucket-config constants are byte-stable
  (drift-protection at the test layer).
- T-MSK-14: key derivation is bijective for valid inputs;
  malformed inputs raise ``ValueError``.
- T-MSK-15: ``put_marker_stack`` rejects naive datetimes on
  ``appended_at`` with :class:`MarkerStackArgumentError`.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from wirelang.federation.cross_org_attenuation_verifier import (
    BridgeRevocationMarker,
)
from wirelang.federation.marker_composition import (
    BridgeRevokedEvent,
    CaveatOverrideEvent,
    CompositionState,
    EffectiveVerdict,
    ReIssuanceEvent,
    RevokeEvent,
    UnrevokeEvent,
    reduce_marker_stack,
)
from wirelang.federation.marker_stack_kv import (
    BUCKET_CONFIG,
    BUCKET_NAME_PREFIX,
    VALUE_SCHEMA,
    MarkerStackArgumentError,
    MarkerStackConcurrencyConflictError,
    MarkerStackContextConflictError,
    MarkerStackCrossOrgBoundaryError,
    MarkerStackEnvelopeError,
    MarkerStackVersion,
    MarkerStackWatchEvent,
    NatsKvMarkerStackBackend,
    StackContext,
    bucket_name_for_org,
    key_for_event,
    parse_event_key,
    reduce_persistent_marker_stack,
)


# ---------------------------------------------------------------------------
# Mock KV (mirrors Sprint-5 Tag-2 shape; adds ``create`` contract)
# ---------------------------------------------------------------------------


class _MockBucketKeyExistsError(Exception):
    """Mirrors nats-py's ``KeyAlreadyExistsError`` class-name pattern."""


class _MockBucketNotFoundError(Exception):
    """Mirrors nats-py's ``KeyNotFoundError`` class-name pattern."""


@dataclass
class _MockKvEntry:
    value: bytes
    revision: int = 0
    operation: str = "PUT"
    key: str = ""


@dataclass
class _MockWatcher:
    """Mock watcher pushing updates to subscribers.

    Two-shape implementation (``__anext__`` + ``updates()`` both
    backed by the same internal queue) so the test surface
    covers both nats-py adapter shapes.
    """

    queue: "asyncio.Queue[Any]" = field(default_factory=asyncio.Queue)
    _stopped: bool = False

    async def __anext__(self) -> Any:
        if self._stopped:
            raise StopAsyncIteration
        item = await self.queue.get()
        if item is None and self._stopped:
            raise StopAsyncIteration
        return item

    async def updates(self) -> Any:
        if self._stopped:
            return None
        return await self.queue.get()

    def stop(self) -> None:
        self._stopped = True


@dataclass
class _MockKv:
    bucket: str = ""
    store: Dict[str, _MockKvEntry] = field(default_factory=dict)
    revision: int = 0
    watchers: List[_MockWatcher] = field(default_factory=list)

    async def get(self, key: str) -> _MockKvEntry:
        if key not in self.store:
            raise _MockBucketNotFoundError(f"key not found: {key}")
        entry = self.store[key]
        # Surface the key on the returned entry so callers that
        # introspect it (the watch decoder) see a real value.
        return _MockKvEntry(
            value=entry.value,
            revision=entry.revision,
            operation=entry.operation,
            key=key,
        )

    async def put(self, key: str, value: bytes) -> int:
        self.revision += 1
        self.store[key] = _MockKvEntry(
            value=bytes(value), revision=self.revision, key=key
        )
        for w in self.watchers:
            await w.queue.put(self.store[key])
        return self.revision

    async def create(self, key: str, value: bytes) -> int:
        if key in self.store:
            raise _MockBucketKeyExistsError(f"key already exists: {key}")
        return await self.put(key, value)

    async def keys(self) -> List[str]:
        return list(self.store.keys())

    async def watchall(self) -> _MockWatcher:
        w = _MockWatcher()
        # nats-py watchall() replays the bucket's current state to
        # the watcher before the live tail; mirror that contract.
        for key in sorted(self.store.keys()):
            entry = self.store[key]
            await w.queue.put(
                _MockKvEntry(
                    value=entry.value,
                    revision=entry.revision,
                    operation="PUT",
                    key=key,
                )
            )
        self.watchers.append(w)
        return w


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_T0 = datetime(2026, 5, 13, 9, 0, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 5, 13, 10, 0, 0, tzinfo=timezone.utc)
_T2 = datetime(2026, 5, 13, 11, 0, 0, tzinfo=timezone.utc)
_T3 = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)


def _make_backend(org_id: str = "org-a", kv: Optional[_MockKv] = None) -> NatsKvMarkerStackBackend:
    if kv is None:
        kv = _MockKv(bucket=bucket_name_for_org(org_id))
    return NatsKvMarkerStackBackend(kv=kv, org_id=org_id)


def _ctx() -> StackContext:
    return StackContext(minted_at=_T0, original_caveat_set=None)


def _ctx_with_caveat() -> StackContext:
    return StackContext(
        minted_at=_T0,
        original_caveat_set=(("delegated_to", ("verifier-A",)),),
    )


# ---------------------------------------------------------------------------
# T-MSK-01: put + get round-trip
# ---------------------------------------------------------------------------


def test_t_msk_01_put_get_roundtrip():
    backend = _make_backend()
    ctx = _ctx()
    rev1 = RevokeEvent(event_at=_T1, revocation_reason="compromise", tie_break=0)
    unrev = UnrevokeEvent(
        event_at=_T2,
        previous_revoked_at=_T1,
        unrevoke_reason="false-positive",
        tie_break=0,
    )

    async def run():
        v1 = await backend.put_marker_stack(
            org_id="org-a",
            capability_token_id="tok-1",
            marker_event=rev1,
            stack_context=ctx,
            appended_at=_T1,
        )
        v2 = await backend.put_marker_stack(
            org_id="org-a",
            capability_token_id="tok-1",
            marker_event=unrev,
            stack_context=ctx,
            appended_at=_T2,
        )
        stack = await backend.get_marker_stack(
            org_id="org-a", capability_token_id="tok-1"
        )
        return v1, v2, stack

    v1, v2, stack = asyncio.run(run())
    assert isinstance(v1, MarkerStackVersion)
    assert v1.sequence == 1
    assert v2.sequence == 2
    assert stack is not None
    assert stack.token_id == "tok-1"
    assert stack.minted_at == _T0
    assert len(stack.events) == 2
    assert stack.events[0] == rev1
    assert stack.events[1] == unrev


# ---------------------------------------------------------------------------
# T-MSK-02: get on unknown token-id returns None
# ---------------------------------------------------------------------------


def test_t_msk_02_get_unknown_returns_none():
    backend = _make_backend()

    async def run():
        return await backend.get_marker_stack(
            org_id="org-a", capability_token_id="never-issued"
        )

    assert asyncio.run(run()) is None


# ---------------------------------------------------------------------------
# T-MSK-03: append-only invariant (two writers at same sequence)
# ---------------------------------------------------------------------------


def test_t_msk_03_concurrent_create_conflict():
    kv = _MockKv()
    backend = _make_backend(kv=kv)
    ctx = _ctx()
    rev = RevokeEvent(event_at=_T1, tie_break=0)

    async def run():
        # First writer lands sequence 1.
        await backend.put_marker_stack(
            org_id="org-a",
            capability_token_id="tok-1",
            marker_event=rev,
            stack_context=ctx,
            appended_at=_T1,
        )
        # Bypass the backend's pre-read by writing the same KV
        # key directly so the second writer's create() hits a
        # populated slot. This simulates a racing writer that
        # appended after our pre-read but before our create.
        # We simulate by re-using the backend with an
        # expected_next_sequence locked to 2 but inject an extra
        # event at sequence 2 first.
        rev2 = RevokeEvent(event_at=_T2, tie_break=0)
        # Drop a manual envelope at sequence 2 via direct kv write
        # to simulate the race.
        await backend.put_marker_stack(
            org_id="org-a",
            capability_token_id="tok-1",
            marker_event=rev2,
            stack_context=ctx,
            appended_at=_T2,
        )
        # Now try to append at sequence 2 again via direct create
        # (skipping the pre-read pathway) — must fail with conflict.
        from wirelang.federation.marker_stack_kv import (
            _encode_envelope,
            _kv_create,
            key_for_event,
        )
        blob = _encode_envelope(
            org_id="org-a",
            capability_token_id="tok-1",
            sequence=2,
            event=rev2,
            stack_context=ctx,
            appended_at=_T2,
        )
        await _kv_create(kv, key_for_event("tok-1", 2), blob)

    with pytest.raises(MarkerStackConcurrencyConflictError) as exc_info:
        asyncio.run(run())
    assert "already exists" in str(exc_info.value)


# ---------------------------------------------------------------------------
# T-MSK-04: expected_next_sequence mismatch
# ---------------------------------------------------------------------------


def test_t_msk_04_expected_next_sequence_mismatch():
    backend = _make_backend()
    ctx = _ctx()
    rev = RevokeEvent(event_at=_T1, tie_break=0)

    async def run():
        # First append claims sequence=1 explicitly; succeeds.
        await backend.put_marker_stack(
            org_id="org-a",
            capability_token_id="tok-1",
            marker_event=rev,
            stack_context=ctx,
            appended_at=_T1,
            expected_next_sequence=1,
        )
        # Second append claims sequence=5 but the computed next
        # is 2; mismatch must raise.
        await backend.put_marker_stack(
            org_id="org-a",
            capability_token_id="tok-1",
            marker_event=RevokeEvent(event_at=_T2),
            stack_context=ctx,
            appended_at=_T2,
            expected_next_sequence=5,
        )

    with pytest.raises(MarkerStackConcurrencyConflictError) as exc_info:
        asyncio.run(run())
    assert exc_info.value.expected_sequence == 5
    assert exc_info.value.observed_max_sequence == 1


# ---------------------------------------------------------------------------
# T-MSK-05: cross-org boundary enforcement
# ---------------------------------------------------------------------------


def test_t_msk_05_cross_org_boundary_enforcement():
    backend = _make_backend(org_id="org-a")
    ctx = _ctx()
    rev = RevokeEvent(event_at=_T1)

    async def put_wrong_org():
        await backend.put_marker_stack(
            org_id="org-b",
            capability_token_id="tok-1",
            marker_event=rev,
            stack_context=ctx,
            appended_at=_T1,
        )

    async def get_wrong_org():
        await backend.get_marker_stack(
            org_id="org-b", capability_token_id="tok-1"
        )

    async def list_wrong_org():
        await backend.list_marker_stacks(org_id="org-b")

    async def watch_wrong_org():
        await backend.watch_marker_stack(
            org_id="org-b", capability_token_id="tok-1"
        )

    for coro_fn in (put_wrong_org, get_wrong_org, list_wrong_org, watch_wrong_org):
        with pytest.raises(MarkerStackCrossOrgBoundaryError) as exc_info:
            asyncio.run(coro_fn())
        assert exc_info.value.backend_org_id == "org-a"
        assert exc_info.value.requested_org_id == "org-b"


# ---------------------------------------------------------------------------
# T-MSK-06: stack-context conflict
# ---------------------------------------------------------------------------


def test_t_msk_06_stack_context_conflict():
    backend = _make_backend()
    ctx1 = _ctx()
    ctx2 = StackContext(minted_at=_T1, original_caveat_set=None)  # different mint
    rev = RevokeEvent(event_at=_T1)

    async def run():
        await backend.put_marker_stack(
            org_id="org-a",
            capability_token_id="tok-1",
            marker_event=rev,
            stack_context=ctx1,
            appended_at=_T1,
        )
        # Second append with a different minted_at: rejected pre-write.
        await backend.put_marker_stack(
            org_id="org-a",
            capability_token_id="tok-1",
            marker_event=RevokeEvent(event_at=_T2),
            stack_context=ctx2,
            appended_at=_T2,
        )

    with pytest.raises(MarkerStackContextConflictError) as exc_info:
        asyncio.run(run())
    assert "tok-1" in str(exc_info.value)


# ---------------------------------------------------------------------------
# T-MSK-07: list_marker_stacks + prefix filter
# ---------------------------------------------------------------------------


def test_t_msk_07_list_marker_stacks_with_prefix():
    backend = _make_backend()
    ctx = _ctx()

    async def run():
        for token_id in ("alpha-1", "alpha-2", "beta-1"):
            await backend.put_marker_stack(
                org_id="org-a",
                capability_token_id=token_id,
                marker_event=RevokeEvent(event_at=_T1),
                stack_context=ctx,
                appended_at=_T1,
            )
        all_ids = await backend.list_marker_stacks(org_id="org-a")
        alpha_ids = await backend.list_marker_stacks(
            org_id="org-a", prefix="alpha-"
        )
        return all_ids, alpha_ids

    all_ids, alpha_ids = asyncio.run(run())
    assert all_ids == ["alpha-1", "alpha-2", "beta-1"]
    assert alpha_ids == ["alpha-1", "alpha-2"]


# ---------------------------------------------------------------------------
# T-MSK-08: watch filter pre token-id
# ---------------------------------------------------------------------------


def test_t_msk_08_watch_stream_filters_by_token_id():
    backend = _make_backend()
    ctx = _ctx()

    async def run():
        # Pre-populate two tokens so the initial replay carries
        # both. The filter MUST drop the foreign token's event.
        await backend.put_marker_stack(
            org_id="org-a",
            capability_token_id="tok-target",
            marker_event=RevokeEvent(event_at=_T1, revocation_reason="A"),
            stack_context=ctx,
            appended_at=_T1,
        )
        await backend.put_marker_stack(
            org_id="org-a",
            capability_token_id="tok-other",
            marker_event=RevokeEvent(event_at=_T1, revocation_reason="B"),
            stack_context=ctx,
            appended_at=_T1,
        )
        # Open the watcher — it now contains both pre-existing
        # entries (the mock pushes them as the put() side-effect).
        # Drain three updates from the queue, accepting only the
        # tok-target one.
        watcher = await backend.watch_marker_stack(
            org_id="org-a", capability_token_id="tok-target"
        )
        # Drain via __anext__ until the queue is empty; we expect
        # one match.
        matches: List[MarkerStackWatchEvent] = []
        try:
            # Read with a timeout so the test never hangs.
            for _ in range(3):
                ev = await asyncio.wait_for(watcher.__anext__(), timeout=0.5)
                matches.append(ev)
        except asyncio.TimeoutError:
            pass
        return matches

    matches = asyncio.run(run())
    assert len(matches) == 1
    assert matches[0].capability_token_id == "tok-target"
    assert matches[0].record.event.revocation_reason == "A"


# ---------------------------------------------------------------------------
# T-MSK-09: reducer integration — byte-identical verdict
# ---------------------------------------------------------------------------


def test_t_msk_09_reducer_integration_byte_identical():
    backend = _make_backend()
    ctx = _ctx_with_caveat()
    rev = RevokeEvent(event_at=_T1, revocation_reason="r1", tie_break=0)
    unrev = UnrevokeEvent(
        event_at=_T2,
        previous_revoked_at=_T1,
        unrevoke_reason="u1",
        tie_break=0,
    )

    async def run():
        await backend.put_marker_stack(
            org_id="org-a",
            capability_token_id="tok-1",
            marker_event=rev,
            stack_context=ctx,
            appended_at=_T1,
        )
        await backend.put_marker_stack(
            org_id="org-a",
            capability_token_id="tok-1",
            marker_event=unrev,
            stack_context=ctx,
            appended_at=_T2,
        )
        stack = await backend.get_marker_stack(
            org_id="org-a", capability_token_id="tok-1"
        )
        return stack

    stack = asyncio.run(run())
    assert stack is not None
    persistent_verdict = reduce_marker_stack(stack)

    from wirelang.federation.marker_composition import MarkerStack
    in_memory_stack = MarkerStack(
        token_id="tok-1",
        minted_at=ctx.minted_at,
        original_caveat_set=ctx.original_caveat_set,
        events=(rev, unrev),
    )
    in_memory_verdict = reduce_marker_stack(in_memory_stack)
    assert persistent_verdict == in_memory_verdict
    assert persistent_verdict.state == CompositionState.ACTIVE
    assert persistent_verdict.effective == EffectiveVerdict.ACTIVE


# ---------------------------------------------------------------------------
# T-MSK-10: poisoned envelope
# ---------------------------------------------------------------------------


def test_t_msk_10_poisoned_envelope_raises():
    kv = _MockKv()
    backend = _make_backend(kv=kv)
    # Inject a malformed envelope directly.
    asyncio.run(
        kv.put(
            "marker-events/tok-x/000000000001",
            b"not-json-at-all",
        )
    )

    async def run():
        return await backend.get_marker_stack(
            org_id="org-a", capability_token_id="tok-x"
        )

    with pytest.raises(MarkerStackEnvelopeError):
        asyncio.run(run())


# ---------------------------------------------------------------------------
# T-MSK-11: per-org bucket isolation
# ---------------------------------------------------------------------------


def test_t_msk_11_per_org_bucket_isolation():
    kv_a = _MockKv(bucket=bucket_name_for_org("org-a"))
    kv_b = _MockKv(bucket=bucket_name_for_org("org-b"))
    backend_a = NatsKvMarkerStackBackend(kv=kv_a, org_id="org-a")
    backend_b = NatsKvMarkerStackBackend(kv=kv_b, org_id="org-b")
    ctx = _ctx()

    async def run():
        # Org-A appends a unique event.
        await backend_a.put_marker_stack(
            org_id="org-a",
            capability_token_id="tok-A",
            marker_event=RevokeEvent(event_at=_T1, revocation_reason="A"),
            stack_context=ctx,
            appended_at=_T1,
        )
        # Org-B independently has a different token.
        await backend_b.put_marker_stack(
            org_id="org-b",
            capability_token_id="tok-B",
            marker_event=RevokeEvent(event_at=_T1, revocation_reason="B"),
            stack_context=ctx,
            appended_at=_T1,
        )
        a_ids = await backend_a.list_marker_stacks(org_id="org-a")
        b_ids = await backend_b.list_marker_stacks(org_id="org-b")
        return a_ids, b_ids

    a_ids, b_ids = asyncio.run(run())
    assert a_ids == ["tok-A"]
    assert b_ids == ["tok-B"]
    assert backend_a.bucket_name == "wakir-marker-stack-org-a"
    assert backend_b.bucket_name == "wakir-marker-stack-org-b"


# ---------------------------------------------------------------------------
# T-MSK-12: reduce_persistent_marker_stack convenience
# ---------------------------------------------------------------------------


def test_t_msk_12_reduce_persistent_convenience_matches_manual():
    backend = _make_backend()
    ctx = _ctx()
    bridge_marker = BridgeRevocationMarker(
        source_ftd_id="ftd:org-a",
        target_ftd_id="ftd:org-c",
        revoked_at=_T0,  # before mint
    )
    bridge_event = BridgeRevokedEvent(marker=bridge_marker, tie_break=0)

    async def run():
        await backend.put_marker_stack(
            org_id="org-a",
            capability_token_id="tok-bridge",
            marker_event=bridge_event,
            stack_context=ctx,
            appended_at=_T1,
        )
        # Convenience.
        verdict = await reduce_persistent_marker_stack(
            backend, org_id="org-a", capability_token_id="tok-bridge"
        )
        # Manual.
        stack = await backend.get_marker_stack(
            org_id="org-a", capability_token_id="tok-bridge"
        )
        manual_verdict = reduce_marker_stack(stack)
        return verdict, manual_verdict

    verdict, manual_verdict = asyncio.run(run())
    assert verdict is not None
    assert verdict == manual_verdict
    # Bridge was revoked before mint, lifecycle still ACTIVE,
    # effective verdict is BRIDGE_BLOCKED.
    assert verdict.state == CompositionState.ACTIVE
    assert verdict.bridge_blocked is True
    assert verdict.effective == EffectiveVerdict.BRIDGE_BLOCKED


# ---------------------------------------------------------------------------
# T-MSK-13: bucket-config constants stable
# ---------------------------------------------------------------------------


def test_t_msk_13_bucket_config_constants_stable():
    assert BUCKET_NAME_PREFIX == "wakir-marker-stack-"
    assert VALUE_SCHEMA == "wakir.wirelang.marker-stack-event/1"
    # BUCKET_CONFIG carries the operator-managed bucket shape.
    assert BUCKET_CONFIG["history"] == 1
    assert BUCKET_CONFIG["ttl_seconds"] == 0
    assert BUCKET_CONFIG["max_value_size"] == 32_768
    assert BUCKET_CONFIG["storage"] == "file"
    assert BUCKET_CONFIG["replicas"] == 1


# ---------------------------------------------------------------------------
# T-MSK-14: key derivation bijection
# ---------------------------------------------------------------------------


def test_t_msk_14_key_derivation_bijection():
    # Valid round-trip.
    key = key_for_event("tok-1", 42)
    assert key == "marker-events/tok-1/000000000042"
    assert parse_event_key(key) == ("tok-1", 42)

    # Negative cases.
    with pytest.raises(ValueError):
        key_for_event("", 1)
    with pytest.raises(ValueError):
        key_for_event("tok-1", 0)
    with pytest.raises(ValueError):
        key_for_event("tok with space", 1)
    with pytest.raises(ValueError):
        parse_event_key("foreign-shape/tok-1/1")
    with pytest.raises(ValueError):
        parse_event_key("marker-events/only-one-segment")
    with pytest.raises(ValueError):
        parse_event_key("marker-events/tok-1/not-an-int")

    # bucket_name round-trip.
    assert bucket_name_for_org("org-a") == "wakir-marker-stack-org-a"
    from wirelang.federation.marker_stack_kv import org_id_for_bucket_name
    assert org_id_for_bucket_name("wakir-marker-stack-org-a") == "org-a"
    with pytest.raises(ValueError):
        bucket_name_for_org("")
    with pytest.raises(ValueError):
        bucket_name_for_org("has space")
    with pytest.raises(ValueError):
        org_id_for_bucket_name("not-the-prefix")


# ---------------------------------------------------------------------------
# T-MSK-15: naive datetime rejected on appended_at
# ---------------------------------------------------------------------------


def test_t_msk_15_naive_appended_at_rejected():
    backend = _make_backend()
    ctx = _ctx()
    naive_dt = datetime(2026, 5, 13, 10, 0, 0)  # no tzinfo

    async def run():
        await backend.put_marker_stack(
            org_id="org-a",
            capability_token_id="tok-1",
            marker_event=RevokeEvent(event_at=_T1),
            stack_context=ctx,
            appended_at=naive_dt,
        )

    with pytest.raises(MarkerStackArgumentError) as exc_info:
        asyncio.run(run())
    assert "timezone-aware" in str(exc_info.value)
