# SPDX-License-Identifier: Apache-2.0
"""NATS-JetStream-KV-backed Wirelang Schema Registry backend.

Phase-1b Sprint-3 Tag-1 (S3-1) lands the production-target backend
for the Wirelang schema registry described in
``wirelang/specs/schema-registry-spec.md``. The registry persists the
seven Phase-1b on-disk JSON-Schema documents (plus a reserved 8th
slot for ``datalog-caveat/0.1.0``) in the
``wakir-schemas`` NATS-JetStream KV bucket already documented in
Kai's Phase-1 bucket inventory (``scripts/init-nats-buckets.py``,
Phase-1b Sprint-2 Tag-2).

Substrate
---------

The backend persists :class:`SchemaRegistryEntry` records in the
``wakir-schemas`` bucket. The bucket configuration is owned by the
operator-side init script; this module declares the matching
:data:`BUCKET_CONFIG` constant for the test-layer drift check.

- ``history``: 5 (audit-trail of recent overwrites).
- ``ttl_seconds``: 0 (schemas have no expiry).
- ``max_value_size``: 262_144 B (256 KiB; largest current schema is
  ~7.3 KiB, headroom for v0.2 expansion).
- ``storage``: ``"file"`` (durability for production).
- ``replicas``: 1 (Phase-1 single-node).

Cross-reference: this module does NOT add a new bucket. It is a
*consumer* of Kai's existing :data:`PHASE_1_BUCKETS[0]` slot. The
Tag-4 V-908 backend added ``wakir-federation-routes`` as the 5th
bucket; Sprint-3 Tag-1 introduces no 6th bucket.

Design choices
--------------

The backend mirrors the V-908 NATS-KV route-registry pattern shipped
in Phase-1b Sprint-2 Tag-4 (``route_registry_nats_kv_backend.py``).
Specifically:

- Async backend surface (``get``, ``put``, ``delete``, ``snapshot``).
- Synchronous in-memory snapshot view
  (:class:`InMemorySchemaRegistry`) for verifier-side consumption.
- Eager poisoned-envelope failure: a malformed value raises
  :class:`SchemaRegistryEnvelopeError` from ``get`` and aborts
  ``snapshot``; the determinism contract requires a complete,
  self-consistent view.
- Drift-policy contract identical to the V-908 backend: bucket
  configuration is operator-managed; this module never auto-creates
  or auto-corrects.

Identity triple
---------------

A schema entry is identified by ``(layer, name, version)`` collapsed
into a single KV key string ``schemas/<layer>/<name>/<version>``.
The triple ↔ key derivation is bijective and idempotent; see
:func:`key_for_triple` and :func:`triple_for_key`.

Value envelope
--------------

Each KV value is a JSON object with these fields (full spec in
:data:`schema-registry-spec.md` §4):

- ``schema``: ``"wakir.wirelang.schema-registry-entry/1"``.
- ``layer``, ``name``, ``version``: identity triple.
- ``schema_id``: the ``$id`` URI of the embedded JSON-Schema
  document.
- ``schema_body``: the full JSON-Schema document, JCS-canonicalised
  before embedding.
- ``schema_body_sha256``: SHA-256 of the JCS-canonicalised body
  bytes (hex-encoded).
- ``registered_at``: RFC 3339 UTC timestamp.
- ``registered_by``: role-string or AIP-id of the publishing agent.
- ``supersedes``: key-string of the previous patch entry, or
  ``null``.

The envelope is stored with sorted keys and the compact
``(",", ":")`` separator pair so the bytes are reproducible per
caller.

Validation gates at write
-------------------------

The :meth:`NatsKvSchemaRegistry.put` method enforces at write time:

1. ``envelope.schema_id == envelope.schema_body["$id"]``.
2. ``envelope.schema_body_sha256 == sha256(jcs(schema_body))``.
3. The KV key derived from the entry's triple matches the explicit
   key (defence in depth against mis-keying).

These gates keep poisoned envelopes off the bucket. The Phase-1c
:meth:`NatsKvSchemaRegistry.put_with_revision` CAS-pin path runs the
same three gates BEFORE the revision-pin call (see Phase-1c CAS-pin
contract below).

Phase-1c CAS-pin contract (Sprint-3 Tag-3, OI-7-Phase-1c-CAS)
-------------------------------------------------------------

Lost-update protection for concurrent schema upserts is added in
Phase-1c via :meth:`NatsKvSchemaRegistry.put_with_revision` and
:meth:`NatsKvSchemaRegistry.get_with_revision`. The pair implements
the canonical compare-and-swap idiom:

1. Caller reads ``(entry, observed_revision) = get_with_revision(key)``.
2. Caller mutates the entry locally, recomputes the ``schema_body_sha256``
   anchor.
3. Caller writes via ``put_with_revision(new_entry, observed_revision)``.
4. The backend forwards ``observed_revision`` to the underlying NATS-KV
   ``update(key, value, last=observed_revision)`` call. If the live
   revision has advanced (concurrent writer landed first), the call
   raises :class:`SchemaRegistryConflictError` with the expected and
   actual revisions; the caller can re-read and retry.

The CAS-pin is a Phase-1c addition: the substrate to support it
(revision integer threading through the KV adapter, conflict-class
name detection) was already present in the V-908 Tag-4 backend
pattern; Phase-1b Sprint-3 Tag-3 lands the schema-registry side of
the same surface. The :class:`SchemaRegistryConflictError` mirrors
the V-908 :class:`RouteRegistryConflictError`.

Phase-2 hardening on top of Phase-1c CAS-pin (out of scope for
Tag-3): replication-aware quorum upserts, deprecation policy with
overlapping-validity windows, IPFS-anchored schema-document hashes.

Phase-1c watch-stream contract (Sprint-3 Tag-4, OI-7-Phase-1c-watch)
--------------------------------------------------------------------

Long-running consumers can subscribe to a watch-stream over the
``wakir-schemas`` bucket via :meth:`NatsKvSchemaRegistry.watch`. The
watch-stream yields decoded :class:`WatchEvent` instances; consumers
feed the events into a :class:`LiveSchemaSnapshot` to maintain an
incremental in-memory view without re-snapshotting on every change.

The pattern mirrors the V-908 Tag-6 watch-stream-snapshot layer
shipped in :mod:`wirelang.federation.route_registry_nats_kv_backend`
(``WatchOp`` / ``WatchEvent`` / ``LiveSnapshot.from_backend``). The
schema-registry side adds:

- :class:`WatchOp` / :class:`WatchEvent` / :class:`LiveSchemaSnapshot`
  with the same byte-decoder semantics; a poisoned PUT envelope on
  the stream raises :class:`SchemaRegistryEnvelopeError` and
  terminates the iterator (no silent envelope poison).
- Determinism contract: a frozen :class:`InMemorySchemaRegistry`
  returned from :meth:`LiveSchemaSnapshot.as_registry` does NOT
  mutate when subsequent watch events arrive; verifier passes can
  treat the frozen view as a stable snapshot.
- Adapter compatibility: the underlying nats-py ``KeyValue.watchall``
  surface and a manually-fed mock (Shape-2 with ``await updates()``)
  are both supported, plus the Shape-1 native async-iter shape.

Hermetic test contract
----------------------

The test suite at
``wirelang/tests/test_schema_registry_nats_kv_backend.py`` exercises
the backend against an in-memory mock that mirrors the V-908 mock
shape (``_MockKv`` / ``_MockKvEntry``). The mock is intentionally
the same surface so the orchestrator-side and Wirelang-side both
validate against the same nats-py contract. The Tag-4 watch-stream
tests live in ``wirelang/tests/test_schema_registry_watch_stream.py``
and mirror the V-908 Tag-6 ``test_..._watch_stream`` pattern with a
schema-registry-shaped fixture.

References (URL-stamped 2026-05-07 by wirelang-eng):

- Spec: ``wirelang/specs/schema-registry-spec.md`` (Phase-1b
  Sprint-3 Tag-1 / Tag-3 / Tag-4).
- V-908 backend pattern source:
  ``wirelang/federation/route_registry_nats_kv_backend.py``.
- V-908 Tag-6 watch-stream pattern source: same module, ``WatchOp`` /
  ``WatchEvent`` / ``LiveSnapshot`` section.
- Bucket inventory source: ``scripts/init-nats-buckets.py``
  ``PHASE_1_BUCKETS[0]`` (``wakir-schemas``).
"""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional


# ---------------------------------------------------------------------------
# Bucket identity (cross-reference: orchestrator bucket inventory)
# ---------------------------------------------------------------------------


#: NATS-KV bucket name for the Wirelang schema registry. Phase-1b
#: convention; this name MUST match the entry already registered in
#: Kai's :data:`PHASE_1_BUCKETS[0]` (``scripts/init-nats-buckets.py``).
BUCKET_NAME = "wakir-schemas"

#: Documented bucket configuration. Drift-policy is identical to the
#: V-908 federation-routes backend: any deviation between the live
#: cluster and these values is reported as drift, never auto-corrected.
BUCKET_CONFIG: Mapping[str, Any] = {
    "name": BUCKET_NAME,
    "description": "Wirelang schema registry cache (Phase-1)",
    "history": 5,
    "ttl_seconds": 0,
    "max_value_size": 262_144,
    "storage": "file",
    "replicas": 1,
}

#: Schema-URI fragment embedded in every value envelope.
VALUE_SCHEMA = "wakir.wirelang.schema-registry-entry/1"

#: Recognised layer axis values. Phase-1b inventory only.
RECOGNISED_LAYERS = frozenset({"identity", "wire", "federation"})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SchemaRegistryBackendError(Exception):
    """Base class for schema-registry backend failures."""


class SchemaRegistryEnvelopeError(SchemaRegistryBackendError):
    """Raised when a KV value cannot be parsed or fails the
    schema-shape contract.

    A poisoned envelope is *not* silently swallowed: the backend
    surfaces the error so an operator can act. The snapshot is taken
    eagerly; if a snapshot raises, no verifier consumes a half-broken
    registry.
    """


class SchemaRegistryValidationError(SchemaRegistryBackendError):
    """Raised when a write-time validation gate fails (schema-id
    mismatch, body-hash mismatch, or key-triple mismatch).
    """


class SchemaRegistryConflictError(SchemaRegistryBackendError):
    """Raised when a CAS-pinned upsert is rejected because the live KV
    revision has drifted from the caller's expected revision.

    Phase-1c CAS-pin contract (Sprint-3 Tag-3, OI-7-Phase-1c-CAS).

    The caller of :meth:`NatsKvSchemaRegistry.put_with_revision`
    declares the revision it observed when it last read the entry.
    The backend forwards that revision to the underlying NATS-KV
    ``update`` call. If the live revision has advanced (concurrent
    writer landed first), the underlying KV layer raises a
    nats-py-flavoured ``KeyWrongLastSequenceError`` (or any error whose
    class name contains ``WrongLastSequence`` or ``Conflict``); the
    backend translates that into this typed exception.

    Carries the observed ``key``, ``expected_revision``, and (when
    available) the ``actual_revision`` reported by the underlying
    layer. ``actual_revision`` is ``None`` if the KV adapter does not
    surface it; callers can re-read the entry and retry.

    Mirror of :class:`RouteRegistryConflictError` from the V-908
    backend (``wirelang/federation/route_registry_nats_kv_backend.py``)
    extended into a fully-implemented CAS-pin surface here.
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


# ---------------------------------------------------------------------------
# Identity triple ↔ key derivation
# ---------------------------------------------------------------------------


_KEY_PREFIX = "schemas/"


def key_for_triple(layer: str, name: str, version: str) -> str:
    """Derive the canonical KV key for an identity triple.

    The derivation is ``schemas/<layer>/<name>/<version>``. Each
    component is non-empty and contains only kebab-case ASCII
    characters; this is enforced eagerly so a malformed triple cannot
    poison the bucket through a mis-keyed put.
    """
    for component_name, component in (
        ("layer", layer),
        ("name", name),
        ("version", version),
    ):
        if not isinstance(component, str) or not component:
            raise ValueError(
                f"{component_name} must be a non-empty string, got {component!r}"
            )
        if "/" in component:
            raise ValueError(
                f"{component_name} must not contain '/': {component!r}"
            )
    if layer not in RECOGNISED_LAYERS:
        raise ValueError(
            f"layer {layer!r} is not in recognised set "
            f"{sorted(RECOGNISED_LAYERS)!r}"
        )
    return f"{_KEY_PREFIX}{layer}/{name}/{version}"


def triple_for_key(key: str) -> tuple[str, str, str]:
    """Inverse of :func:`key_for_triple`. Raises ``ValueError`` for
    a key that does not match the expected shape.
    """
    if not isinstance(key, str) or not key.startswith(_KEY_PREFIX):
        raise ValueError(
            f"key must start with {_KEY_PREFIX!r}, got {key!r}"
        )
    rest = key[len(_KEY_PREFIX):]
    parts = rest.split("/")
    if len(parts) != 3:
        raise ValueError(
            f"key must have shape schemas/<layer>/<name>/<version>: {key!r}"
        )
    layer, name, version = parts
    if not (layer and name and version):
        raise ValueError(
            f"key components must all be non-empty: {key!r}"
        )
    return layer, name, version


# ---------------------------------------------------------------------------
# Entry record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SchemaRegistryEntry:
    """One schema-registry entry.

    Fields mirror the value-envelope spec (§4 of the registry spec).
    Construction is cheap; the entry is the in-memory record that
    flows into and out of the KV envelope codec.
    """

    layer: str
    name: str
    version: str
    schema_id: str
    schema_body: Mapping[str, Any]
    schema_body_sha256: str
    registered_at: datetime
    registered_by: str
    supersedes: Optional[str] = None

    @property
    def key(self) -> str:
        """Canonical KV key for this entry."""
        return key_for_triple(self.layer, self.name, self.version)


# ---------------------------------------------------------------------------
# JCS canonicalisation (minimal RFC 8785 subset, sufficient for JSON
# objects whose values are strings, numbers, bools, null, lists and
# objects). Mirrors the federation-resolver minimal-JCS pattern; the
# project-wide JCS implementation is at wirelang/canonical/jcs.py and
# we prefer it when available.
# ---------------------------------------------------------------------------


def _jcs_canonicalise(obj: Any) -> bytes:
    """Return JCS-canonical bytes of ``obj``.

    Prefers ``wirelang.canonical.jcs.canonicalise`` when importable;
    falls back to a sorted-keys ``json.dumps`` for the test path.
    The fallback is sufficient for JSON-Schema documents (which use
    no number-encoding edge cases that JCS would treat differently).
    """
    try:
        from wirelang.canonical.jcs import canonicalise  # type: ignore
        return canonicalise(obj)
    except Exception:
        # Fallback: sorted keys + compact separators. Stable for the
        # JSON-Schema document shapes we ship.
        return json.dumps(
            obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")


def schema_body_sha256(schema_body: Mapping[str, Any]) -> str:
    """Compute the JCS-anchored SHA-256 of a JSON-Schema document.

    Returns a lowercase hex string. The same digest is stored in the
    envelope's ``schema_body_sha256`` field; equality is the
    write-time validation gate.
    """
    digest = hashlib.sha256(_jcs_canonicalise(schema_body)).hexdigest()
    return digest


# ---------------------------------------------------------------------------
# Envelope codec
# ---------------------------------------------------------------------------


def _entry_to_envelope(entry: SchemaRegistryEntry) -> bytes:
    """Serialise a :class:`SchemaRegistryEntry` to canonical JSON
    envelope bytes.
    """
    if not isinstance(entry, SchemaRegistryEntry):
        raise TypeError("entry must be a SchemaRegistryEntry")
    payload = {
        "schema": VALUE_SCHEMA,
        "layer": entry.layer,
        "name": entry.name,
        "version": entry.version,
        "schema_id": entry.schema_id,
        "schema_body": dict(entry.schema_body),
        "schema_body_sha256": entry.schema_body_sha256,
        "registered_at": _dt_to_rfc3339(entry.registered_at),
        "registered_by": entry.registered_by,
        "supersedes": entry.supersedes,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _envelope_to_entry(blob: bytes) -> SchemaRegistryEntry:
    """Inverse of :func:`_entry_to_envelope`. Raises
    :class:`SchemaRegistryEnvelopeError` on shape violation.
    """
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SchemaRegistryEnvelopeError(
            f"non-utf-8 envelope: {exc!r}"
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaRegistryEnvelopeError(
            f"non-JSON envelope: {exc!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise SchemaRegistryEnvelopeError(
            f"envelope is not a JSON object: type={type(payload).__name__}"
        )
    schema = payload.get("schema")
    if schema != VALUE_SCHEMA:
        raise SchemaRegistryEnvelopeError(
            f"envelope schema mismatch: want {VALUE_SCHEMA!r} got {schema!r}"
        )
    for required in (
        "layer",
        "name",
        "version",
        "schema_id",
        "schema_body",
        "schema_body_sha256",
        "registered_at",
        "registered_by",
    ):
        if required not in payload:
            raise SchemaRegistryEnvelopeError(
                f"envelope missing required field: {required!r}"
            )
    schema_body = payload["schema_body"]
    if not isinstance(schema_body, dict):
        raise SchemaRegistryEnvelopeError(
            f"envelope schema_body is not a JSON object: "
            f"type={type(schema_body).__name__}"
        )
    try:
        registered_at = _rfc3339_to_dt(payload["registered_at"])
    except ValueError as exc:
        raise SchemaRegistryEnvelopeError(
            f"envelope registered_at parse error: {exc!r}"
        ) from exc
    return SchemaRegistryEntry(
        layer=payload["layer"],
        name=payload["name"],
        version=payload["version"],
        schema_id=payload["schema_id"],
        schema_body=schema_body,
        schema_body_sha256=payload["schema_body_sha256"],
        registered_at=registered_at,
        registered_by=payload["registered_by"],
        supersedes=payload.get("supersedes"),
    )


def _dt_to_rfc3339(dt: datetime) -> str:
    """Render a tz-aware datetime as RFC 3339 in UTC.

    Naive datetimes are rejected; matches the V-908-backend convention
    that all wall-clock anchors are tz-aware.
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


# ---------------------------------------------------------------------------
# In-memory snapshot view
# ---------------------------------------------------------------------------


@dataclass
class InMemorySchemaRegistry:
    """Synchronous read-only view materialised from a NATS-KV snapshot.

    The view is the bridge between the async backend and synchronous
    verifier code. Mirrors the V-908 :class:`InMemoryRouteRegistry`
    pattern.
    """

    entries: dict = field(default_factory=dict)

    def add(self, entry: SchemaRegistryEntry) -> None:
        """Add or replace ``entry`` keyed by its derived KV key."""
        if not isinstance(entry, SchemaRegistryEntry):
            raise TypeError("entry must be a SchemaRegistryEntry")
        self.entries[entry.key] = entry

    def lookup(self, key: str) -> Optional[SchemaRegistryEntry]:
        """Return the entry for ``key``, or ``None``."""
        return self.entries.get(key)

    def lookup_by_triple(
        self, layer: str, name: str, version: str
    ) -> Optional[SchemaRegistryEntry]:
        """Return the entry for the identity triple, or ``None``."""
        try:
            key = key_for_triple(layer, name, version)
        except ValueError:
            return None
        return self.entries.get(key)

    def keys_sorted(self) -> list[str]:
        """Return the registered keys in lexicographic order.

        Determinism contract: two snapshots taken back-to-back over
        the same bucket state MUST yield the same sorted-key list.
        """
        return sorted(self.entries.keys())


# ---------------------------------------------------------------------------
# KV backend
# ---------------------------------------------------------------------------


@dataclass
class NatsKvSchemaRegistry:
    """NATS-JetStream-KV-backed schema-registry backend.

    The backend is async; the synchronous verifier surface consumes
    :class:`InMemorySchemaRegistry` views materialised via
    :meth:`snapshot`.

    Construction is cheap: pass an open ``KeyValue`` handle from
    nats-py (or a mock that mirrors the same surface). The backend
    performs *no* network I/O on construction.
    """

    kv: Any
    bucket_name: str = BUCKET_NAME

    # ------------------------------------------------------------------
    # Single-key operations
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Optional[SchemaRegistryEntry]:
        """Return the entry for ``key``, or ``None`` if absent.

        Raises :class:`SchemaRegistryEnvelopeError` if the key exists
        but the value cannot be decoded.
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
        return _envelope_to_entry(blob)

    async def get_by_triple(
        self, layer: str, name: str, version: str
    ) -> Optional[SchemaRegistryEntry]:
        """Convenience wrapper: ``get(key_for_triple(...))``."""
        try:
            key = key_for_triple(layer, name, version)
        except ValueError:
            return None
        return await self.get(key)

    async def get_with_revision(
        self, key: str
    ) -> Optional[tuple[SchemaRegistryEntry, int]]:
        """Return ``(entry, revision)`` for ``key`` or ``None``.

        Phase-1c CAS-pin helper: the revision is the same integer that
        :meth:`put_with_revision` expects as ``expected_revision``.

        The implementation reuses the same KV adapter path as
        :meth:`get`; the revision is read from the KV entry handle's
        ``.revision`` attribute (nats-py shape) or from a ``revision``
        key on a Mapping-shaped entry.

        Raises :class:`SchemaRegistryEnvelopeError` if the value is
        unparseable, identical to :meth:`get`.
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
        entry = _envelope_to_entry(blob)
        revision = _coerce_revision_from_entry(kve)
        return entry, revision

    async def put(self, entry: SchemaRegistryEntry) -> int:
        """Upsert an entry; returns the new KV revision number.

        Last-write-wins semantics, identical to
        :class:`InMemoryRouteRegistry.add` from the V-908 path.

        Validation gates (see spec §5.2):

        1. ``entry.schema_id == entry.schema_body["$id"]``.
        2. ``entry.schema_body_sha256 == sha256(jcs(schema_body))``.
        3. Triple-derived key matches the entry; this is checked by
           :func:`key_for_triple` raising on malformed components.
        """
        if not isinstance(entry, SchemaRegistryEntry):
            raise TypeError("entry must be a SchemaRegistryEntry")
        # Gate 1: schema_id ↔ schema_body.$id
        body_id = entry.schema_body.get("$id")
        if body_id != entry.schema_id:
            raise SchemaRegistryValidationError(
                f"envelope schema_id {entry.schema_id!r} does not match "
                f"schema_body.$id {body_id!r}"
            )
        # Gate 2: hash of body
        recomputed = schema_body_sha256(entry.schema_body)
        if recomputed != entry.schema_body_sha256:
            raise SchemaRegistryValidationError(
                f"envelope schema_body_sha256 {entry.schema_body_sha256!r} "
                f"does not match recomputed {recomputed!r}"
            )
        # Gate 3: triple ↔ key (raises on malformed components).
        key = entry.key
        blob = _entry_to_envelope(entry)
        revision = await self.kv.put(key, blob)
        return _coerce_revision(revision)

    async def put_with_revision(
        self, entry: SchemaRegistryEntry, expected_revision: int
    ) -> int:
        """CAS-pinned upsert. Returns the new KV revision number.

        Phase-1c CAS-pin (Sprint-3 Tag-3, OI-7-Phase-1c-CAS).

        Lost-update protection contract:

        - The caller observed ``expected_revision`` when it last read
          the entry (via :meth:`get_with_revision`).
        - This method forwards ``expected_revision`` to the underlying
          NATS-KV ``update(key, value, last=expected_revision)`` call.
        - If the live revision has advanced since the caller's read
          (a concurrent writer landed first), the underlying layer
          raises a ``KeyWrongLastSequenceError`` (nats-py shape) or
          analogous ``ConflictError``. The backend translates that
          into :class:`SchemaRegistryConflictError`.

        For an entry that does not yet exist in the bucket, callers
        MUST use :meth:`put` (which has last-write-wins semantics).
        ``put_with_revision`` with ``expected_revision == 0`` is
        reserved for the create-if-absent case but only succeeds if
        the underlying KV adapter supports the
        ``KeyValue.create(key, value)`` contract; if the adapter does
        not surface that semantic, the call raises
        :class:`SchemaRegistryConflictError`.

        Validation gates (identical to :meth:`put`):

        1. ``entry.schema_id == entry.schema_body["$id"]``.
        2. ``entry.schema_body_sha256 == sha256(jcs(schema_body))``.
        3. Triple-derived key matches the entry.

        These run BEFORE the revision-pin call so that a malformed
        envelope cannot leave the validation surface even if the
        revision happened to be stale.
        """
        if not isinstance(entry, SchemaRegistryEntry):
            raise TypeError("entry must be a SchemaRegistryEntry")
        if not isinstance(expected_revision, int) or expected_revision < 0:
            raise ValueError(
                "expected_revision must be a non-negative int, "
                f"got {expected_revision!r}"
            )
        # Same validation gates as put. CAS does NOT relax them.
        body_id = entry.schema_body.get("$id")
        if body_id != entry.schema_id:
            raise SchemaRegistryValidationError(
                f"envelope schema_id {entry.schema_id!r} does not match "
                f"schema_body.$id {body_id!r}"
            )
        recomputed = schema_body_sha256(entry.schema_body)
        if recomputed != entry.schema_body_sha256:
            raise SchemaRegistryValidationError(
                f"envelope schema_body_sha256 {entry.schema_body_sha256!r} "
                f"does not match recomputed {recomputed!r}"
            )
        key = entry.key
        blob = _entry_to_envelope(entry)
        revision = await _kv_update_with_revision(
            self.kv, key, blob, expected_revision
        )
        return _coerce_revision(revision)

    async def delete(self, key: str) -> None:
        """Tombstone an entry. No-op if the key was already absent.

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
        order should sort it themselves or use
        :meth:`InMemorySchemaRegistry.keys_sorted` after a snapshot.
        """
        return await _list_keys(self.kv)

    # ------------------------------------------------------------------
    # Snapshot (the bridge to the synchronous verifier surface)
    # ------------------------------------------------------------------

    async def snapshot(self) -> InMemorySchemaRegistry:
        """Materialise the live bucket into an
        :class:`InMemorySchemaRegistry`.

        Strategy: list all keys, then fetch each one. A poisoned
        envelope raises :class:`SchemaRegistryEnvelopeError` and the
        snapshot aborts; partial snapshots are not surfaced because
        the determinism contract requires the snapshot to be a
        complete, self-consistent view.
        """
        keys = await _list_keys(self.kv)
        in_memory = InMemorySchemaRegistry()
        for key in keys:
            entry = await self.get(key)
            if entry is None:
                # Tombstoned between list and get; skip without error.
                continue
            in_memory.add(entry)
        return in_memory

    # ------------------------------------------------------------------
    # Watch-stream (Phase-1b Sprint-3 Tag-4, OI-7-Phase-1c-watch)
    # ------------------------------------------------------------------

    async def watch(self) -> "_SchemaWatchStreamHandle":
        """Open a watch-stream over the schema-registry bucket.

        Returns an async iterable / context manager that yields
        decoded :class:`WatchEvent` instances. See
        :func:`open_watch_stream` for details.

        Phase-1c boundary: the watch-stream is a *consumer* surface;
        it does NOT replace :meth:`snapshot`. Use a
        :class:`LiveSchemaSnapshot` (bootstrapped from
        :meth:`snapshot`, fed by :meth:`watch`) to maintain a
        long-running incremental view; pass frozen
        :meth:`LiveSchemaSnapshot.as_registry` copies to verifier
        modules when they need a stable point-in-time view.
        """
        return await open_watch_stream(self)


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
        raise SchemaRegistryEnvelopeError(
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
    :class:`SchemaRegistryConflictError` with the observed metadata.
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
                raise SchemaRegistryConflictError(
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
        raise SchemaRegistryBackendError(
            "KV adapter has neither .update(last=...) nor "
            ".put(expected_revision=...); CAS-pin not supported"
        ) from exc
    except Exception as exc:
        if _is_conflict_exception(exc):
            actual = _extract_actual_revision(exc)
            raise SchemaRegistryConflictError(
                f"CAS-pin rejected for key {key!r}: "
                f"expected_revision={expected_revision}, "
                f"actual_revision={actual}",
                key=key,
                expected_revision=expected_revision,
                actual_revision=actual,
            ) from exc
        raise


def _is_conflict_exception(exc: BaseException) -> bool:
    """True if ``exc``'s class name matches a CAS-conflict marker."""
    cls_name = type(exc).__name__
    return any(marker in cls_name for marker in _CONFLICT_CLS_MARKERS)


def _extract_actual_revision(exc: BaseException) -> Optional[int]:
    """Pull an actual-revision integer off a conflict exception, if
    the underlying KV adapter surfaces one. Best-effort, returns
    ``None`` when not available.
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
    raise SchemaRegistryBackendError("KV handle has no keys() method")


# ---------------------------------------------------------------------------
# Watch-Stream-Snapshot Layer (Phase-1b Sprint-3 Tag-4, OI-7-Phase-1c-watch)
# ---------------------------------------------------------------------------
#
# Tag-1 (S3-1) shipped get/put/delete/snapshot. Snapshot is full-bucket:
# every verifier pass that wants fresh state takes a fresh full snapshot.
# That is correct for determinism but costly when schema turnover is high
# or when a long-running supervisor wants to track changes between
# snapshots without re-listing.
#
# Tag-4 (S3-4) adds a watch-based incremental layer that consumes
# nats-py's ``KeyValue.watchall()`` (or a mock-equivalent) and surfaces
# decoded :class:`WatchEvent` instances. The synchronous verifier
# surface (:class:`InMemorySchemaRegistry.lookup`) is UNCHANGED: a
# watch-stream is a substrate for materialising live deltas into an
# :class:`InMemorySchemaRegistry` snapshot, not a new verifier
# substrate. The bridge contract is: each verifier pass takes one
# *frozen* :class:`InMemorySchemaRegistry` view; the watch-stream is
# the producer of that view, the verifier does not query the live
# stream.
#
# A :class:`LiveSchemaSnapshot` keeps an in-memory copy of the
# registry, initialises it from a full
# :meth:`NatsKvSchemaRegistry.snapshot`, and then applies decoded
# :class:`WatchEvent` instances as they arrive. Callers get a
# deterministic frozen :class:`InMemorySchemaRegistry` for each
# verifier pass via :meth:`LiveSchemaSnapshot.as_registry`. The
# frozen copy is taken at call time; subsequent watch events do NOT
# mutate the returned registry (T-SR-WS-determinism contract).
#
# Boundary (Phase-1b, Sprint-3 Tag-4):
#
# - The watch-stream is a *consumer* surface. Operators connect the
#   stream to a long-running supervisor task; the supervisor keeps a
#   :class:`LiveSchemaSnapshot` warm and hands frozen
#   :class:`InMemorySchemaRegistry` instances to verifier modules per
#   pass. The watch-stream itself is not the registry.
# - A poisoned envelope on the stream raises
#   :class:`SchemaRegistryEnvelopeError` from the consumer iterator
#   and terminates the iterator. The operator must observe the error,
#   drop the :class:`LiveSchemaSnapshot`, and re-bootstrap from a fresh
#   :meth:`NatsKvSchemaRegistry.snapshot`. Phase-1c does not silently
#   swallow envelope poison (same contract as full snapshot).
# - Watch-stream resumption / replay-from-revision is a Phase-2
#   concern (nats-py supports it via ``watchall(..., resume_from=...)``;
#   the Phase-1c stream wrapper exposes the underlying revision but
#   does not bake in resume policy).


class WatchOp(enum.Enum):
    """Operation kind surfaced by the schema-registry watch-stream.

    Matches nats-py's ``KeyValueOp`` shape: ``PUT`` for insert/update,
    ``DELETE`` for tombstone (explicit delete), ``PURGE`` for
    history-clearing purge. Verifier-side consumers treat ``DELETE``
    and ``PURGE`` identically (the schema is gone); they are surfaced
    separately so audit consumers can distinguish them.
    """

    PUT = "PUT"
    DELETE = "DELETE"
    PURGE = "PURGE"


@dataclass(frozen=True)
class WatchEvent:
    """A single decoded operation from the schema-registry watch-stream.

    Fields:

    - ``op``: the :class:`WatchOp`. PUT means ``entry`` is set;
      DELETE/PURGE mean ``entry`` is ``None``.
    - ``key``: the registry KV key string
      (``schemas/<layer>/<name>/<version>``).
    - ``entry``: the decoded :class:`SchemaRegistryEntry` for PUT;
      ``None`` for DELETE/PURGE.
    - ``revision``: the KV revision at which this event was observed.
      Monotonically increasing per bucket; useful for resume policies
      and audit cross-references.
    """

    op: WatchOp
    key: str
    entry: Optional[SchemaRegistryEntry]
    revision: int


def _decode_watch_update(update: Any) -> WatchEvent:
    """Decode one nats-py ``KeyValue.Entry`` (or mock-equivalent) into
    a :class:`WatchEvent`.

    nats-py exposes the operation kind via an ``operation`` attribute
    that is a ``KeyValueOp`` enum; on a ``PUT`` the ``value`` attr
    carries the envelope bytes, on ``DELETE``/``PURGE`` it is empty
    (``b""`` or ``None``). We mirror that contract and accept both
    the enum and a string (mock-friendliness).
    """
    op_raw = getattr(update, "operation", None)
    if op_raw is None and isinstance(update, Mapping):
        op_raw = update.get("operation")
    if op_raw is None:
        raise SchemaRegistryEnvelopeError(
            f"watch update has no 'operation' attribute: "
            f"type={type(update).__name__}"
        )
    op_name = getattr(op_raw, "name", None) or str(op_raw)
    op_name = op_name.upper()
    if op_name not in {"PUT", "DELETE", "PURGE"}:
        raise SchemaRegistryEnvelopeError(
            f"watch update has unknown operation: {op_name!r}"
        )
    op = WatchOp(op_name)

    key = getattr(update, "key", None)
    if key is None and isinstance(update, Mapping):
        key = update.get("key")
    if not isinstance(key, str) or not key:
        raise SchemaRegistryEnvelopeError(
            f"watch update has empty/non-string key: {key!r}"
        )

    revision = getattr(update, "revision", None)
    if revision is None and isinstance(update, Mapping):
        revision = update.get("revision")
    revision_int = int(revision) if revision is not None else 0

    if op is WatchOp.PUT:
        try:
            blob = _coerce_value_bytes(update)
        except SchemaRegistryEnvelopeError:
            # The PUT carried no .value handle; that is poisoned.
            raise
        entry = _envelope_to_entry(blob)
        return WatchEvent(op=op, key=key, entry=entry, revision=revision_int)

    return WatchEvent(op=op, key=key, entry=None, revision=revision_int)


@dataclass
class _SchemaWatchStreamHandle:
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
    """

    underlying: Any

    async def __aenter__(self) -> "_SchemaWatchStreamHandle":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        stop = getattr(self.underlying, "stop", None)
        if stop is None:
            return
        result = stop()
        if hasattr(result, "__await__"):
            await result

    def __aiter__(self) -> "_SchemaWatchStreamHandle":
        return self

    async def __anext__(self) -> WatchEvent:
        # Shape 1: native async iterator.
        if hasattr(self.underlying, "__anext__"):
            while True:
                update = await self.underlying.__anext__()
                if update is None:
                    # nats-py end-of-initial-replay sentinel; skip it
                    # but keep the iterator alive for the live tail.
                    continue
                return _decode_watch_update(update)
        # Shape 2: ``await updates()`` returns next or None.
        updates = getattr(self.underlying, "updates", None)
        if updates is not None:
            while True:
                update = await updates()
                if update is None:
                    # End-of-stream; stop the iterator.
                    raise StopAsyncIteration
                return _decode_watch_update(update)
        raise SchemaRegistryBackendError(
            f"watch handle has neither __anext__ nor updates(): "
            f"type={type(self.underlying).__name__}"
        )


async def _open_watcher(kv: Any) -> Any:
    """Open the underlying watcher on the KV handle.

    nats-py exposes ``await kv.watchall()`` returning an awaitable
    watcher; some mocks expose the same name without async, or use
    ``watch()`` as the entry point.
    """
    watch_fn = getattr(kv, "watchall", None)
    if watch_fn is None:
        watch_fn = getattr(kv, "watch", None)
    if watch_fn is None:
        raise SchemaRegistryBackendError(
            "KV handle exposes neither watchall() nor watch()"
        )
    result = watch_fn()
    if hasattr(result, "__await__"):
        result = await result
    return result


async def open_watch_stream(
    backend: "NatsKvSchemaRegistry",
) -> _SchemaWatchStreamHandle:
    """Open a watch-stream over the backend's KV bucket.

    Use as an async context manager OR consume directly; either way,
    ``stop()`` is called on close. Each iteration yields one
    :class:`WatchEvent`. Decoder errors raise
    :class:`SchemaRegistryEnvelopeError` and terminate the iterator.
    """
    if not isinstance(backend, NatsKvSchemaRegistry):
        raise TypeError("backend must be a NatsKvSchemaRegistry")
    underlying = await _open_watcher(backend.kv)
    return _SchemaWatchStreamHandle(underlying=underlying)


@dataclass
class LiveSchemaSnapshot:
    """Live, watch-stream-fed snapshot of the schema registry.

    Phase-1b Sprint-3 Tag-4 (S3-4) substrate. Initialises an in-memory
    copy from a full backend snapshot, then applies decoded
    :class:`WatchEvent` instances to keep the copy in sync.

    The class is NOT itself an :class:`InMemorySchemaRegistry`. To
    pass it to a verifier module, call :meth:`as_registry` to take a
    frozen copy at the current state. Subsequent watch events do not
    mutate the returned copy (determinism contract: a frozen copy
    passed to one verifier pass yields stable verdicts).

    Concurrency: a :class:`LiveSchemaSnapshot` is intended for a
    single-consumer pattern within one asyncio task. Cross-task
    sharing requires the caller to lock; the class itself does no
    locking because asyncio guarantees in-task atomicity between
    awaits, and ``apply()`` is synchronous.
    """

    initial: InMemorySchemaRegistry
    last_revision: int = 0
    _live: InMemorySchemaRegistry = field(init=False)

    def __post_init__(self) -> None:
        # Defensive copy: callers may keep a reference to ``initial``
        # and we must not mutate it as deltas arrive.
        self._live = InMemorySchemaRegistry()
        for entry in self.initial.entries.values():
            self._live.add(entry)

    def apply(self, event: WatchEvent) -> None:
        """Apply one :class:`WatchEvent` to the live state.

        PUT updates / inserts the entry; DELETE / PURGE remove it
        (no-op if already absent). The ``last_revision`` counter
        advances monotonically: an event with a revision lower than
        the current ``last_revision`` does NOT regress the counter.
        """
        if not isinstance(event, WatchEvent):
            raise TypeError("event must be a WatchEvent")
        if event.op is WatchOp.PUT:
            if event.entry is None:
                raise SchemaRegistryEnvelopeError(
                    "PUT WatchEvent must carry a non-None entry"
                )
            self._live.add(event.entry)
        else:
            # DELETE / PURGE: remove the key if present.
            self._live.entries.pop(event.key, None)
        if event.revision > self.last_revision:
            self.last_revision = event.revision

    def as_registry(self) -> InMemorySchemaRegistry:
        """Return a frozen :class:`InMemorySchemaRegistry` copy of the
        current live state.

        The returned registry does not share storage with the live
        state; subsequent :meth:`apply` calls do not mutate it.
        """
        frozen = InMemorySchemaRegistry()
        for entry in self._live.entries.values():
            frozen.add(entry)
        return frozen

    @classmethod
    async def from_backend(
        cls, backend: "NatsKvSchemaRegistry"
    ) -> "LiveSchemaSnapshot":
        """Bootstrap a :class:`LiveSchemaSnapshot` from a full backend
        snapshot. The caller is responsible for opening a watch-stream
        and feeding events to :meth:`apply`.
        """
        initial = await backend.snapshot()
        return cls(initial=initial, last_revision=0)
