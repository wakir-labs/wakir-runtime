# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Hermetic Race-Reproduction Tests for the Sprint-9 Tag-5
# NATS-Connect-Retry-Layer.
"""Hermetic race-reproduction tests for the Sprint-9 Tag-5 retry layer.

The Pilot-VM smoke discrepancy (2/6 ↔ 4/6) was driven by four
candidate race conditions (Mira-Bug-Bilanz 2026-05-13). Each
test below reproduces ONE hypothesis against a mock adapter that
emits a scripted sequence of (raise, raise, succeed) outcomes,
asserting:

1. The retry layer classifies the failure correctly.
2. The retry layer succeeds within the schedule when the race
   window clears.
3. The retry layer surfaces a structured attempt log so an
   operator can audit which window fired.

These tests are **race-reproducible without a live NATS or a
live SPIRE** — the scripted-failure mock drives the retry layer
through every transition deterministically.

The test style follows the existing
:mod:`wirelang.tests.test_real_nats_adapter_mirror` convention:
synchronous ``def test_*`` wrappers around an ``asyncio.run``-
driven coroutine body. The repo does not depend on
``pytest-asyncio``.
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

import pytest

from wirelang.adapters.real_nats_adapter.adapter import (
    NatsAdapterAuthenticationError,
    NatsAdapterError,
    NatsAdapterUnavailable,
)
from wirelang.adapters.real_nats_adapter.connect_retry import (
    DEFAULT_RETRY_SCHEDULE,
    NatsConnectAttemptLog,
    NatsConnectAttemptRecord,
    REASON_AUTH_REJECTED,
    REASON_JWT_CACHE_COLD,
    REASON_NATS_PY_CONNECT_FAIL,
    REASON_SUCCESS,
    REASON_TCP_UNREACHABLE,
    REASON_UNKNOWN_TRANSIENT,
    StaticReadyView,
    classify_failure,
    connect_with_retry,
    jittered_delay,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _FakeClock:
    """Deterministic monotonic-clock substitute.

    Advances on every read by ``tick_seconds``. Tests can also
    call :meth:`advance` to skip large gaps without polling.
    """

    def __init__(self, *, start: float = 0.0, tick_seconds: float = 0.0):
        self._now = start
        self._tick = tick_seconds

    def __call__(self) -> float:
        out = self._now
        self._now += self._tick
        return out

    def advance(self, seconds: float) -> None:
        self._now += seconds


class _FakeSleep:
    """Async-sleep substitute that records the requested gaps.

    Does not actually sleep; cooperates with the test's clock
    by advancing it (when bound to one).
    """

    def __init__(self, clock: Optional[_FakeClock] = None):
        self.gaps: List[float] = []
        self._clock = clock

    async def __call__(self, seconds: float) -> None:
        self.gaps.append(seconds)
        if self._clock is not None:
            self._clock.advance(seconds)


def _no_jitter(lo: float, hi: float) -> float:
    """Deterministic RNG substitute: always return the lower bound."""
    return lo


def _scripted_connect(outcomes: List[Optional[BaseException]]):
    """Build a connect coroutine that pops ``outcomes`` per call.

    ``None`` outcomes mean "succeed". Exception outcomes are
    raised.
    """
    pending = list(outcomes)

    async def connect() -> None:
        if not pending:
            raise AssertionError(
                "scripted connect: no more outcomes; test pushed too "
                "few entries onto the queue"
            )
        next_outcome = pending.pop(0)
        if next_outcome is not None:
            raise next_outcome

    return connect


# ---------------------------------------------------------------------------
# Hypothesis 1 — JWT-Auth-Timing-Race
# ---------------------------------------------------------------------------


class _CacheReadyAfterPolls:
    """JwtCacheReadyView that flips to ready after N polls.

    Emulates the SPIRE-Agent-SVID-Issuance race: the cache is
    cold for the first ``cold_polls`` invocations of
    :meth:`is_ready`, then transitions to hot.
    """

    def __init__(self, *, cold_polls: int):
        self._remaining_cold = cold_polls

    def is_ready(self) -> bool:
        if self._remaining_cold > 0:
            self._remaining_cold -= 1
            return False
        return True


def test_hypothesis_1_jwt_cache_cold_then_hot_resolves_inside_schedule():
    """Hypothesis 1: SVID cold at start; hot before the schedule exhausts.

    Models the SPIRE-Agent crash-loop scenario where the agent
    eventually stabilises and the cache hot-loads. The retry
    layer waits, then connects successfully on the SAME attempt
    once the cache goes hot.
    """

    async def _drive():
        cache = _CacheReadyAfterPolls(cold_polls=2)
        clock = _FakeClock(tick_seconds=0.0)
        sleep = _FakeSleep(clock=clock)

        connect = _scripted_connect([None])  # one success scheduled
        log = await connect_with_retry(
            connect,
            schedule=(0.1, 0.2, 0.4),
            jwt_cache=cache,
            jwt_cache_wait_seconds=1.0,
            jwt_cache_poll_interval_seconds=0.05,
            clock=clock,
            sleep=sleep,
            random_uniform=_no_jitter,
        )
        assert log.succeeded is True, log
        # The connect attempt itself succeeded after the cache
        # cleared, so we see exactly one attempt record with
        # REASON_SUCCESS.
        assert log.attempts[-1].reason == REASON_SUCCESS

    asyncio.run(_drive())


def test_hypothesis_1_jwt_cache_stays_cold_exhausts_budget():
    """Hypothesis 1, worst case: SPIRE-Agent never recovers.

    The cache stays cold past the full retry schedule. The retry
    layer records every attempt as ``REASON_JWT_CACHE_COLD`` and
    reports failure.
    """

    async def _drive():
        cache = _CacheReadyAfterPolls(cold_polls=999)
        clock = _FakeClock(tick_seconds=0.0)
        sleep = _FakeSleep(clock=clock)

        connect = _scripted_connect([])  # connect should never run
        log = await connect_with_retry(
            connect,
            schedule=(0.05, 0.05),  # 3 attempts total
            jwt_cache=cache,
            jwt_cache_wait_seconds=0.2,
            jwt_cache_poll_interval_seconds=0.05,
            clock=clock,
            sleep=sleep,
            random_uniform=_no_jitter,
        )
        assert log.succeeded is False
        assert log.attempt_count() == 3
        assert all(r == REASON_JWT_CACHE_COLD for r in log.reasons())

    asyncio.run(_drive())


# ---------------------------------------------------------------------------
# Hypothesis 2 — Trust-Bundle-Rotation-Race
# ---------------------------------------------------------------------------


def test_hypothesis_2_auth_rejected_then_accepted():
    """Hypothesis 2: NATS-server rejects auth twice, then accepts.

    Models the trust-bundle-rotation race: SVID is present but
    the server's bundle lags. The third attempt succeeds.
    """

    async def _drive():
        clock = _FakeClock(tick_seconds=0.0)
        sleep = _FakeSleep(clock=clock)
        connect = _scripted_connect(
            [
                NatsAdapterAuthenticationError(
                    "NATS auth rejected — invalid JWT signature"
                ),
                NatsAdapterAuthenticationError(
                    "NATS auth rejected — bundle rotation in progress"
                ),
                None,
            ]
        )
        log = await connect_with_retry(
            connect,
            schedule=(0.05, 0.05, 0.05),
            clock=clock,
            sleep=sleep,
            random_uniform=_no_jitter,
        )
        assert log.succeeded is True
        assert [a.reason for a in log.attempts] == [
            REASON_AUTH_REJECTED,
            REASON_AUTH_REJECTED,
            REASON_SUCCESS,
        ]

    asyncio.run(_drive())


def test_hypothesis_2_auth_persistently_rejected_terminates():
    """Hypothesis 2, terminal: auth is wrong forever.

    The retry layer exhausts the schedule and reports failure
    with ``final_error_repr`` carrying the last exception.
    """

    async def _drive():
        clock = _FakeClock(tick_seconds=0.0)
        sleep = _FakeSleep(clock=clock)
        connect = _scripted_connect(
            [NatsAdapterAuthenticationError("perma-fail")] * 4
        )
        log = await connect_with_retry(
            connect,
            schedule=(0.05, 0.05, 0.05),  # 4 attempts total
            clock=clock,
            sleep=sleep,
            random_uniform=_no_jitter,
        )
        assert log.succeeded is False
        assert log.attempt_count() == 4
        assert all(r == REASON_AUTH_REJECTED for r in log.reasons())
        assert "perma-fail" in log.final_error_repr

    asyncio.run(_drive())


# ---------------------------------------------------------------------------
# Hypothesis 4 — NATS-KV-Bucket-Init-Race
# ---------------------------------------------------------------------------


def test_hypothesis_4_tcp_unreachable_then_reachable():
    """Hypothesis 4 surface: TCP-probe fails twice, then succeeds.

    Models the NATS-server-coming-up race where the systemd unit
    is "active" but the listener has not yet bound. The retry
    layer catches the ``TCP probe`` ``NatsAdapterUnavailable``
    and classifies it as ``REASON_TCP_UNREACHABLE``.
    """

    async def _drive():
        clock = _FakeClock(tick_seconds=0.0)
        sleep = _FakeSleep(clock=clock)
        connect = _scripted_connect(
            [
                NatsAdapterUnavailable(
                    "TCP probe of nats://127.0.0.1:4222 failed"
                ),
                NatsAdapterUnavailable(
                    "TCP probe of nats://127.0.0.1:4222 failed"
                ),
                None,
            ]
        )
        log = await connect_with_retry(
            connect,
            schedule=(0.05, 0.05, 0.05),
            clock=clock,
            sleep=sleep,
            random_uniform=_no_jitter,
        )
        assert log.succeeded is True
        assert [a.reason for a in log.attempts] == [
            REASON_TCP_UNREACHABLE,
            REASON_TCP_UNREACHABLE,
            REASON_SUCCESS,
        ]

    asyncio.run(_drive())


def test_hypothesis_4_nats_py_connect_fail_distinct_from_tcp():
    """Hypothesis 4 sibling: nats-py connect fails (not TCP probe).

    Distinct reason code so the operator log differentiates
    between "the TCP socket didn't accept" (pre-handshake) and
    "the NATS handshake itself failed" (post-handshake, e.g.
    JetStream-stream-init race).
    """

    async def _drive():
        clock = _FakeClock(tick_seconds=0.0)
        sleep = _FakeSleep(clock=clock)
        connect = _scripted_connect(
            [
                NatsAdapterUnavailable(
                    "NATS connect failed — stream registration pending"
                ),
                None,
            ]
        )
        log = await connect_with_retry(
            connect,
            schedule=(0.05, 0.05),
            clock=clock,
            sleep=sleep,
            random_uniform=_no_jitter,
        )
        assert log.succeeded is True
        assert log.attempts[0].reason == REASON_NATS_PY_CONNECT_FAIL

    asyncio.run(_drive())


# ---------------------------------------------------------------------------
# Mixed-hypotheses sequencing (the actual Pilot-VM bug bilanz pattern)
# ---------------------------------------------------------------------------


def test_mixed_sequence_tcp_then_auth_then_success():
    """Realistic Pilot-VM sequence: substrate boots, then auth lags,
    then everything stabilises.

    Mirrors the smoke 2/6 → 4/6 transition where the NATS server
    is up (TCP-reachable) but the SPIRE chain takes one more
    cycle. The retry layer connects on attempt 3.
    """

    async def _drive():
        clock = _FakeClock(tick_seconds=0.0)
        sleep = _FakeSleep(clock=clock)
        connect = _scripted_connect(
            [
                NatsAdapterUnavailable(
                    "TCP probe of nats://127.0.0.1:4222 failed"
                ),
                NatsAdapterAuthenticationError(
                    "NATS auth rejected — JWT validation pending"
                ),
                None,
            ]
        )
        log = await connect_with_retry(
            connect,
            schedule=DEFAULT_RETRY_SCHEDULE,
            clock=clock,
            sleep=sleep,
            random_uniform=_no_jitter,
        )
        assert log.succeeded is True
        assert [a.reason for a in log.attempts] == [
            REASON_TCP_UNREACHABLE,
            REASON_AUTH_REJECTED,
            REASON_SUCCESS,
        ]
        # The operator-log reasons surface the actual race window.
        assert log.attempts[0].error_repr.startswith(
            "NatsAdapterUnavailable"
        )
        assert log.attempts[1].error_repr.startswith(
            "NatsAdapterAuthenticationError"
        )

    asyncio.run(_drive())


# ---------------------------------------------------------------------------
# Cooperative classifier (no import-coupling with the callback skizze)
# ---------------------------------------------------------------------------


class _FakeJwtCallbackCacheEmpty(Exception):
    """Stand-in for ``NatsJwtCallbackCacheEmpty`` (Sprint-6 Tag-10).

    The retry layer cooperates with the callback skizze by
    matching the exception CLASS NAME, not by importing the
    callback module. We construct a same-named class here in
    the test scope to exercise that code path.
    """


# Rename so the classifier's class-name check matches.
_FakeJwtCallbackCacheEmpty.__name__ = "NatsJwtCallbackCacheEmpty"


def test_classifier_recognises_jwt_callback_cache_empty_by_class_name():
    """The classifier handles the JWT-callback exception without import."""
    exc = _FakeJwtCallbackCacheEmpty("cold cache")
    assert classify_failure(exc) == REASON_JWT_CACHE_COLD


def test_classifier_distinguishes_tcp_probe_from_nats_py_fail():
    """The two NatsAdapterUnavailable variants map to distinct reasons."""
    tcp = NatsAdapterUnavailable(
        "TCP probe of nats://localhost:4222 failed — refused"
    )
    npy = NatsAdapterUnavailable(
        "NATS connect failed — handshake timeout"
    )
    assert classify_failure(tcp) == REASON_TCP_UNREACHABLE
    assert classify_failure(npy) == REASON_NATS_PY_CONNECT_FAIL


def test_classifier_auth_with_cold_cache_marker_maps_to_jwt_cache_cold():
    """The auth-rejected-with-cache-cold-marker maps to JWT_CACHE_COLD.

    This protects the case where the consumer wires the
    NatsJwtCallbackCacheEmpty exception through the user_jwt_cb
    path and nats-py surfaces it as an auth error.
    """
    exc = NatsAdapterAuthenticationError(
        "auth callback raised: JwtSvidCache is empty at "
        "CONNECT-frame-build time"
    )
    assert classify_failure(exc) == REASON_JWT_CACHE_COLD


# ---------------------------------------------------------------------------
# Jitter contract
# ---------------------------------------------------------------------------


def test_jittered_delay_bounds():
    """The jittered delay is bounded by ``[base*(1-j), base*(1+j)]``."""
    lo_only = jittered_delay(
        1.0, jitter_factor=0.2, random_uniform=_no_jitter
    )
    assert lo_only == pytest.approx(0.8, abs=1e-9)
    hi_only = jittered_delay(
        1.0, jitter_factor=0.2, random_uniform=lambda lo, hi: hi
    )
    assert hi_only == pytest.approx(1.2, abs=1e-9)


def test_jittered_delay_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        jittered_delay(1.0, jitter_factor=1.5)
    with pytest.raises(ValueError):
        jittered_delay(-0.5)


def test_jittered_delay_zero_base_is_zero():
    """A zero schedule entry yields zero sleep regardless of jitter."""
    assert (
        jittered_delay(0.0, jitter_factor=0.5, random_uniform=_no_jitter)
        == 0.0
    )


# ---------------------------------------------------------------------------
# Attempt-log invariants
# ---------------------------------------------------------------------------


def test_attempt_log_records_total_elapsed_includes_sleep_gaps():
    """``total_elapsed_seconds`` sums attempt + sleep gaps."""

    async def _drive():
        clock = _FakeClock(tick_seconds=0.0)
        sleep = _FakeSleep(clock=clock)
        connect = _scripted_connect(
            [NatsAdapterUnavailable("TCP probe failed"), None]
        )
        log = await connect_with_retry(
            connect,
            schedule=(0.1, 0.1),
            clock=clock,
            sleep=sleep,
            random_uniform=_no_jitter,
        )
        assert log.succeeded is True
        # First attempt slept 0.1*(1-0.2)=0.08s, second attempt
        # succeeded immediately. The clock advances on sleep so
        # total_elapsed >= 0.08.
        assert log.total_elapsed_seconds >= 0.08
        # Two attempts recorded.
        assert log.attempt_count() == 2

    asyncio.run(_drive())


def test_attempt_log_unknown_transient_does_not_swallow_non_adapter_error():
    """A truly unexpected exception class propagates."""

    async def _drive():
        clock = _FakeClock(tick_seconds=0.0)
        sleep = _FakeSleep(clock=clock)

        async def _connect():
            raise RuntimeError("unexpected — not a NatsAdapterError")

        with pytest.raises(RuntimeError, match="unexpected"):
            await connect_with_retry(
                _connect,
                schedule=(0.05,),
                clock=clock,
                sleep=sleep,
                random_uniform=_no_jitter,
            )

    asyncio.run(_drive())


# ---------------------------------------------------------------------------
# StaticReadyView shim
# ---------------------------------------------------------------------------


def test_static_ready_view_default_is_ready():
    view = StaticReadyView()
    assert view.is_ready() is True
    view.set_ready(False)
    assert view.is_ready() is False


def test_static_ready_view_ready_does_not_block_loop():
    """A consumer that wires StaticReadyView(ready=True) sees zero wait."""

    async def _drive():
        clock = _FakeClock(tick_seconds=0.0)
        sleep = _FakeSleep(clock=clock)
        cache = StaticReadyView(ready=True)
        connect = _scripted_connect([None])
        log = await connect_with_retry(
            connect,
            schedule=(0.05,),
            jwt_cache=cache,
            clock=clock,
            sleep=sleep,
            random_uniform=_no_jitter,
        )
        assert log.succeeded is True
        # No jwt-cache-cold attempts; the success is the first
        # attempt.
        assert log.attempts[0].reason == REASON_SUCCESS

    asyncio.run(_drive())


# ---------------------------------------------------------------------------
# Schedule edge cases
# ---------------------------------------------------------------------------


def test_empty_schedule_single_attempt_only():
    """``schedule=()`` collapses the retry loop to one attempt."""

    async def _drive():
        clock = _FakeClock(tick_seconds=0.0)
        sleep = _FakeSleep(clock=clock)
        connect = _scripted_connect(
            [NatsAdapterUnavailable("TCP probe failed")]
        )
        log = await connect_with_retry(
            connect,
            schedule=(),
            clock=clock,
            sleep=sleep,
            random_uniform=_no_jitter,
        )
        assert log.succeeded is False
        assert log.attempt_count() == 1

    asyncio.run(_drive())


def test_first_attempt_success_skips_sleep_entirely():
    """A success on attempt 0 records exactly one attempt, zero sleep."""

    async def _drive():
        clock = _FakeClock(tick_seconds=0.0)
        sleep = _FakeSleep(clock=clock)
        connect = _scripted_connect([None])
        log = await connect_with_retry(
            connect,
            schedule=(1.0, 1.0),
            clock=clock,
            sleep=sleep,
            random_uniform=_no_jitter,
        )
        assert log.succeeded is True
        assert log.attempt_count() == 1
        assert sleep.gaps == []

    asyncio.run(_drive())
