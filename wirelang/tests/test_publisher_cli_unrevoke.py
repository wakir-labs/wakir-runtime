# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``wirelang.schemas.publisher_cli`` ``unrevoke``.

Phase-2 Sprint-6 Tag-7 — Publisher-CLI ``unrevoke`` subcommand.
End-to-end operator-experience: CLI → NATS-KV
(``wakir-capability-policies``) → LWW write (Sprint-6 Tag-1 backend
revocation-monotonic invariant is bypassed BY DESIGN; the unrevoke
gesture is structurally LWW because the CAS-pin path forbids
``revoked_at=None`` against a live revoked record) → typed exit codes.

The Sprint-6 Tag-7 test inventory pins eight concerns (T-SR-UREV-01..08):

- T-SR-UREV-01: happy path — live record is revoked, unrevoke writes
  a record with ``revoked_at=None`` / ``revocation_reason=None`` via
  LWW; receipt records ``cmd='unrevoke'``, ``mode='lww'``,
  ``previous_revoked_at``, ``previous_revocation_reason``,
  ``previous_revision`` / ``new_revision`` pair.
- T-SR-UREV-02: bundle preservation — every non-revocation capability-
  bundle field (allowed_kids, allowed_triples, disabled, note,
  not_before, not_after) is byte-equal on the rewritten unrevoked
  record.
- T-SR-UREV-03: target-not-revoked — live record exists but is NOT
  revoked; CLI surfaces :class:`ExitCode.UNREVOKE_TARGET_NOT_REVOKED`
  (10), distinct from REVOKE_TARGET_NOT_FOUND. Bucket state unchanged.
- T-SR-UREV-04: target-not-found — non-existent (registered_by,
  policy_id) surfaces :class:`ExitCode.REVOKE_TARGET_NOT_FOUND` (9)
  (reused — the "not found" semantics are identical for both subcommands).
- T-SR-UREV-05: ``--registered-by-publisher`` non-empty — empty string
  surfaces INPUT_ERROR (3).
- T-SR-UREV-06: ``--unrevoke-reason`` audit-trail surfaces on the
  receipt but is NOT persisted on the rewritten record (the record is
  byte-equal to a fresh unrevoked policy modulo registered_at /
  registered_by_publisher).
- T-SR-UREV-07: argparse rejects ``--lww`` and ``--expected-revision``
  on the unrevoke subcommand (these flags are absent by design;
  argparse usage error exit 2).
- T-SR-UREV-08: round-trip — revoke a policy, then unrevoke it; the
  unrevoke receipt's ``previous_revoked_at`` byte-equals the revoke
  receipt's ``revoked_at``; subsequent revoke of the same policy
  succeeds (the policy is back in the unrevoked state and a fresh
  revoke is no longer monotonicity-bound).

Hermetic
--------

- No NATS, no real transport.
- Reuses the same in-memory ``_MockKvCapability`` shape as the
  Sprint-6 Tag-2 ``revoke`` tests; the mock tracks revisions across
  get/put so LWW vs. CAS-pin distinctions are byte-precisely
  asserted.
- The capability-bucket factory is injected via the public
  ``capability_bucket_factory`` argument of ``run()``.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pytest

from wirelang.schemas.capability_policy_nats_kv_backend import (
    BUCKET_NAME as CAPABILITY_BUCKET_NAME,
    CapabilityPolicyRecord,
    NatsKvCapabilityPolicyBackend,
    _record_to_envelope,
    _envelope_to_record,
    key_for_policy_pair,
)
from wirelang.schemas.publisher_cli import (
    ExitCode,
    UnrevokeReceipt,
    build_parser,
    run,
)
from wirelang.schemas.registered_by_capability import (
    CapabilityPolicy,
)


# ---------------------------------------------------------------------------
# In-memory KV mock (mirror of Sprint-6 Tag-2 fixture)
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
class _MockKvCapability:
    """CAS-aware capability-policy KV mock (Sprint-6 Tag-2 mirror)."""

    bucket: str = CAPABILITY_BUCKET_NAME
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


def _make_capability_factory(
    kv: _MockKvCapability, *, cleanup_log: list | None = None
):
    async def _factory(_connect_url: str):
        backend = NatsKvCapabilityPolicyBackend(kv=kv)

        async def _cleanup() -> None:
            if cleanup_log is not None:
                cleanup_log.append("cleanup")

        return backend, _cleanup

    return _factory


def _io_streams() -> tuple[io.StringIO, io.StringIO]:
    return io.StringIO(), io.StringIO()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_REGISTERED_AT_BUCKET = datetime(2026, 5, 11, 13, 0, 0, tzinfo=timezone.utc)
_REVOKED_AT = datetime(2026, 5, 11, 22, 0, 0, tzinfo=timezone.utc)
_REVOKED_AT_STR = "2026-05-11T22:00:00Z"
_REVOCATION_REASON = "key compromise reported by audit"
_REGISTERED_AT_UNREVOKE_STR = "2026-05-12T10:00:00Z"
_REGISTERED_AT_UNREVOKE = datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)


def _make_policy(
    *,
    registered_by: str = "wirelang-eng",
    allowed_kids: tuple = ("biscuit-root-1", "biscuit-root-2"),
    allowed_triples: tuple = (("wire", "layer-1-*"), ("agent", "*")),
    disabled: bool = False,
    note: Optional[str] = "audit-note",
    revoked_at: Optional[datetime] = None,
    revocation_reason: Optional[str] = None,
    not_before: Optional[datetime] = None,
    not_after: Optional[datetime] = None,
) -> CapabilityPolicy:
    return CapabilityPolicy(
        registered_by=registered_by,
        allowed_kids=allowed_kids,
        allowed_triples=allowed_triples,
        disabled=disabled,
        note=note,
        revoked_at=revoked_at,
        revocation_reason=revocation_reason,
        not_before=not_before,
        not_after=not_after,
    )


def _make_record(
    *,
    policy: Optional[CapabilityPolicy] = None,
    policy_id: str = "default",
    registered_by_publisher: str = "ops-eng",
) -> CapabilityPolicyRecord:
    if policy is None:
        policy = _make_policy()
    return CapabilityPolicyRecord(
        policy=policy,
        policy_id=policy_id,
        registered_at=_REGISTERED_AT_BUCKET,
        registered_by_publisher=registered_by_publisher,
    )


def _seed_bucket(
    kv: _MockKvCapability, *records: CapabilityPolicyRecord
) -> None:
    for record in records:
        kv.store[record.key] = _MockKvEntry(
            value=_record_to_envelope(record),
            revision=kv.revision + 1,
        )
        kv.revision += 1


def _unrevoke_argv(
    *,
    registered_by: str = "wirelang-eng",
    policy_id: str = "default",
    registered_by_publisher: str = "incident-responder-2",
    unrevoke_reason: Optional[str] = (
        "post-incident review: original revocation rescinded"
    ),
    registered_at: Optional[str] = _REGISTERED_AT_UNREVOKE_STR,
) -> list[str]:
    argv = [
        "unrevoke",
        "--registered-by",
        registered_by,
        "--policy-id",
        policy_id,
        "--registered-by-publisher",
        registered_by_publisher,
    ]
    if unrevoke_reason is not None:
        argv.extend(["--unrevoke-reason", unrevoke_reason])
    if registered_at is not None:
        argv.extend(["--registered-at", registered_at])
    return argv


# ---------------------------------------------------------------------------
# T-SR-UREV-01: happy path
# ---------------------------------------------------------------------------


class TestTSRUREV01HappyPath:
    """T-SR-UREV-01: revoked target → unrevoke writes revoked_at=None /
    revocation_reason=None via LWW; receipt records the prior
    revocation state for audit traceability.
    """

    def test_unrevoke_happy_path(self):
        kv = _MockKvCapability()
        revoked_policy = _make_policy(
            revoked_at=_REVOKED_AT,
            revocation_reason=_REVOCATION_REASON,
        )
        _seed_bucket(kv, _make_record(policy=revoked_policy))
        live_revision_before = kv.revision  # 1

        out, err = _io_streams()
        cleanup_log: list = []
        code = run(
            _unrevoke_argv(),
            capability_bucket_factory=_make_capability_factory(
                kv, cleanup_log=cleanup_log
            ),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.OK), err.getvalue()
        receipt = json.loads(out.getvalue())
        assert receipt["cmd"] == "unrevoke"
        assert receipt["mode"] == "lww"
        assert receipt["registered_by"] == "wirelang-eng"
        assert receipt["policy_id"] == "default"
        assert receipt["previous_revoked_at"] == _REVOKED_AT_STR
        assert receipt["previous_revocation_reason"] == _REVOCATION_REASON
        assert receipt["previous_revision"] == live_revision_before
        assert receipt["new_revision"] == live_revision_before + 1
        assert receipt["registered_at"] == _REGISTERED_AT_UNREVOKE_STR
        assert receipt["registered_by_publisher"] == (
            "incident-responder-2"
        )
        assert receipt["unrevoke_reason"] == (
            "post-incident review: original revocation rescinded"
        )
        assert receipt["key"] == key_for_policy_pair(
            "wirelang-eng", "default"
        )

        # Bucket state: revocation is cleared.
        key = key_for_policy_pair("wirelang-eng", "default")
        live = _envelope_to_record(kv.store[key].value)
        assert live.policy.revoked_at is None
        assert live.policy.revocation_reason is None
        # Cleanup ran.
        assert cleanup_log == ["cleanup"]


# ---------------------------------------------------------------------------
# T-SR-UREV-02: bundle preservation
# ---------------------------------------------------------------------------


class TestTSRUREV02BundlePreservation:
    """T-SR-UREV-02: every non-revocation capability-bundle field is
    byte-equal on the rewritten unrevoked record.
    """

    def test_bundle_fields_preserved_byte_equally(self):
        kv = _MockKvCapability()
        not_before = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        not_after = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        revoked_policy = _make_policy(
            allowed_kids=("biscuit-root-1", "biscuit-root-2", "biscuit-root-3"),
            allowed_triples=(
                ("wire", "layer-1-*"),
                ("agent", "*"),
                ("schema", "v2"),
            ),
            disabled=False,
            note="critical-bundle-note",
            revoked_at=_REVOKED_AT,
            revocation_reason="provisional revocation pending review",
            not_before=not_before,
            not_after=not_after,
        )
        _seed_bucket(kv, _make_record(policy=revoked_policy))

        out, err = _io_streams()
        code = run(
            _unrevoke_argv(),
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.OK), err.getvalue()

        key = key_for_policy_pair("wirelang-eng", "default")
        live = _envelope_to_record(kv.store[key].value)
        assert live.policy.allowed_kids == (
            "biscuit-root-1",
            "biscuit-root-2",
            "biscuit-root-3",
        )
        assert live.policy.allowed_triples == (
            ("wire", "layer-1-*"),
            ("agent", "*"),
            ("schema", "v2"),
        )
        assert live.policy.disabled is False
        assert live.policy.note == "critical-bundle-note"
        assert live.policy.not_before == not_before
        assert live.policy.not_after == not_after
        # Revocation cleared.
        assert live.policy.revoked_at is None
        assert live.policy.revocation_reason is None


# ---------------------------------------------------------------------------
# T-SR-UREV-03: target-not-revoked surfaces UNREVOKE_TARGET_NOT_REVOKED (10)
# ---------------------------------------------------------------------------


class TestTSRUREV03TargetNotRevoked:
    """T-SR-UREV-03: live record exists but is NOT revoked; CLI surfaces
    UNREVOKE_TARGET_NOT_REVOKED (10) and the bucket is not touched.
    """

    def test_unrevoke_unrevoked_target_refused(self):
        kv = _MockKvCapability()
        unrevoked_policy = _make_policy()  # revoked_at=None by default
        _seed_bucket(kv, _make_record(policy=unrevoked_policy))
        live_revision_before = kv.revision

        out, err = _io_streams()
        code = run(
            _unrevoke_argv(),
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.UNREVOKE_TARGET_NOT_REVOKED)
        assert out.getvalue() == ""
        err_payload = json.loads(err.getvalue())
        assert err_payload["error"] == "UNREVOKE_TARGET_NOT_REVOKED"
        assert err_payload["exit_code"] == 10
        assert "not currently revoked" in err_payload["message"]
        # Bucket state unchanged.
        assert kv.revision == live_revision_before


# ---------------------------------------------------------------------------
# T-SR-UREV-04: target-not-found surfaces REVOKE_TARGET_NOT_FOUND (9)
# ---------------------------------------------------------------------------


class TestTSRUREV04TargetNotFound:
    """T-SR-UREV-04: non-existent target surfaces REVOKE_TARGET_NOT_FOUND
    (reused; the "not found" semantics are identical for both subcommands).
    """

    def test_unrevoke_missing_target(self):
        kv = _MockKvCapability()
        # Bucket is empty.

        out, err = _io_streams()
        code = run(
            _unrevoke_argv(
                registered_by="never-existed",
                policy_id="never-existed-policy",
            ),
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.REVOKE_TARGET_NOT_FOUND)
        assert out.getvalue() == ""
        err_payload = json.loads(err.getvalue())
        assert err_payload["error"] == "REVOKE_TARGET_NOT_FOUND"
        assert err_payload["exit_code"] == 9
        assert "never-existed" in err_payload["message"]


# ---------------------------------------------------------------------------
# T-SR-UREV-05: --registered-by-publisher non-empty (INPUT_ERROR 3)
# ---------------------------------------------------------------------------


class TestTSRUREV05RegisteredByPublisherNonEmpty:
    """T-SR-UREV-05: an empty --registered-by-publisher is rejected
    pre-connect with INPUT_ERROR (3).
    """

    def test_empty_registered_by_publisher_rejected(self):
        kv = _MockKvCapability()
        revoked_policy = _make_policy(
            revoked_at=_REVOKED_AT, revocation_reason=_REVOCATION_REASON
        )
        _seed_bucket(kv, _make_record(policy=revoked_policy))
        live_revision_before = kv.revision

        out, err = _io_streams()
        code = run(
            _unrevoke_argv(registered_by_publisher="   "),
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.INPUT_ERROR)
        err_payload = json.loads(err.getvalue())
        assert err_payload["error"] == "INPUT_ERROR"
        assert "registered-by-publisher" in err_payload["message"]
        # Bucket state unchanged (pre-connect refusal).
        assert kv.revision == live_revision_before


# ---------------------------------------------------------------------------
# T-SR-UREV-06: --unrevoke-reason on receipt only, not persisted
# ---------------------------------------------------------------------------


class TestTSRUREV06UnrevokeReasonAuditOnly:
    """T-SR-UREV-06: --unrevoke-reason surfaces on the receipt but is
    NOT persisted on the rewritten record. The rewritten record is
    byte-equal to a fresh unrevoked policy (modulo registered_at /
    registered_by_publisher bookkeeping).
    """

    def test_unrevoke_reason_audit_only_not_persisted(self):
        kv = _MockKvCapability()
        revoked_policy = _make_policy(
            revoked_at=_REVOKED_AT, revocation_reason=_REVOCATION_REASON
        )
        _seed_bucket(kv, _make_record(policy=revoked_policy))

        out, err = _io_streams()
        code = run(
            _unrevoke_argv(
                unrevoke_reason="ticket-12345: revocation rescinded by IR"
            ),
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.OK), err.getvalue()
        receipt = json.loads(out.getvalue())
        assert receipt["unrevoke_reason"] == (
            "ticket-12345: revocation rescinded by IR"
        )

        # The rewritten record carries NO trace of the unrevoke reason.
        key = key_for_policy_pair("wirelang-eng", "default")
        live = _envelope_to_record(kv.store[key].value)
        assert live.policy.revoked_at is None
        assert live.policy.revocation_reason is None
        # No "unrevoke_reason" field is added to the policy bundle.
        assert not hasattr(live.policy, "unrevoke_reason")


# ---------------------------------------------------------------------------
# T-SR-UREV-07: argparse rejects --lww / --expected-revision
# ---------------------------------------------------------------------------


class TestTSRUREV07ArgparseSurfaceNarrow:
    """T-SR-UREV-07: --lww and --expected-revision are absent on the
    unrevoke subcommand by design (the unrevoke path is structurally
    LWW-only). argparse surfaces both as usage errors (exit 2).
    """

    def test_lww_flag_not_present(self):
        parser = build_parser()
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(
                _unrevoke_argv(registered_at=None) + ["--lww"]
            )
        assert excinfo.value.code == 2

    def test_expected_revision_flag_not_present(self):
        parser = build_parser()
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(
                _unrevoke_argv(registered_at=None)
                + ["--expected-revision", "1"]
            )
        assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# T-SR-UREV-08: revoke → unrevoke round-trip
# ---------------------------------------------------------------------------


class TestTSRUREV08RevokeUnrevokeRoundTrip:
    """T-SR-UREV-08: revoke a policy via the Tag-2 revoke subcommand,
    then unrevoke it via the Tag-7 unrevoke subcommand; verify the
    audit-trail correlation (unrevoke.previous_revoked_at ==
    revoke.revoked_at) and that a subsequent re-revoke succeeds (the
    policy is back in the unrevoked state, so revocation-monotonic
    has nothing to enforce).
    """

    def test_revoke_then_unrevoke_round_trip(self):
        kv = _MockKvCapability()
        unrevoked = _make_policy()
        _seed_bucket(kv, _make_record(policy=unrevoked))

        # Step 1: revoke.
        out1, err1 = _io_streams()
        revoke_argv = [
            "revoke",
            "--registered-by",
            "wirelang-eng",
            "--policy-id",
            "default",
            "--revoked-at",
            _REVOKED_AT_STR,
            "--revocation-reason",
            _REVOCATION_REASON,
            "--registered-by-publisher",
            "incident-responder-1",
            "--registered-at",
            "2026-05-11T22:15:00Z",
        ]
        code1 = run(
            revoke_argv,
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out1,
            stderr=err1,
        )
        assert code1 == int(ExitCode.OK), err1.getvalue()
        revoke_receipt = json.loads(out1.getvalue())
        assert revoke_receipt["cmd"] == "revoke"
        assert revoke_receipt["revoked_at"] == _REVOKED_AT_STR

        # Step 2: unrevoke.
        out2, err2 = _io_streams()
        code2 = run(
            _unrevoke_argv(),
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out2,
            stderr=err2,
        )
        assert code2 == int(ExitCode.OK), err2.getvalue()
        unrevoke_receipt = json.loads(out2.getvalue())
        assert unrevoke_receipt["cmd"] == "unrevoke"
        # Audit-trail correlation: unrevoke records the prior revoked_at
        # byte-equally.
        assert (
            unrevoke_receipt["previous_revoked_at"]
            == revoke_receipt["revoked_at"]
        )
        assert (
            unrevoke_receipt["previous_revocation_reason"]
            == revoke_receipt["revocation_reason"]
        )
        # Revisions chain.
        assert (
            unrevoke_receipt["previous_revision"]
            == revoke_receipt["new_revision"]
        )
        assert (
            unrevoke_receipt["new_revision"]
            == revoke_receipt["new_revision"] + 1
        )

        # Step 3: re-revoke at a NEW instant succeeds (the policy is
        # back in the unrevoked state; monotonicity has no prior
        # revocation to defend).
        out3, err3 = _io_streams()
        new_revoke_argv = [
            "revoke",
            "--registered-by",
            "wirelang-eng",
            "--policy-id",
            "default",
            "--revoked-at",
            "2026-05-13T12:00:00Z",
            "--revocation-reason",
            "second incident",
            "--registered-by-publisher",
            "incident-responder-3",
            "--registered-at",
            "2026-05-13T12:05:00Z",
        ]
        code3 = run(
            new_revoke_argv,
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out3,
            stderr=err3,
        )
        assert code3 == int(ExitCode.OK), err3.getvalue()
        revoke2_receipt = json.loads(out3.getvalue())
        assert revoke2_receipt["revoked_at"] == "2026-05-13T12:00:00Z"
        # Final bucket state: re-revoked.
        key = key_for_policy_pair("wirelang-eng", "default")
        live = _envelope_to_record(kv.store[key].value)
        assert live.policy.revoked_at == datetime(
            2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc
        )
        assert live.policy.revocation_reason == "second incident"
