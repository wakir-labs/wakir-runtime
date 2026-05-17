# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Subscribe-Loop ack-record helpers (Tag-19 Mini-Welle, Phase-3a Python-sync).

This module is the Python sibling of the ack-record substrate that
lives in the Rust crate ``persona-engine-subscribe-loop`` (PR #132,
gemerged 2026-05-17). Both sides emit a byte-identical JCS-canonical
``SubscribeAckRecord`` per inbound NATS frame so the Phase-3a
3-way-triangle (Doppelbetrieb-Vergleich) can diff Python-side and
Rust-side subscribe-acks byte-for-byte without round-tripping through
the BridgeAuditWriter substrate.

Why a sibling module?
---------------------

``wirelang.persona_engine.nats_subscribe_loop`` is a 1153-line mature
substrate that already drives the persona-engine's NATS-bound
behaviour (parse envelopes, dispatch to LLM hook, emit reply on output
subject, audit-emit through BridgeAuditWriter). The Tag-19 ack-record
contract is **orthogonal** to that flow: it is a pure-function pair
``build_subscribe_ack_record`` / ``serialize_subscribe_ack`` plus a
small helper that turns a parsed envelope + outcome into a record.
Keeping the helpers in a separate module preserves the Sprint-10
Doppelbetrieb-Konsistenz contract (the existing loop's byte-output
does not change) and matches the pattern Reza used for
``wirelang.persona_engine.anchor_emitter`` (Tag-18 sibling of the
``persona-engine-anchor-emitter`` Rust crate).

The record shape — sorted JSON keys, UTF-8 bytes, JCS-canonical
form — is the cross-lang pin. The Rust crate's
``build_ack_record`` / ``serialize_ack`` / ``ack_record_sha256_hex``
must produce byte-identical bytes for the five fixture vectors in
``tests/fixtures/subscribe-loop-cross-lang/fixtures.json``.

Schema
------

The ack-record carries exactly seven fields (alphabetically sorted
in the canonical form):

- ``auftrag_id`` — Bridge-Forward-Pipe envelope auftrag_id, or "" for
  malformed/unparsable frames.
- ``frame_index`` — Monotonic 0-based index of this frame within the
  ack-burst. Captures ordered-delivery preservation.
- ``outcome`` — One of: ``"processed"``, ``"malformed"``,
  ``"persona_mismatch"``, ``"rejected"``, ``"empty_payload"``.
- ``persona_id`` — Envelope persona_id, or "" for malformed frames.
- ``prompt_sha256`` — Envelope prompt_sha256 (with ``sha256:`` prefix),
  or "" for malformed frames.
- ``schema`` — Schema identifier; constant
  ``"wakir.persona-engine.subscribe-ack/1"``.
- ``subject`` — Inbound NATS subject the frame arrived on. Captures
  subject-routing context (wildcard-bound subscribes preserve the
  concrete subject in the record).

Serialization
-------------

The canonical bytes are produced by ``json.dumps`` with
``sort_keys=True``, ``separators=(",", ":")``, ``ensure_ascii=False``,
UTF-8-encoded. This matches the JCS-canonical form used by the
existing ``build_output_envelope`` (line 480 of ``nats_subscribe_loop``)
and the byte-for-byte form the Rust crate's ``serde_json`` output
emits when keys are pre-sorted by the Rust code.

ADR anchors
-----------

- ADR-0063 §Folgeartefakte Phase-3a Item 4 (subscribe-loop Rust
  scaffold) + Tag-19 Python-sync follow-on.
- Selin PR #79  (Bug-42 fix; Python subscribe-loop ownership).
- Selin PR #113 (3-way-triangle Doppelbetrieb).
- Reza  PR #132 (Rust subscribe-loop crate; ack-record target).
- Reza  PR #170 (Tag-18 anchor-emitter Python-sync; pattern
  reference for sibling-module + cross-lang fixture).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, List, Optional


#: Schema identifier emitted on every subscribe-ack record.
ACK_RECORD_SCHEMA = "wakir.persona-engine.subscribe-ack/1"

#: Prefix used by the prefixed-form hash (matches
#: ``persona-engine-anchor-emitter`` and ``BridgeAuditWriter``).
HASH_PREFIX = "sha256:"

#: Length of a bare-hex SHA-256 digest (no prefix).
SHA256_HEX_LEN = 64

#: Outcome literals — the canonical strings the ack-record carries.
#: Defined as constants so both sides have a single source of truth
#: (and so a typo on either side is a static-analysis-catchable bug,
#: not a silent cross-lang drift).
OUTCOME_PROCESSED = "processed"
OUTCOME_MALFORMED = "malformed"
OUTCOME_PERSONA_MISMATCH = "persona_mismatch"
OUTCOME_REJECTED = "rejected"
OUTCOME_EMPTY_PAYLOAD = "empty_payload"

#: All outcome literals (used by validation paths).
VALID_OUTCOMES = frozenset(
    {
        OUTCOME_PROCESSED,
        OUTCOME_MALFORMED,
        OUTCOME_PERSONA_MISMATCH,
        OUTCOME_REJECTED,
        OUTCOME_EMPTY_PAYLOAD,
    }
)


class InvalidOutcomeError(ValueError):
    """Outcome string is not one of :data:`VALID_OUTCOMES`."""


class InvalidFrameIndexError(ValueError):
    """frame_index must be a non-negative integer."""


@dataclass(frozen=True)
class SubscribeAckRecord:
    """Immutable per-frame subscribe-ack record.

    The seven fields map 1:1 to the JCS-canonical JSON keys. The
    dataclass is ``frozen=True`` so accidental mutation cannot
    desynchronise a record from its already-serialised bytes.
    """

    auftrag_id: str
    frame_index: int
    outcome: str
    persona_id: str
    prompt_sha256: str
    schema: str
    subject: str


def build_subscribe_ack_record(
    *,
    auftrag_id: str,
    frame_index: int,
    outcome: str,
    persona_id: str,
    prompt_sha256: str,
    subject: str,
) -> SubscribeAckRecord:
    """Construct an ack-record with strict validation.

    All string fields are pass-through (the empty string is allowed
    for malformed-frame records). ``frame_index`` must be a
    non-negative integer; ``outcome`` must be one of
    :data:`VALID_OUTCOMES`. The schema field is set to the constant
    :data:`ACK_RECORD_SCHEMA` and cannot be overridden.

    Raises
    ------
    InvalidOutcomeError
        If ``outcome`` is not in :data:`VALID_OUTCOMES`.
    InvalidFrameIndexError
        If ``frame_index`` is negative or not an ``int``.
    """
    if not isinstance(frame_index, int) or isinstance(frame_index, bool):
        # bool is a subclass of int — reject explicitly to keep the
        # JCS-bytes deterministic (True would serialise as ``true``).
        raise InvalidFrameIndexError(
            f"frame_index must be int, got {type(frame_index).__name__}"
        )
    if frame_index < 0:
        raise InvalidFrameIndexError(
            f"frame_index must be >= 0, got {frame_index}"
        )
    if outcome not in VALID_OUTCOMES:
        raise InvalidOutcomeError(
            f"outcome must be one of {sorted(VALID_OUTCOMES)}, "
            f"got {outcome!r}"
        )
    return SubscribeAckRecord(
        auftrag_id=auftrag_id,
        frame_index=frame_index,
        outcome=outcome,
        persona_id=persona_id,
        prompt_sha256=prompt_sha256,
        schema=ACK_RECORD_SCHEMA,
        subject=subject,
    )


def serialize_subscribe_ack(record: SubscribeAckRecord) -> bytes:
    """Serialise an ack-record to JCS-canonical UTF-8 bytes.

    The canonical form is:

    - Keys sorted alphabetically.
    - No whitespace (`,` / `:` separators only).
    - Unicode pass-through (no ``\\uXXXX`` escaping for non-ASCII).
    - UTF-8 encoded.

    This matches the byte-for-byte form the Rust crate emits via
    pre-sorted ``serde_json::Map`` insertion.
    """
    obj = {
        "auftrag_id": record.auftrag_id,
        "frame_index": record.frame_index,
        "outcome": record.outcome,
        "persona_id": record.persona_id,
        "prompt_sha256": record.prompt_sha256,
        "schema": record.schema,
        "subject": record.subject,
    }
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Bare-hex SHA-256 digest of the supplied bytes.

    Helper for cross-lang fixture comparisons. Mirrors the Rust
    crate's ``sha256_hex`` (which is in the
    ``persona-engine-anchor-emitter`` crate; the subscribe-loop crate
    re-implements the same lowercase-hex format inline).
    """
    return hashlib.sha256(data).hexdigest()


def ack_record_sha256_hex(record: SubscribeAckRecord) -> str:
    """Bare-hex SHA-256 of the canonical bytes of ``record``."""
    return sha256_hex(serialize_subscribe_ack(record))


def ack_record_hash_prefixed(record: SubscribeAckRecord) -> str:
    """Prefixed-form (``sha256:<hex>``) SHA-256 of the record bytes."""
    return HASH_PREFIX + ack_record_sha256_hex(record)


def serialize_and_hash(
    record: SubscribeAckRecord,
) -> "tuple[bytes, str]":
    """Convenience: return both the canonical bytes and the prefixed hash.

    The two are produced from the same ``serialize_subscribe_ack``
    call, so callers that need both do not pay the JCS-encode cost
    twice.
    """
    bytes_ = serialize_subscribe_ack(record)
    return bytes_, HASH_PREFIX + sha256_hex(bytes_)


# ---------------------------------------------------------------------
# Burst helpers (multi-frame ordered-delivery preservation)
# ---------------------------------------------------------------------


def build_ack_burst(
    records: Iterable[SubscribeAckRecord],
) -> List[SubscribeAckRecord]:
    """Materialise an iterable of records into a list, in iteration order.

    The burst-list itself is not serialised — the per-record bytes are
    the cross-lang unit. The burst-helper exists so callers can
    construct multi-record batches with monotonic ``frame_index`` and
    then pass the list through to the cross-lang diff engine.

    Raises
    ------
    InvalidFrameIndexError
        If the frame_index values are not strictly monotonic
        (0, 1, 2, ...). Out-of-order indices break the
        ordered-delivery-preservation invariant.
    """
    out: List[SubscribeAckRecord] = []
    for i, rec in enumerate(records):
        if rec.frame_index != i:
            raise InvalidFrameIndexError(
                f"frame_index must be strictly monotonic 0..N-1; "
                f"position {i} has frame_index={rec.frame_index}"
            )
        out.append(rec)
    return out


def serialize_ack_burst(
    records: Iterable[SubscribeAckRecord],
) -> List[bytes]:
    """Serialise each record in iteration order; returns list of bytes.

    Does **not** validate monotonicity (use :func:`build_ack_burst`
    first if monotonicity is part of the contract). This separation
    keeps the wire-form helper pure: any iterable of records can be
    serialised, with monotonicity a separate, opt-in check.
    """
    return [serialize_subscribe_ack(r) for r in records]


# ---------------------------------------------------------------------
# Engine-side convenience: derive an ack-record from a parsed envelope
# ---------------------------------------------------------------------


def ack_record_from_parsed(
    *,
    parsed: Optional[object],  # ParsedAuftrag (avoid hard import cycle)
    frame_index: int,
    outcome: str,
    subject: str,
    fallback_persona_id: str = "",
) -> SubscribeAckRecord:
    """Build an ack-record from a parsed envelope (or None for malformed).

    The ``parsed`` parameter is typed as ``Optional[object]`` to avoid
    a hard import of ``ParsedAuftrag`` from
    ``wirelang.persona_engine.nats_subscribe_loop`` (which would
    create a tight coupling between this orthogonal substrate and the
    1153-line loop module). At runtime, the function reads the
    ``auftrag_id`` / ``persona_id`` / ``prompt_sha256`` attributes
    via ``getattr`` with empty-string defaults.

    For malformed frames the caller passes ``parsed=None``; all
    envelope-derived fields default to the empty string.
    """
    if parsed is None:
        auftrag_id = ""
        persona_id = fallback_persona_id
        prompt_sha256 = ""
    else:
        auftrag_id = getattr(parsed, "auftrag_id", "") or ""
        persona_id = getattr(parsed, "persona_id", "") or fallback_persona_id
        prompt_sha256 = getattr(parsed, "prompt_sha256", "") or ""
    return build_subscribe_ack_record(
        auftrag_id=auftrag_id,
        frame_index=frame_index,
        outcome=outcome,
        persona_id=persona_id,
        prompt_sha256=prompt_sha256,
        subject=subject,
    )
