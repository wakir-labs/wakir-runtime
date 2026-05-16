# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Heuristic Model-Router — ADR-0064 §A.3 (Phase-2b-Stub).

Overview
--------

ADR-0064 (Model-Routing + Prompt-Caching, approved 2026-05-16) lists
five candidate routing patterns. The Phase-2a Quick-Win is B.2
(Static-Prefix-Caching, see :mod:`anthropic_cache`). The Phase-2b
**Heuristic-Routing-Prototype** is this module: it inspects the
incoming task payload and the persona-def and returns a
:class:`RouterDecision` selecting one of Haiku / Sonnet / Opus.

Phase-2b is intentionally an opt-in, **observation-only** stub:

- Default routing mode is ``static`` (ADR-0064 Phase-2a, persona-def
  selects the model). The heuristic-router does **not** override
  static routing unless the operator explicitly sets
  ``WAKIR_ROUTING_MODE=heuristic``.
- When enabled, the router's decision is logged via the routing-event
  envelope (:func:`build_routing_event`) so the A/B-test described in
  ADR-0064 Phase-2b §4 can compare heuristic-suggested vs.
  static-configured models without changing production behaviour.
- Live model-swap on the back of the heuristic is **Phase-3
  substance** — Sprint-Heuristic-Routing-Stub-MINI ships the
  decision logic + telemetry envelope, **not** the live swap.

The router is intentionally provider-agnostic in its decision type
(``HAIKU`` / ``SONNET`` / ``OPUS`` are tier-names, not Anthropic
model-ids). The mapping from tier to concrete model-id lives in the
persona-def / hook layer; the router's contract is only to pick a
tier given task-content heuristics and persona-Befugnis-Rahmen.

Heuristic inputs
----------------

1. **Token-length estimate** (input).
   Cheap stdlib approximation: ``len(prompt) / 4`` bytes-per-token
   heuristic (Anthropic-tokenizer rule-of-thumb). Long prompts
   (>16k chars ~= >4k tokens) tilt toward Sonnet; very long
   (>64k chars ~= >16k tokens) tilt toward Opus for context-fidelity.

2. **Schema-complexity score**.
   Counts JSON-Schema-like markers (``properties``, ``required``,
   ``additionalProperties``, ``$ref``) plus nesting depth. High
   schema-complexity is a strong Opus-signal (audit-trail-grade
   structured-output where Haiku-drift bites hardest).

3. **Code-vs-prose detection**.
   Counts triple-backtick code-blocks and inline-code spans.
   Code-heavy tasks tilt toward Sonnet (mid-tier code-reasoning is
   Sonnet's sweet-spot per Anthropic-pricing-page-2026-05-16). Pure
   prose with low schema-complexity tilts toward Haiku.

4. **Persona-Befugnis-Rahmen**.
   Audit-personas (Henrik Voss / Internal-Audit, Aisha Rahman / HR,
   Mira-CEO-spawns) get an Opus-floor — the cost-spread is justified
   by the consequence of mis-classification. Routine-comms-personas
   (julia-comms, brand-ops) get a Haiku-ceiling. Engineering-personas
   (tomas, kai, reza, lena, noa, selin, amara) use the heuristic
   verbatim with no floor/ceiling override.

Decision-Combiner
-----------------

The four heuristic inputs feed a deterministic, transparent
combiner — no ML, no learned weights. Each input contributes a
score in ``{-2, -1, 0, +1, +2}`` (negative = Haiku-pull, positive
= Opus-pull, zero = Sonnet-default), summed; the band-mapping is:

- sum <= -2 → ``HAIKU``
- -1 <= sum <= +1 → ``SONNET``
- sum >= +2 → ``OPUS``

Persona-Befugnis-overrides apply *after* the score band-mapping:

- audit-persona override pulls the decision up to ``OPUS`` floor.
- routine-comms override pulls the decision down to ``HAIKU`` ceiling.

The override is recorded in the routing-event envelope so the
A/B-test telemetry can separate "heuristic chose X" from
"persona-override forced X".

A/B-test envelope
-----------------

For every call, the router emits a routing-event dict (see
:func:`build_routing_event`) suitable for structured-JSON logging
or NATS-publish. The envelope contains:

- ``persona_id``, ``auftrag_id``, ``ts_utc``.
- ``routing_mode``: ``static`` or ``heuristic``.
- ``static_choice``: the persona-def's configured tier (for
  comparison even when mode is ``heuristic``).
- ``heuristic_choice``: the router's tier-decision.
- ``effective_choice``: the tier actually used (in stub-mode this
  equals ``static_choice`` to preserve production behaviour; in
  Phase-3 it equals ``heuristic_choice`` when mode is
  ``heuristic``).
- ``inputs``: the four heuristic input scores + the raw measurements
  (``token_len_estimate``, ``schema_complexity_score``,
  ``code_block_count``, ``persona_role_band``).
- ``befugnis_override``: ``null`` or one of
  ``audit-opus-floor`` / ``routine-haiku-ceiling``.

The envelope is byte-stable for identical inputs (modulo the
operator-supplied ``ts_utc``) so the A/B-test diff-CLI can compare
runs without flakiness.

Hermetic-test surface
---------------------

All tests in ``wirelang/tests/persona_engine/test_heuristic_router.py``
are pure-stdlib (no network, no LLM, no NATS). The module imports
only ``dataclasses``, ``enum``, ``hashlib``, ``json``, ``os``, ``re``,
``time``, ``typing`` from the stdlib.

Provider-lock-in boundary
-------------------------

The router emits tier-names (HAIKU/SONNET/OPUS), not Anthropic
model-ids. A different provider (OpenAI gpt-4o / gpt-4o-mini /
o3-mini) can plug into the same tier-band by mapping at the hook
layer. The heuristic itself is provider-agnostic.

Cost-Optimization-IP boundary
-----------------------------

Per ADR-0064 §"Provider-Lock-In" and §"Hosted-Service-relevant", the
**concrete heuristic logic** (thresholds, scoring weights, persona
overrides) is a Hosted-Service-Cost-Optimization-Hebel. The
substrate is BUSL-1.1; the Phase-3 production-tuned thresholds may
land in a separate Hosted-Service-only module.
"""

from __future__ import annotations

import enum
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

HEURISTIC_ROUTER_VERSION = "v1"

# ---------------------------------------------------------------------------
# ENV variable contract
# ---------------------------------------------------------------------------

WAKIR_ROUTING_MODE_ENV = "WAKIR_ROUTING_MODE"
WAKIR_ROUTING_MODE_STATIC = "static"
WAKIR_ROUTING_MODE_HEURISTIC = "heuristic"
WAKIR_ROUTING_MODE_DEFAULT = WAKIR_ROUTING_MODE_STATIC


def read_routing_mode(env: Optional[dict] = None) -> str:
    """Return ``static`` or ``heuristic``.

    Unknown values fall back to ``static`` to preserve production
    behaviour (ADR-0064 Phase-2a unverändert ohne explizite Opt-in-
    Aktivierung).
    """
    src = env if env is not None else os.environ
    raw = (src.get(WAKIR_ROUTING_MODE_ENV) or "").strip().lower()
    if raw == WAKIR_ROUTING_MODE_HEURISTIC:
        return WAKIR_ROUTING_MODE_HEURISTIC
    return WAKIR_ROUTING_MODE_STATIC


# ---------------------------------------------------------------------------
# Decision enum
# ---------------------------------------------------------------------------


class RouterDecision(enum.Enum):
    """Model-tier decision.

    Tier-names, not Anthropic model-ids — see module docstring,
    Provider-lock-in-boundary section.
    """

    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"

    @classmethod
    def from_str(cls, raw: Optional[str]) -> Optional["RouterDecision"]:
        if raw is None:
            return None
        normalized = raw.strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        return None


# ---------------------------------------------------------------------------
# Heuristic input measurements
# ---------------------------------------------------------------------------


# Approximate Anthropic-tokenizer rule-of-thumb: ~4 chars per token
# for English+code prompts. Used as a stdlib-only estimate; the hook
# layer can pass an exact tokenizer count if available.
CHARS_PER_TOKEN_ESTIMATE = 4

# Token-length thresholds — tunable via Hosted-Service module.
TOKEN_LEN_HAIKU_THRESHOLD = 500  # below: lean Haiku
TOKEN_LEN_SONNET_THRESHOLD = 4_000  # below: neutral / Sonnet
TOKEN_LEN_OPUS_THRESHOLD = 16_000  # above: lean Opus

# Schema-complexity markers.
_SCHEMA_MARKER_RE = re.compile(
    r"\b(properties|required|additionalProperties|\$ref|oneOf|anyOf|allOf)\b"
)

# Code-block detection.
_CODE_FENCE_RE = re.compile(r"```", re.MULTILINE)

# Persona-Befugnis-bands.
AUDIT_PERSONA_IDS = frozenset(
    {
        "henrik",  # Internal Audit
        "henrik-voss",
        "internal-audit",
        "aisha",  # HR / Org-Designer (audit-grade decisions)
        "aisha-rahman",
        "hr",
        "mira",  # CEO-spawns
        "mira-kessler",
        "ceo",
    }
)

ROUTINE_COMMS_PERSONA_IDS = frozenset(
    {
        "julia",  # Comms
        "julia-comms",
        "comms",
        "brand-ops",
        "brand",
    }
)


@dataclass(frozen=True)
class HeuristicInputs:
    """The four heuristic input measurements + scores.

    Each ``*_score`` value is in ``{-2, -1, 0, +1, +2}``. The combiner
    sums the four scores to produce a band-mapped decision.
    """

    token_len_estimate: int
    token_len_score: int

    schema_complexity_score: int
    schema_complexity_raw: int

    code_block_count: int
    code_vs_prose_score: int

    persona_role_band: str  # "audit" | "routine-comms" | "engineering" | "unknown"
    persona_role_score: int


def _estimate_token_len(prompt: str) -> int:
    if not prompt:
        return 0
    return max(1, len(prompt) // CHARS_PER_TOKEN_ESTIMATE)


def _score_token_len(token_len: int) -> int:
    # Token-length is the dominant heuristic input — very long prompts
    # must overpower the pure-prose (-1) + no-schema (-1) penalty
    # without help from other inputs. We therefore widen the extreme
    # band to ``+4`` so the band-mapping (sum >= +2 → Opus) is robust
    # against worst-case neutral inputs elsewhere.
    if token_len < TOKEN_LEN_HAIKU_THRESHOLD:
        return -2
    if token_len < TOKEN_LEN_SONNET_THRESHOLD:
        return -1
    if token_len < TOKEN_LEN_OPUS_THRESHOLD:
        return +1
    return +4


def _schema_complexity_raw(prompt: str) -> int:
    if not prompt:
        return 0
    return len(_SCHEMA_MARKER_RE.findall(prompt))


def _score_schema_complexity(raw: int) -> int:
    if raw == 0:
        return -1
    if raw <= 2:
        return 0
    if raw <= 6:
        return +1
    return +2


def _count_code_blocks(prompt: str) -> int:
    if not prompt:
        return 0
    fences = len(_CODE_FENCE_RE.findall(prompt))
    # Pairs of fences make blocks; lone trailing fence counts as 0.
    return fences // 2


def _score_code_vs_prose(code_blocks: int, prompt_len: int) -> int:
    if prompt_len == 0:
        return 0
    # Heavy code (>=3 fenced blocks): mid-tier Sonnet lean (+1).
    # Some code (1-2 blocks): neutral (0).
    # No code at all (pure prose): -1 Haiku-lean.
    if code_blocks >= 3:
        return +1
    if code_blocks >= 1:
        return 0
    return -1


def _persona_role_band(persona_def: Optional[dict]) -> str:
    if not persona_def:
        return "unknown"
    pid = (persona_def.get("persona_id") or persona_def.get("id") or "").strip().lower()
    role = (persona_def.get("role") or "").strip().lower()
    candidates = {pid, role}
    candidates.discard("")
    if candidates & AUDIT_PERSONA_IDS:
        return "audit"
    if candidates & ROUTINE_COMMS_PERSONA_IDS:
        return "routine-comms"
    # Engineering personas explicitly listed in module docstring; any
    # known engineering tag maps to engineering, otherwise unknown.
    engineering_ids = frozenset(
        {
            "tomas",
            "tomas-reinhart",
            "dev-engineering",
            "kai",
            "reza",
            "lena",
            "frontend",
            "noa",
            "sre",
            "selin",
            "pengine",
            "amara",
            "qa",
            "priya",
            "priya-nakamura",
            "cto",
        }
    )
    if candidates & engineering_ids:
        return "engineering"
    return "unknown"


def _score_persona_role(band: str) -> int:
    # Audit / Routine-Comms are *overrides*, not score-contributions —
    # they apply after band-mapping (see _apply_befugnis_override).
    # Persona-role-score itself contributes only weakly to the sum.
    if band == "audit":
        return +1
    if band == "routine-comms":
        return -1
    return 0  # engineering / unknown contribute zero


def measure_heuristic_inputs(
    prompt: str, persona_def: Optional[dict] = None
) -> HeuristicInputs:
    """Compute the four heuristic-input measurements + scores."""
    token_len = _estimate_token_len(prompt)
    schema_raw = _schema_complexity_raw(prompt)
    code_blocks = _count_code_blocks(prompt)
    role_band = _persona_role_band(persona_def)
    return HeuristicInputs(
        token_len_estimate=token_len,
        token_len_score=_score_token_len(token_len),
        schema_complexity_raw=schema_raw,
        schema_complexity_score=_score_schema_complexity(schema_raw),
        code_block_count=code_blocks,
        code_vs_prose_score=_score_code_vs_prose(code_blocks, len(prompt or "")),
        persona_role_band=role_band,
        persona_role_score=_score_persona_role(role_band),
    )


# ---------------------------------------------------------------------------
# Decision combiner
# ---------------------------------------------------------------------------


def _band_map(total: int) -> RouterDecision:
    if total <= -2:
        return RouterDecision.HAIKU
    if total >= +2:
        return RouterDecision.OPUS
    return RouterDecision.SONNET


def _apply_befugnis_override(
    base: RouterDecision, role_band: str
) -> tuple[RouterDecision, Optional[str]]:
    if role_band == "audit":
        # Opus floor: never serve audit-personas a sub-Opus tier.
        if base != RouterDecision.OPUS:
            return RouterDecision.OPUS, "audit-opus-floor"
        return base, None
    if role_band == "routine-comms":
        # Haiku ceiling: never serve routine-comms a super-Haiku tier.
        if base != RouterDecision.HAIKU:
            return RouterDecision.HAIKU, "routine-comms-haiku-ceiling"
        return base, None
    return base, None


def _decide_from_inputs(
    inputs: HeuristicInputs,
) -> tuple[RouterDecision, Optional[str]]:
    total = (
        inputs.token_len_score
        + inputs.schema_complexity_score
        + inputs.code_vs_prose_score
        + inputs.persona_role_score
    )
    base = _band_map(total)
    return _apply_befugnis_override(base, inputs.persona_role_band)


# ---------------------------------------------------------------------------
# Public API: route_task
# ---------------------------------------------------------------------------


def route_task(
    task_payload: dict, persona_def: Optional[dict] = None
) -> RouterDecision:
    """Return a :class:`RouterDecision` for ``task_payload``.

    The ``task_payload`` is expected to be a dict-shaped envelope
    similar to the Bridge-Forward-Pipe payload — the router reads the
    ``prompt_payload`` field (string). If absent, the function looks
    at ``prompt`` or ``payload`` as fallbacks. An empty / missing
    prompt yields ``HAIKU`` (lowest-cost fallback, deterministic).

    ``persona_def`` is the persona-frontmatter-derived dict; the
    router reads ``persona_id`` / ``id`` and ``role`` to determine
    the Befugnis-band.
    """
    if not isinstance(task_payload, dict):
        task_payload = {}
    prompt = (
        task_payload.get("prompt_payload")
        or task_payload.get("prompt")
        or task_payload.get("payload")
        or ""
    )
    if not isinstance(prompt, str):
        prompt = str(prompt)
    inputs = measure_heuristic_inputs(prompt, persona_def)
    decision, _override = _decide_from_inputs(inputs)
    return decision


# ---------------------------------------------------------------------------
# A/B-test envelope
# ---------------------------------------------------------------------------


def _utc_now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass(frozen=True)
class RoutingEvent:
    """Routing-decision envelope for structured-JSON logging.

    See module docstring §"A/B-test envelope" for the contract.
    """

    persona_id: str
    auftrag_id: str
    ts_utc: str
    routing_mode: str  # "static" | "heuristic"
    static_choice: Optional[str]
    heuristic_choice: str
    effective_choice: str
    befugnis_override: Optional[str]
    inputs: dict  # asdict(HeuristicInputs)
    router_version: str = field(default=HEURISTIC_ROUTER_VERSION)

    def to_json(self) -> str:
        """Byte-stable JSON serialization (keys sorted)."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def build_routing_event(
    *,
    persona_id: str,
    auftrag_id: str,
    task_payload: dict,
    persona_def: Optional[dict] = None,
    static_choice: Optional[str] = None,
    routing_mode: Optional[str] = None,
    ts_utc: Optional[str] = None,
    env: Optional[dict] = None,
) -> RoutingEvent:
    """Build a :class:`RoutingEvent` for the A/B-test telemetry.

    Parameters:

    - ``static_choice``: the persona-def's configured tier name
      (e.g. ``"sonnet"``). May be ``None`` if the persona-def does
      not specify a tier (in which case ``effective_choice`` falls
      back to ``heuristic_choice`` regardless of mode).
    - ``routing_mode``: ``"static"`` / ``"heuristic"``. If ``None``,
      reads from :data:`WAKIR_ROUTING_MODE_ENV`.
    - ``ts_utc``: operator-supplied timestamp for deterministic
      tests; ``None`` uses :func:`time.gmtime`.
    - ``env``: optional environment-dict for hermetic tests.

    Semantics of ``effective_choice``:

    - ``routing_mode == "static"`` AND ``static_choice`` given →
      ``effective_choice = static_choice``.
    - ``routing_mode == "static"`` AND ``static_choice`` is ``None``
      → ``effective_choice = heuristic_choice`` (fallback to keep
      the engine running; the absence of a static-choice is logged
      via the ``static_choice: null`` field).
    - ``routing_mode == "heuristic"`` → ``effective_choice
      = heuristic_choice``.

    Phase-2b note: in the production engine wiring (see
    :mod:`llm_call_shim` integration in
    :class:`HeuristicRoutingShim`), ``effective_choice`` is only
    *logged*, not consumed for live model-swap. The live swap is
    Phase-3 substance.
    """
    mode = (routing_mode or read_routing_mode(env)).strip().lower()
    if mode != WAKIR_ROUTING_MODE_HEURISTIC:
        mode = WAKIR_ROUTING_MODE_STATIC
    inputs = measure_heuristic_inputs(
        task_payload.get("prompt_payload")
        or task_payload.get("prompt")
        or task_payload.get("payload")
        or "",
        persona_def,
    )
    heuristic_decision, override = _decide_from_inputs(inputs)
    heuristic_choice = heuristic_decision.value
    if mode == WAKIR_ROUTING_MODE_HEURISTIC:
        effective_choice = heuristic_choice
    else:
        effective_choice = static_choice if static_choice else heuristic_choice
    ts = ts_utc or _utc_now_rfc3339()
    return RoutingEvent(
        persona_id=persona_id,
        auftrag_id=auftrag_id,
        ts_utc=ts,
        routing_mode=mode,
        static_choice=static_choice,
        heuristic_choice=heuristic_choice,
        effective_choice=effective_choice,
        befugnis_override=override,
        inputs=asdict(inputs),
    )


# ---------------------------------------------------------------------------
# Shim for llm_call_shim integration (optional pre-LLM-hook hook)
# ---------------------------------------------------------------------------


@dataclass
class HeuristicRoutingShim:
    """Optional pre-LLM-hook shim that records a routing-event.

    The shim is **observation-only** in Phase-2b: it builds the
    :class:`RoutingEvent` and hands it off to an operator-supplied
    sink callback (e.g. structured-JSON logger or NATS-publish), then
    returns control to the caller without altering the LLM-hook
    behaviour. Phase-3 swaps this shim with a routing-aware variant
    that selects the live model on the back of the heuristic.

    Wiring pattern in :mod:`llm_call_shim`:

    Engine code-path (engine_async / nats_subscribe_loop) MAY call
    :meth:`record` immediately before :meth:`LlmCallHook.call`. The
    shim is constructed with the persona-def's configured tier
    (``static_choice``) and an optional sink. If the sink is ``None``
    the routing-event is silently discarded — the shim becomes a
    no-op without breaking the engine.

    Hermetic-test contract: tests pass a list-append sink and assert
    on the captured events. No log-capture, no NATS-mock.
    """

    static_choice: Optional[str] = None
    sink: Optional[object] = None  # Callable[[RoutingEvent], None] | None
    env: Optional[dict] = None

    def record(
        self,
        *,
        persona_id: str,
        auftrag_id: str,
        task_payload: dict,
        persona_def: Optional[dict] = None,
        ts_utc: Optional[str] = None,
    ) -> RoutingEvent:
        event = build_routing_event(
            persona_id=persona_id,
            auftrag_id=auftrag_id,
            task_payload=task_payload,
            persona_def=persona_def,
            static_choice=self.static_choice,
            ts_utc=ts_utc,
            env=self.env,
        )
        sink = self.sink
        if sink is not None:
            try:
                sink(event)  # type: ignore[misc]
            except Exception:
                # Observation-only shim must never break the engine
                # path. A broken sink is silently swallowed; tests
                # exercise the sink-failure path explicitly.
                pass
        return event

    def is_heuristic_active(self) -> bool:
        """``True`` iff the env selects heuristic-mode.

        Phase-2b: this flag is informational only — the shim records
        in both modes so the A/B-test has paired observations.
        """
        return read_routing_mode(self.env) == WAKIR_ROUTING_MODE_HEURISTIC


__all__ = [
    "AUDIT_PERSONA_IDS",
    "CHARS_PER_TOKEN_ESTIMATE",
    "HEURISTIC_ROUTER_VERSION",
    "HeuristicInputs",
    "HeuristicRoutingShim",
    "ROUTINE_COMMS_PERSONA_IDS",
    "RouterDecision",
    "RoutingEvent",
    "TOKEN_LEN_HAIKU_THRESHOLD",
    "TOKEN_LEN_OPUS_THRESHOLD",
    "TOKEN_LEN_SONNET_THRESHOLD",
    "WAKIR_ROUTING_MODE_DEFAULT",
    "WAKIR_ROUTING_MODE_ENV",
    "WAKIR_ROUTING_MODE_HEURISTIC",
    "WAKIR_ROUTING_MODE_STATIC",
    "build_routing_event",
    "measure_heuristic_inputs",
    "read_routing_mode",
    "route_task",
]
