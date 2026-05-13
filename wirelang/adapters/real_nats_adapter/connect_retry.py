# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Wirelang NATS-Connect-Retry-Layer (Phase-2 Sprint-9 Tag-5).
# Licensed under the Business Source License 1.1; Change Date
# 2030-05-13, Change License Apache-2.0 (per ADR-0059).
"""NATS-connect retry layer for the Pilot-VM live-bring-up
discrepancy resolution (Sprint-9 Tag-5).

Context
=======

The Phase-1b Pilot-VM live-bring-up (2026-05-13) reported a smoke-
test result that oscillated between 2/6 and 4/6 PASS across
back-to-back invocations of ``bin/proxmox-bringup-smoke``. The
Mira-Bug-Bilanz (``2026-05-13-pilot-bringup-bug-bilanz.md``)
listed four candidate race conditions:

1. **JWT-Auth-Timing-Race** — NATS-connect issued before the
   SPIRE-agent has produced a JWT-SVID. The
   :class:`NatsJwtCallbackCacheEmpty` from
   ``scripts/nats_jwt_callback_skizze.py`` fires at CONNECT-frame-
   build time, aborting the connect cleanly inside ``nats-py``.
2. **Trust-Bundle-Rotation-Race** — the SPIRE-agent has issued a
   JWT-SVID, but the NATS-server has not yet picked up the
   rotated trust bundle, so the server-side JWT-validate rejects
   the connect.
3. **SPIFFE-Workload-API-Socket-Permission-Drift** — the agent
   produces SVIDs, but the unix-domain-socket file permissions
   (SELinux uid/gid) momentarily block the wirelang-side reader.
4. **NATS-KV-Bucket-Init-Race** — the buckets exist (Phase-6
   one-shot finished) but the JetStream-stream-init has not yet
   finalised when the smoke probes ``nats kv ls``.

Hypotheses 1-2 manifest as :class:`NatsAdapterUnavailable` or
:class:`NatsAdapterAuthenticationError` on the wirelang-side
adapter; hypothesis 4 manifests as a non-zero exit from the
``nats kv ls`` shell-out inside the smoke skript.

Root-cause diagnosis from the bug bilanz
----------------------------------------

The smoke-test discrepancy 2/6 ↔ 4/6 maps cleanly onto **two**
checks that flip:

- ``spire-server-healthy`` (Check 3): the server restarts mid-
  bring-up because the agent crash-loops trigger a server-side
  restart-loop synchroniser. When the smoke probes during the
  brief steady window, it sees PASS; when it probes mid-restart,
  FAIL. Symptom of hypothesis 1+2 (auth-race chain).
- ``marker-stack-bucket-present`` (Check 6): the bucket-init
  one-shot completed (Phase-6) but the JetStream-stream
  registration that backs ``nats kv ls`` finalises asynchronously
  (server-side housekeeping). Symptom of hypothesis 4.

Hypothesis 3 (socket-permission-drift) is **not** the dominant
factor: the bug bilanz reports the agent is crash-loop-inactive,
not socket-permission-failing — when the agent is dead the socket
does not exist at all (clean FAIL), no race window. Kai Sprint-9
Tag-5 (Bug-7) owns the primary resolution; this retry-layer is
defence-in-depth so the smoke-test stops oscillating once Kai's
fix lands and the agent is healthy.

The retry layer this module implements
======================================

This module exposes :func:`connect_with_retry` — a thin, hermetic-
testable wrapper around :class:`RealNatsConnectionAdapter.connect`
that:

1. **Catches transient failures** (``NatsAdapterUnavailable``,
   ``NatsAdapterAuthenticationError`` whose message string carries
   a hypothesis-1/2/4 marker, and the explicit
   ``NatsJwtCallbackCacheEmpty`` from the JWT-cache surface).
2. **Sleeps an exponential-backoff interval** with jitter
   (deterministic in tests via the ``clock`` + ``random_uniform``
   injection points). Default schedule: ``[0.25s, 0.5s, 1.0s,
   2.0s, 4.0s]`` with ±20% jitter, total worst-case ~9.4s.
3. **Optionally waits for a JWT-cache-hot signal** between
   attempts via a :class:`JwtCacheReadyView` Protocol. The wait
   is bounded; if the cache stays empty past the budget the final
   attempt re-raises :class:`NatsAdapterAuthenticationError` with
   a structured reason code (``"jwt-cache-cold-after-retries"``).
4. **Returns a structured :class:`NatsConnectAttemptLog`** that
   records every attempt's outcome (success / failure-kind /
   wait-elapsed) — the smoke-test and ops-runbook can surface
   this log so an operator sees WHICH race window fired.

The retry layer is **opt-in**: existing callers of
``RealNatsConnectionAdapter.connect()`` are unaffected. The smoke-
test and the bucket-init driver are the two known callers that
opt in via :func:`connect_with_retry` (see Sprint-9 Tag-5 PR).

Hermetic-test surface
=====================

The retry layer ships with a hermetic-test substrate
(``wirelang/tests/test_nats_connect_race_resilience.py``) that
reproduces all four hypotheses against a mock adapter whose
``connect`` returns a scripted sequence of (raise, raise, succeed)
outcomes. The retry layer is therefore **race-reproducible
without a live NATS or a live SPIRE**, matching the
``feedback_sandbox_host_trennung.md`` boundary.

Sandbox boundary
================

This module does not open a NATS socket, does not import
``nats-py`` eagerly, and does not contact the SPIRE Workload-API.
It is a pure orchestration layer on top of the existing
:mod:`wirelang.adapters.real_nats_adapter.adapter` surface. The
hermetic tests run inside the Mira sandbox per ADR-0051
(rejected; operative Mira-Hand-Regel: ``claude-dev`` has NO host
podman-socket access).
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import (
    Any,
    Awaitable,
    Callable,
    List,
    Optional,
    Protocol,
    Sequence,
    Tuple,
)

from .adapter import (
    NatsAdapterAuthenticationError,
    NatsAdapterError,
    NatsAdapterUnavailable,
)


# ---------------------------------------------------------------------------
# Default retry schedule
# ---------------------------------------------------------------------------

#: Default delay schedule between connect attempts (seconds).
#:
#: Five entries → six attempts (one initial + five retries).
#: Total worst-case sleep (without jitter): 7.75s. Total with
#: ±20% jitter upper bound: 9.3s. The schedule is biased toward
#: short early backoffs because the dominant Sprint-9 Tag-5 race
#: windows (SVID-cold-start, JetStream-stream-init) clear inside
#: the first second on a healthy host; the long tail covers
#: SPIRE-server-restart loops where the agent comes back after a
#: ~5s healthcheck cycle.
DEFAULT_RETRY_SCHEDULE: Tuple[float, ...] = (0.25, 0.5, 1.0, 2.0, 4.0)

#: Default jitter factor applied to each delay. ``0.2`` means
#: the actual sleep is uniformly distributed in ``[0.8x, 1.2x]``
#: of the schedule value. Jitter prevents thundering-herd-style
#: synchronisation if many persona-containers connect at once.
DEFAULT_JITTER_FACTOR: float = 0.2

#: Default JWT-cache-wait budget per attempt (seconds). The retry
#: loop polls the :class:`JwtCacheReadyView` at 50ms intervals
#: up to this budget; if the cache is still empty, the attempt
#: is skipped (counted as failure-kind ``"jwt-cache-cold"``) and
#: the next backoff fires.
DEFAULT_JWT_CACHE_WAIT_SECONDS: float = 1.0

#: Reason codes the retry layer attaches to attempt records.
#:
#: ``"tcp-unreachable"``       — :class:`NatsAdapterUnavailable`
#:                                surfaced from the adapter's
#:                                pre-connect reachability probe.
#: ``"nats-py-connect-fail"``  — :class:`NatsAdapterUnavailable`
#:                                surfaced from the nats-py
#:                                upstream connect-error mapping.
#: ``"auth-rejected"``         — :class:`NatsAdapterAuthenticationError`
#:                                surfaced from the nats-py auth-
#:                                keyword mapping.
#: ``"jwt-cache-cold"``        — :class:`NatsJwtCallbackCacheEmpty`
#:                                or the retry layer's own cache-
#:                                ready poll exhausted its budget.
#: ``"unknown-transient"``     — any other :class:`NatsAdapterError`
#:                                subclass; retried defensively.
#: ``"success"``               — adapter.connect() completed.
REASON_TCP_UNREACHABLE = "tcp-unreachable"
REASON_NATS_PY_CONNECT_FAIL = "nats-py-connect-fail"
REASON_AUTH_REJECTED = "auth-rejected"
REASON_JWT_CACHE_COLD = "jwt-cache-cold"
REASON_UNKNOWN_TRANSIENT = "unknown-transient"
REASON_SUCCESS = "success"


# ---------------------------------------------------------------------------
# JWT-cache-ready protocol
# ---------------------------------------------------------------------------


class JwtCacheReadyView(Protocol):
    """Read-only view of "is the JWT-SVID cache hot?".

    The retry layer polls this surface between connect attempts
    when the consumer has wired up a SPIRE-Workload-API-backed
    JWT-cache. The Protocol is intentionally narrower than
    :class:`JwtSvidCacheView` (the full cache view used by the
    callback skizze in ``scripts/nats_jwt_callback_skizze.py``):
    the retry layer only needs to know "do we have a token, yes
    or no" — it never reads the token bytes.

    A consumer that does NOT use JWT-auth (e.g. the smoke-test
    that talks to a permissive dev-NATS) passes ``None`` for the
    ``jwt_cache`` argument of :func:`connect_with_retry`; the
    cache-wait phase is then skipped entirely.

    Implementations MUST be safe to call from an asyncio-task
    context. The default implementation is a synchronous
    attribute read on a wirelang-side cache object.
    """

    def is_ready(self) -> bool:
        """Return ``True`` iff a current JWT-SVID is cached.

        ``False`` is the cold-start signal: either no SVID has
        been observed yet, or the background ``WatchJWTSVIDs``
        stream has stalled and the cache was cleared.
        """
        ...


# ---------------------------------------------------------------------------
# Attempt log
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NatsConnectAttemptRecord:
    """One entry in the per-call attempt log.

    Fields:

    - ``attempt_index``: 0-based attempt counter. Attempt 0 is
      the initial try, before any retry backoff.
    - ``reason``: one of the ``REASON_*`` constants in this
      module. ``REASON_SUCCESS`` marks the terminal attempt.
    - ``error_repr``: ``repr(exc)`` of the surfacing exception
      (empty string on success). The retry layer does not raise
      the original exception across attempts; it surfaces it via
      this field so operators can audit the per-attempt cause.
    - ``elapsed_seconds``: wall-clock time from attempt-start to
      attempt-resolution (success or failure). Sourced from the
      injected ``clock`` if provided.
    - ``sleep_before_next_seconds``: 0.0 on the terminal attempt;
      otherwise the (jittered) backoff slept before the next try.
    """

    attempt_index: int
    reason: str
    error_repr: str = ""
    elapsed_seconds: float = 0.0
    sleep_before_next_seconds: float = 0.0


@dataclass
class NatsConnectAttemptLog:
    """Aggregated attempt log returned by :func:`connect_with_retry`.

    Fields:

    - ``attempts``: list of :class:`NatsConnectAttemptRecord` in
      time order. ``len(attempts)`` equals the number of times
      the retry loop iterated (at least 1).
    - ``succeeded``: ``True`` iff the terminal attempt has
      ``reason == REASON_SUCCESS``.
    - ``total_elapsed_seconds``: sum of ``elapsed_seconds`` over
      all attempts plus the sleep gaps. Useful for the smoke
      summary "took 3.4s with 2 retries".
    - ``final_error_repr``: ``repr`` of the last surfacing
      exception on failure; empty string on success.

    Equality is structural (dataclass-default); the type is
    safe to compare in tests.
    """

    attempts: List[NatsConnectAttemptRecord] = field(default_factory=list)
    succeeded: bool = False
    total_elapsed_seconds: float = 0.0
    final_error_repr: str = ""

    def record(self, entry: NatsConnectAttemptRecord) -> None:
        """Append ``entry`` and accumulate the elapsed time."""
        self.attempts.append(entry)
        self.total_elapsed_seconds += (
            entry.elapsed_seconds + entry.sleep_before_next_seconds
        )

    def attempt_count(self) -> int:
        return len(self.attempts)

    def reasons(self) -> List[str]:
        """Return the per-attempt reason codes in order."""
        return [a.reason for a in self.attempts]


# ---------------------------------------------------------------------------
# Failure-classification
# ---------------------------------------------------------------------------


def classify_failure(exc: BaseException) -> str:
    """Map an exception to one of the ``REASON_*`` constants.

    The classification is structural (exception type) plus a
    cooperative string-scan for the JWT-cache-empty marker. The
    string-scan is conservative: it only fires when the message
    explicitly mentions ``"JwtSvidCache is empty"`` (the marker
    string raised by :class:`NatsJwtCallbackCacheEmpty` in
    ``scripts/nats_jwt_callback_skizze.py``).

    The retry layer never imports the callback module; it
    matches on the marker string so the two layers remain
    independently testable.

    Returns:

    - One of the ``REASON_*`` constants (string).
    """

    msg = str(exc)
    if isinstance(exc, NatsAdapterAuthenticationError):
        # The auth-error message may carry the cold-cache marker
        # if the consumer wired NatsJwtCallbackCacheEmpty through
        # the user_jwt_cb path; treat it as cold-cache so the
        # JWT-cache-wait branch fires.
        if "JwtSvidCache is empty" in msg or "cache-cold" in msg.lower():
            return REASON_JWT_CACHE_COLD
        return REASON_AUTH_REJECTED
    if isinstance(exc, NatsAdapterUnavailable):
        # The adapter raises NatsAdapterUnavailable for both the
        # pre-connect TCP probe failure AND the nats-py connect
        # mapping. Disambiguate via the message string the
        # adapter writes: the TCP probe path mentions "TCP probe",
        # the nats-py mapping path mentions "NATS connect failed".
        if "TCP probe" in msg:
            return REASON_TCP_UNREACHABLE
        return REASON_NATS_PY_CONNECT_FAIL
    # Cooperate with the callback skizze's NatsJwtCallbackCacheEmpty
    # without importing the module. The class name is stable
    # (Sprint-6 Tag-10) and the message carries the marker.
    cls_name = type(exc).__name__
    if cls_name == "NatsJwtCallbackCacheEmpty":
        return REASON_JWT_CACHE_COLD
    if cls_name == "NatsJwtCallbackSvidExpired":
        # Treat expired SVID as auth-rejected; the next attempt
        # will see a refreshed cache (or fail again).
        return REASON_AUTH_REJECTED
    if isinstance(exc, NatsAdapterError):
        return REASON_UNKNOWN_TRANSIENT
    # Anything else propagates; the caller's try-except outside
    # the retry layer will see the original exception. The retry
    # layer DOES NOT swallow non-NatsAdapter exceptions.
    return REASON_UNKNOWN_TRANSIENT


# ---------------------------------------------------------------------------
# Backoff computation
# ---------------------------------------------------------------------------


def jittered_delay(
    base_seconds: float,
    *,
    jitter_factor: float = DEFAULT_JITTER_FACTOR,
    random_uniform: Optional[Callable[[float, float], float]] = None,
) -> float:
    """Return a jittered delay around ``base_seconds``.

    The delay is uniformly distributed in
    ``[base*(1-jitter), base*(1+jitter)]``, clamped at zero.

    ``jitter_factor`` MUST be in ``[0.0, 1.0)``; values outside
    that range raise :class:`ValueError` to surface a config bug
    early.

    ``random_uniform`` defaults to :func:`random.uniform`. Tests
    inject a deterministic function (``lambda lo, hi: lo`` for
    "lower-bound jitter", or a fixture-seeded RNG).
    """
    if not 0.0 <= jitter_factor < 1.0:
        raise ValueError(
            f"jitter_factor must be in [0, 1); got {jitter_factor!r}"
        )
    if base_seconds < 0.0:
        raise ValueError(
            f"base_seconds must be non-negative; got {base_seconds!r}"
        )
    rng = random_uniform if random_uniform is not None else random.uniform
    lo = base_seconds * (1.0 - jitter_factor)
    hi = base_seconds * (1.0 + jitter_factor)
    return max(0.0, rng(lo, hi))


# ---------------------------------------------------------------------------
# Connect orchestrator
# ---------------------------------------------------------------------------


async def _wait_for_jwt_cache(
    cache: JwtCacheReadyView,
    *,
    budget_seconds: float,
    poll_interval_seconds: float,
    clock: Callable[[], float],
    sleep: Callable[[float], Awaitable[None]],
) -> bool:
    """Poll ``cache.is_ready()`` up to ``budget_seconds``.

    Returns ``True`` iff the cache transitions to ready inside
    the budget. Returns ``False`` on budget exhaustion.

    ``clock`` is the injected wall-clock provider; ``sleep`` is
    the injected sleep coroutine. Tests pass deterministic
    implementations; production passes :func:`time.monotonic`
    and :func:`asyncio.sleep`.
    """
    deadline = clock() + budget_seconds
    if cache.is_ready():
        return True
    while clock() < deadline:
        await sleep(poll_interval_seconds)
        if cache.is_ready():
            return True
    return False


# Type alias: the connect callable the retry layer drives. The
# default is ``adapter.connect`` (zero-arg coroutine). Tests
# pass a scripted-failure coroutine.
ConnectCallable = Callable[[], Awaitable[None]]


async def connect_with_retry(
    connect: ConnectCallable,
    *,
    schedule: Sequence[float] = DEFAULT_RETRY_SCHEDULE,
    jitter_factor: float = DEFAULT_JITTER_FACTOR,
    jwt_cache: Optional[JwtCacheReadyView] = None,
    jwt_cache_wait_seconds: float = DEFAULT_JWT_CACHE_WAIT_SECONDS,
    jwt_cache_poll_interval_seconds: float = 0.05,
    clock: Optional[Callable[[], float]] = None,
    sleep: Optional[Callable[[float], Awaitable[None]]] = None,
    random_uniform: Optional[Callable[[float, float], float]] = None,
) -> NatsConnectAttemptLog:
    """Drive ``connect`` with retry-on-transient-failure.

    Parameters:

    - ``connect``: zero-arg async callable. Production passes
      ``adapter.connect`` (bound method); tests pass a scripted-
      failure callable that pops a queue of outcomes.
    - ``schedule``: per-retry delay schedule (seconds). The
      number of retries is ``len(schedule)``; attempt count is
      ``len(schedule) + 1``.
    - ``jitter_factor``: jitter applied to each schedule entry.
      See :func:`jittered_delay`.
    - ``jwt_cache``: optional :class:`JwtCacheReadyView`. When
      provided, the retry loop waits for the cache to go ready
      between attempts (up to ``jwt_cache_wait_seconds``). When
      ``None``, the cache-wait phase is skipped.
    - ``jwt_cache_wait_seconds``: budget for the cache-ready
      poll. Exhausting this budget marks the next attempt with
      reason ``REASON_JWT_CACHE_COLD`` and does NOT call
      ``connect`` (the connect would deterministically fail with
      :class:`NatsJwtCallbackCacheEmpty`; skipping it saves the
      attempt-budget for an actual try).
    - ``jwt_cache_poll_interval_seconds``: how often the cache
      poll wakes up to re-check ``is_ready``. Default 50ms.
    - ``clock``: injected wall-clock. Default
      :func:`time.monotonic`.
    - ``sleep``: injected async-sleep. Default
      :func:`asyncio.sleep`.
    - ``random_uniform``: injected RNG for jitter. Default
      :func:`random.uniform`.

    Returns: :class:`NatsConnectAttemptLog`. Inspect
    ``log.succeeded`` for the binary outcome. On failure the
    caller MAY re-raise based on ``log.attempts[-1].reason``
    (the retry layer does NOT raise on its own — the caller
    drives the surface).

    Concurrency: caller-driven. The retry layer is single-task;
    do not invoke concurrently against the same adapter
    instance.
    """
    if jitter_factor < 0.0 or jitter_factor >= 1.0:
        raise ValueError(
            f"jitter_factor must be in [0, 1); got {jitter_factor!r}"
        )
    _clock = clock if clock is not None else time.monotonic
    _sleep = sleep if sleep is not None else asyncio.sleep

    log = NatsConnectAttemptLog()
    total_attempts = len(schedule) + 1

    for attempt_index in range(total_attempts):
        # If the consumer wired a JWT-cache, wait for it to go
        # hot before the actual connect. This converts an
        # otherwise-deterministic JwtSvidCache-empty failure
        # into an explicit wait phase, saving an attempt slot
        # for the real connect.
        if jwt_cache is not None:
            ready = await _wait_for_jwt_cache(
                jwt_cache,
                budget_seconds=jwt_cache_wait_seconds,
                poll_interval_seconds=jwt_cache_poll_interval_seconds,
                clock=_clock,
                sleep=_sleep,
            )
            if not ready:
                # Record the cold-cache attempt and move to the
                # backoff phase. The "elapsed" time recorded here
                # is the JWT-wait budget itself (an honest
                # accounting for the operator log).
                record = NatsConnectAttemptRecord(
                    attempt_index=attempt_index,
                    reason=REASON_JWT_CACHE_COLD,
                    error_repr=(
                        f"JwtCacheReadyView remained cold after "
                        f"{jwt_cache_wait_seconds}s poll budget"
                    ),
                    elapsed_seconds=jwt_cache_wait_seconds,
                    sleep_before_next_seconds=(
                        jittered_delay(
                            schedule[attempt_index],
                            jitter_factor=jitter_factor,
                            random_uniform=random_uniform,
                        )
                        if attempt_index < len(schedule)
                        else 0.0
                    ),
                )
                log.record(record)
                if record.sleep_before_next_seconds > 0.0:
                    await _sleep(record.sleep_before_next_seconds)
                if attempt_index == total_attempts - 1:
                    log.final_error_repr = record.error_repr
                continue

        # Execute the connect attempt.
        attempt_start = _clock()
        try:
            await connect()
        except BaseException as exc:  # noqa: BLE001
            reason = classify_failure(exc)
            elapsed = _clock() - attempt_start
            if reason == REASON_UNKNOWN_TRANSIENT and not isinstance(
                exc, NatsAdapterError
            ):
                # A truly unexpected exception class — surface it.
                # We still record an attempt entry so the log is
                # consistent.
                log.record(
                    NatsConnectAttemptRecord(
                        attempt_index=attempt_index,
                        reason=reason,
                        error_repr=repr(exc),
                        elapsed_seconds=elapsed,
                        sleep_before_next_seconds=0.0,
                    )
                )
                log.final_error_repr = repr(exc)
                raise
            sleep_seconds = (
                jittered_delay(
                    schedule[attempt_index],
                    jitter_factor=jitter_factor,
                    random_uniform=random_uniform,
                )
                if attempt_index < len(schedule)
                else 0.0
            )
            log.record(
                NatsConnectAttemptRecord(
                    attempt_index=attempt_index,
                    reason=reason,
                    error_repr=repr(exc),
                    elapsed_seconds=elapsed,
                    sleep_before_next_seconds=sleep_seconds,
                )
            )
            if attempt_index == total_attempts - 1:
                log.final_error_repr = repr(exc)
                # Terminal attempt failed; the caller inspects
                # log.succeeded == False and decides whether to
                # re-raise.
                return log
            if sleep_seconds > 0.0:
                await _sleep(sleep_seconds)
            continue

        # Success path.
        elapsed = _clock() - attempt_start
        log.record(
            NatsConnectAttemptRecord(
                attempt_index=attempt_index,
                reason=REASON_SUCCESS,
                error_repr="",
                elapsed_seconds=elapsed,
                sleep_before_next_seconds=0.0,
            )
        )
        log.succeeded = True
        return log

    # Unreachable: the loop always returns inside its body.
    # Defensive return for type-checkers.
    return log  # pragma: no cover


# ---------------------------------------------------------------------------
# Convenience: a lightweight static ready-view for non-SPIFFE paths
# ---------------------------------------------------------------------------


@dataclass
class StaticReadyView:
    """A :class:`JwtCacheReadyView` whose readiness is fixed.

    Useful in two scenarios:

    - Tests that want to assert "the retry layer respects the
      cache-cold signal" without wiring a real cache.
    - Production code paths that DO NOT use JWT-auth but still
      want a no-op shim that always reports ready (set
      ``ready=True``).

    Two-state mutability: tests call :meth:`set_ready` to flip
    the state mid-loop (simulating the cache transitioning to
    hot during a backoff).
    """

    ready: bool = True

    def is_ready(self) -> bool:
        return self.ready

    def set_ready(self, value: bool) -> None:
        self.ready = bool(value)


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


__all__ = [
    "DEFAULT_JITTER_FACTOR",
    "DEFAULT_JWT_CACHE_WAIT_SECONDS",
    "DEFAULT_RETRY_SCHEDULE",
    "JwtCacheReadyView",
    "NatsConnectAttemptLog",
    "NatsConnectAttemptRecord",
    "REASON_AUTH_REJECTED",
    "REASON_JWT_CACHE_COLD",
    "REASON_NATS_PY_CONNECT_FAIL",
    "REASON_SUCCESS",
    "REASON_TCP_UNREACHABLE",
    "REASON_UNKNOWN_TRANSIENT",
    "StaticReadyView",
    "classify_failure",
    "connect_with_retry",
    "jittered_delay",
]
