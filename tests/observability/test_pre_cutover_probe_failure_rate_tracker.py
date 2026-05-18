#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for scripts/observability/pre-cutover-probe-failure-rate-tracker.py.

Coverage targets the pure-function rollup core. I/O wrappers
(``walk_probe_reports``, ``load_henrik_signoffs_from_file``) are
covered via tmp_path fixtures.

Anchor: Tag-42 Noa-SRE Pre-Cutover-Probe-Observability.
Author: Noa Bergstroem (SRE)
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Loader: import the tracker module from its hyphenated path.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_TRACKER_PATH = (
    _REPO_ROOT
    / "scripts"
    / "observability"
    / "pre-cutover-probe-failure-rate-tracker.py"
)

_spec = importlib.util.spec_from_file_location(
    "pre_cutover_probe_failure_rate_tracker", str(_TRACKER_PATH)
)
assert _spec is not None
assert _spec.loader is not None
tracker = importlib.util.module_from_spec(_spec)
sys.modules["pre_cutover_probe_failure_rate_tracker"] = tracker
_spec.loader.exec_module(tracker)


# ---------------------------------------------------------------------------
# Helper builders.
# ---------------------------------------------------------------------------


def _mk_probe(
    welle: str,
    verdict: str,
    *,
    ts: float = 1718000000.0,
    operator: str = "test-operator",
    detail: str = "",
) -> "tracker.ProbeRun":
    return tracker.ProbeRun(
        welle=welle,
        timestamp_unixtime=ts,
        verdict=verdict,
        operator=operator,
        detail=detail,
    )


def _mk_signoff(
    welle: str,
    *,
    signed: bool = True,
    ts: float = 1718000000.0,
) -> "tracker.HenrikSignOff":
    return tracker.HenrikSignOff(
        welle=welle,
        signed_off=signed,
        timestamp_unixtime=ts if signed else None,
        detail="hermetic-test",
    )


# ---------------------------------------------------------------------------
# Test 1: WELLE_SLUGS invariant — seven Welle in cutover-order.
# ---------------------------------------------------------------------------


def test_welle_slugs_invariant():
    """Welle slugs must be welle-1..welle-7 in that order."""
    assert tracker.WELLE_SLUGS == (
        "welle-1",
        "welle-2",
        "welle-3",
        "welle-4",
        "welle-5",
        "welle-6",
        "welle-7",
    )


# ---------------------------------------------------------------------------
# Test 2: ALLOWED_VERDICTS invariant — the five canonical verdicts.
# ---------------------------------------------------------------------------


def test_allowed_verdicts_invariant():
    """ALLOWED_VERDICTS must be the five canonical values + nothing else."""
    assert set(tracker.ALLOWED_VERDICTS) == {
        "GREEN",
        "CAUTION",
        "BLOCK",
        "NOT-EXEC",
        "PENDING",
    }
    # Every allowed verdict must have a numeric mapping.
    for v in tracker.ALLOWED_VERDICTS:
        assert v in tracker.VERDICT_TO_NUMERIC


# ---------------------------------------------------------------------------
# Test 3: rollup_per_welle yields one rollup per Welle, in order, even
# when zero probes were recorded for some Wellen.
# ---------------------------------------------------------------------------


def test_rollup_per_welle_empty_input_returns_pending_per_welle():
    """With no probes + no Henrik-Signoffs, every Welle gets PENDING."""
    rollups = tracker.rollup_per_welle([], [])
    assert len(rollups) == 7
    assert [r.welle for r in rollups] == list(tracker.WELLE_SLUGS)
    for r in rollups:
        assert r.current_verdict == "PENDING"
        assert r.history == []
        assert r.henrik_signed_off is False
        # PENDING wellen have no coupling-blockers from their deps,
        # because deps are likewise PENDING+unsigned; check the matrix.
        # welle-1..-4 have no deps -> always met.
        # welle-5..-7 have deps; with empty inputs they are blocked.
        if r.welle in ("welle-5", "welle-6", "welle-7"):
            assert r.coupling_pre_conditions_met is False
            assert r.coupling_blockers, f"{r.welle} should list blockers"
        else:
            assert r.coupling_pre_conditions_met is True


# ---------------------------------------------------------------------------
# Test 4: rollup_per_welle picks the most-recent probe as current_verdict.
# ---------------------------------------------------------------------------


def test_rollup_per_welle_picks_most_recent_verdict():
    """When multiple probe-runs exist, current_verdict == most-recent."""
    probes = [
        _mk_probe("welle-1", "GREEN", ts=1718000000.0),
        _mk_probe("welle-1", "CAUTION", ts=1718100000.0),  # most recent
        _mk_probe("welle-1", "BLOCK", ts=1717000000.0),
    ]
    rollups = tracker.rollup_per_welle(probes, [])
    w1 = next(r for r in rollups if r.welle == "welle-1")
    assert w1.current_verdict == "CAUTION"
    # History must be most-recent-first.
    assert [p.verdict for p in w1.history] == ["CAUTION", "GREEN", "BLOCK"]


# ---------------------------------------------------------------------------
# Test 5: stability_consecutive_green counts from most-recent backward.
# ---------------------------------------------------------------------------


def test_stability_consecutive_green_counts_correctly():
    """Three GREEN-in-a-row from most-recent => count == 3."""
    probes = [
        _mk_probe("welle-1", "GREEN", ts=1718300000.0),  # most recent
        _mk_probe("welle-1", "GREEN", ts=1718200000.0),
        _mk_probe("welle-1", "GREEN", ts=1718100000.0),
        _mk_probe("welle-1", "CAUTION", ts=1718000000.0),
        _mk_probe("welle-1", "GREEN", ts=1717000000.0),
    ]
    rollups = tracker.rollup_per_welle(probes, [])
    w1 = next(r for r in rollups if r.welle == "welle-1")
    # 3 GREEN at the top -> 3. The CAUTION below halts the run.
    assert w1.stability_consecutive_green == 3

    # Edge: a CAUTION at the very top breaks the streak entirely.
    probes2 = [
        _mk_probe("welle-1", "CAUTION", ts=1718300000.0),
        _mk_probe("welle-1", "GREEN", ts=1718200000.0),
    ]
    rollups2 = tracker.rollup_per_welle(probes2, [])
    w1_2 = next(r for r in rollups2 if r.welle == "welle-1")
    assert w1_2.stability_consecutive_green == 0


# ---------------------------------------------------------------------------
# Test 6: Coupling pre-conditions — Welle-7 needs Welle-3 sign-off AND
# Welle-4 Cutover-Done.
# ---------------------------------------------------------------------------


def test_coupling_pre_conditions_welle_7_unblocked_only_when_deps_met():
    """Welle-7 blocked until Welle-3 signed AND Welle-4 GREEN+signed."""
    # Case A: deps unmet -> blocked.
    probes_a = [_mk_probe("welle-7", "GREEN", ts=1718000000.0)]
    rollups_a = tracker.rollup_per_welle(probes_a, [])
    w7_a = next(r for r in rollups_a if r.welle == "welle-7")
    assert w7_a.coupling_pre_conditions_met is False
    assert any("welle-3" in b for b in w7_a.coupling_blockers)
    assert any("welle-4" in b for b in w7_a.coupling_blockers)

    # Case B: deps met -> unblocked.
    probes_b = [
        _mk_probe("welle-3", "GREEN", ts=1718000000.0),
        _mk_probe("welle-4", "GREEN", ts=1718000000.0),
        _mk_probe("welle-7", "GREEN", ts=1718000000.0),
    ]
    signoffs_b = [
        _mk_signoff("welle-3"),
        _mk_signoff("welle-4"),
    ]
    rollups_b = tracker.rollup_per_welle(probes_b, signoffs_b)
    w7_b = next(r for r in rollups_b if r.welle == "welle-7")
    assert w7_b.coupling_pre_conditions_met is True
    assert w7_b.coupling_blockers == []


# ---------------------------------------------------------------------------
# Test 7: compute_marathon_readiness_score — 7x GREEN + 7x Henrik = 100%.
# ---------------------------------------------------------------------------


def test_marathon_readiness_score_full_house_is_100_percent():
    """All 7 GREEN + all 7 Henrik-signed => 100% (capped)."""
    probes = [
        _mk_probe(w, "GREEN", ts=1718000000.0) for w in tracker.WELLE_SLUGS
    ]
    signoffs = [_mk_signoff(w) for w in tracker.WELLE_SLUGS]
    rollups = tracker.rollup_per_welle(probes, signoffs)
    score = tracker.compute_marathon_readiness_score(rollups)
    assert score == pytest.approx(100.0, abs=0.01)


def test_marathon_readiness_score_pending_is_zero():
    """No probes at all => score 0.0."""
    rollups = tracker.rollup_per_welle([], [])
    score = tracker.compute_marathon_readiness_score(rollups)
    assert score == 0.0


def test_marathon_readiness_score_block_zero_henrik_partial():
    """A BLOCK Welle contributes 0; Henrik-signed adds 5pp."""
    probes = [_mk_probe("welle-1", "BLOCK", ts=1718000000.0)]
    signoffs = [_mk_signoff("welle-1")]
    rollups = tracker.rollup_per_welle(probes, signoffs)
    score = tracker.compute_marathon_readiness_score(rollups)
    # BLOCK -> 0pp verdict; Henrik-signed -> 5pp.
    assert score == pytest.approx(5.0, abs=0.01)


def test_marathon_readiness_score_caution_is_half():
    """A CAUTION Welle contributes half a GREEN."""
    probes = [_mk_probe("welle-1", "CAUTION", ts=1718000000.0)]
    rollups = tracker.rollup_per_welle(probes, [])
    score = tracker.compute_marathon_readiness_score(rollups)
    # 14.28 * 0.5 = 7.14.
    assert score == pytest.approx(7.142857, abs=0.01)


# ---------------------------------------------------------------------------
# Test 8: render_prometheus_textfile — schema invariants.
# ---------------------------------------------------------------------------


def test_render_prometheus_textfile_emits_expected_metrics():
    """The textfile must contain every required metric name + per-Welle rows."""
    probes = [_mk_probe("welle-1", "GREEN", ts=1718000000.0)]
    rollups = tracker.rollup_per_welle(probes, [])
    score = tracker.compute_marathon_readiness_score(rollups)
    text = tracker.render_prometheus_textfile(
        rollups, marathon_score=score, timestamp_unixtime=1718000000.0
    )
    # Top-level metric names.
    for metric in (
        "wakir_pre_cutover_probe_verdict",
        "wakir_pre_cutover_probe_history_count",
        "wakir_pre_cutover_probe_stability_consecutive_green",
        "wakir_pre_cutover_henrik_signoff",
        "wakir_pre_cutover_coupling_pre_conditions_met",
        "wakir_marathon_readiness_score",
    ):
        assert metric in text, f"Missing {metric}"
        # HELP + TYPE for every metric.
        assert f"# HELP {metric}" in text
        assert f"# TYPE {metric} gauge" in text
    # One verdict line per Welle.
    for slug in tracker.WELLE_SLUGS:
        assert (
            f'wakir_pre_cutover_probe_verdict{{welle="{slug}"}}' in text
        ), f"Missing verdict line for {slug}"


# ---------------------------------------------------------------------------
# Test 9: render_json_rollup is valid JSON and contains all Wellen.
# ---------------------------------------------------------------------------


def test_render_json_rollup_is_valid_json_with_all_wellen():
    """JSON output must parse and contain seven Welle entries."""
    rollups = tracker.rollup_per_welle([], [])
    text = tracker.render_json_rollup(
        rollups, marathon_score=0.0, timestamp_unixtime=1718000000.0
    )
    obj = json.loads(text)
    assert obj["schema_version"] == 1
    assert obj["marathon_readiness_score"] == 0.0
    assert len(obj["wellen"]) == 7
    welle_slugs = [w["welle"] for w in obj["wellen"]]
    assert welle_slugs == list(tracker.WELLE_SLUGS)
    # Cutover-window populated per ADR-0066.
    for w in obj["wellen"]:
        assert "cutover_window" in w
        assert "week" in w["cutover_window"]
        assert "date" in w["cutover_window"]


# ---------------------------------------------------------------------------
# Test 10: parse_probe_report extracts verdict from canonical report text.
# ---------------------------------------------------------------------------


def test_parse_probe_report_extracts_verdict_from_welle_1_format():
    """Parse the Welle-1 probe-report format Reza-Tag-41 emits."""
    text = """# Welle-1 v907_verify Pre-Cutover-Probe (Tag-41)

Operator: Reza Hassani
Summary: All five axes matched; ready for KW-24 cutover.

| AXIS | VERDICT | DETAIL |
|---|---|---|
| 1 | GREEN | python+rust verify parity |
| 2 | GREEN | golden-corpus delta zero |
| 3 | GREEN | bridge-audit replay clean |
| 4 | GREEN | SVID resolver path |
| 5 | GREEN | aggregator clean |
| AGGREGATE | GREEN | all-axes match |
"""
    run = tracker.parse_probe_report(
        text, filename="2026-05-18-welle-1-pre-cutover-probe.md"
    )
    assert run is not None
    assert run.welle == "welle-1"
    assert run.verdict == "GREEN"
    assert run.operator == "Reza Hassani"
    assert "all five axes" in run.detail.lower()


def test_parse_probe_report_returns_none_for_stub_without_verdict():
    """A stub report without AGGREGATE line returns None."""
    text = "# Welle-2 stub\n\nNot yet run.\n"
    run = tracker.parse_probe_report(
        text, filename="2026-05-18-welle-2-pre-cutover-probe.md"
    )
    assert run is None


def test_parse_probe_report_handles_block_verdict():
    """BLOCK verdict is parsed and preserved."""
    text = "AGGREGATE: BLOCK\nOperator: Selin\n"
    run = tracker.parse_probe_report(
        text, filename="2026-05-18-welle-3-pre-cutover-probe.md"
    )
    assert run is not None
    assert run.verdict == "BLOCK"
    assert run.operator == "Selin"


# ---------------------------------------------------------------------------
# Test 11: walk_probe_reports + fixture-mode I/O round-trip.
# ---------------------------------------------------------------------------


def test_walk_probe_reports_picks_up_matching_files(tmp_path):
    """walk_probe_reports finds and parses pre-cutover-probe.md files."""
    d = tmp_path / "reports" / "live-vm"
    d.mkdir(parents=True)
    (d / "2026-05-18-welle-1-pre-cutover-probe.md").write_text(
        "AGGREGATE: GREEN\nOperator: Reza\n", encoding="utf-8"
    )
    (d / "2026-05-19-welle-2-pre-cutover-probe.md").write_text(
        "AGGREGATE: CAUTION\nOperator: Selin\n", encoding="utf-8"
    )
    # A non-matching file is ignored.
    (d / "README.md").write_text("ignore me\n", encoding="utf-8")
    runs = tracker.walk_probe_reports(d)
    welles = {r.welle for r in runs}
    assert welles == {"welle-1", "welle-2"}


def test_walk_probe_reports_returns_empty_on_missing_dir(tmp_path):
    """A missing reports directory yields an empty list, not an exception."""
    runs = tracker.walk_probe_reports(tmp_path / "does-not-exist")
    assert runs == []


# ---------------------------------------------------------------------------
# Test 12: load_fixture_probes round-trip.
# ---------------------------------------------------------------------------


def test_load_fixture_probes_round_trip(tmp_path):
    """Fixture-mode JSON loads both probes and Henrik-Signoffs."""
    fixture = {
        "probes": [
            {
                "welle": "welle-1",
                "timestamp_unixtime": 1718000000.0,
                "verdict": "GREEN",
                "operator": "Reza",
                "detail": "all five green",
            }
        ],
        "henrik_signoffs": [
            {
                "welle": "welle-1",
                "signed_off": True,
                "timestamp_unixtime": 1718010000.0,
                "detail": "Henrik approved Welle-1",
            }
        ],
    }
    p = tmp_path / "fixture.json"
    p.write_text(json.dumps(fixture), encoding="utf-8")
    probes, signoffs = tracker.load_fixture_probes(p)
    assert len(probes) == 1
    assert probes[0].welle == "welle-1"
    assert probes[0].verdict == "GREEN"
    assert len(signoffs) == 1
    assert signoffs[0].signed_off is True


# ---------------------------------------------------------------------------
# Test 13: main entrypoint in fixture-mode writes JSON + Prometheus + Markdown.
# ---------------------------------------------------------------------------


def test_main_fixture_mode_writes_all_outputs(tmp_path):
    """End-to-end run in --mode=fixture writes JSON + Prom + Markdown."""
    fixture = {
        "probes": [
            {
                "welle": w,
                "timestamp_unixtime": 1718000000.0,
                "verdict": "GREEN",
                "operator": "test",
                "detail": "",
            }
            for w in tracker.WELLE_SLUGS
        ],
        "henrik_signoffs": [
            {
                "welle": w,
                "signed_off": True,
                "timestamp_unixtime": 1718000000.0,
                "detail": "",
            }
            for w in tracker.WELLE_SLUGS
        ],
    }
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    json_out = tmp_path / "rollup.json"
    prom_out = tmp_path / "rollup.prom"
    md_out = tmp_path / "rollup.md"
    rc = tracker.main(
        [
            "--mode=fixture",
            f"--fixture-probes={fixture_path}",
            f"--json-output={json_out}",
            f"--prometheus-output={prom_out}",
            f"--markdown-output={md_out}",
        ]
    )
    assert rc == 0
    # JSON.
    rollup = json.loads(json_out.read_text(encoding="utf-8"))
    assert rollup["marathon_readiness_score"] == pytest.approx(100.0, abs=0.01)
    # Prom.
    prom_text = prom_out.read_text(encoding="utf-8")
    assert "wakir_marathon_readiness_score 100.00" in prom_text
    # Markdown.
    md_text = md_out.read_text(encoding="utf-8")
    assert "Marathon-Readiness-Score: 100.0%" in md_text
    assert "welle-1" in md_text and "welle-7" in md_text


def test_main_fixture_mode_fail_on_block_exits_one(tmp_path):
    """--fail-on-block returns rc=1 when any Welle is BLOCK."""
    fixture = {
        "probes": [
            {
                "welle": "welle-1",
                "timestamp_unixtime": 1718000000.0,
                "verdict": "BLOCK",
                "operator": "test",
                "detail": "",
            }
        ],
        "henrik_signoffs": [],
    }
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    json_out = tmp_path / "rollup.json"
    rc = tracker.main(
        [
            "--mode=fixture",
            f"--fixture-probes={fixture_path}",
            f"--json-output={json_out}",
            "--fail-on-block",
        ]
    )
    assert rc == 1


# ---------------------------------------------------------------------------
# Test 14: CUTOVER_DAY_WINDOWS contains all seven Wellen with required keys.
# ---------------------------------------------------------------------------


def test_cutover_day_windows_complete_and_well_formed():
    """Every Welle slug has a window entry with week+date+slot."""
    assert set(tracker.CUTOVER_DAY_WINDOWS.keys()) == set(tracker.WELLE_SLUGS)
    for slug, win in tracker.CUTOVER_DAY_WINDOWS.items():
        assert "week" in win and win["week"].startswith("KW-")
        assert "date" in win and win["date"].startswith("2026-")
        assert "slot" in win and "CEST" in win["slot"]
