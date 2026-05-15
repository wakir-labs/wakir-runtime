# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the LLM-Call-Shim (Sprint-Pengine-10 OI-PEFR-8).

Covers the Phase-2-Stub EchoReflectionLlmHook (deterministic echo
responder) and the Phase-3 stub raise-fast contract.
"""

from __future__ import annotations

import hashlib

import pytest

from wirelang.persona_engine.llm_call_shim import (
    AnthropicMessagesHookNotImplemented,
    ECHO_REFLECTION_PROMPT_PREFIX_CHARS,
    ECHO_REFLECTION_VERSION,
    EchoReflectionLlmHook,
    LlmCallResult,
    anthropic_messages_hook_phase_3_stub,
)


# ---------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------


def test_echo_reflection_version_is_v1():
    assert ECHO_REFLECTION_VERSION == "v1"


def test_default_prefix_chars_is_256():
    assert ECHO_REFLECTION_PROMPT_PREFIX_CHARS == 256


# ---------------------------------------------------------------------
# EchoReflectionLlmHook — call semantics
# ---------------------------------------------------------------------


def test_call_returns_llm_call_result():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="tomas",
        auftrag_id="a-1",
        prompt_payload="hello",
        ts_utc="2026-05-15T22:00:00Z",
    )
    assert isinstance(res, LlmCallResult)


def test_call_result_has_correct_persona_id():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="tomas",
        auftrag_id="a-1",
        prompt_payload="hello",
        ts_utc="2026-05-15T22:00:00Z",
    )
    assert res.persona_id == "tomas"


def test_call_result_has_correct_auftrag_id():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="tomas",
        auftrag_id="auftrag-xyz",
        prompt_payload="hello",
        ts_utc="2026-05-15T22:00:00Z",
    )
    assert res.auftrag_id == "auftrag-xyz"


def test_call_result_has_correct_ts_utc():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="tomas",
        auftrag_id="a-1",
        prompt_payload="hello",
        ts_utc="2026-05-15T22:00:00Z",
    )
    assert res.ts_utc == "2026-05-15T22:00:00Z"


def test_call_result_hook_kind_is_echo_reflection():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="tomas",
        auftrag_id="a-1",
        prompt_payload="hello",
        ts_utc="2026-05-15T22:00:00Z",
    )
    assert res.hook_kind == "echo-reflection"


def test_prompt_sha256_format():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="tomas",
        auftrag_id="a-1",
        prompt_payload="hello",
        ts_utc="2026-05-15T22:00:00Z",
    )
    assert res.prompt_sha256.startswith("sha256:")
    expected = "sha256:" + hashlib.sha256(b"hello").hexdigest()
    assert res.prompt_sha256 == expected


def test_reply_sha256_format():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="tomas",
        auftrag_id="a-1",
        prompt_payload="hello",
        ts_utc="2026-05-15T22:00:00Z",
    )
    assert res.reply_sha256.startswith("sha256:")
    expected = "sha256:" + hashlib.sha256(
        res.reply_text.encode("utf-8")
    ).hexdigest()
    assert res.reply_sha256 == expected


# ---------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------


def test_determinism_same_inputs_same_reply():
    hook = EchoReflectionLlmHook()
    res1 = hook.call(
        persona_id="tomas",
        auftrag_id="a-1",
        prompt_payload="hello world",
        ts_utc="2026-05-15T22:00:00Z",
    )
    res2 = hook.call(
        persona_id="tomas",
        auftrag_id="a-1",
        prompt_payload="hello world",
        ts_utc="2026-05-15T22:00:00Z",
    )
    assert res1.reply_text == res2.reply_text
    assert res1.reply_sha256 == res2.reply_sha256


def test_determinism_byte_identical_across_instances():
    h1 = EchoReflectionLlmHook()
    h2 = EchoReflectionLlmHook()
    res1 = h1.call(
        persona_id="t", auftrag_id="x", prompt_payload="p",
        ts_utc="2026-01-01T00:00:00Z",
    )
    res2 = h2.call(
        persona_id="t", auftrag_id="x", prompt_payload="p",
        ts_utc="2026-01-01T00:00:00Z",
    )
    assert res1.reply_text.encode("utf-8") == res2.reply_text.encode("utf-8")


def test_different_persona_id_different_reply():
    hook = EchoReflectionLlmHook()
    a = hook.call(
        persona_id="tomas", auftrag_id="a-1", prompt_payload="hi",
        ts_utc="2026-05-15T22:00:00Z",
    )
    b = hook.call(
        persona_id="reza", auftrag_id="a-1", prompt_payload="hi",
        ts_utc="2026-05-15T22:00:00Z",
    )
    assert a.reply_text != b.reply_text


def test_different_auftrag_id_different_reply():
    hook = EchoReflectionLlmHook()
    a = hook.call(
        persona_id="tomas", auftrag_id="a-1", prompt_payload="hi",
        ts_utc="2026-05-15T22:00:00Z",
    )
    b = hook.call(
        persona_id="tomas", auftrag_id="a-2", prompt_payload="hi",
        ts_utc="2026-05-15T22:00:00Z",
    )
    assert a.reply_text != b.reply_text


def test_different_ts_utc_different_reply():
    hook = EchoReflectionLlmHook()
    a = hook.call(
        persona_id="tomas", auftrag_id="a-1", prompt_payload="hi",
        ts_utc="2026-05-15T22:00:00Z",
    )
    b = hook.call(
        persona_id="tomas", auftrag_id="a-1", prompt_payload="hi",
        ts_utc="2026-05-15T22:00:01Z",
    )
    assert a.reply_text != b.reply_text


# ---------------------------------------------------------------------
# Reply text shape
# ---------------------------------------------------------------------


def test_reply_first_line_is_echo_reflection_version():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="t", auftrag_id="a", prompt_payload="p",
        ts_utc="2026-01-01T00:00:00Z",
    )
    assert res.reply_text.splitlines()[0] == "echo-reflection v1"


def test_reply_contains_persona_id_line():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="alice", auftrag_id="a", prompt_payload="p",
        ts_utc="2026-01-01T00:00:00Z",
    )
    assert "persona_id=alice" in res.reply_text


def test_reply_contains_auftrag_id_line():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="t", auftrag_id="auftrag-foo", prompt_payload="p",
        ts_utc="2026-01-01T00:00:00Z",
    )
    assert "auftrag_id=auftrag-foo" in res.reply_text


def test_reply_contains_prompt_sha256_line():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="t", auftrag_id="a", prompt_payload="p",
        ts_utc="2026-01-01T00:00:00Z",
    )
    assert res.prompt_sha256 in res.reply_text


def test_reply_contains_byte_len_line():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="t", auftrag_id="a", prompt_payload="hello",
        ts_utc="2026-01-01T00:00:00Z",
    )
    assert "prompt_byte_len=5" in res.reply_text


def test_reply_contains_line_count_line():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="t", auftrag_id="a", prompt_payload="a\nb\nc",
        ts_utc="2026-01-01T00:00:00Z",
    )
    # 3 lines (a, b, c — no trailing newline so trailing partial counts).
    assert "prompt_line_count=3" in res.reply_text


def test_empty_prompt_line_count_zero():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="t", auftrag_id="a", prompt_payload="",
        ts_utc="2026-01-01T00:00:00Z",
    )
    assert "prompt_line_count=0" in res.reply_text


def test_reply_includes_prompt_prefix_for_short_prompt():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="t", auftrag_id="a", prompt_payload="hello world",
        ts_utc="2026-01-01T00:00:00Z",
    )
    assert "hello world" in res.reply_text


def test_reply_truncates_prompt_prefix_for_long_prompt():
    hook = EchoReflectionLlmHook(prompt_prefix_chars=10)
    big = "X" * 1000
    res = hook.call(
        persona_id="t", auftrag_id="a", prompt_payload=big,
        ts_utc="2026-01-01T00:00:00Z",
    )
    # The 10-char prefix is on its own line.
    assert "X" * 10 in res.reply_text
    # The full prompt is NOT inlined.
    assert "X" * 100 not in res.reply_text


def test_reply_prefix_zero_omits_prompt():
    hook = EchoReflectionLlmHook(prompt_prefix_chars=0)
    res = hook.call(
        persona_id="t", auftrag_id="a", prompt_payload="should-not-appear",
        ts_utc="2026-01-01T00:00:00Z",
    )
    assert "should-not-appear" not in res.reply_text


# ---------------------------------------------------------------------
# Default ts_utc handling
# ---------------------------------------------------------------------


def test_call_default_ts_utc_uses_now():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="t", auftrag_id="a", prompt_payload="p",
    )
    # Should be an RFC3339 UTC string.
    assert res.ts_utc.endswith("Z")
    assert len(res.ts_utc) == len("2026-05-15T22:00:00Z")


# ---------------------------------------------------------------------
# Phase-3 stub
# ---------------------------------------------------------------------


def test_anthropic_messages_hook_phase_3_stub_raises():
    with pytest.raises(AnthropicMessagesHookNotImplemented):
        anthropic_messages_hook_phase_3_stub()


def test_anthropic_messages_hook_not_implemented_is_subclass():
    assert issubclass(
        AnthropicMessagesHookNotImplemented,
        NotImplementedError,
    )


# ---------------------------------------------------------------------
# Unicode + edge cases
# ---------------------------------------------------------------------


def test_unicode_prompt_handled():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="t", auftrag_id="a", prompt_payload="café \U0001f680",
        ts_utc="2026-01-01T00:00:00Z",
    )
    assert "café" in res.reply_text


def test_large_prompt_handled_without_error():
    hook = EchoReflectionLlmHook()
    big = "abc" * 100_000  # 300 KB
    res = hook.call(
        persona_id="t", auftrag_id="a", prompt_payload=big,
        ts_utc="2026-01-01T00:00:00Z",
    )
    # Prefix = default 256 chars; bigger than 256 still works.
    assert "prompt_byte_len=300000" in res.reply_text


def test_newline_only_prompt():
    hook = EchoReflectionLlmHook()
    res = hook.call(
        persona_id="t", auftrag_id="a", prompt_payload="\n",
        ts_utc="2026-01-01T00:00:00Z",
    )
    # Single newline = 1 line ending with \n; line_count counts trailing
    # newline as terminator -> 1.
    assert "prompt_line_count=1" in res.reply_text
