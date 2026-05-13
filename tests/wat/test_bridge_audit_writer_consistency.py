# SPDX-License-Identifier: BUSL-1.1
"""24h, 1000+-event consistency tests for the Doppel-Audit-Trail bridge.

Verifies the Migrations-Plan-Schritt-5 done-criterion (per
``projects/migration-plan.md``): for a realistic pilot-phase trace
the two audit sinks MUST stay byte-balanced.

Invariants
----------

1. **Linecount balance:** ``count_wat_markers(persona)`` equals
   ``count_activity_log_lines_for_persona(persona)`` after a clean
   run for every persona that emitted events.
2. **Byte-deterministic ordering:** when events are submitted in a
   stable canonical order (sorted by ``(time, persona_id, action_type)``),
   the activity-log file is byte-identical across two independent runs.
3. **Failure rollback:** when a single Pre-Framework-failure is
   injected mid-trace, the WAT side stays balanced with the
   activity-log (failed event left no trace on either sink).
4. **WAT failure isolation:** when a single WAT-failure is injected,
   neither sink records the failed event; the trace continues
   cleanly for the remaining events.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import random
from pathlib import Path
from typing import List, Tuple

import pytest

from wat.anchor.bridge_audit_writer import (
    STATUS_OK,
    STATUS_PRE_FRAMEWORK_FAILED,
    STATUS_WAT_FAILED,
    count_activity_log_lines_for_persona,
    count_wat_markers,
    write_bridge_audit,
)


# ---------------------------------------------------------------------------
# Mock-Trace generator
# ---------------------------------------------------------------------------


PILOT_PERSONAS = ["tomas", "reza", "kai", "mira", "selin", "amara"]

ACTION_TYPES = [
    "pr-open",
    "pr-merge",
    "adr-vote",
    "hourly-tick",
    "git-commit",
    "spawn-dispatch",
    "outbox-write",
    "inbox-ack",
]


def _generate_24h_trace(
    event_count: int = 1024,
    base_day: str = "2026-05-13",
    seed: int = 42,
) -> List[Tuple[str, str, str, str]]:
    """Generate ``event_count`` mock persona-activity events over 24h.

    Each event is a ``(event_time, persona_id, action_type, payload_str)``
    tuple. Times are uniformly distributed across the day in 1-second
    granularity; persona/action picks come from a seeded RNG so reruns
    are reproducible byte-for-byte.

    Returns the events sorted ASCENDING by
    ``(event_time, persona_id, action_type)`` — the canonical order
    the bridge expects for byte-deterministic outputs.
    """
    rng = random.Random(seed)
    events: List[Tuple[str, str, str, str]] = []
    day_start = dt.datetime.fromisoformat(f"{base_day}T00:00:00+00:00")
    for i in range(event_count):
        seconds_into_day = rng.randint(0, 24 * 3600 - 1)
        when = day_start + dt.timedelta(seconds=seconds_into_day)
        ts = when.strftime("%Y-%m-%dT%H:%M:%SZ")
        persona = rng.choice(PILOT_PERSONAS)
        action = rng.choice(ACTION_TYPES)
        payload = f"event-{i}-{persona}-{action}"
        events.append((ts, persona, action, payload))
    # Sort by canonical tie-break order: time → persona → action.
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    return events


# ---------------------------------------------------------------------------
# Invariant 1: Linecount balance over a clean 1000+-event trace
# ---------------------------------------------------------------------------


def test_24h_1000_events_linecount_balanced(tmp_path: Path):
    spool_root = tmp_path / "spool"
    activity_log = tmp_path / "activity-log.md"
    activity_log.write_text("# Activity Log — consistency-trace\n\n", encoding="utf-8")

    events = _generate_24h_trace(event_count=1024)
    assert len(events) == 1024

    per_persona_submitted: dict[str, int] = {p: 0 for p in PILOT_PERSONAS}
    for ts, persona, action, payload in events:
        result = write_bridge_audit(
            persona_id=persona,
            action_type=action,
            payload_hash=hashlib.sha256(payload.encode()).hexdigest(),
            metadata={"ref": f"trace-{payload}"},
            spool_root=spool_root,
            activity_log_path=activity_log,
            event_time=ts,
        )
        assert result.status == STATUS_OK, result.error
        per_persona_submitted[persona] += 1

    # Per-persona linecount balance.
    for persona, expected in per_persona_submitted.items():
        wat = count_wat_markers(spool_root, persona)
        pre = count_activity_log_lines_for_persona(activity_log, persona)
        assert wat == expected, (
            f"persona={persona}: WAT count {wat} != expected {expected}"
        )
        assert pre == expected, (
            f"persona={persona}: pre-framework count {pre} != expected {expected}"
        )
        assert wat == pre, (
            f"persona={persona}: WAT {wat} vs pre-framework {pre} drift"
        )


# ---------------------------------------------------------------------------
# Invariant 2: Byte-deterministic activity-log
# ---------------------------------------------------------------------------


def test_24h_trace_is_byte_deterministic(tmp_path: Path):
    """Two independent runs with the same canonical-ordered event
    sequence MUST produce byte-identical activity-log files (modulo
    the seed header line)."""
    events = _generate_24h_trace(event_count=512)

    def _run(run_dir: Path) -> bytes:
        spool_root = run_dir / "spool"
        log = run_dir / "activity-log.md"
        # Empty seed header so the comparison is event-only.
        log.write_text("", encoding="utf-8")
        for ts, persona, action, payload in events:
            write_bridge_audit(
                persona_id=persona,
                action_type=action,
                payload_hash=hashlib.sha256(payload.encode()).hexdigest(),
                metadata={"ref": f"det-{payload}"},
                spool_root=spool_root,
                activity_log_path=log,
                event_time=ts,
            )
        return log.read_bytes()

    run_a_dir = tmp_path / "run-a"
    run_b_dir = tmp_path / "run-b"
    run_a_dir.mkdir()
    run_b_dir.mkdir()
    out_a = _run(run_a_dir)
    out_b = _run(run_b_dir)
    assert out_a == out_b, "byte-identity of activity-log across runs broken"


# ---------------------------------------------------------------------------
# Invariant 3: Pre-Framework failure mid-trace stays balanced
# ---------------------------------------------------------------------------


def test_pre_framework_failure_mid_trace_keeps_sinks_balanced(tmp_path: Path):
    spool_root = tmp_path / "spool"
    activity_log = tmp_path / "activity-log.md"
    activity_log.write_text("", encoding="utf-8")

    events = _generate_24h_trace(event_count=100)
    # Inject failure on the 37th event (arbitrary mid-trace pick).
    failure_index = 37

    per_persona_ok: dict[str, int] = {p: 0 for p in PILOT_PERSONAS}
    statuses: list[str] = []
    for i, (ts, persona, action, payload) in enumerate(events):
        fail_pre = i == failure_index
        result = write_bridge_audit(
            persona_id=persona,
            action_type=action,
            payload_hash=hashlib.sha256(payload.encode()).hexdigest(),
            metadata={"ref": f"trace-{payload}"},
            spool_root=spool_root,
            activity_log_path=activity_log,
            event_time=ts,
            _fail_pre_framework=fail_pre,
        )
        statuses.append(result.status)
        if result.status == STATUS_OK:
            per_persona_ok[persona] += 1

    # Exactly one event landed as PRE_FRAMEWORK_FAILED.
    assert statuses.count(STATUS_PRE_FRAMEWORK_FAILED) == 1
    # All others OK.
    assert statuses.count(STATUS_OK) == 99

    # Per-persona balance still holds: the failed event left no trace
    # on either sink.
    for persona, expected_ok in per_persona_ok.items():
        wat = count_wat_markers(spool_root, persona)
        pre = count_activity_log_lines_for_persona(activity_log, persona)
        assert wat == expected_ok, (
            f"persona={persona}: WAT {wat} vs expected-ok {expected_ok}"
        )
        assert pre == expected_ok, (
            f"persona={persona}: pre-framework {pre} vs expected-ok {expected_ok}"
        )


# ---------------------------------------------------------------------------
# Invariant 4: WAT-side failure isolation
# ---------------------------------------------------------------------------


def test_wat_failure_mid_trace_does_not_touch_activity_log(tmp_path: Path):
    spool_root = tmp_path / "spool"
    activity_log = tmp_path / "activity-log.md"
    activity_log.write_text("", encoding="utf-8")

    events = _generate_24h_trace(event_count=50, seed=99)
    failure_index = 13

    statuses: list[str] = []
    for i, (ts, persona, action, payload) in enumerate(events):
        fail_wat = i == failure_index
        result = write_bridge_audit(
            persona_id=persona,
            action_type=action,
            payload_hash=hashlib.sha256(payload.encode()).hexdigest(),
            metadata={"ref": f"wat-iso-{payload}"},
            spool_root=spool_root,
            activity_log_path=activity_log,
            event_time=ts,
            _fail_wat=fail_wat,
        )
        statuses.append(result.status)

    assert statuses.count(STATUS_WAT_FAILED) == 1
    assert statuses.count(STATUS_OK) == 49

    # Total balance across all personas.
    total_wat = sum(
        count_wat_markers(spool_root, p) for p in PILOT_PERSONAS
    )
    total_pre = sum(
        count_activity_log_lines_for_persona(activity_log, p)
        for p in PILOT_PERSONAS
    )
    assert total_wat == 49
    assert total_pre == 49
    assert total_wat == total_pre


# ---------------------------------------------------------------------------
# Invariant 5: Across-persona ordering tie-break is stable
# ---------------------------------------------------------------------------


def test_same_timestamp_events_use_stable_persona_action_tie_break(tmp_path: Path):
    """Two events with the same RFC-3339 second-precision time MUST
    land on the activity-log in ``(persona_id, action_type)``-ASCII
    order. This guarantees byte-determinism when sub-second-precision
    is not available.
    """
    spool_root = tmp_path / "spool"
    activity_log = tmp_path / "activity-log.md"
    activity_log.write_text("", encoding="utf-8")

    ts = "2026-05-13T16:00:00Z"
    # Submit deliberately out-of-order to exercise the caller's
    # responsibility to sort first. The bridge does NOT internally
    # re-order; it relies on the caller honouring the canonical
    # (time, persona, action) sort. Here we sort explicitly to
    # demonstrate the contract.
    raw_events = [
        ("reza", "adr-vote"),
        ("tomas", "pr-open"),
        ("kai", "spawn-dispatch"),
        ("tomas", "git-commit"),
    ]
    canonical = sorted(raw_events, key=lambda e: (ts, e[0], e[1]))

    for persona, action in canonical:
        result = write_bridge_audit(
            persona_id=persona,
            action_type=action,
            payload_hash=hashlib.sha256(
                f"{persona}-{action}".encode()
            ).hexdigest(),
            metadata={},
            spool_root=spool_root,
            activity_log_path=activity_log,
            event_time=ts,
        )
        assert result.status == STATUS_OK

    lines = [
        line
        for line in activity_log.read_text(encoding="utf-8").splitlines()
        if " · " in line
    ]
    # Expected ASCII tie-break order:
    #   kai < reza < tomas
    #   tomas/git-commit < tomas/pr-open
    expected_first_columns = [
        ("kai", "spawn-dispatch"),
        ("reza", "adr-vote"),
        ("tomas", "git-commit"),
        ("tomas", "pr-open"),
    ]
    parsed = []
    for line in lines:
        parts = [p.strip() for p in line.split(" · ")]
        if len(parts) >= 3:
            parsed.append((parts[1], parts[2]))
    assert parsed == expected_first_columns
