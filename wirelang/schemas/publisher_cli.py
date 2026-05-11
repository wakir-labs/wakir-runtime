# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Operator publisher CLI for the Wirelang schema registry.

Phase-1b Sprint-3 Tag-5 — OI-7-Phase-1c-publisher.
Phase-2 Sprint-5 Tag-1 — capability-gating end-to-end integration.

This module exposes an argparse surface that lets an operator publish
a module-shipped schema body onto the ``wakir-schemas`` NATS-KV bucket.
It is the natural composition of the Tag-3 CAS-pin contract
(``put_with_revision``) and the Tag-1 last-write-wins surface
(``put``); the watch-stream surface from Tag-4 is the consumer side
(post-publish observability) and is not invoked from the publisher.

Sprint-5 Tag-1 adds three optional flags (``--sign``, ``--gate``,
``--capability-registry``) that lift the canonical Phase-2
capability-gated publish flow (Sprint-4 Tag-6 §5.12 Composition
Pattern) onto the operator surface without altering the backend
contract or the receipt's bare-publish shape.

Design philosophy
-----------------

The CLI is **deliberately minimal**: it is an *operator helper*, not
a privileged daemon. Every piece of state it touches is the same
state that ``NatsKvSchemaRegistry`` already validates at the gate
layer (schema-id, body-hash, identity-triple). The CLI does not
introduce new validation; it routes operator intent into the
existing backend gates.

The Sprint-5 Tag-1 capability path is additive: signing and gating
run between ``_build_entry`` and the backend write, leaving the
backend's validation gates and the receipt's existing fields
byte-equal. A deny short-circuits with :class:`ExitCode.CAPABILITY_DENY`
(7) and the bucket is not touched.

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
from wirelang.schemas.entry_signing import (
    SchemaRegistrySignatureError,
    SignedSchemaRegistryEntry,
    sign_entry,
)
from wirelang.schemas.registered_by_capability import (
    CapabilityGateDecision,
    CapabilityPolicy,
    CapabilityPolicyRegistry,
    RegisteredByCapabilityError,
    gate_signed_entry,
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
    CAPABILITY_DENY = 7  # Sprint-5 Tag-1: --gate decision was a deny


# ---------------------------------------------------------------------------
# Receipt shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PublishReceipt:
    """Canonical receipt printed on stdout on success.

    The receipt is JSON-serialisable and stable across modes; the
    ``revision`` field is ``None`` for ``--dry-run``.

    Sprint-5 Tag-1 additions
    ------------------------

    Three optional fields surface the capability path; each defaults
    to its "feature-off" value so receipts from the original bare
    publish path stay byte-equal:

    - ``signed``: ``False`` when ``--sign`` was not requested; ``True``
      when ``sign_entry`` was called successfully.
    - ``kid``: the kid embedded in the signature block, or ``None``.
    - ``gate_decision``: a small JSON object with ``allowed``,
      ``source``, ``reason`` on the gate-allow path, or ``None`` when
      ``--gate`` was not requested.

    These fields are additive; pipelines that do not opt in to
    ``--sign`` / ``--gate`` continue to receive the exact pre-Sprint-5
    receipt shape (with the three optional fields all set to their
    default-off values).
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
    signed: bool = False
    kid: Optional[str] = None
    gate_decision: Optional[dict[str, Any]] = None

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
            "signed": self.signed,
            "kid": self.kid,
            "gate_decision": self.gate_decision,
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
    _add_capability_flags(p_pub)

    p_dry = sub.add_parser(
        "dry-run",
        help=(
            "Validate inputs and print the canonical receipt without "
            "touching the bucket."
        ),
    )
    _add_input_flags(p_dry)
    _add_capability_flags(p_dry)

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


def _add_capability_flags(p: argparse.ArgumentParser) -> None:
    """Sprint-5 Tag-1 capability flags (shared by ``publish`` and ``dry-run``).

    Three concerns are wired in:

    - ``--sign`` plus a private-key source (``--ed25519-priv-key-hex``
      XOR ``--ed25519-priv-key-file``) plus ``--kid`` enable signing
      via :func:`wirelang.schemas.entry_signing.sign_entry`.

    - ``--gate`` plus ``--capability-registry <path>`` enable gating
      via :func:`wirelang.schemas.registered_by_capability.gate_signed_entry`.
      ``--gate`` requires ``--sign`` (the gate reads ``kid`` from the
      signature block).

    - ``--gate-as-of`` is an optional RFC-3339 timestamp passed to the
      gate as ``as_of``. When omitted, the gate skips validity-window
      enforcement (consistent with Sprint-4 Tag-6 §5.12 contract).

    All flags default off; pipelines that omit them retain the
    pre-Sprint-5 publish surface byte-equal.
    """

    p.add_argument(
        "--sign",
        action="store_true",
        help=(
            "Sign the entry locally before publish/dry-run "
            "(requires --kid and exactly one of --ed25519-priv-key-hex "
            "or --ed25519-priv-key-file)."
        ),
    )
    p.add_argument(
        "--kid",
        default=None,
        help=(
            "Key identifier embedded in the signature block. Required "
            "when --sign is set. Should match an AIP-document "
            "public_keys entry."
        ),
    )
    key_src = p.add_mutually_exclusive_group()
    key_src.add_argument(
        "--ed25519-priv-key-hex",
        default=None,
        help=(
            "Ed25519 private key as a 64-character hex string "
            "(32-byte raw seed). Mutually exclusive with "
            "--ed25519-priv-key-file. Test paths only; production "
            "should prefer --ed25519-priv-key-file."
        ),
    )
    key_src.add_argument(
        "--ed25519-priv-key-file",
        default=None,
        help=(
            "Path to a file containing a 32-byte raw Ed25519 private "
            "key seed (binary, exactly 32 bytes, or 64 hex characters "
            "for ASCII convenience). Mutually exclusive with "
            "--ed25519-priv-key-hex."
        ),
    )
    p.add_argument(
        "--gate",
        action="store_true",
        help=(
            "Run the Sprint-4 Tag-6 capability gate on the signed entry "
            "before publishing (requires --sign and "
            "--capability-registry)."
        ),
    )
    p.add_argument(
        "--capability-registry",
        default=None,
        help=(
            "Path to a capability-registry JSON file (top-level "
            "{policies: [...]}). Required when --gate is set."
        ),
    )
    p.add_argument(
        "--gate-as-of",
        default=None,
        help=(
            "Optional RFC-3339 instant (with timezone) used as the "
            "gate's as_of value (validity-window enforcement). "
            "Defaults to None, which bypasses window enforcement."
        ),
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
# Sprint-5 Tag-1 — capability-flag validation, key-loading, registry-loading
# ---------------------------------------------------------------------------


def _validate_capability_flag_consistency(args: argparse.Namespace) -> None:
    """Check the cross-flag invariants for ``--sign`` / ``--gate``.

    Invariants enforced (each raises :class:`ValueError`):

    1. ``--sign`` requires ``--kid``.
    2. ``--sign`` requires exactly one of ``--ed25519-priv-key-hex`` /
       ``--ed25519-priv-key-file`` (mutual exclusion is enforced by
       argparse; absence is checked here).
    3. ``--gate`` requires ``--sign`` (kid must be present in the
       signature block).
    4. ``--gate`` requires ``--capability-registry`` (no implicit
       empty registry — the deny semantics differ from explicit
       empty).
    5. ``--kid`` / ``--ed25519-priv-key-*`` / ``--capability-registry``
       / ``--gate-as-of`` without ``--sign`` / ``--gate`` is a usage
       error (no-op flag is reported, not silently ignored).
    """

    sign = getattr(args, "sign", False)
    gate = getattr(args, "gate", False)
    kid = getattr(args, "kid", None)
    hex_key = getattr(args, "ed25519_priv_key_hex", None)
    file_key = getattr(args, "ed25519_priv_key_file", None)
    cap_path = getattr(args, "capability_registry", None)
    gate_as_of = getattr(args, "gate_as_of", None)

    if sign:
        if kid is None or kid == "":
            raise ValueError("--sign requires --kid (non-empty)")
        if hex_key is None and file_key is None:
            raise ValueError(
                "--sign requires --ed25519-priv-key-hex or "
                "--ed25519-priv-key-file"
            )
    else:
        if kid is not None or hex_key is not None or file_key is not None:
            raise ValueError(
                "--kid / --ed25519-priv-key-hex / --ed25519-priv-key-file "
                "require --sign"
            )

    if gate:
        if not sign:
            raise ValueError("--gate requires --sign")
        if cap_path is None:
            raise ValueError(
                "--gate requires --capability-registry <path>"
            )
    else:
        if cap_path is not None or gate_as_of is not None:
            raise ValueError(
                "--capability-registry / --gate-as-of require --gate"
            )


def _load_ed25519_priv_key(
    *, hex_value: Optional[str], file_value: Optional[str]
) -> bytes:
    """Load a 32-byte Ed25519 private-key seed from the supplied source.

    Exactly one of ``hex_value`` / ``file_value`` is non-``None``
    (enforced by argparse mutual exclusion + the consistency check
    in :func:`_validate_capability_flag_consistency`).

    The file path accepts two encodings:

    - **Binary**: exactly 32 bytes long.
    - **ASCII hex**: exactly 64 hex characters (UTF-8), optionally
      surrounded by whitespace. Useful for committing test vectors.

    Raises :class:`ValueError` on malformed input; raises
    :class:`FileNotFoundError` / :class:`PermissionError` for I/O
    failures so the caller can route them through ExitCode.INPUT_ERROR.
    """

    if hex_value is not None:
        return _decode_hex_seed(hex_value, source="--ed25519-priv-key-hex")
    assert file_value is not None  # _validate_capability_flag_consistency
    path = Path(file_value)
    raw = path.read_bytes()
    if len(raw) == 32:
        return bytes(raw)
    # Try ASCII-hex interpretation (RFC 8032 test-vector convention).
    try:
        text = raw.decode("ascii").strip()
    except UnicodeDecodeError:
        raise ValueError(
            f"--ed25519-priv-key-file {file_value!r} must contain "
            f"32 raw bytes or 64 hex characters (ASCII)"
        )
    return _decode_hex_seed(text, source=f"--ed25519-priv-key-file {file_value!r}")


def _decode_hex_seed(value: str, *, source: str) -> bytes:
    """Decode a 64-character hex string into a 32-byte seed.

    Raises :class:`ValueError` on bad length or non-hex characters.
    """

    s = value.strip()
    if len(s) != 64:
        raise ValueError(
            f"{source} must be exactly 64 hex characters (32-byte seed); "
            f"got {len(s)}"
        )
    try:
        seed = bytes.fromhex(s)
    except ValueError as exc:
        raise ValueError(f"{source} is not valid hex: {exc}") from exc
    if len(seed) != 32:
        # Defensive: bytes.fromhex on 64 hex chars yields 32 bytes,
        # but pin the invariant.
        raise ValueError(
            f"{source} decoded to {len(seed)} bytes (expected 32)"
        )
    return seed


def _load_capability_registry(path_str: str) -> CapabilityPolicyRegistry:
    """Load a capability-policy registry from a JSON file.

    File format::

        {
          "policies": [
            {
              "registered_by": "wirelang-eng",
              "allowed_kids": ["biscuit-root-1"],
              "allowed_triples": [["wire", "layer-1-*"], ["*", "*"]],
              "not_before": "2026-05-01T00:00:00Z",
              "not_after":  "2027-05-01T00:00:00Z",
              "disabled": false,
              "note": "wirelang engineering publisher"
            },
            ...
          ]
        }

    The top-level object MUST contain a ``policies`` array. Each entry
    is mapped to a :class:`CapabilityPolicy` via
    :func:`_policy_from_dict`. Errors during loading raise
    :class:`ValueError` (file-shape) or
    :class:`RegisteredByCapabilityError` (policy-shape); the caller
    routes them through ``ExitCode.INPUT_ERROR`` and
    ``ExitCode.VALIDATION_ERROR`` respectively.
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
            f"--capability-registry file is not valid UTF-8: {path_str}",
        )
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise TypeError(
            f"--capability-registry root must be a JSON object, "
            f"got {type(parsed).__name__}"
        )
    policies = parsed.get("policies")
    if not isinstance(policies, list):
        raise TypeError(
            "--capability-registry must contain a top-level 'policies' "
            "array"
        )
    registry = CapabilityPolicyRegistry()
    for i, item in enumerate(policies):
        if not isinstance(item, dict):
            raise TypeError(
                f"--capability-registry policies[{i}] must be an object"
            )
        registry.add_policy(_policy_from_dict(item, index=i))
    return registry


def _policy_from_dict(item: Mapping[str, Any], *, index: int) -> CapabilityPolicy:
    """Construct a :class:`CapabilityPolicy` from a parsed JSON object.

    The function enforces the surface-level shape (required keys,
    tuple-vs-list conversion, RFC-3339 parsing for the optional
    validity window) and then defers structural validation to
    :class:`CapabilityPolicy.__post_init__`.
    """

    try:
        registered_by = item["registered_by"]
        allowed_kids = tuple(item["allowed_kids"])
        raw_triples = item["allowed_triples"]
    except KeyError as exc:
        raise TypeError(
            f"--capability-registry policies[{index}] missing key {exc}"
        )
    if not isinstance(raw_triples, list):
        raise TypeError(
            f"--capability-registry policies[{index}].allowed_triples "
            f"must be a list of [layer, name_glob] pairs"
        )
    triples: Tuple[Tuple[str, str], ...] = tuple(
        (t[0], t[1]) if isinstance(t, list) and len(t) == 2 else (None, None)  # type: ignore[arg-type]
        for t in raw_triples
    )
    not_before = _parse_optional_rfc3339(
        item.get("not_before"),
        flag=f"policies[{index}].not_before",
    )
    not_after = _parse_optional_rfc3339(
        item.get("not_after"),
        flag=f"policies[{index}].not_after",
    )
    disabled = bool(item.get("disabled", False))
    note = item.get("note")
    return CapabilityPolicy(
        registered_by=registered_by,
        allowed_kids=allowed_kids,
        allowed_triples=triples,
        not_before=not_before,
        not_after=not_after,
        disabled=disabled,
        note=note,
    )


def _parse_optional_rfc3339(
    value: Optional[str], *, flag: str
) -> Optional[_dt.datetime]:
    """Parse an optional RFC-3339 timestamp (with timezone) into UTC.

    Mirrors :func:`_parse_registered_at` for the policy-side dates.
    """

    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"--capability-registry {flag} must be a string or null")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    parsed = _dt.datetime.fromisoformat(s)
    if parsed.tzinfo is None:
        raise ValueError(
            f"--capability-registry {flag} {value!r} requires a timezone"
        )
    return parsed.astimezone(_dt.timezone.utc)


def _decision_to_dict(decision: CapabilityGateDecision) -> dict[str, Any]:
    """Render a :class:`CapabilityGateDecision` as a small JSON object
    for the receipt's ``gate_decision`` field.
    """

    return {
        "allowed": decision.allowed,
        "source": decision.source.value,
        "reason": decision.reason,
    }


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
    signed_entry: Optional[SignedSchemaRegistryEntry] = None
    gate_decision: Optional[CapabilityGateDecision] = None
    try:
        _validate_capability_flag_consistency(args)
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
        # Sprint-5 Tag-1: optional sign + gate pipeline. Both run
        # strictly between entry construction and backend write; a
        # deny short-circuits before the connect call so the bucket
        # is not touched.
        if getattr(args, "sign", False):
            priv_key = _load_ed25519_priv_key(
                hex_value=args.ed25519_priv_key_hex,
                file_value=args.ed25519_priv_key_file,
            )
            signed_entry = sign_entry(entry, priv_key, kid=args.kid)
        if getattr(args, "gate", False):
            assert signed_entry is not None  # consistency check above
            registry = _load_capability_registry(args.capability_registry)
            as_of = _parse_optional_rfc3339(
                args.gate_as_of, flag="--gate-as-of"
            )
            gate_decision = gate_signed_entry(
                signed_entry, registry, as_of=as_of
            )
            if not gate_decision.allowed:
                _print_error_stderr(
                    ExitCode.CAPABILITY_DENY,
                    (
                        f"capability deny ({gate_decision.source.value}): "
                        f"{gate_decision.reason}"
                    ),
                    stderr,
                )
                return int(ExitCode.CAPABILITY_DENY)
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
    except SchemaRegistrySignatureError as exc:
        _print_error_stderr(ExitCode.VALIDATION_ERROR, str(exc), stderr)
        return int(ExitCode.VALIDATION_ERROR)
    except RegisteredByCapabilityError as exc:
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
        signed=signed_entry is not None,
        kid=(signed_entry.signature["kid"] if signed_entry is not None else None),
        gate_decision=(
            _decision_to_dict(gate_decision) if gate_decision is not None else None
        ),
    )
    _print_receipt_stdout(receipt, stdout)
    return int(ExitCode.OK)


def _run_dry_run(
    args: argparse.Namespace, stdout, stderr
) -> int:
    signed_entry: Optional[SignedSchemaRegistryEntry] = None
    gate_decision: Optional[CapabilityGateDecision] = None
    try:
        _validate_capability_flag_consistency(args)
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
        # Sprint-5 Tag-1: optional sign + gate pipeline (dry-run also).
        if getattr(args, "sign", False):
            priv_key = _load_ed25519_priv_key(
                hex_value=args.ed25519_priv_key_hex,
                file_value=args.ed25519_priv_key_file,
            )
            signed_entry = sign_entry(entry, priv_key, kid=args.kid)
        if getattr(args, "gate", False):
            assert signed_entry is not None
            registry = _load_capability_registry(args.capability_registry)
            as_of = _parse_optional_rfc3339(
                args.gate_as_of, flag="--gate-as-of"
            )
            gate_decision = gate_signed_entry(
                signed_entry, registry, as_of=as_of
            )
            if not gate_decision.allowed:
                _print_error_stderr(
                    ExitCode.CAPABILITY_DENY,
                    (
                        f"capability deny ({gate_decision.source.value}): "
                        f"{gate_decision.reason}"
                    ),
                    stderr,
                )
                return int(ExitCode.CAPABILITY_DENY)
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
    except SchemaRegistrySignatureError as exc:
        _print_error_stderr(ExitCode.VALIDATION_ERROR, str(exc), stderr)
        return int(ExitCode.VALIDATION_ERROR)
    except RegisteredByCapabilityError as exc:
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
        signed=signed_entry is not None,
        kid=(signed_entry.signature["kid"] if signed_entry is not None else None),
        gate_decision=(
            _decision_to_dict(gate_decision) if gate_decision is not None else None
        ),
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
