#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for scripts/observability/aggregator-failure-rate-tracker.py.

Coverage targets the pure-function decision core. The I/O wrappers
(``fetch_aggregator_runs``, ``fetch_aggregator_runs_via_gh_cli``) are
not unit-tested here — integration coverage lives in the dry-run
fixture-mode entrypoint.

Anchor: ADR-0068 Tag-38 SRE Observability-Substrate.
Author: Noa Bergstroem (SRE)
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Loader: import the tracker module from its hyphenated path.
# ---------------------------------------------------------------------------
#
# The tracker file uses dashes in its name (project convention for
# scripts/) and is not a regular package. We load it via importlib so
# the tests don't need a symlink or a package-style re-export.

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_TRACKER_PATH = (
    _REPO_ROOT / "scripts" / "observability" / "aggregator-failure-rate-tracker.py"
)

_spec = importlib.util.spec_from_file_location(
    "aggregator_failure_rate_tracker", str(_TRACKER_PATH)
)
assert _spec is not None
assert _spec.loader is not None
tracker = importlib.util.module_from_spec(_spec)
# Register in sys.modules BEFORE exec_module so dataclasses' frozen=True
# can resolve cls.__module__ during _process_class. Python 3.14 made
# this stricter; 3.13 tolerated the absence. See CPython gh-128924.
sys.modules["aggregator_failure_rate_tracker"] = tracker
_spec.loader.exec_module(tracker)


# ---------------------------------------------------------------------------
# Fixtures: synthetic AggregatorRun lists.
# ---------------------------------------------------------------------------


def _mk_job(
    name: str, conclusion: str, duration_seconds: float = 30.0
) -> "tracker.JobOutcome":
    """Construct a JobOutcome with reasonable defaults."""
    return tracker.JobOutcome(
        name=name,
        conclusion=conclusion,
        duration_seconds=duration_seconds,
        started_at="2026-05-18T10:00:00Z",
        completed_at="2026-05-18T10:00:30Z",
    )


def _mk_run(
    run_id: int,
    head_sha: str,
    *,
    aggregator: str = "success",
    legacy: dict = None,
    durations: dict = None,
) -> "tracker.AggregatorRun":
    """Construct an AggregatorRun with the six legacy jobs + aggregator."""
    legacy = legacy or {n: "success" for n in tracker.LEGACY_REQUIRED_NAMES}
    durations = durations or {}
    jobs = []
    for name in tracker.LEGACY_REQUIRED_NAMES:
        jobs.append(
            _mk_job(
                name,
                legacy.get(name, "success"),
                duration_seconds=durations.get(name, 30.0),
            )
        )
    jobs.append(
        _mk_job(
            tracker.AGGREGATOR_CHECK_NAME,
            aggregator,
            duration_seconds=durations.get(tracker.AGGREGATOR_CHECK_NAME, 60.0),
        )
    )
    return tracker.AggregatorRun(
        run_id=run_id,
        head_sha=head_sha,
        conclusion=aggregator,
        created_at="2026-05-18T10:00:00Z",
        jobs=tuple(jobs),
    )


# ---------------------------------------------------------------------------
# Test 1: _percentile pure-function edge cases.
# ---------------------------------------------------------------------------


def test_percentile_handles_empty_sequence():
    """Empty input must not divide by zero or raise."""
    assert tracker._percentile([], 50) == 0.0
    assert tracker._percentile([], 95) == 0.0
    assert tracker._percentile([], 99) == 0.0


def test_percentile_single_sample():
    """One sample => that value at every percentile."""
    assert tracker._percentile([42.0], 50) == 42.0
    assert tracker._percentile([42.0], 99) == 42.0


def test_percentile_known_distribution():
    """Linear-interpolation percentile against a hand-computed distribution.

    Values 1..10, percentile 50 = 5.5 (midpoint between 5 and 6 at
    rank 4.5).
    """
    vals = [float(i) for i in range(1, 11)]
    p50 = tracker._percentile(vals, 50)
    assert abs(p50 - 5.5) < 1e-6
    p100 = tracker._percentile(vals, 100)
    assert p100 == 10.0
    p0 = tracker._percentile(vals, 0)
    assert p0 == 1.0


# ---------------------------------------------------------------------------
# Test 2: rollup_failure_rate with all-success runs.
# ---------------------------------------------------------------------------


def test_rollup_failure_rate_all_success():
    """All-success runs => failure_rate == 0.0 across every window."""
    runs = [_mk_run(i, f"sha{i}") for i in range(10)]
    rollups = tracker.rollup_failure_rate(
        runs,
        check_names=[tracker.AGGREGATOR_CHECK_NAME],
        window_sizes=(50, 100, 500),
    )
    assert len(rollups) == 1
    for win in (50, 100, 500):
        wr = rollups[0].by_window[win]
        assert wr.failure_count == 0
        assert wr.success_count == 10
        assert wr.failure_rate == 0.0


# ---------------------------------------------------------------------------
# Test 3: rollup_failure_rate with mixed runs.
# ---------------------------------------------------------------------------


def test_rollup_failure_rate_mixed_runs():
    """Mixed success+failure => failure_rate = failures / (failures + successes)."""
    # 3 failures, 7 successes => failure_rate = 0.3 over the entire window.
    runs = [
        _mk_run(i, f"sha{i}", aggregator="failure" if i < 3 else "success")
        for i in range(10)
    ]
    rollups = tracker.rollup_failure_rate(
        runs,
        check_names=[tracker.AGGREGATOR_CHECK_NAME],
        window_sizes=(50,),
    )
    wr = rollups[0].by_window[50]
    assert wr.failure_count == 3
    assert wr.success_count == 7
    assert abs(wr.failure_rate - 0.3) < 1e-9


# ---------------------------------------------------------------------------
# Test 4: rollup_failure_rate skipped excluded from denominator.
# ---------------------------------------------------------------------------


def test_rollup_failure_rate_skipped_excluded():
    """Skipped jobs do NOT inflate the denominator.

    Operator-question: ``when this sub-workflow DID run, how often did
    it fail`` — skipped means the path-filter did not trigger, the
    sub-workflow never ran. Including skipped in the denominator would
    artificially deflate the failure-rate when path-filters are narrow.
    """
    # 1 failure, 1 success, 8 skipped => failure_rate = 0.5 (1/(1+1)).
    runs = []
    for i in range(10):
        if i == 0:
            agg = "failure"
        elif i == 1:
            agg = "success"
        else:
            agg = "skipped"
        runs.append(_mk_run(i, f"sha{i}", aggregator=agg))
    rollups = tracker.rollup_failure_rate(
        runs,
        check_names=[tracker.AGGREGATOR_CHECK_NAME],
        window_sizes=(50,),
    )
    wr = rollups[0].by_window[50]
    assert wr.failure_count == 1
    assert wr.success_count == 1
    assert wr.skipped_count == 8
    assert abs(wr.failure_rate - 0.5) < 1e-9
    assert wr.sample_count == 10


# ---------------------------------------------------------------------------
# Test 5: sliding window cap honoured.
# ---------------------------------------------------------------------------


def test_rollup_window_size_caps_sample_count():
    """Window size larger than available samples => all samples included.

    Window size smaller than available samples => only the most-recent
    N are counted.
    """
    runs = [_mk_run(i, f"sha{i}") for i in range(120)]
    rollups = tracker.rollup_failure_rate(
        runs,
        check_names=[tracker.AGGREGATOR_CHECK_NAME],
        window_sizes=(50, 100, 500),
    )
    wr_50 = rollups[0].by_window[50]
    wr_100 = rollups[0].by_window[100]
    wr_500 = rollups[0].by_window[500]
    assert wr_50.sample_count == 50
    assert wr_100.sample_count == 100
    assert wr_500.sample_count == 120  # capped by available data


# ---------------------------------------------------------------------------
# Test 6: rollup latency reports correct percentiles.
# ---------------------------------------------------------------------------


def test_rollup_latency_percentiles():
    """Latency p50/p95/p99 should reflect the per-job duration distribution."""
    # Construct 10 runs where the aggregator job's duration is i*10
    # seconds for run i (10s, 20s, ..., 100s).
    runs = []
    for i in range(10):
        durations = {tracker.AGGREGATOR_CHECK_NAME: float((i + 1) * 10)}
        runs.append(_mk_run(i, f"sha{i}", durations=durations))
    rollups = tracker.rollup_failure_rate(
        runs,
        check_names=[tracker.AGGREGATOR_CHECK_NAME],
        window_sizes=(50,),
    )
    wr = rollups[0].by_window[50]
    # p50 of [10,20,...,100] = 55.0.
    assert abs(wr.latency_p50_seconds - 55.0) < 1e-6
    # p99 should be close to 100.
    assert wr.latency_p99_seconds > 95.0


# ---------------------------------------------------------------------------
# Test 7: compute_legacy_vs_aggregator_drift — clean window.
# ---------------------------------------------------------------------------


def test_drift_detection_clean_window():
    """All-success across all jobs => no drift events."""
    runs = [_mk_run(i, f"sha{i}", aggregator="success") for i in range(20)]
    events = tracker.compute_legacy_vs_aggregator_drift(runs)
    assert events == []


# ---------------------------------------------------------------------------
# Test 8: compute_legacy_vs_aggregator_drift — divergence detected.
# ---------------------------------------------------------------------------


def test_drift_detection_aggregator_disagrees_with_legacy():
    """Aggregator says success, legacy says failure => one drift event.

    This is the canonical false-negative case ADR-0068 §Migration-
    Step-2 blocks the cutover on.
    """
    legacy = {n: "success" for n in tracker.LEGACY_REQUIRED_NAMES}
    legacy[tracker.LEGACY_REQUIRED_NAMES[0]] = "failure"
    runs = [_mk_run(1, "sha1", aggregator="success", legacy=legacy)]
    events = tracker.compute_legacy_vs_aggregator_drift(runs)
    assert len(events) == 1
    ev = events[0]
    assert ev.run_id == 1
    assert ev.head_sha == "sha1"
    assert ev.aggregator_verdict == "success"
    assert ev.legacy_union_verdict == "failure"
    assert (
        ev.legacy_per_check[tracker.LEGACY_REQUIRED_NAMES[0]] == "failure"
    )


# ---------------------------------------------------------------------------
# Test 9: compute_legacy_vs_aggregator_drift — all-skipped legacy = success.
# ---------------------------------------------------------------------------


def test_drift_detection_all_legacy_skipped_no_drift():
    """All six legacy = skipped, aggregator = success => union also success.

    No drift expected: ``skipped`` is the legacy equivalent of the
    aggregator's ``skip-ok`` path. Both roll up to ``success``.
    """
    legacy = {n: "skipped" for n in tracker.LEGACY_REQUIRED_NAMES}
    runs = [_mk_run(1, "sha1", aggregator="success", legacy=legacy)]
    events = tracker.compute_legacy_vs_aggregator_drift(runs)
    assert events == []


# ---------------------------------------------------------------------------
# Test 10: render_prometheus_textfile schema.
# ---------------------------------------------------------------------------


def test_prometheus_textfile_emits_help_and_type_headers():
    """Prometheus textfile output must contain HELP + TYPE for each metric.

    Required by the Prometheus exposition format spec — scrape rejects
    metrics without TYPE.
    """
    runs = [_mk_run(i, f"sha{i}") for i in range(5)]
    rollups = tracker.rollup_failure_rate(
        runs, check_names=[tracker.AGGREGATOR_CHECK_NAME]
    )
    events = tracker.compute_legacy_vs_aggregator_drift(runs)
    text = tracker.render_prometheus_textfile(
        rollups, events, timestamp_unixtime=1747584000.0
    )
    assert "# HELP wakir_aggregator_failure_rate" in text
    assert "# TYPE wakir_aggregator_failure_rate gauge" in text
    assert "# HELP wakir_aggregator_latency_seconds" in text
    assert "# TYPE wakir_aggregator_latency_seconds gauge" in text
    assert "# HELP wakir_aggregator_drift_events" in text
    assert "# TYPE wakir_aggregator_drift_events gauge" in text
    # Drift gauge value must be 0 for a clean window.
    assert "wakir_aggregator_drift_events 0" in text


# ---------------------------------------------------------------------------
# Test 11: render_json_rollup schema.
# ---------------------------------------------------------------------------


def test_json_rollup_schema_versioned():
    """JSON rollup must carry schema_version + anchor for operator clarity."""
    runs = [_mk_run(i, f"sha{i}") for i in range(5)]
    rollups = tracker.rollup_failure_rate(
        runs, check_names=[tracker.AGGREGATOR_CHECK_NAME]
    )
    events = tracker.compute_legacy_vs_aggregator_drift(runs)
    json_text = tracker.render_json_rollup(rollups, events)
    payload = json.loads(json_text)
    assert payload["schema_version"] == 1
    assert "ADR-0068" in payload["anchor"]
    assert payload["summary"]["rollup_count"] == 1
    assert payload["summary"]["drift_event_count"] == 0
    assert len(payload["rollups"]) == 1
    assert payload["rollups"][0]["check_name"] == tracker.AGGREGATOR_CHECK_NAME


# ---------------------------------------------------------------------------
# Test 12: legacy required names match the aggregator inventory.
# ---------------------------------------------------------------------------


def test_legacy_required_names_match_aggregator_inventory():
    """The six legacy names in this tracker must match ci_aggregator.SUB_WORKFLOWS.

    Drift between this tracker's name list and the aggregator's
    inventory creates a class of false-drift events. The hermetic test
    pins the relationship.
    """
    # Lazy-import ci_aggregator so this test does not run if the
    # aggregator script is missing (defensive against incomplete
    # checkouts).
    ci_agg_path = _REPO_ROOT / "scripts" / "ci" / "ci_aggregator.py"
    if not ci_agg_path.exists():
        pytest.skip("ci_aggregator.py not present in checkout")
    spec = importlib.util.spec_from_file_location(
        "ci_aggregator_module", str(ci_agg_path)
    )
    assert spec is not None
    assert spec.loader is not None
    ci_agg = importlib.util.module_from_spec(spec)
    # See note above re. Python 3.14 dataclass sys.modules requirement.
    sys.modules["ci_aggregator_module"] = ci_agg
    spec.loader.exec_module(ci_agg)

    inventory_names = {sw.check_name for sw in ci_agg.SUB_WORKFLOWS}
    tracker_names = set(tracker.LEGACY_REQUIRED_NAMES)
    assert tracker_names == inventory_names, (
        f"Tracker legacy names diverge from aggregator inventory.\n"
        f"  tracker - aggregator: {tracker_names - inventory_names}\n"
        f"  aggregator - tracker: {inventory_names - tracker_names}"
    )


# ---------------------------------------------------------------------------
# Test 13: _legacy_union semantics.
# ---------------------------------------------------------------------------


def test_legacy_union_failure_dominates():
    """Any legacy failure => union failure."""
    per_check = {n: "success" for n in tracker.LEGACY_REQUIRED_NAMES}
    per_check[tracker.LEGACY_REQUIRED_NAMES[2]] = "failure"
    union = tracker._legacy_union(per_check, tracker.LEGACY_REQUIRED_NAMES)
    assert union == "failure"


def test_legacy_union_empty_means_missing():
    """No legacy verdicts at all => union missing.

    Surfaces the legacy-path-filter Forever-Pending case that ADR-0068
    structurally eliminates.
    """
    union = tracker._legacy_union({}, tracker.LEGACY_REQUIRED_NAMES)
    assert union == "missing"


def test_legacy_union_cancelled_is_failure():
    """``cancelled`` and ``timed_out`` legacy verdicts roll up to failure."""
    per_check = {n: "success" for n in tracker.LEGACY_REQUIRED_NAMES}
    per_check[tracker.LEGACY_REQUIRED_NAMES[1]] = "cancelled"
    union = tracker._legacy_union(per_check, tracker.LEGACY_REQUIRED_NAMES)
    assert union == "failure"
    per_check[tracker.LEGACY_REQUIRED_NAMES[1]] = "timed_out"
    union = tracker._legacy_union(per_check, tracker.LEGACY_REQUIRED_NAMES)
    assert union == "failure"


# ---------------------------------------------------------------------------
# Test 14: parse_run_payload tolerates partial fields.
# ---------------------------------------------------------------------------


def test_parse_run_payload_handles_missing_fields():
    """Missing timestamps => duration 0.0, no crash."""
    payload = {"id": 42, "head_sha": "abc", "conclusion": "success",
               "created_at": "2026-05-18T10:00:00Z"}
    jobs_payload = {"jobs": [{"name": "ci-aggregator", "conclusion": "success"}]}
    run = tracker.parse_run_payload(payload, jobs_payload)
    assert run.run_id == 42
    assert run.head_sha == "abc"
    assert len(run.jobs) == 1
    assert run.jobs[0].duration_seconds == 0.0


def test_parse_run_payload_computes_duration():
    """Valid ISO-8601 timestamps => correct duration_seconds."""
    payload = {"id": 1, "head_sha": "x", "conclusion": "success",
               "created_at": "2026-05-18T10:00:00Z"}
    jobs_payload = {
        "jobs": [
            {
                "name": "ci-aggregator",
                "conclusion": "success",
                "started_at": "2026-05-18T10:00:00Z",
                "completed_at": "2026-05-18T10:02:30Z",
            }
        ]
    }
    run = tracker.parse_run_payload(payload, jobs_payload)
    assert abs(run.jobs[0].duration_seconds - 150.0) < 1e-6


# ---------------------------------------------------------------------------
# Test 15: fixture-mode entrypoint end-to-end.
# ---------------------------------------------------------------------------


def test_entrypoint_fixture_mode_clean_exits_zero(tmp_path, monkeypatch, capsys):
    """End-to-end fixture-mode invocation must exit 0 on a clean window."""
    fixture = [
        {
            "payload": {
                "id": i,
                "head_sha": f"sha{i}",
                "conclusion": "success",
                "created_at": "2026-05-18T10:00:00Z",
            },
            "jobs_payload": {
                "jobs": [
                    {
                        "name": tracker.AGGREGATOR_CHECK_NAME,
                        "conclusion": "success",
                        "started_at": "2026-05-18T10:00:00Z",
                        "completed_at": "2026-05-18T10:01:00Z",
                    }
                ]
                + [
                    {
                        "name": n,
                        "conclusion": "success",
                        "started_at": "2026-05-18T10:00:00Z",
                        "completed_at": "2026-05-18T10:00:30Z",
                    }
                    for n in tracker.LEGACY_REQUIRED_NAMES
                ],
            },
        }
        for i in range(5)
    ]
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    json_out = tmp_path / "rollup.json"
    prom_out = tmp_path / "rollup.prom"

    rc = tracker.main(
        [
            "--mode=fixture",
            f"--fixture-runs={fixture_path}",
            f"--json-output={json_out}",
            f"--prometheus-output={prom_out}",
        ]
    )
    assert rc == 0
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["summary"]["drift_event_count"] == 0
    # Prometheus textfile must exist and contain the failure-rate metric.
    prom_text = prom_out.read_text(encoding="utf-8")
    assert "wakir_aggregator_failure_rate" in prom_text


def test_entrypoint_fixture_mode_drift_exits_nonzero(tmp_path):
    """End-to-end fixture-mode with one drift event => exit 1.

    Mira-Notify-blocking signal: cutover script must not run when this
    tracker exits non-zero (ADR-0068 §Migration-Step-3).
    """
    legacy_jobs = [
        {
            "name": n,
            "conclusion": "failure" if i == 0 else "success",
            "started_at": "2026-05-18T10:00:00Z",
            "completed_at": "2026-05-18T10:00:30Z",
        }
        for i, n in enumerate(tracker.LEGACY_REQUIRED_NAMES)
    ]
    fixture = [
        {
            "payload": {
                "id": 1,
                "head_sha": "sha1",
                "conclusion": "success",
                "created_at": "2026-05-18T10:00:00Z",
            },
            "jobs_payload": {
                "jobs": [
                    {
                        "name": tracker.AGGREGATOR_CHECK_NAME,
                        "conclusion": "success",
                        "started_at": "2026-05-18T10:00:00Z",
                        "completed_at": "2026-05-18T10:01:00Z",
                    }
                ]
                + legacy_jobs,
            },
        }
    ]
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    json_out = tmp_path / "rollup.json"
    rc = tracker.main(
        [
            "--mode=fixture",
            f"--fixture-runs={fixture_path}",
            f"--json-output={json_out}",
        ]
    )
    assert rc == 1
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["summary"]["drift_event_count"] == 1


# ---------------------------------------------------------------------------
# Test 16: escape_label handles spaces, parens, special chars.
# ---------------------------------------------------------------------------


def test_escape_label_preserves_spaces_and_parens():
    """Prometheus quoted-label-value supports spaces; only quotes/backslash escape."""
    out = tracker._escape_label('License-Hygiene Gate (ADR-0061)')
    assert out == 'License-Hygiene Gate (ADR-0061)'


def test_escape_label_escapes_quote_and_backslash():
    """Embedded ``"`` and ``\\`` must be backslash-escaped."""
    out = tracker._escape_label('weird"name\\here')
    assert out == 'weird\\"name\\\\here'


# ---------------------------------------------------------------------------
# Test 17 (Tag-42 regression): gh-cli command builder embeds query in path
# rather than as -f form fields. The original implementation passed
# ``-f per_page=100 -f page=N`` which forced ``gh`` into POST semantics
# and yielded HTTP 404 on Reza's Tag-41 probe-run. The fix embeds the
# query parameters in the URL path and sets ``-X GET`` explicitly.
# ---------------------------------------------------------------------------


def test_build_gh_cli_get_cmd_embeds_query_in_path():
    """Query params must be in the path, not as ``-f`` form fields.

    Regression test for the Tag-41 404 bug. Asserts:
      1. The command does NOT contain ``-f`` flags.
      2. The command DOES contain ``-X GET``.
      3. Query params are URL-encoded in the path argument.
      4. Sort-order of params is deterministic (alphabetical).
    """
    cmd = tracker._build_gh_cli_get_cmd(
        "/repos/wakir-labs/wakir-runtime/actions/workflows/ci-aggregator.yml/runs",
        query={"per_page": 100, "page": 3},
    )
    # No -f flags (the bug).
    assert "-f" not in cmd, f"Found regressed -f flag in: {cmd}"
    # -X GET present (the fix).
    assert "-X" in cmd and "GET" in cmd
    # Path argument contains the embedded query.
    path_arg = cmd[-1]
    assert "?" in path_arg
    assert "per_page=100" in path_arg
    assert "page=3" in path_arg
    # Deterministic sort order: page before per_page alphabetically.
    assert path_arg.index("page=3") < path_arg.index("per_page=100")


def test_build_gh_cli_get_cmd_no_query_yields_clean_path():
    """When no query is supplied, the path stays unmodified."""
    cmd = tracker._build_gh_cli_get_cmd(
        "/repos/wakir-labs/wakir-runtime/actions/runs/12345/jobs"
    )
    assert cmd[-1] == "/repos/wakir-labs/wakir-runtime/actions/runs/12345/jobs"
    assert "?" not in cmd[-1]
    assert "-X" in cmd and "GET" in cmd
