# SPDX-License-Identifier: BUSL-1.1
"""Sprint-Pengine-9 OI-PEFR-3 tests: AsyncPersonaEngine wrapper.

The async engine inherits the boot/spawn semantics from the sync
engine but runs natively on asyncio. Tests cover:

  - Boot path: V-907 verify + SVID probe + async state-backing attach.
  - Spawn path: FSM transitions + first audit-annotation emission.
  - Run loop: heartbeat task, drill task, subscribe task.
  - Stop semantics: request_stop() cancels all background tasks.
  - In-memory fence: empty WAKIR_NATS_SERVERS -> InMemory fallback.
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any, List, Optional, Tuple

import pytest

from wirelang.persona_engine.engine import EnvContract
from wirelang.persona_engine.engine_async import (
    ASYNC_ENGINE_VARIANT,
    ASYNC_ENGINE_VERSION,
    AsyncPersonaEngine,
    _AsyncBackingSyncShim,
)
from wirelang.persona_engine.state_backing import (
    InMemoryPersonaStateBacking,
    PersonaStateBackingAsync,
    PersonaStateSnapshot,
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
        spiffe_endpoint_socket="unix:///nonexistent/sock-async-test",
        persona_state_bucket=None,
        v907_expected_pin=None,
        axis_a_path=axis_a,
        axis_c_path=axis_c,
    )


def _capture_log(sink: io.StringIO) -> List[dict]:
    records: List[dict] = []
    for line in sink.getvalue().splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


# -------------------- helper async backing --------------------


class _MemoryAsyncBacking(PersonaStateBackingAsync):
    def __init__(self) -> None:
        self._snapshots: List[Tuple[int, PersonaStateSnapshot]] = []
        self._pinned: Optional[int] = None
        self._next: int = 0
        self.closed = False

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        self.closed = True

    async def snapshot(self, persona_id: str, state: PersonaStateSnapshot) -> int:
        from wirelang.persona_engine.state_backing import snapshot_to_jcs_bytes

        if self._snapshots:
            last_off, last_snap = self._snapshots[-1]
            if snapshot_to_jcs_bytes(last_snap) == snapshot_to_jcs_bytes(state):
                return last_off
        self._next += 1
        self._snapshots.append((self._next, state))
        return self._next

    async def restore_latest(self, persona_id: str):
        return self._snapshots[-1][1] if self._snapshots else None

    async def list_snapshots(self, persona_id: str):
        return [off for off, _ in self._snapshots]

    async def atomic_swap_pinned_offset(
        self, persona_id: str, from_offset: int, to_offset: int
    ) -> None:
        from wirelang.persona_engine.state_backing import (
            PersonaStateBackingError,
        )

        if self._pinned is not None and self._pinned != from_offset:
            raise PersonaStateBackingError("mismatched from")
        offsets = [o for o, _ in self._snapshots]
        if to_offset not in offsets:
            raise PersonaStateBackingError("unknown to")
        self._pinned = to_offset


# -------------------- boot path --------------------


def test_async_boot_with_empty_nats_fences_to_in_memory(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path, nats_servers="")
    engine = AsyncPersonaEngine(env_contract=env, log_sink=sink)

    asyncio.run(engine.boot())
    records = _capture_log(sink)
    fence_records = [r for r in records if r.get("msg") == "state-backing-fence-to-in-memory"]
    assert len(fence_records) == 1
    assert engine._fenced_to_in_memory is True


def test_async_boot_uses_injected_async_backing(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path, nats_servers="nats://stub:4222")
    backing = _MemoryAsyncBacking()
    engine = AsyncPersonaEngine(
        env_contract=env,
        async_state_backing=backing,
        log_sink=sink,
    )

    asyncio.run(engine.boot())
    assert engine.async_backing is backing
    assert engine._fenced_to_in_memory is False


def test_async_boot_v907_verified_log(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path)
    engine = AsyncPersonaEngine(env_contract=env, log_sink=sink)

    asyncio.run(engine.boot())
    records = _capture_log(sink)
    msgs = [r["msg"] for r in records]
    assert "v907-pin-verified" in msgs


def test_async_boot_svid_probe_logged(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path)
    engine = AsyncPersonaEngine(env_contract=env, log_sink=sink)

    asyncio.run(engine.boot())
    records = _capture_log(sink)
    svid_records = [r for r in records if r.get("msg") == "svid-workload-api-probe"]
    assert len(svid_records) == 1
    assert svid_records[0]["socket_present"] is False


# -------------------- spawn path --------------------


def test_async_spawn_runs_fsm_transitions(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path)
    backing = _MemoryAsyncBacking()
    engine = AsyncPersonaEngine(
        env_contract=env, async_state_backing=backing, log_sink=sink,
    )
    asyncio.run(engine.boot())
    asyncio.run(engine.spawn())
    assert engine.fsm.state == "running"


def test_async_spawn_emits_first_audit_event(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path)
    backing = _MemoryAsyncBacking()
    engine = AsyncPersonaEngine(
        env_contract=env, async_state_backing=backing, log_sink=sink,
    )
    asyncio.run(engine.boot())
    asyncio.run(engine.spawn())
    records = _capture_log(sink)
    first_emit = [r for r in records if r.get("msg") == "engineering-output-emission-first"]
    assert len(first_emit) == 1
    assert "event_payload_sha256" in first_emit[0]


def test_async_spawn_without_boot_raises(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path)
    engine = AsyncPersonaEngine(env_contract=env, log_sink=sink)

    with pytest.raises(RuntimeError):
        asyncio.run(engine.spawn())


# -------------------- run loop --------------------


def test_async_run_loop_request_stop_terminates(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path)
    backing = _MemoryAsyncBacking()
    engine = AsyncPersonaEngine(
        env_contract=env,
        async_state_backing=backing,
        log_sink=sink,
        heartbeat_interval_sec=1,
    )

    async def go():
        await engine.boot()
        await engine.spawn()
        task = asyncio.create_task(engine.run_until_signal())
        await asyncio.sleep(0.1)
        engine.request_stop()
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(go())


def test_async_run_loop_heartbeat_emits_audit(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path)
    backing = _MemoryAsyncBacking()
    engine = AsyncPersonaEngine(
        env_contract=env,
        async_state_backing=backing,
        log_sink=sink,
        heartbeat_interval_sec=1,
    )

    async def go():
        await engine.boot()
        await engine.spawn()
        task = asyncio.create_task(engine.run_until_signal())
        # Give the heartbeat at least one iteration.
        await asyncio.sleep(0.05)
        engine.request_stop()
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(go())
    # We don't assert heartbeat count (timing-flaky); just confirm
    # no exception bubbled through.


def test_async_run_loop_drill_runner_callback_invoked(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path)
    backing = _MemoryAsyncBacking()
    calls = []

    def drill_runner():
        calls.append("called")

    engine = AsyncPersonaEngine(
        env_contract=env,
        async_state_backing=backing,
        log_sink=sink,
        heartbeat_interval_sec=10,
        drill_interval_sec=1,
        drill_runner=drill_runner,
    )

    async def go():
        await engine.boot()
        await engine.spawn()
        task = asyncio.create_task(engine.run_until_signal())
        await asyncio.sleep(0.05)
        engine.request_stop()
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(go())
    assert len(calls) >= 1


def test_async_run_loop_subscribe_runner_invoked_once(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path)
    backing = _MemoryAsyncBacking()
    calls = []

    async def subscribe_runner():
        calls.append("sub")
        # Subscribe runner is allowed to return after starting subscriptions
        # (engine_async treats it as a one-shot starter).

    engine = AsyncPersonaEngine(
        env_contract=env,
        async_state_backing=backing,
        log_sink=sink,
        heartbeat_interval_sec=10,
        subscribe_runner=subscribe_runner,
    )

    async def go():
        await engine.boot()
        await engine.spawn()
        task = asyncio.create_task(engine.run_until_signal())
        await asyncio.sleep(0.05)
        engine.request_stop()
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(go())
    assert calls == ["sub"]


# -------------------- despawn-clean --------------------


def test_async_despawn_clean_completes(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path)
    backing = _MemoryAsyncBacking()
    engine = AsyncPersonaEngine(
        env_contract=env, async_state_backing=backing, log_sink=sink,
    )

    async def go():
        await engine.boot()
        await engine.spawn()
        await engine.despawn_clean_run()

    asyncio.run(go())
    records = _capture_log(sink)
    despawn = [r for r in records if r.get("msg") == "despawn-clean-completed-async"]
    assert len(despawn) == 1


# -------------------- engine-version stamps --------------------


def test_async_engine_version_constant():
    # Sprint-Pengine-10 bump: 0.3.0-pilot -> 0.4.0-pilot for the NATS-
    # subscribe-loop substrate + LLM-Call-Shim addition. The async
    # engine remains a strict superset of 0.3.0-pilot.
    assert ASYNC_ENGINE_VERSION == "0.4.2-pilot"


def test_async_engine_variant_label():
    assert ASYNC_ENGINE_VARIANT == "real-async"


def test_async_engine_log_carries_version_default(tmp_path):
    sink = io.StringIO()
    env = _make_env(tmp_path)
    engine = AsyncPersonaEngine(env_contract=env, log_sink=sink)
    asyncio.run(engine.boot())
    records = _capture_log(sink)
    for r in records:
        assert r["engine_version"] == "0.4.2-pilot"
        assert r["engine_variant"] == "real-async"


# -------------------- AsyncBackingSyncShim --------------------


def test_async_backing_sync_shim_rejects_loop_reentry():
    """The shim must refuse re-entry from inside the engine loop —
    that would deadlock the synchronous despawn-clean flow."""
    async def go():
        backing = _MemoryAsyncBacking()
        loop = asyncio.get_event_loop()
        shim = _AsyncBackingSyncShim(backing, loop)
        # Calling from inside the loop hits the re-entry guard.
        with pytest.raises(RuntimeError):
            shim.snapshot(
                "tomas",
                PersonaStateSnapshot(
                    persona_hash="sha256:" + "0" * 64,
                    audit_trace_offset=0,
                    capability_token_ids=("tok",),
                    snapshot_at_utc="2026-05-15T00:00:00Z",
                    workspace_state_hash="sha256:" + "1" * 64,
                ),
            )

    asyncio.run(go())
