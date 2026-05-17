# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Persona-engine anchor-submit-worker — Python pendant.

This module is the **Python sibling** of the Rust crate
``persona-engine-anchor-submit-worker`` (Phase-3a Item 12, PR #149,
merged 2026-05-15). The Rust crate defines the authoritative
FSM-decision shape and tick semantics; this module mirrors them so
the Phase-3a 3-way-triangle (Doppelbetrieb) can diff Python-side
and Rust-side decision records byte-for-byte for the same
deterministic input stream.

Scope
-----

The submit-worker is the production-loop substrate on top of the
anchor-emitter envelopes. It accepts in-flight ``AnchorEnvelope``
records, drives a deterministic retry / dead-letter / writeback
FSM, and produces one of five outcomes per ``tick()``:

* ``Success``   — transport accepted; writeback invoked; envelope
                  removed from queue.
* ``Throttled`` — token-bucket refused; transport NOT called;
                  envelope requeued at the front; retry-count
                  unchanged.
* ``Retrying``  — transport returned a retriable error; retry
                  budget consumed; envelope requeued with a
                  full-jitter backoff delay.
* ``Dead``      — retry budget exhausted (or permanent error);
                  envelope moved to the dead-letter store.
* ``Idle``      — no eligible envelope (queue empty or every
                  queued envelope has ``next_eligible_at > now``).

The FSM is single-stepped: one ``tick()`` advances exactly one
envelope through one transition, then returns. This single-step
posture matches the Rust crate and is what makes cross-lang
fixture replay deterministic — no embedded sleeps, no background
pollers, no time-dependent assertions.

Schema parity table (Python <-> Rust)
-------------------------------------

::

    Python helper                          <-> Rust function
    ---------------------------------------------------------------
    AnchorSubmitWorker (class)             <-> SubmitWorker (struct)
    SubmitWorkerConfig (dataclass)         <-> SubmitWorkerConfig
    SubmitResultKind (enum)                <-> SubmitResult (variants)
    decision_record(result) -> dict        <-> (see below)
    TransportOutcome (enum)                <-> TransportOutcome
    DeadLetterRecord (dataclass)           <-> DeadLetterRecord
    DEFAULT_RATE_REQUESTS / _WINDOW_SECS /
      _MAX_RETRY / _RETRY_BASE_DELAY_SECS /
      _RETRY_MAX_DELAY_SECS                <-> same constants
    ENV_SUBMIT_RATE / ENV_MAX_RETRY        <-> same env var names

Decision record (cross-lang pin)
--------------------------------

For each ``tick()`` the worker emits a **decision record** — a
``dict`` with a JCS-canonical wire-shape that the Rust crate emits
in the same byte-for-byte form. The wire-shape is the cross-lang
fixture-pin contract; the Python and Rust sides agree on the same
JSON object per (deterministic input + clock + RNG) replay.

Top-level keys (lex-ordered for JCS):

* ``attempt`` — one-based retry attempt that just happened
                (0 for Success/Throttled/Idle/permanent-Dead).
* ``event_id`` — envelope identifier (``""`` for Idle).
* ``kind`` — one of ``"success"``, ``"throttled"``, ``"retrying"``,
             ``"dead"``, ``"idle"``.
* ``next_delay_secs`` — backoff delay drawn for the next attempt
                        (0 for non-Retrying outcomes).
* ``terminal_error`` — last error string (``""`` for non-Dead).

Backoff schedule
----------------

Full-jitter (Marc Brooker formulation):

    delay(attempt) = uniform[0, min(cap, base * 2^(attempt - 1))]

where ``attempt`` is one-based. The Python ``Rng`` interface is a
single-method ``gen_range_secs(upper_inclusive) -> int`` matching
the Rust ``Rng`` trait; the deterministic stub cycles a pinned
``Sequence[int]`` and clamps values exceeding the upper bound
(parity-pinned with ``DeterministicRng`` on the Rust side).

Throttling semantics
--------------------

``Throttled`` is a back-pressure signal, **not a failure**. The
token-bucket check happens **first**; only after a token is
consumed do we call the transport. A throttle does not call the
transport, does not increment the retry counter, does not invoke
the writeback, and re-queues the envelope at the **front** of the
queue so the next eligible tick serves it first.

Sandbox boundary
----------------

The submit-worker is a **pure FSM** with three injected substrates:
``SubmitTransport`` (caller-supplied I/O), ``Clock`` (caller-supplied
time source), ``Rng`` (caller-supplied jitter source). No module-level
I/O; no implicit network or filesystem dependency. Safe to call from
any sandbox; the cross-lang fixture tests exercise it with pinned
deterministic substrates.

ADR anchors
-----------

* ADR-0007 — OTS-anchor substrate (parent module).
* ADR-0023a / ADR-0023b — Spec-first discipline.
* ADR-0036 — Phase-3a 3-way-triangle (Python / Rust / Cross-lang).
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Constants (cross-lang pin — must mirror the Rust crate).
# ---------------------------------------------------------------------------

#: Default token-bucket refill rate (requests per window).
DEFAULT_RATE_REQUESTS: int = 1

#: Default token-bucket refill window in seconds.
DEFAULT_RATE_WINDOW_SECS: int = 30

#: Default max retry attempts before dead-lettering.
DEFAULT_MAX_RETRY: int = 5

#: Default base delay for exponential backoff (seconds).
DEFAULT_RETRY_BASE_DELAY_SECS: int = 1

#: Default cap on the upper bound of the full-jitter delay (seconds).
DEFAULT_RETRY_MAX_DELAY_SECS: int = 300

#: Environment-variable name controlling the token-bucket rate.
ENV_SUBMIT_RATE: str = "WAKIR_ANCHOR_SUBMIT_RATE"

#: Environment-variable name controlling the max retry budget.
ENV_MAX_RETRY: str = "WAKIR_ANCHOR_MAX_RETRY"

#: Decision-record wire-shape schema identifier (cross-lang pin).
DECISION_RECORD_SCHEMA: str = "wakir.wat.anchor-submit-decision/1"

#: SubmitResult kind wire-strings (cross-lang pin with Rust).
KIND_SUCCESS: str = "success"
KIND_THROTTLED: str = "throttled"
KIND_RETRYING: str = "retrying"
KIND_DEAD: str = "dead"
KIND_IDLE: str = "idle"

_VALID_KINDS: Tuple[str, ...] = (
    KIND_DEAD,
    KIND_IDLE,
    KIND_RETRYING,
    KIND_SUCCESS,
    KIND_THROTTLED,
)


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class SubmitWorkerError(Exception):
    """Base error for submit-worker misuse."""


# ---------------------------------------------------------------------------
# Transport outcome enum + transport surface.
# ---------------------------------------------------------------------------


class TransportOutcomeKind(enum.Enum):
    """Three-arm outcome enum mirroring the Rust crate."""

    ACCEPTED = "accepted"
    RETRIABLE = "retriable"
    PERMANENT = "permanent"


@dataclass(frozen=True)
class TransportOutcome:
    """One transport submission outcome.

    Constructor helpers ``accepted()``, ``retriable(err)``,
    ``permanent(err)`` mirror the Rust enum variants.
    """

    kind: TransportOutcomeKind
    error: str = ""

    @staticmethod
    def accepted() -> "TransportOutcome":
        return TransportOutcome(TransportOutcomeKind.ACCEPTED, "")

    @staticmethod
    def retriable(err: str) -> "TransportOutcome":
        return TransportOutcome(TransportOutcomeKind.RETRIABLE, err)

    @staticmethod
    def permanent(err: str) -> "TransportOutcome":
        return TransportOutcome(TransportOutcomeKind.PERMANENT, err)


class SubmitTransport:
    """Abstract OTS-calendar transport.

    Implementations override :meth:`submit` to perform the real
    HTTPS call. The cross-lang fixture tests inject a
    :class:`ScriptedTransport` that pops outcomes from a pinned list.
    """

    def submit(self, envelope: Mapping[str, Any]) -> TransportOutcome:
        raise NotImplementedError


class ScriptedTransport(SubmitTransport):
    """Test-only transport that pops outcomes from a pinned script.

    Mirrors the Rust ``FakeTransport``: any extra ``submit()`` call
    after the script is exhausted raises (loud-fail) so the
    throttle / idle invariants can be asserted.
    """

    def __init__(self, script: Sequence[TransportOutcome]) -> None:
        self._script: List[TransportOutcome] = list(script)
        self._calls: int = 0
        self._seen: List[str] = []

    @property
    def calls(self) -> int:
        return self._calls

    @property
    def seen(self) -> List[str]:
        return list(self._seen)

    def submit(self, envelope: Mapping[str, Any]) -> TransportOutcome:
        self._calls += 1
        self._seen.append(str(envelope.get("event_id", "")))
        if not self._script:
            raise SubmitWorkerError(
                "ScriptedTransport script exhausted but submit() was called "
                f"for event_id={envelope.get('event_id')!r} — this signals "
                "an unintended extra transport call (likely a throttle/idle "
                "invariant violation)"
            )
        return self._script.pop(0)


# ---------------------------------------------------------------------------
# Writeback sink.
# ---------------------------------------------------------------------------


class WriteBackSink:
    """Hook invoked on successful submission."""

    def write_success(self, envelope: Mapping[str, Any]) -> None:
        raise NotImplementedError


class NoopWriteBackSink(WriteBackSink):
    """Default no-op sink. Production code injects a substantive sink."""

    def write_success(self, envelope: Mapping[str, Any]) -> None:  # noqa: D401
        return None


class RecordingWriteBackSink(WriteBackSink):
    """Test-only sink that records the order of write_success calls."""

    def __init__(self) -> None:
        self._calls: List[str] = []

    @property
    def calls(self) -> List[str]:
        return list(self._calls)

    def write_success(self, envelope: Mapping[str, Any]) -> None:
        self._calls.append(str(envelope.get("event_id", "")))


# ---------------------------------------------------------------------------
# Clock + RNG (deterministic-substrate interfaces).
# ---------------------------------------------------------------------------


class Clock:
    """Pluggable seconds-since-epoch clock."""

    def now_secs(self) -> int:
        raise NotImplementedError


class SystemClock(Clock):
    """Wall-clock implementation."""

    def now_secs(self) -> int:
        return int(time.time())


class ManualClock(Clock):
    """Test clock: monotonic, advanced explicitly by the caller."""

    def __init__(self, start: int = 0) -> None:
        self._now: int = int(start)

    def now_secs(self) -> int:
        return self._now

    def advance(self, by_secs: int) -> None:
        if by_secs < 0:
            raise SubmitWorkerError(
                "ManualClock.advance() requires a non-negative delta"
            )
        self._now += int(by_secs)


class Rng:
    """Pluggable bounded-integer RNG used by full-jitter backoff."""

    def gen_range_secs(self, upper_inclusive: int) -> int:
        raise NotImplementedError


class DeterministicRng(Rng):
    """Cycle a pinned sequence; clamp values exceeding the upper bound.

    Matches the Rust ``DeterministicRng``: clamping (not modulo)
    matches "uniform draw within bound" semantics, the sequence
    wraps at the end, and ``upper_inclusive == 0`` always returns 0.
    """

    def __init__(self, sequence: Sequence[int]) -> None:
        if not sequence:
            raise SubmitWorkerError(
                "DeterministicRng requires a non-empty sequence"
            )
        self._sequence: List[int] = list(sequence)
        self._cursor: int = 0

    def gen_range_secs(self, upper_inclusive: int) -> int:
        if upper_inclusive == 0:
            return 0
        raw = self._sequence[self._cursor % len(self._sequence)]
        self._cursor = (self._cursor + 1) % len(self._sequence)
        return upper_inclusive if raw > upper_inclusive else raw


# ---------------------------------------------------------------------------
# Dead-letter store + record.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeadLetterRecord:
    """One row in the dead-letter store.

    Wire-parity with Rust ``DeadLetterRecord``: same five fields in
    the same order; ``dead_letter_at`` is RFC-3339 second-precision
    UTC (``YYYY-MM-DDTHH:MM:SSZ``).
    """

    event_id: str
    persona_id: str
    dead_letter_at: str
    terminal_error: str
    retry_count: int

    def to_wire_dict(self) -> Dict[str, Any]:
        """Lex-ordered JCS-friendly dict for cross-lang byte parity."""

        return {
            "dead_letter_at": self.dead_letter_at,
            "event_id": self.event_id,
            "persona_id": self.persona_id,
            "retry_count": int(self.retry_count),
            "terminal_error": self.terminal_error,
        }


class DeadLetterStore:
    """Abstract dead-letter store."""

    def record(self, record: DeadLetterRecord) -> None:
        raise NotImplementedError

    def snapshot(self) -> List[DeadLetterRecord]:
        raise NotImplementedError


class InMemoryDeadLetterStore(DeadLetterStore):
    """Default backing for tests and pure-FSM callers."""

    def __init__(self) -> None:
        self._rows: List[DeadLetterRecord] = []

    def record(self, record: DeadLetterRecord) -> None:
        self._rows.append(record)

    def snapshot(self) -> List[DeadLetterRecord]:
        return list(self._rows)


# ---------------------------------------------------------------------------
# Config.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubmitWorkerConfig:
    """Worker construction parameters.

    Field semantics are identical to the Rust crate's
    ``SubmitWorkerConfig``; the wire-shape of
    :meth:`to_wire_dict` is the cross-lang config-pin.
    """

    rate_requests: int = DEFAULT_RATE_REQUESTS
    rate_window_secs: int = DEFAULT_RATE_WINDOW_SECS
    max_retry: int = DEFAULT_MAX_RETRY
    retry_base_delay_secs: int = DEFAULT_RETRY_BASE_DELAY_SECS
    retry_max_delay_secs: int = DEFAULT_RETRY_MAX_DELAY_SECS

    def to_wire_dict(self) -> Dict[str, Any]:
        return {
            "max_retry": int(self.max_retry),
            "rate_requests": int(self.rate_requests),
            "rate_window_secs": int(self.rate_window_secs),
            "retry_base_delay_secs": int(self.retry_base_delay_secs),
            "retry_max_delay_secs": int(self.retry_max_delay_secs),
        }

    @staticmethod
    def from_env_with(
        getenv: Callable[[str], Optional[str]],
    ) -> "SubmitWorkerConfig":
        cfg = SubmitWorkerConfig()
        rate_raw = getenv(ENV_SUBMIT_RATE)
        retry_raw = getenv(ENV_MAX_RETRY)
        rate_requests = cfg.rate_requests
        rate_window_secs = cfg.rate_window_secs
        max_retry = cfg.max_retry
        if rate_raw is not None:
            parsed = _parse_rate_spec(rate_raw)
            if parsed is not None:
                rate_requests, rate_window_secs = parsed
        if retry_raw is not None:
            try:
                n = int(retry_raw.strip())
                if n >= 0:
                    max_retry = n
            except (ValueError, AttributeError):
                pass
        return SubmitWorkerConfig(
            rate_requests=rate_requests,
            rate_window_secs=rate_window_secs,
            max_retry=max_retry,
            retry_base_delay_secs=cfg.retry_base_delay_secs,
            retry_max_delay_secs=cfg.retry_max_delay_secs,
        )

    @staticmethod
    def from_env() -> "SubmitWorkerConfig":
        return SubmitWorkerConfig.from_env_with(lambda k: os.environ.get(k))


def _parse_rate_spec(s: str) -> Optional[Tuple[int, int]]:
    """Parse ``"<reqs>/<secs>"`` returning ``None`` on garbage / zero."""

    s = s.strip()
    if "/" not in s:
        return None
    a, b = s.split("/", 1)
    try:
        reqs = int(a.strip())
        secs = int(b.strip())
    except ValueError:
        return None
    if reqs <= 0 or secs <= 0:
        return None
    return (reqs, secs)


# ---------------------------------------------------------------------------
# SubmitResult — decision-record building blocks.
# ---------------------------------------------------------------------------


class SubmitResultKind(enum.Enum):
    """Result enum mirroring the Rust ``SubmitResult`` variants."""

    SUCCESS = KIND_SUCCESS
    THROTTLED = KIND_THROTTLED
    RETRYING = KIND_RETRYING
    DEAD = KIND_DEAD
    IDLE = KIND_IDLE


@dataclass(frozen=True)
class SubmitResult:
    """One ``tick()`` outcome carrying every field needed for the
    cross-lang decision record."""

    kind: SubmitResultKind
    event_id: str = ""
    attempt: int = 0
    next_delay_secs: int = 0
    terminal_error: str = ""

    @staticmethod
    def success(event_id: str) -> "SubmitResult":
        return SubmitResult(SubmitResultKind.SUCCESS, event_id=event_id)

    @staticmethod
    def throttled(event_id: str) -> "SubmitResult":
        return SubmitResult(SubmitResultKind.THROTTLED, event_id=event_id)

    @staticmethod
    def retrying(event_id: str, attempt: int, next_delay_secs: int) -> "SubmitResult":
        return SubmitResult(
            SubmitResultKind.RETRYING,
            event_id=event_id,
            attempt=int(attempt),
            next_delay_secs=int(next_delay_secs),
        )

    @staticmethod
    def dead(event_id: str, terminal_error: str, attempt: int = 0) -> "SubmitResult":
        return SubmitResult(
            SubmitResultKind.DEAD,
            event_id=event_id,
            attempt=int(attempt),
            terminal_error=terminal_error,
        )

    @staticmethod
    def idle() -> "SubmitResult":
        return SubmitResult(SubmitResultKind.IDLE)

    def to_decision_record(self) -> Dict[str, Any]:
        """Serialise to the JCS-friendly decision-record wire-shape.

        Keys are lex-ordered to match the Rust sibling's JSON
        emission and to make canonical-bytes byte-identical when the
        same JCS serialiser runs on both sides.
        """

        return {
            "attempt": int(self.attempt),
            "event_id": str(self.event_id),
            "kind": self.kind.value,
            "next_delay_secs": int(self.next_delay_secs),
            "terminal_error": str(self.terminal_error),
        }


def serialize_decision_record(result: SubmitResult) -> bytes:
    """JCS-canonical bytes of a decision record.

    Stable JSON form: UTF-8, lex-ordered keys, no whitespace,
    ``ensure_ascii=False`` so Unicode round-trips bit-for-bit.
    """

    return json.dumps(
        result.to_decision_record(),
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(blob: bytes) -> str:
    """Lower-case hex SHA-256 of ``blob`` (helper, mirrors Rust)."""

    return hashlib.sha256(blob).hexdigest()


def decision_record_hash(result: SubmitResult) -> str:
    """``sha256:<hex>`` of the canonical decision-record bytes."""

    return "sha256:" + sha256_hex(serialize_decision_record(result))


# ---------------------------------------------------------------------------
# Token-bucket (internal).
# ---------------------------------------------------------------------------


class _TokenBucket:
    """Single-endpoint refill bucket — parity with Rust ``TokenBucket``."""

    __slots__ = ("capacity", "window_secs", "tokens", "last_refill_at")

    def __init__(self, capacity: int, window_secs: int) -> None:
        self.capacity: int = int(capacity)
        self.window_secs: int = int(window_secs)
        self.tokens: int = int(capacity)
        self.last_refill_at: int = 0

    def try_consume(self, now: int) -> bool:
        self._refill(now)
        if self.tokens > 0:
            self.tokens -= 1
            return True
        return False

    def _refill(self, now: int) -> None:
        if self.window_secs == 0 or self.capacity == 0:
            return
        if now < self.last_refill_at:
            return
        elapsed = now - self.last_refill_at
        if elapsed >= self.window_secs:
            windows = elapsed // self.window_secs
            add = self.capacity * windows
            self.tokens = min(self.tokens + add, self.capacity)
            self.last_refill_at += windows * self.window_secs


# ---------------------------------------------------------------------------
# Queue entry (internal).
# ---------------------------------------------------------------------------


@dataclass
class _QueuedEnvelope:
    envelope: Dict[str, Any]
    retry_count: int = 0
    next_eligible_at: int = 0
    last_error: Optional[str] = None


# ---------------------------------------------------------------------------
# RFC-3339 formatter (no chrono dep, parity with Rust crate).
# ---------------------------------------------------------------------------


def format_rfc3339_secs(secs: int) -> str:
    """Format seconds-since-epoch as ``YYYY-MM-DDTHH:MM:SSZ``.

    Hinnant's civil-from-days algorithm; produces the same shape as
    the Rust crate's ``format_rfc3339_secs``.
    """

    if secs < 0:
        secs = 0
    days = secs // 86_400
    secs_of_day = secs % 86_400
    hour = secs_of_day // 3600
    minute = (secs_of_day % 3600) // 60
    second = secs_of_day % 60

    z = days + 719_468
    era = z // 146_097 if z >= 0 else (z - 146_096) // 146_097
    doe = z - era * 146_097
    yoe = (doe - doe // 1460 + doe // 36_524 - doe // 146_096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    year = y + 1 if m <= 2 else y
    return f"{year:04d}-{m:02d}-{d:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"


# ---------------------------------------------------------------------------
# AnchorSubmitWorker — the FSM driver.
# ---------------------------------------------------------------------------


class AnchorSubmitWorker:
    """Tick-driven submit-worker with parity to the Rust sibling.

    Construction parity: ``AnchorSubmitWorker(config, transport,
    dead_letter, writeback, clock, rng)`` matches the Rust
    ``SubmitWorker::new``. Defaults: ``InMemoryDeadLetterStore``,
    ``NoopWriteBackSink``, ``SystemClock``, ``DeterministicRng([0])``
    — the deterministic-RNG default lets callers exercise the FSM
    without supplying jitter.
    """

    def __init__(
        self,
        config: Optional[SubmitWorkerConfig] = None,
        transport: Optional[SubmitTransport] = None,
        dead_letter: Optional[DeadLetterStore] = None,
        writeback: Optional[WriteBackSink] = None,
        clock: Optional[Clock] = None,
        rng: Optional[Rng] = None,
    ) -> None:
        if transport is None:
            raise SubmitWorkerError(
                "AnchorSubmitWorker requires an injected SubmitTransport"
            )
        self._config: SubmitWorkerConfig = config or SubmitWorkerConfig()
        self._transport: SubmitTransport = transport
        self._dead_letter: DeadLetterStore = dead_letter or InMemoryDeadLetterStore()
        self._writeback: WriteBackSink = writeback or NoopWriteBackSink()
        self._clock: Clock = clock or SystemClock()
        self._rng: Rng = rng or DeterministicRng([0])
        self._queue: Deque[_QueuedEnvelope] = deque()
        self._bucket: _TokenBucket = _TokenBucket(
            self._config.rate_requests, self._config.rate_window_secs
        )

    # -- introspection -----------------------------------------------------

    @property
    def config(self) -> SubmitWorkerConfig:
        return self._config

    @property
    def dead_letter_store(self) -> DeadLetterStore:
        return self._dead_letter

    @property
    def writeback_sink(self) -> WriteBackSink:
        return self._writeback

    def queue_len(self) -> int:
        return len(self._queue)

    # -- enqueue + tick ----------------------------------------------------

    def enqueue(self, envelope: Mapping[str, Any]) -> None:
        """Queue an envelope for submission.

        ``envelope`` must be a mapping with at least ``event_id`` and
        ``persona_id`` keys; the value is shallow-copied into a dict
        so the worker does not retain a reference to caller state.
        """

        if "event_id" not in envelope:
            raise SubmitWorkerError("envelope missing 'event_id'")
        if "persona_id" not in envelope:
            raise SubmitWorkerError("envelope missing 'persona_id'")
        self._queue.append(
            _QueuedEnvelope(
                envelope=dict(envelope),
                retry_count=0,
                next_eligible_at=0,
                last_error=None,
            )
        )

    def tick(self) -> SubmitResult:
        """Advance the FSM by one step.

        Eligibility uses ``Clock.now_secs()``. Order of evaluation per
        envelope:

        1. Token-bucket check → :class:`SubmitResultKind.THROTTLED`
           on refusal (no transport call, no retry-count change,
           envelope requeued at the front).
        2. Transport submission.
        3. Outcome dispatch:

           - ``ACCEPTED``  → writeback + ``SUCCESS``.
           - ``RETRIABLE`` → retry-count + 1; if budget exhausted,
             dead-letter + ``DEAD``; else requeue with full-jitter
             backoff + ``RETRYING``.
           - ``PERMANENT`` → dead-letter + ``DEAD`` (no retry-budget
             consumed).
        """

        now = self._clock.now_secs()

        idx: Optional[int] = None
        for i, e in enumerate(self._queue):
            if e.next_eligible_at <= now:
                idx = i
                break
        if idx is None:
            return SubmitResult.idle()

        # Pop the eligible entry. Use rotation to pop from arbitrary
        # index (deque has efficient O(1) popleft/popright; for
        # interior indices we accept O(k)).
        if idx == 0:
            entry = self._queue.popleft()
        else:
            self._queue.rotate(-idx)
            entry = self._queue.popleft()
            self._queue.rotate(idx)

        # Token-bucket gate (no side-effects on refusal).
        if not self._bucket.try_consume(now):
            event_id = str(entry.envelope.get("event_id", ""))
            self._queue.appendleft(entry)
            return SubmitResult.throttled(event_id)

        outcome = self._transport.submit(entry.envelope)
        event_id = str(entry.envelope.get("event_id", ""))

        if outcome.kind == TransportOutcomeKind.ACCEPTED:
            self._writeback.write_success(entry.envelope)
            return SubmitResult.success(event_id)

        if outcome.kind == TransportOutcomeKind.RETRIABLE:
            entry.retry_count += 1
            entry.last_error = outcome.error
            if entry.retry_count > self._config.max_retry:
                record = self._build_dead_letter_record(entry, outcome.error)
                self._dead_letter.record(record)
                return SubmitResult.dead(
                    event_id,
                    terminal_error=record.terminal_error,
                    attempt=entry.retry_count,
                )
            delay = self._backoff_for_attempt(entry.retry_count)
            entry.next_eligible_at = now + delay
            self._queue.append(entry)
            return SubmitResult.retrying(
                event_id,
                attempt=entry.retry_count,
                next_delay_secs=delay,
            )

        # PERMANENT.
        record = self._build_dead_letter_record(entry, outcome.error)
        self._dead_letter.record(record)
        return SubmitResult.dead(
            event_id,
            terminal_error=record.terminal_error,
            attempt=entry.retry_count,
        )

    # -- internals ---------------------------------------------------------

    def _backoff_for_attempt(self, attempt: int) -> int:
        """Full-jitter backoff: ``uniform[0, min(cap, base * 2^(attempt - 1))]``.

        Matches the Rust pendant's ``backoff_for_attempt``.
        """

        base = max(self._config.retry_base_delay_secs, 1)
        cap = self._config.retry_max_delay_secs
        shift = max(attempt - 1, 0)
        shift = min(shift, 63)
        exp = base * (1 << shift)
        upper = min(exp, max(cap, 1))
        drawn = self._rng.gen_range_secs(upper)
        return int(drawn)

    def _build_dead_letter_record(
        self, entry: _QueuedEnvelope, last_error: str
    ) -> DeadLetterRecord:
        now = self._clock.now_secs()
        return DeadLetterRecord(
            event_id=str(entry.envelope.get("event_id", "")),
            persona_id=str(entry.envelope.get("persona_id", "")),
            dead_letter_at=format_rfc3339_secs(now),
            terminal_error=last_error,
            retry_count=int(entry.retry_count),
        )


# ---------------------------------------------------------------------------
# Spec-invariant self-check (mirrors Rust assert_spec_invariants).
# ---------------------------------------------------------------------------


def assert_spec_invariants() -> None:
    """Raise :class:`SubmitWorkerError` on any cross-lang drift in
    the constants block. Module-import sentinel."""

    if DEFAULT_RATE_REQUESTS <= 0:
        raise SubmitWorkerError("DEFAULT_RATE_REQUESTS must be > 0")
    if DEFAULT_RATE_WINDOW_SECS <= 0:
        raise SubmitWorkerError("DEFAULT_RATE_WINDOW_SECS must be > 0")
    if DEFAULT_MAX_RETRY <= 0:
        raise SubmitWorkerError("DEFAULT_MAX_RETRY must be > 0")
    if DEFAULT_RETRY_BASE_DELAY_SECS <= 0:
        raise SubmitWorkerError("DEFAULT_RETRY_BASE_DELAY_SECS must be >= 1")
    if DEFAULT_RETRY_MAX_DELAY_SECS < DEFAULT_RETRY_BASE_DELAY_SECS:
        raise SubmitWorkerError(
            "DEFAULT_RETRY_MAX_DELAY_SECS must be >= DEFAULT_RETRY_BASE_DELAY_SECS"
        )
    if ENV_SUBMIT_RATE != "WAKIR_ANCHOR_SUBMIT_RATE":
        raise SubmitWorkerError(
            "ENV_SUBMIT_RATE drifted from Sprint-Auftrag-pinned value"
        )
    if ENV_MAX_RETRY != "WAKIR_ANCHOR_MAX_RETRY":
        raise SubmitWorkerError(
            "ENV_MAX_RETRY drifted from Sprint-Auftrag-pinned value"
        )
    if set(_VALID_KINDS) != {
        KIND_SUCCESS,
        KIND_THROTTLED,
        KIND_RETRYING,
        KIND_DEAD,
        KIND_IDLE,
    }:
        raise SubmitWorkerError("SubmitResultKind wire-set drifted")


# Drift sentinel at import time.
assert_spec_invariants()


__all__ = [
    "AnchorSubmitWorker",
    "Clock",
    "DEFAULT_MAX_RETRY",
    "DEFAULT_RATE_REQUESTS",
    "DEFAULT_RATE_WINDOW_SECS",
    "DEFAULT_RETRY_BASE_DELAY_SECS",
    "DEFAULT_RETRY_MAX_DELAY_SECS",
    "DECISION_RECORD_SCHEMA",
    "DeadLetterRecord",
    "DeadLetterStore",
    "DeterministicRng",
    "ENV_MAX_RETRY",
    "ENV_SUBMIT_RATE",
    "InMemoryDeadLetterStore",
    "KIND_DEAD",
    "KIND_IDLE",
    "KIND_RETRYING",
    "KIND_SUCCESS",
    "KIND_THROTTLED",
    "ManualClock",
    "NoopWriteBackSink",
    "RecordingWriteBackSink",
    "Rng",
    "ScriptedTransport",
    "SubmitResult",
    "SubmitResultKind",
    "SubmitTransport",
    "SubmitWorkerConfig",
    "SubmitWorkerError",
    "SystemClock",
    "TransportOutcome",
    "TransportOutcomeKind",
    "WriteBackSink",
    "assert_spec_invariants",
    "decision_record_hash",
    "format_rfc3339_secs",
    "serialize_decision_record",
    "sha256_hex",
]
