# SPDX-License-Identifier: Apache-2.0
"""Tests for scripts/mira-hourly-watchdog.py — Sprint-SRE Tag-15.

Hermetic — no real systemd, no real telemetry file. Drives the
watchdog's public functions against fabricated telemetry tails and
asserts:

  - The quota-cap signature is detected (`classify_record`).
  - Consecutive aborts are counted correctly.
  - Rendered Prometheus textfile output has the expected gauges
    with the expected values.
  - The state-file transition logic only triggers ntfy on healthy
    -> unhealthy edges.

The watchdog script is stdlib-only, but lives outside the python
package tree under ``scripts/``. We import it via importlib.util so
hyphenated filenames stay legal.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Import the watchdog script as a module
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[1]
WATCHDOG_PATH = REPO_ROOT / "scripts" / "mira-hourly-watchdog.py"


def _load_watchdog_module():
    spec = importlib.util.spec_from_file_location(
        "mira_hourly_watchdog", WATCHDOG_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


watchdog = _load_watchdog_module()


# ---------------------------------------------------------------------------
# classify_record — quota-cap detection
# ---------------------------------------------------------------------------


def make_success_record(ts="2026-05-16T05:02:20+00:00") -> dict:
    """Successful synthesis run, real cost."""
    return {
        "timestamp_utc": ts,
        "run_id": ts.replace("Z", "Z"),
        "invoker": "mira-hourly",
        "session_id": "abc-1",
        "duration_ms": 125040,
        "num_turns": 14,
        "is_error": False,
        "stop_reason": "end_turn",
        "total_cost_usd": 0.98,
        "input_tokens": 19,
        "output_tokens": 7189,
    }


def make_quota_cap_record(ts="2026-05-15T16:00:22+00:00") -> dict:
    """The 2026-05-15 18:00/19:00 CEST quota-cap signature."""
    return {
        "timestamp_utc": ts,
        "run_id": ts.replace("Z", "Z"),
        "invoker": "mira-hourly",
        "session_id": "abc-2",
        "duration_ms": 670,
        "num_turns": 1,
        "is_error": True,
        "stop_reason": "stop_sequence",
        "total_cost_usd": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }


def test_classify_success_record():
    assert watchdog.classify_record(make_success_record()) == "success"


def test_classify_quota_cap_record():
    assert watchdog.classify_record(make_quota_cap_record()) == "abort"


def test_classify_mid_run_error_is_abort():
    rec = make_success_record()
    rec["is_error"] = True
    rec["stop_reason"] = "stop_sequence"
    # Real cost, real turns — not a quota cap, but still unhealthy.
    assert watchdog.classify_record(rec) == "abort"


# ---------------------------------------------------------------------------
# consecutive_aborts_from_tail
# ---------------------------------------------------------------------------


def test_consecutive_aborts_zero_when_last_is_success():
    records = [
        make_quota_cap_record("2026-05-15T16:00:22+00:00"),
        make_quota_cap_record("2026-05-15T17:00:22+00:00"),
        make_success_record("2026-05-15T18:04:07+00:00"),
    ]
    assert watchdog.consecutive_aborts_from_tail(records) == 0


def test_consecutive_aborts_counts_streak_from_tail():
    records = [
        make_success_record("2026-05-15T15:05:52+00:00"),
        make_quota_cap_record("2026-05-15T16:00:22+00:00"),
        make_quota_cap_record("2026-05-15T17:00:22+00:00"),
    ]
    assert watchdog.consecutive_aborts_from_tail(records) == 2


def test_consecutive_aborts_handles_empty():
    assert watchdog.consecutive_aborts_from_tail([]) == 0


# ---------------------------------------------------------------------------
# parse_iso_utc_seconds — telemetry ts shape tolerance
# ---------------------------------------------------------------------------


def test_parse_iso_utc_seconds_plus_zero_offset():
    epoch = watchdog.parse_iso_utc_seconds("2026-05-15T16:00:22+00:00")
    assert epoch is not None
    # Sanity: that date in UTC seconds.
    expected = int(time.mktime((2026, 5, 15, 16, 0, 22, 0, 0, 0))) - time.timezone
    assert epoch == expected


def test_parse_iso_utc_seconds_trailing_z():
    epoch = watchdog.parse_iso_utc_seconds("2026-05-16T05:02:20Z")
    assert epoch is not None


def test_parse_iso_utc_seconds_empty_returns_none():
    assert watchdog.parse_iso_utc_seconds("") is None


def test_parse_iso_utc_seconds_garbage_returns_none():
    assert watchdog.parse_iso_utc_seconds("not-a-timestamp") is None


# ---------------------------------------------------------------------------
# render_textfile — Prometheus exposition format
# ---------------------------------------------------------------------------


def test_render_textfile_emits_all_four_gauges():
    text = watchdog.render_textfile(
        last_tick_age_seconds=120,
        last_tick_success=True,
        consecutive_abort_count=0,
        max_age_seconds=4800,
        consecutive_abort_threshold=2,
    )
    assert "mira_hourly_last_tick_age_seconds 120" in text
    assert "mira_hourly_last_tick_success 1" in text
    assert "mira_hourly_consecutive_abort_count 0" in text
    assert "mira_hourly_watchdog_unhealthy 0" in text
    # Every gauge must have a # HELP and # TYPE line.
    for metric in (
        "mira_hourly_last_tick_age_seconds",
        "mira_hourly_last_tick_success",
        "mira_hourly_consecutive_abort_count",
        "mira_hourly_watchdog_unhealthy",
    ):
        assert f"# HELP {metric}" in text
        assert f"# TYPE {metric} gauge" in text


def test_render_textfile_marks_unhealthy_on_stale_tick():
    text = watchdog.render_textfile(
        last_tick_age_seconds=10000,  # > 4800
        last_tick_success=True,
        consecutive_abort_count=0,
        max_age_seconds=4800,
        consecutive_abort_threshold=2,
    )
    assert "mira_hourly_watchdog_unhealthy 1" in text


def test_render_textfile_marks_unhealthy_on_consecutive_aborts():
    text = watchdog.render_textfile(
        last_tick_age_seconds=120,
        last_tick_success=False,
        consecutive_abort_count=2,
        max_age_seconds=4800,
        consecutive_abort_threshold=2,
    )
    assert "mira_hourly_watchdog_unhealthy 1" in text


# ---------------------------------------------------------------------------
# read_telemetry_tail — file shape tolerance
# ---------------------------------------------------------------------------


def test_read_telemetry_tail_skips_blank_and_garbage_lines(tmp_path: Path):
    p = tmp_path / "telemetry.jsonl"
    p.write_text(
        json.dumps(make_success_record("2026-05-16T05:02:20+00:00")) + "\n"
        + "\n"  # blank line
        + "this-is-not-json\n"
        + json.dumps(make_success_record("2026-05-16T06:02:20+00:00")) + "\n",
        encoding="utf-8",
    )
    records = watchdog.read_telemetry_tail(p)
    assert len(records) == 2
    assert records[0]["timestamp_utc"] == "2026-05-16T05:02:20+00:00"
    assert records[1]["timestamp_utc"] == "2026-05-16T06:02:20+00:00"


def test_read_telemetry_tail_raises_for_missing_file(tmp_path: Path):
    with pytest.raises(watchdog.TelemetryError):
        watchdog.read_telemetry_tail(tmp_path / "does-not-exist.jsonl")


# ---------------------------------------------------------------------------
# atomic_write — output safety
# ---------------------------------------------------------------------------


def test_atomic_write_creates_parent_and_replaces_existing(tmp_path: Path):
    target = tmp_path / "sub" / "out.prom"
    watchdog.atomic_write(target, "v1\n")
    assert target.read_text() == "v1\n"
    watchdog.atomic_write(target, "v2\n")
    assert target.read_text() == "v2\n"


# ---------------------------------------------------------------------------
# State machine — healthy <-> unhealthy edge detection
# ---------------------------------------------------------------------------


def test_load_state_returns_default_for_missing_file(tmp_path: Path):
    state = watchdog.load_state(tmp_path / "state.json")
    assert state == {"unhealthy": False, "last_alert_ts_utc": None}


def test_save_and_load_state_roundtrip(tmp_path: Path):
    path = tmp_path / "state.json"
    watchdog.save_state(path, {"unhealthy": True, "x": 1})
    out = watchdog.load_state(path)
    assert out == {"unhealthy": True, "x": 1}


# ---------------------------------------------------------------------------
# main() end-to-end with --dry-run
# ---------------------------------------------------------------------------


def test_main_dry_run_reports_healthy(tmp_path: Path, capsys):
    p = tmp_path / "telemetry.jsonl"
    now_ts = "2026-05-16T08:00:00+00:00"
    p.write_text(json.dumps(make_success_record(now_ts)) + "\n", encoding="utf-8")
    rc = watchdog.main([
        "--telemetry-path", str(p),
        "--textfile-output", str(tmp_path / "out.prom"),
        "--state-file", str(tmp_path / "state.json"),
        "--now", str(int(time.mktime((2026, 5, 16, 8, 0, 30, 0, 0, 0))) - time.timezone),
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    payload_lines = out.splitlines()
    report = json.loads(payload_lines[0])
    assert report["last_tick_success"] is True
    assert report["consecutive_abort_count"] == 0
    assert report["unhealthy"] is False


def test_main_dry_run_reports_unhealthy_on_quota_caps(tmp_path: Path, capsys):
    p = tmp_path / "telemetry.jsonl"
    p.write_text(
        json.dumps(make_quota_cap_record("2026-05-15T16:00:22+00:00")) + "\n"
        + json.dumps(make_quota_cap_record("2026-05-15T17:00:22+00:00")) + "\n",
        encoding="utf-8",
    )
    rc = watchdog.main([
        "--telemetry-path", str(p),
        "--textfile-output", str(tmp_path / "out.prom"),
        "--state-file", str(tmp_path / "state.json"),
        "--now", str(int(time.mktime((2026, 5, 15, 17, 30, 0, 0, 0, 0))) - time.timezone),
        "--dry-run",
    ])
    assert rc == 0
    report = json.loads(capsys.readouterr().out.splitlines()[0])
    assert report["last_tick_success"] is False
    assert report["consecutive_abort_count"] == 2
    assert report["unhealthy"] is True
    assert report["transitioning_to_unhealthy"] is True


def test_main_writes_textfile_and_state(tmp_path: Path):
    p = tmp_path / "telemetry.jsonl"
    p.write_text(
        json.dumps(make_success_record("2026-05-16T08:00:00+00:00")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.prom"
    state = tmp_path / "state.json"
    rc = watchdog.main([
        "--telemetry-path", str(p),
        "--textfile-output", str(out),
        "--state-file", str(state),
        "--now", str(int(time.mktime((2026, 5, 16, 8, 5, 0, 0, 0, 0))) - time.timezone),
    ])
    assert rc == 0
    text = out.read_text()
    assert "mira_hourly_last_tick_success 1" in text
    assert state.is_file()
    state_obj = json.loads(state.read_text())
    assert state_obj["unhealthy"] is False


def test_main_missing_telemetry_returns_1(tmp_path: Path):
    rc = watchdog.main([
        "--telemetry-path", str(tmp_path / "does-not-exist.jsonl"),
        "--textfile-output", str(tmp_path / "out.prom"),
        "--state-file", str(tmp_path / "state.json"),
        "--dry-run",
    ])
    assert rc == 1
