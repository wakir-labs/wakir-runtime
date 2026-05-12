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
  startup (or on a periodic refresh schedule). The Sprint-5 Tag-2
  slot was full-snapshot only; the live tail
  (:meth:`NatsKvCapabilityPolicyBackend.watch` /
  :class:`LiveCapabilityPolicySnapshot`) is **added in Sprint-5 Tag-5**
  (pattern-mirror on the schema-registry watch-stream, Sprint-3 Tag-4)
  and stays a *consumer* surface: a long-running supervisor task feeds
  a :class:`LiveCapabilityPolicySnapshot` from :meth:`watch` and hands
  frozen :class:`CapabilityPolicyRegistry` copies to verifier modules
  via :meth:`LiveCapabilityPolicySnapshot.as_registry`. The full
  :meth:`snapshot` / :meth:`snapshot_registry` path remains supported
  and orthogonal; CAS-pin is unaffected.
- Sprint-5 Tag-2 ships PUT (LWW) only. The CAS-pinned upsert path
  ``put_with_revision`` is **added in Sprint-5 Tag-4** (pattern-mirror
  on the schema-registry CAS-pin, Sprint-3 Tag-3) — see
  :meth:`NatsKvCapabilityPolicyBackend.put_with_revision` and
  :class:`CapabilityPolicyConflictError` below. The Sprint-5 Tag-2
  ``put`` LWW path remains supported and orthogonal: CAS-pin is the
  opt-in lost-update-protection surface for operators who edit
  policies concurrently (e.g. rotating ``allowed_kids`` on a
  key-rollover), while LWW remains the default for create-once /
  rarely-touched policy authorship flows.
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


class CapabilityPolicyConflictError(CapabilityPolicyBackendError):
    """Raised when a CAS-pinned upsert is rejected because the live KV
    revision has drifted from the caller's expected revision.

    Phase-2 Sprint-5 Tag-4 CAS-pin contract (pattern-mirror on the
    Phase-1b Sprint-3 Tag-3 schema-registry CAS-pin path; see
    :class:`wirelang.schemas.registry_nats_kv_backend.SchemaRegistryConflictError`).

    The caller of
    :meth:`NatsKvCapabilityPolicyBackend.put_with_revision` declares
    the revision it observed when it last read the record. The backend
    forwards that revision to the underlying NATS-KV ``update`` call.
    If the live revision has advanced (a concurrent policy-authorship
    writer landed first), the underlying KV layer raises a
    nats-py-flavoured ``KeyWrongLastSequenceError`` (or any error
    whose class name contains ``WrongLastSequence``, ``Conflict``, or
    ``RevisionMismatch``); the backend translates that into this typed
    exception.

    Carries the observed ``key``, ``expected_revision``, and (when
    available) the ``actual_revision`` reported by the underlying
    layer. ``actual_revision`` is ``None`` if the KV adapter does not
    surface it; callers can re-read the record and retry.

    Lost-update protection on capability-policy authorship is the
    Sprint-5 Tag-4 substance: two operators editing the same
    ``(registered_by, policy_id)`` pair concurrently — for example to
    rotate ``allowed_kids`` after a key-rollover — would otherwise risk
    one overwriting the other's edit silently under the Sprint-5
    Tag-2 last-write-wins ``put`` contract. CAS-pin makes the conflict
    explicit so the second writer can re-read and re-apply.
    """

    def __init__(
        self,
        message: str,
        *,
        key: Optional[str] = None,
        expected_revision: Optional[int] = None,
        actual_revision: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.key = key
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision


class CapabilityPolicyRevocationConflict(CapabilityPolicyBackendError):
    """Raised when a write would un-revoke a policy that is already
    revoked, or would advance the ``revoked_at`` instant strictly
    later than the live one.

    Phase-2 Sprint-6 Tag-1: revocation is a one-way state transition.
    Once a policy carries a ``revoked_at`` instant, subsequent writes
    MUST either preserve that instant byte-equally (idempotent
    re-write, e.g. note refresh) or refuse. A later revocation
    instant is rejected because revocation is an authority gesture
    that cannot be retroactively softened. An ``un-revoke`` (revoked
    policy → unrevoked policy) is rejected because the revocation
    represents an authority statement of compromise; the operator
    MUST mint a new ``policy_id`` instead.

    This invariant is enforced on
    :meth:`NatsKvCapabilityPolicyBackend.put_with_revision` (the
    CAS-pinned write path); the unsafe LWW ``put`` path does NOT
    enforce it (consistent with the Sprint-5 Tag-4 rationale: LWW
    writes are operator-deliberate, CAS-pinned writes guard the
    safety invariants).

    Carries ``key`` and the conflicting ``existing_revoked_at`` /
    ``proposed_revoked_at`` instants for downstream audit.
    """

    def __init__(
        self,
        message: str,
        *,
        key: Optional[str] = None,
        existing_revoked_at: Optional[datetime] = None,
        proposed_revoked_at: Optional[datetime] = None,
    ) -> None:
        super().__init__(message)
        self.key = key
        self.existing_revoked_at = existing_revoked_at
        self.proposed_revoked_at = proposed_revoked_at


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
class UnrevokeAuditMarker:
    """Operator-deliberate-unrevoke audit marker carried on a
    :class:`CapabilityPolicyRecord` envelope.

    Phase-2 Sprint-6 Tag-9 (additive over Sprint-6 Tag-7). The
    publisher-CLI ``unrevoke`` subcommand (Sprint-6 Tag-7) writes a
    rewritten record with ``policy.revoked_at = None`` against a
    prior-revoked bucket entry. On the watch-stream that write is
    *structurally indistinguishable* on the policy axis from an
    out-of-band un-revoke (substrate corruption or manual override),
    which the Sprint-6 Tag-3 classifier surfaces as
    :attr:`RevocationEventKind.REVOCATION_MONOTONIC_BREACH`.

    To let audit consumers separate operator-deliberate unrevoke from
    accidental BREACH **on the watch-stream alone** (without
    cross-referencing the receipts persisted on a separate audit
    channel), the ``unrevoke`` subcommand attaches an
    :class:`UnrevokeAuditMarker` to the envelope. The marker carries:

    - ``unrevoke_reason``: the operator-supplied free-form audit
      string from ``--unrevoke-reason`` (or ``None`` if omitted).
      Mirrors the receipt's ``unrevoke_reason`` field. Persisted on
      the envelope so the audit-trail surfaces it to every watch
      consumer (not only to the operator who saw the receipt on
      stdout).
    - ``previous_revoked_at``: the prior live record's
      ``policy.revoked_at`` instant (always non-None — the unrevoke
      subcommand refuses unrevoked targets via
      :attr:`ExitCode.UNREVOKE_TARGET_NOT_REVOKED`). The classifier
      cross-checks this against its own per-key prior view: a marker
      whose ``previous_revoked_at`` matches the classifier's prior
      state validates the gesture; a mismatch is itself a witness of
      tampering and falls through to BREACH.
    - ``previous_revocation_reason``: the prior live record's
      ``policy.revocation_reason`` (or ``None`` if the prior
      revocation carried no reason). Audit-only; not cross-checked.

    Backward compatibility: every envelope written before Sprint-6
    Tag-9 omits the marker; the decoder treats absence as ``None``
    (no marker) so legacy envelopes round-trip byte-equally. A
    legacy operator-bypass un-revoke (or a substrate-corruption
    un-revoke) still surfaces as BREACH on the classifier.

    Forward compatibility: the marker is gate-orthogonal — the
    :class:`CapabilityPolicy` bundle is unchanged by its presence.
    Verifier-side gating (Sprint-4 Tag-6, Sprint-6 Tag-1 revocation
    precedence) reads only ``policy.*`` fields; the marker is
    audit-axis state living on the record-bookkeeping side of the
    envelope, not on the policy bundle.

    Frozen by construction; the embedded values are primitives /
    ``datetime`` so the marker is fully immutable and safe to put
    into sets / dict keys.
    """

    unrevoke_reason: Optional[str]
    previous_revoked_at: datetime
    previous_revocation_reason: Optional[str]

    def __post_init__(self) -> None:
        if self.unrevoke_reason is not None and not isinstance(
            self.unrevoke_reason, str
        ):
            raise CapabilityPolicyValidationError(
                f"unrevoke_reason must be a string or None: type="
                f"{type(self.unrevoke_reason).__name__}"
            )
        if not isinstance(self.previous_revoked_at, datetime):
            raise CapabilityPolicyValidationError(
                f"previous_revoked_at must be a datetime: type="
                f"{type(self.previous_revoked_at).__name__}"
            )
        if self.previous_revoked_at.tzinfo is None:
            raise CapabilityPolicyValidationError(
                "previous_revoked_at must be timezone-aware"
            )
        if self.previous_revocation_reason is not None and not isinstance(
            self.previous_revocation_reason, str
        ):
            raise CapabilityPolicyValidationError(
                f"previous_revocation_reason must be a string or None: "
                f"type={type(self.previous_revocation_reason).__name__}"
            )


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
    - ``unrevoke_audit_marker``: Phase-2 Sprint-6 Tag-9 additive
      operator-deliberate-unrevoke marker. Default ``None`` for every
      legacy write path (publish, revoke, replication). The
      publisher-CLI ``unrevoke`` subcommand sets a non-None
      :class:`UnrevokeAuditMarker` so the watch-side classifier can
      distinguish the deliberate gesture from an accidental
      out-of-band un-revoke (substrate corruption / manual override),
      which still surfaces as
      :attr:`RevocationEventKind.REVOCATION_MONOTONIC_BREACH`.

    The record is frozen by construction; the embedded
    :class:`CapabilityPolicy` is itself frozen, so the record is fully
    immutable.
    """

    policy: CapabilityPolicy
    policy_id: str
    registered_at: datetime
    registered_by_publisher: str
    # Phase-2 Sprint-6 Tag-9: additive operator-deliberate-unrevoke
    # marker. Default ``None`` for every non-unrevoke write path so
    # the field is byte-equally invisible to existing callers.
    unrevoke_audit_marker: Optional[UnrevokeAuditMarker] = None

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
        # Phase-2 Sprint-6 Tag-9 invariant: the marker, if present,
        # MUST refer to an unrevoked rewritten record. A marker on a
        # record whose policy is still revoked is a contradiction
        # (the marker witnesses the *transition to unrevoked*; if the
        # policy is still revoked, the gesture has not been applied).
        # The constructor rejects the contradiction so the bucket can
        # never persist a self-inconsistent envelope.
        if self.unrevoke_audit_marker is not None:
            if not isinstance(
                self.unrevoke_audit_marker, UnrevokeAuditMarker
            ):
                raise CapabilityPolicyValidationError(
                    f"unrevoke_audit_marker must be an "
                    f"UnrevokeAuditMarker or None: type="
                    f"{type(self.unrevoke_audit_marker).__name__}"
                )
            if self.policy.revoked_at is not None:
                raise CapabilityPolicyValidationError(
                    "unrevoke_audit_marker requires policy.revoked_at "
                    "to be None (the marker witnesses the operator-"
                    "deliberate transition to unrevoked; carrying it "
                    "on a still-revoked policy is contradictory)"
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
        # Phase-2 Sprint-6 Tag-1: additive revocation surface.
        # Both fields default to ``None`` (no revocation); a Sprint-5
        # Tag-2..5 envelope without these keys decodes byte-equally
        # via :func:`_envelope_to_record` to an unrevoked policy.
        "revoked_at": (
            _dt_to_rfc3339(policy.revoked_at)
            if policy.revoked_at is not None
            else None
        ),
        "revocation_reason": policy.revocation_reason,
        "registered_at": _dt_to_rfc3339(record.registered_at),
        "registered_by_publisher": record.registered_by_publisher,
    }
    # Phase-2 Sprint-6 Tag-9: additive unrevoke-audit-marker. The key
    # is only emitted when a marker is present so legacy / non-unrevoke
    # write paths produce envelopes that are byte-equal to the
    # Sprint-6 Tag-1..8 shape (back-compat invariant). The decoder's
    # ``payload.get("unrevoke_audit_marker")`` mirrors the asymmetry.
    if record.unrevoke_audit_marker is not None:
        marker = record.unrevoke_audit_marker
        payload["unrevoke_audit_marker"] = {
            "unrevoke_reason": marker.unrevoke_reason,
            "previous_revoked_at": _dt_to_rfc3339(
                marker.previous_revoked_at
            ),
            "previous_revocation_reason": (
                marker.previous_revocation_reason
            ),
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
    # Phase-2 Sprint-6 Tag-1: optional revocation fields (additive).
    # Older Sprint-5 Tag-2..5 envelopes omit these keys; the decoder
    # treats absence as ``None`` (unrevoked) so back-compat is
    # byte-precise. New envelopes carry RFC-3339 ``revoked_at`` and
    # a free-form ``revocation_reason`` string (or both ``null``).
    revoked_at_raw = payload.get("revoked_at")
    try:
        revoked_at = (
            _rfc3339_to_dt(revoked_at_raw)
            if revoked_at_raw is not None
            else None
        )
    except ValueError as exc:
        raise CapabilityPolicyEnvelopeError(
            f"envelope revoked_at parse error: {exc!r}"
        ) from exc
    revocation_reason_raw = payload.get("revocation_reason")
    if revocation_reason_raw is not None and not isinstance(
        revocation_reason_raw, str
    ):
        raise CapabilityPolicyEnvelopeError(
            f"envelope revocation_reason must be a string or null: type="
            f"{type(revocation_reason_raw).__name__}"
        )
    # Phase-2 Sprint-6 Tag-9: optional unrevoke-audit-marker (additive,
    # back-compat). Absence => marker is None; presence => fully-formed
    # sub-object with three keys. The decoder rejects partial / wrong-
    # shape sub-objects so a poisoned marker surfaces as an envelope
    # error (not silently as a missing marker).
    marker_raw = payload.get("unrevoke_audit_marker")
    unrevoke_audit_marker: Optional[UnrevokeAuditMarker] = None
    if marker_raw is not None:
        if not isinstance(marker_raw, dict):
            raise CapabilityPolicyEnvelopeError(
                f"envelope unrevoke_audit_marker must be a JSON object "
                f"or null: type={type(marker_raw).__name__}"
            )
        for required in (
            "unrevoke_reason",
            "previous_revoked_at",
            "previous_revocation_reason",
        ):
            if required not in marker_raw:
                raise CapabilityPolicyEnvelopeError(
                    f"envelope unrevoke_audit_marker missing required "
                    f"field: {required!r}"
                )
        marker_reason_raw = marker_raw["unrevoke_reason"]
        if marker_reason_raw is not None and not isinstance(
            marker_reason_raw, str
        ):
            raise CapabilityPolicyEnvelopeError(
                f"envelope unrevoke_audit_marker.unrevoke_reason must "
                f"be a string or null: type="
                f"{type(marker_reason_raw).__name__}"
            )
        marker_prev_revoked_raw = marker_raw["previous_revoked_at"]
        if marker_prev_revoked_raw is None:
            raise CapabilityPolicyEnvelopeError(
                "envelope unrevoke_audit_marker.previous_revoked_at "
                "must be a non-null RFC-3339 string (the marker "
                "witnesses an operator-deliberate transition AWAY "
                "from a non-None revoked_at)"
            )
        try:
            marker_prev_revoked = _rfc3339_to_dt(marker_prev_revoked_raw)
        except ValueError as exc:
            raise CapabilityPolicyEnvelopeError(
                f"envelope unrevoke_audit_marker.previous_revoked_at "
                f"parse error: {exc!r}"
            ) from exc
        marker_prev_reason_raw = marker_raw["previous_revocation_reason"]
        if marker_prev_reason_raw is not None and not isinstance(
            marker_prev_reason_raw, str
        ):
            raise CapabilityPolicyEnvelopeError(
                f"envelope unrevoke_audit_marker."
                f"previous_revocation_reason must be a string or null: "
                f"type={type(marker_prev_reason_raw).__name__}"
            )
        try:
            unrevoke_audit_marker = UnrevokeAuditMarker(
                unrevoke_reason=marker_reason_raw,
                previous_revoked_at=marker_prev_revoked,
                previous_revocation_reason=marker_prev_reason_raw,
            )
        except CapabilityPolicyValidationError as exc:
            raise CapabilityPolicyEnvelopeError(
                f"envelope unrevoke_audit_marker is invalid: {exc!r}"
            ) from exc
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
            revoked_at=revoked_at,
            revocation_reason=revocation_reason_raw,
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
            unrevoke_audit_marker=unrevoke_audit_marker,
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

    async def get_with_revision(
        self, key: str
    ) -> Optional[Tuple[CapabilityPolicyRecord, int]]:
        """Return ``(record, revision)`` for ``key`` or ``None``.

        Phase-2 Sprint-5 Tag-4 CAS-pin helper. The revision is the
        same integer that :meth:`put_with_revision` expects as
        ``expected_revision``.

        The implementation reuses the same KV adapter path as
        :meth:`get`; the revision is read from the KV entry handle's
        ``.revision`` attribute (nats-py shape) or from a ``revision``
        key on a Mapping-shaped entry.

        Raises :class:`CapabilityPolicyEnvelopeError` if the value is
        unparseable, identical to :meth:`get`.

        Mirror of
        :meth:`wirelang.schemas.registry_nats_kv_backend.NatsKvSchemaRegistry.get_with_revision`.
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
        record = _envelope_to_record(blob)
        revision = _coerce_revision_from_entry(kve)
        return record, revision

    async def get_with_revision_by_pair(
        self, registered_by: str, policy_id: str
    ) -> Optional[Tuple[CapabilityPolicyRecord, int]]:
        """Convenience wrapper:
        ``get_with_revision(key_for_policy_pair(...))``.
        """
        try:
            key = key_for_policy_pair(registered_by, policy_id)
        except ValueError:
            return None
        return await self.get_with_revision(key)

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

    async def put_with_revision(
        self, record: CapabilityPolicyRecord, expected_revision: int
    ) -> int:
        """CAS-pinned upsert. Returns the new KV revision number.

        Phase-2 Sprint-5 Tag-4 CAS-pin (pattern-mirror on the
        Phase-1b Sprint-3 Tag-3 schema-registry CAS-pin path).

        Lost-update protection contract:

        - The caller observed ``expected_revision`` when it last read
          the record (via :meth:`get_with_revision`).
        - This method forwards ``expected_revision`` to the underlying
          NATS-KV ``update(key, value, last=expected_revision)`` call.
        - If the live revision has advanced since the caller's read
          (a concurrent writer landed first), the underlying layer
          raises a ``KeyWrongLastSequenceError`` (nats-py shape) or
          analogous ``ConflictError``. The backend translates that
          into :class:`CapabilityPolicyConflictError`.

        For a record that does not yet exist in the bucket, callers
        MUST use :meth:`put` (which has last-write-wins semantics).
        ``put_with_revision`` with ``expected_revision == 0`` is
        reserved for the create-if-absent case but only succeeds if
        the underlying KV adapter supports the
        ``KeyValue.create(key, value)`` contract; if the adapter does
        not surface that semantic, the call raises
        :class:`CapabilityPolicyConflictError`.

        Validation gates (identical to :meth:`put`):

        1. ``record`` is a :class:`CapabilityPolicyRecord` (and the
           embedded :class:`CapabilityPolicy` round-trip is enforced by
           the dataclass ``__post_init__``).
        2. Pair ↔ key derivation succeeds (the
           ``(record.policy.registered_by, record.policy_id)`` pair
           matches the canonical key derivation).

        These run BEFORE the revision-pin call so that a malformed
        envelope cannot leave the validation surface even if the
        revision happened to be stale. This mirrors the schema-registry
        CAS-pin "validation gates run BEFORE CAS" determinism contract
        (Sprint-3 Tag-3 spec §5.4).
        """
        if not isinstance(record, CapabilityPolicyRecord):
            raise TypeError("record must be a CapabilityPolicyRecord")
        if not isinstance(expected_revision, int) or expected_revision < 0:
            raise ValueError(
                "expected_revision must be a non-negative int, "
                f"got {expected_revision!r}"
            )
        # Gate 1: bundle round-trip (already validated by the record
        # and policy __post_init__; we re-validate here defensively).
        if not isinstance(record.policy, CapabilityPolicy):
            raise CapabilityPolicyValidationError(
                f"record.policy must be a CapabilityPolicy: type="
                f"{type(record.policy).__name__}"
            )
        # Gate 2: pair ↔ key (raises on malformed components).
        key = record.key
        # Gate 3 (Phase-2 Sprint-6 Tag-1): revocation-monotonic.
        # If the live record at this key carries a revocation, the
        # incoming record MUST either preserve the same ``revoked_at``
        # instant or refuse. An incoming ``revoked_at=None`` against a
        # live revoked policy is an un-revoke attempt and is rejected
        # (the operator MUST mint a new policy_id instead). An
        # incoming ``revoked_at`` strictly greater than the live one
        # is rejected because revocation cannot be retroactively
        # softened; equal-instant rewrites are permitted (so a
        # ``revocation_reason`` note refresh remains legal).
        try:
            existing = await self.get(key)
        except CapabilityPolicyEnvelopeError:
            # A poisoned live envelope is surfaced by ``get``; the
            # CAS-pin path forwards that failure up. Reza-Hand: a
            # poisoned-on-disk policy must not be silently overwritten
            # by CAS-pin either.
            raise
        if existing is not None and existing.policy.revoked_at is not None:
            live_revoked_at = existing.policy.revoked_at
            new_revoked_at = record.policy.revoked_at
            if new_revoked_at is None:
                raise CapabilityPolicyRevocationConflict(
                    "cannot un-revoke a revoked policy via CAS-pin: "
                    f"key={key!r} live_revoked_at={live_revoked_at!r} "
                    "(mint a new policy_id instead)",
                    key=key,
                    existing_revoked_at=live_revoked_at,
                    proposed_revoked_at=None,
                )
            if new_revoked_at != live_revoked_at:
                raise CapabilityPolicyRevocationConflict(
                    "cannot change the revocation instant of an already-"
                    f"revoked policy: key={key!r} "
                    f"live_revoked_at={live_revoked_at!r} "
                    f"proposed_revoked_at={new_revoked_at!r} "
                    "(equal-instant idempotent rewrites are permitted)",
                    key=key,
                    existing_revoked_at=live_revoked_at,
                    proposed_revoked_at=new_revoked_at,
                )
        blob = _record_to_envelope(record)
        revision = await _kv_update_with_revision(
            self.kv, key, blob, expected_revision
        )
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

    # ------------------------------------------------------------------
    # Watch-stream (Phase-2 Sprint-5 Tag-5, additive over Sprint-5 Tag-4)
    # ------------------------------------------------------------------

    async def watch(self) -> "_CapabilityPolicyWatchStreamHandle":
        """Open a watch-stream over the capability-policy bucket.

        Returns an async iterable / context manager that yields decoded
        :class:`CapabilityPolicyWatchEvent` instances. See
        :func:`open_capability_policy_watch_stream` for details.

        Phase-2 Sprint-5 Tag-5 boundary: the watch-stream is a *consumer*
        surface; it does NOT replace :meth:`snapshot_registry`. Use a
        :class:`LiveCapabilityPolicySnapshot` (bootstrapped from
        :meth:`snapshot_registry`, fed by :meth:`watch`) to maintain a
        long-running incremental view; pass frozen
        :meth:`LiveCapabilityPolicySnapshot.as_registry` copies to the
        Sprint-4 Tag-6 :func:`check_registered_by_capability` gate when
        it needs a stable point-in-time view.

        Pattern-mirror on Sprint-3 Tag-4 schema-registry watch-stream
        (:meth:`NatsKvSchemaRegistry.watch`).
        """
        return await open_capability_policy_watch_stream(self)


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


def _coerce_revision_from_entry(kve: Any) -> int:
    """Read the revision integer from a KV entry handle.

    nats-py exposes ``kve.revision``; some mocks expose the same field
    on a Mapping-shaped entry. A missing revision is returned as ``0``
    (sentinel for "create-if-absent" CAS contract) but the caller
    should normally observe a positive revision because it just read
    the entry from the bucket.

    Phase-2 Sprint-5 Tag-4 CAS-pin helper (pattern-mirror on the
    schema-registry CAS-pin helper of the same name).
    """
    if isinstance(kve, (bytes, bytearray)):
        return 0
    revision = getattr(kve, "revision", None)
    if revision is None and isinstance(kve, Mapping):
        revision = kve.get("revision")
    if revision is None:
        return 0
    return int(revision)


_CONFLICT_CLS_MARKERS = (
    "WrongLastSequence",
    "Conflict",
    "RevisionMismatch",
)


async def _kv_update_with_revision(
    kv: Any,
    key: str,
    value: bytes,
    expected_revision: int,
) -> Any:
    """CAS-pinned KV write.

    nats-py exposes ``KeyValue.update(key, value, last=revision)``
    which raises ``KeyWrongLastSequenceError`` if the live revision
    differs. We accept three KV adapter shapes here:

    1. ``kv.update(key, value, last=revision)`` — the canonical
       nats-py shape.
    2. ``kv.update(key, value, expected_revision)`` — positional
       fallback for mocks.
    3. ``kv.put(key, value, expected_revision=...)`` — keyword
       fallback for mocks that overload ``put``.

    On conflict (any exception whose class name carries one of the
    markers in :data:`_CONFLICT_CLS_MARKERS`), the function raises
    :class:`CapabilityPolicyConflictError` with the observed metadata.

    Phase-2 Sprint-5 Tag-4 CAS-pin helper (pattern-mirror on the
    schema-registry CAS-pin helper of the same name; the schema-
    registry helper raises
    :class:`SchemaRegistryConflictError`, this one raises
    :class:`CapabilityPolicyConflictError`).
    """
    update = getattr(kv, "update", None)
    if update is not None:
        try:
            try:
                return await update(key, value, last=expected_revision)
            except TypeError:
                # Mock that doesn't accept the ``last`` keyword.
                return await update(key, value, expected_revision)
        except Exception as exc:
            if _is_conflict_exception(exc):
                actual = _extract_actual_revision(exc)
                raise CapabilityPolicyConflictError(
                    f"CAS-pin rejected for key {key!r}: "
                    f"expected_revision={expected_revision}, "
                    f"actual_revision={actual}",
                    key=key,
                    expected_revision=expected_revision,
                    actual_revision=actual,
                ) from exc
            raise
    # Fallback: try put with kwarg.
    try:
        return await kv.put(key, value, expected_revision=expected_revision)
    except TypeError as exc:
        raise CapabilityPolicyBackendError(
            "KV adapter has neither .update(last=...) nor "
            ".put(expected_revision=...); CAS-pin not supported"
        ) from exc
    except Exception as exc:
        if _is_conflict_exception(exc):
            actual = _extract_actual_revision(exc)
            raise CapabilityPolicyConflictError(
                f"CAS-pin rejected for key {key!r}: "
                f"expected_revision={expected_revision}, "
                f"actual_revision={actual}",
                key=key,
                expected_revision=expected_revision,
                actual_revision=actual,
            ) from exc
        raise


def _is_conflict_exception(exc: BaseException) -> bool:
    """True if ``exc``'s class name matches a CAS-conflict marker.

    Phase-2 Sprint-5 Tag-4 CAS-pin helper (pattern-mirror on the
    schema-registry CAS-pin helper of the same name; both detect
    nats-py-style conflict exception class names by class-name marker
    rather than by isinstance check, so the backend stays
    nats-py-version-agnostic).
    """
    cls_name = type(exc).__name__
    return any(marker in cls_name for marker in _CONFLICT_CLS_MARKERS)


def _extract_actual_revision(exc: BaseException) -> Optional[int]:
    """Pull an actual-revision integer off a conflict exception, if
    the underlying KV adapter surfaces one. Best-effort, returns
    ``None`` when not available.

    Phase-2 Sprint-5 Tag-4 CAS-pin helper (pattern-mirror on the
    schema-registry CAS-pin helper of the same name).
    """
    for attr in ("actual_revision", "actual", "revision", "last"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


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


# ---------------------------------------------------------------------------
# Watch-Stream-Snapshot Layer (Phase-2 Sprint-5 Tag-5, additive over Tag-4)
# ---------------------------------------------------------------------------
#
# Tag-2 (S5-2) shipped get/put/delete/snapshot/snapshot_registry. The
# snapshot path is full-bucket: every verifier pass that wants fresh
# state takes a fresh full snapshot. That is correct for determinism
# but costly when policy turnover is high (e.g. operator-side rotation
# campaigns rolling kids across many policies) or when a long-running
# supervisor wants to track changes between snapshots without
# re-listing.
#
# Tag-5 (S5-5) adds a watch-based incremental layer that consumes
# nats-py's ``KeyValue.watchall()`` (or a mock-equivalent) and surfaces
# decoded :class:`CapabilityPolicyWatchEvent` instances. The
# synchronous verifier surface
# (:func:`check_registered_by_capability`) is UNCHANGED: the
# watch-stream is a substrate for materialising live deltas into a
# :class:`CapabilityPolicyRegistry` snapshot, not a new verifier
# substrate. The bridge contract is: each verifier pass takes one
# *frozen* :class:`CapabilityPolicyRegistry` view; the watch-stream is
# the producer of that view, the verifier does not query the live
# stream.
#
# A :class:`LiveCapabilityPolicySnapshot` keeps an in-memory copy of
# the registry (indexed by KV-key so deltas can update / remove a
# specific ``(registered_by, policy_id)`` entry), initialises it from
# a full :meth:`NatsKvCapabilityPolicyBackend.snapshot`, and then
# applies decoded :class:`CapabilityPolicyWatchEvent` instances as
# they arrive. Callers get a deterministic frozen
# :class:`CapabilityPolicyRegistry` for each verifier pass via
# :meth:`LiveCapabilityPolicySnapshot.as_registry`. The frozen copy
# is taken at call time; subsequent watch events do NOT mutate the
# returned registry (T-CPP-WS-determinism contract).
#
# Boundary (Phase-2 Sprint-5 Tag-5):
#
# - The watch-stream is a *consumer* surface. Operators connect the
#   stream to a long-running supervisor task; the supervisor keeps a
#   :class:`LiveCapabilityPolicySnapshot` warm and hands frozen
#   :class:`CapabilityPolicyRegistry` instances to the
#   :func:`check_registered_by_capability` gate per pass. The
#   watch-stream itself is not the registry.
# - A poisoned envelope on the stream raises
#   :class:`CapabilityPolicyEnvelopeError` from the consumer iterator
#   and terminates the iterator. The operator must observe the error,
#   drop the :class:`LiveCapabilityPolicySnapshot`, and re-bootstrap
#   from a fresh :meth:`NatsKvCapabilityPolicyBackend.snapshot`.
#   Phase-2 Sprint-5 Tag-5 does not silently swallow envelope poison
#   (same contract as the full snapshot path).
# - Watch-stream resumption / replay-from-revision is a Phase-3
#   concern (nats-py supports it via ``watchall(..., resume_from=...)``;
#   the Sprint-5 Tag-5 stream wrapper exposes the underlying revision
#   but does not bake in resume policy).
# - The watch-stream is orthogonal to the Tag-4 CAS-pin surface. A
#   CAS-pin PUT (lossless update) yields one PUT event on the stream
#   identical to a LWW PUT; an LWW write yields one PUT event; a
#   stale CAS-pin write rejected by the bucket yields NO event (the
#   write was not durable). Determinism contract: the stream is a
#   strict suffix of the durable bucket history.


class CapabilityPolicyWatchOp(enum.Enum):
    """Operation kind surfaced by the capability-policy watch-stream.

    Matches nats-py's ``KeyValueOp`` shape: ``PUT`` for insert/update,
    ``DELETE`` for tombstone (explicit delete), ``PURGE`` for
    history-clearing purge. Verifier-side consumers treat ``DELETE``
    and ``PURGE`` identically (the policy is gone); they are surfaced
    separately so audit consumers can distinguish them.

    Byte-equal mirror of
    :class:`wirelang.schemas.registry_nats_kv_backend.WatchOp`
    (Sprint-3 Tag-4). The class identity is module-local to keep the
    two backends evolving independently.
    """

    PUT = "PUT"
    DELETE = "DELETE"
    PURGE = "PURGE"


@dataclass(frozen=True)
class CapabilityPolicyWatchEvent:
    """A single decoded operation from the capability-policy watch-stream.

    Fields:

    - ``op``: the :class:`CapabilityPolicyWatchOp`. PUT means
      ``record`` is set; DELETE/PURGE mean ``record`` is ``None``.
    - ``key``: the registry KV key string
      (``capability-policies/<registered_by>/<policy_id>``).
    - ``record``: the decoded :class:`CapabilityPolicyRecord` for PUT;
      ``None`` for DELETE/PURGE.
    - ``revision``: the KV revision at which this event was observed.
      Monotonically increasing per bucket; useful for resume policies
      and audit cross-references.

    Pattern-mirror on
    :class:`wirelang.schemas.registry_nats_kv_backend.WatchEvent`
    with ``entry`` renamed to ``record`` to match this module's
    canonical noun for the persisted unit.
    """

    op: CapabilityPolicyWatchOp
    key: str
    record: Optional[CapabilityPolicyRecord]
    revision: int


def _decode_capability_policy_watch_update(
    update: Any,
) -> CapabilityPolicyWatchEvent:
    """Decode one nats-py ``KeyValue.Entry`` (or mock-equivalent) into
    a :class:`CapabilityPolicyWatchEvent`.

    nats-py exposes the operation kind via an ``operation`` attribute
    that is a ``KeyValueOp`` enum; on a ``PUT`` the ``value`` attr
    carries the envelope bytes, on ``DELETE``/``PURGE`` it is empty
    (``b""`` or ``None``). We mirror that contract and accept both
    the enum and a string (mock-friendliness).

    Byte-equal source mirror of
    :func:`wirelang.schemas.registry_nats_kv_backend._decode_watch_update`
    with module-local class identities
    (:class:`CapabilityPolicyEnvelopeError` instead of
    :class:`SchemaRegistryEnvelopeError`;
    :class:`CapabilityPolicyWatchOp` /
    :class:`CapabilityPolicyWatchEvent` instead of the schema-registry
    siblings; :func:`_envelope_to_record` instead of
    :func:`_envelope_to_entry`).
    """
    op_raw = getattr(update, "operation", None)
    if op_raw is None and isinstance(update, Mapping):
        op_raw = update.get("operation")
    if op_raw is None:
        raise CapabilityPolicyEnvelopeError(
            f"watch update has no 'operation' attribute: "
            f"type={type(update).__name__}"
        )
    op_name = getattr(op_raw, "name", None) or str(op_raw)
    op_name = op_name.upper()
    if op_name not in {"PUT", "DELETE", "PURGE"}:
        raise CapabilityPolicyEnvelopeError(
            f"watch update has unknown operation: {op_name!r}"
        )
    op = CapabilityPolicyWatchOp(op_name)

    key = getattr(update, "key", None)
    if key is None and isinstance(update, Mapping):
        key = update.get("key")
    if not isinstance(key, str) or not key:
        raise CapabilityPolicyEnvelopeError(
            f"watch update has empty/non-string key: {key!r}"
        )

    revision = getattr(update, "revision", None)
    if revision is None and isinstance(update, Mapping):
        revision = update.get("revision")
    revision_int = int(revision) if revision is not None else 0

    if op is CapabilityPolicyWatchOp.PUT:
        try:
            blob = _coerce_value_bytes(update)
        except CapabilityPolicyEnvelopeError:
            # The PUT carried no .value handle; that is poisoned.
            raise
        record = _envelope_to_record(blob)
        return CapabilityPolicyWatchEvent(
            op=op, key=key, record=record, revision=revision_int
        )

    return CapabilityPolicyWatchEvent(
        op=op, key=key, record=None, revision=revision_int
    )


@dataclass
class _CapabilityPolicyWatchStreamHandle:
    """Internal wrapper around the underlying nats-py watcher.

    Adapts to two mock shapes:

    1. The watcher is itself an async iterator (``__aiter__`` /
       ``__anext__``); ``stop()`` (sync or async) closes it.
    2. The watcher exposes ``await updates()`` returning the next
       update or ``None`` for end-of-stream; ``stop()`` closes it.

    nats-py's real ``KeyWatcher`` matches shape 2 with a sentinel
    ``None`` between the initial snapshot replay and the live tail;
    we surface that sentinel as a stream-internal marker only and
    do NOT emit it to the consumer.

    Byte-equal source mirror of
    :class:`wirelang.schemas.registry_nats_kv_backend._SchemaWatchStreamHandle`
    with the decoder swapped for
    :func:`_decode_capability_policy_watch_update` and the no-iter
    fallback raise swapped for :class:`CapabilityPolicyBackendError`.
    """

    underlying: Any

    async def __aenter__(self) -> "_CapabilityPolicyWatchStreamHandle":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        stop = getattr(self.underlying, "stop", None)
        if stop is None:
            return
        result = stop()
        if hasattr(result, "__await__"):
            await result

    def __aiter__(self) -> "_CapabilityPolicyWatchStreamHandle":
        return self

    async def __anext__(self) -> CapabilityPolicyWatchEvent:
        # Shape 1: native async iterator.
        if hasattr(self.underlying, "__anext__"):
            while True:
                update = await self.underlying.__anext__()
                if update is None:
                    # nats-py end-of-initial-replay sentinel; skip it
                    # but keep the iterator alive for the live tail.
                    continue
                return _decode_capability_policy_watch_update(update)
        # Shape 2: ``await updates()`` returns next or None.
        updates = getattr(self.underlying, "updates", None)
        if updates is not None:
            while True:
                update = await updates()
                if update is None:
                    # End-of-stream; stop the iterator.
                    raise StopAsyncIteration
                return _decode_capability_policy_watch_update(update)
        raise CapabilityPolicyBackendError(
            f"watch handle has neither __anext__ nor updates(): "
            f"type={type(self.underlying).__name__}"
        )


async def _open_capability_policy_watcher(kv: Any) -> Any:
    """Open the underlying watcher on the KV handle.

    nats-py exposes ``await kv.watchall()`` returning an awaitable
    watcher; some mocks expose the same name without async, or use
    ``watch()`` as the entry point.

    Byte-equal source mirror of
    :func:`wirelang.schemas.registry_nats_kv_backend._open_watcher`
    with the backend-error class swapped.
    """
    watch_fn = getattr(kv, "watchall", None)
    if watch_fn is None:
        watch_fn = getattr(kv, "watch", None)
    if watch_fn is None:
        raise CapabilityPolicyBackendError(
            "KV handle exposes neither watchall() nor watch()"
        )
    result = watch_fn()
    if hasattr(result, "__await__"):
        result = await result
    return result


async def open_capability_policy_watch_stream(
    backend: "NatsKvCapabilityPolicyBackend",
) -> _CapabilityPolicyWatchStreamHandle:
    """Open a watch-stream over the backend's KV bucket.

    Use as an async context manager OR consume directly; either way,
    ``stop()`` is called on close. Each iteration yields one
    :class:`CapabilityPolicyWatchEvent`. Decoder errors raise
    :class:`CapabilityPolicyEnvelopeError` and terminate the iterator.

    Pattern-mirror on
    :func:`wirelang.schemas.registry_nats_kv_backend.open_watch_stream`.
    """
    if not isinstance(backend, NatsKvCapabilityPolicyBackend):
        raise TypeError(
            "backend must be a NatsKvCapabilityPolicyBackend"
        )
    underlying = await _open_capability_policy_watcher(backend.kv)
    return _CapabilityPolicyWatchStreamHandle(underlying=underlying)


@dataclass
class LiveCapabilityPolicySnapshot:
    """Live, watch-stream-fed snapshot of the capability-policy registry.

    Phase-2 Sprint-5 Tag-5 (S5-5) substrate. Initialises an in-memory
    copy from a full backend snapshot, then applies decoded
    :class:`CapabilityPolicyWatchEvent` instances to keep the copy in
    sync.

    The class is NOT itself a :class:`CapabilityPolicyRegistry`. To
    pass it to a verifier module
    (:func:`check_registered_by_capability`), call
    :meth:`as_registry` to take a frozen copy at the current state.
    Subsequent watch events do not mutate the returned copy
    (determinism contract: a frozen copy passed to one verifier pass
    yields stable verdicts).

    Internal storage: a per-key map of records
    (``capability-policies/<registered_by>/<policy_id>`` -> record).
    The map is the canonical state; :meth:`as_registry` rebuilds a
    :class:`CapabilityPolicyRegistry` from the values on each call.
    This indirection is intentional: the
    :class:`CapabilityPolicyRegistry` from Sprint-4 Tag-6 is indexed by
    ``registered_by`` only (a single issuer may carry multiple
    policies); the watch-stream needs per-(issuer, policy_id) update /
    delete semantics, so we keep the key-indexed map alongside.

    Concurrency: a :class:`LiveCapabilityPolicySnapshot` is intended
    for a single-consumer pattern within one asyncio task. Cross-task
    sharing requires the caller to lock; the class itself does no
    locking because asyncio guarantees in-task atomicity between
    awaits, and :meth:`apply` is synchronous.

    Pattern-mirror on
    :class:`wirelang.schemas.registry_nats_kv_backend.LiveSchemaSnapshot`.
    """

    initial: list  # list[CapabilityPolicyRecord]
    last_revision: int = 0
    _live: dict = field(init=False)  # dict[str, CapabilityPolicyRecord]

    def __post_init__(self) -> None:
        # Defensive copy: callers may keep a reference to ``initial``
        # and we must not mutate it as deltas arrive.
        self._live = {}
        for record in self.initial:
            if not isinstance(record, CapabilityPolicyRecord):
                raise CapabilityPolicyValidationError(
                    f"initial snapshot must contain CapabilityPolicyRecord "
                    f"instances: got type={type(record).__name__}"
                )
            self._live[record.key] = record

    def apply(self, event: CapabilityPolicyWatchEvent) -> None:
        """Apply one :class:`CapabilityPolicyWatchEvent` to the live state.

        PUT updates / inserts the record; DELETE / PURGE remove it
        (no-op if already absent). The ``last_revision`` counter
        advances monotonically: an event with a revision lower than
        the current ``last_revision`` does NOT regress the counter.
        """
        if not isinstance(event, CapabilityPolicyWatchEvent):
            raise TypeError(
                "event must be a CapabilityPolicyWatchEvent"
            )
        if event.op is CapabilityPolicyWatchOp.PUT:
            if event.record is None:
                raise CapabilityPolicyEnvelopeError(
                    "PUT CapabilityPolicyWatchEvent must carry a "
                    "non-None record"
                )
            self._live[event.key] = event.record
        else:
            # DELETE / PURGE: remove the key if present.
            self._live.pop(event.key, None)
        if event.revision > self.last_revision:
            self.last_revision = event.revision

    def as_registry(self) -> CapabilityPolicyRegistry:
        """Return a frozen :class:`CapabilityPolicyRegistry` copy of the
        current live state.

        The returned registry does not share storage with the live
        state; subsequent :meth:`apply` calls do not mutate it.

        Records are added in sorted-key order, mirroring the
        :meth:`NatsKvCapabilityPolicyBackend.snapshot_registry`
        determinism contract.
        """
        registry = CapabilityPolicyRegistry()
        for key in sorted(self._live.keys()):
            registry.add_policy(self._live[key].policy)
        return registry

    def records(self) -> list:
        """Return a stable list of records in sorted-key order.

        Useful for audit consumers that want the full record
        (including operator-side bookkeeping fields) rather than the
        gate-ready :class:`CapabilityPolicyRegistry`.
        """
        return [self._live[key] for key in sorted(self._live.keys())]

    @classmethod
    async def from_backend(
        cls, backend: "NatsKvCapabilityPolicyBackend"
    ) -> "LiveCapabilityPolicySnapshot":
        """Bootstrap a :class:`LiveCapabilityPolicySnapshot` from a
        full backend snapshot. The caller is responsible for opening a
        watch-stream and feeding events to :meth:`apply`.
        """
        initial = await backend.snapshot()
        return cls(initial=initial, last_revision=0)


# ---------------------------------------------------------------------------
# Revocation Event Classifier (Phase-2 Sprint-6 Tag-3, consumer-side
# symmetry to Sprint-6 Tag-1 backend revocation-axis)
# ---------------------------------------------------------------------------
#
# Sprint-6 Tag-1 added the backend-write side of the revocation surface
# (the ``CapabilityPolicy.revoked_at`` + ``revocation_reason`` fields,
# the ``CapabilityPolicyRevocationConflict`` invariants on the write
# path, the publisher-CLI ``revoke`` subcommand from Tag-2). The
# consumer side – an audit-track observer that watches the bucket and
# wants to know "WHICH watch-event was a revocation?" – had no
# explicit surface: a downstream consumer had to compare PUT-event
# records' ``policy.revoked_at`` against its own prior view to
# classify each event.
#
# Sprint-6 Tag-3 closes that asymmetry. The
# :class:`RevocationEventClassifier` keeps a per-key map of the last
# observed ``revoked_at`` instant and turns each
# :class:`CapabilityPolicyWatchEvent` into a
# :class:`ClassifiedRevocationEvent` annotated with one of five
# :class:`RevocationEventKind` values. The classifier is a pure-Python
# value object: it owns no async resources, performs no IO, and is
# safe to instantiate without a running event loop.
#
# Audit pattern: a consumer opens the watch-stream, drives both
# :class:`LiveCapabilityPolicySnapshot.apply` (for the live registry
# view) and :meth:`RevocationEventClassifier.classify` (for the
# revocation-event-axis annotation) from the same event sequence. The
# two are orthogonal: the live snapshot tracks "what is the active
# policy state right now", the classifier tracks "what kind of
# transition did each event represent".
#
# Symmetry with Sprint-6 Tag-1: the classifier mirrors the same
# revocation-monotonic invariant the backend enforces on writes – once
# a key is revoked, subsequent PUTs MUST preserve ``revoked_at``
# byte-equally; an apparent un-revoke or an advanced ``revoked_at`` is
# a witness of substrate corruption or out-of-band tampering and is
# surfaced as :attr:`RevocationEventKind.REVOCATION_MONOTONIC_BREACH`.
# The classifier does NOT raise on a breach – it surfaces the kind so
# audit consumers can decide their policy (alert, halt, etc.). This is
# deliberate: a classifier is an observation layer, not an enforcement
# layer.


class RevocationEventKind(enum.Enum):
    """Classification of a capability-policy watch event with respect
    to the revocation axis.

    Six kinds (Sprint-6 Tag-3 introduced five, Sprint-6 Tag-9 added
    :attr:`EXPLICIT_UNREVOKE`) cover the cross-product of {PUT,
    DELETE/PURGE} x {prior-state present?} x {prior revoked?} x
    {incoming revoked?} x {operator-deliberate marker present?}.

    - :attr:`NOT_REVOCATION_RELATED`: a PUT with ``revoked_at=None``
      against a prior live state that was also ``revoked_at=None`` (or
      no prior state). The event has no revocation-axis content.
    - :attr:`REVOCATION_TRANSITION`: a PUT carrying ``revoked_at != None``
      against a prior live state with ``revoked_at=None`` (or no prior
      state). This is the *first* time the key carries a revocation
      instant; downstream audit consumers should treat this as the
      authoritative "policy became revoked at <instant>" moment.
    - :attr:`REVOCATION_REFRESH`: a PUT carrying the same ``revoked_at``
      instant as the prior live state (which was already revoked). This
      is an audit-trail refresh (e.g. ``revocation_reason`` updated,
      ``registered_at`` advanced) without altering the revocation
      decision. Verifier-side gating is unchanged.
    - :attr:`EXPLICIT_UNREVOKE` (Sprint-6 Tag-9): a PUT against a
      prior-revoked key that drops ``revoked_at`` to ``None`` AND
      carries an :class:`UnrevokeAuditMarker` whose
      ``previous_revoked_at`` matches the classifier's prior view.
      This is the operator-deliberate counterpart of the publisher-
      CLI ``unrevoke`` subcommand (Sprint-6 Tag-7); the marker
      witnesses that an authorised operator performed the gesture and
      lets watch-side audit consumers distinguish it from
      :attr:`REVOCATION_MONOTONIC_BREACH` without cross-referencing a
      separate receipt channel.
    - :attr:`REVOCATION_MONOTONIC_BREACH`: a PUT against a prior-revoked
      key that either (a) drops ``revoked_at`` to ``None`` *without*
      a valid :class:`UnrevokeAuditMarker` (no marker, marker whose
      ``previous_revoked_at`` mismatches the classifier's prior view,
      or marker present but the gesture is otherwise inconsistent) or
      (b) carries a strictly different ``revoked_at`` instant
      (advance or retreat). CAS-pin backend invariants from Sprint-6
      Tag-1 forbid these transitions even via the LWW path's Sprint-6
      Tag-7 unrevoke subcommand (which writes a fully-formed
      unrevoked record on the LWW path); observing the unmarked
      shape on the watch-stream is a *witness* that the bucket state
      was mutated out-of-band (substrate corruption, manual override,
      or a classifier-internal book-keeping error). The classifier
      surfaces the kind; the consumer decides the response.
    - :attr:`KEY_REMOVED`: a DELETE or PURGE event. The classifier
      preserves no revocation history beyond the event; if the key is
      later re-introduced via PUT, the next event will be classified
      against a fresh prior-empty state. (Rationale: DELETE is a
      hard removal in the KV substrate; the revocation lineage is
      severed by definition.)

    The enum is an :class:`enum.Enum`, not :class:`enum.IntEnum`, by
    design: the values are not ordered and equality checks should be
    explicit (``kind is RevocationEventKind.REVOCATION_TRANSITION``).
    """

    NOT_REVOCATION_RELATED = "not_revocation_related"
    REVOCATION_TRANSITION = "revocation_transition"
    REVOCATION_REFRESH = "revocation_refresh"
    REVOCATION_MONOTONIC_BREACH = "revocation_monotonic_breach"
    KEY_REMOVED = "key_removed"
    EXPLICIT_UNREVOKE = "explicit_unrevoke"


@dataclass(frozen=True)
class ClassifiedRevocationEvent:
    """A :class:`CapabilityPolicyWatchEvent` annotated with a
    :class:`RevocationEventKind`.

    Fields:

    - ``event``: the underlying :class:`CapabilityPolicyWatchEvent`.
      The classifier does not mutate or replace it; downstream
      consumers can still apply it to a
      :class:`LiveCapabilityPolicySnapshot` for the live-registry
      axis.
    - ``kind``: the :class:`RevocationEventKind`.
    - ``prior_revoked_at``: the ``revoked_at`` instant observed for
      this key before this event (or ``None`` if no prior state).
      Useful for audit consumers that want to log the full state
      transition (prior vs. incoming).
    - ``current_revoked_at``: the ``revoked_at`` instant carried by
      this event's record. ``None`` for DELETE / PURGE events, or for
      PUT events whose record has ``revoked_at=None``.
    - ``current_revocation_reason``: the ``revocation_reason`` carried
      by this event's record. ``None`` for DELETE / PURGE events, or
      for PUT events whose record carries no ``revocation_reason``.

    Frozen: a classifier returns a stable value per event; consumers
    can put :class:`ClassifiedRevocationEvent` into sets and use them
    as dict keys without surprise.
    """

    event: CapabilityPolicyWatchEvent
    kind: RevocationEventKind
    prior_revoked_at: Optional[datetime]
    current_revoked_at: Optional[datetime]
    current_revocation_reason: Optional[str]


class RevocationEventClassifier:
    """Stateful classifier that annotates each
    :class:`CapabilityPolicyWatchEvent` with a
    :class:`RevocationEventKind`.

    The classifier keeps a per-key ``revoked_at``-history map. The map
    is the minimum state needed to classify a new event: only the
    last-seen ``revoked_at`` instant per key is retained, not the full
    record history (which the
    :class:`LiveCapabilityPolicySnapshot` already maintains in
    parallel).

    Usage::

        classifier = RevocationEventClassifier()
        # Optionally seed from a snapshot for resume-after-restart
        # scenarios:
        classifier.seed_from_records(await backend.snapshot())
        async with await backend.watch() as stream:
            async for event in stream:
                classified = classifier.classify(event)
                if classified.kind is \\
                        RevocationEventKind.REVOCATION_TRANSITION:
                    audit_log.record_revocation(classified)
                elif classified.kind is \\
                        RevocationEventKind.REVOCATION_MONOTONIC_BREACH:
                    alert.fire(classified)

    Concurrency: the classifier is intended for a single-consumer
    pattern in one asyncio task. :meth:`classify` and
    :meth:`seed_from_records` are synchronous and mutate the internal
    map; cross-task sharing requires caller-side locking.

    Pattern-mirror on :class:`LiveCapabilityPolicySnapshot`: both are
    "watch-stream-fed observer" objects. The split keeps each one's
    concern narrow – the live snapshot tracks the *current registry*,
    the classifier tracks the *revocation-axis transitions*.
    """

    def __init__(self) -> None:
        # Per-key last-seen ``revoked_at`` instant. ``None`` value means
        # the key has been observed but is not currently revoked. The
        # absence of a key from the map means "no prior state".
        self._revoked_at_by_key: dict = {}

    def seed_from_records(self, records: list) -> None:
        """Seed the classifier's per-key state from a list of
        :class:`CapabilityPolicyRecord` instances (e.g. a full
        ``await backend.snapshot()`` result).

        Useful for resume-after-restart scenarios where the consumer
        has bootstrapped its live snapshot from the backend and now
        wants the classifier's prior-state map to reflect the same
        baseline. Without seeding, the first watch event for each key
        would be classified as a transition (or not-revocation) against
        an empty prior state.

        Idempotent: calling :meth:`seed_from_records` repeatedly with
        the same input produces the same internal state. Subsequent
        :meth:`classify` calls overwrite the seeded state as events
        arrive.
        """
        for record in records:
            if not isinstance(record, CapabilityPolicyRecord):
                raise CapabilityPolicyValidationError(
                    f"seed_from_records expects CapabilityPolicyRecord "
                    f"instances: got type={type(record).__name__}"
                )
            self._revoked_at_by_key[record.key] = (
                record.policy.revoked_at
            )

    def classify(
        self, event: CapabilityPolicyWatchEvent
    ) -> ClassifiedRevocationEvent:
        """Classify one :class:`CapabilityPolicyWatchEvent`.

        Returns a :class:`ClassifiedRevocationEvent`. Side-effect: the
        classifier's internal per-key state map is updated to reflect
        the event's effect, so the next event for the same key is
        classified against the now-updated prior state.

        Decision table (Sprint-6 Tag-9 extended with marker column):

        ===========  ============  ============  ============  ==================================
        op           prior state   incoming      marker        kind
        ===========  ============  ============  ============  ==================================
        PUT          absent        None          any           NOT_REVOCATION_RELATED
        PUT          absent        non-None      any           REVOCATION_TRANSITION
        PUT          None          None          any           NOT_REVOCATION_RELATED
        PUT          None          non-None      any           REVOCATION_TRANSITION
        PUT          non-None X    None          marker.prev=X EXPLICIT_UNREVOKE
        PUT          non-None X    None          absent / mismatch REVOCATION_MONOTONIC_BREACH
        PUT          non-None X    non-None X    any           REVOCATION_REFRESH
        PUT          non-None X    non-None Y    any           REVOCATION_MONOTONIC_BREACH
        DELETE       any           N/A           N/A           KEY_REMOVED
        PURGE        any           N/A           N/A           KEY_REMOVED
        ===========  ============  ============  ============  ==================================

        Marker semantics (Sprint-6 Tag-9): the
        :class:`UnrevokeAuditMarker` on the incoming record carries
        ``previous_revoked_at`` — the publisher-CLI ``unrevoke``
        subcommand reads the live record before rewriting and
        captures that instant on the marker. The classifier cross-
        checks that against its own per-key prior view: a match
        validates the operator-deliberate gesture
        (``EXPLICIT_UNREVOKE``); a mismatch (or absence) means the
        gesture cannot be authenticated against the observed prior
        state and is itself a witness of tampering
        (``REVOCATION_MONOTONIC_BREACH``).

        Marker presence on non-unrevoke shapes (e.g. a marker on a
        PUT that does not drop ``revoked_at`` to None — which the
        :class:`CapabilityPolicyRecord` constructor already rejects
        — or on a NOT_REVOCATION_RELATED / REVOCATION_TRANSITION /
        REVOCATION_REFRESH shape) is *ignored* on the classification
        axis: the gesture type is determined by the revocation-axis
        transition, not by marker presence alone. The marker is only
        load-bearing on the specific prior-revoked-to-unrevoked
        transition.

        After classification, the per-key state map is updated:

        - PUT: prior-state := record.policy.revoked_at
        - DELETE / PURGE: key is removed from the map
        """
        if not isinstance(event, CapabilityPolicyWatchEvent):
            raise TypeError(
                "event must be a CapabilityPolicyWatchEvent"
            )

        prior_revoked_at = self._revoked_at_by_key.get(event.key)
        key_had_prior_state = event.key in self._revoked_at_by_key

        if event.op in (
            CapabilityPolicyWatchOp.DELETE,
            CapabilityPolicyWatchOp.PURGE,
        ):
            # Drop the key from the classifier's map; revocation lineage
            # is severed by definition (substrate-level hard removal).
            self._revoked_at_by_key.pop(event.key, None)
            return ClassifiedRevocationEvent(
                event=event,
                kind=RevocationEventKind.KEY_REMOVED,
                prior_revoked_at=prior_revoked_at
                if key_had_prior_state
                else None,
                current_revoked_at=None,
                current_revocation_reason=None,
            )

        # PUT branch: the event MUST carry a record (the decoder's
        # contract). A PUT with record=None would have been raised
        # earlier in the pipeline by
        # :func:`_decode_capability_policy_watch_update`; we re-assert
        # the invariant defensively.
        if event.record is None:
            raise CapabilityPolicyEnvelopeError(
                "PUT CapabilityPolicyWatchEvent must carry a "
                "non-None record (classifier invariant)"
            )

        incoming_revoked_at = event.record.policy.revoked_at
        incoming_revocation_reason = (
            event.record.policy.revocation_reason
        )

        # Classification logic.
        if prior_revoked_at is None:
            # Prior state is either absent or unrevoked. Marker (if
            # any) is ignored — the operator-deliberate-unrevoke
            # gesture is only meaningful AWAY from a non-None prior
            # state. A marker carried on a non-unrevoke-shape record
            # is structurally suppressed earlier by the record
            # constructor (rejects marker + revoked_at != None) and
            # ignored here for the no-prior-revoked-state branch.
            if incoming_revoked_at is None:
                kind = RevocationEventKind.NOT_REVOCATION_RELATED
            else:
                kind = RevocationEventKind.REVOCATION_TRANSITION
        else:
            # Prior state is revoked.
            if incoming_revoked_at is None:
                # Apparent un-revoke. Sprint-6 Tag-9: branch on the
                # operator-deliberate marker. A marker present AND
                # whose ``previous_revoked_at`` matches the
                # classifier's prior view authenticates the gesture.
                # Any other shape (marker absent, marker with
                # ``previous_revoked_at`` mismatching the prior view)
                # falls through to BREACH — the watch-stream cannot
                # tell apart an unmarked operator bypass from a
                # substrate-corruption un-revoke, so the safe default
                # is the louder kind.
                marker = event.record.unrevoke_audit_marker
                if (
                    marker is not None
                    and marker.previous_revoked_at == prior_revoked_at
                ):
                    kind = RevocationEventKind.EXPLICIT_UNREVOKE
                else:
                    kind = (
                        RevocationEventKind.REVOCATION_MONOTONIC_BREACH
                    )
            elif incoming_revoked_at == prior_revoked_at:
                kind = RevocationEventKind.REVOCATION_REFRESH
            else:
                # Strictly different revoked_at (advance or retreat;
                # both forbidden by backend invariants).
                kind = RevocationEventKind.REVOCATION_MONOTONIC_BREACH

        # Update the per-key state map AFTER classification so the
        # classifier observes the prior state correctly for THIS event,
        # then advances for the next.
        self._revoked_at_by_key[event.key] = incoming_revoked_at

        return ClassifiedRevocationEvent(
            event=event,
            kind=kind,
            prior_revoked_at=prior_revoked_at
            if key_had_prior_state
            else None,
            current_revoked_at=incoming_revoked_at,
            current_revocation_reason=incoming_revocation_reason,
        )

    def known_keys(self) -> list:
        """Return the sorted list of keys the classifier has observed.

        Useful for audit-trail surfacing (e.g. "how many distinct
        policy-pairs have we seen on this stream?") without exposing
        the internal map.
        """
        return sorted(self._revoked_at_by_key.keys())

    def last_revoked_at(self, key: str) -> Optional[datetime]:
        """Return the last-observed ``revoked_at`` instant for ``key``,
        or ``None`` if the key is not currently revoked (either it has
        never been observed, has been observed as unrevoked, or has
        been removed by DELETE / PURGE).

        Note: the return value ``None`` is intentionally ambiguous
        between "never observed" and "observed but unrevoked". Callers
        that need the distinction should use :meth:`known_keys` or
        track the membership themselves.
        """
        return self._revoked_at_by_key.get(key)


async def filter_revocation_events(
    stream: Any,
    classifier: Optional["RevocationEventClassifier"] = None,
    kinds: Optional[frozenset] = None,
):
    """Async generator that wraps an async iterator of
    :class:`CapabilityPolicyWatchEvent` and yields the subset matching
    ``kinds``, classified via ``classifier``.

    Parameters:

    - ``stream``: any async iterator yielding
      :class:`CapabilityPolicyWatchEvent` instances. The
      :class:`_CapabilityPolicyWatchStreamHandle` returned by
      :meth:`NatsKvCapabilityPolicyBackend.watch` is the canonical
      input.
    - ``classifier``: optional :class:`RevocationEventClassifier`
      instance. If ``None``, a fresh one is constructed. Pass an
      existing classifier to preserve per-key state across multiple
      filter calls or to share the classifier with another consumer.
    - ``kinds``: optional frozenset of
      :class:`RevocationEventKind` values to surface. If ``None``,
      defaults to ``{REVOCATION_TRANSITION, REVOCATION_REFRESH,
      REVOCATION_MONOTONIC_BREACH, EXPLICIT_UNREVOKE}`` (the four
      revocation-axis kinds — three from Sprint-6 Tag-3 plus the
      Sprint-6 Tag-9 operator-deliberate-unrevoke kind). Pass
      ``frozenset(RevocationEventKind)`` to surface every classified
      event (useful for full-audit consumers).

    Yields: :class:`ClassifiedRevocationEvent` instances whose ``kind``
    is in ``kinds``. The classifier sees EVERY event in the stream
    (so its state map stays consistent); only the kinds matching the
    filter are yielded.

    Closing semantics: when the underlying stream ends, this generator
    completes naturally. The classifier remains usable for further
    calls after the generator returns.
    """
    if classifier is None:
        classifier = RevocationEventClassifier()
    elif not isinstance(classifier, RevocationEventClassifier):
        raise TypeError(
            "classifier must be a RevocationEventClassifier or None"
        )

    if kinds is None:
        kinds = frozenset({
            RevocationEventKind.REVOCATION_TRANSITION,
            RevocationEventKind.REVOCATION_REFRESH,
            RevocationEventKind.REVOCATION_MONOTONIC_BREACH,
            # Sprint-6 Tag-9: surface operator-deliberate unrevoke
            # by default so audit consumers see the gesture on the
            # same default filter as BREACH (the two are sister
            # kinds on the prior-revoked-to-unrevoked transition).
            RevocationEventKind.EXPLICIT_UNREVOKE,
        })
    elif not isinstance(kinds, (frozenset, set)):
        raise TypeError(
            "kinds must be a frozenset/set of RevocationEventKind or None"
        )
    else:
        for k in kinds:
            if not isinstance(k, RevocationEventKind):
                raise TypeError(
                    f"kinds members must be RevocationEventKind: got "
                    f"type={type(k).__name__}"
                )
        kinds = frozenset(kinds)

    async for event in stream:
        classified = classifier.classify(event)
        if classified.kind in kinds:
            yield classified


__all__ = [
    "BUCKET_NAME",
    "BUCKET_CONFIG",
    "VALUE_SCHEMA",
    "CapabilityPolicyBackendError",
    "CapabilityPolicyConflictError",
    "CapabilityPolicyEnvelopeError",
    "CapabilityPolicyRevocationConflict",
    "CapabilityPolicyValidationError",
    "CapabilityPolicyRecord",
    "CapabilityPolicyWatchEvent",
    "CapabilityPolicyWatchOp",
    "ClassifiedRevocationEvent",
    "LiveCapabilityPolicySnapshot",
    "NatsKvCapabilityPolicyBackend",
    "RevocationEventClassifier",
    "RevocationEventKind",
    "UnrevokeAuditMarker",
    "filter_revocation_events",
    "key_for_policy_pair",
    "open_capability_policy_watch_stream",
    "pair_for_key",
]
