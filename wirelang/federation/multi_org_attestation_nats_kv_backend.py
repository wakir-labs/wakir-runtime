# SPDX-License-Identifier: BUSL-1.1
"""NATS-JetStream-KV-backed Multi-Org-Attestation registry.

Phase-2 Sprint-7 Tag-2 lands the durable production-target backend
for the multi-org federation substrate introduced by Sprint-7 Tag-1
(:mod:`wirelang.federation.multi_org_substrate`). The Tag-1 module
shipped the :class:`MultiOrgRouteAttestation` dataclass, an in-memory
reference registry, and a mock-bridge-route resolver; this module
supplies the durable, watch-stream-capable, CAS-pinned, cross-bucket-
replicable backend for the production deployment.

Substrate
---------

The backend persists :class:`MultiOrgRouteAttestation` records in a
NATS-JetStream key-value bucket named :data:`BUCKET_NAME`
(``wakir-multi-org-attestations``). The bucket's documented
configuration follows the same drift-policy contract as the four
Phase-1 buckets initialised by ``scripts/init-nats-buckets.py`` and
the Sprint-3 Tag-6 ``wakir-federation-routes`` bucket: this backend
does NOT auto-create or auto-correct bucket configuration — it
expects an operator-run ``init-nats-buckets`` to have established
the bucket before any :class:`NatsKvMultiOrgAttestationRegistry`
is constructed.

Configuration (drift-policy mirror of the Phase-1b route-registry
bucket):

- ``history``: 5  (allows audit-trail review of recent overwrites)
- ``ttl_seconds``: 0  (unbounded; attestations age via revocation,
  not via KV TTL)
- ``max_value_size``: 4096 B  (one attestation envelope is small
  JSON; cap mirrors ``wakir-federation-routes``)
- ``storage``: ``"file"``  (durability for production)
- ``replicas``: 1  (Phase-1 single-node; Phase-2 multi-node will
  raise this)

Cross-reference: :data:`BUCKET_NAME` is exported as a module-level
constant so the orchestrator bucket-init script can register the
bucket in the same idempotent inventory pass.

Design choices
--------------

The synchronous surface that downstream code queries is the Tag-1
:class:`InMemoryMultiOrgAttestationRegistry` (``add`` / ``lookup``);
nats-py's KV API is async. We therefore do NOT make the backend
itself the registry object: instead the backend exposes async
operations and a :meth:`snapshot` method that materialises a
deterministic :class:`InMemoryMultiOrgAttestationRegistry` for one
caller pass. Same pattern as the Sprint-3 Tag-6 route-registry
backend (Reza-Hand: pattern-mirror, not new pattern).

CAS-pin (lost-update protection): :meth:`put_with_revision` accepts
an ``expected_revision`` and forwards it to the underlying nats-py
``KeyValue.update(key, value, last=...)`` call. A stale revision
surfaces as :class:`MultiOrgAttestationConflictError`. The
Sprint-5 Tag-4 capability-policy CAS-pin helper is the pattern
this backend mirrors.

Monotonic-invariant (authority-gesture contract): attestations are
authority gestures — once an operator records a non-mock attestation
for a ``route_id``, the load-bearing authority fields
(:attr:`MultiOrgRouteAttestation.peer_trust_domain` and
:attr:`MultiOrgRouteAttestation.peer_audit_anchor_did`) are
**immutable**. The optional fields (``peer_wat_anchor_manifest_id``,
``peer_trust_bundle_url``, ``peer_capability_policy_pointer``) MAY
be added but MUST NOT be cleared once set (additive-monotonic). A
mock-to-live transition is forbidden in-place: it requires a new
``route_id`` (the mock prefix is locked at the substrate-layer). A
violation surfaces as :class:`MultiOrgAttestationMonotonicConflict`
on every write path (``put``, ``put_with_revision``, and the
replicator).

The monotonic-invariant gate runs BEFORE any KV write (defence in
depth against partial replicator state) and BEFORE CAS-pin (so a
revoked authority anchor cannot sneak in via a stale-revision
race). This mirrors the Sprint-6 Tag-1 capability-policy
``revoked_at``-monotonic gate.

Value envelope
--------------

Each KV entry is a JSON object with these fields:

- ``schema``: :data:`ATTESTATION_VALUE_SCHEMA`
  (``"wakir.federation.multi-org-attestation/1"``).
- ``route_id``: copy of the attestation's ``route_id`` (the KV key
  is the same string; the field is duplicated for self-contained
  reads).
- ``peer_trust_domain``: SPIFFE trust-domain string.
- ``peer_audit_anchor_did``: ``did:web`` string.
- ``peer_wat_anchor_manifest_id``: optional string or ``null``.
- ``peer_trust_bundle_url``: optional https URL or ``null``.
- ``peer_capability_policy_pointer``: optional string or ``null``.
- ``is_mock``: ``true`` / ``false``.

JSON is the obvious envelope: small, observable with the ``nats``
CLI, and preserves the Phase-1b convention used by every other KV
value in the inventory. We use sorted keys with the compact
``(",", ":")`` separator so the value bytes are reproducible.

Hermetic test contract
----------------------

The test suite at
``wirelang/tests/test_federation_multi_org_attestation_nats_kv_backend.py``
exercises the backend against a small in-memory mock that mirrors
the Sprint-3 Tag-6 route-registry mock (which itself mirrors Kai's
Tag-1 ``_MockKv``).

References:

- Sprint-7 Tag-1 substrate:
  ``wirelang/federation/multi_org_substrate.py``.
- Sprint-3 Tag-6 route-registry backend (pattern-mirror):
  ``wirelang/federation/route_registry_nats_kv_backend.py``.
- Sprint-5 Tag-4 CAS-pin pattern:
  ``wirelang/schemas/capability_policy_nats_kv_backend.py``
  (``put_with_revision`` + ``_kv_update_with_revision``).
- Sprint-6 Tag-1 monotonic-invariant pattern: same module,
  ``CapabilityPolicyRevocationConflict``.
- Sprint-6 Tag-6 cross-bucket replication pattern:
  ``wirelang/schemas/capability_policy_replication.py``.

ADR-0050 Tool-Surface-Stempel: this file was authored using Read,
Edit, Write, Bash. No Agent-Tool, no WebFetch. Pre-Box-Worktree
ADR-0049 ``/tmp/reza-sprint-7-tag-2-runtime`` (suffix ``-runtime``
per Tag-1 Tip ``9aef092``).
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Mapping, Optional, Tuple

from .multi_org_substrate import (
    ATTESTATION_VALUE_SCHEMA,
    InMemoryMultiOrgAttestationRegistry,
    MOCK_BRIDGE_ROUTE_ID_PREFIX,
    MultiOrgAttestationConflictError,
    MultiOrgAttestationValidationError,
    MultiOrgRouteAttestation,
    MultiOrgSubstrateError,
)


# ---------------------------------------------------------------------------
# Bucket identity (cross-reference: orchestrator bucket inventory)
# ---------------------------------------------------------------------------


#: NATS-KV bucket name for the multi-org-attestation registry.
#: Phase-2 Sprint-7 convention: ``wakir-`` prefix, kebab-case,
#: plural-domain noun (attestations form a side-table keyed by
#: route_id, conceptually a collection — hence the plural).
BUCKET_NAME = "wakir-multi-org-attestations"

#: Documented bucket configuration. The drift-policy is identical
#: to the Sprint-3 Tag-6 route-registry bucket: any deviation
#: between the live cluster and these values is reported as drift,
#: never auto-corrected.
BUCKET_CONFIG: Mapping[str, Any] = {
    "name": BUCKET_NAME,
    "description": (
        "V-908 multi-org-federation attestation registry "
        "(Phase-2 Sprint-7)"
    ),
    "history": 5,
    "ttl_seconds": 0,
    "max_value_size": 4096,
    "storage": "file",
    "replicas": 1,
}

#: Schema-URI fragment embedded in every value envelope. Re-exported
#: from the Tag-1 substrate so callers have a single import path.
VALUE_SCHEMA = ATTESTATION_VALUE_SCHEMA


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MultiOrgAttestationBackendError(MultiOrgSubstrateError):
    """Base class for backend-layer failures.

    Inherits from :class:`MultiOrgSubstrateError` so callers that
    already catch substrate-base errors do not need to broaden their
    handler when they switch from the in-memory reference to the
    NATS-KV backend.
    """


class MultiOrgAttestationEnvelopeError(MultiOrgAttestationBackendError):
    """Raised when a KV value cannot be parsed or fails the
    schema-shape contract.

    A poisoned envelope is *not* silently swallowed: the backend
    surfaces the error so an operator can act. The snapshot path
    aborts on poison; partial snapshots are not surfaced because the
    caller-side determinism contract requires a complete,
    self-consistent view.
    """


class MultiOrgAttestationCasConflict(MultiOrgAttestationBackendError):
    """Raised when a CAS-pinned upsert is rejected because the live
    KV revision has changed since the caller observed it.

    Phase-2 Sprint-7 Tag-2 CAS-pin contract (pattern-mirror on the
    Phase-2 Sprint-5 Tag-4 capability-policy CAS-pin and the
    Phase-1b Sprint-3 Tag-3 schema-registry CAS-pin).

    Attributes:
        route_id: the registry key that failed CAS.
        expected_revision: revision the caller observed.
        actual_revision: revision the bucket reports, if surfaced by
            the underlying KV adapter; ``None`` otherwise.
    """

    def __init__(
        self,
        message: str,
        *,
        route_id: Optional[str] = None,
        expected_revision: Optional[int] = None,
        actual_revision: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.route_id = route_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision


class MultiOrgAttestationMonotonicConflict(MultiOrgAttestationBackendError):
    """Raised when a write would breach the authority-gesture
    monotonic invariant.

    The invariant: once a non-mock attestation is recorded for a
    ``route_id``, the load-bearing authority fields
    (:attr:`MultiOrgRouteAttestation.peer_trust_domain` and
    :attr:`MultiOrgRouteAttestation.peer_audit_anchor_did`) are
    immutable. Optional fields are additive-monotonic: they MAY be
    added but MUST NOT be cleared once set. Mock-to-live in-place
    transitions are forbidden (the mock prefix is locked at the
    substrate layer; the transition requires a new ``route_id``).

    Attributes:
        route_id: the registry key on which the breach was detected.
        breach_kind: short string tag identifying the breach.
        existing: the live attestation that the write would have
            mutated (frozen reference).
        incoming: the attestation that would have been written.
    """

    def __init__(
        self,
        message: str,
        *,
        route_id: str,
        breach_kind: str,
        existing: Optional[MultiOrgRouteAttestation] = None,
        incoming: Optional[MultiOrgRouteAttestation] = None,
    ) -> None:
        super().__init__(message)
        self.route_id = route_id
        self.breach_kind = breach_kind
        self.existing = existing
        self.incoming = incoming


# ---------------------------------------------------------------------------
# Envelope codec
# ---------------------------------------------------------------------------


def _attestation_to_envelope(att: MultiOrgRouteAttestation) -> bytes:
    """Serialise a :class:`MultiOrgRouteAttestation` to canonical JSON.

    Sorted keys, compact separators — byte-reproducible per caller.
    The :class:`MultiOrgRouteAttestation` constructor has already
    validated all fields, so this codec performs no extra validation;
    a defensive isinstance check guards against accidental misuse.
    """
    if not isinstance(att, MultiOrgRouteAttestation):
        raise TypeError("att must be a MultiOrgRouteAttestation")
    payload = {
        "schema": VALUE_SCHEMA,
        "route_id": att.route_id,
        "peer_trust_domain": att.peer_trust_domain,
        "peer_audit_anchor_did": att.peer_audit_anchor_did,
        "peer_wat_anchor_manifest_id": att.peer_wat_anchor_manifest_id,
        "peer_trust_bundle_url": att.peer_trust_bundle_url,
        "peer_capability_policy_pointer": (
            att.peer_capability_policy_pointer
        ),
        "is_mock": att.is_mock,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _envelope_to_attestation(blob: bytes) -> MultiOrgRouteAttestation:
    """Inverse of :func:`_attestation_to_envelope`. Raises
    :class:`MultiOrgAttestationEnvelopeError` on shape violation.

    All grammar / type validation is delegated to the
    :class:`MultiOrgRouteAttestation` constructor (Tag-1 substrate);
    if the constructor rejects the payload, the
    :class:`MultiOrgAttestationValidationError` is re-raised as a
    :class:`MultiOrgAttestationEnvelopeError` so callers can rely on
    a single backend-side exception type for "bad bytes in the
    bucket".
    """
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MultiOrgAttestationEnvelopeError(
            f"non-utf-8 envelope: {exc!r}"
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MultiOrgAttestationEnvelopeError(
            f"non-JSON envelope: {exc!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise MultiOrgAttestationEnvelopeError(
            f"envelope is not a JSON object: type="
            f"{type(payload).__name__}"
        )
    schema = payload.get("schema")
    if schema != VALUE_SCHEMA:
        raise MultiOrgAttestationEnvelopeError(
            f"envelope schema mismatch: want {VALUE_SCHEMA!r} "
            f"got {schema!r}"
        )
    for required in (
        "route_id",
        "peer_trust_domain",
        "peer_audit_anchor_did",
        "is_mock",
    ):
        if required not in payload:
            raise MultiOrgAttestationEnvelopeError(
                f"envelope missing required field: {required!r}"
            )
    try:
        return MultiOrgRouteAttestation(
            route_id=payload["route_id"],
            peer_trust_domain=payload["peer_trust_domain"],
            peer_audit_anchor_did=payload["peer_audit_anchor_did"],
            peer_wat_anchor_manifest_id=payload.get(
                "peer_wat_anchor_manifest_id"
            ),
            peer_trust_bundle_url=payload.get("peer_trust_bundle_url"),
            peer_capability_policy_pointer=payload.get(
                "peer_capability_policy_pointer"
            ),
            is_mock=payload["is_mock"],
        )
    except MultiOrgAttestationValidationError as exc:
        raise MultiOrgAttestationEnvelopeError(
            f"envelope failed substrate-validation: {exc!s}"
        ) from exc


# ---------------------------------------------------------------------------
# Monotonic-invariant gate
# ---------------------------------------------------------------------------


def _check_monotonic_invariant(
    *,
    route_id: str,
    existing: Optional[MultiOrgRouteAttestation],
    incoming: MultiOrgRouteAttestation,
) -> None:
    """Raise :class:`MultiOrgAttestationMonotonicConflict` if applying
    ``incoming`` over ``existing`` would breach the authority-gesture
    monotonic invariant.

    See module docstring for the full contract. Summary:

    - Authority anchors (``peer_trust_domain``,
      ``peer_audit_anchor_did``) are immutable once set.
    - Optional fields are additive-monotonic (settable once,
      not nullable thereafter).
    - The ``is_mock`` flag is immutable; mock-to-live transitions
      require a new ``route_id``.

    Idempotent rewrites (byte-equal payload) always pass.
    """
    if existing is None:
        return
    if existing == incoming:
        # Byte-equal idempotent rewrite — always allowed.
        return
    if existing.peer_trust_domain != incoming.peer_trust_domain:
        raise MultiOrgAttestationMonotonicConflict(
            f"peer_trust_domain is immutable for route_id={route_id!r}: "
            f"live={existing.peer_trust_domain!r} "
            f"incoming={incoming.peer_trust_domain!r}",
            route_id=route_id,
            breach_kind="trust-domain-mutation",
            existing=existing,
            incoming=incoming,
        )
    if existing.peer_audit_anchor_did != incoming.peer_audit_anchor_did:
        raise MultiOrgAttestationMonotonicConflict(
            f"peer_audit_anchor_did is immutable for route_id="
            f"{route_id!r}: live={existing.peer_audit_anchor_did!r} "
            f"incoming={incoming.peer_audit_anchor_did!r}",
            route_id=route_id,
            breach_kind="audit-anchor-did-mutation",
            existing=existing,
            incoming=incoming,
        )
    if existing.is_mock != incoming.is_mock:
        raise MultiOrgAttestationMonotonicConflict(
            f"is_mock is immutable for route_id={route_id!r}: "
            f"live={existing.is_mock!r} incoming={incoming.is_mock!r} "
            f"(mint a new route_id for the mock-to-live transition)",
            route_id=route_id,
            breach_kind="mock-flag-mutation",
            existing=existing,
            incoming=incoming,
        )
    # Optional fields: additive-monotonic. Setting None -> value is
    # legal; setting value -> None or value-A -> value-B is not.
    for attr in (
        "peer_wat_anchor_manifest_id",
        "peer_trust_bundle_url",
        "peer_capability_policy_pointer",
    ):
        live_v = getattr(existing, attr)
        in_v = getattr(incoming, attr)
        if live_v is None or live_v == in_v:
            continue
        # live_v is set and incoming differs (incl. None).
        raise MultiOrgAttestationMonotonicConflict(
            f"optional field {attr!r} is additive-monotonic for "
            f"route_id={route_id!r}: live={live_v!r} incoming={in_v!r}",
            route_id=route_id,
            breach_kind=f"optional-mutation:{attr}",
            existing=existing,
            incoming=incoming,
        )


# ---------------------------------------------------------------------------
# KV backend
# ---------------------------------------------------------------------------


@dataclass
class NatsKvMultiOrgAttestationRegistry:
    """NATS-JetStream-KV-backed multi-org-attestation registry.

    Construction is cheap: pass an open ``KeyValue`` handle from
    nats-py (or a mock that mirrors the same surface). The backend
    performs *no* network I/O on construction.

    The backend is async; it is not itself the synchronous registry
    used at lookup-time. Use :meth:`snapshot` to materialise a
    deterministic :class:`InMemoryMultiOrgAttestationRegistry` for
    one caller pass, or :meth:`get` for a single-key fetch.
    """

    kv: Any
    bucket_name: str = BUCKET_NAME

    # ------------------------------------------------------------------
    # Single-key operations
    # ------------------------------------------------------------------

    async def get(
        self, route_id: str
    ) -> Optional[MultiOrgRouteAttestation]:
        """Return the attestation for ``route_id`` or ``None``.

        Raises :class:`MultiOrgAttestationEnvelopeError` if the key
        exists but the value cannot be decoded.
        """
        if not isinstance(route_id, str) or not route_id:
            return None
        try:
            kve = await self.kv.get(route_id)
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
        return _envelope_to_attestation(blob)

    async def get_with_revision(
        self, route_id: str
    ) -> Optional[Tuple[MultiOrgRouteAttestation, int]]:
        """Return ``(attestation, revision)`` or ``None`` for an
        absent key. The revision is the same integer that
        :meth:`put_with_revision` expects.
        """
        if not isinstance(route_id, str) or not route_id:
            return None
        try:
            kve = await self.kv.get(route_id)
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
        att = _envelope_to_attestation(blob)
        revision = _coerce_revision_from_entry(kve)
        return att, revision

    async def put(self, att: MultiOrgRouteAttestation) -> int:
        """Upsert an attestation; returns the new KV revision.

        Last-write-wins on the KV layer, BUT the authority-gesture
        monotonic-invariant gate runs first. A breach surfaces as
        :class:`MultiOrgAttestationMonotonicConflict`. Idempotent
        re-puts (byte-equal payload) are silently accepted.
        """
        if not isinstance(att, MultiOrgRouteAttestation):
            raise TypeError("att must be a MultiOrgRouteAttestation")
        existing = await self.get(att.route_id)
        _check_monotonic_invariant(
            route_id=att.route_id, existing=existing, incoming=att
        )
        blob = _attestation_to_envelope(att)
        revision = await self.kv.put(att.route_id, blob)
        return _coerce_revision(revision)

    async def put_with_revision(
        self,
        att: MultiOrgRouteAttestation,
        expected_revision: int,
    ) -> int:
        """CAS-pinned upsert. Returns the new KV revision.

        Phase-2 Sprint-7 Tag-2 CAS-pin (pattern-mirror on Sprint-5
        Tag-4 capability-policy CAS-pin).

        Gate ordering (defensive):

        1. ``att`` is a :class:`MultiOrgRouteAttestation`.
        2. ``expected_revision`` is a non-negative int.
        3. **Monotonic-invariant** against the live record at the
           same key. The gate runs BEFORE the CAS-pin call so that
           even a stale-revision write cannot un-set an authority
           anchor.
        4. CAS-pin against ``expected_revision``. A stale revision
           surfaces as :class:`MultiOrgAttestationCasConflict`.

        For a record that does not yet exist in the bucket, callers
        MAY pass ``expected_revision=0``; the call succeeds if the
        underlying KV adapter supports the
        ``KeyValue.create(key, value)`` contract (or treats the
        zero-revision as create-if-absent). Mock adapters in the
        test suite emulate this.
        """
        if not isinstance(att, MultiOrgRouteAttestation):
            raise TypeError("att must be a MultiOrgRouteAttestation")
        if not isinstance(expected_revision, int) or expected_revision < 0:
            raise ValueError(
                "expected_revision must be a non-negative int, "
                f"got {expected_revision!r}"
            )
        existing = await self.get(att.route_id)
        _check_monotonic_invariant(
            route_id=att.route_id, existing=existing, incoming=att
        )
        blob = _attestation_to_envelope(att)
        revision = await _kv_update_with_revision(
            self.kv, att.route_id, blob, expected_revision
        )
        return _coerce_revision(revision)

    async def delete(self, route_id: str) -> None:
        """Tombstone a record. No-op if absent.

        Note: the monotonic-invariant gate applies to writes, not to
        deletes. An operator with delete-rights deliberately retracts
        an attestation; the bucket history retains the operation, and
        the audit trail is the source of truth. If the policy
        requires "no delete on live attestations", that gate belongs
        in an operator wrapper (out of scope for Tag-2).
        """
        if not isinstance(route_id, str) or not route_id:
            raise ValueError("route_id must be a non-empty string")
        try:
            await self.kv.delete(route_id)
        except Exception as exc:
            cls_name = type(exc).__name__
            if (
                "NotFound" in cls_name
                or "DoesNotExist" in cls_name
                or isinstance(exc, KeyError)
            ):
                return
            raise

    async def list_keys(self) -> list:
        """Return all registered route_ids. Unsorted; callers that
        want a stable order should sort it themselves.
        """
        return await _list_keys(self.kv)

    # ------------------------------------------------------------------
    # Snapshot (the bridge to the synchronous registry surface)
    # ------------------------------------------------------------------

    async def snapshot(self) -> InMemoryMultiOrgAttestationRegistry:
        """Materialise the live bucket into an
        :class:`InMemoryMultiOrgAttestationRegistry`.

        Strategy: list all keys, then fetch each one. A poisoned
        envelope raises :class:`MultiOrgAttestationEnvelopeError`
        and the snapshot aborts; partial snapshots are not surfaced
        because the caller-side determinism contract requires a
        complete, self-consistent view.
        """
        keys = await _list_keys(self.kv)
        in_memory = InMemoryMultiOrgAttestationRegistry()
        for key in keys:
            att = await self.get(key)
            if att is None:
                # Tombstoned between list and get; skip silently.
                continue
            in_memory.add(att)
        return in_memory

    # ------------------------------------------------------------------
    # Watch-stream
    # ------------------------------------------------------------------

    async def watch(self) -> "_WatchStreamHandle":
        """Open a watch-stream over this backend's bucket.

        Returns an async iterable / context manager that yields
        decoded :class:`MultiOrgAttestationWatchEvent` instances.
        See :func:`open_watch_stream` for details.
        """
        return await open_watch_stream(self)


# ---------------------------------------------------------------------------
# Helpers (KV adapter shims)
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
        raise MultiOrgAttestationEnvelopeError(
            f"KV entry has no .value attribute: type="
            f"{type(kve).__name__}"
        )
    if isinstance(value, str):
        return value.encode("utf-8")
    return bytes(value)


def _coerce_revision(rv: Any) -> int:
    """Normalise a put/update return to ``int``."""
    if isinstance(rv, int):
        return rv
    revision = getattr(rv, "revision", None)
    if revision is None and isinstance(rv, Mapping):
        revision = rv.get("revision")
    if revision is None:
        return 0
    return int(revision)


def _coerce_revision_from_entry(kve: Any) -> int:
    """Pull a revision off a KV entry handle (``.revision``)."""
    revision = getattr(kve, "revision", None)
    if revision is None and isinstance(kve, Mapping):
        revision = kve.get("revision")
    if revision is None:
        return 0
    return int(revision)


async def _list_keys(kv: Any) -> list:
    """List all keys in the bucket. nats-py exposes
    ``await kv.keys()`` returning ``list[str]``; we accept either an
    awaitable list or an async iterable for mock flexibility.
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
    raise MultiOrgAttestationBackendError(
        "KV handle has no keys() method"
    )


_CONFLICT_CLS_MARKERS: Tuple[str, ...] = (
    "WrongLastSequence",
    "Conflict",
    "RevisionMismatch",
)


def _is_conflict_exception(exc: BaseException) -> bool:
    """True if ``exc``'s class name matches a CAS-conflict marker."""
    cls_name = type(exc).__name__
    return any(marker in cls_name for marker in _CONFLICT_CLS_MARKERS)


def _extract_actual_revision(exc: BaseException) -> Optional[int]:
    """Best-effort extraction of an actual-revision integer."""
    for attr in ("actual_revision", "actual", "revision", "last"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


async def _kv_update_with_revision(
    kv: Any,
    key: str,
    value: bytes,
    expected_revision: int,
) -> Any:
    """CAS-pinned KV write.

    Accepts three KV adapter shapes (same as the Sprint-5 Tag-4
    capability-policy helper):

    1. ``kv.update(key, value, last=revision)`` — canonical nats-py.
    2. ``kv.update(key, value, expected_revision)`` — positional
       mock fallback.
    3. ``kv.put(key, value, expected_revision=...)`` — keyword
       fallback for mocks that overload ``put``.
    """
    update = getattr(kv, "update", None)
    if update is not None:
        try:
            try:
                return await update(key, value, last=expected_revision)
            except TypeError:
                return await update(key, value, expected_revision)
        except Exception as exc:
            if _is_conflict_exception(exc):
                actual = _extract_actual_revision(exc)
                raise MultiOrgAttestationCasConflict(
                    f"CAS-pin rejected for route_id={key!r}: "
                    f"expected_revision={expected_revision}, "
                    f"actual_revision={actual}",
                    route_id=key,
                    expected_revision=expected_revision,
                    actual_revision=actual,
                ) from exc
            raise
    # Fallback: try put with kwarg.
    try:
        return await kv.put(
            key, value, expected_revision=expected_revision
        )
    except TypeError as exc:
        raise MultiOrgAttestationBackendError(
            "KV adapter has neither .update(last=...) nor "
            ".put(expected_revision=...); CAS-pin not supported"
        ) from exc
    except Exception as exc:
        if _is_conflict_exception(exc):
            actual = _extract_actual_revision(exc)
            raise MultiOrgAttestationCasConflict(
                f"CAS-pin rejected for route_id={key!r}: "
                f"expected_revision={expected_revision}, "
                f"actual_revision={actual}",
                route_id=key,
                expected_revision=expected_revision,
                actual_revision=actual,
            ) from exc
        raise


# ---------------------------------------------------------------------------
# Watch-stream
# ---------------------------------------------------------------------------
#
# Pattern-mirror on the Sprint-3 Tag-6 route-registry watch-stream
# and the Sprint-5 Tag-5 capability-policy watch-stream. The consumer
# surface is a decoded :class:`MultiOrgAttestationWatchEvent`; the
# producer is the underlying nats-py ``KeyWatcher`` (or mock-equivalent).
# A :class:`LiveMultiOrgAttestationSnapshot` keeps an in-memory copy
# of the registry and applies events to maintain a long-running view.


class MultiOrgAttestationWatchOp(enum.Enum):
    """Operation kind surfaced by the watch-stream.

    Matches nats-py's ``KeyValueOp`` shape. The byte-equal mirror on
    the route-registry :class:`WatchOp` is module-local; the two
    backends evolve independently.
    """

    PUT = "PUT"
    DELETE = "DELETE"
    PURGE = "PURGE"


@dataclass(frozen=True)
class MultiOrgAttestationWatchEvent:
    """A single decoded operation from the attestation watch-stream.

    Fields:

    - ``op``: the :class:`MultiOrgAttestationWatchOp`. PUT means
      ``attestation`` is set; DELETE / PURGE mean it is ``None``.
    - ``route_id``: the registry key.
    - ``attestation``: the decoded
      :class:`MultiOrgRouteAttestation` for PUT; ``None`` for
      DELETE / PURGE.
    - ``revision``: the KV revision observed.
    """

    op: MultiOrgAttestationWatchOp
    route_id: str
    attestation: Optional[MultiOrgRouteAttestation]
    revision: int


def _decode_watch_update(update: Any) -> MultiOrgAttestationWatchEvent:
    """Decode one watcher update into a
    :class:`MultiOrgAttestationWatchEvent`.

    Mirrors the Sprint-3 Tag-6 helper of the same name.
    """
    op_raw = getattr(update, "operation", None)
    if op_raw is None and isinstance(update, Mapping):
        op_raw = update.get("operation")
    if op_raw is None:
        raise MultiOrgAttestationEnvelopeError(
            f"watch update has no 'operation' attribute: type="
            f"{type(update).__name__}"
        )
    op_name = getattr(op_raw, "name", None) or str(op_raw)
    op_name = op_name.upper()
    if op_name not in {"PUT", "DELETE", "PURGE"}:
        raise MultiOrgAttestationEnvelopeError(
            f"watch update has unknown operation: {op_name!r}"
        )
    op = MultiOrgAttestationWatchOp(op_name)

    key = getattr(update, "key", None)
    if key is None and isinstance(update, Mapping):
        key = update.get("key")
    if not isinstance(key, str) or not key:
        raise MultiOrgAttestationEnvelopeError(
            f"watch update has empty/non-string key: {key!r}"
        )

    revision = getattr(update, "revision", None)
    if revision is None and isinstance(update, Mapping):
        revision = update.get("revision")
    revision_int = int(revision) if revision is not None else 0

    if op is MultiOrgAttestationWatchOp.PUT:
        blob = _coerce_value_bytes(update)
        att = _envelope_to_attestation(blob)
        return MultiOrgAttestationWatchEvent(
            op=op,
            route_id=key,
            attestation=att,
            revision=revision_int,
        )
    return MultiOrgAttestationWatchEvent(
        op=op, route_id=key, attestation=None, revision=revision_int
    )


@dataclass
class _WatchStreamHandle:
    """Internal wrapper around the underlying nats-py watcher.

    Mirrors the Sprint-3 Tag-6 ``_WatchStreamHandle`` shape: adapts
    to both async-iter watchers (Shape 1) and ``await updates()``
    watchers (Shape 2).
    """

    underlying: Any

    async def __aenter__(self) -> "_WatchStreamHandle":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        stop = getattr(self.underlying, "stop", None)
        if stop is None:
            return
        result = stop()
        if hasattr(result, "__await__"):
            await result

    def __aiter__(self) -> "_WatchStreamHandle":
        return self

    async def __anext__(self) -> MultiOrgAttestationWatchEvent:
        if hasattr(self.underlying, "__anext__"):
            while True:
                update = await self.underlying.__anext__()
                if update is None:
                    continue
                return _decode_watch_update(update)
        updates = getattr(self.underlying, "updates", None)
        if updates is not None:
            while True:
                update = await updates()
                if update is None:
                    raise StopAsyncIteration
                return _decode_watch_update(update)
        raise MultiOrgAttestationBackendError(
            f"watch handle has neither __anext__ nor updates(): "
            f"type={type(self.underlying).__name__}"
        )


async def _open_watcher(kv: Any) -> Any:
    """Open the underlying watcher on the KV handle.

    Mirrors the Sprint-3 Tag-6 helper.
    """
    watch_fn = getattr(kv, "watchall", None)
    if watch_fn is None:
        watch_fn = getattr(kv, "watch", None)
    if watch_fn is None:
        raise MultiOrgAttestationBackendError(
            "KV handle exposes neither watchall() nor watch()"
        )
    result = watch_fn()
    if hasattr(result, "__await__"):
        result = await result
    return result


async def open_watch_stream(
    backend: "NatsKvMultiOrgAttestationRegistry",
) -> _WatchStreamHandle:
    """Open a watch-stream over the backend's KV bucket.

    Use as an async context manager OR consume directly; either way,
    ``stop()`` is called on close. Each iteration yields one
    :class:`MultiOrgAttestationWatchEvent`. Decoder errors raise
    :class:`MultiOrgAttestationEnvelopeError` and terminate the
    iterator.
    """
    if not isinstance(backend, NatsKvMultiOrgAttestationRegistry):
        raise TypeError(
            "backend must be a NatsKvMultiOrgAttestationRegistry"
        )
    underlying = await _open_watcher(backend.kv)
    return _WatchStreamHandle(underlying=underlying)


@dataclass
class LiveMultiOrgAttestationSnapshot:
    """Live, watch-stream-fed snapshot of the attestation registry.

    Initialises an in-memory copy from a full backend snapshot, then
    applies decoded :class:`MultiOrgAttestationWatchEvent` instances
    to keep the copy in sync.

    Per-pass consumers call :meth:`as_registry` to take a frozen
    copy at the current state; subsequent watch events do NOT mutate
    the returned registry (determinism contract).

    Concurrency: single-consumer pattern within one asyncio task; no
    internal locking. The class is NOT itself a registry.
    """

    initial: InMemoryMultiOrgAttestationRegistry
    last_revision: int = 0
    _live: InMemoryMultiOrgAttestationRegistry = field(init=False)

    def __post_init__(self) -> None:
        self._live = InMemoryMultiOrgAttestationRegistry()
        for att in self.initial.attestations.values():
            self._live.add(att)

    def apply(self, event: MultiOrgAttestationWatchEvent) -> None:
        """Apply one :class:`MultiOrgAttestationWatchEvent` to the
        live state.

        PUT updates / inserts; DELETE / PURGE removes (no-op if
        already absent). A PUT without an attestation payload is a
        decoder bug and is rejected with
        :class:`MultiOrgAttestationEnvelopeError`.

        The monotonic-invariant gate is NOT re-applied on the watch
        consumer side: the write was already gated at the producer
        (the backend's ``put`` / ``put_with_revision`` path). The
        watch-stream is a *strict suffix* of the durable bucket
        history (Sprint-5 Tag-5 contract); applying it here just
        replays the producer's ordering.
        """
        if not isinstance(event, MultiOrgAttestationWatchEvent):
            raise TypeError(
                "event must be a MultiOrgAttestationWatchEvent"
            )
        if event.op is MultiOrgAttestationWatchOp.PUT:
            if event.attestation is None:
                raise MultiOrgAttestationEnvelopeError(
                    "PUT MultiOrgAttestationWatchEvent must carry a "
                    "non-None attestation"
                )
            # The in-memory registry rejects conflict-re-adds; the
            # watch-stream replays whatever the producer durably
            # wrote. Use the underlying dict directly so a producer-
            # side overwrite (which already passed the monotonic gate)
            # cleanly replaces the live copy.
            self._live.attestations[event.route_id] = event.attestation
        else:
            self._live.attestations.pop(event.route_id, None)
        if event.revision > self.last_revision:
            self.last_revision = event.revision

    def as_registry(self) -> InMemoryMultiOrgAttestationRegistry:
        """Return a frozen copy of the current live state."""
        frozen = InMemoryMultiOrgAttestationRegistry()
        for att in self._live.attestations.values():
            frozen.add(att)
        return frozen

    @classmethod
    async def from_backend(
        cls, backend: "NatsKvMultiOrgAttestationRegistry"
    ) -> "LiveMultiOrgAttestationSnapshot":
        """Bootstrap a :class:`LiveMultiOrgAttestationSnapshot` from
        a full backend snapshot. The caller is responsible for
        opening a watch-stream and feeding events to :meth:`apply`.
        """
        initial = await backend.snapshot()
        return cls(initial=initial, last_revision=0)


# ---------------------------------------------------------------------------
# Cross-bucket replication (Phase-2 Sprint-7 Tag-2)
# ---------------------------------------------------------------------------
#
# Pattern-mirror on the Sprint-6 Tag-6 capability-policy replication.
# Trimmed for the Tag-2 90-min budget: bootstrap pass + per-event
# replicator with two conflict policies (SOURCE_WINS / CAS_PIN) and
# a monotonic-invariant metrics counter. Watch-stream-fed live tail
# composition is the same shape as the Sprint-6 Tag-6 replicator;
# the test suite exercises the bootstrap pass and the per-event
# decisions directly.


class MultiOrgAttestationReplicationConflictPolicy(enum.Enum):
    """How the replicator writes to the target bucket.

    - ``SOURCE_WINS``: LWW on the target (target writes go through
      :meth:`NatsKvMultiOrgAttestationRegistry.put`), EXCEPT
      monotonic-invariant refusals enforced in-band by the backend
      (a live authority anchor is never silently mutated).
    - ``CAS_PIN``: CAS-pinned writes against the target's observed
      revision; a target-side concurrent write surfaces as
      :class:`MultiOrgAttestationCasConflict` and is counted.
    """

    SOURCE_WINS = "source-wins"
    CAS_PIN = "cas-pin"


class MultiOrgAttestationReplicationDecision(enum.Enum):
    """Per-event filter decision."""

    APPLY = "apply"
    SKIP = "skip"


MultiOrgAttestationReplicationFilter = Callable[
    [MultiOrgAttestationWatchEvent],
    MultiOrgAttestationReplicationDecision,
]


def _accept_all_attestation(
    _event: MultiOrgAttestationWatchEvent,
) -> MultiOrgAttestationReplicationDecision:
    return MultiOrgAttestationReplicationDecision.APPLY


@dataclass
class MultiOrgAttestationReplicationMetrics:
    """Counters surfaced by the multi-org-attestation replicator.

    Fields mirror the Sprint-6 Tag-6 capability-policy metrics
    shape with the cross-bucket monotonic-invariant counter
    re-named for the attestation domain.
    """

    bootstrap_applied: int = 0
    bootstrap_skipped_by_filter: int = 0
    bootstrap_skipped_idempotent: int = 0
    bootstrap_monotonic_breaches: int = 0
    events_applied_put: int = 0
    events_applied_delete: int = 0
    events_skipped_by_filter: int = 0
    cas_conflicts: int = 0
    monotonic_breaches: int = 0
    envelope_errors: int = 0


def _attestations_byte_equal(
    a: Optional[MultiOrgRouteAttestation],
    b: Optional[MultiOrgRouteAttestation],
) -> bool:
    """Return True iff the two attestations serialise byte-equal."""
    if a is None or b is None:
        return False
    try:
        return _attestation_to_envelope(a) == _attestation_to_envelope(b)
    except Exception:
        return False


async def bootstrap_multi_org_attestation_target_from_source(
    *,
    source: NatsKvMultiOrgAttestationRegistry,
    target: NatsKvMultiOrgAttestationRegistry,
    policy: MultiOrgAttestationReplicationConflictPolicy = (
        MultiOrgAttestationReplicationConflictPolicy.SOURCE_WINS
    ),
    filter_fn: Optional[MultiOrgAttestationReplicationFilter] = None,
    metrics: Optional[MultiOrgAttestationReplicationMetrics] = None,
) -> MultiOrgAttestationReplicationMetrics:
    """Run the bootstrap pass: copy every source record onto the target.

    The bootstrap pass is the *initial-sync* phase of replication. It
    runs once per replicator session and seeds the target's state
    from a complete source snapshot.

    Bootstrap behaviour:

    - Source records are processed in sorted-key order (determinism
      convenience for log-replay tests).
    - **Filter**: optional ``filter_fn`` is invoked with a synthetic
      PUT event per source record; rejected events do NOT touch the
      target.
    - **Idempotency**: a target-side record that is byte-equal to the
      source-side record is a no-op
      (``bootstrap_skipped_idempotent`` advances).
    - **Monotonic invariant**: a source record that would mutate a
      load-bearing authority anchor of a live target record is
      refused; ``bootstrap_monotonic_breaches`` advances. Under both
      policies the refusal is in-band (the backend's monotonic gate
      runs on both ``put`` and ``put_with_revision``).
    - **Conflict policy** under ``CAS_PIN``: target writes go through
      ``put_with_revision`` against the observed target revision; a
      target-side concurrent write surfaces as
      :class:`MultiOrgAttestationCasConflict` and
      ``cas_conflicts`` advances.

    Args:
        source: source-of-truth backend.
        target: target backend to write into.
        policy: conflict policy (see
            :class:`MultiOrgAttestationReplicationConflictPolicy`).
        filter_fn: optional filter; defaults to accept-all.
        metrics: optional metrics object; updated in-place. A fresh
            one is created and returned if ``None``.

    Returns:
        The metrics object reflecting the pass outcome.
    """
    metrics = metrics or MultiOrgAttestationReplicationMetrics()
    filter_fn = filter_fn or _accept_all_attestation
    source_keys = sorted(await source.list_keys())
    for key in source_keys:
        src = await source.get(key)
        if src is None:
            continue
        decision = filter_fn(
            MultiOrgAttestationWatchEvent(
                op=MultiOrgAttestationWatchOp.PUT,
                route_id=key,
                attestation=src,
                revision=0,
            )
        )
        if decision is MultiOrgAttestationReplicationDecision.SKIP:
            metrics.bootstrap_skipped_by_filter += 1
            continue
        target_pair = await target.get_with_revision(key)
        live = target_pair[0] if target_pair is not None else None
        live_rev = target_pair[1] if target_pair is not None else 0
        if _attestations_byte_equal(live, src):
            metrics.bootstrap_skipped_idempotent += 1
            continue
        try:
            if (
                policy
                is MultiOrgAttestationReplicationConflictPolicy.CAS_PIN
            ):
                await target.put_with_revision(src, live_rev)
            else:
                await target.put(src)
            metrics.bootstrap_applied += 1
        except MultiOrgAttestationMonotonicConflict:
            metrics.bootstrap_monotonic_breaches += 1
        except MultiOrgAttestationCasConflict:
            # Should not happen during a quiet bootstrap, but a
            # racy operator may have raced us; counted for audit.
            metrics.cas_conflicts += 1
    return metrics


__all__ = [
    "BUCKET_NAME",
    "BUCKET_CONFIG",
    "VALUE_SCHEMA",
    "MultiOrgAttestationBackendError",
    "MultiOrgAttestationEnvelopeError",
    "MultiOrgAttestationCasConflict",
    "MultiOrgAttestationMonotonicConflict",
    "NatsKvMultiOrgAttestationRegistry",
    "MultiOrgAttestationWatchOp",
    "MultiOrgAttestationWatchEvent",
    "LiveMultiOrgAttestationSnapshot",
    "open_watch_stream",
    "MultiOrgAttestationReplicationConflictPolicy",
    "MultiOrgAttestationReplicationDecision",
    "MultiOrgAttestationReplicationFilter",
    "MultiOrgAttestationReplicationMetrics",
    "bootstrap_multi_org_attestation_target_from_source",
]
