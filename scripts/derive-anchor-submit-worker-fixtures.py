#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Derive cross-lang fixture vectors for the anchor-submit-worker.

Run from the repo root:

    python3 scripts/derive-anchor-submit-worker-fixtures.py > \
        tests/fixtures/anchor-submit-worker-cross-lang/fixtures.json

This is the canonical derivation procedure: the Python side runs
the same scripted scenarios that the Rust sibling test reads back.
If the wire-shape of the decision record changes, re-run this script
on both sides (Python first to mint, Rust second to verify), and
update both test suites in the same PR.
"""

from __future__ import annotations

import base64
import json
import sys
from typing import Any, Dict, List

from wirelang.persona_engine.anchor_submit_worker import (
    AnchorSubmitWorker,
    DeadLetterRecord,
    DeterministicRng,
    InMemoryDeadLetterStore,
    ManualClock,
    NoopWriteBackSink,
    RecordingWriteBackSink,
    ScriptedTransport,
    SubmitResult,
    SubmitResultKind,
    SubmitWorkerConfig,
    TransportOutcome,
    decision_record_hash,
    serialize_decision_record,
    DECISION_RECORD_SCHEMA,
)


def _ledger_entry(result: SubmitResult) -> Dict[str, Any]:
    """One ledger entry — the cross-lang pinned shape per tick."""

    canonical = serialize_decision_record(result)
    return {
        "decision_record": result.to_decision_record(),
        "decision_jcs_b64": base64.b64encode(canonical).decode("ascii"),
        "decision_jcs_len": len(canonical),
        "decision_hash_prefixed": decision_record_hash(result),
    }


def _ledger_from_ticks(
    cfg: SubmitWorkerConfig,
    transport: ScriptedTransport,
    clock: ManualClock,
    rng: DeterministicRng,
    enqueues: List[Dict[str, Any]],
    tick_program: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Drive a worker through a deterministic tick program.

    Each tick-program entry is one of:

      {"op": "enqueue", "envelope": {...}}
      {"op": "advance_clock", "by_secs": 30}
      {"op": "tick"}
    """

    dl = InMemoryDeadLetterStore()
    wb = RecordingWriteBackSink()
    worker = AnchorSubmitWorker(
        config=cfg,
        transport=transport,
        dead_letter=dl,
        writeback=wb,
        clock=clock,
        rng=rng,
    )
    for env in enqueues:
        worker.enqueue(env)

    ledger: List[Dict[str, Any]] = []
    for step in tick_program:
        op = step["op"]
        if op == "tick":
            ledger.append(_ledger_entry(worker.tick()))
        elif op == "advance_clock":
            clock.advance(int(step["by_secs"]))
        elif op == "enqueue":
            worker.enqueue(step["envelope"])
        else:
            raise SystemExit(f"unknown op: {op!r}")

    return {
        "ledger": ledger,
        "transport_calls": transport.calls,
        "transport_seen": transport.seen,
        "writeback_calls": wb.calls,
        "dead_letter_snapshot": [r.to_wire_dict() for r in dl.snapshot()],
        "queue_len_final": worker.queue_len(),
    }


def _fx_success_fast_path() -> Dict[str, Any]:
    cfg = SubmitWorkerConfig()
    transport = ScriptedTransport([TransportOutcome.accepted()])
    clock = ManualClock(0)
    rng = DeterministicRng([0])
    enqueues = [{"event_id": "evt-tag26-f01-success", "persona_id": "reza"}]
    tick_program = [{"op": "tick"}]
    derived = _ledger_from_ticks(cfg, transport, clock, rng, enqueues, tick_program)
    return {
        "name": "f01-success-fast-path",
        "doc": (
            "Single envelope, default config, transport accepts on the "
            "first try. Expected ledger: [Success(e1)]."
        ),
        "input": {
            "config": cfg.to_wire_dict(),
            "rng_sequence": [0],
            "clock_start_secs": 0,
            "enqueues": enqueues,
            "transport_script": [{"kind": "accepted", "error": ""}],
            "tick_program": tick_program,
        },
        "expected": derived,
    }


def _fx_throttled_rate_limit() -> Dict[str, Any]:
    # 1 req / 60s bucket, 2 envelopes, both eligible. tick #1 = Success,
    # tick #2 = Throttled (transport NOT called).
    cfg = SubmitWorkerConfig(
        rate_requests=1,
        rate_window_secs=60,
        max_retry=5,
        retry_base_delay_secs=1,
        retry_max_delay_secs=300,
    )
    # Only ONE outcome scripted — second submit() would raise.
    transport = ScriptedTransport([TransportOutcome.accepted()])
    clock = ManualClock(0)
    rng = DeterministicRng([0])
    enqueues = [
        {"event_id": "evt-tag26-f02-a", "persona_id": "reza"},
        {"event_id": "evt-tag26-f02-b", "persona_id": "tomas"},
    ]
    tick_program = [{"op": "tick"}, {"op": "tick"}]
    derived = _ledger_from_ticks(cfg, transport, clock, rng, enqueues, tick_program)
    return {
        "name": "f02-throttled-rate-limit",
        "doc": (
            "Two envelopes share a 1-token-per-60s bucket. tick #1 = "
            "Success; tick #2 = Throttled (transport NOT called)."
        ),
        "input": {
            "config": cfg.to_wire_dict(),
            "rng_sequence": [0],
            "clock_start_secs": 0,
            "enqueues": enqueues,
            "transport_script": [{"kind": "accepted", "error": ""}],
            "tick_program": tick_program,
        },
        "expected": derived,
    }


def _fx_retry_backoff_success() -> Dict[str, Any]:
    # Generous bucket, RNG always returns upper bound -> backoff is
    # 1s, 2s, 4s, then success.
    cfg = SubmitWorkerConfig(
        rate_requests=100,
        rate_window_secs=1,
        max_retry=5,
        retry_base_delay_secs=1,
        retry_max_delay_secs=300,
    )
    transport = ScriptedTransport(
        [
            TransportOutcome.retriable("calendar-5xx-1"),
            TransportOutcome.retriable("calendar-5xx-2"),
            TransportOutcome.retriable("calendar-5xx-3"),
            TransportOutcome.accepted(),
        ]
    )
    clock = ManualClock(1_700_000_000)
    rng = DeterministicRng([999_999])
    enqueues = [{"event_id": "evt-tag26-f03-retry", "persona_id": "selin"}]
    tick_program = [
        {"op": "tick"},
        {"op": "advance_clock", "by_secs": 2},
        {"op": "tick"},
        {"op": "advance_clock", "by_secs": 3},
        {"op": "tick"},
        {"op": "advance_clock", "by_secs": 5},
        {"op": "tick"},
    ]
    derived = _ledger_from_ticks(cfg, transport, clock, rng, enqueues, tick_program)
    return {
        "name": "f03-retry-backoff-success",
        "doc": (
            "Retriable error three times, fourth attempt succeeds. RNG "
            "pinned to upper bound so the full-jitter backoff schedule "
            "is the deterministic 1s, 2s, 4s sequence."
        ),
        "input": {
            "config": cfg.to_wire_dict(),
            "rng_sequence": [999_999],
            "clock_start_secs": 1_700_000_000,
            "enqueues": enqueues,
            "transport_script": [
                {"kind": "retriable", "error": "calendar-5xx-1"},
                {"kind": "retriable", "error": "calendar-5xx-2"},
                {"kind": "retriable", "error": "calendar-5xx-3"},
                {"kind": "accepted", "error": ""},
            ],
            "tick_program": tick_program,
        },
        "expected": derived,
    }


def _fx_retry_exhausted_dead_letter() -> Dict[str, Any]:
    # max_retry=3, four retriable failures -> dead-letter. Backoffs
    # zero so we don't need to advance clock between ticks.
    cfg = SubmitWorkerConfig(
        rate_requests=100,
        rate_window_secs=1,
        max_retry=3,
        retry_base_delay_secs=1,
        retry_max_delay_secs=300,
    )
    transport = ScriptedTransport(
        [
            TransportOutcome.retriable("err-1"),
            TransportOutcome.retriable("err-2"),
            TransportOutcome.retriable("err-3"),
            TransportOutcome.retriable("TERMINAL-PIN"),
        ]
    )
    clock = ManualClock(1_700_000_500)
    rng = DeterministicRng([0])
    enqueues = [{"event_id": "evt-tag26-f04-dead", "persona_id": "kai"}]
    tick_program = [
        {"op": "tick"},
        {"op": "tick"},
        {"op": "tick"},
        {"op": "tick"},
    ]
    derived = _ledger_from_ticks(cfg, transport, clock, rng, enqueues, tick_program)
    return {
        "name": "f04-retry-exhausted-dead-letter",
        "doc": (
            "Four retriable failures with max_retry=3. The fourth attempt "
            "pushes retry_count above max_retry and dead-letters. RNG "
            "pinned to 0 so backoff is 0 and the tick program doesn't "
            "need clock advances."
        ),
        "input": {
            "config": cfg.to_wire_dict(),
            "rng_sequence": [0],
            "clock_start_secs": 1_700_000_500,
            "enqueues": enqueues,
            "transport_script": [
                {"kind": "retriable", "error": "err-1"},
                {"kind": "retriable", "error": "err-2"},
                {"kind": "retriable", "error": "err-3"},
                {"kind": "retriable", "error": "TERMINAL-PIN"},
            ],
            "tick_program": tick_program,
        },
        "expected": derived,
    }


def _fx_idle_empty_queue() -> Dict[str, Any]:
    cfg = SubmitWorkerConfig()
    transport = ScriptedTransport([])
    clock = ManualClock(1_700_001_234)
    rng = DeterministicRng([0])
    enqueues: List[Dict[str, Any]] = []
    tick_program = [{"op": "tick"}, {"op": "tick"}]
    derived = _ledger_from_ticks(cfg, transport, clock, rng, enqueues, tick_program)
    return {
        "name": "f05-idle-empty-queue",
        "doc": (
            "Empty queue, two ticks both return Idle. No transport call, "
            "no dead-letter, no writeback. Idle decision record has "
            "empty event_id and zero attempt/next_delay/terminal_error."
        ),
        "input": {
            "config": cfg.to_wire_dict(),
            "rng_sequence": [0],
            "clock_start_secs": 1_700_001_234,
            "enqueues": enqueues,
            "transport_script": [],
            "tick_program": tick_program,
        },
        "expected": derived,
    }


def main() -> None:
    fixtures = [
        _fx_success_fast_path(),
        _fx_throttled_rate_limit(),
        _fx_retry_backoff_success(),
        _fx_retry_exhausted_dead_letter(),
        _fx_idle_empty_queue(),
    ]
    doc = {
        "_comment": (
            "Cross-lang fixture vectors for the persona-engine "
            "anchor-submit-worker (Phase-3a Item 12 / Tag-26 Python-sync). "
            "Authoritative wire-pin: any drift on either side (Rust crate "
            "persona-engine-anchor-submit-worker or Python "
            "wirelang.persona_engine.anchor_submit_worker) must update "
            "this file in the same PR. Derivation procedure: "
            "scripts/derive-anchor-submit-worker-fixtures.py. Fixtures "
            "pinned 2026-05-17."
        ),
        "schema_version": DECISION_RECORD_SCHEMA,
        "fixtures": fixtures,
    }
    json.dump(doc, sys.stdout, indent=2, sort_keys=False, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
