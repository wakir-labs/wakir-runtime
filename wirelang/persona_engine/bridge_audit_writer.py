# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Bridge-audit-writer (Doppelbetrieb-Shadow output bridging).

Sprint-1 Tag-4 (PR #19, commit ``2c1f3a6``) introduced the bridge-
audit-writer: a structured envelope that mirrors every engineering
output emission to **two sinks** so the Doppelbetrieb-Shadow phase
can compare Pre-Framework Tomás-spawn output against the
wakir-runtime persona-engine output byte-for-byte.

This module is the engine-side caller. The two sinks are:

1. **Pre-Framework sink.** A Markdown append to
   ``/var/lib/wakir/persona/<persona_id>/bridge-audit.md`` — a
   pre-existing convention from the Pre-Framework Tomás spawn that
   keeps human-readable conversation tails. The persona-engine
   appends one section per output emission with a heading line + the
   JCS-canonical envelope rendered as a fenced JSON block.

2. **Wakir-Runtime sink.** A structured-log JSON envelope on stderr
   that the Quadlet ``podman logs`` substrate collects. The audit
   substrate (separate from this module) snapshots the log into
   the NATS-KV state-pack bucket via the Sprint-9 Tag-1 forwarder
   chain; we do not bind NATS directly here (NATS-write is the
   ``state_backing`` module's job).

Stub vs. real
-------------

The 0.1.0-pilot stub binary emits **no** engineering output; the
heartbeat log line is not output, it is process-presence telemetry.
The 0.2.0-pilot real engine emits one EngineeringOutputEvent per
tool call (currently: per spawn-session step). The Doppelbetrieb-
Vergleich-4-Wochen-Clock starts effectively when the first real
EngineeringOutputEvent lands.

JCS envelope shape
------------------

::

    {
      "event_kind": "engineering_output",
      "org_id": "acme",
      "persona_id": "tomas",
      "session_id": "<uuid-or-counter>",
      "step_index": 0,
      "ts_utc": "2026-05-15T15:00:00Z",
      "output_kind": "tool_call|reply|audit_annotation",
      "output_payload_sha256": "sha256:<64hex>",
      "engine_version": "0.2.0-pilot",
      "v907_pin": "sha256:<64hex>"
    }

The envelope **does NOT carry the payload bytes** — only their hash.
The payload itself goes to the persona's workspace-state hash bucket
(Tag-N+ binding); the audit substrate hashes-only by design to keep
the Doppelbetrieb-Vergleich substrate lean.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional, TextIO


# ---------------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------------

#: Default Pre-Framework bridge-audit Markdown sink path.
DEFAULT_PREFRAMEWORK_SINK_TEMPLATE = (
    "/var/lib/wakir/persona/{persona_id}/bridge-audit.md"
)

#: Engineering-output envelope schema-version (single-source-of-truth
#: for the wirelang.schemas registry).
ENGINEERING_OUTPUT_SCHEMA = "wakir.persona.engineering-output/1"


# ---------------------------------------------------------------------------
# Envelope.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineeringOutputEvent:
    """One emission event in the Doppelbetrieb-Shadow audit stream."""

    org_id: str
    persona_id: str
    session_id: str
    step_index: int
    output_kind: str  # "tool_call" | "reply" | "audit_annotation"
    output_payload_sha256: str  # "sha256:<64hex>"
    engine_version: str
    v907_pin: str
    ts_utc: str  # RFC 3339 UTC second-precision

    def to_jcs_bytes(self) -> bytes:
        """JCS-canonical byte form (alphabetical key order)."""
        return json.dumps(
            {
                "engine_version": self.engine_version,
                "event_kind": "engineering_output",
                "org_id": self.org_id,
                "output_kind": self.output_kind,
                "output_payload_sha256": self.output_payload_sha256,
                "persona_id": self.persona_id,
                "schema": ENGINEERING_OUTPUT_SCHEMA,
                "session_id": self.session_id,
                "step_index": self.step_index,
                "ts_utc": self.ts_utc,
                "v907_pin": self.v907_pin,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def payload_sha256(self) -> str:
        """SHA-256 of the envelope's JCS bytes; "sha256:<64hex>"."""
        return "sha256:" + hashlib.sha256(self.to_jcs_bytes()).hexdigest()


def sha256_hex(payload: bytes) -> str:
    """Return the SHA-256 of ``payload`` as ``"sha256:<64hex>"``."""
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _utc_now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Writer.
# ---------------------------------------------------------------------------


class BridgeAuditWriter:
    """Double-sink writer: Pre-Framework Markdown + Wakir-Runtime JSON.

    Single-writer per persona; not async-safe. The engine instantiates
    one writer per spawn-session and the per-emission append is
    synchronous on stderr (so ``podman logs`` collects in order).
    """

    def __init__(
        self,
        org_id: str,
        persona_id: str,
        session_id: str,
        engine_version: str,
        v907_pin: str,
        *,
        preframework_sink_path: Optional[Path] = None,
        wakir_runtime_sink: TextIO = sys.stderr,
        bridge_mode: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
        rust_engine_adapter: Optional[Callable[..., None]] = None,
    ) -> None:
        self.org_id = org_id
        self.persona_id = persona_id
        self.session_id = session_id
        self.engine_version = engine_version
        self.v907_pin = v907_pin
        if preframework_sink_path is None:
            preframework_sink_path = Path(
                DEFAULT_PREFRAMEWORK_SINK_TEMPLATE.format(
                    persona_id=persona_id
                )
            )
        self.preframework_sink_path = preframework_sink_path
        self.wakir_runtime_sink = wakir_runtime_sink
        # Bridge-mode resolution: explicit constructor pin overrides
        # env; env defaults to os.environ. Imported lazily to avoid a
        # circular import with bridge_audit_triangle.
        if bridge_mode is not None:
            self.bridge_mode = bridge_mode
        else:
            from .bridge_audit_triangle import resolve_bridge_mode

            self.bridge_mode = resolve_bridge_mode(env)
        # Rust-engine adapter is invoked in 3-way mode only. The
        # adapter signature mirrors the EngineeringOutputEvent emit
        # contract — a no-op default keeps 2-way callers unaffected.
        self.rust_engine_adapter = rust_engine_adapter
        self._step_counter = 0

    def emit(
        self,
        output_kind: str,
        payload: bytes,
        *,
        ts_utc: Optional[str] = None,
    ) -> EngineeringOutputEvent:
        """Emit one engineering-output event to both sinks.

        Returns the resulting :class:`EngineeringOutputEvent` so the
        caller can correlate (e.g. attach the envelope's JCS bytes to a
        marker-stack append).
        """
        if output_kind not in ("tool_call", "reply", "audit_annotation"):
            raise ValueError(
                f"unknown output_kind {output_kind!r}; "
                "valid: tool_call, reply, audit_annotation"
            )
        evt = EngineeringOutputEvent(
            org_id=self.org_id,
            persona_id=self.persona_id,
            session_id=self.session_id,
            step_index=self._step_counter,
            output_kind=output_kind,
            output_payload_sha256=sha256_hex(payload),
            engine_version=self.engine_version,
            v907_pin=self.v907_pin,
            ts_utc=ts_utc or _utc_now_rfc3339(),
        )
        self._step_counter += 1
        self._write_preframework_sink(evt)
        self._write_wakir_runtime_sink(evt)
        self._invoke_rust_engine_adapter_if_3way(evt, payload)
        return evt

    # ------------------------------------------------------------------
    # 3-way Rust-engine-stub invocation
    # ------------------------------------------------------------------

    def _invoke_rust_engine_adapter_if_3way(
        self, evt: EngineeringOutputEvent, payload: bytes
    ) -> None:
        """Invoke the Rust-engine adapter when bridge-mode is 3way.

        In 2-way mode this is a no-op. In 3-way mode the adapter is
        invoked with the just-emitted :class:`EngineeringOutputEvent`
        plus the original payload bytes so the Rust engine can produce
        its own envelope for the cross-check triangle.

        The adapter is a fire-and-forget hook from the writer's
        perspective: the actual triangle cross-check is run separately
        by callers that want to gate emissions on consistency. The
        writer itself does not block on the adapter's output — the
        bridge-audit-writer's job is to land the two Python sinks
        deterministically, not to orchestrate Phase-3a cross-checking.

        Exceptions from the adapter are swallowed (same operator-
        substrate-only failure mode as the Pre-Framework sink) so a
        broken Rust-engine adapter never breaks the engineering-output
        path. The adapter contract documents that for hard-gate use
        callers should use :func:`bridge_audit_triangle.cross_check_triangle`
        directly instead of relying on this hook.
        """
        from .bridge_audit_triangle import BridgeMode

        if self.bridge_mode != BridgeMode.THREE_WAY:
            return
        if self.rust_engine_adapter is None:
            return
        try:
            self.rust_engine_adapter(evt, payload)
        except Exception:
            # Operator-substrate-only failure; the two Python sinks
            # already landed and the triangle is run separately.
            pass

    # ------------------------------------------------------------------

    def _write_preframework_sink(self, evt: EngineeringOutputEvent) -> None:
        # The Pre-Framework sink is a Markdown append. If the parent
        # directory does not exist (sandbox mode) we silently skip —
        # the wakir-runtime sink alone is sufficient for hermetic
        # tests; the Pre-Framework sink is operator-substrate.
        try:
            self.preframework_sink_path.parent.mkdir(
                parents=True, exist_ok=True
            )
        except (OSError, PermissionError):
            return
        try:
            with self.preframework_sink_path.open("a", encoding="utf-8") as fh:
                fh.write(
                    "\n"
                    f"## step {evt.step_index} — {evt.output_kind} "
                    f"({evt.ts_utc})\n\n"
                )
                fh.write("```json\n")
                fh.write(evt.to_jcs_bytes().decode("utf-8"))
                fh.write("\n```\n")
        except (OSError, PermissionError):
            # Pre-Framework sink unreachable; the Wakir-Runtime sink
            # still records the event so the audit substrate is not
            # gap-prone. Operator-substrate-only failure.
            pass

    def _write_wakir_runtime_sink(
        self, evt: EngineeringOutputEvent
    ) -> None:
        self.wakir_runtime_sink.write(
            evt.to_jcs_bytes().decode("utf-8") + "\n"
        )
        self.wakir_runtime_sink.flush()
