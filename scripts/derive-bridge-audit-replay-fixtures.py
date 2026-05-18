#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Derive cross-lang fixture vectors for bridge-audit-replay canonical-trace.

Tag-37 Phase-3a 14. Modul fixture-derivation script.  Mirrors the
shape of ``scripts/derive-bridge-audit-diff-engine-fixtures.py``
(Tag-36 13. Modul) and ``scripts/derive-v907-verify-fixtures.py``
(Tag-35 12. Modul).

Output file
-----------

``tests/fixtures/bridge-audit-replay-cross-lang/fixtures.json``

Vector taxonomy (six fixtures)
------------------------------

- ``f01-empty-streams-success`` — both actual and expected are
  empty.  Pins the empty-stream stream-hash plus the success-path
  trace (sentinel ``-1`` first-step, empty summary).
- ``f02-single-record-success`` — both streams contain the SAME
  single record.  Pins the single-record stream-hash plus the
  success-path trace.
- ``f03-three-record-success`` — both streams contain the SAME
  three-record session (a different mix of output-kinds and payload
  hashes per step).  Pins the multi-record success-path.
- ``f04-value-mismatch-at-step-1`` — three-record session, actual
  step-1 has a different payload-sha than expected step-1.  Pins
  ``divergence_first_step=1`` ``divergence_first_kind=value-mismatch``.
- ``f05-missing-in-actual-at-step-2`` — expected has 3 records,
  actual has 2.  Pins ``divergence_first_step=2``
  ``divergence_first_kind=missing-in-actual``.
- ``f06-extra-in-actual-at-step-3`` — expected has 3 records,
  actual has 4 (extra final record).  Pins
  ``divergence_first_step=3`` ``divergence_first_kind=extra-in-actual``.

Each vector pins the trace JCS bytes (base64-encoded), the trace SHA-256
hex digest, and the prefixed outer hash.

The ``input_streams_b64`` carries the actual and expected record
streams as base64-encoded JCS-canonical JSON (so the Rust pendant test
decodes them with the same canonicaliser without depending on
re-parsing the comment-laden outer JSON).

Run
---

::

    python3 scripts/derive-bridge-audit-replay-fixtures.py

Re-baselines the fixture file in-place.  The CI cross-lang parity tests
will then pick the new pins up automatically.
"""

from __future__ import annotations

import base64
import json
import pathlib
import sys

# Allow running from a checkout without `pip install -e .`.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from wirelang.persona_engine.bridge_audit_replay import (  # noqa: E402
    AuditRecord,
    ExpectedTrajectory,
    ReplayEngine,
    stream_hash,
)
from wirelang.persona_engine.bridge_audit_replay_canonical import (  # noqa: E402
    REPLAY_TRACE_SCHEMA,
    build_replay_trace,
    replay_trace_hash_prefixed,
    replay_trace_sha256_hex,
    serialize_replay_trace,
)

OUT_PATH = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "bridge-audit-replay-cross-lang"
    / "fixtures.json"
)


def mk(step: int, kind: str, payload_c: str) -> AuditRecord:
    """Deterministic record builder used by every fixture vector."""
    return AuditRecord(
        org_id="wakir-labs",
        persona_id="mira",
        session_id="tag-37-sess",
        step_index=step,
        output_kind=kind,
        output_payload_sha256="sha256:" + payload_c * 64,
        engine_version="0.2.0-pilot",
        v907_pin="sha256:" + "b" * 64,
        ts_utc=f"2026-05-18T10:00:0{step}Z",
    )


def encode_stream(records: list[AuditRecord]) -> str:
    """Encode a record stream as base64-JCS for cross-lang ingest.

    The outer wrapper is the same ``{"stream": [...], "stream_len": N}``
    envelope the live :func:`stream_hash` uses, so the Rust pendant
    parses it with the same canonical-key alphabet.
    """
    envelope = {"stream": [r.to_envelope() for r in records], "stream_len": len(records)}
    # We deliberately use json.dumps with sort_keys + comma/colon
    # separators rather than rfc8785: the input vectors stay
    # readable in the JSON fixture file without depending on
    # rfc8785-side fidelity at fixture-read time.  The replay
    # engine will re-canonicalise on the way in.
    return base64.standard_b64encode(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def vector(name: str, actual: list[AuditRecord], expected: list[AuditRecord]) -> dict:
    """Build one fixture vector dict ready for JSON serialisation."""
    eng = ReplayEngine()
    expected_traj = ExpectedTrajectory.from_records(expected)
    report = eng.replay_stream(actual, expected_traj)
    trace = build_replay_trace(actual, expected_traj)
    trace_bytes = serialize_replay_trace(trace)
    return {
        "name": name,
        "input_actual_b64": encode_stream(actual),
        "input_expected_b64": encode_stream(expected),
        "expected": {
            "actual_record_count": int(trace.actual_record_count),
            "divergence_first_kind": trace.divergence_first_kind,
            "divergence_first_step": int(trace.divergence_first_step),
            "divergences_summary": trace.divergences_summary,
            "expected_record_count": int(trace.expected_record_count),
            "stream_hash_actual": trace.stream_hash_actual,
            "stream_hash_expected": trace.stream_hash_expected,
            "success": bool(trace.success),
            "trace_jcs_bytes_b64": base64.standard_b64encode(trace_bytes).decode(
                "ascii"
            ),
            "trace_jcs_bytes_len": len(trace_bytes),
            "trace_sha256_hex": replay_trace_sha256_hex(trace),
            "trace_hash_prefixed": replay_trace_hash_prefixed(trace),
            # Operator-readable echo of the report's first-step
            # invariants — duplicates `divergence_first_step` for
            # debug-trace context.
            "live_report_summary": report.summary(),
        },
    }


def main() -> None:
    # Three-record happy-path session reused by f03 + drift fixtures.
    happy3 = [
        mk(0, "tool_call", "a"),
        mk(1, "reply", "c"),
        mk(2, "audit_annotation", "d"),
    ]

    # f04 — actual differs from expected at step 1 (different payload).
    drift_value = [
        mk(0, "tool_call", "a"),
        mk(1, "reply", "x"),  # drift: payload 'x' instead of 'c'
        mk(2, "audit_annotation", "d"),
    ]

    # f05 — actual is missing the last record.
    missing_last = [
        mk(0, "tool_call", "a"),
        mk(1, "reply", "c"),
        # step 2 missing
    ]

    # f06 — actual has an extra record at the end.
    extra_one = [
        mk(0, "tool_call", "a"),
        mk(1, "reply", "c"),
        mk(2, "audit_annotation", "d"),
        mk(3, "tool_call", "e"),  # extra: trajectory has only 3 records
    ]
    # For f06 the EXPECTED trajectory is happy3 (3 records),
    # the actual stream has 4 records.

    fixtures = [
        vector("f01-empty-streams-success", [], []),
        vector("f02-single-record-success", [mk(0, "tool_call", "a")], [mk(0, "tool_call", "a")]),
        vector("f03-three-record-success", happy3, happy3),
        vector("f04-value-mismatch-at-step-1", drift_value, happy3),
        vector("f05-missing-in-actual-at-step-2", missing_last, happy3),
        vector("f06-extra-in-actual-at-step-3", extra_one, happy3),
    ]

    document = {
        "_comment": (
            "Cross-lang fixture vectors for the persona-engine "
            "bridge-audit-replay canonical-trace (Tag-37 Mini-Welle "
            "Phase-3a Python-sync, 14. Modul, closes the bridge-audit "
            "trilogy: writer/diff-engine/replay). Six outcomes "
            "covered: empty-stream success, single-record success, "
            "three-record success, value-mismatch drift at step 1, "
            "missing-in-actual at step 2, extra-in-actual at step 3. "
            "The 'expected' block is the authoritative cross-lang pin: "
            "any drift on either side (Rust crate "
            "persona-engine-bridge-audit-replay canonical module or "
            "Python wirelang.persona_engine.bridge_audit_replay_canonical) "
            "must change every other side too. Pinned 2026-05-18."
        ),
        "schema_version": REPLAY_TRACE_SCHEMA,
        "fixed_ts_utc": "2026-05-18T00:00:00Z",
        "fixtures": fixtures,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT_PATH} with {len(fixtures)} fixtures")


if __name__ == "__main__":
    main()
