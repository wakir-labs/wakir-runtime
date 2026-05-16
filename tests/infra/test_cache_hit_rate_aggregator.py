# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/cache-hit-rate-aggregator.py — Sprint-Phase-2b MINI.

Hermetic — no real persona-engine, no real textfile-collector
directory. Drives the aggregator's public functions against
fabricated structured-JSON log fixtures and asserts:

  - The ``anthropic_cache_telemetry`` event shape (Selin PR #97)
    round-trips through token extraction.
  - Per-(persona, model) separation is correct (Tomas + Selin,
    Opus + Sonnet stay isolated even when they share a model).
  - The cache-hit-rate math is token-weighted and consistent with
    ``CacheTelemetry.cache_hit_rate_input_only`` semantics.
  - Cost-savings vs. cache-creation premium follow the ADR-0064
    pricing table (~90% discount on cached reads, 25% premium on
    cache-creation tokens, 5-min ephemeral slot).
  - Bilance is savings minus creation cost; positive => caching net-
    positive, negative => paying premium without enough reads.
  - The Prometheus exposition format renders the documented gauge
    schema with correct label escaping (persona + model).
  - Records that are not ``anthropic_cache_telemetry`` events are
    skipped (request-built / span / FSM / cost-only).

The aggregator script is stdlib-only and lives outside the
python package tree under ``scripts/``. We import it via
importlib.util so the hyphenated filename stays legal.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Import the aggregator script as a module
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_PATH = REPO_ROOT / "scripts" / "cache-hit-rate-aggregator.py"


def _load_aggregator_module():
    spec = importlib.util.spec_from_file_location(
        "cache_hit_rate_aggregator", AGGREGATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


aggregator = _load_aggregator_module()


# ---------------------------------------------------------------------------
# Log fixture factories
# ---------------------------------------------------------------------------


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
    """Mirror CacheTelemetry.to_structured_log_dict (Selin PR #97).

    Carries the ``event`` discriminator + the affinity-key shape that
    embeds (model, persona, v907_pin, ttl) so the aggregator resolves
    both ids from a single field.
    """
    total_input = (
        input_tokens + cache_read_input_tokens + cache_creation_input_tokens
    )
    hit_rate = (
        cache_read_input_tokens / total_input if total_input > 0 else 0.0
    )
    return {
        "event": "anthropic_cache_telemetry",
        "cache_affinity_key": (
            f"anthropic:{model}:{persona}:{v907_pin}:ttl{ttl_seconds}"
        ),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cache_read_input_tokens,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "total_input_tokens": total_input,
        "cache_hit_rate_input_only": hit_rate,
        "cache_ephemeral_5m_input_tokens": cache_creation_input_tokens,
        "cache_ephemeral_1h_input_tokens": 0,
    }


def write_log(tmp_path: Path, records: list) -> Path:
    """Materialise records as JSON-lines into a tmp log file."""
    p = tmp_path / "persona-engine.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return p


# ---------------------------------------------------------------------------
# Test 1: is_cache_telemetry_record — event discriminator
# ---------------------------------------------------------------------------


def test_is_cache_telemetry_record_recognises_event():
    rec = telemetry_record()
    assert aggregator.is_cache_telemetry_record(rec) is True


def test_is_cache_telemetry_record_rejects_other_events():
    rec = {
        "event": "anthropic_request_built",
        "model": "claude-opus-4-7",
        "input_tokens": 100,
    }
    assert aggregator.is_cache_telemetry_record(rec) is False


def test_is_cache_telemetry_record_rejects_span_records():
    """An otel-span record with no event field is not a cache telemetry."""
    rec = {
        "msg": "otel-span",
        "span_name": "persona_engine.spawn",
        "duration_seconds": 1.0,
    }
    assert aggregator.is_cache_telemetry_record(rec) is False


# ---------------------------------------------------------------------------
# Test 2: extract_persona_and_model — affinity-key parsing
# ---------------------------------------------------------------------------


def test_extract_persona_and_model_from_affinity_key():
    rec = telemetry_record(model="claude-sonnet-4-6", persona="selin")
    persona, model = aggregator.extract_persona_and_model(rec)
    assert persona == "selin"
    assert model == "claude-sonnet-4-6"


def test_extract_persona_and_model_unknown_falls_back():
    """A record with neither affinity-key nor explicit fields lands in
    the unknown sentinel buckets, not in a real persona/model row."""
    rec = {"event": "anthropic_cache_telemetry", "input_tokens": 10}
    persona, model = aggregator.extract_persona_and_model(rec)
    assert persona == aggregator.PERSONA_UNKNOWN_BUCKET
    assert model == aggregator.MODEL_UNKNOWN_BUCKET


def test_extract_persona_and_model_direct_keys_override_affinity():
    """Explicit ``model`` / ``persona`` top-level keys win over the
    affinity-key derivation (request-side records carry both)."""
    rec = {
        "event": "anthropic_cache_telemetry",
        "cache_affinity_key": (
            "anthropic:claude-sonnet-4-6:selin:v907-pin-xy:ttl300"
        ),
        "model": "claude-opus-4-7",
        "persona": "tomas",
    }
    persona, model = aggregator.extract_persona_and_model(rec)
    assert persona == "tomas"
    assert model == "claude-opus-4-7"


# ---------------------------------------------------------------------------
# Test 3: extract_cache_envelope — token shape
# ---------------------------------------------------------------------------


def test_extract_cache_envelope_full_shape():
    rec = telemetry_record(
        input_tokens=100,
        cache_read_input_tokens=400,
        cache_creation_input_tokens=50,
    )
    env = aggregator.extract_cache_envelope(rec)
    assert env == {
        "input_tokens": 100,
        "cache_read_input_tokens": 400,
        "cache_creation_input_tokens": 50,
        "total_input_tokens": 550,
    }


def test_extract_cache_envelope_recomputes_total_defensive():
    """If a hand-crafted log fixture carries a stale total, the
    aggregator re-derives it from the three components so the rate
    stays consistent with the displayed counts."""
    rec = {
        "event": "anthropic_cache_telemetry",
        "input_tokens": 100,
        "cache_read_input_tokens": 200,
        "cache_creation_input_tokens": 50,
        "total_input_tokens": 999_999,  # stale / drift
    }
    env = aggregator.extract_cache_envelope(rec)
    assert env["total_input_tokens"] == 350


def test_extract_cache_envelope_returns_none_for_no_token_fields():
    rec = {"event": "anthropic_cache_telemetry"}
    assert aggregator.extract_cache_envelope(rec) is None


# ---------------------------------------------------------------------------
# Test 4: compute_cache_savings_and_cost — ADR-0064 pricing
# ---------------------------------------------------------------------------


def test_cache_read_savings_opus_one_mtok():
    """1M cache-read on Opus: paid 1.50 USD, would have paid 15 USD
    uncached, so savings = 13.50 USD."""
    savings, creation = aggregator.compute_cache_savings_and_cost(
        model_id="claude-opus-4-7",
        cache_read_input_tokens=1_000_000,
        cache_creation_input_tokens=0,
    )
    assert savings == pytest.approx(13.50)
    assert creation == pytest.approx(0.0)


def test_cache_creation_premium_opus_one_mtok():
    """1M cache-creation on Opus: 1.25 * 15 = 18.75 USD."""
    savings, creation = aggregator.compute_cache_savings_and_cost(
        model_id="claude-opus-4-7",
        cache_read_input_tokens=0,
        cache_creation_input_tokens=1_000_000,
    )
    assert savings == pytest.approx(0.0)
    assert creation == pytest.approx(18.75)


def test_cache_savings_haiku_lower_than_opus():
    """The pricing-spread invariant: same token count, Haiku savings
    must be strictly smaller than Opus (Haiku input rate is lower)."""
    opus_savings, _ = aggregator.compute_cache_savings_and_cost(
        model_id="claude-opus-4-7",
        cache_read_input_tokens=1_000_000,
        cache_creation_input_tokens=0,
    )
    haiku_savings, _ = aggregator.compute_cache_savings_and_cost(
        model_id="claude-haiku-4-5",
        cache_read_input_tokens=1_000_000,
        cache_creation_input_tokens=0,
    )
    assert haiku_savings < opus_savings
    # 1M * 0.80 * 0.90 = 0.72 USD
    assert haiku_savings == pytest.approx(0.72)


def test_cache_unknown_model_returns_zero_savings_and_cost():
    savings, creation = aggregator.compute_cache_savings_and_cost(
        model_id="claude-future-5-0",
        cache_read_input_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
    )
    assert savings == 0.0
    assert creation == 0.0


# ---------------------------------------------------------------------------
# Test 5: aggregate_records — per (persona, model) separation
# ---------------------------------------------------------------------------


def test_aggregate_records_separates_persona_model_pairs():
    """Same model, different personas => two buckets."""
    records = [
        telemetry_record(
            model="claude-opus-4-7",
            persona="tomas",
            input_tokens=100,
            cache_read_input_tokens=900,
        ),
        telemetry_record(
            model="claude-opus-4-7",
            persona="selin",
            input_tokens=200,
            cache_read_input_tokens=800,
        ),
    ]
    buckets = aggregator.aggregate_records(records)
    assert ("tomas", "claude-opus-4-7") in buckets
    assert ("selin", "claude-opus-4-7") in buckets
    assert (
        buckets[("tomas", "claude-opus-4-7")]["cache_read_input_tokens"]
        == 900
    )
    assert (
        buckets[("selin", "claude-opus-4-7")]["cache_read_input_tokens"]
        == 800
    )


def test_aggregate_records_separates_models_for_one_persona():
    """Same persona, different models => two buckets."""
    records = [
        telemetry_record(
            model="claude-opus-4-7",
            persona="noa",
            input_tokens=100,
        ),
        telemetry_record(
            model="claude-sonnet-4-6",
            persona="noa",
            input_tokens=200,
        ),
    ]
    buckets = aggregator.aggregate_records(records)
    assert ("noa", "claude-opus-4-7") in buckets
    assert ("noa", "claude-sonnet-4-6") in buckets


def test_aggregate_records_hit_rate_token_weighted():
    """Hit rate is token-weighted across all records in a bucket, not
    a mean of per-record rates. Two records:
      A: 100 input + 900 cache-read => rate = 0.9
      B: 900 input + 100 cache-read => rate = 0.1
    Mean of rates: 0.5. Token-weighted: 1000 / 2000 = 0.5 here too —
    so to disambiguate we use a 1:9 weight split.
    """
    records = [
        telemetry_record(
            model="claude-opus-4-7",
            persona="tomas",
            input_tokens=10,
            cache_read_input_tokens=90,
        ),  # tiny record, 90% hit
        telemetry_record(
            model="claude-opus-4-7",
            persona="tomas",
            input_tokens=900,
            cache_read_input_tokens=100,
        ),  # large record, 10% hit
    ]
    buckets = aggregator.aggregate_records(records)
    b = buckets[("tomas", "claude-opus-4-7")]
    # cache_read total = 190; total_input = 100 + 1000 = 1100 -> rate ~ 0.1727
    assert b["cache_hit_rate"] == pytest.approx(190 / 1100)
    # If this were a mean of per-record rates we would get
    # (0.9 + 0.1) / 2 = 0.5 — guard against that regression.
    assert b["cache_hit_rate"] < 0.4


def test_aggregate_records_bilance_positive_when_read_dominant():
    """Heavy cache-read, minimal creation => bilance must be positive."""
    records = [
        telemetry_record(
            model="claude-opus-4-7",
            persona="tomas",
            input_tokens=0,
            cache_read_input_tokens=1_000_000,
            cache_creation_input_tokens=10_000,
        ),
    ]
    buckets = aggregator.aggregate_records(records)
    b = buckets[("tomas", "claude-opus-4-7")]
    # savings ~ 13.50; creation_cost ~ 0.1875; bilance ~ 13.31
    assert b["cache_bilance_usd"] > 13.0
    assert b["cache_read_savings_usd"] > b["cache_creation_cost_usd"]


def test_aggregate_records_bilance_negative_when_creation_dominant():
    """Pure cache-creation, no read => bilance is the full negative
    creation cost (we paid the premium and never read it back)."""
    records = [
        telemetry_record(
            model="claude-opus-4-7",
            persona="selin",
            input_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=1_000_000,
        ),
    ]
    buckets = aggregator.aggregate_records(records)
    b = buckets[("selin", "claude-opus-4-7")]
    assert b["cache_read_savings_usd"] == pytest.approx(0.0)
    assert b["cache_creation_cost_usd"] == pytest.approx(18.75)
    assert b["cache_bilance_usd"] == pytest.approx(-18.75)


def test_aggregate_records_skips_non_telemetry_events():
    """Records that are not anthropic_cache_telemetry are ignored —
    we only see response-side cache events, not request-built or span
    or per-model-cost-aggregator records."""
    records = [
        {
            "event": "anthropic_request_built",
            "model": "claude-opus-4-7",
            "input_tokens": 1_000_000,
        },
        {
            "msg": "otel-span",
            "span_name": "persona_engine.spawn",
            "duration_seconds": 1.0,
        },
        telemetry_record(
            model="claude-opus-4-7",
            persona="tomas",
            input_tokens=100,
        ),
    ]
    buckets = aggregator.aggregate_records(records)
    assert list(buckets.keys()) == [("tomas", "claude-opus-4-7")]


def test_aggregate_records_unknown_model_isolated():
    """Records with no resolvable model land in the unknown bucket and
    have zero USD (pricing miss), preserving the token gauges for drift
    detection."""
    rec = {
        "event": "anthropic_cache_telemetry",
        "cache_affinity_key": (
            "anthropic:claude-future-5-0:tomas:v907-pin-xy:ttl300"
        ),
        "input_tokens": 0,
        "cache_read_input_tokens": 1_000_000,
        "cache_creation_input_tokens": 0,
    }
    buckets = aggregator.aggregate_records([rec])
    b = buckets[("tomas", "claude-future-5-0")]
    assert b["cache_read_input_tokens"] == 1_000_000
    assert b["cache_read_savings_usd"] == 0.0
    assert b["cache_creation_cost_usd"] == 0.0


# ---------------------------------------------------------------------------
# Test 6: render_textfile — Prometheus exposition format
# ---------------------------------------------------------------------------


def test_render_textfile_emits_all_nine_metrics():
    buckets = {
        ("tomas", "claude-opus-4-7"): {
            "input_tokens": 100,
            "cache_read_input_tokens": 200,
            "cache_creation_input_tokens": 30,
            "total_input_tokens": 330,
            "cache_hit_rate": 200 / 330,
            "cache_read_savings_usd": 0.0027,
            "cache_creation_cost_usd": 0.0005625,
            "cache_bilance_usd": 0.00213,
            "record_count": 3,
        },
    }
    out = aggregator.render_textfile(buckets, scrape_ts_utc=1715875200)
    expected_metrics = [
        "persona_engine_cache_input_tokens_total",
        "persona_engine_cache_read_tokens_total",
        "persona_engine_cache_creation_tokens_total",
        "persona_engine_cache_total_input_tokens",
        "persona_engine_cache_hit_rate",
        "persona_engine_cache_read_savings_usd",
        "persona_engine_cache_creation_cost_usd",
        "persona_engine_cache_bilance_usd",
        "persona_engine_cache_record_count_total",
        "persona_engine_cache_scrape_timestamp_seconds",
    ]
    for metric in expected_metrics:
        assert f"# HELP {metric}" in out
        assert f"# TYPE {metric} gauge" in out


def test_render_textfile_persona_and_model_labels_both_present():
    buckets = {
        ("selin", "claude-sonnet-4-6"): {
            "input_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "total_input_tokens": 1,
            "cache_hit_rate": 0.0,
            "cache_read_savings_usd": 0.0,
            "cache_creation_cost_usd": 0.0,
            "cache_bilance_usd": 0.0,
            "record_count": 1,
        },
    }
    out = aggregator.render_textfile(buckets, scrape_ts_utc=1715875200)
    assert (
        'persona_engine_cache_input_tokens_total'
        '{persona="selin",model="claude-sonnet-4-6"} 1'
    ) in out


def test_render_textfile_stable_ordering():
    """(persona, model) tuples sort lexicographically — keeps the diff
    deterministic for golden-file regression."""
    buckets = {
        ("tomas", "claude-sonnet-4-6"): {
            "input_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "total_input_tokens": 1,
            "cache_hit_rate": 0.0,
            "cache_read_savings_usd": 0.0,
            "cache_creation_cost_usd": 0.0,
            "cache_bilance_usd": 0.0,
            "record_count": 1,
        },
        ("selin", "claude-opus-4-7"): {
            "input_tokens": 2,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "total_input_tokens": 2,
            "cache_hit_rate": 0.0,
            "cache_read_savings_usd": 0.0,
            "cache_creation_cost_usd": 0.0,
            "cache_bilance_usd": 0.0,
            "record_count": 1,
        },
    }
    out = aggregator.render_textfile(buckets, scrape_ts_utc=1715875200)
    selin_pos = out.find('persona="selin",model="claude-opus-4-7"')
    tomas_pos = out.find('persona="tomas",model="claude-sonnet-4-6"')
    assert selin_pos != -1 and tomas_pos != -1
    # 'selin' < 'tomas' lexicographically.
    assert selin_pos < tomas_pos


def test_render_textfile_label_escaping():
    """Backslash and double-quote in persona / model id are escaped."""
    buckets = {
        ('weird"\\persona', "claude-opus-4-7"): {
            "input_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "total_input_tokens": 1,
            "cache_hit_rate": 0.0,
            "cache_read_savings_usd": 0.0,
            "cache_creation_cost_usd": 0.0,
            "cache_bilance_usd": 0.0,
            "record_count": 1,
        },
    }
    out = aggregator.render_textfile(buckets, scrape_ts_utc=1715875200)
    assert 'persona="weird\\"\\\\persona",model="claude-opus-4-7"' in out


def test_render_textfile_hit_rate_renders_as_float():
    """A 0.5 hit rate must render as ``0.5``, not as ``0`` (the
    integer-collapsing helper must not eat fractional rates)."""
    buckets = {
        ("tomas", "claude-opus-4-7"): {
            "input_tokens": 500,
            "cache_read_input_tokens": 500,
            "cache_creation_input_tokens": 0,
            "total_input_tokens": 1000,
            "cache_hit_rate": 0.5,
            "cache_read_savings_usd": 0.00675,
            "cache_creation_cost_usd": 0.0,
            "cache_bilance_usd": 0.00675,
            "record_count": 1,
        },
    }
    out = aggregator.render_textfile(buckets, scrape_ts_utc=1715875200)
    assert (
        'persona_engine_cache_hit_rate{persona="tomas",model="claude-opus-4-7"} 0.5'
    ) in out


def test_render_textfile_scrape_timestamp_present():
    out = aggregator.render_textfile({}, scrape_ts_utc=1715875200)
    assert (
        "persona_engine_cache_scrape_timestamp_seconds 1715875200"
    ) in out


def test_render_textfile_empty_buckets_still_carries_schema():
    """Cold-start: even with zero records the HELP/TYPE lines and the
    scrape timestamp are emitted so Prometheus does not flap."""
    out = aggregator.render_textfile({}, scrape_ts_utc=1715875200)
    assert "# HELP persona_engine_cache_hit_rate" in out
    assert "# TYPE persona_engine_cache_bilance_usd gauge" in out


# ---------------------------------------------------------------------------
# Test 7: end-to-end main — log read + textfile write
# ---------------------------------------------------------------------------


def test_main_writes_textfile_atomically(tmp_path):
    log_path = write_log(
        tmp_path,
        [
            telemetry_record(
                model="claude-opus-4-7",
                persona="tomas",
                input_tokens=0,
                cache_read_input_tokens=1_000_000,
                cache_creation_input_tokens=0,
            ),
            telemetry_record(
                model="claude-sonnet-4-6",
                persona="selin",
                input_tokens=0,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=1_000_000,
            ),
        ],
    )
    out_path = tmp_path / "out" / "cache_hit_rate.prom"
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
    # 1M cache-read on Opus => 13.50 USD savings.
    assert (
        'persona_engine_cache_read_savings_usd'
        '{persona="tomas",model="claude-opus-4-7"} 13.5'
    ) in payload
    # 1M cache-creation on Sonnet => 3 * 1.25 = 3.75 USD creation cost.
    assert (
        'persona_engine_cache_creation_cost_usd'
        '{persona="selin",model="claude-sonnet-4-6"} 3.75'
    ) in payload


def test_main_dry_run_does_not_write(tmp_path, capsys):
    log_path = write_log(
        tmp_path,
        [
            telemetry_record(
                model="claude-haiku-4-5",
                persona="tomas",
                input_tokens=0,
                cache_read_input_tokens=1_000_000,
            ),
        ],
    )
    out_path = tmp_path / "out" / "cache_hit_rate.prom"
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
    assert "persona_engine_cache_hit_rate" in captured.out


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
                persona="tomas",
                input_tokens=100,
                cache_read_input_tokens=900,
            ),
        ],
    )
    out_path = tmp_path / "out" / "cache_hit_rate.prom"
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
                    persona="tomas",
                    input_tokens=0,
                    cache_read_input_tokens=1_000_000,
                ),
                sort_keys=True,
            )
            + "\n"
        )
        fh.write("{partial: ")  # truncated
    out_path = tmp_path / "out" / "cache_hit_rate.prom"
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
        'persona_engine_cache_read_savings_usd'
        '{persona="tomas",model="claude-opus-4-7"} 13.5'
    ) in payload


# ---------------------------------------------------------------------------
# Test 8: pricing-table parity with per-model-cost-aggregator
# ---------------------------------------------------------------------------


def test_pricing_table_covers_phase_2a_models():
    """The cache aggregator's pricing table must carry the same three
    models that the cost aggregator uses, else cache-savings drift
    versus cost gauges silently when the cost table is updated."""
    assert "claude-haiku-4-5" in aggregator.MODEL_PRICING
    assert "claude-sonnet-4-6" in aggregator.MODEL_PRICING
    assert "claude-opus-4-7" in aggregator.MODEL_PRICING


def test_pricing_table_matches_cost_aggregator():
    """Cross-aggregator parity guard: load the cost aggregator's
    pricing table and assert each entry matches. If a future ADR rev
    splits the tables this test breaks loudly so we update both
    aggregators atomically."""
    import importlib.util as _il

    cost_path = REPO_ROOT / "scripts" / "per-model-cost-aggregator.py"
    spec = _il.spec_from_file_location("_cost_agg", cost_path)
    assert spec is not None and spec.loader is not None
    cost_mod = _il.module_from_spec(spec)
    spec.loader.exec_module(cost_mod)
    for model_id, entry in aggregator.MODEL_PRICING.items():
        cost_entry = cost_mod.MODEL_PRICING.get(model_id)
        assert cost_entry is not None, (
            f"model {model_id} missing from cost-aggregator pricing"
        )
        assert (
            entry["input_usd_per_mtok"]
            == cost_entry["input_usd_per_mtok"]
        )
        assert (
            entry["output_usd_per_mtok"]
            == cost_entry["output_usd_per_mtok"]
        )
        assert (
            entry["cache_read_multiplier"]
            == cost_entry["cache_read_multiplier"]
        )
        assert (
            entry["cache_creation_multiplier"]
            == cost_entry["cache_creation_multiplier"]
        )
