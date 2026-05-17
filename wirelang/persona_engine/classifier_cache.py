# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Classifier-Decision-Cache — ADR-0064 Phase-2c production-wiring.

Overview
--------

ADR-0064 Phase-2c ships the LLM-Classifier path
(:mod:`llm_classifier`) and the production-mode integration
(:mod:`anthropic_call`). For Tag-16 we close the cost-control loop:
every classifier verdict is keyed on a deterministic *task-hash*
(persona-id + persona-def-pin + prompt-payload) and cached so that an
identical task does **not** trigger a second Haiku call within the TTL
window. The cache is a process-local TTL dict — Phase-3 will swap in a
shared NATS-KV-backed backend behind the same interface.

Design intent
-------------

- **Pure-stdlib**: no third-party imports, no network. The cache lives
  in process memory; a restart clears it (this is intentional for
  Phase-2c — Phase-3 adds a durable backend).
- **TTL-honest**: every entry stores the wall-clock insertion time;
  reads compute remaining-TTL on access and evict on expiry. The clock
  source is injectable for hermetic tests (deterministic monotonic
  fake).
- **Task-hash determinism**: identical inputs → identical key (SHA-256
  hex). The hash includes the persona-id, the persona-def pin (so a
  persona-def change invalidates the cache automatically), and the
  full prompt-payload. The classifier's verdict envelope changes
  *only* when one of these inputs changes; caching the verdict is
  therefore safe.
- **Default-aus**: TTL ``0`` (or unset env var) means the cache is
  disabled and every call hits the classifier. Production behaviour
  stays byte-identical to pre-Tag-16 when the operator has not opted
  in.

ENV variable contract
---------------------

::

    WAKIR_CLASSIFIER_CACHE_TTL (default "3600")

        Classifier-decision cache TTL in seconds. ``0`` disables the
        cache. Negative values are clamped to ``0``. Unparseable
        values fall back to the default (3600 = 1h).

Cache-key derivation
--------------------

The cache key is a SHA-256 hex-digest of a canonical byte-string
composed of:

    persona_id || "\\x1f" || persona_def_pin || "\\x1f" || prompt_payload

``persona_def_pin`` is the V-907 pin of the persona-def when
available (read from ``persona_def["v907_pin"]``); when absent we use
a stable JSON-canonical serialization of the persona-def dict so a
persona-def field change invalidates the cache. The ``\\x1f`` (US,
unit separator) delimiter prevents prefix-collision ambiguity (e.g.
two personas whose IDs differ only by a trailing-space).

Telemetry
---------

Every cache lookup emits a structured-JSON event to the optional
``sink`` callable so operators can wire the events into the same
JSONL substrate the routing-decision sink uses. The event shape is:

::

    {
        "ts_utc": "<rfc3339>",
        "persona_id": "<id>",
        "task_hash_prefix": "<first-12-chars-of-key>",
        "cache_event": "<hit|miss|expired|disabled>",
        "ttl_seconds_remaining": <int|null>,
        "cache_size": <int>,
    }

Only the first 12 hex characters of the key are emitted to keep the
sink output bounded and to avoid leaking full prompt-payload
provenance to the operator-facing log (the full hash is internal).

Hermetic-test surface
---------------------

All tests in
``wirelang/tests/persona_engine/test_classifier_cache.py`` and the
relevant entries in ``test_anthropic_routing_integration.py`` are
pure-stdlib. The clock source is overridable via the
:class:`ClassifierDecisionCache` ``clock`` parameter so TTL-expiry
behaviour is deterministic without ``time.sleep``.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .llm_classifier import LlmClassifierEvent

CLASSIFIER_CACHE_VERSION = "v1"

WAKIR_CLASSIFIER_CACHE_TTL_ENV = "WAKIR_CLASSIFIER_CACHE_TTL"
WAKIR_CLASSIFIER_CACHE_TTL_DEFAULT_SECONDS = 3600

_UNIT_SEPARATOR = "\x1f"


def read_cache_ttl_seconds(env: Optional[dict] = None) -> int:
    """Return the operator-configured cache-TTL in seconds.

    Default :data:`WAKIR_CLASSIFIER_CACHE_TTL_DEFAULT_SECONDS` if the
    env-var is unset. ``0`` disables the cache; negative values are
    clamped to ``0`` (so misconfiguration cannot create a negative-TTL
    cache that would expire on every read with confusing telemetry).
    Unparseable values fall back to the default.
    """
    src = env if env is not None else os.environ
    raw = (src.get(WAKIR_CLASSIFIER_CACHE_TTL_ENV) or "").strip()
    if not raw:
        return WAKIR_CLASSIFIER_CACHE_TTL_DEFAULT_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return WAKIR_CLASSIFIER_CACHE_TTL_DEFAULT_SECONDS
    if value < 0:
        return 0
    return value


def _canonical_persona_def_pin(persona_def: Optional[dict]) -> str:
    """Return the V-907 pin if present, else a JSON-canonical fallback.

    Including the persona-def in the cache key ensures that a
    persona-def field change (e.g. role-band update, llm_tier change,
    Befugnis-Rahmen edit) automatically invalidates the classifier
    cache. The V-907 pin is the cheap path — when persona-def carries
    the substrate-built pin we use it directly. When absent (e.g.
    hermetic tests with synthetic persona-defs) we fall back to a
    sorted-key JSON serialization so the result is still deterministic.
    """
    if persona_def is None:
        return ""
    pin_field = persona_def.get("v907_pin")
    if isinstance(pin_field, str) and pin_field:
        return pin_field
    try:
        return json.dumps(persona_def, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        # Defensive: a persona-def with unserialisable values still
        # produces a stable-enough key from its repr (the cache is
        # observation-only; a key collision is acceptable).
        return repr(persona_def)


def derive_task_hash(
    *,
    persona_id: str,
    persona_def: Optional[dict],
    prompt_payload: str,
) -> str:
    """SHA-256 hex digest of the canonical task-hash byte-string.

    The hash is the cache key. See module docstring for the
    derivation rules. Returns a 64-char lowercase hex string.
    """
    if not isinstance(persona_id, str):
        persona_id = str(persona_id)
    if not isinstance(prompt_payload, str):
        prompt_payload = str(prompt_payload)
    pin = _canonical_persona_def_pin(persona_def)
    parts = [persona_id, pin, prompt_payload]
    canonical = _UNIT_SEPARATOR.join(parts).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _utc_now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass(frozen=True)
class CacheLookupEvent:
    """Structured-JSON envelope for a single cache lookup.

    Fields:

    - ``ts_utc``: RFC3339 lookup timestamp (operator-supplied for
      hermetic tests; otherwise wall-clock UTC).
    - ``persona_id``: persona-id that issued the lookup.
    - ``task_hash_prefix``: first 12 hex chars of the full task-hash
      (full hash kept internal to avoid leaking prompt provenance).
    - ``cache_event``: ``"hit"`` / ``"miss"`` / ``"expired"`` /
      ``"disabled"``. ``"expired"`` means a stale entry was evicted
      during this lookup; the caller still issues the classifier
      call. ``"disabled"`` means TTL=0 so the cache is bypassed.
    - ``ttl_seconds_remaining``: remaining TTL of the returned entry
      (only set on ``"hit"``); ``None`` otherwise.
    - ``cache_size``: number of entries in the cache *after* this
      lookup (post-eviction).
    """

    ts_utc: str
    persona_id: str
    task_hash_prefix: str
    cache_event: str
    ttl_seconds_remaining: Optional[int]
    cache_size: int

    def to_json(self) -> str:
        """Byte-stable JSON serialization (keys sorted)."""
        return json.dumps(
            {
                "cache_event": self.cache_event,
                "cache_size": self.cache_size,
                "persona_id": self.persona_id,
                "task_hash_prefix": self.task_hash_prefix,
                "ts_utc": self.ts_utc,
                "ttl_seconds_remaining": self.ttl_seconds_remaining,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass
class _CacheEntry:
    """Internal cache entry: classifier-event + insertion wall-clock.

    Stored in the dict keyed by task-hash. The insertion timestamp is
    a monotonic-clock reading so TTL math is robust against
    wall-clock drift.
    """

    event: LlmClassifierEvent
    inserted_monotonic: float


@dataclass
class ClassifierDecisionCache:
    """In-process TTL-cache for LLM-classifier decisions.

    Parameters:

    - ``ttl_seconds``: cache TTL. ``0`` disables the cache (every
      lookup yields ``"disabled"`` and the caller must invoke the
      classifier). Default from
      :func:`read_cache_ttl_seconds`.
    - ``clock``: callable returning a monotonic timestamp (seconds,
      float). Defaults to :func:`time.monotonic`. Tests inject a
      fake clock to drive TTL expiry deterministically.
    - ``sink``: optional callable receiving every
      :class:`CacheLookupEvent`. Sink exceptions are swallowed so a
      broken observability target never breaks the engine path
      (consistent with the heuristic-router + llm-classifier sinks).

    Thread-safety: the cache is **not** thread-safe. Phase-2c targets
    single-threaded persona-engine invocations; Phase-3's NATS-KV
    backend handles cross-process concurrency.
    """

    ttl_seconds: int = field(default=WAKIR_CLASSIFIER_CACHE_TTL_DEFAULT_SECONDS)
    clock: Callable[[], float] = field(default=time.monotonic)
    sink: Optional[Callable[[CacheLookupEvent], None]] = field(default=None)
    _store: dict[str, _CacheEntry] = field(default_factory=dict, init=False)

    @classmethod
    def from_env(
        cls,
        env: Optional[dict] = None,
        *,
        clock: Optional[Callable[[], float]] = None,
        sink: Optional[Callable[[CacheLookupEvent], None]] = None,
    ) -> "ClassifierDecisionCache":
        """Construct a cache with TTL read from the operator env."""
        return cls(
            ttl_seconds=read_cache_ttl_seconds(env),
            clock=clock if clock is not None else time.monotonic,
            sink=sink,
        )

    @property
    def enabled(self) -> bool:
        """``True`` iff the cache is honouring lookups (TTL > 0)."""
        return self.ttl_seconds > 0

    def lookup(
        self,
        *,
        persona_id: str,
        persona_def: Optional[dict],
        prompt_payload: str,
        ts_utc: Optional[str] = None,
    ) -> Optional[LlmClassifierEvent]:
        """Look up a cached classifier event for the given inputs.

        Returns:

        - ``None`` if the cache is disabled (TTL=0), the entry is
          missing, or the entry has expired (in which case the stale
          entry is evicted as a side-effect).
        - The cached :class:`LlmClassifierEvent` otherwise.

        Emits exactly one :class:`CacheLookupEvent` to the configured
        sink per call (regardless of the outcome).
        """
        key = derive_task_hash(
            persona_id=persona_id,
            persona_def=persona_def,
            prompt_payload=prompt_payload,
        )
        prefix = key[:12]
        ts = ts_utc or _utc_now_rfc3339()
        if not self.enabled:
            self._emit(
                CacheLookupEvent(
                    ts_utc=ts,
                    persona_id=persona_id,
                    task_hash_prefix=prefix,
                    cache_event="disabled",
                    ttl_seconds_remaining=None,
                    cache_size=len(self._store),
                )
            )
            return None
        entry = self._store.get(key)
        if entry is None:
            self._emit(
                CacheLookupEvent(
                    ts_utc=ts,
                    persona_id=persona_id,
                    task_hash_prefix=prefix,
                    cache_event="miss",
                    ttl_seconds_remaining=None,
                    cache_size=len(self._store),
                )
            )
            return None
        elapsed = self.clock() - entry.inserted_monotonic
        remaining = self.ttl_seconds - int(elapsed)
        if remaining <= 0:
            # Stale → evict + report expired (treated as a miss by the
            # caller; the caller should issue the classifier call).
            del self._store[key]
            self._emit(
                CacheLookupEvent(
                    ts_utc=ts,
                    persona_id=persona_id,
                    task_hash_prefix=prefix,
                    cache_event="expired",
                    ttl_seconds_remaining=None,
                    cache_size=len(self._store),
                )
            )
            return None
        self._emit(
            CacheLookupEvent(
                ts_utc=ts,
                persona_id=persona_id,
                task_hash_prefix=prefix,
                cache_event="hit",
                ttl_seconds_remaining=remaining,
                cache_size=len(self._store),
            )
        )
        return entry.event

    def store(
        self,
        *,
        persona_id: str,
        persona_def: Optional[dict],
        prompt_payload: str,
        event: LlmClassifierEvent,
    ) -> str:
        """Cache a classifier event for future lookups.

        Returns the task-hash that was used as the storage key (the
        caller may want to log it). When the cache is disabled
        (TTL=0) this is a silent no-op and the function still returns
        the would-be key so the caller's telemetry is consistent.
        """
        key = derive_task_hash(
            persona_id=persona_id,
            persona_def=persona_def,
            prompt_payload=prompt_payload,
        )
        if not self.enabled:
            return key
        self._store[key] = _CacheEntry(
            event=event,
            inserted_monotonic=self.clock(),
        )
        return key

    def clear(self) -> None:
        """Drop all cached entries (test + operator-tool hook)."""
        self._store.clear()

    def size(self) -> int:
        """Return the current number of cached entries."""
        return len(self._store)

    def _emit(self, event: CacheLookupEvent) -> None:
        sink = self.sink
        if sink is None:
            return
        try:
            sink(event)
        except Exception:
            # Observation-only sink. Engine path stays intact even if
            # the operator-configured target is broken.
            pass


__all__ = [
    "CLASSIFIER_CACHE_VERSION",
    "CacheLookupEvent",
    "ClassifierDecisionCache",
    "WAKIR_CLASSIFIER_CACHE_TTL_DEFAULT_SECONDS",
    "WAKIR_CLASSIFIER_CACHE_TTL_ENV",
    "derive_task_hash",
    "read_cache_ttl_seconds",
]
