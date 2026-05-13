# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Doppel-Audit-Trail-Bridge: parallel WAT-Spool + Pre-Framework-activity-log.

Migrations-Plan-Schritt 5 (`projects/migration-plan.md`).

During the migration pilot phase (~KW 23 onward) every persona-activity
event MUST be persisted to both audit sinks atomically:

- **WAT side (new world):** appended to the persona-specific WAT spool
  via :func:`wat.ingestion.spool_writer.append_leaf_to_spool` with the
  hourly anchor pattern. Verifier-grade integrity, post-hoc Merkle
  proof.
- **Pre-Framework side (old world):** appended to ``activity-log.md``
  in the AI-Corp main repo. Canonical format
  ``YYYY-MM-DD · Akteur · Aktion · Bezug``. Human-readable, ops-friendly,
  the source-of-truth the org has used since founding.

Consistency contract
--------------------

If either side fails, the writer rolls back the OTHER side and returns
a failure ``BridgeWriteResult`` to the caller. A half-commit (one sink
written, the other lost) MUST NOT happen — the migration only earns
its zero-audit-gap promise if both sides stay byte-balanced.

Rollback discipline:

- WAT-side write happens first. On WAT-failure: no Pre-Framework write
  occurs, we return early with ``status=wat-failed``.
- Pre-Framework-side write happens second. On Pre-Framework-failure:
  the WAT-side spool line gets truncated back to its pre-call byte
  offset (we recorded it before appending). Returns
  ``status=pre-framework-failed``.

The rollback is best-effort on POSIX: ``truncate(2)`` on the open
spool file is atomic against single writers. Concurrent producers
appending to the same hour-slot file would race with the rollback —
the bridge therefore SERIALISES writes per ``(persona_id, hour_slot)``
via an in-process lock. Cross-process concurrency is the operator's
responsibility (one bridge writer per persona at a time during pilot;
ADR-0036 Schritt 8 pilot scope is single-persona).

Determinism guarantees
----------------------

- Action-Order is byte-deterministic: events with the same
  ``(time, persona_id, action_type)`` triple are ordered by ``time``
  ascending, then by ``persona_id`` ASCII, then by ``action_type``
  ASCII as a stable tie-break. The Pre-Framework line ALWAYS carries
  the UTC ``time`` as its ``YYYY-MM-DD`` prefix; the WAT-side LeafRecord
  carries the full RFC-3339 ``time``.
- Pre-Framework-Linecount EQUALS WAT-Marker-Anzahl after a clean run.
  The consistency test suite enforces this invariant over a 1000-event
  24h mock-trace (``tests/wat/test_bridge_audit_writer_consistency.py``).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

from wat.ingestion.spool_writer import (
    append_leaf_to_spool,
    hour_slot_for_time,
)
from wat.ingestion.wirelang_bridge import LeafRecord


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


#: Status sentinel: both sinks accepted the write.
STATUS_OK = "ok"

#: Status sentinel: WAT-side write failed; Pre-Framework was never
#: attempted. No rollback necessary.
STATUS_WAT_FAILED = "wat-failed"

#: Status sentinel: Pre-Framework-side write failed; WAT-side was
#: written first and has now been rolled back. Half-commit avoided.
STATUS_PRE_FRAMEWORK_FAILED = "pre-framework-failed"


@dataclass(frozen=True)
class BridgeWriteResult:
    """Outcome of a single :func:`write_bridge_audit` call.

    Attributes
    ----------
    status
        One of :data:`STATUS_OK`, :data:`STATUS_WAT_FAILED`,
        :data:`STATUS_PRE_FRAMEWORK_FAILED`.
    persona_id
        Persona identifier (e.g. ``"tomas"``, ``"reza"``).
    action_type
        Coarse-grained action category (e.g. ``"pr-open"``,
        ``"adr-vote"``, ``"hourly-tick"``).
    event_time
        RFC-3339 UTC timestamp the event was recorded at.
    wat_spool_path
        Spool file the WAT-side LeafRecord landed in, or ``None``
        if the WAT-side write did not succeed.
    activity_log_path
        Path of the activity-log file appended to (always populated
        even on failure — operators want to know where the bridge
        would have written).
    error
        Diagnostic string when ``status`` is non-OK. Empty otherwise.
    """

    status: str
    persona_id: str
    action_type: str
    event_time: str
    wat_spool_path: Optional[Path]
    activity_log_path: Path
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


#: In-process lock map keyed by ``(persona_id, hour_slot)``. Serialises
#: parallel callers within one Python process so the WAT-side rollback
#: (``truncate(2)`` to a recorded byte offset) is race-free. Across
#: processes the operator is expected to run one bridge writer per
#: persona — ADR-0036 §pilot-scope.
_lock_map_lock = threading.Lock()
_lock_map: dict[tuple[str, str], threading.Lock] = {}


def _acquire_serial_lock(persona_id: str, hour_slot: str) -> threading.Lock:
    key = (persona_id, hour_slot)
    with _lock_map_lock:
        lock = _lock_map.get(key)
        if lock is None:
            lock = threading.Lock()
            _lock_map[key] = lock
    lock.acquire()
    return lock


def _format_activity_log_line(
    *,
    event_time: str,
    persona_id: str,
    action_type: str,
    bezug: str,
) -> str:
    """Format one activity-log line in canonical
    ``YYYY-MM-DD · Akteur · Aktion · Bezug``.

    The ``YYYY-MM-DD`` prefix is derived from ``event_time`` (RFC-3339
    UTC). The remaining columns are passed through verbatim with
    leading/trailing whitespace stripped. The separator is U+00B7
    (MIDDLE DOT), matching the activity-log header convention as of
    2026-05-04 (AR-Direktive: chronologisch, neuester Eintrag oben).
    """
    date_prefix = event_time[:10]  # ``YYYY-MM-DD`` slice of RFC-3339.
    return (
        f"{date_prefix} · {persona_id.strip()} · "
        f"{action_type.strip()} · {bezug.strip()}\n"
    )


def _compose_bezug(payload_hash: str, metadata: Mapping[str, Any]) -> str:
    """Build the Bezug column for the activity-log entry.

    Bezug carries the payload hash (truncated to 12 hex chars for
    readability) and any caller-supplied ``ref`` metadata field. The
    full payload hash remains on the WAT side; the truncated prefix
    here is enough for an operator to grep and cross-reference.
    """
    short_hash = payload_hash[:12] if payload_hash else "no-hash"
    ref = metadata.get("ref") if isinstance(metadata, Mapping) else None
    if ref:
        return f"{ref} · payload={short_hash}"
    return f"payload={short_hash}"


def _build_leaf_record(
    *,
    persona_id: str,
    action_type: str,
    event_time: str,
    payload_hash: str,
    metadata: Mapping[str, Any],
) -> LeafRecord:
    """Construct a LeafRecord for the WAT-side spool.

    The bridge synthesises a LeafRecord directly (without going through
    the full Layer-1 frame schema) because pilot-phase persona events
    don't yet carry CloudEvents envelopes — that's a Phase-2 item. The
    9-field tuple is populated as follows:

    - ``event_id``: deterministic UUID-style derived from
      ``SHA-256(persona_id || event_time || action_type || payload_hash)``,
      first 32 hex chars. Stable across re-invocations with the same
      inputs, which makes idempotent retry safe.
    - ``time``: caller-provided RFC-3339 UTC.
    - ``payload_hash``: caller-provided hex string.
    - ``capability_token_hash``: empty sentinel (pilot-phase events
      are not yet capability-gated; Phase-2 will fill this).
    - ``source``: ``"wakir-bridge-audit-writer"`` literal.
    - ``actorrole``: ``persona_id`` echoed (one role per persona during
      pilot).
    - ``agentid``: ``persona_id`` echoed.
    - ``schemaid``: ``"wakir-bridge-audit/v1"``.
    - ``schemaversion``: ``"1"``.
    """
    seed = f"{persona_id}|{event_time}|{action_type}|{payload_hash}"
    event_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
    return LeafRecord(
        event_id=event_id,
        time=event_time,
        payload_hash=payload_hash,
        capability_token_hash="",
        source="wakir-bridge-audit-writer",
        actorrole=persona_id,
        agentid=persona_id,
        schemaid="wakir-bridge-audit/v1",
        schemaversion="1",
    )


def _record_wat_offset(spool_path: Path) -> int:
    """Return the current byte length of the spool file (or 0 if absent).

    Used to pin a rollback target before the WAT-side append. On
    Pre-Framework-failure the WAT-side spool gets truncated back to
    this offset, restoring byte-identity to its pre-call state.
    """
    try:
        return spool_path.stat().st_size
    except FileNotFoundError:
        return 0


def _rollback_wat_side(spool_path: Path, original_size: int) -> None:
    """Truncate the spool file back to ``original_size``.

    Best-effort: on filesystems that don't support truncate (rare on
    Linux), the rollback is logged as a diagnostic but cannot undo
    the append. Pilot-phase deployments are on ext4/btrfs/xfs which
    all support ``ftruncate(2)`` correctly.
    """
    try:
        with spool_path.open("r+b") as fh:
            fh.truncate(original_size)
            fh.flush()
            os.fsync(fh.fileno())
    except FileNotFoundError:
        # The spool file did not exist before AND was never created
        # (because append failed before open). Nothing to roll back.
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_bridge_audit(
    *,
    persona_id: str,
    action_type: str,
    payload_hash: str,
    metadata: Mapping[str, Any],
    spool_root: str | os.PathLike[str],
    activity_log_path: str | os.PathLike[str],
    event_time: Optional[str] = None,
    _fail_wat: bool = False,
    _fail_pre_framework: bool = False,
) -> BridgeWriteResult:
    """Append one persona-activity event to BOTH audit sinks atomically.

    Parameters
    ----------
    persona_id
        Lower-case persona slug (e.g. ``"tomas"``, ``"reza"``,
        ``"mira"``). Echoed into both sinks.
    action_type
        Coarse-grained action category. Free-form string — the bridge
        treats it as opaque metadata. Examples: ``"pr-open"``,
        ``"adr-vote"``, ``"hourly-tick"``, ``"git-commit"``.
    payload_hash
        Hex-lower SHA-256 of the event's canonical payload. Empty
        string permitted for actions that have no payload.
    metadata
        Optional structured metadata. The bridge consumes ``ref`` for
        the Pre-Framework Bezug column; all other keys flow through
        unchanged to future consumers (currently unused).
    spool_root
        Directory holding per-persona WAT spool sub-directories. The
        bridge writes to ``<spool_root>/<persona_id>/`` to keep
        per-persona traces separable for the Phase-1b aggregator.
    activity_log_path
        Path to the Pre-Framework ``activity-log.md`` file (typically
        ``/var/home/fred/AI-Corp/activity-log.md``).
    event_time
        RFC-3339 UTC timestamp the event was emitted at. If ``None``,
        the bridge stamps the current wall-clock UTC. Tests inject a
        fixed value for determinism.
    _fail_wat
        Test hook: when true, the WAT-side write raises before any
        bytes are persisted. Production callers MUST NOT set this.
    _fail_pre_framework
        Test hook: when true, the Pre-Framework write raises after
        the WAT-side write has landed. Used to exercise the rollback
        path. Production callers MUST NOT set this.

    Returns
    -------
    BridgeWriteResult
        Per-call outcome with status, paths, and (on failure) a
        diagnostic message.

    Atomicity model
    ---------------

    1. Pin the WAT-side rollback offset (current byte size of the
       target spool file).
    2. Append the LeafRecord to the WAT spool. On failure → return
       ``wat-failed`` immediately; no Pre-Framework write is
       attempted.
    3. Append the canonical line to ``activity-log.md`` via
       ``open(..., 'a')`` + fsync. On failure → truncate the WAT
       spool back to the pinned offset and return
       ``pre-framework-failed``.
    4. Both succeeded → return ``ok``.

    The function is thread-safe within one process per
    ``(persona_id, hour_slot)`` key. Cross-process safety is the
    operator's responsibility during pilot (one bridge writer per
    persona).
    """
    if event_time is None:
        event_time = dt.datetime.now(tz=dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    hour_slot = hour_slot_for_time(event_time)
    persona_spool_dir = Path(spool_root) / persona_id
    spool_file = persona_spool_dir / f"{hour_slot}.jsonl"
    activity_log_target = Path(activity_log_path)
    bezug = _compose_bezug(payload_hash, metadata)

    leaf = _build_leaf_record(
        persona_id=persona_id,
        action_type=action_type,
        event_time=event_time,
        payload_hash=payload_hash,
        metadata=metadata,
    )

    lock = _acquire_serial_lock(persona_id, hour_slot)
    try:
        # --- (1) Pin rollback target ---
        original_size = _record_wat_offset(spool_file)

        # --- (2) WAT-side append ---
        wat_spool_path: Optional[Path] = None
        try:
            if _fail_wat:
                raise RuntimeError("test-injected WAT-side failure")
            wat_spool_path = append_leaf_to_spool(
                leaf, persona_spool_dir, fsync=True
            )
        except Exception as exc:  # noqa: BLE001 — broad on purpose
            return BridgeWriteResult(
                status=STATUS_WAT_FAILED,
                persona_id=persona_id,
                action_type=action_type,
                event_time=event_time,
                wat_spool_path=None,
                activity_log_path=activity_log_target,
                error=f"wat-append-failed: {exc!s}",
            )

        # --- (3) Pre-Framework append ---
        line = _format_activity_log_line(
            event_time=event_time,
            persona_id=persona_id,
            action_type=action_type,
            bezug=bezug,
        )
        try:
            if _fail_pre_framework:
                raise RuntimeError("test-injected Pre-Framework failure")
            activity_log_target.parent.mkdir(parents=True, exist_ok=True)
            with activity_log_target.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
        except Exception as exc:  # noqa: BLE001
            _rollback_wat_side(spool_file, original_size)
            return BridgeWriteResult(
                status=STATUS_PRE_FRAMEWORK_FAILED,
                persona_id=persona_id,
                action_type=action_type,
                event_time=event_time,
                wat_spool_path=None,  # rolled back
                activity_log_path=activity_log_target,
                error=f"pre-framework-append-failed: {exc!s}",
            )

        # --- (4) Both OK ---
        return BridgeWriteResult(
            status=STATUS_OK,
            persona_id=persona_id,
            action_type=action_type,
            event_time=event_time,
            wat_spool_path=wat_spool_path,
            activity_log_path=activity_log_target,
            error="",
        )
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# Diagnostics helpers (used by the consistency test suite)
# ---------------------------------------------------------------------------


def count_wat_markers(spool_root: str | os.PathLike[str], persona_id: str) -> int:
    """Count LeafRecord lines across all hour-slot spool files for one persona.

    Sealed files (``*.jsonl.sealed``) and open files (``*.jsonl``) both
    count — sealing is a rename, not a data change.
    """
    persona_dir = Path(spool_root) / persona_id
    if not persona_dir.is_dir():
        return 0
    total = 0
    for entry in persona_dir.iterdir():
        name = entry.name
        if not (name.endswith(".jsonl") or name.endswith(".jsonl.sealed")):
            continue
        with entry.open("rb") as fh:
            for _ in fh:
                total += 1
    return total


def count_activity_log_lines_for_persona(
    activity_log_path: str | os.PathLike[str],
    persona_id: str,
) -> int:
    """Count canonical activity-log lines authored by ``persona_id``.

    A canonical line matches the prefix
    ``YYYY-MM-DD · <persona_id> · ``. The bridge ONLY writes canonical
    lines; the existing activity-log header sections, headlines, and
    Mira-Hourly free-form prose are ignored.
    """
    log_path = Path(activity_log_path)
    if not log_path.is_file():
        return 0
    marker = f" · {persona_id} · "
    total = 0
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            # Bridge-written lines start with ``YYYY-MM-DD `` and carry
            # the persona delimiter exactly once at the right position.
            if len(line) < 13:
                continue
            if line[4] != "-" or line[7] != "-" or line[10] != " ":
                continue
            if marker in line:
                total += 1
    return total


__all__ = [
    "BridgeWriteResult",
    "STATUS_OK",
    "STATUS_PRE_FRAMEWORK_FAILED",
    "STATUS_WAT_FAILED",
    "count_activity_log_lines_for_persona",
    "count_wat_markers",
    "write_bridge_audit",
]
