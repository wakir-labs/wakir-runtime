#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/observability/per-welle-heatmap-prom-emitter.py``.

These tests are stdlib + pytest only. No network, no podman, no
live VM. The emitter's I/O surface is exercised via ``tmp_path``
fixtures.

Test coverage (>= 10 tests, Auftrag-Tag-49 minimum):

  1.  test_numeric_for_verdict_known_buckets
  2.  test_numeric_for_verdict_missing_and_unknown
  3.  test_esc_handles_quotes_and_backslashes
  4.  test_today_iso_to_unix_returns_midnight_utc
  5.  test_today_iso_to_unix_falls_back_for_garbage
  6.  test_normalise_envelope_baseline_shape
  7.  test_normalise_envelope_skips_malformed_cells
  8.  test_normalise_envelope_handles_missing_summary_counts
  9.  test_compute_stability_match_counts_stable_row
  10. test_compute_stability_match_counts_flipped_row
  11. test_compute_stability_match_counts_blank_latest
  12. test_render_includes_all_metric_families
  13. test_render_verdict_numeric_mapping_per_cell
  14. test_render_summary_count_one_line_per_bucket
  15. test_render_stability_match_count_per_row
  16. test_render_window_days_gauge_present
  17. test_render_timestamp_gauge_uses_today_midnight
  18. test_render_missing_verdict_uses_minus_one_and_label_missing
  19. test_write_textfile_is_atomic_temp_then_rename
  20. test_resolve_envelope_path_picks_latest_when_today_unset
  21. test_resolve_envelope_path_raises_when_dir_empty
  22. test_cli_writes_output_and_returns_zero
  23. test_cli_print_flag_emits_to_stdout

Anchors:
  * Tag-48 PR #309 renderer + dashboard.
  * Tag-48 runbook explicit Tag-49 emitter deferral.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------
# Loader: import the emitter module from its hyphenated path.
# ---------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_EMITTER_PATH = (
    _REPO_ROOT
    / "scripts"
    / "observability"
    / "per-welle-heatmap-prom-emitter.py"
)


@pytest.fixture(scope="module")
def emitter_mod():
    mod_name = "per_welle_heatmap_prom_emitter"
    spec = importlib.util.spec_from_file_location(mod_name, _EMITTER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return mod


# ---------------------------------------------------------------------
# Synthetic envelope helper.
# ---------------------------------------------------------------------


def make_envelope(
    today_iso: str = "2026-05-19",
    window_days: int = 3,
) -> dict:
    """Build a minimal-but-realistic 3-row x N-day heatmap envelope.

    Shape mirrors what
    ``scripts/observability/per-welle-trend-heatmap.py`` writes into
    ``state/per-welle-heatmap/yyyy-mm-dd.json``.
    """
    from datetime import date, timedelta

    end = date.fromisoformat(today_iso)
    dates = [
        (end - timedelta(days=i)).isoformat()
        for i in range(window_days - 1, -1, -1)
    ]
    cells = []
    rows = ["welle-1", "welle-7", "aggregate"]
    # welle-1 stable CAUTION
    for d in dates:
        cells.append(
            {
                "date_iso": d,
                "row_key": "welle-1",
                "welle": 1,
                "verdict": "CAUTION",
                "glyph": "C",
                "color": "yellow",
            }
        )
    # welle-7 stable BLOCK
    for d in dates:
        cells.append(
            {
                "date_iso": d,
                "row_key": "welle-7",
                "welle": 7,
                "verdict": "BLOCK",
                "glyph": "B",
                "color": "red",
            }
        )
    # aggregate: 2x NOT-READY then 1x BLOCK (most-recent)
    agg_verdicts = ["NOT-READY"] * (window_days - 1) + ["BLOCK"]
    for d, v in zip(dates, agg_verdicts):
        glyph = "X" if v == "NOT-READY" else "B"
        color = "red"
        cells.append(
            {
                "date_iso": d,
                "row_key": "aggregate",
                "welle": None,
                "verdict": v,
                "glyph": glyph,
                "color": color,
            }
        )
    summary_counts = {
        "welle-1": {"CAUTION": window_days},
        "welle-7": {"BLOCK": window_days},
        "aggregate": {"NOT-READY": window_days - 1, "BLOCK": 1},
    }
    return {
        "schema_version": "1.0",
        "today_date_iso": today_iso,
        "window_days": window_days,
        "window_dates": dates,
        "rows": rows,
        "cells": cells,
        "summary_counts": summary_counts,
        "legend": {
            "C": "CAUTION",
            "B": "BLOCK",
            "X": "NOT-READY (aggregate)",
        },
    }


# ---------------------------------------------------------------------
# Pure-helper tests.
# ---------------------------------------------------------------------


def test_numeric_for_verdict_known_buckets(emitter_mod):
    f = emitter_mod._numeric_for_verdict
    assert f("GREEN") == 0
    assert f("CAUTION") == 1
    assert f("NOT-EXEC") == 2
    assert f("BLOCK") == 3
    assert f("READY") == 4
    assert f("NOT-READY") == 5


def test_numeric_for_verdict_missing_and_unknown(emitter_mod):
    f = emitter_mod._numeric_for_verdict
    assert f("") == -1
    assert f("MISSING") == -1
    assert f("FOO-BAR") == -1


def test_esc_handles_quotes_and_backslashes(emitter_mod):
    e = emitter_mod._esc
    assert e('a"b') == 'a\\"b'
    assert e("a\\b") == "a\\\\b"
    assert e("a\nb") == "a\\nb"
    # integer welle should survive
    assert e(7) == "7"


def test_today_iso_to_unix_returns_midnight_utc(emitter_mod):
    ts = emitter_mod._today_iso_to_unix("2026-05-19")
    expected = datetime(2026, 5, 19, tzinfo=timezone.utc).timestamp()
    assert ts == expected


def test_today_iso_to_unix_falls_back_for_garbage(emitter_mod):
    ts = emitter_mod._today_iso_to_unix("not-a-date")
    # Should still be a positive unix timestamp (wall clock fallback).
    assert ts > 0


# ---------------------------------------------------------------------
# Envelope normalisation tests.
# ---------------------------------------------------------------------


def test_normalise_envelope_baseline_shape(emitter_mod):
    env = make_envelope(today_iso="2026-05-19", window_days=3)
    norm = emitter_mod._normalise_envelope(env)
    assert norm["today_date_iso"] == "2026-05-19"
    assert norm["window_days"] == 3
    assert norm["rows"] == ["welle-1", "welle-7", "aggregate"]
    assert len(norm["cells"]) == 9  # 3 rows x 3 days
    assert norm["summary_counts"]["welle-1"] == {"CAUTION": 3}


def test_normalise_envelope_skips_malformed_cells(emitter_mod):
    env = make_envelope()
    env["cells"].extend([
        "not-a-dict",
        42,
        None,
    ])
    norm = emitter_mod._normalise_envelope(env)
    # The 3 garbage entries must be dropped.
    assert len(norm["cells"]) == 9


def test_normalise_envelope_handles_missing_summary_counts(emitter_mod):
    env = make_envelope()
    env.pop("summary_counts")
    norm = emitter_mod._normalise_envelope(env)
    assert norm["summary_counts"] == {}


# ---------------------------------------------------------------------
# Stability-match-count tests.
# ---------------------------------------------------------------------


def test_compute_stability_match_counts_stable_row(emitter_mod):
    cells = [
        {"date_iso": "2026-05-17", "row_key": "r", "verdict": "GREEN"},
        {"date_iso": "2026-05-18", "row_key": "r", "verdict": "GREEN"},
        {"date_iso": "2026-05-19", "row_key": "r", "verdict": "GREEN"},
    ]
    out = emitter_mod.compute_stability_match_counts(cells)
    assert out["r"] == 3


def test_compute_stability_match_counts_flipped_row(emitter_mod):
    cells = [
        {"date_iso": "2026-05-17", "row_key": "r", "verdict": "GREEN"},
        {"date_iso": "2026-05-18", "row_key": "r", "verdict": "GREEN"},
        {"date_iso": "2026-05-19", "row_key": "r", "verdict": "BLOCK"},
    ]
    out = emitter_mod.compute_stability_match_counts(cells)
    # Latest verdict is BLOCK, only 1 day matches.
    assert out["r"] == 1


def test_compute_stability_match_counts_blank_latest(emitter_mod):
    cells = [
        {"date_iso": "2026-05-17", "row_key": "r", "verdict": ""},
        {"date_iso": "2026-05-18", "row_key": "r", "verdict": ""},
        {"date_iso": "2026-05-19", "row_key": "r", "verdict": ""},
    ]
    out = emitter_mod.compute_stability_match_counts(cells)
    # All blank -> all match (latest is also blank).
    assert out["r"] == 3


# ---------------------------------------------------------------------
# Render-textfile tests.
# ---------------------------------------------------------------------


def test_render_includes_all_metric_families(emitter_mod):
    env = make_envelope()
    out = emitter_mod.render_prometheus_textfile(env, timestamp_unixtime=1.0)
    for metric in (
        "persona_engine_per_welle_heatmap_verdict",
        "persona_engine_per_welle_heatmap_summary_count",
        "persona_engine_per_welle_heatmap_stability_match_count",
        "persona_engine_per_welle_heatmap_window_days",
        "persona_engine_per_welle_heatmap_render_timestamp_seconds",
    ):
        assert f"# HELP {metric}" in out, f"missing HELP for {metric}"
        assert f"# TYPE {metric} gauge" in out, f"missing TYPE for {metric}"


def test_render_verdict_numeric_mapping_per_cell(emitter_mod):
    env = make_envelope(today_iso="2026-05-19", window_days=3)
    out = emitter_mod.render_prometheus_textfile(env, timestamp_unixtime=0.0)
    # welle-1 CAUTION -> numeric 1.
    line_welle1 = [
        line
        for line in out.splitlines()
        if line.startswith("persona_engine_per_welle_heatmap_verdict{")
        and 'row_key="welle-1"' in line
        and 'date_iso="2026-05-19"' in line
    ]
    assert len(line_welle1) == 1
    assert line_welle1[0].split("} ")[1].split(" ")[0] == "1"
    # welle-7 BLOCK -> numeric 3.
    line_welle7 = [
        line
        for line in out.splitlines()
        if line.startswith("persona_engine_per_welle_heatmap_verdict{")
        and 'row_key="welle-7"' in line
        and 'date_iso="2026-05-19"' in line
    ]
    assert line_welle7[0].split("} ")[1].split(" ")[0] == "3"
    # aggregate BLOCK at most-recent date.
    line_agg = [
        line
        for line in out.splitlines()
        if line.startswith("persona_engine_per_welle_heatmap_verdict{")
        and 'row_key="aggregate"' in line
        and 'date_iso="2026-05-19"' in line
    ]
    assert line_agg[0].split("} ")[1].split(" ")[0] == "3"


def test_render_summary_count_one_line_per_bucket(emitter_mod):
    env = make_envelope()
    out = emitter_mod.render_prometheus_textfile(env, timestamp_unixtime=0.0)
    summary_lines = [
        line
        for line in out.splitlines()
        if line.startswith("persona_engine_per_welle_heatmap_summary_count{")
    ]
    # welle-1 has 1 bucket, welle-7 has 1, aggregate has 2 -> 4 lines.
    assert len(summary_lines) == 4
    assert any('row_key="welle-1"' in line and 'verdict="CAUTION"' in line for line in summary_lines)
    assert any('row_key="aggregate"' in line and 'verdict="BLOCK"' in line for line in summary_lines)
    assert any('row_key="aggregate"' in line and 'verdict="NOT-READY"' in line for line in summary_lines)


def test_render_stability_match_count_per_row(emitter_mod):
    env = make_envelope(today_iso="2026-05-19", window_days=3)
    out = emitter_mod.render_prometheus_textfile(env, timestamp_unixtime=0.0)
    # welle-1 fully stable -> 3.
    line_w1 = [
        line
        for line in out.splitlines()
        if line.startswith("persona_engine_per_welle_heatmap_stability_match_count{")
        and 'row_key="welle-1"' in line
    ]
    assert line_w1[0].split("} ")[1].split(" ")[0] == "3"
    # aggregate flipped on the most-recent day -> only latest matches -> 1.
    line_agg = [
        line
        for line in out.splitlines()
        if line.startswith("persona_engine_per_welle_heatmap_stability_match_count{")
        and 'row_key="aggregate"' in line
    ]
    assert line_agg[0].split("} ")[1].split(" ")[0] == "1"


def test_render_window_days_gauge_present(emitter_mod):
    env = make_envelope(today_iso="2026-05-19", window_days=7)
    out = emitter_mod.render_prometheus_textfile(env, timestamp_unixtime=0.0)
    matching = [
        line
        for line in out.splitlines()
        if line.startswith("persona_engine_per_welle_heatmap_window_days ")
    ]
    assert len(matching) == 1
    assert matching[0].split(" ")[1] == "7"


def test_render_timestamp_gauge_uses_today_midnight(emitter_mod):
    env = make_envelope(today_iso="2026-05-19", window_days=3)
    out = emitter_mod.render_prometheus_textfile(env, timestamp_unixtime=0.0)
    line = [
        line
        for line in out.splitlines()
        if line.startswith(
            "persona_engine_per_welle_heatmap_render_timestamp_seconds "
        )
    ][0]
    expected = int(
        datetime(2026, 5, 19, tzinfo=timezone.utc).timestamp()
    )
    assert int(line.split(" ")[1]) == expected


def test_render_missing_verdict_uses_minus_one_and_label_missing(emitter_mod):
    env = make_envelope(today_iso="2026-05-19", window_days=3)
    # Inject one MISSING cell.
    env["cells"].append(
        {
            "date_iso": "2026-05-18",
            "row_key": "welle-3",
            "welle": 3,
            "verdict": "",
            "glyph": ".",
            "color": "transparent",
        }
    )
    out = emitter_mod.render_prometheus_textfile(env, timestamp_unixtime=0.0)
    line = [
        line
        for line in out.splitlines()
        if line.startswith("persona_engine_per_welle_heatmap_verdict{")
        and 'row_key="welle-3"' in line
    ]
    assert len(line) == 1
    assert 'verdict="MISSING"' in line[0]
    assert line[0].split("} ")[1].split(" ")[0] == "-1"


# ---------------------------------------------------------------------
# I/O tests.
# ---------------------------------------------------------------------


def test_write_textfile_is_atomic_temp_then_rename(emitter_mod, tmp_path):
    out_path = tmp_path / "out" / "x.prom"
    emitter_mod.write_textfile("hello\n", out_path)
    assert out_path.read_text(encoding="utf-8") == "hello\n"
    # Re-write: should overwrite, no stray tmp files left.
    emitter_mod.write_textfile("world\n", out_path)
    assert out_path.read_text(encoding="utf-8") == "world\n"
    leftover = [p for p in out_path.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftover == []


def test_resolve_envelope_path_picks_latest_when_today_unset(emitter_mod, tmp_path):
    d = tmp_path / "heatmap"
    d.mkdir()
    (d / "2026-05-17.json").write_text("{}", encoding="utf-8")
    (d / "2026-05-19.json").write_text("{}", encoding="utf-8")
    (d / "2026-05-18.json").write_text("{}", encoding="utf-8")
    resolved = emitter_mod.resolve_envelope_path(d, None)
    assert resolved.name == "2026-05-19.json"


def test_resolve_envelope_path_raises_when_dir_empty(emitter_mod, tmp_path):
    d = tmp_path / "heatmap"
    d.mkdir()
    with pytest.raises(FileNotFoundError):
        emitter_mod.resolve_envelope_path(d, None)


# ---------------------------------------------------------------------
# CLI tests.
# ---------------------------------------------------------------------


def test_cli_writes_output_and_returns_zero(emitter_mod, tmp_path):
    env = make_envelope(today_iso="2026-05-19", window_days=3)
    envelope_path = tmp_path / "2026-05-19.json"
    envelope_path.write_text(json.dumps(env), encoding="utf-8")
    out_path = tmp_path / "out" / "per-welle-heatmap.prom"
    rc = emitter_mod.cli_main(
        [
            "--input-envelope",
            str(envelope_path),
            "--output",
            str(out_path),
        ]
    )
    assert rc == 0
    assert out_path.is_file()
    text = out_path.read_text(encoding="utf-8")
    assert "persona_engine_per_welle_heatmap_verdict" in text


def test_cli_print_flag_emits_to_stdout(emitter_mod, tmp_path, capsys):
    env = make_envelope(today_iso="2026-05-19", window_days=3)
    envelope_path = tmp_path / "2026-05-19.json"
    envelope_path.write_text(json.dumps(env), encoding="utf-8")
    out_path = tmp_path / "out" / "per-welle-heatmap.prom"
    rc = emitter_mod.cli_main(
        [
            "--input-envelope",
            str(envelope_path),
            "--output",
            str(out_path),
            "--print",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "persona_engine_per_welle_heatmap_verdict" in captured.out
