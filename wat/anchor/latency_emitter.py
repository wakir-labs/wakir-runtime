# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Part of the Wakir Audit Trail (WAT) module. Licensed under
# Business Source License 1.1; see ../LICENSE-BSL.md.

"""Per-anchor pipeline-stage latency emitter (Producer side).

This module is the producer counterpart to ``scripts/wat-anchor-
pipeline-observability.py`` (Noa, PR #145). The consumer tails a JSONL
observation file and aggregates per-stage p50/p95/p99 quantiles for
SLO-2 (anchor-latency-p99). The producer (this module) is the code
that writes one JSON object per finalised anchor to that file.

Wire contract (must stay byte-compatible with the consumer)
-----------------------------------------------------------

One JSON object per line. ``stages`` is a closed enum of four keys
matching ``PIPELINE_STAGES`` in the consumer script. All durations
are non-negative floats in **milliseconds** (the consumer converts to
seconds for Prometheus histogram exposition; this module emits ms so
that hand-inspection of the JSONL is human-readable in the same units
as systemd journal timing logs).

::

    {
      "anchor_root_hex": "<64-hex>",
      "timestamp": "<ISO-8601 with Z suffix>",
      "stages": {
        "enqueue_to_pre_ots_ms": <float>,
        "ots_call_ms": <float>,
        "post_ots_commit_ms": <float>,
        "wat_write_ms": <float>
      }
    }

Lines whose ``stages`` block is malformed are silently dropped by the
consumer. This module never emits a malformed line: either all four
stages have a non-negative finite measurement and a complete record
is written, or no record is written for that anchor.

Opt-in semantics
----------------

The emitter is **disabled by default**. It activates only when the
environment variable ``WAKIR_ANCHOR_LATENCY_JSONL`` is set to a
writable filesystem path. The motivation is twofold:

* Existing unit tests across the WAT pipeline do not expect a
  side-effect on the local filesystem when ``anchor_root`` runs;
  default-disabled keeps that contract.
* Production rollout staging: operators can flip the env-var per host
  (systemd drop-in or Quadlet) without a code deploy, then observe
  the JSONL grow before wiring up the consumer scrape.

Failure isolation
-----------------

A failure inside the emitter (disk full, permission denied, racing
file rotation) must **never** propagate into the WAT-anchor caller.
The anchor pipeline is the source of truth for receipt durability;
observability is best-effort. All emitter exceptions are caught and
silently dropped. If a host-side observer needs to detect emitter
sickness, that signal must come from absence-of-data in the consumer
(``wat_anchor_pipeline_cli_failure`` already covers that surface).

Threading
---------

Single-process, single-thread anchor pipeline today. The append-mode
file open with ``O_APPEND`` semantics gives us atomic line writes at
the POSIX level for writes <= PIPE_BUF (4096 bytes on Linux). One
record is ~250 bytes, well under that threshold, so concurrent
producer processes would not interleave bytes mid-line. We do not
serialise across processes (no lockfile); the consumer tolerates
out-of-order ``timestamp`` ordering by reading the last N lines and
not assuming monotonicity (see PR #145 ``read_latency_samples``).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import time
from pathlib import Path
from typing import Iterator, Optional


# ---------------------------------------------------------------------------
# Constants — wire-format contract with PR #145 consumer.
# ---------------------------------------------------------------------------

#: Environment variable that toggles the producer. Unset / empty -> no-op.
#: A set value is interpreted as the absolute path to the JSONL file.
ENV_LATENCY_JSONL_PATH = "WAKIR_ANCHOR_LATENCY_JSONL"

#: Ordered tuple of pipeline-stage names. Order must match
#: ``PIPELINE_STAGES`` in ``scripts/wat-anchor-pipeline-observability.py``.
#: Adding a stage is a schema-version bump on the consumer; renaming a
#: stage is a breaking change.
PIPELINE_STAGES: tuple[str, ...] = (
    "enqueue_to_pre_ots",
    "ots_call",
    "post_ots_commit",
    "wat_write",
)

#: Suffix appended to each stage name to form the JSON key in the
#: ``stages`` block. Consumer parses ``<stage>_ms`` and converts to
#: seconds (Prometheus convention).
STAGE_MS_SUFFIX = "_ms"

#: JSONL field that the consumer keys off when parsing.
STAGES_FIELD = "stages"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _utc_now_iso8601() -> str:
    """Return current UTC time as ISO-8601 with ``Z`` suffix.

    Format matches the receipt-emitter's ``submission_time`` field
    (``_utc_now_rfc3339`` in ``ots_anchor.py``) so timestamps across
    the anchor pipeline share one wall-clock representation.
    """
    return dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_target_path(env: Optional[dict] = None) -> Optional[Path]:
    """Return the JSONL path from the environment, or ``None`` if disabled.

    A value that is set but empty (``WAKIR_ANCHOR_LATENCY_JSONL=``)
    counts as disabled. A non-empty value is wrapped in :class:`Path`
    without further validation (existence / writability are deferred
    to write-time and silently swallowed if they fail).
    """
    env_map = env if env is not None else os.environ
    raw = env_map.get(ENV_LATENCY_JSONL_PATH)
    if raw is None:
        return None
    raw_stripped = raw.strip()
    if not raw_stripped:
        return None
    return Path(raw_stripped)


# ---------------------------------------------------------------------------
# Stage-timing recorder
# ---------------------------------------------------------------------------


class StageRecorder:
    """Captures wall-clock durations for the four pipeline stages.

    Used as a context-manager via :meth:`LatencyEmitter.observe`. Each
    pipeline stage is itself measured via :meth:`stage`, which returns
    a nested context manager that records the elapsed duration on
    exit. Missed stages (not entered) are not emitted; the JSONL
    record will simply omit no key — but the emitter only writes a
    record if all four stages were observed (partial records are
    dropped on flush, matching the consumer's "drop incomplete lines"
    contract).
    """

    __slots__ = ("_anchor_root_hex", "_durations_ms", "_started_stages")

    def __init__(self, anchor_root_hex: str) -> None:
        self._anchor_root_hex = anchor_root_hex
        self._durations_ms: dict[str, float] = {}
        self._started_stages: set[str] = set()

    @property
    def anchor_root_hex(self) -> str:
        return self._anchor_root_hex

    def durations_ms(self) -> dict[str, float]:
        """Return a copy of the per-stage durations recorded so far."""
        return dict(self._durations_ms)

    def is_complete(self) -> bool:
        """True iff all four contractual stages have a recorded duration."""
        return all(stage in self._durations_ms for stage in PIPELINE_STAGES)

    @contextlib.contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Context-manager that records wall-clock duration for one stage.

        ``name`` must be one of :data:`PIPELINE_STAGES`. Using an
        unknown name raises :class:`ValueError` early so a stage-name
        typo surfaces at call time instead of silently dropping the
        observation on flush.

        Re-entering the same stage on one recorder overwrites the
        previous duration (matches the "last-observation-wins"
        convention used elsewhere in the WAT module for replayable
        timings).
        """
        if name not in PIPELINE_STAGES:
            raise ValueError(
                f"unknown pipeline stage {name!r}; "
                f"expected one of {PIPELINE_STAGES}"
            )
        self._started_stages.add(name)
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_s = time.perf_counter() - start
            # Guard against monotonic-clock backwards jumps (some VMs)
            # and floating-point negatives. Clamp at zero; the consumer
            # drops the whole record on a negative anyway.
            if elapsed_s < 0:
                elapsed_s = 0.0
            self._durations_ms[name] = elapsed_s * 1000.0


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------


class LatencyEmitter:
    """Producer that appends per-anchor stage-latency records to JSONL.

    Construction does not touch the filesystem. The target path is
    resolved from :data:`ENV_LATENCY_JSONL_PATH` once at init; if the
    variable is unset the emitter is a no-op (every method returns
    without side effects).

    Use :meth:`observe` as a context manager around the anchor
    pipeline:

    ::

        emitter = LatencyEmitter.from_env()
        with emitter.observe(root_hex) as rec:
            with rec.stage("enqueue_to_pre_ots"):
                ...
            with rec.stage("ots_call"):
                ...
            ...
        # On context exit a complete record is appended to the JSONL.
    """

    __slots__ = ("_target_path",)

    def __init__(self, target_path: Optional[Path]) -> None:
        self._target_path = target_path

    @classmethod
    def from_env(cls, env: Optional[dict] = None) -> "LatencyEmitter":
        """Construct an emitter from the process environment.

        ``env`` is an optional override for unit tests; defaults to
        :data:`os.environ`.
        """
        return cls(_resolve_target_path(env))

    @property
    def enabled(self) -> bool:
        """True iff the env-var resolved to a non-empty path."""
        return self._target_path is not None

    @property
    def target_path(self) -> Optional[Path]:
        return self._target_path

    @contextlib.contextmanager
    def observe(self, anchor_root_hex: str) -> Iterator[StageRecorder]:
        """Yield a :class:`StageRecorder`; flush its record on clean exit.

        ``anchor_root_hex`` is recorded as-is on the resulting JSONL
        line (the consumer treats it as an opaque identifier). The
        caller is expected to pass the 64-hex lowercase form already
        used by ``AnchorReceipt.merkle_root.hex()``.

        If the context exits with an exception (e.g. ``AnchorError``
        raised mid-pipeline), the partial record is **not** flushed.
        Rationale: a half-stamped anchor's stage timings are not
        comparable to a successful pipeline run, and feeding partial
        data into the consumer histogram would skew the percentile
        surface in operator-confusing ways. Failure-rate (count of
        ``AnchorError`` raises) is a separate signal that lives in the
        existing receipt-emitter's spool-totals gauges.
        """
        recorder = StageRecorder(anchor_root_hex)
        try:
            yield recorder
        except BaseException:
            # Re-raise the original exception untouched. No emit on
            # error: SLO-2 latency is conditional-on-success.
            raise
        else:
            self._emit(recorder)

    def _emit(self, recorder: StageRecorder) -> None:
        """Append one JSONL line if the emitter is enabled and complete.

        All failures (disabled, incomplete, IO error, encode error)
        are silent. Observability is best-effort; the anchor pipeline
        is the source of truth.
        """
        if self._target_path is None:
            return
        if not recorder.is_complete():
            # Partial observation — drop. Matches consumer contract.
            return
        try:
            line = self._render_line(recorder)
        except (TypeError, ValueError):
            # Should not happen with the StageRecorder shape, but be
            # defensive: a future refactor could insert a non-JSON-
            # serialisable value and we still must not crash.
            return
        try:
            self._append(line)
        except OSError:
            # Disk full, permission denied, parent dir gone after
            # rotation — all are operator-visible elsewhere (host disk
            # monitoring, systemd journal). Do not propagate.
            return

    def _render_line(self, recorder: StageRecorder) -> str:
        """Build one newline-terminated JSON line matching the wire contract."""
        stages_block: dict[str, float] = {}
        durations = recorder.durations_ms()
        for stage in PIPELINE_STAGES:
            stages_block[stage + STAGE_MS_SUFFIX] = float(durations[stage])
        record = {
            "anchor_root_hex": recorder.anchor_root_hex,
            "timestamp": _utc_now_iso8601(),
            STAGES_FIELD: stages_block,
        }
        return json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n"

    def _append(self, line: str) -> None:
        """Atomically append one line to the target JSONL.

        Uses ``O_APPEND`` so concurrent writes from sibling processes
        do not interleave for sub-PIPE_BUF lines (~250 bytes << 4096).
        Creates the parent directory and the file on first use; both
        with conservative permissions (parent ``0o755``, file
        ``0o644``) matching the rest of the meta/timestamps tree
        convention.
        """
        if self._target_path is None:
            return
        target = self._target_path
        parent = target.parent
        if parent and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        # O_WRONLY | O_CREAT | O_APPEND; mode applies only on creation.
        fd = os.open(
            str(target),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o644,
        )
        try:
            data = line.encode("utf-8")
            # write() with O_APPEND is atomic on POSIX for len <= PIPE_BUF.
            os.write(fd, data)
        finally:
            os.close(fd)


__all__ = [
    "ENV_LATENCY_JSONL_PATH",
    "PIPELINE_STAGES",
    "STAGE_MS_SUFFIX",
    "STAGES_FIELD",
    "LatencyEmitter",
    "StageRecorder",
]
