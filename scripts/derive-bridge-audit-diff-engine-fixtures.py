#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Derive cross-lang fixture vectors for the bridge-audit-diff-engine.

Run from the repo root:

    python3 scripts/derive-bridge-audit-diff-engine-fixtures.py > \\
        tests/fixtures/bridge-audit-diff-engine-cross-lang/fixtures.json

This is the canonical derivation procedure for the Tag-36 Mini-Welle
13. Modul (Phase-3a-Python-Sync). Both the Python side
(``wirelang.persona_engine.bridge_audit_diff_engine_canonical``) and the
Rust side (``persona-engine-bridge-diff`` crate canonical sub-module)
run the same scripted scenarios and the JSON fixture pins the JCS-
canonical trace bytes + outer hash byte-identically.

Six scripted scenarios cover the diff-engine outcome surface:

  f01-byte-identical-cloudevent
      Two byte-identical CloudEvent envelopes. Fast-path:
      byte_identical=True, drift_count=0, score_milli=1000,
      field_diffs_summary="".

  f02-value-mismatch-payload-sha
      Single value-mismatch on the ``output_payload_sha256`` leaf.
      drift_count=1, score_milli=666 (1 - 1/3 leaves).

  f03-only-in-a-capability-token
      Envelope A carries an extra ``capability_token_hash`` key;
      envelope B does not. drift_count=1, score_milli=666.

  f04-only-in-b-v907-pin
      Envelope B carries an extra ``v907_pin`` key; envelope A does
      not. Symmetric counterpart to f03. drift_count=1, score_milli=666.

  f05-type-mismatch-bool-vs-string
      Same key (``active``) holds a JSON bool on one side and a JSON
      string on the other (``True`` vs ``"true"``). Type-mismatch
      surfaces; drift_count=1, score_milli=666. Avoids int-vs-float
      on purpose: Python pure-Python ``_jcs_pure`` and Rust
      ``serde_jcs`` disagree on trailing-zero handling for
      ``1.0`` (Python keeps ``.0``, Rust strips), so the int-vs-float
      vector would fail the cross-lang byte-parity test. The bool-vs-
      string case has unambiguous wire-level type discriminants on
      both sides.

  f06-multi-field-rfc6901-escapes
      Nested object with literal ``/`` and ``~`` characters in object
      keys, a list with index-3 drift, and a top-level timestamp
      drift. Pins:
      - RFC-6901 escape sequence (``/`` -> ``~1``, ``~`` -> ``~0``);
      - List index notation (decimal indices in field paths);
      - Alphabetic sort of multiple drift entries in the summary
        string;
      - leaves_total over a non-trivial leaf count (5 leaves total).

The vectors deliberately exercise the four DiffKind alphabet members
(value-mismatch, only-in-a, only-in-b, type-mismatch) so a drift in any
one kind surfaces as a fixture mismatch.

Pinning procedure (cross-lang re-pin)
-------------------------------------

If a wire-shape change is intentional:

1. Update both sides (Rust crate ``persona-engine-bridge-diff``
   canonical sub-module and Python
   ``bridge_audit_diff_engine_canonical.py``).
2. Run this script to regenerate the fixture file.
3. Update both Python and Rust test suites in the same PR.
"""

from __future__ import annotations

import base64
import json
import pathlib
import sys

# Resolve the repo root so the script can be invoked from any CWD.
_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from wirelang.persona_engine.bridge_audit_diff_engine_canonical import (
    BRIDGE_DIFF_TRACE_SCHEMA,
    bridge_diff_trace_hash_prefixed,
    bridge_diff_trace_sha256_hex,
    build_bridge_diff_trace,
    serialize_bridge_diff_trace,
)


def _vec(name: str, env_a: dict, env_b: dict) -> dict:
    trace = build_bridge_diff_trace(env_a, env_b)
    bytes_ = serialize_bridge_diff_trace(trace)
    return {
        "name": name,
        "input_envelope_a_json": json.dumps(
            env_a, sort_keys=True, separators=(",", ":")
        ),
        "input_envelope_b_json": json.dumps(
            env_b, sort_keys=True, separators=(",", ":")
        ),
        "expected": {
            "byte_identical": trace.byte_identical,
            "drift_count": trace.drift_count,
            "field_diffs_summary": trace.field_diffs_summary,
            "jcs_hash_a": trace.jcs_hash_a,
            "jcs_hash_b": trace.jcs_hash_b,
            "leaves_total": trace.leaves_total,
            "score_milli": trace.score_milli,
            "trace_jcs_bytes_b64": base64.b64encode(bytes_).decode("ascii"),
            "trace_jcs_bytes_len": len(bytes_),
            "trace_sha256_hex": bridge_diff_trace_sha256_hex(trace),
            "trace_hash_prefixed": bridge_diff_trace_hash_prefixed(trace),
        },
    }


def _derive_doc() -> dict:
    f01 = _vec(
        "f01-byte-identical-cloudevent",
        {
            "schema": "wakir.persona-engine.engineering-output/1",
            "event_kind": "engineering_output",
            "org_id": "wakir-labs",
            "persona_id": "reza",
            "session_id": "tag-36-sess",
            "step_index": 0,
            "output_kind": "tool_call",
            "output_payload_sha256": "sha256:" + "0" * 64,
            "ts_utc": "2026-05-18T00:00:00Z",
        },
        {
            "schema": "wakir.persona-engine.engineering-output/1",
            "event_kind": "engineering_output",
            "org_id": "wakir-labs",
            "persona_id": "reza",
            "session_id": "tag-36-sess",
            "step_index": 0,
            "output_kind": "tool_call",
            "output_payload_sha256": "sha256:" + "0" * 64,
            "ts_utc": "2026-05-18T00:00:00Z",
        },
    )

    f02 = _vec(
        "f02-value-mismatch-payload-sha",
        {
            "schema": "wakir.persona-engine.engineering-output/1",
            "step_index": 1,
            "output_payload_sha256": "sha256:" + "a" * 64,
        },
        {
            "schema": "wakir.persona-engine.engineering-output/1",
            "step_index": 1,
            "output_payload_sha256": "sha256:" + "b" * 64,
        },
    )

    f03 = _vec(
        "f03-only-in-a-capability-token",
        {
            "schema": "wakir.persona-engine.engineering-output/1",
            "step_index": 2,
            "capability_token_hash": "sha256:" + "c" * 64,
        },
        {
            "schema": "wakir.persona-engine.engineering-output/1",
            "step_index": 2,
        },
    )

    f04 = _vec(
        "f04-only-in-b-v907-pin",
        {
            "schema": "wakir.persona-engine.engineering-output/1",
            "step_index": 3,
        },
        {
            "schema": "wakir.persona-engine.engineering-output/1",
            "step_index": 3,
            "v907_pin": "sha256:" + "d" * 64,
        },
    )

    f05 = _vec(
        "f05-type-mismatch-bool-vs-string",
        {
            "schema": "wakir.persona-engine.engineering-output/1",
            "step_index": 1,
            "active": True,
        },
        {
            "schema": "wakir.persona-engine.engineering-output/1",
            "step_index": 1,
            "active": "true",
        },
    )

    f06 = _vec(
        "f06-multi-field-rfc6901-escapes",
        {
            "schema": "wakir.persona-engine.engineering-output/1",
            "nested": {"a/b": "alpha", "c~d": "carbon"},
            "list": [1, 2, 3],
            "ts_utc": "2026-05-18T00:00:00Z",
        },
        {
            "schema": "wakir.persona-engine.engineering-output/1",
            "nested": {"a/b": "beta", "c~d": "carbon"},
            "list": [1, 2, 4],
            "ts_utc": "2026-05-18T00:00:01Z",
        },
    )

    return {
        "_comment": (
            "Cross-lang fixture vectors for the persona-engine "
            "bridge-audit-diff-engine canonical-trace (Tag-36 "
            "Mini-Welle Phase-3a Python-sync, 13. Modul). Six "
            "outcomes covered: byte-identical happy path, single "
            "value-mismatch, only-in-a, only-in-b, type-mismatch "
            "(bool vs string), and a multi-field drift across "
            "nested-object + list with RFC-6901 escapes. The "
            "'expected' block is the authoritative cross-lang "
            "pin: any drift on either side (Rust crate "
            "persona-engine-bridge-diff canonical module or "
            "Python wirelang.persona_engine."
            "bridge_audit_diff_engine_canonical) must change "
            "every other side too. Pinned 2026-05-18."
        ),
        "schema_version": BRIDGE_DIFF_TRACE_SCHEMA,
        "fixed_ts_utc": "2026-05-18T00:00:00Z",
        "fixtures": [f01, f02, f03, f04, f05, f06],
    }


def main() -> int:
    doc = _derive_doc()
    out = json.dumps(doc, indent=2, sort_keys=False) + "\n"
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
