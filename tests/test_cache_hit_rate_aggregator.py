# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for scripts/cache-hit-rate-aggregator.py.

Sprint-SRE Phase-2b (Noa Bergstroem / SRE). ADR-0064 Phase-2b
Folgeartefakte Item 3.

Hermetic — no real systemd timer, no real telemetry file. Drives the
aggregator's public functions against fabricated
``anthropic_cache_telemetry`` events (exactly the schema emitted by
``wirelang/persona_engine/anthropic_cache.py::CacheTelemetry.to_struct
ured_log_dict``).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
AGG_PATH = REPO_ROOT / "scripts" / "cache-hit-rate-aggregator.py"


def _load_aggregator_module():
    spec = importlib.util.spec_from_file_location(
        "cache_hit_rate_aggregator", AGG_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


agg = _load_aggregator_module()


# ---------------------------------------------------------------------------
# Helpers — fabricate input records
# ---------------------------------------------------------------------------


def make_cache_event(
    *,
    model="claude-opus-4-7[1m]",
    persona_id="kai",
    v907_pin="abc123",
    ttl_seconds=300,
    input_tokens=100,
    output_tokens=500,
    cache_read=800,
    cache_creation=200,
    ephemeral_5m=200,
    ephemeral_1h=None,
):
    """Return a one-line anthropic_cache_telemetry event dict.

    Matches the schema emitted by
    wirelang/persona_engine/anthropic_cache.py::CacheTelemetry.to_struct
    ured_log_dict.
    """
    affinity = f"anthropic:{model}:{persona_id}:{v907_pin}:ttl{ttl_seconds}"
    total = input_tokens + cache_read + cache_creation
    hit_rate = cache_read / total if total > 0 else 0.0
    return {
        "event": "anthropic_cache_telemetry",
        "cache_affinity_key": affinity,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_creation,
        "total_input_tokens": total,
        "cache_hit_rate_input_only": hit_rate,
        "cache_ephemeral_5m_input_tokens": ephemeral_5m,
        "cache_ephemeral_1h_input_tokens": ephemeral_1h,
    }


# ---------------------------------------------------------------------------
# Vector 1 — parse_cache_affinity_key happy path
# ---------------------------------------------------------------------------


def test_parse_cache_affinity_key_happy_path():
    key = "anthropic:claude-opus-4-7[1m]:kai:abc123:ttl300"
    assert agg.parse_cache_affinity_key(key) == ("claude-opus-4-7[1m]", "kai")


# ---------------------------------------------------------------------------
# Vector 2 — parse_cache_affinity_key rejects non-Anthropic prefix
# ---------------------------------------------------------------------------


def test_parse_cache_affinity_key_rejects_other_provider():
    assert agg.parse_cache_affinity_key("openai:gpt-4:kai:abc:ttl300") is None


# ---------------------------------------------------------------------------
# Vector 3 — parse_cache_affinity_key rejects malformed shape
# ---------------------------------------------------------------------------


def test_parse_cache_affinity_key_rejects_short_shape():
    assert agg.parse_cache_affinity_key("anthropic:opus:kai") is None
    assert agg.parse_cache_affinity_key("") is None
    assert agg.parse_cache_affinity_key(None) is None


# ---------------------------------------------------------------------------
# Vector 4 — parse_cache_affinity_key rejects missing ttl marker
# ---------------------------------------------------------------------------


def test_parse_cache_affinity_key_rejects_missing_ttl_marker():
    assert (
        agg.parse_cache_affinity_key("anthropic:opus:kai:pin:notatll")
        is None
    )


# ---------------------------------------------------------------------------
# Vector 5 — aggregate_cache_telemetry: single event
# ---------------------------------------------------------------------------


def test_aggregate_single_event():
    rec = make_cache_event()
    result = agg.aggregate_cache_telemetry([rec])
    key = ("kai", "claude-opus-4-7[1m]")
    assert key in result
    bucket = result[key]
    assert bucket["input_tokens"] == 100
    assert bucket["cache_read_input_tokens"] == 800
    assert bucket["cache_creation_input_tokens"] == 200
    assert bucket["cache_ephemeral_5m_input_tokens"] == 200
    assert bucket["cache_ephemeral_1h_input_tokens"] == 0  # null -> 0 accumulator
    assert bucket["event_count"] == 1
    assert bucket["last_hit_rate_input_only"] == pytest.approx(800 / 1100)


# ---------------------------------------------------------------------------
# Vector 6 — aggregate_cache_telemetry: cumulative across events
# ---------------------------------------------------------------------------


def test_aggregate_cumulative_across_events():
    rec1 = make_cache_event(cache_read=800, cache_creation=200)
    rec2 = make_cache_event(cache_read=1000, cache_creation=0)
    result = agg.aggregate_cache_telemetry([rec1, rec2])
    bucket = result[("kai", "claude-opus-4-7[1m]")]
    assert bucket["cache_read_input_tokens"] == 1800
    assert bucket["cache_creation_input_tokens"] == 200
    assert bucket["event_count"] == 2
    # Last event's hit-rate is the one retained.
    assert bucket["last_hit_rate_input_only"] == pytest.approx(
        1000 / (100 + 1000 + 0)
    )


# ---------------------------------------------------------------------------
# Vector 7 — aggregate_cache_telemetry: ignores non-event records
# ---------------------------------------------------------------------------


def test_aggregate_ignores_non_event_records():
    rec = {"msg": "otel-metric", "metric_name": "persona_engine.spawn.latency_seconds"}
    result = agg.aggregate_cache_telemetry([rec])
    assert result == {}


# ---------------------------------------------------------------------------
# Vector 8 — aggregate_cache_telemetry: ignores malformed affinity key
# ---------------------------------------------------------------------------


def test_aggregate_ignores_malformed_affinity_key():
    rec = make_cache_event()
    rec["cache_affinity_key"] = "broken-key"
    result = agg.aggregate_cache_telemetry([rec])
    assert result == {}


# ---------------------------------------------------------------------------
# Vector 9 — aggregate_cache_telemetry: distinct personas separate
# ---------------------------------------------------------------------------


def test_aggregate_distinct_personas_separate():
    rec1 = make_cache_event(persona_id="kai")
    rec2 = make_cache_event(persona_id="tomas")
    result = agg.aggregate_cache_telemetry([rec1, rec2])
    assert ("kai", "claude-opus-4-7[1m]") in result
    assert ("tomas", "claude-opus-4-7[1m]") in result


# ---------------------------------------------------------------------------
# Vector 10 — aggregate_cache_telemetry: distinct models separate
# ---------------------------------------------------------------------------


def test_aggregate_distinct_models_separate():
    rec1 = make_cache_event(model="claude-opus-4-7[1m]")
    rec2 = make_cache_event(model="claude-haiku-4-5-20251001")
    result = agg.aggregate_cache_telemetry([rec1, rec2])
    assert ("kai", "claude-opus-4-7[1m]") in result
    assert ("kai", "claude-haiku-4-5-20251001") in result


# ---------------------------------------------------------------------------
# Vector 11 — compute_window_average_hit_rate happy path
# ---------------------------------------------------------------------------


def test_compute_window_average_hit_rate_happy():
    bucket = agg._empty_bucket()
    bucket["input_tokens"] = 100
    bucket["cache_read_input_tokens"] = 800
    bucket["cache_creation_input_tokens"] = 200
    rate = agg.compute_window_average_hit_rate(bucket)
    assert rate == pytest.approx(800 / 1100)


# ---------------------------------------------------------------------------
# Vector 12 — compute_window_average_hit_rate: zero-denominator -> 0.0
# ---------------------------------------------------------------------------


def test_compute_window_average_hit_rate_zero_denominator():
    bucket = agg._empty_bucket()
    rate = agg.compute_window_average_hit_rate(bucket)
    assert rate == 0.0


# ---------------------------------------------------------------------------
# Vector 13 — render_textfile emits all expected gauges
# ---------------------------------------------------------------------------


def test_render_textfile_emits_all_gauges():
    rec = make_cache_event()
    per_tuple = agg.aggregate_cache_telemetry([rec])
    payload = agg.render_textfile(
        per_tuple=per_tuple,
        records_consumed=1,
        now_unixtime=1700000000,
    )
    expected_metrics = [
        "wakir_cache_hit_rate_input_only",
        "wakir_cache_hit_rate_window_average",
        "wakir_cache_read_input_tokens_total",
        "wakir_cache_creation_input_tokens_total",
        "wakir_cache_ephemeral_5m_input_tokens_total",
        "wakir_cache_ephemeral_1h_input_tokens_total",
        "wakir_cache_telemetry_event_count_total",
        "wakir_cache_aggregator_records_consumed_total",
        "wakir_cache_aggregator_last_run_unixtime",
    ]
    for metric in expected_metrics:
        assert f"# HELP {metric}" in payload
        assert f"# TYPE {metric} gauge" in payload


# ---------------------------------------------------------------------------
# Vector 14 — render_textfile sorts rows stably by label set
# ---------------------------------------------------------------------------


def test_render_textfile_sorts_rows_stably():
    rec_kai = make_cache_event(persona_id="kai")
    rec_tomas = make_cache_event(persona_id="tomas")
    per_tuple = agg.aggregate_cache_telemetry([rec_tomas, rec_kai])
    payload = agg.render_textfile(
        per_tuple=per_tuple,
        records_consumed=2,
        now_unixtime=1700000000,
    )
    lines = [
        l
        for l in payload.splitlines()
        if l.startswith("wakir_cache_hit_rate_input_only{")
    ]
    assert len(lines) == 2
    assert "kai" in lines[0]
    assert "tomas" in lines[1]


# ---------------------------------------------------------------------------
# Vector 15 — render_textfile zero-row blocks still have HELP/TYPE
# ---------------------------------------------------------------------------


def test_render_textfile_zero_row_blocks_still_have_help_type():
    payload = agg.render_textfile(
        per_tuple={},
        records_consumed=0,
        now_unixtime=1700000000,
    )
    assert "# HELP wakir_cache_hit_rate_input_only" in payload
    assert "wakir_cache_aggregator_last_run_unixtime 1700000000.0" in payload
    assert "wakir_cache_aggregator_records_consumed_total 0.0" in payload


# ---------------------------------------------------------------------------
# Vector 16 — render_textfile escapes label values
# ---------------------------------------------------------------------------


def test_render_textfile_escapes_label_values():
    per_tuple = {
        ('quote"persona', 'back\\slash'): agg._empty_bucket()
    }
    payload = agg.render_textfile(
        per_tuple=per_tuple,
        records_consumed=0,
        now_unixtime=0,
    )
    assert 'persona_id="quote\\"persona"' in payload
    assert 'model="back\\\\slash"' in payload


# ---------------------------------------------------------------------------
# Vector 17 — read_jsonl_tail tolerates missing path (Phase-2a)
# ---------------------------------------------------------------------------


def test_read_jsonl_tail_missing_path_returns_empty(tmp_path):
    missing = tmp_path / "x.jsonl"
    assert agg.read_jsonl_tail(missing) == []


# ---------------------------------------------------------------------------
# Vector 18 — read_jsonl_tail rejects directory with TelemetryError
# ---------------------------------------------------------------------------


def test_read_jsonl_tail_directory_raises(tmp_path):
    d = tmp_path / "directory"
    d.mkdir()
    with pytest.raises(agg.TelemetryError):
        agg.read_jsonl_tail(d)


# ---------------------------------------------------------------------------
# Vector 19 — read_jsonl_tail honours max_records tail bound
# ---------------------------------------------------------------------------


def test_read_jsonl_tail_honours_max_records(tmp_path):
    p = tmp_path / "x.jsonl"
    lines = [json.dumps({"i": i}) for i in range(10)]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tail = agg.read_jsonl_tail(p, max_records=3)
    assert tail == [{"i": 7}, {"i": 8}, {"i": 9}]


# ---------------------------------------------------------------------------
# Vector 20 — atomic_write replaces atomically
# ---------------------------------------------------------------------------


def test_atomic_write_replaces_atomically(tmp_path):
    target = tmp_path / "sub" / "x.prom"
    agg.atomic_write(target, "a 1\n")
    assert target.read_text(encoding="utf-8") == "a 1\n"
    agg.atomic_write(target, "a 2\n")
    assert target.read_text(encoding="utf-8") == "a 2\n"


# ---------------------------------------------------------------------------
# Vector 21 — main() happy path returns 0
# ---------------------------------------------------------------------------


def test_main_happy_path_returns_zero(tmp_path):
    log = tmp_path / "pe.jsonl"
    log.write_text(json.dumps(make_cache_event()) + "\n", encoding="utf-8")
    out = tmp_path / "out.prom"
    rc = agg.main(
        [
            "--persona-engine-log",
            str(log),
            "--textfile-output",
            str(out),
            "--now",
            "1700000000",
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "wakir_cache_hit_rate_input_only{model=" in text
    assert "kai" in text


# ---------------------------------------------------------------------------
# Vector 22 — main() dry-run does not write
# ---------------------------------------------------------------------------


def test_main_dry_run_does_not_write(tmp_path, capsys):
    log = tmp_path / "pe.jsonl"
    log.write_text(json.dumps(make_cache_event()) + "\n", encoding="utf-8")
    out = tmp_path / "out.prom"
    rc = agg.main(
        [
            "--persona-engine-log",
            str(log),
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
    assert "wakir_cache_hit_rate_input_only" in captured.out


# ---------------------------------------------------------------------------
# Vector 23 — main() error path on directory-as-path returns 1
# ---------------------------------------------------------------------------


def test_main_directory_path_returns_one(tmp_path):
    d = tmp_path / "dir"
    d.mkdir()
    rc = agg.main(
        [
            "--persona-engine-log",
            str(d),
            "--textfile-output",
            str(tmp_path / "out.prom"),
            "--now",
            "1700000000",
        ]
    )
    assert rc == 1


# ---------------------------------------------------------------------------
# Vector 24 — end-to-end cache-creation-vs-savings posture is preserved
# ---------------------------------------------------------------------------


def test_end_to_end_cache_creation_vs_savings_preserved(tmp_path):
    """Verify the cost-savings ledger is faithfully aggregated.

    Three events for the same (persona, model): one cold-start (only
    cache_creation), one warm (only cache_read), one mixed.
    """
    cold = make_cache_event(cache_read=0, cache_creation=1000, input_tokens=0)
    warm = make_cache_event(cache_read=900, cache_creation=0, input_tokens=100)
    mixed = make_cache_event(
        cache_read=500, cache_creation=100, input_tokens=50
    )
    result = agg.aggregate_cache_telemetry([cold, warm, mixed])
    bucket = result[("kai", "claude-opus-4-7[1m]")]
    assert bucket["cache_read_input_tokens"] == 1400
    assert bucket["cache_creation_input_tokens"] == 1100
    assert bucket["event_count"] == 3
    window_avg = agg.compute_window_average_hit_rate(bucket)
    # 1400 / (1400 + 1100 + 150) = 1400/2650
    assert window_avg == pytest.approx(1400 / 2650)
