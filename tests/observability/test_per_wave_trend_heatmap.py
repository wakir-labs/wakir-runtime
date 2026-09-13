#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/observability/per-welle-trend-heatmap.py``.

These tests are stdlib-only (pytest as test runner). No network,
no podman, no live VM. The renderer's I/O surface is exercised
via ``tmp_path`` fixtures.

Test coverage (>= 10 tests, Auftrag-Tag-48 minimum):

  1.  test_window_dates_returns_iso_oldest_to_newest
  2.  test_window_dates_zero_returns_empty
  3.  test_parse_snapshot_persisted_shape
  4.  test_parse_snapshot_live_demo_shape_extracts_per_welle
  5.  test_parse_snapshot_malformed_blob_returns_empty_skeleton
  6.  test_build_heatmap_baseline_fills_all_rows_and_columns
  7.  test_build_heatmap_missing_day_renders_dot_glyph
  8.  test_build_heatmap_summary_counts_match_cell_glyphs
  9.  test_build_heatmap_distinguishes_per_welle_vs_aggregate_glyphs
  10. test_render_ascii_grid_contains_legend_and_rows
  11. test_render_markdown_contains_table_legend_and_summary
  12. test_render_markdown_distinguishes_aggregate_row_label
  13. test_cells_by_row_groups_in_date_order
  14. test_load_state_dir_ignores_malformed_files
  15. test_load_state_dir_ignores_non_iso_filenames
  16. test_write_outputs_writes_sorted_json_and_markdown
  17. test_cli_writes_outputs_for_explicit_today
  18. test_cli_prints_ascii_when_no_outputs_given
  19. test_cli_rejects_zero_window_days

Anchors:
  * Reza Tag-44 PR #285 Pre-Cutover Daily-Trend-Analyzer.
  * Noa Tag-46 PR #296 Mira-Notify emitter+receiver chain.
  * Noa Tag-47 PR #302 Alert-Rule-to-Mira-Notify bridge.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------
# Loader: import the renderer module from its hyphenated path.
# ---------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_HEATMAP_PATH = (
    _REPO_ROOT
    / "scripts"
    / "observability"
    / "per-welle-trend-heatmap.py"
)


@pytest.fixture(scope="module")
def heatmap_mod():
    mod_name = "per_welle_trend_heatmap"
    spec = importlib.util.spec_from_file_location(mod_name, _HEATMAP_PATH)
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


def make_persisted_snapshot(
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
        "date_iso": date_iso,
        "run_id": "test-run",
        "aggregate": aggregate,
        "per_welle": {str(k): v for k, v in per_welle.items()},
        "captured_at_utc": f"{date_iso}T06:00:00Z",
        "expected_aggregate": "BLOCK",
        "aggregate_match": True,
    }


def make_live_demo_snapshot(
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
        "mode": "sandbox-stub",
        "expected_aggregate": "BLOCK",
        "observed_aggregate": aggregate,
        "aggregate_match": True,
        "probes": [
            {"welle": w, "component": f"comp-{w}", "verdict": v}
            for w, v in per_welle.items()
        ],
    }


def baseline_snapshots(start_iso: str, n_days: int) -> dict[str, dict]:
    """Build a baseline of N consecutive BLOCK-baseline *normalised*
    snapshots (build_heatmap's input contract: per_welle keyed by int)."""
    from datetime import date, timedelta

    out: dict[str, dict] = {}
    base = date.fromisoformat(start_iso)
    for i in range(n_days):
        d = (base + timedelta(days=i)).isoformat()
        out[d] = {
            "date_iso": d,
            "aggregate": "BLOCK",
            "per_welle": {
                1: "CAUTION",
                2: "CAUTION",
                3: "CAUTION",
                4: "CAUTION",
                5: "CAUTION",
                6: "GREEN",
                7: "BLOCK",
            },
        }
    return out


# ---------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------


def test_window_dates_returns_iso_oldest_to_newest(heatmap_mod):
    wd = heatmap_mod.window_dates("2026-05-19", 7)
    assert wd == (
        "2026-05-13",
        "2026-05-14",
        "2026-05-15",
        "2026-05-16",
        "2026-05-17",
        "2026-05-18",
        "2026-05-19",
    )


def test_window_dates_zero_returns_empty(heatmap_mod):
    assert heatmap_mod.window_dates("2026-05-19", 0) == tuple()


def test_parse_snapshot_persisted_shape(heatmap_mod):
    blob = make_persisted_snapshot("2026-05-19", aggregate="CAUTION")
    snap = heatmap_mod._parse_snapshot(blob, fallback_date_iso="2026-05-19")
    assert snap["date_iso"] == "2026-05-19"
    assert snap["aggregate"] == "CAUTION"
    assert snap["per_welle"][7] == "BLOCK"
    assert snap["per_welle"][6] == "GREEN"


def test_parse_snapshot_live_demo_shape_extracts_per_welle(heatmap_mod):
    blob = make_live_demo_snapshot("2026-05-19", aggregate="BLOCK")
    snap = heatmap_mod._parse_snapshot(blob, fallback_date_iso="2026-05-19")
    assert snap["date_iso"] == "2026-05-19"
    # Live-demo uses observed_aggregate; parser maps it to aggregate.
    assert snap["aggregate"] == "BLOCK"
    assert set(snap["per_welle"].keys()) == {1, 2, 3, 4, 5, 6, 7}


def test_parse_snapshot_malformed_blob_returns_empty_skeleton(heatmap_mod):
    snap = heatmap_mod._parse_snapshot("not-a-dict", fallback_date_iso="2026-05-19")  # type: ignore[arg-type]
    assert snap["date_iso"] == "2026-05-19"
    assert snap["aggregate"] == ""
    assert snap["per_welle"] == {}


def test_build_heatmap_baseline_fills_all_rows_and_columns(heatmap_mod):
    snaps = baseline_snapshots("2026-05-13", 7)
    hm = heatmap_mod.build_heatmap(snaps, "2026-05-19", window=7)
    # 7 welle rows + aggregate row = 8 rows; 7 columns; 8*7 = 56 cells.
    assert len(hm.rows) == 8
    assert len(hm.window_dates) == 7
    assert len(hm.cells) == 56
    # All Welle-6 cells must be GREEN ('G').
    welle6_cells = [c for c in hm.cells if c.row_key == "welle-6"]
    assert all(c.glyph == "G" for c in welle6_cells)
    # All Welle-7 cells must be BLOCK ('B').
    welle7_cells = [c for c in hm.cells if c.row_key == "welle-7"]
    assert all(c.glyph == "B" for c in welle7_cells)


def test_build_heatmap_missing_day_renders_dot_glyph(heatmap_mod):
    snaps = baseline_snapshots("2026-05-13", 7)
    # Drop two interior days.
    del snaps["2026-05-15"]
    del snaps["2026-05-17"]
    hm = heatmap_mod.build_heatmap(snaps, "2026-05-19", window=7)
    missing_cells = [c for c in hm.cells if c.date_iso in ("2026-05-15", "2026-05-17")]
    # 2 missing days * 8 rows = 16 missing cells.
    assert len(missing_cells) == 16
    assert all(c.glyph == "." for c in missing_cells)
    assert all(c.color == "transparent" for c in missing_cells)


def test_build_heatmap_summary_counts_match_cell_glyphs(heatmap_mod):
    snaps = baseline_snapshots("2026-05-13", 7)
    hm = heatmap_mod.build_heatmap(snaps, "2026-05-19", window=7)
    # Welle-1 is CAUTION every day -> CAUTION=7 in summary.
    assert hm.summary_counts["welle-1"]["CAUTION"] == 7
    # Welle-7 is BLOCK every day -> BLOCK=7.
    assert hm.summary_counts["welle-7"]["BLOCK"] == 7
    # Aggregate is BLOCK every day.
    assert hm.summary_counts["aggregate"]["BLOCK"] == 7


def test_build_heatmap_distinguishes_per_welle_vs_aggregate_glyphs(heatmap_mod):
    """A per-Welle GREEN must render 'G'; an aggregate READY must render 'R'.

    Both map to the same color ('green') but the glyphs differ so
    the operator can tell at a glance whether a green cell is a
    per-Welle verdict or the aggregate flipping to READY.
    """
    snaps = {
        "2026-05-19": {
            "date_iso": "2026-05-19",
            "aggregate": "READY",
            "per_welle": {w: "GREEN" for w in (1, 2, 3, 4, 5, 6, 7)},
        }
    }
    hm = heatmap_mod.build_heatmap(snaps, "2026-05-19", window=1)
    welle_glyphs = {c.glyph for c in hm.cells if c.row_key.startswith("welle-")}
    agg_glyphs = {c.glyph for c in hm.cells if c.row_key == "aggregate"}
    assert welle_glyphs == {"G"}
    assert agg_glyphs == {"R"}


def test_render_ascii_grid_contains_legend_and_rows(heatmap_mod):
    snaps = baseline_snapshots("2026-05-13", 7)
    hm = heatmap_mod.build_heatmap(snaps, "2026-05-19", window=7)
    ascii_grid = heatmap_mod.render_ascii(hm)
    # Title.
    assert "Per-Welle Trend Heatmap" in ascii_grid
    assert "2026-05-19" in ascii_grid
    # Each Welle row.
    for w in range(1, 8):
        assert f"welle-{w}" in ascii_grid
    # Aggregate row labelled AGG (not "aggregate") for visual symmetry.
    assert "AGG" in ascii_grid
    # Legend lines.
    assert "G=GREEN" in ascii_grid
    assert "R=READY" in ascii_grid
    assert ".=MISSING" in ascii_grid


def test_render_markdown_contains_table_legend_and_summary(heatmap_mod):
    snaps = baseline_snapshots("2026-05-13", 7)
    hm = heatmap_mod.build_heatmap(snaps, "2026-05-19", window=7)
    md = heatmap_mod.render_markdown(hm)
    # Header.
    assert "# Per-Welle Trend Heatmap -- 2026-05-19" in md
    # Window line.
    assert "Window: last 7 days" in md
    # Table header has all 7 MM-DD columns.
    for d in ("05-13", "05-14", "05-15", "05-16", "05-17", "05-18", "05-19"):
        assert d in md
    # Legend block present.
    assert "## Legend" in md
    # Summary block present.
    assert "## Summary counts" in md
    # Anchor footer.
    assert "Noa Tag-48" in md


def test_render_markdown_distinguishes_aggregate_row_label(heatmap_mod):
    snaps = baseline_snapshots("2026-05-13", 7)
    hm = heatmap_mod.build_heatmap(snaps, "2026-05-19", window=7)
    md = heatmap_mod.render_markdown(hm)
    # Aggregate row is bold-labeled **AGG** so the operator sees
    # it as the summary band, not just another welle.
    assert "| **AGG** |" in md


def test_cells_by_row_groups_in_date_order(heatmap_mod):
    snaps = baseline_snapshots("2026-05-13", 7)
    hm = heatmap_mod.build_heatmap(snaps, "2026-05-19", window=7)
    grouped = heatmap_mod.cells_by_row(hm)
    welle1 = grouped["welle-1"]
    # 7 cells.
    assert len(welle1) == 7
    # Oldest -> newest order.
    dates = [c.date_iso for c in welle1]
    assert dates == sorted(dates)
    assert dates[0] == "2026-05-13"
    assert dates[-1] == "2026-05-19"


def test_load_state_dir_ignores_malformed_files(heatmap_mod, tmp_path):
    sd = tmp_path / "state"
    sd.mkdir()
    # One good file.
    good = make_persisted_snapshot("2026-05-19", aggregate="BLOCK")
    (sd / "2026-05-19.json").write_text(json.dumps(good), encoding="utf-8")
    # One malformed JSON file.
    (sd / "2026-05-18.json").write_text("{not json", encoding="utf-8")
    # One non-JSON file masquerading as a snapshot.
    (sd / "2026-05-17.json").write_text("plain text", encoding="utf-8")
    loaded = heatmap_mod.load_state_dir(sd)
    # Only the good one survives.
    assert set(loaded.keys()) == {"2026-05-19"}


def test_load_state_dir_ignores_non_iso_filenames(heatmap_mod, tmp_path):
    sd = tmp_path / "state"
    sd.mkdir()
    (sd / "not-a-date.json").write_text("{}", encoding="utf-8")
    (sd / "2026-13-99.json").write_text("{}", encoding="utf-8")
    good = make_persisted_snapshot("2026-05-19", aggregate="BLOCK")
    (sd / "2026-05-19.json").write_text(json.dumps(good), encoding="utf-8")
    loaded = heatmap_mod.load_state_dir(sd)
    assert set(loaded.keys()) == {"2026-05-19"}


def test_write_outputs_writes_sorted_json_and_markdown(heatmap_mod, tmp_path):
    snaps = baseline_snapshots("2026-05-13", 7)
    hm = heatmap_mod.build_heatmap(snaps, "2026-05-19", window=7)
    out_json = tmp_path / "out" / "heatmap.json"
    out_md = tmp_path / "out" / "heatmap.md"
    out_ascii = tmp_path / "out" / "heatmap.txt"
    heatmap_mod.write_outputs(hm, out_json, out_md, out_ascii)
    assert out_json.is_file()
    assert out_md.is_file()
    assert out_ascii.is_file()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["schema_version"] == heatmap_mod.SCHEMA_VERSION
    assert payload["today_date_iso"] == "2026-05-19"
    # JSON must be sorted (top-level keys ordered).
    keys = list(payload.keys())
    assert keys == sorted(keys)


def test_cli_writes_outputs_for_explicit_today(heatmap_mod, tmp_path):
    sd = tmp_path / "state"
    sd.mkdir()
    snaps = baseline_snapshots("2026-05-13", 7)
    for d, blob in snaps.items():
        (sd / f"{d}.json").write_text(json.dumps(blob), encoding="utf-8")
    out_json = tmp_path / "heatmap.json"
    out_md = tmp_path / "heatmap.md"
    out_ascii = tmp_path / "heatmap.txt"
    rc = heatmap_mod.cli_main([
        "--state-dir", str(sd),
        "--today", "2026-05-19",
        "--window-days", "7",
        "--output-json", str(out_json),
        "--output-md", str(out_md),
        "--output-ascii", str(out_ascii),
    ])
    assert rc == 0
    assert out_json.is_file()
    assert out_md.is_file()
    assert out_ascii.is_file()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["today_date_iso"] == "2026-05-19"
    assert payload["window_days"] == 7
    assert len(payload["cells"]) == 56


def test_cli_prints_ascii_when_no_outputs_given(heatmap_mod, tmp_path, capsys):
    sd = tmp_path / "state"
    sd.mkdir()
    snap = make_persisted_snapshot("2026-05-19", aggregate="BLOCK")
    (sd / "2026-05-19.json").write_text(json.dumps(snap), encoding="utf-8")
    rc = heatmap_mod.cli_main([
        "--state-dir", str(sd),
        "--today", "2026-05-19",
        "--window-days", "1",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Per-Welle Trend Heatmap" in captured.out
    assert "Legend:" in captured.out


def test_cli_rejects_zero_window_days(heatmap_mod, tmp_path, capsys):
    rc = heatmap_mod.cli_main([
        "--state-dir", str(tmp_path),
        "--today", "2026-05-19",
        "--window-days", "0",
    ])
    assert rc == 2
    captured = capsys.readouterr()
    assert "--window-days" in captured.err
