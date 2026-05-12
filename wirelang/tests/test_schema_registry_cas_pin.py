# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the Wirelang schema-registry CAS-pin path.

Phase-1b Sprint-3 Tag-3 (S3-3). Tests the additive CAS-pin surface
on :mod:`wirelang.schemas.registry_nats_kv_backend`:

- :meth:`NatsKvSchemaRegistry.get_with_revision`
- :meth:`NatsKvSchemaRegistry.put_with_revision`
- :class:`SchemaRegistryConflictError`

The CAS-pin path is the lost-update protection contract for
concurrent schema-registry upserts (spec §5.4). The Tag-1 LWW path
(``put`` / ``get`` / ``snapshot``) is unaffected; Tag-3 surfaces are
purely additive.

Pattern source for the CAS-aware mock KV: V-908 Tag-6
``_MockKv`` extended with revision-aware ``update``. The
``_MockKvCas`` class below mirrors nats-py's KeyValue.update
contract: ``update(key, value, last=expected_revision)`` raises
``KeyWrongLastSequenceError`` when the live revision has advanced
past ``expected_revision``.

Test inventory (T-SR-CAS-01..10 + 2 aux probes):

- T-SR-CAS-01: get_with_revision round-trips through put_with_revision.
- T-SR-CAS-02: get_with_revision on absent key returns None.
- T-SR-CAS-03: put_with_revision succeeds when expected matches live.
- T-SR-CAS-04: put_with_revision raises ConflictError when stale.
- T-SR-CAS-05: gate-1 (schema_id↔$id) runs BEFORE CAS, no rev advance.
- T-SR-CAS-06: gate-2 (body-hash) runs BEFORE CAS, no rev advance.
- T-SR-CAS-07: negative expected_revision rejected with ValueError.
- T-SR-CAS-08: interleaved CAS pair: exactly one wins.
- T-SR-CAS-09: CAS+LWW remain orthogonal (LWW after CAS observable).
- T-SR-CAS-10: KV without update method falls through; if neither
  surface exists, BackendError raised (no silent LWW demotion).
- T-SR-CAS-aux-determinism: 5-pair interleave yields 5 wins, 5 conflicts.
- T-SR-CAS-aux-conflict-class-detection: marker-based class detection.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pytest

from wirelang.schemas.registry_nats_kv_backend import (
    NatsKvSchemaRegistry,
    SchemaRegistryBackendError,
    SchemaRegistryConflictError,
    SchemaRegistryEntry,
    SchemaRegistryValidationError,
    _is_conflict_exception,
    key_for_triple,
    schema_body_sha256,
)


# ---------------------------------------------------------------------------
# CAS-aware mock KV (mirrors nats-py KeyValue.update contract)
# ---------------------------------------------------------------------------


class _MockKeyWrongLastSequenceError(Exception):
    """Mirrors nats-py's ``KeyWrongLastSequenceError`` class-name
    pattern. Class name carries the ``WrongLastSequence`` marker so
    the backend's class-name-based detection translates it to
    :class:`SchemaRegistryConflictError`.
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

    bucket: str = "wakir-schemas"
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
    :class:`SchemaRegistryBackendError` for CAS attempts (no silent
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
# Fixtures (mirror Tag-1 fixture shape)
# ---------------------------------------------------------------------------


_REGISTERED_AT = datetime(2026, 5, 7, 13, 0, 0, tzinfo=timezone.utc)
_REGISTERED_BY = "wirelang-eng"


def _make_schema_body(schema_id: str, *, extra_field: bool = False) -> dict:
    body = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "title": "CAS test schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {"x": {"type": "string"}},
    }
    if extra_field:
        body["properties"]["y"] = {"type": "integer"}
    return body


def _make_entry(
    *,
    layer: str = "wire",
    name: str = "layer-1-wire",
    version: str = "0.1.0",
    schema_id: Optional[str] = None,
    extra_field: bool = False,
    registered_at: datetime = _REGISTERED_AT,
    registered_by: str = _REGISTERED_BY,
    supersedes: Optional[str] = None,
) -> SchemaRegistryEntry:
    if schema_id is None:
        schema_id = f"https://wakir.dev/wirelang/schema/{name}/{version}"
    body = _make_schema_body(schema_id, extra_field=extra_field)
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
# T-SR-CAS-01..04: round-trip and conflict-detection core path
# ---------------------------------------------------------------------------


def test_t_sr_cas_01_get_with_revision_round_trip():
    """T-SR-CAS-01: ``get_with_revision`` returns the entry and its
    KV revision; the revision matches the one returned from ``put``.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKvCas())
    entry = _make_entry()

    async def _go():
        rev = await backend.put(entry)
        got = await backend.get_with_revision(entry.key)
        return rev, got

    rev, got = _run(_go())
    assert got is not None
    got_entry, got_rev = got
    assert got_entry == entry
    assert got_rev == rev
    assert got_rev >= 1


def test_t_sr_cas_02_get_with_revision_unknown_key_returns_none():
    """T-SR-CAS-02: ``get_with_revision`` for an absent key returns
    ``None``. Mirrors :meth:`get` for absent keys; no exception.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKvCas())

    async def _go():
        return await backend.get_with_revision(
            "schemas/wire/missing/0.0.0"
        )

    assert _run(_go()) is None


def test_t_sr_cas_03_put_with_revision_succeeds_when_expected_matches():
    """T-SR-CAS-03: a CAS-pinned upsert succeeds when the
    ``expected_revision`` argument matches the live revision.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKvCas())
    e1 = _make_entry(extra_field=False)

    async def _go():
        rev1 = await backend.put(e1)
        # Build a mutated entry whose envelope is consistent.
        e2 = _make_entry(extra_field=True)
        rev2 = await backend.put_with_revision(e2, rev1)
        got = await backend.get_with_revision(e1.key)
        return rev1, rev2, got

    rev1, rev2, got = _run(_go())
    assert rev2 > rev1
    assert got is not None
    got_entry, got_rev = got
    assert got_rev == rev2
    # Body content matches the second entry (with extra field).
    assert "y" in got_entry.schema_body["properties"]


def test_t_sr_cas_04_put_with_revision_conflict_when_stale():
    """T-SR-CAS-04: a CAS-pinned upsert with a stale
    ``expected_revision`` raises :class:`SchemaRegistryConflictError`.
    The error carries ``key``, ``expected_revision``, and
    ``actual_revision``.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKvCas())
    e1 = _make_entry(extra_field=False)

    async def _go_setup():
        rev1 = await backend.put(e1)
        # A second concurrent writer landed.
        e2 = _make_entry(extra_field=True)
        rev2 = await backend.put(e2)
        return rev1, rev2

    async def _go_stale_cas(rev1):
        # Caller still has rev1; tries to CAS-pin with stale revision.
        e3 = _make_entry(extra_field=False, registered_by="late-writer")
        await backend.put_with_revision(e3, rev1)

    rev1, rev2 = _run(_go_setup())
    assert rev2 > rev1

    with pytest.raises(SchemaRegistryConflictError) as exc_info:
        _run(_go_stale_cas(rev1))

    err = exc_info.value
    assert err.key == "schemas/wire/layer-1-wire/0.1.0"
    assert err.expected_revision == rev1
    assert err.actual_revision == rev2  # CAS mock surfaces the live rev
    # Bucket revision did NOT advance (the stale write was rejected
    # before reaching put).
    assert _run(backend.get_with_revision(e1.key))[1] == rev2


# ---------------------------------------------------------------------------
# T-SR-CAS-05..07: validation gates run BEFORE CAS, defence-in-depth
# ---------------------------------------------------------------------------


def test_t_sr_cas_05_validation_gate_1_runs_before_cas():
    """T-SR-CAS-05: gate-1 (``schema_id`` ↔ ``schema_body.$id``) runs
    BEFORE the CAS call. A mismatched envelope raises
    :class:`SchemaRegistryValidationError` and the bucket revision
    does NOT advance.
    """
    kv = _MockKvCas()
    backend = NatsKvSchemaRegistry(kv=kv)
    e1 = _make_entry()

    body = _make_schema_body(
        "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
    )
    bad = SchemaRegistryEntry(
        layer="wire",
        name="layer-1-wire",
        version="0.1.0",
        schema_id="https://wakir.dev/wirelang/schema/wrong-id/9.9.9",
        schema_body=body,
        schema_body_sha256=schema_body_sha256(body),
        registered_at=_REGISTERED_AT,
        registered_by=_REGISTERED_BY,
    )

    async def _go():
        rev1 = await backend.put(e1)
        with pytest.raises(SchemaRegistryValidationError):
            await backend.put_with_revision(bad, rev1)
        # Bucket revision unchanged.
        return rev1, kv.revision

    rev1, post_revision = _run(_go())
    assert post_revision == rev1


def test_t_sr_cas_06_validation_gate_2_runs_before_cas():
    """T-SR-CAS-06: gate-2 (``schema_body_sha256``) runs BEFORE the
    CAS call. A mis-anchored hash raises
    :class:`SchemaRegistryValidationError` and the bucket revision
    does NOT advance.
    """
    kv = _MockKvCas()
    backend = NatsKvSchemaRegistry(kv=kv)
    e1 = _make_entry()

    body = _make_schema_body(
        "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
    )
    bad = SchemaRegistryEntry(
        layer="wire",
        name="layer-1-wire",
        version="0.1.0",
        schema_id="https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0",
        schema_body=body,
        schema_body_sha256="00" * 32,  # incorrect digest
        registered_at=_REGISTERED_AT,
        registered_by=_REGISTERED_BY,
    )

    async def _go():
        rev1 = await backend.put(e1)
        with pytest.raises(SchemaRegistryValidationError):
            await backend.put_with_revision(bad, rev1)
        return rev1, kv.revision

    rev1, post_revision = _run(_go())
    assert post_revision == rev1


def test_t_sr_cas_07_negative_expected_revision_rejected():
    """T-SR-CAS-07: ``put_with_revision`` rejects a negative
    ``expected_revision`` with :class:`ValueError`. Defence in depth.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKvCas())
    entry = _make_entry()

    async def _go():
        await backend.put_with_revision(entry, -1)

    with pytest.raises(ValueError):
        _run(_go())


# ---------------------------------------------------------------------------
# T-SR-CAS-08..09: lost-update contract + LWW orthogonality
# ---------------------------------------------------------------------------


def test_t_sr_cas_08_interleaved_pair_exactly_one_wins():
    """T-SR-CAS-08: two concurrent CAS-pin loops on the same key
    observe the same starting revision; exactly one succeeds, the
    other receives :class:`SchemaRegistryConflictError`. The lost-
    update protection contract.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKvCas())
    e0 = _make_entry()

    async def _go():
        rev0 = await backend.put(e0)
        # Both writers observe rev0.
        observed_a = rev0
        observed_b = rev0

        # Writer A lands first.
        new_a = _make_entry(extra_field=False, registered_by="writer-a")
        rev_a = await backend.put_with_revision(new_a, observed_a)

        # Writer B is now stale.
        new_b = _make_entry(extra_field=True, registered_by="writer-b")
        try:
            rev_b = await backend.put_with_revision(new_b, observed_b)
        except SchemaRegistryConflictError as exc:
            return rev_a, exc, None
        return rev_a, None, rev_b

    rev_a, conflict, rev_b = _run(_go())
    assert rev_a >= 1
    assert conflict is not None
    assert rev_b is None
    assert conflict.actual_revision == rev_a
    assert conflict.expected_revision < conflict.actual_revision


def test_t_sr_cas_09_cas_and_lww_orthogonal():
    """T-SR-CAS-09: a CAS-pinned put followed by a non-CAS put is
    observable: the non-CAS put wins (LWW path). Tag-3 CAS-pin and
    Tag-1 LWW remain orthogonal.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKvCas())
    e0 = _make_entry()

    async def _go():
        rev0 = await backend.put(e0)
        # CAS-pin lands.
        e1 = _make_entry(registered_by="cas-writer")
        rev1 = await backend.put_with_revision(e1, rev0)
        # Non-CAS LWW lands on top.
        e2 = _make_entry(extra_field=True, registered_by="lww-writer")
        rev2 = await backend.put(e2)
        got = await backend.get_with_revision(e0.key)
        return rev0, rev1, rev2, got

    rev0, rev1, rev2, got = _run(_go())
    assert rev0 < rev1 < rev2
    assert got is not None
    got_entry, got_rev = got
    assert got_rev == rev2
    assert got_entry.registered_by == "lww-writer"


def test_t_sr_cas_10_kv_without_cas_surface_raises_backend_error():
    """T-SR-CAS-10: a KV adapter without an ``update`` method and
    without a ``put(expected_revision=...)`` keyword path raises
    :class:`SchemaRegistryBackendError`. No silent demotion to LWW.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKvNoCas())
    entry = _make_entry()

    async def _go():
        # Direct put works (LWW path, Tag-1 unchanged).
        rev = await backend.put(entry)
        # CAS-pin attempt must fail explicitly.
        await backend.put_with_revision(entry, rev)

    with pytest.raises(SchemaRegistryBackendError) as exc_info:
        _run(_go())
    # Specifically NOT a ConflictError (which would imply silent
    # demotion); a clean BackendError that says CAS is unsupported.
    assert not isinstance(exc_info.value, SchemaRegistryConflictError)
    assert "CAS-pin not supported" in str(exc_info.value)


# ---------------------------------------------------------------------------
# T-SR-CAS-aux determinism + class-detection invariants
# ---------------------------------------------------------------------------


def test_t_sr_cas_aux_determinism_5_pair_interleave():
    """T-SR-CAS-aux-determinism: ten interleaved CAS-pin pairs over
    a single key yield exactly five winners and five conflicts. The
    final revision is exactly five greater than the starting
    revision (one increment per accepted writer). Anchors the
    determinism contract under bounded concurrency.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKvCas())
    e0 = _make_entry()

    async def _go():
        rev0 = await backend.put(e0)
        wins = 0
        conflicts = 0
        # Five interleave pairs: each pair, both writers observe the
        # current rev, A lands, B is stale.
        current = rev0
        for i in range(5):
            observed_a = current
            observed_b = current
            new_a = _make_entry(
                extra_field=(i % 2 == 0),
                registered_by=f"writer-a-{i}",
            )
            new_b = _make_entry(
                extra_field=(i % 2 == 1),
                registered_by=f"writer-b-{i}",
            )
            current = await backend.put_with_revision(new_a, observed_a)
            wins += 1
            try:
                await backend.put_with_revision(new_b, observed_b)
                wins += 1
            except SchemaRegistryConflictError:
                conflicts += 1
        return rev0, current, wins, conflicts

    rev0, final_rev, wins, conflicts = _run(_go())
    assert wins == 5
    assert conflicts == 5
    # Five increments: final rev is exactly five greater than rev0.
    assert final_rev == rev0 + 5


def test_t_sr_cas_aux_conflict_class_detection():
    """T-SR-CAS-aux-conflict-class-detection: the class-name marker
    detection (:func:`_is_conflict_exception`) recognises typical
    nats-py conflict exception class names (``KeyWrongLastSequenceError``,
    ``KeyValueConflictError``, ``RevisionMismatchError``) and rejects
    unrelated classes (``ValueError``, generic ``Exception``).
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
