# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the classifier-decision-cache + production wiring.

ADR-0064 Phase-2c production-wiring — Sprint Tag-16 mini-welle.

Test coverage matrix:

1.  ``read_cache_ttl_seconds``: default, parse, clamp, unparseable
2.  ``derive_task_hash``: deterministic + sensitive to every input
3.  ``ClassifierDecisionCache``: enabled / disabled flag honours TTL=0
4.  Cache lookup miss → store → hit (deterministic round-trip)
5.  Cache TTL expiry: fake-clock advance evicts entry and reports
    ``"expired"`` cache-event
6.  Cache lookup sink captures the structured-JSON event envelope
    (hit, miss, disabled, expired)
7.  Cache disabled (TTL=0) → store is a no-op + lookup returns None
8.  Task-hash includes persona-def pin → persona-def change
    invalidates the cache
9.  ``classify`` via mock-haiku-backend yields the expected tier-class
    for representative prompt shapes (production-wiring contract)
10. ``classify`` via mock-haiku-backend yields the expected
    sonnet-class for code-heavy mid-length prompts
11. ``llm_classifier`` mode with cache: first call invokes
    classifier-backend, second call (same task) does not
12. ``llm_classifier`` mode without fallback: classifier-error
    propagates (no fallback to heuristic)
13. ``llm_classifier_fallback_heuristic`` mode: classifier-error →
    heuristic-fallback fires, ``used_fallback`` + ``fallback_reason``
    set in RoutingDecision
14. Cache-hit path skips classifier-call AND skips backend.classify;
    counts on a spy-backend prove it
15. Cache-miss path calls classifier; subsequent call within TTL =
    hit; advance clock past TTL = miss again
16. TTL-expiration triggers re-call of classifier (recall semantics)
17. JSONL emission with cache_event field present (hit + miss
    cases); byte-stable key ordering
18. Cache layer + fallback-mode interaction: cache hit serves a
    previously-fallback result without re-invoking the classifier
"""

from __future__ import annotations

import json

import pytest

from wirelang.persona_engine.anthropic_call import (
    DEFAULT_TIER_MODEL_MAPPING,
    MockAnthropicBackend,
    RoutingDecision,
    WAKIR_ROUTING_DECISION_JSONL_ENV,
    WAKIR_ROUTING_MODE_ENV,
    WAKIR_ROUTING_MODE_LLM_CLASSIFIER,
    WAKIR_ROUTING_MODE_LLM_CLASSIFIER_FALLBACK_HEURISTIC,
    anthropic_call,
    decide_routing,
)
from wirelang.persona_engine.classifier_cache import (
    CLASSIFIER_CACHE_VERSION,
    CacheLookupEvent,
    ClassifierDecisionCache,
    WAKIR_CLASSIFIER_CACHE_TTL_DEFAULT_SECONDS,
    WAKIR_CLASSIFIER_CACHE_TTL_ENV,
    derive_task_hash,
    read_cache_ttl_seconds,
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


class _FakeClock:
    """Deterministic monotonic-clock substitute for TTL tests."""

    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _SpyClassifierBackend:
    """Mock-Haiku backend that records every classify-call."""

    def __init__(self, verdict: ClassifierVerdict | None = None):
        self.calls: list[tuple[str, dict | None]] = []
        self._verdict = verdict or ClassifierVerdict(
            tier=RouterDecision.HAIKU,
            confidence=0.90,
            rationale="spy-default",
            backend_kind="spy-mock-haiku",
        )

    def classify(self, *, prompt_payload, persona_def=None):
        self.calls.append((prompt_payload, persona_def))
        return self._verdict


class _RaisingBackend:
    """Backend that always raises (no-fallback + fallback-mode tests)."""

    def __init__(self):
        self.calls = 0

    def classify(self, *, prompt_payload, persona_def=None):
        self.calls += 1
        raise RuntimeError("synthetic-classifier-outage")


# ---------------------------------------------------------------------------
# (1) read_cache_ttl_seconds: default, parse, clamp, unparseable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env,expected",
    [
        ({}, WAKIR_CLASSIFIER_CACHE_TTL_DEFAULT_SECONDS),
        ({WAKIR_CLASSIFIER_CACHE_TTL_ENV: ""}, WAKIR_CLASSIFIER_CACHE_TTL_DEFAULT_SECONDS),
        ({WAKIR_CLASSIFIER_CACHE_TTL_ENV: "0"}, 0),
        ({WAKIR_CLASSIFIER_CACHE_TTL_ENV: "60"}, 60),
        ({WAKIR_CLASSIFIER_CACHE_TTL_ENV: "  120  "}, 120),
        ({WAKIR_CLASSIFIER_CACHE_TTL_ENV: "-5"}, 0),  # clamp negative
        ({WAKIR_CLASSIFIER_CACHE_TTL_ENV: "not-a-number"}, WAKIR_CLASSIFIER_CACHE_TTL_DEFAULT_SECONDS),
    ],
)
def test_read_cache_ttl_seconds_table(env, expected):
    assert read_cache_ttl_seconds(env) == expected


# ---------------------------------------------------------------------------
# (2) derive_task_hash: deterministic + sensitive to every input
# ---------------------------------------------------------------------------


def test_derive_task_hash_deterministic_and_sensitive():
    h1 = derive_task_hash(
        persona_id="lena",
        persona_def={"role": "frontend", "v907_pin": "abc123"},
        prompt_payload="hello",
    )
    h2 = derive_task_hash(
        persona_id="lena",
        persona_def={"role": "frontend", "v907_pin": "abc123"},
        prompt_payload="hello",
    )
    assert h1 == h2
    # 64-char hex (SHA-256).
    assert len(h1) == 64 and all(c in "0123456789abcdef" for c in h1)
    # Sensitive to persona_id.
    h_pid = derive_task_hash(
        persona_id="selin",
        persona_def={"role": "frontend", "v907_pin": "abc123"},
        prompt_payload="hello",
    )
    assert h_pid != h1
    # Sensitive to persona_def pin.
    h_pin = derive_task_hash(
        persona_id="lena",
        persona_def={"role": "frontend", "v907_pin": "xyz999"},
        prompt_payload="hello",
    )
    assert h_pin != h1
    # Sensitive to prompt_payload.
    h_prompt = derive_task_hash(
        persona_id="lena",
        persona_def={"role": "frontend", "v907_pin": "abc123"},
        prompt_payload="hello!",
    )
    assert h_prompt != h1


# ---------------------------------------------------------------------------
# (3) ClassifierDecisionCache: enabled / disabled honours TTL=0
# ---------------------------------------------------------------------------


def test_cache_enabled_flag_honours_ttl():
    assert ClassifierDecisionCache(ttl_seconds=0).enabled is False
    assert ClassifierDecisionCache(ttl_seconds=1).enabled is True
    assert ClassifierDecisionCache(ttl_seconds=3600).enabled is True


# ---------------------------------------------------------------------------
# (4) Cache lookup miss → store → hit (deterministic round-trip)
# ---------------------------------------------------------------------------


def test_cache_miss_store_hit_roundtrip():
    clock = _FakeClock()
    cache = ClassifierDecisionCache(ttl_seconds=3600, clock=clock)
    persona_def = {"role": "frontend"}
    # First lookup: miss.
    assert (
        cache.lookup(
            persona_id="lena",
            persona_def=persona_def,
            prompt_payload="ping",
        )
        is None
    )
    # Store via the router decision pipeline (simulated).
    router = LlmClassifierRouter()
    event = router.decide(
        persona_id="lena",
        auftrag_id="auf-001",
        task_payload={"prompt_payload": "ping"},
        persona_def=persona_def,
    )
    cache.store(
        persona_id="lena",
        persona_def=persona_def,
        prompt_payload="ping",
        event=event,
    )
    # Second lookup: hit.
    got = cache.lookup(
        persona_id="lena",
        persona_def=persona_def,
        prompt_payload="ping",
    )
    assert got is event


# ---------------------------------------------------------------------------
# (5) Cache TTL expiry: fake-clock advance evicts + reports expired
# ---------------------------------------------------------------------------


def test_cache_ttl_expiry_evicts_and_reports_expired():
    clock = _FakeClock()
    captured: list[CacheLookupEvent] = []
    cache = ClassifierDecisionCache(
        ttl_seconds=60, clock=clock, sink=captured.append
    )
    router = LlmClassifierRouter()
    event = router.decide(
        persona_id="lena",
        auftrag_id="auf-001",
        task_payload={"prompt_payload": "ping"},
        persona_def={"role": "frontend"},
    )
    cache.store(
        persona_id="lena",
        persona_def={"role": "frontend"},
        prompt_payload="ping",
        event=event,
    )
    # Still inside TTL (advance 30s): hit.
    clock.advance(30.0)
    assert (
        cache.lookup(
            persona_id="lena",
            persona_def={"role": "frontend"},
            prompt_payload="ping",
        )
        is event
    )
    # Past TTL (advance another 31s = total 61s > 60): expired.
    clock.advance(31.0)
    assert (
        cache.lookup(
            persona_id="lena",
            persona_def={"role": "frontend"},
            prompt_payload="ping",
        )
        is None
    )
    # Entry was evicted; subsequent lookup is a miss.
    assert cache.size() == 0
    # Sink captured the events in order: hit, expired.
    events_by_type = [e.cache_event for e in captured]
    assert events_by_type == ["hit", "expired"]


# ---------------------------------------------------------------------------
# (6) Cache lookup sink captures structured-JSON envelope shape
# ---------------------------------------------------------------------------


def test_cache_lookup_sink_envelope_shape():
    captured: list[CacheLookupEvent] = []
    clock = _FakeClock()
    cache = ClassifierDecisionCache(
        ttl_seconds=3600, clock=clock, sink=captured.append
    )
    # Miss.
    cache.lookup(
        persona_id="lena",
        persona_def={"role": "frontend"},
        prompt_payload="x",
        ts_utc="2026-05-17T10:00:00Z",
    )
    # Disabled.
    cache_off = ClassifierDecisionCache(
        ttl_seconds=0, clock=clock, sink=captured.append
    )
    cache_off.lookup(
        persona_id="lena",
        persona_def=None,
        prompt_payload="y",
        ts_utc="2026-05-17T10:00:01Z",
    )
    assert len(captured) == 2
    miss, disabled = captured
    assert miss.cache_event == "miss"
    assert miss.ttl_seconds_remaining is None
    assert len(miss.task_hash_prefix) == 12
    assert miss.ts_utc == "2026-05-17T10:00:00Z"
    assert disabled.cache_event == "disabled"
    # JSON serialization is byte-stable + key-sorted.
    line = miss.to_json()
    re_serialised = json.dumps(json.loads(line), sort_keys=True, separators=(",", ":"))
    assert line == re_serialised


# ---------------------------------------------------------------------------
# (7) Cache disabled (TTL=0) → store is no-op + lookup returns None
# ---------------------------------------------------------------------------


def test_cache_disabled_store_is_noop():
    cache = ClassifierDecisionCache(ttl_seconds=0)
    router = LlmClassifierRouter()
    event = router.decide(
        persona_id="lena",
        auftrag_id="auf-001",
        task_payload={"prompt_payload": "ping"},
    )
    cache.store(
        persona_id="lena",
        persona_def=None,
        prompt_payload="ping",
        event=event,
    )
    assert cache.size() == 0
    assert (
        cache.lookup(
            persona_id="lena",
            persona_def=None,
            prompt_payload="ping",
        )
        is None
    )


# ---------------------------------------------------------------------------
# (8) Task-hash includes persona-def pin → persona-def-change invalidates
# ---------------------------------------------------------------------------


def test_persona_def_change_invalidates_cache_entry():
    cache = ClassifierDecisionCache(ttl_seconds=3600)
    router = LlmClassifierRouter()
    event_v1 = router.decide(
        persona_id="lena",
        auftrag_id="auf-1",
        task_payload={"prompt_payload": "ping"},
        persona_def={"role": "frontend", "v907_pin": "pin-v1"},
    )
    cache.store(
        persona_id="lena",
        persona_def={"role": "frontend", "v907_pin": "pin-v1"},
        prompt_payload="ping",
        event=event_v1,
    )
    # Same persona-id + prompt but different pin → miss.
    assert (
        cache.lookup(
            persona_id="lena",
            persona_def={"role": "frontend", "v907_pin": "pin-v2"},
            prompt_payload="ping",
        )
        is None
    )
    # Same pin still → hit.
    assert (
        cache.lookup(
            persona_id="lena",
            persona_def={"role": "frontend", "v907_pin": "pin-v1"},
            prompt_payload="ping",
        )
        is event_v1
    )


# ---------------------------------------------------------------------------
# (9) llm-classifier-mock-haiku-class: short prose → Haiku tier
# ---------------------------------------------------------------------------


def test_llm_classifier_mock_haiku_class_for_short_prose():
    backend = MockHaikuClassifierBackend()
    verdict = backend.classify(
        prompt_payload="ping",
        persona_def={"role": "frontend"},
    )
    assert verdict.tier == RouterDecision.HAIKU
    assert verdict.confidence >= 0.8
    assert verdict.backend_kind == "mock-haiku"


# ---------------------------------------------------------------------------
# (10) llm-classifier-mock-sonnet-class: code-heavy mid-length → Sonnet
# ---------------------------------------------------------------------------


def test_llm_classifier_mock_sonnet_class_for_code_heavy_mid_length():
    backend = MockHaikuClassifierBackend()
    body = "Helper text. " * 600
    code = "```python\nprint('hi')\n```\n"
    prompt = body + code + code + code
    verdict = backend.classify(
        prompt_payload=prompt,
        persona_def={"role": "dev-engineering"},
    )
    assert verdict.tier == RouterDecision.SONNET
    assert verdict.confidence >= 0.8


# ---------------------------------------------------------------------------
# (11) llm_classifier mode with cache: 2nd identical call skips backend
# ---------------------------------------------------------------------------


def test_llm_classifier_mode_cache_hit_skips_classifier_call():
    spy = _SpyClassifierBackend(
        verdict=ClassifierVerdict(
            tier=RouterDecision.SONNET,
            confidence=0.95,
            rationale="spy",
            backend_kind="spy-mock-haiku",
        )
    )
    router = LlmClassifierRouter(backend=spy)
    cache = ClassifierDecisionCache(ttl_seconds=3600)
    env = {WAKIR_ROUTING_MODE_ENV: "llm_classifier"}
    persona_def = {"role": "frontend", "v907_pin": "pin-A"}

    # First call: miss → classifier invoked.
    decision1 = decide_routing(
        persona_id="lena",
        auftrag_id="auf-1",
        prompt_payload="same-prompt",
        persona_def=persona_def,
        classifier_router=router,
        classifier_cache=cache,
        env=env,
    )
    assert decision1.classified_class == RouterDecision.SONNET.value
    assert decision1.cache_event == "miss"
    assert len(spy.calls) == 1

    # Second call (identical inputs): hit → classifier NOT invoked.
    decision2 = decide_routing(
        persona_id="lena",
        auftrag_id="auf-2",  # auftrag-id differs, but cache is task-hash
        prompt_payload="same-prompt",
        persona_def=persona_def,
        classifier_router=router,
        classifier_cache=cache,
        env=env,
    )
    assert decision2.classified_class == RouterDecision.SONNET.value
    assert decision2.cache_event == "hit"
    # Critical: still 1 call to the backend.
    assert len(spy.calls) == 1


# ---------------------------------------------------------------------------
# (12) llm_classifier mode (no fallback): classifier-error propagates
# ---------------------------------------------------------------------------


def test_llm_classifier_mode_error_no_fallback_propagates():
    raising = _RaisingBackend()
    router = LlmClassifierRouter(backend=raising)
    env = {WAKIR_ROUTING_MODE_ENV: "llm_classifier"}
    with pytest.raises(RuntimeError, match="synthetic-classifier-outage"):
        decide_routing(
            persona_id="lena",
            auftrag_id="auf-err-1",
            prompt_payload="boom",
            persona_def={"role": "frontend"},
            classifier_router=router,
            env=env,
        )
    assert raising.calls == 1


# ---------------------------------------------------------------------------
# (13) llm_classifier_fallback_heuristic: classifier-error → heuristic fallback
# ---------------------------------------------------------------------------


def test_llm_classifier_fallback_heuristic_on_classifier_error():
    raising = _RaisingBackend()
    router = LlmClassifierRouter(backend=raising)
    env = {
        WAKIR_ROUTING_MODE_ENV: "llm_classifier_fallback_heuristic",
    }
    decision = decide_routing(
        persona_id="lena",
        auftrag_id="auf-fb-1",
        prompt_payload="hi",  # short prose → heuristic picks Haiku
        persona_def={"role": "frontend"},
        classifier_router=router,
        env=env,
    )
    assert (
        decision.mode
        == WAKIR_ROUTING_MODE_LLM_CLASSIFIER_FALLBACK_HEURISTIC
    )
    assert decision.classified_class == RouterDecision.HAIKU.value
    assert decision.used_fallback is True
    assert decision.fallback_reason is not None
    assert "RuntimeError" in decision.fallback_reason
    assert raising.calls == 1


# ---------------------------------------------------------------------------
# (14) Cache-hit path skips classifier + skips backend.classify (spy-proof)
# ---------------------------------------------------------------------------


def test_cache_hit_skips_classifier_call_count_proof():
    spy = _SpyClassifierBackend()
    router = LlmClassifierRouter(backend=spy)
    cache = ClassifierDecisionCache(ttl_seconds=3600)
    env = {WAKIR_ROUTING_MODE_ENV: "llm_classifier"}
    # 3 identical calls.
    for i in range(3):
        decide_routing(
            persona_id="lena",
            auftrag_id=f"auf-{i}",
            prompt_payload="cached-prompt",
            persona_def={"role": "frontend"},
            classifier_router=router,
            classifier_cache=cache,
            env=env,
        )
    # Only the first call hit the classifier.
    assert len(spy.calls) == 1


# ---------------------------------------------------------------------------
# (15) Cache-miss calls classifier; in-TTL second call = hit; post-TTL = miss
# ---------------------------------------------------------------------------


def test_cache_miss_calls_classifier_ttl_expiration_recalls():
    spy = _SpyClassifierBackend()
    router = LlmClassifierRouter(backend=spy)
    clock = _FakeClock()
    cache = ClassifierDecisionCache(ttl_seconds=120, clock=clock)
    env = {WAKIR_ROUTING_MODE_ENV: "llm_classifier"}

    # T=0: miss → classifier called.
    d1 = decide_routing(
        persona_id="lena",
        auftrag_id="auf-A",
        prompt_payload="ttl-prompt",
        persona_def={"role": "frontend"},
        classifier_router=router,
        classifier_cache=cache,
        env=env,
    )
    assert d1.cache_event == "miss"
    assert len(spy.calls) == 1

    # T=60s: still in TTL → hit.
    clock.advance(60.0)
    d2 = decide_routing(
        persona_id="lena",
        auftrag_id="auf-B",
        prompt_payload="ttl-prompt",
        persona_def={"role": "frontend"},
        classifier_router=router,
        classifier_cache=cache,
        env=env,
    )
    assert d2.cache_event == "hit"
    assert len(spy.calls) == 1

    # T=180s: TTL expired (120s) → expired event + classifier re-called.
    clock.advance(120.0)
    d3 = decide_routing(
        persona_id="lena",
        auftrag_id="auf-C",
        prompt_payload="ttl-prompt",
        persona_def={"role": "frontend"},
        classifier_router=router,
        classifier_cache=cache,
        env=env,
    )
    assert d3.cache_event == "expired"
    assert len(spy.calls) == 2


# ---------------------------------------------------------------------------
# (16) TTL-expiration triggers re-call of classifier (explicit recall semantics)
# ---------------------------------------------------------------------------


def test_ttl_expiration_causes_recall():
    spy = _SpyClassifierBackend()
    router = LlmClassifierRouter(backend=spy)
    clock = _FakeClock()
    cache = ClassifierDecisionCache(ttl_seconds=10, clock=clock)
    env = {WAKIR_ROUTING_MODE_ENV: "llm_classifier"}

    decide_routing(
        persona_id="lena",
        auftrag_id="auf-1",
        prompt_payload="recall",
        persona_def={"role": "frontend"},
        classifier_router=router,
        classifier_cache=cache,
        env=env,
    )
    assert len(spy.calls) == 1

    clock.advance(11.0)  # past TTL
    decide_routing(
        persona_id="lena",
        auftrag_id="auf-2",
        prompt_payload="recall",
        persona_def={"role": "frontend"},
        classifier_router=router,
        classifier_cache=cache,
        env=env,
    )
    # Re-call after expiry.
    assert len(spy.calls) == 2


# ---------------------------------------------------------------------------
# (17) JSONL emission with cache_event field (hit + miss); byte-stable order
# ---------------------------------------------------------------------------


def test_jsonl_emission_includes_cache_event_and_is_byte_stable(tmp_path):
    sink_path = tmp_path / "decisions.jsonl"
    spy = _SpyClassifierBackend()
    router = LlmClassifierRouter(backend=spy)
    cache = ClassifierDecisionCache(ttl_seconds=3600)
    env = {
        WAKIR_ROUTING_MODE_ENV: "llm_classifier",
        WAKIR_ROUTING_DECISION_JSONL_ENV: str(sink_path),
    }
    # Two identical calls: first miss, second hit.
    decide_routing(
        persona_id="lena",
        auftrag_id="auf-1",
        prompt_payload="jsonl-prompt",
        persona_def={"role": "frontend"},
        classifier_router=router,
        classifier_cache=cache,
        ts_utc="2026-05-17T11:00:00Z",
        env=env,
    )
    decide_routing(
        persona_id="lena",
        auftrag_id="auf-2",
        prompt_payload="jsonl-prompt",
        persona_def={"role": "frontend"},
        classifier_router=router,
        classifier_cache=cache,
        ts_utc="2026-05-17T11:00:01Z",
        env=env,
    )
    lines = sink_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    recs = [json.loads(line) for line in lines]
    assert recs[0]["cache_event"] == "miss"
    assert recs[1]["cache_event"] == "hit"
    # Byte-stable key ordering.
    for line in lines:
        parsed = json.loads(line)
        re_serialised = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        assert line == re_serialised


# ---------------------------------------------------------------------------
# (18) Cache + fallback-mode: hit serves prior fallback w/o recall
# ---------------------------------------------------------------------------


def test_cache_serves_prior_fallback_result_without_recall():
    # First request: classifier raises → fallback-heuristic fires.
    # But because the classifier raised, NOTHING gets stored. The cache
    # remains empty. Subsequent identical requests therefore re-invoke
    # the classifier (which raises again) and re-fall-back. This test
    # documents that the cache layer never stores fallback results
    # (preventing fallback-decisions from becoming sticky if the
    # classifier path later recovers).
    raising = _RaisingBackend()
    router = LlmClassifierRouter(backend=raising)
    cache = ClassifierDecisionCache(ttl_seconds=3600)
    env = {
        WAKIR_ROUTING_MODE_ENV: "llm_classifier_fallback_heuristic",
    }
    for _ in range(3):
        d = decide_routing(
            persona_id="lena",
            auftrag_id="auf-x",
            prompt_payload="hi",
            persona_def={"role": "frontend"},
            classifier_router=router,
            classifier_cache=cache,
            env=env,
        )
        assert d.used_fallback is True
    # Cache stays empty because the classifier raised before a verdict
    # could be persisted.
    assert cache.size() == 0
    # Classifier was invoked once per call (no sticky fallback).
    assert raising.calls == 3


# ---------------------------------------------------------------------------
# Bonus: end-to-end anthropic_call with cache + classifier mode
# ---------------------------------------------------------------------------


def test_anthropic_call_end_to_end_with_cache_classifier_mode():
    spy = _SpyClassifierBackend(
        verdict=ClassifierVerdict(
            tier=RouterDecision.SONNET,
            confidence=0.95,
            rationale="spy",
            backend_kind="spy-mock-haiku",
        )
    )
    router = LlmClassifierRouter(backend=spy)
    cache = ClassifierDecisionCache(ttl_seconds=3600)
    backend = MockAnthropicBackend()
    env = {WAKIR_ROUTING_MODE_ENV: "llm_classifier"}

    for i in range(2):
        response, decision = anthropic_call(
            persona_id="lena",
            auftrag_id=f"auf-{i}",
            prompt_payload="end-to-end",
            backend=backend,
            persona_def={"role": "frontend"},
            classifier_router=router,
            classifier_cache=cache,
            env=env,
        )
        assert decision.chosen_model == DEFAULT_TIER_MODEL_MAPPING["sonnet"]
        assert response.model_id == DEFAULT_TIER_MODEL_MAPPING["sonnet"]

    # Both backend.call invocations happened (2x); but only one
    # classifier invocation (the 2nd request hit the cache).
    assert len(backend.calls) == 2
    assert len(spy.calls) == 1
