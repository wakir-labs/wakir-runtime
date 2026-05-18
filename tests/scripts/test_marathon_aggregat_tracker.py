# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/phase-3c/marathon-aggregat-tracker.py - Tag-40.

Hermetic, stdlib + pytest only. Loads the tracker via importlib from
its hyphenated path under ``scripts/phase-3c/``. State files are
written to ``tmp_path`` fixtures. No network, no podman, no git.

Scope (16 tests)
----------------

 1. test_module_loads_and_exports_public_surface
 2. test_build_initial_state_has_seven_pending_welles
 3. test_legal_transitions_forward_path_walks_all_states
 4. test_legal_transitions_skip_state_is_rejected
 5. test_legal_transitions_rollback_only_from_cutover_onwards
 6. test_legal_transitions_terminal_states_have_no_outbound
 7. test_update_welle_records_history_with_note
 8. test_save_and_load_state_roundtrip_preserves_history
 9. test_load_state_rejects_unknown_schema_version
10. test_load_state_rejects_unknown_state_name
11. test_compute_aggregate_counters_split_by_class
12. test_phase_3_complete_trigger_fires_exactly_once
13. test_emit_phase_3_complete_event_is_idempotent
14. test_render_marathon_table_contains_all_seven_welles
15. test_coupling_indicator_marks_pair_drift_and_solo
16. test_cli_show_marathon_smoke_and_update_welle_roundtrip
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# Module loader (hyphenated filename -> importlib.util)
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKER_PATH = (
    REPO_ROOT / "scripts" / "phase-3c" / "marathon-aggregat-tracker.py"
)


def _load_tracker_module():
    spec = importlib.util.spec_from_file_location(
        "marathon_aggregat_tracker", TRACKER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


tracker = _load_tracker_module()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface():
    """The tracker module exposes the documented public symbols."""

    expected = {
        "WelleLifecycleState",
        "WELLE_DEFINITIONS",
        "FORWARD_SEQUENCE",
        "LEGAL_TRANSITIONS",
        "TERMINAL_STATES",
        "ROLLBACK_ENTRY_STATES",
        "WelleEntry",
        "MarathonState",
        "AggregateView",
        "build_initial_state",
        "load_state",
        "save_state",
        "load_or_init",
        "validate_transition",
        "update_welle",
        "emit_phase_3_complete_event",
        "compute_aggregate",
        "render_marathon_table",
        "render_welle_detail",
        "main",
        "StateTransitionError",
        "StateFileError",
        "UnknownWelleError",
        "EVENT_PHASE_3_COMPLETE",
        "SCHEMA_VERSION",
    }
    for name in expected:
        assert hasattr(tracker, name), f"missing symbol: {name}"


def test_build_initial_state_has_seven_pending_welles():
    """A fresh initial state has all 7 welles in `pending` with timestamps."""

    state = tracker.build_initial_state(now="2026-05-18T00:00:00Z")
    assert state.schema_version == tracker.SCHEMA_VERSION
    assert state.phase_3_complete is False
    assert state.phase_3_complete_utc is None
    assert set(state.welles.keys()) == {1, 2, 3, 4, 5, 6, 7}
    for num, entry in state.welles.items():
        assert entry.state == tracker.WelleLifecycleState.PENDING
        assert entry.welle == num
        assert entry.first_seen_utc == "2026-05-18T00:00:00Z"
        assert entry.last_updated_utc == "2026-05-18T00:00:00Z"
        assert len(entry.history) == 1
        assert entry.history[0]["state"] == "pending"
        assert entry.history[0]["note"] is None
    # Welle metadata must match WELLE_DEFINITIONS.
    assert state.welles[1].domain == "v907_verify"
    assert state.welles[3].pair == "solo"
    assert state.welles[7].kw == "KW 27"


def test_legal_transitions_forward_path_walks_all_states():
    """All 8 forward transitions are accepted in sequence."""

    state = tracker.build_initial_state(now="2026-05-18T00:00:00Z")
    forward = list(tracker.FORWARD_SEQUENCE)
    # Walk welle-1 through the full forward path.
    for i in range(len(forward) - 1):
        tracker.update_welle(
            state,
            1,
            forward[i + 1],
            note=f"step-{i}",
            now=f"2026-05-18T00:0{i}:00Z",
        )
    assert (
        state.welles[1].state == tracker.WelleLifecycleState.SIGNED_OFF
    )
    # History captures every step including the initial PENDING.
    assert len(state.welles[1].history) == len(forward)


def test_legal_transitions_skip_state_is_rejected():
    """Skipping a forward state is rejected with StateTransitionError."""

    state = tracker.build_initial_state(now="2026-05-18T00:00:00Z")
    # PENDING -> CUTOVER_RUNNING (skipping pre-flight) must fail.
    with pytest.raises(tracker.StateTransitionError):
        tracker.update_welle(
            state,
            2,
            tracker.WelleLifecycleState.CUTOVER_RUNNING,
            now="2026-05-18T00:01:00Z",
        )
    # PENDING -> SIGNED_OFF must also fail.
    with pytest.raises(tracker.StateTransitionError):
        tracker.update_welle(
            state,
            2,
            tracker.WelleLifecycleState.SIGNED_OFF,
            now="2026-05-18T00:02:00Z",
        )
    # State must remain pending after both rejections.
    assert state.welles[2].state == tracker.WelleLifecycleState.PENDING


def test_legal_transitions_rollback_only_from_cutover_onwards():
    """Rollback is illegal from PENDING / pre-flight states (Invariant I3)."""

    state = tracker.build_initial_state(now="2026-05-18T00:00:00Z")
    # PENDING -> ROLLBACK_RUNNING must fail.
    with pytest.raises(tracker.StateTransitionError):
        tracker.update_welle(
            state, 3, tracker.WelleLifecycleState.ROLLBACK_RUNNING,
            now="2026-05-18T00:01:00Z",
        )
    # Advance to PRE_FLIGHT_RUNNING.
    tracker.update_welle(
        state, 3, tracker.WelleLifecycleState.PRE_FLIGHT_RUNNING,
        now="2026-05-18T00:02:00Z",
    )
    with pytest.raises(tracker.StateTransitionError):
        tracker.update_welle(
            state, 3, tracker.WelleLifecycleState.ROLLBACK_RUNNING,
            now="2026-05-18T00:03:00Z",
        )
    # Advance to PRE_FLIGHT_GREEN.
    tracker.update_welle(
        state, 3, tracker.WelleLifecycleState.PRE_FLIGHT_GREEN,
        now="2026-05-18T00:04:00Z",
    )
    with pytest.raises(tracker.StateTransitionError):
        tracker.update_welle(
            state, 3, tracker.WelleLifecycleState.ROLLBACK_RUNNING,
            now="2026-05-18T00:05:00Z",
        )
    # Advance to CUTOVER_RUNNING - now rollback is legal.
    tracker.update_welle(
        state, 3, tracker.WelleLifecycleState.CUTOVER_RUNNING,
        now="2026-05-18T00:06:00Z",
    )
    tracker.update_welle(
        state, 3, tracker.WelleLifecycleState.ROLLBACK_RUNNING,
        now="2026-05-18T00:07:00Z",
    )
    tracker.update_welle(
        state, 3, tracker.WelleLifecycleState.ROLLED_BACK,
        now="2026-05-18T00:08:00Z",
    )
    assert state.welles[3].state == tracker.WelleLifecycleState.ROLLED_BACK


def test_legal_transitions_terminal_states_have_no_outbound():
    """SIGNED_OFF and ROLLED_BACK have no legal outbound transitions."""

    for terminal in tracker.TERMINAL_STATES:
        legal = tracker.LEGAL_TRANSITIONS.get(terminal, frozenset())
        assert legal == frozenset(), (
            f"terminal {terminal.value!r} must have no outbound transitions, "
            f"got {[s.value for s in legal]}"
        )
    # And update_welle on a terminal state raises.
    state = tracker.build_initial_state(now="2026-05-18T00:00:00Z")
    # Walk welle-4 to SIGNED_OFF.
    forward = list(tracker.FORWARD_SEQUENCE)
    for i in range(len(forward) - 1):
        tracker.update_welle(
            state, 4, forward[i + 1],
            now=f"2026-05-18T01:{i:02d}:00Z",
        )
    assert state.welles[4].state == tracker.WelleLifecycleState.SIGNED_OFF
    with pytest.raises(tracker.StateTransitionError):
        tracker.update_welle(
            state, 4, tracker.WelleLifecycleState.PENDING,
            now="2026-05-18T02:00:00Z",
        )


def test_update_welle_records_history_with_note():
    """Each transition appends a history row with note + timestamp."""

    state = tracker.build_initial_state(now="2026-05-18T00:00:00Z")
    tracker.update_welle(
        state, 5,
        tracker.WelleLifecycleState.PRE_FLIGHT_RUNNING,
        note="kicked-off-by-noa",
        now="2026-05-18T00:01:00Z",
    )
    tracker.update_welle(
        state, 5,
        tracker.WelleLifecycleState.PRE_FLIGHT_GREEN,
        note="pr-260-merged",
        now="2026-05-18T00:02:00Z",
    )
    h = state.welles[5].history
    assert len(h) == 3
    assert h[0]["state"] == "pending"
    assert h[1] == {
        "state": "pre-flight-running",
        "utc": "2026-05-18T00:01:00Z",
        "note": "kicked-off-by-noa",
    }
    assert h[2] == {
        "state": "pre-flight-green",
        "utc": "2026-05-18T00:02:00Z",
        "note": "pr-260-merged",
    }
    # Top-level last_updated_utc reflects the latest transition.
    assert state.welles[5].last_updated_utc == "2026-05-18T00:02:00Z"
    assert state.updated_utc == "2026-05-18T00:02:00Z"


def test_save_and_load_state_roundtrip_preserves_history(tmp_path):
    """Save + load produces an equivalent state document."""

    state = tracker.build_initial_state(now="2026-05-18T00:00:00Z")
    tracker.update_welle(
        state, 1, tracker.WelleLifecycleState.PRE_FLIGHT_RUNNING,
        note="step-a", now="2026-05-18T00:01:00Z",
    )
    tracker.update_welle(
        state, 1, tracker.WelleLifecycleState.PRE_FLIGHT_GREEN,
        note="step-b", now="2026-05-18T00:02:00Z",
    )
    path = tmp_path / "subdir" / "state.json"
    tracker.save_state(state, path)
    assert path.exists()
    loaded = tracker.load_state(path)
    assert loaded.schema_version == tracker.SCHEMA_VERSION
    assert loaded.welles[1].state == tracker.WelleLifecycleState.PRE_FLIGHT_GREEN
    assert loaded.welles[1].history == state.welles[1].history
    # All seven welles preserved.
    assert set(loaded.welles.keys()) == set(tracker.WELLE_DEFINITIONS.keys())


def test_load_state_rejects_unknown_schema_version(tmp_path):
    """Schema-version mismatch raises StateFileError."""

    path = tmp_path / "state.json"
    payload = {
        "schema_version": 999,
        "created_utc": "2026-05-18T00:00:00Z",
        "updated_utc": "2026-05-18T00:00:00Z",
        "phase_3_complete": False,
        "phase_3_complete_utc": None,
        "welles": {},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(tracker.StateFileError):
        tracker.load_state(path)


def test_load_state_rejects_unknown_state_name(tmp_path):
    """Unknown lifecycle state in the file raises StateFileError."""

    state = tracker.build_initial_state(now="2026-05-18T00:00:00Z")
    doc = state.to_dict()
    doc["welles"]["1"]["state"] = "garbage-state"
    path = tmp_path / "state.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(tracker.StateFileError):
        tracker.load_state(path)


def test_compute_aggregate_counters_split_by_class():
    """Aggregate splits into pending / in-flight / signed-off / rolled-back."""

    state = tracker.build_initial_state(now="2026-05-18T00:00:00Z")
    # welle-1 fully signed-off.
    forward = list(tracker.FORWARD_SEQUENCE)
    for i in range(len(forward) - 1):
        tracker.update_welle(
            state, 1, forward[i + 1],
            now=f"2026-05-18T01:{i:02d}:00Z",
        )
    # welle-2 mid-flight at SOAK_RUNNING.
    soak_running_idx = forward.index(
        tracker.WelleLifecycleState.SOAK_RUNNING
    )
    for i in range(soak_running_idx):
        tracker.update_welle(
            state, 2, forward[i + 1],
            now=f"2026-05-18T02:{i:02d}:00Z",
        )
    # welle-3 rolled-back.
    cut_idx = forward.index(
        tracker.WelleLifecycleState.CUTOVER_RUNNING
    )
    for i in range(cut_idx):
        tracker.update_welle(
            state, 3, forward[i + 1],
            now=f"2026-05-18T03:{i:02d}:00Z",
        )
    tracker.update_welle(
        state, 3, tracker.WelleLifecycleState.ROLLBACK_RUNNING,
        now="2026-05-18T03:50:00Z",
    )
    tracker.update_welle(
        state, 3, tracker.WelleLifecycleState.ROLLED_BACK,
        now="2026-05-18T03:51:00Z",
    )
    agg = tracker.compute_aggregate(state)
    assert agg.total_welles == 7
    assert agg.signed_off_count == 1
    assert agg.in_flight_count == 1
    assert agg.rolled_back_count == 1
    assert agg.pending_count == 4
    assert agg.progress_pct == pytest.approx(100.0 / 7, abs=0.01)
    assert agg.phase_3_complete is False


def test_phase_3_complete_trigger_fires_exactly_once():
    """All seven welles SIGNED_OFF flips phase_3_complete True exactly once."""

    state = tracker.build_initial_state(now="2026-05-18T00:00:00Z")
    forward = list(tracker.FORWARD_SEQUENCE)
    # Walk all 7 welles to SIGNED_OFF.
    for num in range(1, 8):
        for i in range(len(forward) - 1):
            tracker.update_welle(
                state, num, forward[i + 1],
                now=f"2026-05-{18 + num // 4:02d}T0{num % 4}:{i:02d}:00Z",
            )
    assert state.phase_3_complete is True
    assert state.phase_3_complete_utc is not None
    first_complete_utc = state.phase_3_complete_utc
    # A no-op call to update_welle would itself raise, so the trigger
    # has fired exactly once; the timestamp must remain stable across
    # subsequent reads.
    agg = tracker.compute_aggregate(state)
    assert agg.phase_3_complete is True
    assert agg.phase_3_complete_utc == first_complete_utc
    # All welles SIGNED_OFF.
    for num in range(1, 8):
        assert (
            state.welles[num].state
            == tracker.WelleLifecycleState.SIGNED_OFF
        )


def test_emit_phase_3_complete_event_is_idempotent(tmp_path):
    """Calling emit twice creates the event-file once."""

    state = tracker.build_initial_state(now="2026-05-18T00:00:00Z")
    # Not yet complete - emit returns None.
    assert tracker.emit_phase_3_complete_event(state, tmp_path) is None
    # Walk all welles to SIGNED_OFF.
    forward = list(tracker.FORWARD_SEQUENCE)
    for num in range(1, 8):
        for i in range(len(forward) - 1):
            tracker.update_welle(
                state, num, forward[i + 1],
                now=f"2026-05-{18 + num // 4:02d}T0{num % 4}:{i:02d}:00Z",
            )
    p1 = tracker.emit_phase_3_complete_event(state, tmp_path)
    assert p1 is not None and p1.exists()
    first_mtime = p1.stat().st_mtime_ns
    # Re-emit must not rewrite the file.
    p2 = tracker.emit_phase_3_complete_event(state, tmp_path)
    assert p2 == p1
    assert p2.stat().st_mtime_ns == first_mtime
    payload = json.loads(p1.read_text(encoding="utf-8"))
    assert payload["event"] == tracker.EVENT_PHASE_3_COMPLETE
    assert payload["schema_version"] == tracker.SCHEMA_VERSION
    assert set(payload["welles"].keys()) == {"1", "2", "3", "4", "5", "6", "7"}
    for v in payload["welles"].values():
        assert v == "signed-off"


def test_render_marathon_table_contains_all_seven_welles():
    """The ASCII table renders one row per welle + aggregate summary line."""

    state = tracker.build_initial_state(now="2026-05-18T00:00:00Z")
    tracker.update_welle(
        state, 1, tracker.WelleLifecycleState.PRE_FLIGHT_RUNNING,
        now="2026-05-18T00:01:00Z",
    )
    tracker.update_welle(
        state, 1, tracker.WelleLifecycleState.PRE_FLIGHT_GREEN,
        now="2026-05-18T00:02:00Z",
    )
    out = tracker.render_marathon_table(state)
    # Header + 7 welle rows + aggregate footer.
    for dom in (
        "v907_verify",
        "svid_workload_identity",
        "bridge_audit_writer",
        "state_backing",
        "lifecycle_state_machine",
        "subscribe_loop",
        "recovery_workflow",
    ):
        assert dom in out, f"domain {dom} missing from table"
    assert "KW 24" in out
    assert "KW 27" in out
    assert "Marathon:" in out
    assert "signed-off=0/7" in out


def test_coupling_indicator_marks_pair_drift_and_solo():
    """Welle-3 solo, doppel-wellen show sync/near/drift indicators."""

    state = tracker.build_initial_state(now="2026-05-18T00:00:00Z")
    # Solo.
    assert tracker._coupling_indicator(state, 3) == "solo"
    # Doppel sync at pending.
    assert tracker._coupling_indicator(state, 1) == "<-w2:sync"
    # Advance welle-1 three steps ahead of welle-2.
    forward = list(tracker.FORWARD_SEQUENCE)
    for i in range(3):
        tracker.update_welle(
            state, 1, forward[i + 1],
            now=f"2026-05-18T00:{i:02d}:00Z",
        )
    # welle-1 at CUTOVER_RUNNING (idx 3), welle-2 still PENDING (idx 0).
    assert tracker._coupling_indicator(state, 1) == "<-w2:DRIFT"
    # Advance welle-2 two steps - drift becomes near (1 step).
    tracker.update_welle(
        state, 2, tracker.WelleLifecycleState.PRE_FLIGHT_RUNNING,
        now="2026-05-18T01:00:00Z",
    )
    tracker.update_welle(
        state, 2, tracker.WelleLifecycleState.PRE_FLIGHT_GREEN,
        now="2026-05-18T01:01:00Z",
    )
    assert tracker._coupling_indicator(state, 1) == "<-w2:near"


def test_cli_show_marathon_smoke_and_update_welle_roundtrip(tmp_path):
    """CLI smoke: --show-marathon, --update-welle, --show-aggregat, --show-welle."""

    state_path = tmp_path / "state" / "phase-3-marathon-state.json"
    event_dir = tmp_path / "state" / "events"

    # Initial --show-marathon on empty repo - creates implicit fresh state.
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = tracker.main(
            [
                "--state-path",
                str(state_path),
                "--event-dir",
                str(event_dir),
                "--show-marathon",
            ]
        )
    assert rc == 0
    out = buf.getvalue()
    assert "Marathon:" in out
    # State file is NOT created by show (read-only).
    assert not state_path.exists()

    # --update-welle 1 --state pre-flight-running.
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = tracker.main(
            [
                "--state-path",
                str(state_path),
                "--event-dir",
                str(event_dir),
                "--update-welle",
                "1",
                "--state",
                "pre-flight-running",
                "--note",
                "tag-40-test",
            ]
        )
    assert rc == 0
    assert state_path.exists()
    doc = json.loads(state_path.read_text(encoding="utf-8"))
    assert doc["welles"]["1"]["state"] == "pre-flight-running"

    # Illegal transition is rejected with rc=1.
    buf = io.StringIO()
    errbuf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(errbuf):
        rc = tracker.main(
            [
                "--state-path",
                str(state_path),
                "--event-dir",
                str(event_dir),
                "--update-welle",
                "1",
                "--state",
                "signed-off",
            ]
        )
    assert rc == 1
    assert "transition rejected" in errbuf.getvalue()

    # --show-aggregat emits JSON.
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = tracker.main(
            [
                "--state-path",
                str(state_path),
                "--show-aggregat",
            ]
        )
    assert rc == 0
    agg = json.loads(buf.getvalue())
    assert agg["total_welles"] == 7
    assert agg["phase_3_complete"] is False

    # --show-welle 1 renders detail.
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = tracker.main(
            [
                "--state-path",
                str(state_path),
                "--show-welle",
                "1",
            ]
        )
    assert rc == 0
    out = buf.getvalue()
    assert "Welle 1 - v907_verify" in out
    assert "pre-flight-running" in out
    assert "tag-40-test" in out

    # --show-welle 99 rejected with rc=3.
    buf = io.StringIO()
    errbuf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(errbuf):
        rc = tracker.main(
            [
                "--state-path",
                str(state_path),
                "--show-welle",
                "99",
            ]
        )
    assert rc == 3
    assert "welle=99" in errbuf.getvalue()
