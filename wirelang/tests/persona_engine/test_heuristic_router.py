# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Heuristic Model-Router (ADR-0064 §A.3).

All tests are pure-stdlib — no network, no LLM, no NATS. Test
coverage matrix:

1.  Routing-mode env-var default → static
2.  Routing-mode env-var explicit static
3.  Routing-mode env-var explicit heuristic
4.  Routing-mode env-var unknown value → static (fail-safe)
5.  Token-length scoring bands (Haiku/Sonnet/Opus thresholds)
6.  Schema-complexity scoring
7.  Code-vs-prose scoring
8.  Persona-role-band: audit → Opus-floor override
9.  Persona-role-band: routine-comms → Haiku-ceiling override
10. Persona-role-band: engineering → no override
11. ``route_task`` end-to-end small-prompt → HAIKU
12. ``route_task`` end-to-end audit-persona forces OPUS
13. ``RoutingEvent`` byte-stable JSON serialization
14. ``build_routing_event``: static mode preserves static_choice as
    effective
15. ``build_routing_event``: heuristic mode uses heuristic as effective
16. ``HeuristicRoutingShim``: list-append sink captures events
17. ``HeuristicRoutingShim``: broken sink does not raise

The tests are deliberately tabular where the cardinality of inputs
is small, so the substrate's deterministic contract is visible in
the test source.
"""

from __future__ import annotations

import json

import pytest

from wirelang.persona_engine.heuristic_router import (
    AUDIT_PERSONA_IDS,
    ROUTINE_COMMS_PERSONA_IDS,
    HeuristicRoutingShim,
    RouterDecision,
    RoutingEvent,
    WAKIR_ROUTING_MODE_DEFAULT,
    WAKIR_ROUTING_MODE_HEURISTIC,
    WAKIR_ROUTING_MODE_STATIC,
    build_routing_event,
    measure_heuristic_inputs,
    read_routing_mode,
    route_task,
)


# ---------------------------------------------------------------------------
# 1-4: Routing-mode env-var
# ---------------------------------------------------------------------------


def test_routing_mode_default_static():
    assert read_routing_mode(env={}) == WAKIR_ROUTING_MODE_STATIC
    assert WAKIR_ROUTING_MODE_DEFAULT == WAKIR_ROUTING_MODE_STATIC


def test_routing_mode_explicit_static():
    assert (
        read_routing_mode(env={"WAKIR_ROUTING_MODE": "static"})
        == WAKIR_ROUTING_MODE_STATIC
    )


def test_routing_mode_explicit_heuristic():
    assert (
        read_routing_mode(env={"WAKIR_ROUTING_MODE": "heuristic"})
        == WAKIR_ROUTING_MODE_HEURISTIC
    )


def test_routing_mode_unknown_falls_back_to_static():
    assert (
        read_routing_mode(env={"WAKIR_ROUTING_MODE": "GPT-4O-MAX-PLUS"})
        == WAKIR_ROUTING_MODE_STATIC
    )
    # Case-insensitivity + whitespace tolerance.
    assert (
        read_routing_mode(env={"WAKIR_ROUTING_MODE": "  HEURISTIC  "})
        == WAKIR_ROUTING_MODE_HEURISTIC
    )


# ---------------------------------------------------------------------------
# 5: Token-length scoring bands
# ---------------------------------------------------------------------------


def test_token_length_scoring_bands():
    # Empty prompt → very short → strong Haiku-pull.
    inputs = measure_heuristic_inputs("")
    assert inputs.token_len_score == -2

    # Short prompt (~50 tokens).
    inputs = measure_heuristic_inputs("hello world " * 10)
    assert inputs.token_len_score == -2

    # Medium prompt (~1500 tokens).
    inputs = measure_heuristic_inputs("x" * 6_000)
    assert inputs.token_len_score == -1

    # Long prompt (~5000 tokens) → Opus-lean.
    inputs = measure_heuristic_inputs("x" * 20_000)
    assert inputs.token_len_score == +1

    # Very long prompt (~20000 tokens) → dominant Opus-pull. The
    # extreme band uses ``+4`` so the score alone clears the
    # band-mapping threshold even when other heuristic inputs return
    # their worst-case negative contribution.
    inputs = measure_heuristic_inputs("x" * 80_000)
    assert inputs.token_len_score == +4


# ---------------------------------------------------------------------------
# 6: Schema-complexity scoring
# ---------------------------------------------------------------------------


def test_schema_complexity_scoring():
    pure_prose = "Bitte schreib einen kurzen Brief an den Aufsichtsrat."
    inputs = measure_heuristic_inputs(pure_prose)
    assert inputs.schema_complexity_raw == 0
    assert inputs.schema_complexity_score == -1

    light_schema = (
        '{"type": "object", "properties": {"x": {"type": "string"}}, '
        '"required": ["x"]}'
    )
    inputs = measure_heuristic_inputs(light_schema)
    assert inputs.schema_complexity_raw == 2
    assert inputs.schema_complexity_score == 0

    heavy_schema = (
        "properties required additionalProperties $ref oneOf anyOf allOf "
        "properties required additionalProperties"
    )
    inputs = measure_heuristic_inputs(heavy_schema)
    assert inputs.schema_complexity_raw >= 7
    assert inputs.schema_complexity_score == +2


# ---------------------------------------------------------------------------
# 7: Code-vs-prose scoring
# ---------------------------------------------------------------------------


def test_code_vs_prose_scoring():
    prose = "Eine kurze Prosa-Beschreibung ohne Code-Blocks."
    inputs = measure_heuristic_inputs(prose)
    assert inputs.code_block_count == 0
    assert inputs.code_vs_prose_score == -1

    light_code = "Hier ein Beispiel:\n```python\nprint('hi')\n```\nFertig."
    inputs = measure_heuristic_inputs(light_code)
    assert inputs.code_block_count == 1
    assert inputs.code_vs_prose_score == 0

    heavy_code = (
        "```py\na=1\n```\n```rust\nfn b(){}\n```\n```sh\necho c\n```"
    )
    inputs = measure_heuristic_inputs(heavy_code)
    assert inputs.code_block_count == 3
    assert inputs.code_vs_prose_score == +1


# ---------------------------------------------------------------------------
# 8-10: Persona-Befugnis-Rahmen overrides
# ---------------------------------------------------------------------------


def test_persona_audit_floor_forces_opus():
    # Use a deliberately small prompt that would otherwise route Haiku.
    short_prompt = "Bitte verifiziere den Audit-Trail."
    persona_def = {"persona_id": "henrik", "role": "internal-audit"}
    decision = route_task({"prompt_payload": short_prompt}, persona_def)
    assert decision == RouterDecision.OPUS


def test_persona_routine_comms_ceiling_forces_haiku():
    # Use a deliberately complex prompt that would otherwise route Opus.
    complex_prompt = (
        "properties required additionalProperties $ref oneOf anyOf allOf "
        "properties required additionalProperties " * 50
    )
    persona_def = {"persona_id": "julia", "role": "comms"}
    decision = route_task({"prompt_payload": complex_prompt}, persona_def)
    assert decision == RouterDecision.HAIKU


def test_persona_engineering_no_override():
    # Engineering persona uses the raw heuristic — no floor/ceiling.
    short_prompt = "Liste die TODOs auf."
    persona_def = {"persona_id": "tomas", "role": "dev-engineering"}
    decision = route_task({"prompt_payload": short_prompt}, persona_def)
    # Short prose with engineering persona → Haiku-lean (no override).
    assert decision == RouterDecision.HAIKU


# ---------------------------------------------------------------------------
# Sanity: persona-id sets cover the documented persona roster
# ---------------------------------------------------------------------------


def test_audit_persona_ids_contain_henrik_aisha_mira():
    assert "henrik" in AUDIT_PERSONA_IDS
    assert "aisha" in AUDIT_PERSONA_IDS
    assert "mira" in AUDIT_PERSONA_IDS


def test_routine_comms_persona_ids_contain_julia_brand():
    assert "julia" in ROUTINE_COMMS_PERSONA_IDS
    assert "brand" in ROUTINE_COMMS_PERSONA_IDS


# ---------------------------------------------------------------------------
# 11-12: route_task end-to-end
# ---------------------------------------------------------------------------


def test_route_task_small_prompt_yields_haiku():
    decision = route_task({"prompt_payload": "kurzer prompt"})
    assert decision == RouterDecision.HAIKU


def test_route_task_audit_persona_yields_opus():
    decision = route_task(
        {"prompt_payload": "audit query"},
        {"persona_id": "internal-audit"},
    )
    assert decision == RouterDecision.OPUS


def test_route_task_falls_back_to_haiku_on_missing_prompt():
    decision = route_task({})
    assert decision == RouterDecision.HAIKU


def test_route_task_non_dict_payload_is_tolerated():
    # Defensive: route_task must not raise on garbage input.
    decision = route_task("not-a-dict")  # type: ignore[arg-type]
    assert decision == RouterDecision.HAIKU


def test_route_task_prompt_payload_aliases():
    # ``prompt`` and ``payload`` are accepted as fallbacks.
    d1 = route_task({"prompt": "x" * 80_000})
    d2 = route_task({"payload": "x" * 80_000})
    assert d1 == RouterDecision.OPUS
    assert d2 == RouterDecision.OPUS


# ---------------------------------------------------------------------------
# 13: RoutingEvent byte-stable JSON serialization
# ---------------------------------------------------------------------------


def test_routing_event_json_is_byte_stable():
    event_a = build_routing_event(
        persona_id="tomas",
        auftrag_id="A-123",
        task_payload={"prompt_payload": "kurz"},
        persona_def={"persona_id": "tomas"},
        static_choice="sonnet",
        ts_utc="2026-05-16T10:00:00Z",
    )
    event_b = build_routing_event(
        persona_id="tomas",
        auftrag_id="A-123",
        task_payload={"prompt_payload": "kurz"},
        persona_def={"persona_id": "tomas"},
        static_choice="sonnet",
        ts_utc="2026-05-16T10:00:00Z",
    )
    assert event_a.to_json() == event_b.to_json()
    parsed = json.loads(event_a.to_json())
    assert parsed["persona_id"] == "tomas"
    assert parsed["auftrag_id"] == "A-123"
    assert parsed["routing_mode"] == "static"
    assert parsed["static_choice"] == "sonnet"
    assert parsed["effective_choice"] == "sonnet"
    assert parsed["router_version"] == "v1"


# ---------------------------------------------------------------------------
# 14-15: build_routing_event static vs heuristic mode
# ---------------------------------------------------------------------------


def test_build_routing_event_static_mode_preserves_static_choice():
    event = build_routing_event(
        persona_id="tomas",
        auftrag_id="A-1",
        task_payload={"prompt_payload": "x" * 80_000},  # heuristic → OPUS
        persona_def={"persona_id": "tomas"},
        static_choice="haiku",
        routing_mode="static",
        ts_utc="2026-05-16T10:00:00Z",
    )
    assert event.routing_mode == "static"
    assert event.static_choice == "haiku"
    assert event.heuristic_choice == "opus"
    assert event.effective_choice == "haiku"  # static-mode preserves


def test_build_routing_event_heuristic_mode_uses_heuristic_choice():
    event = build_routing_event(
        persona_id="tomas",
        auftrag_id="A-2",
        task_payload={"prompt_payload": "x" * 80_000},
        persona_def={"persona_id": "tomas"},
        static_choice="haiku",
        routing_mode="heuristic",
        ts_utc="2026-05-16T10:00:00Z",
    )
    assert event.routing_mode == "heuristic"
    assert event.static_choice == "haiku"
    assert event.heuristic_choice == "opus"
    assert event.effective_choice == "opus"  # heuristic-mode wins


def test_build_routing_event_falls_back_to_heuristic_when_no_static():
    event = build_routing_event(
        persona_id="tomas",
        auftrag_id="A-3",
        task_payload={"prompt_payload": "kurz"},
        persona_def={"persona_id": "tomas"},
        static_choice=None,
        routing_mode="static",
        ts_utc="2026-05-16T10:00:00Z",
    )
    # static_choice is None → effective falls back to heuristic_choice.
    assert event.static_choice is None
    assert event.effective_choice == event.heuristic_choice


def test_build_routing_event_befugnis_override_recorded():
    event = build_routing_event(
        persona_id="henrik",
        auftrag_id="A-4",
        task_payload={"prompt_payload": "audit query"},
        persona_def={"persona_id": "henrik", "role": "internal-audit"},
        static_choice="sonnet",
        routing_mode="heuristic",
        ts_utc="2026-05-16T10:00:00Z",
    )
    assert event.heuristic_choice == "opus"
    assert event.befugnis_override == "audit-opus-floor"


# ---------------------------------------------------------------------------
# 16-17: HeuristicRoutingShim
# ---------------------------------------------------------------------------


def test_routing_shim_captures_events_in_list_sink():
    captured: list[RoutingEvent] = []
    shim = HeuristicRoutingShim(
        static_choice="sonnet",
        sink=captured.append,
        env={"WAKIR_ROUTING_MODE": "heuristic"},
    )
    event = shim.record(
        persona_id="tomas",
        auftrag_id="A-5",
        task_payload={"prompt_payload": "x" * 20_000},
        persona_def={"persona_id": "tomas"},
        ts_utc="2026-05-16T10:00:00Z",
    )
    assert len(captured) == 1
    assert captured[0] is event
    assert event.routing_mode == "heuristic"
    assert event.effective_choice == event.heuristic_choice
    assert shim.is_heuristic_active() is True


def test_routing_shim_swallows_broken_sink():
    def broken_sink(_event):
        raise RuntimeError("sink-down")

    shim = HeuristicRoutingShim(
        static_choice="sonnet",
        sink=broken_sink,
        env={"WAKIR_ROUTING_MODE": "heuristic"},
    )
    # Must not raise — observation-only shim must never break the
    # engine path.
    event = shim.record(
        persona_id="tomas",
        auftrag_id="A-6",
        task_payload={"prompt_payload": "kurz"},
        persona_def={"persona_id": "tomas"},
        ts_utc="2026-05-16T10:00:00Z",
    )
    assert event is not None


def test_routing_shim_no_sink_is_noop():
    shim = HeuristicRoutingShim(
        static_choice="sonnet", sink=None, env={"WAKIR_ROUTING_MODE": "static"}
    )
    event = shim.record(
        persona_id="tomas",
        auftrag_id="A-7",
        task_payload={"prompt_payload": "kurz"},
        persona_def={"persona_id": "tomas"},
        ts_utc="2026-05-16T10:00:00Z",
    )
    assert event is not None
    assert event.routing_mode == "static"
    assert shim.is_heuristic_active() is False


# ---------------------------------------------------------------------------
# llm_call_shim integration — observation-only contract
# ---------------------------------------------------------------------------


def test_call_with_routing_event_no_shim_returns_none_event():
    from wirelang.persona_engine.llm_call_shim import (
        EchoReflectionLlmHook,
        call_with_routing_event,
    )

    hook = EchoReflectionLlmHook()
    result, event = call_with_routing_event(
        hook,
        persona_id="tomas",
        auftrag_id="A-8",
        prompt_payload="hello",
        routing_shim=None,
    )
    assert result.persona_id == "tomas"
    assert event is None


def test_call_with_routing_event_with_shim_returns_event():
    from wirelang.persona_engine.llm_call_shim import (
        EchoReflectionLlmHook,
        call_with_routing_event,
    )

    captured: list[RoutingEvent] = []
    shim = HeuristicRoutingShim(
        static_choice="sonnet",
        sink=captured.append,
        env={"WAKIR_ROUTING_MODE": "heuristic"},
    )
    hook = EchoReflectionLlmHook()
    result, event = call_with_routing_event(
        hook,
        persona_id="tomas",
        auftrag_id="A-9",
        prompt_payload="hello",
        persona_def={"persona_id": "tomas"},
        routing_shim=shim,
        ts_utc="2026-05-16T10:00:00Z",
    )
    assert result.persona_id == "tomas"
    assert event is not None
    assert len(captured) == 1
    assert captured[0].routing_mode == "heuristic"


def test_maybe_attach_routing_shim_static_mode_returns_none():
    from wirelang.persona_engine.llm_call_shim import maybe_attach_routing_shim

    shim = maybe_attach_routing_shim(
        static_choice="sonnet", env={"WAKIR_ROUTING_MODE": "static"}
    )
    assert shim is None


def test_maybe_attach_routing_shim_heuristic_mode_returns_shim():
    from wirelang.persona_engine.llm_call_shim import maybe_attach_routing_shim

    shim = maybe_attach_routing_shim(
        static_choice="sonnet", env={"WAKIR_ROUTING_MODE": "heuristic"}
    )
    assert shim is not None
    assert isinstance(shim, HeuristicRoutingShim)
    assert shim.static_choice == "sonnet"


# ---------------------------------------------------------------------------
# Determinism contract — same inputs ⇒ byte-stable RoutingEvent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt,persona_id,role,expected_decision",
    [
        ("kurz", "tomas", "dev-engineering", RouterDecision.HAIKU),
        ("x" * 80_000, "tomas", "dev-engineering", RouterDecision.OPUS),
        ("audit", "henrik", "internal-audit", RouterDecision.OPUS),
        ("comms blast", "julia", "comms", RouterDecision.HAIKU),
    ],
)
def test_route_task_parametrized_determinism(
    prompt, persona_id, role, expected_decision
):
    d1 = route_task(
        {"prompt_payload": prompt},
        {"persona_id": persona_id, "role": role},
    )
    d2 = route_task(
        {"prompt_payload": prompt},
        {"persona_id": persona_id, "role": role},
    )
    assert d1 == d2 == expected_decision
