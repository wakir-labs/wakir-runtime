# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Anthropic-Call Production-Mode Integration — ADR-0064 Phase-2b.

Overview
--------

Phase-2b (Heuristic-Routing-Stub) and Phase-2c (LLM-Classifier-Stub)
both shipped their decision logic + telemetry envelopes as
*observation-only* substrates: the routing decision is *recorded* but
the hook's effective model is decided by the hook itself. This module
is the **production-mode integration entry-point** that closes the loop:
it inspects ``WAKIR_ROUTING_MODE`` *before* the LLM-hook is invoked,
runs the configured router (heuristic / classifier / fallback-chain) to
pick a tier, maps the tier to a concrete Anthropic model-id, and
returns the model-id alongside the routing-decision telemetry. The
caller wires the returned model-id into the actual Anthropic-Messages
``messages.create`` request body.

Provider-lock-in boundary
-------------------------

The router emits *tier-names* (``haiku`` / ``sonnet`` / ``opus``); this
module emits *concrete Anthropic model-ids* (e.g.
``claude-haiku-4-5-20251015``). The tier-to-model-id mapping is the
single provider-lock-in surface: a different provider (OpenAI / Gemini)
substitutes the mapping function without touching the router substrate.
The mapping is *not* persona-specific in this stub — Phase-3 may extend
to per-persona model-id pinning (e.g. ``claude-opus-4-5-1m`` for
context-hungry personas) by reading persona-def fields.

Mode contract
-------------

``WAKIR_ROUTING_MODE`` accepted values (sicherer Default ``static``):

- ``static`` — Phase-2a baseline; persona-def's ``llm_tier`` field
  picks the tier, the heuristic-router and classifier are bypassed.
  Production behaviour is byte-identical to pre-Phase-2b.
- ``heuristic`` — Phase-2b; :mod:`heuristic_router` picks the tier.
- ``llm_classifier`` — Phase-2c; :mod:`llm_classifier` picks the tier;
  on a classifier error the *call fails fast* (the operator has opted
  into the classifier path; failures surface).
- ``llm_classifier_fallback_heuristic`` — Phase-2c with the explicit
  safety-net: on a classifier error (raised exception, missing
  backend, sub-threshold confidence handled inside the router via the
  ``used_fallback`` field), the substrate gracefully falls back to
  the Heuristic-Router decision and records the fallback reason in
  the routing-decision JSONL.

Unknown values fall back to ``static`` to preserve production
behaviour (ADR-0064 §"Risiken und Annahmen" — Default-aus is the
fail-safe).

Tier-to-model-id mapping
------------------------

Model-IDs are sourced from the Anthropic API documentation as of
2026-05-17. The mapping is intentionally a single dict at module
scope so operators can override it via the
:func:`set_tier_model_mapping` test-hook if a hosted-service rollout
requires a frozen pin (e.g. for cost-cap policy).

Default mapping (provider-lock-in surface):

- ``haiku``  → ``claude-haiku-4-5-20251015``
- ``sonnet`` → ``claude-sonnet-4-5-20250930``
- ``opus``   → ``claude-opus-4-5-20251114``

Per ADR-0064 §"Provider-Lock-In", the substrate stays provider-agnostic
at the *router* layer. The concrete Anthropic ID strings are the only
provider-specific values; tests assert on the tier-name to keep the
test surface provider-agnostic.

Decision-JSONL telemetry sink
-----------------------------

When ``WAKIR_ROUTING_DECISION_JSONL`` is set, every decision emits a
JSON line to the configured path:

::

    {
        "ts_utc": "<rfc3339>",
        "task_id": "<auftrag_id>",
        "mode": "<static|heuristic|llm_classifier|llm_classifier_fallback_heuristic>",
        "classified_class": "<haiku|sonnet|opus|null>",
        "chosen_model": "<model-id>",
        "decision_latency_us": <int>
    }

The sink is **disabled by default** (no env-var set → no I/O) so the
hot-path stays byte-identical to pre-Phase-2b when the operator has
not opted in. File I/O errors are silently swallowed: an unavailable
telemetry target must never break the engine path. Tests exercise
both the enabled and disabled paths.

Hermetic-test surface
---------------------

All tests in
``wirelang/tests/persona_engine/test_anthropic_routing_integration.py``
are pure-stdlib: a :class:`MockAnthropicBackend` records the
``messages.create`` calls without any network access. No
``anthropic`` SDK import. Hermetic by construction.

Sandbox safety
--------------

This module **never imports the ``anthropic`` SDK** at runtime and
**never issues a network call**. The substrate ships the integration
entry-point + the model-id-mapping + the decision telemetry only. The
live ``messages.create`` plug-in is Phase-3 substance (and gated by an
operator-supplied backend implementing the :class:`AnthropicBackend`
protocol, never the SDK directly inside this module). This preserves
the Mira-Sandbox-vs.-Host-Operations separation (MEMORY entry
``feedback_sandbox_host_trennung``).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional, Protocol

from .heuristic_router import (
    HeuristicRoutingShim,
    RouterDecision,
    WAKIR_ROUTING_MODE_ENV,
    WAKIR_ROUTING_MODE_HEURISTIC,
    WAKIR_ROUTING_MODE_STATIC,
    build_routing_event,
    read_routing_mode as _read_basic_routing_mode,
    route_task,
)
from .llm_classifier import (
    LlmClassifierRouter,
    MockHaikuClassifierBackend,
    WAKIR_ROUTING_MODE_LLM_CLASSIFIER,
    is_llm_classifier_mode,
)

ANTHROPIC_CALL_VERSION = "v1"

# ---------------------------------------------------------------------------
# ENV contract — extended with the fourth mode + JSONL sink path.
# ---------------------------------------------------------------------------

WAKIR_ROUTING_MODE_LLM_CLASSIFIER_FALLBACK_HEURISTIC = (
    "llm_classifier_fallback_heuristic"
)
"""Phase-2b production-mode fourth value: classifier with explicit
heuristic fallback. The classifier is invoked first; if it raises any
exception, the substrate falls back to the heuristic-router decision
and records the fallback reason."""

WAKIR_ROUTING_DECISION_JSONL_ENV = "WAKIR_ROUTING_DECISION_JSONL"
"""Operator-facing env-var: when set to a file path, every routing
decision emits a JSON line. When unset or empty, the JSONL sink is
disabled and no I/O is performed."""

_ACCEPTED_MODES = frozenset(
    {
        WAKIR_ROUTING_MODE_STATIC,
        WAKIR_ROUTING_MODE_HEURISTIC,
        WAKIR_ROUTING_MODE_LLM_CLASSIFIER,
        WAKIR_ROUTING_MODE_LLM_CLASSIFIER_FALLBACK_HEURISTIC,
    }
)


def read_production_routing_mode(env: Optional[dict] = None) -> str:
    """Return the production-mode routing-mode string.

    Extends :func:`heuristic_router.read_routing_mode` (which only
    knows about ``static`` / ``heuristic``) with the two classifier
    modes. Unknown values fall back to ``static``.
    """
    src = env if env is not None else os.environ
    raw = (src.get(WAKIR_ROUTING_MODE_ENV) or "").strip().lower()
    if raw in _ACCEPTED_MODES:
        return raw
    return WAKIR_ROUTING_MODE_STATIC


# ---------------------------------------------------------------------------
# Tier-to-model-id mapping (provider-lock-in surface)
# ---------------------------------------------------------------------------

DEFAULT_TIER_MODEL_MAPPING: dict[str, str] = {
    RouterDecision.HAIKU.value: "claude-haiku-4-5-20251015",
    RouterDecision.SONNET.value: "claude-sonnet-4-5-20250930",
    RouterDecision.OPUS.value: "claude-opus-4-5-20251114",
}
"""Default Anthropic model-id mapping per tier.

Provider-lock-in surface: a different provider substitutes this dict.
The substrate code-paths key off the tier-name (``haiku`` / ``sonnet``
/ ``opus``), not the model-id, so the router stays provider-agnostic.
"""

_tier_model_mapping: dict[str, str] = dict(DEFAULT_TIER_MODEL_MAPPING)


def get_tier_model_mapping() -> dict[str, str]:
    """Return a copy of the current tier-to-model-id mapping."""
    return dict(_tier_model_mapping)


def set_tier_model_mapping(mapping: dict[str, str]) -> None:
    """Override the tier-to-model-id mapping (test + hosted-service hook).

    The mapping is validated for full tier coverage — every
    :class:`RouterDecision` value must appear as a key — so a partial
    override cannot silently shadow a tier and route traffic to an
    unset model-id.
    """
    required = {member.value for member in RouterDecision}
    missing = required - set(mapping.keys())
    if missing:
        raise ValueError(
            f"tier-model-mapping missing keys: {sorted(missing)} (required {sorted(required)})"
        )
    global _tier_model_mapping
    _tier_model_mapping = dict(mapping)


def reset_tier_model_mapping() -> None:
    """Restore the default mapping (test hook)."""
    global _tier_model_mapping
    _tier_model_mapping = dict(DEFAULT_TIER_MODEL_MAPPING)


def map_tier_to_model_id(tier: str) -> str:
    """Map a tier-name (``haiku`` / ``sonnet`` / ``opus``) to a model-id.

    Raises :class:`ValueError` for unknown tier-names. The caller is
    responsible for ensuring the tier is one of the
    :class:`RouterDecision` values; this function does not silently
    fall back to a default model-id because doing so could route
    traffic to an unintended (and potentially more expensive) model.
    """
    tier_normalized = tier.strip().lower() if isinstance(tier, str) else ""
    if tier_normalized not in _tier_model_mapping:
        raise ValueError(
            f"unknown tier {tier!r}; must be one of "
            f"{sorted(_tier_model_mapping.keys())}"
        )
    return _tier_model_mapping[tier_normalized]


# ---------------------------------------------------------------------------
# Decision-JSONL sink
# ---------------------------------------------------------------------------


def _utc_now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _resolve_jsonl_path(env: Optional[dict] = None) -> Optional[str]:
    src = env if env is not None else os.environ
    raw = (src.get(WAKIR_ROUTING_DECISION_JSONL_ENV) or "").strip()
    return raw if raw else None


def _emit_decision_jsonl(
    path: str,
    record: dict,
) -> None:
    """Append one JSON record to the decision-JSONL sink.

    File I/O errors are silently swallowed — an unavailable telemetry
    target must never break the engine path. Tests exercise both the
    happy-path append and the unwritable-path graceful-degradation.
    """
    try:
        line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        # Observation-only sink. Engine path stays intact even if the
        # operator-configured target is unwritable / on a read-only fs
        # / over a full disk.
        pass


# ---------------------------------------------------------------------------
# Routing decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutingDecision:
    """The result of one production-mode routing decision.

    Fields:

    - ``mode``: the resolved routing-mode (one of :data:`_ACCEPTED_MODES`).
    - ``classified_class``: the tier the router picked
      (``haiku`` / ``sonnet`` / ``opus``) or ``None`` if mode is
      ``static`` and the persona-def did not specify a tier.
    - ``chosen_model``: the concrete Anthropic model-id mapped from
      ``classified_class``. ``None`` only if both ``classified_class``
      is None *and* no fallback tier was available (caller error).
    - ``decision_latency_us``: wall-clock latency of the decision step
      in microseconds (excluding the LLM call itself).
    - ``used_fallback``: ``True`` iff the classifier path raised and
      the substrate fell back to the heuristic-router decision.
    - ``fallback_reason``: short string describing why fallback fired
      (e.g. ``"classifier-exception"``), ``None`` when no fallback.
    """

    mode: str
    classified_class: Optional[str]
    chosen_model: Optional[str]
    decision_latency_us: int
    used_fallback: bool = False
    fallback_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Anthropic-backend Protocol (Phase-3 plug-in surface)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnthropicCallRequest:
    """The minimal request envelope the substrate hands to a backend.

    Phase-3 backends translate this into an actual ``messages.create``
    request body. Phase-2b ships only the envelope + the model-id
    selection — the substrate does not yet wire a live Anthropic call.
    """

    model_id: str
    prompt_payload: str
    persona_id: str
    auftrag_id: str


@dataclass(frozen=True)
class AnthropicCallResponse:
    """The minimal response envelope a backend returns to the caller."""

    reply_text: str
    model_id: str
    backend_kind: str


class AnthropicBackend(Protocol):
    """Phase-3 plug-in surface for the live Anthropic-Messages call.

    Phase-2b ships :class:`MockAnthropicBackend` only. A real backend
    (out of scope for Sprint-Pengine-15) wraps ``anthropic.Anthropic``
    with the substrate's selected model-id + the operator-configured
    retry/backoff/cost-cap policy.
    """

    def call(self, request: AnthropicCallRequest) -> AnthropicCallResponse:
        ...


@dataclass
class MockAnthropicBackend:
    """Deterministic mock backend — no network, no anthropic SDK import.

    Records every call into ``self.calls`` so tests can assert on the
    chosen model-id without spying on a live API. The reply text is a
    debug-string that includes the model-id and a SHA-stable hash of
    the prompt so tests can verify byte-stable routing without
    dependence on the real Anthropic response shape.
    """

    BACKEND_KIND: str = field(default="mock-anthropic", init=False)
    calls: list[AnthropicCallRequest] = field(default_factory=list)

    def call(self, request: AnthropicCallRequest) -> AnthropicCallResponse:
        self.calls.append(request)
        return AnthropicCallResponse(
            reply_text=(
                f"mock-anthropic reply\n"
                f"model_id={request.model_id}\n"
                f"persona_id={request.persona_id}\n"
                f"auftrag_id={request.auftrag_id}\n"
                f"prompt_byte_len={len(request.prompt_payload.encode('utf-8'))}\n"
            ),
            model_id=request.model_id,
            backend_kind=self.BACKEND_KIND,
        )


# ---------------------------------------------------------------------------
# Decision-Step (the production-mode integration entry-point)
# ---------------------------------------------------------------------------


def decide_routing(
    *,
    persona_id: str,
    auftrag_id: str,
    prompt_payload: str,
    persona_def: Optional[dict] = None,
    static_choice: Optional[str] = None,
    classifier_router: Optional[LlmClassifierRouter] = None,
    ts_utc: Optional[str] = None,
    env: Optional[dict] = None,
) -> RoutingDecision:
    """Run the production-mode routing-decision step.

    This is the **ADR-0064 Phase-2b production-mode integration
    entry-point**. Call before invoking the Anthropic-Messages API to
    pick the model-id according to the operator-configured routing-
    mode. Returns a :class:`RoutingDecision` plus emits one line to
    the decision-JSONL sink (when configured).

    Parameters:

    - ``static_choice``: the persona-def's configured tier name
      (e.g. ``"sonnet"``). Used in ``static`` mode + as a fallback
      when no router yields a tier.
    - ``classifier_router``: optional pre-built
      :class:`LlmClassifierRouter`. When ``None`` and the mode
      requires it, the substrate constructs a default one with a
      deterministic :class:`MockHaikuClassifierBackend` (Phase-2b
      sandbox-safe default). Phase-3 wires an Anthropic-Haiku-backed
      router via this parameter.
    - ``ts_utc``: operator-supplied timestamp for deterministic
      tests; ``None`` uses :func:`time.gmtime`.
    - ``env``: optional environment-dict for hermetic tests.

    Mode behaviour:

    - ``static``: tier = ``static_choice`` (no router consulted). If
      ``static_choice`` is None / unknown, the substrate logs the gap
      and falls back to the heuristic-router decision so the call
      can still proceed.
    - ``heuristic``: tier = :func:`heuristic_router.route_task`.
    - ``llm_classifier``: tier = ``classifier_router.decide(...).effective_choice``.
      Classifier exceptions raise (operator opted into strict mode).
    - ``llm_classifier_fallback_heuristic``: as above, but classifier
      exceptions are caught and the substrate falls back to the
      heuristic-router decision, recording the fallback reason.
    """
    mode = read_production_routing_mode(env)
    start_ns = time.perf_counter_ns()
    used_fallback = False
    fallback_reason: Optional[str] = None
    tier: Optional[str] = None

    if mode == WAKIR_ROUTING_MODE_STATIC:
        if static_choice and RouterDecision.from_str(static_choice) is not None:
            tier = RouterDecision.from_str(static_choice).value  # type: ignore[union-attr]
        else:
            # Static mode without a valid static_choice: fall back to
            # heuristic so the call can proceed; flag in JSONL.
            tier = route_task(
                {"prompt_payload": prompt_payload}, persona_def
            ).value
            used_fallback = True
            fallback_reason = "static-mode-missing-static-choice"
    elif mode == WAKIR_ROUTING_MODE_HEURISTIC:
        tier = route_task(
            {"prompt_payload": prompt_payload}, persona_def
        ).value
    elif mode == WAKIR_ROUTING_MODE_LLM_CLASSIFIER:
        router = classifier_router or LlmClassifierRouter(env=env)
        event = router.decide(
            persona_id=persona_id,
            auftrag_id=auftrag_id,
            task_payload={"prompt_payload": prompt_payload},
            persona_def=persona_def,
            static_choice=static_choice,
            ts_utc=ts_utc,
        )
        tier = event.effective_choice
    elif mode == WAKIR_ROUTING_MODE_LLM_CLASSIFIER_FALLBACK_HEURISTIC:
        router = classifier_router or LlmClassifierRouter(env=env)
        try:
            event = router.decide(
                persona_id=persona_id,
                auftrag_id=auftrag_id,
                task_payload={"prompt_payload": prompt_payload},
                persona_def=persona_def,
                static_choice=static_choice,
                ts_utc=ts_utc,
            )
            tier = event.effective_choice
        except Exception as exc:  # noqa: BLE001 — substrate safety-net
            tier = route_task(
                {"prompt_payload": prompt_payload}, persona_def
            ).value
            used_fallback = True
            fallback_reason = f"classifier-exception:{type(exc).__name__}"
    else:
        # Unknown mode (should not reach: read_production_routing_mode
        # already normalises). Defensive fallback to static-tier.
        tier = (
            RouterDecision.from_str(static_choice).value  # type: ignore[union-attr]
            if static_choice and RouterDecision.from_str(static_choice) is not None
            else route_task(
                {"prompt_payload": prompt_payload}, persona_def
            ).value
        )
        used_fallback = True
        fallback_reason = f"unknown-mode:{mode}"

    elapsed_ns = time.perf_counter_ns() - start_ns
    decision_latency_us = max(0, elapsed_ns // 1000)
    chosen_model: Optional[str] = None
    if tier is not None:
        try:
            chosen_model = map_tier_to_model_id(tier)
        except ValueError:
            chosen_model = None

    decision = RoutingDecision(
        mode=mode,
        classified_class=tier,
        chosen_model=chosen_model,
        decision_latency_us=int(decision_latency_us),
        used_fallback=used_fallback,
        fallback_reason=fallback_reason,
    )

    jsonl_path = _resolve_jsonl_path(env)
    if jsonl_path:
        record = {
            "timestamp": ts_utc or _utc_now_rfc3339(),
            "task_id": auftrag_id,
            "mode": mode,
            "classified_class": tier,
            "chosen_model": chosen_model,
            "decision_latency_us": int(decision_latency_us),
        }
        if used_fallback:
            record["used_fallback"] = True
            record["fallback_reason"] = fallback_reason
        _emit_decision_jsonl(jsonl_path, record)

    return decision


# ---------------------------------------------------------------------------
# Top-level production-mode call (decision-step + backend.call)
# ---------------------------------------------------------------------------


def anthropic_call(
    *,
    persona_id: str,
    auftrag_id: str,
    prompt_payload: str,
    backend: AnthropicBackend,
    persona_def: Optional[dict] = None,
    static_choice: Optional[str] = None,
    classifier_router: Optional[LlmClassifierRouter] = None,
    ts_utc: Optional[str] = None,
    env: Optional[dict] = None,
) -> tuple[AnthropicCallResponse, RoutingDecision]:
    """Top-level production-mode call: decision-step + backend invocation.

    The function:

    1. Runs :func:`decide_routing` to pick a model-id according to the
       operator-configured routing-mode.
    2. Builds an :class:`AnthropicCallRequest` with the selected
       model-id.
    3. Invokes ``backend.call(request)``.
    4. Returns ``(response, decision)``.

    The substrate does **not** import the ``anthropic`` SDK — the
    backend is operator-supplied. Tests pass :class:`MockAnthropicBackend`
    to keep the test surface hermetic.
    """
    decision = decide_routing(
        persona_id=persona_id,
        auftrag_id=auftrag_id,
        prompt_payload=prompt_payload,
        persona_def=persona_def,
        static_choice=static_choice,
        classifier_router=classifier_router,
        ts_utc=ts_utc,
        env=env,
    )
    if decision.chosen_model is None:
        # Defensive: should not happen because decide_routing always
        # resolves a tier. If it does, surface a clear error rather
        # than silently calling with a None model-id.
        raise ValueError(
            "decide_routing returned no chosen_model — substrate cannot "
            "invoke backend.call without a model-id"
        )
    request = AnthropicCallRequest(
        model_id=decision.chosen_model,
        prompt_payload=prompt_payload,
        persona_id=persona_id,
        auftrag_id=auftrag_id,
    )
    response = backend.call(request)
    return response, decision


__all__ = [
    "ANTHROPIC_CALL_VERSION",
    "AnthropicBackend",
    "AnthropicCallRequest",
    "AnthropicCallResponse",
    "DEFAULT_TIER_MODEL_MAPPING",
    "MockAnthropicBackend",
    "RoutingDecision",
    "WAKIR_ROUTING_DECISION_JSONL_ENV",
    "WAKIR_ROUTING_MODE_ENV",
    "WAKIR_ROUTING_MODE_HEURISTIC",
    "WAKIR_ROUTING_MODE_LLM_CLASSIFIER",
    "WAKIR_ROUTING_MODE_LLM_CLASSIFIER_FALLBACK_HEURISTIC",
    "WAKIR_ROUTING_MODE_STATIC",
    "anthropic_call",
    "decide_routing",
    "get_tier_model_mapping",
    "map_tier_to_model_id",
    "read_production_routing_mode",
    "reset_tier_model_mapping",
    "set_tier_model_mapping",
]
