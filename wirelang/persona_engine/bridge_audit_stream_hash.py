# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Python pendant of the Rust ``persona-engine-bridge-audit-replay``
stream-hash + JSONL-serialisation helpers.

Sprint-Tag-14 Mini-Welle (Bridge-Audit-Roundtrip-E2E).

The Phase-2 Doppelbetrieb-Bridge consistency drill ships two halves:

* Python emits a stream of :class:`~wirelang.persona_engine.bridge_audit_writer.EngineeringOutputEvent`
  envelopes via :class:`~wirelang.persona_engine.bridge_audit_writer.BridgeAuditWriter`.
* Rust ``persona-engine-bridge-audit-replay`` consumes the serialised
  stream and validates record-for-record consistency.

For the cross-language byte-pin to hold, both sides must agree on the
same wire format. This module provides:

* :func:`record_envelope` — the canonical 11-field envelope shape per
  record, mirroring the Rust ``AuditRecord::to_envelope()`` output.
* :func:`stream_envelope` — the wrapping ``{"stream":[...], "stream_len":N}``
  shape that the Rust ``stream_hash()`` hashes.
* :func:`stream_hash` — JCS-canonical SHA-256 of :func:`stream_envelope`,
  byte-identical to the Rust ``persona_engine_bridge_audit_replay::stream_hash``.
* :func:`records_to_jsonl_bytes` / :func:`jsonl_bytes_to_records` —
  ordered JSONL wire format. One JCS line per record so the Rust CLI
  reads the stream deterministically from stdin / a file.

Cross-language pins (matched against Rust 2026-05-17 fixtures)
--------------------------------------------------------------

* ``F1`` (empty stream): ``sha256:64d11dbb5fe0c2c5e807d22438aedf3912852d81717e532f5c9d2750afa15469``
* ``F2`` (1-record stream, F3's record-0): ``sha256:5d259cab58d5d75772f230ac86d18b6a61fd228829cea7aa1887e98cea3cc770``
* ``F3`` (3-record session): ``sha256:fca1381878f461ea00520d9ee87d3e8c5b536e028e368c002f8de56d8b643bd4``

These pins are cross-checked in
``tests/integration/test_bridge_audit_roundtrip_e2e.py``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Iterable, List, Mapping, Sequence

from wirelang.persona_engine.bridge_audit_writer import (
    ENGINEERING_OUTPUT_SCHEMA,
    EngineeringOutputEvent,
)


__all__ = [
    "EVENT_KIND",
    "record_envelope",
    "stream_envelope",
    "stream_hash",
    "records_to_jsonl_bytes",
    "jsonl_bytes_to_records",
]


#: Constant ``event_kind`` tag pinned to the Rust ``EVENT_KIND`` const.
EVENT_KIND = "engineering_output"


def _jcs_bytes(value: Mapping[str, object]) -> bytes:
    """JCS-canonical (RFC 8785 § 3) JSON byte-string of ``value``.

    The pure-Python ``json.dumps`` with ``sort_keys=True``,
    ``separators=(',', ':')``, ``ensure_ascii=False`` is byte-identical
    to the Rust ``serde_jcs::to_string`` output for the JSON subset
    Wakir uses (scalars: string, bool, int, no floats / no nested
    arrays-of-objects beyond what ``EngineeringOutputEvent`` carries).
    """
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def record_envelope(record: EngineeringOutputEvent) -> dict:
    """Return the canonical 11-field envelope dict for one audit record.

    Mirrors :meth:`wirelang.persona_engine.bridge_audit_writer.EngineeringOutputEvent.to_jcs_bytes`
    pre-JCS (returns the dict, not the bytes) and matches the Rust
    ``AuditRecord::to_envelope()`` keys 1:1. Useful for callers that
    want to inspect / mutate / re-serialise the envelope.
    """
    return {
        "engine_version": record.engine_version,
        "event_kind": EVENT_KIND,
        "org_id": record.org_id,
        "output_kind": record.output_kind,
        "output_payload_sha256": record.output_payload_sha256,
        "persona_id": record.persona_id,
        "schema": ENGINEERING_OUTPUT_SCHEMA,
        "session_id": record.session_id,
        "step_index": record.step_index,
        "ts_utc": record.ts_utc,
        "v907_pin": record.v907_pin,
    }


def stream_envelope(records: Sequence[EngineeringOutputEvent]) -> dict:
    """Return the canonical ``{"stream":[...], "stream_len":N}`` wrapper
    that :func:`stream_hash` hashes.

    The wrapper resists silent truncation (``stream_len`` disagrees with
    the array length on tampered input) and discriminates empty from
    missing streams cleanly.
    """
    return {
        "stream": [record_envelope(r) for r in records],
        "stream_len": len(records),
    }


def stream_hash(records: Sequence[EngineeringOutputEvent]) -> str:
    """Return ``"sha256:<64hex>"`` of the JCS-canonicalised stream envelope.

    Byte-identical to the Rust ``persona_engine_bridge_audit_replay::stream_hash``
    for the same record sequence. The empty-stream / single-record /
    3-record fixture pins are documented in the module docstring and
    pinned in the integration test.
    """
    return "sha256:" + hashlib.sha256(_jcs_bytes(stream_envelope(records))).hexdigest()


def records_to_jsonl_bytes(records: Iterable[EngineeringOutputEvent]) -> bytes:
    """Serialise ``records`` as ordered JSONL.

    One JCS-canonical line per record, trailing newline after the last
    record. The Rust ``replay_cli`` binary consumes this format from
    stdin / a file; the line-order MUST match the emission-order
    because the replay engine is order-sensitive.
    """
    out = bytearray()
    for r in records:
        out.extend(_jcs_bytes(record_envelope(r)))
        out.extend(b"\n")
    return bytes(out)


def jsonl_bytes_to_records(data: bytes) -> List[EngineeringOutputEvent]:
    """Parse JSONL bytes (as produced by :func:`records_to_jsonl_bytes`)
    back into a list of :class:`EngineeringOutputEvent`.

    Ignores empty lines (operator-substrate hygiene for hand-edited
    fixtures) but does not silently skip malformed JSON — a parse
    error surfaces as :class:`json.JSONDecodeError` to the caller.
    """
    out: List[EngineeringOutputEvent] = []
    for line in data.splitlines():
        if not line.strip():
            continue
        env = json.loads(line.decode("utf-8"))
        out.append(
            EngineeringOutputEvent(
                org_id=env["org_id"],
                persona_id=env["persona_id"],
                session_id=env["session_id"],
                step_index=env["step_index"],
                output_kind=env["output_kind"],
                output_payload_sha256=env["output_payload_sha256"],
                engine_version=env["engine_version"],
                v907_pin=env["v907_pin"],
                ts_utc=env["ts_utc"],
            )
        )
    return out
