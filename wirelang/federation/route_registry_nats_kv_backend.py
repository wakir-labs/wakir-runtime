# SPDX-License-Identifier: BUSL-1.1
"""NATS-JetStream-KV-backed :class:`RouteRegistry` implementation.

Phase-1b Sprint-2 Tag-4 (S2-3) lands the production-target backend
for the V-908 federation route registry consumed by
:mod:`wirelang.federation.n2_evaluator`. The Tag-3 module reserved
:class:`RouteRegistry` as a Protocol and shipped
:class:`InMemoryRouteRegistry` as the Phase-1b reference; this
module supplies the durable production form (item I-11 vocabulary,
Phase-2 production-target).

Substrate
---------

The backend persists :class:`RouteRegistryEntry` records in a
NATS-JetStream key-value bucket. The bucket is Phase-1b's
``wakir-federation-routes`` (see :data:`BUCKET_NAME`); its
documented configuration follows the same drift-policy contract
as the four Phase-1 buckets initialised by
``scripts/init-nats-buckets.py`` (orchestrator runbook, Phase-1b
Sprint-2 Tag-1..3 Kai-side delivery):

- ``history``: 5  (allows audit-trail review of recent overwrites)
- ``ttl_seconds``: 0  (unbounded; route windows have their own
  ``active_from`` / ``active_until`` semantics inside the value)
- ``max_value_size``: 4096 B  (one entry is small JSON; cap mirrors
  ``wakir-ftd-poisoned`` for the operational similarity)
- ``storage``: ``"file"``  (durability for production)
- ``replicas``: 1  (Phase-1 single-node; Phase-2 multi-node will
  raise this)

Cross-reference: :data:`BUCKET_NAME` is exported as a module-level
constant so the orchestrator bucket-init script can register the
bucket in the same idempotent inventory pass as the Phase-1 four.
The drift-policy is identical: this backend does NOT auto-create
or auto-correct bucket configuration — it expects an operator-run
``init-nats-buckets`` to have established the bucket before any
:class:`NatsKvRouteRegistry` is constructed.

Design choices
--------------

The :class:`RouteRegistry` Protocol that the N2 evaluator queries
is *synchronous* (`lookup(route_id) -> Optional[RouteRegistryEntry]`).
NATS-py's KV API is async. We therefore do NOT make
:class:`NatsKvRouteRegistry` itself the registry object queried at
evaluation time; instead the backend exposes:

- :meth:`NatsKvRouteRegistry.get` — async lookup (yields one entry
  or ``None``).
- :meth:`NatsKvRouteRegistry.put` — async upsert.
- :meth:`NatsKvRouteRegistry.delete` — async tombstone.
- :meth:`NatsKvRouteRegistry.snapshot` — async snapshot of the
  whole registry into an :class:`InMemoryRouteRegistry`. The
  evaluator queries the snapshot during a single-token validation
  pass; this matches the determinism contract of T-N2-10
  (re-querying the same registry instance MUST yield identical
  results).
- :meth:`NatsKvRouteRegistry.watch` — async watch-stream surface
  added in Phase-1b Sprint-2 Tag-6 (S2-5). Yields decoded
  :class:`WatchEvent` instances for incremental delta tracking.
  Operators feed events into a :class:`LiveSnapshot` to maintain a
  long-running incremental view; the synchronous evaluator surface
  is unchanged and continues to query frozen
  :class:`InMemoryRouteRegistry` copies.

The snapshot pattern keeps the synchronous evaluator surface
unchanged, makes test isolation trivial, and gives a clean
audit-trail point: a single snapshot is one byte-anchorable
artefact (the JSON bytes of the snapshot are stable under JCS).

Value envelope
--------------

Each KV entry is a JSON object with these fields:

- ``schema``: ``"wakir.federation.route-registry-entry/1"`` (URI
  fragment; fixed for Phase-1b).
- ``route_id``: copy of the entry's ``route_id`` (the KV key is the
  same string; the field is duplicated for self-contained reads).
- ``source_ftd_id``: the entry's ``source_ftd_id``.
- ``active_from``: RFC 3339 timestamp string in UTC.
- ``active_until``: RFC 3339 timestamp string in UTC, or ``null``
  for an open-ended window.
- ``wat_anchor_manifest_id``: optional string, or ``null``.

JSON is the obvious envelope: small, observable with the ``nats``
CLI, and preserves the Phase-1b convention used by every other
KV value in the inventory. JCS canonicalisation is not required
for the value itself (NATS-KV has no inter-replica byte-equality
contract for individual values), but we DO use sorted keys with
no extra whitespace so the value bytes are reproducible per
caller.

Hermetic test contract
----------------------

The test suite at
``wirelang/tests/test_federation_route_registry_nats_kv_backend.py``
exercises the backend against a small in-memory mock that mirrors
Kai's Tag-1 ``_MockKv`` / ``_MockJetStream`` shape from
``tests/orchestrator/test_init_nats_buckets.py``. The two mocks are
intentionally analogous (same async surface, same field names) so
the orchestrator-side and the Wirelang-side both validate against
the same nats-py contract.

References (URL-stamped 2026-05-07 by wirelang-eng):

- V-908 spec: ``wirelang/specs/datalog-caveat-vocabulary-phase-2.md``
  §5.5 (Phase-1b N2 evaluator implementation note) and §5.6
  (Phase-1b NATS-KV backend implementation note, added by Tag-4).
- N2 evaluator: ``wirelang/federation/n2_evaluator.py``.
- Orchestrator NATS-KV bucket inventory:
  ``scripts/init-nats-buckets.py`` ``PHASE_1_BUCKETS`` constant
  (Kai-side; this module's :data:`BUCKET_NAME` is the Phase-1b
  Federation-Routes addition that the orchestrator init script
  picks up via the registered constant import path).
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Mapping, Optional

from .n2_evaluator import (
    InMemoryRouteRegistry,
    RouteRegistry,
    RouteRegistryEntry,
)


# ---------------------------------------------------------------------------
# Bucket identity (cross-reference: orchestrator bucket inventory)
# ---------------------------------------------------------------------------


#: NATS-KV bucket name for the federation-route registry. Phase-1b
#: convention: ``wakir-`` prefix, kebab-case, singular-domain noun
#: matching the four Phase-1 buckets registered in
#: ``scripts/init-nats-buckets.py``.
BUCKET_NAME = "wakir-federation-routes"

#: Documented bucket configuration. The drift-policy is the same
#: as for the Phase-1 four: any deviation between the live cluster
#: and these values is reported as drift, never auto-corrected.
BUCKET_CONFIG: Mapping[str, Any] = {
    "name": BUCKET_NAME,
    "description": "V-908 federation-route registry (Phase-1b)",
    "history": 5,
    "ttl_seconds": 0,
    "max_value_size": 4096,
    "storage": "file",
    "replicas": 1,
}

#: Schema-URI fragment embedded in every value envelope.
VALUE_SCHEMA = "wakir.federation.route-registry-entry/1"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RouteRegistryBackendError(Exception):
    """Base class for backend-layer failures."""


class RouteRegistryEnvelopeError(RouteRegistryBackendError):
    """Raised when a KV value cannot be parsed or fails the
    schema-shape contract.

    A poisoned envelope is *not* silently swallowed: the backend
    surfaces the error so an operator can act. The N2 evaluator's
    determinism contract is preserved because a snapshot is taken
    eagerly; if a snapshot raises, no token is evaluated against a
    half-broken registry.
    """


class RouteRegistryConflictError(RouteRegistryBackendError):
    """Raised when a put-with-revision call is rejected because the
    KV revision has changed since the caller observed it.
    """


# ---------------------------------------------------------------------------
# Envelope codec
# ---------------------------------------------------------------------------


def _entry_to_envelope(entry: RouteRegistryEntry) -> bytes:
    """Serialise a :class:`RouteRegistryEntry` to the canonical
    JSON envelope written into the KV bucket.

    The byte form uses sorted keys and the compact ``(",", ":")``
    separator pair so the bytes are reproducible for a given
    entry. Datetimes are normalised to RFC 3339 in UTC.
    """
    if not isinstance(entry, RouteRegistryEntry):
        raise TypeError("entry must be a RouteRegistryEntry")
    payload = {
        "schema": VALUE_SCHEMA,
        "route_id": entry.route_id,
        "source_ftd_id": entry.source_ftd_id,
        "active_from": _dt_to_rfc3339(entry.active_from),
        "active_until": (
            _dt_to_rfc3339(entry.active_until)
            if entry.active_until is not None
            else None
        ),
        "wat_anchor_manifest_id": entry.wat_anchor_manifest_id,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _envelope_to_entry(blob: bytes) -> RouteRegistryEntry:
    """Inverse of :func:`_entry_to_envelope`. Raises
    :class:`RouteRegistryEnvelopeError` on shape violation.
    """
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RouteRegistryEnvelopeError(
            f"non-utf-8 envelope: {exc!r}"
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RouteRegistryEnvelopeError(
            f"non-JSON envelope: {exc!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise RouteRegistryEnvelopeError(
            f"envelope is not a JSON object: type={type(payload).__name__}"
        )
    schema = payload.get("schema")
    if schema != VALUE_SCHEMA:
        raise RouteRegistryEnvelopeError(
            f"envelope schema mismatch: want {VALUE_SCHEMA!r} got {schema!r}"
        )
    for required in ("route_id", "source_ftd_id", "active_from"):
        if required not in payload:
            raise RouteRegistryEnvelopeError(
                f"envelope missing required field: {required!r}"
            )
    try:
        active_from = _rfc3339_to_dt(payload["active_from"])
        active_until_raw = payload.get("active_until")
        active_until = (
            _rfc3339_to_dt(active_until_raw)
            if active_until_raw is not None
            else None
        )
    except ValueError as exc:
        raise RouteRegistryEnvelopeError(
            f"envelope datetime parse error: {exc!r}"
        ) from exc
    return RouteRegistryEntry(
        route_id=payload["route_id"],
        source_ftd_id=payload["source_ftd_id"],
        active_from=active_from,
        active_until=active_until,
        wat_anchor_manifest_id=payload.get("wat_anchor_manifest_id"),
    )


def _dt_to_rfc3339(dt: datetime) -> str:
    """Render a tz-aware datetime as RFC 3339 in UTC.

    Naive datetimes are rejected; this matches the federation-resolver
    convention that all wall-clock anchors are tz-aware.
    """
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    in_utc = dt.astimezone(timezone.utc)
    # `isoformat` already produces RFC-3339 for tz-aware UTC datetimes;
    # we replace the `+00:00` suffix with the canonical `Z` form for
    # operator-friendly readability in the KV store.
    iso = in_utc.isoformat()
    if iso.endswith("+00:00"):
        iso = iso[:-6] + "Z"
    return iso


def _rfc3339_to_dt(value: Any) -> datetime:
    """Parse an RFC 3339 string (with `Z` or `+00:00` suffix) back into
    a tz-aware datetime in UTC. Raises ``ValueError`` for any other
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
# KV backend
# ---------------------------------------------------------------------------


@dataclass
class NatsKvRouteRegistry:
    """NATS-JetStream-KV-backed :class:`RouteRegistry` backend.

    The backend is async; it is not itself the registry passed to
    the N2 evaluator. Use :meth:`snapshot` to materialise a
    deterministic :class:`InMemoryRouteRegistry` for one evaluator
    pass.

    Construction is cheap: pass an open ``KeyValue`` handle from
    nats-py (or a mock that mirrors the same surface). The backend
    performs *no* network I/O on construction.
    """

    kv: Any
    bucket_name: str = BUCKET_NAME

    # ------------------------------------------------------------------
    # Single-key operations
    # ------------------------------------------------------------------

    async def get(self, route_id: str) -> Optional[RouteRegistryEntry]:
        """Return the entry for ``route_id``, or ``None`` if absent.

        Raises :class:`RouteRegistryEnvelopeError` if the key exists
        but the value cannot be decoded.
        """
        if not isinstance(route_id, str) or not route_id:
            return None
        try:
            kve = await self.kv.get(route_id)
        except Exception as exc:
            cls_name = type(exc).__name__
            if "NotFound" in cls_name or "DoesNotExist" in cls_name or isinstance(exc, KeyError):
                return None
            raise
        if kve is None:
            return None
        blob = _coerce_value_bytes(kve)
        return _envelope_to_entry(blob)

    async def put(self, entry: RouteRegistryEntry) -> int:
        """Upsert an entry. Returns the new KV revision number.

        Last-write-wins semantics, identical to
        :class:`InMemoryRouteRegistry.add`.
        """
        if not isinstance(entry, RouteRegistryEntry):
            raise TypeError("entry must be a RouteRegistryEntry")
        blob = _entry_to_envelope(entry)
        revision = await self.kv.put(entry.route_id, blob)
        return _coerce_revision(revision)

    async def delete(self, route_id: str) -> None:
        """Tombstone an entry. No-op if the key was already absent.

        The tombstone is a NATS-KV tombstone: the bucket history
        retains the operation, but :meth:`get` will return ``None``.
        """
        if not isinstance(route_id, str) or not route_id:
            raise ValueError("route_id must be a non-empty string")
        try:
            await self.kv.delete(route_id)
        except Exception as exc:
            cls_name = type(exc).__name__
            if "NotFound" in cls_name or "DoesNotExist" in cls_name or isinstance(exc, KeyError):
                return
            raise

    # ------------------------------------------------------------------
    # Snapshot (the bridge to the synchronous evaluator surface)
    # ------------------------------------------------------------------

    async def snapshot(self) -> InMemoryRouteRegistry:
        """Materialise the live bucket into an
        :class:`InMemoryRouteRegistry`.

        Strategy: list all keys, then fetch each one. A poisoned
        envelope raises :class:`RouteRegistryEnvelopeError` and the
        snapshot aborts; partial snapshots are not surfaced because
        the evaluator's determinism contract requires the snapshot
        to be a complete, self-consistent view.
        """
        keys = await _list_keys(self.kv)
        in_memory = InMemoryRouteRegistry()
        for key in keys:
            entry = await self.get(key)
            if entry is None:
                # Tombstoned between list and get; skip without error.
                continue
            in_memory.add(entry)
        return in_memory

    # ------------------------------------------------------------------
    # Watch-stream (Phase-1b Sprint-2 Tag-6, S2-5)
    # ------------------------------------------------------------------

    async def watch(self) -> "_WatchStreamHandle":
        """Open a watch-stream over this backend's bucket.

        Returns an async iterable / context manager that yields
        decoded :class:`WatchEvent` instances. See
        :func:`open_watch_stream` for details.

        Phase-1b boundary: the watch-stream is a *consumer* surface;
        it does NOT replace :meth:`snapshot`. Use a
        :class:`LiveSnapshot` (bootstrapped from :meth:`snapshot`,
        fed by :meth:`watch`) to maintain a long-running incremental
        view; pass frozen :meth:`LiveSnapshot.as_registry` copies to
        the synchronous evaluator surface.
        """
        return await open_watch_stream(self)


# ---------------------------------------------------------------------------
# Helpers (KV adapter shims for nats-py vs. the test mock)
# ---------------------------------------------------------------------------


def _coerce_value_bytes(kve: Any) -> bytes:
    """Return the raw value bytes from a KV entry handle.

    nats-py exposes ``kve.value`` as bytes; some mocks expose the
    same field. Plain bytes are also accepted for the simplest
    possible mock.
    """
    if isinstance(kve, (bytes, bytearray)):
        return bytes(kve)
    value = getattr(kve, "value", None)
    if value is None and isinstance(kve, Mapping):
        value = kve.get("value")
    if value is None:
        raise RouteRegistryEnvelopeError(
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
    ``await kv.keys()`` returning a list[str]; we accept either an
    awaitable list or an async iterable for mock flexibility.
    """
    if hasattr(kv, "keys"):
        result = kv.keys()
        # The real nats-py ``keys()`` is an async coroutine returning
        # ``list[str]``; some mocks return the list directly without
        # awaiting. Handle both.
        if hasattr(result, "__await__"):
            result = await result
        if hasattr(result, "__aiter__"):
            collected = []
            async for k in result:
                collected.append(k)
            return collected
        return list(result)
    raise RouteRegistryBackendError("KV handle has no keys() method")


# ---------------------------------------------------------------------------
# Watch-Stream-Snapshot Layer (Phase-1b Sprint-2 Tag-6, S2-5)
# ---------------------------------------------------------------------------
#
# Tag-4 (S2-3) shipped get/put/delete/snapshot. Snapshot is full-bucket:
# every evaluator pass that wants fresh state takes a fresh full
# snapshot. That is correct for determinism but costly when route
# turnover is high or when a long-running supervisor wants to track
# changes between snapshots without re-listing.
#
# Tag-6 (S2-5) adds a watch-based incremental layer that consumes
# nats-py's ``KeyValue.watch()`` (or a mock-equivalent) and surfaces
# decoded :class:`WatchEvent` instances. The synchronous evaluator
# surface (`RouteRegistry.lookup`) is UNCHANGED: a watch-stream is a
# substrate for materialising live deltas into an
# :class:`InMemoryRouteRegistry` snapshot, not a new evaluator
# substrate. The bridge contract is: each evaluator pass takes one
# *frozen* :class:`InMemoryRouteRegistry` view; the watch-stream is
# the producer of that view, the evaluator does not query the live
# stream.
#
# A :class:`LiveSnapshot` keeps an in-memory copy of the registry,
# initialises it from a full :meth:`NatsKvRouteRegistry.snapshot`,
# and then applies decoded :class:`WatchEvent` instances as they
# arrive. Callers get a deterministic frozen
# :class:`InMemoryRouteRegistry` for each evaluator pass via
# :meth:`LiveSnapshot.as_registry`. The frozen copy is taken at
# call time; subsequent watch events do NOT mutate the returned
# registry (T-LS-determinism contract).
#
# Boundary (Phase-1b, Sprint-2 Tag-6):
#
# - The watch-stream is a *consumer* surface. Operators connect the
#   stream to a long-running supervisor task; the supervisor keeps a
#   :class:`LiveSnapshot` warm and hands frozen
#   :class:`InMemoryRouteRegistry` instances to the evaluator per
#   token. The watch-stream itself is not the registry.
# - A poisoned envelope on the stream raises
#   :class:`RouteRegistryEnvelopeError` from the consumer iterator and
#   terminates the iterator. The operator must observe the error,
#   drop the :class:`LiveSnapshot`, and re-bootstrap from a fresh
#   :meth:`NatsKvRouteRegistry.snapshot`. Phase-1b does not silently
#   swallow envelope poison (same contract as full snapshot).
# - Watch-stream resumption / replay-from-revision is a Phase-2
#   concern (nats-py supports it via ``watch(..., resume_from=...)``;
#   the Phase-1b stream wrapper exposes the underlying revision but
#   does not bake in resume policy).


class WatchOp(enum.Enum):
    """Operation kind surfaced by the watch-stream.

    Matches nats-py's ``KeyValueOp`` shape: ``PUT`` for insert/update,
    ``DELETE`` for tombstone (explicit delete), ``PURGE`` for
    history-clearing purge. The evaluator-side consumer treats
    ``DELETE`` and ``PURGE`` identically (the route is gone); they
    are surfaced separately so audit consumers can distinguish them.
    """

    PUT = "PUT"
    DELETE = "DELETE"
    PURGE = "PURGE"


@dataclass(frozen=True)
class WatchEvent:
    """A single decoded operation from the registry watch-stream.

    Fields:

    - ``op``: the :class:`WatchOp`. PUT means ``entry`` is set;
      DELETE/PURGE mean ``entry`` is ``None``.
    - ``route_id``: the registry route_id (KV key).
    - ``entry``: the decoded :class:`RouteRegistryEntry` for PUT;
      ``None`` for DELETE/PURGE.
    - ``revision``: the KV revision at which this event was observed.
      Monotonically increasing per bucket; useful for resume policies
      and audit cross-references.
    """

    op: WatchOp
    route_id: str
    entry: Optional[RouteRegistryEntry]
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
        raise RouteRegistryEnvelopeError(
            f"watch update has no 'operation' attribute: type={type(update).__name__}"
        )
    op_name = getattr(op_raw, "name", None) or str(op_raw)
    op_name = op_name.upper()
    if op_name not in {"PUT", "DELETE", "PURGE"}:
        raise RouteRegistryEnvelopeError(
            f"watch update has unknown operation: {op_name!r}"
        )
    op = WatchOp(op_name)

    key = getattr(update, "key", None)
    if key is None and isinstance(update, Mapping):
        key = update.get("key")
    if not isinstance(key, str) or not key:
        raise RouteRegistryEnvelopeError(
            f"watch update has empty/non-string key: {key!r}"
        )

    revision = getattr(update, "revision", None)
    if revision is None and isinstance(update, Mapping):
        revision = update.get("revision")
    revision_int = int(revision) if revision is not None else 0

    if op is WatchOp.PUT:
        try:
            blob = _coerce_value_bytes(update)
        except RouteRegistryEnvelopeError:
            # The PUT carried no .value handle; that is poisoned.
            raise
        entry = _envelope_to_entry(blob)
        return WatchEvent(op=op, route_id=key, entry=entry, revision=revision_int)

    return WatchEvent(op=op, route_id=key, entry=None, revision=revision_int)


@dataclass
class _WatchStreamHandle:
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
        raise RouteRegistryBackendError(
            f"watch handle has neither __anext__ nor updates(): "
            f"type={type(self.underlying).__name__}"
        )


async def _open_watcher(kv: Any) -> Any:
    """Open the underlying watcher on the KV handle.

    nats-py exposes ``await kv.watchall()`` returning an awaitable
    watcher; some mocks expose the same name without async.
    """
    watch_fn = getattr(kv, "watchall", None)
    if watch_fn is None:
        watch_fn = getattr(kv, "watch", None)
    if watch_fn is None:
        raise RouteRegistryBackendError(
            "KV handle exposes neither watchall() nor watch()"
        )
    result = watch_fn()
    if hasattr(result, "__await__"):
        result = await result
    return result


async def open_watch_stream(backend: "NatsKvRouteRegistry") -> _WatchStreamHandle:
    """Open a watch-stream over the backend's KV bucket.

    Use as an async context manager OR consume directly; either way,
    ``stop()`` is called on close. Each iteration yields one
    :class:`WatchEvent`. Decoder errors raise
    :class:`RouteRegistryEnvelopeError` and terminate the iterator.
    """
    if not isinstance(backend, NatsKvRouteRegistry):
        raise TypeError("backend must be a NatsKvRouteRegistry")
    underlying = await _open_watcher(backend.kv)
    return _WatchStreamHandle(underlying=underlying)


@dataclass
class LiveSnapshot:
    """Live, watch-stream-fed snapshot of the route registry.

    Phase-1b Sprint-2 Tag-6 (S2-5) substrate. Initialises an
    in-memory copy from a full backend snapshot, then applies decoded
    :class:`WatchEvent` instances to keep the copy in sync.

    The class is NOT itself a :class:`RouteRegistry`. To pass it to
    the synchronous evaluator surface, call :meth:`as_registry` to
    take a frozen copy at the current state. Subsequent watch events
    do not mutate the returned copy (determinism contract: a frozen
    copy passed to one evaluator pass yields stable verdicts).

    Concurrency: a :class:`LiveSnapshot` is intended for a
    single-consumer pattern within one asyncio task. Cross-task
    sharing requires the caller to lock; the class itself does no
    locking because asyncio guarantees in-task atomicity between
    awaits, and ``apply()`` is synchronous.
    """

    initial: InMemoryRouteRegistry
    last_revision: int = 0
    _live: InMemoryRouteRegistry = field(init=False)

    def __post_init__(self) -> None:
        # Defensive copy: callers may keep a reference to ``initial``
        # and we must not mutate it as deltas arrive.
        self._live = InMemoryRouteRegistry()
        for entry in self.initial.entries.values():
            self._live.add(entry)

    def apply(self, event: WatchEvent) -> None:
        """Apply one :class:`WatchEvent` to the live state.

        PUT updates / inserts the entry; DELETE / PURGE remove it
        (no-op if already absent).
        """
        if not isinstance(event, WatchEvent):
            raise TypeError("event must be a WatchEvent")
        if event.op is WatchOp.PUT:
            if event.entry is None:
                raise RouteRegistryEnvelopeError(
                    "PUT WatchEvent must carry a non-None entry"
                )
            self._live.add(event.entry)
        else:
            # DELETE / PURGE: remove the route_id if present.
            self._live.entries.pop(event.route_id, None)
        if event.revision > self.last_revision:
            self.last_revision = event.revision

    def as_registry(self) -> InMemoryRouteRegistry:
        """Return a frozen :class:`InMemoryRouteRegistry` copy of the
        current live state.

        The returned registry does not share storage with the live
        state; subsequent :meth:`apply` calls do not mutate it.
        """
        frozen = InMemoryRouteRegistry()
        for entry in self._live.entries.values():
            frozen.add(entry)
        return frozen

    @classmethod
    async def from_backend(
        cls, backend: "NatsKvRouteRegistry"
    ) -> "LiveSnapshot":
        """Bootstrap a :class:`LiveSnapshot` from a full backend
        snapshot. The caller is responsible for opening a watch-stream
        and feeding events to :meth:`apply`.
        """
        initial = await backend.snapshot()
        return cls(initial=initial, last_revision=0)
