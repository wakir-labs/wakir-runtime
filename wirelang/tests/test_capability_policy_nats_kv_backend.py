# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the Wirelang capability-policy NATS-KV backend.

Phase-2 Sprint-5 Tag-2 (S5-2). Tests the persistent-distribution tier
:mod:`wirelang.schemas.capability_policy_nats_kv_backend` against an
in-memory mock that mirrors the Sprint-3 Tag-1 schema-registry-backend
mock pattern (``tests/test_schema_registry_nats_kv_backend.py``) and
Kai's Tag-1 mock JetStream surface.

Test inventory T-CPP-01..10 + auxiliary probes:

- T-CPP-01: ``put`` round-trips a record through ``get``.
- T-CPP-02: ``get`` on an unknown key returns ``None``.
- T-CPP-03: ``put`` is last-write-wins (second put overwrites; same
  ``(registered_by, policy_id)`` pair).
- T-CPP-04: ``delete`` removes a record; subsequent ``get`` is
  ``None``; subsequent ``delete`` is a no-op (tombstoned).
- T-CPP-05: ``snapshot`` materialises a sorted list of records;
  ``snapshot_registry`` materialises a
  :class:`CapabilityPolicyRegistry` whose
  :meth:`policies_for` returns the same records the bucket holds.
- T-CPP-06: a poisoned (non-JSON) value raises
  :class:`CapabilityPolicyEnvelopeError` from ``get`` and aborts
  ``snapshot``.
- T-CPP-07: a value with the wrong ``schema`` field is rejected.
- T-CPP-08: bucket-config constants are byte-stable
  (drift-protection at the test layer).
- T-CPP-09: a multi-policy-per-issuer bucket round-trips through
  ``snapshot_registry`` into a
  :class:`CapabilityPolicyRegistry` where the gate evaluation
  (:func:`check_registered_by_capability`) sees both policies and
  allows the union of triples / kids they cover.
- T-CPP-10: a snapshot is determinism-stable across two back-to-back
  calls (sorted-key list is byte-equal; record list is value-equal).

Auxiliary probes:

- T-CPP-aux-key-derivation: ``(registered_by, policy_id)`` ↔ key
  derivation is bijective (round-trip identity + invariants on
  rejected inputs).
- T-CPP-aux-envelope-shape: an envelope with malformed
  ``allowed_triples`` (object instead of 2-tuple, missing field,
  bad type) raises :class:`CapabilityPolicyEnvelopeError`.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pytest

from wirelang.schemas.capability_policy_nats_kv_backend import (
    BUCKET_CONFIG,
    BUCKET_NAME,
    VALUE_SCHEMA,
    CapabilityPolicyEnvelopeError,
    CapabilityPolicyRecord,
    CapabilityPolicyValidationError,
    NatsKvCapabilityPolicyBackend,
    _record_to_envelope,
    key_for_policy_pair,
    pair_for_key,
)
from wirelang.schemas.registered_by_capability import (
    CapabilityPolicy,
    CapabilityPolicyRegistry,
    DecisionSource,
    check_registered_by_capability,
)
from wirelang.schemas.registry_nats_kv_backend import (
    SchemaRegistryEntry,
    schema_body_sha256,
)


# ---------------------------------------------------------------------------
# Mock KV (mirrors schema-registry-backend _MockKv shape)
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


def _make_entry_for_gate(
    *,
    layer: str = "wire",
    name: str = "layer-1-wire",
    version: str = "0.1.0",
    registered_by: str = "wirelang-eng",
) -> SchemaRegistryEntry:
    """Build a minimal SchemaRegistryEntry useful for gate-evaluation
    cross-checks. The schema-body is a minimal stub; the gate does
    NOT introspect schema_body, so the stub is sufficient.
    """
    schema_id = f"https://wakir.dev/wirelang/schemas/{layer}/{name}/{version}"
    schema_body = {"$id": schema_id, "type": "object"}
    return SchemaRegistryEntry(
        layer=layer,
        name=name,
        version=version,
        schema_id=schema_id,
        schema_body=schema_body,
        schema_body_sha256=schema_body_sha256(schema_body),
        registered_at=_REGISTERED_AT,
        registered_by=registered_by,
    )


# ---------------------------------------------------------------------------
# T-CPP-01: put round-trips through get
# ---------------------------------------------------------------------------


def test_t_cpp_01_put_round_trips_through_get():
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    record = _make_record()

    revision = asyncio.run(backend.put(record))
    assert revision == 1
    assert len(kv.store) == 1
    assert record.key in kv.store

    fetched = asyncio.run(backend.get(record.key))
    assert fetched is not None
    assert fetched.policy.registered_by == record.policy.registered_by
    assert fetched.policy.allowed_kids == record.policy.allowed_kids
    assert fetched.policy.allowed_triples == record.policy.allowed_triples
    assert fetched.policy.disabled == record.policy.disabled
    assert fetched.policy_id == record.policy_id
    assert fetched.registered_at == record.registered_at
    assert fetched.registered_by_publisher == record.registered_by_publisher


def test_t_cpp_01_get_by_pair_convenience_path():
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    record = _make_record()
    asyncio.run(backend.put(record))

    fetched = asyncio.run(
        backend.get_by_pair(record.policy.registered_by, record.policy_id)
    )
    assert fetched is not None
    assert fetched.key == record.key


# ---------------------------------------------------------------------------
# T-CPP-02: get on unknown key returns None
# ---------------------------------------------------------------------------


def test_t_cpp_02_get_unknown_key_returns_none():
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    result = asyncio.run(
        backend.get("capability-policies/wirelang-eng/missing")
    )
    assert result is None


def test_t_cpp_02_get_by_pair_unknown_returns_none():
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    result = asyncio.run(backend.get_by_pair("absent-issuer", "absent-pid"))
    assert result is None


# ---------------------------------------------------------------------------
# T-CPP-03: put is last-write-wins
# ---------------------------------------------------------------------------


def test_t_cpp_03_put_last_write_wins_same_pair():
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)

    first = _make_record(
        policy=_make_policy(
            allowed_kids=("biscuit-root-1",),
            allowed_triples=(("wire", "layer-1-*"),),
        )
    )
    second = _make_record(
        policy=_make_policy(
            allowed_kids=("biscuit-root-1", "biscuit-root-2"),
            allowed_triples=(("wire", "*"),),
            note="rotated kid added",
        )
    )

    asyncio.run(backend.put(first))
    asyncio.run(backend.put(second))

    fetched = asyncio.run(backend.get(first.key))
    assert fetched is not None
    assert fetched.policy.allowed_kids == ("biscuit-root-1", "biscuit-root-2")
    assert fetched.policy.allowed_triples == (("wire", "*"),)
    assert fetched.policy.note == "rotated kid added"
    assert kv.revision == 2


# ---------------------------------------------------------------------------
# T-CPP-04: delete removes record
# ---------------------------------------------------------------------------


def test_t_cpp_04_delete_removes_record():
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    record = _make_record()
    asyncio.run(backend.put(record))

    asyncio.run(backend.delete(record.key))
    assert asyncio.run(backend.get(record.key)) is None

    # Second delete is a no-op (idempotent).
    asyncio.run(backend.delete(record.key))
    assert asyncio.run(backend.get(record.key)) is None


# ---------------------------------------------------------------------------
# T-CPP-05: snapshot + snapshot_registry materialise a verifier surface
# ---------------------------------------------------------------------------


def test_t_cpp_05_snapshot_and_snapshot_registry_materialise():
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)

    r1 = _make_record(
        policy=_make_policy(
            registered_by="wirelang-eng",
            allowed_kids=("biscuit-root-1",),
            allowed_triples=(("wire", "layer-1-*"),),
        ),
        policy_id="default",
    )
    r2 = _make_record(
        policy=_make_policy(
            registered_by="wirelang-eng",
            allowed_kids=("biscuit-root-2",),
            allowed_triples=(("identity", "*"),),
        ),
        policy_id="identity-scope",
    )
    r3 = _make_record(
        policy=_make_policy(
            registered_by="federation-eng",
            allowed_kids=("biscuit-fed-1",),
            allowed_triples=(("federation", "*"),),
        ),
        policy_id="default",
    )
    for r in (r1, r2, r3):
        asyncio.run(backend.put(r))

    records = asyncio.run(backend.snapshot())
    assert len(records) == 3
    # snapshot is sorted by key for determinism.
    keys = [r.key for r in records]
    assert keys == sorted(keys)

    registry = asyncio.run(backend.snapshot_registry())
    assert isinstance(registry, CapabilityPolicyRegistry)
    assert set(registry.list_issuers()) == {"wirelang-eng", "federation-eng"}
    wirelang_policies = registry.policies_for("wirelang-eng")
    assert len(wirelang_policies) == 2
    fed_policies = registry.policies_for("federation-eng")
    assert len(fed_policies) == 1


# ---------------------------------------------------------------------------
# T-CPP-06: poisoned (non-JSON) value raises envelope error
# ---------------------------------------------------------------------------


def test_t_cpp_06_poisoned_envelope_raises_from_get_and_snapshot():
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    record = _make_record()
    asyncio.run(backend.put(record))

    # Poison the stored value directly.
    kv.store[record.key] = _MockKvEntry(value=b"not-json", revision=99)

    with pytest.raises(CapabilityPolicyEnvelopeError):
        asyncio.run(backend.get(record.key))

    with pytest.raises(CapabilityPolicyEnvelopeError):
        asyncio.run(backend.snapshot())


# ---------------------------------------------------------------------------
# T-CPP-07: wrong schema field rejected
# ---------------------------------------------------------------------------


def test_t_cpp_07_wrong_schema_field_rejected():
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)

    bad_payload = {
        "schema": "wakir.wirelang.wrong-envelope/1",
        "registered_by": "wirelang-eng",
        "policy_id": "default",
        "allowed_kids": ["biscuit-root-1"],
        "allowed_triples": [["wire", "*"]],
        "disabled": False,
        "registered_at": "2026-05-11T21:00:00Z",
        "registered_by_publisher": "wirelang-eng",
    }
    bad_blob = json.dumps(bad_payload, sort_keys=True).encode("utf-8")
    key = "capability-policies/wirelang-eng/default"
    kv.store[key] = _MockKvEntry(value=bad_blob, revision=1)

    with pytest.raises(CapabilityPolicyEnvelopeError) as excinfo:
        asyncio.run(backend.get(key))
    assert "schema mismatch" in str(excinfo.value)


# ---------------------------------------------------------------------------
# T-CPP-08: bucket-config constants byte-stable
# ---------------------------------------------------------------------------


def test_t_cpp_08_bucket_config_constants_byte_stable():
    """Drift-protection at the test layer.

    The Sprint-5 Tag-2 Kai-side paired-update memo lists these values
    byte-precisely. The orchestrator-side ``BucketSpec`` for the 7th
    bucket will mirror them byte-equal; any deviation surfaces as a
    failure on either side first.
    """
    assert BUCKET_NAME == "wakir-capability-policies"
    assert BUCKET_CONFIG["name"] == BUCKET_NAME
    assert BUCKET_CONFIG["history"] == 5
    assert BUCKET_CONFIG["ttl_seconds"] == 0
    assert BUCKET_CONFIG["max_value_size"] == 16_384
    assert BUCKET_CONFIG["storage"] == "file"
    assert BUCKET_CONFIG["replicas"] == 1
    assert "Phase-2" in BUCKET_CONFIG["description"]
    assert VALUE_SCHEMA == "wakir.wirelang.capability-policy-entry/1"


# ---------------------------------------------------------------------------
# T-CPP-09: multi-policy-per-issuer + gate evaluation
# ---------------------------------------------------------------------------


def test_t_cpp_09_multi_policy_per_issuer_round_trips_to_gate():
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)

    # Two policies for the same issuer, disjoint triple sets.
    p_wire = _make_record(
        policy=_make_policy(
            registered_by="wirelang-eng",
            allowed_kids=("biscuit-root-1",),
            allowed_triples=(("wire", "layer-1-*"),),
        ),
        policy_id="wire-scope",
    )
    p_identity = _make_record(
        policy=_make_policy(
            registered_by="wirelang-eng",
            allowed_kids=("biscuit-root-1",),
            allowed_triples=(("identity", "*"),),
        ),
        policy_id="identity-scope",
    )
    asyncio.run(backend.put(p_wire))
    asyncio.run(backend.put(p_identity))

    registry = asyncio.run(backend.snapshot_registry())

    # Wire-side triple: should allow.
    entry_wire = _make_entry_for_gate(layer="wire", name="layer-1-wire")
    sig_block = {"kid": "biscuit-root-1"}
    decision_wire = check_registered_by_capability(
        entry_wire, sig_block, registry
    )
    assert decision_wire.allowed is True
    assert decision_wire.source is DecisionSource.POLICY_MATCH

    # Identity-side triple: should allow (different policy in the
    # multi-policy-per-issuer registry).
    entry_identity = _make_entry_for_gate(
        layer="identity", name="aip-document"
    )
    decision_identity = check_registered_by_capability(
        entry_identity, sig_block, registry
    )
    assert decision_identity.allowed is True
    assert decision_identity.source is DecisionSource.POLICY_MATCH

    # Federation-side triple: not covered by either policy; should
    # deny with TRIPLE_NOT_ALLOWED.
    entry_fed = _make_entry_for_gate(
        layer="federation", name="federation-trust-document"
    )
    decision_fed = check_registered_by_capability(
        entry_fed, sig_block, registry
    )
    assert decision_fed.allowed is False
    assert decision_fed.source is DecisionSource.TRIPLE_NOT_ALLOWED


# ---------------------------------------------------------------------------
# T-CPP-10: snapshot determinism
# ---------------------------------------------------------------------------


def test_t_cpp_10_snapshot_determinism_back_to_back():
    kv = _MockKv()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    for pid in ("alpha", "beta", "gamma"):
        asyncio.run(
            backend.put(
                _make_record(
                    policy=_make_policy(
                        allowed_triples=((f"wire", f"{pid}-*"),)
                    ),
                    policy_id=pid,
                )
            )
        )

    snap_a = asyncio.run(backend.snapshot())
    snap_b = asyncio.run(backend.snapshot())

    keys_a = [r.key for r in snap_a]
    keys_b = [r.key for r in snap_b]
    assert keys_a == keys_b == sorted(keys_a)

    # Envelope round-trip yields byte-equal blobs.
    blobs_a = [_record_to_envelope(r) for r in snap_a]
    blobs_b = [_record_to_envelope(r) for r in snap_b]
    assert blobs_a == blobs_b


# ---------------------------------------------------------------------------
# T-CPP-aux-key-derivation: pair ↔ key bijection
# ---------------------------------------------------------------------------


class TestAuxKeyDerivation:
    """Bijection between ``(registered_by, policy_id)`` and the KV
    key string, plus negative-case rejection.
    """

    def test_round_trip_identity(self):
        for rb, pid in (
            ("wirelang-eng", "default"),
            ("wirelang-eng", "biscuit-root-1-rotation-2"),
            ("federation-eng", "fed-1"),
            ("aip:wakir.dev:root", "default"),
        ):
            k = key_for_policy_pair(rb, pid)
            assert pair_for_key(k) == (rb, pid)

    def test_empty_components_rejected(self):
        with pytest.raises(ValueError):
            key_for_policy_pair("", "default")
        with pytest.raises(ValueError):
            key_for_policy_pair("wirelang-eng", "")

    def test_slash_in_components_rejected(self):
        with pytest.raises(ValueError):
            key_for_policy_pair("wirelang/eng", "default")
        with pytest.raises(ValueError):
            key_for_policy_pair("wirelang-eng", "foo/bar")

    def test_invalid_characters_rejected(self):
        # Spaces and special chars outside the kebab-case ASCII set.
        with pytest.raises(ValueError):
            key_for_policy_pair("wirelang eng", "default")
        with pytest.raises(ValueError):
            key_for_policy_pair("wirelang-eng", "policy with spaces")

    def test_malformed_key_rejected(self):
        with pytest.raises(ValueError):
            pair_for_key("not-the-prefix/wirelang-eng/default")
        with pytest.raises(ValueError):
            pair_for_key("capability-policies/only-one-component")
        with pytest.raises(ValueError):
            pair_for_key(
                "capability-policies/wirelang-eng/policy/extra-component"
            )

    def test_non_string_inputs_rejected(self):
        with pytest.raises(ValueError):
            key_for_policy_pair(None, "default")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            pair_for_key(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# T-CPP-aux-envelope-shape: malformed-envelope rejection
# ---------------------------------------------------------------------------


class TestAuxEnvelopeShape:
    """Malformed envelopes raise :class:`CapabilityPolicyEnvelopeError`
    with informative messages.
    """

    def _put_raw(self, kv: _MockKv, key: str, payload: dict) -> None:
        blob = json.dumps(payload, sort_keys=True).encode("utf-8")
        kv.store[key] = _MockKvEntry(value=blob, revision=1)

    def _base_payload(self) -> dict:
        return {
            "schema": VALUE_SCHEMA,
            "registered_by": "wirelang-eng",
            "policy_id": "default",
            "allowed_kids": ["biscuit-root-1"],
            "allowed_triples": [["wire", "layer-1-*"]],
            "not_before": None,
            "not_after": None,
            "disabled": False,
            "note": None,
            "registered_at": "2026-05-11T21:00:00Z",
            "registered_by_publisher": "wirelang-eng",
        }

    def test_missing_required_field(self):
        kv = _MockKv()
        backend = NatsKvCapabilityPolicyBackend(kv=kv)
        payload = self._base_payload()
        del payload["allowed_kids"]
        self._put_raw(
            kv, "capability-policies/wirelang-eng/default", payload
        )
        with pytest.raises(CapabilityPolicyEnvelopeError) as excinfo:
            asyncio.run(backend.get("capability-policies/wirelang-eng/default"))
        assert "allowed_kids" in str(excinfo.value)

    def test_allowed_triples_not_a_list(self):
        kv = _MockKv()
        backend = NatsKvCapabilityPolicyBackend(kv=kv)
        payload = self._base_payload()
        payload["allowed_triples"] = {"wire": "layer-1-*"}
        self._put_raw(
            kv, "capability-policies/wirelang-eng/default", payload
        )
        with pytest.raises(CapabilityPolicyEnvelopeError) as excinfo:
            asyncio.run(backend.get("capability-policies/wirelang-eng/default"))
        assert "allowed_triples" in str(excinfo.value)

    def test_allowed_triples_inner_shape(self):
        kv = _MockKv()
        backend = NatsKvCapabilityPolicyBackend(kv=kv)
        payload = self._base_payload()
        payload["allowed_triples"] = [["wire", "layer-1-*", "extra-axis"]]
        self._put_raw(
            kv, "capability-policies/wirelang-eng/default", payload
        )
        with pytest.raises(CapabilityPolicyEnvelopeError):
            asyncio.run(backend.get("capability-policies/wirelang-eng/default"))

    def test_disabled_must_be_boolean(self):
        kv = _MockKv()
        backend = NatsKvCapabilityPolicyBackend(kv=kv)
        payload = self._base_payload()
        payload["disabled"] = "false"  # string, not bool
        self._put_raw(
            kv, "capability-policies/wirelang-eng/default", payload
        )
        with pytest.raises(CapabilityPolicyEnvelopeError) as excinfo:
            asyncio.run(backend.get("capability-policies/wirelang-eng/default"))
        assert "disabled" in str(excinfo.value)

    def test_empty_allowed_kids_rejected_via_policy_bundle(self):
        kv = _MockKv()
        backend = NatsKvCapabilityPolicyBackend(kv=kv)
        payload = self._base_payload()
        payload["allowed_kids"] = []  # CapabilityPolicy rejects empty
        self._put_raw(
            kv, "capability-policies/wirelang-eng/default", payload
        )
        with pytest.raises(CapabilityPolicyEnvelopeError) as excinfo:
            asyncio.run(backend.get("capability-policies/wirelang-eng/default"))
        # Wraps the underlying RegisteredByCapabilityError message.
        assert "allowed_kids" in str(excinfo.value)

    def test_record_validation_rejects_naive_registered_at(self):
        # Direct constructor test (bypasses the envelope path).
        with pytest.raises(CapabilityPolicyValidationError):
            CapabilityPolicyRecord(
                policy=_make_policy(),
                policy_id="default",
                registered_at=datetime(2026, 5, 11, 21, 0, 0),  # naive
                registered_by_publisher="wirelang-eng",
            )
