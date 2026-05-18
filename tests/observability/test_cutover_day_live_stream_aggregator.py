#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for cutover-day-live-stream-aggregator.py (Tag-41).

Coverage targets the pure-function decision core: sliding-window
ingestion, distribution normalisation, total-variation drift
computation, band-crossing detection, JSON / Prometheus rendering,
and the run_pipeline driver against an in-memory fixture iterator.

The I/O wrappers (NATS-CLI subshell, signal handlers, file-tail) are
NOT unit-tested here; integration coverage lives in the fixture-mode
entrypoint and the Bash wrapper's dry-run rehearsal.

Anchor: ADR-0066 Phase-3c, Tag-41 Noa SRE.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Loader: import the aggregator module from its hyphenated path.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_AGG_PATH = (
    _REPO_ROOT
    / "scripts"
    / "observability"
    / "cutover-day-live-stream-aggregator.py"
)

_spec = importlib.util.spec_from_file_location(
    "cutover_day_live_stream_aggregator", str(_AGG_PATH)
)
assert _spec is not None
assert _spec.loader is not None
agg = importlib.util.module_from_spec(_spec)
# Register in sys.modules BEFORE exec_module so dataclasses' frozen=True
# can resolve cls.__module__ during _process_class (Python 3.14 stricter).
sys.modules["cutover_day_live_stream_aggregator"] = agg
_spec.loader.exec_module(agg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_event(
    welle: str,
    outcome: str,
    latency_ms: float = 12.0,
    head_sha: str = "abc123",
    ts: float = 1747740000.0,
) -> "agg.BackendDecisionEvent":
    return agg.BackendDecisionEvent(
        welle=welle,
        outcome=outcome,
        latency_ms=latency_ms,
        head_sha=head_sha,
        timestamp_unixtime=ts,
    )


def _event_line(
    welle: str,
    outcome: str,
    latency_ms: float = 12.0,
    head_sha: str = "abc123",
    ts: float = 1747740000.0,
) -> str:
    return (
        json.dumps(
            {
                "welle": welle,
                "outcome": outcome,
                "latency_ms": latency_ms,
                "head_sha": head_sha,
                "timestamp_unixtime": ts,
            }
        )
        + "\n"
    )


# ---------------------------------------------------------------------------
# 1. parse_event_json
# ---------------------------------------------------------------------------


def test_parse_event_json_well_formed():
    ev = agg.parse_event_json(_event_line("welle-3", "production", 14.2))
    assert ev is not None
    assert ev.welle == "welle-3"
    assert ev.outcome == "production"
    assert ev.latency_ms == pytest.approx(14.2)


def test_parse_event_json_rejects_missing_required_fields():
    # Missing welle.
    assert agg.parse_event_json('{"outcome": "production"}') is None
    # Missing outcome.
    assert agg.parse_event_json('{"welle": "welle-3"}') is None
    # Empty line.
    assert agg.parse_event_json("") is None
    # Whitespace only.
    assert agg.parse_event_json("   \n") is None
    # Malformed JSON.
    assert agg.parse_event_json("not json") is None
    # Non-object JSON.
    assert agg.parse_event_json("[1, 2, 3]") is None


def test_parse_event_json_tolerates_extra_and_missing_optional_fields():
    # Extra field is fine.
    ev = agg.parse_event_json(
        '{"welle": "welle-1", "outcome": "shadow", "extra_field": "ignored"}'
    )
    assert ev is not None
    assert ev.welle == "welle-1"
    assert ev.outcome == "shadow"
    assert ev.latency_ms == 0.0  # default
    assert ev.head_sha == ""  # default
    # Bad latency_ms type falls back to 0.
    ev2 = agg.parse_event_json(
        '{"welle": "welle-1", "outcome": "shadow", "latency_ms": "not-a-number"}'
    )
    assert ev2 is not None
    assert ev2.latency_ms == 0.0


# ---------------------------------------------------------------------------
# 2. WelleWindow / sliding-window semantics
# ---------------------------------------------------------------------------


def test_welle_window_evicts_oldest_at_capacity():
    w = agg.WelleWindow(welle="welle-3", capacity=3)
    # Add 5 events; capacity is 3.
    for i in range(5):
        w.add(_mk_event("welle-3", "production", latency_ms=float(i)))
    assert w.sample_count() == 3
    # The remaining latencies should be the last three (2, 3, 4).
    assert sorted(w.latencies_ms) == [2.0, 3.0, 4.0]


def test_welle_window_distribution_normalised():
    w = agg.WelleWindow(welle="welle-3", capacity=100)
    # 7 production, 3 shadow.
    for _ in range(7):
        w.add(_mk_event("welle-3", "production"))
    for _ in range(3):
        w.add(_mk_event("welle-3", "shadow"))
    dist = w.distribution()
    assert dist["production"] == pytest.approx(0.7)
    assert dist["shadow"] == pytest.approx(0.3)
    assert dist["fallback"] == pytest.approx(0.0)
    # Distribution sums to 1.
    assert sum(dist.values()) == pytest.approx(1.0)


def test_welle_window_unknown_outcome_bucketed_as_unknown():
    w = agg.WelleWindow(welle="welle-3", capacity=100)
    w.add(_mk_event("welle-3", "novel_backend_xyz"))
    assert w.outcome_counts["unknown"] == 1
    assert w.distribution()["unknown"] == pytest.approx(1.0)


def test_welle_window_empty_distribution_is_zero():
    w = agg.WelleWindow(welle="welle-3", capacity=10)
    dist = w.distribution()
    assert all(v == 0.0 for v in dist.values())
    p50, p95, p99 = w.latency_percentiles()
    assert (p50, p95, p99) == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# 3. Drift computation
# ---------------------------------------------------------------------------


def test_drift_zero_when_distributions_identical():
    state = agg.AggregatorState(window_size=100)
    for _ in range(50):
        state.ingest(_mk_event("welle-4", "production"))
        state.ingest(_mk_event("welle-5", "production"))
    readings = agg.compute_pairwise_drift(state.windows)
    assert len(readings) == 1
    r = readings[0]
    assert r.welle_a == "welle-4"
    assert r.welle_b == "welle-5"
    assert r.drift == pytest.approx(0.0)
    assert r.band == "GREEN"


def test_drift_max_when_distributions_disjoint():
    state = agg.AggregatorState(window_size=100)
    for _ in range(50):
        state.ingest(_mk_event("welle-4", "production"))
        state.ingest(_mk_event("welle-5", "fallback"))
    readings = agg.compute_pairwise_drift(state.windows)
    r = readings[0]
    # Total-variation between two point-masses on different buckets = 1.0.
    assert r.drift == pytest.approx(1.0)
    assert r.band == "RED"


def test_drift_zero_when_no_samples():
    # Two empty windows still drift=0 / GREEN (no data is not divergence).
    state = agg.AggregatorState(window_size=100)
    state.windows["welle-4"] = agg.WelleWindow(welle="welle-4", capacity=100)
    state.windows["welle-5"] = agg.WelleWindow(welle="welle-5", capacity=100)
    readings = agg.compute_pairwise_drift(state.windows)
    assert len(readings) == 1
    assert readings[0].drift == 0.0
    assert readings[0].band == "GREEN"


def test_drift_band_thresholds():
    # Exact threshold semantics: < 0.05 GREEN, < 0.15 AMBER, >= 0.15 RED.
    assert agg.classify_drift_band(0.0) == "GREEN"
    assert agg.classify_drift_band(0.04999) == "GREEN"
    assert agg.classify_drift_band(0.05) == "AMBER"
    assert agg.classify_drift_band(0.14999) == "AMBER"
    assert agg.classify_drift_band(0.15) == "RED"
    assert agg.classify_drift_band(1.0) == "RED"


def test_drift_amber_band_mid_range():
    # 80/20 vs. 60/40 production-shadow split: TV-distance = 0.5 * (|0.8-0.6|+|0.2-0.4|) = 0.2.
    state = agg.AggregatorState(window_size=100)
    for _ in range(80):
        state.ingest(_mk_event("welle-4", "production"))
    for _ in range(20):
        state.ingest(_mk_event("welle-4", "shadow"))
    for _ in range(60):
        state.ingest(_mk_event("welle-5", "production"))
    for _ in range(40):
        state.ingest(_mk_event("welle-5", "shadow"))
    readings = agg.compute_pairwise_drift(state.windows)
    r = readings[0]
    assert r.drift == pytest.approx(0.2, abs=1e-6)
    assert r.band == "RED"  # 0.2 >= 0.15


# ---------------------------------------------------------------------------
# 4. Band-crossing detection
# ---------------------------------------------------------------------------


def test_band_crossings_first_seen_pairs_not_emitted():
    # Initial snapshot: no previous bands, so no crossings.
    state = agg.AggregatorState(window_size=100)
    for _ in range(10):
        state.ingest(_mk_event("welle-4", "production"))
        state.ingest(_mk_event("welle-5", "fallback"))
    readings, crossings = state.snapshot(timestamp_unixtime=1.0)
    assert len(readings) == 1
    # First snapshot ever — previous_bands was empty.
    assert crossings == []


def test_band_crossings_detected_on_transition():
    state = agg.AggregatorState(window_size=100)
    # Phase 1: identical distributions → GREEN.
    for _ in range(10):
        state.ingest(_mk_event("welle-4", "production"))
        state.ingest(_mk_event("welle-5", "production"))
    state.snapshot(timestamp_unixtime=1.0)  # record GREEN as previous.
    # Phase 2: welle-5 shifts to fallback → RED.
    for _ in range(40):
        state.ingest(_mk_event("welle-5", "fallback"))
    _, crossings = state.snapshot(timestamp_unixtime=2.0)
    # We expect exactly one crossing GREEN → ??? (likely RED or AMBER).
    assert len(crossings) == 1
    c = crossings[0]
    assert c.previous_band == "GREEN"
    assert c.current_band in ("AMBER", "RED")
    assert c.timestamp_unixtime == 2.0


def test_band_crossings_no_event_if_band_unchanged():
    state = agg.AggregatorState(window_size=100)
    for _ in range(10):
        state.ingest(_mk_event("welle-4", "production"))
        state.ingest(_mk_event("welle-5", "production"))
    state.snapshot(timestamp_unixtime=1.0)
    # Add more events that don't shift the distribution.
    for _ in range(10):
        state.ingest(_mk_event("welle-4", "production"))
        state.ingest(_mk_event("welle-5", "production"))
    _, crossings = state.snapshot(timestamp_unixtime=2.0)
    assert crossings == []


# ---------------------------------------------------------------------------
# 5. JSON rendering
# ---------------------------------------------------------------------------


def test_render_state_json_schema():
    state = agg.AggregatorState(window_size=100)
    for _ in range(5):
        state.ingest(_mk_event("welle-3", "production"))
    readings, _ = state.snapshot(timestamp_unixtime=1747740000.0)
    text = agg.render_state_json(
        state.windows,
        readings,
        window_size=100,
        timestamp_unixtime=1747740000.0,
    )
    obj = json.loads(text)
    assert obj["schema_version"] == 1
    assert obj["window_size"] == 100
    assert "welle-3" in obj["wellen"]
    assert obj["wellen"]["welle-3"]["sample_count"] == 5
    assert obj["wellen"]["welle-3"]["distribution"]["production"] == pytest.approx(1.0)
    assert obj["summary"]["welle_count"] == 1


# ---------------------------------------------------------------------------
# 6. Prometheus textfile rendering
# ---------------------------------------------------------------------------


def test_render_prometheus_textfile_emits_help_type_and_gauges():
    state = agg.AggregatorState(window_size=100)
    for _ in range(10):
        state.ingest(_mk_event("welle-3", "production"))
    readings, _ = state.snapshot(timestamp_unixtime=1747740000.0)
    text = agg.render_prometheus_textfile(
        state.windows,
        readings,
        window_size=100,
        timestamp_unixtime=1747740000.0,
    )
    # HELP / TYPE pairs.
    assert "# HELP wakir_cutover_live_distribution" in text
    assert "# TYPE wakir_cutover_live_distribution gauge" in text
    assert "# HELP wakir_cutover_live_sample_count" in text
    assert "# HELP wakir_cutover_live_latency_ms" in text
    assert "# HELP wakir_cutover_live_drift" in text
    assert "# HELP wakir_cutover_live_drift_red" in text
    assert "# HELP wakir_cutover_live_drift_amber" in text
    # Distribution gauge present with welle + outcome labels.
    assert (
        'wakir_cutover_live_distribution{welle="welle-3",outcome="production"} 1.000000'
        in text
    )
    # Sample-count gauge has the welle label.
    assert 'wakir_cutover_live_sample_count{welle="welle-3"} 10' in text


# ---------------------------------------------------------------------------
# 7. Notify-line rendering
# ---------------------------------------------------------------------------


def test_render_notify_line_red_prefix():
    crossing = agg.DriftCrossing(
        welle_a="welle-4",
        welle_b="welle-5",
        previous_band="GREEN",
        current_band="RED",
        drift=0.32,
        timestamp_unixtime=1747740123.0,
    )
    line = agg.render_notify_line(crossing)
    assert line.startswith("DRIFT_RED_CROSSING")
    assert "welle_a=welle-4" in line
    assert "welle_b=welle-5" in line
    assert "drift=0.3200" in line
    assert "previous_band=GREEN" in line


def test_render_notify_line_amber_prefix():
    crossing = agg.DriftCrossing(
        welle_a="welle-1",
        welle_b="welle-2",
        previous_band="GREEN",
        current_band="AMBER",
        drift=0.08,
        timestamp_unixtime=1747740123.0,
    )
    line = agg.render_notify_line(crossing)
    assert line.startswith("DRIFT_AMBER_CROSSING")


# ---------------------------------------------------------------------------
# 8. run_pipeline driver
# ---------------------------------------------------------------------------


def test_run_pipeline_ingests_and_emits_snapshots():
    state = agg.AggregatorState(window_size=100)
    # 12 lines: 6 welle-4 production, 6 welle-5 production.
    lines = []
    for _ in range(6):
        lines.append(_event_line("welle-4", "production"))
    for _ in range(6):
        lines.append(_event_line("welle-5", "production"))
    # Also inject a malformed line that the pipeline must skip silently.
    lines.append("not-json\n")
    json_sink = io.StringIO()
    notify_sink = io.StringIO()
    count = agg.run_pipeline(
        iter(lines),
        state=state,
        emit_every=5,
        json_sink=json_sink,
        notify_sink=notify_sink,
    )
    assert count == 12  # malformed line skipped
    # Aggregator should have emitted two snapshots (after event 5 and 10).
    json_output = json_sink.getvalue()
    # Both Wellen present in final state.
    assert "welle-4" in json_output
    assert "welle-5" in json_output


def test_run_pipeline_writes_prometheus_textfile(tmp_path):
    state = agg.AggregatorState(window_size=100)
    lines = [_event_line("welle-1", "production") for _ in range(10)]
    prom_path = tmp_path / "out.prom"
    json_sink = io.StringIO()
    notify_sink = io.StringIO()
    agg.run_pipeline(
        iter(lines),
        state=state,
        emit_every=5,
        json_sink=json_sink,
        notify_sink=notify_sink,
        prometheus_path=prom_path,
    )
    text = prom_path.read_text(encoding="utf-8")
    assert "wakir_cutover_live_distribution" in text
    assert 'welle="welle-1"' in text


def test_run_pipeline_emits_notify_on_band_crossing():
    state = agg.AggregatorState(window_size=100)
    lines = []
    # Phase 1: 10 events each Welle, both production → GREEN.
    for _ in range(10):
        lines.append(_event_line("welle-4", "production"))
        lines.append(_event_line("welle-5", "production"))
    # Phase 2: 40 fallback on welle-5 → drift jumps into AMBER/RED.
    for _ in range(40):
        lines.append(_event_line("welle-5", "fallback"))
    json_sink = io.StringIO()
    notify_sink = io.StringIO()
    agg.run_pipeline(
        iter(lines),
        state=state,
        emit_every=20,  # forces multiple snapshots
        json_sink=json_sink,
        notify_sink=notify_sink,
    )
    notify_text = notify_sink.getvalue()
    # We expect at least one drift-band crossing notify line.
    assert (
        "DRIFT_AMBER_CROSSING" in notify_text
        or "DRIFT_RED_CROSSING" in notify_text
    )


# ---------------------------------------------------------------------------
# 9. final_state_dump
# ---------------------------------------------------------------------------


def test_final_state_dump_is_valid_json():
    state = agg.AggregatorState(window_size=100)
    for _ in range(3):
        state.ingest(_mk_event("welle-7", "production"))
    text = agg.final_state_dump(state, timestamp_unixtime=1747740000.0)
    obj = json.loads(text)
    assert obj["wellen"]["welle-7"]["sample_count"] == 3


# ---------------------------------------------------------------------------
# 10. Welle-inventory consistency with dashboard
# ---------------------------------------------------------------------------


def test_welle_inventory_matches_dashboard():
    """Aggregator's WELLE_NAMES must match the dashboard templating list.

    Drift between code and dashboard would mean an active Welle that
    the dashboard cannot filter on (operator-blind spot during
    Cutover-Tag-Morgen). The dashboard JSON is the source-of-truth
    for the templating-variable; we read it and compare.
    """
    dashboard_path = (
        _REPO_ROOT
        / "dashboards"
        / "phase-3c-cutover-day-live-stream.json"
    )
    obj = json.loads(dashboard_path.read_text(encoding="utf-8"))
    welle_template = next(
        t for t in obj["templating"]["list"] if t["name"] == "welle"
    )
    dashboard_wellen = [
        o["value"]
        for o in welle_template["options"]
        if o["value"] != "$__all"
    ]
    assert tuple(dashboard_wellen) == agg.WELLE_NAMES


# ---------------------------------------------------------------------------
# 11. Entrypoint (fixture mode)
# ---------------------------------------------------------------------------


def test_entrypoint_fixture_mode_runs_clean(tmp_path, capsys):
    fixture = tmp_path / "stream.jsonl"
    json_out = tmp_path / "out.jsonl"
    prom_out = tmp_path / "out.prom"
    lines = []
    for _ in range(20):
        lines.append(_event_line("welle-1", "production"))
        lines.append(_event_line("welle-2", "production"))
    fixture.write_text("".join(lines), encoding="utf-8")
    rc = agg.main(
        [
            "--mode",
            "fixture",
            "--fixture-stream",
            str(fixture),
            "--json-output",
            str(json_out),
            "--prometheus-output",
            str(prom_out),
            "--emit-every",
            "10",
            "--window-size",
            "300",
        ]
    )
    assert rc == 0
    assert json_out.exists()
    assert prom_out.exists()
    prom = prom_out.read_text(encoding="utf-8")
    assert "wakir_cutover_live_distribution" in prom
