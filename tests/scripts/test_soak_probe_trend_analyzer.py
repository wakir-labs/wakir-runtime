# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for scripts/persona-engine/soak-probe-trend-analyzer.py
(Tag-55).

The analyzer is loaded via importlib from its hyphenated path under
``scripts/persona-engine/``. No network, no podman, no real time
passes. Synthetic DailyReports drive the trend logic; an end-to-end
test ingests a real soak-probe-5-day report through the analyzer's
ingest+walk+build_trend_report+notify pipeline.

Scope (15 tests, target was >=10)
---------------------------------

1.  test_module_loads_and_exports_public_surface
2.  test_all_invariant_keys_match_soak_probe_module
3.  test_parse_soak_report_accepts_raw_probe_shape
4.  test_parse_soak_report_accepts_persisted_shape_roundtrip
5.  test_parse_soak_report_rejects_garbage
6.  test_classify_invariant_change_all_paths
7.  test_compute_window_dates_basic_and_rejects_zero
8.  test_compute_consecutive_fail_streak_counts_trailing_only
9.  test_build_trend_report_clean_history_all_pass
10. test_build_trend_report_detects_pass_to_fail_invariant_degraded
11. test_build_trend_report_detects_fingerprint_drift
12. test_build_trend_report_counts_consecutive_fails_streak
13. test_build_notify_events_persistent_fail_emits_page
14. test_build_notify_events_dedupe_via_event_id
15. test_build_notify_events_no_changes_emits_nothing
16. test_render_trend_markdown_contains_today_date_and_streak
17. test_e2e_ingest_real_soak_probe_report_and_build_trend
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ANALYZER_PATH = (
    REPO_ROOT
    / "scripts"
    / "persona-engine"
    / "soak-probe-trend-analyzer.py"
)
SOAK_PROBE_PATH = (
    REPO_ROOT / "scripts" / "persona-engine" / "soak-probe-5-day.py"
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def analyzer_mod():
    return _load_module("soak_probe_trend_analyzer", ANALYZER_PATH)


@pytest.fixture(scope="module")
def soak_probe_mod():
    return _load_module("soak_probe_5_day", SOAK_PROBE_PATH)


def _make_daily_report(
    analyzer_mod, *, date_iso, overall_ok=True, invariant_oks=None,
    boot_fp="a" * 64, fsm_trace_hash="b" * 64, v907_pin="c" * 64,
    decisions_payload_bytes=1055,
):
    """Helper: build a synthetic DailyReport with defaults."""
    if invariant_oks is None:
        invariant_oks = {
            k: True for k in analyzer_mod.ALL_INVARIANT_KEYS
        }
    return analyzer_mod.DailyReport(
        date_iso=date_iso,
        overall_ok=overall_ok,
        invariants_passed=sum(1 for v in invariant_oks.values() if v),
        invariants_total=len(invariant_oks),
        days_observed=5,
        invariant_oks=invariant_oks,
        boot_fp=boot_fp,
        fsm_trace_hash=fsm_trace_hash,
        v907_pin=v907_pin,
        decisions_payload_bytes=decisions_payload_bytes,
    )


# ---------------------------------------------------------------------
# Test 1 -- module public surface
# ---------------------------------------------------------------------


def test_module_loads_and_exports_public_surface(analyzer_mod):
    """The analyzer exposes the documented public entry points."""
    for name in (
        "DailyReport",
        "InvariantChange",
        "TrendReport",
        "parse_soak_report",
        "classify_invariant_change",
        "compute_window_dates",
        "compute_consecutive_fail_streak",
        "build_trend_report",
        "build_notify_events",
        "render_trend_markdown",
        "walk_daily_state_dir",
        "write_notify_events",
        "persist_daily_report",
        "ingest_soak_report",
        "cli_main",
        "ALL_INVARIANT_KEYS",
        "DEFAULT_WINDOW_DAYS",
        "DEFAULT_STATE_DIR",
        "DEFAULT_NOTIFY_PATH",
        "ALERT_NAME_INVARIANT_FAIL",
        "ALERT_NAME_PERSISTENT_FAIL",
        "ALERT_NAME_FINGERPRINT_DRIFT",
    ):
        assert hasattr(analyzer_mod, name), (
            f"public surface missing: {name}"
        )


# ---------------------------------------------------------------------
# Test 2 -- ALL_INVARIANT_KEYS matches soak-probe-5-day output
# ---------------------------------------------------------------------


def test_all_invariant_keys_match_soak_probe_module(
    analyzer_mod, soak_probe_mod
):
    """The analyzer's invariant-keys must match the actual keys the
    soak-probe emits. Drift between the two would mean the analyzer
    silently mis-aggregates."""
    actual_report = soak_probe_mod.run_soak_probe(days=2)
    actual_keys = set(actual_report.invariants.keys())
    analyzer_keys = set(analyzer_mod.ALL_INVARIANT_KEYS)
    assert actual_keys == analyzer_keys, (
        f"key drift between probe and analyzer: "
        f"probe-only={actual_keys - analyzer_keys}, "
        f"analyzer-only={analyzer_keys - actual_keys}"
    )


# ---------------------------------------------------------------------
# Test 3 -- parse_soak_report accepts raw probe shape
# ---------------------------------------------------------------------


def test_parse_soak_report_accepts_raw_probe_shape(
    analyzer_mod, soak_probe_mod
):
    """Feed the analyzer a real raw probe report; it parses cleanly."""
    raw_report = soak_probe_mod.run_soak_probe(days=3).as_dict()
    parsed = analyzer_mod.parse_soak_report(
        raw_report, fallback_date_iso="2026-05-19"
    )
    assert parsed.date_iso == "2026-05-19"
    assert parsed.overall_ok is True
    assert parsed.invariants_total == 6
    assert parsed.invariants_passed == 6
    assert parsed.days_observed == 3
    # Fingerprint fields populated from day-1. The v907_pin may
    # be prefixed (``sha256:<hex>``) by the strict-V-907 substrate;
    # the fallback bare-sha256 path emits a plain 64-hex string.
    assert len(parsed.boot_fp) == 64
    assert len(parsed.fsm_trace_hash) == 64
    assert parsed.v907_pin
    assert parsed.decisions_payload_bytes > 0
    # All six invariant keys present.
    assert set(parsed.invariant_oks.keys()) == set(
        analyzer_mod.ALL_INVARIANT_KEYS
    )
    assert all(parsed.invariant_oks.values())


# ---------------------------------------------------------------------
# Test 4 -- parse_soak_report round-trips persisted shape
# ---------------------------------------------------------------------


def test_parse_soak_report_accepts_persisted_shape_roundtrip(
    analyzer_mod
):
    """A DailyReport.to_envelope() -> parse_soak_report() round-trips."""
    rep = _make_daily_report(analyzer_mod, date_iso="2026-05-19")
    blob = rep.to_envelope()
    rep2 = analyzer_mod.parse_soak_report(blob)
    assert rep2.date_iso == rep.date_iso
    assert rep2.overall_ok == rep.overall_ok
    assert rep2.invariant_oks == rep.invariant_oks
    assert rep2.boot_fp == rep.boot_fp
    assert rep2.fsm_trace_hash == rep.fsm_trace_hash
    assert rep2.v907_pin == rep.v907_pin
    assert rep2.decisions_payload_bytes == rep.decisions_payload_bytes


# ---------------------------------------------------------------------
# Test 5 -- parse_soak_report rejects garbage
# ---------------------------------------------------------------------


def test_parse_soak_report_rejects_garbage(analyzer_mod):
    """A non-dict blob raises ValueError; missing required fields too."""
    with pytest.raises(ValueError):
        analyzer_mod.parse_soak_report("not-a-dict")
    with pytest.raises(ValueError):
        # Has none of the recognised top-level keys + no 'days'.
        analyzer_mod.parse_soak_report({"random": "data"})
    with pytest.raises(ValueError):
        # Empty days[] list.
        analyzer_mod.parse_soak_report(
            {"days": [], "invariants": {}, "summary": {}}
        )


# ---------------------------------------------------------------------
# Test 6 -- classify_invariant_change all four paths
# ---------------------------------------------------------------------


def test_classify_invariant_change_all_paths(analyzer_mod):
    """All four kinds (NEW / LATERAL / DEGRADED / IMPROVED) reachable."""
    cic = analyzer_mod.classify_invariant_change
    assert cic(None, True) == analyzer_mod.CHANGE_KIND_NEW
    assert cic(None, False) == analyzer_mod.CHANGE_KIND_NEW
    assert cic(True, True) == analyzer_mod.CHANGE_KIND_LATERAL
    assert cic(False, False) == analyzer_mod.CHANGE_KIND_LATERAL
    assert cic(True, False) == analyzer_mod.CHANGE_KIND_DEGRADED
    assert cic(False, True) == analyzer_mod.CHANGE_KIND_IMPROVED


# ---------------------------------------------------------------------
# Test 7 -- compute_window_dates basics + rejects zero
# ---------------------------------------------------------------------


def test_compute_window_dates_basic_and_rejects_zero(analyzer_mod):
    """Last-7-Days window is inclusive and ends at today."""
    dates = analyzer_mod.compute_window_dates("2026-05-19", 7)
    assert len(dates) == 7
    assert dates[-1] == "2026-05-19"
    assert dates[0] == "2026-05-13"
    # Sorted ascending.
    assert list(dates) == sorted(dates)
    # Window-days=1 -> single-element tuple == [today].
    dates1 = analyzer_mod.compute_window_dates("2026-05-19", 1)
    assert dates1 == ("2026-05-19",)
    with pytest.raises(ValueError):
        analyzer_mod.compute_window_dates("2026-05-19", 0)
    with pytest.raises(ValueError):
        analyzer_mod.compute_window_dates("2026-05-19", -3)


# ---------------------------------------------------------------------
# Test 8 -- compute_consecutive_fail_streak trailing-only
# ---------------------------------------------------------------------


def test_compute_consecutive_fail_streak_counts_trailing_only(
    analyzer_mod
):
    """The streak count is the trailing-False count only."""
    f = analyzer_mod.compute_consecutive_fail_streak
    assert f((True, True, True)) == 0
    assert f((True, True, False)) == 1
    assert f((False, False, False)) == 3
    assert f((False, True, False, False)) == 2
    # None entries (absent days) terminate the streak.
    assert f((False, None, False)) == 1
    # Empty history.
    assert f(()) == 0


# ---------------------------------------------------------------------
# Test 9 -- build_trend_report clean history all pass
# ---------------------------------------------------------------------


def test_build_trend_report_clean_history_all_pass(analyzer_mod):
    """7 days all-passing -> overall_ok_count=7, streak=0, no changes."""
    base_date = date(2026, 5, 13)
    state = {}
    for i in range(7):
        d = (base_date + timedelta(days=i)).isoformat()
        state[d] = _make_daily_report(analyzer_mod, date_iso=d)
    rep = analyzer_mod.build_trend_report(
        today_iso="2026-05-19", window_days=7, state=state
    )
    assert rep.today_date_iso == "2026-05-19"
    assert rep.window_days == 7
    assert len(rep.window_dates) == 7
    assert rep.overall_ok_count == 7
    assert rep.overall_fail_count == 0
    assert rep.consecutive_fail_streak == 0
    assert rep.changes == ()
    for k in analyzer_mod.ALL_INVARIANT_KEYS:
        assert rep.per_invariant_pass_rate[k] == 1.0


# ---------------------------------------------------------------------
# Test 10 -- build_trend_report detects PASS->FAIL (DEGRADED)
# ---------------------------------------------------------------------


def test_build_trend_report_detects_pass_to_fail_invariant_degraded(
    analyzer_mod
):
    """Yesterday PASS, today FAIL on invariant C -> INVARIANT-DEGRADED."""
    inv_ok_pass = {k: True for k in analyzer_mod.ALL_INVARIANT_KEYS}
    inv_ok_fail_c = dict(inv_ok_pass)
    inv_ok_fail_c["C_v907_pin_stable"] = False
    state = {
        "2026-05-18": _make_daily_report(
            analyzer_mod,
            date_iso="2026-05-18",
            invariant_oks=inv_ok_pass,
        ),
        "2026-05-19": _make_daily_report(
            analyzer_mod,
            date_iso="2026-05-19",
            overall_ok=False,
            invariant_oks=inv_ok_fail_c,
        ),
    }
    rep = analyzer_mod.build_trend_report(
        today_iso="2026-05-19", window_days=2, state=state
    )
    # Exactly one change, on C_v907_pin_stable.
    degraded = [
        c for c in rep.changes
        if c.kind == analyzer_mod.CHANGE_KIND_DEGRADED
    ]
    assert len(degraded) == 1
    assert degraded[0].invariant_key == "C_v907_pin_stable"
    assert degraded[0].previous == "PASS"
    assert degraded[0].current == "FAIL"
    assert rep.per_invariant_pass_rate["C_v907_pin_stable"] == 0.5


# ---------------------------------------------------------------------
# Test 11 -- build_trend_report detects fingerprint drift
# ---------------------------------------------------------------------


def test_build_trend_report_detects_fingerprint_drift(analyzer_mod):
    """Today's boot_fp != yesterday's -> FINGERPRINT-DRIFT change."""
    state = {
        "2026-05-18": _make_daily_report(
            analyzer_mod, date_iso="2026-05-18",
            boot_fp="a" * 64,
        ),
        "2026-05-19": _make_daily_report(
            analyzer_mod, date_iso="2026-05-19",
            boot_fp="d" * 64,  # drifted
        ),
    }
    rep = analyzer_mod.build_trend_report(
        today_iso="2026-05-19", window_days=2, state=state
    )
    drifts = [
        c for c in rep.changes
        if c.kind == analyzer_mod.CHANGE_KIND_FINGERPRINT_DRIFT
    ]
    assert len(drifts) == 1
    assert drifts[0].fingerprint_field == "boot_fp"
    assert drifts[0].previous == "a" * 16
    assert drifts[0].current == "d" * 16


# ---------------------------------------------------------------------
# Test 12 -- build_trend_report counts consecutive-fail streak
# ---------------------------------------------------------------------


def test_build_trend_report_counts_consecutive_fails_streak(
    analyzer_mod
):
    """Three consecutive failing days -> streak = 3."""
    inv_ok_pass = {k: True for k in analyzer_mod.ALL_INVARIANT_KEYS}
    inv_ok_fail = dict(inv_ok_pass)
    inv_ok_fail["A_boot_decisions_stable"] = False
    state = {
        "2026-05-17": _make_daily_report(
            analyzer_mod, date_iso="2026-05-17",
            overall_ok=False, invariant_oks=inv_ok_fail,
        ),
        "2026-05-18": _make_daily_report(
            analyzer_mod, date_iso="2026-05-18",
            overall_ok=False, invariant_oks=inv_ok_fail,
        ),
        "2026-05-19": _make_daily_report(
            analyzer_mod, date_iso="2026-05-19",
            overall_ok=False, invariant_oks=inv_ok_fail,
        ),
    }
    rep = analyzer_mod.build_trend_report(
        today_iso="2026-05-19", window_days=3, state=state
    )
    assert rep.consecutive_fail_streak == 3
    assert rep.overall_fail_count == 3
    assert rep.overall_ok_count == 0


# ---------------------------------------------------------------------
# Test 13 -- build_notify_events: persistent-fail emits page severity
# ---------------------------------------------------------------------


def test_build_notify_events_persistent_fail_emits_page(analyzer_mod):
    """Streak >= 2 -> one severity=page event with persistent-fail
    alert-name."""
    inv_ok_pass = {k: True for k in analyzer_mod.ALL_INVARIANT_KEYS}
    inv_ok_fail = dict(inv_ok_pass)
    inv_ok_fail["A_boot_decisions_stable"] = False
    state = {
        "2026-05-18": _make_daily_report(
            analyzer_mod, date_iso="2026-05-18",
            overall_ok=False, invariant_oks=inv_ok_fail,
        ),
        "2026-05-19": _make_daily_report(
            analyzer_mod, date_iso="2026-05-19",
            overall_ok=False, invariant_oks=inv_ok_fail,
        ),
    }
    rep = analyzer_mod.build_trend_report(
        today_iso="2026-05-19", window_days=2, state=state
    )
    events = analyzer_mod.build_notify_events(
        rep, fired_at_utc="2026-05-19T05:00:00Z"
    )
    page_events = [e for e in events if e["severity"] == "page"]
    assert len(page_events) == 1
    assert (
        page_events[0]["alert_name"]
        == analyzer_mod.ALERT_NAME_PERSISTENT_FAIL
    )
    assert page_events[0]["runbook_url"]  # required for page
    # Schema-v1 / runbook + summary present.
    assert page_events[0]["schema_version"] == "1"
    assert "consecutive" in page_events[0]["summary"]


# ---------------------------------------------------------------------
# Test 14 -- build_notify_events: dedupe via event_id
# ---------------------------------------------------------------------


def test_build_notify_events_dedupe_via_event_id(analyzer_mod):
    """Same input + same fired_at_utc -> same event_ids."""
    inv_ok_pass = {k: True for k in analyzer_mod.ALL_INVARIANT_KEYS}
    inv_ok_fail_c = dict(inv_ok_pass)
    inv_ok_fail_c["C_v907_pin_stable"] = False
    state = {
        "2026-05-18": _make_daily_report(
            analyzer_mod, date_iso="2026-05-18",
            invariant_oks=inv_ok_pass,
        ),
        "2026-05-19": _make_daily_report(
            analyzer_mod, date_iso="2026-05-19",
            overall_ok=False, invariant_oks=inv_ok_fail_c,
        ),
    }
    rep = analyzer_mod.build_trend_report(
        today_iso="2026-05-19", window_days=2, state=state
    )
    fired_at = "2026-05-19T05:00:00Z"
    events1 = analyzer_mod.build_notify_events(rep, fired_at_utc=fired_at)
    events2 = analyzer_mod.build_notify_events(rep, fired_at_utc=fired_at)
    ids1 = sorted(e["event_id"] for e in events1)
    ids2 = sorted(e["event_id"] for e in events2)
    assert ids1 == ids2
    assert len(events1) >= 1


# ---------------------------------------------------------------------
# Test 15 -- build_notify_events: nothing when no changes
# ---------------------------------------------------------------------


def test_build_notify_events_no_changes_emits_nothing(analyzer_mod):
    """Clean history (all-pass, no fp drift) -> empty event list."""
    base_date = date(2026, 5, 13)
    state = {}
    for i in range(7):
        d = (base_date + timedelta(days=i)).isoformat()
        state[d] = _make_daily_report(analyzer_mod, date_iso=d)
    rep = analyzer_mod.build_trend_report(
        today_iso="2026-05-19", window_days=7, state=state
    )
    events = analyzer_mod.build_notify_events(
        rep, fired_at_utc="2026-05-19T05:00:00Z"
    )
    assert events == []


# ---------------------------------------------------------------------
# Test 16 -- render_trend_markdown contains today's date + streak
# ---------------------------------------------------------------------


def test_render_trend_markdown_contains_today_date_and_streak(
    analyzer_mod
):
    """Markdown rendering surfaces the headline metrics."""
    inv_ok_pass = {k: True for k in analyzer_mod.ALL_INVARIANT_KEYS}
    inv_ok_fail = dict(inv_ok_pass)
    inv_ok_fail["B_fsm_trace_hash_stable"] = False
    state = {
        "2026-05-18": _make_daily_report(
            analyzer_mod, date_iso="2026-05-18",
            overall_ok=False, invariant_oks=inv_ok_fail,
        ),
        "2026-05-19": _make_daily_report(
            analyzer_mod, date_iso="2026-05-19",
            overall_ok=False, invariant_oks=inv_ok_fail,
        ),
    }
    rep = analyzer_mod.build_trend_report(
        today_iso="2026-05-19", window_days=2, state=state
    )
    md = analyzer_mod.render_trend_markdown(rep)
    assert "2026-05-19" in md
    assert "Consecutive-fail streak" in md
    assert "B_fsm_trace_hash_stable" in md
    assert "Soak-Probe Daily Trend" in md


# ---------------------------------------------------------------------
# Test 17 -- E2E: ingest real soak-probe-5-day report + build trend
# ---------------------------------------------------------------------


def test_e2e_ingest_real_soak_probe_report_and_build_trend(
    analyzer_mod, soak_probe_mod, tmp_path
):
    """End-to-end: real probe -> JSON report -> ingest -> walk -> trend.

    Drives the full disk-bound path:
      1. Run a real soak-probe-5-day report.
      2. Write it as a raw-shape JSON to a temp path.
      3. Call ingest_soak_report() with today=2026-05-19; assert
         the analyzer-shape file lands in the state-dir.
      4. Call walk_daily_state_dir() and assert today's entry parses.
      5. Call build_trend_report() and assert overall_ok=True.
      6. Call build_notify_events() and assert no events fire
         (clean tree).
    """
    raw_report = soak_probe_mod.run_soak_probe(days=2).as_dict()
    raw_path = tmp_path / "raw-soak-report.json"
    raw_path.write_text(
        json.dumps(raw_report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    state_dir = tmp_path / "soak-probe-daily-trend"
    today_iso = "2026-05-19"

    persisted = analyzer_mod.ingest_soak_report(
        state_dir, raw_path, today_iso
    )
    assert persisted.date_iso == today_iso
    assert persisted.overall_ok is True
    # State dir contains exactly one yyyy-mm-dd.json file.
    files = sorted(p.name for p in state_dir.iterdir())
    assert files == [f"{today_iso}.json"]

    state = analyzer_mod.walk_daily_state_dir(state_dir)
    assert today_iso in state
    assert state[today_iso].overall_ok is True

    rep = analyzer_mod.build_trend_report(
        today_iso=today_iso, window_days=7, state=state
    )
    assert rep.today_report.overall_ok is True
    assert rep.consecutive_fail_streak == 0
    # Yesterday absent -> every invariant is STATUS-NEW; we don't
    # emit notify-events for STATUS-NEW (only DEGRADED / drift /
    # persistent-fail).
    events = analyzer_mod.build_notify_events(
        rep, fired_at_utc="2026-05-19T05:00:00Z"
    )
    assert events == []


# ---------------------------------------------------------------------
# Test 18 -- CLI: --output-json + --output-md + --no-notify smoke
# ---------------------------------------------------------------------


def test_cli_smoke_output_json_and_md(
    analyzer_mod, soak_probe_mod, tmp_path
):
    """End-to-end CLI: ingest + state-dir + outputs + no-notify."""
    raw_report = soak_probe_mod.run_soak_probe(days=2).as_dict()
    raw_path = tmp_path / "raw.json"
    raw_path.write_text(
        json.dumps(raw_report, sort_keys=True), encoding="utf-8"
    )
    state_dir = tmp_path / "state"
    out_json = tmp_path / "trend.json"
    out_md = tmp_path / "trend.md"
    rc = analyzer_mod.cli_main(
        [
            "--state-dir", str(state_dir),
            "--ingest-soak-report", str(raw_path),
            "--today", "2026-05-19",
            "--window-days", "3",
            "--output-json", str(out_json),
            "--output-md", str(out_md),
            "--no-notify",
        ]
    )
    assert rc == 0
    assert out_json.exists()
    assert out_md.exists()
    parsed = json.loads(out_json.read_text(encoding="utf-8"))
    assert parsed["today_date_iso"] == "2026-05-19"
    assert parsed["schema_version"] == "1.0"
    md_text = out_md.read_text(encoding="utf-8")
    assert "Soak-Probe Daily Trend" in md_text
    assert "2026-05-19" in md_text
