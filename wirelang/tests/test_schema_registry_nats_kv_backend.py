# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the Wirelang schema-registry NATS-KV backend.

Phase-1b Sprint-3 Tag-1 (S3-1). Tests the production-target backend
:mod:`wirelang.schemas.registry_nats_kv_backend` against an in-memory
mock that mirrors Kai's Tag-1 mock JetStream surface
(``tests/orchestrator/test_init_nats_buckets.py``) and the V-908
backend mock pattern
(``tests/test_federation_route_registry_nats_kv_backend.py``).

Test inventory T-SR-01..10 + auxiliary probes:

- T-SR-01: ``put`` round-trips an entry through ``get``.
- T-SR-02: ``get`` on an unknown key returns ``None``.
- T-SR-03: ``put`` is last-write-wins (second put overwrites).
- T-SR-04: ``delete`` removes an entry; subsequent ``get`` is ``None``.
- T-SR-05: ``snapshot`` materialises an
  :class:`InMemorySchemaRegistry` consumable by verifier code.
- T-SR-06: a poisoned (non-JSON) value raises
  :class:`SchemaRegistryEnvelopeError` from ``get`` and aborts
  ``snapshot``.
- T-SR-07: a value with the wrong ``schema`` field is rejected.
- T-SR-08: ``put`` rejects an entry whose ``schema_id`` does not
  match ``schema_body["$id"]``.
- T-SR-09: ``put`` rejects an entry whose ``schema_body_sha256``
  does not match the recomputed JCS-anchored hash.
- T-SR-10: bucket-config constants match the documented Phase-1
  inventory (drift-protection at the test layer).

Auxiliary probes:

- T-SR-aux-determinism: two back-to-back snapshots over the same
  bucket state yield byte-equal sorted-key lists and equal entries.
- T-SR-aux-key-derivation: triple ↔ key derivation is bijective
  (round-trip identity + invariants on rejected inputs).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pytest

from wirelang.schemas.registry_nats_kv_backend import (
    BUCKET_CONFIG,
    BUCKET_NAME,
    InMemorySchemaRegistry,
    NatsKvSchemaRegistry,
    SchemaRegistryEntry,
    SchemaRegistryEnvelopeError,
    SchemaRegistryValidationError,
    VALUE_SCHEMA,
    _entry_to_envelope,
    key_for_triple,
    schema_body_sha256,
    triple_for_key,
)


# ---------------------------------------------------------------------------
# Mock KV (mirrors V-908 _MockKv shape)
# ---------------------------------------------------------------------------


class _MockBucketNotFoundError(Exception):
    """Mirrors nats-py's ``KeyNotFoundError`` class-name pattern."""


@dataclass
class _MockKvEntry:
    value: bytes
    revision: int = 0


@dataclass
class _MockKv:
    bucket: str = BUCKET_NAME
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

    async def delete(self, key: str) -> None:
        if key not in self.store:
            raise _MockBucketNotFoundError(f"key not found: {key}")
        del self.store[key]
        self.revision += 1

    async def keys(self) -> list:
        return list(self.store.keys())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_REGISTERED_AT = datetime(2026, 5, 7, 13, 0, 0, tzinfo=timezone.utc)
_REGISTERED_BY = "wirelang-eng"


def _make_schema_body(schema_id: str, *, extra_field: bool = False) -> dict:
    """Build a small valid JSON-Schema document with a deterministic
    ``$id``. Used as the embedded ``schema_body`` in test entries.
    """
    body = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "title": "Test schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {"x": {"type": "string"}},
    }
    if extra_field:
        # Used to flip the body so two sibling entries differ.
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
# T-SR-01..04 single-key round-trip semantics
# ---------------------------------------------------------------------------


def test_t_sr_01_put_get_round_trip():
    """T-SR-01: ``put`` then ``get`` returns the same entry; the
    entry's identity triple round-trips through the envelope and the
    KV key derivation is stable.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKv())
    entry = _make_entry()

    async def _go():
        rev = await backend.put(entry)
        got = await backend.get(entry.key)
        return rev, got

    rev, got = _run(_go())
    assert rev >= 1
    assert got == entry
    assert got.key == "schemas/wire/layer-1-wire/0.1.0"


def test_t_sr_02_get_unknown_key_returns_none():
    """T-SR-02: ``get`` for an absent key returns ``None``."""
    backend = NatsKvSchemaRegistry(kv=_MockKv())

    async def _go():
        return await backend.get("schemas/wire/does-not-exist/0.0.0")

    assert _run(_go()) is None


def test_t_sr_03_put_last_write_wins():
    """T-SR-03: a second ``put`` overwrites the first; identity is
    keyed by the triple, not by body content.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKv())
    e1 = _make_entry(extra_field=False)
    e2 = _make_entry(extra_field=True)

    async def _go():
        await backend.put(e1)
        await backend.put(e2)
        return await backend.get(e1.key)

    got = _run(_go())
    assert got == e2
    assert got != e1


def test_t_sr_04_delete_removes_entry():
    """T-SR-04: ``delete`` makes a previously-present key absent."""
    backend = NatsKvSchemaRegistry(kv=_MockKv())
    entry = _make_entry()

    async def _go():
        await backend.put(entry)
        await backend.delete(entry.key)
        return await backend.get(entry.key)

    assert _run(_go()) is None


# ---------------------------------------------------------------------------
# T-SR-05..09 snapshot + envelope-shape gates
# ---------------------------------------------------------------------------


def test_t_sr_05_snapshot_returns_in_memory_registry():
    """T-SR-05: ``snapshot`` materialises an in-memory registry that
    answers ``lookup`` and ``lookup_by_triple`` deterministically.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKv())
    e1 = _make_entry(name="layer-1-wire", version="0.1.0")
    e2 = _make_entry(name="layer-2-semantic", version="0.1.0")

    async def _go():
        await backend.put(e1)
        await backend.put(e2)
        return await backend.snapshot()

    snap = _run(_go())
    assert isinstance(snap, InMemorySchemaRegistry)
    assert snap.lookup("schemas/wire/layer-1-wire/0.1.0") == e1
    assert snap.lookup("schemas/wire/layer-2-semantic/0.1.0") == e2
    assert snap.lookup_by_triple("wire", "layer-1-wire", "0.1.0") == e1
    assert snap.lookup_by_triple("wire", "not-registered", "0.1.0") is None


def test_t_sr_06_poisoned_envelope_raises():
    """T-SR-06: a non-JSON byte payload raises a clean
    :class:`SchemaRegistryEnvelopeError`. The snapshot aborts.
    """
    kv = _MockKv()
    # Hand-poison the bucket with a non-JSON byte sequence at a valid
    # key shape.
    kv.store["schemas/wire/poisoned/0.1.0"] = _MockKvEntry(
        value=b"\xff\xfenot-json", revision=1
    )
    backend = NatsKvSchemaRegistry(kv=kv)

    async def _go_get():
        return await backend.get("schemas/wire/poisoned/0.1.0")

    async def _go_snapshot():
        return await backend.snapshot()

    with pytest.raises(SchemaRegistryEnvelopeError):
        _run(_go_get())
    with pytest.raises(SchemaRegistryEnvelopeError):
        _run(_go_snapshot())


def test_t_sr_07_wrong_envelope_schema_rejected():
    """T-SR-07: a JSON value with a different envelope ``schema``
    field is rejected. Protects against accidental mixing of bucket
    contents (e.g., a copy-paste from another bucket).
    """
    kv = _MockKv()
    bogus = json.dumps(
        {
            "schema": "wakir.unrelated.thing/1",
            "layer": "wire",
            "name": "x",
            "version": "0.0.0",
        }
    ).encode("utf-8")
    kv.store["schemas/wire/x/0.0.0"] = _MockKvEntry(value=bogus, revision=1)
    backend = NatsKvSchemaRegistry(kv=kv)

    async def _go():
        return await backend.get("schemas/wire/x/0.0.0")

    with pytest.raises(SchemaRegistryEnvelopeError):
        _run(_go())


def test_t_sr_08_schema_id_mismatch_rejected_at_put():
    """T-SR-08: ``put`` rejects an entry whose envelope ``schema_id``
    does not match the embedded ``schema_body["$id"]``. Protects the
    determinism contract: a mis-anchored body cannot reach the bucket.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKv())
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
        return await backend.put(bad)

    with pytest.raises(SchemaRegistryValidationError):
        _run(_go())


def test_t_sr_09_body_hash_mismatch_rejected_at_put():
    """T-SR-09: ``put`` rejects an entry whose ``schema_body_sha256``
    does not match the recomputed JCS-anchored hash.
    """
    backend = NatsKvSchemaRegistry(kv=_MockKv())
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
        return await backend.put(bad)

    with pytest.raises(SchemaRegistryValidationError):
        _run(_go())


# ---------------------------------------------------------------------------
# T-SR-10 bucket-config drift
# ---------------------------------------------------------------------------


def test_t_sr_10_bucket_config_matches_documented_inventory():
    """T-SR-10: the module-level ``BUCKET_NAME`` and ``BUCKET_CONFIG``
    constants match the Phase-1 documented inventory.

    Cross-reference: this slot is shared with Kai's
    :data:`PHASE_1_BUCKETS[0]` in
    ``scripts/init-nats-buckets.py``. A drift here is a contract
    violation between the orchestrator-side init and the wirelang-
    side consumer; the test surfaces it before the live cluster
    sees inconsistent settings.
    """
    assert BUCKET_NAME == "wakir-schemas"
    assert BUCKET_CONFIG["name"] == BUCKET_NAME
    assert BUCKET_CONFIG["history"] == 5
    assert BUCKET_CONFIG["ttl_seconds"] == 0
    assert BUCKET_CONFIG["max_value_size"] == 262_144
    assert BUCKET_CONFIG["storage"] == "file"
    assert BUCKET_CONFIG["replicas"] == 1
    assert VALUE_SCHEMA == "wakir.wirelang.schema-registry-entry/1"


# ---------------------------------------------------------------------------
# T-SR-aux determinism and key-derivation invariants
# ---------------------------------------------------------------------------


def test_t_sr_aux_determinism_two_snapshots_byte_equal():
    """T-SR-aux-determinism: two snapshots of the same bucket state
    yield byte-equal envelopes for every entry. Anchors the
    determinism contract (spec §5.1).
    """
    backend = NatsKvSchemaRegistry(kv=_MockKv())
    entries = [
        _make_entry(name="layer-1-wire", version="0.1.0"),
        _make_entry(name="layer-2-semantic", version="0.1.0"),
        _make_entry(
            layer="federation",
            name="datalog-caveat",
            version="0.2.0",
        ),
    ]

    async def _go():
        for e in entries:
            await backend.put(e)
        snap_a = await backend.snapshot()
        snap_b = await backend.snapshot()
        return snap_a, snap_b

    snap_a, snap_b = _run(_go())
    assert snap_a.keys_sorted() == snap_b.keys_sorted()
    for k in snap_a.keys_sorted():
        env_a = _entry_to_envelope(snap_a.lookup(k))
        env_b = _entry_to_envelope(snap_b.lookup(k))
        assert env_a == env_b, f"envelope drift on {k}"


def test_t_sr_aux_key_derivation_round_trip():
    """T-SR-aux-key-derivation: :func:`key_for_triple` is bijective
    against :func:`triple_for_key`; malformed inputs are rejected.
    """
    # Round-trip identity for valid triples.
    cases = [
        ("identity", "aip-document", "0.1.0"),
        ("wire", "layer-3-capability-token", "0.1.0"),
        ("federation", "datalog-caveat", "0.2.0"),
    ]
    for layer, name, version in cases:
        key = key_for_triple(layer, name, version)
        assert key == f"schemas/{layer}/{name}/{version}"
        assert triple_for_key(key) == (layer, name, version)

    # Empty component → ValueError.
    with pytest.raises(ValueError):
        key_for_triple("", "x", "0.1.0")
    with pytest.raises(ValueError):
        key_for_triple("wire", "", "0.1.0")
    with pytest.raises(ValueError):
        key_for_triple("wire", "x", "")

    # Slash in component → ValueError (would corrupt the key shape).
    with pytest.raises(ValueError):
        key_for_triple("wire", "x/y", "0.1.0")

    # Unknown layer → ValueError.
    with pytest.raises(ValueError):
        key_for_triple("unknown-layer", "x", "0.1.0")

    # Malformed key → ValueError on inverse.
    with pytest.raises(ValueError):
        triple_for_key("not-a-schemas-key")
    with pytest.raises(ValueError):
        triple_for_key("schemas/only-two/parts")
    with pytest.raises(ValueError):
        triple_for_key("schemas//empty/components")
