# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``wirelang.schemas.publisher_cli`` ``revoke``.

Phase-2 Sprint-6 Tag-2 — Publisher-CLI ``revoke`` subcommand.
End-to-end operator-experience: CLI → NATS-KV
(``wakir-capability-policies``) → backend revocation-monotonic
invariant (Sprint-6 Tag-1) → typed exit codes.

The Sprint-6 Tag-2 test inventory pins twelve concerns:

- T-SR-REV-01: bucket loader happy path — CAS auto-pin (no
  ``--expected-revision``) reads live revision, writes revocation,
  receipt records ``mode='cas'`` and ``previous_revision`` /
  ``new_revision``.
- T-SR-REV-02: ``--expected-revision`` happy path — operator-supplied
  expected matches live; write succeeds; receipt records
  ``expected_revision``.
- T-SR-REV-03: ``--expected-revision`` mismatch — CLI surfaces
  ``ExitCode.CAS_CONFLICT`` (5) BEFORE the backend call (no bucket
  touch).
- T-SR-REV-04: ``--lww`` happy path — bypasses revocation-monotonic
  invariant; receipt records ``mode='lww'``;
  ``expected_revision == null``.
- T-SR-REV-05: revocation-monotonic — un-revoke via CAS-pin is
  rejected with ``ExitCode.REVOCATION_CONFLICT`` (8).
- T-SR-REV-06: revocation-monotonic — advance ``revoked_at`` via
  CAS-pin is rejected with ``ExitCode.REVOCATION_CONFLICT`` (8).
- T-SR-REV-07: idempotent rewrite — re-apply same ``revoked_at`` with
  different ``revocation_reason`` succeeds (audit-trail refresh).
- T-SR-REV-08: revoke-target-not-found — non-existent
  ``(registered_by, policy_id)`` surfaces with
  ``ExitCode.REVOKE_TARGET_NOT_FOUND`` (9), distinct from INPUT_ERROR.
- T-SR-REV-09: ``--revoked-at`` requires timezone — naive RFC-3339
  surfaces with INPUT_ERROR (3).
- T-SR-REV-10: ``--registered-by-publisher`` non-empty — empty
  string surfaces with INPUT_ERROR (3).
- T-SR-REV-11: ``--expected-revision`` XOR ``--lww`` mutex — supplying
  both is an argparse usage error (exit 2).
- T-SR-REV-12: capability-bundle preservation — every non-revocation
  field of the live policy (allowed_kids, allowed_triples, disabled,
  note, not_before, not_after) is byte-equal on the rewritten record.

Hermetic
--------

- No NATS, no real transport.
- The in-memory ``_MockKvCapability`` mirrors Sprint-5 Tag-2 + Sprint-6
  Tag-1 mock shapes; it tracks revisions across get/put/update so the
  CAS-pin invariants can be asserted byte-precisely.
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
    RevokeReceipt,
    build_parser,
    run,
)
from wirelang.schemas.registered_by_capability import (
    CapabilityPolicy,
)


# ---------------------------------------------------------------------------
# In-memory KV mock (mirror of Sprint-6 Tag-1 fixture)
# ---------------------------------------------------------------------------


class _MockKeyWrongLastSequenceError(Exception):
    """Mirrors nats-py's KeyWrongLastSequenceError class-name shape so
    the backend's exception-class-name match identifies it as a CAS
    conflict.
    """

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
    """CAS-aware capability-policy KV mock (Sprint-6 Tag-1 mirror)."""

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
    """Capability-policy-bucket connect-factory injection."""

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
_REVOKED_AT_STR = "2026-05-11T22:00:00Z"
_REVOKED_AT = datetime(2026, 5, 11, 22, 0, 0, tzinfo=timezone.utc)
_REVOKED_AT_LATER_STR = "2026-05-11T23:00:00Z"
_REGISTERED_AT_REVOKE_STR = "2026-05-11T22:15:00Z"
_REGISTERED_AT_REVOKE = datetime(2026, 5, 11, 22, 15, 0, tzinfo=timezone.utc)


def _make_policy(
    *,
    registered_by: str = "wirelang-eng",
    allowed_kids: tuple = ("biscuit-root-1",),
    allowed_triples: tuple = (("wire", "layer-1-*"),),
    disabled: bool = False,
    note: Optional[str] = None,
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
    """Seed the in-memory capability bucket with pre-validated records.

    Bypasses ``NatsKvCapabilityPolicyBackend.put`` and writes envelopes
    directly so the test fixture stays decoupled from put-time
    validation (which is exercised separately in Sprint-5 Tag-2 tests).
    """
    for record in records:
        kv.store[record.key] = _MockKvEntry(
            value=_record_to_envelope(record),
            revision=kv.revision + 1,
        )
        kv.revision += 1


def _revoke_argv(
    *,
    registered_by: str = "wirelang-eng",
    policy_id: str = "default",
    revoked_at: str = _REVOKED_AT_STR,
    revocation_reason: Optional[str] = "key compromise reported by audit",
    registered_by_publisher: str = "incident-responder-1",
    registered_at: Optional[str] = _REGISTERED_AT_REVOKE_STR,
    expected_revision: Optional[int] = None,
    lww: bool = False,
) -> list[str]:
    argv = [
        "revoke",
        "--registered-by",
        registered_by,
        "--policy-id",
        policy_id,
        "--revoked-at",
        revoked_at,
        "--registered-by-publisher",
        registered_by_publisher,
    ]
    if revocation_reason is not None:
        argv.extend(["--revocation-reason", revocation_reason])
    if registered_at is not None:
        argv.extend(["--registered-at", registered_at])
    if expected_revision is not None:
        argv.extend(["--expected-revision", str(expected_revision)])
    if lww:
        argv.append("--lww")
    return argv


# ---------------------------------------------------------------------------
# T-SR-REV-01: bucket loader happy path (CAS auto-pin)
# ---------------------------------------------------------------------------


class TestTSRREV01CasAutoPin:
    """T-SR-REV-01: CAS auto-pin reads live revision, writes revocation,
    receipt records previous_revision / new_revision.
    """

    def test_cas_auto_pin_happy_path(self):
        kv = _MockKvCapability()
        record = _make_record()
        _seed_bucket(kv, record)
        live_revision_before = kv.revision  # 1

        out, err = _io_streams()
        cleanup_log: list = []
        code = run(
            _revoke_argv(),
            capability_bucket_factory=_make_capability_factory(
                kv, cleanup_log=cleanup_log
            ),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.OK), err.getvalue()
        receipt = json.loads(out.getvalue())
        assert receipt["cmd"] == "revoke"
        assert receipt["mode"] == "cas"
        assert receipt["registered_by"] == "wirelang-eng"
        assert receipt["policy_id"] == "default"
        assert receipt["revoked_at"] == _REVOKED_AT_STR
        assert receipt["revocation_reason"] == (
            "key compromise reported by audit"
        )
        assert receipt["expected_revision"] == live_revision_before
        assert receipt["previous_revision"] == live_revision_before
        assert receipt["new_revision"] == live_revision_before + 1
        assert receipt["registered_at"] == _REGISTERED_AT_REVOKE_STR
        assert receipt["registered_by_publisher"] == (
            "incident-responder-1"
        )
        assert receipt["key"] == key_for_policy_pair(
            "wirelang-eng", "default"
        )

        # Bucket state: revocation is now persisted.
        live = _envelope_to_record(kv.store[record.key].value)
        assert live.policy.revoked_at == _REVOKED_AT
        assert live.policy.revocation_reason == (
            "key compromise reported by audit"
        )
        # Cleanup ran.
        assert cleanup_log == ["cleanup"]


# ---------------------------------------------------------------------------
# T-SR-REV-02: --expected-revision happy path
# ---------------------------------------------------------------------------


class TestTSRREV02ExpectedRevisionHappyPath:
    """T-SR-REV-02: operator-supplied --expected-revision matches live."""

    def test_explicit_expected_revision_matches(self):
        kv = _MockKvCapability()
        _seed_bucket(kv, _make_record())
        live_revision = kv.revision  # 1

        out, err = _io_streams()
        code = run(
            _revoke_argv(expected_revision=live_revision),
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.OK), err.getvalue()
        receipt = json.loads(out.getvalue())
        assert receipt["expected_revision"] == live_revision
        assert receipt["previous_revision"] == live_revision
        assert receipt["new_revision"] == live_revision + 1


# ---------------------------------------------------------------------------
# T-SR-REV-03: --expected-revision mismatch surfaces CAS_CONFLICT (5)
# ---------------------------------------------------------------------------


class TestTSRREV03ExpectedRevisionMismatch:
    """T-SR-REV-03: operator-supplied --expected-revision does NOT match
    live; CLI surfaces ExitCode.CAS_CONFLICT BEFORE any backend write.
    """

    def test_expected_revision_mismatch(self):
        kv = _MockKvCapability()
        _seed_bucket(kv, _make_record())
        live_revision = kv.revision  # 1
        stale_revision = live_revision - 1  # 0; would be a CAS conflict

        out, err = _io_streams()
        code = run(
            _revoke_argv(expected_revision=stale_revision),
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.CAS_CONFLICT)
        # Stdout receipt NOT emitted on conflict.
        assert out.getvalue() == ""
        err_payload = json.loads(err.getvalue())
        assert err_payload["error"] == "CAS_CONFLICT"
        assert "expected-revision" in err_payload["message"]
        assert str(stale_revision) in err_payload["message"]
        # Bucket state unchanged: still at live_revision, not advanced.
        assert kv.revision == live_revision


# ---------------------------------------------------------------------------
# T-SR-REV-04: --lww happy path
# ---------------------------------------------------------------------------


class TestTSRREV04LwwHappyPath:
    """T-SR-REV-04: --lww bypasses CAS-pin; receipt records mode='lww'
    and expected_revision is null on the JSON receipt.
    """

    def test_lww_happy_path(self):
        kv = _MockKvCapability()
        _seed_bucket(kv, _make_record())
        live_revision = kv.revision  # 1

        out, err = _io_streams()
        code = run(
            _revoke_argv(lww=True),
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.OK), err.getvalue()
        receipt = json.loads(out.getvalue())
        assert receipt["mode"] == "lww"
        assert receipt["expected_revision"] is None
        assert receipt["previous_revision"] == live_revision
        assert receipt["new_revision"] == live_revision + 1


# ---------------------------------------------------------------------------
# T-SR-REV-05: un-revoke via CAS-pin is rejected (REVOCATION_CONFLICT 8)
# ---------------------------------------------------------------------------


class TestTSRREV05UnrevokeViaCasRejected:
    """T-SR-REV-05: an un-revoke gesture is rejected by the
    revocation-monotonic backend invariant.

    Reza-Note: the CLI does not (and cannot) syntactically refuse this
    case — the operator could (in principle) write
    ``--revoked-at <past instant>``. The CLI ALWAYS sets revoked_at to
    the operator-supplied value, so an attempt to "un-revoke" via this
    subcommand by passing a different revoked_at on a live-revoked
    policy is structurally the same as the Sprint-6 Tag-1
    advance-instant case (T-SR-REV-06). The "literal un-revoke"
    (``revoked_at=None``) is impossible through this CLI by design;
    operators who deliberately want to un-revoke MUST use the
    ``put_with_revision`` API or LWW with a tooling that writes a
    fully-formed un-revoked record (no ``--revoked-at`` flag).

    What this test asserts: a CAS-pin write that LOWERS revoked_at
    (operator-supplied --revoked-at strictly earlier than the live
    revoked_at) is also rejected by the monotonicity invariant — the
    backend treats ANY revoked_at != live as a conflict. We exercise
    that path explicitly.
    """

    def test_lower_revoked_at_via_cas_rejected(self):
        kv = _MockKvCapability()
        # Live policy is already revoked at a LATE instant; the
        # operator tries to revoke at an EARLIER instant via CAS-pin.
        already_revoked = _make_policy(
            revoked_at=datetime(
                2026, 5, 11, 23, 0, 0, tzinfo=timezone.utc
            ),
            revocation_reason="original revocation",
        )
        _seed_bucket(kv, _make_record(policy=already_revoked))

        out, err = _io_streams()
        code = run(
            _revoke_argv(
                revoked_at=_REVOKED_AT_STR,  # earlier
                revocation_reason="late attempt to lower instant",
            ),
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.REVOCATION_CONFLICT)
        err_payload = json.loads(err.getvalue())
        assert err_payload["error"] == "REVOCATION_CONFLICT"
        assert "revocation-monotonic" in err_payload["message"]


# ---------------------------------------------------------------------------
# T-SR-REV-06: advance revoked_at via CAS-pin is rejected
# ---------------------------------------------------------------------------


class TestTSRREV06AdvanceRevokedAtRejected:
    """T-SR-REV-06: a CAS-pin write that advances revoked_at strictly
    later than the live instant is rejected by the revocation-monotonic
    backend invariant (REVOCATION_CONFLICT 8).
    """

    def test_advance_revoked_at_via_cas_rejected(self):
        kv = _MockKvCapability()
        already_revoked = _make_policy(
            revoked_at=_REVOKED_AT,
            revocation_reason="initial revocation",
        )
        _seed_bucket(kv, _make_record(policy=already_revoked))

        out, err = _io_streams()
        code = run(
            _revoke_argv(
                revoked_at=_REVOKED_AT_LATER_STR,
                revocation_reason="late softening attempt",
            ),
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.REVOCATION_CONFLICT)
        err_payload = json.loads(err.getvalue())
        assert err_payload["error"] == "REVOCATION_CONFLICT"
        # Bucket state unchanged: still at original revoked_at.
        live = _envelope_to_record(
            kv.store[
                key_for_policy_pair("wirelang-eng", "default")
            ].value
        )
        assert live.policy.revoked_at == _REVOKED_AT
        assert live.policy.revocation_reason == "initial revocation"


# ---------------------------------------------------------------------------
# T-SR-REV-07: idempotent rewrite — same revoked_at + new reason
# ---------------------------------------------------------------------------


class TestTSRREV07IdempotentRewrite:
    """T-SR-REV-07: re-applying the same revoked_at with a different
    revocation_reason is permitted (audit-trail refresh), per the
    Sprint-6 Tag-1 equal-instant idempotent-rewrite invariant.
    """

    def test_idempotent_reason_refresh(self):
        kv = _MockKvCapability()
        already_revoked = _make_policy(
            revoked_at=_REVOKED_AT,
            revocation_reason="initial revocation",
        )
        _seed_bucket(kv, _make_record(policy=already_revoked))
        live_revision_before = kv.revision  # 1

        out, err = _io_streams()
        code = run(
            _revoke_argv(
                revoked_at=_REVOKED_AT_STR,
                revocation_reason="audit-trail refresh: ticket CR-42",
            ),
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.OK), err.getvalue()
        receipt = json.loads(out.getvalue())
        assert receipt["mode"] == "cas"
        assert receipt["revocation_reason"] == (
            "audit-trail refresh: ticket CR-42"
        )
        assert receipt["new_revision"] == live_revision_before + 1
        # Bucket carries the refreshed reason but the same instant.
        live = _envelope_to_record(
            kv.store[
                key_for_policy_pair("wirelang-eng", "default")
            ].value
        )
        assert live.policy.revoked_at == _REVOKED_AT
        assert live.policy.revocation_reason == (
            "audit-trail refresh: ticket CR-42"
        )


# ---------------------------------------------------------------------------
# T-SR-REV-08: REVOKE_TARGET_NOT_FOUND (9)
# ---------------------------------------------------------------------------


class TestTSRREV08TargetNotFound:
    """T-SR-REV-08: revoke against a non-existent (registered_by,
    policy_id) surfaces with REVOKE_TARGET_NOT_FOUND (9), distinct from
    INPUT_ERROR.
    """

    def test_target_not_found(self):
        kv = _MockKvCapability()  # empty bucket

        out, err = _io_streams()
        code = run(
            _revoke_argv(
                registered_by="never-existed",
                policy_id="never-existed-policy",
            ),
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.REVOKE_TARGET_NOT_FOUND)
        err_payload = json.loads(err.getvalue())
        assert err_payload["error"] == "REVOKE_TARGET_NOT_FOUND"
        assert "never-existed" in err_payload["message"]
        # Bucket state unchanged.
        assert kv.revision == 0


# ---------------------------------------------------------------------------
# T-SR-REV-09: --revoked-at requires timezone
# ---------------------------------------------------------------------------


class TestTSRREV09RevokedAtRequiresTimezone:
    """T-SR-REV-09: a naive RFC-3339 (no tz suffix) surfaces with
    INPUT_ERROR (3). Mirror of the Sprint-5 publish path's
    ``--registered-at`` invariant.
    """

    def test_naive_revoked_at_rejected(self):
        kv = _MockKvCapability()
        _seed_bucket(kv, _make_record())

        out, err = _io_streams()
        code = run(
            _revoke_argv(revoked_at="2026-05-11T22:00:00"),  # naive
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.INPUT_ERROR)
        err_payload = json.loads(err.getvalue())
        assert err_payload["error"] == "INPUT_ERROR"
        assert "revoked-at" in err_payload["message"]
        # Bucket state unchanged.
        assert kv.revision == 1


# ---------------------------------------------------------------------------
# T-SR-REV-10: --registered-by-publisher non-empty
# ---------------------------------------------------------------------------


class TestTSRREV10RegisteredByPublisherNonEmpty:
    """T-SR-REV-10: empty --registered-by-publisher surfaces with
    INPUT_ERROR (3).
    """

    def test_empty_registered_by_publisher_rejected(self):
        kv = _MockKvCapability()
        _seed_bucket(kv, _make_record())

        out, err = _io_streams()
        code = run(
            _revoke_argv(registered_by_publisher="   "),  # whitespace-only
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.INPUT_ERROR)
        err_payload = json.loads(err.getvalue())
        assert err_payload["error"] == "INPUT_ERROR"
        assert "registered-by-publisher" in err_payload["message"]


# ---------------------------------------------------------------------------
# T-SR-REV-11: --expected-revision XOR --lww mutex
# ---------------------------------------------------------------------------


class TestTSRREV11ExpectedRevisionLwwMutex:
    """T-SR-REV-11: --expected-revision and --lww are mutually
    exclusive at the argparse layer (exit 2 USAGE_ERROR).
    """

    def test_mutex_both_supplied(self):
        kv = _MockKvCapability()
        _seed_bucket(kv, _make_record())

        out, err = _io_streams()
        with pytest.raises(SystemExit) as excinfo:
            run(
                _revoke_argv(expected_revision=1, lww=True),
                capability_bucket_factory=_make_capability_factory(kv),
                stdout=out,
                stderr=err,
            )
        assert excinfo.value.code == int(ExitCode.USAGE_ERROR)
        # Bucket state unchanged.
        assert kv.revision == 1


# ---------------------------------------------------------------------------
# T-SR-REV-12: capability-bundle preservation
# ---------------------------------------------------------------------------


class TestTSRREV12CapabilityBundlePreservation:
    """T-SR-REV-12: revoke preserves every non-revocation field of the
    live policy byte-equally on the rewritten record.

    This is the determinism invariant for the revoke surface: the
    revoke subcommand is a *narrow* mutation (revoked_at +
    revocation_reason ONLY); allowed_kids / allowed_triples / disabled
    / note / not_before / not_after MUST round-trip byte-equal so an
    operator never accidentally loses bundle state by revoking.
    """

    def test_preserves_full_bundle(self):
        kv = _MockKvCapability()
        rich_policy = _make_policy(
            allowed_kids=("biscuit-root-1", "biscuit-root-2"),
            allowed_triples=(
                ("wire", "layer-1-*"),
                ("wat", "tv1-*"),
            ),
            disabled=False,
            note="wirelang engineering publisher",
            not_before=datetime(
                2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc
            ),
            not_after=datetime(
                2027, 5, 1, 0, 0, 0, tzinfo=timezone.utc
            ),
        )
        _seed_bucket(kv, _make_record(policy=rich_policy))

        out, err = _io_streams()
        code = run(
            _revoke_argv(),
            capability_bucket_factory=_make_capability_factory(kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.OK), err.getvalue()

        live = _envelope_to_record(
            kv.store[
                key_for_policy_pair("wirelang-eng", "default")
            ].value
        )
        # Mutated fields:
        assert live.policy.revoked_at == _REVOKED_AT
        assert live.policy.revocation_reason == (
            "key compromise reported by audit"
        )
        # Preserved fields (byte-equal to the live bundle):
        assert live.policy.allowed_kids == (
            "biscuit-root-1",
            "biscuit-root-2",
        )
        assert live.policy.allowed_triples == (
            ("wire", "layer-1-*"),
            ("wat", "tv1-*"),
        )
        assert live.policy.disabled is False
        assert live.policy.note == "wirelang engineering publisher"
        assert live.policy.not_before == datetime(
            2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc
        )
        assert live.policy.not_after == datetime(
            2027, 5, 1, 0, 0, 0, tzinfo=timezone.utc
        )


# ---------------------------------------------------------------------------
# Auxiliary probes
# ---------------------------------------------------------------------------


class TestRevokeAuxiliary:
    """Auxiliary probes: parser shape, receipt JSON canonicalisation."""

    def test_parser_admits_revoke_subcommand(self):
        parser = build_parser()
        # Build a minimal valid revoke argv and ensure parsing
        # succeeds at the argparse layer.
        args = parser.parse_args(
            _revoke_argv()
        )
        assert args.cmd == "revoke"
        assert args.registered_by == "wirelang-eng"
        assert args.policy_id == "default"
        assert args.revoked_at == _REVOKED_AT_STR
        assert args.registered_by_publisher == "incident-responder-1"

    def test_receipt_to_dict_is_json_canonicalisable(self):
        receipt = RevokeReceipt(
            cmd="revoke",
            mode="cas",
            key="capability-policies/wirelang-eng/default",
            registered_by="wirelang-eng",
            policy_id="default",
            revoked_at=_REVOKED_AT_STR,
            revocation_reason="reason",
            expected_revision=1,
            previous_revision=1,
            new_revision=2,
            registered_at=_REGISTERED_AT_REVOKE_STR,
            registered_by_publisher="ops-eng",
        )
        encoded = json.dumps(
            receipt.to_dict(), sort_keys=True, separators=(",", ":")
        )
        round_trip = json.loads(encoded)
        assert round_trip["cmd"] == "revoke"
        assert round_trip["new_revision"] == 2
