# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/routing-decision-observability.py — Tag-16 Mini-Welle.

Hermetic, stdlib-only: the aggregator module is loaded via importlib
from its hyphenated path under ``scripts/``. JSONL inputs are written
to ``tmp_path`` fixtures. No network, no real Prometheus collector.

Scope (12 tests)
----------------

1.  test_module_loads_and_exports_public_surface
2.  test_read_decision_records_tolerates_malformed_and_empty_lines
3.  test_read_decision_records_raises_on_missing_file
4.  test_select_window_returns_trailing_records
5.  test_select_window_clamps_nonpositive_to_default
6.  test_read_window_size_from_env_parses_valid_and_falls_back
7.  test_aggregate_decisions_counts_per_model_and_per_mode
8.  test_aggregate_decisions_latency_percentiles_per_mode
9.  test_aggregate_decisions_classifier_hit_rate
10. test_render_prometheus_emits_expected_metric_names
11. test_main_json_format_round_trip_via_cli
12. test_main_prometheus_dry_run_writes_to_stdout
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import List

import pytest


# ---------------------------------------------------------------------------
# Module loader (hyphenated filename → importlib.util)
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_PATH = REPO_ROOT / "scripts" / "routing-decision-observability.py"


def _load_aggregator_module():
    spec = importlib.util.spec_from_file_location(
        "routing_decision_observability", AGGREGATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


aggregator = _load_aggregator_module()


# ---------------------------------------------------------------------------
# Fixture: write a deterministic JSONL of routing decisions
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, records: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _decision(
    *,
    mode: str = "heuristic",
    chosen_model: str = "claude-sonnet-4-5-20250930",
    classified_class: str = "sonnet",
    decision_latency_us: int = 100,
    task_id: str = "T-0001",
    timestamp: str = "2026-05-17T08:00:00Z",
    used_fallback: bool = False,
    fallback_reason: str | None = None,
) -> dict:
    rec = {
        "timestamp": timestamp,
        "task_id": task_id,
        "mode": mode,
        "classified_class": classified_class,
        "chosen_model": chosen_model,
        "decision_latency_us": decision_latency_us,
    }
    if used_fallback:
        rec["used_fallback"] = True
        if fallback_reason is not None:
            rec["fallback_reason"] = fallback_reason
    return rec


# ---------------------------------------------------------------------------
# 1. Module surface — stable public API contract for sibling tooling
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface():
    """``__all__`` is the contract consumed by the systemd-timer wrapper
    and by the dashboard-render integration. Drift is breaking change.
    """
    expected = {
        "CLASSIFIER_MODES",
        "DEFAULT_TEXTFILE_OUTPUT",
        "DEFAULT_WINDOW_SIZE",
        "JsonlReadError",
        "KNOWN_ROUTING_MODES",
        "MODEL_UNKNOWN_BUCKET",
        "MODE_UNKNOWN_BUCKET",
        "ROUTING_MODE_HEURISTIC",
        "ROUTING_MODE_LLM_CLASSIFIER",
        "ROUTING_MODE_LLM_CLASSIFIER_FALLBACK_HEURISTIC",
        "ROUTING_MODE_STATIC",
        "WAKIR_ROUTING_DECISION_JSONL_ENV",
        "WAKIR_ROUTING_OBS_WINDOW_ENV",
        "aggregate_decisions",
        "atomic_write",
        "build_argparser",
        "main",
        "read_decision_records",
        "read_window_size_from_env",
        "render_prometheus",
        "resolve_jsonl_path",
        "resolve_window_size",
        "select_window",
    }
    assert set(aggregator.__all__) == expected
    for name in expected:
        assert hasattr(aggregator, name), f"missing public symbol: {name}"


# ---------------------------------------------------------------------------
# 2. JSONL parsing tolerance
# ---------------------------------------------------------------------------


def test_read_decision_records_tolerates_malformed_and_empty_lines(tmp_path: Path):
    """Blank lines, malformed JSON, and non-dict JSON values are silently
    skipped. We never raise on a single bad line — a corrupt tail must
    not break the metrics pipeline.
    """
    p = tmp_path / "routing.jsonl"
    p.write_text(
        "\n"  # blank
        + json.dumps({"mode": "static", "chosen_model": "m1", "decision_latency_us": 10}) + "\n"
        + "{not json}\n"  # malformed
        + json.dumps(["list-not-dict"]) + "\n"  # non-dict
        + "   \n"  # whitespace only
        + json.dumps({"mode": "heuristic", "chosen_model": "m2", "decision_latency_us": 20}) + "\n",
        encoding="utf-8",
    )
    out = aggregator.read_decision_records(p)
    assert len(out) == 2
    assert out[0]["chosen_model"] == "m1"
    assert out[1]["chosen_model"] == "m2"


# ---------------------------------------------------------------------------
# 3. JSONL parsing failure mode
# ---------------------------------------------------------------------------


def test_read_decision_records_raises_on_missing_file(tmp_path: Path):
    """A missing path raises :class:`JsonlReadError` so the CLI can map
    it to exit-code 1. The aggregator never silently treats a missing
    file as 'zero decisions' — that would mask an operator misconfig.
    """
    p = tmp_path / "nonexistent.jsonl"
    with pytest.raises(aggregator.JsonlReadError) as excinfo:
        aggregator.read_decision_records(p)
    assert "not a regular file" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 4. Sliding-window selection — tail semantics
# ---------------------------------------------------------------------------


def test_select_window_returns_trailing_records():
    records = [{"i": i} for i in range(10)]
    out = aggregator.select_window(records, 3)
    assert out == [{"i": 7}, {"i": 8}, {"i": 9}]
    # Window larger than the file → return all.
    out_all = aggregator.select_window(records, 1000)
    assert out_all == records
    # Window equal to length → return all.
    out_eq = aggregator.select_window(records, 10)
    assert out_eq == records


# ---------------------------------------------------------------------------
# 5. Sliding-window safety — non-positive window clamps to default
# ---------------------------------------------------------------------------


def test_select_window_clamps_nonpositive_to_default():
    """A zero or negative window-size cannot silently disable windowing.
    The function normalises to DEFAULT_WINDOW_SIZE so a misconfigured
    operator gets the documented default behaviour, not a runaway
    full-file aggregation.
    """
    records = [{"i": i} for i in range(aggregator.DEFAULT_WINDOW_SIZE + 50)]
    out_zero = aggregator.select_window(records, 0)
    assert len(out_zero) == aggregator.DEFAULT_WINDOW_SIZE
    out_neg = aggregator.select_window(records, -5)
    assert len(out_neg) == aggregator.DEFAULT_WINDOW_SIZE
    # And we keep the *trailing* records, not the leading ones.
    assert out_zero[-1] == {"i": aggregator.DEFAULT_WINDOW_SIZE + 50 - 1}


# ---------------------------------------------------------------------------
# 6. ENV parsing
# ---------------------------------------------------------------------------


def test_read_window_size_from_env_parses_valid_and_falls_back():
    """Valid positive ints are honoured. Anything else (unset, empty,
    non-int, zero, negative) falls back to DEFAULT_WINDOW_SIZE without
    raising.
    """
    assert aggregator.read_window_size_from_env({"WAKIR_ROUTING_OBS_WINDOW": "500"}) == 500
    assert aggregator.read_window_size_from_env({}) == aggregator.DEFAULT_WINDOW_SIZE
    assert (
        aggregator.read_window_size_from_env({"WAKIR_ROUTING_OBS_WINDOW": ""})
        == aggregator.DEFAULT_WINDOW_SIZE
    )
    assert (
        aggregator.read_window_size_from_env({"WAKIR_ROUTING_OBS_WINDOW": "not-an-int"})
        == aggregator.DEFAULT_WINDOW_SIZE
    )
    assert (
        aggregator.read_window_size_from_env({"WAKIR_ROUTING_OBS_WINDOW": "0"})
        == aggregator.DEFAULT_WINDOW_SIZE
    )
    assert (
        aggregator.read_window_size_from_env({"WAKIR_ROUTING_OBS_WINDOW": "-7"})
        == aggregator.DEFAULT_WINDOW_SIZE
    )


# ---------------------------------------------------------------------------
# 7. Aggregation — model + mode counts
# ---------------------------------------------------------------------------


def test_aggregate_decisions_counts_per_model_and_per_mode():
    recs = [
        _decision(mode="static", chosen_model="claude-haiku-4-5-20251015"),
        _decision(mode="static", chosen_model="claude-haiku-4-5-20251015"),
        _decision(mode="heuristic", chosen_model="claude-sonnet-4-5-20250930"),
        _decision(mode="llm_classifier", chosen_model="claude-opus-4-5-20251114"),
        _decision(mode="llm_classifier_fallback_heuristic", chosen_model=None),
        # Unknown mode → bucketed under mode_unknown sentinel.
        _decision(mode="garbage-mode", chosen_model="claude-haiku-4-5-20251015"),
    ]
    env = aggregator.aggregate_decisions(recs, window_size=100)
    assert env["sample_size"] == 6
    assert env["window_size"] == 100
    assert env["count_per_model"] == {
        "claude-haiku-4-5-20251015": 3,
        "claude-sonnet-4-5-20250930": 1,
        "claude-opus-4-5-20251114": 1,
        aggregator.MODEL_UNKNOWN_BUCKET: 1,
    }
    assert env["count_per_mode"] == {
        "static": 2,
        "heuristic": 1,
        "llm_classifier": 1,
        "llm_classifier_fallback_heuristic": 1,
        aggregator.MODE_UNKNOWN_BUCKET: 1,
    }


# ---------------------------------------------------------------------------
# 8. Aggregation — per-mode latency percentiles (nearest-rank)
# ---------------------------------------------------------------------------


def test_aggregate_decisions_latency_percentiles_per_mode():
    """Nearest-rank percentile on a controlled sample produces stable
    integer values that correspond to real observed latencies, not
    interpolated phantoms.

    For sorted [10, 20, 30, ..., 100] (10 items):
      - p50 -> ceil(0.5*10)=5 -> values[4] = 50
      - p95 -> ceil(0.95*10)=10 -> values[9] = 100
      - p99 -> ceil(0.99*10)=10 -> values[9] = 100
    """
    recs = [
        _decision(mode="heuristic", decision_latency_us=v)
        for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    ]
    env = aggregator.aggregate_decisions(recs, window_size=100)
    h = env["latency_per_mode"]["heuristic"]
    assert h["count"] == 10
    assert h["p50"] == 50
    assert h["p95"] == 100
    assert h["p99"] == 100
    # avg_decision_latency_us mean of 10..100 = 55
    assert env["avg_decision_latency_us"] == pytest.approx(55.0)


# ---------------------------------------------------------------------------
# 9. Classifier-hit-rate semantics
# ---------------------------------------------------------------------------


def test_aggregate_decisions_classifier_hit_rate():
    """Hit-rate is 1 - fallbacks/attempts within classifier-mode scope.

    Static and heuristic modes are excluded from numerator and
    denominator: an operator running pure-static traffic gets a
    0.0 hit-rate with 0 attempts, not a misleading 1.0.
    """
    # Scenario: 6 classifier-mode decisions, 2 of which fell back.
    # Plus 3 static-mode decisions that must NOT enter the rate.
    recs = (
        [_decision(mode="static") for _ in range(3)]
        + [_decision(mode="llm_classifier") for _ in range(4)]
        + [
            _decision(
                mode="llm_classifier_fallback_heuristic",
                used_fallback=True,
                fallback_reason="classifier-exception:RuntimeError",
            )
            for _ in range(2)
        ]
    )
    env = aggregator.aggregate_decisions(recs, window_size=100)
    assert env["classifier_attempts"] == 6
    assert env["classifier_fallbacks"] == 2
    # 1 - 2/6 = 0.6666...
    assert env["classifier_hit_rate"] == pytest.approx(1.0 - 2 / 6)

    # No traffic → 0.0 (not 1.0; explicit zero-attempt rule).
    env_empty = aggregator.aggregate_decisions([], window_size=100)
    assert env_empty["classifier_attempts"] == 0
    assert env_empty["classifier_fallbacks"] == 0
    assert env_empty["classifier_hit_rate"] == 0.0


# ---------------------------------------------------------------------------
# 10. Prometheus exposition surface
# ---------------------------------------------------------------------------


def test_render_prometheus_emits_expected_metric_names():
    """Every metric name on the dashboard side must appear in the output
    with a matching ``# HELP`` and ``# TYPE`` comment. Drift between
    the script's output schema and the dashboard's PromQL is what we
    are guarding against here.
    """
    recs = [
        _decision(mode="heuristic", chosen_model="claude-sonnet-4-5-20250930", decision_latency_us=10),
        _decision(mode="heuristic", chosen_model="claude-sonnet-4-5-20250930", decision_latency_us=20),
        _decision(mode="llm_classifier", chosen_model="claude-opus-4-5-20251114", decision_latency_us=30),
        _decision(
            mode="llm_classifier_fallback_heuristic",
            chosen_model="claude-haiku-4-5-20251015",
            decision_latency_us=40,
            used_fallback=True,
            fallback_reason="classifier-exception:TimeoutError",
        ),
    ]
    env = aggregator.aggregate_decisions(recs, window_size=100)
    text = aggregator.render_prometheus(env, scrape_ts_utc=1747008000)

    expected_metrics = [
        "persona_engine_routing_decisions_sample_size",
        "persona_engine_routing_decisions_window_size",
        "persona_engine_routing_decisions_per_model",
        "persona_engine_routing_decisions_per_mode",
        "persona_engine_routing_decision_latency_us_avg",
        "persona_engine_routing_decision_latency_us",
        "persona_engine_routing_decision_count_per_mode",
        "persona_engine_routing_classifier_attempts_total",
        "persona_engine_routing_classifier_fallbacks_total",
        "persona_engine_routing_classifier_hit_rate",
        "persona_engine_routing_scrape_timestamp_seconds",
    ]
    for m in expected_metrics:
        assert f"# HELP {m} " in text, f"missing HELP for {m}"
        assert f"# TYPE {m} " in text, f"missing TYPE for {m}"

    # Schema cross-checks on a couple of labelled lines.
    assert (
        'persona_engine_routing_decisions_per_model{model="claude-sonnet-4-5-20250930"} 2'
        in text
    )
    assert 'persona_engine_routing_decisions_per_mode{mode="heuristic"} 2' in text
    assert (
        'persona_engine_routing_decision_latency_us{mode="heuristic",quantile="0.5"}'
        in text
    )
    # 1 attempt + 1 fallback = hit_rate 0.0
    # Wait: 2 classifier attempts (llm_classifier=1 + llm_classifier_fallback_heuristic=1),
    # 1 fallback -> rate 0.5
    assert "persona_engine_routing_classifier_attempts_total 2" in text
    assert "persona_engine_routing_classifier_fallbacks_total 1" in text
    assert "persona_engine_routing_classifier_hit_rate 0.5" in text
    # Scrape timestamp echoed back.
    assert "persona_engine_routing_scrape_timestamp_seconds 1747008000" in text


# ---------------------------------------------------------------------------
# 11. CLI: --format=json round trip
# ---------------------------------------------------------------------------


def test_main_json_format_round_trip_via_cli(tmp_path: Path):
    """Running the CLI with --format=json on a small JSONL fixture
    produces parseable JSON whose envelope matches a direct call to
    ``aggregate_decisions``. This pins the operator-facing default
    path end-to-end.
    """
    jsonl = tmp_path / "routing.jsonl"
    _write_jsonl(
        jsonl,
        [
            _decision(mode="static", chosen_model="claude-haiku-4-5-20251015", decision_latency_us=5),
            _decision(mode="heuristic", chosen_model="claude-sonnet-4-5-20250930", decision_latency_us=15),
            _decision(
                mode="llm_classifier",
                chosen_model="claude-opus-4-5-20251114",
                decision_latency_us=25,
            ),
        ],
    )
    buf_out = io.StringIO()
    buf_err = io.StringIO()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        rc = aggregator.main(
            [
                "--jsonl-path",
                str(jsonl),
                "--window-size",
                "100",
                "--format",
                "json",
            ],
            env={},
        )
    assert rc == 0, f"stderr: {buf_err.getvalue()}"
    parsed = json.loads(buf_out.getvalue())
    assert parsed["sample_size"] == 3
    assert parsed["window_size"] == 100
    assert parsed["count_per_mode"] == {
        "static": 1,
        "heuristic": 1,
        "llm_classifier": 1,
    }
    assert parsed["classifier_attempts"] == 1
    assert parsed["classifier_fallbacks"] == 0
    assert parsed["classifier_hit_rate"] == 1.0


# ---------------------------------------------------------------------------
# 12. CLI: --format=prometheus --dry-run
# ---------------------------------------------------------------------------


def test_main_prometheus_dry_run_writes_to_stdout(tmp_path: Path):
    """In dry-run mode the Prometheus payload goes to stdout instead of
    the textfile path. Hermetic CI cannot write into
    /var/lib/node_exporter — dry-run is how operators preview a
    scrape before flipping the systemd timer on.
    """
    jsonl = tmp_path / "routing.jsonl"
    _write_jsonl(
        jsonl,
        [_decision(mode="heuristic", decision_latency_us=42)],
    )
    buf_out = io.StringIO()
    buf_err = io.StringIO()
    with redirect_stdout(buf_out), redirect_stderr(buf_err):
        rc = aggregator.main(
            [
                "--jsonl-path",
                str(jsonl),
                "--format",
                "prometheus",
                "--dry-run",
                "--now",
                "1747000000",
            ],
            env={},
        )
    assert rc == 0, f"stderr: {buf_err.getvalue()}"
    payload = buf_out.getvalue()
    assert "persona_engine_routing_decisions_sample_size 1" in payload
    assert "persona_engine_routing_scrape_timestamp_seconds 1747000000" in payload
    # Dry-run path must not have routed to a real textfile write at all
    # (the textfile path is never opened in this code branch). The
    # contract assertion above (stdout payload non-empty + sample_size
    # encoded) is the strong invariant; we additionally ensure stderr
    # is empty so any future filesystem-touch regression surfaces here.
    assert buf_err.getvalue() == ""
