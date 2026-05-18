#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/observability/pre-cutover-daily-trend-analyzer.py``.

These tests are stdlib-only (pytest as test runner). No network,
no podman, no live VM. The analyzer's I/O surface is exercised
via ``tmp_path`` fixtures.

Test coverage (>= 12 tests, Auftrag-Tag-44 minimum):

  1.  test_parse_envelope_persisted_shape_roundtrip
  2.  test_parse_envelope_live_demo_shape_extracts_per_welle
  3.  test_classify_change_status_new_when_no_previous
  4.  test_classify_change_status_degraded_caution_to_block
  5.  test_classify_change_status_improved_block_to_green
  6.  test_classify_change_status_lateral_same_verdict
  7.  test_detect_changes_only_returns_non_lateral
  8.  test_window_dates_returns_iso_oldest_to_newest
  9.  test_build_window_histories_fills_missing_with_dash
  10. test_stability_pct_full_match_returns_hundred
  11. test_stability_pct_one_flip_returns_six_of_seven
  12. test_aggregate_stability_counts_handles_unknown_values
  13. test_build_trend_report_today_only_has_status_new_changes
  14. test_build_trend_report_with_yesterday_detects_degradation
  15. test_render_markdown_contains_today_block_and_trend_table
  16. test_render_weekly_bilanz_empty_input_safe
  17. test_render_weekly_bilanz_tallies_degraded_events
  18. test_build_notify_events_skips_lateral
  19. test_walk_daily_state_dir_ignores_malformed_files
  20. test_persist_daily_envelope_writes_sorted_keys
  21. test_cli_daily_mode_writes_outputs_and_notify
  22. test_cli_weekly_bilanz_mode_renders_summary

Anchors:
  * Reza Tag-44 daily-probe-driver.
  * Reza Tag-43 PR #277 Pre-Cutover-Live-Demo (envelope source shape).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest


# ---------------------------------------------------------------------
# Loader: import the analyzer module from its hyphenated path.
# ---------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_ANALYZER_PATH = (
    _REPO_ROOT
    / "scripts"
    / "observability"
    / "pre-cutover-daily-trend-analyzer.py"
)


@pytest.fixture(scope="module")
def analyzer():
    mod_name = "pre_cutover_daily_trend_analyzer"
    spec = importlib.util.spec_from_file_location(mod_name, _ANALYZER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return mod


# ---------------------------------------------------------------------
# Synthetic envelope helpers.
# ---------------------------------------------------------------------


def make_persisted_envelope(
    date_iso: str,
    aggregate: str = "BLOCK",
    per_welle: dict[int, str] | None = None,
    run_id: str = "test-run",
) -> dict:
    per_welle = per_welle or {
        1: "CAUTION",
        2: "CAUTION",
        3: "CAUTION",
        4: "CAUTION",
        5: "CAUTION",
        6: "GREEN",
        7: "BLOCK",
    }
    return {
        "date_iso": date_iso,
        "run_id": run_id,
        "aggregate": aggregate,
        "per_welle": {str(k): v for k, v in per_welle.items()},
        "captured_at_utc": f"{date_iso}T06:00:00Z",
        "expected_aggregate": "BLOCK",
        "aggregate_match": True,
    }


def make_live_demo_envelope(
    date_iso: str,
    aggregate: str = "BLOCK",
    per_welle: dict[int, str] | None = None,
) -> dict:
    per_welle = per_welle or {
        1: "CAUTION",
        2: "CAUTION",
        3: "CAUTION",
        4: "CAUTION",
        5: "CAUTION",
        6: "GREEN",
        7: "BLOCK",
    }
    return {
        "schema_version": "1.0",
        "run_id": "demo-run-id",
        "started_at_utc": f"{date_iso}T06:00:00Z",
        "finished_at_utc": f"{date_iso}T06:01:00Z",
        "repo_root": "/repo",
        "mode": "sandbox-stub",
        "expected_aggregate": "BLOCK",
        "observed_aggregate": aggregate,
        "aggregate_match": True,
        "summary_counts": {
            "GREEN": sum(1 for v in per_welle.values() if v == "GREEN"),
            "CAUTION": sum(1 for v in per_welle.values() if v == "CAUTION"),
            "BLOCK": sum(1 for v in per_welle.values() if v == "BLOCK"),
            "NOT-EXEC": sum(1 for v in per_welle.values() if v == "NOT-EXEC"),
        },
        "probes": [
            {
                "welle": w,
                "component": f"comp-{w}",
                "verdict": v,
            }
            for w, v in per_welle.items()
        ],
        "gh_trigger": {"attempted": False},
    }


# ---------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------


def test_parse_envelope_persisted_shape_roundtrip(analyzer):
    blob = make_persisted_envelope("2026-05-18", aggregate="BLOCK")
    env = analyzer.parse_envelope(blob)
    assert env.date_iso == "2026-05-18"
    assert env.aggregate == "BLOCK"
    assert env.per_welle[7] == "BLOCK"
    assert env.per_welle[6] == "GREEN"
    # Round-trip back to envelope dict, then re-parse.
    redumped = env.to_envelope()
    re_env = analyzer.parse_envelope(redumped)
    assert re_env.per_welle == env.per_welle


def test_parse_envelope_live_demo_shape_extracts_per_welle(analyzer):
    blob = make_live_demo_envelope("2026-05-19", aggregate="CAUTION")
    env = analyzer.parse_envelope(blob, fallback_date_iso="2026-05-19")
    assert env.date_iso == "2026-05-19"
    # Live-demo uses observed_aggregate; analyzer maps it to aggregate.
    assert env.aggregate == "CAUTION"
    assert set(env.per_welle.keys()) == {1, 2, 3, 4, 5, 6, 7}


def test_classify_change_status_new_when_no_previous(analyzer):
    kind = analyzer.classify_change(None, "GREEN", "welle-1")
    assert kind == analyzer.CHANGE_KIND_NEW


def test_classify_change_status_degraded_caution_to_block(analyzer):
    kind = analyzer.classify_change("CAUTION", "BLOCK", "welle-3")
    assert kind == analyzer.CHANGE_KIND_DEGRADED


def test_classify_change_status_improved_block_to_green(analyzer):
    kind = analyzer.classify_change("BLOCK", "GREEN", "welle-7")
    assert kind == analyzer.CHANGE_KIND_IMPROVED


def test_classify_change_status_lateral_same_verdict(analyzer):
    kind = analyzer.classify_change("CAUTION", "CAUTION", "welle-2")
    assert kind == analyzer.CHANGE_KIND_LATERAL


def test_detect_changes_only_returns_non_lateral(analyzer):
    today = analyzer.parse_envelope(
        make_persisted_envelope(
            "2026-05-19",
            aggregate="BLOCK",
            per_welle={
                1: "CAUTION",
                2: "CAUTION",
                3: "BLOCK",  # changed from CAUTION
                4: "CAUTION",
                5: "CAUTION",
                6: "GREEN",
                7: "BLOCK",
            },
        )
    )
    yesterday = analyzer.parse_envelope(
        make_persisted_envelope("2026-05-18", aggregate="BLOCK")
    )
    changes = analyzer.detect_changes(today, yesterday)
    welle_scopes = [c.scope for c in changes]
    # Only welle-3 flipped CAUTION->BLOCK; rest were lateral.
    assert "welle-3" in welle_scopes
    # No aggregate change (both BLOCK).
    assert "aggregate" not in welle_scopes
    # Verify the welle-3 entry classifies as DEGRADED.
    welle_3 = next(c for c in changes if c.scope == "welle-3")
    assert welle_3.kind == analyzer.CHANGE_KIND_DEGRADED
    assert welle_3.previous == "CAUTION"
    assert welle_3.current == "BLOCK"


def test_window_dates_returns_iso_oldest_to_newest(analyzer):
    out = analyzer.window_dates("2026-05-18", 7)
    assert out[-1] == "2026-05-18"
    assert out[0] == "2026-05-12"
    assert len(out) == 7
    # Strictly increasing.
    parsed = [date.fromisoformat(d) for d in out]
    assert all(parsed[i] < parsed[i + 1] for i in range(len(parsed) - 1))


def test_build_window_histories_fills_missing_with_dash(analyzer):
    today = analyzer.parse_envelope(
        make_persisted_envelope("2026-05-18", aggregate="BLOCK")
    )
    envelopes = {"2026-05-18": today}
    wdates = analyzer.window_dates("2026-05-18", 3)
    aggregate_hist, per_welle_hist = analyzer.build_window_histories(
        envelopes, wdates
    )
    # Day 0 and 1 missing, day 2 (today) populated.
    assert aggregate_hist[0] == "-"
    assert aggregate_hist[1] == "-"
    assert aggregate_hist[2] == "BLOCK"
    assert per_welle_hist[1][0] == "-"
    assert per_welle_hist[1][2] == "CAUTION"


def test_stability_pct_full_match_returns_hundred(analyzer):
    pct = analyzer.stability_pct(("GREEN",) * 7)
    assert pct == 100.0


def test_stability_pct_one_flip_returns_six_of_seven(analyzer):
    # latest=BLOCK; window has 6 BLOCK + 1 CAUTION.
    pct = analyzer.stability_pct(("CAUTION",) + ("BLOCK",) * 6)
    # 6 of 7 match the latest (BLOCK).
    assert pct == pytest.approx(85.71, rel=0.01)


def test_aggregate_stability_counts_handles_unknown_values(analyzer):
    counts = analyzer.aggregate_stability_counts(
        ("READY", "READY", "BLOCK", "-", "-")
    )
    assert counts["READY"] == 2
    assert counts["BLOCK"] == 1
    assert counts["MISSING"] == 2


def test_build_trend_report_today_only_has_status_new_changes(analyzer):
    today = analyzer.parse_envelope(
        make_persisted_envelope("2026-05-18", aggregate="BLOCK")
    )
    envelopes = {today.date_iso: today}
    report = analyzer.build_trend_report(today, envelopes, window=7)
    assert report.today_date_iso == "2026-05-18"
    assert report.yesterday_envelope is None
    # All seven Welles emit STATUS-NEW plus the aggregate emits NEW.
    new_kinds = {c.kind for c in report.changes}
    assert new_kinds == {analyzer.CHANGE_KIND_NEW}
    # 7 welles + 1 aggregate = 8 change events.
    assert len(report.changes) == 8


def test_build_trend_report_with_yesterday_detects_degradation(analyzer):
    yesterday = analyzer.parse_envelope(
        make_persisted_envelope(
            "2026-05-17",
            aggregate="CAUTION",
            per_welle={
                1: "GREEN",
                2: "GREEN",
                3: "GREEN",
                4: "GREEN",
                5: "GREEN",
                6: "GREEN",
                7: "CAUTION",
            },
        )
    )
    today = analyzer.parse_envelope(
        make_persisted_envelope(
            "2026-05-18",
            aggregate="BLOCK",
            per_welle={
                1: "GREEN",
                2: "GREEN",
                3: "GREEN",
                4: "GREEN",
                5: "GREEN",
                6: "GREEN",
                7: "BLOCK",  # CAUTION -> BLOCK
            },
        )
    )
    envelopes = {
        yesterday.date_iso: yesterday,
        today.date_iso: today,
    }
    report = analyzer.build_trend_report(today, envelopes, window=7)
    assert report.yesterday_envelope is not None
    # welle-7 degraded CAUTION->BLOCK; aggregate degraded CAUTION->BLOCK.
    degraded = [
        c for c in report.changes if c.kind == analyzer.CHANGE_KIND_DEGRADED
    ]
    welle_scopes = {c.scope for c in degraded}
    assert "welle-7" in welle_scopes
    assert "aggregate" in welle_scopes


def test_render_markdown_contains_today_block_and_trend_table(analyzer):
    today = analyzer.parse_envelope(
        make_persisted_envelope("2026-05-18", aggregate="BLOCK")
    )
    envelopes = {today.date_iso: today}
    report = analyzer.build_trend_report(today, envelopes, window=3)
    md = analyzer.render_markdown(report)
    assert "Phase-3c Pre-Cutover Daily-Probe" in md
    assert "2026-05-18" in md
    assert "Today's per-Welle verdicts" in md
    assert "Trend (last 3 days)" in md
    assert "Stability" in md
    assert "ADR-0065" in md


def test_render_weekly_bilanz_empty_input_safe(analyzer):
    out = analyzer.render_weekly_bilanz([])
    assert "Weekly Bilanz" in out
    assert "No daily reports available" in out


def test_render_weekly_bilanz_tallies_degraded_events(analyzer):
    yesterday = analyzer.parse_envelope(
        make_persisted_envelope("2026-05-17", aggregate="CAUTION")
    )
    today = analyzer.parse_envelope(
        make_persisted_envelope(
            "2026-05-18",
            aggregate="BLOCK",
            per_welle={
                1: "BLOCK",
                2: "CAUTION",
                3: "CAUTION",
                4: "CAUTION",
                5: "CAUTION",
                6: "GREEN",
                7: "BLOCK",
            },
        )
    )
    envelopes = {
        yesterday.date_iso: yesterday,
        today.date_iso: today,
    }
    reports = [
        analyzer.build_trend_report(yesterday, envelopes, window=7),
        analyzer.build_trend_report(today, envelopes, window=7),
    ]
    md = analyzer.render_weekly_bilanz(reports)
    assert "Phase-3c Pre-Cutover Weekly Bilanz" in md
    assert "Days covered" in md
    assert "STATUS-DEGRADED" in md


def test_build_notify_events_skips_lateral(analyzer):
    today = analyzer.parse_envelope(
        make_persisted_envelope(
            "2026-05-18",
            aggregate="BLOCK",
            per_welle={
                1: "BLOCK",  # degraded vs yesterday
                2: "CAUTION",
                3: "CAUTION",
                4: "CAUTION",
                5: "CAUTION",
                6: "GREEN",
                7: "BLOCK",
            },
        )
    )
    yesterday = analyzer.parse_envelope(
        make_persisted_envelope("2026-05-17", aggregate="BLOCK")
    )
    envelopes = {
        yesterday.date_iso: yesterday,
        today.date_iso: today,
    }
    report = analyzer.build_trend_report(today, envelopes, window=7)
    events = analyzer.build_notify_events(report)
    assert all(
        ev["kind"] != analyzer.CHANGE_KIND_LATERAL for ev in events
    )
    # welle-1 changed CAUTION->BLOCK; should appear.
    welle_scopes = {ev["scope"] for ev in events}
    assert "welle-1" in welle_scopes


def test_walk_daily_state_dir_ignores_malformed_files(analyzer, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    # Valid envelope.
    good = make_persisted_envelope("2026-05-18")
    (state / "2026-05-18.json").write_text(
        json.dumps(good), encoding="utf-8"
    )
    # Malformed JSON.
    (state / "2026-05-17.json").write_text(
        "{this-is-not-json", encoding="utf-8"
    )
    # Wrong filename pattern -- skipped.
    (state / "not-a-date.json").write_text(
        json.dumps(good), encoding="utf-8"
    )
    # Non-JSON file.
    (state / "README.md").write_text("# notes", encoding="utf-8")

    loaded = analyzer.walk_daily_state_dir(state)
    assert "2026-05-18" in loaded
    assert "2026-05-17" not in loaded
    assert "not-a-date" not in loaded
    assert len(loaded) == 1


def test_persist_daily_envelope_writes_sorted_keys(analyzer, tmp_path):
    env = analyzer.parse_envelope(make_persisted_envelope("2026-05-18"))
    out = analyzer.persist_daily_envelope(tmp_path, env)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    blob = json.loads(content)
    # Round-trip equivalence.
    assert blob["date_iso"] == "2026-05-18"
    # Sorted keys preserve canonical ordering of nested dicts.
    keys = list(blob.keys())
    assert keys == sorted(keys)


def test_cli_daily_mode_writes_outputs_and_notify(
    analyzer, tmp_path, monkeypatch
):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    notify_path = tmp_path / "notify.jsonl"
    out_json = tmp_path / "trend.json"
    out_md = tmp_path / "trend.md"
    ingest_path = tmp_path / "live-demo.json"

    # Seed yesterday's state so today's ingest produces a non-trivial
    # change-set.
    yest = make_persisted_envelope(
        "2026-05-17",
        aggregate="CAUTION",
        per_welle={
            1: "GREEN",
            2: "GREEN",
            3: "GREEN",
            4: "GREEN",
            5: "GREEN",
            6: "GREEN",
            7: "CAUTION",
        },
    )
    (state_dir / "2026-05-17.json").write_text(
        json.dumps(yest), encoding="utf-8"
    )

    # Live-demo envelope to ingest.
    live = make_live_demo_envelope(
        "2026-05-18",
        aggregate="BLOCK",
        per_welle={
            1: "GREEN",
            2: "GREEN",
            3: "GREEN",
            4: "GREEN",
            5: "GREEN",
            6: "GREEN",
            7: "BLOCK",  # degradation
        },
    )
    ingest_path.write_text(json.dumps(live), encoding="utf-8")

    rc = analyzer.cli_main(
        [
            "--state-dir",
            str(state_dir),
            "--ingest-envelope",
            str(ingest_path),
            "--today",
            "2026-05-18",
            "--window-days",
            "7",
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
            "--notify-path",
            str(notify_path),
        ]
    )
    assert rc == 0
    assert out_json.exists()
    assert out_md.exists()
    # State dir got today's snapshot.
    assert (state_dir / "2026-05-18.json").exists()
    # Notify feed has at least the welle-7 degradation + aggregate.
    assert notify_path.exists()
    events = [
        json.loads(line)
        for line in notify_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    welle_scopes = {ev["scope"] for ev in events}
    assert "welle-7" in welle_scopes
    assert "aggregate" in welle_scopes


def test_cli_weekly_bilanz_mode_renders_summary(
    analyzer, tmp_path
):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    # Seed multiple days.
    for day_offset, iso in enumerate(
        ["2026-05-12", "2026-05-13", "2026-05-14"]
    ):
        env = make_persisted_envelope(iso, aggregate="BLOCK")
        (state_dir / f"{iso}.json").write_text(
            json.dumps(env), encoding="utf-8"
        )

    out_md = tmp_path / "bilanz.md"
    out_json = tmp_path / "bilanz.json"
    rc = analyzer.cli_main(
        [
            "--state-dir",
            str(state_dir),
            "--today",
            "2026-05-14",
            "--window-days",
            "3",
            "--mode",
            "weekly-bilanz",
            "--output-md",
            str(out_md),
            "--output-json",
            str(out_json),
            "--no-notify",
        ]
    )
    assert rc == 0
    assert out_md.exists()
    assert out_json.exists()
    md_text = out_md.read_text(encoding="utf-8")
    assert "Weekly Bilanz" in md_text
    assert "2026-05-12" in md_text
    assert "2026-05-14" in md_text
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["mode"] == "weekly-bilanz"
    assert len(payload["reports"]) == 3


def test_cli_missing_ingest_envelope_returns_two(analyzer, tmp_path):
    rc = analyzer.cli_main(
        [
            "--state-dir",
            str(tmp_path / "state"),
            "--ingest-envelope",
            str(tmp_path / "does-not-exist.json"),
            "--today",
            "2026-05-18",
            "--no-notify",
        ]
    )
    assert rc == 2
