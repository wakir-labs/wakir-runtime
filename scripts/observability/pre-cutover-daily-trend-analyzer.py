#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Phase-3c Pre-Cutover Daily-Trend-Analyzer (Tag-44).

Context
-------

Reza Tag-43 PR #277 shipped the Pre-Cutover-Probe-Phase Live-Demo
orchestrator — a single-shot driver that exercises all seven
ADR-0066 Welle pre-cutover probes in sandbox-stub mode and emits a
per-Welle verdict + Marathon-Readiness aggregate.

Tag-44 promotes that single-shot driver into an *autonomous daily
trend tracker* for the ~3-week pre-KW-24-Cutover window
(2026-05-19 .. 2026-06-07). The companion workflow
``phase-3c-pre-cutover-daily-probe.yml`` runs the live-demo once
per day at 06:00 UTC, persists the resulting envelope into
``state/pre-cutover-daily-trend/yyyy-mm-dd.json``, and invokes
this analyzer to:

* Aggregate per-day verdicts into a Last-7-Days window per Welle.
* Detect verdict *changes* day-over-day (e.g.
  ``CAUTION -> BLOCK`` is a STATUS-DEGRADED event;
  ``BLOCK -> GREEN`` is a STATUS-IMPROVED event).
* Compute Marathon-Readiness stability counters: how many days
  in the last 7 was the aggregate ``READY``? ``BLOCK``?
* Emit a rolled-up trend-report (JSON + Markdown) for the
  GitHub-Actions-Job-Summary and for Mira-Hand-Sichtung.
* Surface verdict-change events into ``state/notify-events.jsonl``
  (operator-inbox feed; one JSON object per line).

Sandbox-stub posture
--------------------

The CI workflow runs the probes in
``--dry-run`` / ``WAKIR_SSH_BIN=true`` mode, so the verdicts
captured by this analyzer reflect *probe-script structural
health*, not live-VM cutover-readiness. The probe contract
mandates that a clean main snapshot in sandbox-stub mode yields
the ``BLOCK`` baseline (5 CAUTION + 1 GREEN + 1 BLOCK; Welle-7
IIA-1130 gate fires by design). Any drift from that baseline is
the trend signal.

Pure-function-vs-IO split
-------------------------

Everything above the ``# --- I/O boundary ---`` marker is pure
stdlib + can be exercised by hermetic tests with synthetic
envelope inputs. The I/O wrappers (``walk_daily_state_dir``,
``write_notify_event``) sit at the bottom.

Trend-Report-Generator-Mode
---------------------------

When invoked with ``--mode=weekly-bilanz``, the analyzer reads
the last N=7 daily-state files and produces a weekly bilanz
markdown summary suitable for the AR-Sitzung pre-cutover-review
(per Mira-Hand-Sichtung).

Anchors
-------

* ADR-0065 — Phase-3c cutover sequence.
* ADR-0066 — Doppel-Welle KW-24/26/27 ordering.
* Reza Tag-43 PR #277 — Pre-Cutover-Probe-Phase Live-Demo.
* Noa Tag-42 PR #270 (sister) — Marathon-Dashboard CI workflow.

Author: Reza Tehrani (Dev-Engineering-2), Sprint-Tag-44, 2026-05-18.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------

ALL_WELLES: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)
ALL_VERDICTS: tuple[str, ...] = ("GREEN", "CAUTION", "BLOCK", "NOT-EXEC")
ALL_AGGREGATES: tuple[str, ...] = ("READY", "CAUTION", "BLOCK", "NOT-READY")

# Verdict ordering for "degraded vs improved" classification.
# Higher rank == worse posture.
VERDICT_RANK: dict[str, int] = {
    "GREEN": 0,
    "CAUTION": 1,
    "NOT-EXEC": 2,
    "BLOCK": 3,
}
AGGREGATE_RANK: dict[str, int] = {
    "READY": 0,
    "CAUTION": 1,
    "BLOCK": 2,
    "NOT-READY": 3,
}

CHANGE_KIND_DEGRADED = "STATUS-DEGRADED"
CHANGE_KIND_IMPROVED = "STATUS-IMPROVED"
CHANGE_KIND_LATERAL = "STATUS-LATERAL"
CHANGE_KIND_NEW = "STATUS-NEW"

DEFAULT_WINDOW_DAYS = 7
DEFAULT_STATE_DIR = "state/pre-cutover-daily-trend"
DEFAULT_NOTIFY_PATH = "state/notify-events.jsonl"


# ---------------------------------------------------------------------
# Data classes.
# ---------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class DailyEnvelope:
    """One day's recorded pre-cutover-probe snapshot.

    Mirrors the envelope shape emitted by
    ``scripts/phase-3c/pre-cutover-probe-phase-live-demo.py``
    (Tag-43, Reza PR #277), but kept as a thin dataclass here so
    the analyzer is decoupled from the demo-script's
    implementation details.
    """

    date_iso: str  # yyyy-mm-dd (UTC)
    run_id: str
    aggregate: str
    per_welle: dict[int, str]  # welle -> verdict
    captured_at_utc: str
    expected_aggregate: str
    aggregate_match: bool

    def to_envelope(self) -> dict[str, Any]:
        return {
            "date_iso": self.date_iso,
            "run_id": self.run_id,
            "aggregate": self.aggregate,
            "per_welle": {str(k): v for k, v in self.per_welle.items()},
            "captured_at_utc": self.captured_at_utc,
            "expected_aggregate": self.expected_aggregate,
            "aggregate_match": self.aggregate_match,
        }


@dataclasses.dataclass(frozen=True)
class VerdictChange:
    """A welle (or aggregate) verdict differs day-over-day."""

    date_iso: str
    scope: str  # "welle-N" or "aggregate"
    welle: int | None
    previous: str | None
    current: str
    kind: str  # STATUS-DEGRADED / STATUS-IMPROVED / STATUS-LATERAL / STATUS-NEW

    def to_envelope(self) -> dict[str, Any]:
        return {
            "date_iso": self.date_iso,
            "scope": self.scope,
            "welle": self.welle,
            "previous": self.previous,
            "current": self.current,
            "kind": self.kind,
        }


@dataclasses.dataclass(frozen=True)
class TrendReport:
    """Aggregate Last-N-Days trend roll-up for one snapshot date."""

    today_date_iso: str
    window_days: int
    today_envelope: DailyEnvelope
    yesterday_envelope: DailyEnvelope | None
    window_dates: tuple[str, ...]
    aggregate_history: tuple[str, ...]
    per_welle_history: dict[int, tuple[str, ...]]
    per_welle_stability_pct: dict[int, float]
    aggregate_stability_counts: dict[str, int]
    changes: tuple[VerdictChange, ...]

    def to_envelope(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "today_date_iso": self.today_date_iso,
            "window_days": self.window_days,
            "today_envelope": self.today_envelope.to_envelope(),
            "yesterday_envelope": (
                self.yesterday_envelope.to_envelope()
                if self.yesterday_envelope is not None
                else None
            ),
            "window_dates": list(self.window_dates),
            "aggregate_history": list(self.aggregate_history),
            "per_welle_history": {
                str(k): list(v) for k, v in self.per_welle_history.items()
            },
            "per_welle_stability_pct": {
                str(k): v for k, v in self.per_welle_stability_pct.items()
            },
            "aggregate_stability_counts": dict(self.aggregate_stability_counts),
            "changes": [c.to_envelope() for c in self.changes],
        }


# ---------------------------------------------------------------------
# Pure-function logic.
# ---------------------------------------------------------------------


def parse_envelope(blob: dict[str, Any], fallback_date_iso: str = "") -> DailyEnvelope:
    """Parse a JSON envelope blob into a DailyEnvelope.

    Accepts either:
      - the analyzer's own persisted shape (with ``date_iso``), or
      - the live-demo orchestrator's envelope (with
        ``started_at_utc`` + ``probes[]``).

    Raises ``ValueError`` on shape mismatch.
    """
    if not isinstance(blob, dict):
        raise ValueError(f"envelope is not a dict: {type(blob).__name__}")

    # Analyzer's persisted shape.
    if "date_iso" in blob and "per_welle" in blob:
        per_welle_raw = blob.get("per_welle") or {}
        per_welle = {int(k): str(v) for k, v in per_welle_raw.items()}
        return DailyEnvelope(
            date_iso=str(blob["date_iso"]),
            run_id=str(blob.get("run_id", "")),
            aggregate=str(blob.get("aggregate", "")),
            per_welle=per_welle,
            captured_at_utc=str(blob.get("captured_at_utc", "")),
            expected_aggregate=str(blob.get("expected_aggregate", "")),
            aggregate_match=bool(blob.get("aggregate_match", False)),
        )

    # Live-demo envelope shape.
    started = blob.get("started_at_utc") or blob.get("finished_at_utc") or ""
    date_iso = ""
    if started:
        # Trim to yyyy-mm-dd. Live-demo emits ISO-8601 with Z suffix.
        date_iso = started[:10]
    if not date_iso:
        date_iso = fallback_date_iso

    probes = blob.get("probes") or []
    per_welle: dict[int, str] = {}
    for p in probes:
        if not isinstance(p, dict):
            continue
        try:
            w = int(p["welle"])
        except (KeyError, TypeError, ValueError):
            continue
        v = str(p.get("verdict", ""))
        per_welle[w] = v

    return DailyEnvelope(
        date_iso=date_iso,
        run_id=str(blob.get("run_id", "")),
        aggregate=str(blob.get("observed_aggregate", "") or blob.get("aggregate", "")),
        per_welle=per_welle,
        captured_at_utc=str(started),
        expected_aggregate=str(blob.get("expected_aggregate", "")),
        aggregate_match=bool(blob.get("aggregate_match", False)),
    )


def classify_change(previous: str | None, current: str, scope: str) -> str:
    """Classify a verdict transition.

    Returns one of:
      * STATUS-NEW       — no previous envelope existed.
      * STATUS-LATERAL   — same verdict as previous (no change).
      * STATUS-DEGRADED  — current is worse than previous.
      * STATUS-IMPROVED  — current is better than previous.
    """
    if previous is None:
        return CHANGE_KIND_NEW
    if previous == current:
        return CHANGE_KIND_LATERAL
    rank_map = AGGREGATE_RANK if scope == "aggregate" else VERDICT_RANK
    prev_rank = rank_map.get(previous, 99)
    curr_rank = rank_map.get(current, 99)
    if curr_rank > prev_rank:
        return CHANGE_KIND_DEGRADED
    if curr_rank < prev_rank:
        return CHANGE_KIND_IMPROVED
    # Same rank, different label — treat as lateral.
    return CHANGE_KIND_LATERAL


def detect_changes(
    today: DailyEnvelope, yesterday: DailyEnvelope | None
) -> tuple[VerdictChange, ...]:
    """Build the per-Welle + aggregate change list (today vs yesterday).

    Only non-lateral changes are returned (STATUS-NEW,
    STATUS-DEGRADED, STATUS-IMPROVED) so the notify-feed isn't
    spammed with every steady-state day.
    """
    changes: list[VerdictChange] = []

    # Per-Welle changes.
    for welle in ALL_WELLES:
        curr = today.per_welle.get(welle)
        if curr is None:
            continue
        prev = (
            yesterday.per_welle.get(welle) if yesterday is not None else None
        )
        kind = classify_change(prev, curr, scope=f"welle-{welle}")
        if kind == CHANGE_KIND_LATERAL:
            continue
        changes.append(
            VerdictChange(
                date_iso=today.date_iso,
                scope=f"welle-{welle}",
                welle=welle,
                previous=prev,
                current=curr,
                kind=kind,
            )
        )

    # Aggregate change.
    prev_agg = yesterday.aggregate if yesterday is not None else None
    curr_agg = today.aggregate
    if curr_agg:
        kind = classify_change(prev_agg, curr_agg, scope="aggregate")
        if kind != CHANGE_KIND_LATERAL:
            changes.append(
                VerdictChange(
                    date_iso=today.date_iso,
                    scope="aggregate",
                    welle=None,
                    previous=prev_agg,
                    current=curr_agg,
                    kind=kind,
                )
            )

    return tuple(changes)


def window_dates(today_iso: str, window: int) -> tuple[str, ...]:
    """Return ``window`` ISO dates ending at ``today_iso`` (inclusive).

    Order: oldest -> newest.
    """
    if window <= 0:
        return tuple()
    end = date.fromisoformat(today_iso)
    return tuple(
        (end - timedelta(days=i)).isoformat()
        for i in range(window - 1, -1, -1)
    )


def build_window_histories(
    envelopes_by_date: dict[str, DailyEnvelope],
    window_iso_dates: Iterable[str],
) -> tuple[tuple[str, ...], dict[int, tuple[str, ...]]]:
    """Roll up the per-welle + aggregate history across the window.

    Missing days are filled with the literal string ``"-"`` so the
    rendered table stays rectangular.
    """
    aggregate_hist: list[str] = []
    per_welle_hist: dict[int, list[str]] = {w: [] for w in ALL_WELLES}
    for d in window_iso_dates:
        env = envelopes_by_date.get(d)
        if env is None:
            aggregate_hist.append("-")
            for w in ALL_WELLES:
                per_welle_hist[w].append("-")
            continue
        aggregate_hist.append(env.aggregate or "-")
        for w in ALL_WELLES:
            per_welle_hist[w].append(env.per_welle.get(w, "-"))
    return tuple(aggregate_hist), {w: tuple(v) for w, v in per_welle_hist.items()}


def stability_pct(history: tuple[str, ...]) -> float:
    """Return % of window-days that match the most-recent verdict.

    A pure-stability metric: if the welle has been GREEN every
    single day of the window, returns 100.0. If it flipped once,
    returns (n-1)/n * 100. Missing days (``"-"``) count as
    instability.

    Empty window returns 0.0.
    """
    if not history:
        return 0.0
    # Most recent is last entry.
    latest = history[-1]
    if latest in (None, "", "-"):
        return 0.0
    matches = sum(1 for v in history if v == latest)
    return round(matches / len(history) * 100.0, 2)


def aggregate_stability_counts(history: tuple[str, ...]) -> dict[str, int]:
    """Per-verdict count across the window."""
    counts = {v: 0 for v in ALL_AGGREGATES}
    counts["MISSING"] = 0
    for v in history:
        if v in counts:
            counts[v] += 1
        elif v in ("-", "", None):
            counts["MISSING"] += 1
        else:
            counts.setdefault(v, 0)
            counts[v] += 1
    return counts


def build_trend_report(
    today: DailyEnvelope,
    envelopes_by_date: dict[str, DailyEnvelope],
    window: int = DEFAULT_WINDOW_DAYS,
) -> TrendReport:
    """Build a complete TrendReport for ``today``.

    ``envelopes_by_date`` MUST contain ``today`` keyed by
    ``today.date_iso``. If ``yesterday`` is absent, the report
    still renders but emits STATUS-NEW changes.
    """
    if today.date_iso not in envelopes_by_date:
        envelopes_by_date = dict(envelopes_by_date)
        envelopes_by_date[today.date_iso] = today

    wdates = window_dates(today.date_iso, window)
    aggregate_hist, per_welle_hist = build_window_histories(
        envelopes_by_date, wdates
    )

    per_welle_stab = {
        w: stability_pct(per_welle_hist[w]) for w in ALL_WELLES
    }
    aggregate_counts = aggregate_stability_counts(aggregate_hist)

    yesterday_iso = (
        date.fromisoformat(today.date_iso) - timedelta(days=1)
    ).isoformat()
    yesterday = envelopes_by_date.get(yesterday_iso)

    changes = detect_changes(today, yesterday)

    return TrendReport(
        today_date_iso=today.date_iso,
        window_days=window,
        today_envelope=today,
        yesterday_envelope=yesterday,
        window_dates=wdates,
        aggregate_history=aggregate_hist,
        per_welle_history=per_welle_hist,
        per_welle_stability_pct=per_welle_stab,
        aggregate_stability_counts=aggregate_counts,
        changes=changes,
    )


def render_markdown(report: TrendReport) -> str:
    """Render the trend report as Markdown.

    The output is appended verbatim to ``$GITHUB_STEP_SUMMARY`` by
    the daily-probe workflow and is also written into
    ``state/pre-cutover-daily-trend/yyyy-mm-dd.md``.
    """
    lines: list[str] = []
    today_iso = report.today_date_iso
    today = report.today_envelope
    lines.append(f"# Phase-3c Pre-Cutover Daily-Probe -- {today_iso}")
    lines.append("")
    lines.append(
        f"**Aggregate:** `{today.aggregate or '-'}`  "
        f"(expected: `{today.expected_aggregate or '-'}`, "
        f"match: `{today.aggregate_match}`)"
    )
    lines.append("")
    lines.append(f"**Run-ID:** `{today.run_id or '-'}`")
    lines.append(f"**Captured at (UTC):** `{today.captured_at_utc or '-'}`")
    lines.append("")

    # Today's per-Welle table.
    lines.append("## Today's per-Welle verdicts")
    lines.append("")
    lines.append("| Welle | Verdict |")
    lines.append("|---|---|")
    for w in ALL_WELLES:
        v = today.per_welle.get(w, "-")
        lines.append(f"| {w} | `{v}` |")
    lines.append("")

    # Last-7-days table.
    lines.append(f"## Trend (last {report.window_days} days)")
    lines.append("")
    header = "| Welle |"
    sep = "|---|"
    for d in report.window_dates:
        header += f" {d[5:]} |"  # show MM-DD
        sep += "---|"
    lines.append(header)
    lines.append(sep)
    for w in ALL_WELLES:
        row = f"| {w} |"
        for v in report.per_welle_history[w]:
            row += f" `{v}` |"
        lines.append(row)
    agg_row = "| **AGG** |"
    for v in report.aggregate_history:
        agg_row += f" `{v}` |"
    lines.append(agg_row)
    lines.append("")

    # Stability panel.
    lines.append("## Stability (% of window matching latest)")
    lines.append("")
    lines.append("| Welle | Stability |")
    lines.append("|---|---|")
    for w in ALL_WELLES:
        pct = report.per_welle_stability_pct.get(w, 0.0)
        lines.append(f"| {w} | {pct:.2f}% |")
    lines.append("")

    # Aggregate counts.
    lines.append("## Aggregate-Verdict counts in window")
    lines.append("")
    lines.append("| Verdict | Days |")
    lines.append("|---|---|")
    for verdict in ALL_AGGREGATES:
        lines.append(
            f"| {verdict} | {report.aggregate_stability_counts.get(verdict, 0)} |"
        )
    missing = report.aggregate_stability_counts.get("MISSING", 0)
    if missing:
        lines.append(f"| MISSING | {missing} |")
    lines.append("")

    # Changes panel.
    lines.append("## Day-over-day changes (today vs yesterday)")
    lines.append("")
    if not report.changes:
        lines.append("_No verdict changes detected (steady state)._")
        lines.append("")
    else:
        lines.append("| Scope | Previous | Current | Kind |")
        lines.append("|---|---|---|---|")
        for c in report.changes:
            lines.append(
                f"| {c.scope} | `{c.previous or '-'}` | "
                f"`{c.current}` | **{c.kind}** |"
            )
        lines.append("")

    # Anchors.
    lines.append("---")
    lines.append(
        "_Anchors: ADR-0065 Phase-3c cutover-plan; "
        "ADR-0066 Doppel-Welle ordering; "
        "Reza Tag-43 PR #277 Pre-Cutover-Live-Demo._"
    )
    lines.append("")
    return "\n".join(lines)


def render_weekly_bilanz(
    reports: list[TrendReport],
) -> str:
    """Render a weekly-bilanz summary across multiple daily reports.

    Used in ``--mode=weekly-bilanz`` to produce the AR-Sitzung
    pre-cutover-review markdown (Mira-Hand-Sichtung).
    """
    if not reports:
        return "# Weekly Bilanz\n\n_No daily reports available._\n"

    sorted_reports = sorted(reports, key=lambda r: r.today_date_iso)
    first = sorted_reports[0].today_date_iso
    last = sorted_reports[-1].today_date_iso

    lines: list[str] = []
    lines.append(f"# Phase-3c Pre-Cutover Weekly Bilanz ({first} -- {last})")
    lines.append("")
    lines.append(f"**Days covered:** {len(sorted_reports)}")
    lines.append("")

    # Aggregate trajectory.
    lines.append("## Aggregate trajectory")
    lines.append("")
    lines.append("| Date | Aggregate | Match |")
    lines.append("|---|---|---|")
    for r in sorted_reports:
        env = r.today_envelope
        lines.append(
            f"| {r.today_date_iso} | `{env.aggregate or '-'}` | "
            f"`{env.aggregate_match}` |"
        )
    lines.append("")

    # Total change-event count.
    total_changes = sum(len(r.changes) for r in sorted_reports)
    degraded = sum(
        1
        for r in sorted_reports
        for c in r.changes
        if c.kind == CHANGE_KIND_DEGRADED
    )
    improved = sum(
        1
        for r in sorted_reports
        for c in r.changes
        if c.kind == CHANGE_KIND_IMPROVED
    )
    lines.append("## Change-event tally")
    lines.append("")
    lines.append(f"- Total verdict-change events: **{total_changes}**")
    lines.append(f"- STATUS-DEGRADED events: **{degraded}**")
    lines.append(f"- STATUS-IMPROVED events: **{improved}**")
    lines.append("")

    # Per-welle change density.
    lines.append("## Per-Welle change density")
    lines.append("")
    lines.append("| Welle | Change events | Degraded | Improved |")
    lines.append("|---|---|---|---|")
    for w in ALL_WELLES:
        total = sum(
            1 for r in sorted_reports for c in r.changes if c.welle == w
        )
        deg = sum(
            1
            for r in sorted_reports
            for c in r.changes
            if c.welle == w and c.kind == CHANGE_KIND_DEGRADED
        )
        imp = sum(
            1
            for r in sorted_reports
            for c in r.changes
            if c.welle == w and c.kind == CHANGE_KIND_IMPROVED
        )
        lines.append(f"| {w} | {total} | {deg} | {imp} |")
    lines.append("")

    lines.append("---")
    lines.append(
        "_Bilanz generated by "
        "``scripts/observability/pre-cutover-daily-trend-analyzer.py`` "
        "(Reza Tag-44)._"
    )
    lines.append("")
    return "\n".join(lines)


def build_notify_events(report: TrendReport) -> list[dict[str, Any]]:
    """Convert a TrendReport into one notify-event per non-lateral change."""
    events: list[dict[str, Any]] = []
    for c in report.changes:
        events.append(
            {
                "schema_version": "1.0",
                "event_type": "pre-cutover-daily-trend-change",
                "date_iso": c.date_iso,
                "scope": c.scope,
                "welle": c.welle,
                "previous": c.previous,
                "current": c.current,
                "kind": c.kind,
                "run_id": report.today_envelope.run_id,
            }
        )
    return events


# ---------------------------------------------------------------------
# --- I/O boundary ---
# ---------------------------------------------------------------------


def walk_daily_state_dir(state_dir: Path) -> dict[str, DailyEnvelope]:
    """Load all yyyy-mm-dd.json files from the daily-state directory."""
    out: dict[str, DailyEnvelope] = {}
    if not state_dir.is_dir():
        return out
    for entry in sorted(state_dir.iterdir()):
        if not entry.is_file():
            continue
        if not entry.name.endswith(".json"):
            continue
        # Filename without extension.
        stem = entry.stem
        try:
            date.fromisoformat(stem)
        except ValueError:
            continue
        try:
            blob = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        try:
            env = parse_envelope(blob, fallback_date_iso=stem)
        except ValueError:
            continue
        out[env.date_iso or stem] = env
    return out


def write_notify_events(notify_path: Path, events: list[dict[str, Any]]) -> int:
    """Append notify-events to JSONL feed.  Returns count appended."""
    if not events:
        return 0
    notify_path.parent.mkdir(parents=True, exist_ok=True)
    with notify_path.open("a", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, sort_keys=True) + "\n")
    return len(events)


def persist_daily_envelope(
    state_dir: Path, envelope: DailyEnvelope
) -> Path:
    """Write a DailyEnvelope to ``state_dir/yyyy-mm-dd.json``."""
    state_dir.mkdir(parents=True, exist_ok=True)
    out_path = state_dir / f"{envelope.date_iso}.json"
    out_path.write_text(
        json.dumps(envelope.to_envelope(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out_path


# ---------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------


def _today_utc_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pre-cutover-daily-trend-analyzer",
        description=(
            "Aggregate daily pre-cutover-probe verdicts into a "
            "Last-N-Days trend report. See module docstring for "
            "modes."
        ),
    )
    p.add_argument(
        "--state-dir",
        default=DEFAULT_STATE_DIR,
        help=f"Directory containing yyyy-mm-dd.json daily envelopes "
             f"(default: {DEFAULT_STATE_DIR}).",
    )
    p.add_argument(
        "--ingest-envelope",
        default=None,
        help="Optional path to a live-demo envelope JSON to ingest "
             "as today's snapshot (overwrites existing today's file).",
    )
    p.add_argument(
        "--today",
        default=None,
        help="Override today's date as yyyy-mm-dd (default: UTC today).",
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
        help=f"JSONL feed for notify events "
             f"(default: {DEFAULT_NOTIFY_PATH}).",
    )
    p.add_argument(
        "--no-notify",
        action="store_true",
        help="Skip writing notify-events.jsonl.",
    )
    p.add_argument(
        "--mode",
        choices=("daily", "weekly-bilanz"),
        default="daily",
        help="Analysis mode (default: daily).",
    )
    return p


def cli_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    state_dir = Path(args.state_dir)
    today_iso = args.today or _today_utc_iso()

    # Optional ingest step: read the live-demo envelope, convert to a
    # DailyEnvelope, persist into the state dir.
    if args.ingest_envelope:
        ingest_path = Path(args.ingest_envelope)
        if not ingest_path.is_file():
            print(
                f"error: --ingest-envelope path not found: {ingest_path}",
                file=sys.stderr,
            )
            return 2
        try:
            blob = json.loads(ingest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"error: failed to parse ingest envelope: {exc}",
                file=sys.stderr,
            )
            return 2
        try:
            ingested = parse_envelope(blob, fallback_date_iso=today_iso)
        except ValueError as exc:
            print(f"error: envelope shape invalid: {exc}", file=sys.stderr)
            return 2
        # Force today's date to be authoritative regardless of envelope's
        # embedded started_at_utc, so the analyzer-state-dir is keyed on
        # the operator's intended snapshot date.
        ingested = dataclasses.replace(ingested, date_iso=today_iso)
        persist_daily_envelope(state_dir, ingested)

    envelopes_by_date = walk_daily_state_dir(state_dir)

    if args.mode == "weekly-bilanz":
        # Produce one trend-report per snapshot day in the window
        # ending at today, then render the weekly summary.
        wdates = window_dates(today_iso, args.window_days)
        reports: list[TrendReport] = []
        for d in wdates:
            env = envelopes_by_date.get(d)
            if env is None:
                continue
            reports.append(
                build_trend_report(
                    env, envelopes_by_date, window=args.window_days
                )
            )
        md = render_weekly_bilanz(reports)
        if args.output_md:
            Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output_md).write_text(md, encoding="utf-8")
        else:
            print(md)
        if args.output_json:
            payload = {
                "schema_version": "1.0",
                "mode": "weekly-bilanz",
                "today_date_iso": today_iso,
                "window_days": args.window_days,
                "reports": [r.to_envelope() for r in reports],
            }
            Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output_json).write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return 0

    # daily mode
    today_env = envelopes_by_date.get(today_iso)
    if today_env is None:
        # Tolerate missing today: synthesise an empty envelope so the
        # rendered output makes it obvious there was no probe.
        today_env = DailyEnvelope(
            date_iso=today_iso,
            run_id="",
            aggregate="",
            per_welle={},
            captured_at_utc="",
            expected_aggregate="",
            aggregate_match=False,
        )

    report = build_trend_report(
        today_env, envelopes_by_date, window=args.window_days
    )

    md = render_markdown(report)
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(md, encoding="utf-8")
    else:
        print(md)

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(
            json.dumps(report.to_envelope(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if not args.no_notify:
        events = build_notify_events(report)
        write_notify_events(Path(args.notify_path), events)

    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
