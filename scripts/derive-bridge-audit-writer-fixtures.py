#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Derive cross-lang fixture vectors for the bridge-audit-writer.

Run from the repo root:

    python3 scripts/derive-bridge-audit-writer-fixtures.py > \\
        tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json

This is the canonical derivation procedure for the Tag-30 Mini-Welle
12. Modul (Phase-3a-Python-Sync / Welle-3 byte-parity oracle). Both the
Python side (``wirelang.persona_engine.bridge_audit_writer``) and the
Rust side (``persona-engine-bridge-audit-writer`` crate, this Tag) run
the same scripted scenarios and the JSON fixture pins the JCS-canonical
envelope bytes + record hash byte-identically.

Five scripted scenarios cover the writer-side surface:

  f01-empty-audit-stream
      A freshly-constructed writer with no emit() calls. Pins the
      empty-stream invariant (zero records, step_counter == 0).

  f02-single-record-write
      One emit() call -- the minimal non-empty trajectory. Pins the
      step_index == 0 / payload-hash / JCS-byte invariants for the
      Welle-3 single-record oracle.

  f03-batch-write
      Three sequential emit() calls with distinct output_kind values
      (tool_call -> reply -> audit_annotation). Pins the
      step_counter monotonicity invariant (0,1,2) and per-record
      independence of JCS bytes (same persona / session / engine but
      different output_kind / payload / ts_utc).

  f04-error-write-rollback
      Two successful emit()s sandwich one ValueError-raising emit()
      (output_kind="garbage"). The step_counter must NOT advance on
      the failed call, so the post-rollback emit() carries step_index
      == 2, not 3. Pins the rollback invariant.

  f05-append-only-discipline
      Two writers emit the same logical sequence with identical
      arguments; the resulting envelopes are byte-identical record-by-
      record. Pins the deterministic-and-append-only contract: the
      writer is a pure function of (constructor args, emit args) with
      no hidden state beyond the monotonic step counter.

Wire-shape fields pinned per fixture record
-------------------------------------------

For each record we pin:

  - ``envelope`` : the dict the Python pendant emits inside
    ``EngineeringOutputEvent.to_jcs_bytes`` (eleven keys, lex-ordered
    by JCS canonicaliser).
  - ``jcs_b64`` : base64 of the JCS-canonical bytes.
  - ``jcs_len`` : byte length of the JCS-canonical bytes.
  - ``hash_prefixed`` : ``"sha256:<64hex>"`` of the JCS bytes (same
    output as ``EngineeringOutputEvent.payload_sha256()``).

If the wire-shape of the envelope changes, re-run this script on the
Python side first to mint, then re-run the Rust cross-lang test second
to verify, and update both test suites in the same PR.
"""

from __future__ import annotations

import base64
import json
import sys
from typing import Any, Dict, List, Tuple

from wirelang.persona_engine.bridge_audit_writer import (
    BridgeAuditWriter,
    ENGINEERING_OUTPUT_SCHEMA,
    EngineeringOutputEvent,
    sha256_hex,
)


_V907_PIN = "sha256:" + "a" * 64
_ENGINE_VERSION = "0.2.0-pilot"
_ORG_ID = "acme"
_PERSONA_ID = "tomas"


def _record_entry(evt: EngineeringOutputEvent) -> Dict[str, Any]:
    """One fixture record entry -- the cross-lang pinned shape."""
    jcs_bytes = evt.to_jcs_bytes()
    return {
        "envelope": json.loads(jcs_bytes.decode("utf-8")),
        "jcs_b64": base64.b64encode(jcs_bytes).decode("ascii"),
        "jcs_len": len(jcs_bytes),
        "hash_prefixed": evt.payload_sha256(),
    }


def _writer(session_id: str) -> BridgeAuditWriter:
    """A writer with sinks pointed at /dev/null-equivalent (StringIO).

    The fixture only pins the deterministic envelope surface, never the
    sinks; we use an unwriteable stub path for the Pre-Framework sink so
    nothing actually lands on disk during derivation.
    """
    import io
    import pathlib

    return BridgeAuditWriter(
        org_id=_ORG_ID,
        persona_id=_PERSONA_ID,
        session_id=session_id,
        engine_version=_ENGINE_VERSION,
        v907_pin=_V907_PIN,
        # Use /dev/null-as-directory so the markdown append silently
        # skips (parent.mkdir fails). The deterministic surface does
        # not depend on the sink succeeding.
        preframework_sink_path=pathlib.Path("/dev/null/unused"),
        wakir_runtime_sink=io.StringIO(),
    )


# ---------------------------------------------------------------------
# F01 -- empty-audit-stream
# ---------------------------------------------------------------------


def _fixture_f01() -> Dict[str, Any]:
    w = _writer("sess-f01")
    return {
        "name": "f01-empty-audit-stream",
        "doc": (
            "A freshly-constructed writer with no emit() calls. Pins "
            "the empty-stream invariant: zero records, step_counter == 0."
        ),
        "input": {
            "org_id": _ORG_ID,
            "persona_id": _PERSONA_ID,
            "session_id": "sess-f01",
            "engine_version": _ENGINE_VERSION,
            "v907_pin": _V907_PIN,
            "emissions": [],
        },
        "expected": {
            "records": [],
            "step_counter_final": w.step_counter()
            if hasattr(w, "step_counter")
            else w._step_counter,
        },
    }


# ---------------------------------------------------------------------
# F02 -- single-record-write
# ---------------------------------------------------------------------


def _fixture_f02() -> Dict[str, Any]:
    w = _writer("sess-f02")
    evt = w.emit(
        "tool_call",
        b"payload-bytes",
        ts_utc="2026-05-17T12:00:00Z",
    )
    return {
        "name": "f02-single-record-write",
        "doc": (
            "One emit() call -- the minimal non-empty trajectory. "
            "Pins step_index == 0 / payload-hash / JCS-byte invariants."
        ),
        "input": {
            "org_id": _ORG_ID,
            "persona_id": _PERSONA_ID,
            "session_id": "sess-f02",
            "engine_version": _ENGINE_VERSION,
            "v907_pin": _V907_PIN,
            "emissions": [
                {
                    "output_kind": "tool_call",
                    "payload_b64": base64.b64encode(b"payload-bytes").decode("ascii"),
                    "ts_utc": "2026-05-17T12:00:00Z",
                }
            ],
        },
        "expected": {
            "records": [_record_entry(evt)],
            "step_counter_final": w._step_counter,
        },
    }


# ---------------------------------------------------------------------
# F03 -- batch-write (three records, three distinct output_kinds)
# ---------------------------------------------------------------------


def _fixture_f03() -> Dict[str, Any]:
    w = _writer("sess-f03")
    e0 = w.emit("tool_call", b"call-payload", ts_utc="2026-05-17T12:00:00Z")
    e1 = w.emit("reply", b"reply-payload", ts_utc="2026-05-17T12:00:01Z")
    e2 = w.emit(
        "audit_annotation",
        b"annotation-payload",
        ts_utc="2026-05-17T12:00:02Z",
    )
    return {
        "name": "f03-batch-write",
        "doc": (
            "Three sequential emit() calls with distinct output_kind "
            "values (tool_call -> reply -> audit_annotation). Pins "
            "step_counter monotonicity (0,1,2) and per-record JCS "
            "independence."
        ),
        "input": {
            "org_id": _ORG_ID,
            "persona_id": _PERSONA_ID,
            "session_id": "sess-f03",
            "engine_version": _ENGINE_VERSION,
            "v907_pin": _V907_PIN,
            "emissions": [
                {
                    "output_kind": "tool_call",
                    "payload_b64": base64.b64encode(b"call-payload").decode("ascii"),
                    "ts_utc": "2026-05-17T12:00:00Z",
                },
                {
                    "output_kind": "reply",
                    "payload_b64": base64.b64encode(b"reply-payload").decode("ascii"),
                    "ts_utc": "2026-05-17T12:00:01Z",
                },
                {
                    "output_kind": "audit_annotation",
                    "payload_b64": base64.b64encode(b"annotation-payload").decode(
                        "ascii"
                    ),
                    "ts_utc": "2026-05-17T12:00:02Z",
                },
            ],
        },
        "expected": {
            "records": [_record_entry(e0), _record_entry(e1), _record_entry(e2)],
            "step_counter_final": w._step_counter,
        },
    }


# ---------------------------------------------------------------------
# F04 -- error-write-rollback (ValueError must NOT advance counter)
# ---------------------------------------------------------------------


def _fixture_f04() -> Dict[str, Any]:
    w = _writer("sess-f04")
    e0 = w.emit("tool_call", b"first", ts_utc="2026-05-17T12:00:00Z")
    e1 = w.emit("reply", b"second", ts_utc="2026-05-17T12:00:01Z")
    # Intentional failed emission -- garbage kind. Counter must NOT advance.
    try:
        w.emit("garbage_kind", b"third", ts_utc="2026-05-17T12:00:02Z")
    except ValueError:
        pass
    # Post-rollback emission -- step_index must be 2, not 3.
    e_post = w.emit(
        "audit_annotation", b"post-rollback", ts_utc="2026-05-17T12:00:03Z"
    )
    return {
        "name": "f04-error-write-rollback",
        "doc": (
            "Two successful emit()s sandwich one ValueError-raising "
            "emit() (output_kind=\"garbage_kind\"). The step_counter "
            "must NOT advance on the failed call; post-rollback emit() "
            "carries step_index == 2, not 3."
        ),
        "input": {
            "org_id": _ORG_ID,
            "persona_id": _PERSONA_ID,
            "session_id": "sess-f04",
            "engine_version": _ENGINE_VERSION,
            "v907_pin": _V907_PIN,
            "emissions": [
                {
                    "output_kind": "tool_call",
                    "payload_b64": base64.b64encode(b"first").decode("ascii"),
                    "ts_utc": "2026-05-17T12:00:00Z",
                },
                {
                    "output_kind": "reply",
                    "payload_b64": base64.b64encode(b"second").decode("ascii"),
                    "ts_utc": "2026-05-17T12:00:01Z",
                },
                {
                    "output_kind": "garbage_kind",
                    "payload_b64": base64.b64encode(b"third").decode("ascii"),
                    "ts_utc": "2026-05-17T12:00:02Z",
                    "expect_error": True,
                },
                {
                    "output_kind": "audit_annotation",
                    "payload_b64": base64.b64encode(b"post-rollback").decode("ascii"),
                    "ts_utc": "2026-05-17T12:00:03Z",
                },
            ],
        },
        "expected": {
            "records": [
                _record_entry(e0),
                _record_entry(e1),
                _record_entry(e_post),
            ],
            "step_counter_final": w._step_counter,
        },
    }


# ---------------------------------------------------------------------
# F05 -- append-only-discipline (two writers, identical sequences)
# ---------------------------------------------------------------------


def _fixture_f05() -> Dict[str, Any]:
    # Two separate writers; same constructor args + same emit args ->
    # byte-identical records record-by-record.
    w_a = _writer("sess-f05")
    w_b = _writer("sess-f05")
    seq: List[Tuple[str, bytes, str]] = [
        ("tool_call", b"alpha", "2026-05-17T13:00:00Z"),
        ("reply", b"beta", "2026-05-17T13:00:01Z"),
    ]
    recs_a = [w_a.emit(k, p, ts_utc=t) for (k, p, t) in seq]
    recs_b = [w_b.emit(k, p, ts_utc=t) for (k, p, t) in seq]
    # Cross-check before pinning -- if this fails the writer is not
    # deterministic and the fixture is meaningless.
    for ra, rb in zip(recs_a, recs_b):
        assert ra.to_jcs_bytes() == rb.to_jcs_bytes(), (
            "writer not deterministic across two identical constructions"
        )
    return {
        "name": "f05-append-only-discipline",
        "doc": (
            "Two writers emit the same logical sequence with identical "
            "constructor + emit args; the resulting envelopes are "
            "byte-identical record-by-record. Pins the deterministic-"
            "and-append-only contract."
        ),
        "input": {
            "org_id": _ORG_ID,
            "persona_id": _PERSONA_ID,
            "session_id": "sess-f05",
            "engine_version": _ENGINE_VERSION,
            "v907_pin": _V907_PIN,
            "emissions": [
                {
                    "output_kind": k,
                    "payload_b64": base64.b64encode(p).decode("ascii"),
                    "ts_utc": t,
                }
                for (k, p, t) in seq
            ],
        },
        "expected": {
            "records": [_record_entry(r) for r in recs_a],
            "step_counter_final": w_a._step_counter,
        },
    }


# ---------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------


def build_fixtures() -> Dict[str, Any]:
    return {
        "_comment": (
            "Cross-lang fixture vectors for the persona-engine "
            "bridge-audit-writer (Tag-30 Mini-Welle / Phase-3a Item 12 / "
            "ADR-0066 Welle-3 byte-parity oracle). Authoritative wire-"
            "pin: any drift on either side (Rust crate persona-engine-"
            "bridge-audit-writer or Python wirelang.persona_engine."
            "bridge_audit_writer) must update this file in the same "
            "PR. Derivation procedure: scripts/derive-bridge-audit-"
            "writer-fixtures.py. Fixtures pinned 2026-05-17."
        ),
        "schema_version": ENGINEERING_OUTPUT_SCHEMA,
        "fixtures": [
            _fixture_f01(),
            _fixture_f02(),
            _fixture_f03(),
            _fixture_f04(),
            _fixture_f05(),
        ],
    }


def main() -> int:
    fixtures = build_fixtures()
    json.dump(fixtures, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
