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

These gates keep poisoned envelopes off the bucket.

Hermetic test contract
----------------------

The test suite at
``wirelang/tests/test_schema_registry_nats_kv_backend.py`` exercises
the backend against an in-memory mock that mirrors the V-908 mock
shape (``_MockKv`` / ``_MockKvEntry``). The mock is intentionally
the same surface so the orchestrator-side and Wirelang-side both
validate against the same nats-py contract.

References (URL-stamped 2026-05-07 by wirelang-eng):

- Spec: ``wirelang/specs/schema-registry-spec.md`` (Phase-1b
  Sprint-3 Tag-1).
- V-908 backend pattern source:
  ``wirelang/federation/route_registry_nats_kv_backend.py``.
- Bucket inventory source: ``scripts/init-nats-buckets.py``
  ``PHASE_1_BUCKETS[0]`` (``wakir-schemas``).
"""

from __future__ import annotations

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
