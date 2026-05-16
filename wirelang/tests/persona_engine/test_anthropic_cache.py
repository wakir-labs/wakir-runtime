# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Anthropic prompt-caching helpers
(Sprint-Pengine-14 OI-PCACHE-1, ADR-0064 Phase-2a).

These tests drive ``wirelang.persona_engine.anthropic_cache`` and the
``LlmCallHook.supports_caching`` extension on the Phase-2-Stub
``EchoReflectionLlmHook``. No network call, no ``anthropic`` SDK
import, no live mock-server — all inputs are stdlib literals.

Vector count
------------

The test surface ships 27 vectors covering:

1.  Cache-Breakpoint placement: system+persona+tools cached, task-payload NOT cached
2.  V-907 pin in the cache-affinity key (pin change -> different key)
3.  Cache-TTL env-var honour: default 300 -> "5m"
4.  Cache-TTL env-var honour: override 600 -> still "5m" slot
5.  Cache-TTL env-var honour: override 1800 -> "5m" slot upper edge
6.  Cache-TTL env-var honour: override 1801 -> "1h" slot
7.  Cache-TTL env-var honour: override 3600 -> "1h" exact
8.  Cache-TTL env-var honour: override 7200 -> clamped to 3600 ("1h")
9.  Cache-disabled path: WAKIR_ANTHROPIC_CACHE_TTL_SECONDS=0 -> no cache_control block
10. Cache-disabled path: affinity key still encodes ttl0 for telemetry
11. Mock-Anthropic-response telemetry parsing: cache_read > 0
12. Mock-Anthropic-response telemetry parsing: cache_creation > 0
13. Mock-Anthropic-response telemetry parsing: cache_creation breakdown 5m vs 1h
14. Mock-Anthropic-response telemetry parsing: missing cache_creation dict -> None
15. Mock-Anthropic-response telemetry log-format JSON shape
16. supports_caching() interface: EchoReflectionLlmHook returns False
17. supports_caching() interface: module-level anthropic_hook_supports_caching True
18. CachedRequestPayload.breakpoint_count cap: <= ANTHROPIC_MAX_CACHE_BREAKPOINTS
19. Cache-affinity key model-scoping (different model -> different key)
20. Cache-affinity key persona-scoping (different persona -> different key)
21. Resolve-TTL malformed env raises ValueError
22. Resolve-TTL negative env raises ValueError
23. build_anthropic_request_payload rejects empty static prefix
24. build_anthropic_request_payload includes tools when supplied
25. build_anthropic_request_payload places task in messages array
26. Cache-hit-rate calculation on zero-input degenerate response
27. CacheTelemetry.to_structured_log_line yields stable JSON
"""

from __future__ import annotations

import json

import pytest

from wirelang.persona_engine.anthropic_cache import (
    ANTHROPIC_MAX_CACHE_BREAKPOINTS,
    DEFAULT_CACHE_TTL_SECONDS,
    ENV_CACHE_TTL_SECONDS,
    TTL_STRING_1H,
    TTL_STRING_5M,
    CacheTelemetry,
    CachedRequestPayload,
    CacheTtlResolution,
    anthropic_hook_supports_caching,
    build_anthropic_request_payload,
    derive_cache_affinity_key,
    parse_cache_telemetry,
    resolve_cache_ttl_from_env,
)
from wirelang.persona_engine.llm_call_shim import EchoReflectionLlmHook


# ---------------------------------------------------------------------
# Shared fixture inputs
# ---------------------------------------------------------------------


PERSONA_ID = "tomas"
V907_PIN = "sha256:" + ("a" * 64)
V907_PIN_DRIFTED = "sha256:" + ("b" * 64)
MODEL_OPUS = "claude-opus-4-7"
MODEL_SONNET = "claude-sonnet-4-6"
STATIC_PREFIX = (
    "SYSTEM: You are the wakir-persona-engine bridge.\n"
    "PERSONA: tomas — WAT-OTS lead.\n"
    "TOOLS: shell, read, write."
)
TASK_PAYLOAD = "Build the V-907 substrate annex."


# =====================================================================
# 1. Cache-Breakpoint placement (system cached, task not cached)
# =====================================================================


def test_breakpoint_on_system_block_when_enabled():
    """Vector 1: cache_control sits on the system block, not the user
    message block."""
    out = build_anthropic_request_payload(
        model=MODEL_OPUS,
        persona_id=PERSONA_ID,
        v907_pin=V907_PIN,
        static_prefix_text=STATIC_PREFIX,
        task_user_text=TASK_PAYLOAD,
        env={},
    )
    assert out.cache_enabled is True
    sys_block = out.payload["system"][0]
    assert sys_block["type"] == "text"
    assert sys_block["text"] == STATIC_PREFIX
    assert sys_block["cache_control"] == {
        "type": "ephemeral",
        "ttl": TTL_STRING_5M,
    }
    # The per-task user block carries NO cache_control.
    user_block = out.payload["messages"][0]["content"][0]
    assert "cache_control" not in user_block
    assert user_block["text"] == TASK_PAYLOAD
    assert out.breakpoint_count == 1


# =====================================================================
# 2. V-907 pin in the cache-affinity key
# =====================================================================


def test_v907_pin_change_changes_cache_affinity_key():
    """Vector 2: pin change yields a different affinity key (parity
    with Anthropic's prefix-token-driven cache slot rotation)."""
    a = derive_cache_affinity_key(
        persona_id=PERSONA_ID,
        v907_pin=V907_PIN,
        model=MODEL_OPUS,
        ttl_seconds=300,
    )
    b = derive_cache_affinity_key(
        persona_id=PERSONA_ID,
        v907_pin=V907_PIN_DRIFTED,
        model=MODEL_OPUS,
        ttl_seconds=300,
    )
    assert a != b
    assert V907_PIN in a
    assert V907_PIN_DRIFTED in b


# =====================================================================
# 3-8. Cache-TTL env-var honour
# =====================================================================


def test_ttl_default_resolves_to_300_seconds_5m_slot():
    """Vector 3: env absent -> 300s, 5m slot, source=default."""
    res = resolve_cache_ttl_from_env(env={})
    assert res.enabled is True
    assert res.seconds == DEFAULT_CACHE_TTL_SECONDS
    assert res.api_ttl_string == TTL_STRING_5M
    assert res.source == "default"
    assert res.raw_value is None


def test_ttl_override_600_seconds_still_5m_slot():
    """Vector 4: 600s is below 5m-slot upper bound -> "5m"."""
    res = resolve_cache_ttl_from_env(env={ENV_CACHE_TTL_SECONDS: "600"})
    assert res.enabled is True
    assert res.seconds == 600
    assert res.api_ttl_string == TTL_STRING_5M
    assert res.source == "env"


def test_ttl_override_1800_seconds_5m_slot_upper_edge():
    """Vector 5: 1800s is the inclusive upper bound of the 5m slot."""
    res = resolve_cache_ttl_from_env(env={ENV_CACHE_TTL_SECONDS: "1800"})
    assert res.api_ttl_string == TTL_STRING_5M
    assert res.seconds == 1800


def test_ttl_override_1801_seconds_1h_slot():
    """Vector 6: 1801s crosses into the 1h slot."""
    res = resolve_cache_ttl_from_env(env={ENV_CACHE_TTL_SECONDS: "1801"})
    assert res.api_ttl_string == TTL_STRING_1H
    assert res.seconds == 1801


def test_ttl_override_3600_seconds_1h_exact():
    """Vector 7: 3600s = exactly one hour."""
    res = resolve_cache_ttl_from_env(env={ENV_CACHE_TTL_SECONDS: "3600"})
    assert res.api_ttl_string == TTL_STRING_1H
    assert res.seconds == 3600


def test_ttl_override_above_3600_clamped_to_1h():
    """Vector 8: > 3600 clamps to 3600 with 1h slot."""
    res = resolve_cache_ttl_from_env(
        env={ENV_CACHE_TTL_SECONDS: "7200"}
    )
    assert res.api_ttl_string == TTL_STRING_1H
    assert res.seconds == 3600


# =====================================================================
# 9. Cache-disabled path
# =====================================================================


def test_cache_disabled_path_emits_no_cache_control():
    """Vector 9: env=0 -> no cache_control block on system."""
    out = build_anthropic_request_payload(
        model=MODEL_OPUS,
        persona_id=PERSONA_ID,
        v907_pin=V907_PIN,
        static_prefix_text=STATIC_PREFIX,
        task_user_text=TASK_PAYLOAD,
        env={ENV_CACHE_TTL_SECONDS: "0"},
    )
    assert out.cache_enabled is False
    sys_block = out.payload["system"][0]
    assert "cache_control" not in sys_block
    assert out.breakpoint_count == 0


# =====================================================================
# 10. Cache-disabled affinity key still tagged
# =====================================================================


def test_cache_disabled_affinity_key_tags_ttl0():
    """Vector 10: affinity key carries `ttl0` when caching is disabled
    so telemetry consumers can distinguish disabled-mode runs."""
    out = build_anthropic_request_payload(
        model=MODEL_OPUS,
        persona_id=PERSONA_ID,
        v907_pin=V907_PIN,
        static_prefix_text=STATIC_PREFIX,
        task_user_text=TASK_PAYLOAD,
        env={ENV_CACHE_TTL_SECONDS: "0"},
    )
    assert out.cache_affinity_key.endswith(":ttl0")


# =====================================================================
# 11-15. Mock-Anthropic-response telemetry parsing
# =====================================================================


def _affinity() -> str:
    return derive_cache_affinity_key(
        persona_id=PERSONA_ID,
        v907_pin=V907_PIN,
        model=MODEL_OPUS,
        ttl_seconds=300,
    )


def test_telemetry_parses_cache_read_field():
    """Vector 11: a cache-hit response surfaces cache_read_input_tokens."""
    usage = {
        "input_tokens": 50,
        "output_tokens": 120,
        "cache_read_input_tokens": 1800,
        "cache_creation_input_tokens": 0,
    }
    tel = parse_cache_telemetry(usage=usage, cache_affinity_key=_affinity())
    assert tel.cache_read_input_tokens == 1800
    assert tel.cache_creation_input_tokens == 0
    assert tel.input_tokens == 50
    assert tel.output_tokens == 120
    # 1800 / (1800 + 0 + 50) = 0.9729...
    assert abs(tel.cache_hit_rate_input_only - (1800 / 1850)) < 1e-9


def test_telemetry_parses_cache_creation_field():
    """Vector 12: cold-start / cache-write response surfaces
    cache_creation_input_tokens with hit_rate=0."""
    usage = {
        "input_tokens": 50,
        "output_tokens": 120,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 5120,
    }
    tel = parse_cache_telemetry(usage=usage, cache_affinity_key=_affinity())
    assert tel.cache_creation_input_tokens == 5120
    assert tel.cache_read_input_tokens == 0
    assert tel.cache_hit_rate_input_only == 0.0


def test_telemetry_parses_cache_creation_breakdown():
    """Vector 13: cache_creation.ephemeral_5m_input_tokens and
    ephemeral_1h_input_tokens both surfaced."""
    usage = {
        "input_tokens": 50,
        "output_tokens": 120,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 5120,
        "cache_creation": {
            "ephemeral_5m_input_tokens": 4000,
            "ephemeral_1h_input_tokens": 1120,
        },
    }
    tel = parse_cache_telemetry(usage=usage, cache_affinity_key=_affinity())
    assert tel.cache_ephemeral_5m_input_tokens == 4000
    assert tel.cache_ephemeral_1h_input_tokens == 1120


def test_telemetry_missing_breakdown_yields_none():
    """Vector 14: older response shape (no cache_creation sub-dict) ->
    None for the per-slot breakdown."""
    usage = {
        "input_tokens": 50,
        "output_tokens": 120,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    tel = parse_cache_telemetry(usage=usage, cache_affinity_key=_affinity())
    assert tel.cache_ephemeral_5m_input_tokens is None
    assert tel.cache_ephemeral_1h_input_tokens is None


def test_telemetry_log_line_json_shape_stable():
    """Vector 15: to_structured_log_line emits a sort_keys JSON object
    with the documented event name."""
    usage = {
        "input_tokens": 50,
        "output_tokens": 120,
        "cache_read_input_tokens": 1800,
        "cache_creation_input_tokens": 0,
        "cache_creation": {
            "ephemeral_5m_input_tokens": 0,
            "ephemeral_1h_input_tokens": 0,
        },
    }
    tel = parse_cache_telemetry(usage=usage, cache_affinity_key=_affinity())
    line = tel.to_structured_log_line()
    # Re-parse: must be valid JSON.
    decoded = json.loads(line)
    assert decoded["event"] == "anthropic_cache_telemetry"
    assert decoded["cache_read_input_tokens"] == 1800
    assert decoded["cache_creation_input_tokens"] == 0
    # sort_keys=True -> keys appear in lexicographic order.
    keys = list(decoded.keys())
    assert keys == sorted(keys)


# =====================================================================
# 16-17. supports_caching() interface
# =====================================================================


def test_echo_reflection_supports_caching_false():
    """Vector 16: Phase-2-Stub returns False (no LLM prefix to cache)."""
    hook = EchoReflectionLlmHook()
    assert hook.supports_caching() is False


def test_anthropic_module_supports_caching_true():
    """Vector 17: module-level capability probe returns True."""
    assert anthropic_hook_supports_caching() is True


# =====================================================================
# 18. Breakpoint count cap
# =====================================================================


def test_breakpoint_count_within_anthropic_limit():
    """Vector 18: B.2 pattern emits exactly 0 or 1 breakpoint, well
    within the documented Anthropic limit of 4."""
    out = build_anthropic_request_payload(
        model=MODEL_OPUS,
        persona_id=PERSONA_ID,
        v907_pin=V907_PIN,
        static_prefix_text=STATIC_PREFIX,
        task_user_text=TASK_PAYLOAD,
        env={},
    )
    assert out.breakpoint_count <= ANTHROPIC_MAX_CACHE_BREAKPOINTS
    assert out.breakpoint_count in (0, 1)


# =====================================================================
# 19-20. Affinity key scoping
# =====================================================================


def test_affinity_key_model_scoped():
    """Vector 19: different model -> different affinity key."""
    opus = derive_cache_affinity_key(
        persona_id=PERSONA_ID,
        v907_pin=V907_PIN,
        model=MODEL_OPUS,
        ttl_seconds=300,
    )
    sonnet = derive_cache_affinity_key(
        persona_id=PERSONA_ID,
        v907_pin=V907_PIN,
        model=MODEL_SONNET,
        ttl_seconds=300,
    )
    assert opus != sonnet
    assert MODEL_OPUS in opus
    assert MODEL_SONNET in sonnet


def test_affinity_key_persona_scoped():
    """Vector 20: different persona -> different affinity key."""
    tomas = derive_cache_affinity_key(
        persona_id="tomas",
        v907_pin=V907_PIN,
        model=MODEL_OPUS,
        ttl_seconds=300,
    )
    reza = derive_cache_affinity_key(
        persona_id="reza",
        v907_pin=V907_PIN,
        model=MODEL_OPUS,
        ttl_seconds=300,
    )
    assert tomas != reza


# =====================================================================
# 21-22. Resolve-TTL malformed input
# =====================================================================


def test_resolve_ttl_malformed_env_raises():
    """Vector 21: non-integer env var raises ValueError."""
    with pytest.raises(ValueError):
        resolve_cache_ttl_from_env(env={ENV_CACHE_TTL_SECONDS: "abc"})


def test_resolve_ttl_negative_env_raises():
    """Vector 22: negative env var raises ValueError."""
    with pytest.raises(ValueError):
        resolve_cache_ttl_from_env(env={ENV_CACHE_TTL_SECONDS: "-1"})


# =====================================================================
# 23. Empty-prefix guard
# =====================================================================


def test_build_payload_rejects_empty_static_prefix():
    """Vector 23: builder rejects empty static prefix (defeats
    operator-intent of B.2 — the whole point is a substantive prefix
    to cache)."""
    with pytest.raises(ValueError):
        build_anthropic_request_payload(
            model=MODEL_OPUS,
            persona_id=PERSONA_ID,
            v907_pin=V907_PIN,
            static_prefix_text="",
            task_user_text=TASK_PAYLOAD,
            env={},
        )


# =====================================================================
# 24. Tools array pass-through
# =====================================================================


def test_build_payload_includes_tools_when_supplied():
    """Vector 24: tools list is passed through verbatim, no
    auto-decoration with cache_control (Phase-2a defers tool-array
    breakpoints to a later phase)."""
    tools = [
        {
            "name": "shell_exec",
            "description": "Execute a shell command.",
            "input_schema": {"type": "object"},
        },
    ]
    out = build_anthropic_request_payload(
        model=MODEL_OPUS,
        persona_id=PERSONA_ID,
        v907_pin=V907_PIN,
        static_prefix_text=STATIC_PREFIX,
        task_user_text=TASK_PAYLOAD,
        tools=tools,
        env={},
    )
    assert out.payload["tools"] == tools
    assert "cache_control" not in out.payload["tools"][0]


# =====================================================================
# 25. Task lives in messages array
# =====================================================================


def test_build_payload_places_task_in_messages_array():
    """Vector 25: task text lives in messages[0].content[0].text with
    role=user."""
    out = build_anthropic_request_payload(
        model=MODEL_OPUS,
        persona_id=PERSONA_ID,
        v907_pin=V907_PIN,
        static_prefix_text=STATIC_PREFIX,
        task_user_text=TASK_PAYLOAD,
        env={},
    )
    msg = out.payload["messages"][0]
    assert msg["role"] == "user"
    assert msg["content"][0]["type"] == "text"
    assert msg["content"][0]["text"] == TASK_PAYLOAD


# =====================================================================
# 26. Hit-rate zero-input degenerate case
# =====================================================================


def test_telemetry_zero_input_yields_zero_hit_rate():
    """Vector 26: degenerate response (no input tokens at all) -> 0.0,
    not ZeroDivisionError."""
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    tel = parse_cache_telemetry(usage=usage, cache_affinity_key=_affinity())
    assert tel.cache_hit_rate_input_only == 0.0
    assert tel.total_input_tokens == 0


# =====================================================================
# 27. JSON log line stable across repeats (sort_keys=True contract)
# =====================================================================


def test_telemetry_log_line_byte_stable_across_repeats():
    """Vector 27: same usage -> byte-identical log line (sort_keys=True
    + dataclass(frozen=True) determinism)."""
    usage = {
        "input_tokens": 50,
        "output_tokens": 120,
        "cache_read_input_tokens": 1800,
        "cache_creation_input_tokens": 0,
    }
    tel1 = parse_cache_telemetry(usage=usage, cache_affinity_key=_affinity())
    tel2 = parse_cache_telemetry(usage=usage, cache_affinity_key=_affinity())
    assert tel1.to_structured_log_line() == tel2.to_structured_log_line()


# =====================================================================
# Bonus: CachedRequestPayload field roundtrip + dataclass surface
# =====================================================================


def test_cached_request_payload_is_frozen_dataclass():
    """Defence: CachedRequestPayload is immutable; downstream code
    cannot mutate the payload mapping by accident."""
    out = build_anthropic_request_payload(
        model=MODEL_OPUS,
        persona_id=PERSONA_ID,
        v907_pin=V907_PIN,
        static_prefix_text=STATIC_PREFIX,
        task_user_text=TASK_PAYLOAD,
        env={},
    )
    with pytest.raises((AttributeError, Exception)):
        out.cache_enabled = False  # type: ignore[misc]


def test_ttl_resolution_passthrough_overrides_env():
    """Defence: pre-resolved TTL bypasses env entirely (useful for
    deterministic CI runs)."""
    resolved = CacheTtlResolution(
        enabled=True,
        seconds=3600,
        api_ttl_string=TTL_STRING_1H,
        source="env",
        raw_value="3600",
    )
    out = build_anthropic_request_payload(
        model=MODEL_OPUS,
        persona_id=PERSONA_ID,
        v907_pin=V907_PIN,
        static_prefix_text=STATIC_PREFIX,
        task_user_text=TASK_PAYLOAD,
        ttl_resolution=resolved,
        env={ENV_CACHE_TTL_SECONDS: "0"},  # would normally disable
    )
    sys_block = out.payload["system"][0]
    assert sys_block["cache_control"]["ttl"] == TTL_STRING_1H
