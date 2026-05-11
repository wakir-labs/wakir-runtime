# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Operator publisher CLI for the Wirelang schema registry.

Phase-1b Sprint-3 Tag-5 — OI-7-Phase-1c-publisher.
Phase-2 Sprint-5 Tag-1 — capability-gating end-to-end integration.
Phase-2 Sprint-5 Tag-3 — ``--capability-bucket`` persistent-policy source.
Phase-2 Sprint-6 Tag-2 — ``revoke`` subcommand for explicit
capability-policy revocation (Sprint-6 Tag-1 backend axis).

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

Sprint-5 Tag-3 adds the ``--capability-bucket`` flag, an alternative
policy source that loads the capability registry from the persistent
``wakir-capability-policies`` NATS-KV bucket (Sprint-5 Tag-2
``capability_policy_nats_kv_backend.NatsKvCapabilityPolicyBackend``)
via :meth:`snapshot_registry`. Operators choose exactly one of
``--capability-registry`` (operator-local JSON file) or
``--capability-bucket`` (cluster-distributed persistent policies); the
gate decision is byte-identical regardless of source.

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

``revoke`` (Sprint-6 Tag-2)
    Apply an explicit revocation to an existing capability-policy
    record on the ``wakir-capability-policies`` bucket. This
    subcommand does NOT touch the ``wakir-schemas`` schema-registry
    bucket; it mutates a capability-policy record in place by reading
    the live record, attaching ``revoked_at`` / ``revocation_reason``,
    and writing back via either CAS-pin (default, safe) or LWW
    (``--lww`` opt-in, escape-hatch for operator-deliberate un-revoke
    semantics — note that an un-revoke via CAS-pin is rejected by the
    backend revocation-monotonicity invariant). The receipt records
    the chosen mode, the old/new KV revision, and the revocation
    instant; a CAS-pin conflict surfaces with the new
    :class:`ExitCode.REVOCATION_CONFLICT` (8) so pipelines can
    distinguish "stale revision" from "revocation-monotonic refusal".

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
from wirelang.schemas.capability_policy_nats_kv_backend import (
    BUCKET_NAME as CAPABILITY_BUCKET_NAME,
    CapabilityPolicyBackendError,
    CapabilityPolicyConflictError,
    CapabilityPolicyEnvelopeError,
    CapabilityPolicyRecord,
    CapabilityPolicyRevocationConflict,
    CapabilityPolicyValidationError,
    NatsKvCapabilityPolicyBackend,
    key_for_policy_pair,
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
    REVOCATION_CONFLICT = 8  # Sprint-6 Tag-2: revoke CAS-pin path tripped
    #                          the Sprint-6 Tag-1 revocation-monotonicity
    #                          invariant (un-revoke or advance-instant).
    REVOKE_TARGET_NOT_FOUND = 9  # Sprint-6 Tag-2: revoke target
    #                              (registered_by, policy_id) does not
    #                              exist on the bucket. Distinct from
    #                              INPUT_ERROR so pipelines can detect
    #                              "policy never existed" vs. "operator
    #                              typo in flag".


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

    Sprint-5 Tag-3 additions
    ------------------------

    One further field audits the policy-source axis:

    - ``gate_policy_source``: ``"file"`` when ``--capability-registry``
      was used; ``"bucket"`` when ``--capability-bucket`` was used;
      ``None`` when ``--gate`` was not requested. The gate decision
      itself is byte-identical regardless of source; this audit field
      records the operator's chosen source so deploy pipelines can
      assert on it (e.g. "all production publishes must use
      ``gate_policy_source == 'bucket'``").
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
    gate_policy_source: Optional[str] = None

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
            "gate_policy_source": self.gate_policy_source,
        }


# ---------------------------------------------------------------------------
# Revoke receipt shape (Sprint-6 Tag-2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RevokeReceipt:
    """Canonical receipt printed on stdout on success of ``revoke``.

    Phase-2 Sprint-6 Tag-2 — distinct from :class:`PublishReceipt`
    because the revoke path operates on a different bucket
    (``wakir-capability-policies``) with a different identity-pair
    surface (``registered_by, policy_id``) and a different mutation
    semantic (modify-in-place vs. publish-new). Two distinct dataclasses
    keep each receipt's invariants narrow and self-documenting; the
    receipt's top-level ``cmd`` field disambiguates them at the JSON
    layer so downstream consumers can dispatch generically.

    Fields
    ------

    - ``cmd``: always ``"revoke"``. Pipelines can use this to switch on
      receipt shape without needing to inspect mode.
    - ``mode``: ``"cas"`` (default, CAS-pinned write) or ``"lww"``
      (last-write-wins escape-hatch; bypasses the revocation-monotonic
      backend gate).
    - ``key``: the canonical KV key
      ``capability-policies/<registered_by>/<policy_id>``.
    - ``registered_by`` / ``policy_id``: the policy identity pair.
    - ``revoked_at``: RFC-3339 UTC instant of the applied revocation.
    - ``revocation_reason``: the free-form audit string (or ``None``).
    - ``expected_revision``: the revision the CLI pinned for CAS, or
      ``None`` on the ``--lww`` path.
    - ``previous_revision``: the live revision that the CLI READ from
      the bucket before applying the write (always present so audit
      trails can correlate the read↔write pair).
    - ``new_revision``: the revision the bucket assigned after the
      write succeeded.
    - ``registered_at``: the new ``registered_at`` set on the rewritten
      record (RFC-3339 UTC). Defaults to ``now`` unless the operator
      passes ``--registered-at``.
    - ``registered_by_publisher``: the operator-identifier of who
      authored the revocation (audit field; mirrors the publish
      receipt's audit gesture).
    """

    cmd: str  # always "revoke"
    mode: str  # "cas" | "lww"
    key: str
    registered_by: str
    policy_id: str
    revoked_at: str
    revocation_reason: Optional[str]
    expected_revision: Optional[int]
    previous_revision: int
    new_revision: int
    registered_at: str
    registered_by_publisher: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "cmd": self.cmd,
            "mode": self.mode,
            "key": self.key,
            "registered_by": self.registered_by,
            "policy_id": self.policy_id,
            "revoked_at": self.revoked_at,
            "revocation_reason": self.revocation_reason,
            "expected_revision": self.expected_revision,
            "previous_revision": self.previous_revision,
            "new_revision": self.new_revision,
            "registered_at": self.registered_at,
            "registered_by_publisher": self.registered_by_publisher,
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

    p_rev = sub.add_parser(
        "revoke",
        help=(
            "Apply an explicit revocation to a capability-policy "
            "record on the wakir-capability-policies bucket "
            "(Sprint-6 Tag-2)."
        ),
    )
    _add_revoke_flags(p_rev)

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
    """Sprint-5 Tag-1/3 capability flags (shared by ``publish`` and
    ``dry-run``).

    Four concerns are wired in:

    - ``--sign`` plus a private-key source (``--ed25519-priv-key-hex``
      XOR ``--ed25519-priv-key-file``) plus ``--kid`` enable signing
      via :func:`wirelang.schemas.entry_signing.sign_entry`.

    - ``--gate`` enables gating via
      :func:`wirelang.schemas.registered_by_capability.gate_signed_entry`.
      ``--gate`` requires ``--sign`` (the gate reads ``kid`` from the
      signature block) AND exactly one policy source.

    - **Policy source** (Sprint-5 Tag-3): exactly one of
      ``--capability-registry <path>`` (operator-local JSON file,
      Sprint-5 Tag-1) or ``--capability-bucket`` (persistent
      ``wakir-capability-policies`` NATS-KV bucket loaded via
      :meth:`NatsKvCapabilityPolicyBackend.snapshot_registry`,
      Sprint-5 Tag-3). The two sources are mutually exclusive at
      argparse level; the gate decision is byte-identical regardless
      of source.

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
            "before publishing (requires --sign and exactly one of "
            "--capability-registry or --capability-bucket)."
        ),
    )
    policy_src = p.add_mutually_exclusive_group()
    policy_src.add_argument(
        "--capability-registry",
        default=None,
        help=(
            "Path to a capability-registry JSON file (top-level "
            "{policies: [...]}). Operator-local source. Mutually "
            "exclusive with --capability-bucket. Required when --gate "
            "is set unless --capability-bucket is supplied."
        ),
    )
    policy_src.add_argument(
        "--capability-bucket",
        action="store_true",
        help=(
            "Load capability policies from the persistent NATS-KV "
            "bucket wakir-capability-policies (Sprint-5 Tag-2 backend) "
            "via NatsKvCapabilityPolicyBackend.snapshot_registry(). "
            "Mutually exclusive with --capability-registry. Connection "
            "URL defaults to --capability-bucket-connect-url. Required "
            "when --gate is set unless --capability-registry is "
            "supplied."
        ),
    )
    p.add_argument(
        "--capability-bucket-connect-url",
        default="nats://127.0.0.1:4222",
        help=(
            "NATS connect URL for the capability-policy bucket "
            "(default %(default)s). Used only with "
            "--capability-bucket."
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
# Sprint-6 Tag-2 — revoke subcommand flags
# ---------------------------------------------------------------------------


def _add_revoke_flags(p: argparse.ArgumentParser) -> None:
    """Operator-input flags for the ``revoke`` subcommand.

    Five concerns are wired in:

    - **Identity pair** (``--registered-by`` + ``--policy-id``):
      identifies the capability-policy record on the
      ``wakir-capability-policies`` bucket. Both required.

    - **Revocation payload** (``--revoked-at`` + optional
      ``--revocation-reason``): the wall-clock instant at which the
      revocation takes effect (RFC-3339 with timezone) and an optional
      free-form audit string. The instant is the canonical surface
      that downstream gate decisions (Sprint-4 Tag-6 + Sprint-6 Tag-1)
      use to deny.

    - **Audit field** (``--registered-by-publisher``): who is
      authoring the revocation, recorded on the rewritten record.
      Required so the bucket history has a non-ambiguous audit trail
      of which operator pressed the button.

    - **Write mode** (``--expected-revision N`` XOR ``--lww``):
      CAS-pin is the default (safer); LWW is an explicit opt-in
      escape-hatch for operator-deliberate semantics. CAS-pin requires
      the operator to declare the revision they observed via a prior
      read; LWW does not. The Sprint-6 Tag-1 revocation-monotonic
      backend invariant runs ONLY on CAS-pin, by design.

    - **Connection** (``--connect-url``): NATS connect URL for the
      capability-policy bucket; default ``nats://127.0.0.1:4222``.

    Two further flags shape the rewritten record's bookkeeping fields
    (mirrors the publish path):

    - ``--registered-at``: optional RFC-3339 override for the
      ``registered_at`` field on the rewritten record. Defaults to
      current UTC when omitted; deterministic test paths supply it.
    """

    p.add_argument(
        "--registered-by",
        required=True,
        help=(
            "registered_by of the capability-policy record to revoke. "
            "Component of the canonical KV key."
        ),
    )
    p.add_argument(
        "--policy-id",
        required=True,
        help=(
            "policy_id of the capability-policy record to revoke. "
            "Component of the canonical KV key."
        ),
    )
    p.add_argument(
        "--revoked-at",
        required=True,
        help=(
            "Wall-clock instant of the revocation (RFC-3339, with "
            "timezone, e.g. 2026-05-11T22:00:00Z). The gate denies any "
            "as_of >= this instant with source POLICY_REVOKED."
        ),
    )
    p.add_argument(
        "--revocation-reason",
        default=None,
        help=(
            "Optional free-form audit string surfaced in the gate's "
            "deny reason and persisted on the record."
        ),
    )
    p.add_argument(
        "--registered-by-publisher",
        required=True,
        help=(
            "Operator-identifier authoring the revocation write. "
            "Recorded on the rewritten record's registered_by_publisher "
            "field for audit. NOT the same as --registered-by (which "
            "names the policy issuer being revoked)."
        ),
    )
    p.add_argument(
        "--registered-at",
        default=None,
        help=(
            "Optional RFC-3339 instant (with timezone) set on the "
            "rewritten record's registered_at field. Defaults to the "
            "current UTC instant; deterministic test paths supply it "
            "explicitly."
        ),
    )

    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--expected-revision",
        type=int,
        default=None,
        help=(
            "CAS-pin: pass the revision observed by a prior read "
            "(get_with_revision_by_pair). The CLI ALSO reads the live "
            "revision before the write so the receipt always records "
            "previous_revision; --expected-revision MUST match that "
            "live revision or the write fails with CAS_CONFLICT. "
            "Mutually exclusive with --lww."
        ),
    )
    mode.add_argument(
        "--lww",
        action="store_true",
        help=(
            "Last-write-wins escape-hatch. Bypasses the Sprint-6 "
            "Tag-1 revocation-monotonic backend invariant; permits "
            "operator-deliberate semantics (e.g. an authorised "
            "un-revoke). Mutually exclusive with --expected-revision. "
            "Default is CAS-pin (no --lww, no --expected-revision => "
            "CLI auto-reads live revision and pins to it)."
        ),
    )
    p.add_argument(
        "--connect-url",
        default="nats://127.0.0.1:4222",
        help=(
            "NATS connect URL for the wakir-capability-policies bucket "
            "(default %(default)s)."
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
    4. ``--gate`` requires exactly one of ``--capability-registry`` or
       ``--capability-bucket`` (no implicit empty registry — the deny
       semantics differ from explicit empty). The two sources are
       mutex at the argparse layer; absence is checked here.
    5. ``--kid`` / ``--ed25519-priv-key-*`` / ``--capability-registry``
       / ``--capability-bucket`` / ``--gate-as-of`` without
       ``--sign`` / ``--gate`` is a usage error (no-op flag is
       reported, not silently ignored).

    Sprint-5 Tag-3 adds invariant 4's bucket-source axis. The
    ``--capability-bucket-connect-url`` flag has a non-None default
    so it is not an "orphan" when present without
    ``--capability-bucket``; the connect URL is simply ignored when
    bucket mode is off.
    """

    sign = getattr(args, "sign", False)
    gate = getattr(args, "gate", False)
    kid = getattr(args, "kid", None)
    hex_key = getattr(args, "ed25519_priv_key_hex", None)
    file_key = getattr(args, "ed25519_priv_key_file", None)
    cap_path = getattr(args, "capability_registry", None)
    cap_bucket = getattr(args, "capability_bucket", False)
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
        if cap_path is None and not cap_bucket:
            raise ValueError(
                "--gate requires --capability-registry <path> or "
                "--capability-bucket"
            )
    else:
        if cap_path is not None or cap_bucket or gate_as_of is not None:
            raise ValueError(
                "--capability-registry / --capability-bucket / "
                "--gate-as-of require --gate"
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

#: Sprint-5 Tag-3 capability-bucket factory type. Mirrors
#: :data:`ConnectFactory` but yields a
#: :class:`NatsKvCapabilityPolicyBackend` against the
#: ``wakir-capability-policies`` bucket. Tests inject a factory that
#: returns an in-memory mock backend.
CapabilityBucketConnectFactory = Callable[
    [str],
    Awaitable[Tuple[NatsKvCapabilityPolicyBackend, Callable[[], Awaitable[None]]]],
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


async def _default_capability_bucket_factory(
    connect_url: str,
) -> Tuple[NatsKvCapabilityPolicyBackend, Callable[[], Awaitable[None]]]:
    """Default capability-bucket factory (Sprint-5 Tag-3).

    Connects to NATS and returns a
    :class:`NatsKvCapabilityPolicyBackend` against the
    ``wakir-capability-policies`` bucket. Late-imports nats-py so the
    CLI module loads cleanly in hermetic test environments.
    """

    # Late import: hermetic test paths never exercise this branch.
    import nats  # type: ignore

    nc = await nats.connect(connect_url)
    js = nc.jetstream()
    kv = await js.key_value(CAPABILITY_BUCKET_NAME)
    backend = NatsKvCapabilityPolicyBackend(kv=kv)

    async def _cleanup() -> None:
        await nc.drain()
        await nc.close()

    return backend, _cleanup


async def _load_capability_registry_from_bucket(
    factory: CapabilityBucketConnectFactory, connect_url: str
) -> CapabilityPolicyRegistry:
    """Load a :class:`CapabilityPolicyRegistry` from the persistent
    capability-policy bucket (Sprint-5 Tag-3).

    Opens the bucket via ``factory(connect_url)``, calls
    :meth:`NatsKvCapabilityPolicyBackend.snapshot_registry` and closes
    the connection. Any backend / decode error propagates verbatim so
    the caller can route it through ``ExitCode.BACKEND_ERROR`` (live
    backend transport) or ``ExitCode.VALIDATION_ERROR`` (poisoned
    envelope on the bucket).
    """

    backend, cleanup = await factory(connect_url)
    try:
        return await backend.snapshot_registry()
    finally:
        try:
            await cleanup()
        except Exception:
            # Cleanup failures must NOT mask the snapshot outcome.
            pass


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
    capability_bucket_factory: Optional[CapabilityBucketConnectFactory] = None,
) -> int:
    mode, expected_revision = _resolve_mode(args)
    signed_entry: Optional[SignedSchemaRegistryEntry] = None
    gate_decision: Optional[CapabilityGateDecision] = None
    gate_policy_source: Optional[str] = None
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
            # Sprint-5 Tag-3: two policy sources, mutually exclusive.
            if getattr(args, "capability_bucket", False):
                factory = (
                    capability_bucket_factory
                    if capability_bucket_factory is not None
                    else _default_capability_bucket_factory
                )
                registry = await _load_capability_registry_from_bucket(
                    factory, args.capability_bucket_connect_url
                )
                gate_policy_source = "bucket"
            else:
                registry = _load_capability_registry(args.capability_registry)
                gate_policy_source = "file"
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
    except CapabilityPolicyBackendError as exc:
        # Sprint-5 Tag-3: poisoned bucket envelope or non-JSON value.
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
        gate_policy_source=gate_policy_source,
    )
    _print_receipt_stdout(receipt, stdout)
    return int(ExitCode.OK)


async def _run_revoke(
    args: argparse.Namespace,
    capability_bucket_factory: CapabilityBucketConnectFactory,
    stdout,
    stderr,
) -> int:
    """Apply an explicit revocation to a capability-policy record.

    Phase-2 Sprint-6 Tag-2 — operator surface for the Sprint-6 Tag-1
    backend axis. The flow is intentionally narrow:

    1. Parse + validate the revocation payload (``--revoked-at`` must
       parse and carry a timezone; ``--registered-by-publisher`` must
       be non-empty).
    2. Connect to the capability-policy bucket via the injected
       factory (tests inject a mock; production uses
       :func:`_default_capability_bucket_factory`).
    3. Read the live record via
       :meth:`get_with_revision_by_pair`. A missing record raises
       :class:`ExitCode.REVOKE_TARGET_NOT_FOUND` (9) — distinct from
       INPUT_ERROR so pipelines can distinguish "policy never existed"
       from "operator typo in argparse".
    4. Construct the rewritten record by replacing the policy's
       ``revoked_at`` / ``revocation_reason`` fields (all other
       capability-bundle fields are preserved byte-equally; the
       backend's revocation-monotonic invariant guards the CAS-pin
       path against un-revoke / advance-instant).
    5. Choose the write path:
       - default + ``--expected-revision N``: CAS-pin via
         :meth:`put_with_revision`. The CLI checks the operator's
         ``--expected-revision`` against the live revision returned by
         step 3; a mismatch surfaces with
         :class:`ExitCode.CAS_CONFLICT` (5) BEFORE the write call
         touches the bucket (saves a round-trip and gives a clearer
         error than the backend's post-update CAS exception).
       - default + no ``--expected-revision``: CAS-pin pinned to the
         live revision read in step 3 (auto-pin path).
       - ``--lww``: LWW via :meth:`put`. Bypasses the Sprint-6 Tag-1
         backend revocation-monotonic invariant.
    6. Emit the canonical :class:`RevokeReceipt` on stdout.

    Connection cleanup runs in the ``finally`` block. Cleanup failures
    never mask the write outcome (mirror of the publish path).
    """

    backend: Optional[NatsKvCapabilityPolicyBackend] = None
    cleanup: Optional[Callable[[], Awaitable[None]]] = None
    try:
        # Step 1 — payload validation (pre-connect, so a malformed flag
        # never opens a NATS connection).
        try:
            revoked_at = _parse_registered_at(args.revoked_at)
        except ValueError as exc:
            _print_error_stderr(
                ExitCode.INPUT_ERROR,
                f"--revoked-at parse error: {exc}",
                stderr,
            )
            return int(ExitCode.INPUT_ERROR)
        if not isinstance(args.registered_by_publisher, str) or not (
            args.registered_by_publisher.strip()
        ):
            _print_error_stderr(
                ExitCode.INPUT_ERROR,
                "--registered-by-publisher must be a non-empty string",
                stderr,
            )
            return int(ExitCode.INPUT_ERROR)
        if (
            args.revocation_reason is not None
            and not isinstance(args.revocation_reason, str)
        ):
            # argparse always hands us str-or-None, but pin the
            # invariant defensively (mirrors the publish-path style).
            _print_error_stderr(
                ExitCode.INPUT_ERROR,
                "--revocation-reason must be a string (or omitted)",
                stderr,
            )
            return int(ExitCode.INPUT_ERROR)
        # Eagerly validate the identity-pair surface (raises ValueError
        # for malformed components; the backend would catch it too but
        # we want a clean INPUT_ERROR before any connect).
        try:
            key = key_for_policy_pair(args.registered_by, args.policy_id)
        except ValueError as exc:
            _print_error_stderr(
                ExitCode.INPUT_ERROR,
                f"--registered-by / --policy-id invalid: {exc}",
                stderr,
            )
            return int(ExitCode.INPUT_ERROR)
        registered_at = _parse_registered_at(args.registered_at)
        use_lww = bool(getattr(args, "lww", False))
        operator_expected_revision: Optional[int] = getattr(
            args, "expected_revision", None
        )

        # Step 2 — connect.
        backend, cleanup = await capability_bucket_factory(args.connect_url)

        # Step 3 — read the live record.
        try:
            read_result = await backend.get_with_revision_by_pair(
                args.registered_by, args.policy_id
            )
        except CapabilityPolicyEnvelopeError as exc:
            _print_error_stderr(
                ExitCode.VALIDATION_ERROR,
                f"live capability-policy envelope is poisoned: {exc}",
                stderr,
            )
            return int(ExitCode.VALIDATION_ERROR)
        if read_result is None:
            _print_error_stderr(
                ExitCode.REVOKE_TARGET_NOT_FOUND,
                (
                    f"capability-policy record not found: "
                    f"registered_by={args.registered_by!r} "
                    f"policy_id={args.policy_id!r} (key={key!r})"
                ),
                stderr,
            )
            return int(ExitCode.REVOKE_TARGET_NOT_FOUND)
        live_record, live_revision = read_result

        # Step 4 — construct the rewritten record. We preserve every
        # capability-bundle field byte-equally and overlay only
        # revoked_at + revocation_reason. Re-using dataclasses.replace
        # would also work but the explicit construction makes the
        # invariant-preservation contract self-documenting.
        from dataclasses import replace

        try:
            new_policy = replace(
                live_record.policy,
                revoked_at=revoked_at,
                revocation_reason=args.revocation_reason,
            )
            new_record = CapabilityPolicyRecord(
                policy=new_policy,
                policy_id=live_record.policy_id,
                registered_at=registered_at,
                registered_by_publisher=args.registered_by_publisher,
            )
        except (RegisteredByCapabilityError, CapabilityPolicyValidationError) as exc:
            _print_error_stderr(
                ExitCode.VALIDATION_ERROR,
                f"rewritten record is invalid: {exc}",
                stderr,
            )
            return int(ExitCode.VALIDATION_ERROR)

        # Step 5 — write path selection.
        mode_label: str
        expected_revision_recorded: Optional[int] = None
        try:
            if use_lww:
                mode_label = "lww"
                new_revision = await backend.put(new_record)
            else:
                mode_label = "cas"
                # Operator-supplied --expected-revision MUST match the
                # live revision the CLI just read. A mismatch is a
                # CAS_CONFLICT surfaced BEFORE the backend call (no
                # bucket touch on the publish side; the backend would
                # also reject it but we save a round-trip and give a
                # clearer error message).
                if operator_expected_revision is not None:
                    if operator_expected_revision != live_revision:
                        _print_error_stderr(
                            ExitCode.CAS_CONFLICT,
                            (
                                f"--expected-revision "
                                f"{operator_expected_revision} does not "
                                f"match live revision {live_revision} "
                                f"for key {key!r}: re-read the record "
                                f"and retry"
                            ),
                            stderr,
                        )
                        return int(ExitCode.CAS_CONFLICT)
                    expected_revision_recorded = operator_expected_revision
                else:
                    expected_revision_recorded = live_revision
                new_revision = await backend.put_with_revision(
                    new_record, expected_revision=live_revision
                )
        except CapabilityPolicyRevocationConflict as exc:
            _print_error_stderr(
                ExitCode.REVOCATION_CONFLICT,
                (
                    f"revocation-monotonic backend invariant tripped: "
                    f"{exc} (existing_revoked_at="
                    f"{exc.existing_revoked_at!r}, proposed_revoked_at="
                    f"{exc.proposed_revoked_at!r})"
                ),
                stderr,
            )
            return int(ExitCode.REVOCATION_CONFLICT)
        except CapabilityPolicyConflictError as exc:
            _print_error_stderr(ExitCode.CAS_CONFLICT, str(exc), stderr)
            return int(ExitCode.CAS_CONFLICT)
        except CapabilityPolicyValidationError as exc:
            _print_error_stderr(ExitCode.VALIDATION_ERROR, str(exc), stderr)
            return int(ExitCode.VALIDATION_ERROR)
        except CapabilityPolicyEnvelopeError as exc:
            _print_error_stderr(ExitCode.VALIDATION_ERROR, str(exc), stderr)
            return int(ExitCode.VALIDATION_ERROR)
        except CapabilityPolicyBackendError as exc:
            _print_error_stderr(ExitCode.BACKEND_ERROR, str(exc), stderr)
            return int(ExitCode.BACKEND_ERROR)
        except Exception as exc:  # transport / unknown
            _print_error_stderr(
                ExitCode.BACKEND_ERROR,
                f"backend error: {type(exc).__name__}: {exc}",
                stderr,
            )
            return int(ExitCode.BACKEND_ERROR)

        receipt = RevokeReceipt(
            cmd="revoke",
            mode=mode_label,
            key=key,
            registered_by=args.registered_by,
            policy_id=args.policy_id,
            revoked_at=revoked_at.isoformat().replace("+00:00", "Z"),
            revocation_reason=args.revocation_reason,
            expected_revision=expected_revision_recorded,
            previous_revision=live_revision,
            new_revision=new_revision,
            registered_at=(
                registered_at.isoformat().replace("+00:00", "Z")
            ),
            registered_by_publisher=args.registered_by_publisher,
        )
        _print_receipt_stdout(receipt, stdout)
        return int(ExitCode.OK)
    finally:
        if cleanup is not None:
            try:
                await cleanup()
            except Exception:
                # Cleanup failures must NOT mask the revoke outcome.
                pass


async def _run_dry_run_async(
    args: argparse.Namespace,
    stdout,
    stderr,
    capability_bucket_factory: Optional[CapabilityBucketConnectFactory] = None,
) -> int:
    signed_entry: Optional[SignedSchemaRegistryEntry] = None
    gate_decision: Optional[CapabilityGateDecision] = None
    gate_policy_source: Optional[str] = None
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
            # Sprint-5 Tag-3: two policy sources, mutually exclusive.
            if getattr(args, "capability_bucket", False):
                factory = (
                    capability_bucket_factory
                    if capability_bucket_factory is not None
                    else _default_capability_bucket_factory
                )
                registry = await _load_capability_registry_from_bucket(
                    factory, args.capability_bucket_connect_url
                )
                gate_policy_source = "bucket"
            else:
                registry = _load_capability_registry(args.capability_registry)
                gate_policy_source = "file"
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
    except CapabilityPolicyBackendError as exc:
        # Sprint-5 Tag-3: poisoned bucket envelope or non-JSON value.
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
        gate_policy_source=gate_policy_source,
    )
    _print_receipt_stdout(receipt, stdout)
    return int(ExitCode.OK)


def _run_dry_run(
    args: argparse.Namespace,
    stdout,
    stderr,
    capability_bucket_factory: Optional[CapabilityBucketConnectFactory] = None,
) -> int:
    """Synchronous wrapper around :func:`_run_dry_run_async`.

    Dry-run uses a single short-lived ``asyncio.run`` only when the
    capability-bucket path is active; the pure-file path does not need
    an event loop at all but the wrapper is uniformly async-routed so
    the surface is the same for both sources.
    """
    return asyncio.run(
        _run_dry_run_async(args, stdout, stderr, capability_bucket_factory)
    )


def run(
    argv: Optional[Sequence[str]] = None,
    *,
    connect_factory: Optional[ConnectFactory] = None,
    capability_bucket_factory: Optional[CapabilityBucketConnectFactory] = None,
    stdout=None,
    stderr=None,
) -> int:
    """Argparse-driven entry-point.

    ``argv`` defaults to ``sys.argv[1:]``. ``connect_factory`` defaults
    to :func:`_default_connect_factory` which requires nats-py at
    runtime. ``capability_bucket_factory`` (Sprint-5 Tag-3) defaults to
    :func:`_default_capability_bucket_factory` and is used only when
    ``--capability-bucket`` is set. Tests inject factories that return
    in-memory backends.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr

    if args.cmd == "dry-run":
        return _run_dry_run(args, out, err, capability_bucket_factory)

    if args.cmd == "revoke":
        revoke_factory = (
            capability_bucket_factory
            if capability_bucket_factory is not None
            else _default_capability_bucket_factory
        )
        return asyncio.run(_run_revoke(args, revoke_factory, out, err))

    factory = (
        connect_factory if connect_factory is not None else _default_connect_factory
    )
    return asyncio.run(
        _run_publish(args, factory, out, err, capability_bucket_factory)
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
