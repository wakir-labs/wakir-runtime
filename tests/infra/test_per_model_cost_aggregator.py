# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/per-model-cost-aggregator.py — Sprint-Phase-2b MINI.

Hermetic — no real persona-engine, no real textfile-collector
directory. Drives the aggregator's public functions against
fabricated structured-JSON log fixtures and asserts:

  - The persona-engine structured-JSON log shape (request-side
    and cache-telemetry-side) round-trips through token extraction.
  - Per-model separation is correct (claude-opus-4-7 vs
    claude-sonnet-4-6 vs claude-haiku-4-5 buckets stay isolated).
  - The aggregation math matches the ADR-0064 pricing table for
    pure-uncached, cache-read, and cache-creation token mixes.
  - The Prometheus exposition format renders the documented gauge
    schema with correct label escaping.
  - Unknown-model records fall into the ``model_unknown`` bucket
    with zero USD cost and non-zero token counts (drift detection).
  - The end-to-end ``main`` writes the textfile atomically.

The aggregator script is stdlib-only and lives outside the
python package tree under ``scripts/``. We import it via
importlib.util so the hyphenated filename stays legal.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Import the aggregator script as a module
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_PATH = REPO_ROOT / "scripts" / "per-model-cost-aggregator.py"


def _load_aggregator_module():
    spec = importlib.util.spec_from_file_location(
        "per_model_cost_aggregator", AGGREGATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


aggregator = _load_aggregator_module()


# ---------------------------------------------------------------------------
# Log fixture factories
# ---------------------------------------------------------------------------


def request_record(
    *,
    model: str,
    persona: str = "tomas",
    v907_pin: str = "v907-pin-abc",
    ttl_seconds: int = 300,
) -> dict:
    """Mirror persona_engine.anthropic_cache.build_cached_request_payload.

    Produces a request-side log line that carries the ``model`` key
    directly (not via affinity-key parsing).
    """
    return {
        "ts_utc": "2026-05-16T18:00:00+00:00",
        "component": "wakir-persona-engine",
        "level": "INFO",
        "msg": "anthropic_request_built",
        "model": model,
        "cache_affinity_key": (
            f"anthropic:{model}:{persona}:{v907_pin}:ttl{ttl_seconds}"
        ),
    }


def telemetry_record(
    *,
    model: str = "claude-opus-4-7",
    persona: str = "tomas",
    v907_pin: str = "v907-pin-abc",
    ttl_seconds: int = 300,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> dict:
    """Mirror persona_engine.anthropic_cache.CacheTelemetry.to_structured_log_dict.

    The telemetry record carries the cache-affinity-key (which embeds
    the model id) but **not** an explicit ``model`` key — so
    ``extract_model_id`` resolves via affinity-key parsing.
    """
    return {
        "event": "anthropic_cache_telemetry",
        "cache_affinity_key": (
            f"anthropic:{model}:{persona}:{v907_pin}:ttl{ttl_seconds}"
        ),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cache_read_input_tokens,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "total_input_tokens": (
            input_tokens + cache_read_input_tokens + cache_creation_input_tokens
        ),
        "cache_hit_rate_input_only": 0.0,
        "cache_ephemeral_5m_input_tokens": cache_creation_input_tokens,
        "cache_ephemeral_1h_input_tokens": 0,
    }


def otel_metric_record(
    *,
    model: str,
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> dict:
    """Mirror PersonaEngineObservability._StructuredLogSink shape."""
    return {
        "ts_utc": "2026-05-16T18:00:00+00:00",
        "component": "wakir-persona-engine",
        "level": "INFO",
        "msg": "otel-metric",
        "metric_name": "persona_engine.anthropic.tokens",
        "metric_kind": "counter",
        "metric_value": float(input_tokens + output_tokens),
        "attributes": {"model": model},
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def write_log(tmp_path: Path, records: list) -> Path:
    """Materialise records as JSON-lines into a tmp log file."""
    p = tmp_path / "persona-engine.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return p


# ---------------------------------------------------------------------------
# Test 1: extract_model_id — three resolution paths
# ---------------------------------------------------------------------------


def test_extract_model_id_direct_key():
    rec = {"model": "claude-opus-4-7"}
    assert aggregator.extract_model_id(rec) == "claude-opus-4-7"


def test_extract_model_id_otel_attributes():
    rec = {"attributes": {"model": "claude-sonnet-4-6"}}
    assert aggregator.extract_model_id(rec) == "claude-sonnet-4-6"


def test_extract_model_id_cache_affinity_key():
    rec = {
        "cache_affinity_key": (
            "anthropic:claude-haiku-4-5:noa:v907-pin-xy:ttl300"
        )
    }
    assert aggregator.extract_model_id(rec) == "claude-haiku-4-5"


def test_extract_model_id_missing_falls_back_to_unknown_bucket():
    rec = {"input_tokens": 10, "output_tokens": 5}
    assert (
        aggregator.extract_model_id(rec)
        == aggregator.MODEL_UNKNOWN_BUCKET
    )


def test_extract_model_id_prefers_direct_over_affinity():
    """If a record carries both, the direct key wins (request-side
    record is more authoritative than the derived affinity key)."""
    rec = {
        "model": "claude-opus-4-7",
        "cache_affinity_key": (
            "anthropic:claude-sonnet-4-6:noa:v907-pin-xy:ttl300"
        ),
    }
    assert aggregator.extract_model_id(rec) == "claude-opus-4-7"


# ---------------------------------------------------------------------------
# Test 2: extract_token_envelope — token-shape detection
# ---------------------------------------------------------------------------


def test_extract_token_envelope_full_shape():
    rec = telemetry_record(
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=20,
        cache_creation_input_tokens=10,
    )
    env = aggregator.extract_token_envelope(rec)
    assert env == {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read_input_tokens": 20,
        "cache_creation_input_tokens": 10,
    }


def test_extract_token_envelope_skips_pure_span_record():
    """An ``otel-span`` record with no token-shape fields returns None."""
    rec = {
        "ts_utc": "2026-05-16T18:00:00+00:00",
        "msg": "otel-span",
        "span_name": "persona_engine.spawn",
        "duration_seconds": 12.0,
        "status": "ok",
    }
    assert aggregator.extract_token_envelope(rec) is None


def test_extract_token_envelope_handles_missing_keys_as_zero():
    rec = {"input_tokens": 10}
    env = aggregator.extract_token_envelope(rec)
    assert env == {
        "input_tokens": 10,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


def test_extract_token_envelope_tolerates_non_numeric():
    rec = {
        "input_tokens": "not-a-number",
        "output_tokens": 5,
    }
    env = aggregator.extract_token_envelope(rec)
    assert env == {
        "input_tokens": 0,
        "output_tokens": 5,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


# ---------------------------------------------------------------------------
# Test 3: compute_cost_usd — ADR-0064 pricing math
# ---------------------------------------------------------------------------


def test_compute_cost_usd_opus_pure_uncached():
    """1M input + 1M output on Opus = 15 + 75 = 90 USD."""
    cost = aggregator.compute_cost_usd(
        model_id="claude-opus-4-7",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    assert cost == pytest.approx(90.0)


def test_compute_cost_usd_sonnet_pure_uncached():
    """1M input + 1M output on Sonnet = 3 + 15 = 18 USD."""
    cost = aggregator.compute_cost_usd(
        model_id="claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    assert cost == pytest.approx(18.0)


def test_compute_cost_usd_haiku_pure_uncached():
    """1M input + 1M output on Haiku = 0.80 + 4 = 4.80 USD."""
    cost = aggregator.compute_cost_usd(
        model_id="claude-haiku-4-5",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    assert cost == pytest.approx(4.80)


def test_compute_cost_usd_cache_read_discount():
    """Cache-read tokens billed at 10% of input rate.

    1M cache_read on Opus = 1M * (15 * 0.10) = 1.50 USD (vs 15 USD
    uncached); plus zero output. ADR-0064 +
    anthropic_cache.parse_cache_telemetry contract.
    """
    cost = aggregator.compute_cost_usd(
        model_id="claude-opus-4-7",
        input_tokens=0,
        output_tokens=0,
        cache_read_input_tokens=1_000_000,
        cache_creation_input_tokens=0,
    )
    assert cost == pytest.approx(1.50)


def test_compute_cost_usd_cache_creation_premium():
    """Cache-creation tokens billed at 1.25x input rate (5-min slot).

    1M cache_creation on Opus = 1M * (15 * 1.25) = 18.75 USD.
    """
    cost = aggregator.compute_cost_usd(
        model_id="claude-opus-4-7",
        input_tokens=0,
        output_tokens=0,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=1_000_000,
    )
    assert cost == pytest.approx(18.75)


def test_compute_cost_usd_unknown_model_returns_zero():
    """Records with a model not in the ADR-0064 pricing table return 0.0
    so the gauge stays additive; drift is surfaced via the unknown
    bucket's non-zero token counts."""
    cost = aggregator.compute_cost_usd(
        model_id="claude-future-5-0",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    assert cost == 0.0


# ---------------------------------------------------------------------------
# Test 4: aggregate_records — per-model separation
# ---------------------------------------------------------------------------


def test_aggregate_records_separates_three_models():
    records = [
        telemetry_record(model="claude-opus-4-7", input_tokens=100),
        telemetry_record(model="claude-sonnet-4-6", input_tokens=200),
        telemetry_record(model="claude-haiku-4-5", input_tokens=300),
        telemetry_record(model="claude-opus-4-7", input_tokens=50),
    ]
    buckets = aggregator.aggregate_records(records)
    assert set(buckets.keys()) == {
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    }
    # Opus accumulates two records, others one each.
    assert buckets["claude-opus-4-7"]["input_tokens"] == 150
    assert buckets["claude-opus-4-7"]["record_count"] == 2
    assert buckets["claude-sonnet-4-6"]["input_tokens"] == 200
    assert buckets["claude-sonnet-4-6"]["record_count"] == 1
    assert buckets["claude-haiku-4-5"]["input_tokens"] == 300
    assert buckets["claude-haiku-4-5"]["record_count"] == 1


def test_aggregate_records_unknown_model_bucket_isolated():
    """Records with no resolvable model land in MODEL_UNKNOWN_BUCKET
    and do not contaminate the named buckets."""
    records = [
        telemetry_record(model="claude-opus-4-7", input_tokens=100),
        {"input_tokens": 999, "output_tokens": 999},  # no model
    ]
    buckets = aggregator.aggregate_records(records)
    assert "claude-opus-4-7" in buckets
    assert aggregator.MODEL_UNKNOWN_BUCKET in buckets
    assert buckets["claude-opus-4-7"]["input_tokens"] == 100
    assert (
        buckets[aggregator.MODEL_UNKNOWN_BUCKET]["input_tokens"] == 999
    )
    # Unknown bucket gets zero cost (pricing table miss).
    assert buckets[aggregator.MODEL_UNKNOWN_BUCKET]["cost_usd"] == 0.0


def test_aggregate_records_cost_math_compounds_across_records():
    """Two Opus records of 1M input each should accumulate to 30 USD
    (2 * 15 USD per MTok input)."""
    records = [
        telemetry_record(
            model="claude-opus-4-7",
            input_tokens=1_000_000,
            output_tokens=0,
        ),
        telemetry_record(
            model="claude-opus-4-7",
            input_tokens=1_000_000,
            output_tokens=0,
        ),
    ]
    buckets = aggregator.aggregate_records(records)
    assert buckets["claude-opus-4-7"]["cost_usd"] == pytest.approx(30.0)
    assert buckets["claude-opus-4-7"]["input_tokens"] == 2_000_000


def test_aggregate_records_total_tokens_sums_all_four_fields():
    records = [
        telemetry_record(
            model="claude-opus-4-7",
            input_tokens=10,
            output_tokens=20,
            cache_read_input_tokens=30,
            cache_creation_input_tokens=40,
        ),
    ]
    buckets = aggregator.aggregate_records(records)
    assert buckets["claude-opus-4-7"]["total_tokens"] == 100


def test_aggregate_records_skips_non_token_records():
    """Span / FSM records with no token-shape fields do not create
    empty buckets."""
    records = [
        {
            "msg": "otel-span",
            "span_name": "persona_engine.spawn",
            "duration_seconds": 1.0,
            "status": "ok",
            "attributes": {"model": "claude-opus-4-7"},
        },
    ]
    buckets = aggregator.aggregate_records(records)
    assert buckets == {}


def test_aggregate_records_resolves_via_otel_metric_attributes():
    """A record with the ``otel-metric`` shape that carries the model
    only via ``attributes.model`` aggregates correctly."""
    records = [
        otel_metric_record(
            model="claude-sonnet-4-6",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        ),
    ]
    buckets = aggregator.aggregate_records(records)
    assert "claude-sonnet-4-6" in buckets
    assert buckets["claude-sonnet-4-6"]["cost_usd"] == pytest.approx(
        18.0
    )


# ---------------------------------------------------------------------------
# Test 5: render_textfile — Prometheus exposition format
# ---------------------------------------------------------------------------


def test_render_textfile_emits_all_seven_metrics_per_model():
    buckets = {
        "claude-opus-4-7": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 20,
            "cache_creation_input_tokens": 10,
            "total_tokens": 180,
            "cost_usd": 0.0042,
            "record_count": 3,
        },
    }
    out = aggregator.render_textfile(buckets, scrape_ts_utc=1715875200)
    # All seven per-model metrics + the scrape timestamp.
    expected_metrics = [
        "persona_engine_cost_input_tokens_total",
        "persona_engine_cost_output_tokens_total",
        "persona_engine_cost_cache_read_tokens_total",
        "persona_engine_cost_cache_creation_tokens_total",
        "persona_engine_cost_total_tokens",
        "persona_engine_cost_usd",
        "persona_engine_cost_record_count_total",
        "persona_engine_cost_scrape_timestamp_seconds",
    ]
    for metric in expected_metrics:
        assert f"# HELP {metric}" in out
        assert f"# TYPE {metric} gauge" in out


def test_render_textfile_model_label_present():
    buckets = {
        "claude-haiku-4-5": {
            "input_tokens": 1,
            "output_tokens": 2,
            "cache_read_input_tokens": 3,
            "cache_creation_input_tokens": 4,
            "total_tokens": 10,
            "cost_usd": 0.5,
            "record_count": 1,
        },
    }
    out = aggregator.render_textfile(buckets, scrape_ts_utc=1715875200)
    assert (
        'persona_engine_cost_input_tokens_total{model="claude-haiku-4-5"} 1'
        in out
    )


def test_render_textfile_value_format_integer_floats_collapse():
    """Integer-valued floats render without trailing '.0'."""
    buckets = {
        "claude-opus-4-7": {
            "input_tokens": 1000.0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "total_tokens": 1000.0,
            "cost_usd": 0.015,
            "record_count": 1,
        },
    }
    out = aggregator.render_textfile(buckets, scrape_ts_utc=1715875200)
    # Token gauge is an integer-valued float -> renders as 1000 (no .0).
    assert 'persona_engine_cost_input_tokens_total{model="claude-opus-4-7"} 1000' in out
    # Cost gauge is a non-integer float -> renders with decimals.
    assert 'persona_engine_cost_usd{model="claude-opus-4-7"} 0.015' in out


def test_render_textfile_stable_model_ordering():
    """Models are emitted in sorted order — keeps the textfile diff
    readable and makes golden tests deterministic."""
    buckets = {
        "claude-sonnet-4-6": {
            "input_tokens": 1,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "total_tokens": 1,
            "cost_usd": 0.0,
            "record_count": 1,
        },
        "claude-opus-4-7": {
            "input_tokens": 2,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "total_tokens": 2,
            "cost_usd": 0.0,
            "record_count": 1,
        },
    }
    out = aggregator.render_textfile(buckets, scrape_ts_utc=1715875200)
    opus_pos = out.find('model="claude-opus-4-7"')
    sonnet_pos = out.find('model="claude-sonnet-4-6"')
    assert opus_pos != -1 and sonnet_pos != -1
    assert opus_pos < sonnet_pos  # 'opus' < 'sonnet' lexicographically


def test_render_textfile_label_escaping():
    """Backslash and double-quote in model id are escaped per Prometheus
    label-value contract."""
    buckets = {
        'claude-"weird\\name': {
            "input_tokens": 1,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "total_tokens": 1,
            "cost_usd": 0.0,
            "record_count": 1,
        },
    }
    out = aggregator.render_textfile(buckets, scrape_ts_utc=1715875200)
    assert 'model="claude-\\"weird\\\\name"' in out


def test_render_textfile_scrape_timestamp_present():
    out = aggregator.render_textfile({}, scrape_ts_utc=1715875200)
    assert (
        "persona_engine_cost_scrape_timestamp_seconds 1715875200" in out
    )


def test_render_textfile_empty_buckets_still_emits_help_lines():
    """Even with zero records the textfile carries the schema headers,
    so Prometheus scraping does not flap on cold-start."""
    out = aggregator.render_textfile({}, scrape_ts_utc=1715875200)
    assert "# HELP persona_engine_cost_usd" in out
    assert "# TYPE persona_engine_cost_usd gauge" in out
    assert (
        "persona_engine_cost_scrape_timestamp_seconds 1715875200" in out
    )


# ---------------------------------------------------------------------------
# Test 6: end-to-end main — log read + textfile write
# ---------------------------------------------------------------------------


def test_main_writes_textfile_atomically(tmp_path):
    log_path = write_log(
        tmp_path,
        [
            telemetry_record(
                model="claude-opus-4-7",
                input_tokens=1_000_000,
                output_tokens=0,
            ),
            telemetry_record(
                model="claude-sonnet-4-6",
                input_tokens=1_000_000,
                output_tokens=0,
            ),
        ],
    )
    out_path = tmp_path / "out" / "per_model_cost.prom"
    rc = aggregator.main(
        [
            "--log-path",
            str(log_path),
            "--textfile-output",
            str(out_path),
            "--now",
            "1715875200",
        ],
        env={},
    )
    assert rc == 0
    assert out_path.is_file()
    payload = out_path.read_text(encoding="utf-8")
    # 1M Opus input @ $15/MTok = $15.
    assert (
        'persona_engine_cost_usd{model="claude-opus-4-7"} 15' in payload
    )
    # 1M Sonnet input @ $3/MTok = $3.
    assert (
        'persona_engine_cost_usd{model="claude-sonnet-4-6"} 3' in payload
    )


def test_main_dry_run_does_not_write(tmp_path, capsys):
    log_path = write_log(
        tmp_path,
        [
            telemetry_record(
                model="claude-haiku-4-5",
                input_tokens=1_000_000,
                output_tokens=0,
            ),
        ],
    )
    out_path = tmp_path / "out" / "per_model_cost.prom"
    rc = aggregator.main(
        [
            "--log-path",
            str(log_path),
            "--textfile-output",
            str(out_path),
            "--now",
            "1715875200",
            "--dry-run",
        ],
        env={},
    )
    assert rc == 0
    assert not out_path.exists()
    captured = capsys.readouterr()
    assert "persona_engine_cost_usd" in captured.out


def test_main_log_missing_returns_exit_1(tmp_path, capsys):
    rc = aggregator.main(
        [
            "--log-path",
            str(tmp_path / "does-not-exist.jsonl"),
            "--textfile-output",
            str(tmp_path / "out.prom"),
        ],
        env={},
    )
    assert rc == 1
    captured = capsys.readouterr()
    assert "is not a regular file" in captured.err


def test_main_env_var_log_path_fallback(tmp_path):
    log_path = write_log(
        tmp_path,
        [
            telemetry_record(
                model="claude-opus-4-7",
                input_tokens=100,
                output_tokens=50,
            ),
        ],
    )
    out_path = tmp_path / "out" / "per_model_cost.prom"
    rc = aggregator.main(
        [
            "--textfile-output",
            str(out_path),
            "--now",
            "1715875200",
        ],
        env={"WAKIR_PERSONA_ENGINE_LOG_PATH": str(log_path)},
    )
    assert rc == 0
    assert out_path.is_file()


def test_main_tolerates_blank_and_malformed_log_lines(tmp_path):
    """Real logs carry partial lines after crashes; the aggregator
    skips both blanks and malformed JSON without aborting."""
    log_path = tmp_path / "persona-engine.jsonl"
    with log_path.open("w", encoding="utf-8") as fh:
        fh.write("\n")
        fh.write("not json at all\n")
        fh.write(
            json.dumps(
                telemetry_record(
                    model="claude-opus-4-7",
                    input_tokens=1_000_000,
                    output_tokens=0,
                ),
                sort_keys=True,
            )
            + "\n"
        )
        fh.write("{partial: ")  # truncated
    out_path = tmp_path / "out" / "per_model_cost.prom"
    rc = aggregator.main(
        [
            "--log-path",
            str(log_path),
            "--textfile-output",
            str(out_path),
            "--now",
            "1715875200",
        ],
        env={},
    )
    assert rc == 0
    payload = out_path.read_text(encoding="utf-8")
    assert (
        'persona_engine_cost_usd{model="claude-opus-4-7"} 15' in payload
    )


# ---------------------------------------------------------------------------
# Test 7: ADR-0064 pricing table parity guard
# ---------------------------------------------------------------------------


def test_pricing_table_carries_all_three_phase_2a_models():
    """Sanity guard: if a future ADR-0064b removes one of the three
    models from the routing-set, this test breaks loudly so the
    aggregator rev gets revised alongside."""
    assert "claude-haiku-4-5" in aggregator.MODEL_PRICING
    assert "claude-sonnet-4-6" in aggregator.MODEL_PRICING
    assert "claude-opus-4-7" in aggregator.MODEL_PRICING


def test_pricing_table_haiku_cheaper_than_sonnet_cheaper_than_opus():
    """The ADR-0064 cost-spread (Faktor 15-20x) implies this invariant.
    If a typo flips the table, this catches it before deploy."""
    haiku_in = aggregator.MODEL_PRICING["claude-haiku-4-5"][
        "input_usd_per_mtok"
    ]
    sonnet_in = aggregator.MODEL_PRICING["claude-sonnet-4-6"][
        "input_usd_per_mtok"
    ]
    opus_in = aggregator.MODEL_PRICING["claude-opus-4-7"][
        "input_usd_per_mtok"
    ]
    assert haiku_in < sonnet_in < opus_in
    haiku_out = aggregator.MODEL_PRICING["claude-haiku-4-5"][
        "output_usd_per_mtok"
    ]
    sonnet_out = aggregator.MODEL_PRICING["claude-sonnet-4-6"][
        "output_usd_per_mtok"
    ]
    opus_out = aggregator.MODEL_PRICING["claude-opus-4-7"][
        "output_usd_per_mtok"
    ]
    assert haiku_out < sonnet_out < opus_out
    # Spread guard — ADR-0064 cites Faktor ~15-20x.
    assert opus_in / haiku_in >= 15.0
