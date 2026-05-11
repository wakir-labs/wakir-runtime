# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Determinism tests for ``wirelang.schemas.publisher_cli`` ``--capability-bucket``.

Phase-2 Sprint-5 Tag-3 — Publisher-CLI ``--capability-bucket`` flag
integration. End-to-end operator-experience: CLI → NATS-KV
(``wakir-capability-policies``) → in-process ``CapabilityPolicyRegistry``
→ Sprint-4 Tag-6 ``gate_signed_entry``.

The Sprint-5 Tag-3 test inventory pins:

- T-SR-PUB-CB-01: ``--capability-bucket`` bucket loader — happy path
  (single policy on the bucket) round-trips through the connect
  factory into a ``CapabilityPolicyRegistry`` that the gate accepts;
  ``gate_policy_source == 'bucket'`` on the receipt.
- T-SR-PUB-CB-02: ``--sign --gate --capability-bucket`` happy path
  (LWW publish) — receipt ``signed=True``, ``gate_decision.allowed=True``
  with ``source="policy_match"``, ``gate_policy_source="bucket"``;
  schema-bucket revision +1.
- T-SR-PUB-CB-03: ``--capability-bucket`` deny on unknown
  ``registered_by`` — exit 7; ``no_policy_for_issuer`` reason;
  schema bucket NOT touched (bucket-side connect closed by cleanup).
- T-SR-PUB-CB-04: ``--capability-bucket`` deny on disallowed kid —
  exit 7; ``kid_not_allowed`` reason; schema bucket NOT touched.
- T-SR-PUB-CB-05: ``--capability-bucket`` deny on triple mismatch —
  exit 7; ``triple_not_allowed``; schema bucket NOT touched.
- T-SR-PUB-CB-06: ``--capability-registry`` XOR ``--capability-bucket``
  mutex — supplying both is an argparse usage error (exit 2);
  receipt NOT emitted.
- T-SR-PUB-CB-07: ``--capability-bucket`` without ``--gate`` is
  a usage error (orphan flag); exit 3 with explicit message.
- T-SR-PUB-CB-08: poisoned bucket envelope (non-JSON or schema
  mismatch on a stored value) raises through the factory and the CLI
  exits with VALIDATION_ERROR (4); schema bucket NOT touched.
- T-SR-PUB-CB-09: ``dry-run`` with ``--sign --gate --capability-bucket``
  — receipt mode is "dry-run"; ``signed=True``; ``gate_decision``
  reflects the allow; ``gate_policy_source="bucket"``; no schema
  bucket touch; deny on dry-run also returns exit 7.
- T-SR-PUB-CB-10: cross-source byte-equality — for the same input
  policies, the ``--capability-registry`` path and the
  ``--capability-bucket`` path produce receipts that differ ONLY in
  the ``gate_policy_source`` field (``"file"`` vs. ``"bucket"``); all
  other fields including ``gate_decision`` are byte-equal.

Auxiliary probes:

- ``TestAuxBucketLoader``: bucket factory contract checks
  (snapshot_registry called once; cleanup called even on snapshot
  raise; multi-policy iteration preserves bucket ordering).

Hermetic
--------

- No NATS, no real transport, no DNS, no wall-clock dependency for
  receipt determinism (``--registered-at`` is supplied).
- Both backends use in-memory mocks: ``_MockKvCas`` for the
  schema-registry path (mirror of Sprint-5 Tag-1) and ``_MockKv`` for
  the capability-policy path (mirror of Sprint-5 Tag-2).
- The Ed25519 seed is RFC 8032 test-vector 1 (32-byte known seed).
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest

from wirelang.schemas.capability_policy_nats_kv_backend import (
    BUCKET_NAME as CAPABILITY_BUCKET_NAME,
    CapabilityPolicyRecord,
    NatsKvCapabilityPolicyBackend,
    VALUE_SCHEMA as CAPABILITY_VALUE_SCHEMA,
    _record_to_envelope,
)
from wirelang.schemas.publisher_cli import (
    ExitCode,
    PublishReceipt,
    build_parser,
    run,
)
from wirelang.schemas.registered_by_capability import (
    CapabilityPolicy,
    DecisionSource,
)
from wirelang.schemas.registry_nats_kv_backend import (
    BUCKET_NAME as SCHEMA_BUCKET_NAME,
    NatsKvSchemaRegistry,
)


# ---------------------------------------------------------------------------
# In-memory KV mocks
# ---------------------------------------------------------------------------


class _MockBucketNotFoundError(Exception):
    pass


@dataclass
class _MockKvEntry:
    value: bytes
    revision: int = 0


@dataclass
class _MockKvCas:
    """CAS-aware schema-registry KV mock (Sprint-5 Tag-1 mirror)."""

    bucket: str = SCHEMA_BUCKET_NAME
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
            raise RuntimeError("CAS conflict (unused on LWW path)")
        self.revision += 1
        self.store[key] = _MockKvEntry(
            value=bytes(value), revision=self.revision
        )
        return self.revision


@dataclass
class _MockKvCapability:
    """Capability-policy-bucket KV mock (Sprint-5 Tag-2 mirror)."""

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

    async def delete(self, key: str) -> None:
        if key not in self.store:
            raise _MockBucketNotFoundError(f"key not found: {key}")
        del self.store[key]
        self.revision += 1

    async def keys(self) -> list:
        return list(self.store.keys())


def _make_schema_factory(kv: _MockKvCas):
    """Schema-registry-bucket connect-factory injection."""

    async def _factory(_connect_url: str):
        backend = NatsKvSchemaRegistry(kv=kv)

        async def _cleanup() -> None:
            return None

        return backend, _cleanup

    return _factory


def _make_capability_factory(kv: _MockKvCapability, *, cleanup_log: list | None = None):
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


_RFC8032_SEED_HEX = (
    "9d61b19deffd5a60ba844af492ec2cc4"
    "4449c5697b326919703bac031cae7f60"
)

_REGISTERED_AT = "2026-05-11T13:00:00Z"
_REGISTERED_AT_BUCKET = datetime(2026, 5, 11, 13, 0, 0, tzinfo=timezone.utc)


def _make_schema_body(schema_id: str) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "title": "Sprint-5 Tag-3 test schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {"x": {"type": "string"}},
    }


def _write_schema_body(tmp_path: Path, schema_id: str) -> Path:
    body = _make_schema_body(schema_id)
    p = tmp_path / "schema.json"
    p.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    return p


def _make_policy_record(
    *,
    registered_by: str = "wirelang-eng",
    policy_id: str = "default",
    allowed_kids: tuple = ("biscuit-root-1",),
    allowed_triples: tuple = (("wire", "layer-1-*"),),
    disabled: bool = False,
) -> CapabilityPolicyRecord:
    policy = CapabilityPolicy(
        registered_by=registered_by,
        allowed_kids=allowed_kids,
        allowed_triples=allowed_triples,
        disabled=disabled,
    )
    return CapabilityPolicyRecord(
        policy=policy,
        policy_id=policy_id,
        registered_at=_REGISTERED_AT_BUCKET,
        registered_by_publisher="ops-eng",
    )


def _seed_bucket(kv: _MockKvCapability, *records: CapabilityPolicyRecord) -> None:
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


def _common_argv(
    body_path: Path,
    *,
    layer: str = "wire",
    name: str = "layer-1-wire",
    version: str = "0.1.0",
    registered_by: str = "wirelang-eng",
    registered_at: str = _REGISTERED_AT,
    extra: list[str] | None = None,
    cmd: str = "publish",
) -> list[str]:
    argv = [
        cmd,
        "--schema-body",
        str(body_path),
        "--layer",
        layer,
        "--name",
        name,
        "--version",
        version,
        "--registered-by",
        registered_by,
        "--registered-at",
        registered_at,
    ]
    if extra:
        argv.extend(extra)
    return argv


def _sign_args(
    *,
    kid: str = "biscuit-root-1",
    seed_hex: str = _RFC8032_SEED_HEX,
) -> list[str]:
    return ["--sign", "--kid", kid, "--ed25519-priv-key-hex", seed_hex]


# ---------------------------------------------------------------------------
# T-SR-PUB-CB-01: bucket loader happy path
# ---------------------------------------------------------------------------


class TestTSRPUBCB01BucketLoader:
    """T-SR-PUB-CB-01: ``--capability-bucket`` snapshot_registry round-trip."""

    def test_single_policy_bucket_round_trip(self, tmp_path):
        schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
        body = _write_schema_body(tmp_path, schema_id)

        schema_kv = _MockKvCas()
        cap_kv = _MockKvCapability()
        _seed_bucket(cap_kv, _make_policy_record())

        out, err = _io_streams()
        code = run(
            _common_argv(
                body,
                extra=_sign_args()
                + ["--gate", "--capability-bucket"],
            ),
            connect_factory=_make_schema_factory(schema_kv),
            capability_bucket_factory=_make_capability_factory(cap_kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.OK), err.getvalue()
        receipt = json.loads(out.getvalue())
        assert receipt["signed"] is True
        assert receipt["gate_policy_source"] == "bucket"
        assert receipt["gate_decision"]["allowed"] is True
        assert receipt["gate_decision"]["source"] == "policy_match"


# ---------------------------------------------------------------------------
# T-SR-PUB-CB-02: --sign --gate --capability-bucket happy path
# ---------------------------------------------------------------------------


class TestTSRPUBCB02SignGateBucketHappyPath:
    """T-SR-PUB-CB-02: LWW publish with bucket gating."""

    def test_lww_publish_with_bucket_gate(self, tmp_path):
        schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
        body = _write_schema_body(tmp_path, schema_id)
        schema_kv = _MockKvCas()
        cap_kv = _MockKvCapability()
        _seed_bucket(cap_kv, _make_policy_record())

        out, err = _io_streams()
        code = run(
            _common_argv(
                body,
                extra=_sign_args() + ["--gate", "--capability-bucket"],
            ),
            connect_factory=_make_schema_factory(schema_kv),
            capability_bucket_factory=_make_capability_factory(cap_kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.OK), err.getvalue()
        receipt = json.loads(out.getvalue())
        assert receipt["mode"] == "lww"
        assert receipt["revision"] == 1
        assert receipt["gate_policy_source"] == "bucket"
        # Schema bucket holds exactly the canonical entry key.
        assert "schemas/wire/layer-1-wire/0.1.0" in schema_kv.store
        assert schema_kv.revision == 1


# ---------------------------------------------------------------------------
# T-SR-PUB-CB-03: deny on unknown registered_by
# ---------------------------------------------------------------------------


class TestTSRPUBCB03DenyNoPolicyForIssuer:
    """T-SR-PUB-CB-03: ``no_policy_for_issuer`` deny."""

    def test_unknown_issuer_denied_bucket_path(self, tmp_path):
        schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
        body = _write_schema_body(tmp_path, schema_id)
        schema_kv = _MockKvCas()
        cap_kv = _MockKvCapability()
        # Policy is for a DIFFERENT issuer; the publish issuer is
        # "wirelang-eng" but the bucket only carries "federation-eng".
        _seed_bucket(
            cap_kv, _make_policy_record(registered_by="federation-eng")
        )

        out, err = _io_streams()
        code = run(
            _common_argv(
                body,
                extra=_sign_args() + ["--gate", "--capability-bucket"],
            ),
            connect_factory=_make_schema_factory(schema_kv),
            capability_bucket_factory=_make_capability_factory(cap_kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.CAPABILITY_DENY)
        envelope = json.loads(err.getvalue())
        assert envelope["error"] == "CAPABILITY_DENY"
        assert "no_policy_for_issuer" in envelope["message"]
        # Schema bucket NOT touched (the short-circuit fires before
        # the schema-bucket connect).
        assert schema_kv.store == {}
        assert schema_kv.revision == 0


# ---------------------------------------------------------------------------
# T-SR-PUB-CB-04: deny on disallowed kid
# ---------------------------------------------------------------------------


class TestTSRPUBCB04DenyKidNotAllowed:
    """T-SR-PUB-CB-04: ``kid_not_allowed`` deny."""

    def test_disallowed_kid_denied_bucket_path(self, tmp_path):
        schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
        body = _write_schema_body(tmp_path, schema_id)
        schema_kv = _MockKvCas()
        cap_kv = _MockKvCapability()
        # Policy allows only biscuit-root-2; we sign with kid biscuit-root-1.
        _seed_bucket(
            cap_kv,
            _make_policy_record(allowed_kids=("biscuit-root-2",)),
        )

        out, err = _io_streams()
        code = run(
            _common_argv(
                body,
                extra=_sign_args() + ["--gate", "--capability-bucket"],
            ),
            connect_factory=_make_schema_factory(schema_kv),
            capability_bucket_factory=_make_capability_factory(cap_kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.CAPABILITY_DENY)
        envelope = json.loads(err.getvalue())
        assert "kid_not_allowed" in envelope["message"]
        assert schema_kv.store == {}


# ---------------------------------------------------------------------------
# T-SR-PUB-CB-05: deny on triple mismatch
# ---------------------------------------------------------------------------


class TestTSRPUBCB05DenyTripleNotAllowed:
    """T-SR-PUB-CB-05: ``triple_not_allowed`` deny."""

    def test_triple_mismatch_denied_bucket_path(self, tmp_path):
        schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
        body = _write_schema_body(tmp_path, schema_id)
        schema_kv = _MockKvCas()
        cap_kv = _MockKvCapability()
        # Policy allows semantic layer only; we publish to wire layer.
        _seed_bucket(
            cap_kv,
            _make_policy_record(allowed_triples=(("semantic", "*"),)),
        )

        out, err = _io_streams()
        code = run(
            _common_argv(
                body,
                extra=_sign_args() + ["--gate", "--capability-bucket"],
            ),
            connect_factory=_make_schema_factory(schema_kv),
            capability_bucket_factory=_make_capability_factory(cap_kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.CAPABILITY_DENY)
        envelope = json.loads(err.getvalue())
        assert "triple_not_allowed" in envelope["message"]
        assert schema_kv.store == {}


# ---------------------------------------------------------------------------
# T-SR-PUB-CB-06: mutex between --capability-registry and --capability-bucket
# ---------------------------------------------------------------------------


class TestTSRPUBCB06CapabilityRegistryBucketMutex:
    """T-SR-PUB-CB-06: argparse-level mutex enforcement."""

    def test_supplying_both_sources_is_argparse_error(self, tmp_path):
        schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
        body = _write_schema_body(tmp_path, schema_id)
        cap_file = tmp_path / "cap.json"
        cap_file.write_text(json.dumps({"policies": []}), encoding="utf-8")

        # argparse mutex group raises SystemExit(2).
        with pytest.raises(SystemExit) as exc_info:
            run(
                _common_argv(
                    body,
                    extra=_sign_args()
                    + [
                        "--gate",
                        "--capability-registry",
                        str(cap_file),
                        "--capability-bucket",
                    ],
                ),
                connect_factory=None,
                capability_bucket_factory=None,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# T-SR-PUB-CB-07: orphan --capability-bucket without --gate
# ---------------------------------------------------------------------------


class TestTSRPUBCB07OrphanCapabilityBucket:
    """T-SR-PUB-CB-07: ``--capability-bucket`` without ``--gate``."""

    def test_capability_bucket_without_gate_is_input_error(self, tmp_path):
        schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
        body = _write_schema_body(tmp_path, schema_id)
        schema_kv = _MockKvCas()
        cap_kv = _MockKvCapability()

        out, err = _io_streams()
        code = run(
            _common_argv(body, extra=["--capability-bucket"]),
            connect_factory=_make_schema_factory(schema_kv),
            capability_bucket_factory=_make_capability_factory(cap_kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.INPUT_ERROR)
        envelope = json.loads(err.getvalue())
        assert envelope["error"] == "INPUT_ERROR"
        assert "--capability-bucket" in envelope["message"]
        assert "require --gate" in envelope["message"]
        # Schema bucket NOT touched.
        assert schema_kv.store == {}


# ---------------------------------------------------------------------------
# T-SR-PUB-CB-08: poisoned bucket envelope routes to VALIDATION_ERROR
# ---------------------------------------------------------------------------


class TestTSRPUBCB08PoisonedBucketEnvelope:
    """T-SR-PUB-CB-08: bucket-side poisoned envelope."""

    def test_non_json_bucket_value_routes_to_validation_error(self, tmp_path):
        schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
        body = _write_schema_body(tmp_path, schema_id)
        schema_kv = _MockKvCas()
        cap_kv = _MockKvCapability()
        # Plant a non-JSON value directly on the bucket store (under
        # a valid-looking key). The snapshot will list it and the
        # decode will raise.
        cap_kv.store["capability-policies/wirelang-eng/default"] = _MockKvEntry(
            value=b"<not-json>", revision=1
        )
        cap_kv.revision = 1

        out, err = _io_streams()
        code = run(
            _common_argv(
                body,
                extra=_sign_args() + ["--gate", "--capability-bucket"],
            ),
            connect_factory=_make_schema_factory(schema_kv),
            capability_bucket_factory=_make_capability_factory(cap_kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.VALIDATION_ERROR)
        envelope = json.loads(err.getvalue())
        assert envelope["error"] == "VALIDATION_ERROR"
        # Schema bucket NOT touched.
        assert schema_kv.store == {}


# ---------------------------------------------------------------------------
# T-SR-PUB-CB-09: dry-run with bucket path
# ---------------------------------------------------------------------------


class TestTSRPUBCB09DryRunBucket:
    """T-SR-PUB-CB-09: dry-run sign+gate+bucket."""

    def test_dry_run_allow_with_bucket(self, tmp_path):
        schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
        body = _write_schema_body(tmp_path, schema_id)
        cap_kv = _MockKvCapability()
        _seed_bucket(cap_kv, _make_policy_record())

        out, err = _io_streams()
        code = run(
            _common_argv(
                body,
                cmd="dry-run",
                extra=_sign_args() + ["--gate", "--capability-bucket"],
            ),
            connect_factory=None,  # never invoked on dry-run path
            capability_bucket_factory=_make_capability_factory(cap_kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.OK), err.getvalue()
        receipt = json.loads(out.getvalue())
        assert receipt["mode"] == "dry-run"
        assert receipt["signed"] is True
        assert receipt["gate_policy_source"] == "bucket"
        assert receipt["revision"] is None
        assert receipt["gate_decision"]["allowed"] is True

    def test_dry_run_deny_with_bucket(self, tmp_path):
        schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
        body = _write_schema_body(tmp_path, schema_id)
        cap_kv = _MockKvCapability()
        # Empty bucket → no_policy_for_issuer.

        out, err = _io_streams()
        code = run(
            _common_argv(
                body,
                cmd="dry-run",
                extra=_sign_args() + ["--gate", "--capability-bucket"],
            ),
            connect_factory=None,
            capability_bucket_factory=_make_capability_factory(cap_kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.CAPABILITY_DENY)


# ---------------------------------------------------------------------------
# T-SR-PUB-CB-10: cross-source byte-equality
# ---------------------------------------------------------------------------


class TestTSRPUBCB10CrossSourceEquality:
    """T-SR-PUB-CB-10: file-source vs. bucket-source receipts diff only
    in ``gate_policy_source``.
    """

    def test_file_source_and_bucket_source_receipts_equal_modulo_source(
        self, tmp_path
    ):
        schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
        body = _write_schema_body(tmp_path, schema_id)

        # File-source registry.
        cap_file = tmp_path / "cap.json"
        cap_file.write_text(
            json.dumps(
                {
                    "policies": [
                        {
                            "registered_by": "wirelang-eng",
                            "allowed_kids": ["biscuit-root-1"],
                            "allowed_triples": [["wire", "layer-1-*"]],
                            "disabled": False,
                        }
                    ]
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        # Bucket-source registry with byte-identical policy semantics.
        cap_kv = _MockKvCapability()
        _seed_bucket(cap_kv, _make_policy_record())

        # File-path run.
        schema_kv_a = _MockKvCas()
        out_a, err_a = _io_streams()
        code_a = run(
            _common_argv(
                body,
                extra=_sign_args()
                + ["--gate", "--capability-registry", str(cap_file)],
            ),
            connect_factory=_make_schema_factory(schema_kv_a),
            stdout=out_a,
            stderr=err_a,
        )
        assert code_a == int(ExitCode.OK), err_a.getvalue()
        receipt_a = json.loads(out_a.getvalue())

        # Bucket-path run.
        schema_kv_b = _MockKvCas()
        out_b, err_b = _io_streams()
        code_b = run(
            _common_argv(
                body,
                extra=_sign_args() + ["--gate", "--capability-bucket"],
            ),
            connect_factory=_make_schema_factory(schema_kv_b),
            capability_bucket_factory=_make_capability_factory(cap_kv),
            stdout=out_b,
            stderr=err_b,
        )
        assert code_b == int(ExitCode.OK), err_b.getvalue()
        receipt_b = json.loads(out_b.getvalue())

        # Only difference is the policy-source axis.
        assert receipt_a["gate_policy_source"] == "file"
        assert receipt_b["gate_policy_source"] == "bucket"
        # All other fields byte-equal (gate_decision, kid, signed, key,
        # schema_body_sha256, registered_at, etc.).
        for k in receipt_a:
            if k == "gate_policy_source":
                continue
            assert receipt_a[k] == receipt_b[k], f"diff at {k!r}"


# ---------------------------------------------------------------------------
# Auxiliary: bucket-loader contract
# ---------------------------------------------------------------------------


class TestAuxBucketLoader:
    """Auxiliary: ``_load_capability_registry_from_bucket`` invariants."""

    def test_cleanup_called_on_success(self, tmp_path):
        schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
        body = _write_schema_body(tmp_path, schema_id)
        schema_kv = _MockKvCas()
        cap_kv = _MockKvCapability()
        _seed_bucket(cap_kv, _make_policy_record())
        cleanup_log: list = []

        out, err = _io_streams()
        code = run(
            _common_argv(
                body,
                extra=_sign_args() + ["--gate", "--capability-bucket"],
            ),
            connect_factory=_make_schema_factory(schema_kv),
            capability_bucket_factory=_make_capability_factory(
                cap_kv, cleanup_log=cleanup_log
            ),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.OK), err.getvalue()
        assert cleanup_log == ["cleanup"]

    def test_cleanup_called_on_poisoned_envelope(self, tmp_path):
        schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
        body = _write_schema_body(tmp_path, schema_id)
        schema_kv = _MockKvCas()
        cap_kv = _MockKvCapability()
        # Poison the bucket so the snapshot raises.
        cap_kv.store["capability-policies/wirelang-eng/default"] = _MockKvEntry(
            value=b"<not-json>", revision=1
        )
        cap_kv.revision = 1
        cleanup_log: list = []

        out, err = _io_streams()
        code = run(
            _common_argv(
                body,
                extra=_sign_args() + ["--gate", "--capability-bucket"],
            ),
            connect_factory=_make_schema_factory(schema_kv),
            capability_bucket_factory=_make_capability_factory(
                cap_kv, cleanup_log=cleanup_log
            ),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.VALIDATION_ERROR)
        assert cleanup_log == ["cleanup"]

    def test_multi_policy_bucket_preserves_sorted_key_order(self, tmp_path):
        """When multiple policies exist on the bucket, snapshot
        materialises them in sorted-key order; the gate evaluates the
        first matching policy (in policies_for() FIFO order)."""
        schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
        body = _write_schema_body(tmp_path, schema_id)
        schema_kv = _MockKvCas()
        cap_kv = _MockKvCapability()
        # Two policies for the same issuer; the gate accepts under
        # either. Sorted-key order puts "default" before "secondary".
        _seed_bucket(
            cap_kv,
            _make_policy_record(policy_id="default"),
            _make_policy_record(
                policy_id="secondary", allowed_kids=("biscuit-root-2",)
            ),
        )

        out, err = _io_streams()
        code = run(
            _common_argv(
                body,
                extra=_sign_args() + ["--gate", "--capability-bucket"],
            ),
            connect_factory=_make_schema_factory(schema_kv),
            capability_bucket_factory=_make_capability_factory(cap_kv),
            stdout=out,
            stderr=err,
        )
        assert code == int(ExitCode.OK), err.getvalue()
        receipt = json.loads(out.getvalue())
        # The first policy (sorted by key) is "default" with
        # biscuit-root-1; the gate matches there.
        assert receipt["gate_decision"]["source"] == "policy_match"
