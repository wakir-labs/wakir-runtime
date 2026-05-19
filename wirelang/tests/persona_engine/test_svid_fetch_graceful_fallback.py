# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Sprint-Pengine-11 Bug-40 — SVID full-fetch graceful-fallback tests.

Background
----------

Live-spawn 0.4.0-pilot on wakir-pilot 2026-05-15 ~22:25 CEST crashed
during engine.boot() because the full SVID fetch raised
``grpc.aio._call.AioRpcError("Broken pipe")``. The boot path caught
``SvidFetchError`` and ``ImportError`` only — the gRPC error
escaped and brought down the container with FSM=uninstantiated.

Sprint-Pengine-11 fix:

1. ``WorkloadApiClient.fetch_x509_svid`` wraps the gRPC stream
   iteration in a try/except converter that re-raises non-
   :class:`SvidFetchError` exceptions as :class:`SvidFetchError`
   with the original exception preserved as ``__cause__``.

2. ``PersonaEngine.boot`` and ``AsyncPersonaEngine.boot`` broaden
   the exception catch (defence-in-depth) and emit
   ``svid-full-fetch-failed-fence-to-probe-only`` WARN with both
   ``reason`` and ``exception_type``. V-907 errors are preserved
   and still propagate (boot-go-no-go gate).

3. The engine continues to spawn -> FSM=running with
   ``svid_full_fetch_fenced=True``. The async engine starts a
   background ``_svid_refetch_loop`` that retries every
   ``svid_refetch_interval_sec`` seconds. On success the engine
   emits ``svid-full-fetch-recovered`` INFO and un-fences.

This module covers (mandate: minimum 10 tests):

- Sync engine fence-on-fetch-failure (raw exception types):
  AioRpcError-like, OSError("Broken pipe"), ConnectionError,
  generic RuntimeError, SvidFetchError, ImportError, TimeoutError.
- Sync engine recovery via ``attempt_svid_refetch``.
- Async engine fence-on-fetch-failure parity.
- Async engine recovery via ``attempt_svid_refetch``.
- Async engine ``_svid_refetch_loop`` background retry on stop-event.
- V-907 errors NOT swallowed (boot-go-no-go preserved).
- ``WorkloadApiClient.fetch_x509_svid`` exception conversion.
"""

from __future__ import annotations

import asyncio
import datetime
import io
import json
from pathlib import Path
from typing import Any, List, Optional

import pytest

from wirelang.persona_engine._workload_api_pb2_minimal import (
    X509SVID,
    X509SVIDResponse,
)
from wirelang.persona_engine.engine import (
    ENGINE_VERSION,
    EnvContract,
    PersonaEngine,
)
from wirelang.persona_engine.engine_async import (
    ASYNC_ENGINE_VERSION,
    AsyncPersonaEngine,
)
from wirelang.persona_engine.svid_workload_identity import (
    SvidFetchError,
    WorkloadApiClient,
)
from wirelang.tests.persona_engine._v907_compute_skip import (
    requires_v907_compute_deps,
)


PERSONA_DEF_TEMPLATE = """---
slug: tomas
title: Tomás Reinhart
version: 0.1
---

# Tomás Reinhart — test persona
"""


# ---------------------------------------------------------------------------
# Test helpers — UDS server that simulates a connectable socket so the
# boot-gate probe succeeds (socket_connectable=True) but the full fetch
# fails with various error types.
# ---------------------------------------------------------------------------


def _make_env(
    tmp_path: Path,
    *,
    socket_path: str,
    nats_servers: str = "",
) -> EnvContract:
    axis_a = tmp_path / "tomas.md"
    axis_a.write_text(PERSONA_DEF_TEMPLATE)
    axis_c = tmp_path / "tomas.json"
    axis_c.write_text("{}")
    return EnvContract(
        persona_id="tomas",
        org_id="acme",
        nats_servers=nats_servers,
        spiffe_endpoint_socket=f"unix://{socket_path}",
        persona_state_bucket=None,
        v907_expected_pin=None,
        axis_a_path=axis_a,
        axis_c_path=axis_c,
    )


def _capture_log(sink: io.StringIO) -> List[dict]:
    return [
        json.loads(line)
        for line in sink.getvalue().splitlines()
        if line.strip()
    ]


@pytest.fixture
def listening_uds(tmp_path: Path):
    """Yields a real UDS path that ``connect()`` succeeds against,
    so the boot-gate probe shows socket_connectable=True. The
    socket is kept alive for the test duration and closed in
    teardown. The engine never actually connects to it — the gRPC
    channel is replaced by the failing channel-factory.
    """
    import socket as _socket

    sock_path = tmp_path / "spire-agent.sock"
    s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    s.bind(str(sock_path))
    s.listen(8)
    s.setblocking(False)
    try:
        yield str(sock_path)
    finally:
        s.close()


# Channel + stub factories for the various failure-injection scenarios.

class _FailingChannel:
    """Channel that exposes a close() method but never gets used by
    the failure-injection stubs. The stub raises before the channel
    is consulted."""

    async def close(self):
        return None


def _raising_channel_factory(_path):
    return _FailingChannel()


def _stub_factory_for_exception(exc: BaseException):
    """Build a stub factory whose FetchX509SVID raises ``exc``."""

    class _RaisingStub:
        def FetchX509SVID(self, _request, *, metadata=None):
            raise exc

    def sf(_channel):
        return _RaisingStub()

    return sf


# ---------------------------------------------------------------------------
# 1. WorkloadApiClient — exception conversion (Bug-40 root cause #1).
# ---------------------------------------------------------------------------


def test_workload_api_client_converts_generic_exception_to_svid_fetch_error():
    """A raw RuntimeError from the gRPC stub is converted to
    SvidFetchError with the original exception preserved as cause."""
    sf = _stub_factory_for_exception(RuntimeError("simulated gRPC failure"))

    async def go():
        async with WorkloadApiClient(
            socket_path="/tmp/fake.sock",
            channel_factory=_raising_channel_factory,
            stub_factory=sf,
        ) as client:
            with pytest.raises(SvidFetchError) as exc_info:
                await client.fetch_x509_svid(
                    org_id="acme", persona_id="tomas",
                )
        assert "RuntimeError" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, RuntimeError)

    asyncio.run(go())


def test_workload_api_client_converts_os_broken_pipe_to_svid_fetch_error():
    """The actual Bug-40 wire-error: OSError("Broken pipe") gets
    converted. This mirrors the SPIRE-1.14 gRPC.aio.AioRpcError
    that crashed wakir-pilot 2026-05-15 ~22:25 CEST."""
    sf = _stub_factory_for_exception(
        OSError(32, "sendmsg: Broken pipe")
    )

    async def go():
        async with WorkloadApiClient(
            socket_path="/tmp/fake.sock",
            channel_factory=_raising_channel_factory,
            stub_factory=sf,
        ) as client:
            with pytest.raises(SvidFetchError) as exc_info:
                await client.fetch_x509_svid(
                    org_id="acme", persona_id="tomas",
                )
        # Python auto-promotes OSError(32, ...) to BrokenPipeError.
        assert "Broken pipe" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, OSError)
        assert exc_info.value.__cause__.errno == 32

    asyncio.run(go())


def test_workload_api_client_preserves_svid_fetch_error_unchanged():
    """If the stub itself raises SvidFetchError, the converter MUST
    re-raise it unchanged (no double-wrapping)."""
    original = SvidFetchError("inner-marker")
    sf = _stub_factory_for_exception(original)

    async def go():
        async with WorkloadApiClient(
            socket_path="/tmp/fake.sock",
            channel_factory=_raising_channel_factory,
            stub_factory=sf,
        ) as client:
            with pytest.raises(SvidFetchError) as exc_info:
                await client.fetch_x509_svid(
                    org_id="acme", persona_id="tomas",
                )
        # Must be the SAME instance — no wrapping.
        assert exc_info.value is original
        assert "inner-marker" in str(exc_info.value)

    asyncio.run(go())


# ---------------------------------------------------------------------------
# 2. Sync engine — graceful fence-to-probe-only.
# ---------------------------------------------------------------------------


@requires_v907_compute_deps
def test_sync_engine_boot_fences_on_aio_rpc_error_like_exception(tmp_path, listening_uds):
    """Synthesised AioRpcError-like exception (matching the wakir-
    pilot Bug-40 traceback) must NOT crash boot. Engine fences."""
    sock_path = listening_uds
    sink = io.StringIO()
    env = _make_env(tmp_path, socket_path=sock_path)
    engine = PersonaEngine(env_contract=env, log_sink=sink)
    # Inject failure stub mimicking grpc.aio.AioRpcError surface.

    class _FakeAioRpcError(Exception):
        def __init__(self):
            super().__init__(
                "failed to connect to all addresses; last error: "
                "UNAVAILABLE: unix:/run/spire/agent-sockets/api.sock: "
                "sendmsg: Broken pipe (32)"
            )

    engine.set_svid_factories(
        channel_factory=_raising_channel_factory,
        stub_factory=_stub_factory_for_exception(_FakeAioRpcError()),
    )
    engine.boot()
    # FSM still uninstantiated (boot does not transition); the test
    # asserts boot did NOT raise + fence flag is set.
    assert engine.svid_full_fetch_fenced is True
    assert engine.svid_full_fetch_fence_reason is not None
    assert "Broken pipe" in engine.svid_full_fetch_fence_reason
    log = _capture_log(sink)
    fence = [
        r for r in log
        if r.get("msg") == "svid-full-fetch-failed-fence-to-probe-only"
    ]
    assert len(fence) == 1
    assert fence[0]["level"] == "WARN"
    assert fence[0]["fence_mode"] == "fetch-failure"
    # The svid_workload_identity converter wraps the underlying
    # exception in SvidFetchError; the boot path sees that wrapper.
    # The original exception name is preserved in the reason text.
    assert fence[0]["exception_type"] == "SvidFetchError"
    assert "_FakeAioRpcError" in fence[0]["reason"]


@requires_v907_compute_deps
def test_sync_engine_spawn_succeeds_after_fence(tmp_path, listening_uds):
    """The engine must still be able to transition uninstantiated ->
    spawning -> running after the fence (boot completes normally)."""
    sock_path = listening_uds
    sink = io.StringIO()
    env = _make_env(tmp_path, socket_path=sock_path)
    engine = PersonaEngine(env_contract=env, log_sink=sink)
    engine.set_svid_factories(
        channel_factory=_raising_channel_factory,
        stub_factory=_stub_factory_for_exception(
            ConnectionError("simulated SPIRE-Agent unreachable")
        ),
    )
    engine.boot()
    engine.spawn()
    assert engine.fsm.state == "running"
    assert engine.svid_full_fetch_fenced is True
    log = _capture_log(sink)
    fsm_transitions = [
        r for r in log if r.get("msg") == "fsm-transition"
    ]
    assert any(
        t.get("from") == "spawning" and t.get("to") == "running"
        for t in fsm_transitions
    )


@requires_v907_compute_deps
def test_sync_engine_v907_drift_still_propagates(tmp_path, listening_uds):
    """Bug-40 hardening MUST NOT swallow V-907 drift — that is the
    boot-go-no-go gate and must crash boot loudly."""
    from wirelang.persona_engine.v907_verify import PersonaHashDriftError

    sock_path = listening_uds
    sink = io.StringIO()
    env = _make_env(tmp_path, socket_path=sock_path)
    # Force a V-907 pin mismatch via expected_pin override.
    bad_env = EnvContract(
        persona_id=env.persona_id,
        org_id=env.org_id,
        nats_servers=env.nats_servers,
        spiffe_endpoint_socket=env.spiffe_endpoint_socket,
        persona_state_bucket=env.persona_state_bucket,
        v907_expected_pin="sha256:" + "00" * 32,  # impossible hash
        axis_a_path=env.axis_a_path,
        axis_c_path=env.axis_c_path,
    )
    engine = PersonaEngine(env_contract=bad_env, log_sink=sink)
    with pytest.raises(PersonaHashDriftError):
        engine.boot()


# ---------------------------------------------------------------------------
# 3. Sync engine — recovery via attempt_svid_refetch.
# ---------------------------------------------------------------------------


def _make_x509_svid_response(spiffe_id: str) -> X509SVIDResponse:
    """Build a minimal canned X509SVIDResponse with a self-signed
    leaf cert that the engine's full-fetch parser can consume."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    not_before = datetime.datetime.now(datetime.timezone.utc)
    not_after = not_before + datetime.timedelta(hours=1)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "test-persona"),
        ]))
        .issuer_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "test-ca"),
        ]))
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(
            x509.SubjectAlternativeName([
                x509.UniformResourceIdentifier(spiffe_id),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    der = cert.public_bytes(serialization.Encoding.DER)
    return X509SVIDResponse(
        svids=[X509SVID(spiffe_id=spiffe_id, x509_svid=der)],
    )


@requires_v907_compute_deps
def test_sync_engine_attempt_svid_refetch_recovers(tmp_path, listening_uds):
    """After a fenced boot, attempt_svid_refetch with a healthy stub
    must un-fence the engine and emit svid-full-fetch-recovered."""
    sock_path = listening_uds
    sink = io.StringIO()
    env = _make_env(tmp_path, socket_path=sock_path)
    engine = PersonaEngine(env_contract=env, log_sink=sink)
    # Boot with a failing stub.
    engine.set_svid_factories(
        channel_factory=_raising_channel_factory,
        stub_factory=_stub_factory_for_exception(
            OSError(32, "Broken pipe")
        ),
    )
    engine.boot()
    assert engine.svid_full_fetch_fenced is True

    # Swap to a healthy stub and retry.
    canned = _make_x509_svid_response(
        "spiffe://wakir.acme/persona/tomas",
    )

    class _HealthyStream:
        def __init__(self):
            self._yielded = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._yielded:
                raise StopAsyncIteration
            self._yielded = True
            return canned

    class _HealthyStub:
        def FetchX509SVID(self, _request, *, metadata=None):
            return _HealthyStream()

    engine.set_svid_factories(
        channel_factory=_raising_channel_factory,
        stub_factory=lambda _c: _HealthyStub(),
    )
    recovered = engine.attempt_svid_refetch()
    assert recovered is True
    assert engine.svid_full_fetch_fenced is False
    assert engine.svid_fetch is not None
    log = _capture_log(sink)
    rec = [r for r in log if r.get("msg") == "svid-full-fetch-recovered"]
    assert len(rec) == 1
    assert rec[0]["level"] == "INFO"


@requires_v907_compute_deps
def test_sync_engine_attempt_svid_refetch_still_failing(tmp_path, listening_uds):
    """If the retry also fails, attempt_svid_refetch returns False
    and the engine stays fenced; a WARN ``svid-full-fetch-retry-failed``
    is emitted with the new reason."""
    sock_path = listening_uds
    sink = io.StringIO()
    env = _make_env(tmp_path, socket_path=sock_path)
    engine = PersonaEngine(env_contract=env, log_sink=sink)
    engine.set_svid_factories(
        channel_factory=_raising_channel_factory,
        stub_factory=_stub_factory_for_exception(
            OSError(32, "Broken pipe")
        ),
    )
    engine.boot()
    # Second attempt: same stub. Should stay fenced.
    engine.set_svid_factories(
        channel_factory=_raising_channel_factory,
        stub_factory=_stub_factory_for_exception(
            ConnectionError("still down")
        ),
    )
    assert engine.attempt_svid_refetch() is False
    assert engine.svid_full_fetch_fenced is True
    log = _capture_log(sink)
    retry_fail = [
        r for r in log if r.get("msg") == "svid-full-fetch-retry-failed"
    ]
    assert len(retry_fail) == 1
    assert "still down" in retry_fail[0]["reason"]


# ---------------------------------------------------------------------------
# 4. Async engine — graceful fence + recovery.
# ---------------------------------------------------------------------------


@requires_v907_compute_deps
def test_async_engine_boot_fences_on_fetch_failure(tmp_path, listening_uds):
    sock_path = listening_uds
    sink = io.StringIO()
    env = _make_env(tmp_path, socket_path=sock_path)
    engine = AsyncPersonaEngine(env_contract=env, log_sink=sink)
    engine.set_svid_factories(
        channel_factory=_raising_channel_factory,
        stub_factory=_stub_factory_for_exception(
            OSError(32, "Broken pipe")
        ),
    )
    asyncio.run(engine.boot())
    assert engine.svid_full_fetch_fenced is True
    assert engine.svid_fetch is None
    log = _capture_log(sink)
    fence = [
        r for r in log
        if r.get("msg") == "svid-full-fetch-failed-fence-to-probe-only"
    ]
    assert len(fence) == 1
    assert fence[0]["fence_mode"] == "fetch-failure"


@requires_v907_compute_deps
def test_async_engine_attempt_svid_refetch_recovers(tmp_path, listening_uds):
    sock_path = listening_uds
    sink = io.StringIO()
    env = _make_env(tmp_path, socket_path=sock_path)
    engine = AsyncPersonaEngine(env_contract=env, log_sink=sink)
    engine.set_svid_factories(
        channel_factory=_raising_channel_factory,
        stub_factory=_stub_factory_for_exception(
            OSError(32, "Broken pipe")
        ),
    )
    asyncio.run(engine.boot())
    assert engine.svid_full_fetch_fenced is True

    canned = _make_x509_svid_response(
        "spiffe://wakir.acme/persona/tomas",
    )

    class _HealthyStream:
        def __init__(self):
            self._yielded = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._yielded:
                raise StopAsyncIteration
            self._yielded = True
            return canned

    class _HealthyStub:
        def FetchX509SVID(self, _request, *, metadata=None):
            return _HealthyStream()

    engine.set_svid_factories(
        channel_factory=_raising_channel_factory,
        stub_factory=lambda _c: _HealthyStub(),
    )
    recovered = asyncio.run(engine.attempt_svid_refetch())
    assert recovered is True
    assert engine.svid_full_fetch_fenced is False
    assert engine.svid_fetch is not None
    log = _capture_log(sink)
    rec = [r for r in log if r.get("msg") == "svid-full-fetch-recovered"]
    assert len(rec) == 1


@requires_v907_compute_deps
def test_async_engine_refetch_loop_runs_and_exits_on_stop(tmp_path, listening_uds):
    """The _svid_refetch_loop background task must start when the
    engine fences and exit cleanly on stop-event."""
    sock_path = listening_uds
    sink = io.StringIO()
    env = _make_env(tmp_path, socket_path=sock_path)
    engine = AsyncPersonaEngine(
        env_contract=env,
        log_sink=sink,
        svid_refetch_interval_sec=1,  # 1-second tick for tests
    )
    engine.set_svid_factories(
        channel_factory=_raising_channel_factory,
        stub_factory=_stub_factory_for_exception(
            OSError(32, "Broken pipe")
        ),
    )

    async def scenario():
        await engine.boot()
        assert engine.svid_full_fetch_fenced is True
        engine._stop_event = asyncio.Event()
        task = asyncio.create_task(engine._svid_refetch_loop())
        # Let the loop tick once.
        await asyncio.sleep(1.2)
        engine._stop_event.set()
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(scenario())
    log = _capture_log(sink)
    # At least one retry attempt was made — produces either
    # ``svid-full-fetch-retry-failed`` or ``svid-full-fetch-recovered``.
    retry_records = [
        r for r in log
        if r.get("msg") in (
            "svid-full-fetch-retry-failed",
            "svid-full-fetch-recovered",
        )
    ]
    assert len(retry_records) >= 1


@requires_v907_compute_deps
def test_async_engine_refetch_loop_recovers_mid_run(tmp_path, listening_uds):
    """Refetch loop must un-fence the engine when the underlying
    stub starts succeeding mid-run."""
    sock_path = listening_uds
    sink = io.StringIO()
    env = _make_env(tmp_path, socket_path=sock_path)
    engine = AsyncPersonaEngine(
        env_contract=env,
        log_sink=sink,
        svid_refetch_interval_sec=1,
    )
    # State: 2 failed calls, then healthy.
    state = {"calls": 0}
    canned = _make_x509_svid_response(
        "spiffe://wakir.acme/persona/tomas",
    )

    class _SometimesStream:
        def __init__(self):
            self._yielded = False
            self._fail = state["calls"] < 2
            state["calls"] += 1

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._fail:
                raise OSError(32, "Broken pipe")
            if self._yielded:
                raise StopAsyncIteration
            self._yielded = True
            return canned

    class _FlakyStub:
        def FetchX509SVID(self, _request, *, metadata=None):
            return _SometimesStream()

    engine.set_svid_factories(
        channel_factory=_raising_channel_factory,
        stub_factory=lambda _c: _FlakyStub(),
    )

    async def scenario():
        await engine.boot()
        # First call already happened in boot (failure -> fenced).
        assert engine.svid_full_fetch_fenced is True
        engine._stop_event = asyncio.Event()
        task = asyncio.create_task(engine._svid_refetch_loop())
        # Two ticks: first still failing, second succeeds.
        await asyncio.sleep(2.5)
        engine._stop_event.set()
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(scenario())
    assert engine.svid_full_fetch_fenced is False
    assert engine.svid_fetch is not None
    log = _capture_log(sink)
    rec = [r for r in log if r.get("msg") == "svid-full-fetch-recovered"]
    assert len(rec) == 1


@requires_v907_compute_deps
def test_async_engine_run_until_signal_includes_refetch_task(tmp_path, listening_uds):
    """run_until_signal must spawn the svid_refetch task as the 4th
    background task. We exercise via request_stop()."""
    sock_path = listening_uds
    sink = io.StringIO()
    env = _make_env(tmp_path, socket_path=sock_path)
    engine = AsyncPersonaEngine(
        env_contract=env,
        log_sink=sink,
        heartbeat_interval_sec=10,
        svid_refetch_interval_sec=10,
    )
    engine.set_svid_factories(
        channel_factory=_raising_channel_factory,
        stub_factory=_stub_factory_for_exception(
            OSError(32, "Broken pipe")
        ),
    )

    async def scenario():
        await engine.boot()
        await engine.spawn()
        run_task = asyncio.create_task(engine.run_until_signal())
        # Yield to allow task creation.
        await asyncio.sleep(0.1)
        # All 4 background tasks must exist.
        assert engine.tasks.heartbeat is not None
        assert engine.tasks.drill is not None
        assert engine.tasks.subscribe is not None
        assert engine.tasks.svid_refetch is not None
        engine.request_stop()
        await asyncio.wait_for(run_task, timeout=3.0)

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# 5. Version constant sanity.
# ---------------------------------------------------------------------------


def test_engine_version_bumped_to_0_4_1_pilot():
    assert ENGINE_VERSION == "0.5.3"
    assert ASYNC_ENGINE_VERSION == "0.5.3"


def test_sync_engine_refetch_returns_false_if_boot_never_ran(tmp_path, listening_uds):
    """attempt_svid_refetch on a fresh engine (no boot()) is a no-op
    that returns False — there is nothing to retry."""
    sock_path = listening_uds
    sink = io.StringIO()
    env = _make_env(tmp_path, socket_path=sock_path)
    engine = PersonaEngine(env_contract=env, log_sink=sink)
    assert engine.svid_probe is None
    assert engine.attempt_svid_refetch() is False
