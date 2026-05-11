# SPDX-License-Identifier: Apache-2.0
"""Hermetic tests for the Wirelang capability-policy explicit-revocation
surface (Phase-2 Sprint-6 Tag-1, S6-1).

This is the Sprint-6 follow-on to Sprint-5 Tag-2..5 (capability-policy
NATS-KV backend, CAS-pin, watch-stream). Sprint-6 Tag-1 adds an
*explicit revocation* axis to :class:`CapabilityPolicy` that is
distinct from the Sprint-4 Tag-6 ``disabled`` soft kill-switch:

- ``revoked_at: Optional[datetime]`` — wall-clock instant at which the
  policy becomes categorically revoked (gate denies any ``as_of >=
  revoked_at`` with source ``POLICY_REVOKED``).
- ``revocation_reason: Optional[str]`` — free-form audit string.
- Top-precedence gate semantics: a revoked policy never produces an
  allow decision, regardless of disabled / kid / triple / window.
- Backend envelope-additive: ``revoked_at`` (RFC-3339 or null) and
  ``revocation_reason`` (string or null) extend the
  ``wakir.wirelang.capability-policy-entry/1`` envelope additively
  (M-2 conformance preserved; older envelopes decode byte-equally).
- Backend CAS-pin enforces *revocation-monotonicity*: a revoked
  policy cannot be un-revoked, nor can its revocation instant be
  advanced; equal-instant idempotent rewrites are permitted (so a
  ``revocation_reason`` refresh remains legal). LWW ``put`` does NOT
  enforce — consistent with the Sprint-5 Tag-4 "LWW is
  operator-deliberate, CAS-pin guards safety invariants" rationale.

Test inventory (T-CPP-REV-01..10 + 2 auxiliary probes):

- T-CPP-REV-01: CapabilityPolicy admits revoked_at + revocation_reason.
- T-CPP-REV-02: revocation_reason without revoked_at is rejected.
- T-CPP-REV-03: gate denies with POLICY_REVOKED when as_of >= revoked_at.
- T-CPP-REV-04: gate allows when as_of < revoked_at (precedes revocation).
- T-CPP-REV-05: gate denies with POLICY_REVOKED when as_of=None
  (categorical: a revoked policy never bypasses time-gating).
- T-CPP-REV-06: revocation outranks disabled / kid / triple / window
  in fallback ordering (mixed-state two-policy registry).
- T-CPP-REV-07: envelope round-trip preserves revoked_at +
  revocation_reason byte-equally.
- T-CPP-REV-08: envelope decoder admits older envelopes without
  the revocation keys (back-compat byte-equal).
- T-CPP-REV-09: put_with_revision rejects un-revoke
  (RevocationConflict; live revision unchanged).
- T-CPP-REV-10: put_with_revision admits equal-instant idempotent
  rewrite (revocation_reason refresh).
- T-CPP-REV-aux-advance-rejected: put_with_revision rejects an
  attempt to advance revoked_at strictly later.
- T-CPP-REV-aux-lww-allows-unrevoke: Sprint-5 Tag-2 LWW ``put`` does
  NOT enforce revocation-monotonicity (consistent with the Sprint-5
  Tag-4 LWW vs. CAS-pin safety-invariant policy).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pytest

from wirelang.schemas.capability_policy_nats_kv_backend import (
    CapabilityPolicyBackendError,
    CapabilityPolicyConflictError,
    CapabilityPolicyEnvelopeError,
    CapabilityPolicyRecord,
    CapabilityPolicyRevocationConflict,
    NatsKvCapabilityPolicyBackend,
    VALUE_SCHEMA,
    _envelope_to_record,
    _record_to_envelope,
)
from wirelang.schemas.registered_by_capability import (
    CapabilityGateDecision,
    CapabilityPolicy,
    CapabilityPolicyRegistry,
    DecisionSource,
    RegisteredByCapabilityError,
    check_registered_by_capability,
)
from wirelang.schemas.registry_nats_kv_backend import SchemaRegistryEntry


# ---------------------------------------------------------------------------
# Mock KV (CAS-aware, mirrors Sprint-5 Tag-4 test fixture shape)
# ---------------------------------------------------------------------------


class _MockKeyWrongLastSequenceError(Exception):
    def __init__(self, message: str, *, actual_revision: int) -> None:
        super().__init__(message)
        self.actual_revision = actual_revision


class _MockBucketNotFoundError(Exception):
    pass


@dataclass
class _MockKvEntry:
    value: bytes
    revision: int = 0


@dataclass
class _MockKvCas:
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
        existing = self.store.get(key)
        live_revision = existing.revision if existing is not None else 0
        if live_revision != last:
            raise _MockKeyWrongLastSequenceError(
                f"CAS conflict on {key!r}: expected last={last}, "
                f"actual={live_revision}",
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_REGISTERED_AT = datetime(2026, 5, 11, 21, 0, 0, tzinfo=timezone.utc)
_REVOKED_AT = datetime(2026, 5, 11, 22, 0, 0, tzinfo=timezone.utc)
_BEFORE_REVOKED = datetime(2026, 5, 11, 21, 30, 0, tzinfo=timezone.utc)
_AFTER_REVOKED = datetime(2026, 5, 11, 22, 30, 0, tzinfo=timezone.utc)
_REVOKED_AT_LATER = datetime(2026, 5, 11, 23, 0, 0, tzinfo=timezone.utc)
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
    revoked_at: Optional[datetime] = None,
    revocation_reason: Optional[str] = None,
) -> CapabilityPolicy:
    return CapabilityPolicy(
        registered_by=registered_by,
        allowed_kids=allowed_kids,
        allowed_triples=allowed_triples,
        not_before=not_before,
        not_after=not_after,
        disabled=disabled,
        note=note,
        revoked_at=revoked_at,
        revocation_reason=revocation_reason,
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


def _entry(
    registered_by: str = "wirelang-eng",
    layer: str = "wire",
    name: str = "layer-1-wire",
    version: str = "0.1.0",
) -> SchemaRegistryEntry:
    return SchemaRegistryEntry(
        layer=layer,
        name=name,
        version=version,
        schema_id=f"wakir.{layer}.{name}/{version}",
        schema_body={"type": "object"},
        schema_body_sha256="a" * 64,
        registered_at=_REGISTERED_AT,
        registered_by=registered_by,
    )


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# T-CPP-REV-01: bundle admits revoked_at + revocation_reason
# ---------------------------------------------------------------------------


def test_t_cpp_rev_01_bundle_admits_revoked_fields():
    """T-CPP-REV-01: a CapabilityPolicy admits ``revoked_at`` and
    ``revocation_reason``; both fields default to ``None`` (unrevoked).
    """
    p_unrevoked = _make_policy()
    assert p_unrevoked.revoked_at is None
    assert p_unrevoked.revocation_reason is None

    p_revoked = _make_policy(
        revoked_at=_REVOKED_AT,
        revocation_reason="key compromise reported by audit",
    )
    assert p_revoked.revoked_at == _REVOKED_AT
    assert p_revoked.revocation_reason == "key compromise reported by audit"
    # Naive datetime is rejected.
    with pytest.raises(RegisteredByCapabilityError):
        _make_policy(revoked_at=datetime(2026, 5, 11, 22, 0, 0))


# ---------------------------------------------------------------------------
# T-CPP-REV-02: revocation_reason without revoked_at is rejected
# ---------------------------------------------------------------------------


def test_t_cpp_rev_02_reason_requires_revoked_at():
    """T-CPP-REV-02: a ``revocation_reason`` with no ``revoked_at`` is
    structurally invalid; the bundle constructor raises.
    """
    with pytest.raises(RegisteredByCapabilityError):
        _make_policy(revocation_reason="orphaned reason")


# ---------------------------------------------------------------------------
# T-CPP-REV-03: gate denies POLICY_REVOKED when as_of >= revoked_at
# ---------------------------------------------------------------------------


def test_t_cpp_rev_03_gate_denies_revoked_when_as_of_at_or_after():
    """T-CPP-REV-03: when ``as_of >= revoked_at``, the gate denies with
    ``DecisionSource.POLICY_REVOKED``. The reason includes the
    ``revoked_at`` instant; if ``revocation_reason`` is set, it is
    surfaced in the reason string (audit aid).
    """
    policy = _make_policy(
        revoked_at=_REVOKED_AT,
        revocation_reason="key compromise reported by audit",
    )
    registry = CapabilityPolicyRegistry()
    registry.add_policy(policy)
    entry = _entry()
    sig = {"kid": "biscuit-root-1"}

    # Exactly at the revocation instant: revoked.
    d_at = check_registered_by_capability(entry, sig, registry, as_of=_REVOKED_AT)
    assert d_at.allowed is False
    assert d_at.source is DecisionSource.POLICY_REVOKED
    assert "revoked" in d_at.reason
    assert "key compromise reported by audit" in d_at.reason

    # Strictly after: revoked.
    d_after = check_registered_by_capability(
        entry, sig, registry, as_of=_AFTER_REVOKED
    )
    assert d_after.allowed is False
    assert d_after.source is DecisionSource.POLICY_REVOKED


# ---------------------------------------------------------------------------
# T-CPP-REV-04: gate allows when as_of < revoked_at
# ---------------------------------------------------------------------------


def test_t_cpp_rev_04_gate_allows_before_revoked_at():
    """T-CPP-REV-04: when ``as_of < revoked_at``, the gate evaluates
    the policy normally (revocation has not yet taken effect).
    """
    policy = _make_policy(revoked_at=_REVOKED_AT)
    registry = CapabilityPolicyRegistry()
    registry.add_policy(policy)
    entry = _entry()
    sig = {"kid": "biscuit-root-1"}

    decision = check_registered_by_capability(
        entry, sig, registry, as_of=_BEFORE_REVOKED
    )
    assert decision.allowed is True
    assert decision.source is DecisionSource.POLICY_MATCH


# ---------------------------------------------------------------------------
# T-CPP-REV-05: gate denies POLICY_REVOKED when as_of=None
# ---------------------------------------------------------------------------


def test_t_cpp_rev_05_gate_denies_revoked_when_as_of_none():
    """T-CPP-REV-05: revocation is *categorical* — a revoked policy
    denies even when the caller omits ``as_of``. This is deliberately
    stricter than the ``not_before`` / ``not_after`` window semantics
    (which skip when ``as_of=None``); a revocation must never be
    silently bypassed by a verifier that omits a clock.
    """
    policy = _make_policy(revoked_at=_REVOKED_AT)
    registry = CapabilityPolicyRegistry()
    registry.add_policy(policy)
    entry = _entry()
    sig = {"kid": "biscuit-root-1"}

    decision = check_registered_by_capability(entry, sig, registry)
    assert decision.allowed is False
    assert decision.source is DecisionSource.POLICY_REVOKED


# ---------------------------------------------------------------------------
# T-CPP-REV-06: revocation outranks disabled / kid / triple / window
# ---------------------------------------------------------------------------


def test_t_cpp_rev_06_revocation_outranks_other_fallbacks():
    """T-CPP-REV-06: when an issuer carries a mix of fallback-deny
    candidates (one revoked, one with kid-mismatch, one disabled), the
    final decision is POLICY_REVOKED — revocation outranks the other
    fallback sources in the gate's deny-source ordering.
    """
    revoked_policy = _make_policy(
        registered_by="wirelang-eng",
        allowed_kids=("biscuit-root-old",),
        revoked_at=_REVOKED_AT,
    )
    kid_mismatch_policy = _make_policy(
        registered_by="wirelang-eng",
        allowed_kids=("biscuit-root-2",),
    )
    disabled_policy = _make_policy(
        registered_by="wirelang-eng",
        allowed_kids=("biscuit-root-3",),
        disabled=True,
    )
    registry = CapabilityPolicyRegistry()
    # Insert in a non-revoked-first order to verify ordering is by
    # priority not by insertion.
    registry.add_policy(disabled_policy)
    registry.add_policy(kid_mismatch_policy)
    registry.add_policy(revoked_policy)
    entry = _entry()
    sig = {"kid": "biscuit-root-1"}

    decision = check_registered_by_capability(
        entry, sig, registry, as_of=_AFTER_REVOKED
    )
    assert decision.allowed is False
    assert decision.source is DecisionSource.POLICY_REVOKED
    assert decision.policy == revoked_policy


# ---------------------------------------------------------------------------
# T-CPP-REV-07: envelope round-trip preserves revoked_at + reason
# ---------------------------------------------------------------------------


def test_t_cpp_rev_07_envelope_round_trip_preserves_revocation_fields():
    """T-CPP-REV-07: ``_record_to_envelope`` / ``_envelope_to_record``
    round-trip a record carrying ``revoked_at`` + ``revocation_reason``
    byte-equally. The serialised JSON contains both keys; the decoded
    record carries the same tz-aware datetime (UTC-normalised).
    """
    policy = _make_policy(
        revoked_at=_REVOKED_AT,
        revocation_reason="key compromise reported by audit",
    )
    record = _make_record(policy=policy)
    blob = _record_to_envelope(record)
    parsed = json.loads(blob.decode("utf-8"))
    assert "revoked_at" in parsed
    assert "revocation_reason" in parsed
    assert parsed["revocation_reason"] == "key compromise reported by audit"
    assert parsed["revoked_at"].endswith("Z")

    decoded = _envelope_to_record(blob)
    assert decoded.policy.revoked_at == _REVOKED_AT
    assert (
        decoded.policy.revocation_reason
        == "key compromise reported by audit"
    )
    assert decoded.policy.registered_by == record.policy.registered_by
    assert decoded.policy_id == record.policy_id


# ---------------------------------------------------------------------------
# T-CPP-REV-08: envelope back-compat — older envelope without revocation keys
# ---------------------------------------------------------------------------


def test_t_cpp_rev_08_envelope_back_compat_without_revocation_keys():
    """T-CPP-REV-08: an envelope from Sprint-5 Tag-2..5 (no
    ``revoked_at`` / ``revocation_reason`` keys) decodes byte-equally
    via the additive Sprint-6 Tag-1 decoder to an unrevoked policy.
    """
    legacy_payload = {
        "schema": VALUE_SCHEMA,
        "registered_by": "wirelang-eng",
        "policy_id": "legacy",
        "allowed_kids": ["biscuit-root-1"],
        "allowed_triples": [["wire", "layer-1-*"]],
        "not_before": None,
        "not_after": None,
        "disabled": False,
        "note": None,
        "registered_at": _REGISTERED_AT.isoformat().replace("+00:00", "Z"),
        "registered_by_publisher": _REGISTERED_BY_PUBLISHER,
        # Note: no revoked_at, no revocation_reason.
    }
    blob = json.dumps(
        legacy_payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    decoded = _envelope_to_record(blob)
    assert decoded.policy.revoked_at is None
    assert decoded.policy.revocation_reason is None
    assert decoded.policy_id == "legacy"


# ---------------------------------------------------------------------------
# T-CPP-REV-09: put_with_revision rejects un-revoke
# ---------------------------------------------------------------------------


def test_t_cpp_rev_09_put_with_revision_rejects_un_revoke():
    """T-CPP-REV-09: CAS-pin path enforces revocation-monotonicity.
    Once a policy is revoked, a subsequent ``put_with_revision`` with
    ``revoked_at=None`` is rejected with
    :class:`CapabilityPolicyRevocationConflict`; the live KV revision
    is unchanged.
    """
    kv = _MockKvCas()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    revoked_record = _make_record(
        policy=_make_policy(
            revoked_at=_REVOKED_AT,
            revocation_reason="initial revocation",
        )
    )
    unrevoke_attempt = _make_record(
        policy=_make_policy()  # revoked_at=None
    )

    async def _go():
        rev_revoked = await backend.put(revoked_record)
        try:
            await backend.put_with_revision(unrevoke_attempt, rev_revoked)
        except CapabilityPolicyRevocationConflict as exc:
            # Live revision unchanged: still rev_revoked.
            entry = await kv.get(revoked_record.key)
            return rev_revoked, exc, entry.revision
        return rev_revoked, None, None

    rev_revoked, exc, post_revision = _run(_go())
    assert exc is not None
    assert exc.key == revoked_record.key
    assert exc.existing_revoked_at == _REVOKED_AT
    assert exc.proposed_revoked_at is None
    assert post_revision == rev_revoked


# ---------------------------------------------------------------------------
# T-CPP-REV-10: put_with_revision admits equal-instant idempotent rewrite
# ---------------------------------------------------------------------------


def test_t_cpp_rev_10_put_with_revision_admits_idempotent_revoked_rewrite():
    """T-CPP-REV-10: a CAS-pin write that preserves ``revoked_at``
    byte-equally is permitted (e.g. a ``revocation_reason`` refresh
    for audit). Live KV revision advances by one.
    """
    kv = _MockKvCas()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    initial = _make_record(
        policy=_make_policy(
            revoked_at=_REVOKED_AT,
            revocation_reason="initial revocation",
        )
    )
    refresh = _make_record(
        policy=_make_policy(
            revoked_at=_REVOKED_AT,
            revocation_reason="audit-trail refresh: ticket CR-42",
        )
    )

    async def _go():
        rev_initial = await backend.put(initial)
        rev_refresh = await backend.put_with_revision(refresh, rev_initial)
        live = await backend.get(refresh.key)
        return rev_initial, rev_refresh, live

    rev_initial, rev_refresh, live = _run(_go())
    assert rev_refresh > rev_initial
    assert live is not None
    assert live.policy.revoked_at == _REVOKED_AT
    assert live.policy.revocation_reason == (
        "audit-trail refresh: ticket CR-42"
    )


# ---------------------------------------------------------------------------
# T-CPP-REV-aux-advance-rejected: cannot advance revoked_at later
# ---------------------------------------------------------------------------


def test_t_cpp_rev_aux_advance_rejected():
    """T-CPP-REV-aux: a CAS-pin write that advances ``revoked_at``
    strictly later than the live instant is rejected.
    Revocation cannot be retroactively softened.
    """
    kv = _MockKvCas()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    initial = _make_record(
        policy=_make_policy(revoked_at=_REVOKED_AT)
    )
    advance_attempt = _make_record(
        policy=_make_policy(
            revoked_at=_REVOKED_AT_LATER,
            revocation_reason="late softening attempt",
        )
    )

    async def _go():
        rev_initial = await backend.put(initial)
        try:
            await backend.put_with_revision(advance_attempt, rev_initial)
        except CapabilityPolicyRevocationConflict as exc:
            entry = await kv.get(initial.key)
            return exc, entry.revision, rev_initial
        return None, None, rev_initial

    exc, post_revision, rev_initial = _run(_go())
    assert exc is not None
    assert exc.existing_revoked_at == _REVOKED_AT
    assert exc.proposed_revoked_at == _REVOKED_AT_LATER
    assert post_revision == rev_initial


# ---------------------------------------------------------------------------
# T-CPP-REV-aux-lww-allows-unrevoke: LWW path does NOT enforce monotonicity
# ---------------------------------------------------------------------------


def test_t_cpp_rev_aux_lww_does_not_enforce_revocation_monotonic():
    """T-CPP-REV-aux: the Sprint-5 Tag-2 LWW ``put`` path does NOT
    enforce revocation-monotonicity. This is consistent with the
    Sprint-5 Tag-4 rationale: LWW writes are operator-deliberate, the
    CAS-pin path is the safety-invariant guard. An operator who
    deliberately wants to un-revoke must use the LWW path AND accept
    the audit consequences (the revocation event remains in the
    bucket history depth).
    """
    kv = _MockKvCas()
    backend = NatsKvCapabilityPolicyBackend(kv=kv)
    revoked = _make_record(
        policy=_make_policy(revoked_at=_REVOKED_AT)
    )
    unrevoke = _make_record(policy=_make_policy())

    async def _go():
        await backend.put(revoked)
        # LWW: not guarded.
        rev = await backend.put(unrevoke)
        live = await backend.get(revoked.key)
        return rev, live

    rev, live = _run(_go())
    assert rev >= 2
    assert live is not None
    assert live.policy.revoked_at is None
