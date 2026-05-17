# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the LLM-Classifier-Routing-Stub (ADR-0064 §A.4).

All tests are pure-stdlib — no network, no LLM, no NATS. Test
coverage matrix:

1.  ``is_llm_classifier_mode``: default env → False
2.  ``is_llm_classifier_mode``: explicit value → True (whitespace +
    case tolerant)
3.  ``read_confidence_threshold``: default when unset
4.  ``read_confidence_threshold``: parses + clamps out-of-range
5.  ``MockHaikuClassifierBackend``: determinism across repeated calls
6.  ``MockHaikuClassifierBackend``: audit-persona band → Opus-floor
    high-confidence
7.  ``MockHaikuClassifierBackend``: borderline mid-length prose →
    sub-threshold confidence
8.  ``LlmClassifierRouter``: above-threshold classifier verdict is
    honoured (no fallback)
9.  ``LlmClassifierRouter``: below-threshold classifier verdict falls
    back to heuristic-router decision
10. ``LlmClassifierRouter``: sink captures emitted events; broken sink
    does not raise
11. ``LlmClassifierEvent``: byte-stable JSON serialization
12. ``maybe_attach_classifier_router``: returns None unless env opt-in
13. ``llm_call_shim.call_with_classifier_event``: pass-through when
    router is None
14. ``llm_call_shim.call_with_classifier_event``: with router → event
    emitted, hook reply unchanged

Tests are tabular where possible — the deterministic mock backend lets
us assert exact tier + confidence verdicts in source.
"""

from __future__ import annotations

import json

import pytest

from wirelang.persona_engine.heuristic_router import RouterDecision
from wirelang.persona_engine.llm_call_shim import (
    EchoReflectionLlmHook,
    LlmCallResult,
    call_with_classifier_event,
)
from wirelang.persona_engine.llm_classifier import (
    LLM_CLASSIFIER_VERSION,
    LlmClassifierEvent,
    LlmClassifierRouter,
    MockHaikuClassifierBackend,
    WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_DEFAULT,
    WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_ENV,
    WAKIR_ROUTING_MODE_ENV,
    is_llm_classifier_mode,
    maybe_attach_classifier_router,
    read_confidence_threshold,
)


# ---------------------------------------------------------------------------
# (1) is_llm_classifier_mode: default env → False
# ---------------------------------------------------------------------------


def test_is_llm_classifier_mode_default_false():
    assert is_llm_classifier_mode(env={}) is False
    assert is_llm_classifier_mode(env={WAKIR_ROUTING_MODE_ENV: ""}) is False
    assert (
        is_llm_classifier_mode(env={WAKIR_ROUTING_MODE_ENV: "static"}) is False
    )
    assert (
        is_llm_classifier_mode(env={WAKIR_ROUTING_MODE_ENV: "heuristic"})
        is False
    )


# ---------------------------------------------------------------------------
# (2) is_llm_classifier_mode: explicit opt-in tolerant of case/whitespace
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "llm_classifier",
        "LLM_CLASSIFIER",
        "  llm_classifier  ",
        " LLM_Classifier ",
    ],
)
def test_is_llm_classifier_mode_opt_in_variants(raw: str):
    assert is_llm_classifier_mode(env={WAKIR_ROUTING_MODE_ENV: raw}) is True


# ---------------------------------------------------------------------------
# (3) + (4) confidence threshold: default + clamp + parse-failure
# ---------------------------------------------------------------------------


def test_read_confidence_threshold_default_when_unset():
    assert (
        read_confidence_threshold(env={})
        == WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_DEFAULT
    )
    assert (
        read_confidence_threshold(
            env={WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_ENV: ""}
        )
        == WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_DEFAULT
    )


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0.5", 0.5),
        ("1.0", 1.0),
        ("0.0", 0.0),
        ("-0.1", 0.0),  # clamp-low
        ("1.5", 1.0),  # clamp-high
        ("not-a-number", WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_DEFAULT),
        ("0.85", 0.85),
    ],
)
def test_read_confidence_threshold_parse_and_clamp(raw: str, expected: float):
    assert (
        read_confidence_threshold(
            env={WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_ENV: raw}
        )
        == expected
    )


# ---------------------------------------------------------------------------
# (5) Mock-Haiku determinism across repeated calls
# ---------------------------------------------------------------------------


def test_mock_haiku_backend_is_deterministic():
    backend = MockHaikuClassifierBackend()
    prompt = "Refactor the bridge-audit-writer to support batched flushes."
    v1 = backend.classify(prompt_payload=prompt, persona_def=None)
    v2 = backend.classify(prompt_payload=prompt, persona_def=None)
    assert v1 == v2
    assert v1.backend_kind == "mock-haiku"


# ---------------------------------------------------------------------------
# (6) Mock-Haiku: audit-persona → Opus-floor at high confidence
# ---------------------------------------------------------------------------


def test_mock_haiku_audit_persona_opus_floor():
    backend = MockHaikuClassifierBackend()
    verdict = backend.classify(
        prompt_payload="Short audit-trail prompt.",
        persona_def={"persona_id": "henrik", "role": "internal-audit"},
    )
    assert verdict.tier == RouterDecision.OPUS
    assert verdict.confidence >= 0.9
    assert verdict.rationale == "befugnis-audit-floor"


# ---------------------------------------------------------------------------
# (7) Mock-Haiku: borderline mid-length prose → sub-threshold
# ---------------------------------------------------------------------------


def test_mock_haiku_borderline_subthreshold_confidence():
    backend = MockHaikuClassifierBackend()
    # Mid-length prose (between Haiku and Sonnet thresholds), no code,
    # no schema markers, no persona-band override.
    prompt = "x" * 2_500
    verdict = backend.classify(prompt_payload=prompt, persona_def=None)
    assert verdict.tier == RouterDecision.SONNET
    assert (
        verdict.confidence < WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_DEFAULT
    )
    assert verdict.rationale == "borderline-prose-mid-length"


# ---------------------------------------------------------------------------
# (8) LlmClassifierRouter: above-threshold verdict honoured (no fallback)
# ---------------------------------------------------------------------------


def test_router_above_threshold_no_fallback():
    captured: list[LlmClassifierEvent] = []
    router = LlmClassifierRouter(sink=captured.append, env={})
    event = router.decide(
        persona_id="henrik",
        auftrag_id="A-001",
        task_payload={"prompt_payload": "Audit summary."},
        persona_def={"persona_id": "henrik", "role": "internal-audit"},
        static_choice="sonnet",
        ts_utc="2026-05-17T00:00:00Z",
    )
    assert event.classifier_choice == "opus"
    assert event.used_fallback is False
    assert event.effective_choice == "opus"
    assert event.classifier_confidence >= event.confidence_threshold
    assert len(captured) == 1
    assert captured[0] is event


# ---------------------------------------------------------------------------
# (9) LlmClassifierRouter: below-threshold verdict falls back to heuristic
# ---------------------------------------------------------------------------


def test_router_below_threshold_fallback_to_heuristic():
    router = LlmClassifierRouter(env={})
    # Borderline prose triggers sub-threshold confidence; heuristic-
    # router on the same prompt yields SONNET (mid-length, no code,
    # no schema, no persona override = sum 0 → SONNET band).
    event = router.decide(
        persona_id="tomas",
        auftrag_id="A-002",
        task_payload={"prompt_payload": "x" * 2_500},
        persona_def={"persona_id": "tomas", "role": "dev-engineering"},
        ts_utc="2026-05-17T00:00:00Z",
    )
    assert event.classifier_rationale == "borderline-prose-mid-length"
    assert event.used_fallback is True
    # The effective choice now mirrors the heuristic-router decision,
    # not the classifier's (low-confidence) verdict.
    assert event.effective_choice == event.heuristic_choice


# ---------------------------------------------------------------------------
# (10) Sink capture + broken-sink resilience
# ---------------------------------------------------------------------------


def test_router_sink_capture_and_broken_sink_swallowed():
    captured: list[LlmClassifierEvent] = []

    def good_sink(ev: LlmClassifierEvent) -> None:
        captured.append(ev)

    def broken_sink(_ev: LlmClassifierEvent) -> None:
        raise RuntimeError("simulated sink failure")

    # Good sink path.
    router_ok = LlmClassifierRouter(sink=good_sink, env={})
    router_ok.decide(
        persona_id="p",
        auftrag_id="A-OK",
        task_payload={"prompt_payload": "Short prompt."},
    )
    assert len(captured) == 1

    # Broken sink path must NOT raise.
    router_bad = LlmClassifierRouter(sink=broken_sink, env={})
    event = router_bad.decide(
        persona_id="p",
        auftrag_id="A-BAD",
        task_payload={"prompt_payload": "Short prompt."},
    )
    assert event.auftrag_id == "A-BAD"


# ---------------------------------------------------------------------------
# (11) LlmClassifierEvent: byte-stable JSON serialization
# ---------------------------------------------------------------------------


def test_classifier_event_json_byte_stable():
    router = LlmClassifierRouter(env={})
    payload = {"prompt_payload": "Short audit prompt."}
    persona = {"persona_id": "henrik", "role": "internal-audit"}
    event_a = router.decide(
        persona_id="henrik",
        auftrag_id="A-JSON",
        task_payload=payload,
        persona_def=persona,
        static_choice="sonnet",
        ts_utc="2026-05-17T00:00:00Z",
    )
    event_b = router.decide(
        persona_id="henrik",
        auftrag_id="A-JSON",
        task_payload=payload,
        persona_def=persona,
        static_choice="sonnet",
        ts_utc="2026-05-17T00:00:00Z",
    )
    assert event_a.to_json() == event_b.to_json()
    # And the JSON must parse to a dict that includes the version + the
    # effective_choice for downstream A/B-test telemetry.
    decoded = json.loads(event_a.to_json())
    assert decoded["classifier_version"] == LLM_CLASSIFIER_VERSION
    assert decoded["effective_choice"] == "opus"
    assert decoded["routing_mode"] == "llm_classifier"


# ---------------------------------------------------------------------------
# (12) maybe_attach_classifier_router: opt-in gating
# ---------------------------------------------------------------------------


def test_maybe_attach_classifier_router_opt_in_only():
    assert maybe_attach_classifier_router(env={}) is None
    assert (
        maybe_attach_classifier_router(env={WAKIR_ROUTING_MODE_ENV: "static"})
        is None
    )
    assert (
        maybe_attach_classifier_router(
            env={WAKIR_ROUTING_MODE_ENV: "heuristic"}
        )
        is None
    )
    router = maybe_attach_classifier_router(
        env={WAKIR_ROUTING_MODE_ENV: "llm_classifier"}
    )
    assert isinstance(router, LlmClassifierRouter)


# ---------------------------------------------------------------------------
# (13) llm_call_shim.call_with_classifier_event: pass-through when None
# ---------------------------------------------------------------------------


def test_call_with_classifier_event_no_router_is_passthrough():
    hook = EchoReflectionLlmHook()
    result, event = call_with_classifier_event(
        hook,
        persona_id="tomas",
        auftrag_id="A-PASS",
        prompt_payload="hello",
        ts_utc="2026-05-17T00:00:00Z",
    )
    assert isinstance(result, LlmCallResult)
    assert result.hook_kind == "echo-reflection"
    assert event is None


# ---------------------------------------------------------------------------
# (14) llm_call_shim.call_with_classifier_event: with router emits event,
#      hook reply unchanged (observation-only Phase-2c contract).
# ---------------------------------------------------------------------------


def test_call_with_classifier_event_with_router_emits_event():
    hook = EchoReflectionLlmHook()
    captured: list[LlmClassifierEvent] = []
    router = LlmClassifierRouter(sink=captured.append, env={})
    result, event = call_with_classifier_event(
        hook,
        persona_id="henrik",
        auftrag_id="A-OBS",
        prompt_payload="Audit-grade summary.",
        persona_def={"persona_id": "henrik", "role": "internal-audit"},
        static_choice="sonnet",
        classifier_router=router,
        ts_utc="2026-05-17T00:00:00Z",
    )
    # Phase-2c is observation-only: the LLM-result is the unchanged
    # echo-reflection output (substrate does NOT swap the model based
    # on the classifier verdict yet).
    assert isinstance(result, LlmCallResult)
    assert result.hook_kind == "echo-reflection"
    assert result.persona_id == "henrik"
    # Classifier-event captured in the sink AND returned.
    assert event is not None
    assert event.classifier_choice == "opus"
    assert event.effective_choice == "opus"
    assert len(captured) == 1
    assert captured[0].auftrag_id == "A-OBS"
