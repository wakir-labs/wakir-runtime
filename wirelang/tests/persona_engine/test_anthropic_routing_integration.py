# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for anthropic-call production-mode routing integration.

ADR-0064 Phase-2b — Sprint Tag-15 mini-welle.

Test coverage matrix:

1.  ``read_production_routing_mode``: default + all four modes + unknown
2.  ``static`` mode is a no-op: tier comes from persona-def, no router
    is invoked, jsonl sink disabled by default → no I/O
3.  ``heuristic`` mode, very-short prose → Haiku class
4.  ``heuristic`` mode, audit-persona override → Opus class
5.  ``heuristic`` mode, very-long prompt → Opus class
6.  ``heuristic`` mode, code-heavy mid-length → Sonnet class
7.  ``llm_classifier`` mode: above-threshold classifier → honoured
8.  ``llm_classifier_fallback_heuristic``: classifier raises → fallback
    to heuristic decision; ``used_fallback`` + ``fallback_reason`` set
9.  Metric-emission disabled (env unset) → no file written; decision
    still returned correctly
10. Metric-emission enabled → JSONL line written with all required
    fields; multiple calls append, byte-stable key ordering
11. ``map_tier_to_model_id`` returns the configured Anthropic model-id
    for each tier; unknown tier raises ValueError
12. ``anthropic_call`` invokes the backend with the decided model-id
    (end-to-end smoke); ``MockAnthropicBackend`` records the request
13. JSONL sink swallows file-write errors gracefully (unwritable path)
14. ``set_tier_model_mapping`` validates full tier coverage
15. ``static`` mode without static_choice → fallback to heuristic,
    recorded in JSONL when enabled
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

import pytest

from wirelang.persona_engine.anthropic_call import (
    DEFAULT_TIER_MODEL_MAPPING,
    MockAnthropicBackend,
    RoutingDecision,
    WAKIR_ROUTING_DECISION_JSONL_ENV,
    WAKIR_ROUTING_MODE_ENV,
    WAKIR_ROUTING_MODE_HEURISTIC,
    WAKIR_ROUTING_MODE_LLM_CLASSIFIER,
    WAKIR_ROUTING_MODE_LLM_CLASSIFIER_FALLBACK_HEURISTIC,
    WAKIR_ROUTING_MODE_STATIC,
    anthropic_call,
    decide_routing,
    get_tier_model_mapping,
    map_tier_to_model_id,
    read_production_routing_mode,
    reset_tier_model_mapping,
    set_tier_model_mapping,
)
from wirelang.persona_engine.heuristic_router import (
    RouterDecision,
    TOKEN_LEN_OPUS_THRESHOLD,
    CHARS_PER_TOKEN_ESTIMATE,
)
from wirelang.persona_engine.llm_classifier import (
    ClassifierVerdict,
    LlmClassifierRouter,
    MockHaikuClassifierBackend,
)


# ---------------------------------------------------------------------------
# (1) read_production_routing_mode: default + all four modes + unknown
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env,expected",
    [
        ({}, WAKIR_ROUTING_MODE_STATIC),  # default fall-back
        ({WAKIR_ROUTING_MODE_ENV: ""}, WAKIR_ROUTING_MODE_STATIC),
        ({WAKIR_ROUTING_MODE_ENV: "static"}, WAKIR_ROUTING_MODE_STATIC),
        (
            {WAKIR_ROUTING_MODE_ENV: "heuristic"},
            WAKIR_ROUTING_MODE_HEURISTIC,
        ),
        (
            {WAKIR_ROUTING_MODE_ENV: "llm_classifier"},
            WAKIR_ROUTING_MODE_LLM_CLASSIFIER,
        ),
        (
            {
                WAKIR_ROUTING_MODE_ENV: (
                    "llm_classifier_fallback_heuristic"
                )
            },
            WAKIR_ROUTING_MODE_LLM_CLASSIFIER_FALLBACK_HEURISTIC,
        ),
        (
            {WAKIR_ROUTING_MODE_ENV: "  HEURISTIC  "},
            WAKIR_ROUTING_MODE_HEURISTIC,
        ),
        (
            {WAKIR_ROUTING_MODE_ENV: "bogus-unknown-value"},
            WAKIR_ROUTING_MODE_STATIC,
        ),
    ],
)
def test_read_production_routing_mode_table(env, expected):
    assert read_production_routing_mode(env) == expected


# ---------------------------------------------------------------------------
# (2) static mode is a no-op: tier from persona-def, no jsonl I/O
# ---------------------------------------------------------------------------


def test_static_mode_uses_static_choice_no_jsonl(tmp_path):
    # Sink env intentionally unset → no I/O happens.
    decision = decide_routing(
        persona_id="lena",
        auftrag_id="auf-001",
        prompt_payload="Anything here, irrelevant in static mode.",
        static_choice="sonnet",
        env={},  # default mode = static, no jsonl
    )
    assert decision.mode == WAKIR_ROUTING_MODE_STATIC
    assert decision.classified_class == "sonnet"
    assert decision.chosen_model == DEFAULT_TIER_MODEL_MAPPING["sonnet"]
    assert decision.used_fallback is False
    assert decision.fallback_reason is None
    # Nothing should have been written anywhere.
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# (3) heuristic mode, very-short prose → Haiku class
# ---------------------------------------------------------------------------


def test_heuristic_mode_short_prose_classifies_haiku():
    decision = decide_routing(
        persona_id="lena",
        auftrag_id="auf-h-001",
        prompt_payload="hello",
        persona_def={"persona_id": "lena", "role": "frontend"},
        env={WAKIR_ROUTING_MODE_ENV: "heuristic"},
    )
    assert decision.mode == WAKIR_ROUTING_MODE_HEURISTIC
    assert decision.classified_class == RouterDecision.HAIKU.value
    assert decision.chosen_model == DEFAULT_TIER_MODEL_MAPPING["haiku"]


# ---------------------------------------------------------------------------
# (4) heuristic mode, audit-persona override → Opus class
# ---------------------------------------------------------------------------


def test_heuristic_mode_audit_persona_overrides_to_opus():
    decision = decide_routing(
        persona_id="henrik",
        auftrag_id="auf-h-002",
        prompt_payload="short audit ping",
        persona_def={"persona_id": "henrik", "role": "internal-audit"},
        env={WAKIR_ROUTING_MODE_ENV: "heuristic"},
    )
    assert decision.classified_class == RouterDecision.OPUS.value
    assert decision.chosen_model == DEFAULT_TIER_MODEL_MAPPING["opus"]


# ---------------------------------------------------------------------------
# (5) heuristic mode, very-long prompt → Opus class
# ---------------------------------------------------------------------------


def test_heuristic_mode_very_long_prompt_classifies_opus():
    # Build a prompt that crosses the OPUS token threshold.
    long_prompt = "x" * (
        (TOKEN_LEN_OPUS_THRESHOLD + 100) * CHARS_PER_TOKEN_ESTIMATE
    )
    decision = decide_routing(
        persona_id="selin",
        auftrag_id="auf-h-003",
        prompt_payload=long_prompt,
        persona_def={"persona_id": "selin", "role": "pengine"},
        env={WAKIR_ROUTING_MODE_ENV: "heuristic"},
    )
    assert decision.classified_class == RouterDecision.OPUS.value


# ---------------------------------------------------------------------------
# (6) heuristic mode, code-heavy mid-length → Sonnet class
# ---------------------------------------------------------------------------


def test_heuristic_mode_code_heavy_mid_length_classifies_sonnet():
    # Mid-length prompt (~2k tokens) with three code blocks → Sonnet.
    body = "Helper text. " * 600  # ~ 7800 chars ~ 1950 tokens
    code = "```python\nprint('hi')\n```\n"
    prompt = body + code + code + code
    decision = decide_routing(
        persona_id="tomas",
        auftrag_id="auf-h-004",
        prompt_payload=prompt,
        persona_def={"persona_id": "tomas", "role": "dev-engineering"},
        env={WAKIR_ROUTING_MODE_ENV: "heuristic"},
    )
    assert decision.classified_class == RouterDecision.SONNET.value
    assert decision.chosen_model == DEFAULT_TIER_MODEL_MAPPING["sonnet"]


# ---------------------------------------------------------------------------
# (7) llm_classifier mode: above-threshold classifier verdict honoured
# ---------------------------------------------------------------------------


def test_llm_classifier_mode_above_threshold_honoured():
    # Use a short prose prompt → MockHaiku returns ("haiku", 0.90) ≥ 0.8.
    decision = decide_routing(
        persona_id="julia",
        auftrag_id="auf-c-001",
        prompt_payload="short ack",
        persona_def={"persona_id": "lena", "role": "frontend"},
        # Use frontend persona to avoid the routine-comms Haiku-ceiling
        # path; the substrate should still pick Haiku from the very-
        # short-prose mock band.
        env={WAKIR_ROUTING_MODE_ENV: "llm_classifier"},
    )
    assert decision.mode == WAKIR_ROUTING_MODE_LLM_CLASSIFIER
    assert decision.classified_class == RouterDecision.HAIKU.value
    assert decision.used_fallback is False


# ---------------------------------------------------------------------------
# (8) llm_classifier_fallback_heuristic: classifier raises → fallback
# ---------------------------------------------------------------------------


class _RaisingClassifierBackend:
    """Mock backend that always raises — exercises the fallback path."""

    def classify(self, *, prompt_payload, persona_def=None):
        raise RuntimeError("simulated classifier outage")


def test_classifier_fallback_heuristic_on_exception():
    raising_router = LlmClassifierRouter(backend=_RaisingClassifierBackend())
    decision = decide_routing(
        persona_id="lena",
        auftrag_id="auf-fb-001",
        prompt_payload="hi",
        persona_def={"persona_id": "lena", "role": "frontend"},
        classifier_router=raising_router,
        env={
            WAKIR_ROUTING_MODE_ENV: "llm_classifier_fallback_heuristic"
        },
    )
    assert (
        decision.mode
        == WAKIR_ROUTING_MODE_LLM_CLASSIFIER_FALLBACK_HEURISTIC
    )
    # The heuristic-fallback decision for a 2-char prose prompt is Haiku.
    assert decision.classified_class == RouterDecision.HAIKU.value
    assert decision.used_fallback is True
    assert decision.fallback_reason is not None
    assert "RuntimeError" in decision.fallback_reason


# ---------------------------------------------------------------------------
# (9) Metric-emission disabled (env unset) → no file written
# ---------------------------------------------------------------------------


def test_metric_emission_disabled_by_default(tmp_path):
    # No sink env-var → no file should be written even if we offer a
    # path candidate (we just don't pass the env var pointing to it).
    sink_path = tmp_path / "should-not-exist.jsonl"
    decision = decide_routing(
        persona_id="lena",
        auftrag_id="auf-m-001",
        prompt_payload="ping",
        static_choice="sonnet",
        env={},  # no jsonl env-var
    )
    assert decision.classified_class == "sonnet"
    assert not sink_path.exists()


# ---------------------------------------------------------------------------
# (10) Metric-emission enabled → JSONL append with all required fields
# ---------------------------------------------------------------------------


def test_metric_emission_enabled_appends_jsonl(tmp_path):
    sink = tmp_path / "decisions.jsonl"
    env = {
        WAKIR_ROUTING_MODE_ENV: "heuristic",
        WAKIR_ROUTING_DECISION_JSONL_ENV: str(sink),
    }
    decision_one = decide_routing(
        persona_id="selin",
        auftrag_id="auf-m-002",
        prompt_payload="short ping",
        persona_def={"persona_id": "selin", "role": "pengine"},
        ts_utc="2026-05-17T12:00:00Z",
        env=env,
    )
    decision_two = decide_routing(
        persona_id="selin",
        auftrag_id="auf-m-003",
        prompt_payload="another short ping",
        persona_def={"persona_id": "selin", "role": "pengine"},
        ts_utc="2026-05-17T12:00:01Z",
        env=env,
    )
    lines = sink.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    for rec, dec, expected_ts in (
        (records[0], decision_one, "2026-05-17T12:00:00Z"),
        (records[1], decision_two, "2026-05-17T12:00:01Z"),
    ):
        # All required envelope keys present.
        assert set(rec.keys()) >= {
            "timestamp",
            "task_id",
            "mode",
            "classified_class",
            "chosen_model",
            "decision_latency_us",
        }
        assert rec["timestamp"] == expected_ts
        assert rec["mode"] == "heuristic"
        assert rec["classified_class"] == dec.classified_class
        assert rec["chosen_model"] == dec.chosen_model
        assert isinstance(rec["decision_latency_us"], int)
        assert rec["decision_latency_us"] >= 0
    # Byte-stable key ordering: every line must be sorted-key JSON.
    for line in lines:
        parsed = json.loads(line)
        re_serialised = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        assert line == re_serialised


# ---------------------------------------------------------------------------
# (11) map_tier_to_model_id returns Anthropic model-id; unknown → raises
# ---------------------------------------------------------------------------


def test_map_tier_to_model_id_table():
    assert (
        map_tier_to_model_id("haiku") == DEFAULT_TIER_MODEL_MAPPING["haiku"]
    )
    assert (
        map_tier_to_model_id("sonnet") == DEFAULT_TIER_MODEL_MAPPING["sonnet"]
    )
    assert (
        map_tier_to_model_id("opus") == DEFAULT_TIER_MODEL_MAPPING["opus"]
    )
    # Model IDs follow Anthropic's `claude-<tier>-<gen>-<date>` shape.
    for tier in ("haiku", "sonnet", "opus"):
        assert re.match(
            rf"^claude-{tier}-\d", map_tier_to_model_id(tier)
        ), f"model-id for tier {tier!r} does not match Anthropic shape"
    with pytest.raises(ValueError):
        map_tier_to_model_id("turbo-9000")


# ---------------------------------------------------------------------------
# (12) anthropic_call end-to-end: backend invoked with chosen model-id
# ---------------------------------------------------------------------------


def test_anthropic_call_end_to_end_with_mock_backend():
    backend = MockAnthropicBackend()
    response, decision = anthropic_call(
        persona_id="lena",
        auftrag_id="auf-e2e-001",
        prompt_payload="hi",
        backend=backend,
        static_choice="sonnet",
        env={},  # default static mode
    )
    assert decision.classified_class == "sonnet"
    expected_model = DEFAULT_TIER_MODEL_MAPPING["sonnet"]
    assert decision.chosen_model == expected_model
    assert response.model_id == expected_model
    assert response.backend_kind == "mock-anthropic"
    assert len(backend.calls) == 1
    assert backend.calls[0].model_id == expected_model
    assert backend.calls[0].persona_id == "lena"
    assert backend.calls[0].auftrag_id == "auf-e2e-001"
    assert backend.calls[0].prompt_payload == "hi"


# ---------------------------------------------------------------------------
# (13) JSONL sink swallows file-write errors gracefully
# ---------------------------------------------------------------------------


def test_jsonl_sink_swallows_unwritable_path():
    # Point the sink at a path inside a non-existent directory; the
    # write must fail silently and the decision must still be returned.
    bogus_path = "/var/empty/__never_exists__/decisions.jsonl"
    env = {
        WAKIR_ROUTING_MODE_ENV: "heuristic",
        WAKIR_ROUTING_DECISION_JSONL_ENV: bogus_path,
    }
    decision = decide_routing(
        persona_id="selin",
        auftrag_id="auf-fail-001",
        prompt_payload="ping",
        persona_def={"persona_id": "selin", "role": "pengine"},
        env=env,
    )
    assert decision.classified_class is not None
    assert decision.chosen_model is not None
    # The bogus path must not have been created (best-effort check —
    # we just assert no exception escaped).
    assert not Path(bogus_path).exists()


# ---------------------------------------------------------------------------
# (14) set_tier_model_mapping validates full tier coverage
# ---------------------------------------------------------------------------


def test_set_tier_model_mapping_validates_coverage():
    try:
        with pytest.raises(ValueError):
            set_tier_model_mapping({"haiku": "x", "sonnet": "y"})
        # Successful override + readback.
        custom = {
            "haiku": "claude-haiku-custom",
            "sonnet": "claude-sonnet-custom",
            "opus": "claude-opus-custom",
        }
        set_tier_model_mapping(custom)
        assert get_tier_model_mapping() == custom
        assert map_tier_to_model_id("sonnet") == "claude-sonnet-custom"
    finally:
        reset_tier_model_mapping()
        assert get_tier_model_mapping() == DEFAULT_TIER_MODEL_MAPPING


# ---------------------------------------------------------------------------
# (15) static mode without static_choice → heuristic-fallback in JSONL
# ---------------------------------------------------------------------------


def test_static_mode_missing_static_choice_falls_back_and_logs(tmp_path):
    sink = tmp_path / "decisions.jsonl"
    env = {
        # Mode = static (no env var or explicit static), but no
        # static_choice given to decide_routing.
        WAKIR_ROUTING_MODE_ENV: "static",
        WAKIR_ROUTING_DECISION_JSONL_ENV: str(sink),
    }
    decision = decide_routing(
        persona_id="selin",
        auftrag_id="auf-fb-002",
        prompt_payload="ping",
        persona_def={"persona_id": "selin", "role": "pengine"},
        static_choice=None,
        env=env,
    )
    assert decision.mode == WAKIR_ROUTING_MODE_STATIC
    assert decision.used_fallback is True
    assert decision.fallback_reason == "static-mode-missing-static-choice"
    assert decision.classified_class is not None
    assert decision.chosen_model is not None
    # JSONL captured the fallback reason.
    line = sink.read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["mode"] == "static"
    assert rec["used_fallback"] is True
    assert rec["fallback_reason"] == "static-mode-missing-static-choice"
