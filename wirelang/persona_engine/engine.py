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
from .state_backing import (
    InMemoryPersonaStateBacking,
    NatsKvPersonaStateBacking,
    PersonaStateBacking,
    PersonaStateBackingError,
)
from .svid_workload_identity import (
    SvidProbeResult,
    probe_workload_api_socket,
    resolve_socket_path,
)
from .v907_verify import (
    PersonaHashComputeError,
    PersonaHashDriftError,
    V907VerifyResult,
    verify_v907_pin,
)


ENGINE_VERSION = "0.2.0-pilot"
ENGINE_VARIANT = "real"
DEFAULT_PERSONA_DEF_DIR = Path("/etc/wakir/persona")
DEFAULT_HEARTBEAT_INTERVAL_SEC = 30


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
    ) -> None:
        self.env = env_contract
        self.log_sink = log_sink
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.session_id = str(uuid.uuid4())
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
        self._stop_requested = False

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

    def _select_state_backing(self) -> PersonaStateBacking:
        if not self.env.nats_servers:
            self._log({
                "level": "WARN",
                "msg": "state-backing-fence-to-in-memory",
                "reason": "WAKIR_NATS_SERVERS empty",
            })
            return InMemoryPersonaStateBacking()
        try:
            return NatsKvPersonaStateBacking(
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

    # ------------------------------------------------------------------
    # Spawn flow.
    # ------------------------------------------------------------------

    def boot(self) -> None:
        """Pre-spawn verification (V-907 pin + SVID probe)."""
        self._log({
            "level": "INFO",
            "msg": "boot-begin",
            "persona_id": self.env.persona_id,
            "org_id": self.env.org_id,
            "session_id": self.session_id,
        })
        # V-907 pin verify.
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
        except PersonaHashDriftError as exc:
            self._log({
                "level": "ERROR",
                "msg": "v907-pin-drift",
                "expected": exc.expected,
                "computed": exc.computed,
            })
            raise
        except PersonaHashComputeError as exc:
            self._log({
                "level": "ERROR",
                "msg": "v907-pin-compute-failed",
                "detail": str(exc),
            })
            raise

        # SVID workload-API probe.
        self.svid_probe = probe_workload_api_socket(
            org_id=self.env.org_id,
            persona_id=self.env.persona_id,
            socket_path=resolve_socket_path(
                {"SPIFFE_ENDPOINT_SOCKET": self.env.spiffe_endpoint_socket}
            ),
        )
        self._log({
            "level": "INFO" if self.svid_probe.socket_connectable else "WARN",
            "msg": "svid-workload-api-probe",
            "socket_present": self.svid_probe.socket_present,
            "socket_connectable": self.svid_probe.socket_connectable,
            "expected_spiffe_id": self.svid_probe.expected_spiffe_id,
        })

    def spawn(self) -> None:
        """Run the spawning -> running transition pair.

        Wires the BridgeAuditWriter once the V-907 pin is known.
        Emits the first EngineeringOutputEvent (audit signal that the
        engine is REAL).
        """
        if self.v907_result is None:
            raise RuntimeError("spawn() called before boot()")
        # FSM: uninstantiated -> spawning -> running.
        self.fsm.transition_to("spawning")
        self._log({
            "level": "INFO",
            "msg": "fsm-transition",
            "from": "uninstantiated",
            "to": "spawning",
        })
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
