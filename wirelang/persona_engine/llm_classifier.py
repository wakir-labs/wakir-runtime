# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""LLM-Classifier-Routing-Stub — ADR-0064 §A.4 (Phase-2c-Stub).

Overview
--------

ADR-0064 (Model-Routing + Prompt-Caching, approved 2026-05-16) lists
five candidate routing patterns. Phase-2a shipped B.2 (Static-Prefix-
Caching, see :mod:`anthropic_cache`). Phase-2b shipped A.3 (Heuristic-
Routing, see :mod:`heuristic_router`). This module is the Phase-2c
substrate for **§A.4 — LLM-Classifier-Routing**: a *separate* (cheap)
Haiku-call inspects the incoming task and emits a tier-decision
(HAIKU / SONNET / OPUS) plus a confidence score; the engine consumes
the decision when confidence clears a configurable threshold and
otherwise falls back to the Heuristic-Router (A.3) so production
behaviour stays bounded.

Design intent (Phase-2c-Stub):

- This module **never calls a real LLM**. It ships a deterministic
  ``MockHaikuClassifierBackend`` that mirrors the contract a real
  Haiku-Messages-call would honour (return tier + confidence) without
  network or API-key dependency. Phase-3 substance is a separate
  ``AnthropicHaikuClassifierBackend`` that issues the actual Haiku
  call; the substrate here is the **integration scaffolding** + the
  envelope + the fallback logic.
- Default routing-mode stays ``static`` (ADR-0064 Phase-2a). The
  classifier is opt-in via
  ``WAKIR_ROUTING_MODE=llm_classifier``. Other modes (``static``,
  ``heuristic``) are unaffected.
- When opt-in, the classifier records a
  :class:`LlmClassifierEvent` for every call. The envelope is byte-
  stable for identical inputs (modulo the operator-supplied
  ``ts_utc``) so the ADR-0064 §4 A/B-test diff-CLI can compare
  static / heuristic / llm-classifier verdicts side-by-side.

Routing-mode contract
---------------------

``WAKIR_ROUTING_MODE`` accepted values (extended for Phase-2c):

- ``static``    — Phase-2a default; persona-def picks the tier.
- ``heuristic`` — Phase-2b; :mod:`heuristic_router` picks the tier.
- ``llm_classifier`` — Phase-2c (this module); a Mock-Haiku-call
  picks the tier with a confidence score; below-threshold confidence
  falls back to the Heuristic-Router decision.

Unknown values fall back to ``static`` to preserve production
behaviour (see ADR-0064 §"Risiken und Annahmen" — Default-aus is the
fail-safe).

Confidence-threshold contract
-----------------------------

Default threshold: ``0.8`` (configurable via
:data:`WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_ENV`). Reasoning:

- Below 0.8 the Mock-Haiku-call's decision is treated as ``uncertain``
  and the engine falls back to the Heuristic-Router. This bounds the
  Heuristic-Drift-Risiko (ADR-0064 §"Risiken und Annahmen") because
  the substrate never serves a low-confidence classifier verdict to
  production traffic.
- At-or-above 0.8 the classifier's tier is honoured. The
  classifier-event records the confidence + the fallback flag so
  operators can tune the threshold from A/B-test telemetry without
  changing code.

The threshold is read once per :class:`LlmClassifierRouter` call so
hermetic tests can override via the ``env`` parameter.

Mock-Haiku-Backend contract
---------------------------

The :class:`MockHaikuClassifierBackend` is *deterministic* — given
identical ``prompt_payload`` + ``persona_def`` it returns the same
tier + confidence. The mock derives the tier from the same shape of
inputs the Phase-3 Haiku-prompt would inspect (prompt length, schema
markers, code blocks, persona Befugnis-band) but emits a *coarser*
verdict band than the heuristic-router's continuous scoring — this
matches the expected shape of a real Haiku-Messages-call's
discrete-label output.

Confidence is also deterministic: it scales with the *strength* of
the dominant signal (long prompt → high confidence in Opus;
mid-length code prompt → moderate confidence in Sonnet; very short
prompt → high confidence in Haiku). Borderline cases (mid-length
non-code prose without schema) yield sub-threshold confidence so the
fallback path is exercised in tests.

The mock's deterministic shape lets hermetic tests verify the
classifier-event envelope, the fallback wiring, and the integration
into :mod:`llm_call_shim` without flake.

Provider-lock-in / Cost-Optimization-IP boundary
------------------------------------------------

Per ADR-0064 §"Provider-Lock-In", classifier verdicts are tier-names
(HAIKU/SONNET/OPUS), not Anthropic model-ids — a different provider
can plug in by mapping at the backend layer. Per ADR-0064 §"Hosted-
Service-relevant", the **concrete classifier-prompt-template** and
the **Phase-3 production-tuned threshold** are Hosted-Service cost-
optimization hebels and may land in a separate Hosted-Service-only
module (substrate here is BUSL-1.1).

Hermetic-test surface
---------------------

All tests in ``wirelang/tests/persona_engine/test_llm_classifier.py``
are pure-stdlib (no network, no LLM, no NATS). This module imports
only ``dataclasses``, ``enum``, ``json``, ``os``, ``time``,
``typing`` + the existing :mod:`heuristic_router` substrate.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Optional, Protocol

from .heuristic_router import (
    HEURISTIC_ROUTER_VERSION,
    HeuristicInputs,
    RouterDecision,
    _decide_from_inputs,
    measure_heuristic_inputs,
)

LLM_CLASSIFIER_VERSION = "v1"

# ---------------------------------------------------------------------------
# ENV contract — extends WAKIR_ROUTING_MODE with the third value.
# ---------------------------------------------------------------------------

WAKIR_ROUTING_MODE_ENV = "WAKIR_ROUTING_MODE"
WAKIR_ROUTING_MODE_LLM_CLASSIFIER = "llm_classifier"

WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_ENV = (
    "WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD"
)
WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_DEFAULT = 0.8


def is_llm_classifier_mode(env: Optional[dict] = None) -> bool:
    """``True`` iff ``WAKIR_ROUTING_MODE=llm_classifier``.

    The function is permissive about whitespace + case (``  LLM_CLASSIFIER  ``
    is accepted) so operators can set the env-var in the Quadlet env-file
    or systemd unit without surprises. Any other value (including
    ``static`` / ``heuristic`` / unknown) returns ``False``.
    """
    src = env if env is not None else os.environ
    raw = (src.get(WAKIR_ROUTING_MODE_ENV) or "").strip().lower()
    return raw == WAKIR_ROUTING_MODE_LLM_CLASSIFIER


def read_confidence_threshold(env: Optional[dict] = None) -> float:
    """Return the operator-configured confidence threshold.

    Default :data:`WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_DEFAULT` if the
    env-var is unset or unparseable. Clamps to ``[0.0, 1.0]`` — out-of-
    range values are coerced to the nearest bound so misconfiguration
    never elevates the substrate above its declared safety envelope.
    """
    src = env if env is not None else os.environ
    raw = (src.get(WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_ENV) or "").strip()
    if not raw:
        return WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_DEFAULT
    try:
        value = float(raw)
    except ValueError:
        return WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_DEFAULT
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


# ---------------------------------------------------------------------------
# Backend protocol + deterministic Mock-Haiku-Backend
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassifierVerdict:
    """Output of one classifier backend call.

    Fields:

    - ``tier``: the :class:`RouterDecision` the backend would prefer.
    - ``confidence``: ``[0.0, 1.0]`` confidence in ``tier``.
    - ``rationale``: short human-readable label (mock-derived; in
      Phase-3 a Haiku-emitted phrase).
    - ``backend_kind``: discriminator (``mock-haiku`` /
      ``anthropic-haiku`` in Phase-3).
    """

    tier: RouterDecision
    confidence: float
    rationale: str
    backend_kind: str


class ClassifierBackend(Protocol):
    """The single interface the :class:`LlmClassifierRouter` binds against.

    Phase-2c-Stub implementation: :class:`MockHaikuClassifierBackend`.
    Phase-3 implementation: an ``AnthropicHaikuClassifierBackend`` that
    issues an actual ``messages.create`` call against the Haiku model
    and parses the structured-output verdict. Out of scope for this
    sprint.
    """

    def classify(
        self,
        *,
        prompt_payload: str,
        persona_def: Optional[dict] = None,
    ) -> ClassifierVerdict:
        ...


@dataclass
class MockHaikuClassifierBackend:
    """Deterministic Mock-Haiku-Classifier — no network, no LLM.

    The mock derives ``(tier, confidence)`` from the same input shape a
    real Haiku-Messages-call would consume (prompt length, schema
    markers, code blocks, persona Befugnis-band). It deliberately
    produces a *coarser* verdict band than the heuristic-router's
    continuous score so the substrate exercises the fallback path on
    borderline inputs.

    Determinism contract: identical ``prompt_payload`` + ``persona_def``
    yields identical :class:`ClassifierVerdict` (modulo NO timestamp —
    the verdict itself is stateless).
    """

    BACKEND_KIND: str = field(default="mock-haiku", init=False)

    def classify(
        self,
        *,
        prompt_payload: str,
        persona_def: Optional[dict] = None,
    ) -> ClassifierVerdict:
        inputs = measure_heuristic_inputs(prompt_payload, persona_def)
        tier, confidence, rationale = _mock_haiku_verdict(inputs)
        return ClassifierVerdict(
            tier=tier,
            confidence=confidence,
            rationale=rationale,
            backend_kind=self.BACKEND_KIND,
        )


def _mock_haiku_verdict(
    inputs: HeuristicInputs,
) -> tuple[RouterDecision, float, str]:
    """Translate the heuristic-input-measurements into a coarse verdict.

    Verdict bands (chosen to differ from the heuristic-router's bands so
    the A/B-test surface is meaningful, and to expose a borderline band
    that yields sub-threshold confidence and exercises the fallback):

    - **Audit-Persona**           → ``OPUS`` @ 0.95 (mock mirrors the
      Befugnis-Floor that the heuristic-router applies as an override).
    - **Routine-Comms-Persona**   → ``HAIKU`` @ 0.95 (mirror of the
      Haiku-Ceiling override).
    - **Very-long prompt** (token_len >= TOKEN_LEN_OPUS_THRESHOLD)
      → ``OPUS`` @ 0.92.
    - **High schema-complexity** (schema_complexity_raw >= 7)
      → ``OPUS`` @ 0.88.
    - **Very-short prompt** (token_len < TOKEN_LEN_HAIKU_THRESHOLD)
      AND no code blocks → ``HAIKU`` @ 0.90.
    - **Code-heavy mid-length** (code_block_count >= 3 and
      token_len < TOKEN_LEN_OPUS_THRESHOLD) → ``SONNET`` @ 0.85.
    - **Mid-length prose-only** (TOKEN_LEN_HAIKU_THRESHOLD <= token_len
      < TOKEN_LEN_SONNET_THRESHOLD, no code, low schema) → ``SONNET``
      @ 0.55 (sub-threshold; engine falls back to heuristic).
    - **Catch-all** → ``SONNET`` @ 0.70 (sub-threshold; fallback).

    The mock returns a short ``rationale`` label so the
    :class:`LlmClassifierEvent` envelope captures *why* the verdict
    landed where it did — useful for operator telemetry during the
    ADR-0064 §4 A/B-test.
    """
    from .heuristic_router import (
        TOKEN_LEN_HAIKU_THRESHOLD,
        TOKEN_LEN_OPUS_THRESHOLD,
        TOKEN_LEN_SONNET_THRESHOLD,
    )

    band = inputs.persona_role_band
    if band == "audit":
        return RouterDecision.OPUS, 0.95, "befugnis-audit-floor"
    if band == "routine-comms":
        return RouterDecision.HAIKU, 0.95, "befugnis-routine-ceiling"
    if inputs.token_len_estimate >= TOKEN_LEN_OPUS_THRESHOLD:
        return RouterDecision.OPUS, 0.92, "very-long-prompt"
    if inputs.schema_complexity_raw >= 7:
        return RouterDecision.OPUS, 0.88, "high-schema-complexity"
    if (
        inputs.token_len_estimate < TOKEN_LEN_HAIKU_THRESHOLD
        and inputs.code_block_count == 0
    ):
        return RouterDecision.HAIKU, 0.90, "very-short-prose"
    if (
        inputs.code_block_count >= 3
        and inputs.token_len_estimate < TOKEN_LEN_OPUS_THRESHOLD
    ):
        return RouterDecision.SONNET, 0.85, "code-heavy-mid-length"
    if (
        TOKEN_LEN_HAIKU_THRESHOLD
        <= inputs.token_len_estimate
        < TOKEN_LEN_SONNET_THRESHOLD
        and inputs.code_block_count == 0
        and inputs.schema_complexity_raw <= 2
    ):
        return RouterDecision.SONNET, 0.55, "borderline-prose-mid-length"
    return RouterDecision.SONNET, 0.70, "catch-all"


# ---------------------------------------------------------------------------
# Router with confidence-threshold + heuristic-fallback
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LlmClassifierEvent:
    """Classifier-decision envelope for structured-JSON logging.

    Captures every classifier call so the ADR-0064 §4 A/B-test
    diff-CLI can compare static / heuristic / llm-classifier
    verdicts. Byte-stable JSON when keys are sorted (see
    :meth:`to_json`).
    """

    persona_id: str
    auftrag_id: str
    ts_utc: str
    routing_mode: str  # "llm_classifier"
    backend_kind: str
    static_choice: Optional[str]
    classifier_choice: str
    classifier_confidence: float
    classifier_rationale: str
    heuristic_choice: str
    heuristic_befugnis_override: Optional[str]
    confidence_threshold: float
    used_fallback: bool
    effective_choice: str
    inputs: dict  # asdict(HeuristicInputs)
    router_version: str = field(default=HEURISTIC_ROUTER_VERSION)
    classifier_version: str = field(default=LLM_CLASSIFIER_VERSION)

    def to_json(self) -> str:
        """Byte-stable JSON serialization (keys sorted)."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def _utc_now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class LlmClassifierRouter:
    """Phase-2c LLM-Classifier-Router.

    Wraps a :class:`ClassifierBackend` (default: deterministic
    :class:`MockHaikuClassifierBackend`) with the confidence-threshold
    + heuristic-fallback contract documented in the module docstring.

    Parameters:

    - ``backend``: optional :class:`ClassifierBackend`; defaults to a
      fresh :class:`MockHaikuClassifierBackend` instance.
    - ``sink``: optional callable that receives every emitted
      :class:`LlmClassifierEvent`. Sink failures are swallowed (analog
      to :class:`heuristic_router.HeuristicRoutingShim`) so a broken
      observability target never breaks the engine path.
    - ``env``: optional env-dict for hermetic tests.

    Phase-2c is observation-only at the engine level: the engine
    integration in :mod:`llm_call_shim` reads :meth:`decide` and logs
    the event, but the live model-swap stays Phase-3 substance.
    """

    backend: Optional[ClassifierBackend] = None
    sink: Optional[object] = None  # Callable[[LlmClassifierEvent], None] | None
    env: Optional[dict] = None

    def __post_init__(self) -> None:
        if self.backend is None:
            self.backend = MockHaikuClassifierBackend()

    def decide(
        self,
        *,
        persona_id: str,
        auftrag_id: str,
        task_payload: dict,
        persona_def: Optional[dict] = None,
        static_choice: Optional[str] = None,
        ts_utc: Optional[str] = None,
    ) -> LlmClassifierEvent:
        """Run the classifier + fallback logic, emit a routing-event.

        The returned event is also dispatched to ``self.sink`` (if
        configured). The caller (engine wrapper in
        :mod:`llm_call_shim`) uses ``event.effective_choice`` as the
        Phase-2c tier-recommendation; Phase-2c stub does not yet drive
        live model-swap.
        """
        prompt = (
            task_payload.get("prompt_payload")
            or task_payload.get("prompt")
            or task_payload.get("payload")
            or ""
        )
        if not isinstance(prompt, str):
            prompt = str(prompt)
        verdict = self.backend.classify(  # type: ignore[union-attr]
            prompt_payload=prompt, persona_def=persona_def
        )
        inputs = measure_heuristic_inputs(prompt, persona_def)
        heuristic_decision, heuristic_override = _decide_from_inputs(inputs)
        threshold = read_confidence_threshold(self.env)
        used_fallback = verdict.confidence < threshold
        if used_fallback:
            effective = heuristic_decision.value
        else:
            effective = verdict.tier.value
        event = LlmClassifierEvent(
            persona_id=persona_id,
            auftrag_id=auftrag_id,
            ts_utc=ts_utc or _utc_now_rfc3339(),
            routing_mode=WAKIR_ROUTING_MODE_LLM_CLASSIFIER,
            backend_kind=verdict.backend_kind,
            static_choice=static_choice,
            classifier_choice=verdict.tier.value,
            classifier_confidence=verdict.confidence,
            classifier_rationale=verdict.rationale,
            heuristic_choice=heuristic_decision.value,
            heuristic_befugnis_override=heuristic_override,
            confidence_threshold=threshold,
            used_fallback=used_fallback,
            effective_choice=effective,
            inputs=asdict(inputs),
        )
        sink = self.sink
        if sink is not None:
            try:
                sink(event)  # type: ignore[misc]
            except Exception:
                # Observation-only — sink failures never break the
                # engine path. Tests exercise the broken-sink branch
                # explicitly.
                pass
        return event


def maybe_attach_classifier_router(
    *,
    backend: Optional[ClassifierBackend] = None,
    sink: Optional[object] = None,
    env: Optional[dict] = None,
) -> Optional[LlmClassifierRouter]:
    """Factory: return a :class:`LlmClassifierRouter` iff routing-mode
    is opt-in-enabled via ``WAKIR_ROUTING_MODE=llm_classifier``.

    Engine wiring code-pattern (mirrors
    :func:`llm_call_shim.maybe_attach_routing_shim`):

    ::

        router = maybe_attach_classifier_router(sink=my_classifier_sink)
        result, event = call_with_classifier_event(
            hook, ..., classifier_router=router,
        )

    Default-aus: when the env-var is unset (or any value other than
    ``llm_classifier``), this factory returns ``None`` and the call-
    site sees no classifier-event. Production behaviour stays
    byte-identical to pre-Phase-2c. Operators opt in by setting the
    env-var in the Quadlet env-file or systemd unit, never in code.
    """
    if not is_llm_classifier_mode(env):
        return None
    return LlmClassifierRouter(backend=backend, sink=sink, env=env)


__all__ = [
    "ClassifierBackend",
    "ClassifierVerdict",
    "LLM_CLASSIFIER_VERSION",
    "LlmClassifierEvent",
    "LlmClassifierRouter",
    "MockHaikuClassifierBackend",
    "WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_DEFAULT",
    "WAKIR_CLASSIFIER_CONFIDENCE_THRESHOLD_ENV",
    "WAKIR_ROUTING_MODE_ENV",
    "WAKIR_ROUTING_MODE_LLM_CLASSIFIER",
    "is_llm_classifier_mode",
    "maybe_attach_classifier_router",
    "read_confidence_threshold",
]
