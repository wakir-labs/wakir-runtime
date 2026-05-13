# SPDX-License-Identifier: Apache-2.0
"""Durable NATS-KV-backed ``SequenceNumberLedger`` for the
CaveatOverrideEvent cross-org export surface (Phase-2 Sprint-9 Tag-2).

Sprint-9 Tag-1 shipped the
:class:`~wirelang.federation.caveat_override_export.SequenceNumberLedger`
Protocol with an
:class:`~wirelang.federation.caveat_override_export.InMemorySequenceNumberLedger`
default. The in-memory default is hermetic-test-grade and
single-process-exporter-grade: any process restart loses the
ledger state and an exporter cluster running on more than one
node cannot share the ledger. For **multi-org federation** where
the replay-protection invariant is load-bearing — Org-A and Org-B
must agree byte-deterministically on the (route_id,
chain_hash) -> last_seen_sequence axis even across operator
process restarts — the ledger MUST be durable.

This module is the durable tier: a **per-organisation NATS-KV
bucket** where each (route_id, chain_hash) pair gets a single
sequence-number key that is updated by **optimistic-concurrency
CAS-pin** on the underlying KV revision. Two concurrent exporters
attempting the same record_export at the same expected
last-revision get exactly one winner; the loser raises
:class:`SequenceNumberLedgerConcurrencyConflictError` and the
caller MUST re-read the live last_seen and retry.

Pattern alignment
=================

This module mirrors the Sprint-8 Tag-4
:mod:`wirelang.federation.marker_stack_kv` backend with three
deliberate differences for the ledger axis:

1. **Single-key-per-pair** (instead of append-only event-log).
   The marker-stack KV backend stores **one event per sequence**
   (append-only); the ledger stores **one cell per pair** that
   carries the current last_seen_sequence (overwrite-with-CAS).
   The ledger axis is "what is the highest sequence I have ever
   admitted" — a scalar per pair, not a log.
2. **CAS-pin on the KV revision**, not on the sequence number.
   The marker-stack backend CAS-pins on the sequence-number axis
   (the key includes the sequence; ``create`` fails if the key
   already exists). The ledger CAS-pins on the **KV revision** of
   the existing cell: an :meth:`update` call carries the
   previously observed revision and the KV layer rejects the
   write if the cell has since been mutated. This is the standard
   NATS-KV optimistic-concurrency pattern (``update`` with
   ``last_revision``).
3. **Per-org bucket isolation**: each org gets its own bucket
   ``wakir-caveat-override-export-sequence-{org_id}``. Cross-org
   reads/writes raise
   :class:`SequenceNumberLedgerCrossOrgBoundaryError` instead of
   touching the bucket. This mirrors the Sprint-8 Tag-4 per-org
   bucket isolation contract.

Bucket identity
---------------

Bucket name: ``wakir-caveat-override-export-sequence-{org_id}``
(deterministically derived from a validated ``org_id``).
``org_id`` follows the same permitted-character regex as the
marker-stack-KV / Sprint-7 ``peer_org`` predicates (URI-safe
ASCII subset, no slashes, no whitespace).

Key schema: ``sequence/<route_id>/<chain_hash>``. Both
``route_id`` and ``chain_hash`` are permitted-character-validated
before they are concatenated into the key path. The
``chain_hash`` field is a 64-hex BLAKE2b-256 digest produced by
:func:`~wirelang.federation.caveat_override_export.derive_caveat_chain_hash`;
the validator admits the broader URI-safe ASCII subset so that
operator-side smoke fixtures can use shorter pseudonyms in
hermetic tests without forcing a 64-hex round-trip.

Value envelope
--------------

Each KV value is a JSON object with these fields:

- ``schema``: ``"wakir.federation.caveat-override-export-sequence/1"``.
- ``org_id``: the producing org's id (matches the bucket).
- ``route_id``: the export route this cell tracks.
- ``chain_hash``: the original-caveat-chain-hash this cell tracks.
- ``last_seen_sequence``: the highest sequence_number admitted
  so far (positive int, monotonically increasing across writes
  to the same cell).
- ``recorded_at``: RFC-3339 UTC timestamp of the latest write.
  Operator-side bookkeeping; not load-bearing for the ledger
  invariant.

Replay-protection contract
--------------------------

The ledger MUST refuse to admit a sequence less-than-or-equal-to
the currently recorded ``last_seen_sequence`` for any pair.
:meth:`NatsKvSequenceNumberLedger.record_export` raises
:class:`~wirelang.federation.caveat_override_export.CaveatOverrideExportReplayError`
synchronously for a replay; the ledger cell is left untouched.
This is byte-equivalent to the
:class:`~wirelang.federation.caveat_override_export.InMemorySequenceNumberLedger`
contract — production deployments install the durable tier and
the exporter surface stays identical.

Cross-trust-domain isolation
----------------------------

Each org operates against its own
:class:`NatsKvSequenceNumberLedger` instance, bound to a
specific ``org_id`` at construction. Reads/writes against a
different org-id raise
:class:`SequenceNumberLedgerCrossOrgBoundaryError` without I/O.
Cross-org export verification flows through the Sprint-7
cross-trust-domain bridge surface, which is out of scope for this
module — the ledger sits **behind** the exporter and is consulted
by Org-A's exporter / Org-B's verifier independently against
their own buckets.

Sandbox boundary
----------------

Live NATS connections are operator-hand
(``feedback_sandbox_host_trennung.md`` memory). All tests in this
module run against an in-memory mock that mirrors the Sprint-8
Tag-4 :class:`_MockKv` shape with an ``update`` CAS-pin
extension. No live NATS connection is established from the
sandbox.

References
----------

- Sprint-9 Tag-1 source:
  :mod:`wirelang.federation.caveat_override_export`.
- Sprint-8 Tag-4 pattern:
  :mod:`wirelang.federation.marker_stack_kv`.
- Spec: ``wirelang/specs/schema-registry-spec.md`` §5.18 (added
  in v0.34.0).
- Reza Persona §2 (Capability-Token-Layer: Reza-Owner-Domain).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Tuple

from wirelang.federation.caveat_override_export import (
    CaveatOverrideExportReplayError,
    CaveatOverrideExportShapeError,
    SequenceNumberLedger,
)


# ---------------------------------------------------------------------------
# Bucket identity / key derivation
# ---------------------------------------------------------------------------


#: Bucket name prefix; the full bucket name is
#: ``BUCKET_NAME_PREFIX + org_id``.
BUCKET_NAME_PREFIX = "wakir-caveat-override-export-sequence-"

#: Documented bucket configuration. Drift-policy: any deviation
#: between the live cluster and these values is reported as drift,
#: never auto-corrected (same contract as Sprint-5 Tag-2 / Sprint-8
#: Tag-4 backends).
BUCKET_CONFIG: Mapping[str, Any] = {
    "description": "Wirelang durable caveat-override-export sequence-number ledger (Phase-2)",
    "history": 1,
    "ttl_seconds": 0,
    "max_value_size": 4_096,
    "storage": "file",
    "replicas": 1,
}

#: Schema URI embedded in every value envelope.
VALUE_SCHEMA = "wakir.federation.caveat-override-export-sequence/1"

#: Permitted-character regex for ``org_id`` (URI-safe ASCII
#: subset, no slashes, no whitespace).
_ORG_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$")

#: Permitted-character regex for ``route_id`` and ``chain_hash``;
#: identical to the Sprint-7 ``peer_org`` predicate subset, so a
#: 64-hex BLAKE2b digest matches naturally.
_KEY_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$")

_KEY_PREFIX = "sequence/"


def bucket_name_for_org(org_id: str) -> str:
    """Return the canonical bucket name for ``org_id``.

    Raises :class:`ValueError` if ``org_id`` does not match the
    permitted-character regex. The derivation is deterministic and
    bijective: ``bucket_name_for_org`` and
    :func:`org_id_for_bucket_name` round-trip byte-equal.
    """
    if not isinstance(org_id, str) or not org_id:
        raise ValueError(
            f"org_id must be a non-empty string, got {org_id!r}"
        )
    if not _ORG_ID_RE.match(org_id):
        raise ValueError(
            f"org_id {org_id!r} does not match permitted-character "
            f"pattern {_ORG_ID_RE.pattern!r}"
        )
    return f"{BUCKET_NAME_PREFIX}{org_id}"


def org_id_for_bucket_name(bucket_name: str) -> str:
    """Inverse of :func:`bucket_name_for_org`. Raises
    :class:`ValueError` for a non-matching prefix.
    """
    if not isinstance(bucket_name, str):
        raise ValueError(
            f"bucket_name must be a string, got {bucket_name!r}"
        )
    if not bucket_name.startswith(BUCKET_NAME_PREFIX):
        raise ValueError(
            f"bucket_name must start with {BUCKET_NAME_PREFIX!r}: "
            f"{bucket_name!r}"
        )
    org_id = bucket_name[len(BUCKET_NAME_PREFIX):]
    if not _ORG_ID_RE.match(org_id):
        raise ValueError(
            f"bucket_name carries malformed org_id {org_id!r}"
        )
    return org_id


def key_for_pair(route_id: str, chain_hash: str) -> str:
    """Derive the canonical KV key for a (route_id, chain_hash) pair.

    Format: ``sequence/<route_id>/<chain_hash>``. Both components
    are permitted-character-validated.

    Raises :class:`ValueError` for malformed components.
    """
    if not isinstance(route_id, str) or not route_id:
        raise ValueError(
            f"route_id must be a non-empty string, got {route_id!r}"
        )
    if not _KEY_COMPONENT_RE.match(route_id):
        raise ValueError(
            f"route_id {route_id!r} does not match permitted-"
            f"character pattern {_KEY_COMPONENT_RE.pattern!r}"
        )
    if not isinstance(chain_hash, str) or not chain_hash:
        raise ValueError(
            f"chain_hash must be a non-empty string, got "
            f"{chain_hash!r}"
        )
    if not _KEY_COMPONENT_RE.match(chain_hash):
        raise ValueError(
            f"chain_hash {chain_hash!r} does not match permitted-"
            f"character pattern {_KEY_COMPONENT_RE.pattern!r}"
        )
    return f"{_KEY_PREFIX}{route_id}/{chain_hash}"


def parse_pair_key(key: str) -> Tuple[str, str]:
    """Inverse of :func:`key_for_pair`. Returns
    ``(route_id, chain_hash)``. Raises :class:`ValueError` for a
    malformed key shape.
    """
    if not isinstance(key, str) or not key.startswith(_KEY_PREFIX):
        raise ValueError(
            f"key must start with {_KEY_PREFIX!r}, got {key!r}"
        )
    rest = key[len(_KEY_PREFIX):]
    parts = rest.split("/")
    if len(parts) != 2:
        raise ValueError(
            f"key must have shape sequence/<route_id>/<chain_hash>: "
            f"{key!r}"
        )
    route_id, chain_hash = parts
    if not route_id or not _KEY_COMPONENT_RE.match(route_id):
        raise ValueError(
            f"key carries malformed route_id {route_id!r}"
        )
    if not chain_hash or not _KEY_COMPONENT_RE.match(chain_hash):
        raise ValueError(
            f"key carries malformed chain_hash {chain_hash!r}"
        )
    return route_id, chain_hash


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SequenceNumberLedgerError(Exception):
    """Base class for durable sequence-number-ledger failures."""


class SequenceNumberLedgerEnvelopeError(SequenceNumberLedgerError):
    """Raised when a KV value cannot be parsed or fails the
    schema-shape contract. A poisoned envelope is never silently
    swallowed; it surfaces from :meth:`last_seen` / :meth:`next_sequence`
    / :meth:`record_export` so an operator can act.
    """


class SequenceNumberLedgerConcurrencyConflictError(SequenceNumberLedgerError):
    """Raised when an optimistic-concurrency ``update`` is rejected
    because another writer landed first at the same expected
    revision.

    The caller MUST re-read the live last_seen, recompute their
    intended sequence, and retry. Optimistic concurrency: no
    implicit retry, no silent overwrite — the conflict is surfaced
    so the ledger invariant (monotonic per-pair last_seen) is
    preserved.
    """

    def __init__(
        self,
        message: str,
        *,
        key: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.key = key
        self.expected_revision = expected_revision


class SequenceNumberLedgerCrossOrgBoundaryError(SequenceNumberLedgerError):
    """Raised when a caller asks a ledger bound to ``org_id=A`` to
    read or write a pair under ``org_id=B``.

    Cross-org reads are explicit operator-deliberate gestures that
    flow through the Sprint-7 cross-trust-domain bridge surface;
    a direct cross-bucket read via
    :class:`NatsKvSequenceNumberLedger` is a configuration error
    and is surfaced as this typed exception.
    """

    def __init__(
        self,
        message: str,
        *,
        backend_org_id: Optional[str] = None,
        requested_org_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.backend_org_id = backend_org_id
        self.requested_org_id = requested_org_id


# ---------------------------------------------------------------------------
# JSON encode / decode helpers
# ---------------------------------------------------------------------------


def _rfc3339(dt: datetime) -> str:
    """Encode a timezone-aware datetime as an RFC-3339 UTC string."""
    if dt.tzinfo is None:
        raise SequenceNumberLedgerEnvelopeError(
            f"datetime must be timezone-aware: {dt!r}"
        )
    aware = dt.astimezone(timezone.utc)
    return aware.strftime("%Y-%m-%dT%H:%M:%S.%f").rstrip("0").rstrip(".") + "Z"


def _parse_rfc3339(s: Any) -> datetime:
    """Decode an RFC-3339 UTC string into a timezone-aware
    datetime. Raises :class:`SequenceNumberLedgerEnvelopeError` on
    failure.
    """
    if not isinstance(s, str):
        raise SequenceNumberLedgerEnvelopeError(
            f"datetime field must be a string, got "
            f"type={type(s).__name__}"
        )
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SequenceNumberLedgerEnvelopeError(
            f"datetime field failed to parse: {s!r} ({exc})"
        ) from exc


@dataclass(frozen=True)
class _LedgerCell:
    """Internal record assembled from a decoded ledger cell."""

    org_id: str
    route_id: str
    chain_hash: str
    last_seen_sequence: int
    recorded_at: datetime
    revision: int


def _encode_envelope(
    *,
    org_id: str,
    route_id: str,
    chain_hash: str,
    last_seen_sequence: int,
    recorded_at: datetime,
) -> bytes:
    """Serialise a ledger cell into a deterministic JSON envelope.

    Uses sorted-key + compact-separator output so the bytes are
    reproducible byte-for-byte per caller (Sprint-5 Tag-2 / Sprint-8
    Tag-4 envelope contract).
    """
    payload: dict = {
        "schema": VALUE_SCHEMA,
        "org_id": org_id,
        "route_id": route_id,
        "chain_hash": chain_hash,
        "last_seen_sequence": last_seen_sequence,
        "recorded_at": _rfc3339(recorded_at),
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _decode_envelope(
    blob: bytes, *, revision: int
) -> _LedgerCell:
    """Inverse of :func:`_encode_envelope`.

    Raises :class:`SequenceNumberLedgerEnvelopeError` on any shape
    failure (unparseable JSON, wrong schema URI, missing field, ...).
    """
    if not isinstance(blob, (bytes, bytearray)):
        raise SequenceNumberLedgerEnvelopeError(
            f"envelope blob must be bytes, got "
            f"type={type(blob).__name__}"
        )
    try:
        payload = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SequenceNumberLedgerEnvelopeError(
            f"envelope is not valid JSON: {exc!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise SequenceNumberLedgerEnvelopeError(
            f"envelope top-level must be a JSON object: type="
            f"{type(payload).__name__}"
        )
    schema = payload.get("schema")
    if schema != VALUE_SCHEMA:
        raise SequenceNumberLedgerEnvelopeError(
            f"envelope schema must be {VALUE_SCHEMA!r}, got "
            f"{schema!r}"
        )
    for required in (
        "org_id",
        "route_id",
        "chain_hash",
        "last_seen_sequence",
        "recorded_at",
    ):
        if required not in payload:
            raise SequenceNumberLedgerEnvelopeError(
                f"envelope missing required field: {required!r}"
            )
    last_seen_raw = payload["last_seen_sequence"]
    if (
        not isinstance(last_seen_raw, int)
        or isinstance(last_seen_raw, bool)
        or last_seen_raw < 1
    ):
        raise SequenceNumberLedgerEnvelopeError(
            f"envelope last_seen_sequence must be positive int, "
            f"got {last_seen_raw!r}"
        )
    return _LedgerCell(
        org_id=payload["org_id"],
        route_id=payload["route_id"],
        chain_hash=payload["chain_hash"],
        last_seen_sequence=last_seen_raw,
        recorded_at=_parse_rfc3339(payload["recorded_at"]),
        revision=revision,
    )


# ---------------------------------------------------------------------------
# KV-adapter helpers (mock + nats-py shapes)
# ---------------------------------------------------------------------------


def _coerce_value_bytes(kve: Any) -> bytes:
    """Return the raw value bytes from a KV entry handle."""
    if isinstance(kve, (bytes, bytearray)):
        return bytes(kve)
    value = getattr(kve, "value", None)
    if value is None and isinstance(kve, Mapping):
        value = kve.get("value")
    if value is None:
        raise SequenceNumberLedgerEnvelopeError(
            f"KV entry has no .value attribute: "
            f"type={type(kve).__name__}"
        )
    if isinstance(value, str):
        return value.encode("utf-8")
    return bytes(value)


def _coerce_revision(kve: Any) -> int:
    """Read the revision integer from a KV entry handle."""
    if isinstance(kve, (bytes, bytearray)):
        return 0
    revision = getattr(kve, "revision", None)
    if revision is None and isinstance(kve, Mapping):
        revision = kve.get("revision")
    if revision is None:
        return 0
    return int(revision)


def _is_not_found_exception(exc: BaseException) -> bool:
    cls_name = type(exc).__name__
    return (
        "NotFound" in cls_name
        or "DoesNotExist" in cls_name
        or isinstance(exc, KeyError)
    )


_CONFLICT_CLS_MARKERS = (
    "WrongLastSequence",
    "AlreadyExists",
    "KeyExists",
    "Conflict",
    "CAS",
)


def _is_conflict_exception(exc: BaseException) -> bool:
    cls_name = type(exc).__name__
    return any(marker in cls_name for marker in _CONFLICT_CLS_MARKERS)


async def _kv_get_entry(
    kv: Any, key: str
) -> Optional[Any]:
    """Fetch a KV entry; return ``None`` if not found."""
    try:
        result = kv.get(key)
        if hasattr(result, "__await__"):
            result = await result
        return result
    except Exception as exc:
        if _is_not_found_exception(exc):
            return None
        raise


async def _kv_create(kv: Any, key: str, value: bytes) -> int:
    """Create a key (raise conflict if it already exists). Returns
    the new revision.
    """
    create = getattr(kv, "create", None)
    if create is None:
        raise SequenceNumberLedgerError(
            f"KV adapter has no create() method: "
            f"type={type(kv).__name__}"
        )
    try:
        result = create(key, value)
        if hasattr(result, "__await__"):
            result = await result
        return int(result) if not isinstance(result, int) else result
    except Exception as exc:
        if _is_conflict_exception(exc):
            raise SequenceNumberLedgerConcurrencyConflictError(
                f"key {key!r} already exists (create conflict)",
                key=key,
            ) from exc
        raise


async def _kv_update(
    kv: Any, key: str, value: bytes, *, last_revision: int
) -> int:
    """Update a key with optimistic CAS-pin on ``last_revision``.

    Returns the new revision on success. Raises
    :class:`SequenceNumberLedgerConcurrencyConflictError` if the
    CAS-pin failed (someone else updated the cell since the caller
    read it).
    """
    update = getattr(kv, "update", None)
    if update is None:
        raise SequenceNumberLedgerError(
            f"KV adapter has no update() method: "
            f"type={type(kv).__name__}"
        )
    try:
        result = update(key, value, last=last_revision)
        if hasattr(result, "__await__"):
            result = await result
        return int(result) if not isinstance(result, int) else result
    except Exception as exc:
        if _is_conflict_exception(exc):
            raise SequenceNumberLedgerConcurrencyConflictError(
                f"key {key!r} update conflict at "
                f"expected_revision={last_revision}",
                key=key,
                expected_revision=last_revision,
            ) from exc
        raise


# ---------------------------------------------------------------------------
# Async durable ledger
# ---------------------------------------------------------------------------


@dataclass
class NatsKvSequenceNumberLedger:
    """NATS-JetStream-KV-backed durable sequence-number ledger.

    Bound to a specific ``org_id`` at construction. Cross-org
    reads/writes raise
    :class:`SequenceNumberLedgerCrossOrgBoundaryError` instead of
    touching the underlying KV.

    Async surface: callers integrate this ledger into async
    exporter pipelines via :meth:`a_last_seen`, :meth:`a_next_sequence`,
    and :meth:`a_record_export`. A
    :class:`SyncSequenceNumberLedgerAdapter` adapter is provided
    for synchronous callsites (e.g. the legacy
    :class:`~wirelang.federation.caveat_override_export.SequenceNumberLedger`
    Protocol).

    Construction is cheap: pass an open ``KeyValue`` handle from
    nats-py (or a mock that mirrors the same surface). The backend
    performs no network I/O on construction.
    """

    kv: Any
    org_id: str

    def __post_init__(self) -> None:
        # Validate org_id eagerly; the constructor must reject
        # malformed identifiers before they reach the bucket.
        bucket_name_for_org(self.org_id)

    @property
    def bucket_name(self) -> str:
        return bucket_name_for_org(self.org_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _read_cell(
        self, *, route_id: str, chain_hash: str
    ) -> Optional[_LedgerCell]:
        """Read the cell for one pair; return ``None`` if absent.

        Raises :class:`SequenceNumberLedgerEnvelopeError` if the
        cell is present but malformed (poisoned envelope), or if
        the envelope carries a foreign ``org_id``.
        """
        key = key_for_pair(route_id, chain_hash)
        entry = await _kv_get_entry(self.kv, key)
        if entry is None:
            return None
        blob = _coerce_value_bytes(entry)
        revision = _coerce_revision(entry)
        cell = _decode_envelope(blob, revision=revision)
        if cell.org_id != self.org_id:
            raise SequenceNumberLedgerEnvelopeError(
                f"ledger cell at key {key!r} carries "
                f"org_id={cell.org_id!r} but bucket is bound to "
                f"org_id={self.org_id!r}"
            )
        if cell.route_id != route_id:
            raise SequenceNumberLedgerEnvelopeError(
                f"ledger cell at key {key!r} carries "
                f"route_id={cell.route_id!r} but the key path "
                f"says {route_id!r}"
            )
        if cell.chain_hash != chain_hash:
            raise SequenceNumberLedgerEnvelopeError(
                f"ledger cell at key {key!r} carries "
                f"chain_hash={cell.chain_hash!r} but the key path "
                f"says {chain_hash!r}"
            )
        return cell

    def _validate_org_id(
        self, *, requested_org_id: Optional[str]
    ) -> None:
        if requested_org_id is None:
            return
        if not isinstance(requested_org_id, str):
            raise CaveatOverrideExportShapeError(
                f"org_id must be a string or None, got "
                f"type={type(requested_org_id).__name__}"
            )
        if requested_org_id != self.org_id:
            raise SequenceNumberLedgerCrossOrgBoundaryError(
                f"ledger bound to org_id={self.org_id!r}; refusing "
                f"call for org_id={requested_org_id!r}",
                backend_org_id=self.org_id,
                requested_org_id=requested_org_id,
            )

    # ------------------------------------------------------------------
    # Async surface
    # ------------------------------------------------------------------

    async def a_last_seen(
        self,
        *,
        route_id: str,
        chain_hash: str,
        requested_org_id: Optional[str] = None,
    ) -> int:
        """Return the highest sequence_number previously recorded
        for the pair, or ``0`` if none.

        ``requested_org_id``: optional cross-org-boundary cross-check.
        If supplied, MUST equal this ledger's ``org_id``; a mismatch
        raises :class:`SequenceNumberLedgerCrossOrgBoundaryError`.
        """
        self._validate_org_id(requested_org_id=requested_org_id)
        cell = await self._read_cell(
            route_id=route_id, chain_hash=chain_hash
        )
        return 0 if cell is None else cell.last_seen_sequence

    async def a_next_sequence(
        self,
        *,
        route_id: str,
        chain_hash: str,
        requested_org_id: Optional[str] = None,
    ) -> int:
        """Return the next sequence the exporter SHOULD use for the
        pair (``last_seen + 1``).
        """
        last = await self.a_last_seen(
            route_id=route_id,
            chain_hash=chain_hash,
            requested_org_id=requested_org_id,
        )
        return last + 1

    async def a_record_export(
        self,
        *,
        route_id: str,
        chain_hash: str,
        sequence: int,
        recorded_at: Optional[datetime] = None,
        requested_org_id: Optional[str] = None,
    ) -> int:
        """Durably record an export at the given sequence.

        Returns the new KV revision on success.

        Raises:
            :class:`~wirelang.federation.caveat_override_export.CaveatOverrideExportShapeError`:
                if ``sequence`` is not a positive int.
            :class:`~wirelang.federation.caveat_override_export.CaveatOverrideExportReplayError`:
                if ``sequence`` is not strictly greater than the
                recorded last_seen for the pair.
            :class:`SequenceNumberLedgerConcurrencyConflictError`:
                if a concurrent writer landed first. Caller MUST
                re-read and retry.
            :class:`SequenceNumberLedgerCrossOrgBoundaryError`: on
                a foreign ``requested_org_id``.
        """
        self._validate_org_id(requested_org_id=requested_org_id)
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
        ):
            raise CaveatOverrideExportShapeError(
                f"sequence must be int: type={type(sequence).__name__}"
            )
        if sequence < 1:
            raise CaveatOverrideExportShapeError(
                f"sequence must be >= 1: got {sequence}"
            )
        # Validate components by deriving the key (cheap).
        key = key_for_pair(route_id, chain_hash)
        if recorded_at is None:
            recorded_at = datetime.now(timezone.utc)
        if recorded_at.tzinfo is None:
            raise CaveatOverrideExportShapeError(
                f"recorded_at must be timezone-aware: {recorded_at!r}"
            )
        cell = await self._read_cell(
            route_id=route_id, chain_hash=chain_hash
        )
        last_seen = 0 if cell is None else cell.last_seen_sequence
        if sequence <= last_seen:
            raise CaveatOverrideExportReplayError(
                f"sequence {sequence} is not strictly greater than "
                f"last_seen {last_seen} for "
                f"(route_id={route_id!r}, chain_hash={chain_hash!r})",
                route_id=route_id,
                chain_hash=chain_hash,
                last_seen_sequence=last_seen,
                attempted_sequence=sequence,
            )
        blob = _encode_envelope(
            org_id=self.org_id,
            route_id=route_id,
            chain_hash=chain_hash,
            last_seen_sequence=sequence,
            recorded_at=recorded_at,
        )
        if cell is None:
            return await _kv_create(self.kv, key, blob)
        return await _kv_update(
            self.kv, key, blob, last_revision=cell.revision
        )


# ---------------------------------------------------------------------------
# Sync adapter — implements SequenceNumberLedger Protocol
# ---------------------------------------------------------------------------


@dataclass
class SyncSequenceNumberLedgerAdapter:
    """Synchronous adapter that exposes a
    :class:`NatsKvSequenceNumberLedger` as a
    :class:`~wirelang.federation.caveat_override_export.SequenceNumberLedger`.

    Bridges the durable async ledger into the Tag-1 exporter
    surface (which is synchronous). Internally drives the async
    methods to completion via :func:`asyncio.run` on a new event
    loop. **Not safe to call from within an existing event loop**;
    callers running inside ``asyncio`` should use
    :class:`NatsKvSequenceNumberLedger` directly.

    Provided so Tag-1 callsites can swap their default
    :class:`InMemorySequenceNumberLedger` for the durable tier
    without changing the exporter API.
    """

    durable: NatsKvSequenceNumberLedger

    def _run(self, coro: Any) -> Any:
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            raise SequenceNumberLedgerError(
                "SyncSequenceNumberLedgerAdapter cannot be driven "
                "from inside a running event loop; use "
                "NatsKvSequenceNumberLedger directly with await."
            )
        return asyncio.run(coro)

    def next_sequence(
        self, *, route_id: str, chain_hash: str
    ) -> int:
        return self._run(
            self.durable.a_next_sequence(
                route_id=route_id, chain_hash=chain_hash
            )
        )

    def record_export(
        self,
        *,
        route_id: str,
        chain_hash: str,
        sequence: int,
    ) -> None:
        self._run(
            self.durable.a_record_export(
                route_id=route_id,
                chain_hash=chain_hash,
                sequence=sequence,
            )
        )

    def last_seen(
        self, *, route_id: str, chain_hash: str
    ) -> int:
        return self._run(
            self.durable.a_last_seen(
                route_id=route_id, chain_hash=chain_hash
            )
        )


# Defence-in-depth: prove at import-time that the sync adapter
# satisfies the Tag-1 Protocol shape. Mypy / pyright pick this up
# statically; runtime check is a single isinstance with the
# Protocol class (which is a no-op without ``runtime_checkable``,
# so we settle for the explicit method-presence assertion below).
_PROTOCOL_METHODS = ("next_sequence", "record_export", "last_seen")
for _m in _PROTOCOL_METHODS:
    if not callable(getattr(SyncSequenceNumberLedgerAdapter, _m, None)):
        raise RuntimeError(
            f"SyncSequenceNumberLedgerAdapter missing required "
            f"protocol method {_m!r}"
        )


# ---------------------------------------------------------------------------
# Public surface declaration
# ---------------------------------------------------------------------------


__all__ = [
    "BUCKET_CONFIG",
    "BUCKET_NAME_PREFIX",
    "NatsKvSequenceNumberLedger",
    "SequenceNumberLedger",
    "SequenceNumberLedgerConcurrencyConflictError",
    "SequenceNumberLedgerCrossOrgBoundaryError",
    "SequenceNumberLedgerEnvelopeError",
    "SequenceNumberLedgerError",
    "SyncSequenceNumberLedgerAdapter",
    "VALUE_SCHEMA",
    "bucket_name_for_org",
    "key_for_pair",
    "org_id_for_bucket_name",
    "parse_pair_key",
]
