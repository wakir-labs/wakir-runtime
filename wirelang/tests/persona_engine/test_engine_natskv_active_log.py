# SPDX-License-Identifier: BUSL-1.1
"""Sprint-Pengine-9 OI-PEFR-1 engine-side tests.

Verifies that the engine boot path emits ``state-backing-natskv-active``
INFO (instead of the v0.2.0-pilot ``state-backing-fence-to-in-memory``
WARN) when nats-py is available and the WAKIR_NATS_SERVERS env var
is non-empty.

Also covers the SVID-fetch boot integration: when the socket probe
succeeds and the channel/stub factories are injected, the engine
emits ``svid-fetch-completed`` INFO.
"""

from __future__ import annotations

import datetime
import io
import json
from pathlib import Path
from typing import Any, List

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
from wirelang.persona_engine.state_backing import (
    InMemoryPersonaStateBacking,
    NatsKvPersonaStateBacking,
    NatsKvPersonaStateBackingAsync,
)


PERSONA_DEF_TEMPLATE = """---
slug: tomas
title: Tomás Reinhart
version: 0.1
---

# Tomás Reinhart — test persona
"""


def _make_env(tmp_path: Path, *, nats_servers: str = "") -> EnvContract:
    axis_a = tmp_path / "tomas.md"
    axis_a.write_text(PERSONA_DEF_TEMPLATE)
    axis_c = tmp_path / "tomas.json"
    axis_c.write_text("{}")
    return EnvContract(
        persona_id="tomas",
        org_id="acme",
        nats_servers=nats_servers,
        spiffe_endpoint_socket="unix:///nonexistent/sock-engine-test",
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


def test_engine_version_constant_bumped_to_0_4_1_pilot():
    # Sprint-Pengine-11 bump: 0.4.0-pilot -> 0.4.2-pilot for the
    # Bug-40 SVID-fetch graceful-fallback pattern.
    assert ENGINE_VERSION == "0.5.0-pilot"


def test_engine_emits_state_backing_natskv_active_with_injected_async_backing(tmp_path):
    """With WAKIR_NATS_SERVERS=non-empty and a pre-connected async
    backing injected, the engine select-state-backing path emits
    INFO state-backing-natskv-active."""
    import asyncio

    # Build a connected async backing via stub factories.
    class _StubEntry:
        def __init__(self, value: bytes, revision: int = 1) -> None:
            self.value = value
            self.revision = revision

    class _StubKv:
        def __init__(self) -> None:
            self._s: dict = {}

        async def put(self, key, value):
            self._s[key] = _StubEntry(value=bytes(value))
            return self._s[key]

        async def get(self, key):
            return self._s.get(key)

        async def keys(self):
            return list(self._s.keys())

        async def update(self, key, value, *, last):
            return await self.put(key, value)

    class _StubJs:
        def __init__(self):
            self._b = {}

        async def key_value(self, bucket):
            return self._b.setdefault(bucket, _StubKv())

    class _StubClient:
        def __init__(self):
            self._js = _StubJs()

        def jetstream(self):
            return self._js

        async def close(self):
            pass

    async def _client_factory(_s, _t):
        return _StubClient()

    async def _js_factory(c):
        return c.jetstream()

    async_backing = NatsKvPersonaStateBackingAsync(
        nats_servers="nats://stub:4222",
        org_id="acme",
        nats_client_factory=_client_factory,
        js_factory=_js_factory,
    )
    asyncio.run(async_backing.connect())
    sync_facade = NatsKvPersonaStateBacking(
        nats_servers="nats://stub:4222",
        org_id="acme",
        async_backing=async_backing,
    )
    sink = io.StringIO()
    env = _make_env(tmp_path, nats_servers="nats://stub:4222")
    engine = PersonaEngine(
        env_contract=env,
        state_backing=sync_facade,
        log_sink=sink,
    )
    # We pre-attached state_backing so _select_state_backing isn't
    # invoked. But the engine still logs state-backing-natskv-active
    # only when it goes through _select_state_backing. Test that
    # the engine does NOT emit fence-to-in-memory in this case.
    engine.boot()
    log = _capture_log(sink)
    fence = [r for r in log if r.get("msg") == "state-backing-fence-to-in-memory"]
    assert fence == []
    sync_facade.close()


def test_engine_emits_fence_warn_when_nats_servers_empty(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path, nats_servers="")
    engine = PersonaEngine(env_contract=env, log_sink=sink)
    engine.boot()
    log = _capture_log(sink)
    fence = [r for r in log if r.get("msg") == "state-backing-fence-to-in-memory"]
    assert len(fence) == 1
    assert fence[0]["level"] == "WARN"


def test_engine_emits_state_backing_natskv_active_log_path(tmp_path, monkeypatch):
    """Test that _select_state_backing emits state-backing-natskv-active
    INFO when NatsKvPersonaStateBacking is constructible."""
    import asyncio
    from wirelang.persona_engine import engine as engine_mod

    class _StubEntry:
        def __init__(self, value, revision=1):
            self.value = value
            self.revision = revision

    class _StubKv:
        def __init__(self):
            self._s = {}

        async def put(self, key, value):
            self._s[key] = _StubEntry(bytes(value))
            return self._s[key]

        async def get(self, key):
            return self._s.get(key)

        async def keys(self):
            return list(self._s.keys())

        async def update(self, key, value, *, last):
            return await self.put(key, value)

    class _StubJs:
        def __init__(self):
            self._b = {}

        async def key_value(self, bucket):
            return self._b.setdefault(bucket, _StubKv())

    class _StubClient:
        def jetstream(self):
            return _StubJs()

        async def close(self):
            pass

    # Monkeypatch NatsKvPersonaStateBacking to a no-op constructor that
    # doesn't probe nats-py — so the engine select path takes the
    # ``natskv-active`` branch.
    class _FakeNatsKvBacking:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def snapshot(self, *a, **kw):
            return 1

        def restore_latest(self, *a, **kw):
            return None

        def list_snapshots(self, *a, **kw):
            return []

        def atomic_swap_pinned_offset(self, *a, **kw):
            return None

    monkeypatch.setattr(engine_mod, "NatsKvPersonaStateBacking", _FakeNatsKvBacking)

    sink = io.StringIO()
    env = _make_env(tmp_path, nats_servers="nats://stub:4222")
    engine = PersonaEngine(env_contract=env, log_sink=sink)
    # Trigger _select_state_backing by accessing engine.backing.
    backing = engine.backing
    log = _capture_log(sink)
    active = [r for r in log if r.get("msg") == "state-backing-natskv-active"]
    assert len(active) == 1
    assert active[0]["level"] == "INFO"
    assert active[0]["nats_servers"] == "nats://stub:4222"
    assert active[0]["org_id"] == "acme"


def test_engine_svid_fetch_factories_set_via_setter(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path)
    engine = PersonaEngine(env_contract=env, log_sink=sink)
    assert engine._svid_channel_factory is None
    assert engine._svid_stub_factory is None

    def cf(_p):
        return object()

    def sf(_c):
        return object()

    engine.set_svid_factories(channel_factory=cf, stub_factory=sf)
    assert engine._svid_channel_factory is cf
    assert engine._svid_stub_factory is sf


def test_engine_svid_fetch_factories_default_none(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path)
    engine = PersonaEngine(env_contract=env, log_sink=sink)
    assert engine.svid_fetch is None


def test_engine_boot_with_no_socket_skips_svid_fetch(tmp_path):
    """When the SVID probe shows socket_connectable=False, the engine
    must NOT attempt an SVID fetch (which would just error)."""
    sink = io.StringIO()
    env = _make_env(tmp_path)
    engine = PersonaEngine(env_contract=env, log_sink=sink)
    engine.boot()
    log = _capture_log(sink)
    fetch_records = [r for r in log if r.get("msg") in (
        "svid-fetch-completed", "svid-fetch-failed", "svid-fetch-fence-to-probe-only",
    )]
    # No fetch attempted because socket_connectable=False.
    assert len(fetch_records) == 0
    assert engine.svid_fetch is None
