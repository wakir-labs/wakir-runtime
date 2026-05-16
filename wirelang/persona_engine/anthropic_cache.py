# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Anthropic Messages API prompt-caching helpers (ADR-0064 Phase-2a).

Overview
--------

ADR-0064 (Model-Routing + Prompt-Caching, approved 2026-05-16) selects
Pattern B.2 ("Statisches Prompt-Caching mit Cache-Breakpoint") as the
Phase-2a Quick-Win. This module is the **pure-Python implementation
substrate** for that decision:

- Build the Anthropic Messages API request payload with one
  ``cache_control: {"type": "ephemeral"}`` breakpoint placed
  **after** the static prefix (system prompt + persona-def + tool
  definitions) and **before** the per-task user payload.
- Derive a cache-affinity key that bakes the V-907 persona-hash pin
  into the cache identity so that a Pin-change causes an automatic
  cache-miss (ADR-0064 §"Risiken und Annahmen", V-907-Pin-Verify +
  Cache-Konflikt mitigation).
- Read the cache-TTL from the ``WAKIR_ANTHROPIC_CACHE_TTL_SECONDS``
  environment variable (Default ``300`` = Anthropic-Default 5 min).
  ``0`` disables caching entirely (no ``cache_control`` block emitted,
  V-907 pin still present in the affinity key for telemetry-only).
- Parse the Anthropic ``usage`` response object into a structured
  :class:`CacheTelemetry` envelope that downstream loggers / Prometheus
  textfile-gauge writers (Noa's Watchdog-Pattern) can consume without
  re-tokenising the raw HTTP body.
- Provide ``supports_caching()`` as part of the LLM-hook capability
  interface so the provider-lock-in boundary (ADR-0064 §"Provider-Lock-
  In") is explicit: an OpenAI-hook can return ``False`` and the engine
  treats the request as cache-disabled without code-paths leaking.

Scope boundaries
----------------

This module is **provider-aware** (Anthropic-specific request payload
shape) but **transport-agnostic** — it does **not** import ``anthropic``
or ``httpx`` and does **not** make any network call. Phase-2a ships the
payload-builder and telemetry-parser; the live HTTP-POST integration is
a Phase-3 follow-up that consumes the artefacts produced here.

The hermetic test surface (``test_anthropic_cache.py``) drives every
public function with stdlib-only inputs and asserts byte-stable
behaviour. No live API call. No mock-anthropic-server. The Mock-
Anthropic-Response objects in the test suite are plain dicts that
mirror the response shape documented at
``https://docs.claude.com/en/docs/build-with-claude/prompt-caching``
(URL-200-stamped 2026-05-16, see Outbox-Brief).

V-907 cache-affinity contract
-----------------------------

The cache key Anthropic uses internally is opaque — it is derived from
the prefix tokens preceding the breakpoint. Two different system+persona
prefixes therefore land in different cache slots automatically. The
:func:`derive_cache_affinity_key` function returns a *Wakir-side*
affinity string that the engine can log alongside ``cache_creation`` /
``cache_read`` metrics so that operators can cross-reference Anthropic-
side cache hits with Wakir-side persona-pin changes. The affinity key is
deliberately **not** sent to Anthropic — it is a telemetry-only
substance.

ENV variable contract
---------------------

::

    WAKIR_ANTHROPIC_CACHE_TTL_SECONDS  (default "300")

        Cache-TTL in seconds. Anthropic supports two discrete TTLs:
        300 (5 minutes) and 3600 (1 hour). Any value 1..1800 maps to
        the 5-minute slot; 1801..3600 maps to the 1-hour slot;
        anything above 3600 is clamped to 3600 with a structured-JSON
        warning log entry. ``0`` disables caching entirely.

        Rationale: Anthropic's API exposes only two TTL strings
        (``"5m"`` and ``"1h"``), not a free-form integer. The
        Wakir-side env var keeps the integer ergonomics (parity with
        ``WAKIR_*_SECONDS`` convention across the codebase) while
        normalising to the two supported slots at the boundary.

Cache-breakpoint placement
--------------------------

::

    request = {
        "system": [
            {"type": "text", "text": "<system+persona+tools digest>",
             "cache_control": {"type": "ephemeral", "ttl": "5m"}},
        ],
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "<per-task payload>"},
            ]},
        ],
    }

The cache breakpoint lives on the **last block of the static prefix**
(the ``system`` array's final text block). The per-task ``messages``
content carries no ``cache_control`` — it is intentionally cache-miss
on every call. This is exactly the B.2 pattern from ADR-0064.

ADR-0064 §"Folgeartefakte" Phase-2a item 1 is satisfied by this module
plus the hook-interface extension in ``llm_call_shim.py``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

ENV_CACHE_TTL_SECONDS = "WAKIR_ANTHROPIC_CACHE_TTL_SECONDS"
DEFAULT_CACHE_TTL_SECONDS = 300
TTL_SLOT_5M_MAX_SECONDS = 1800  # inclusive upper bound for the 5m slot
TTL_SLOT_1H_MAX_SECONDS = 3600  # inclusive upper bound for the 1h slot
TTL_STRING_5M = "5m"
TTL_STRING_1H = "1h"

# Anthropic-documented hard limit (URL-200-stamped 2026-05-16). The
# B.2 pattern uses exactly one breakpoint (system-array tail); the
# constant is exposed so future Phase-2b/2c logic that adds further
# breakpoints can guard against the API contract.
ANTHROPIC_MAX_CACHE_BREAKPOINTS = 4


# ---------------------------------------------------------------------------
# Cache-TTL ENV parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CacheTtlResolution:
    """Outcome of resolving ``WAKIR_ANTHROPIC_CACHE_TTL_SECONDS``.

    - :attr:`enabled`: ``False`` iff the env var resolves to ``0``.
    - :attr:`seconds`: the integer value after clamping.
    - :attr:`api_ttl_string`: the Anthropic-API ttl marker
      (``"5m"`` or ``"1h"``), or ``None`` when caching is disabled.
    - :attr:`source`: ``"env"`` when read from the env var,
      ``"default"`` when the env var was absent.
    - :attr:`raw_value`: the unparsed env-var string (for log audits),
      or ``None`` when ``source == "default"``.
    """

    enabled: bool
    seconds: int
    api_ttl_string: Optional[str]
    source: str
    raw_value: Optional[str]


def resolve_cache_ttl_from_env(
    env: Optional[Mapping[str, str]] = None,
) -> CacheTtlResolution:
    """Resolve the cache-TTL env variable to an API-ready TTL string.

    Behaviour:

    - Absent env var -> ``CacheTtlResolution(enabled=True,
      seconds=300, api_ttl_string="5m", source="default")``.
    - ``"0"`` -> ``CacheTtlResolution(enabled=False, seconds=0,
      api_ttl_string=None, source="env")``.
    - ``"1".."1800"`` -> 5-minute slot.
    - ``"1801".."3600"`` -> 1-hour slot.
    - ``> 3600`` -> clamped to 3600 (1-hour slot).
    - Non-integer or negative -> :class:`ValueError`.

    The function never raises on a missing env var; it raises only on
    a *present-but-malformed* env var (so misconfigured deployments
    fail loudly at engine boot rather than silently caching wrong).
    """
    if env is None:
        env = os.environ
    raw = env.get(ENV_CACHE_TTL_SECONDS)
    if raw is None:
        return CacheTtlResolution(
            enabled=True,
            seconds=DEFAULT_CACHE_TTL_SECONDS,
            api_ttl_string=TTL_STRING_5M,
            source="default",
            raw_value=None,
        )
    try:
        parsed = int(raw, 10)
    except ValueError as exc:
        raise ValueError(
            f"{ENV_CACHE_TTL_SECONDS}={raw!r} is not a base-10 integer "
            f"(must be 0, 1..1800 for 5m, or 1801..3600 for 1h)"
        ) from exc
    if parsed < 0:
        raise ValueError(
            f"{ENV_CACHE_TTL_SECONDS}={raw!r} must be non-negative"
        )
    if parsed == 0:
        return CacheTtlResolution(
            enabled=False,
            seconds=0,
            api_ttl_string=None,
            source="env",
            raw_value=raw,
        )
    if parsed <= TTL_SLOT_5M_MAX_SECONDS:
        return CacheTtlResolution(
            enabled=True,
            seconds=parsed,
            api_ttl_string=TTL_STRING_5M,
            source="env",
            raw_value=raw,
        )
    clamped = min(parsed, TTL_SLOT_1H_MAX_SECONDS)
    return CacheTtlResolution(
        enabled=True,
        seconds=clamped,
        api_ttl_string=TTL_STRING_1H,
        source="env",
        raw_value=raw,
    )


# ---------------------------------------------------------------------------
# Cache-affinity key (Wakir-side telemetry, not sent to Anthropic)
# ---------------------------------------------------------------------------


def derive_cache_affinity_key(
    *,
    persona_id: str,
    v907_pin: str,
    model: str,
    ttl_seconds: int,
) -> str:
    """Build the Wakir-side cache-affinity key.

    Format::

        anthropic:<model>:<persona_id>:<v907_pin>:ttl<seconds>

    Properties:

    - **V-907-pin-bound**: changing the pin (Persona-Def change)
      yields a different affinity key, parity with the Anthropic-side
      cache-miss-on-prefix-change behaviour (the breakpoint hashes the
      prefix tokens, which contain the persona-def text whose hash is
      the V-907 pin).
    - **Model-scoped**: Claude-Opus-4-7 vs. Claude-Sonnet-4-6 do not
      share a cache slot (Anthropic's behaviour); the affinity key
      reflects that explicitly.
    - **Persona-scoped**: two different personas with the *same*
      pin would still share the affinity key by accident; the
      ``persona_id`` segment makes the key persona-unique.
    - **TTL-tagged**: 5m and 1h slots are distinct on the Anthropic
      side; the affinity key tags ``ttl<seconds>`` so operators can
      cross-reference.

    The affinity key is deliberately not sent to the API. It is a
    log/metric label only, intended for the ``cache_affinity_key``
    field in the structured-JSON :class:`CacheTelemetry` log line.
    """
    if not persona_id:
        raise ValueError("persona_id must be non-empty")
    if not v907_pin:
        raise ValueError("v907_pin must be non-empty")
    if not model:
        raise ValueError("model must be non-empty")
    if ttl_seconds < 0:
        raise ValueError("ttl_seconds must be non-negative")
    return f"anthropic:{model}:{persona_id}:{v907_pin}:ttl{ttl_seconds}"


# ---------------------------------------------------------------------------
# Request payload builder (B.2 pattern, ADR-0064)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CachedRequestPayload:
    """The Anthropic Messages API request payload + provenance.

    - :attr:`payload`: dict ready to be JSON-encoded and POST-ed to
      ``api.anthropic.com/v1/messages``.
    - :attr:`cache_enabled`: ``True`` iff a ``cache_control`` block
      was placed on the static prefix.
    - :attr:`cache_affinity_key`: Wakir-side telemetry key (see
      :func:`derive_cache_affinity_key`).
    - :attr:`breakpoint_count`: number of ``cache_control`` blocks
      in the payload (always 0 or 1 in the Phase-2a B.2 pattern).
    """

    payload: Mapping[str, Any]
    cache_enabled: bool
    cache_affinity_key: str
    breakpoint_count: int


def build_anthropic_request_payload(
    *,
    model: str,
    persona_id: str,
    v907_pin: str,
    static_prefix_text: str,
    task_user_text: str,
    max_tokens: int = 1024,
    tools: Optional[Sequence[Mapping[str, Any]]] = None,
    ttl_resolution: Optional[CacheTtlResolution] = None,
    env: Optional[Mapping[str, str]] = None,
) -> CachedRequestPayload:
    """Build the Anthropic Messages API request payload with B.2 caching.

    Arguments:

    - ``static_prefix_text``: the concatenated System-Prompt +
      Persona-Def + tool-description text. The cache breakpoint is
      placed at the **end** of this block. Persona-Def + tool-defs
      are the substantive bytes the operator wants Anthropic to
      cache (~90% cost-discount on these tokens).
    - ``task_user_text``: the per-task user payload. The cache
      breakpoint lives **before** this block; the per-task content is
      always cache-miss.
    - ``tools``: optional list of tool-definition dicts in Anthropic
      tool format. When supplied, the *last* tool entry receives a
      ``cache_control`` block additionally to the ``system`` array tail
      — but Phase-2a defaults to placing the breakpoint on the system
      tail only (the operator-controlled, stable surface). This
      function therefore does NOT auto-decorate ``tools[-1]``; callers
      that want a tool-array breakpoint can compose it explicitly.
    - ``ttl_resolution``: pre-resolved TTL outcome. When ``None`` the
      env var is resolved on the spot via
      :func:`resolve_cache_ttl_from_env`.
    - ``env``: optional env mapping for testability; passed through to
      :func:`resolve_cache_ttl_from_env` when ``ttl_resolution`` is
      ``None``.

    Returns a :class:`CachedRequestPayload`. Behaviour:

    - **Cache enabled** (``ttl_resolution.enabled is True``): the
      ``system`` array final text block carries
      ``cache_control: {"type": "ephemeral", "ttl": "5m"|"1h"}``.
    - **Cache disabled** (``ttl_resolution.enabled is False``): the
      ``system`` array final text block carries no ``cache_control``
      key at all. The affinity key still encodes ``ttl0`` so log
      consumers see the disabled state explicitly.

    The function never imports the ``anthropic`` SDK and never makes
    any HTTP call. Phase-3 wires the live POST against the returned
    payload.
    """
    if ttl_resolution is None:
        ttl_resolution = resolve_cache_ttl_from_env(env=env)
    if not model:
        raise ValueError("model must be non-empty")
    if not persona_id:
        raise ValueError("persona_id must be non-empty")
    if not v907_pin:
        raise ValueError("v907_pin must be non-empty")
    if not static_prefix_text:
        raise ValueError("static_prefix_text must be non-empty")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")

    system_block: dict[str, Any] = {
        "type": "text",
        "text": static_prefix_text,
    }
    breakpoints = 0
    if ttl_resolution.enabled:
        system_block["cache_control"] = {
            "type": "ephemeral",
            "ttl": ttl_resolution.api_ttl_string,
        }
        breakpoints = 1

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [system_block],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": task_user_text},
                ],
            }
        ],
    }
    if tools is not None:
        payload["tools"] = list(tools)

    if breakpoints > ANTHROPIC_MAX_CACHE_BREAKPOINTS:
        # Defence-in-depth; the B.2 pattern caps at 1, but a future
        # extension that composes tool-array + multi-system breakpoints
        # should fail loudly rather than ship a 400-Bad-Request.
        raise ValueError(
            f"breakpoint_count={breakpoints} exceeds Anthropic limit "
            f"{ANTHROPIC_MAX_CACHE_BREAKPOINTS}"
        )

    affinity_key = derive_cache_affinity_key(
        persona_id=persona_id,
        v907_pin=v907_pin,
        model=model,
        ttl_seconds=ttl_resolution.seconds,
    )
    return CachedRequestPayload(
        payload=payload,
        cache_enabled=ttl_resolution.enabled,
        cache_affinity_key=affinity_key,
        breakpoint_count=breakpoints,
    )


# ---------------------------------------------------------------------------
# Telemetry — parse Anthropic ``usage`` response into a structured envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CacheTelemetry:
    """Structured Cache-Hit-Rate telemetry envelope.

    Built from the Anthropic Messages API response ``usage`` object.

    Fields:

    - :attr:`input_tokens`: tokens **after** the last cache breakpoint
      (uncached input on this request, i.e. the per-task user payload).
    - :attr:`output_tokens`: generated output tokens.
    - :attr:`cache_read_input_tokens`: tokens served from cache
      (cache-hit count).
    - :attr:`cache_creation_input_tokens`: tokens written into the
      cache by this request (cold-start / TTL-expired path).
    - :attr:`total_input_tokens`: convenience sum
      (``input + cache_read + cache_creation``).
    - :attr:`cache_hit_rate_input_only`: ratio
      ``cache_read / (cache_read + cache_creation + input)``,
      0.0 when no input tokens at all (degenerate response).
    - :attr:`cache_ephemeral_5m_input_tokens`: of the
      ``cache_creation_input_tokens``, how many landed in the 5-minute
      slot. ``None`` when the API did not split (older response shape).
    - :attr:`cache_ephemeral_1h_input_tokens`: 1-hour slot writes.
    - :attr:`cache_affinity_key`: passed through from the
      :class:`CachedRequestPayload` that produced the request.
    """

    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    total_input_tokens: int
    cache_hit_rate_input_only: float
    cache_ephemeral_5m_input_tokens: Optional[int]
    cache_ephemeral_1h_input_tokens: Optional[int]
    cache_affinity_key: str

    def to_structured_log_dict(self) -> dict[str, Any]:
        """Return the structured-JSON log-line representation."""
        return {
            "event": "anthropic_cache_telemetry",
            "cache_affinity_key": self.cache_affinity_key,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "total_input_tokens": self.total_input_tokens,
            "cache_hit_rate_input_only": self.cache_hit_rate_input_only,
            "cache_ephemeral_5m_input_tokens": (
                self.cache_ephemeral_5m_input_tokens
            ),
            "cache_ephemeral_1h_input_tokens": (
                self.cache_ephemeral_1h_input_tokens
            ),
        }

    def to_structured_log_line(self) -> str:
        """Return the structured-JSON log-line as a single JSON string."""
        return json.dumps(self.to_structured_log_dict(), sort_keys=True)


def parse_cache_telemetry(
    *,
    usage: Mapping[str, Any],
    cache_affinity_key: str,
) -> CacheTelemetry:
    """Parse the Anthropic Messages API ``usage`` object into telemetry.

    Tolerates the older response shape (no ``cache_creation`` sub-dict)
    by setting the per-slot breakdown fields to ``None``. Missing
    ``cache_read_input_tokens`` / ``cache_creation_input_tokens`` keys
    default to ``0`` (the API omits these on cache-disabled responses).
    """
    if not isinstance(usage, Mapping):
        raise TypeError(
            f"usage must be a mapping, got {type(usage).__name__}"
        )
    if not cache_affinity_key:
        raise ValueError("cache_affinity_key must be non-empty")

    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    cache_read = int(usage.get("cache_read_input_tokens", 0))
    cache_creation = int(usage.get("cache_creation_input_tokens", 0))

    total_input = input_tokens + cache_read + cache_creation
    if total_input > 0:
        hit_rate = cache_read / total_input
    else:
        hit_rate = 0.0

    creation_breakdown = usage.get("cache_creation")
    ephemeral_5m: Optional[int]
    ephemeral_1h: Optional[int]
    if isinstance(creation_breakdown, Mapping):
        ephemeral_5m = int(
            creation_breakdown.get("ephemeral_5m_input_tokens", 0)
        )
        ephemeral_1h = int(
            creation_breakdown.get("ephemeral_1h_input_tokens", 0)
        )
    else:
        ephemeral_5m = None
        ephemeral_1h = None

    return CacheTelemetry(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
        total_input_tokens=total_input,
        cache_hit_rate_input_only=hit_rate,
        cache_ephemeral_5m_input_tokens=ephemeral_5m,
        cache_ephemeral_1h_input_tokens=ephemeral_1h,
        cache_affinity_key=cache_affinity_key,
    )


# ---------------------------------------------------------------------------
# Provider-lock-in boundary helper (ADR-0064 §"Provider-Lock-In")
# ---------------------------------------------------------------------------


def anthropic_hook_supports_caching() -> bool:
    """Module-level capability probe.

    An Anthropic-Messages-API hook returns ``True`` from its
    ``supports_caching()`` method by delegating to this constant. An
    OpenAI / other-provider hook returns ``False`` (its own cache
    model is incompatible with the B.2 breakpoint shape; ADR-0064b
    would carry that out).
    """
    return True


__all__ = [
    "ANTHROPIC_MAX_CACHE_BREAKPOINTS",
    "CacheTelemetry",
    "CacheTtlResolution",
    "CachedRequestPayload",
    "DEFAULT_CACHE_TTL_SECONDS",
    "ENV_CACHE_TTL_SECONDS",
    "TTL_SLOT_1H_MAX_SECONDS",
    "TTL_SLOT_5M_MAX_SECONDS",
    "TTL_STRING_1H",
    "TTL_STRING_5M",
    "anthropic_hook_supports_caching",
    "build_anthropic_request_payload",
    "derive_cache_affinity_key",
    "parse_cache_telemetry",
    "resolve_cache_ttl_from_env",
]
