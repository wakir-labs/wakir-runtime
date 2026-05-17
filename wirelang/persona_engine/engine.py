# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""PersonaEngine orchestrator (Sprint-Pengine-8, v0.2.0-pilot).

Wires the six subsystems imported from this package into the
spawn-session control flow:

  1. ``lifecycle_state_machine`` — six-state FSM (spec §3.3).
  2. ``state_backing`` — persistence trait (spec §3.7.5).
  3. ``v907_verify`` — pin-verify gate (spec §3.7.2.2 #1 / §5).
  4. ``svid_workload_identity`` — Workload-API probe (Zone-L, R3).
  5. ``bridge_audit_writer`` — Doppelbetrieb double-sink.
  6. ``recovery_workflow`` + ``despawn_clean`` — R1..R4 / P1..P4.

The engine is **synchronous** for v0.2.0-pilot; async-orchestration
(asyncio + grpcio for SVID-fetch) lands on Sprint-Pengine-9.

Env-var contract (spec §"Env var contract")
-------------------------------------------

Required:

- ``WAKIR_PERSONA_ID``
- ``WAKIR_ORG_ID``
- ``WAKIR_NATS_SERVERS``
- ``SPIFFE_ENDPOINT_SOCKET``

Optional:

- ``WAKIR_PERSONA_STATE_BUCKET`` — production NATS-KV bucket name;
  if absent the engine fences to InMemoryPersonaStateBacking.
- ``WAKIR_PERSONA_V907_EXPECTED_PIN`` — operator-supplied pin; if
  absent the engine computes-only (no drift gate).
- ``WAKIR_PERSONA_AXIS_A_PATH`` — override the axis-A bind-mount
  path (default ``/etc/wakir/persona/<persona_id>.md``).
- ``WAKIR_PERSONA_AXIS_C_PATH`` — override the axis-C path
  (default ``/etc/wakir/persona/<persona_id>.json``).
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, TextIO

from .bridge_audit_writer import (
    BridgeAuditWriter,
    EngineeringOutputEvent,
)
from .lifecycle_state_machine import (
    LifecycleStateMachine,
    InvalidTransitionError,
)
from .observability import PersonaEngineObservability
from .state_backing import (
    InMemoryPersonaStateBacking,
    NatsKvPersonaStateBacking,
    PersonaStateBacking,
    PersonaStateBackingError,
)
from .svid_workload_identity import (
    SvidFetchError,
    SvidFetchResult,
    SvidProbeResult,
    WorkloadApiClient,
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


ENGINE_VERSION = "0.5.0-pilot"
ENGINE_VARIANT = "real"
DEFAULT_PERSONA_DEF_DIR = Path("/etc/wakir/persona")
DEFAULT_HEARTBEAT_INTERVAL_SEC = 30
DEFAULT_SVID_REFETCH_INTERVAL_SEC = 300  # 5 min — Sprint-Pengine-11 Bug-40


# ---------------------------------------------------------------------------
# Env resolution.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnvContract:
    """Resolved env-var contract bundle (spec §"Env var contract")."""

    persona_id: str
    org_id: str
    nats_servers: str
    spiffe_endpoint_socket: str
    persona_state_bucket: Optional[str]
    v907_expected_pin: Optional[str]
    axis_a_path: Path
    axis_c_path: Path


class EnvContractError(RuntimeError):
    """Raised when a required env var is missing or malformed."""


def resolve_env(
    persona_id: Optional[str] = None,
    *,
    env: Optional[dict] = None,
) -> EnvContract:
    """Resolve the env-var contract. ``persona_id`` from CLI takes
    precedence over ``WAKIR_PERSONA_ID``; either MUST be set."""
    if env is None:
        env = dict(os.environ)
    pid = persona_id or env.get("WAKIR_PERSONA_ID")
    if not pid:
        raise EnvContractError(
            "WAKIR_PERSONA_ID env var (or --persona-slug) is required"
        )
    org_id = env.get("WAKIR_ORG_ID")
    if not org_id:
        raise EnvContractError("WAKIR_ORG_ID env var is required")
    nats_servers = env.get("WAKIR_NATS_SERVERS", "")
    spiffe_endpoint = env.get(
        "SPIFFE_ENDPOINT_SOCKET",
        "unix:///run/spire/agent-sockets/api.sock",
    )
    state_bucket = env.get("WAKIR_PERSONA_STATE_BUCKET")
    v907_pin = env.get("WAKIR_PERSONA_V907_EXPECTED_PIN")
    axis_a = Path(
        env.get(
            "WAKIR_PERSONA_AXIS_A_PATH",
            str(DEFAULT_PERSONA_DEF_DIR / f"{pid}.md"),
        )
    )
    axis_c = Path(
        env.get(
            "WAKIR_PERSONA_AXIS_C_PATH",
            str(DEFAULT_PERSONA_DEF_DIR / f"{pid}.json"),
        )
    )
    return EnvContract(
        persona_id=pid,
        org_id=org_id,
        nats_servers=nats_servers,
        spiffe_endpoint_socket=spiffe_endpoint,
        persona_state_bucket=state_bucket,
        v907_expected_pin=v907_pin,
        axis_a_path=axis_a,
        axis_c_path=axis_c,
    )


# ---------------------------------------------------------------------------
# Engineering-output emission (spec §"engineering output").
# ---------------------------------------------------------------------------


def _utc_now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Engine.
# ---------------------------------------------------------------------------


class PersonaEngine:
    """The wakir-persona-engine real-implementation orchestrator.

    Lifecycle:

      1. ``boot`` — resolve env, verify V-907 pin, probe SVID socket,
         attach state-backing.
      2. ``spawn`` — FSM uninstantiated -> spawning -> running; emit
         the first EngineeringOutputEvent (which is the audit signal
         that the engine is REAL not STUB).
      3. ``run_until_signal`` — block on SIGTERM/SIGINT; emit
         heartbeat audit annotations.
      4. ``despawn_clean`` — run the P1..P4 protocol; FSM
         running -> despawning -> uninstantiated.
    """

    def __init__(
        self,
        env_contract: EnvContract,
        *,
        state_backing: Optional[PersonaStateBacking] = None,
        bridge_writer: Optional[BridgeAuditWriter] = None,
        log_sink: TextIO = sys.stderr,
        heartbeat_interval_sec: int = DEFAULT_HEARTBEAT_INTERVAL_SEC,
        observability: Optional[PersonaEngineObservability] = None,
    ) -> None:
        self.env = env_contract
        self.log_sink = log_sink
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.session_id = str(uuid.uuid4())
        # Observability facade. Sprint-SRE Tag-15 instrumentation seam;
        # if no facade is injected, construct a structured-log-only
        # default that reuses the engine's existing log_sink (so the
        # audit substrate already in use stays populated).
        if observability is None:
            self.observability = PersonaEngineObservability(log_sink=log_sink)
        else:
            self.observability = observability
        self.fsm = LifecycleStateMachine(
            persona_id=env_contract.persona_id,
            org_id=env_contract.org_id,
        )
        # State backing — try NATS-KV first, fence to InMemory if
        # nats-py is missing (parity with the wakir-provisioner
        # BUCKET_FAMILIES probe try-chain).
        if state_backing is not None:
            self.backing = state_backing
        else:
            self.backing = self._select_state_backing()
        self.bridge_writer = bridge_writer  # set during spawn (needs v907_pin)
        self.v907_result: Optional[V907VerifyResult] = None
        self.svid_probe: Optional[SvidProbeResult] = None
        self.svid_fetch: Optional[SvidFetchResult] = None
        # Sprint-Pengine-11 Bug-40 — graceful-fallback state.
        # When the full SVID-fetch fails at boot the engine fences to
        # socket-probe-only mode (parity with the Pengine-8 NATS-py-
        # fence-to-in-memory pattern) and records the fence reason so
        # a future refetch can flip the flag back via the recovery
        # log "svid-full-fetch-recovered".
        self.svid_full_fetch_fenced: bool = False
        self.svid_full_fetch_fence_reason: Optional[str] = None
        # OI-PEFR-2 injection hooks for hermetic tests.
        self._svid_channel_factory = None
        self._svid_stub_factory = None
        self._stop_requested = False
        # Sprint-SRE Tag-15 — spawn-latency timer. Started at boot() entry,
        # stopped at the first engineering-output emit inside spawn().
        # Stays None until boot() runs so observability records a clean
        # "no spawn-latency" signal if boot fails before the timer starts.
        self._spawn_latency_start_monotonic: Optional[float] = None
        # Bind observability with persona/org/session metadata. The
        # SPIFFE-ID is filled in during boot() once the SVID-probe runs.
        self.observability.bind_workload_identity(
            spiffe_id=None,
            persona_id=env_contract.persona_id,
            org_id=env_contract.org_id,
            session_id=self.session_id,
        )

    # ------------------------------------------------------------------
    # Helpers.
    # ------------------------------------------------------------------

    def _log(self, payload: dict) -> None:
        payload.setdefault("ts_utc", _utc_now_rfc3339())
        payload.setdefault("component", "wakir-persona-engine")
        payload.setdefault("engine_version", ENGINE_VERSION)
        payload.setdefault("engine_variant", ENGINE_VARIANT)
        self.log_sink.write(json.dumps(payload, sort_keys=True) + "\n")
        self.log_sink.flush()

    def set_svid_factories(
        self,
        channel_factory: Optional[object] = None,
        stub_factory: Optional[object] = None,
    ) -> None:
        """Inject SVID-fetch channel + stub factories (hermetic tests).

        Used by ``test_svid_workload_identity.py`` to drive the
        FetchX509SVID call with a fake stream that yields a forged
        X509SVIDResponse byte frame, without binding to grpcio.
        """
        self._svid_channel_factory = channel_factory
        self._svid_stub_factory = stub_factory

    def _run_svid_fetch(self, socket_path: str) -> SvidFetchResult:
        """Drive :func:`fetch_workload_svid` on a private event loop.

        We do not assume an asyncio loop is already running — the
        sync engine is the only caller. The async-engine wrapper
        (OI-PEFR-3) uses :func:`fetch_workload_svid` directly with
        the orchestrator's existing loop.
        """
        import asyncio as _aio

        return _aio.run(
            fetch_workload_svid(
                org_id=self.env.org_id,
                persona_id=self.env.persona_id,
                socket_path=socket_path,
                channel_factory=self._svid_channel_factory,
                stub_factory=self._svid_stub_factory,
            )
        )

    def _select_state_backing(self) -> PersonaStateBacking:
        # Tag-17: ENV-gated Rust-backend switch
        # (WAKIR_STATE_BACKING_BACKEND). Default is python (current
        # behaviour, opt-in switch). Rust-bound values fall back
        # gracefully to python when the binary is unavailable; the
        # per-decision audit-log surfaces both the request and the
        # actually-chosen backend. Tag-17 substance: production-
        # default switch, no disruptive migration.
        from .rust_backend_switch import (
            StateBackingBackend,
            build_state_backing,
            resolve_state_backing_backend,
        )

        chosen_backend, _decision = resolve_state_backing_backend(
            env=None, log_sink=self.log_sink
        )
        if chosen_backend is not StateBackingBackend.PYTHON:
            # Operator explicitly opted into Rust; build the
            # subprocess-bridge.
            self._log({
                "level": "INFO",
                "msg": "state-backing-rust-subprocess-active",
                "backend": chosen_backend.value,
            })
            return build_state_backing(
                chosen_backend,
                nats_servers=self.env.nats_servers,
                org_id=self.env.org_id,
                persona_state_bucket=self.env.persona_state_bucket,
            )
        # Python path — original Pengine-9 logic, unchanged.
        if not self.env.nats_servers:
            self._log({
                "level": "WARN",
                "msg": "state-backing-fence-to-in-memory",
                "reason": "WAKIR_NATS_SERVERS empty",
            })
            return InMemoryPersonaStateBacking()
        try:
            backing = NatsKvPersonaStateBacking(
                nats_servers=self.env.nats_servers,
                org_id=self.env.org_id,
            )
        except PersonaStateBackingError as exc:
            self._log({
                "level": "WARN",
                "msg": "state-backing-fence-to-in-memory",
                "reason": str(exc),
            })
            return InMemoryPersonaStateBacking()
        # Sprint-Pengine-9 OI-PEFR-1: NATS-KV asyncio-backed state-backing
        # is now real. Log the upgrade so Doppelbetrieb-Vergleichs-
        # operators can see the v0.2.0-pilot WARN-fence is closed.
        self._log({
            "level": "INFO",
            "msg": "state-backing-natskv-active",
            "nats_servers": self.env.nats_servers,
            "org_id": self.env.org_id,
            "persona_state_bucket": self.env.persona_state_bucket,
        })
        return backing

    # ------------------------------------------------------------------
    # Spawn flow.
    # ------------------------------------------------------------------

    def boot(self) -> None:
        """Pre-spawn verification (V-907 pin + SVID probe)."""
        self._spawn_latency_start_monotonic = time.monotonic()
        self._log({
            "level": "INFO",
            "msg": "boot-begin",
            "persona_id": self.env.persona_id,
            "org_id": self.env.org_id,
            "session_id": self.session_id,
        })
        # Tag-17: resolve recovery-backend choice up-front. Default is
        # python (current behaviour, opt-in switch). Per-decision log
        # surfaces the choice + latency. Recovery construction itself
        # stays lazy (drill-scheduler / despawn_clean own that surface);
        # the engine just records the decision so the Doppelbetrieb-
        # comparison set has a deterministic per-boot anchor.
        from .rust_backend_switch import (
            resolve_bridge_diff_backend,
            resolve_fsm_backend,
            resolve_recovery_backend,
            resolve_v907_verify_backend,
        )

        try:
            self._recovery_backend, self._recovery_backend_decision = (
                resolve_recovery_backend(env=None, log_sink=self.log_sink)
            )
        except Exception as exc:  # noqa: BLE001 — strict env-validation
            self._log({
                "level": "ERROR",
                "msg": "backend-switch-validation-failed",
                "domain": "recovery",
                "error": str(exc),
            })
            raise
        # Tag-18: resolve FSM-backend choice up-front, parallel to
        # recovery + state_backing. Default is python (current
        # behaviour, opt-in switch). The engine keeps the Python
        # `LifecycleStateMachine` instance alive in ``self.fsm`` during
        # Phase-3b Doppelbetrieb — the per-boot decision audit-record
        # is what the cross-lang comparison harness consumes.
        # Phase-3c cutover (out of scope for Tag-18) will swap the
        # `self.fsm` instance behind the same public surface via
        # :func:`build_fsm`.
        try:
            self._fsm_backend, self._fsm_backend_decision = (
                resolve_fsm_backend(env=None, log_sink=self.log_sink)
            )
        except Exception as exc:  # noqa: BLE001 — strict env-validation
            self._log({
                "level": "ERROR",
                "msg": "backend-switch-validation-failed",
                "domain": "fsm",
                "error": str(exc),
            })
            raise
        # Tag-19: resolve V-907-verify-backend choice up-front, parallel
        # to recovery + state_backing + fsm. Default is python (current
        # behaviour, opt-in switch). V-907 is the hash-determinism
        # anchor (spec §5) — the per-decision audit-record is critical
        # for the Phase-3b Doppelbetrieb comparison set. The engine
        # keeps :func:`verify_v907_pin` Python-backed during Phase-3b;
        # Phase-3c cutover (out of scope here) swaps in the Rust
        # subprocess-bridge via :func:`build_v907_verify` once Tomás
        # (Zone-K) has co-signed the binary-hash-pinning step.
        try:
            (
                self._v907_verify_backend,
                self._v907_verify_backend_decision,
            ) = resolve_v907_verify_backend(
                env=None, log_sink=self.log_sink
            )
        except Exception as exc:  # noqa: BLE001 — strict env-validation
            self._log({
                "level": "ERROR",
                "msg": "backend-switch-validation-failed",
                "domain": "v907_verify",
                "error": str(exc),
            })
            raise
        # Tag-20: resolve bridge-diff-backend choice up-front, parallel
        # to recovery + state_backing + fsm + v907_verify. Default is
        # python (current behaviour, opt-in switch). Bridge-diff is the
        # Doppelbetrieb-comparison oracle (Phase-3a/3b cross-lang parity
        # gate) — the per-decision audit-record is critical for the
        # Phase-3b comparison set because any silent drift between
        # Python and Rust diff outputs would corrupt the entire
        # Doppelbetrieb truth claim. The engine keeps the Python
        # authority active during Phase-3b; Phase-3c cutover (out of
        # scope here) swaps in the Rust subprocess-bridge via
        # :func:`build_bridge_diff`. This is the **5th** BackendDecision
        # record emitted per boot (Tag-17 recovery + state_backing +
        # Tag-18 fsm + Tag-19 v907_verify + Tag-20 bridge_diff).
        try:
            (
                self._bridge_diff_backend,
                self._bridge_diff_backend_decision,
            ) = resolve_bridge_diff_backend(
                env=None, log_sink=self.log_sink
            )
        except Exception as exc:  # noqa: BLE001 — strict env-validation
            self._log({
                "level": "ERROR",
                "msg": "backend-switch-validation-failed",
                "domain": "bridge_diff",
                "error": str(exc),
            })
            raise
        # Open the persona_engine.boot span — exits on the first error
        # or when boot() returns.
        boot_span_cm = self.observability.span(
            "persona_engine.boot",
            attributes={
                "persona_id": self.env.persona_id,
                "org_id": self.env.org_id,
                "session_id": self.session_id,
            },
        )
        boot_span_cm.__enter__()
        boot_span_exit_ok = False
        try:
            self._boot_internal()
            boot_span_exit_ok = True
        finally:
            # Pass exception context through if boot_internal raised.
            if boot_span_exit_ok:
                boot_span_cm.__exit__(None, None, None)
            else:
                exc_type, exc_val, exc_tb = sys.exc_info()
                boot_span_cm.__exit__(exc_type, exc_val, exc_tb)

    def _boot_internal(self) -> None:
        """Internal boot sequence — wrapped by :meth:`boot` for spans."""
        # V-907 pin verify with timing.
        v907_start = time.monotonic()
        v907_outcome = "compute_error"
        try:
            self.v907_result = verify_v907_pin(
                persona_id=self.env.persona_id,
                axis_a_path=self.env.axis_a_path,
                expected_pin=self.env.v907_expected_pin,
            )
            v907_outcome = "ok"
            self._log({
                "level": "INFO",
                "msg": "v907-pin-verified",
                "v907_pin": self.v907_result.pin,
                "v907_pin_mode": self.v907_result.mode,
                "matched": self.v907_result.matched,
            })
            self.observability.record_v907_verify_duration(
                duration_seconds=time.monotonic() - v907_start,
                mode=self.v907_result.mode,
                matched=self.v907_result.matched,
            )
        except PersonaHashDriftError as exc:
            self._log({
                "level": "ERROR",
                "msg": "v907-pin-drift",
                "expected": exc.expected,
                "computed": exc.computed,
            })
            self.observability.record_v907_verify_duration(
                duration_seconds=time.monotonic() - v907_start,
                mode="drift",
            )
            raise
        except PersonaHashComputeError as exc:
            self._log({
                "level": "ERROR",
                "msg": "v907-pin-compute-failed",
                "detail": str(exc),
            })
            self.observability.record_v907_verify_duration(
                duration_seconds=time.monotonic() - v907_start,
                mode="compute_error",
            )
            raise

        # SVID workload-API probe (boot-gate; Sprint-Pengine-9 keeps
        # this as the fast pre-fetch gate).
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
        # Sprint-Pengine-9 OI-PEFR-2: full SVID-fetch over gRPC once
        # the boot-gate probe confirmed the socket is connectable.
        # Failures are logged WARN and the engine continues; the
        # probe alone is sufficient for the boot-go-no-go decision.
        #
        # Sprint-Pengine-11 Bug-40 graceful-fallback hardening:
        # the SPIRE-Agent can return any of grpc.aio.AioRpcError,
        # grpc.RpcError, asyncio.TimeoutError, or — under certain
        # SPIRE-1.14 selector-mismatch conditions — a generic
        # OSError("Broken pipe"). None of these inherit from
        # SvidFetchError (the svid_workload_identity.py converter
        # closes that gap, but we keep the broad catch here as
        # defence-in-depth). Any non-V907 boot-fetch error fences
        # the engine to socket-probe-only mode; boot continues and
        # the engine transitions to FSM=running. A later refetch
        # (driven by AsyncPersonaEngine._svid_refetch_loop) can
        # recover and emit "svid-full-fetch-recovered" INFO.
        if self.svid_probe.socket_connectable:
            try:
                self.svid_fetch = self._run_svid_fetch(socket_path)
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
                # Bind the real SPIFFE-ID as the observability
                # correlation-key once the fetch succeeded.
                self.observability.bind_workload_identity(
                    spiffe_id=self.svid_fetch.spiffe_id,
                    persona_id=self.env.persona_id,
                    org_id=self.env.org_id,
                    session_id=self.session_id,
                )
            except (PersonaHashDriftError, PersonaHashComputeError):
                # V-907 errors are NEVER swallowed — they are the
                # boot-go-no-go gate and must propagate.
                raise
            except ImportError as exc:
                # grpcio/cryptography wheel missing — engine fences
                # to socket-probe-only mode.
                self.svid_full_fetch_fenced = True
                self.svid_full_fetch_fence_reason = str(exc)
                self._log({
                    "level": "WARN",
                    "msg": "svid-full-fetch-failed-fence-to-probe-only",
                    "reason": str(exc),
                    "exception_type": type(exc).__name__,
                    "fence_mode": "wheel-missing",
                })
                self.observability.record_svid_fetch_failure(
                    fence_mode="wheel-missing",
                )
            except Exception as exc:  # noqa: BLE001 - intentional broad catch
                # Any other failure (SvidFetchError, AioRpcError,
                # OSError broken-pipe, ConnectionError, ...) fences
                # the engine to socket-probe-only mode without
                # crashing boot. Bug-40 root cause.
                self.svid_full_fetch_fenced = True
                self.svid_full_fetch_fence_reason = str(exc)
                self._log({
                    "level": "WARN",
                    "msg": "svid-full-fetch-failed-fence-to-probe-only",
                    "reason": str(exc),
                    "exception_type": type(exc).__name__,
                    "fence_mode": "fetch-failure",
                })
                self.observability.record_svid_fetch_failure(
                    fence_mode="fetch-failure",
                )

    def attempt_svid_refetch(self) -> bool:
        """Re-run the full SVID fetch on a fenced engine.

        Returns ``True`` if the fetch succeeded and the engine
        un-fenced (emits ``svid-full-fetch-recovered`` INFO).
        Returns ``False`` if the fetch still fails (emits a WARN
        with the new failure reason; the engine stays fenced).

        This is the sync-engine retry hook for Sprint-Pengine-11
        Bug-40. The AsyncPersonaEngine drives this in a background
        task; the sync engine relies on the operator (or a future
        signal-driven refetch trigger) to invoke it.
        """
        if self.svid_probe is None:
            # boot() never ran; nothing to retry.
            return False
        if not self.svid_probe.socket_connectable:
            # Re-probe the socket first — the SPIRE-Agent might
            # have come up between boot and refetch.
            socket_path = resolve_socket_path(
                {"SPIFFE_ENDPOINT_SOCKET": self.env.spiffe_endpoint_socket}
            )
            self.svid_probe = probe_workload_api_socket(
                org_id=self.env.org_id,
                persona_id=self.env.persona_id,
                socket_path=socket_path,
            )
            if not self.svid_probe.socket_connectable:
                return False
        socket_path = resolve_socket_path(
            {"SPIFFE_ENDPOINT_SOCKET": self.env.spiffe_endpoint_socket}
        )
        try:
            new_fetch = self._run_svid_fetch(socket_path)
        except Exception as exc:  # noqa: BLE001 - parity with boot
            self._log({
                "level": "WARN",
                "msg": "svid-full-fetch-retry-failed",
                "reason": str(exc),
                "exception_type": type(exc).__name__,
            })
            self.svid_full_fetch_fence_reason = str(exc)
            return False
        self.svid_fetch = new_fetch
        was_fenced = self.svid_full_fetch_fenced
        self.svid_full_fetch_fenced = False
        self.svid_full_fetch_fence_reason = None
        self._log({
            "level": "INFO" if was_fenced else "INFO",
            "msg": "svid-full-fetch-recovered" if was_fenced else "svid-fetch-refreshed",
            "spiffe_id": new_fetch.spiffe_id,
            "matches_expected": new_fetch.matches_expected,
            "fetch_elapsed_sec": new_fetch.fetch_elapsed_sec,
        })
        return True

    def spawn(self) -> None:
        """Run the spawning -> running transition pair.

        Wires the BridgeAuditWriter once the V-907 pin is known.
        Emits the first EngineeringOutputEvent (audit signal that the
        engine is REAL).
        """
        if self.v907_result is None:
            raise RuntimeError("spawn() called before boot()")
        with self.observability.span(
            "persona_engine.spawn",
            attributes={
                "persona_id": self.env.persona_id,
                "org_id": self.env.org_id,
                "session_id": self.session_id,
            },
        ):
            # FSM: uninstantiated -> spawning -> running.
            self.fsm.transition_to("spawning")
            self._log({
                "level": "INFO",
                "msg": "fsm-transition",
                "from": "uninstantiated",
                "to": "spawning",
            })
            self.observability.record_fsm_transition(
                from_state="uninstantiated",
                to_state="spawning",
                accepted=True,
            )
            # Wire BridgeAuditWriter.
            if self.bridge_writer is None:
                self.bridge_writer = BridgeAuditWriter(
                    org_id=self.env.org_id,
                    persona_id=self.env.persona_id,
                    session_id=self.session_id,
                    engine_version=ENGINE_VERSION,
                    v907_pin=self.v907_result.pin,
                    wakir_runtime_sink=self.log_sink,
                )
            # Emit the first engineering-output event — the audit signal
            # that the Doppelbetrieb-Vergleichs-Clock can start counting.
            first_event = self.bridge_writer.emit(
                output_kind="audit_annotation",
                payload=(
                    f"persona-engine-boot persona_id={self.env.persona_id} "
                    f"org_id={self.env.org_id} variant={ENGINE_VARIANT}"
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
            self.observability.record_fsm_transition(
                from_state="spawning",
                to_state="running",
                accepted=True,
            )
            # Spawn-latency clock stops here: from boot() entry to the
            # first engineering-output event — the audit signal the
            # Doppelbetrieb-Vergleichs-Clock cares about.
            if self._spawn_latency_start_monotonic is not None:
                self.observability.record_spawn_latency(
                    duration_seconds=time.monotonic()
                    - self._spawn_latency_start_monotonic,
                    outcome="success",
                )

    def run_until_signal(self) -> None:
        """Block on SIGTERM/SIGINT; emit periodic heartbeat events.

        Heartbeats are audit_annotation kind so the Doppelbetrieb-
        Vergleich does not include them in the engineering-output
        comparison-test-set (per Migration-Playbook §5).
        """
        def _handle(signum: int, _frame: object) -> None:
            self._log({
                "level": "INFO",
                "msg": "signal-received",
                "signum": signum,
            })
            self._stop_requested = True

        signal.signal(signal.SIGTERM, _handle)
        signal.signal(signal.SIGINT, _handle)
        while not self._stop_requested:
            if self.bridge_writer is not None:
                self.bridge_writer.emit(
                    output_kind="audit_annotation",
                    payload=b"heartbeat",
                )
            # Responsive sleep — wake every 1s to check stop flag.
            for _ in range(self.heartbeat_interval_sec):
                if self._stop_requested:
                    break
                time.sleep(1.0)

    def despawn_clean_run(self) -> None:
        """Run the P1..P4 despawn-clean protocol.

        Imports despawn_clean lazily to avoid circular imports.
        """
        from .despawn_clean import DespawnCleanWorkflow

        wf = DespawnCleanWorkflow(
            state_machine=self.fsm,
            state_backing=self.backing,
        )
        result = wf.run()
        self._log({
            "level": "INFO",
            "msg": "despawn-clean-completed",
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
