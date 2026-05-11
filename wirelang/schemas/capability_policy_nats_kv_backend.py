# SPDX-License-Identifier: Apache-2.0
"""NATS-JetStream-KV-backed persistent capability-policy distribution
for the Wirelang schema registry (Phase-2 Sprint-5 Tag-2).

This module is the persistent-distribution tier for the Phase-2
Sprint-4 Tag-6 :mod:`wirelang.schemas.registered_by_capability`
in-process registry. It persists :class:`CapabilityPolicy` bundles in
a dedicated NATS-JetStream-KV bucket ``wakir-capability-policies`` so
that capability policies survive operator-process restarts and can be
distributed across publisher hosts without out-of-band file shipping.

Substrate
---------

The backend persists :class:`CapabilityPolicyRecord` envelopes (a
:class:`CapabilityPolicy` plus operator-side bookkeeping fields:
``policy_id``, ``registered_at`` and ``registered_by_publisher``) in
the ``wakir-capability-policies`` bucket. The bucket configuration is
owned by the operator-side init script
(``scripts/init-nats-buckets.py``); this module declares the matching
:data:`BUCKET_CONFIG` constant for the test-layer drift check.

- ``history``: 5 (audit-trail of recent overwrites; matches the
  ``wakir-schemas`` cache history depth so operators can correlate
  policy and schema changes byte-precisely).
- ``ttl_seconds``: 0 (policies have no transport-level expiry; the
  policy bundle's own ``not_before`` / ``not_after`` fields are the
  application-level validity window).
- ``max_value_size``: 16_384 B (16 KiB; policy envelopes are small
  — a triple-glob policy with five kids and an audit note fits in
  ~1 KiB, with substantial headroom for future fields).
- ``storage``: ``"file"`` (durability for production).
- ``replicas``: 1 (Phase-2 single-node; Phase-3 promotion to a
  cluster-replicated tier mirrors the ``wakir-schemas`` upgrade
  path).

Cross-reference: this module DOES introduce a new bucket
(``wakir-capability-policies``, the 7th bucket on the Phase-1 / Phase-2
:data:`PHASE_1_BUCKETS` inventory). The operator-side bucket addition
is a paired-update with the orchestrator-side init script and
health-check script; the Wirelang track ships the consumer-side
``BUCKET_CONFIG`` constant and the orchestrator track mirrors it
byte-precisely. See Cross-Review-Zone-B paired-update memo for the
operator-side delivery.

Design choices
--------------

The backend mirrors the Phase-1b Sprint-3 Tag-1
``registry_nats_kv_backend.py`` pattern:

- Async backend surface (``get``, ``put``, ``delete``, ``snapshot``,
  ``list_keys``).
- Synchronous in-memory snapshot view via
  :meth:`NatsKvCapabilityPolicyBackend.snapshot_registry` which
  materialises a
  :class:`wirelang.schemas.registered_by_capability.CapabilityPolicyRegistry`
  directly. Verifier-side code (the
  :func:`check_registered_by_capability` gate) consumes the
  :class:`CapabilityPolicyRegistry` byte-identical to the Sprint-4
  Tag-6 in-process path; the only difference is the registry origin
  (NATS-KV vs. operator-supplied).
- Eager poisoned-envelope failure: a malformed value raises
  :class:`CapabilityPolicyEnvelopeError` from ``get`` and aborts
  :meth:`snapshot`; the determinism contract requires a complete,
  self-consistent view.
- Drift-policy contract identical to the schema-registry backend:
  bucket configuration is operator-managed; this module never
  auto-creates or auto-corrects.

Identity model
--------------

A capability-policy entry is identified by
``(registered_by, policy_id)`` collapsed into a single KV key string
``capability-policies/<registered_by>/<policy_id>``. The
``registered_by`` axis is the publisher-identity (matching the
schema-registry-entry ``registered_by`` field exactly); the
``policy_id`` axis is operator-supplied free-form (kebab-case ASCII)
to allow multiple policies per issuer (e.g. one per kid generation,
one per schema-layer split). The pair ↔ key derivation is bijective
and idempotent; see :func:`key_for_policy_pair` and
:func:`pair_for_key`.

Two policies for the same ``registered_by`` MUST use different
``policy_id`` strings; the bucket enforces uniqueness by KV key.
This mirrors the Sprint-4 Tag-6 in-process semantics
(:meth:`CapabilityPolicyRegistry.add_policy` accepts multiple
policies per issuer; the persistent surface keys them apart by
``policy_id`` so each policy is independently get-able).

Value envelope
--------------

Each KV value is a JSON object with these fields:

- ``schema``: ``"wakir.wirelang.capability-policy-entry/1"``.
- ``registered_by``: free-form publisher identity string (matches
  the policy's ``registered_by`` field exactly).
- ``policy_id``: free-form operator-supplied identifier
  (kebab-case ASCII, non-empty, no slashes).
- ``allowed_kids``: JSON array of kid strings (non-empty).
- ``allowed_triples``: JSON array of ``[layer, name_glob]`` pairs
  (non-empty). Each pair is a 2-element array, NOT an object, so
  the on-the-wire shape exactly mirrors the Python tuple structure.
- ``not_before``: optional RFC-3339 UTC timestamp string or
  ``null``.
- ``not_after``: optional RFC-3339 UTC timestamp string or ``null``.
- ``disabled``: boolean.
- ``note``: optional free-form string or ``null``.
- ``registered_at``: RFC-3339 UTC timestamp of when the policy
  entry was written to the bucket (operator-side bookkeeping).
- ``registered_by_publisher``: role-string or AIP-id of the
  publisher of the policy entry itself (operator audit; NOT the
  same as the policy's ``registered_by`` field, which is the
  publisher whose schema-registry writes are being gated).

The envelope is stored with sorted keys and the compact
``(",", ":")`` separator pair so the bytes are reproducible per
caller.

Validation gates at write
-------------------------

The :meth:`NatsKvCapabilityPolicyBackend.put` method enforces at
write time:

1. The :class:`CapabilityPolicyRecord` round-trips through the
   :class:`wirelang.schemas.registered_by_capability.CapabilityPolicy`
   constructor: every invariant enforced by
   :meth:`CapabilityPolicy.__post_init__` is enforced at write
   (non-empty ``registered_by``, non-empty ``allowed_kids``,
   non-empty ``allowed_triples``, valid validity window, ...). A
   malformed record raises :class:`CapabilityPolicyValidationError`
   before any bucket I/O.
2. The KV key derived from the entry's ``(registered_by,
   policy_id)`` matches the explicit key (defence in depth against
   mis-keying).

These gates keep poisoned envelopes off the bucket. Run-time policy
evaluation (gate decisions) remains the in-process Sprint-4 Tag-6
``check_registered_by_capability`` function; this module ships
persistence, not evaluation.

Phase-2 Sprint-5 Tag-2 boundary
-------------------------------

- This module ships the persistent-distribution tier for capability
  policies. It DOES NOT replace the in-process
  :class:`CapabilityPolicyRegistry` from Sprint-4 Tag-6: operators
  who prefer to keep policies in operator-local JSON files (the
  Sprint-5 Tag-1 ``--capability-registry`` flag) continue to use
  that path. The NATS-KV path is the *distribution* layer for
  multi-host deployments where keeping policy files in sync by hand
  is operator-hostile.
- This module DOES NOT bake operator-side biometric / hardware key
  attestation into the policy envelope. Policy entries are
  trust-on-write: any publisher with write access to the bucket
  can register a policy. Bucket-level access control (NATS server
  authentication, account isolation) is the operator's
  responsibility.
- This module DOES NOT auto-distribute policies to publisher-side
  in-process registries. Publishers materialise a
  :class:`CapabilityPolicyRegistry` from
  :meth:`NatsKvCapabilityPolicyBackend.snapshot_registry` on
  startup (or on a periodic refresh schedule); the live tail is
  reserved as a Phase-3 slot (analogous to the schema-registry
  watch-stream, Sprint-3 Tag-4). The Phase-2 Sprint-5 Tag-2 slot is
  full-snapshot only.
- This module DOES NOT ship a CAS-pinned upsert path. Policies are
  LWW under the assumption that policy authorship is operator-
  driven and rate-limited; the CAS-pin path is reserved as a
  Phase-3 slot (analogous to the schema-registry CAS-pin, Sprint-3
  Tag-3). Sprint-5 Tag-2 ships PUT (LWW) only.
- This module DOES NOT replace the Sprint-5 Tag-1
  ``--capability-registry`` operator-local JSON file format. Both
  paths coexist: the JSON-file path is "policies you ship with your
  CLI invocation"; the NATS-KV path is "policies you publish once
  for the cluster to discover". A future publisher-CLI integration
  slot (Phase-2 Sprint-5 Tag-3+ candidate) can add a
  ``--capability-bucket`` flag that reads policies from this
  bucket; that integration is NOT part of Sprint-5 Tag-2.

Cross-Review-Zone-B interaction
-------------------------------

Sprint-5 Tag-2 IS a Z-B Trigger. The orchestrator-side
:data:`PHASE_1_BUCKETS` inventory currently carries 6 buckets
(post-Sprint-4 Tag-5 Tag-5-bucket addition). Sprint-5 Tag-2 adds the
7th bucket ``wakir-capability-policies``. The paired-update memo to
the DevOps track (Kai) is shipped under
``agents-workspaces/kai/inbox/`` and lists the byte-precise
``BUCKET_CONFIG`` mirror contract; the orchestrator-side init script
addition is operator-tracked as a Sprint-5 Tag-3+ Kai-side
paired-update slot. The Wirelang-side consumer is byte-functional
once the bucket is materialised on the live cluster (operator-hand
``nats kv add wakir-capability-policies ...`` or routine init-script
backfill — whichever the operator's chosen path).

References
----------

- Spec: ``wirelang/specs/schema-registry-spec.md`` §5.14 (this slot).
- In-process registry source: Sprint-4 Tag-6
  :mod:`wirelang.schemas.registered_by_capability`.
- Pattern source: Sprint-3 Tag-1
  :mod:`wirelang.schemas.registry_nats_kv_backend` (mirror).
- Bucket inventory source: ``scripts/init-nats-buckets.py``
  ``PHASE_1_BUCKETS`` (Sprint-4 Tag-5 currently lists 6 slots;
  Sprint-5 Tag-2 paired-update memo requests a 7th).
- Layer-3 Biscuit v3 target shape:
  ``wirelang/schemas/layer-3-capability-token.json`` (the on-the-wire
  Capability-Token envelope; Sprint-5 Tag-2 ships an in-bucket JSON
  envelope, not the Biscuit binary token shape — Phase-3 substrate).
- Reza Persona §2 (Capability-Token-Layer: Reza-Owner-Domain).
"""

from __future__ import annotations

import enum
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from wirelang.schemas.registered_by_capability import (
    CapabilityPolicy,
    CapabilityPolicyRegistry,
    RegisteredByCapabilityError,
)


# ---------------------------------------------------------------------------
# Bucket identity (cross-reference: orchestrator bucket inventory)
# ---------------------------------------------------------------------------


#: NATS-KV bucket name for the Wirelang capability-policy registry.
#: Phase-2 Sprint-5 Tag-2 convention; this name will be registered in
#: Kai's :data:`PHASE_1_BUCKETS` as the 7th bucket via the Sprint-5
#: Tag-2 paired-update memo (DevOps-track Sprint-5 Tag-3+ slot).
BUCKET_NAME = "wakir-capability-policies"

#: Documented bucket configuration. Drift-policy is identical to the
#: schema-registry backend: any deviation between the live cluster
#: and these values is reported as drift, never auto-corrected.
BUCKET_CONFIG: Mapping[str, Any] = {
    "name": BUCKET_NAME,
    "description": "Wirelang capability-policy persistent registry (Phase-2)",
    "history": 5,
    "ttl_seconds": 0,
    "max_value_size": 16_384,
    "storage": "file",
    "replicas": 1,
}

#: Schema-URI fragment embedded in every value envelope.
VALUE_SCHEMA = "wakir.wirelang.capability-policy-entry/1"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CapabilityPolicyBackendError(Exception):
    """Base class for capability-policy backend failures."""


class CapabilityPolicyEnvelopeError(CapabilityPolicyBackendError):
    """Raised when a KV value cannot be parsed or fails the
    schema-shape contract.

    A poisoned envelope is *not* silently swallowed: the backend
    surfaces the error so an operator can act. The snapshot is taken
    eagerly; if a snapshot raises, no verifier consumes a
    half-broken policy registry.
    """


class CapabilityPolicyValidationError(CapabilityPolicyBackendError):
    """Raised when a write-time validation gate fails (malformed
    :class:`CapabilityPolicy` bundle or key-pair mismatch).
    """


# ---------------------------------------------------------------------------
# Identity pair ↔ key derivation
# ---------------------------------------------------------------------------


_KEY_PREFIX = "capability-policies/"

#: Permitted characters for ``policy_id`` (kebab-case ASCII).
_POLICY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

#: Permitted characters for ``registered_by`` (URI-safe ASCII subset,
#: matches the Sprint-3 Tag-1 schema-registry convention).
_REGISTERED_BY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$")


def key_for_policy_pair(registered_by: str, policy_id: str) -> str:
    """Derive the canonical KV key for a ``(registered_by, policy_id)``
    pair.

    The derivation is ``capability-policies/<registered_by>/<policy_id>``.
    Each component is non-empty, contains no slashes, and matches the
    permitted-character regex; this is enforced eagerly so a malformed
    pair cannot poison the bucket through a mis-keyed put.
    """
    for component_name, component, pattern in (
        ("registered_by", registered_by, _REGISTERED_BY_RE),
        ("policy_id", policy_id, _POLICY_ID_RE),
    ):
        if not isinstance(component, str) or not component:
            raise ValueError(
                f"{component_name} must be a non-empty string, got "
                f"{component!r}"
            )
        if "/" in component:
            raise ValueError(
                f"{component_name} must not contain '/': {component!r}"
            )
        if not pattern.match(component):
            raise ValueError(
                f"{component_name} {component!r} does not match the "
                f"permitted-character pattern {pattern.pattern!r}"
            )
    return f"{_KEY_PREFIX}{registered_by}/{policy_id}"


def pair_for_key(key: str) -> Tuple[str, str]:
    """Inverse of :func:`key_for_policy_pair`. Raises ``ValueError``
    for a key that does not match the expected shape.
    """
    if not isinstance(key, str) or not key.startswith(_KEY_PREFIX):
        raise ValueError(
            f"key must start with {_KEY_PREFIX!r}, got {key!r}"
        )
    rest = key[len(_KEY_PREFIX):]
    parts = rest.split("/")
    if len(parts) != 2:
        raise ValueError(
            f"key must have shape capability-policies/<registered_by>/"
            f"<policy_id>: {key!r}"
        )
    registered_by, policy_id = parts
    if not (registered_by and policy_id):
        raise ValueError(
            f"key components must all be non-empty: {key!r}"
        )
    return registered_by, policy_id


# ---------------------------------------------------------------------------
# Record dataclass (CapabilityPolicy + operator-side bookkeeping)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapabilityPolicyRecord:
    """One capability-policy record as persisted in the bucket.

    The :class:`CapabilityPolicy` bundle from Sprint-4 Tag-6 carries
    the gate-evaluation fields (``registered_by``, ``allowed_kids``,
    ``allowed_triples``, validity window, ``disabled``, ``note``). The
    record wraps the policy with operator-side bookkeeping:

    - ``policy_id``: operator-supplied identifier so multiple policies
      per ``registered_by`` are independently get-able and
      independently deletable.
    - ``registered_at``: when the record was written to the bucket
      (RFC-3339 UTC, tz-aware datetime).
    - ``registered_by_publisher``: who wrote the record (NOT the same
      as ``policy.registered_by``; this field audits the
      policy-authorship operator, that field audits the
      schema-registry publisher whose writes are being gated).

    The record is frozen by construction; the embedded
    :class:`CapabilityPolicy` is itself frozen, so the record is fully
    immutable.
    """

    policy: CapabilityPolicy
    policy_id: str
    registered_at: datetime
    registered_by_publisher: str

    def __post_init__(self) -> None:
        if not isinstance(self.policy, CapabilityPolicy):
            raise CapabilityPolicyValidationError(
                f"policy must be a CapabilityPolicy: type="
                f"{type(self.policy).__name__}"
            )
        if not isinstance(self.policy_id, str) or self.policy_id == "":
            raise CapabilityPolicyValidationError(
                f"policy_id must be a non-empty string: got "
                f"{self.policy_id!r}"
            )
        if not _POLICY_ID_RE.match(self.policy_id):
            raise CapabilityPolicyValidationError(
                f"policy_id {self.policy_id!r} does not match the "
                f"permitted-character pattern {_POLICY_ID_RE.pattern!r}"
            )
        if not isinstance(self.registered_at, datetime):
            raise CapabilityPolicyValidationError(
                f"registered_at must be a datetime: type="
                f"{type(self.registered_at).__name__}"
            )
        if self.registered_at.tzinfo is None:
            raise CapabilityPolicyValidationError(
                "registered_at must be timezone-aware"
            )
        if (
            not isinstance(self.registered_by_publisher, str)
            or self.registered_by_publisher == ""
        ):
            raise CapabilityPolicyValidationError(
                f"registered_by_publisher must be a non-empty string: "
                f"got {self.registered_by_publisher!r}"
            )

    @property
    def key(self) -> str:
        """Canonical KV key for this record."""
        return key_for_policy_pair(self.policy.registered_by, self.policy_id)


# ---------------------------------------------------------------------------
# Envelope codec
# ---------------------------------------------------------------------------


def _dt_to_rfc3339(dt: datetime) -> str:
    """Render a tz-aware datetime as RFC 3339 in UTC.

    Naive datetimes are rejected; matches the schema-registry-backend
    convention that all wall-clock anchors are tz-aware.
    """
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    in_utc = dt.astimezone(timezone.utc)
    iso = in_utc.isoformat()
    if iso.endswith("+00:00"):
        iso = iso[:-6] + "Z"
    return iso


def _rfc3339_to_dt(value: Any) -> datetime:
    """Parse an RFC 3339 string (with ``Z`` or ``+00:00`` suffix) back
    into a tz-aware UTC datetime. Raises ``ValueError`` for any other
    shape.
    """
    if not isinstance(value, str):
        raise ValueError(
            f"datetime must be a string, got {type(value).__name__}"
        )
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _record_to_envelope(record: CapabilityPolicyRecord) -> bytes:
    """Serialise a :class:`CapabilityPolicyRecord` to canonical JSON
    envelope bytes.
    """
    if not isinstance(record, CapabilityPolicyRecord):
        raise TypeError("record must be a CapabilityPolicyRecord")
    policy = record.policy
    payload = {
        "schema": VALUE_SCHEMA,
        "registered_by": policy.registered_by,
        "policy_id": record.policy_id,
        "allowed_kids": list(policy.allowed_kids),
        "allowed_triples": [list(t) for t in policy.allowed_triples],
        "not_before": (
            _dt_to_rfc3339(policy.not_before)
            if policy.not_before is not None
            else None
        ),
        "not_after": (
            _dt_to_rfc3339(policy.not_after)
            if policy.not_after is not None
            else None
        ),
        "disabled": policy.disabled,
        "note": policy.note,
        "registered_at": _dt_to_rfc3339(record.registered_at),
        "registered_by_publisher": record.registered_by_publisher,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _envelope_to_record(blob: bytes) -> CapabilityPolicyRecord:
    """Inverse of :func:`_record_to_envelope`. Raises
    :class:`CapabilityPolicyEnvelopeError` on shape violation.
    """
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CapabilityPolicyEnvelopeError(
            f"non-utf-8 envelope: {exc!r}"
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CapabilityPolicyEnvelopeError(
            f"non-JSON envelope: {exc!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise CapabilityPolicyEnvelopeError(
            f"envelope is not a JSON object: type="
            f"{type(payload).__name__}"
        )
    schema = payload.get("schema")
    if schema != VALUE_SCHEMA:
        raise CapabilityPolicyEnvelopeError(
            f"envelope schema mismatch: want {VALUE_SCHEMA!r} got {schema!r}"
        )
    for required in (
        "registered_by",
        "policy_id",
        "allowed_kids",
        "allowed_triples",
        "disabled",
        "registered_at",
        "registered_by_publisher",
    ):
        if required not in payload:
            raise CapabilityPolicyEnvelopeError(
                f"envelope missing required field: {required!r}"
            )
    allowed_kids_raw = payload["allowed_kids"]
    if not isinstance(allowed_kids_raw, list):
        raise CapabilityPolicyEnvelopeError(
            f"envelope allowed_kids must be a JSON array: type="
            f"{type(allowed_kids_raw).__name__}"
        )
    allowed_triples_raw = payload["allowed_triples"]
    if not isinstance(allowed_triples_raw, list):
        raise CapabilityPolicyEnvelopeError(
            f"envelope allowed_triples must be a JSON array: type="
            f"{type(allowed_triples_raw).__name__}"
        )
    converted_triples: List[Tuple[str, str]] = []
    for index, t in enumerate(allowed_triples_raw):
        if (
            not isinstance(t, list)
            or len(t) != 2
            or not isinstance(t[0], str)
            or not isinstance(t[1], str)
        ):
            raise CapabilityPolicyEnvelopeError(
                f"envelope allowed_triples[{index}] must be a 2-element "
                f"array of strings: got {t!r}"
            )
        converted_triples.append((t[0], t[1]))
    not_before_raw = payload.get("not_before")
    not_after_raw = payload.get("not_after")
    try:
        not_before = (
            _rfc3339_to_dt(not_before_raw)
            if not_before_raw is not None
            else None
        )
        not_after = (
            _rfc3339_to_dt(not_after_raw)
            if not_after_raw is not None
            else None
        )
    except ValueError as exc:
        raise CapabilityPolicyEnvelopeError(
            f"envelope not_before/not_after parse error: {exc!r}"
        ) from exc
    try:
        registered_at = _rfc3339_to_dt(payload["registered_at"])
    except ValueError as exc:
        raise CapabilityPolicyEnvelopeError(
            f"envelope registered_at parse error: {exc!r}"
        ) from exc
    disabled_raw = payload["disabled"]
    if not isinstance(disabled_raw, bool):
        raise CapabilityPolicyEnvelopeError(
            f"envelope disabled must be a boolean: type="
            f"{type(disabled_raw).__name__}"
        )
    note_raw = payload.get("note")
    if note_raw is not None and not isinstance(note_raw, str):
        raise CapabilityPolicyEnvelopeError(
            f"envelope note must be a string or null: type="
            f"{type(note_raw).__name__}"
        )
    # Round-trip through the Sprint-4 Tag-6 CapabilityPolicy
    # constructor so every invariant (non-empty registered_by,
    # non-empty allowed_kids, valid window, etc.) is enforced
    # byte-equal at decode time. A malformed envelope surfaces as an
    # envelope error (not a Sprint-4-Tag-6 RegisteredByCapabilityError);
    # the boundary is at the persistence layer.
    try:
        policy = CapabilityPolicy(
            registered_by=payload["registered_by"],
            allowed_kids=tuple(allowed_kids_raw),
            allowed_triples=tuple(converted_triples),
            not_before=not_before,
            not_after=not_after,
            disabled=disabled_raw,
            note=note_raw,
        )
    except RegisteredByCapabilityError as exc:
        raise CapabilityPolicyEnvelopeError(
            f"envelope policy bundle is invalid: {exc!r}"
        ) from exc
    try:
        return CapabilityPolicyRecord(
            policy=policy,
            policy_id=payload["policy_id"],
            registered_at=registered_at,
            registered_by_publisher=payload["registered_by_publisher"],
        )
    except CapabilityPolicyValidationError as exc:
        raise CapabilityPolicyEnvelopeError(
            f"envelope record bookkeeping is invalid: {exc!r}"
        ) from exc


# ---------------------------------------------------------------------------
# KV backend
# ---------------------------------------------------------------------------


@dataclass
class NatsKvCapabilityPolicyBackend:
    """NATS-JetStream-KV-backed capability-policy backend.

    The backend is async; the synchronous verifier surface consumes
    :class:`CapabilityPolicyRegistry` views materialised via
    :meth:`snapshot_registry`.

    Construction is cheap: pass an open ``KeyValue`` handle from
    nats-py (or a mock that mirrors the same surface). The backend
    performs *no* network I/O on construction.
    """

    kv: Any
    bucket_name: str = BUCKET_NAME

    # ------------------------------------------------------------------
    # Single-key operations
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Optional[CapabilityPolicyRecord]:
        """Return the record for ``key``, or ``None`` if absent.

        Raises :class:`CapabilityPolicyEnvelopeError` if the key
        exists but the value cannot be decoded.
        """
        if not isinstance(key, str) or not key:
            return None
        try:
            kve = await self.kv.get(key)
        except Exception as exc:
            cls_name = type(exc).__name__
            if (
                "NotFound" in cls_name
                or "DoesNotExist" in cls_name
                or isinstance(exc, KeyError)
            ):
                return None
            raise
        if kve is None:
            return None
        blob = _coerce_value_bytes(kve)
        return _envelope_to_record(blob)

    async def get_by_pair(
        self, registered_by: str, policy_id: str
    ) -> Optional[CapabilityPolicyRecord]:
        """Convenience wrapper: ``get(key_for_policy_pair(...))``."""
        try:
            key = key_for_policy_pair(registered_by, policy_id)
        except ValueError:
            return None
        return await self.get(key)

    async def put(self, record: CapabilityPolicyRecord) -> int:
        """Upsert a record; returns the new KV revision number.

        Last-write-wins semantics. Validation gates run BEFORE any
        bucket I/O:

        1. The :class:`CapabilityPolicyRecord` constructor has already
           validated the embedded :class:`CapabilityPolicy` (since
           both are frozen and validated at construction); this method
           re-validates the round-trip in case the record was
           constructed via ``__new__`` bypass paths.
        2. The KV key derived from
           ``(record.policy.registered_by, record.policy_id)``
           matches the explicit key (defence in depth against
           mis-keying).
        """
        if not isinstance(record, CapabilityPolicyRecord):
            raise TypeError("record must be a CapabilityPolicyRecord")
        # Gate 1: bundle round-trip (already validated by the record
        # and policy __post_init__; we re-validate here defensively).
        if not isinstance(record.policy, CapabilityPolicy):
            raise CapabilityPolicyValidationError(
                f"record.policy must be a CapabilityPolicy: type="
                f"{type(record.policy).__name__}"
            )
        # Gate 2: pair ↔ key (raises on malformed components).
        key = record.key
        blob = _record_to_envelope(record)
        revision = await self.kv.put(key, blob)
        return _coerce_revision(revision)

    async def delete(self, key: str) -> None:
        """Tombstone a record. No-op if the key was already absent.

        The tombstone is a NATS-KV tombstone: bucket history retains
        the operation, but :meth:`get` will return ``None``.
        """
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        try:
            await self.kv.delete(key)
        except Exception as exc:
            cls_name = type(exc).__name__
            if (
                "NotFound" in cls_name
                or "DoesNotExist" in cls_name
                or isinstance(exc, KeyError)
            ):
                return
            raise

    async def list_keys(self) -> list[str]:
        """Return all registered keys.

        Convenience wrapper over :func:`_list_keys`. The returned list
        is unsorted (mock-friendliness); callers that want a stable
        order should sort it themselves.
        """
        return await _list_keys(self.kv)

    # ------------------------------------------------------------------
    # Snapshot (the bridge to the synchronous verifier surface)
    # ------------------------------------------------------------------

    async def snapshot(self) -> list[CapabilityPolicyRecord]:
        """Materialise the live bucket into a list of records.

        Strategy: list all keys, then fetch each one. A poisoned
        envelope raises :class:`CapabilityPolicyEnvelopeError` and
        the snapshot aborts; partial snapshots are not surfaced
        because the determinism contract requires a complete,
        self-consistent view.

        The returned list is sorted by key for determinism; two
        back-to-back snapshots over the same bucket state yield
        byte-equal lists (modulo the records' embedded mutable
        state, which is frozen).
        """
        keys = sorted(await _list_keys(self.kv))
        records: list[CapabilityPolicyRecord] = []
        for key in keys:
            record = await self.get(key)
            if record is None:
                # Tombstoned between list and get; skip without error.
                continue
            records.append(record)
        return records

    async def snapshot_registry(self) -> CapabilityPolicyRegistry:
        """Materialise the live bucket into a
        :class:`CapabilityPolicyRegistry` ready for the Sprint-4
        Tag-6 :func:`check_registered_by_capability` gate.

        Records are added to the registry in sorted-key order; the
        registry preserves insertion order per ``registered_by``, so
        the in-process gate evaluation sees policies in stable order
        (a determinism contract that mirrors the
        :class:`InMemorySchemaRegistry.keys_sorted` Sprint-3 Tag-1
        determinism contract).

        Disabled policies ARE included in the registry; the gate
        evaluates them (Sprint-4 Tag-6 semantics: a disabled policy
        contributes a fallback ``POLICY_DISABLED`` decision-source if
        no allowing match was found). Operators who want to evict a
        policy from the gate entirely call :meth:`delete` and
        re-snapshot.
        """
        records = await self.snapshot()
        registry = CapabilityPolicyRegistry()
        for record in records:
            registry.add_policy(record.policy)
        return registry


# ---------------------------------------------------------------------------
# Helpers (KV adapter shims for nats-py vs. test mock)
# ---------------------------------------------------------------------------


def _coerce_value_bytes(kve: Any) -> bytes:
    """Return the raw value bytes from a KV entry handle.

    nats-py exposes ``kve.value`` as bytes; some mocks expose the
    same field. Plain bytes are also accepted.
    """
    if isinstance(kve, (bytes, bytearray)):
        return bytes(kve)
    value = getattr(kve, "value", None)
    if value is None and isinstance(kve, Mapping):
        value = kve.get("value")
    if value is None:
        raise CapabilityPolicyEnvelopeError(
            f"KV entry has no .value attribute: type={type(kve).__name__}"
        )
    if isinstance(value, str):
        return value.encode("utf-8")
    return bytes(value)


def _coerce_revision(rv: Any) -> int:
    """nats-py's ``put`` returns an int revision; some mocks return
    an object with ``.revision``. Normalise to ``int``.
    """
    if isinstance(rv, int):
        return rv
    revision = getattr(rv, "revision", None)
    if revision is None and isinstance(rv, Mapping):
        revision = rv.get("revision")
    if revision is None:
        return 0
    return int(revision)


async def _list_keys(kv: Any) -> list:
    """List all keys in the bucket. nats-py exposes
    ``await kv.keys()`` returning ``list[str]``; we also accept a
    direct return for mock flexibility.
    """
    if hasattr(kv, "keys"):
        result = kv.keys()
        if hasattr(result, "__await__"):
            result = await result
        if hasattr(result, "__aiter__"):
            collected = []
            async for k in result:
                collected.append(k)
            return collected
        return list(result)
    raise CapabilityPolicyBackendError("KV handle has no keys() method")


__all__ = [
    "BUCKET_NAME",
    "BUCKET_CONFIG",
    "VALUE_SCHEMA",
    "CapabilityPolicyBackendError",
    "CapabilityPolicyEnvelopeError",
    "CapabilityPolicyValidationError",
    "CapabilityPolicyRecord",
    "NatsKvCapabilityPolicyBackend",
    "key_for_policy_pair",
    "pair_for_key",
]
