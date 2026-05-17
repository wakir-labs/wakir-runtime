# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""LLM-Call-Shim — Sprint-Pengine-10 OI-PEFR-8 (Phase-2-Stub, Phase-3-Ersatz).

Overview
--------

The Wakir-Runtime persona-engine receives engineering Aufträge via the
Bridge-Forward-Pipe (Sprint-10 Tag-6, ``wirelang/specs/bridge-forward-
pipe-v1.md``). To start the Doppelbetrieb-Vergleich-4-Wochen-Clock
**we need outputs to compare** — but Phase-2-Pilot is intentionally
*not* the moment when real LLM-inference goes live. Phase-3 (Anthropic
API plug-in) carries that substrate.

This module provides the **Phase-2-Stub**: a deterministic echo
responder that emits a reply payload derived from the prompt without
any network or LLM call. The reply is deterministic across repeats for
the same inputs (modulo the operator-supplied ``ts_utc``) so the
Doppelbetrieb-Score-CLI can produce stable verdicts during the pilot.

The shim is also the **Phase-3 hook surface**: callers obtain an
``LlmCallHook`` and the engine wires that single hook through the
subscribe-loop. Phase-3 swaps the implementation (e.g.
``AnthropicMessagesHook``) without touching the subscribe-loop or
engine code.

Determinism contract
--------------------

Given identical ``persona_id``, ``prompt_payload``, and ``ts_utc``, the
``EchoReflectionLlmHook`` MUST return byte-identical
``LlmCallResult.reply_text`` and ``reply_sha256``. This is the
foundation of the Doppelbetrieb-Score-CLI byte-for-byte comparison.

The reply shape is **intentionally non-conversational** for the
Phase-2-Stub: it is an audit-tag, not a simulated assistant response.
The point is to flow data through the subscribe -> hook -> bridge-
audit pipeline so the substrate is exercised end-to-end before
Phase-3.

Reply text format
-----------------

::

    echo-reflection v1
    persona_id=<persona_id>
    auftrag_id=<auftrag_id>
    prompt_sha256=sha256:<64hex>
    ts_utc=<rfc3339-utc>
    prompt_byte_len=<int>
    prompt_line_count=<int>
    <empty line>
    <first 256 chars of prompt_payload, newlines preserved>

The 256-char prefix preserves enough of the prompt for human-readable
audit at the Pre-Framework-sink (bridge-audit.md) while keeping the
reply envelope size-bounded.

Hermetic-test surface
---------------------

All tests in ``wirelang/tests/persona_engine/test_llm_call_shim.py``
are pure-stdlib (no network, no LLM). The shim never imports
``anthropic``, ``httpx``, or any other external dependency.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Optional, Protocol

from .heuristic_router import (
    HeuristicRoutingShim,
    RoutingEvent,
    read_routing_mode,
)
from .llm_classifier import (
    LlmClassifierEvent,
    LlmClassifierRouter,
    is_llm_classifier_mode,
    maybe_attach_classifier_router,
)

ECHO_REFLECTION_VERSION = "v1"
ECHO_REFLECTION_PROMPT_PREFIX_CHARS = 256


def _utc_now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LlmCallResult:
    """The outcome of one LLM-call (or its Phase-2-Stub equivalent).

    Fields:

    - ``persona_id``: the persona that owns this call (pass-through).
    - ``auftrag_id``: the round-trip key from the Bridge-Forward-Pipe
      envelope (pass-through to the engineering-output envelope).
    - ``prompt_sha256``: sha256 of the prompt UTF-8 bytes.
    - ``reply_text``: the reply payload (UTF-8 text).
    - ``reply_sha256``: sha256 of the reply UTF-8 bytes.
    - ``ts_utc``: RFC3339 UTC timestamp the hook completed at.
    - ``hook_kind``: discriminator for the hook implementation
      (``echo-reflection`` for the Phase-2-Stub).
    """

    persona_id: str
    auftrag_id: str
    prompt_sha256: str
    reply_text: str
    reply_sha256: str
    ts_utc: str
    hook_kind: str


# ---------------------------------------------------------------------------
# Hook protocol
# ---------------------------------------------------------------------------


class LlmCallHook(Protocol):
    """The single interface the engine binds against.

    Phase-2 implementation: :class:`EchoReflectionLlmHook`.
    Phase-3 implementation: e.g. ``AnthropicMessagesHook`` (out of scope
    for Sprint-Pengine-10).

    Sprint-Pengine-14 extension (ADR-0064 Phase-2a): hooks expose a
    :meth:`supports_caching` capability probe so the engine knows
    whether to attach the Anthropic-Messages-API ``cache_control``
    prefix-breakpoint to the request payload. Provider-lock-in
    boundary per ADR-0064 §"Provider-Lock-In": OpenAI / other-provider
    hooks return ``False`` because their cache models are not
    compatible with the B.2 breakpoint shape; this is a *capability*
    contract, not a routing contract.
    """

    def call(
        self,
        *,
        persona_id: str,
        auftrag_id: str,
        prompt_payload: str,
        ts_utc: Optional[str] = None,
    ) -> LlmCallResult:
        ...

    def supports_caching(self) -> bool:
        """Capability probe — ``True`` iff the hook accepts the
        Anthropic-Messages-API ``cache_control`` prefix-breakpoint
        shape. Stub hooks and non-Anthropic provider hooks return
        ``False``.
        """
        ...


# ---------------------------------------------------------------------------
# Phase-2-Stub: EchoReflectionLlmHook
# ---------------------------------------------------------------------------


@dataclass
class EchoReflectionLlmHook:
    """Deterministic echo-reflection LLM-Stub for Phase-2-Pilot.

    Does NOT call any LLM. Returns a reply derived purely from the
    inputs (persona_id, auftrag_id, prompt_payload, ts_utc) so the
    Doppelbetrieb-Score-CLI can compare against a Pre-Framework
    Tomás-Spawn output with byte-stable determinism.

    Parameters:

    - ``prompt_prefix_chars``: how many leading chars of the prompt to
      include in the reply. Default 256 (per
      ``ECHO_REFLECTION_PROMPT_PREFIX_CHARS``). Set to 0 for
      hash-only-mode (no prompt-prefix in reply).
    """

    prompt_prefix_chars: int = ECHO_REFLECTION_PROMPT_PREFIX_CHARS

    HOOK_KIND: str = field(default="echo-reflection", init=False)

    def call(
        self,
        *,
        persona_id: str,
        auftrag_id: str,
        prompt_payload: str,
        ts_utc: Optional[str] = None,
    ) -> LlmCallResult:
        ts = ts_utc or _utc_now_rfc3339()
        prompt_sha = _sha256(prompt_payload)
        prompt_bytes = prompt_payload.encode("utf-8")
        line_count = prompt_payload.count("\n") + (
            0 if (prompt_payload == "" or prompt_payload.endswith("\n")) else 1
        )
        prefix = (
            prompt_payload[: self.prompt_prefix_chars]
            if self.prompt_prefix_chars > 0
            else ""
        )
        lines = [
            f"echo-reflection {ECHO_REFLECTION_VERSION}",
            f"persona_id={persona_id}",
            f"auftrag_id={auftrag_id}",
            f"prompt_sha256={prompt_sha}",
            f"ts_utc={ts}",
            f"prompt_byte_len={len(prompt_bytes)}",
            f"prompt_line_count={line_count}",
            "",
            prefix,
        ]
        reply_text = "\n".join(lines)
        return LlmCallResult(
            persona_id=persona_id,
            auftrag_id=auftrag_id,
            prompt_sha256=prompt_sha,
            reply_text=reply_text,
            reply_sha256=_sha256(reply_text),
            ts_utc=ts,
            hook_kind=self.HOOK_KIND,
        )

    def supports_caching(self) -> bool:
        """Phase-2-Stub never sends prefix-breakpoint cache_control.

        The echo-reflection responder does not call an LLM; it has no
        prefix to cache. Returning ``False`` keeps the engine code-path
        identical between stub and live-LLM modes.
        """
        return False


# ---------------------------------------------------------------------------
# Phase-3 hook stub (NOT implemented)
# ---------------------------------------------------------------------------


class AnthropicMessagesHookNotImplemented(NotImplementedError):
    """Placeholder for the Phase-3 Anthropic Messages API hook.

    Sprint-Pengine-10 ships the Phase-2-Stub (EchoReflectionLlmHook).
    The Anthropic-API plug-in lands in a dedicated Phase-3 sprint with
    its own:

    - API-key env-var contract (``ANTHROPIC_API_KEY``).
    - Rate-limit + retry-with-backoff policy.
    - Cost-cap guard (budget cents per spawn-session).
    - Bridge-Audit-Writer integration that flags `hook_kind=anthropic-messages`.

    Raising this error from the call-site documents the substitution
    point without shipping un-vetted live-API code.
    """


def anthropic_messages_hook_phase_3_stub() -> LlmCallHook:
    """Factory that fails fast with a documented NotImplementedError.

    The Sprint-Pengine-10 substrate intentionally does NOT ship a
    live-LLM-call. Callers that import this factory get a clear signal
    that Phase-3 substance is the next sprint.
    """
    raise AnthropicMessagesHookNotImplemented(
        "AnthropicMessagesHook is Phase-3 substance; Sprint-Pengine-10 "
        "ships the Phase-2-Stub EchoReflectionLlmHook only."
    )


# ---------------------------------------------------------------------------
# Heuristic-Routing wrapper (ADR-0064 Phase-2b, optional pre-hook)
# ---------------------------------------------------------------------------


def call_with_routing_event(
    hook: LlmCallHook,
    *,
    persona_id: str,
    auftrag_id: str,
    prompt_payload: str,
    persona_def: Optional[dict] = None,
    static_choice: Optional[str] = None,
    routing_shim: Optional[HeuristicRoutingShim] = None,
    ts_utc: Optional[str] = None,
) -> tuple[LlmCallResult, Optional[RoutingEvent]]:
    """Invoke ``hook.call`` with an optional Phase-2b routing-event log.

    This wrapper is the **ADR-0064 §A.3 Phase-2b integration point**:
    callers (engine code-paths) may use it to record a routing-event
    before delegating to the underlying LLM-hook. Default behaviour
    is non-invasive — if ``routing_shim`` is ``None``, the wrapper
    degenerates to a plain ``hook.call`` and returns
    ``(result, None)``.

    When ``routing_shim`` is provided, the wrapper builds a
    :class:`RoutingEvent` (via :meth:`HeuristicRoutingShim.record`)
    *before* calling ``hook.call``. The routing-event is **observation
    only** in Phase-2b — the effective model used by the hook is
    decided by the hook itself, not by the routing-event. This
    preserves ADR-0064 §"Risiken und Annahmen" mitigation: Heuristic-
    Drift-Risiko stays bounded because the heuristic does not yet
    drive live model-swap.

    ENV-default contract: see
    :data:`heuristic_router.WAKIR_ROUTING_MODE_ENV`. The wrapper
    itself does not branch on the env-var — it simply records the
    mode-tagged event when a shim is wired. Engine integration code
    decides whether to attach the shim based on the env-var so the
    static-mode code-path stays byte-identical to pre-Phase-2b.
    """
    result = hook.call(
        persona_id=persona_id,
        auftrag_id=auftrag_id,
        prompt_payload=prompt_payload,
        ts_utc=ts_utc,
    )
    if routing_shim is None:
        return result, None
    event = routing_shim.record(
        persona_id=persona_id,
        auftrag_id=auftrag_id,
        task_payload={"prompt_payload": prompt_payload},
        persona_def=persona_def,
        ts_utc=ts_utc or result.ts_utc,
    )
    return result, event


def maybe_attach_routing_shim(
    *,
    static_choice: Optional[str] = None,
    sink: Optional[object] = None,
    env: Optional[dict] = None,
) -> Optional[HeuristicRoutingShim]:
    """Factory: return a :class:`HeuristicRoutingShim` iff routing-mode
    is opt-in-enabled via :data:`heuristic_router.WAKIR_ROUTING_MODE_ENV`.

    Engine wiring code-pattern:

    ::

        shim = maybe_attach_routing_shim(
            static_choice=persona_def.get("llm_tier"),
            sink=my_routing_sink,
        )
        result, event = call_with_routing_event(
            hook, ..., routing_shim=shim,
        )

    Default-aus: when the env-var is unset (or ``static``), this
    factory returns ``None`` and the call-site sees no routing-event.
    Production behaviour is identical to pre-Phase-2b. Engineering
    teams opt in by setting ``WAKIR_ROUTING_MODE=heuristic`` in the
    Quadlet env-file or the systemd unit, never in code.
    """
    if read_routing_mode(env) != "heuristic":
        return None
    return HeuristicRoutingShim(static_choice=static_choice, sink=sink, env=env)


# ---------------------------------------------------------------------------
# LLM-Classifier-Routing wrapper (ADR-0064 Phase-2c, optional pre-hook)
# ---------------------------------------------------------------------------


def call_with_classifier_event(
    hook: LlmCallHook,
    *,
    persona_id: str,
    auftrag_id: str,
    prompt_payload: str,
    persona_def: Optional[dict] = None,
    static_choice: Optional[str] = None,
    classifier_router: Optional[LlmClassifierRouter] = None,
    ts_utc: Optional[str] = None,
) -> tuple[LlmCallResult, Optional[LlmClassifierEvent]]:
    """Invoke ``hook.call`` with an optional Phase-2c classifier-event log.

    This wrapper is the **ADR-0064 §A.4 Phase-2c integration point** —
    sister-function to :func:`call_with_routing_event` (Phase-2b). If
    ``classifier_router`` is ``None`` the wrapper degenerates to a
    plain ``hook.call`` and returns ``(result, None)`` so the static-
    mode code-path stays byte-identical to pre-Phase-2c.

    When ``classifier_router`` is provided, the wrapper invokes
    :meth:`LlmClassifierRouter.decide` *before* calling ``hook.call``
    and dispatches the resulting :class:`LlmClassifierEvent` to the
    router's sink. The event is **observation only** in Phase-2c —
    the live model used by ``hook`` is still decided by the hook
    itself; the substrate here ships the classifier-decision
    telemetry + the fallback contract, not the live model-swap.
    This preserves ADR-0064 §"Risiken und Annahmen": Classifier-
    Cost-Drift-Risiko stays bounded because the classifier verdict
    does not yet drive live traffic.

    Engine integration code decides whether to attach the router
    based on ``WAKIR_ROUTING_MODE`` (see
    :func:`llm_classifier.maybe_attach_classifier_router`).
    """
    result = hook.call(
        persona_id=persona_id,
        auftrag_id=auftrag_id,
        prompt_payload=prompt_payload,
        ts_utc=ts_utc,
    )
    if classifier_router is None:
        return result, None
    event = classifier_router.decide(
        persona_id=persona_id,
        auftrag_id=auftrag_id,
        task_payload={"prompt_payload": prompt_payload},
        persona_def=persona_def,
        static_choice=static_choice,
        ts_utc=ts_utc or result.ts_utc,
    )
    return result, event


__all__ = [
    "AnthropicMessagesHookNotImplemented",
    "ECHO_REFLECTION_PROMPT_PREFIX_CHARS",
    "ECHO_REFLECTION_VERSION",
    "EchoReflectionLlmHook",
    "LlmCallHook",
    "LlmCallResult",
    "LlmClassifierEvent",
    "LlmClassifierRouter",
    "anthropic_messages_hook_phase_3_stub",
    "call_with_classifier_event",
    "call_with_routing_event",
    "is_llm_classifier_mode",
    "maybe_attach_classifier_router",
    "maybe_attach_routing_shim",
]
