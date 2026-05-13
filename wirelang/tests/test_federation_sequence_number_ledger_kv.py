# SPDX-License-Identifier: BUSL-1.1
"""Hermetic tests for the durable NATS-KV-backed
``SequenceNumberLedger`` (Phase-2 Sprint-9 Tag-2).

Tests :mod:`wirelang.federation.sequence_number_ledger_kv` against
an in-memory mock that mirrors the Sprint-8 Tag-4
:class:`_MockKv` shape with an ``update`` CAS-pin extension.

Test inventory (13 tests):

- T-SNLK-01: round-trip — first record_export creates the cell;
  a_last_seen returns the recorded sequence.
- T-SNLK-02: a_last_seen on an unknown pair returns ``0``;
  a_next_sequence returns ``1``.
- T-SNLK-03: monotonic-invariant — recording 1, then 2, then 5
  succeeds; a_last_seen reports 5.
- T-SNLK-04: replay-detection — recording an equal-or-less
  sequence raises :class:`CaveatOverrideExportReplayError` and
  the cell remains at the prior value.
- T-SNLK-05: concurrency-conflict — two concurrent updates at the
  same expected revision yield exactly one
  :class:`SequenceNumberLedgerConcurrencyConflictError`.
- T-SNLK-06: cross-org boundary — Org-A ledger refuses
  ``requested_org_id="org-b"`` on all three async surfaces.
- T-SNLK-07: durability-after-restart — a second ledger pointed
  at the same KV handle observes the cell state without any
  cross-instance shared memory.
- T-SNLK-08: per-org bucket isolation — two ledgers bound to
  different ``org_id`` and different KV handles cannot see each
  other's cells.
- T-SNLK-09: poisoned envelope — a malformed JSON value raises
  :class:`SequenceNumberLedgerEnvelopeError` from a_last_seen.
- T-SNLK-10: foreign-org-id envelope — a cell whose payload
  carries an ``org_id`` different from the bucket's binding
  raises :class:`SequenceNumberLedgerEnvelopeError`.
- T-SNLK-11: bucket-config / schema constants are byte-stable
  (drift-protection at the test layer).
- T-SNLK-12: key derivation is bijective for valid inputs;
  malformed inputs raise ``ValueError``.
- T-SNLK-13: SyncSequenceNumberLedgerAdapter implements the
  Tag-1 :class:`SequenceNumberLedger` Protocol shape (the three
  methods round-trip end-to-end against the durable backend).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pytest

from wirelang.federation.caveat_override_export import (
    CaveatOverrideExportReplayError,
    CaveatOverrideExportShapeError,
)
from wirelang.federation.sequence_number_ledger_kv import (
    BUCKET_CONFIG,
    BUCKET_NAME_PREFIX,
    VALUE_SCHEMA,
    NatsKvSequenceNumberLedger,
    SequenceNumberLedgerConcurrencyConflictError,
    SequenceNumberLedgerCrossOrgBoundaryError,
    SequenceNumberLedgerEnvelopeError,
    SyncSequenceNumberLedgerAdapter,
    bucket_name_for_org,
    key_for_pair,
    org_id_for_bucket_name,
    parse_pair_key,
)


# ---------------------------------------------------------------------------
# Mock KV (mirrors Sprint-8 Tag-4 _MockKv shape; adds ``update`` CAS-pin)
# ---------------------------------------------------------------------------


class _MockKvKeyExistsError(Exception):
    """Mirrors nats-py's ``KeyAlreadyExistsError`` class-name pattern."""


class _MockKvKeyNotFoundError(Exception):
    """Mirrors nats-py's ``KeyNotFoundError`` class-name pattern."""


class _MockKvWrongLastSequenceError(Exception):
    """Mirrors nats-py's ``WrongLastSequenceError`` class-name pattern."""


@dataclass
class _MockKvEntry:
    value: bytes
    revision: int = 0


@dataclass
class _MockKv:
    bucket: str = ""
    store: Dict[str, _MockKvEntry] = field(default_factory=dict)
    revision: int = 0

    async def get(self, key: str) -> _MockKvEntry:
        if key not in self.store:
            raise _MockKvKeyNotFoundError(f"key not found: {key}")
        entry = self.store[key]
        return _MockKvEntry(value=entry.value, revision=entry.revision)

    async def create(self, key: str, value: bytes) -> int:
        if key in self.store:
            raise _MockKvKeyExistsError(f"key already exists: {key}")
        self.revision += 1
        self.store[key] = _MockKvEntry(
            value=bytes(value), revision=self.revision
        )
        return self.revision

    async def update(
        self, key: str, value: bytes, *, last: int
    ) -> int:
        if key not in self.store:
            raise _MockKvKeyNotFoundError(f"key not found: {key}")
        existing = self.store[key]
        if existing.revision != last:
            raise _MockKvWrongLastSequenceError(
                f"CAS-pin mismatch: expected revision={last} but "
                f"observed revision={existing.revision} on key {key!r}"
            )
        self.revision += 1
        self.store[key] = _MockKvEntry(
            value=bytes(value), revision=self.revision
        )
        return self.revision


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_T0 = datetime(2026, 5, 13, 9, 0, 0, tzinfo=timezone.utc)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _make_ledger(org_id: str = "org-a") -> NatsKvSequenceNumberLedger:
    return NatsKvSequenceNumberLedger(kv=_MockKv(), org_id=org_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_snlk_01_round_trip_first_record_creates_cell() -> None:
    """T-SNLK-01: first record_export creates the cell; a_last_seen
    returns the recorded sequence.
    """
    ledger = _make_ledger()
    # Pre-state: no cell.
    pre = _run(
        ledger.a_last_seen(
            route_id="route-x", chain_hash="hash-1"
        )
    )
    assert pre == 0
    # Record.
    revision = _run(
        ledger.a_record_export(
            route_id="route-x",
            chain_hash="hash-1",
            sequence=1,
            recorded_at=_T0,
        )
    )
    assert revision == 1
    # Post-state.
    post = _run(
        ledger.a_last_seen(
            route_id="route-x", chain_hash="hash-1"
        )
    )
    assert post == 1


def test_snlk_02_last_seen_unknown_pair_returns_zero() -> None:
    """T-SNLK-02: a_last_seen on an unknown pair returns 0;
    a_next_sequence returns 1.
    """
    ledger = _make_ledger()
    last = _run(
        ledger.a_last_seen(
            route_id="route-unseen", chain_hash="hash-unseen"
        )
    )
    assert last == 0
    nxt = _run(
        ledger.a_next_sequence(
            route_id="route-unseen", chain_hash="hash-unseen"
        )
    )
    assert nxt == 1


def test_snlk_03_monotonic_invariant_sequences_advance() -> None:
    """T-SNLK-03: recording 1, then 2, then 5 (gap allowed)
    advances last_seen monotonically.
    """
    ledger = _make_ledger()
    for seq in (1, 2, 5):
        _run(
            ledger.a_record_export(
                route_id="route-mono",
                chain_hash="hash-mono",
                sequence=seq,
                recorded_at=_T0,
            )
        )
    last = _run(
        ledger.a_last_seen(
            route_id="route-mono", chain_hash="hash-mono"
        )
    )
    assert last == 5
    # next_sequence past the gap is last_seen + 1 = 6.
    nxt = _run(
        ledger.a_next_sequence(
            route_id="route-mono", chain_hash="hash-mono"
        )
    )
    assert nxt == 6


def test_snlk_04_replay_at_same_sequence_rejected() -> None:
    """T-SNLK-04: recording an equal-or-less sequence raises
    :class:`CaveatOverrideExportReplayError` and the cell remains
    at the prior value.
    """
    ledger = _make_ledger()
    _run(
        ledger.a_record_export(
            route_id="route-r",
            chain_hash="hash-r",
            sequence=3,
            recorded_at=_T0,
        )
    )
    # Same sequence — must reject.
    with pytest.raises(CaveatOverrideExportReplayError) as exc_info:
        _run(
            ledger.a_record_export(
                route_id="route-r",
                chain_hash="hash-r",
                sequence=3,
                recorded_at=_T0,
            )
        )
    assert exc_info.value.last_seen_sequence == 3
    assert exc_info.value.attempted_sequence == 3
    # Less-than — must reject.
    with pytest.raises(CaveatOverrideExportReplayError):
        _run(
            ledger.a_record_export(
                route_id="route-r",
                chain_hash="hash-r",
                sequence=2,
                recorded_at=_T0,
            )
        )
    # Cell unchanged.
    last = _run(
        ledger.a_last_seen(
            route_id="route-r", chain_hash="hash-r"
        )
    )
    assert last == 3


def test_snlk_05_concurrency_conflict_one_winner() -> None:
    """T-SNLK-05: two concurrent updates at the same expected
    revision yield exactly one
    :class:`SequenceNumberLedgerConcurrencyConflictError`.

    Constructs two ledger instances pointed at the same underlying
    KV. Both read the cell, both compute next_sequence, both call
    record_export. Mock CAS-pin admits exactly one.
    """
    kv = _MockKv()
    ledger_a = NatsKvSequenceNumberLedger(kv=kv, org_id="org-a")
    ledger_b = NatsKvSequenceNumberLedger(kv=kv, org_id="org-a")
    # Seed cell at sequence=1 so both updates collide on update
    # (not create).
    _run(
        ledger_a.a_record_export(
            route_id="route-cc",
            chain_hash="hash-cc",
            sequence=1,
            recorded_at=_T0,
        )
    )
    # Both ledger instances read in interleaved order. We simulate
    # the conflict by having ledger_a read+update first (succeeds),
    # then ledger_b update with the *stale* read (must conflict).
    # The simplest deterministic reproduction is to read the cell
    # snapshot, then race the writes.
    snapshot_a = _run(
        ledger_a._read_cell(
            route_id="route-cc", chain_hash="hash-cc"
        )
    )
    snapshot_b = _run(
        ledger_b._read_cell(
            route_id="route-cc", chain_hash="hash-cc"
        )
    )
    assert snapshot_a is not None
    assert snapshot_b is not None
    assert snapshot_a.revision == snapshot_b.revision
    # ledger_a writes sequence=2 successfully.
    _run(
        ledger_a.a_record_export(
            route_id="route-cc",
            chain_hash="hash-cc",
            sequence=2,
            recorded_at=_T0,
        )
    )
    # ledger_b would have computed sequence=2 from the same stale
    # snapshot — but the cell has moved on. Internal _read_cell
    # now returns the fresh revision and would block the replay
    # at the replay-gate; force the CAS-conflict by reaching
    # directly into _kv_update with the stale revision.
    from wirelang.federation.sequence_number_ledger_kv import (
        _kv_update,
        _encode_envelope,
    )
    stale_blob = _encode_envelope(
        org_id="org-a",
        route_id="route-cc",
        chain_hash="hash-cc",
        last_seen_sequence=2,
        recorded_at=_T0,
    )
    with pytest.raises(SequenceNumberLedgerConcurrencyConflictError) as exc_info:
        _run(
            _kv_update(
                kv,
                key_for_pair("route-cc", "hash-cc"),
                stale_blob,
                last_revision=snapshot_b.revision,
            )
        )
    assert exc_info.value.expected_revision == snapshot_b.revision


def test_snlk_06_cross_org_boundary_refuses() -> None:
    """T-SNLK-06: Org-A ledger refuses ``requested_org_id="org-b"``
    on all three async surfaces.
    """
    ledger = _make_ledger("org-a")
    for caller in (
        lambda: ledger.a_last_seen(
            route_id="route-x",
            chain_hash="hash-1",
            requested_org_id="org-b",
        ),
        lambda: ledger.a_next_sequence(
            route_id="route-x",
            chain_hash="hash-1",
            requested_org_id="org-b",
        ),
        lambda: ledger.a_record_export(
            route_id="route-x",
            chain_hash="hash-1",
            sequence=1,
            recorded_at=_T0,
            requested_org_id="org-b",
        ),
    ):
        with pytest.raises(
            SequenceNumberLedgerCrossOrgBoundaryError
        ) as exc_info:
            _run(caller())
        assert exc_info.value.backend_org_id == "org-a"
        assert exc_info.value.requested_org_id == "org-b"


def test_snlk_07_durability_after_restart() -> None:
    """T-SNLK-07: a second ledger pointed at the same KV handle
    observes the cell state without any cross-instance shared
    memory — the durability tier is the bucket, not the wrapper.
    """
    kv = _MockKv()
    ledger_v1 = NatsKvSequenceNumberLedger(kv=kv, org_id="org-a")
    _run(
        ledger_v1.a_record_export(
            route_id="route-restart",
            chain_hash="hash-restart",
            sequence=7,
            recorded_at=_T0,
        )
    )
    # "Restart" — a fresh ledger instance reads the same bucket.
    ledger_v2 = NatsKvSequenceNumberLedger(kv=kv, org_id="org-a")
    last = _run(
        ledger_v2.a_last_seen(
            route_id="route-restart", chain_hash="hash-restart"
        )
    )
    assert last == 7
    # Recording 8 must succeed (monotonic).
    _run(
        ledger_v2.a_record_export(
            route_id="route-restart",
            chain_hash="hash-restart",
            sequence=8,
            recorded_at=_T0,
        )
    )
    # And 7 again must replay-fail.
    with pytest.raises(CaveatOverrideExportReplayError):
        _run(
            ledger_v2.a_record_export(
                route_id="route-restart",
                chain_hash="hash-restart",
                sequence=7,
                recorded_at=_T0,
            )
        )


def test_snlk_08_per_org_bucket_isolation() -> None:
    """T-SNLK-08: two ledgers bound to different ``org_id`` and
    different KV handles cannot see each other's cells (the
    isolation is per-bucket).
    """
    kv_a = _MockKv()
    kv_b = _MockKv()
    ledger_a = NatsKvSequenceNumberLedger(kv=kv_a, org_id="org-a")
    ledger_b = NatsKvSequenceNumberLedger(kv=kv_b, org_id="org-b")
    _run(
        ledger_a.a_record_export(
            route_id="route-shared",
            chain_hash="hash-shared",
            sequence=4,
            recorded_at=_T0,
        )
    )
    # Org-B's ledger sees a fresh cell.
    last_b = _run(
        ledger_b.a_last_seen(
            route_id="route-shared", chain_hash="hash-shared"
        )
    )
    assert last_b == 0
    # Org-B can record sequence=1 against its own bucket without
    # collision.
    _run(
        ledger_b.a_record_export(
            route_id="route-shared",
            chain_hash="hash-shared",
            sequence=1,
            recorded_at=_T0,
        )
    )
    # Org-A is unaffected.
    last_a = _run(
        ledger_a.a_last_seen(
            route_id="route-shared", chain_hash="hash-shared"
        )
    )
    assert last_a == 4


def test_snlk_09_poisoned_envelope_surfaces_typed_error() -> None:
    """T-SNLK-09: a malformed JSON value raises
    :class:`SequenceNumberLedgerEnvelopeError` from a_last_seen.
    """
    kv = _MockKv()
    ledger = NatsKvSequenceNumberLedger(kv=kv, org_id="org-a")
    # Inject a poisoned cell directly into the mock.
    kv.store[key_for_pair("route-p", "hash-p")] = _MockKvEntry(
        value=b"this-is-not-json", revision=1
    )
    with pytest.raises(SequenceNumberLedgerEnvelopeError):
        _run(
            ledger.a_last_seen(
                route_id="route-p", chain_hash="hash-p"
            )
        )


def test_snlk_10_foreign_org_id_envelope_surfaces_typed_error() -> None:
    """T-SNLK-10: a cell whose payload carries an ``org_id``
    different from the bucket's binding raises
    :class:`SequenceNumberLedgerEnvelopeError`.
    """
    kv = _MockKv()
    ledger_a = NatsKvSequenceNumberLedger(kv=kv, org_id="org-a")
    # Inject a cell whose payload claims to be from org-b.
    foreign_blob = json.dumps(
        {
            "schema": VALUE_SCHEMA,
            "org_id": "org-b",
            "route_id": "route-f",
            "chain_hash": "hash-f",
            "last_seen_sequence": 1,
            "recorded_at": "2026-05-13T09:00:00Z",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    kv.store[key_for_pair("route-f", "hash-f")] = _MockKvEntry(
        value=foreign_blob, revision=1
    )
    with pytest.raises(SequenceNumberLedgerEnvelopeError) as exc_info:
        _run(
            ledger_a.a_last_seen(
                route_id="route-f", chain_hash="hash-f"
            )
        )
    assert "org-b" in str(exc_info.value)
    assert "org-a" in str(exc_info.value)


def test_snlk_11_bucket_config_byte_stable() -> None:
    """T-SNLK-11: bucket-config / schema constants are byte-stable
    (drift-protection at the test layer).
    """
    assert BUCKET_NAME_PREFIX == "wakir-caveat-override-export-sequence-"
    assert VALUE_SCHEMA == "wakir.federation.caveat-override-export-sequence/1"
    assert BUCKET_CONFIG["description"].startswith("Wirelang durable ")
    assert BUCKET_CONFIG["history"] == 1
    assert BUCKET_CONFIG["ttl_seconds"] == 0
    assert BUCKET_CONFIG["max_value_size"] == 4_096
    assert BUCKET_CONFIG["storage"] == "file"
    assert BUCKET_CONFIG["replicas"] == 1
    # bucket_name round-trip.
    assert bucket_name_for_org("org-a") == (
        "wakir-caveat-override-export-sequence-org-a"
    )
    assert (
        org_id_for_bucket_name(
            "wakir-caveat-override-export-sequence-org-a"
        )
        == "org-a"
    )


def test_snlk_12_key_derivation_bijective_and_validating() -> None:
    """T-SNLK-12: key derivation is bijective for valid inputs;
    malformed inputs raise ``ValueError``.
    """
    # Valid round-trip.
    key = key_for_pair("route-x", "hash-1")
    assert key == "sequence/route-x/hash-1"
    assert parse_pair_key(key) == ("route-x", "hash-1")
    # Malformed inputs.
    for bad in ("", "with/slash", "with space"):
        with pytest.raises(ValueError):
            key_for_pair(bad, "hash-1")
        with pytest.raises(ValueError):
            key_for_pair("route-x", bad)
    # Parse rejects shape errors.
    with pytest.raises(ValueError):
        parse_pair_key("not-a-key")
    with pytest.raises(ValueError):
        parse_pair_key("sequence/")
    with pytest.raises(ValueError):
        parse_pair_key("sequence/only-one")
    # Org-id validation.
    with pytest.raises(ValueError):
        bucket_name_for_org("")
    with pytest.raises(ValueError):
        bucket_name_for_org("with/slash")


def test_snlk_13_sync_adapter_protocol_round_trip() -> None:
    """T-SNLK-13: SyncSequenceNumberLedgerAdapter implements the
    Tag-1 :class:`SequenceNumberLedger` Protocol shape; the three
    methods round-trip end-to-end against the durable backend.
    """
    durable = _make_ledger("org-a")
    adapter = SyncSequenceNumberLedgerAdapter(durable=durable)
    # First call on an unknown pair.
    assert adapter.last_seen(
        route_id="route-sync", chain_hash="hash-sync"
    ) == 0
    assert adapter.next_sequence(
        route_id="route-sync", chain_hash="hash-sync"
    ) == 1
    # Record + read.
    adapter.record_export(
        route_id="route-sync", chain_hash="hash-sync", sequence=1
    )
    assert adapter.last_seen(
        route_id="route-sync", chain_hash="hash-sync"
    ) == 1
    # Replay rejected through the adapter.
    with pytest.raises(CaveatOverrideExportReplayError):
        adapter.record_export(
            route_id="route-sync", chain_hash="hash-sync", sequence=1
        )
    # Shape error surfaces through the adapter.
    with pytest.raises(CaveatOverrideExportShapeError):
        adapter.record_export(
            route_id="route-sync",
            chain_hash="hash-sync",
            sequence=0,
        )
