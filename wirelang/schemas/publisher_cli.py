# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Operator publisher CLI for the Wirelang schema registry.

Phase-1b Sprint-3 Tag-5 — OI-7-Phase-1c-publisher.

This module exposes an argparse surface that lets an operator publish
a module-shipped schema body onto the ``wakir-schemas`` NATS-KV bucket.
It is the natural composition of the Tag-3 CAS-pin contract
(``put_with_revision``) and the Tag-1 last-write-wins surface
(``put``); the watch-stream surface from Tag-4 is the consumer side
(post-publish observability) and is not invoked from the publisher.

Design philosophy
-----------------

The CLI is **deliberately minimal**: it is an *operator helper*, not
a privileged daemon. Every piece of state it touches is the same
state that ``NatsKvSchemaRegistry`` already validates at the gate
layer (schema-id, body-hash, identity-triple). The CLI does not
introduce new validation; it routes operator intent into the
existing backend gates.

Subject-mapping pattern source
------------------------------

The CLI mirrors the V-908 federation NATS-subject-to-route_id
convention applied at the **operator-input layer**: the user supplies
the canonical identity triple (``--layer / --name / --version``) plus
a schema-body file; the CLI derives the canonical KV key
(``schemas/<layer>/<name>/<version>``) via :func:`key_for_triple` and
the canonical body hash via :func:`schema_body_sha256`. There is no
intermediate "subject" namespace; the triple is the subject and the
key derivation is the mapping. Mirror principle preserved without
introducing a parallel namespace.

Subcommands
-----------

``publish``
    Publish a schema-body file under an identity triple. Three modes:
    last-write-wins (default), CAS-pin (``--expected-revision N``),
    and create-only (``--create-only`` ≡ CAS-pin with revision 0).

``dry-run``
    Validate inputs and print the canonical receipt without touching
    the bucket. Useful for CI pipelines that want to gate on the
    canonical hash before granting write capability.

Receipt
-------

On success, ``publish`` and ``dry-run`` emit a single JSON object on
stdout (canonical key, schema_id, body-hash, layer/name/version,
mode, and — for non-dry-run — the new KV revision). On failure, a
JSON error envelope on stderr plus a non-zero exit code; see
:func:`run`.

This file does NOT open NATS connections of its own. The
``connect_factory`` argument of :func:`run` allows the caller to
inject a connect strategy (used by tests; production wires
``nats.aio.client.Client`` plus ``js.key_value(BUCKET_NAME)``).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import enum
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence, Tuple

from wirelang.schemas.registry_nats_kv_backend import (
    BUCKET_NAME,
    NatsKvSchemaRegistry,
    RECOGNISED_LAYERS,
    SchemaRegistryConflictError,
    SchemaRegistryEntry,
    SchemaRegistryEnvelopeError,
    SchemaRegistryValidationError,
    key_for_triple,
    schema_body_sha256,
)


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------
#
# The exit-code matrix is stable; pipeline gates (CI, operator scripts)
# may rely on these specific values. Changing a value is a breaking
# change for those consumers and requires a spec-side note.


class ExitCode(enum.IntEnum):
    """Stable exit-code matrix for the publisher CLI.

    The values are part of the operator contract; do not renumber.
    """

    OK = 0
    USAGE_ERROR = 2  # argparse default
    INPUT_ERROR = 3  # file not found / unreadable / not JSON
    VALIDATION_ERROR = 4  # schema-body shape / id / hash gate failure
    CAS_CONFLICT = 5  # CAS-pin or create-only conflict
    BACKEND_ERROR = 6  # any other backend / transport failure


# ---------------------------------------------------------------------------
# Receipt shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PublishReceipt:
    """Canonical receipt printed on stdout on success.

    The receipt is JSON-serialisable and stable across modes; the
    ``revision`` field is ``None`` for ``--dry-run``.
    """

    mode: str  # "lww" | "cas" | "create-only" | "dry-run"
    key: str
    layer: str
    name: str
    version: str
    schema_id: str
    schema_body_sha256: str
    revision: Optional[int]
    expected_revision: Optional[int]
    registered_by: str
    registered_at: str
    supersedes: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "key": self.key,
            "layer": self.layer,
            "name": self.name,
            "version": self.version,
            "schema_id": self.schema_id,
            "schema_body_sha256": self.schema_body_sha256,
            "revision": self.revision,
            "expected_revision": self.expected_revision,
            "registered_by": self.registered_by,
            "registered_at": self.registered_at,
            "supersedes": self.supersedes,
        }


# ---------------------------------------------------------------------------
# Argparse surface
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argparse parser.

    Subcommands: ``publish`` (default operator path) and ``dry-run``
    (validate-only). The two subcommands share the operator-input
    flag set; ``publish`` adds the connection / mode flags.
    """

    parser = argparse.ArgumentParser(
        prog="wakir-schema-registry",
        description=(
            "Operator publisher for the Wirelang schema registry "
            "(wakir-schemas NATS-KV bucket)."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pub = sub.add_parser(
        "publish",
        help="Publish a schema body onto the wakir-schemas bucket.",
    )
    _add_input_flags(p_pub)
    _add_publish_flags(p_pub)

    p_dry = sub.add_parser(
        "dry-run",
        help=(
            "Validate inputs and print the canonical receipt without "
            "touching the bucket."
        ),
    )
    _add_input_flags(p_dry)

    return parser


def _add_input_flags(p: argparse.ArgumentParser) -> None:
    """Operator-input flags shared by ``publish`` and ``dry-run``."""

    p.add_argument(
        "--schema-body",
        required=True,
        help="Path to the schema-body JSON file (RFC 8259 UTF-8).",
    )
    p.add_argument(
        "--layer",
        required=True,
        choices=sorted(RECOGNISED_LAYERS),
        help="Schema-registry layer axis.",
    )
    p.add_argument(
        "--name",
        required=True,
        help="Schema name component (kebab-case ASCII).",
    )
    p.add_argument(
        "--version",
        required=True,
        help="Schema version component (kebab-case ASCII).",
    )
    p.add_argument(
        "--registered-by",
        required=True,
        help=(
            "Free-form actor identifier for the registered_by field. "
            "Phase-1b accepts any non-empty string; signature hardening "
            "is OI-7-Phase-2-sig (reserved)."
        ),
    )
    p.add_argument(
        "--supersedes",
        default=None,
        help="Optional schema_id of the entry this one supersedes.",
    )
    p.add_argument(
        "--registered-at",
        default=None,
        help=(
            "Override registered_at (RFC 3339, UTC). Defaults to the "
            "current UTC instant if omitted; deterministic test paths "
            "supply this flag explicitly."
        ),
    )


def _add_publish_flags(p: argparse.ArgumentParser) -> None:
    """Connection / mode flags exclusive to ``publish``."""

    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--expected-revision",
        type=int,
        default=None,
        help=(
            "CAS-pin: pass the revision observed by a prior get_with_revision. "
            "Mutually exclusive with --create-only."
        ),
    )
    mode.add_argument(
        "--create-only",
        action="store_true",
        help=(
            "CAS-pin with revision 0: succeed only if the entry does "
            "not yet exist on the bucket. Mutually exclusive with "
            "--expected-revision."
        ),
    )
    p.add_argument(
        "--connect-url",
        default="nats://127.0.0.1:4222",
        help="NATS connect URL (default %(default)s).",
    )


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------


def _load_schema_body(path_str: str) -> Mapping[str, Any]:
    """Read a schema-body JSON file and return the parsed mapping.

    Raises :class:`FileNotFoundError`, :class:`PermissionError`,
    :class:`UnicodeDecodeError`, :class:`json.JSONDecodeError`, or
    :class:`TypeError` (non-object root). Each surfaces with
    :class:`ExitCode.INPUT_ERROR` from :func:`run`.
    """

    path = Path(path_str)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnicodeDecodeError(
            exc.encoding,
            exc.object,
            exc.start,
            exc.end,
            f"--schema-body file is not valid UTF-8: {path_str}",
        )
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise TypeError(
            f"--schema-body root must be a JSON object, got {type(parsed).__name__}"
        )
    return parsed


def _parse_registered_at(value: Optional[str]) -> _dt.datetime:
    """Parse the ``--registered-at`` flag (or default to ``utcnow``).

    Test paths supply ``--registered-at`` so the receipt is byte-stable;
    production paths leave it unset and accept the current UTC instant.
    """

    if value is None:
        return _dt.datetime.now(tz=_dt.timezone.utc)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    parsed = _dt.datetime.fromisoformat(s)
    if parsed.tzinfo is None:
        raise ValueError(
            f"--registered-at {value!r} requires a timezone (use Z)"
        )
    return parsed.astimezone(_dt.timezone.utc)


# ---------------------------------------------------------------------------
# Entry construction (validation gates run inside the backend; the CLI
# only enforces *input-shape* gates so a malformed --schema-body cannot
# even reach the backend layer).
# ---------------------------------------------------------------------------


def _build_entry(
    *,
    schema_body: Mapping[str, Any],
    layer: str,
    name: str,
    version: str,
    registered_by: str,
    registered_at: _dt.datetime,
    supersedes: Optional[str],
) -> SchemaRegistryEntry:
    """Construct a :class:`SchemaRegistryEntry` from the operator inputs.

    Two CLI-side gates run BEFORE the backend gates (so a structurally
    broken file fails fast with a clear error):

    1. ``schema_body["$id"]`` MUST be present and a non-empty string.
    2. ``registered_by`` MUST be a non-empty string.

    The remaining backend gates (id↔body match, body-hash match,
    triple↔key match) run inside ``NatsKvSchemaRegistry.put`` /
    ``put_with_revision``.
    """

    body_id = schema_body.get("$id")
    if not isinstance(body_id, str) or not body_id:
        raise SchemaRegistryValidationError(
            "schema_body['$id'] must be a non-empty string"
        )
    if not isinstance(registered_by, str) or not registered_by.strip():
        raise SchemaRegistryValidationError(
            "--registered-by must be a non-empty string"
        )
    body_hash = schema_body_sha256(schema_body)
    return SchemaRegistryEntry(
        layer=layer,
        name=name,
        version=version,
        schema_id=body_id,
        schema_body=schema_body,
        schema_body_sha256=body_hash,
        registered_at=registered_at,
        registered_by=registered_by,
        supersedes=supersedes,
    )


# ---------------------------------------------------------------------------
# Connect factory contract
# ---------------------------------------------------------------------------
#
# Tests inject a factory; production wires the real one. The factory
# must return an awaitable that resolves to a tuple
# (NatsKvSchemaRegistry, async-cleanup-callable). The cleanup is
# always awaited in the finally block of :func:`_run_publish`.


ConnectFactory = Callable[
    [str], Awaitable[Tuple[NatsKvSchemaRegistry, Callable[[], Awaitable[None]]]]
]


async def _default_connect_factory(
    connect_url: str,
) -> Tuple[NatsKvSchemaRegistry, Callable[[], Awaitable[None]]]:
    """Default factory: connects to NATS and returns the schema-registry
    backend on the ``wakir-schemas`` bucket.

    This factory is NOT used by the test path (tests inject their own).
    The default exists so an operator running ``python -m
    wirelang.schemas.publisher_cli`` against a live cluster gets a
    working path.
    """

    # Late import: the CLI module loads cleanly even without nats-py
    # installed (test paths never exercise this branch).
    import nats  # type: ignore

    nc = await nats.connect(connect_url)
    js = nc.jetstream()
    kv = await js.key_value(BUCKET_NAME)
    backend = NatsKvSchemaRegistry(kv=kv)

    async def _cleanup() -> None:
        await nc.drain()
        await nc.close()

    return backend, _cleanup


# ---------------------------------------------------------------------------
# Main run() entry-point. The argparse Namespace is converted into a
# canonical receipt and either printed or routed through the backend.
# ---------------------------------------------------------------------------


def _print_receipt_stdout(receipt: PublishReceipt, stream) -> None:
    json.dump(receipt.to_dict(), stream, sort_keys=True, separators=(",", ":"))
    stream.write("\n")


def _print_error_stderr(code: ExitCode, message: str, stream) -> None:
    payload = {"error": code.name, "exit_code": int(code), "message": message}
    json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
    stream.write("\n")


def _resolve_mode(args: argparse.Namespace) -> Tuple[str, Optional[int]]:
    """Resolve the publish mode and the CAS-pin revision (if any)."""

    if args.create_only:
        return "create-only", 0
    if args.expected_revision is not None:
        return "cas", int(args.expected_revision)
    return "lww", None


async def _run_publish(
    args: argparse.Namespace,
    connect_factory: ConnectFactory,
    stdout,
    stderr,
) -> int:
    mode, expected_revision = _resolve_mode(args)
    try:
        schema_body = _load_schema_body(args.schema_body)
        registered_at = _parse_registered_at(args.registered_at)
        entry = _build_entry(
            schema_body=schema_body,
            layer=args.layer,
            name=args.name,
            version=args.version,
            registered_by=args.registered_by,
            registered_at=registered_at,
            supersedes=args.supersedes,
        )
    except (FileNotFoundError, PermissionError, UnicodeDecodeError) as exc:
        _print_error_stderr(ExitCode.INPUT_ERROR, str(exc), stderr)
        return int(ExitCode.INPUT_ERROR)
    except json.JSONDecodeError as exc:
        _print_error_stderr(
            ExitCode.INPUT_ERROR, f"--schema-body is not valid JSON: {exc}", stderr
        )
        return int(ExitCode.INPUT_ERROR)
    except (TypeError, ValueError) as exc:
        _print_error_stderr(ExitCode.INPUT_ERROR, str(exc), stderr)
        return int(ExitCode.INPUT_ERROR)
    except SchemaRegistryValidationError as exc:
        _print_error_stderr(ExitCode.VALIDATION_ERROR, str(exc), stderr)
        return int(ExitCode.VALIDATION_ERROR)

    # Connect and publish.
    backend, cleanup = await connect_factory(args.connect_url)
    try:
        try:
            if expected_revision is None:
                revision = await backend.put(entry)
            else:
                revision = await backend.put_with_revision(
                    entry, expected_revision=expected_revision
                )
        except SchemaRegistryValidationError as exc:
            _print_error_stderr(ExitCode.VALIDATION_ERROR, str(exc), stderr)
            return int(ExitCode.VALIDATION_ERROR)
        except SchemaRegistryConflictError as exc:
            _print_error_stderr(ExitCode.CAS_CONFLICT, str(exc), stderr)
            return int(ExitCode.CAS_CONFLICT)
        except SchemaRegistryEnvelopeError as exc:
            # Should not occur on a put path (this error is the
            # poisoned-read shape) but route it through anyway.
            _print_error_stderr(ExitCode.BACKEND_ERROR, str(exc), stderr)
            return int(ExitCode.BACKEND_ERROR)
        except Exception as exc:  # backend transport / unknown error
            _print_error_stderr(
                ExitCode.BACKEND_ERROR,
                f"backend error: {type(exc).__name__}: {exc}",
                stderr,
            )
            return int(ExitCode.BACKEND_ERROR)
    finally:
        try:
            await cleanup()
        except Exception:
            # Cleanup failures must NOT mask the publish outcome.
            pass

    receipt = PublishReceipt(
        mode=mode,
        key=entry.key,
        layer=entry.layer,
        name=entry.name,
        version=entry.version,
        schema_id=entry.schema_id,
        schema_body_sha256=entry.schema_body_sha256,
        revision=revision,
        expected_revision=expected_revision,
        registered_by=entry.registered_by,
        registered_at=entry.registered_at.isoformat(),
        supersedes=entry.supersedes,
    )
    _print_receipt_stdout(receipt, stdout)
    return int(ExitCode.OK)


def _run_dry_run(
    args: argparse.Namespace, stdout, stderr
) -> int:
    try:
        schema_body = _load_schema_body(args.schema_body)
        registered_at = _parse_registered_at(args.registered_at)
        entry = _build_entry(
            schema_body=schema_body,
            layer=args.layer,
            name=args.name,
            version=args.version,
            registered_by=args.registered_by,
            registered_at=registered_at,
            supersedes=args.supersedes,
        )
        # Run the same key-derivation gate that put() runs (so a malformed
        # triple fails dry-run, not just the live publish).
        _ = key_for_triple(entry.layer, entry.name, entry.version)
    except (FileNotFoundError, PermissionError, UnicodeDecodeError) as exc:
        _print_error_stderr(ExitCode.INPUT_ERROR, str(exc), stderr)
        return int(ExitCode.INPUT_ERROR)
    except json.JSONDecodeError as exc:
        _print_error_stderr(
            ExitCode.INPUT_ERROR, f"--schema-body is not valid JSON: {exc}", stderr
        )
        return int(ExitCode.INPUT_ERROR)
    except (TypeError, ValueError) as exc:
        _print_error_stderr(ExitCode.INPUT_ERROR, str(exc), stderr)
        return int(ExitCode.INPUT_ERROR)
    except SchemaRegistryValidationError as exc:
        _print_error_stderr(ExitCode.VALIDATION_ERROR, str(exc), stderr)
        return int(ExitCode.VALIDATION_ERROR)

    receipt = PublishReceipt(
        mode="dry-run",
        key=entry.key,
        layer=entry.layer,
        name=entry.name,
        version=entry.version,
        schema_id=entry.schema_id,
        schema_body_sha256=entry.schema_body_sha256,
        revision=None,
        expected_revision=None,
        registered_by=entry.registered_by,
        registered_at=entry.registered_at.isoformat(),
        supersedes=entry.supersedes,
    )
    _print_receipt_stdout(receipt, stdout)
    return int(ExitCode.OK)


def run(
    argv: Optional[Sequence[str]] = None,
    *,
    connect_factory: Optional[ConnectFactory] = None,
    stdout=None,
    stderr=None,
) -> int:
    """Argparse-driven entry-point.

    ``argv`` defaults to ``sys.argv[1:]``. ``connect_factory`` defaults
    to :func:`_default_connect_factory` which requires nats-py at
    runtime. Tests inject a factory that returns an in-memory backend.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr

    if args.cmd == "dry-run":
        return _run_dry_run(args, out, err)

    factory = (
        connect_factory if connect_factory is not None else _default_connect_factory
    )
    return asyncio.run(_run_publish(args, factory, out, err))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
