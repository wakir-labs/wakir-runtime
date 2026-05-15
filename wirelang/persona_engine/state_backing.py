# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Persona-state-backing trait surface (spec §3.7.5).

Python pendant of the Rust ``PersonaStateBacking`` trait declared in
``persona-engine-format-spec.md`` §3.7.5.1. Two bindings:

- :class:`InMemoryPersonaStateBacking` — hermetic-test binding; mirrors
  the Rust ``InMemoryPersonaStateBacking`` HashMap shape.
- :class:`NatsKvPersonaStateBacking` — production binding against the
  ``wakir-persona-state-<org_id>-<persona_id>`` bucket family declared
  in ``wirelang.persona.persona_state_kv``. Imports ``nats.aio.client``
  lazily inside the constructor; if the wheel is missing the backing
  refuses to construct and the engine falls back to in-memory mode
  with a WARN-level audit annotation (parity with the
  ``wakir-provisioner`` family-probe try-chain).

Snapshot envelope
-----------------

:class:`PersonaStateSnapshot` mirrors the Rust struct of the same
name (spec §3.7.5.2): five fields, RFC 3339 second-precision UTC
timestamp, sha256-prefixed hex digests. The envelope is JCS-
canonicalisable via :func:`snapshot_to_jcs_bytes` for byte-equal
storage across the two backings.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Spec §3.7.5.2 — snapshot envelope.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PersonaStateSnapshot:
    """Spec §3.7.5.2 snapshot envelope.

    Fields are byte-stable per JCS canonicalisation: alphabetical key
    order, no insignificant whitespace, RFC 3339 UTC second-precision
    timestamp.
    """

    persona_hash: str  # "sha256:<64hex>"
    audit_trace_offset: int
    capability_token_ids: Tuple[str, ...]
    snapshot_at_utc: str  # "2026-05-15T14:30:00Z"
    workspace_state_hash: str  # "sha256:<64hex>"


def snapshot_to_jcs_bytes(snapshot: PersonaStateSnapshot) -> bytes:
    """JCS-canonicalise a snapshot to a byte-stable form.

    Stdlib-only implementation of the JCS-relevant rules used here:
    alphabetical key order, no extra whitespace, integer / string
    rendering matches RFC 8785. Capability-token-id tuple is rendered
    as a JSON array preserving insertion order (capability-token
    creation order is the canonical sort).
    """
    canonical = {
        "audit_trace_offset": snapshot.audit_trace_offset,
        "capability_token_ids": list(snapshot.capability_token_ids),
        "persona_hash": snapshot.persona_hash,
        "snapshot_at_utc": snapshot.snapshot_at_utc,
        "workspace_state_hash": snapshot.workspace_state_hash,
    }
    return json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def snapshot_payload_sha256(snapshot: PersonaStateSnapshot) -> str:
    """SHA-256 of the JCS canonical bytes; "sha256:<64hex>"."""
    return "sha256:" + hashlib.sha256(snapshot_to_jcs_bytes(snapshot)).hexdigest()


class PersonaStateBackingError(RuntimeError):
    """Errors raised by any backing implementation."""


# ---------------------------------------------------------------------------
# Spec §3.7.5.1 — abstract trait surface.
# ---------------------------------------------------------------------------


class PersonaStateBacking:
    """Abstract trait (spec §3.7.5.1).

    Concrete bindings override :meth:`snapshot`, :meth:`restore_latest`,
    :meth:`list_snapshots`, :meth:`atomic_swap_pinned_offset`.
    """

    def snapshot(
        self, persona_id: str, state: PersonaStateSnapshot
    ) -> int:
        """Persist ``state`` and return its new audit_trace_offset.

        Idempotent: re-snapshotting a byte-identical state returns the
        existing offset (no new write).
        """
        raise NotImplementedError

    def restore_latest(
        self, persona_id: str
    ) -> Optional[PersonaStateSnapshot]:
        """Return the latest snapshot for ``persona_id`` or None
        (cold start)."""
        raise NotImplementedError

    def list_snapshots(self, persona_id: str) -> List[int]:
        """Return all snapshot offsets for ``persona_id``, oldest first."""
        raise NotImplementedError

    def atomic_swap_pinned_offset(
        self,
        persona_id: str,
        from_offset: int,
        to_offset: int,
    ) -> None:
        """Atomically swap pinned offset; used by §3.7.3 migrate-version."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Spec §3.7.5.3 — InMemoryPersonaStateBacking (hermetic-test binding).
# ---------------------------------------------------------------------------


class InMemoryPersonaStateBacking(PersonaStateBacking):
    """Pure-stdlib HashMap-backed binding for hermetic tests.

    Single-writer per-persona: callers MUST NOT spawn parallel
    snapshot calls for the same ``persona_id``. The cross-persona
    operations are independent (different keys in the underlying
    map), but the per-persona offset counter is not atomic across
    threads. Tests run single-threaded; production uses NATS-KV.
    """

    def __init__(self) -> None:
        # persona_id -> ordered list of (offset, snapshot)
        self._snapshots: Dict[str, List[Tuple[int, PersonaStateSnapshot]]] = {}
        # persona_id -> pinned offset (None until first pin)
        self._pinned: Dict[str, Optional[int]] = {}
        # persona_id -> last offset assigned (monotonic per persona)
        self._next_offset: Dict[str, int] = {}
        self._lock = threading.RLock()

    def snapshot(
        self, persona_id: str, state: PersonaStateSnapshot
    ) -> int:
        with self._lock:
            entries = self._snapshots.setdefault(persona_id, [])
            # Idempotence: byte-equal latest snapshot -> return its offset.
            if entries:
                latest_offset, latest_snap = entries[-1]
                if snapshot_to_jcs_bytes(latest_snap) == snapshot_to_jcs_bytes(state):
                    return latest_offset
            next_off = self._next_offset.get(persona_id, 0) + 1
            self._next_offset[persona_id] = next_off
            entries.append((next_off, state))
            return next_off

    def restore_latest(
        self, persona_id: str
    ) -> Optional[PersonaStateSnapshot]:
        with self._lock:
            entries = self._snapshots.get(persona_id, [])
            if not entries:
                return None
            return entries[-1][1]

    def list_snapshots(self, persona_id: str) -> List[int]:
        with self._lock:
            entries = self._snapshots.get(persona_id, [])
            return [off for off, _ in entries]

    def atomic_swap_pinned_offset(
        self,
        persona_id: str,
        from_offset: int,
        to_offset: int,
    ) -> None:
        with self._lock:
            current = self._pinned.get(persona_id)
            if current is not None and current != from_offset:
                raise PersonaStateBackingError(
                    f"atomic_swap_pinned_offset({persona_id!r}): "
                    f"expected from_offset={from_offset}, "
                    f"current pinned offset={current}"
                )
            offsets = [off for off, _ in self._snapshots.get(persona_id, [])]
            if to_offset not in offsets:
                raise PersonaStateBackingError(
                    f"atomic_swap_pinned_offset({persona_id!r}): "
                    f"to_offset={to_offset} not in known snapshots {offsets}"
                )
            self._pinned[persona_id] = to_offset


# ---------------------------------------------------------------------------
# Spec §3.7.5.3 — NatsKvPersonaStateBacking (production binding stub).
# ---------------------------------------------------------------------------


class NatsKvPersonaStateBacking(PersonaStateBacking):
    """Production binding against the
    ``wakir-persona-state-<org_id>-<persona_id>`` bucket family.

    The constructor lazily imports ``nats-py``. If the wheel is
    missing the constructor raises :class:`PersonaStateBackingError`
    with a clear remediation hint; the engine catches this and
    fences over to :class:`InMemoryPersonaStateBacking` with a
    structured-log WARN annotation (Sprint-Pengine-7 Tag-5 PEP-562
    pattern, parity with the wakir-provisioner BUCKET_FAMILIES probe).

    The implementation is **intentionally narrow** for v0.2.0-pilot:
    snapshot writes a single per-offset key
    ``state-pack/<offset>`` carrying the JCS-canonical bytes;
    restore_latest does a per-bucket get with the highest offset;
    list_snapshots scans the bucket; atomic_swap_pinned_offset
    writes to ``state-pack/__pinned__`` with NATS-KV
    Compare-And-Swap semantics. The bucket name is computed via
    :func:`wirelang.persona.persona_state_kv_constants.bucket_name_for_pair`.
    """

    def __init__(
        self,
        nats_servers: str,
        org_id: str,
        *,
        connect_timeout_sec: float = 5.0,
    ) -> None:
        # Lazy import — if nats-py is missing on the runtime wheel set,
        # the engine retries in InMemory mode.
        try:
            import nats  # type: ignore[import-not-found]  # noqa: F401
        except ImportError as exc:
            raise PersonaStateBackingError(
                "nats-py wheel missing; cannot construct "
                "NatsKvPersonaStateBacking. Engine will fence to "
                "InMemoryPersonaStateBacking with a WARN audit "
                "annotation. Remediation: rebuild the wakir-persona-"
                "engine image with nats-py>=2.6 in the wheel set."
            ) from exc
        self._nats_servers: str = nats_servers
        self._org_id: str = org_id
        self._connect_timeout_sec: float = connect_timeout_sec
        # Lazy connection — opened on first call (production engine
        # wires this through asyncio; the v0.2.0-pilot binding is
        # synchronous and uses a thread-pool wrapper).
        self._client = None
        self._js = None

    def _bucket_name(self, persona_id: str) -> str:
        # Defer to the canonical constants shim so the bucket-name
        # rule is single-sourced (Sprint-Pengine-7 Tag-5 OI-PILOT-2).
        from wirelang.persona.persona_state_kv_constants import (
            bucket_name_for_pair,
        )

        return bucket_name_for_pair(self._org_id, persona_id)

    def snapshot(
        self, persona_id: str, state: PersonaStateSnapshot
    ) -> int:
        # v0.2.0-pilot: synchronous NATS connect is heavy; for the
        # initial Doppelbetrieb-Shadow phase the engine uses
        # InMemory and writes a per-key copy to NATS-KV on
        # successful snapshot. Full asyncio binding lands on the
        # Sprint-Pengine-9 axis.
        raise PersonaStateBackingError(
            "NatsKvPersonaStateBacking.snapshot is deferred to "
            "Sprint-Pengine-9; v0.2.0-pilot uses InMemory + "
            "per-event audit-write through bridge_audit_writer."
        )

    def restore_latest(
        self, persona_id: str
    ) -> Optional[PersonaStateSnapshot]:
        raise PersonaStateBackingError(
            "NatsKvPersonaStateBacking.restore_latest is deferred to "
            "Sprint-Pengine-9; v0.2.0-pilot uses InMemory."
        )

    def list_snapshots(self, persona_id: str) -> List[int]:
        raise PersonaStateBackingError(
            "NatsKvPersonaStateBacking.list_snapshots is deferred to "
            "Sprint-Pengine-9; v0.2.0-pilot uses InMemory."
        )

    def atomic_swap_pinned_offset(
        self,
        persona_id: str,
        from_offset: int,
        to_offset: int,
    ) -> None:
        raise PersonaStateBackingError(
            "NatsKvPersonaStateBacking.atomic_swap_pinned_offset is "
            "deferred to Sprint-Pengine-9; v0.2.0-pilot uses InMemory."
        )
