# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Persona-state-backing trait surface (spec §3.7.5).

Python pendant of the Rust ``PersonaStateBacking`` trait declared in
``persona-engine-format-spec.md`` §3.7.5.1. Three bindings:

- :class:`InMemoryPersonaStateBacking` — hermetic-test binding; mirrors
  the Rust ``InMemoryPersonaStateBacking`` HashMap shape.
- :class:`NatsKvPersonaStateBacking` — production sync-facade binding
  that wraps an asyncio NATS-KV client in a private event loop
  (preserves the v0.2.0-pilot synchronous engine contract). Sprint-
  Pengine-9 closes the v0.2.0-pilot snapshot/restore stubs.
- :class:`NatsKvPersonaStateBackingAsync` — Sprint-Pengine-9
  asyncio-native binding consumed by the
  :mod:`wirelang.persona_engine.engine_async` orchestrator
  (OI-PEFR-3). Same write semantics as the sync binding; no thread
  hop on the hot path.

Snapshot envelope
-----------------

:class:`PersonaStateSnapshot` mirrors the Rust struct of the same
name (spec §3.7.5.2): five fields, RFC 3339 second-precision UTC
timestamp, sha256-prefixed hex digests. The envelope is JCS-
canonicalisable via :func:`snapshot_to_jcs_bytes` for byte-equal
storage across the three backings.

State-pack key layout
---------------------

The NATS-KV bucket layout is fixed by spec §3.7.5.4:

  - ``state-pack/<offset>``       — per-offset JCS-canonical snapshot
                                    (offsets are zero-padded to 20
                                    decimal digits for KV-sort order).
  - ``state-pack/latest``         — pointer to the highest-offset
                                    snapshot key.
  - ``state-pack/__pinned__``     — current pinned-offset (used by
                                    §3.7.3 migrate-version mechanic).
  - ``state-pack/__next_offset__``— monotonic counter for new
                                    snapshots; compare-and-swap on
                                    write.

The layout is single-sourced via :data:`STATE_PACK_KEY_PREFIX` and
the helper :func:`offset_key`.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

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


def snapshot_from_jcs_bytes(blob: bytes) -> PersonaStateSnapshot:
    """Inverse of :func:`snapshot_to_jcs_bytes`. Raises ValueError on
    malformed input (corrupt KV value)."""
    obj = json.loads(blob.decode("utf-8"))
    required = {
        "audit_trace_offset",
        "capability_token_ids",
        "persona_hash",
        "snapshot_at_utc",
        "workspace_state_hash",
    }
    missing = required - set(obj.keys())
    if missing:
        raise ValueError(f"snapshot JCS payload missing keys: {sorted(missing)}")
    return PersonaStateSnapshot(
        persona_hash=str(obj["persona_hash"]),
        audit_trace_offset=int(obj["audit_trace_offset"]),
        capability_token_ids=tuple(str(x) for x in obj["capability_token_ids"]),
        snapshot_at_utc=str(obj["snapshot_at_utc"]),
        workspace_state_hash=str(obj["workspace_state_hash"]),
    )


class PersonaStateBackingError(RuntimeError):
    """Errors raised by any backing implementation."""


# ---------------------------------------------------------------------------
# Spec §3.7.5.4 — state-pack KV key layout.
# ---------------------------------------------------------------------------

#: Top-level prefix for all persona-state-bucket keys.
STATE_PACK_KEY_PREFIX = "state-pack"

#: Width of the zero-padded offset segment (20 digits gives 10^20
#: snapshots, well above any plausible single-persona lifetime).
OFFSET_KEY_WIDTH = 20

#: Sentinel keys (spec §3.7.5.4).
PINNED_KEY = f"{STATE_PACK_KEY_PREFIX}/__pinned__"
NEXT_OFFSET_KEY = f"{STATE_PACK_KEY_PREFIX}/__next_offset__"
LATEST_KEY = f"{STATE_PACK_KEY_PREFIX}/latest"


def offset_key(offset: int) -> str:
    """Render a per-offset snapshot key. The 20-digit zero-pad makes
    the natural NATS-KV listing order match numeric offset order."""
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset!r}")
    return f"{STATE_PACK_KEY_PREFIX}/{offset:0{OFFSET_KEY_WIDTH}d}"


def offset_from_key(key: str) -> int:
    """Inverse of :func:`offset_key`. Raises ValueError on malformed
    input (e.g. ``state-pack/__pinned__``)."""
    if not key.startswith(f"{STATE_PACK_KEY_PREFIX}/"):
        raise ValueError(f"not a state-pack key: {key!r}")
    suffix = key[len(STATE_PACK_KEY_PREFIX) + 1:]
    if not suffix.isdigit():
        raise ValueError(f"sentinel key, not an offset: {key!r}")
    return int(suffix)


# ---------------------------------------------------------------------------
# Spec §3.7.5.1 — abstract trait surface (sync).
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
# Spec §3.7.5.1 — abstract trait surface (async).
# ---------------------------------------------------------------------------


class PersonaStateBackingAsync:
    """Async variant of :class:`PersonaStateBacking` (Sprint-Pengine-9
    OI-PEFR-3 surface).

    Concrete async bindings override the same four operations as the
    sync trait but with ``async def`` signatures. The engine_async
    orchestrator (:mod:`wirelang.persona_engine.engine_async`)
    consumes this trait.
    """

    async def snapshot(
        self, persona_id: str, state: PersonaStateSnapshot
    ) -> int:
        raise NotImplementedError

    async def restore_latest(
        self, persona_id: str
    ) -> Optional[PersonaStateSnapshot]:
        raise NotImplementedError

    async def list_snapshots(self, persona_id: str) -> List[int]:
        raise NotImplementedError

    async def atomic_swap_pinned_offset(
        self,
        persona_id: str,
        from_offset: int,
        to_offset: int,
    ) -> None:
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

    # Convenience read accessor used by tests (no spec equivalent).
    def get_pinned(self, persona_id: str) -> Optional[int]:
        with self._lock:
            return self._pinned.get(persona_id)


# ---------------------------------------------------------------------------
# Spec §3.7.5.3 — NatsKvPersonaStateBackingAsync (Sprint-Pengine-9 OI-PEFR-1).
# ---------------------------------------------------------------------------


class NatsKvPersonaStateBackingAsync(PersonaStateBackingAsync):
    """Async production binding against the
    ``wakir-persona-state-<org_id>-<persona_id>`` bucket family.

    Uses ``nats.aio.client.Client`` + ``JetStreamContext.key_value``
    for the per-bucket asyncio access. The bucket name is computed
    via :func:`wirelang.persona.persona_state_kv_constants.bucket_name_for_pair`.

    Connection lifecycle
    --------------------
    The class is connection-owning: :meth:`connect` opens the NATS
    client + JetStream context, :meth:`close` tears them down. Tests
    should always wrap usage in an ``async with`` block via
    :meth:`__aenter__` / :meth:`__aexit__`.

    Hermetic test posture
    ---------------------
    The tests in ``test_state_backing_async.py`` inject a stub
    ``nats_client_factory`` and ``js_factory`` so the binding runs
    without a live NATS server. The factories return objects
    implementing the minimal subset of ``nats-py`` 2.6+ surface
    (``key_value``, ``KeyValue.put``, ``KeyValue.get``,
    ``KeyValue.keys``, ``KeyValue.update`` with revision check).
    """

    def __init__(
        self,
        nats_servers: str,
        org_id: str,
        *,
        connect_timeout_sec: float = 5.0,
        nats_client_factory: Optional[Any] = None,
        js_factory: Optional[Any] = None,
    ) -> None:
        self._nats_servers: str = nats_servers
        self._org_id: str = org_id
        self._connect_timeout_sec: float = connect_timeout_sec
        # Factory hooks for hermetic tests; if None we lazy-import nats.
        self._nats_client_factory = nats_client_factory
        self._js_factory = js_factory
        self._client: Any = None
        self._js: Any = None
        # Per-bucket KeyValue handle cache.
        self._kv_cache: Dict[str, Any] = {}
        # Per-persona asyncio lock to serialise CAS writes
        # (next-offset + latest pointer + per-offset key).
        self._locks: Dict[str, asyncio.Lock] = {}

    async def __aenter__(self) -> "NatsKvPersonaStateBackingAsync":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def connect(self) -> None:
        if self._client is not None:
            return
        if self._nats_client_factory is not None:
            self._client = await self._nats_client_factory(
                self._nats_servers,
                self._connect_timeout_sec,
            )
        else:
            try:
                import nats  # type: ignore[import-not-found]
            except ImportError as exc:
                raise PersonaStateBackingError(
                    "nats-py wheel missing; cannot construct "
                    "NatsKvPersonaStateBackingAsync. Remediation: "
                    "rebuild the wakir-persona-engine image with "
                    "the persona-engine-runtime pyproject extra "
                    "(adds nats-py>=2.6)."
                ) from exc
            self._client = await nats.connect(
                self._nats_servers,
                connect_timeout=self._connect_timeout_sec,
            )
        if self._js_factory is not None:
            self._js = await self._js_factory(self._client)
        else:
            self._js = self._client.jetstream()

    async def close(self) -> None:
        if self._client is None:
            return
        try:
            await self._client.close()
        finally:
            self._client = None
            self._js = None
            self._kv_cache.clear()

    def _bucket_name(self, persona_id: str) -> str:
        # The constants-only shim
        # ``wirelang.persona.persona_state_kv_constants`` does not
        # expose ``bucket_name_for_pair`` by design (see its
        # module docstring: callers requiring the strict pair-
        # shape "MUST use ``bucket_name_for_pair`` directly (and
        # accept the crypto-bearing transitive import)"). The
        # async backing always runs in the persona-engine runtime
        # context where the full ``persona_state_kv`` module is
        # already imported via the NATS-KV substrate, so the
        # transitive crypto dependency is already paid for.
        from wirelang.persona.persona_state_kv import (
            bucket_name_for_pair,
        )

        return bucket_name_for_pair(self._org_id, persona_id)

    async def _kv_for(self, persona_id: str) -> Any:
        bucket = self._bucket_name(persona_id)
        if bucket in self._kv_cache:
            return self._kv_cache[bucket]
        if self._js is None:
            raise PersonaStateBackingError(
                "NatsKvPersonaStateBackingAsync not connected; call connect()"
            )
        kv = await self._js.key_value(bucket)
        self._kv_cache[bucket] = kv
        return kv

    def _lock_for(self, persona_id: str) -> asyncio.Lock:
        lock = self._locks.get(persona_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[persona_id] = lock
        return lock

    async def snapshot(
        self, persona_id: str, state: PersonaStateSnapshot
    ) -> int:
        kv = await self._kv_for(persona_id)
        async with self._lock_for(persona_id):
            # Idempotence: read latest; if byte-equal return its offset.
            existing_latest = await self._read_latest_offset(kv)
            if existing_latest is not None:
                latest_snap = await self._read_offset(kv, existing_latest)
                if latest_snap is not None and (
                    snapshot_to_jcs_bytes(latest_snap)
                    == snapshot_to_jcs_bytes(state)
                ):
                    return existing_latest
            # Allocate next offset (CAS on __next_offset__).
            next_off = await self._allocate_next_offset(kv)
            # Write per-offset key.
            await kv.put(offset_key(next_off), snapshot_to_jcs_bytes(state))
            # Update latest pointer.
            await kv.put(LATEST_KEY, str(next_off).encode("utf-8"))
            return next_off

    async def restore_latest(
        self, persona_id: str
    ) -> Optional[PersonaStateSnapshot]:
        kv = await self._kv_for(persona_id)
        offset = await self._read_latest_offset(kv)
        if offset is None:
            return None
        return await self._read_offset(kv, offset)

    async def list_snapshots(self, persona_id: str) -> List[int]:
        kv = await self._kv_for(persona_id)
        keys = await kv.keys()
        offsets: List[int] = []
        for k in keys:
            try:
                offsets.append(offset_from_key(k))
            except ValueError:
                # Sentinel keys (__pinned__, __next_offset__, latest).
                continue
        offsets.sort()
        return offsets

    async def atomic_swap_pinned_offset(
        self,
        persona_id: str,
        from_offset: int,
        to_offset: int,
    ) -> None:
        kv = await self._kv_for(persona_id)
        async with self._lock_for(persona_id):
            current = await self._read_pinned(kv)
            if current is not None and current != from_offset:
                raise PersonaStateBackingError(
                    f"atomic_swap_pinned_offset({persona_id!r}): "
                    f"expected from_offset={from_offset}, "
                    f"current pinned offset={current}"
                )
            # Verify to_offset exists.
            snap = await self._read_offset(kv, to_offset)
            if snap is None:
                raise PersonaStateBackingError(
                    f"atomic_swap_pinned_offset({persona_id!r}): "
                    f"to_offset={to_offset} not present in bucket"
                )
            await kv.put(PINNED_KEY, str(to_offset).encode("utf-8"))

    # ------------------------------------------------------------------
    # Low-level KV helpers.
    # ------------------------------------------------------------------

    async def _read_latest_offset(self, kv: Any) -> Optional[int]:
        try:
            entry = await kv.get(LATEST_KEY)
        except Exception:
            return None
        if entry is None:
            return None
        value = _entry_value(entry)
        if not value:
            return None
        try:
            return int(value.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None

    async def _read_pinned(self, kv: Any) -> Optional[int]:
        try:
            entry = await kv.get(PINNED_KEY)
        except Exception:
            return None
        if entry is None:
            return None
        value = _entry_value(entry)
        if not value:
            return None
        try:
            return int(value.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None

    async def _read_offset(
        self, kv: Any, offset: int
    ) -> Optional[PersonaStateSnapshot]:
        try:
            entry = await kv.get(offset_key(offset))
        except Exception:
            return None
        if entry is None:
            return None
        value = _entry_value(entry)
        if not value:
            return None
        return snapshot_from_jcs_bytes(value)

    async def _allocate_next_offset(self, kv: Any) -> int:
        # Read-then-CAS — relies on KV revision semantics. In hermetic
        # stubs the CAS check is implemented in the stub's update().
        try:
            entry = await kv.get(NEXT_OFFSET_KEY)
        except Exception:
            entry = None
        current = 0
        revision = 0
        if entry is not None:
            value = _entry_value(entry)
            if value:
                try:
                    current = int(value.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    current = 0
            revision = getattr(entry, "revision", 0)
        nxt = current + 1
        if hasattr(kv, "update"):
            try:
                await kv.update(
                    NEXT_OFFSET_KEY,
                    str(nxt).encode("utf-8"),
                    last=revision,
                )
            except Exception:
                # Fall back to put (single-writer-per-persona via lock).
                await kv.put(NEXT_OFFSET_KEY, str(nxt).encode("utf-8"))
        else:
            await kv.put(NEXT_OFFSET_KEY, str(nxt).encode("utf-8"))
        return nxt


def _entry_value(entry: Any) -> Optional[bytes]:
    """Extract the byte payload from a NATS-KV entry across nats-py
    versions (2.6..2.14). The attribute is ``value`` since 2.6."""
    if entry is None:
        return None
    return getattr(entry, "value", None)


# ---------------------------------------------------------------------------
# Spec §3.7.5.3 — NatsKvPersonaStateBacking (sync facade).
# ---------------------------------------------------------------------------


class NatsKvPersonaStateBacking(PersonaStateBacking):
    """Sync facade around :class:`NatsKvPersonaStateBackingAsync`.

    Carries a dedicated asyncio event loop on a background thread so
    callers retain the v0.2.0-pilot synchronous engine contract. The
    overhead is one thread + one loop per engine process; the
    per-call latency is dominated by NATS round-trip, not the
    inter-thread hop.

    Sprint-Pengine-9 closes the v0.2.0-pilot ``snapshot``/``restore_latest``
    stubs: this facade now delegates to the real async binding and
    the engine boot-log emits ``state-backing-natskv-active`` INFO
    instead of the v0.2.0-pilot ``state-backing-fence-to-in-memory``
    WARN.
    """

    def __init__(
        self,
        nats_servers: str,
        org_id: str,
        *,
        connect_timeout_sec: float = 5.0,
        # Hermetic-test injection point: pass a custom async backing
        # (e.g. a stub with fake KV) instead of building one from
        # nats-py.
        async_backing: Optional[NatsKvPersonaStateBackingAsync] = None,
    ) -> None:
        # Probe nats-py availability eagerly so the engine falls back
        # to InMemory before the first call.
        if async_backing is None:
            try:
                import nats  # type: ignore[import-not-found]  # noqa: F401
            except ImportError as exc:
                raise PersonaStateBackingError(
                    "nats-py wheel missing; cannot construct "
                    "NatsKvPersonaStateBacking. Engine will fence to "
                    "InMemoryPersonaStateBacking with a WARN audit "
                    "annotation. Remediation: rebuild the wakir-persona-"
                    "engine image with the persona-engine-runtime "
                    "pyproject extra (adds nats-py>=2.6)."
                ) from exc
        self._nats_servers: str = nats_servers
        self._org_id: str = org_id
        self._connect_timeout_sec: float = connect_timeout_sec
        self._async_backing: Optional[NatsKvPersonaStateBackingAsync] = (
            async_backing
        )
        # Dedicated event loop on a background thread.
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._connected: bool = False
        # RLock (re-entrant) because ``_ensure_connected`` calls
        # ``_submit`` -> ``_ensure_loop`` while still holding the
        # lock; a plain ``threading.Lock`` would self-deadlock on
        # first ``snapshot()`` call. See test_state_backing_async
        # ``test_sync_facade_delegates_to_async_backing``.
        self._connect_lock = threading.RLock()

    # ------------------------------------------------------------------
    # Loop management.
    # ------------------------------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop
        with self._connect_lock:
            if self._loop is not None:
                return self._loop
            loop = asyncio.new_event_loop()
            t = threading.Thread(
                target=loop.run_forever,
                name="wakir-persona-engine-state-backing-loop",
                daemon=True,
            )
            t.start()
            self._loop = loop
            self._loop_thread = t
            return loop

    def _submit(self, coro: Any) -> Any:
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=self._connect_timeout_sec * 6.0)

    def _ensure_connected(self) -> None:
        if self._connected:
            return
        with self._connect_lock:
            if self._connected:
                return
            if self._async_backing is None:
                self._async_backing = NatsKvPersonaStateBackingAsync(
                    nats_servers=self._nats_servers,
                    org_id=self._org_id,
                    connect_timeout_sec=self._connect_timeout_sec,
                )
            self._submit(self._async_backing.connect())
            self._connected = True

    def close(self) -> None:
        if not self._connected or self._async_backing is None:
            return
        try:
            self._submit(self._async_backing.close())
        except Exception:
            pass
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop = None
        self._loop_thread = None
        self._connected = False

    # ------------------------------------------------------------------
    # Trait surface.
    # ------------------------------------------------------------------

    def snapshot(
        self, persona_id: str, state: PersonaStateSnapshot
    ) -> int:
        self._ensure_connected()
        assert self._async_backing is not None
        return self._submit(self._async_backing.snapshot(persona_id, state))

    def restore_latest(
        self, persona_id: str
    ) -> Optional[PersonaStateSnapshot]:
        self._ensure_connected()
        assert self._async_backing is not None
        return self._submit(self._async_backing.restore_latest(persona_id))

    def list_snapshots(self, persona_id: str) -> List[int]:
        self._ensure_connected()
        assert self._async_backing is not None
        return self._submit(self._async_backing.list_snapshots(persona_id))

    def atomic_swap_pinned_offset(
        self,
        persona_id: str,
        from_offset: int,
        to_offset: int,
    ) -> None:
        self._ensure_connected()
        assert self._async_backing is not None
        self._submit(
            self._async_backing.atomic_swap_pinned_offset(
                persona_id, from_offset, to_offset,
            )
        )
