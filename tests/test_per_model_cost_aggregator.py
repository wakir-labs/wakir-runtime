# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for scripts/per-model-cost-aggregator.py.

Sprint-SRE Phase-2b (Noa Bergstroem / SRE). ADR-0064 Phase-2b
Folgeartefakte Item 2.

Hermetic — no real systemd timer, no real telemetry file. Drives the
aggregator's public functions against fabricated input records and
asserts:

  - mira-hourly aggregation honours the canonical ``model_usage``
    camelCase schema.
  - persona-engine aggregation listens for ``msg=="otel-metric"``
    records and counts invocations once per cost-emission.
  - merge_aggregations sums identical (model, invoker) keys.
  - Rendered Prometheus textfile output has the expected gauges,
    metric types, and label sort order (hermetic-test friendly).
  - Missing telemetry path is tolerated (empty result, no exception).
  - Existing but non-regular path raises TelemetryError.
  - main() returns 0 on the happy path and 1 on TelemetryError.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
AGG_PATH = REPO_ROOT / "scripts" / "per-model-cost-aggregator.py"


def _load_aggregator_module():
    spec = importlib.util.spec_from_file_location(
        "per_model_cost_aggregator", AGG_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


agg = _load_aggregator_module()


# ---------------------------------------------------------------------------
# Helpers — fabricate input records
# ---------------------------------------------------------------------------


def make_mira_hourly_record(
    *,
    invoker="mira-hourly",
    model_usage=None,
    total_cost_usd=1.0,
):
    """Return a one-line mira-hourly telemetry record dict."""
    if model_usage is None:
        model_usage = {
            "claude-opus-4-7[1m]": {
                "inputTokens": 16,
                "outputTokens": 19005,
                "cacheReadInputTokens": 844122,
                "cacheCreationInputTokens": 90345,
                "costUSD": 1.46192225,
            },
        }
    return {
        "timestamp_utc": "2026-05-16T12:04:07+00:00",
        "run_id": "2026-05-16T12:00:05Z",
        "invoker": invoker,
        "session_id": "abc-1",
        "duration_ms": 241485,
        "num_turns": 22,
        "is_error": False,
        "total_cost_usd": total_cost_usd,
        "model_usage": model_usage,
    }


def make_persona_engine_cost_record(
    *,
    model="claude-opus-4-7[1m]",
    persona_id="kai",
    cost_usd=0.5,
    metric_name="persona_engine.llm_call.cost_usd",
):
    """Return a persona-engine structured-JSON-log record."""
    return {
        "ts_utc": "2026-05-16T12:00:00Z",
        "component": "wakir-persona-engine",
        "level": "INFO",
        "msg": "otel-metric",
        "metric_name": metric_name,
        "metric_kind": "counter",
        "metric_value": cost_usd,
        "attributes": {
            "persona_id": persona_id,
            "model": model,
            "org_id": "wakir-labs",
        },
    }


# ---------------------------------------------------------------------------
# Vector 1 — mira-hourly single-model aggregation
# ---------------------------------------------------------------------------


def test_mira_hourly_single_record_single_model():
    rec = make_mira_hourly_record()
    result = agg.aggregate_mira_hourly([rec])
    key = ("claude-opus-4-7[1m]", "mira-hourly")
    assert key in result
    bucket = result[key]
    assert bucket["cost_usd"] == pytest.approx(1.46192225)
    assert bucket["input_tokens"] == 16.0
    assert bucket["output_tokens"] == 19005.0
    assert bucket["cache_read_input_tokens"] == 844122.0
    assert bucket["cache_creation_input_tokens"] == 90345.0
    assert bucket["invocation_count"] == 1.0


# ---------------------------------------------------------------------------
# Vector 2 — mira-hourly multi-model record
# ---------------------------------------------------------------------------


def test_mira_hourly_single_record_multi_model():
    rec = make_mira_hourly_record(
        model_usage={
            "claude-haiku-4-5-20251001": {
                "inputTokens": 3085,
                "outputTokens": 18,
                "cacheReadInputTokens": 0,
                "cacheCreationInputTokens": 0,
                "costUSD": 0.003175,
            },
            "claude-opus-4-7[1m]": {
                "inputTokens": 16,
                "outputTokens": 19005,
                "cacheReadInputTokens": 844122,
                "cacheCreationInputTokens": 90345,
                "costUSD": 1.46192225,
            },
        }
    )
    result = agg.aggregate_mira_hourly([rec])
    assert ("claude-haiku-4-5-20251001", "mira-hourly") in result
    assert ("claude-opus-4-7[1m]", "mira-hourly") in result
    haiku = result[("claude-haiku-4-5-20251001", "mira-hourly")]
    opus = result[("claude-opus-4-7[1m]", "mira-hourly")]
    assert haiku["cost_usd"] == pytest.approx(0.003175)
    assert opus["cost_usd"] == pytest.approx(1.46192225)
    # Each model gets one invocation on the same record (one record
    # touches two models).
    assert haiku["invocation_count"] == 1.0
    assert opus["invocation_count"] == 1.0


# ---------------------------------------------------------------------------
# Vector 3 — mira-hourly cumulative across multiple records
# ---------------------------------------------------------------------------


def test_mira_hourly_cumulative_across_records():
    rec1 = make_mira_hourly_record()
    rec2 = make_mira_hourly_record()
    result = agg.aggregate_mira_hourly([rec1, rec2])
    bucket = result[("claude-opus-4-7[1m]", "mira-hourly")]
    assert bucket["cost_usd"] == pytest.approx(1.46192225 * 2)
    assert bucket["invocation_count"] == 2.0


# ---------------------------------------------------------------------------
# Vector 4 — mira-hourly missing model_usage skipped without crash
# ---------------------------------------------------------------------------


def test_mira_hourly_missing_model_usage_skipped():
    bad = {"timestamp_utc": "2026-05-16T12:04:07+00:00", "invoker": "mira-hourly"}
    good = make_mira_hourly_record()
    result = agg.aggregate_mira_hourly([bad, good])
    assert ("claude-opus-4-7[1m]", "mira-hourly") in result
    bucket = result[("claude-opus-4-7[1m]", "mira-hourly")]
    assert bucket["invocation_count"] == 1.0


# ---------------------------------------------------------------------------
# Vector 5 — mira-hourly missing invoker -> "unknown" label
# ---------------------------------------------------------------------------


def test_mira_hourly_missing_invoker_falls_back_to_unknown():
    rec = make_mira_hourly_record()
    del rec["invoker"]
    result = agg.aggregate_mira_hourly([rec])
    key = ("claude-opus-4-7[1m]", agg.INVOKER_UNKNOWN)
    assert key in result


# ---------------------------------------------------------------------------
# Vector 6 — persona-engine cost-line aggregation
# ---------------------------------------------------------------------------


def test_persona_engine_cost_line_aggregated():
    rec = make_persona_engine_cost_record(cost_usd=0.75)
    result = agg.aggregate_persona_engine([rec])
    key = ("claude-opus-4-7[1m]", agg.SOURCE_PERSONA_ENGINE)
    assert key in result
    bucket = result[key]
    assert bucket["cost_usd"] == pytest.approx(0.75)
    assert bucket["invocation_count"] == 1.0


# ---------------------------------------------------------------------------
# Vector 7 — persona-engine token-lines aggregate without counting as
# additional invocations
# ---------------------------------------------------------------------------


def test_persona_engine_token_lines_do_not_double_count_invocations():
    cost = make_persona_engine_cost_record(cost_usd=0.5)
    input_tokens_rec = make_persona_engine_cost_record(
        metric_name="persona_engine.llm_call.input_tokens", cost_usd=100.0
    )
    output_tokens_rec = make_persona_engine_cost_record(
        metric_name="persona_engine.llm_call.output_tokens", cost_usd=200.0
    )
    cache_read_rec = make_persona_engine_cost_record(
        metric_name="persona_engine.llm_call.cache_read_input_tokens",
        cost_usd=50.0,
    )
    cache_create_rec = make_persona_engine_cost_record(
        metric_name="persona_engine.llm_call.cache_creation_input_tokens",
        cost_usd=25.0,
    )
    result = agg.aggregate_persona_engine(
        [cost, input_tokens_rec, output_tokens_rec, cache_read_rec, cache_create_rec]
    )
    key = ("claude-opus-4-7[1m]", agg.SOURCE_PERSONA_ENGINE)
    bucket = result[key]
    # One cost-line => one invocation, NOT five.
    assert bucket["invocation_count"] == 1.0
    assert bucket["cost_usd"] == pytest.approx(0.5)
    assert bucket["input_tokens"] == 100.0
    assert bucket["output_tokens"] == 200.0
    assert bucket["cache_read_input_tokens"] == 50.0
    assert bucket["cache_creation_input_tokens"] == 25.0


# ---------------------------------------------------------------------------
# Vector 8 — persona-engine non-cost metric ignored
# ---------------------------------------------------------------------------


def test_persona_engine_non_cost_metric_ignored():
    irrelevant = {
        "msg": "otel-metric",
        "metric_name": "persona_engine.spawn.latency_seconds",
        "metric_value": 12.5,
        "attributes": {"model": "claude-opus-4-7[1m]", "persona_id": "kai"},
    }
    result = agg.aggregate_persona_engine([irrelevant])
    assert result == {}


# ---------------------------------------------------------------------------
# Vector 9 — persona-engine missing model attribute -> "unknown"
# ---------------------------------------------------------------------------


def test_persona_engine_missing_model_attribute_falls_back_to_unknown():
    rec = make_persona_engine_cost_record()
    del rec["attributes"]["model"]
    result = agg.aggregate_persona_engine([rec])
    assert ("unknown", agg.SOURCE_PERSONA_ENGINE) in result


# ---------------------------------------------------------------------------
# Vector 10 — merge_aggregations sums identical keys
# ---------------------------------------------------------------------------


def test_merge_aggregations_sums_identical_keys():
    a = {
        ("claude-opus-4-7[1m]", "mira-hourly"): {
            "cost_usd": 1.0,
            "input_tokens": 10.0,
            "output_tokens": 20.0,
            "cache_read_input_tokens": 30.0,
            "cache_creation_input_tokens": 40.0,
            "invocation_count": 1.0,
        }
    }
    b = {
        ("claude-opus-4-7[1m]", "mira-hourly"): {
            "cost_usd": 2.0,
            "input_tokens": 5.0,
            "output_tokens": 10.0,
            "cache_read_input_tokens": 15.0,
            "cache_creation_input_tokens": 20.0,
            "invocation_count": 1.0,
        }
    }
    merged = agg.merge_aggregations(a, b)
    bucket = merged[("claude-opus-4-7[1m]", "mira-hourly")]
    assert bucket["cost_usd"] == pytest.approx(3.0)
    assert bucket["input_tokens"] == 15.0
    assert bucket["output_tokens"] == 30.0
    assert bucket["cache_read_input_tokens"] == 45.0
    assert bucket["cache_creation_input_tokens"] == 60.0
    assert bucket["invocation_count"] == 2.0


# ---------------------------------------------------------------------------
# Vector 11 — merge_aggregations keeps distinct keys separate
# ---------------------------------------------------------------------------


def test_merge_aggregations_keeps_distinct_keys_separate():
    a = {
        ("claude-opus-4-7[1m]", "mira-hourly"): agg._empty_bucket()
    }
    a[("claude-opus-4-7[1m]", "mira-hourly")]["cost_usd"] = 1.0
    b = {
        ("claude-haiku-4-5-20251001", "mira-hourly"): agg._empty_bucket()
    }
    b[("claude-haiku-4-5-20251001", "mira-hourly")]["cost_usd"] = 0.01
    merged = agg.merge_aggregations(a, b)
    assert len(merged) == 2


# ---------------------------------------------------------------------------
# Vector 12 — render_textfile emits HELP/TYPE/lines in stable order
# ---------------------------------------------------------------------------


def test_render_textfile_stable_label_sort_order():
    per_model = {
        ("claude-opus-4-7[1m]", "mira-hourly"): {
            "cost_usd": 1.5,
            "input_tokens": 16.0,
            "output_tokens": 19005.0,
            "cache_read_input_tokens": 844122.0,
            "cache_creation_input_tokens": 90345.0,
            "invocation_count": 1.0,
        },
        ("claude-haiku-4-5-20251001", "mira-hourly"): {
            "cost_usd": 0.003,
            "input_tokens": 3085.0,
            "output_tokens": 18.0,
            "cache_read_input_tokens": 0.0,
            "cache_creation_input_tokens": 0.0,
            "invocation_count": 1.0,
        },
    }
    payload = agg.render_textfile(
        per_model=per_model,
        records_consumed={"mira_hourly": 1, "persona_engine": 0},
        now_unixtime=1700000000,
    )
    # HELP/TYPE for each metric.
    assert "# HELP wakir_model_cost_usd_total" in payload
    assert "# TYPE wakir_model_cost_usd_total gauge" in payload
    # Both models present, sorted alphabetically by label set.
    lines = [l for l in payload.splitlines() if l.startswith("wakir_model_cost_usd_total{")]
    assert len(lines) == 2
    # Haiku sorts before Opus because invoker is identical and model
    # "claude-haiku-..." < "claude-opus-..." lexicographically.
    assert "haiku" in lines[0]
    assert "opus" in lines[1]


# ---------------------------------------------------------------------------
# Vector 13 — render_textfile emits zero-row blocks with HELP/TYPE
# ---------------------------------------------------------------------------


def test_render_textfile_zero_row_block_still_has_help_type():
    payload = agg.render_textfile(
        per_model={},
        records_consumed={},
        now_unixtime=1700000000,
    )
    # No data rows, but HELP/TYPE blocks must still be present
    # (node_exporter must not see metric-name flicker).
    assert "# HELP wakir_model_cost_usd_total" in payload
    assert "# TYPE wakir_model_cost_usd_total gauge" in payload
    assert "wakir_per_model_aggregator_last_run_unixtime 1700000000.0" in payload


# ---------------------------------------------------------------------------
# Vector 14 — render_textfile escapes label values per spec
# ---------------------------------------------------------------------------


def test_render_textfile_escapes_label_values():
    per_model = {
        ('weird"model\\name', "invoker\n"): agg._empty_bucket()
    }
    payload = agg.render_textfile(
        per_model=per_model,
        records_consumed={},
        now_unixtime=0,
    )
    # Double-quotes -> \", backslashes -> \\, newlines -> \\n.
    assert 'model="weird\\"model\\\\name"' in payload
    assert 'invoker="invoker\\n"' in payload


# ---------------------------------------------------------------------------
# Vector 15 — read_jsonl_tail returns [] for missing path
# ---------------------------------------------------------------------------


def test_read_jsonl_tail_missing_path_returns_empty(tmp_path):
    missing = tmp_path / "does-not-exist.jsonl"
    assert agg.read_jsonl_tail(missing) == []


# ---------------------------------------------------------------------------
# Vector 16 — read_jsonl_tail raises TelemetryError on directory
# ---------------------------------------------------------------------------


def test_read_jsonl_tail_directory_raises(tmp_path):
    d = tmp_path / "dir-not-file"
    d.mkdir()
    with pytest.raises(agg.TelemetryError):
        agg.read_jsonl_tail(d)


# ---------------------------------------------------------------------------
# Vector 17 — read_jsonl_tail skips malformed JSON lines
# ---------------------------------------------------------------------------


def test_read_jsonl_tail_skips_malformed_lines(tmp_path):
    p = tmp_path / "x.jsonl"
    good = json.dumps({"a": 1})
    p.write_text(f"{good}\nnot-json\n\n{good}\n", encoding="utf-8")
    rows = agg.read_jsonl_tail(p)
    assert rows == [{"a": 1}, {"a": 1}]


# ---------------------------------------------------------------------------
# Vector 18 — atomic_write writes payload and replaces atomically
# ---------------------------------------------------------------------------


def test_atomic_write_replaces_atomically(tmp_path):
    target = tmp_path / "subdir" / "x.prom"
    agg.atomic_write(target, "metric_name 1.0\n")
    assert target.read_text(encoding="utf-8") == "metric_name 1.0\n"
    # Replace with new payload.
    agg.atomic_write(target, "metric_name 2.0\n")
    assert target.read_text(encoding="utf-8") == "metric_name 2.0\n"


# ---------------------------------------------------------------------------
# Vector 19 — main() happy path returns 0
# ---------------------------------------------------------------------------


def test_main_happy_path_returns_zero(tmp_path):
    mh = tmp_path / "mh.jsonl"
    mh.write_text(json.dumps(make_mira_hourly_record()) + "\n", encoding="utf-8")
    pe = tmp_path / "pe.jsonl"
    pe.write_text(
        json.dumps(make_persona_engine_cost_record()) + "\n", encoding="utf-8"
    )
    out = tmp_path / "out.prom"
    rc = agg.main(
        [
            "--mira-hourly-telemetry",
            str(mh),
            "--persona-engine-log",
            str(pe),
            "--textfile-output",
            str(out),
            "--now",
            "1700000000",
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "wakir_model_cost_usd_total" in text
    assert "wakir_per_model_aggregator_records_consumed_total" in text


# ---------------------------------------------------------------------------
# Vector 20 — main() dry-run does not write
# ---------------------------------------------------------------------------


def test_main_dry_run_does_not_write(tmp_path, capsys):
    mh = tmp_path / "mh.jsonl"
    mh.write_text(json.dumps(make_mira_hourly_record()) + "\n", encoding="utf-8")
    out = tmp_path / "out.prom"
    rc = agg.main(
        [
            "--mira-hourly-telemetry",
            str(mh),
            "--persona-engine-log",
            str(tmp_path / "missing.jsonl"),
            "--textfile-output",
            str(out),
            "--now",
            "1700000000",
            "--dry-run",
        ]
    )
    assert rc == 0
    assert not out.exists()
    captured = capsys.readouterr()
    assert "wakir_model_cost_usd_total" in captured.out


# ---------------------------------------------------------------------------
# Vector 21 — main() error path on directory-as-path returns 1
# ---------------------------------------------------------------------------


def test_main_directory_path_returns_one(tmp_path):
    d = tmp_path / "directory-not-file"
    d.mkdir()
    rc = agg.main(
        [
            "--mira-hourly-telemetry",
            str(d),
            "--persona-engine-log",
            str(tmp_path / "missing.jsonl"),
            "--textfile-output",
            str(tmp_path / "out.prom"),
            "--now",
            "1700000000",
        ]
    )
    assert rc == 1


# ---------------------------------------------------------------------------
# Vector 22 — end-to-end: mira-hourly + persona-engine merged correctly
# ---------------------------------------------------------------------------


def test_end_to_end_merge_mira_and_persona_engine(tmp_path):
    mh = tmp_path / "mh.jsonl"
    mh.write_text(json.dumps(make_mira_hourly_record()) + "\n", encoding="utf-8")
    pe = tmp_path / "pe.jsonl"
    pe.write_text(
        json.dumps(make_persona_engine_cost_record(cost_usd=0.5)) + "\n",
        encoding="utf-8",
    )
    mh_records = agg.read_jsonl_tail(mh)
    pe_records = agg.read_jsonl_tail(pe)
    mh_agg = agg.aggregate_mira_hourly(mh_records)
    pe_agg = agg.aggregate_persona_engine(pe_records)
    merged = agg.merge_aggregations(mh_agg, pe_agg)
    # Both sources keyed by same model but different invoker => two
    # distinct entries.
    assert ("claude-opus-4-7[1m]", "mira-hourly") in merged
    assert ("claude-opus-4-7[1m]", agg.SOURCE_PERSONA_ENGINE) in merged
