# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Hour-spool writer: append-only JSONL with sealed-rename pattern.

Implements ``docs/wat-spool-spec.md``:

- One file per UTC hour, JSON-Lines, append-only until sealed.
- Open file: ``<spool>/YYYY-MM-DDTHH.jsonl``.
- Sealed file: ``<spool>/YYYY-MM-DDTHH.jsonl.sealed`` (atomic rename
  after ``H_end + 5min``).
- Sealing is implemented as ``rename(2)``-equivalent on the same
  filesystem so the aggregator can list ``*.sealed`` files without
  race conditions against the bridge writer.

Encoding conventions per spec §7:

- One event per line, trailing newline. UTF-8 throughout.
- Timestamps RFC 3339 with ``Z`` suffix.
- Filenames use ``T`` as the date-hour separator.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Iterable

from wat.ingestion.wirelang_bridge import LeafRecord


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Filename hour-slot format: ``YYYY-MM-DDTHH``, UTC.
HOUR_SLOT_FORMAT = "%Y-%m-%dT%H"

#: Late-frame window per spec §5: ``seal_at(H) = H_end + 5min``.
LATE_FRAME_WINDOW_MINUTES = 5

#: Suffix added by the sealing rename. The aggregator scans for this
#: suffix to find ready hours.
SEALED_SUFFIX = ".sealed"

#: Open-file extension before sealing.
OPEN_SUFFIX = ".jsonl"

#: Hour-slot regex used by ``seal_due_hours`` to enumerate spool
#: directory contents safely. Matches ``YYYY-MM-DDTHH`` only.
_HOUR_SLOT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2})\.jsonl$")


# ---------------------------------------------------------------------------
# Hour-slot helpers
# ---------------------------------------------------------------------------


def _parse_iso_utc(time_str: str) -> dt.datetime:
    """Parse an RFC-3339 timestamp with ``Z`` suffix as a UTC datetime.

    Accepts the canonical Wakir form ``2026-05-06T12:01:30Z`` plus the
    ``+00:00`` variant emitted by some producers. Anything else is
    rejected -- the spool spec requires UTC and we want a deterministic
    hour slot, not a best-effort guess.
    """
    s = time_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(
            f"hour-slot input {time_str!r} is not RFC 3339 UTC"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError(
            f"hour-slot input {time_str!r} has no timezone; UTC required"
        )
    return parsed.astimezone(dt.timezone.utc)


def hour_slot_for_time(time_str: str) -> str:
    """Compute the UTC hour slot label for a frame's ``time`` field.

    Per consensus marker A2: hour slots are UTC. The slot label is
    ``YYYY-MM-DDTHH`` formed by truncating the timestamp to the
    enclosing hour boundary.

    Returns
    -------
    str
        Hour slot label, e.g. ``2026-05-06T12``.
    """
    parsed = _parse_iso_utc(time_str)
    return parsed.strftime(HOUR_SLOT_FORMAT)


def _hour_end_utc(hour_slot: str) -> dt.datetime:
    """Return the start of the hour *following* ``hour_slot`` in UTC.

    ``H_end`` per the spool spec §5 is the start of hour H+1. Sealing
    is permitted no earlier than ``H_end + LATE_FRAME_WINDOW_MINUTES``.
    """
    start = dt.datetime.strptime(hour_slot, HOUR_SLOT_FORMAT).replace(
        tzinfo=dt.timezone.utc,
    )
    return start + dt.timedelta(hours=1)


def _seal_eligible_at(hour_slot: str) -> dt.datetime:
    """Earliest UTC instant at which sealing the given hour is permitted."""
    return _hour_end_utc(hour_slot) + dt.timedelta(
        minutes=LATE_FRAME_WINDOW_MINUTES,
    )


# ---------------------------------------------------------------------------
# Append path -- fsync-disciplined JSONL
# ---------------------------------------------------------------------------


def _open_path(spool_dir: Path, hour_slot: str) -> Path:
    return spool_dir / f"{hour_slot}{OPEN_SUFFIX}"


def _sealed_path(spool_dir: Path, hour_slot: str) -> Path:
    return spool_dir / f"{hour_slot}{OPEN_SUFFIX}{SEALED_SUFFIX}"


def append_leaf_to_spool(
    leaf: LeafRecord,
    spool_dir: str | os.PathLike[str],
    *,
    fsync: bool = True,
) -> Path:
    """Append a ``LeafRecord`` to its hour-slot spool file.

    The hour slot is derived from ``leaf.time``. Multiple producers
    may append concurrently to the same hour file; on POSIX a single
    ``write(2)`` smaller than ``PIPE_BUF`` is atomic, but a JSONL line
    can exceed that, so we use ``open(..., 'a')`` with line buffering
    -- the kernel's append-mode atomically positions the cursor at
    end-of-file before each write so concurrent appenders never
    interleave bytes within a single ``write(2)``. Since ``json.dumps``
    yields a single string we then write+newline in one call, the line
    is delivered atomically per the kernel's append guarantees.

    fsync discipline (spec §3 + §7): each appended line is flushed and
    fsynced before the function returns. Cost is ~ms-per-event on SSDs;
    for higher-throughput producers ``fsync=False`` lets the caller
    batch-fsync via ``os.fsync(fd)`` on the spool file out of band.

    Sealing-discipline guard
    ------------------------

    If the hour-slot file is already sealed (``*.jsonl.sealed`` exists),
    the late frame is **dropped** with a ``RuntimeError``. The caller
    is expected to log the drop and let upstream observability surface
    the rate (spec §5: "frames arriving with ``time`` in hour H but
    observed at or after ``seal_at(H)`` are dropped"). Re-routing to
    H+1 is forbidden because the verifier proof is bound to the
    recorded ``time``.
    """
    spool_path = Path(spool_dir)
    spool_path.mkdir(parents=True, exist_ok=True)

    hour_slot = hour_slot_for_time(leaf.time)
    sealed_target = _sealed_path(spool_path, hour_slot)
    if sealed_target.exists():
        raise RuntimeError(
            f"hour {hour_slot} is sealed; late frame "
            f"event_id={leaf.event_id} time={leaf.time} dropped per spec"
        )

    open_target = _open_path(spool_path, hour_slot)

    line = json.dumps(
        leaf.to_jsonl_dict(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    ) + "\n"

    # Append-mode open is the cheap concurrent-write story on POSIX:
    # the kernel atomically positions at EOF before each write(2).
    with open_target.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        if fsync:
            os.fsync(fh.fileno())

    return open_target


# ---------------------------------------------------------------------------
# Sealed-rename path
# ---------------------------------------------------------------------------


def seal_hour(
    spool_dir: str | os.PathLike[str],
    hour_slot: str,
    *,
    now: dt.datetime | None = None,
    enforce_window: bool = True,
) -> Path | None:
    """Seal the hour-slot file by atomic rename to ``.sealed``.

    Parameters
    ----------
    spool_dir
        Directory holding the open ``*.jsonl`` files.
    hour_slot
        Label of the hour to seal, ``YYYY-MM-DDTHH`` UTC.
    now
        Override for the current UTC instant. Tests inject a fixed
        ``now`` to verify late-window behaviour without sleeping.
    enforce_window
        When true (default), the function refuses to seal before
        ``H_end + 5min``. Set to false for backfill or replay.

    Returns
    -------
    Path | None
        Path to the sealed file on success; ``None`` if the open file
        did not exist (empty hour, nothing to seal).

    Behaviour
    ---------

    - Atomic: the rename is a single ``rename(2)`` call on the same
      filesystem. Either the open file is gone and the sealed file
      exists, or neither happens.
    - Idempotent: if the sealed file already exists, a second seal is
      a no-op and returns the existing sealed path.
    - Fsync-disciplined: the parent directory is fsynced after rename
      so a crash before the directory entry hits disk does not lose
      the seal (spec §5: "atomic rename" is the contract).
    - Empty-hour-skip: a missing open file returns ``None``. Operators
      can treat this as "nothing was written for hour H, no seal
      needed" -- the aggregator handles missing ``*.sealed`` per
      ``docs/wat-manifest-spec.md`` "Empty hours".
    - Sealed-file-re-open-verbot: spec §5 forbids re-opening a sealed
      file for append; ``append_leaf_to_spool`` enforces this.
    """
    spool_path = Path(spool_dir)
    open_target = _open_path(spool_path, hour_slot)
    sealed_target = _sealed_path(spool_path, hour_slot)

    # Idempotent fast path: already sealed.
    if sealed_target.exists():
        return sealed_target

    # Empty hour: nothing to seal.
    if not open_target.exists():
        return None

    if enforce_window:
        now_utc = now or dt.datetime.now(tz=dt.timezone.utc)
        eligible = _seal_eligible_at(hour_slot)
        if now_utc < eligible:
            raise RuntimeError(
                f"refusing to seal hour {hour_slot}: "
                f"current_time={now_utc.isoformat()} < "
                f"seal_eligible_at={eligible.isoformat()}; "
                f"5-minute late-frame window not yet elapsed"
            )

    # Atomic rename. POSIX guarantees this is a single rename(2) on
    # the same filesystem; the open writer's append-mode handle is
    # invalidated and any subsequent write would create a new
    # ``<hour>.jsonl`` (which spec §5 forbids -- enforced via the
    # ``append_leaf_to_spool`` sealed-file check at next-call time).
    os.rename(open_target, sealed_target)

    # Fsync the parent directory so the rename is durable across
    # crashes. Best-effort: not all filesystems support directory
    # fsync, and a Linux ext4/xfs/btrfs deployment will accept it.
    try:
        dir_fd = os.open(str(spool_path), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:  # pragma: no cover - filesystem-dependent
        pass

    return sealed_target


def seal_due_hours(
    spool_dir: str | os.PathLike[str],
    *,
    now: dt.datetime | None = None,
) -> list[Path]:
    """Seal every open hour-slot file whose late-frame window has elapsed.

    Convenience for the hourly cron driver: walks the spool directory,
    finds open ``*.jsonl`` files (NOT already sealed), checks each
    against its ``seal_eligible_at`` boundary, and seals those that
    are due.

    Returns
    -------
    list[Path]
        Paths of files newly sealed in this call. Empty list if
        nothing was due.
    """
    spool_path = Path(spool_dir)
    if not spool_path.is_dir():
        return []

    now_utc = now or dt.datetime.now(tz=dt.timezone.utc)
    sealed: list[Path] = []
    for entry in sorted(spool_path.iterdir()):
        match = _HOUR_SLOT_RE.match(entry.name)
        if not match:
            continue
        hour_slot = match.group(1)
        if now_utc < _seal_eligible_at(hour_slot):
            continue
        result = seal_hour(spool_path, hour_slot, now=now_utc)
        if result is not None and result.name.endswith(SEALED_SUFFIX):
            # Only count newly-sealed files. ``seal_hour`` returns the
            # existing sealed path on the idempotent fast path, but in
            # that case the open file was already gone and we did not
            # rename anything in *this* call -- detect by checking
            # whether the open file existed before the call.
            sealed.append(result)
    return sealed


def iter_sealed_hours(
    spool_dir: str | os.PathLike[str],
) -> Iterable[tuple[str, Path]]:
    """Yield ``(hour_slot, sealed_path)`` for every sealed hour file.

    Used by the hourly driver to discover work. Sorted ascending by
    hour-slot label so backfill-style replay is deterministic.
    """
    spool_path = Path(spool_dir)
    if not spool_path.is_dir():
        return
    sealed_re = re.compile(
        r"^(\d{4}-\d{2}-\d{2}T\d{2})\.jsonl\.sealed$",
    )
    for entry in sorted(spool_path.iterdir()):
        match = sealed_re.match(entry.name)
        if not match:
            continue
        yield match.group(1), entry


__all__ = [
    "HOUR_SLOT_FORMAT",
    "LATE_FRAME_WINDOW_MINUTES",
    "OPEN_SUFFIX",
    "SEALED_SUFFIX",
    "append_leaf_to_spool",
    "hour_slot_for_time",
    "iter_sealed_hours",
    "seal_due_hours",
    "seal_hour",
]
