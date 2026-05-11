# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the Wirelang capability-policy CAS-pin path.

Phase-2 Sprint-5 Tag-4 (S5-4). Tests the additive CAS-pin surface
on :mod:`wirelang.schemas.capability_policy_nats_kv_backend`:

- :meth:`NatsKvCapabilityPolicyBackend.get_with_revision`
- :meth:`NatsKvCapabilityPolicyBackend.get_with_revision_by_pair`
- :meth:`NatsKvCapabilityPolicyBackend.put_with_revision`
- :class:`CapabilityPolicyConflictError`

The CAS-pin path is the lost-update protection contract for
concurrent capability-policy authorship (a Sprint-5 Tag-4 addition).
The Sprint-5 Tag-2 LWW path (``put`` / ``get`` / ``delete`` /
``snapshot`` / ``snapshot_registry``) is unaffected; Tag-4 surfaces
are purely additive.

Pattern-Mirror source: Phase-1b Sprint-3 Tag-3 schema-registry
CAS-pin test inventory (``test_schema_registry_cas_pin.py``). The
CAS-aware mock KV ``_MockKvCas`` mirrors nats-py's KeyValue.update
contract: ``update(key, value, last=expected_revision)`` raises
``KeyWrongLastSequenceError`` when the live revision has advanced
past ``expected_revision``.

Test inventory (T-CPP-CAS-01..10 + 2 auxiliary probes):

- T-CPP-CAS-01: get_with_revision round-trips through put_with_revision.
- T-CPP-CAS-02: get_with_revision on absent key returns None.
- T-CPP-CAS-03: put_with_revision succeeds when expected matches live.
- T-CPP-CAS-04: put_with_revision raises ConflictError when stale.
- T-CPP-CAS-05: gate-1 (record-type) runs BEFORE CAS, no rev advance.
- T-CPP-CAS-06: gate-2 (pair-key derivation) runs BEFORE CAS,
  no rev advance (defence in depth on a mis-keyed record).
- T-CPP-CAS-07: negative expected_revision rejected with ValueError.
- T-CPP-CAS-08: interleaved CAS pair: exactly one wins.
- T-CPP-CAS-09: CAS+LWW remain orthogonal (LWW after CAS observable).
- T-CPP-CAS-10: KV without update method falls through; if neither
  surface exists, BackendError raised (no silent LWW demotion).
- T-CPP-CAS-aux-determinism: 5-pair interleave yields 5 wins, 5 conflicts.
- T-CPP-CAS-aux-conflict-class-detection: marker-based class detection.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pytest

from wirelang.schemas.capability_policy_nats_kv_backend import (
    CapabilityPolicyBackendError,
    CapabilityPolicyConflictError,
    CapabilityPolicyRecord,
    NatsKvCapabilityPolicyBackend,
    _is_conflict_exception,
    key_for_policy_pair,
)
from wirelang.schemas.registered_by_capability import CapabilityPolicy


# ---------------------------------------------------------------------------
# CAS-aware mock KV (mirrors nats-py KeyValue.update contract)
# ---------------------------------------------------------------------------


class _MockKeyWrongLastSequenceError(Exception):
    """Mirrors nats-py's ``KeyWrongLastSequenceError`` class-name
    pattern. Class name carries the ``WrongLastSequence`` marker so
    the backend's class-name-based detection translates it to
    :class:`CapabilityPolicyConflictError`.
    """

    def __init__(self, message: str, *, actual_revision: int) -> None:
        super().__init__(message)
        self.actual_revision = actual_revision


class _MockBucketNotFoundError(Exception):
    """Mirrors nats-py's ``KeyNotFoundError`` class-name pattern."""


@dataclass
class _MockKvEntry:
    value: bytes
    revision: int = 0


@dataclass
class _MockKvCas:
    """In-memory KV mock with CAS-aware ``update`` semantics.

    Supports the canonical nats-py shape:
    ``update(key, value, last=expected_revision)``. Raises
    :class:`_MockKeyWrongLastSequenceError` (whose class name
    contains the ``WrongLastSequence`` marker) when the live revision
    has advanced past ``expected_revision``.

    Also surfaces a non-CAS ``put`` path for orthogonality testing.
    """

    bucket: str = "wakir-capability-policies"
    store: dict = field(default_factory=dict)
    revision: int = 0

    async def get(self, key: str) -> _MockKvEntry:
        if key not in self.store:
            raise _MockBucketNotFoundError(f"key not found: {key}")
        return self.store[key]

    async def put(self, key: str, value: bytes) -> int:
        self.revision += 1
        self.store[key] = _MockKvEntry(
            value=bytes(value), revision=self.revision
        )
        return self.revision

    async def update(self, key: str, value: bytes, last: int) -> int:
        """CAS-pinned upsert. Raises if live revision has advanced."""
        existing = self.store.get(key)
        live_revision = existing.revision if existing is not None else 0
        if live_revision != last:
            raise _MockKeyWrongLastSequenceError(
                f"CAS conflict on {key!r}: "
                f"expected last={last}, actual={live_revision}",
                actual_revision=live_revision,
            )
        self.revision += 1
        self.store[key] = _MockKvEntry(
            value=bytes(value), revision=self.revision
        )
        return self.revision

    async def delete(self, key: str) -> None:
        if key not in self.store:
            raise _MockBucketNotFoundError(f"key not found: {key}")
        del self.store[key]
        self.revision += 1

    async def keys(self) -> list:
        return list(self.store.keys())


@dataclass
class _MockKvNoCas:
    """KV mock that does NOT expose ``update`` and does NOT accept
    ``expected_revision`` on ``put``. Forces the backend to raise
    :class:`CapabilityPolicyBackendError` for CAS attempts (no silent
    demotion to LWW).
    """

    store: dict = field(default_factory=dict)
    revision: int = 0

    async def get(self, key: str):
        if key not in self.store:
            raise _MockBucketNotFoundError(f"key not found: {key}")
        return self.store[key]

    async def put(self, key: str, value: bytes) -> int:
        # Strict: refuses extra keyword args.
        self.revision += 1
        self.store[key] = _MockKvEntry(
            value=bytes(value), revision=self.revision
        )
        return self.revision

    async def keys(self) -> list:
        return list(self.store.keys())


# ---------------------------------------------------------------------------
# Fixtures (mirror Tag-2 fixture shape)
# ---------------------------------------------------------------------------


_REGISTERED_AT = datetime(2026, 5, 11, 21, 0, 0, tzinfo=timezone.utc)
_REGISTERED_BY_PUBLISHER = "wirelang-eng"


def _make_policy(
    *,
    registered_by: str = "wirelang-eng",
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
) -> CapabilityPolicyRecord:
    if policy is None:
        policy = _make_policy()
    return CapabilityPolicyRecord(
        policy=policy,
        policy_id=policy_id,
        registered_at=registered_at,
        registered_by_publisher=registered_by_publisher,
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# T-CPP-CAS-01..04: round-trip and conflict-detection core path
# ---------------------------------------------------------------------------


def test_t_cpp_cas_01_get_with_revision_round_trip():
    """T-CPP-CAS-01: ``get_with_revision`` returns the record and its
    KV revision; the revision matches the one returned from ``put``.
    """
    backend = NatsKvCapabilityPolicyBackend(kv=_MockKvCas())
    record = _make_record()

    async def _go():
        rev = await backend.put(record)
        got = await backend.get_with_revision(record.key)
        return rev, got

    rev, got = _run(_go())
    assert got is not None
    got_record, got_rev = got
    assert got_record.policy.registered_by == record.policy.registered_by
    assert got_record.policy.allowed_kids == record.policy.allowed_kids
    assert got_record.policy.allowed_triples == record.policy.allowed_triples
    assert got_record.policy_id == record.policy_id
    assert got_rev == rev
    assert got_rev >= 1

    # by_pair convenience wrapper byte-equivalent.
    got_by_pair = _run(
        backend.get_with_revision_by_pair(
            record.policy.registered_by, record.policy_id
        )
    )
    assert got_by_pair is not None
    assert got_by_pair[1] == got_rev


def test_t_cpp_cas_02_get_with_revision_unknown_key_returns_none():
    """T-CPP-CAS-02: ``get_with_revision`` for an absent key returns
    ``None``. Mirrors :meth:`get` for absent keys; no exception.
    Same for the ``_by_pair`` convenience wrapper.
    """
    backend = NatsKvCapabilityPolicyBackend(kv=_MockKvCas())

    async def _go():
        a = await backend.get_with_revision(
            "capability-policies/nobody/missing"
        )
        b = await backend.get_with_revision_by_pair(
            "nobody", "missing-policy"
        )
        # Malformed pair: should also return None, not raise.
        c = await backend.get_with_revision_by_pair("", "missing")
        return a, b, c

    a, b, c = _run(_go())
    assert a is None
    assert b is None
    assert c is None


def test_t_cpp_cas_03_put_with_revision_succeeds_when_expected_matches():
    """T-CPP-CAS-03: a CAS-pinned upsert succeeds when the
    ``expected_revision`` argument matches the live revision. The
    updated record is observable via ``get_with_revision`` at the
    new revision.
    """
    backend = NatsKvCapabilityPolicyBackend(kv=_MockKvCas())
    r1 = _make_record(
        policy=_make_policy(allowed_kids=("biscuit-root-1",)),
        policy_id="rollover",
    )

    async def _go():
        rev1 = await backend.put(r1)
        # Build a mutated record (allowed_kids rotated). Same
        # (registered_by, policy_id) pair → same key.
        r2 = _make_record(
            policy=_make_policy(
                allowed_kids=("biscuit-root-1", "biscuit-root-2"),
            ),
            policy_id="rollover",
        )
        rev2 = await backend.put_with_revision(r2, rev1)
        got = await backend.get_with_revision(r1.key)
        return rev1, rev2, got

    rev1, rev2, got = _run(_go())
    assert rev2 > rev1
    assert got is not None
    got_record, got_rev = got
    assert got_rev == rev2
    # Rotated kids observable: two-kid set now lives in bucket.
    assert got_record.policy.allowed_kids == (
        "biscuit-root-1",
        "biscuit-root-2",
    )


def test_t_cpp_cas_04_put_with_revision_conflict_when_stale():
    """T-CPP-CAS-04: a CAS-pinned upsert with a stale
    ``expected_revision`` raises :class:`CapabilityPolicyConflictError`.
    The error carries ``key``, ``expected_revision``, and
    ``actual_revision``. The bucket revision does NOT advance from
    the rejected stale write.
    """
    kv = _MockKvCas()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    r1 = _make_record(policy_id="rollover")

    async def _go_setup():
        rev1 = await backend.put(r1)
        # A second concurrent writer landed (LWW).
        r2 = _make_record(
            policy=_make_policy(
                allowed_kids=("biscuit-root-2",),
                note="bumped by concurrent writer",
            ),
            policy_id="rollover",
        )
        rev2 = await backend.put(r2)
        return rev1, rev2

    async def _go_stale_cas(rev1):
        # Caller still has rev1; tries to CAS-pin with stale revision.
        r3 = _make_record(
            policy=_make_policy(
                allowed_kids=("biscuit-root-3",),
                note="late-writer",
            ),
            policy_id="rollover",
            registered_by_publisher="late-writer",
        )
        await backend.put_with_revision(r3, rev1)

    rev1, rev2 = _run(_go_setup())
    assert rev2 > rev1

    pre_rev = kv.revision
    with pytest.raises(CapabilityPolicyConflictError) as exc_info:
        _run(_go_stale_cas(rev1))

    err = exc_info.value
    assert err.key == key_for_policy_pair("wirelang-eng", "rollover")
    assert err.expected_revision == rev1
    assert err.actual_revision == rev2  # CAS mock surfaces the live rev
    # Bucket revision did NOT advance (the stale write was rejected
    # before reaching put).
    assert kv.revision == pre_rev


# ---------------------------------------------------------------------------
# T-CPP-CAS-05..07: validation gates run BEFORE CAS, defence-in-depth
# ---------------------------------------------------------------------------


def test_t_cpp_cas_05_validation_gate_record_type_runs_before_cas():
    """T-CPP-CAS-05: gate-1 (``record`` must be a
    :class:`CapabilityPolicyRecord`) runs BEFORE the CAS call. A
    non-record argument raises :class:`TypeError` and the bucket
    revision does NOT advance. Defence in depth.
    """
    kv = _MockKvCas()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    r1 = _make_record()

    async def _go():
        rev1 = await backend.put(r1)
        with pytest.raises(TypeError):
            await backend.put_with_revision("not-a-record", rev1)
        # Bucket revision unchanged.
        return rev1, kv.revision

    rev1, post_revision = _run(_go())
    assert post_revision == rev1


def test_t_cpp_cas_06_validation_gate_pair_key_runs_before_cas():
    """T-CPP-CAS-06: gate-2 (pair ↔ key derivation) runs BEFORE the
    CAS call. The record's ``key`` property invokes
    :func:`key_for_policy_pair` which validates the components; a
    record with a malformed ``policy_id`` cannot be constructed in
    the first place (Sprint-5 Tag-2 ``__post_init__`` invariant),
    and an attempt to build one raises
    :class:`CapabilityPolicyValidationError` before any backend
    interaction. The bucket revision does NOT advance from the
    rejected validation attempt.
    """
    kv = _MockKvCas()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    r1 = _make_record()

    async def _go_setup():
        return await backend.put(r1)

    rev1 = _run(_go_setup())
    pre_revision = kv.revision

    # Attempt to construct a malformed-policy_id record: the dataclass
    # __post_init__ rejects it before the record exists.
    from wirelang.schemas.capability_policy_nats_kv_backend import (
        CapabilityPolicyValidationError,
    )

    with pytest.raises(CapabilityPolicyValidationError):
        _make_record(policy_id="bad/slash/inside")  # slashes not permitted

    # Bucket revision unchanged: no put_with_revision was attempted
    # because the record could not be built.
    assert kv.revision == pre_revision
    assert rev1 == pre_revision


def test_t_cpp_cas_07_negative_expected_revision_rejected():
    """T-CPP-CAS-07: ``put_with_revision`` rejects a negative
    ``expected_revision`` with :class:`ValueError`. Defence in depth.
    """
    backend = NatsKvCapabilityPolicyBackend(kv=_MockKvCas())
    record = _make_record()

    async def _go():
        await backend.put_with_revision(record, -1)

    with pytest.raises(ValueError):
        _run(_go())


# ---------------------------------------------------------------------------
# T-CPP-CAS-08..09: lost-update contract + LWW orthogonality
# ---------------------------------------------------------------------------


def test_t_cpp_cas_08_interleaved_pair_exactly_one_wins():
    """T-CPP-CAS-08: two concurrent CAS-pin loops on the same key
    observe the same starting revision; exactly one succeeds, the
    other receives :class:`CapabilityPolicyConflictError`. The lost-
    update protection contract.
    """
    backend = NatsKvCapabilityPolicyBackend(kv=_MockKvCas())
    r0 = _make_record(policy_id="rollover")

    async def _go():
        rev0 = await backend.put(r0)
        # Both writers observe rev0.
        observed_a = rev0
        observed_b = rev0

        # Writer A lands first.
        new_a = _make_record(
            policy=_make_policy(allowed_kids=("biscuit-root-a",)),
            policy_id="rollover",
            registered_by_publisher="writer-a",
        )
        rev_a = await backend.put_with_revision(new_a, observed_a)

        # Writer B is now stale.
        new_b = _make_record(
            policy=_make_policy(allowed_kids=("biscuit-root-b",)),
            policy_id="rollover",
            registered_by_publisher="writer-b",
        )
        try:
            rev_b = await backend.put_with_revision(new_b, observed_b)
        except CapabilityPolicyConflictError as exc:
            return rev_a, exc, None
        return rev_a, None, rev_b

    rev_a, conflict, rev_b = _run(_go())
    assert rev_a >= 1
    assert conflict is not None
    assert rev_b is None
    assert conflict.actual_revision == rev_a
    assert conflict.expected_revision < conflict.actual_revision


def test_t_cpp_cas_09_cas_and_lww_orthogonal():
    """T-CPP-CAS-09: a CAS-pinned put followed by a non-CAS put is
    observable: the non-CAS put wins (LWW path). Tag-4 CAS-pin and
    Tag-2 LWW remain orthogonal.
    """
    backend = NatsKvCapabilityPolicyBackend(kv=_MockKvCas())
    r0 = _make_record(policy_id="rollover")

    async def _go():
        rev0 = await backend.put(r0)
        # CAS-pin lands.
        r1 = _make_record(
            policy=_make_policy(allowed_kids=("biscuit-root-cas",)),
            policy_id="rollover",
            registered_by_publisher="cas-writer",
        )
        rev1 = await backend.put_with_revision(r1, rev0)
        # Non-CAS LWW lands on top.
        r2 = _make_record(
            policy=_make_policy(allowed_kids=("biscuit-root-lww",)),
            policy_id="rollover",
            registered_by_publisher="lww-writer",
        )
        rev2 = await backend.put(r2)
        got = await backend.get_with_revision(r0.key)
        return rev0, rev1, rev2, got

    rev0, rev1, rev2, got = _run(_go())
    assert rev0 < rev1 < rev2
    assert got is not None
    got_record, got_rev = got
    assert got_rev == rev2
    assert got_record.registered_by_publisher == "lww-writer"
    assert got_record.policy.allowed_kids == ("biscuit-root-lww",)


def test_t_cpp_cas_10_kv_without_cas_surface_raises_backend_error():
    """T-CPP-CAS-10: a KV adapter without an ``update`` method and
    without a ``put(expected_revision=...)`` keyword path raises
    :class:`CapabilityPolicyBackendError`. No silent demotion to LWW.
    """
    backend = NatsKvCapabilityPolicyBackend(kv=_MockKvNoCas())
    record = _make_record()

    async def _go():
        # Direct put works (LWW path, Tag-2 unchanged).
        rev = await backend.put(record)
        # CAS-pin attempt must fail explicitly.
        await backend.put_with_revision(record, rev)

    with pytest.raises(CapabilityPolicyBackendError) as exc_info:
        _run(_go())
    # Specifically NOT a ConflictError (which would imply silent
    # demotion); a clean BackendError that says CAS is unsupported.
    assert not isinstance(exc_info.value, CapabilityPolicyConflictError)
    assert "CAS-pin not supported" in str(exc_info.value)


# ---------------------------------------------------------------------------
# T-CPP-CAS-aux determinism + class-detection invariants
# ---------------------------------------------------------------------------


def test_t_cpp_cas_aux_determinism_5_pair_interleave():
    """T-CPP-CAS-aux-determinism: ten interleaved CAS-pin pairs over
    a single key yield exactly five winners and five conflicts. The
    final revision is exactly five greater than the starting
    revision (one increment per accepted writer). Anchors the
    determinism contract under bounded concurrency.
    """
    backend = NatsKvCapabilityPolicyBackend(kv=_MockKvCas())
    r0 = _make_record(policy_id="rollover")

    async def _go():
        rev0 = await backend.put(r0)
        wins = 0
        conflicts = 0
        current = rev0
        for i in range(5):
            observed_a = current
            observed_b = current
            new_a = _make_record(
                policy=_make_policy(
                    allowed_kids=(f"biscuit-root-a-{i}",),
                ),
                policy_id="rollover",
                registered_by_publisher=f"writer-a-{i}",
            )
            new_b = _make_record(
                policy=_make_policy(
                    allowed_kids=(f"biscuit-root-b-{i}",),
                ),
                policy_id="rollover",
                registered_by_publisher=f"writer-b-{i}",
            )
            current = await backend.put_with_revision(new_a, observed_a)
            wins += 1
            try:
                await backend.put_with_revision(new_b, observed_b)
                wins += 1
            except CapabilityPolicyConflictError:
                conflicts += 1
        return rev0, current, wins, conflicts

    rev0, final_rev, wins, conflicts = _run(_go())
    assert wins == 5
    assert conflicts == 5
    # Five increments: final rev is exactly five greater than rev0.
    assert final_rev == rev0 + 5


def test_t_cpp_cas_aux_conflict_class_detection():
    """T-CPP-CAS-aux-conflict-class-detection: the class-name marker
    detection (:func:`_is_conflict_exception`) recognises typical
    nats-py conflict exception class names (``KeyWrongLastSequenceError``,
    ``KeyValueConflictError``, ``RevisionMismatchError``) and rejects
    unrelated classes (``ValueError``, generic ``Exception``,
    ``UnrelatedError``).
    """

    class KeyWrongLastSequenceError(Exception):
        pass

    class KeyValueConflictError(Exception):
        pass

    class RevisionMismatchError(Exception):
        pass

    class UnrelatedError(Exception):
        pass

    assert _is_conflict_exception(KeyWrongLastSequenceError("x"))
    assert _is_conflict_exception(KeyValueConflictError("x"))
    assert _is_conflict_exception(RevisionMismatchError("x"))
    assert not _is_conflict_exception(UnrelatedError("x"))
    assert not _is_conflict_exception(ValueError("x"))
    assert not _is_conflict_exception(Exception("x"))
