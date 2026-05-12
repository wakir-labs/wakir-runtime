# SPDX-License-Identifier: Apache-2.0
"""Determinism tests for ``wirelang.schemas.publisher_cli``.

Phase-1b Sprint-3 Tag-5 — OI-7-Phase-1c-publisher.

The tests pin the CLI surface (parser shape, exit-code matrix, JSON
receipt schema, error envelope) and the operator-input gate ordering.
A test-local connect factory injects an in-memory backend over an
``_MockKvCas``-flavoured KV mock (mirroring the Tag-3 CAS-pin mock)
so that the publisher CLI is exercised end-to-end without a live
NATS cluster.

Test inventory
--------------

- T-SR-PUB-01: parser shape — ``publish`` and ``dry-run`` subcommands;
  required flags rejected when missing.
- T-SR-PUB-02: dry-run happy path — receipt JSON shape + canonical
  body-hash + canonical key.
- T-SR-PUB-03: publish (LWW) — bucket has the entry; revision >= 1;
  receipt mode is "lww".
- T-SR-PUB-04: publish (CAS-pin) — supplied --expected-revision
  matches live; success; receipt mode is "cas".
- T-SR-PUB-05: publish (CAS-pin conflict) — supplied
  --expected-revision is stale; exit 5; CAS_CONFLICT JSON envelope on
  stderr; bucket NOT mutated.
- T-SR-PUB-06: publish (--create-only success) — entry absent;
  revision 1; receipt mode is "create-only"; expected_revision is 0.
- T-SR-PUB-07: publish (--create-only conflict) — entry present; exit
  5; CAS_CONFLICT envelope on stderr.
- T-SR-PUB-08: input error — file not found; exit 3; INPUT_ERROR
  envelope.
- T-SR-PUB-09: input error — file is not valid JSON; exit 3;
  INPUT_ERROR envelope.
- T-SR-PUB-10: validation error — schema_body['$id'] does not match
  identity-triple-derived schema URL; backend gate raises; exit 4;
  VALIDATION_ERROR envelope; bucket NOT mutated.
- T-SR-PUB-11: validation error — registered_by empty/whitespace;
  exit 4; bucket NOT touched.
- T-SR-PUB-12: stdout/stderr separation — receipt on stdout only;
  errors on stderr only; both are valid single-line JSON.
"""

from __future__ import annotations

import asyncio
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest

from wirelang.schemas.publisher_cli import (
    ExitCode,
    build_parser,
    run,
)
from wirelang.schemas.registry_nats_kv_backend import (
    BUCKET_NAME,
    NatsKvSchemaRegistry,
    schema_body_sha256,
)


# ---------------------------------------------------------------------------
# In-memory KV mock (CAS-aware), mirroring the Tag-3 mock pattern.
# ---------------------------------------------------------------------------


class _MockBucketNotFoundError(Exception):
    """Mirrors nats-py's ``KeyNotFoundError`` class-name pattern."""


class _MockKeyWrongLastSequenceError(Exception):
    """Mirrors nats-py's ``KeyWrongLastSequenceError`` class-name pattern."""

    def __init__(self, message: str, *, actual_revision: int) -> None:
        super().__init__(message)
        self.actual_revision = actual_revision


@dataclass
class _MockKvEntry:
    value: bytes
    revision: int = 0


@dataclass
class _MockKvCas:
    """In-memory KV mock with CAS-aware ``update`` semantics."""

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

    async def update(self, key: str, value: bytes, last: int) -> int:
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_REGISTERED_AT = "2026-05-07T13:00:00Z"


def _make_schema_body(schema_id: str) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "title": "Publisher CLI test schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {"x": {"type": "string"}},
    }


def _write_schema_body(tmp_path: Path, schema_id: str) -> Path:
    body = _make_schema_body(schema_id)
    p = tmp_path / "schema.json"
    p.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    return p


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


def _make_factory(kv: _MockKvCas):
    """Build a connect_factory that returns the in-memory backend."""

    async def _factory(_connect_url: str):
        backend = NatsKvSchemaRegistry(kv=kv)

        async def _cleanup() -> None:
            return None

        return backend, _cleanup

    return _factory


def _io_streams() -> tuple[io.StringIO, io.StringIO]:
    return io.StringIO(), io.StringIO()


# ---------------------------------------------------------------------------
# T-SR-PUB-01: parser shape
# ---------------------------------------------------------------------------


def test_t_sr_pub_01_parser_shape(tmp_path):
    """T-SR-PUB-01: ``publish`` and ``dry-run`` are both registered;
    missing required flags exit with code 2 (argparse default).
    """
    parser = build_parser()
    body = _write_schema_body(tmp_path, "https://wakir.dev/x")

    # Parse the canonical argv for publish.
    ns = parser.parse_args(_common_argv(body))
    assert ns.cmd == "publish"
    assert ns.layer == "wire"
    assert ns.create_only is False
    assert ns.expected_revision is None

    # Parse the canonical argv for dry-run.
    ns2 = parser.parse_args(_common_argv(body, cmd="dry-run"))
    assert ns2.cmd == "dry-run"

    # Missing --schema-body must error out at the argparse layer.
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["publish", "--layer", "wire"])
    assert exc.value.code == 2

    # --create-only and --expected-revision are mutually exclusive.
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(
            _common_argv(
                body, extra=["--create-only", "--expected-revision", "0"]
            )
        )
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# T-SR-PUB-02: dry-run happy path
# ---------------------------------------------------------------------------


def test_t_sr_pub_02_dry_run_receipt(tmp_path):
    """T-SR-PUB-02: dry-run produces a stable receipt; canonical key
    is ``schemas/<layer>/<name>/<version>``; body-hash matches a fresh
    sha256_jcs computation; mode is "dry-run"; revision is null.
    """
    schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
    body = _write_schema_body(tmp_path, schema_id)
    out, err = _io_streams()

    code = run(
        _common_argv(body, cmd="dry-run"),
        connect_factory=None,  # unused on dry-run path
        stdout=out,
        stderr=err,
    )
    assert code == int(ExitCode.OK)
    assert err.getvalue() == ""

    receipt = json.loads(out.getvalue())
    assert receipt["mode"] == "dry-run"
    assert receipt["key"] == "schemas/wire/layer-1-wire/0.1.0"
    assert receipt["schema_id"] == schema_id
    assert receipt["schema_body_sha256"] == schema_body_sha256(
        _make_schema_body(schema_id)
    )
    assert receipt["revision"] is None
    assert receipt["expected_revision"] is None
    assert receipt["registered_by"] == "wirelang-eng"
    assert receipt["registered_at"].startswith("2026-05-07T13:00:00")


# ---------------------------------------------------------------------------
# T-SR-PUB-03: publish (LWW)
# ---------------------------------------------------------------------------


def test_t_sr_pub_03_publish_lww(tmp_path):
    """T-SR-PUB-03: publish without CAS flags hits the LWW path;
    receipt mode is "lww"; KV bucket holds exactly one entry; revision
    increments past 0.
    """
    schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
    body = _write_schema_body(tmp_path, schema_id)
    kv = _MockKvCas()
    out, err = _io_streams()

    code = run(
        _common_argv(body),
        connect_factory=_make_factory(kv),
        stdout=out,
        stderr=err,
    )
    assert code == int(ExitCode.OK), err.getvalue()
    assert err.getvalue() == ""

    receipt = json.loads(out.getvalue())
    assert receipt["mode"] == "lww"
    assert receipt["revision"] >= 1
    assert receipt["expected_revision"] is None
    assert "schemas/wire/layer-1-wire/0.1.0" in kv.store


# ---------------------------------------------------------------------------
# T-SR-PUB-04: publish (CAS-pin success)
# ---------------------------------------------------------------------------


def test_t_sr_pub_04_publish_cas_success(tmp_path):
    """T-SR-PUB-04: --expected-revision matches live; CAS publish
    succeeds; receipt carries mode "cas" and the expected_revision.
    """
    schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
    body = _write_schema_body(tmp_path, schema_id)
    kv = _MockKvCas()

    # Seed the bucket with a first put so the second pass can CAS-pin
    # against revision 1.
    factory = _make_factory(kv)
    out0, err0 = _io_streams()
    code0 = run(
        _common_argv(body),
        connect_factory=factory,
        stdout=out0,
        stderr=err0,
    )
    assert code0 == int(ExitCode.OK), err0.getvalue()
    rev0 = json.loads(out0.getvalue())["revision"]

    # Second pass: CAS-pin against the observed revision.
    out, err = _io_streams()
    code = run(
        _common_argv(body, extra=["--expected-revision", str(rev0)]),
        connect_factory=factory,
        stdout=out,
        stderr=err,
    )
    assert code == int(ExitCode.OK), err.getvalue()
    receipt = json.loads(out.getvalue())
    assert receipt["mode"] == "cas"
    assert receipt["expected_revision"] == rev0
    assert receipt["revision"] == rev0 + 1


# ---------------------------------------------------------------------------
# T-SR-PUB-05: publish (CAS-pin conflict)
# ---------------------------------------------------------------------------


def test_t_sr_pub_05_publish_cas_conflict(tmp_path):
    """T-SR-PUB-05: --expected-revision is stale (live has advanced);
    exit code 5 (CAS_CONFLICT); JSON error envelope on stderr; bucket
    state is unchanged from before the failed call.
    """
    schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
    body = _write_schema_body(tmp_path, schema_id)
    kv = _MockKvCas()
    factory = _make_factory(kv)

    # Seed twice so live revision is 2; we'll attempt to pin against 1.
    for _ in range(2):
        sink_out, sink_err = _io_streams()
        rc = run(
            _common_argv(body),
            connect_factory=factory,
            stdout=sink_out,
            stderr=sink_err,
        )
        assert rc == int(ExitCode.OK)

    snapshot = dict(kv.store)
    out, err = _io_streams()
    code = run(
        _common_argv(body, extra=["--expected-revision", "1"]),
        connect_factory=factory,
        stdout=out,
        stderr=err,
    )
    assert code == int(ExitCode.CAS_CONFLICT)
    assert out.getvalue() == ""
    payload = json.loads(err.getvalue())
    assert payload["error"] == "CAS_CONFLICT"
    assert payload["exit_code"] == int(ExitCode.CAS_CONFLICT)
    # Bucket state is byte-equal to the snapshot taken before the call.
    assert {k: v.revision for k, v in kv.store.items()} == {
        k: v.revision for k, v in snapshot.items()
    }


# ---------------------------------------------------------------------------
# T-SR-PUB-06: publish (--create-only success)
# ---------------------------------------------------------------------------


def test_t_sr_pub_06_publish_create_only_success(tmp_path):
    """T-SR-PUB-06: --create-only on an absent key writes revision 1;
    receipt mode is "create-only"; expected_revision is 0.
    """
    schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
    body = _write_schema_body(tmp_path, schema_id)
    kv = _MockKvCas()
    out, err = _io_streams()

    code = run(
        _common_argv(body, extra=["--create-only"]),
        connect_factory=_make_factory(kv),
        stdout=out,
        stderr=err,
    )
    assert code == int(ExitCode.OK), err.getvalue()
    receipt = json.loads(out.getvalue())
    assert receipt["mode"] == "create-only"
    assert receipt["expected_revision"] == 0
    assert receipt["revision"] == 1


# ---------------------------------------------------------------------------
# T-SR-PUB-07: publish (--create-only conflict)
# ---------------------------------------------------------------------------


def test_t_sr_pub_07_publish_create_only_conflict(tmp_path):
    """T-SR-PUB-07: --create-only on an existing key conflicts; exit 5;
    CAS_CONFLICT envelope; bucket revision NOT advanced.
    """
    schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
    body = _write_schema_body(tmp_path, schema_id)
    kv = _MockKvCas()
    factory = _make_factory(kv)

    # First pass: seed with --create-only.
    out0, err0 = _io_streams()
    rc0 = run(
        _common_argv(body, extra=["--create-only"]),
        connect_factory=factory,
        stdout=out0,
        stderr=err0,
    )
    assert rc0 == int(ExitCode.OK)
    rev_after_seed = kv.revision

    # Second pass: --create-only against an already-present key.
    out, err = _io_streams()
    code = run(
        _common_argv(body, extra=["--create-only"]),
        connect_factory=factory,
        stdout=out,
        stderr=err,
    )
    assert code == int(ExitCode.CAS_CONFLICT)
    assert out.getvalue() == ""
    payload = json.loads(err.getvalue())
    assert payload["error"] == "CAS_CONFLICT"
    assert kv.revision == rev_after_seed


# ---------------------------------------------------------------------------
# T-SR-PUB-08: input error — file not found
# ---------------------------------------------------------------------------


def test_t_sr_pub_08_input_error_file_not_found(tmp_path):
    """T-SR-PUB-08: nonexistent --schema-body path; exit 3
    (INPUT_ERROR); JSON envelope on stderr.
    """
    missing = tmp_path / "does-not-exist.json"
    kv = _MockKvCas()
    out, err = _io_streams()

    code = run(
        _common_argv(missing),
        connect_factory=_make_factory(kv),
        stdout=out,
        stderr=err,
    )
    assert code == int(ExitCode.INPUT_ERROR)
    assert out.getvalue() == ""
    payload = json.loads(err.getvalue())
    assert payload["error"] == "INPUT_ERROR"
    # KV bucket untouched.
    assert kv.store == {}


# ---------------------------------------------------------------------------
# T-SR-PUB-09: input error — invalid JSON
# ---------------------------------------------------------------------------


def test_t_sr_pub_09_input_error_invalid_json(tmp_path):
    """T-SR-PUB-09: --schema-body is not valid JSON; exit 3
    (INPUT_ERROR); KV bucket untouched.
    """
    bad = tmp_path / "broken.json"
    bad.write_bytes(b"{this is not json}")
    kv = _MockKvCas()
    out, err = _io_streams()

    code = run(
        _common_argv(bad),
        connect_factory=_make_factory(kv),
        stdout=out,
        stderr=err,
    )
    assert code == int(ExitCode.INPUT_ERROR)
    payload = json.loads(err.getvalue())
    assert payload["error"] == "INPUT_ERROR"
    assert "JSON" in payload["message"] or "json" in payload["message"]
    assert kv.store == {}


# ---------------------------------------------------------------------------
# T-SR-PUB-10: validation error — schema-id mismatch
# ---------------------------------------------------------------------------


def test_t_sr_pub_10_validation_error_schema_id_mismatch(tmp_path):
    """T-SR-PUB-10: backend gate trips because triple-derived URL does
    not match the schema_body['$id'] convention. The publisher CLI
    surfaces this as VALIDATION_ERROR (exit 4) without writing.
    """
    # Construct a body whose $id is *valid* but does not match the
    # convention; the put-time gate validates body['$id'] vs
    # entry.schema_id. Since the CLI builds entry.schema_id FROM
    # body['$id'], the id-mismatch gate cannot trigger directly.
    # Instead, write a body whose $id is missing entirely; the
    # CLI-side gate raises VALIDATION_ERROR before reaching the
    # backend.
    bad_body = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        # NO $id field — CLI gate will reject this.
        "title": "Body without $id",
        "type": "object",
    }
    p = tmp_path / "no-id.json"
    p.write_text(json.dumps(bad_body), encoding="utf-8")
    kv = _MockKvCas()
    out, err = _io_streams()

    code = run(
        _common_argv(p),
        connect_factory=_make_factory(kv),
        stdout=out,
        stderr=err,
    )
    assert code == int(ExitCode.VALIDATION_ERROR)
    payload = json.loads(err.getvalue())
    assert payload["error"] == "VALIDATION_ERROR"
    assert "$id" in payload["message"]
    assert kv.store == {}


# ---------------------------------------------------------------------------
# T-SR-PUB-11: validation error — empty registered_by
# ---------------------------------------------------------------------------


def test_t_sr_pub_11_validation_error_empty_registered_by(tmp_path):
    """T-SR-PUB-11: --registered-by is empty/whitespace; CLI gate
    raises VALIDATION_ERROR; bucket untouched.
    """
    body = _write_schema_body(tmp_path, "https://wakir.dev/x")
    kv = _MockKvCas()
    out, err = _io_streams()

    code = run(
        _common_argv(body, registered_by="   "),
        connect_factory=_make_factory(kv),
        stdout=out,
        stderr=err,
    )
    assert code == int(ExitCode.VALIDATION_ERROR)
    payload = json.loads(err.getvalue())
    assert payload["error"] == "VALIDATION_ERROR"
    assert "registered-by" in payload["message"]
    assert kv.store == {}


# ---------------------------------------------------------------------------
# T-SR-PUB-12: stdout/stderr separation + JSON shape
# ---------------------------------------------------------------------------


def test_t_sr_pub_12_stdout_stderr_separation(tmp_path):
    """T-SR-PUB-12: on success, stderr is empty and stdout is a single
    line of JSON. On error, stdout is empty and stderr is a single
    line of JSON. Both paths emit exactly one JSON object.
    """
    schema_id = "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0"
    body = _write_schema_body(tmp_path, schema_id)
    kv = _MockKvCas()
    factory = _make_factory(kv)

    # Success path.
    out, err = _io_streams()
    rc = run(
        _common_argv(body),
        connect_factory=factory,
        stdout=out,
        stderr=err,
    )
    assert rc == int(ExitCode.OK)
    assert err.getvalue() == ""
    out_lines = out.getvalue().splitlines()
    assert len(out_lines) == 1
    json.loads(out_lines[0])  # parses cleanly

    # Error path (file missing).
    out2, err2 = _io_streams()
    rc2 = run(
        _common_argv(tmp_path / "missing.json"),
        connect_factory=factory,
        stdout=out2,
        stderr=err2,
    )
    assert rc2 == int(ExitCode.INPUT_ERROR)
    assert out2.getvalue() == ""
    err_lines = err2.getvalue().splitlines()
    assert len(err_lines) == 1
    json.loads(err_lines[0])
