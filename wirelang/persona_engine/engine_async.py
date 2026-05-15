# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Async PersonaEngine wrapper (Sprint-Pengine-9 OI-PEFR-3).

The synchronous :class:`wirelang.persona_engine.engine.PersonaEngine`
keeps the v0.2.0-pilot run-until-signal loop semantics. Sprint-
Pengine-10 will introduce a NATS-subscribe-based auftrags-pipeline
that requires asyncio at the orchestration layer; this module is
the preparation surface for that pipeline.

Surface
-------

:class:`AsyncPersonaEngine` mirrors the sync engine API but exposes
``async def`` boot/spawn/run-until-signal methods. The boot path
uses the asyncio-native :class:`PersonaStateBackingAsync` binding
and the async :func:`fetch_workload_svid` call directly — no
thread-pool hop. The run loop wires:

  - Heartbeat task (audit-annotation emission, parity with sync).
  - Recovery drill scheduler task (OI-PEFR-4 ``DrillScheduler``).
  - NATS-subscribe task (placeholder; full subscribe logic lands
    in Sprint-Pengine-10).
  - Signal-handler task (SIGTERM / SIGINT -> graceful shutdown).

Determinism
-----------

The async engine reuses the same :class:`LifecycleStateMachine`,
:class:`BridgeAuditWriter`, and :class:`V907VerifyResult` types as
the sync engine. State-pack JCS bytes are byte-identical across the
sync and async paths so cross-engine state-pack reads work (the
foundation of OI-PEFR-5 migrate-version).
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional, TextIO

from .bridge_audit_writer import (
    BridgeAuditWriter,
    EngineeringOutputEvent,
)
from .engine import (
    DEFAULT_HEARTBEAT_INTERVAL_SEC,
    ENGINE_VARIANT,
    EnvContract,
    resolve_env,
)
from .llm_call_shim import (
    EchoReflectionLlmHook,
    LlmCallHook,
)
from .nats_subscribe_loop import (
    NatsSubscribeLoop,
    PublishSink,
    SubscribeLoopConfig,
    TaskProcessingTracker,
    build_subscribe_subject,
)
from .lifecycle_state_machine import (
    InvalidTransitionError,
    LifecycleStateMachine,
)
from .state_backing import (
    InMemoryPersonaStateBacking,
    NatsKvPersonaStateBackingAsync,
    PersonaStateBacking,
    PersonaStateBackingAsync,
    PersonaStateBackingError,
    PersonaStateSnapshot,
)
from .svid_workload_identity import (
    SvidFetchError,
    SvidFetchResult,
    SvidProbeResult,
    fetch_workload_svid,
    probe_workload_api_socket,
    resolve_socket_path,
)
from .v907_verify import (
    PersonaHashComputeError,
    PersonaHashDriftError,
    V907VerifyResult,
    verify_v907_pin,
)

ASYNC_ENGINE_VERSION = "0.4.2-pilot"
ASYNC_ENGINE_VARIANT = "real-async"
DEFAULT_SVID_REFETCH_INTERVAL_SEC = 300  # 5 min — Sprint-Pengine-11 Bug-40


def _utc_now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class _AsyncBackingSyncShim(PersonaStateBacking):
    """Adapter so the sync ``BridgeAuditWriter`` and ``DespawnCleanWorkflow``
    (which both take :class:`PersonaStateBacking`) can ride on top of
    an async backing inside the async engine. The shim defers each
    call to the engine's running event loop.

    NOTE: this shim is **engine-internal only** — production async
    callers consume :class:`PersonaStateBackingAsync` directly.
    """

    def __init__(
        self,
        async_backing: PersonaStateBackingAsync,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._a = async_backing
        self._loop = loop

    def _submit(self, coro: Any) -> Any:
        # Same-thread re-entry: if we are inside the loop, we cannot
        # use run_coroutine_threadsafe (it would deadlock). Use
        # asyncio.ensure_future + spinning the loop — but the async
        # despawn path is async-native, so this shim is only hit when
        # legacy sync callers reach down into it. For Sprint-Pengine-9
        # we route everything through the async path.
        if asyncio.get_event_loop_policy().get_event_loop() is self._loop:
            raise RuntimeError(
                "_AsyncBackingSyncShim re-entered from inside the "
                "engine loop; async callers must use "
                "PersonaStateBackingAsync directly"
            )
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result()

    def snapshot(self, persona_id: str, state: PersonaStateSnapshot) -> int:
        return self._submit(self._a.snapshot(persona_id, state))

    def restore_latest(self, persona_id: str):
        return self._submit(self._a.restore_latest(persona_id))

    def list_snapshots(self, persona_id: str):
        return self._submit(self._a.list_snapshots(persona_id))

    def atomic_swap_pinned_offset(
        self, persona_id: str, from_offset: int, to_offset: int
    ) -> None:
        self._submit(
            self._a.atomic_swap_pinned_offset(
                persona_id, from_offset, to_offset,
            )
        )


@dataclass
class AsyncEngineTasks:
    """Container for the background asyncio tasks the engine owns."""

    heartbeat: Optional[asyncio.Task] = None
    drill: Optional[asyncio.Task] = None
    subscribe: Optional[asyncio.Task] = None
    # Sprint-Pengine-11 Bug-40 — full-SVID-fetch refetch background task.
    svid_refetch: Optional[asyncio.Task] = None


class AsyncPersonaEngine:
    """Async-native PersonaEngine orchestrator (Sprint-Pengine-9 OI-PEFR-3).

    Lifecycle:

      1. ``boot()`` — async; V-907 pin verify + SVID fetch +
         async state-backing attach.
      2. ``spawn()`` — async; FSM uninstantiated -> spawning -> running.
      3. ``run_until_signal()`` — async; spawn heartbeat + drill +
         subscribe tasks; await SIGTERM/SIGINT.
      4. ``despawn_clean_run()`` — async; runs the P1..P4 protocol.

    The engine is **single-instance** per process; spawning two
    AsyncPersonaEngines for the same ``(org_id, persona_id)`` pair
    violates the spec §3.3 ``max_concurrent_instances=1`` invariant.
    """

    def __init__(
        self,
        env_contract: EnvContract,
        *,
        async_state_backing: Optional[PersonaStateBackingAsync] = None,
        bridge_writer: Optional[BridgeAuditWriter] = None,
        log_sink: TextIO = sys.stderr,
        heartbeat_interval_sec: int = DEFAULT_HEARTBEAT_INTERVAL_SEC,
        drill_interval_sec: int = 7 * 24 * 3600,  # weekly by default
        drill_runner: Optional[Callable[[], Any]] = None,
        subscribe_runner: Optional[Callable[[], Any]] = None,
        subscribe_env: Optional[str] = None,
        llm_hook: Optional[LlmCallHook] = None,
        # Sprint-Pengine-11 Bug-40 — background SVID-refetch loop.
        svid_refetch_interval_sec: int = DEFAULT_SVID_REFETCH_INTERVAL_SEC,
    ) -> None:
        self.env = env_contract
        self.log_sink = log_sink
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.drill_interval_sec = drill_interval_sec
        self.session_id = str(uuid.uuid4())
        self.fsm = LifecycleStateMachine(
            persona_id=env_contract.persona_id,
            org_id=env_contract.org_id,
        )
        self.async_backing: Optional[PersonaStateBackingAsync] = (
            async_state_backing
        )
        self.bridge_writer = bridge_writer
        self.v907_result: Optional[V907VerifyResult] = None
        self.svid_probe: Optional[SvidProbeResult] = None
        self.svid_fetch: Optional[SvidFetchResult] = None
        # Sprint-Pengine-11 Bug-40 — graceful-fallback state (parity
        # with the sync engine fields).
        self.svid_full_fetch_fenced: bool = False
        self.svid_full_fetch_fence_reason: Optional[str] = None
        self.svid_refetch_interval_sec: int = svid_refetch_interval_sec
        # Hermetic-test factory hooks (parity with sync engine).
        self._svid_channel_factory = None
        self._svid_stub_factory = None
        # User-supplied drill / subscribe runners (Sprint-Pengine-10
        # fills these in; for Sprint-Pengine-9 they are optional).
        self._drill_runner = drill_runner
        self._subscribe_runner = subscribe_runner
        self._stop_event: Optional[asyncio.Event] = None
        self.tasks = AsyncEngineTasks()
        self._fenced_to_in_memory = False
        self._in_memory_fallback: Optional[PersonaStateBacking] = None
        # Sprint-Pengine-10 OI-PEFR-6 + OI-PEFR-8: subscribe-loop wiring.
        # ``subscribe_env`` defaults to env var WAKIR_ENV (or "dev").
        # ``llm_hook`` defaults to the Phase-2 EchoReflectionLlmHook.
        self._subscribe_env: str = (
            subscribe_env or os.environ.get("WAKIR_ENV", "dev")
        )
        self._llm_hook: LlmCallHook = llm_hook or EchoReflectionLlmHook()
        self._attached_subscribe_loop: Optional[NatsSubscribeLoop] = None
        self._tracker = TaskProcessingTracker()

    # ------------------------------------------------------------------
    # Helpers.
    # ------------------------------------------------------------------

    def _log(self, payload: dict) -> None:
        payload.setdefault("ts_utc", _utc_now_rfc3339())
        payload.setdefault("component", "wakir-persona-engine")
        payload.setdefault("engine_version", ASYNC_ENGINE_VERSION)
        payload.setdefault("engine_variant", ASYNC_ENGINE_VARIANT)
        self.log_sink.write(json.dumps(payload, sort_keys=True) + "\n")
        self.log_sink.flush()

    def set_svid_factories(
        self,
        channel_factory: Optional[Callable[[str], Any]] = None,
        stub_factory: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        self._svid_channel_factory = channel_factory
        self._svid_stub_factory = stub_factory

    def attach_subscribe_loop(
        self,
        *,
        msg_iter: Any,
        publish_sink: Optional[PublishSink] = None,
        env: Optional[str] = None,
        persona_slug: Optional[str] = None,
    ) -> NatsSubscribeLoop:
        """Wire a hermetic-mode subscribe-loop driven by ``msg_iter``.

        This is the Sprint-Pengine-10 OI-PEFR-6 surface that tests +
        the live-NATS runner share. The engine constructs the
        :class:`NatsSubscribeLoop` from the bridge_writer (must be
        set; call after :meth:`spawn`) + the configured LLM hook.

        Returns the constructed loop so the caller can wire the run
        method via ``set_subscribe_runner`` if it wants to drive the
        loop directly.
        """
        if self.bridge_writer is None:
            raise RuntimeError(
                "attach_subscribe_loop() called before spawn() — "
                "bridge_writer is None"
            )
        cfg = SubscribeLoopConfig(
            env=env or self._subscribe_env,
            persona_slug=persona_slug or self.env.persona_id,
            org_id=self.env.org_id,
            bridge_writer=self.bridge_writer,
            hook=self._llm_hook,
            tracker=self._tracker,
            publish_output=publish_sink is not None,
        )
        loop = NatsSubscribeLoop(
            cfg,
            publish_sink=publish_sink,
            log_sink=self.log_sink,
        )
        self._attached_subscribe_loop = loop

        async def _runner() -> None:
            await loop.run_with_iterator(
                msg_iter, stop_event=self._stop_event,
            )

        self._subscribe_runner = _runner
        return loop

    @property
    def task_tracker(self) -> TaskProcessingTracker:
        """Return the engine's task-processing tracker (audit-helper)."""
        return self._tracker

    @property
    def subscribe_loop(self) -> Optional[NatsSubscribeLoop]:
        """Return the wired subscribe-loop (if any)."""
        return self._attached_subscribe_loop

    # ------------------------------------------------------------------
    # Boot.
    # ------------------------------------------------------------------

    async def boot(self) -> None:
        self._log({
            "level": "INFO",
            "msg": "async-boot-begin",
            "persona_id": self.env.persona_id,
            "org_id": self.env.org_id,
            "session_id": self.session_id,
        })
        # V-907.
        try:
            self.v907_result = verify_v907_pin(
                persona_id=self.env.persona_id,
                axis_a_path=self.env.axis_a_path,
                expected_pin=self.env.v907_expected_pin,
            )
            self._log({
                "level": "INFO",
                "msg": "v907-pin-verified",
                "v907_pin": self.v907_result.pin,
                "v907_pin_mode": self.v907_result.mode,
                "matched": self.v907_result.matched,
            })
        except (PersonaHashComputeError, PersonaHashDriftError):
            raise

        # SVID probe + fetch.
        socket_path = resolve_socket_path(
            {"SPIFFE_ENDPOINT_SOCKET": self.env.spiffe_endpoint_socket}
        )
        self.svid_probe = probe_workload_api_socket(
            org_id=self.env.org_id,
            persona_id=self.env.persona_id,
            socket_path=socket_path,
        )
        self._log({
            "level": "INFO" if self.svid_probe.socket_connectable else "WARN",
            "msg": "svid-workload-api-probe",
            "socket_present": self.svid_probe.socket_present,
            "socket_connectable": self.svid_probe.socket_connectable,
            "expected_spiffe_id": self.svid_probe.expected_spiffe_id,
        })
        # Sprint-Pengine-11 Bug-40 graceful-fallback hardening:
        # any non-V907 failure during full SVID-fetch fences the
        # engine to socket-probe-only mode and lets boot continue.
        # The ``_svid_refetch_loop`` background task will retry
        # every ``svid_refetch_interval_sec`` seconds and emit a
        # ``svid-full-fetch-recovered`` INFO on success.
        if self.svid_probe.socket_connectable:
            try:
                self.svid_fetch = await fetch_workload_svid(
                    org_id=self.env.org_id,
                    persona_id=self.env.persona_id,
                    socket_path=socket_path,
                    channel_factory=self._svid_channel_factory,
                    stub_factory=self._svid_stub_factory,
                )
                self._log({
                    "level": "INFO" if self.svid_fetch.matches_expected else "WARN",
                    "msg": "svid-fetch-completed",
                    "spiffe_id": self.svid_fetch.spiffe_id,
                    "san_uris": list(self.svid_fetch.san_uris),
                    "not_after_utc": self.svid_fetch.not_after_utc,
                    "bind_state_sha256": self.svid_fetch.bind_state_sha256,
                    "trust_domain": self.svid_fetch.trust_domain,
                    "matches_expected": self.svid_fetch.matches_expected,
                    "fetch_elapsed_sec": self.svid_fetch.fetch_elapsed_sec,
                    "soft_cap_exceeded": self.svid_fetch.soft_cap_exceeded,
                })
            except ImportError as exc:
                self.svid_full_fetch_fenced = True
                self.svid_full_fetch_fence_reason = str(exc)
                self._log({
                    "level": "WARN",
                    "msg": "svid-full-fetch-failed-fence-to-probe-only",
                    "reason": str(exc),
                    "exception_type": type(exc).__name__,
                    "fence_mode": "wheel-missing",
                })
            except Exception as exc:  # noqa: BLE001 - intentional broad catch
                # SvidFetchError, AioRpcError, OSError("Broken pipe"),
                # ConnectionError, asyncio.TimeoutError all land here.
                # Bug-40 root cause; engine continues to FSM=running.
                self.svid_full_fetch_fenced = True
                self.svid_full_fetch_fence_reason = str(exc)
                self._log({
                    "level": "WARN",
                    "msg": "svid-full-fetch-failed-fence-to-probe-only",
                    "reason": str(exc),
                    "exception_type": type(exc).__name__,
                    "fence_mode": "fetch-failure",
                })

        # Async state-backing attach.
        if self.async_backing is None:
            await self._select_async_state_backing()

    async def _select_async_state_backing(self) -> None:
        if not self.env.nats_servers:
            self._fenced_to_in_memory = True
            self._in_memory_fallback = InMemoryPersonaStateBacking()
            self._log({
                "level": "WARN",
                "msg": "state-backing-fence-to-in-memory",
                "reason": "WAKIR_NATS_SERVERS empty",
            })
            return
        try:
            backing = NatsKvPersonaStateBackingAsync(
                nats_servers=self.env.nats_servers,
                org_id=self.env.org_id,
            )
            await backing.connect()
            self.async_backing = backing
            self._log({
                "level": "INFO",
                "msg": "state-backing-natskv-active",
                "nats_servers": self.env.nats_servers,
                "org_id": self.env.org_id,
                "persona_state_bucket": self.env.persona_state_bucket,
            })
        except PersonaStateBackingError as exc:
            self._fenced_to_in_memory = True
            self._in_memory_fallback = InMemoryPersonaStateBacking()
            self._log({
                "level": "WARN",
                "msg": "state-backing-fence-to-in-memory",
                "reason": str(exc),
            })

    # ------------------------------------------------------------------
    # Spawn.
    # ------------------------------------------------------------------

    async def spawn(self) -> None:
        if self.v907_result is None:
            raise RuntimeError("spawn() called before boot()")
        self.fsm.transition_to("spawning")
        self._log({
            "level": "INFO",
            "msg": "fsm-transition",
            "from": "uninstantiated",
            "to": "spawning",
        })
        if self.bridge_writer is None:
            self.bridge_writer = BridgeAuditWriter(
                org_id=self.env.org_id,
                persona_id=self.env.persona_id,
                session_id=self.session_id,
                engine_version=ASYNC_ENGINE_VERSION,
                v907_pin=self.v907_result.pin,
                wakir_runtime_sink=self.log_sink,
            )
        first_event = self.bridge_writer.emit(
            output_kind="audit_annotation",
            payload=(
                f"persona-engine-boot-async persona_id={self.env.persona_id} "
                f"org_id={self.env.org_id} variant={ASYNC_ENGINE_VARIANT}"
            ).encode("utf-8"),
        )
        self._log({
            "level": "INFO",
            "msg": "engineering-output-emission-first",
            "event_payload_sha256": first_event.output_payload_sha256,
            "step_index": first_event.step_index,
        })
        self.fsm.transition_to("running")
        self._log({
            "level": "INFO",
            "msg": "fsm-transition",
            "from": "spawning",
            "to": "running",
        })

    # ------------------------------------------------------------------
    # Run loop.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Sprint-Pengine-11 Bug-40 — graceful-fallback refetch.
    # ------------------------------------------------------------------

    async def attempt_svid_refetch(self) -> bool:
        """Re-run the full SVID fetch.

        Returns ``True`` if the fetch succeeded (engine un-fences if
        it was fenced) and ``False`` otherwise. Emits one of:

        - ``svid-full-fetch-recovered`` INFO — fenced engine recovered.
        - ``svid-fetch-refreshed`` INFO — refresh on an already-healthy
          engine (e.g. periodic re-pull near the not-after horizon).
        - ``svid-full-fetch-retry-failed`` WARN — fetch still fails;
          engine stays fenced.
        """
        if self.svid_probe is None:
            return False
        socket_path = resolve_socket_path(
            {"SPIFFE_ENDPOINT_SOCKET": self.env.spiffe_endpoint_socket}
        )
        if not self.svid_probe.socket_connectable:
            # Re-probe in case SPIRE-Agent came up between boot and now.
            self.svid_probe = probe_workload_api_socket(
                org_id=self.env.org_id,
                persona_id=self.env.persona_id,
                socket_path=socket_path,
            )
            if not self.svid_probe.socket_connectable:
                return False
        try:
            new_fetch = await fetch_workload_svid(
                org_id=self.env.org_id,
                persona_id=self.env.persona_id,
                socket_path=socket_path,
                channel_factory=self._svid_channel_factory,
                stub_factory=self._svid_stub_factory,
            )
        except Exception as exc:  # noqa: BLE001 - parity with boot
            self._log({
                "level": "WARN",
                "msg": "svid-full-fetch-retry-failed",
                "reason": str(exc),
                "exception_type": type(exc).__name__,
            })
            self.svid_full_fetch_fence_reason = str(exc)
            return False
        was_fenced = self.svid_full_fetch_fenced
        self.svid_fetch = new_fetch
        self.svid_full_fetch_fenced = False
        self.svid_full_fetch_fence_reason = None
        self._log({
            "level": "INFO",
            "msg": "svid-full-fetch-recovered" if was_fenced else "svid-fetch-refreshed",
            "spiffe_id": new_fetch.spiffe_id,
            "matches_expected": new_fetch.matches_expected,
            "fetch_elapsed_sec": new_fetch.fetch_elapsed_sec,
        })
        return True

    async def _svid_refetch_loop(self) -> None:
        """Background task: every ``svid_refetch_interval_sec`` retry
        the SVID fetch if the engine is fenced. Exits cleanly on
        stop-event or task cancellation.
        """
        assert self._stop_event is not None
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.svid_refetch_interval_sec,
                    )
                    # Stop-event fired — exit loop.
                    return
                except asyncio.TimeoutError:
                    pass
                # Only retry while we are fenced. A future enhancement
                # may also re-pull SVIDs proactively near not-after,
                # but for Sprint-Pengine-11 the recovery path is the
                # explicit goal.
                if self.svid_full_fetch_fenced:
                    try:
                        await self.attempt_svid_refetch()
                    except Exception as exc:  # noqa: BLE001 - logged only
                        self._log({
                            "level": "ERROR",
                            "msg": "svid-refetch-loop-error",
                            "reason": str(exc),
                            "exception_type": type(exc).__name__,
                        })
        except asyncio.CancelledError:
            return

    async def _heartbeat_loop(self) -> None:
        assert self._stop_event is not None
        try:
            while not self._stop_event.is_set():
                if self.bridge_writer is not None:
                    self.bridge_writer.emit(
                        output_kind="audit_annotation",
                        payload=b"heartbeat-async",
                    )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.heartbeat_interval_sec,
                    )
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            return

    async def _drill_loop(self) -> None:
        assert self._stop_event is not None
        if self._drill_runner is None:
            return
        try:
            while not self._stop_event.is_set():
                try:
                    res = self._drill_runner()
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as exc:  # pragma: no cover - logged only
                    self._log({
                        "level": "ERROR",
                        "msg": "drill-runner-error",
                        "reason": str(exc),
                    })
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.drill_interval_sec,
                    )
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            return

    async def _subscribe_loop(self) -> None:
        assert self._stop_event is not None
        if self._subscribe_runner is None:
            return
        try:
            res = self._subscribe_runner()
            if asyncio.iscoroutine(res):
                await res
        except asyncio.CancelledError:
            return
        except Exception as exc:  # pragma: no cover - logged only
            self._log({
                "level": "ERROR",
                "msg": "subscribe-runner-error",
                "reason": str(exc),
            })

    async def run_until_signal(self) -> None:
        loop = asyncio.get_event_loop()
        self._stop_event = asyncio.Event()

        def _handle_signal(signum: int) -> None:
            self._log({
                "level": "INFO",
                "msg": "signal-received-async",
                "signum": signum,
            })
            self._stop_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _handle_signal, sig)
            except (NotImplementedError, RuntimeError):
                # Not supported on all platforms / inside threads;
                # tests stop the engine via ``request_stop()``.
                pass

        self.tasks.heartbeat = asyncio.create_task(
            self._heartbeat_loop(), name="async-engine-heartbeat",
        )
        self.tasks.drill = asyncio.create_task(
            self._drill_loop(), name="async-engine-drill",
        )
        self.tasks.subscribe = asyncio.create_task(
            self._subscribe_loop(), name="async-engine-subscribe",
        )
        # Sprint-Pengine-11 Bug-40 — SVID-refetch background loop.
        self.tasks.svid_refetch = asyncio.create_task(
            self._svid_refetch_loop(), name="async-engine-svid-refetch",
        )
        await self._stop_event.wait()
        # Cooperative shutdown.
        for t in (
            self.tasks.heartbeat,
            self.tasks.drill,
            self.tasks.subscribe,
            self.tasks.svid_refetch,
        ):
            if t is not None:
                t.cancel()
        for t in (
            self.tasks.heartbeat,
            self.tasks.drill,
            self.tasks.subscribe,
            self.tasks.svid_refetch,
        ):
            if t is not None:
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    def request_stop(self) -> None:
        """Signal the run loop to terminate (test hook + signal-handler)."""
        if self._stop_event is not None:
            self._stop_event.set()

    # ------------------------------------------------------------------
    # Despawn-clean.
    # ------------------------------------------------------------------

    async def despawn_clean_run(self) -> None:
        from .despawn_clean import DespawnCleanWorkflow

        sync_backing = self._sync_backing_view()
        wf = DespawnCleanWorkflow(
            state_machine=self.fsm,
            state_backing=sync_backing,
        )
        result = wf.run()
        self._log({
            "level": "INFO",
            "msg": "despawn-clean-completed-async",
            "phases": [
                {
                    "phase": p.phase.value,
                    "terminal_status": p.terminal_status,
                    "elapsed_sec": p.elapsed_sec,
                    "audit_annotation": p.audit_annotation,
                }
                for p in result.phases
            ],
            "total_elapsed_sec": result.total_elapsed_sec,
            "final_state": result.final_state,
        })
        # Close async backing (graceful TCP-FIN on the NATS connection).
        if self.async_backing is not None:
            try:
                close = getattr(self.async_backing, "close", None)
                if close is not None:
                    res = close()
                    if asyncio.iscoroutine(res):
                        await res
            except Exception:  # pragma: no cover - best-effort close
                pass

    def _sync_backing_view(self) -> PersonaStateBacking:
        """Return a sync :class:`PersonaStateBacking` for the despawn-
        clean workflow (which is sync-only for Sprint-Pengine-9).

        If the engine fenced to in-memory we return the in-memory
        fallback directly; otherwise we wrap the async backing in
        :class:`_AsyncBackingSyncShim`.
        """
        if self._fenced_to_in_memory and self._in_memory_fallback is not None:
            return self._in_memory_fallback
        if self.async_backing is None:
            # Defensive: should not happen if boot() ran.
            return InMemoryPersonaStateBacking()
        loop = asyncio.get_event_loop()
        return _AsyncBackingSyncShim(self.async_backing, loop)
