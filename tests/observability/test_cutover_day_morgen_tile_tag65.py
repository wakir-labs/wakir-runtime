# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-65 Cutover-Day-Morgen Marathon-Dashboard-Kachel tests.

Covers (>= 12 tests; ships 16):

  T01  Dashboard JSON is loadable and has the expected top-level
       schema fields (title, uid, tags, schemaVersion, refresh).
  T02  Dashboard carries the six expected panel ids 1..6 in order.
  T03  Panel-1 (verdict-stat) targets the Tag-64 recording-rule
       wakir_cutover_day_morgen_verdict_class and has the trinary
       value-mappings 0/1/2 -> READY/CAUTION/BLOCK.
  T04  Panel-2 (window-days-remaining) targets
       wakir_cutover_day_morgen_window_days_remaining with unit 'd',
       min -1, max 28, and a value-mapping for -1 -> out-of-window.
  T05  Panel-3 (last-update timestamp) uses the
       'time() - wakir_cutover_day_morgen_verdict_emitted_at_seconds'
       expression with seconds-unit and tiered thresholds.
  T06  Panel-4 (per-substrate ladder) targets
       wakir_cutover_day_morgen_substrate_class with substrate as
       legend-template.
  T07  Helper module importable and exposes the four series-name
       constants plus the VERDICT_TO_CLASS / STATUS_TO_CLASS maps.
  T08  verdict_to_class returns 0/1/2 for the three canonical
       verdict strings and SENTINEL_UNKNOWN for unknown/None.
  T09  substrate_status_to_class returns 0/1/2 for green/yellow/red
       and SENTINEL_UNKNOWN for unknown/None.
  T10  emitted_at_to_unix parses a Tag-64-shaped ISO timestamp
       to the correct Unix-seconds and SENTINEL_UNKNOWN on garbage.
  T11  window_days_remaining returns -1 after the window end,
       a positive integer inside the window, and clamps to
       WINDOW_DAYS_TOTAL before window-start.
  T12  in_cutover_window returns 1 for {24,25,26,27} and 0 for
       outside / None.
  T13  render() output contains all 5 series families and the
       canonical substrate-ordering engine -> pyramide -> e2e.
  T14  render() carries # HELP and # TYPE lines for every series
       (Prometheus textfile-collector convention).
  T15  CLI writes the textfile-block to --output and exits 0 on
       a real Tag-64-shaped envelope fixture.
  T16  Cross-repo mirror at wirelang/specs/protocol-mirror-seed/
       dashboards/cutover-day-morgen-verdict-tile.json is
       byte-identical to the runtime-side dashboard.

Anchor: Tag-65 Marathon-Continuous-Mode Cutover-Day-Morgen Verdict
        Marathon-Dashboard-Kachel.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "tooling/ci/render_cutover_day_morgen_tile.py"
DASHBOARD_PATH = REPO_ROOT / "dashboards/cutover-day-morgen-verdict-tile.json"
MIRROR_PATH = (
    REPO_ROOT
    / "wirelang/specs/protocol-mirror-seed/dashboards/"
    "cutover-day-morgen-verdict-tile.json"
)


# ---------------------------------------------------------------------------
# Loader + fixtures
# ---------------------------------------------------------------------------


def _load_helper():
    mod_name = "render_cutover_day_morgen_tile"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, str(HELPER_PATH))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def helper():
    return _load_helper()


@pytest.fixture(scope="module")
def dashboard() -> dict:
    return json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))


def _make_envelope(
    verdict: str = "CUTOVER-DAY-MORGEN-READY",
    emitted_at_utc: str = "2026-06-15T06:00:00+00:00",
    iso_week: int | None = 24,
    step_results: dict | None = None,
) -> dict:
    if step_results is None:
        step_results = {
            "engine_composite": "green",
            "pyramide_composite": "green",
            "e2e_smoke": "green",
        }
    return {
        "schema_version": 1,
        "workflow": "cutover-day-morgen-auto-scheduler",
        "tag": "tag-64",
        "emitted_at_utc": emitted_at_utc,
        "verdict": verdict,
        "step_results": step_results,
        "window": {
            "iso_week": iso_week,
            "in_cutover_window": iso_week in (24, 25, 26, 27)
            if isinstance(iso_week, int)
            else False,
            "cutover_iso_weeks": [24, 25, 26, 27],
        },
    }


# ---------------------------------------------------------------------------
# Dashboard JSON tests
# ---------------------------------------------------------------------------


def test_dashboard_schema_shape(dashboard):
    """T01 -- top-level schema fields are present and well-typed."""
    assert dashboard["title"] == "Wakir - Cutover-Day-Morgen Verdict Tile"
    assert dashboard["uid"] == "wakir-cutover-day-morgen-verdict-tile"
    assert dashboard["schemaVersion"] == 38
    assert dashboard["refresh"] == "1m"
    assert "tag-65" in dashboard["tags"]
    assert "cutover-day-morgen" in dashboard["tags"]
    assert "trinary-verdict" in dashboard["tags"]


def test_dashboard_panel_ids_in_order(dashboard):
    """T02 -- exactly six panels with ids 1..6 in canonical order."""
    panels = dashboard["panels"]
    assert len(panels) == 6
    assert [p["id"] for p in panels] == [1, 2, 3, 4, 5, 6]


def test_panel1_verdict_stat_targets_recording_rule(dashboard):
    """T03 -- panel-1 reads the trinary recording-rule with mappings."""
    panel = dashboard["panels"][0]
    assert panel["type"] == "stat"
    assert (
        panel["targets"][0]["expr"]
        == "wakir_cutover_day_morgen_verdict_class"
    )
    mappings = panel["fieldConfig"]["defaults"]["mappings"]
    options = mappings[0]["options"]
    assert options["0"]["text"] == "READY"
    assert options["1"]["text"] == "CAUTION"
    assert options["2"]["text"] == "BLOCK"
    # Colour-band: green/yellow/red.
    assert options["0"]["color"] == "green"
    assert options["1"]["color"] == "yellow"
    assert options["2"]["color"] == "red"


def test_panel2_window_days_remaining(dashboard):
    """T04 -- panel-2 gauge has the correct unit, range, and mapping."""
    panel = dashboard["panels"][1]
    assert panel["type"] == "gauge"
    assert (
        panel["targets"][0]["expr"]
        == "wakir_cutover_day_morgen_window_days_remaining"
    )
    defaults = panel["fieldConfig"]["defaults"]
    assert defaults["unit"] == "d"
    assert defaults["min"] == -1
    assert defaults["max"] == 28
    mappings = defaults["mappings"][0]["options"]
    assert mappings["-1"]["text"] == "out-of-window"


def test_panel3_last_update_timestamp(dashboard):
    """T05 -- panel-3 uses the time()-minus-emitted-at expression."""
    panel = dashboard["panels"][2]
    assert panel["type"] == "stat"
    expr = panel["targets"][0]["expr"]
    assert "wakir_cutover_day_morgen_verdict_emitted_at_seconds" in expr
    assert "time()" in expr
    defaults = panel["fieldConfig"]["defaults"]
    assert defaults["unit"] == "s"
    steps = defaults["thresholds"]["steps"]
    step_values = [s.get("value") for s in steps]
    # Tiered thresholds: null -> green, 600 -> yellow, 3600 -> red.
    assert 600 in step_values
    assert 3600 in step_values


def test_panel4_per_substrate_ladder(dashboard):
    """T06 -- panel-4 targets the per-substrate gauge with label."""
    panel = dashboard["panels"][3]
    assert panel["type"] == "stat"
    assert (
        panel["targets"][0]["expr"]
        == "wakir_cutover_day_morgen_substrate_class"
    )
    assert panel["targets"][0]["legendFormat"] == "{{substrate}}"


# ---------------------------------------------------------------------------
# Helper-module tests
# ---------------------------------------------------------------------------


def test_helper_constants_present(helper):
    """T07 -- series-name + class-map constants are exposed."""
    assert (
        helper.SERIES_VERDICT_CLASS
        == "wakir_cutover_day_morgen_verdict_class"
    )
    assert (
        helper.SERIES_EMITTED_AT_SECONDS
        == "wakir_cutover_day_morgen_verdict_emitted_at_seconds"
    )
    assert (
        helper.SERIES_WINDOW_DAYS_REMAINING
        == "wakir_cutover_day_morgen_window_days_remaining"
    )
    assert (
        helper.SERIES_SUBSTRATE_CLASS
        == "wakir_cutover_day_morgen_substrate_class"
    )
    assert helper.VERDICT_TO_CLASS == {
        "CUTOVER-DAY-MORGEN-READY": 0,
        "CUTOVER-DAY-MORGEN-CAUTION": 1,
        "CUTOVER-DAY-MORGEN-BLOCK": 2,
    }
    assert helper.STATUS_TO_CLASS == {
        "green": 0,
        "yellow": 1,
        "red": 2,
    }
    assert helper.SENTINEL_UNKNOWN == -1


def test_verdict_to_class(helper):
    """T08 -- canonical verdict strings map to 0/1/2; junk -> -1."""
    assert helper.verdict_to_class("CUTOVER-DAY-MORGEN-READY") == 0
    assert helper.verdict_to_class("CUTOVER-DAY-MORGEN-CAUTION") == 1
    assert helper.verdict_to_class("CUTOVER-DAY-MORGEN-BLOCK") == 2
    assert helper.verdict_to_class(None) == -1
    assert helper.verdict_to_class("READY") == -1
    assert helper.verdict_to_class(42) == -1


def test_substrate_status_to_class(helper):
    """T09 -- green/yellow/red map to 0/1/2; junk -> -1."""
    assert helper.substrate_status_to_class("green") == 0
    assert helper.substrate_status_to_class("yellow") == 1
    assert helper.substrate_status_to_class("red") == 2
    assert helper.substrate_status_to_class(None) == -1
    assert helper.substrate_status_to_class("GREEN") == -1


def test_emitted_at_to_unix(helper):
    """T10 -- parses ISO timestamp; SENTINEL on parse failure."""
    # 2026-06-15T06:00:00+00:00 is 1781503200 Unix-seconds.
    assert (
        helper.emitted_at_to_unix("2026-06-15T06:00:00+00:00")
        == 1781503200
    )
    # Naive (no tzinfo) defaults to UTC.
    assert (
        helper.emitted_at_to_unix("2026-06-15T06:00:00")
        == 1781503200
    )
    assert helper.emitted_at_to_unix(None) == -1
    assert helper.emitted_at_to_unix("not-a-timestamp") == -1


def test_window_days_remaining(helper):
    """T11 -- inside / before / after the KW-24..27 window."""
    # Window end: 2026-07-03 (Fri KW-27 2026).
    # Inside: 2026-06-15 -> 18 days remaining.
    assert helper.window_days_remaining(date(2026, 6, 15)) == 18
    # Day-of window end: 0 days remaining (still in-window).
    assert helper.window_days_remaining(date(2026, 7, 3)) == 0
    # After: 2026-07-10 -> -1.
    assert helper.window_days_remaining(date(2026, 7, 10)) == -1
    # Before window start: clamp at WINDOW_DAYS_TOTAL (28).
    assert (
        helper.window_days_remaining(date(2026, 5, 1))
        == helper.WINDOW_DAYS_TOTAL
    )


def test_in_cutover_window(helper):
    """T12 -- KW-24..27 -> 1; else 0."""
    for week in (24, 25, 26, 27):
        assert helper.in_cutover_window(week) == 1
    for week in (1, 23, 28, 53):
        assert helper.in_cutover_window(week) == 0
    assert helper.in_cutover_window(None) == 0
    assert helper.in_cutover_window("24") == 0  # type-strict


def test_render_contains_all_series_and_ordering(helper):
    """T13 -- render output contains every series family in order."""
    env = _make_envelope()
    block = helper.render(env, today=date(2026, 6, 15))
    # All five series-name constants present.
    assert helper.SERIES_VERDICT_CLASS in block
    assert helper.SERIES_EMITTED_AT_SECONDS in block
    assert helper.SERIES_WINDOW_DAYS_REMAINING in block
    assert helper.SERIES_IN_CUTOVER_WINDOW in block
    assert helper.SERIES_SUBSTRATE_CLASS in block
    # Substrate ordering: engine -> pyramide -> e2e (substring order).
    engine_idx = block.index('substrate="engine_composite"')
    pyramide_idx = block.index('substrate="pyramide_composite"')
    e2e_idx = block.index('substrate="e2e_smoke"')
    assert engine_idx < pyramide_idx < e2e_idx
    # Verdict-class line carries the integer 0 (READY fixture).
    assert f"{helper.SERIES_VERDICT_CLASS} 0\n" in block


def test_render_has_help_and_type_lines(helper):
    """T14 -- every series carries a # HELP and a # TYPE line."""
    env = _make_envelope()
    block = helper.render(env, today=date(2026, 6, 15))
    for series in (
        helper.SERIES_VERDICT_CLASS,
        helper.SERIES_EMITTED_AT_SECONDS,
        helper.SERIES_WINDOW_DAYS_REMAINING,
        helper.SERIES_IN_CUTOVER_WINDOW,
        helper.SERIES_SUBSTRATE_CLASS,
    ):
        assert f"# HELP {series} " in block
        assert f"# TYPE {series} gauge" in block


def test_cli_writes_textfile_block(tmp_path):
    """T15 -- CLI writes a textfile-block and exits 0."""
    env_path = tmp_path / "envelope.json"
    out_path = tmp_path / "tile.prom"
    env_path.write_text(
        json.dumps(_make_envelope(verdict="CUTOVER-DAY-MORGEN-CAUTION")),
        encoding="utf-8",
    )
    res = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--envelope",
            str(env_path),
            "--today",
            "2026-06-15",
            "--output",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    content = out_path.read_text(encoding="utf-8")
    assert "wakir_cutover_day_morgen_verdict_class 1\n" in content
    assert "wakir_cutover_day_morgen_window_days_remaining 18\n" in content


def test_cross_repo_mirror_byte_identical():
    """T16 -- runtime + mirror dashboards are byte-identical."""
    assert MIRROR_PATH.exists(), f"mirror missing: {MIRROR_PATH}"
    runtime_bytes = DASHBOARD_PATH.read_bytes()
    mirror_bytes = MIRROR_PATH.read_bytes()
    assert runtime_bytes == mirror_bytes, (
        "runtime + mirror dashboard files diverged; "
        "re-mirror required"
    )
