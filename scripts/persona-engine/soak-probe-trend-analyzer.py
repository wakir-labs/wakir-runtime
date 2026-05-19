#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Persona-Engine Soak-Probe Daily-Trend-Analyzer (Tag-55).

Context
-------

Tag-54 PR #348 shipped ``scripts/persona-engine/soak-probe-5-day.py``
-- the sandbox-side compressed-time 5-day soak probe for the
Persona-Engine 0.5.2-final-pre-cutover boot fan-out + FSM + V-907
substrates. The probe verifies six invariants (A boot-decisions
stable, A' boot-decisions count==10, B FSM trace hash stable,
C V-907 pin stable, D resource object-count within budget,
D' decision-payload-bytes stable).

Tag-55 promotes that single-shot probe into an *autonomous daily
trend tracker* for the ~3-week pre-KW-24-Cutover window. The
companion workflow ``persona-engine-soak-probe-daily.yml`` runs
the probe once per day at 05:00 UTC, persists the resulting
report into ``state/soak-probe-daily-trend/yyyy-mm-dd.json``,
and invokes this analyzer to:

* Aggregate per-day overall-OK + per-invariant-OK into a
  Last-N-Days window (default 7 days).
* Detect verdict *changes* day-over-day (e.g. an invariant that
  was passing yesterday but fails today -> INVARIANT-DEGRADED;
  recovered -> INVARIANT-IMPROVED).
* Compute Stability counters: how many days in the last N was
  the overall_ok = True? Per-invariant pass-rate over the window?
* Surface invariant-fail events into a Mira-notify-emitter
  compatible JSONL feed (``state/soak-probe-notify-events.jsonl``)
  for operator-inbox materialisation.
* Emit a rolled-up trend report (JSON + Markdown) for the
  GitHub-Actions-Job-Summary.

The notify-event envelopes carry severity ``warning`` (single-day
invariant-fail) or ``page`` (two-or-more consecutive days of
invariant-fail; canonical "cutover-blocker" signal). The format
matches ``scripts/observability/mira-notify-emitter.py`` schema
version "1" so the existing Mira-Notify-Receiver picks it up
without bespoke routing.

Sandbox-mode posture
--------------------

The probe runs in compressed-time sandbox mode (no real time
passes -- the "5 days" is a counter). The trend tracker is a
*meta*-tracker: it samples one probe-run per real day and reports
on the cross-day stability of *the probe's own deterministic
output*. Any drift across real days is a structural signal:

  * Either the runtime tree changed (legitimate -- new feature
    landed, expect a new fingerprint baseline); or
  * The probe substrate itself is non-deterministic (a leak, a
    crate-side state-accumulator, gc-internals drift); the
    Tag-55 trend tracker is precisely the witness that catches
    the second case before the cutover-day Live-VM rehearsal.

Pure-function-vs-IO split
-------------------------

Everything above the ``# --- I/O boundary ---`` marker is pure
stdlib + can be exercised by hermetic tests with synthetic
report inputs. The I/O wrappers (``walk_daily_state_dir``,
``write_notify_events``, ``persist_daily_report``) sit at the
bottom.

Cross-zone discipline
---------------------

This analyzer is sandbox-side persona-engine work (Selin /
pengine domain). It does NOT:

  * Edit persona-definition files (Aisha-domain).
  * Touch WAT-core / OTS-anchor logic (Tomás-domain, Zone K).
  * Touch identity-substrate keys (Reza-domain, Zone L).
  * Touch Quadlet container definitions (Kai-domain, Zone J).

It reads the soak-probe report JSON (Tag-54 substrate; same-
zone) and emits Mira-notify-emitter-compatible JSONL (Tag-46
Noa-SRE substrate; cross-zone consumer, read-only against its
schema).

Anchors
-------

* Tag-54 PR #348 -- ``soak-probe-5-day.py`` substrate.
* Tag-46 PR #294 -- ``mira-notify-emitter.py`` schema v1.
* Tag-44 PR #287 -- ``pre-cutover-daily-trend-analyzer.py``
  (sister tracker, same Last-N-Days windowing pattern).

Author: Selin Çelik (Persona-Engine-Engineer), Tag-55, 2026-05-19.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------

# The six invariant keys emitted by soak-probe-5-day.py
# (DEFAULT_INVARIANT_KEYS in that module's _check_invariants).
ALL_INVARIANT_KEYS: tuple[str, ...] = (
    "A_boot_decisions_stable",
    "A_boot_decisions_count_ten",
    "B_fsm_trace_hash_stable",
    "C_v907_pin_stable",
    "D_resource_object_count_within_budget",
    "D_decision_payload_bytes_stable",
)

CHANGE_KIND_DEGRADED = "INVARIANT-DEGRADED"
CHANGE_KIND_IMPROVED = "INVARIANT-IMPROVED"
CHANGE_KIND_LATERAL = "INVARIANT-LATERAL"
CHANGE_KIND_NEW = "INVARIANT-NEW"
CHANGE_KIND_FINGERPRINT_DRIFT = "FINGERPRINT-DRIFT"

DEFAULT_WINDOW_DAYS = 7
DEFAULT_STATE_DIR = "state/soak-probe-daily-trend"
DEFAULT_NOTIFY_PATH = "state/soak-probe-notify-events.jsonl"

# Notify-emitter schema-v1 constants (mirror mira-notify-emitter.py).
NOTIFY_SCHEMA_VERSION = "1"
NOTIFY_SOURCE = "soak-probe-trend-analyzer"
# Runbook URL: pending the dedicated runbook document (SRE/Noa
# follow-up). The URL is the canonical anchor a Mira-notify-emitter
# severity=page event must carry (validate_event() requirement).
# Points to the trend-analyzer source as the interim operator
# reference; the dedicated runbook MD will land in a sibling PR
# alongside the first observed cutover-blocker fire.
NOTIFY_RUNBOOK_URL = (
    "https://github.com/wakir-labs/wakir-runtime/blob/main/"
    "scripts/persona-engine/soak-probe-trend-analyzer.py"
)
ALERT_NAME_INVARIANT_FAIL = "PersonaEngineSoakProbeInvariantFail"
ALERT_NAME_PERSISTENT_FAIL = "PersonaEngineSoakProbePersistentFail"
ALERT_NAME_FINGERPRINT_DRIFT = "PersonaEngineSoakProbeFingerprintDrift"


# ---------------------------------------------------------------------
# Data classes.
# ---------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class DailyReport:
    """One day's recorded soak-probe snapshot.

    Mirrors the report-dict shape emitted by
    ``scripts/persona-engine/soak-probe-5-day.py``
    (``SoakReport.as_dict``), but reduced to the cross-day-stable
    fields the trend tracker needs. The observational
    ``object_count`` is intentionally dropped from the comparison
    fingerprint (gc-internals vary slightly across interpreter
    sessions); invariant D bounds the *delta* within the probe
    run, not absolute equality across runs.
    """

    date_iso: str  # yyyy-mm-dd (UTC)
    overall_ok: bool
    invariants_passed: int
    invariants_total: int
    days_observed: int
    invariant_oks: dict[str, bool]  # key -> ok
    # Cross-day-stable fingerprint = (boot_fp[0], fsm_hash[0],
    # v907_pin[0], decisions_payload_bytes[0]). Day-1 sample is
    # sufficient because invariants A/B/C/D' assert intra-day
    # stability already.
    boot_fp: str
    fsm_trace_hash: str
    v907_pin: str
    decisions_payload_bytes: int

    def to_envelope(self) -> dict[str, Any]:
        return {
            "date_iso": self.date_iso,
            "overall_ok": self.overall_ok,
            "invariants_passed": self.invariants_passed,
            "invariants_total": self.invariants_total,
            "days_observed": self.days_observed,
            "invariant_oks": dict(self.invariant_oks),
            "boot_fp": self.boot_fp,
            "fsm_trace_hash": self.fsm_trace_hash,
            "v907_pin": self.v907_pin,
            "decisions_payload_bytes": self.decisions_payload_bytes,
        }


@dataclasses.dataclass(frozen=True)
class InvariantChange:
    """An invariant's pass/fail differs day-over-day, or a
    cross-day-stable fingerprint shifted."""

    date_iso: str
    scope: str  # "invariant:<key>" or "fingerprint:<field>"
    invariant_key: str | None  # populated when scope is invariant
    fingerprint_field: str | None  # populated when scope is fingerprint
    previous: str | None  # "PASS"/"FAIL" or hex prefix
    current: str  # "PASS"/"FAIL" or hex prefix
    kind: str  # one of CHANGE_KIND_*

    def to_envelope(self) -> dict[str, Any]:
        return {
            "date_iso": self.date_iso,
            "scope": self.scope,
            "invariant_key": self.invariant_key,
            "fingerprint_field": self.fingerprint_field,
            "previous": self.previous,
            "current": self.current,
            "kind": self.kind,
        }


@dataclasses.dataclass(frozen=True)
class TrendReport:
    """Aggregate Last-N-Days trend rollup for one snapshot date."""

    today_date_iso: str
    window_days: int
    today_report: DailyReport
    yesterday_report: DailyReport | None
    window_dates: tuple[str, ...]
    overall_ok_history: tuple[bool, ...]
    per_invariant_history: dict[str, tuple[bool, ...]]
    per_invariant_pass_rate: dict[str, float]
    overall_ok_count: int
    overall_fail_count: int
    consecutive_fail_streak: int  # ending at today
    changes: tuple[InvariantChange, ...]

    def to_envelope(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "today_date_iso": self.today_date_iso,
            "window_days": self.window_days,
            "today_report": self.today_report.to_envelope(),
            "yesterday_report": (
                self.yesterday_report.to_envelope()
                if self.yesterday_report is not None
                else None
            ),
            "window_dates": list(self.window_dates),
            "overall_ok_history": list(self.overall_ok_history),
            "per_invariant_history": {
                k: list(v) for k, v in self.per_invariant_history.items()
            },
            "per_invariant_pass_rate": {
                k: v for k, v in self.per_invariant_pass_rate.items()
            },
            "overall_ok_count": self.overall_ok_count,
            "overall_fail_count": self.overall_fail_count,
            "consecutive_fail_streak": self.consecutive_fail_streak,
            "changes": [c.to_envelope() for c in self.changes],
        }


# ---------------------------------------------------------------------
# Pure-function logic.
# ---------------------------------------------------------------------


def parse_soak_report(blob: dict[str, Any], fallback_date_iso: str = "") -> DailyReport:
    """Parse a soak-probe report JSON blob into a DailyReport.

    Accepts either:
      - the analyzer's own persisted shape (with ``date_iso`` +
        ``boot_fp``/``fsm_trace_hash``/etc top-level), or
      - the raw soak-probe-5-day report shape (with ``days[]`` +
        ``invariants{}`` + ``summary{}``).

    Raises ``ValueError`` on shape mismatch.
    """
    if not isinstance(blob, dict):
        raise ValueError(f"blob is not a dict: {type(blob).__name__}")

    # Analyzer's persisted shape.
    if "date_iso" in blob and "boot_fp" in blob and "invariant_oks" in blob:
        return DailyReport(
            date_iso=str(blob["date_iso"]),
            overall_ok=bool(blob.get("overall_ok", False)),
            invariants_passed=int(blob.get("invariants_passed", 0)),
            invariants_total=int(blob.get("invariants_total", 0)),
            days_observed=int(blob.get("days_observed", 0)),
            invariant_oks={
                str(k): bool(v)
                for k, v in (blob.get("invariant_oks") or {}).items()
            },
            boot_fp=str(blob.get("boot_fp", "")),
            fsm_trace_hash=str(blob.get("fsm_trace_hash", "")),
            v907_pin=str(blob.get("v907_pin", "")),
            decisions_payload_bytes=int(
                blob.get("decisions_payload_bytes", 0)
            ),
        )

    # Raw soak-probe-5-day report shape.
    summary = blob.get("summary") or {}
    invariants_raw = blob.get("invariants") or {}
    days_arr = blob.get("days") or []
    if not isinstance(days_arr, list) or not days_arr:
        raise ValueError(
            "raw soak-probe report missing 'days' list"
        )
    if not isinstance(summary, dict):
        raise ValueError("raw soak-probe report 'summary' is not a dict")
    if not isinstance(invariants_raw, dict):
        raise ValueError("raw soak-probe report 'invariants' is not a dict")

    day1 = days_arr[0]
    if not isinstance(day1, dict):
        raise ValueError("raw soak-probe report day-1 is not a dict")

    invariant_oks: dict[str, bool] = {}
    for key, val in invariants_raw.items():
        if isinstance(val, dict):
            invariant_oks[str(key)] = bool(val.get("ok", False))
        elif isinstance(val, (list, tuple)) and val:
            invariant_oks[str(key)] = bool(val[0])
        else:
            invariant_oks[str(key)] = bool(val)

    return DailyReport(
        date_iso=fallback_date_iso,
        overall_ok=bool(summary.get("overall_ok", False)),
        invariants_passed=int(summary.get("invariants_passed", 0)),
        invariants_total=int(summary.get("invariants_total", 0)),
        days_observed=int(summary.get("days_observed", 0)),
        invariant_oks=invariant_oks,
        boot_fp=str(day1.get("boot_decisions_fingerprint", "")),
        fsm_trace_hash=str(day1.get("fsm_trace_hash", "")),
        v907_pin=str(day1.get("v907_pin", "")),
        decisions_payload_bytes=int(
            day1.get("decisions_payload_bytes", 0)
        ),
    )


def classify_invariant_change(
    previous: bool | None, current: bool
) -> str:
    """Classify an invariant pass/fail transition."""
    if previous is None:
        return CHANGE_KIND_NEW
    if previous == current:
        return CHANGE_KIND_LATERAL
    if previous is True and current is False:
        return CHANGE_KIND_DEGRADED
    if previous is False and current is True:
        return CHANGE_KIND_IMPROVED
    # Unreachable; satisfies type-checker.
    return CHANGE_KIND_LATERAL


def compute_window_dates(
    today_iso: str, window_days: int
) -> tuple[str, ...]:
    """Return the inclusive Last-N-Days window of yyyy-mm-dd strings
    ending at ``today_iso``."""
    if window_days < 1:
        raise ValueError(f"window_days must be >= 1, got {window_days}")
    today = date.fromisoformat(today_iso)
    out = [
        (today - timedelta(days=offset)).isoformat()
        for offset in range(window_days - 1, -1, -1)
    ]
    return tuple(out)


def compute_consecutive_fail_streak(
    overall_ok_history: tuple[bool | None, ...]
) -> int:
    """Count the trailing consecutive-False entries ending at the
    last element of the history."""
    streak = 0
    for ok in reversed(overall_ok_history):
        if ok is False:
            streak += 1
        else:
            break
    return streak


def build_trend_report(
    today_iso: str,
    window_days: int,
    state: dict[str, DailyReport],
) -> TrendReport:
    """Construct a TrendReport from the per-day state dict.

    ``state`` maps yyyy-mm-dd -> DailyReport.  Days absent from
    the state dict are treated as "no observation" (not "fail");
    the analyzer is forgiving of missing days (CI-run skipped,
    runner-pool outage). The history-tuple uses ``None`` for
    absent days; pass-rate calculations divide by observed days
    only.
    """
    today_report = state.get(today_iso)
    if today_report is None:
        raise ValueError(
            f"no report for today ({today_iso}) in state dict; "
            f"keys: {sorted(state)}"
        )

    window_dates = compute_window_dates(today_iso, window_days)

    # Build per-day overall_ok history (None for absent days).
    overall_ok_history: list[bool | None] = []
    per_invariant_history_lists: dict[str, list[bool | None]] = {
        k: [] for k in ALL_INVARIANT_KEYS
    }
    for d in window_dates:
        rep = state.get(d)
        if rep is None:
            overall_ok_history.append(None)
            for k in ALL_INVARIANT_KEYS:
                per_invariant_history_lists[k].append(None)
        else:
            overall_ok_history.append(rep.overall_ok)
            for k in ALL_INVARIANT_KEYS:
                per_invariant_history_lists[k].append(
                    rep.invariant_oks.get(k)
                )

    # Pass-rate per invariant: count(True) / count(observed-not-None).
    per_invariant_pass_rate: dict[str, float] = {}
    for k in ALL_INVARIANT_KEYS:
        seq = per_invariant_history_lists[k]
        observed = [x for x in seq if x is not None]
        if not observed:
            per_invariant_pass_rate[k] = 0.0
        else:
            per_invariant_pass_rate[k] = (
                sum(1 for x in observed if x) / len(observed)
            )

    overall_ok_count = sum(
        1 for x in overall_ok_history if x is True
    )
    overall_fail_count = sum(
        1 for x in overall_ok_history if x is False
    )

    # Yesterday's report (if present); used for verdict-change detection.
    yesterday_iso = (
        date.fromisoformat(today_iso) - timedelta(days=1)
    ).isoformat()
    yesterday_report = state.get(yesterday_iso)

    # Detect verdict changes today vs yesterday.
    changes: list[InvariantChange] = []
    for k in ALL_INVARIANT_KEYS:
        today_ok = today_report.invariant_oks.get(k)
        yesterday_ok = (
            yesterday_report.invariant_oks.get(k)
            if yesterday_report is not None
            else None
        )
        if today_ok is None:
            continue
        kind = classify_invariant_change(yesterday_ok, today_ok)
        if kind == CHANGE_KIND_LATERAL:
            # Don't emit a change-event for steady-state laterals.
            continue
        changes.append(
            InvariantChange(
                date_iso=today_iso,
                scope=f"invariant:{k}",
                invariant_key=k,
                fingerprint_field=None,
                previous=(
                    None
                    if yesterday_ok is None
                    else ("PASS" if yesterday_ok else "FAIL")
                ),
                current=("PASS" if today_ok else "FAIL"),
                kind=kind,
            )
        )

    # Detect fingerprint drift today vs yesterday. Fingerprint
    # drift is independent of invariant-fail (a build that changes
    # the runtime tree will legitimately shift the fp -- a drift
    # signal still warrants operator-eyes so we mark it).
    if yesterday_report is not None:
        for field in ("boot_fp", "fsm_trace_hash", "v907_pin"):
            prev_val = getattr(yesterday_report, field)
            curr_val = getattr(today_report, field)
            if prev_val and curr_val and prev_val != curr_val:
                changes.append(
                    InvariantChange(
                        date_iso=today_iso,
                        scope=f"fingerprint:{field}",
                        invariant_key=None,
                        fingerprint_field=field,
                        previous=prev_val[:16],
                        current=curr_val[:16],
                        kind=CHANGE_KIND_FINGERPRINT_DRIFT,
                    )
                )

    consecutive_fail_streak = compute_consecutive_fail_streak(
        tuple(overall_ok_history)
    )

    # Compact history -> tuples of bool (None coerced to False for
    # the public envelope; the absent-day count is implicit in
    # window_dates vs sum(history)).
    overall_ok_history_compact = tuple(
        bool(x) for x in overall_ok_history if x is not None
    )
    per_invariant_history_compact: dict[str, tuple[bool, ...]] = {
        k: tuple(bool(x) for x in v if x is not None)
        for k, v in per_invariant_history_lists.items()
    }

    return TrendReport(
        today_date_iso=today_iso,
        window_days=window_days,
        today_report=today_report,
        yesterday_report=yesterday_report,
        window_dates=window_dates,
        overall_ok_history=overall_ok_history_compact,
        per_invariant_history=per_invariant_history_compact,
        per_invariant_pass_rate=per_invariant_pass_rate,
        overall_ok_count=overall_ok_count,
        overall_fail_count=overall_fail_count,
        consecutive_fail_streak=consecutive_fail_streak,
        changes=tuple(changes),
    )


# ---------------------------------------------------------------------
# Notify-event construction (Mira-notify-emitter schema v1).
# ---------------------------------------------------------------------


def _now_utc_iso() -> str:
    """ISO-8601 UTC timestamp with Z suffix.

    Separated for test monkey-patching.
    """
    return datetime.now(tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _derive_event_id(
    alert_name: str, fired_at_utc: str, labels: dict[str, str]
) -> str:
    """Deterministic event-id (truncated sha256). Mirrors
    mira-notify-emitter.derive_event_id."""
    labels_json = json.dumps(dict(labels), sort_keys=True)
    payload = f"{alert_name}|{fired_at_utc}|{labels_json}"
    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()[:16]


def build_notify_events(
    report: TrendReport, fired_at_utc: str | None = None
) -> list[dict[str, Any]]:
    """Build Mira-notify-emitter-compatible notify-event dicts
    from a TrendReport.

    Emission policy:

      * One ``severity=page`` event when the consecutive_fail_streak
        is >= 2 (persistent failure -- canonical cutover-blocker).
      * One ``severity=warning`` event per INVARIANT-DEGRADED
        change observed today (single-day fail).
      * One ``severity=info`` event per FINGERPRINT-DRIFT change
        observed today (legitimate-build-shift or substrate drift;
        operator-eyes only).

    Same-day re-runs produce identical event_id values (dedupe-
    safe at the receiver).
    """
    fired_at_utc = fired_at_utc or _now_utc_iso()
    events: list[dict[str, Any]] = []

    if report.consecutive_fail_streak >= 2:
        labels = {
            "date_iso": report.today_date_iso,
            "streak": str(report.consecutive_fail_streak),
        }
        eid = _derive_event_id(
            ALERT_NAME_PERSISTENT_FAIL, fired_at_utc, labels
        )
        events.append(
            {
                "schema_version": NOTIFY_SCHEMA_VERSION,
                "event_id": eid,
                "alert_name": ALERT_NAME_PERSISTENT_FAIL,
                "severity": "page",
                "fired_at_utc": fired_at_utc,
                "failure_mode_id": None,
                "runbook_url": NOTIFY_RUNBOOK_URL,
                "summary": (
                    f"Persona-Engine soak-probe has been failing for "
                    f"{report.consecutive_fail_streak} consecutive "
                    f"days (ending {report.today_date_iso}). Cutover-"
                    f"blocker."
                )[:200],
                "description": None,
                "labels": labels,
                "annotations": {},
                "source": NOTIFY_SOURCE,
            }
        )

    for change in report.changes:
        if change.kind == CHANGE_KIND_DEGRADED:
            labels = {
                "date_iso": change.date_iso,
                "invariant_key": change.invariant_key or "",
            }
            eid = _derive_event_id(
                ALERT_NAME_INVARIANT_FAIL, fired_at_utc, labels
            )
            events.append(
                {
                    "schema_version": NOTIFY_SCHEMA_VERSION,
                    "event_id": eid,
                    "alert_name": ALERT_NAME_INVARIANT_FAIL,
                    "severity": "warning",
                    "fired_at_utc": fired_at_utc,
                    "failure_mode_id": None,
                    "runbook_url": NOTIFY_RUNBOOK_URL,
                    "summary": (
                        f"Persona-Engine soak-probe invariant "
                        f"{change.invariant_key} flipped PASS->FAIL "
                        f"on {change.date_iso}."
                    )[:200],
                    "description": None,
                    "labels": labels,
                    "annotations": {},
                    "source": NOTIFY_SOURCE,
                }
            )
        elif change.kind == CHANGE_KIND_FINGERPRINT_DRIFT:
            labels = {
                "date_iso": change.date_iso,
                "fingerprint_field": change.fingerprint_field or "",
                "previous": change.previous or "",
                "current": change.current or "",
            }
            eid = _derive_event_id(
                ALERT_NAME_FINGERPRINT_DRIFT, fired_at_utc, labels
            )
            events.append(
                {
                    "schema_version": NOTIFY_SCHEMA_VERSION,
                    "event_id": eid,
                    "alert_name": ALERT_NAME_FINGERPRINT_DRIFT,
                    "severity": "info",
                    "fired_at_utc": fired_at_utc,
                    "failure_mode_id": None,
                    "runbook_url": NOTIFY_RUNBOOK_URL,
                    "summary": (
                        f"Persona-Engine soak-probe fingerprint "
                        f"{change.fingerprint_field} drifted "
                        f"({change.previous}...->{change.current}...) "
                        f"on {change.date_iso}."
                    )[:200],
                    "description": None,
                    "labels": labels,
                    "annotations": {},
                    "source": NOTIFY_SOURCE,
                }
            )

    return events


# ---------------------------------------------------------------------
# Markdown rendering.
# ---------------------------------------------------------------------


def render_trend_markdown(report: TrendReport) -> str:
    """Render the trend report as a Job-Summary-friendly markdown."""
    lines: list[str] = []
    lines.append(
        f"# Persona-Engine Soak-Probe Daily Trend "
        f"({report.today_date_iso})"
    )
    lines.append("")
    lines.append(
        f"Window: **Last {report.window_days} days** "
        f"(`{report.window_dates[0]}` to `{report.window_dates[-1]}`)"
    )
    lines.append("")
    lines.append(f"**Today's overall_ok:** "
                 f"`{report.today_report.overall_ok}`")
    lines.append(
        f"**Today's invariants:** "
        f"{report.today_report.invariants_passed} / "
        f"{report.today_report.invariants_total}"
    )
    lines.append(
        f"**Window overall-OK days:** "
        f"{report.overall_ok_count} (FAIL: {report.overall_fail_count})"
    )
    lines.append(
        f"**Consecutive-fail streak (ending today):** "
        f"{report.consecutive_fail_streak}"
    )
    lines.append("")
    lines.append("## Per-invariant pass rate (window)")
    lines.append("")
    lines.append("| Invariant | Pass rate |")
    lines.append("|---|---|")
    for k in ALL_INVARIANT_KEYS:
        pct = report.per_invariant_pass_rate.get(k, 0.0) * 100.0
        lines.append(f"| `{k}` | {pct:.1f}% |")
    lines.append("")
    lines.append("## Today's cross-day-stable fingerprints (head-16)")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(
        f"| boot_fp | `{report.today_report.boot_fp[:16]}...` |"
    )
    lines.append(
        f"| fsm_trace_hash | "
        f"`{report.today_report.fsm_trace_hash[:16]}...` |"
    )
    lines.append(
        f"| v907_pin | `{report.today_report.v907_pin[:16]}...` |"
    )
    lines.append(
        f"| decisions_payload_bytes | "
        f"`{report.today_report.decisions_payload_bytes}` |"
    )
    lines.append("")
    if report.changes:
        lines.append("## Verdict changes today vs yesterday")
        lines.append("")
        lines.append("| Scope | Previous | Current | Kind |")
        lines.append("|---|---|---|---|")
        for c in report.changes:
            lines.append(
                f"| `{c.scope}` | `{c.previous or 'n/a'}` | "
                f"`{c.current}` | `{c.kind}` |"
            )
        lines.append("")
    else:
        lines.append("_No verdict changes today vs yesterday._")
        lines.append("")
    lines.append(
        "Anchors: Tag-54 soak-probe-5-day.py; "
        "Tag-55 soak-probe-trend-analyzer.py."
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------
# --- I/O boundary ---
# Everything below performs filesystem reads/writes. Pure-function
# tests target only the code above this marker.
# ---------------------------------------------------------------------


def walk_daily_state_dir(state_dir: Path) -> dict[str, DailyReport]:
    """Read every yyyy-mm-dd.json in ``state_dir`` and return a
    ``{date_iso: DailyReport}`` map.  Skips unreadable files silently.
    """
    out: dict[str, DailyReport] = {}
    if not state_dir.exists():
        return out
    for p in sorted(state_dir.iterdir()):
        if not p.is_file():
            continue
        if not p.name.endswith(".json"):
            continue
        stem = p.stem
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        try:
            rep = parse_soak_report(blob, fallback_date_iso=stem)
        except ValueError:
            continue
        out[rep.date_iso or stem] = rep
    return out


def write_notify_events(
    notify_path: Path, events: list[dict[str, Any]]
) -> int:
    """Append notify-events to JSONL feed.  Returns count appended."""
    if not events:
        return 0
    notify_path.parent.mkdir(parents=True, exist_ok=True)
    with notify_path.open("a", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, sort_keys=True) + "\n")
    return len(events)


def persist_daily_report(
    state_dir: Path, report: DailyReport
) -> Path:
    """Write a DailyReport to ``state_dir/yyyy-mm-dd.json``."""
    state_dir.mkdir(parents=True, exist_ok=True)
    out_path = state_dir / f"{report.date_iso}.json"
    out_path.write_text(
        json.dumps(report.to_envelope(), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return out_path


def ingest_soak_report(
    state_dir: Path,
    soak_report_path: Path,
    today_iso: str,
) -> DailyReport:
    """Read a raw soak-probe-5-day JSON report and persist it as
    ``state_dir/<today_iso>.json`` in the analyzer's normalized shape.

    Returns the persisted DailyReport.
    """
    blob = json.loads(soak_report_path.read_text(encoding="utf-8"))
    parsed = parse_soak_report(blob, fallback_date_iso=today_iso)
    # Force the persisted date_iso to today (caller-driven).
    parsed_with_date = DailyReport(
        date_iso=today_iso,
        overall_ok=parsed.overall_ok,
        invariants_passed=parsed.invariants_passed,
        invariants_total=parsed.invariants_total,
        days_observed=parsed.days_observed,
        invariant_oks=dict(parsed.invariant_oks),
        boot_fp=parsed.boot_fp,
        fsm_trace_hash=parsed.fsm_trace_hash,
        v907_pin=parsed.v907_pin,
        decisions_payload_bytes=parsed.decisions_payload_bytes,
    )
    persist_daily_report(state_dir, parsed_with_date)
    return parsed_with_date


# ---------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------


def _today_utc_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="soak-probe-trend-analyzer",
        description=(
            "Aggregate daily Persona-Engine soak-probe reports into "
            "a Last-N-Days trend report and emit Mira-notify-emitter-"
            "compatible JSONL events on invariant-fail / persistent-"
            "fail / fingerprint-drift."
        ),
    )
    p.add_argument(
        "--state-dir",
        default=DEFAULT_STATE_DIR,
        help=(
            f"Directory containing yyyy-mm-dd.json daily soak-probe "
            f"reports (default: {DEFAULT_STATE_DIR})."
        ),
    )
    p.add_argument(
        "--ingest-soak-report",
        default=None,
        help=(
            "Optional path to a raw soak-probe-5-day JSON report to "
            "ingest as today's snapshot (overwrites existing today's "
            "file in the state-dir)."
        ),
    )
    p.add_argument(
        "--today",
        default=None,
        help=(
            "Override today's date as yyyy-mm-dd "
            "(default: UTC today)."
        ),
    )
    p.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=f"Trend window size (default: {DEFAULT_WINDOW_DAYS}).",
    )
    p.add_argument(
        "--output-json",
        default=None,
        help="Write the trend report JSON to this path.",
    )
    p.add_argument(
        "--output-md",
        default=None,
        help="Write the trend report Markdown to this path.",
    )
    p.add_argument(
        "--notify-path",
        default=DEFAULT_NOTIFY_PATH,
        help=(
            f"JSONL feed for Mira-notify-emitter events "
            f"(default: {DEFAULT_NOTIFY_PATH})."
        ),
    )
    p.add_argument(
        "--no-notify",
        action="store_true",
        help="Skip writing notify-events.jsonl.",
    )
    p.add_argument(
        "--fail-on-invariant-fail",
        action="store_true",
        help=(
            "Exit non-zero (exit 1) when today's report has "
            "overall_ok=False. Default: exit 0 regardless (CI "
            "treats the run as informational unless this flag is "
            "supplied)."
        ),
    )
    return p


def cli_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    state_dir = Path(args.state_dir)
    today_iso = args.today or _today_utc_iso()

    if args.ingest_soak_report:
        soak_path = Path(args.ingest_soak_report)
        if not soak_path.exists():
            print(
                f"error: --ingest-soak-report path not found: "
                f"{soak_path}",
                file=sys.stderr,
            )
            return 2
        try:
            ingest_soak_report(state_dir, soak_path, today_iso)
        except (json.JSONDecodeError, ValueError) as exc:
            print(
                f"error: could not ingest soak-report "
                f"{soak_path}: {exc}",
                file=sys.stderr,
            )
            return 2

    state = walk_daily_state_dir(state_dir)
    if today_iso not in state:
        print(
            f"error: no daily-report for today ({today_iso}) found "
            f"in {state_dir}. Use --ingest-soak-report or pre-populate "
            f"the state-dir.",
            file=sys.stderr,
        )
        return 2

    report = build_trend_report(today_iso, args.window_days, state)

    if args.output_json:
        Path(args.output_json).parent.mkdir(
            parents=True, exist_ok=True
        )
        Path(args.output_json).write_text(
            json.dumps(report.to_envelope(), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

    if args.output_md:
        Path(args.output_md).parent.mkdir(
            parents=True, exist_ok=True
        )
        Path(args.output_md).write_text(
            render_trend_markdown(report), encoding="utf-8"
        )

    if not args.no_notify:
        events = build_notify_events(report)
        if events:
            write_notify_events(Path(args.notify_path), events)
            print(
                f"appended {len(events)} notify-events to "
                f"{args.notify_path}",
                file=sys.stderr,
            )

    if args.fail_on_invariant_fail and not report.today_report.overall_ok:
        print(
            f"today's soak-probe report has overall_ok=False "
            f"(invariants: "
            f"{report.today_report.invariants_passed}/"
            f"{report.today_report.invariants_total}); "
            f"--fail-on-invariant-fail set, exiting 1.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(cli_main())
