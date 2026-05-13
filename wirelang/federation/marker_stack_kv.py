# SPDX-License-Identifier: Apache-2.0
"""Persistent marker-stack NATS-KV backend (Sprint-8 Tag-4).

Sprint-8 Tag-3 (``wirelang.federation.marker_composition``) shipped
the pure in-memory marker-stack reducer. In production the marker
stack must survive operator-process restarts and be replayable for
cross-org audit-trail recovery. This module is the persistent tier:
an **append-only event-sourced NATS-KV bucket per organisation**
where each marker event is a single key, and the live
``MarkerStack`` is re-constituted by aggregating all events for a
given ``(org_id, capability_token_id)`` pair.

Why event-sourced
-----------------

The Sprint-8 Tag-3 reducer is **deterministic and sort-stable**:
out-of-order arrivals collapse to the same verdict. Persisting
individual events (rather than overwriting a single
``MarkerStack`` blob) is therefore a natural fit:

- Each :meth:`PutMarkerStack` call **appends one event** to the
  bucket under a monotonically-increasing sequence number. Two
  appends for the same token-id never overwrite each other.
- :meth:`GetMarkerStack` reads all events for the token-id and
  hands them to the Sprint-8 Tag-3
  :func:`reduce_marker_stack` for a byte-identical verdict.
- :meth:`WatchMarkerStack` streams new event appends to a
  consumer for live audit-trail recovery.

This mirrors the **Sprint-5 Tag-2 capability-policy backend**
pattern (a single bucket with per-key envelopes) but with two
deliberate differences:

1. **Append-only sequence keys** instead of single-key
   overwrites. Marker events are immutable audit-trail records;
   they accumulate, they don't replace. The reducer absorbs the
   accumulation.
2. **Per-organisation bucket isolation**: each org gets its own
   bucket ``wakir-marker-stack-{org_id}``. Cross-org reads MUST
   go through the Sprint-7 cross-trust-domain bridge surface;
   there is no shared bucket that one org can directly read
   from another.

Bucket identity
---------------

Bucket name: ``wakir-marker-stack-{org_id}`` (deterministically
derived from a validated ``org_id``). ``org_id`` follows the same
permitted-character regex as Sprint-7 ``peer_org`` predicates
(URI-safe ASCII subset, no slashes, no whitespace).

Key schema: ``marker-events/<capability_token_id>/<sequence>``
where ``sequence`` is the monotonically-increasing sequence
number this org has assigned to the event. Sequence numbers are
1-indexed and are **strictly monotonic per token-id**: the first
event for a token-id is sequence ``1``, the second ``2``, and so on.
The backend never re-uses sequence numbers and never overwrites
existing entries; CAS-pin on key creation enforces the invariant.

Event envelope
--------------

Each KV value is a JSON object with these fields:

- ``schema``: ``"wakir.wirelang.marker-stack-event/1"``.
- ``org_id``: the producing org's id (matches the bucket).
- ``capability_token_id``: the token-id this event belongs to.
- ``sequence``: this event's sequence number (defence-in-depth
  duplicate of the KV key suffix).
- ``event_kind``: one of ``"revoke"``, ``"unrevoke"``,
  ``"re_issuance"``, ``"caveat_override"``, ``"bridge_revoked"``.
- ``event_payload``: a JSON object carrying the per-event-kind
  fields (decodes to the corresponding Sprint-8 Tag-3 event
  dataclass).
- ``stack_context``: a JSON object carrying the marker-stack
  identity fields (``minted_at``, ``original_caveat_set``); the
  first event for a token-id ratifies this context, subsequent
  events MUST carry the byte-equal value or
  :class:`MarkerStackContextConflictError` is raised at read.
- ``appended_at``: RFC-3339 UTC timestamp of when this event
  was appended to the bucket (operator-side bookkeeping; not
  the event's domain ``event_at``).

Cross-trust-domain isolation
----------------------------

Each org operates against its own
:class:`NatsKvMarkerStackBackend` instance, bound to a specific
``org_id`` at construction time. Reads against the wrong
``org_id`` (e.g. a token-id from Org-B handed to an Org-A
backend) return :class:`MarkerStackCrossOrgBoundaryError`
without I/O — the org-id mismatch is a hard refusal, not a
silent empty stack. Cross-org reads MUST go through the
explicit Sprint-7 ``SpiffeCrossTrustDomainBridge`` /
``MultiOrgAttestationEnvelope`` surfaces, which are out of
scope for this module.

Reducer integration
-------------------

:meth:`GetMarkerStack` returns a fully-constituted
:class:`MarkerStack` ready to hand to the Sprint-8 Tag-3
:func:`reduce_marker_stack`. The verdict is byte-identical to
what an in-memory caller would have computed from the same
sequence of events: the persistent tier is a **transport layer
for the same reducer**, never a replacement.

Phase-2 Sprint-8 Tag-4 boundary
-------------------------------

- This module ships **persistent storage and live recovery**.
  It does NOT introduce new reducer rules; the Sprint-8 Tag-3
  reducer is byte-unchanged.
- This module enforces **per-org bucket isolation**; it does
  NOT implement cross-org bridge operations. Cross-org reads
  are explicit operator-deliberate gestures wired through the
  Sprint-7 bridge surface.
- This module persists events with **append-only semantics**;
  there is no UPDATE or DELETE on individual events. Operators
  who need to redact a poisoned event MUST issue a PURGE on the
  entire token-id key-space (a separate operator-tool, out of
  scope for Tag-4) and re-bootstrap. The audit-trail invariant
  forbids silent event mutation.
- This module does NOT bake CAS-pin on event-payload contents;
  the CAS-pin invariant is on the **sequence number** axis only
  (no two events share a sequence per token-id).

Sandbox boundary
----------------

Live NATS connections are operator-hand (per
``feedback_sandbox_host_trennung.md`` memory). All tests in this
module run against an in-memory mock that mirrors the Sprint-5
Tag-2 :class:`_MockKv` shape.

References
----------

- Reducer source: Sprint-8 Tag-3
  :mod:`wirelang.federation.marker_composition`.
- Pattern source: Sprint-5 Tag-2
  :mod:`wirelang.schemas.capability_policy_nats_kv_backend`.
- Cross-trust-domain bridge: Sprint-7 Tag-3
  ``SpiffeCrossTrustDomainBridge``.
- Spec: ``wirelang/specs/schema-registry-spec.md`` §5.16
  (added in v0.31.0).
- Reza Persona §2 (Capability-Token-Layer: Reza-Owner-Domain).
"""

from __future__ import annotations

import enum
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import (
    Any,
    AsyncIterator,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from wirelang.federation.cross_org_attenuation_verifier import (
    BridgeRevocationMarker,
)
from wirelang.federation.marker_composition import (
    AuditTraceEntry,
    BridgeRevokedEvent,
    CaveatOverrideEvent,
    CompositionVerdict,
    MarkerStack,
    ReIssuanceEvent,
    RevokeEvent,
    UnrevokeEvent,
    reduce_marker_stack,
)
from wirelang.federation.n2_evaluator import FederationPredicateError


# ---------------------------------------------------------------------------
# Bucket identity / key derivation
# ---------------------------------------------------------------------------


#: Bucket name prefix; the full bucket name is
#: ``BUCKET_NAME_PREFIX + org_id``.
BUCKET_NAME_PREFIX = "wakir-marker-stack-"

#: Documented bucket configuration. Drift-policy: any deviation
#: between the live cluster and these values is reported as drift,
#: never auto-corrected (same contract as Sprint-5 Tag-2).
BUCKET_CONFIG: Mapping[str, Any] = {
    "description": "Wirelang persistent marker-stack event log (Phase-2)",
    "history": 1,
    "ttl_seconds": 0,
    "max_value_size": 32_768,
    "storage": "file",
    "replicas": 1,
}

#: Schema URI embedded in every value envelope.
VALUE_SCHEMA = "wakir.wirelang.marker-stack-event/1"

#: Permitted-character regex for ``org_id`` and
#: ``capability_token_id`` (URI-safe ASCII subset, no slashes).
_IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$")

_KEY_PREFIX = "marker-events/"


def bucket_name_for_org(org_id: str) -> str:
    """Return the canonical bucket name for ``org_id``.

    Raises :class:`ValueError` if ``org_id`` does not match the
    permitted-character regex. The derivation is deterministic
    and bijective: ``bucket_name_for_org`` and
    :func:`org_id_for_bucket_name` round-trip byte-equal.
    """
    if not isinstance(org_id, str) or not org_id:
        raise ValueError(
            f"org_id must be a non-empty string, got {org_id!r}"
        )
    if not _IDENT_RE.match(org_id):
        raise ValueError(
            f"org_id {org_id!r} does not match permitted-character "
            f"pattern {_IDENT_RE.pattern!r}"
        )
    return f"{BUCKET_NAME_PREFIX}{org_id}"


def org_id_for_bucket_name(bucket_name: str) -> str:
    """Inverse of :func:`bucket_name_for_org`. Raises
    :class:`ValueError` for a non-matching prefix.
    """
    if not isinstance(bucket_name, str):
        raise ValueError(f"bucket_name must be a string, got {bucket_name!r}")
    if not bucket_name.startswith(BUCKET_NAME_PREFIX):
        raise ValueError(
            f"bucket_name must start with {BUCKET_NAME_PREFIX!r}: "
            f"{bucket_name!r}"
        )
    org_id = bucket_name[len(BUCKET_NAME_PREFIX):]
    if not _IDENT_RE.match(org_id):
        raise ValueError(
            f"bucket_name carries malformed org_id {org_id!r}"
        )
    return org_id


def key_for_event(capability_token_id: str, sequence: int) -> str:
    """Derive the canonical KV key for an event.

    Format: ``marker-events/<capability_token_id>/<sequence>``.
    Sequence is 1-indexed and zero-padded to 12 digits so KV
    list-key iteration returns events in append order without
    a sort step.

    Raises :class:`ValueError` for malformed components.
    """
    if not isinstance(capability_token_id, str) or not capability_token_id:
        raise ValueError(
            f"capability_token_id must be a non-empty string, got "
            f"{capability_token_id!r}"
        )
    if not _IDENT_RE.match(capability_token_id):
        raise ValueError(
            f"capability_token_id {capability_token_id!r} does not "
            f"match permitted-character pattern {_IDENT_RE.pattern!r}"
        )
    if not isinstance(sequence, int) or sequence < 1:
        raise ValueError(
            f"sequence must be a positive int, got {sequence!r}"
        )
    return f"{_KEY_PREFIX}{capability_token_id}/{sequence:012d}"


def parse_event_key(key: str) -> Tuple[str, int]:
    """Inverse of :func:`key_for_event`. Returns
    ``(capability_token_id, sequence)``. Raises
    :class:`ValueError` for a malformed key shape.
    """
    if not isinstance(key, str) or not key.startswith(_KEY_PREFIX):
        raise ValueError(
            f"key must start with {_KEY_PREFIX!r}, got {key!r}"
        )
    rest = key[len(_KEY_PREFIX):]
    parts = rest.split("/")
    if len(parts) != 2:
        raise ValueError(
            f"key must have shape marker-events/<token>/<seq>: {key!r}"
        )
    capability_token_id, sequence_raw = parts
    if not capability_token_id:
        raise ValueError(f"key carries empty token-id: {key!r}")
    if not _IDENT_RE.match(capability_token_id):
        raise ValueError(
            f"key carries malformed token-id {capability_token_id!r}"
        )
    try:
        sequence = int(sequence_raw, 10)
    except ValueError as exc:
        raise ValueError(
            f"key carries non-integer sequence {sequence_raw!r}"
        ) from exc
    if sequence < 1:
        raise ValueError(
            f"key carries non-positive sequence {sequence!r}"
        )
    return capability_token_id, sequence


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MarkerStackBackendError(Exception):
    """Base class for marker-stack backend failures."""


class MarkerStackEnvelopeError(MarkerStackBackendError):
    """Raised when a KV value cannot be parsed or fails the
    schema-shape contract. A poisoned envelope is never silently
    swallowed; it surfaces from :meth:`GetMarkerStack` so an
    operator can act.
    """


class MarkerStackArgumentError(MarkerStackBackendError):
    """Raised when an argument shape gate fails (malformed
    ``org_id``, ``capability_token_id``, missing event field).
    """


class MarkerStackConcurrencyConflictError(MarkerStackBackendError):
    """Raised when an :meth:`PutMarkerStack` append is rejected
    because another writer landed first at the same sequence.

    The caller MUST re-read the current stack, recompute the next
    sequence, and retry. Optimistic concurrency: no implicit
    retry, no silent overwrite — the conflict is surfaced so the
    audit-trail invariant (one event per sequence) is preserved.
    """

    def __init__(
        self,
        message: str,
        *,
        key: Optional[str] = None,
        expected_sequence: Optional[int] = None,
        observed_max_sequence: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.key = key
        self.expected_sequence = expected_sequence
        self.observed_max_sequence = observed_max_sequence


class MarkerStackCrossOrgBoundaryError(MarkerStackBackendError):
    """Raised when a caller asks a backend bound to ``org_id=A`` to
    read or write events under ``org_id=B``.

    Cross-org reads are explicit operator-deliberate gestures that
    flow through the Sprint-7 cross-trust-domain bridge surface
    (``SpiffeCrossTrustDomainBridge`` /
    ``MultiOrgAttestationEnvelope``). A direct cross-bucket read
    via :class:`NatsKvMarkerStackBackend` is a configuration
    error and is surfaced as this typed exception.
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


class MarkerStackContextConflictError(MarkerStackBackendError):
    """Raised when subsequent events for a token-id carry a
    ``stack_context`` (``minted_at`` / ``original_caveat_set``)
    that does not byte-match the first observed event's context.

    The marker-stack identity is fixed at first event; later
    events MUST carry the same identity or the audit-trail is
    inconsistent. This is a semantic conflict, not a transport
    error.
    """


# ---------------------------------------------------------------------------
# Event-payload envelope + decode
# ---------------------------------------------------------------------------


class MarkerEventKind(enum.Enum):
    """Closed enumeration of supported event kinds for the
    persistent backend.

    Byte-equal mirror of the five Sprint-8 Tag-3 event-dataclass
    families. The string values are stable wire identifiers and
    MUST NOT be renamed without a major-version envelope bump.
    """

    REVOKE = "revoke"
    UNREVOKE = "unrevoke"
    RE_ISSUANCE = "re_issuance"
    CAVEAT_OVERRIDE = "caveat_override"
    BRIDGE_REVOKED = "bridge_revoked"


# Type alias: any of the five Sprint-8 Tag-3 event dataclasses.
MarkerEvent = (
    RevokeEvent
    | UnrevokeEvent
    | ReIssuanceEvent
    | CaveatOverrideEvent
    | BridgeRevokedEvent
)


@dataclass(frozen=True)
class StackContext:
    """The marker-stack identity carried on every event envelope.

    Persisted on the first event for a token-id and cross-checked
    on every subsequent event. A mismatch raises
    :class:`MarkerStackContextConflictError`.
    """

    minted_at: datetime
    original_caveat_set: Optional[
        Tuple[Tuple[str, Tuple[object, ...]], ...]
    ]


@dataclass(frozen=True)
class MarkerEventRecord:
    """Internal record assembled from a decoded event envelope.

    Carries the decoded :class:`MarkerEvent`, the
    :class:`StackContext`, plus the bookkeeping fields surfaced
    on watch-stream events (``sequence``, ``appended_at``).
    """

    org_id: str
    capability_token_id: str
    sequence: int
    event_kind: MarkerEventKind
    event: MarkerEvent
    stack_context: StackContext
    appended_at: datetime


@dataclass(frozen=True)
class MarkerStackVersion:
    """Returned from :meth:`PutMarkerStack` for the appended event.

    Carries the sequence number assigned to the event and the
    appended-at instant. Operators use this for receipt /
    correlation; the sequence is the same monotonic axis the
    backend uses internally for CAS-pin.
    """

    capability_token_id: str
    sequence: int
    appended_at: datetime


# ---------------------------------------------------------------------------
# JSON encode / decode helpers
# ---------------------------------------------------------------------------


def _rfc3339(dt: datetime) -> str:
    """Encode a timezone-aware datetime as an RFC-3339 UTC string."""
    if dt.tzinfo is None:
        raise MarkerStackArgumentError(
            f"datetime must be timezone-aware: {dt!r}"
        )
    aware = dt.astimezone(timezone.utc)
    return aware.strftime("%Y-%m-%dT%H:%M:%S.%f").rstrip("0").rstrip(".") + "Z"


def _parse_rfc3339(s: Any) -> datetime:
    """Decode an RFC-3339 UTC string into a timezone-aware
    datetime. Raises :class:`MarkerStackEnvelopeError` on failure.
    """
    if not isinstance(s, str):
        raise MarkerStackEnvelopeError(
            f"datetime field must be a string, got type={type(s).__name__}"
        )
    try:
        # Python's fromisoformat handles "+00:00"; "Z" needs replacement.
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MarkerStackEnvelopeError(
            f"datetime field failed to parse: {s!r} ({exc})"
        ) from exc


def _encode_caveat_set(
    cs: Optional[Tuple[Tuple[str, Tuple[object, ...]], ...]],
) -> Optional[List[List[Any]]]:
    """Encode an optional caveat set into a JSON-ready list of
    ``[predicate, args]`` pairs. ``None`` is preserved.
    """
    if cs is None:
        return None
    result: List[List[Any]] = []
    for entry in cs:
        if not (
            isinstance(entry, tuple)
            and len(entry) == 2
            and isinstance(entry[0], str)
            and isinstance(entry[1], tuple)
        ):
            raise MarkerStackArgumentError(
                f"caveat-set entry must be (predicate, args-tuple): {entry!r}"
            )
        predicate, args = entry
        result.append([predicate, list(args)])
    return result


def _decode_caveat_set(
    raw: Any,
) -> Optional[Tuple[Tuple[str, Tuple[object, ...]], ...]]:
    """Inverse of :func:`_encode_caveat_set`. Returns ``None`` for
    explicit ``None`` in the envelope; raises
    :class:`MarkerStackEnvelopeError` for malformed shapes.
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise MarkerStackEnvelopeError(
            f"caveat-set must be a JSON array or null: type="
            f"{type(raw).__name__}"
        )
    decoded: List[Tuple[str, Tuple[object, ...]]] = []
    for i, entry in enumerate(raw):
        if not (
            isinstance(entry, list)
            and len(entry) == 2
            and isinstance(entry[0], str)
            and isinstance(entry[1], list)
        ):
            raise MarkerStackEnvelopeError(
                f"caveat-set[{i}] must be a [predicate, args-array] "
                f"pair: got {entry!r}"
            )
        predicate, args = entry
        decoded.append((predicate, tuple(args)))
    return tuple(decoded)


def _event_kind_for(event: MarkerEvent) -> MarkerEventKind:
    """Map a Sprint-8 Tag-3 event dataclass to its wire enum."""
    if isinstance(event, RevokeEvent):
        return MarkerEventKind.REVOKE
    if isinstance(event, UnrevokeEvent):
        return MarkerEventKind.UNREVOKE
    if isinstance(event, ReIssuanceEvent):
        return MarkerEventKind.RE_ISSUANCE
    if isinstance(event, CaveatOverrideEvent):
        return MarkerEventKind.CAVEAT_OVERRIDE
    if isinstance(event, BridgeRevokedEvent):
        return MarkerEventKind.BRIDGE_REVOKED
    raise MarkerStackArgumentError(
        f"event must be a Sprint-8 Tag-3 marker event, got "
        f"type={type(event).__name__}"
    )


def _encode_event_payload(event: MarkerEvent) -> Mapping[str, Any]:
    """Encode an event dataclass into a JSON-ready payload mapping.

    The encoding is reversible by :func:`_decode_event_payload` and
    byte-equal across repeated calls (no clock, no mutation).
    """
    if isinstance(event, RevokeEvent):
        return {
            "event_at": _rfc3339(event.event_at),
            "revocation_reason": event.revocation_reason,
            "tie_break": event.tie_break,
            "wat_anchor_manifest_id": event.wat_anchor_manifest_id,
        }
    if isinstance(event, UnrevokeEvent):
        return {
            "event_at": _rfc3339(event.event_at),
            "previous_revoked_at": _rfc3339(event.previous_revoked_at),
            "unrevoke_reason": event.unrevoke_reason,
            "tie_break": event.tie_break,
            "wat_anchor_manifest_id": event.wat_anchor_manifest_id,
        }
    if isinstance(event, ReIssuanceEvent):
        return {
            "event_at": _rfc3339(event.event_at),
            "new_token_id": event.new_token_id,
            "re_issuance_reason": event.re_issuance_reason,
            "tie_break": event.tie_break,
            "wat_anchor_manifest_id": event.wat_anchor_manifest_id,
        }
    if isinstance(event, CaveatOverrideEvent):
        return {
            "event_at": _rfc3339(event.event_at),
            "original_caveat_set": _encode_caveat_set(
                event.original_caveat_set
            ),
            "narrowed_caveat_set": _encode_caveat_set(
                event.narrowed_caveat_set
            ),
            "override_reason": event.override_reason,
            "tie_break": event.tie_break,
            "wat_anchor_manifest_id": event.wat_anchor_manifest_id,
        }
    if isinstance(event, BridgeRevokedEvent):
        return {
            "marker": {
                "source_ftd_id": event.marker.source_ftd_id,
                "target_ftd_id": event.marker.target_ftd_id,
                "revoked_at": _rfc3339(event.marker.revoked_at),
            },
            "tie_break": event.tie_break,
            "wat_anchor_manifest_id": event.wat_anchor_manifest_id,
        }
    raise MarkerStackArgumentError(
        f"event must be a Sprint-8 Tag-3 marker event, got "
        f"type={type(event).__name__}"
    )


def _decode_event_payload(
    kind: MarkerEventKind, payload: Mapping[str, Any]
) -> MarkerEvent:
    """Inverse of :func:`_encode_event_payload`. Raises
    :class:`MarkerStackEnvelopeError` on shape mismatch.
    """
    if not isinstance(payload, Mapping):
        raise MarkerStackEnvelopeError(
            f"event_payload must be a JSON object: type="
            f"{type(payload).__name__}"
        )
    try:
        if kind is MarkerEventKind.REVOKE:
            return RevokeEvent(
                event_at=_parse_rfc3339(payload["event_at"]),
                revocation_reason=payload.get("revocation_reason"),
                tie_break=int(payload.get("tie_break", 0)),
                wat_anchor_manifest_id=payload.get(
                    "wat_anchor_manifest_id"
                ),
            )
        if kind is MarkerEventKind.UNREVOKE:
            return UnrevokeEvent(
                event_at=_parse_rfc3339(payload["event_at"]),
                previous_revoked_at=_parse_rfc3339(
                    payload["previous_revoked_at"]
                ),
                unrevoke_reason=payload.get("unrevoke_reason"),
                tie_break=int(payload.get("tie_break", 0)),
                wat_anchor_manifest_id=payload.get(
                    "wat_anchor_manifest_id"
                ),
            )
        if kind is MarkerEventKind.RE_ISSUANCE:
            return ReIssuanceEvent(
                event_at=_parse_rfc3339(payload["event_at"]),
                new_token_id=payload["new_token_id"],
                re_issuance_reason=payload.get("re_issuance_reason"),
                tie_break=int(payload.get("tie_break", 0)),
                wat_anchor_manifest_id=payload.get(
                    "wat_anchor_manifest_id"
                ),
            )
        if kind is MarkerEventKind.CAVEAT_OVERRIDE:
            return CaveatOverrideEvent(
                event_at=_parse_rfc3339(payload["event_at"]),
                original_caveat_set=_decode_caveat_set(
                    payload["original_caveat_set"]
                ),
                narrowed_caveat_set=_decode_caveat_set(
                    payload["narrowed_caveat_set"]
                ),
                override_reason=payload.get("override_reason"),
                tie_break=int(payload.get("tie_break", 0)),
                wat_anchor_manifest_id=payload.get(
                    "wat_anchor_manifest_id"
                ),
            )
        if kind is MarkerEventKind.BRIDGE_REVOKED:
            marker_raw = payload["marker"]
            if not isinstance(marker_raw, Mapping):
                raise MarkerStackEnvelopeError(
                    f"bridge_revoked.marker must be a JSON object: "
                    f"type={type(marker_raw).__name__}"
                )
            marker = BridgeRevocationMarker(
                source_ftd_id=marker_raw["source_ftd_id"],
                target_ftd_id=marker_raw["target_ftd_id"],
                revoked_at=_parse_rfc3339(marker_raw["revoked_at"]),
            )
            return BridgeRevokedEvent(
                marker=marker,
                tie_break=int(payload.get("tie_break", 0)),
                wat_anchor_manifest_id=payload.get(
                    "wat_anchor_manifest_id"
                ),
            )
    except KeyError as exc:
        raise MarkerStackEnvelopeError(
            f"event_payload missing required field for kind="
            f"{kind.value}: {exc}"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise MarkerStackEnvelopeError(
            f"event_payload shape error for kind={kind.value}: {exc}"
        ) from exc
    raise MarkerStackEnvelopeError(
        f"unknown event kind: {kind!r}"
    )


def _encode_envelope(
    *,
    org_id: str,
    capability_token_id: str,
    sequence: int,
    event: MarkerEvent,
    stack_context: StackContext,
    appended_at: datetime,
) -> bytes:
    """Serialise an event into a deterministic JSON envelope.

    The encoder uses sorted-key + compact-separator output so the
    bytes are reproducible byte-for-byte per caller, in line with
    the Sprint-5 Tag-2 envelope contract.
    """
    kind = _event_kind_for(event)
    payload: dict = {
        "schema": VALUE_SCHEMA,
        "org_id": org_id,
        "capability_token_id": capability_token_id,
        "sequence": sequence,
        "event_kind": kind.value,
        "event_payload": dict(_encode_event_payload(event)),
        "stack_context": {
            "minted_at": _rfc3339(stack_context.minted_at),
            "original_caveat_set": _encode_caveat_set(
                stack_context.original_caveat_set
            ),
        },
        "appended_at": _rfc3339(appended_at),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _decode_envelope(blob: bytes) -> MarkerEventRecord:
    """Inverse of :func:`_encode_envelope`.

    Raises :class:`MarkerStackEnvelopeError` on any shape failure
    (unparseable JSON, wrong schema URI, missing field, etc.).
    """
    if not isinstance(blob, (bytes, bytearray)):
        raise MarkerStackEnvelopeError(
            f"envelope blob must be bytes, got type={type(blob).__name__}"
        )
    try:
        payload = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarkerStackEnvelopeError(
            f"envelope is not valid JSON: {exc!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise MarkerStackEnvelopeError(
            f"envelope top-level must be a JSON object: type="
            f"{type(payload).__name__}"
        )
    schema = payload.get("schema")
    if schema != VALUE_SCHEMA:
        raise MarkerStackEnvelopeError(
            f"envelope schema must be {VALUE_SCHEMA!r}, got {schema!r}"
        )
    for required in (
        "org_id",
        "capability_token_id",
        "sequence",
        "event_kind",
        "event_payload",
        "stack_context",
        "appended_at",
    ):
        if required not in payload:
            raise MarkerStackEnvelopeError(
                f"envelope missing required field: {required!r}"
            )
    org_id = payload["org_id"]
    capability_token_id = payload["capability_token_id"]
    sequence_raw = payload["sequence"]
    if not isinstance(sequence_raw, int) or sequence_raw < 1:
        raise MarkerStackEnvelopeError(
            f"envelope sequence must be positive int, got {sequence_raw!r}"
        )
    try:
        kind = MarkerEventKind(payload["event_kind"])
    except ValueError as exc:
        raise MarkerStackEnvelopeError(
            f"envelope event_kind is unknown: {payload['event_kind']!r}"
        ) from exc
    event = _decode_event_payload(kind, payload["event_payload"])
    stack_context_raw = payload["stack_context"]
    if not isinstance(stack_context_raw, Mapping):
        raise MarkerStackEnvelopeError(
            f"envelope stack_context must be a JSON object: type="
            f"{type(stack_context_raw).__name__}"
        )
    try:
        minted_at = _parse_rfc3339(stack_context_raw["minted_at"])
    except KeyError as exc:
        raise MarkerStackEnvelopeError(
            f"envelope stack_context missing minted_at: {exc}"
        ) from exc
    original_caveat_set = _decode_caveat_set(
        stack_context_raw.get("original_caveat_set")
    )
    appended_at = _parse_rfc3339(payload["appended_at"])
    return MarkerEventRecord(
        org_id=org_id,
        capability_token_id=capability_token_id,
        sequence=sequence_raw,
        event_kind=kind,
        event=event,
        stack_context=StackContext(
            minted_at=minted_at,
            original_caveat_set=original_caveat_set,
        ),
        appended_at=appended_at,
    )


# ---------------------------------------------------------------------------
# Watch-event surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarkerStackWatchEvent:
    """A single decoded append observed on the watch-stream.

    Fields:

    - ``capability_token_id``: the token-id this event belongs to.
    - ``record``: the decoded :class:`MarkerEventRecord`.
    - ``revision``: the underlying KV revision at which this
      event was observed. Monotonically increasing per bucket.

    Marker-stack watch-stream is append-only; there are no DELETE
    or PURGE events emitted to the consumer (substrate-level
    operator PURGE is out of scope for the watch contract).
    """

    capability_token_id: str
    record: MarkerEventRecord
    revision: int


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
        raise MarkerStackEnvelopeError(
            f"KV entry has no .value attribute: type={type(kve).__name__}"
        )
    if isinstance(value, str):
        return value.encode("utf-8")
    return bytes(value)


def _coerce_revision_from_entry(kve: Any) -> int:
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
)


def _is_conflict_exception(exc: BaseException) -> bool:
    cls_name = type(exc).__name__
    return any(marker in cls_name for marker in _CONFLICT_CLS_MARKERS)


async def _list_keys(kv: Any) -> List[str]:
    """List all keys in the bucket; mirrors the Sprint-5 Tag-2 helper."""
    if hasattr(kv, "keys"):
        result = kv.keys()
        if hasattr(result, "__await__"):
            result = await result
        return list(result)
    raise MarkerStackBackendError(
        f"KV handle has no keys() method: type={type(kv).__name__}"
    )


async def _kv_create(kv: Any, key: str, value: bytes) -> int:
    """Create a key (raise if it already exists). Mirrors the
    nats-py ``create`` contract; falls back to ``put`` if the
    adapter does not expose ``create``.

    Returns the KV revision on success.
    """
    create = getattr(kv, "create", None)
    if create is not None:
        try:
            revision = create(key, value)
            if hasattr(revision, "__await__"):
                revision = await revision
            return int(revision) if not isinstance(revision, int) else revision
        except Exception as exc:
            if _is_conflict_exception(exc):
                raise MarkerStackConcurrencyConflictError(
                    f"key {key!r} already exists (create conflict)",
                    key=key,
                ) from exc
            raise
    # Fallback: ``put`` with explicit absence check is not atomic
    # against concurrent writers; this path is mock-only and
    # production deployments should always expose ``create``.
    get = getattr(kv, "get", None)
    if get is None:
        raise MarkerStackBackendError(
            "KV adapter has neither create() nor get(); append "
            "semantics cannot be enforced"
        )
    try:
        existing = get(key)
        if hasattr(existing, "__await__"):
            existing = await existing
        if existing is not None:
            raise MarkerStackConcurrencyConflictError(
                f"key {key!r} already exists (put-fallback conflict)",
                key=key,
            )
    except Exception as exc:
        if not _is_not_found_exception(exc):
            raise
    revision = kv.put(key, value)
    if hasattr(revision, "__await__"):
        revision = await revision
    return int(revision) if not isinstance(revision, int) else revision


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


@dataclass
class NatsKvMarkerStackBackend:
    """NATS-JetStream-KV-backed persistent marker-stack backend.

    Bound to a specific ``org_id`` at construction. Cross-org
    reads/writes raise :class:`MarkerStackCrossOrgBoundaryError`
    instead of touching the underlying KV.

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
    # PutMarkerStack — append-only single-event write
    # ------------------------------------------------------------------

    async def put_marker_stack(
        self,
        *,
        org_id: str,
        capability_token_id: str,
        marker_event: MarkerEvent,
        stack_context: StackContext,
        appended_at: Optional[datetime] = None,
        expected_next_sequence: Optional[int] = None,
    ) -> MarkerStackVersion:
        """Append one event to the marker-stack log.

        The append is atomic on the underlying KV ``create``
        contract: two concurrent writers cannot both succeed at
        the same sequence (the second raises
        :class:`MarkerStackConcurrencyConflictError`).

        Arguments:
            org_id: must equal this backend's ``org_id``;
                cross-org appends raise
                :class:`MarkerStackCrossOrgBoundaryError`.
            capability_token_id: the token this event belongs to.
            marker_event: a Sprint-8 Tag-3 event dataclass.
            stack_context: the marker-stack identity. Validated
                against any prior events for this token-id; a
                mismatch raises
                :class:`MarkerStackContextConflictError`.
            appended_at: bookkeeping wall-clock for the append.
                MUST be timezone-aware. Defaults to ``datetime.now(
                timezone.utc)`` — but tests SHOULD pass an explicit
                value for determinism.
            expected_next_sequence: if supplied, the optimistic
                concurrency hint. The append succeeds iff the
                live stack's next sequence equals this value;
                otherwise raises
                :class:`MarkerStackConcurrencyConflictError`.
                If omitted, the backend computes the next
                sequence from the live stack at call time.
        """
        if not isinstance(org_id, str) or not org_id:
            raise MarkerStackArgumentError(
                f"org_id must be a non-empty string, got {org_id!r}"
            )
        if org_id != self.org_id:
            raise MarkerStackCrossOrgBoundaryError(
                f"backend bound to org_id={self.org_id!r}; refusing put "
                f"for org_id={org_id!r}",
                backend_org_id=self.org_id,
                requested_org_id=org_id,
            )
        if not isinstance(capability_token_id, str) or not capability_token_id:
            raise MarkerStackArgumentError(
                f"capability_token_id must be a non-empty string, got "
                f"{capability_token_id!r}"
            )
        if not _IDENT_RE.match(capability_token_id):
            raise MarkerStackArgumentError(
                f"capability_token_id {capability_token_id!r} does not "
                f"match permitted-character pattern {_IDENT_RE.pattern!r}"
            )
        if not isinstance(stack_context, StackContext):
            raise MarkerStackArgumentError(
                f"stack_context must be StackContext: type="
                f"{type(stack_context).__name__}"
            )
        # Compute live next-sequence and check stack-context
        # consistency in one pass over existing events.
        live_records = await self._read_token_events(capability_token_id)
        observed_max_sequence = (
            max((r.sequence for r in live_records), default=0)
        )
        if live_records:
            first = live_records[0]
            if first.stack_context != stack_context:
                raise MarkerStackContextConflictError(
                    f"stack_context mismatch for token-id "
                    f"{capability_token_id!r}: first-event context "
                    f"{first.stack_context!r} vs proposed "
                    f"{stack_context!r}"
                )
        computed_next_sequence = observed_max_sequence + 1
        if expected_next_sequence is not None:
            if not isinstance(expected_next_sequence, int):
                raise MarkerStackArgumentError(
                    f"expected_next_sequence must be int, got "
                    f"{expected_next_sequence!r}"
                )
            if expected_next_sequence != computed_next_sequence:
                raise MarkerStackConcurrencyConflictError(
                    f"expected_next_sequence={expected_next_sequence} but "
                    f"computed_next_sequence={computed_next_sequence} for "
                    f"token-id {capability_token_id!r}",
                    expected_sequence=expected_next_sequence,
                    observed_max_sequence=observed_max_sequence,
                )
        sequence = computed_next_sequence
        # Validate the event shape by mapping it to the wire enum
        # (this raises MarkerStackArgumentError for unknown types).
        _event_kind_for(marker_event)
        if appended_at is None:
            appended_at = datetime.now(timezone.utc)
        if appended_at.tzinfo is None:
            raise MarkerStackArgumentError(
                f"appended_at must be timezone-aware: {appended_at!r}"
            )
        key = key_for_event(capability_token_id, sequence)
        blob = _encode_envelope(
            org_id=self.org_id,
            capability_token_id=capability_token_id,
            sequence=sequence,
            event=marker_event,
            stack_context=stack_context,
            appended_at=appended_at,
        )
        await _kv_create(self.kv, key, blob)
        return MarkerStackVersion(
            capability_token_id=capability_token_id,
            sequence=sequence,
            appended_at=appended_at,
        )

    # ------------------------------------------------------------------
    # GetMarkerStack — re-constitute the stack from event-log
    # ------------------------------------------------------------------

    async def get_marker_stack(
        self,
        *,
        org_id: str,
        capability_token_id: str,
    ) -> Optional[MarkerStack]:
        """Re-constitute the :class:`MarkerStack` for one token.

        Returns ``None`` if no events have been logged for this
        token-id. The returned stack is ready to hand to the
        Sprint-8 Tag-3 :func:`reduce_marker_stack`.

        Raises:
            :class:`MarkerStackCrossOrgBoundaryError`: if
                ``org_id`` does not match this backend's
                ``org_id``.
            :class:`MarkerStackContextConflictError`: if events
                for the token-id carry inconsistent
                stack-context fields.
            :class:`MarkerStackEnvelopeError`: if any event
                envelope cannot be decoded.
        """
        if not isinstance(org_id, str) or not org_id:
            raise MarkerStackArgumentError(
                f"org_id must be a non-empty string, got {org_id!r}"
            )
        if org_id != self.org_id:
            raise MarkerStackCrossOrgBoundaryError(
                f"backend bound to org_id={self.org_id!r}; refusing get "
                f"for org_id={org_id!r}",
                backend_org_id=self.org_id,
                requested_org_id=org_id,
            )
        if not isinstance(capability_token_id, str) or not capability_token_id:
            raise MarkerStackArgumentError(
                f"capability_token_id must be a non-empty string, got "
                f"{capability_token_id!r}"
            )
        records = await self._read_token_events(capability_token_id)
        if not records:
            return None
        # Stack-context cross-check (the first event's context is
        # authoritative; subsequent events MUST byte-match).
        first = records[0]
        for r in records[1:]:
            if r.stack_context != first.stack_context:
                raise MarkerStackContextConflictError(
                    f"stack_context mismatch in event log for "
                    f"token-id {capability_token_id!r}: first-event "
                    f"context {first.stack_context!r} vs sequence "
                    f"{r.sequence} context {r.stack_context!r}"
                )
        events = tuple(r.event for r in records)
        return MarkerStack(
            token_id=capability_token_id,
            minted_at=first.stack_context.minted_at,
            original_caveat_set=first.stack_context.original_caveat_set,
            events=events,
        )

    # ------------------------------------------------------------------
    # ListMarkerStacks — token-ids known to this org
    # ------------------------------------------------------------------

    async def list_marker_stacks(
        self,
        *,
        org_id: str,
        prefix: Optional[str] = None,
    ) -> List[str]:
        """List the capability-token ids known to this org's bucket.

        Arguments:
            org_id: must equal this backend's ``org_id``.
            prefix: optional kebab-case ASCII prefix; only
                token-ids starting with this string are returned.

        Returns a sorted list of distinct token-ids.
        """
        if not isinstance(org_id, str) or not org_id:
            raise MarkerStackArgumentError(
                f"org_id must be a non-empty string, got {org_id!r}"
            )
        if org_id != self.org_id:
            raise MarkerStackCrossOrgBoundaryError(
                f"backend bound to org_id={self.org_id!r}; refusing list "
                f"for org_id={org_id!r}",
                backend_org_id=self.org_id,
                requested_org_id=org_id,
            )
        if prefix is not None and not isinstance(prefix, str):
            raise MarkerStackArgumentError(
                f"prefix must be a string or None, got type="
                f"{type(prefix).__name__}"
            )
        keys = await _list_keys(self.kv)
        token_ids: set[str] = set()
        for key in keys:
            try:
                token_id, _ = parse_event_key(key)
            except ValueError:
                # Foreign key in the bucket — skip silently. A
                # poisoned shape is the operator's problem to
                # purge; we don't want a single bad key to break
                # listing of well-formed token-ids.
                continue
            if prefix is not None and not token_id.startswith(prefix):
                continue
            token_ids.add(token_id)
        return sorted(token_ids)

    # ------------------------------------------------------------------
    # WatchMarkerStack — live append-stream per token-id
    # ------------------------------------------------------------------

    async def watch_marker_stack(
        self,
        *,
        org_id: str,
        capability_token_id: str,
    ) -> AsyncIterator[MarkerStackWatchEvent]:
        """Open a live append-stream filtered to one token-id.

        Returns an async iterator that yields one
        :class:`MarkerStackWatchEvent` per appended event. The
        iterator filters out events for other token-ids in the
        same bucket — consumers only see appends for the
        requested token.

        The iterator runs until the underlying watcher closes
        (end-of-stream sentinel) or the consumer breaks out.
        Decoder failures raise
        :class:`MarkerStackEnvelopeError` and terminate the
        iterator.
        """
        if not isinstance(org_id, str) or not org_id:
            raise MarkerStackArgumentError(
                f"org_id must be a non-empty string, got {org_id!r}"
            )
        if org_id != self.org_id:
            raise MarkerStackCrossOrgBoundaryError(
                f"backend bound to org_id={self.org_id!r}; refusing watch "
                f"for org_id={org_id!r}",
                backend_org_id=self.org_id,
                requested_org_id=org_id,
            )
        if not isinstance(capability_token_id, str) or not capability_token_id:
            raise MarkerStackArgumentError(
                f"capability_token_id must be a non-empty string, got "
                f"{capability_token_id!r}"
            )
        underlying = await _open_marker_stack_watcher(self.kv)
        return _MarkerStackWatchStream(
            underlying=underlying,
            filter_token_id=capability_token_id,
            backend_org_id=self.org_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _read_token_events(
        self, capability_token_id: str
    ) -> List[MarkerEventRecord]:
        """Read all events for one token-id, sorted by sequence."""
        keys = await _list_keys(self.kv)
        prefix = f"{_KEY_PREFIX}{capability_token_id}/"
        matching_keys: List[str] = []
        for key in keys:
            if not isinstance(key, str):
                continue
            if not key.startswith(prefix):
                continue
            matching_keys.append(key)
        records: List[MarkerEventRecord] = []
        for key in matching_keys:
            try:
                kve = self.kv.get(key)
                if hasattr(kve, "__await__"):
                    kve = await kve
            except Exception as exc:
                if _is_not_found_exception(exc):
                    continue
                raise
            if kve is None:
                continue
            blob = _coerce_value_bytes(kve)
            record = _decode_envelope(blob)
            if record.org_id != self.org_id:
                raise MarkerStackEnvelopeError(
                    f"event envelope carries org_id={record.org_id!r} but "
                    f"bucket is bound to org_id={self.org_id!r}"
                )
            if record.capability_token_id != capability_token_id:
                raise MarkerStackEnvelopeError(
                    f"event at key {key!r} carries token-id "
                    f"{record.capability_token_id!r} but the key path "
                    f"says {capability_token_id!r}"
                )
            records.append(record)
        records.sort(key=lambda r: r.sequence)
        # Defence-in-depth: detect sequence gaps / duplicates.
        seen_sequences: set[int] = set()
        for r in records:
            if r.sequence in seen_sequences:
                raise MarkerStackEnvelopeError(
                    f"duplicate sequence {r.sequence} for token-id "
                    f"{capability_token_id!r}"
                )
            seen_sequences.add(r.sequence)
        return records


# ---------------------------------------------------------------------------
# Reducer-integration convenience
# ---------------------------------------------------------------------------


async def reduce_persistent_marker_stack(
    backend: NatsKvMarkerStackBackend,
    *,
    org_id: str,
    capability_token_id: str,
) -> Optional[CompositionVerdict]:
    """Re-constitute and reduce in one call.

    Returns ``None`` if no events have been logged for this token.
    Otherwise returns the byte-identical
    :class:`CompositionVerdict` an in-memory caller would have
    obtained from the same event sequence.
    """
    if not isinstance(backend, NatsKvMarkerStackBackend):
        raise TypeError(
            f"backend must be NatsKvMarkerStackBackend, got type="
            f"{type(backend).__name__}"
        )
    stack = await backend.get_marker_stack(
        org_id=org_id,
        capability_token_id=capability_token_id,
    )
    if stack is None:
        return None
    return reduce_marker_stack(stack)


# ---------------------------------------------------------------------------
# Watch-stream handle
# ---------------------------------------------------------------------------


async def _open_marker_stack_watcher(kv: Any) -> Any:
    """Open the underlying watcher on the KV handle."""
    watch_fn = getattr(kv, "watchall", None)
    if watch_fn is None:
        watch_fn = getattr(kv, "watch", None)
    if watch_fn is None:
        raise MarkerStackBackendError(
            f"KV handle exposes neither watchall() nor watch(): "
            f"type={type(kv).__name__}"
        )
    result = watch_fn()
    if hasattr(result, "__await__"):
        result = await result
    return result


@dataclass
class _MarkerStackWatchStream:
    """Internal wrapper around the underlying nats-py watcher.

    Filters to a single ``capability_token_id``, decodes each
    yielded envelope into a :class:`MarkerStackWatchEvent`, and
    surfaces decode errors as
    :class:`MarkerStackEnvelopeError` (terminating the iterator).

    Cross-org boundary: every decoded event is cross-checked
    against ``backend_org_id``; a foreign envelope raises
    :class:`MarkerStackEnvelopeError` (the bucket is malformed,
    not just the iterator's filter).
    """

    underlying: Any
    filter_token_id: str
    backend_org_id: str

    def __aiter__(self) -> "_MarkerStackWatchStream":
        return self

    async def __anext__(self) -> MarkerStackWatchEvent:
        if hasattr(self.underlying, "__anext__"):
            while True:
                update = await self.underlying.__anext__()
                if update is None:
                    # Initial-replay end sentinel; keep going.
                    continue
                event = self._decode_filtered(update)
                if event is not None:
                    return event
                # Foreign-token append; skip and continue.
                continue
        updates = getattr(self.underlying, "updates", None)
        if updates is not None:
            while True:
                update = await updates()
                if update is None:
                    raise StopAsyncIteration
                event = self._decode_filtered(update)
                if event is not None:
                    return event
                continue
        raise MarkerStackBackendError(
            f"watch handle has neither __anext__ nor updates(): "
            f"type={type(self.underlying).__name__}"
        )

    async def __aenter__(self) -> "_MarkerStackWatchStream":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        stop = getattr(self.underlying, "stop", None)
        if stop is None:
            return
        result = stop()
        if hasattr(result, "__await__"):
            await result

    def _decode_filtered(
        self, update: Any
    ) -> Optional[MarkerStackWatchEvent]:
        """Decode one watch-update; return ``None`` if it is for
        a different token-id than the iterator's filter.

        Marker-stack watch is append-only; DELETE / PURGE
        operations on individual events are out of scope and
        silently filtered (substrate-level PURGE is operator-hand).
        """
        op_raw = getattr(update, "operation", None)
        if op_raw is None and isinstance(update, Mapping):
            op_raw = update.get("operation")
        if op_raw is not None:
            op_name = getattr(op_raw, "name", None) or str(op_raw)
            op_name = op_name.upper()
            if op_name != "PUT":
                # Append-only contract: ignore DELETE/PURGE.
                return None
        key = getattr(update, "key", None)
        if key is None and isinstance(update, Mapping):
            key = update.get("key")
        if not isinstance(key, str) or not key:
            raise MarkerStackEnvelopeError(
                f"watch update has empty/non-string key: {key!r}"
            )
        try:
            token_id, _seq = parse_event_key(key)
        except ValueError:
            # Foreign key shape in the bucket; treat as
            # poison-on-disk for safety.
            raise MarkerStackEnvelopeError(
                f"watch update carries malformed key: {key!r}"
            )
        if token_id != self.filter_token_id:
            return None
        revision = getattr(update, "revision", None)
        if revision is None and isinstance(update, Mapping):
            revision = update.get("revision")
        revision_int = int(revision) if revision is not None else 0
        blob = _coerce_value_bytes(update)
        record = _decode_envelope(blob)
        if record.org_id != self.backend_org_id:
            raise MarkerStackEnvelopeError(
                f"watch event envelope carries org_id={record.org_id!r} "
                f"but backend is bound to org_id={self.backend_org_id!r}"
            )
        return MarkerStackWatchEvent(
            capability_token_id=record.capability_token_id,
            record=record,
            revision=revision_int,
        )


# ---------------------------------------------------------------------------
# Public surface declaration
# ---------------------------------------------------------------------------


__all__ = [
    "BUCKET_CONFIG",
    "BUCKET_NAME_PREFIX",
    "MarkerEvent",
    "MarkerEventKind",
    "MarkerEventRecord",
    "MarkerStackArgumentError",
    "MarkerStackBackendError",
    "MarkerStackConcurrencyConflictError",
    "MarkerStackContextConflictError",
    "MarkerStackCrossOrgBoundaryError",
    "MarkerStackEnvelopeError",
    "MarkerStackVersion",
    "MarkerStackWatchEvent",
    "NatsKvMarkerStackBackend",
    "StackContext",
    "VALUE_SCHEMA",
    "bucket_name_for_org",
    "key_for_event",
    "org_id_for_bucket_name",
    "parse_event_key",
    "reduce_persistent_marker_stack",
]
