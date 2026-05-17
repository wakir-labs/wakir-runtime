# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/backend-decision-observability.py — Tag-22 Mini-Welle.

Hermetic, stdlib-only: the aggregator module is loaded via importlib
from its hyphenated path under ``scripts/``. JSONL inputs are written
to ``tmp_path`` fixtures. No network, no real Prometheus collector.

Scope (12 tests)
----------------

1.  test_module_loads_and_exports_public_surface
2.  test_read_decision_records_tolerates_malformed_and_filters_non_decision_msg
3.  test_read_decision_records_raises_on_missing_file
4.  test_select_window_returns_trailing_records_and_clamps_nonpositive
5.  test_read_window_size_from_env_parses_valid_and_falls_back
6.  test_aggregate_decisions_counts_per_component_backend
7.  test_aggregate_decisions_latency_percentiles_per_component
8.  test_aggregate_decisions_fallback_rates_per_component_and_aggregated
9.  test_aggregate_decisions_handles_unknown_component_and_backend
10. test_render_prometheus_emits_expected_metric_names_and_labels
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
from typing import List, Optional

import pytest


# ---------------------------------------------------------------------------
# Module loader (hyphenated filename -> importlib.util)
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_PATH = REPO_ROOT / "scripts" / "backend-decision-observability.py"


def _load_aggregator_module():
    spec = importlib.util.spec_from_file_location(
        "backend_decision_observability", AGGREGATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


aggregator = _load_aggregator_module()


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, records: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _decision(
    *,
    domain: str = "recovery",
    chosen_backend: str = "python",
    resolution_latency_us: int = 100,
    requested_backend: str = "python",
    fallback_reason: Optional[str] = None,
    bin_path: Optional[str] = None,
    include_envelope: bool = True,
) -> dict:
    """Build a BackendDecision JSONL record.

    With ``include_envelope=True`` the record carries the engine
    ``msg`` envelope (production shape). With ``False`` it omits the
    envelope (test-fixture direct-emit shape) — the aggregator
    accepts both per the liberal-reader principle.
    """
    rec: dict = {
        "domain": domain,
        "requested_backend": requested_backend,
        "chosen_backend": chosen_backend,
        "resolution_latency_us": resolution_latency_us,
        "fallback_reason": fallback_reason,
        "bin_path": bin_path,
    }
    if include_envelope:
        rec["level"] = "INFO"
        rec["msg"] = "backend-decision"
    return rec


# ---------------------------------------------------------------------------
# 1. Module surface — stable public API contract
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface():
    """``__all__`` is the contract consumed by the systemd-timer wrapper
    and by the dashboard-render integration. Drift is a breaking change.
    """
    expected = {
        "BACKEND_DECISION_MSG",
        "BACKEND_UNKNOWN_BUCKET",
        "COMPONENT_BRIDGE_DIFF",
        "COMPONENT_FSM",
        "COMPONENT_RECOVERY",
        "COMPONENT_STATE_BACKING",
        "COMPONENT_UNKNOWN_BUCKET",
        "COMPONENT_V907_VERIFY",
        "DEFAULT_TEXTFILE_OUTPUT",
        "DEFAULT_WINDOW_SIZE",
        "JsonlReadError",
        "KNOWN_COMPONENTS",
        "WAKIR_BACKEND_DECISION_JSONL_ENV",
        "WAKIR_BACKEND_DECISION_OBS_WINDOW_ENV",
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
    # And the well-known constants resolve to the documented values.
    assert aggregator.BACKEND_DECISION_MSG == "backend-decision"
    assert aggregator.DEFAULT_WINDOW_SIZE == 500
    assert set(aggregator.KNOWN_COMPONENTS) == {
        "recovery",
        "state_backing",
        "fsm",
        "v907_verify",
        "bridge_diff",
    }


# ---------------------------------------------------------------------------
# 2. JSONL parsing tolerance + msg-envelope filtering
# ---------------------------------------------------------------------------


def test_read_decision_records_tolerates_malformed_and_filters_non_decision_msg(
    tmp_path: Path,
):
    """Blank lines, malformed JSON, and non-dict values are silently
    skipped. Records whose ``msg`` field is present and **not** equal
    to ``backend-decision`` are filtered out — the engine log_sink is
    a shared stream and unrelated events must not contaminate the
    aggregator. Records without a ``msg`` field are accepted
    (liberal-reader for direct-fixture emit).
    """
    p = tmp_path / "log.jsonl"
    p.write_text(
        "\n"  # blank
        + json.dumps(_decision(domain="recovery", chosen_backend="python")) + "\n"
        + "{not json}\n"  # malformed
        + json.dumps(["list-not-dict"]) + "\n"  # non-dict
        + "   \n"  # whitespace only
        # Foreign event in the same log_sink — must be filtered.
        + json.dumps(
            {"msg": "observability-event", "domain": "recovery", "chosen_backend": "rust"}
        )
        + "\n"
        # Direct fixture-emit (no msg envelope) — must be accepted.
        + json.dumps(_decision(domain="fsm", chosen_backend="rust", include_envelope=False))
        + "\n",
        encoding="utf-8",
    )
    out = aggregator.read_decision_records(p)
    assert len(out) == 2
    assert out[0]["domain"] == "recovery" and out[0]["chosen_backend"] == "python"
    assert out[1]["domain"] == "fsm" and out[1]["chosen_backend"] == "rust"


# ---------------------------------------------------------------------------
# 3. JSONL missing-file → JsonlReadError → CLI exit 1
# ---------------------------------------------------------------------------


def test_read_decision_records_raises_on_missing_file(tmp_path: Path):
    """A missing path raises :class:`JsonlReadError` so the CLI can
    map it to exit-code 1. Never silently treat a missing file as
    'zero decisions' — that masks operator misconfig.
    """
    p = tmp_path / "nonexistent.jsonl"
    with pytest.raises(aggregator.JsonlReadError) as excinfo:
        aggregator.read_decision_records(p)
    assert "not a regular file" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 4. Sliding window — trailing semantics + nonpositive clamp
# ---------------------------------------------------------------------------


def test_select_window_returns_trailing_records_and_clamps_nonpositive():
    """Trailing-window semantics + a zero/negative window-size cannot
    silently disable windowing. Both invariants pinned in one test.
    """
    records = [{"i": i} for i in range(10)]
    out = aggregator.select_window(records, 3)
    assert out == [{"i": 7}, {"i": 8}, {"i": 9}]

    # Window larger than the file -> return all.
    assert aggregator.select_window(records, 1000) == records

    # Non-positive clamps to default and keeps the *trailing* records.
    big = [{"i": i} for i in range(aggregator.DEFAULT_WINDOW_SIZE + 50)]
    out_zero = aggregator.select_window(big, 0)
    assert len(out_zero) == aggregator.DEFAULT_WINDOW_SIZE
    assert out_zero[-1] == {"i": aggregator.DEFAULT_WINDOW_SIZE + 50 - 1}
    out_neg = aggregator.select_window(big, -5)
    assert len(out_neg) == aggregator.DEFAULT_WINDOW_SIZE


# ---------------------------------------------------------------------------
# 5. ENV parsing
# ---------------------------------------------------------------------------


def test_read_window_size_from_env_parses_valid_and_falls_back():
    """Valid positive ints are honoured. Unset, empty, non-int, zero
    or negative falls back to DEFAULT_WINDOW_SIZE without raising.
    """
    env_var = aggregator.WAKIR_BACKEND_DECISION_OBS_WINDOW_ENV
    assert aggregator.read_window_size_from_env({env_var: "250"}) == 250
    assert aggregator.read_window_size_from_env({}) == aggregator.DEFAULT_WINDOW_SIZE
    assert (
        aggregator.read_window_size_from_env({env_var: ""})
        == aggregator.DEFAULT_WINDOW_SIZE
    )
    assert (
        aggregator.read_window_size_from_env({env_var: "not-an-int"})
        == aggregator.DEFAULT_WINDOW_SIZE
    )
    assert (
        aggregator.read_window_size_from_env({env_var: "0"})
        == aggregator.DEFAULT_WINDOW_SIZE
    )
    assert (
        aggregator.read_window_size_from_env({env_var: "-7"})
        == aggregator.DEFAULT_WINDOW_SIZE
    )


# ---------------------------------------------------------------------------
# 6. Aggregation — per-(component, backend) counts
# ---------------------------------------------------------------------------


def test_aggregate_decisions_counts_per_component_backend():
    """The core operator question: how many of each Phase-3b component
    booted under Rust vs. Python in the current window.
    """
    recs = [
        # recovery: 2x rust, 1x python
        _decision(domain="recovery", chosen_backend="rust"),
        _decision(domain="recovery", chosen_backend="rust"),
        _decision(domain="recovery", chosen_backend="python"),
        # state_backing: 1x rust_inmemory, 1x python
        _decision(domain="state_backing", chosen_backend="rust_inmemory"),
        _decision(domain="state_backing", chosen_backend="python"),
        # fsm: 1x rust
        _decision(domain="fsm", chosen_backend="rust"),
        # v907_verify: 1x python (no rust traffic this window)
        _decision(domain="v907_verify", chosen_backend="python"),
        # bridge_diff: 1x rust
        _decision(domain="bridge_diff", chosen_backend="rust"),
    ]
    env = aggregator.aggregate_decisions(recs, window_size=100)
    assert env["sample_size"] == 8
    assert env["window_size"] == 100
    assert env["count_per_component_backend"] == {
        "recovery": {"rust": 2, "python": 1},
        "state_backing": {"rust_inmemory": 1, "python": 1},
        "fsm": {"rust": 1},
        "v907_verify": {"python": 1},
        "bridge_diff": {"rust": 1},
    }
    assert env["count_per_component"] == {
        "recovery": 3,
        "state_backing": 2,
        "fsm": 1,
        "v907_verify": 1,
        "bridge_diff": 1,
    }


# ---------------------------------------------------------------------------
# 7. Aggregation — per-component latency percentiles (nearest-rank)
# ---------------------------------------------------------------------------


def test_aggregate_decisions_latency_percentiles_per_component():
    """Nearest-rank percentiles on a controlled sample produce stable
    integer values that correspond to real observed latencies.

    For sorted [10, 20, 30, ..., 100] (10 items):
      - p50 -> ceil(0.5*10)=5 -> values[4] = 50
      - p95 -> ceil(0.95*10)=10 -> values[9] = 100
      - p99 -> ceil(0.99*10)=10 -> values[9] = 100
      - avg -> 55.0
    """
    recs = [
        _decision(domain="recovery", resolution_latency_us=v)
        for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    ]
    env = aggregator.aggregate_decisions(recs, window_size=100)
    r = env["latency_per_component"]["recovery"]
    assert r["count"] == 10
    assert r["p50"] == 50
    assert r["p95"] == 100
    assert r["p99"] == 100
    assert r["avg"] == pytest.approx(55.0)


# ---------------------------------------------------------------------------
# 8. Fallback rates per component + aggregated
# ---------------------------------------------------------------------------


def test_aggregate_decisions_fallback_rates_per_component_and_aggregated():
    """Per-component fallback-rate is fallbacks/decisions in [0, 1];
    components with zero observations are absent from the dict
    (distinct from "zero fallback-rate"). Aggregated rate is the
    cross-component total-fallbacks / total-decisions.
    """
    recs = [
        # recovery: 4 decisions, 1 fallback -> 0.25
        _decision(domain="recovery", chosen_backend="python", fallback_reason=None),
        _decision(domain="recovery", chosen_backend="python", fallback_reason=None),
        _decision(domain="recovery", chosen_backend="python", fallback_reason=None),
        _decision(
            domain="recovery",
            chosen_backend="python",
            fallback_reason="binary_missing",
        ),
        # fsm: 2 decisions, 2 fallbacks -> 1.0
        _decision(
            domain="fsm",
            chosen_backend="python",
            fallback_reason="binary_not_executable",
        ),
        _decision(
            domain="fsm",
            chosen_backend="python",
            fallback_reason="binary_missing",
        ),
        # bridge_diff: 2 decisions, 0 fallbacks -> 0.0
        _decision(domain="bridge_diff", chosen_backend="rust"),
        _decision(domain="bridge_diff", chosen_backend="rust"),
    ]
    env = aggregator.aggregate_decisions(recs, window_size=100)
    assert env["fallback_counts_per_component"] == {
        "recovery": 1,
        "fsm": 2,
    }
    assert env["fallback_rate_per_component"] == {
        "recovery": pytest.approx(0.25),
        "fsm": pytest.approx(1.0),
        "bridge_diff": pytest.approx(0.0),
    }
    # Aggregated: 3 fallbacks / 8 decisions = 0.375
    assert env["aggregated_fallback_rate"] == pytest.approx(0.375)

    # Empty sample: aggregated rate is an explicit 0.0 (zero-attempt
    # rule), not NaN, not 1.0.
    env_empty = aggregator.aggregate_decisions([], window_size=100)
    assert env_empty["sample_size"] == 0
    assert env_empty["aggregated_fallback_rate"] == 0.0
    assert env_empty["fallback_rate_per_component"] == {}
    assert env_empty["count_per_component"] == {}


# ---------------------------------------------------------------------------
# 9. Unknown component / unknown backend bucketing
# ---------------------------------------------------------------------------


def test_aggregate_decisions_handles_unknown_component_and_backend():
    """Records with a ``domain`` outside KNOWN_COMPONENTS are bucketed
    under the component_unknown sentinel — drift surfaces on the
    dashboard instead of being silently discarded. Same for
    chosen_backend == null / missing.
    """
    recs = [
        _decision(domain="some-future-component", chosen_backend="rust"),
        _decision(domain="recovery", chosen_backend=None),  # type: ignore[arg-type]
        # Record with no domain at all.
        {"msg": "backend-decision", "chosen_backend": "python", "resolution_latency_us": 5},
    ]
    env = aggregator.aggregate_decisions(recs, window_size=100)
    assert (
        aggregator.COMPONENT_UNKNOWN_BUCKET in env["count_per_component"]
    )
    assert env["count_per_component"][aggregator.COMPONENT_UNKNOWN_BUCKET] == 2
    # recovery received one record but its chosen_backend was null ->
    # backend_unknown bucket under recovery.
    assert env["count_per_component_backend"]["recovery"] == {
        aggregator.BACKEND_UNKNOWN_BUCKET: 1
    }


# ---------------------------------------------------------------------------
# 10. Prometheus exposition surface
# ---------------------------------------------------------------------------


def test_render_prometheus_emits_expected_metric_names_and_labels():
    """Every metric name on the dashboard side must appear in the
    output with matching HELP/TYPE comments. Drift between the
    script's output schema and the dashboard's PromQL is what we
    guard against here. Specific label-rendering invariants
    (component+backend pair, fallback-rate float) are also pinned.
    """
    recs = [
        _decision(domain="recovery", chosen_backend="rust", resolution_latency_us=10),
        _decision(domain="recovery", chosen_backend="rust", resolution_latency_us=20),
        _decision(
            domain="recovery",
            chosen_backend="python",
            resolution_latency_us=30,
            fallback_reason="binary_missing",
        ),
        _decision(domain="fsm", chosen_backend="rust", resolution_latency_us=40),
    ]
    env = aggregator.aggregate_decisions(recs, window_size=100)
    text = aggregator.render_prometheus(env, scrape_ts_utc=1747008000)

    expected_metrics = [
        "persona_engine_backend_decisions_sample_size",
        "persona_engine_backend_decisions_window_size",
        "persona_engine_backend_decisions_per_component_backend",
        "persona_engine_backend_decisions_per_component",
        "persona_engine_backend_decision_latency_us",
        "persona_engine_backend_decision_latency_us_avg",
        "persona_engine_backend_decision_count_per_component",
        "persona_engine_backend_decision_fallbacks_total",
        "persona_engine_backend_decision_fallback_rate",
        "persona_engine_backend_decision_fallback_rate_aggregated",
        "persona_engine_backend_decisions_scrape_timestamp_seconds",
    ]
    for m in expected_metrics:
        assert f"# HELP {m} " in text, f"missing HELP for {m}"
        assert f"# TYPE {m} " in text, f"missing TYPE for {m}"

    # Pair-label rendering (component + backend on the per-pair metric).
    assert (
        'persona_engine_backend_decisions_per_component_backend'
        '{component="recovery",backend="rust"} 2'
    ) in text
    assert (
        'persona_engine_backend_decisions_per_component_backend'
        '{component="recovery",backend="python"} 1'
    ) in text
    assert (
        'persona_engine_backend_decisions_per_component_backend'
        '{component="fsm",backend="rust"} 1'
    ) in text

    # Per-component totals.
    assert (
        'persona_engine_backend_decisions_per_component{component="recovery"} 3'
        in text
    )
    assert (
        'persona_engine_backend_decisions_per_component{component="fsm"} 1' in text
    )

    # Percentile labels.
    assert (
        'persona_engine_backend_decision_latency_us'
        '{component="recovery",quantile="0.5"}'
    ) in text

    # Fallback rate (recovery: 1/3 = 0.3333...).
    # Aggregated: 1 fallback / 4 decisions = 0.25.
    assert (
        "persona_engine_backend_decision_fallback_rate_aggregated 0.25" in text
    )
    # Scrape timestamp echoed back.
    assert (
        "persona_engine_backend_decisions_scrape_timestamp_seconds 1747008000"
        in text
    )


# ---------------------------------------------------------------------------
# 11. CLI: --format=json round trip
# ---------------------------------------------------------------------------


def test_main_json_format_round_trip_via_cli(tmp_path: Path):
    """Running the CLI with --format=json on a small JSONL fixture
    produces parseable JSON whose envelope matches a direct call to
    ``aggregate_decisions``. Pins the operator-facing default path
    end-to-end.
    """
    jsonl = tmp_path / "backend-decisions.jsonl"
    _write_jsonl(
        jsonl,
        [
            _decision(domain="recovery", chosen_backend="rust", resolution_latency_us=5),
            _decision(domain="fsm", chosen_backend="python", resolution_latency_us=15),
            _decision(
                domain="v907_verify",
                chosen_backend="python",
                resolution_latency_us=25,
                fallback_reason="binary_missing",
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
    assert parsed["count_per_component"] == {
        "recovery": 1,
        "fsm": 1,
        "v907_verify": 1,
    }
    assert parsed["count_per_component_backend"]["recovery"] == {"rust": 1}
    assert parsed["count_per_component_backend"]["fsm"] == {"python": 1}
    assert parsed["count_per_component_backend"]["v907_verify"] == {"python": 1}
    assert parsed["fallback_counts_per_component"] == {"v907_verify": 1}
    # 1 fallback / 3 decisions.
    assert parsed["aggregated_fallback_rate"] == pytest.approx(1.0 / 3.0)


# ---------------------------------------------------------------------------
# 12. CLI: --format=prometheus --dry-run
# ---------------------------------------------------------------------------


def test_main_prometheus_dry_run_writes_to_stdout(tmp_path: Path):
    """In dry-run mode the Prometheus payload goes to stdout instead
    of the textfile path. Hermetic CI cannot write into
    /var/lib/node_exporter — dry-run is how operators preview a
    scrape before flipping the systemd timer on.
    """
    jsonl = tmp_path / "backend-decisions.jsonl"
    _write_jsonl(
        jsonl,
        [_decision(domain="recovery", chosen_backend="rust", resolution_latency_us=42)],
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
    assert "persona_engine_backend_decisions_sample_size 1" in payload
    assert (
        "persona_engine_backend_decisions_scrape_timestamp_seconds 1747000000"
        in payload
    )
    # Dry-run path must not touch the textfile path.
    assert buf_err.getvalue() == ""
