#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""phase-3c-observability-baseline-tracker — Tag-25 Gate-4 baseline tracker.

Background
----------

ADR-0065 (Phase-3c cutover) declares five trigger-gates. Gate-4 is the
**Backend-Decision-Observability baseline**: before the Python -> Rust
default-backend flip, at least seven distinct days of operational
``BackendDecision`` evidence must have accumulated so the cutover rests
on real fallback-rate data rather than a cold-start guess.

The Tag-24 trigger-gate aggregator
(``scripts/phase-3c-trigger-gate-aggregator.py``) already evaluates the
gate as a *single tri-state*: red (aggregator script missing), yellow
(ENV unset / baseline file missing / fewer than seven days), green
(>= seven distinct days). That is enough to **block** the cutover, but
it is not enough to **track readiness** — an operator preparing the
cutover needs to know:

  * **How many days of evidence have I accumulated so far?**
  * **Per component, what is the python-vs-rust split today?**
  * **What is the fallback-rate per component?** (the substantive
    fitness signal that says the Rust binaries are actually running
    on the production path.)
  * **What is my burn-up trajectory: 7-day mark, 14-day mark?**

This tracker fills that gap. It is a *richer view* of the same JSONL
baseline file Gate-4 already inspects. The aggregator stays the
binary go/no-go signal; the tracker is the burn-up dashboard that
runs daily, emits an artifact, and lets the cutover-decision-meeting
look at a trend, not a single point.

Posture
-------

Stdlib-only. No cosign / podman / systemctl invocation. No network.
Reads one JSONL file, writes one JSON report.

Tri-state status semantics (parity with the Tag-24 aggregator):

  * ``red``   — < ``DEFAULT_BASELINE_MIN_DAYS`` distinct days (cutover
                blocker; same threshold as Gate-4 of the aggregator).
  * ``yellow`` — between the minimum and the comfort floor (>=7 but
                <14 distinct days; cutover is technically permitted
                but the burn-up is still building confidence).
  * ``green`` — >= ``DEFAULT_BASELINE_COMFORT_DAYS`` distinct days
                (two weeks of evidence; the ADR-0065 comfort floor).

Exit-code (CI-consumable):

  * ``0`` — green.
  * ``1`` — yellow.
  * ``2`` — red.

ENV contract
------------

The tracker resolves the JSONL path in this order:

  1. ``--jsonl-path PATH`` CLI flag (operator-hand override).
  2. ``WAKIR_PHASE_3C_OBS_BASELINE_PATH`` ENV — the path Gate-4 of the
     Tag-24 aggregator also reads. Sharing the ENV name guarantees the
     tracker and the aggregator inspect the same file.
  3. ``WAKIR_BACKEND_DECISION_JSONL`` ENV — the canonical ENV the
     ``scripts/backend-decision-observability.py`` aggregator reads.
     This fallback lets a deployment configure ONE ENV and have both
     the live aggregator AND the daily tracker pick the file up.

If no path resolves, the tracker emits a ``red`` status with
``reason=no-path-configured`` and exits 2 — the same posture the
Tag-24 Gate-4 takes when the aggregator script itself is missing.

Usage
-----

::

    # Stdout JSON, exit-code reflects status.
    python scripts/phase-3c-observability-baseline-tracker.py

    # Write the report to a file (CI-artifact pattern).
    python scripts/phase-3c-observability-baseline-tracker.py \
        --out /tmp/phase-3c-baseline-tracker.json

    # Operator-hand override.
    python scripts/phase-3c-observability-baseline-tracker.py \
        --jsonl-path /var/lib/wakir/backend-decisions.jsonl

Schema alignment
----------------

The JSONL is the same one ``scripts/backend-decision-observability.py``
emits and ``scripts/phase-3c-trigger-gate-aggregator.py`` Gate-4 reads.
Each record has these fields (per
``wirelang/persona_engine/rust_backend_switch.py::log_backend_decision``):

::

    {
        "level": "INFO",
        "msg": "backend-decision",
        "domain": "recovery|state_backing|fsm|v907_verify|bridge_diff|...",
        "requested_backend": "<env-normalised>",
        "chosen_backend": "rust|python|rust_inmemory|rust_natskv|...",
        "resolution_latency_us": <int>,
        "fallback_reason": "binary_missing|binary_not_executable|"
                           "explicit_python|null",
        "bin_path": "<path>|null"
    }

The tracker accepts records with OR without a ``msg`` envelope
(liberal-reader, same as the Tag-22 aggregator). The timestamp is
read from ``ts``, ``ts_utc``, ``timestamp``, or ``time``; the first
ISO-8601 date (``YYYY-MM-DD``) found anywhere in the string supplies
the day-bucket. Records without a parseable timestamp are dropped
from the day-distinct count (they cannot anchor a calendar day) but
they DO still count for the per-component split and fallback rate.
"""

from __future__ import annotations

import argparse
import dataclasses
import enum
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


#: Minimum distinct-day count for ``yellow``. Below this -> ``red``.
#: Matches the ADR-0065 cutover-confidence floor (seven days).
DEFAULT_BASELINE_MIN_DAYS = 7


#: Comfort-floor distinct-day count for ``green``. Two weeks of
#: operational evidence. Between MIN and COMFORT the status is
#: yellow: the cutover is technically allowed but the burn-up is
#: still building.
DEFAULT_BASELINE_COMFORT_DAYS = 14


#: ENV the Tag-24 trigger-gate aggregator's Gate-4 reads. Sharing
#: the same ENV name guarantees the tracker and the aggregator
#: inspect the same baseline file.
ENV_PHASE_3C_OBS_BASELINE_PATH = "WAKIR_PHASE_3C_OBS_BASELINE_PATH"


#: ENV the live observability aggregator
#: (``scripts/backend-decision-observability.py``) reads. Used as a
#: secondary fallback so a deployment can configure one ENV and have
#: both lanes pick the file up.
ENV_BACKEND_DECISION_JSONL = "WAKIR_BACKEND_DECISION_JSONL"


#: Wire-string the engine emits to identify a BackendDecision record
#: in a mixed log_sink stream. Records WITHOUT a ``msg`` field are
#: also accepted (liberal-reader, matches the Tag-22 aggregator).
BACKEND_DECISION_MSG = "backend-decision"


#: Bucket key for records whose ``domain`` field is missing or empty.
COMPONENT_UNKNOWN_BUCKET = "component_unknown"


#: Bucket key for records whose ``chosen_backend`` field is null or
#: missing. We do not silently drop these.
BACKEND_UNKNOWN_BUCKET = "backend_unknown"


#: Regex pulling the first ``YYYY-MM-DD`` substring out of any
#: timestamp field. Aligns with the Tag-24 Gate-4 day-distinct logic.
_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


# ---------------------------------------------------------------------------
# Result-types
# ---------------------------------------------------------------------------


class BaselineStatus(str, enum.Enum):
    """Tri-state baseline status. String-enum so it round-trips through JSON."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclasses.dataclass(frozen=True)
class ComponentStats:
    """Per-component split. All counts are non-negative ints."""

    component: str
    total_decisions: int
    python_count: int
    rust_count: int
    other_count: int
    fallback_count: int

    @property
    def python_rate(self) -> float:
        if self.total_decisions == 0:
            return 0.0
        return self.python_count / self.total_decisions

    @property
    def rust_rate(self) -> float:
        if self.total_decisions == 0:
            return 0.0
        return self.rust_count / self.total_decisions

    @property
    def fallback_rate(self) -> float:
        if self.total_decisions == 0:
            return 0.0
        return self.fallback_count / self.total_decisions

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component": self.component,
            "total_decisions": self.total_decisions,
            "python_count": self.python_count,
            "rust_count": self.rust_count,
            "other_count": self.other_count,
            "fallback_count": self.fallback_count,
            "python_rate": round(self.python_rate, 6),
            "rust_rate": round(self.rust_rate, 6),
            "fallback_rate": round(self.fallback_rate, 6),
        }


@dataclasses.dataclass(frozen=True)
class BaselineReport:
    """Top-level tracker report.

    ``days_of_data`` is computed as ``(latest_day - earliest_day) + 1``
    when both anchors resolve, or 0 otherwise. ``distinct_days`` is the
    SET-cardinality of all observed day-buckets (the substantive
    Gate-4-equivalent measure).
    """

    schema: str
    status: BaselineStatus
    reason: str
    jsonl_path: Optional[str]
    sample_count: int
    parse_errors: int
    earliest_ts: Optional[str]
    latest_ts: Optional[str]
    earliest_day: Optional[str]
    latest_day: Optional[str]
    distinct_days: int
    days_of_data: int
    min_days_required: int
    comfort_days_required: int
    components: List[ComponentStats]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status.value,
            "reason": self.reason,
            "jsonl_path": self.jsonl_path,
            "sample_count": self.sample_count,
            "parse_errors": self.parse_errors,
            "earliest_ts": self.earliest_ts,
            "latest_ts": self.latest_ts,
            "earliest_day": self.earliest_day,
            "latest_day": self.latest_day,
            "distinct_days": self.distinct_days,
            "days_of_data": self.days_of_data,
            "min_days_required": self.min_days_required,
            "comfort_days_required": self.comfort_days_required,
            "components": [c.to_dict() for c in self.components],
        }

    @property
    def exit_code(self) -> int:
        return {
            BaselineStatus.GREEN: 0,
            BaselineStatus.YELLOW: 1,
            BaselineStatus.RED: 2,
        }[self.status]


# ---------------------------------------------------------------------------
# Record-parsing helpers
# ---------------------------------------------------------------------------


def _is_backend_decision_record(obj: Any) -> bool:
    """Return True when ``obj`` is a dict that looks like a backend-decision.

    Liberal-reader: records without a ``msg`` field (raw test fixtures
    or pre-envelope log_sink writes) are accepted. Records with a
    ``msg`` field must match :data:`BACKEND_DECISION_MSG`.
    """

    if not isinstance(obj, dict):
        return False
    msg = obj.get("msg")
    if msg is None:
        return True
    return msg == BACKEND_DECISION_MSG


def _extract_timestamp(record: Mapping[str, Any]) -> Optional[str]:
    """Pull the first non-empty timestamp field from the record.

    Field-name priority mirrors the Tag-24 Gate-4 logic plus
    ``ts_utc`` (the field name the persona-engine's ``_log`` helper
    stamps on production records).
    """

    for key in ("ts_utc", "ts", "timestamp", "time"):
        val = record.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _extract_day(ts: Optional[str]) -> Optional[str]:
    """Return the ``YYYY-MM-DD`` day-bucket for ``ts`` if parseable."""

    if not ts:
        return None
    m = _ISO_DATE_RE.search(ts)
    return m.group(0) if m else None


def _normalise_backend(value: Any) -> str:
    """Lower-case the chosen_backend value, mapping null/missing to a sentinel."""

    if value is None:
        return BACKEND_UNKNOWN_BUCKET
    if not isinstance(value, str):
        return BACKEND_UNKNOWN_BUCKET
    stripped = value.strip().lower()
    if not stripped:
        return BACKEND_UNKNOWN_BUCKET
    return stripped


def _normalise_component(value: Any) -> str:
    """Map the JSONL ``domain`` field to a component key."""

    if value is None:
        return COMPONENT_UNKNOWN_BUCKET
    if not isinstance(value, str):
        return COMPONENT_UNKNOWN_BUCKET
    stripped = value.strip()
    if not stripped:
        return COMPONENT_UNKNOWN_BUCKET
    return stripped


def _backend_family(chosen: str) -> str:
    """Map a normalised chosen_backend to ``python|rust|other``.

    The persona-engine surfaces several Rust sub-variants
    (``rust``, ``rust_inmemory``, ``rust_natskv``, ...). For the
    tracker's python-vs-rust split we lump them all into ``rust``.
    Anything else (the ``BACKEND_UNKNOWN_BUCKET`` sentinel,
    transitional values) falls into ``other``.
    """

    if chosen == "python":
        return "python"
    if chosen.startswith("rust"):
        return "rust"
    return "other"


def _has_fallback(record: Mapping[str, Any]) -> bool:
    """Return True when the record signals a fallback to Python.

    A record is a fallback when ``fallback_reason`` is a non-empty
    string. The persona-engine writes ``None`` (or omits the field)
    on the clean-Rust path, and a token like ``binary_missing`` /
    ``binary_not_executable`` / ``explicit_python`` on the fallback
    path.
    """

    reason = record.get("fallback_reason")
    return isinstance(reason, str) and bool(reason.strip())


# ---------------------------------------------------------------------------
# JSONL ingestion
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _Accumulator:
    """Mutable in-flight state during JSONL ingestion."""

    sample_count: int = 0
    parse_errors: int = 0
    earliest_ts: Optional[str] = None
    latest_ts: Optional[str] = None
    distinct_days: set = dataclasses.field(default_factory=set)
    # component -> {"total": int, "python": int, "rust": int,
    #               "other": int, "fallback": int}
    component_counts: Dict[str, Dict[str, int]] = dataclasses.field(
        default_factory=dict
    )

    def observe(self, record: Mapping[str, Any]) -> None:
        self.sample_count += 1
        ts = _extract_timestamp(record)
        if ts:
            if self.earliest_ts is None or ts < self.earliest_ts:
                self.earliest_ts = ts
            if self.latest_ts is None or ts > self.latest_ts:
                self.latest_ts = ts
            day = _extract_day(ts)
            if day:
                self.distinct_days.add(day)

        comp = _normalise_component(record.get("domain"))
        chosen = _normalise_backend(record.get("chosen_backend"))
        family = _backend_family(chosen)
        slot = self.component_counts.setdefault(
            comp,
            {"total": 0, "python": 0, "rust": 0, "other": 0, "fallback": 0},
        )
        slot["total"] += 1
        slot[family] += 1
        if _has_fallback(record):
            slot["fallback"] += 1


def _ingest_jsonl(path: Path) -> _Accumulator:
    """Stream the JSONL file into an :class:`_Accumulator`.

    Tolerant reader: lines that do not parse as JSON, or that parse
    into a non-backend-decision shape, are counted as parse-errors
    but do not abort the ingest. This mirrors the Tag-22 aggregator's
    liberal-reader posture.
    """

    acc = _Accumulator()
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                acc.parse_errors += 1
                continue
            if not _is_backend_decision_record(obj):
                acc.parse_errors += 1
                continue
            acc.observe(obj)
    return acc


# ---------------------------------------------------------------------------
# Public API: build_report
# ---------------------------------------------------------------------------


SCHEMA_ID = "wakir.phase-3c.observability-baseline-tracker/1"


def _days_of_data(earliest_day: Optional[str], latest_day: Optional[str]) -> int:
    """Return ``(latest - earliest) + 1`` as a calendar-day span.

    Both anchors are ``YYYY-MM-DD`` strings produced by
    :func:`_extract_day`, so lexical comparison is calendar-correct.
    We compute the span via :mod:`datetime` to avoid hand-rolled
    calendar math. Returns 0 when either anchor is None.
    """

    if not earliest_day or not latest_day:
        return 0
    from datetime import date

    try:
        e = date.fromisoformat(earliest_day)
        l = date.fromisoformat(latest_day)
    except ValueError:
        return 0
    delta = (l - e).days
    if delta < 0:
        return 0
    return delta + 1


def _classify(
    distinct_days: int,
    *,
    min_days: int,
    comfort_days: int,
) -> Tuple[BaselineStatus, str]:
    """Map ``distinct_days`` to a tri-state status + a human reason."""

    if distinct_days < min_days:
        return (
            BaselineStatus.RED,
            f"distinct_days={distinct_days} < min_days={min_days}",
        )
    if distinct_days < comfort_days:
        return (
            BaselineStatus.YELLOW,
            f"distinct_days={distinct_days} in [{min_days}, {comfort_days})",
        )
    return (
        BaselineStatus.GREEN,
        f"distinct_days={distinct_days} >= comfort_days={comfort_days}",
    )


def build_report(
    jsonl_path: Optional[Path],
    *,
    min_days: int = DEFAULT_BASELINE_MIN_DAYS,
    comfort_days: int = DEFAULT_BASELINE_COMFORT_DAYS,
) -> BaselineReport:
    """Compute the baseline-tracker report for ``jsonl_path``.

    ``jsonl_path=None`` (no path resolved) yields a red report. Same
    posture when the resolved path does not exist on disk.
    """

    if jsonl_path is None:
        return BaselineReport(
            schema=SCHEMA_ID,
            status=BaselineStatus.RED,
            reason="no-path-configured",
            jsonl_path=None,
            sample_count=0,
            parse_errors=0,
            earliest_ts=None,
            latest_ts=None,
            earliest_day=None,
            latest_day=None,
            distinct_days=0,
            days_of_data=0,
            min_days_required=min_days,
            comfort_days_required=comfort_days,
            components=[],
        )

    if not jsonl_path.is_file():
        return BaselineReport(
            schema=SCHEMA_ID,
            status=BaselineStatus.RED,
            reason="jsonl-file-not-found",
            jsonl_path=str(jsonl_path),
            sample_count=0,
            parse_errors=0,
            earliest_ts=None,
            latest_ts=None,
            earliest_day=None,
            latest_day=None,
            distinct_days=0,
            days_of_data=0,
            min_days_required=min_days,
            comfort_days_required=comfort_days,
            components=[],
        )

    acc = _ingest_jsonl(jsonl_path)

    earliest_day = _extract_day(acc.earliest_ts)
    latest_day = _extract_day(acc.latest_ts)
    distinct_days = len(acc.distinct_days)
    days_span = _days_of_data(earliest_day, latest_day)

    status, reason = _classify(
        distinct_days, min_days=min_days, comfort_days=comfort_days
    )

    # Sample-count 0 -> red regardless of the threshold path (a
    # path-resolved-but-empty file is a meaningful red, not a green).
    if acc.sample_count == 0:
        status = BaselineStatus.RED
        reason = "no-samples-in-jsonl"

    components = sorted(
        (
            ComponentStats(
                component=name,
                total_decisions=slot["total"],
                python_count=slot["python"],
                rust_count=slot["rust"],
                other_count=slot["other"],
                fallback_count=slot["fallback"],
            )
            for name, slot in acc.component_counts.items()
        ),
        key=lambda c: c.component,
    )

    return BaselineReport(
        schema=SCHEMA_ID,
        status=status,
        reason=reason,
        jsonl_path=str(jsonl_path),
        sample_count=acc.sample_count,
        parse_errors=acc.parse_errors,
        earliest_ts=acc.earliest_ts,
        latest_ts=acc.latest_ts,
        earliest_day=earliest_day,
        latest_day=latest_day,
        distinct_days=distinct_days,
        days_of_data=days_span,
        min_days_required=min_days,
        comfort_days_required=comfort_days,
        components=components,
    )


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def resolve_jsonl_path(
    cli_path: Optional[str],
    env: Optional[Mapping[str, str]] = None,
) -> Optional[Path]:
    """Resolve the JSONL path per the documented priority order.

      1. ``cli_path`` (operator-hand override).
      2. ``WAKIR_PHASE_3C_OBS_BASELINE_PATH`` ENV.
      3. ``WAKIR_BACKEND_DECISION_JSONL`` ENV.
      4. None (caller turns into a red report).

    Empty/whitespace-only strings count as unset.
    """

    env_map = env if env is not None else os.environ
    if cli_path and cli_path.strip():
        return Path(cli_path.strip())
    for key in (ENV_PHASE_3C_OBS_BASELINE_PATH, ENV_BACKEND_DECISION_JSONL):
        val = env_map.get(key)
        if isinstance(val, str) and val.strip():
            return Path(val.strip())
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="phase-3c-observability-baseline-tracker",
        description=(
            "Phase-3c Gate-4 observability baseline tracker: per-component "
            "python-vs-rust split + day-of-data burn-up status."
        ),
    )
    p.add_argument(
        "--jsonl-path",
        type=str,
        default=None,
        help=(
            "Path to the backend-decision JSONL. Overrides "
            f"${ENV_PHASE_3C_OBS_BASELINE_PATH} and "
            f"${ENV_BACKEND_DECISION_JSONL}."
        ),
    )
    p.add_argument(
        "--min-days",
        type=int,
        default=DEFAULT_BASELINE_MIN_DAYS,
        help=(
            "Distinct-day count required for at least yellow "
            f"(default: {DEFAULT_BASELINE_MIN_DAYS})."
        ),
    )
    p.add_argument(
        "--comfort-days",
        type=int,
        default=DEFAULT_BASELINE_COMFORT_DAYS,
        help=(
            "Distinct-day count required for green "
            f"(default: {DEFAULT_BASELINE_COMFORT_DAYS})."
        ),
    )
    p.add_argument(
        "--out",
        type=str,
        default=None,
        help=(
            "Write the JSON report to this path (in addition to stdout). "
            "Used by the daily-snapshot workflow."
        ),
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.min_days < 1:
        print(
            "phase-3c-observability-baseline-tracker: --min-days must be >= 1",
            file=sys.stderr,
        )
        return 2
    if args.comfort_days < args.min_days:
        print(
            "phase-3c-observability-baseline-tracker: --comfort-days must "
            ">= --min-days",
            file=sys.stderr,
        )
        return 2

    jsonl_path = resolve_jsonl_path(args.jsonl_path)
    report = build_report(
        jsonl_path,
        min_days=args.min_days,
        comfort_days=args.comfort_days,
    )

    payload = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    print(payload)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload + "\n", encoding="utf-8")

    return report.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
