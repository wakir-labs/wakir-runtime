#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Phase-3c Per-Welle Trend-Heatmap Renderer (Tag-48).

Context
-------

Tag-44 (Reza, PR #285) shipped the Pre-Cutover Daily-Trend-Analyzer
which aggregates per-day verdicts into a Last-7-Days window per
Welle and produces a Markdown table.

Tag-46 (Noa, PR #296) shipped the Mira-Notify emitter+receiver
chain so trend-degradation events surface as operator-inbox feeds.

Tag-47 (Noa, PR #302) shipped the Alert-Rule-to-Mira-Notify
bridge so PromQL alerts also funnel into the same operator inbox.

Tag-48 (this script) adds the *visualisation layer*: an at-a-glance
heatmap renderer that consumes the same daily-state directory the
analyzer writes (``state/pre-cutover-daily-trend/yyyy-mm-dd.json``)
and emits a per-Welle ASCII-grid (operator console) plus a
structured JSON heatmap envelope (Grafana panel ingest +
notify-feed input).

The heatmap is not a replacement for the daily trend-report. It is
an at-a-glance posture surface that the operator can scan in three
seconds during the daily cutover-readiness huddle:

* Rows: Welle-1 .. Welle-7 + AGG (aggregate).
* Columns: oldest -> newest snapshot date in the window.
* Cells: glyph + verdict-color-bucket
    GREEN     -> "G"  (green/healthy)
    CAUTION   -> "C"  (yellow/caution)
    NOT-EXEC  -> "N"  (grey/not-executed)
    BLOCK     -> "B"  (red/blocked)
    READY     -> "R"  (green-aggregate)
    NOT-READY -> "X"  (red-aggregate)
    MISSING   -> "."  (no snapshot)

Pure-function-vs-IO split
-------------------------

Everything above the ``# --- I/O boundary ---`` marker is pure
stdlib + can be exercised by hermetic tests with synthetic
envelope inputs. The I/O wrappers (``load_state_dir``,
``write_outputs``) sit at the bottom.

Reuse vs. duplication
---------------------

This script intentionally re-implements the small subset of
envelope parsing it needs (date_iso, aggregate, per_welle) rather
than importing the daily-trend-analyzer. The reason is two-fold:

1. The analyzer's module path uses hyphens, which forces an
   importlib.util loader (we already do this once in tests; doing
   it again in production code makes the script brittle).
2. The heatmap consumes only a tiny slice of the envelope. Coupling
   it to the analyzer's full DailyEnvelope dataclass would force
   the heatmap to know about ``aggregate_match`` /
   ``expected_aggregate`` which are not heatmap concerns.

If the heatmap ever needs richer envelope semantics, lift the
envelope parser into a shared module (``scripts/observability/_state.py``)
and have both consumers import from there.

Anchors
-------

* ADR-0065 Phase-3c cutover sequence.
* ADR-0066 Doppel-Welle KW-24/26/27 ordering.
* Reza Tag-44 PR #285 Pre-Cutover Daily-Trend-Analyzer.
* Noa Tag-46 PR #296 Mira-Notify emitter+receiver chain.
* Noa Tag-47 PR #302 Alert-Rule-to-Mira-Notify bridge.

Author: Noa Bergstroem (SRE), Sprint-Tag-48, 2026-05-19.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------

ALL_WELLES: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)

# Per-Welle verdict glyphs (single-char ASCII for stable column
# widths in the operator console).
VERDICT_GLYPH: dict[str, str] = {
    "GREEN": "G",
    "CAUTION": "C",
    "NOT-EXEC": "N",
    "BLOCK": "B",
}

# Aggregate-level glyphs. Different namespace because ``GREEN`` and
# ``READY`` are semantically distinct (per-welle vs aggregate).
AGGREGATE_GLYPH: dict[str, str] = {
    "READY": "R",
    "CAUTION": "C",
    "BLOCK": "B",
    "NOT-READY": "X",
}

# Color-bucket lookup for Grafana panel ingest. The downstream
# Grafana stat-panel uses these as field-value mappings to drive
# cell color.
VERDICT_COLOR: dict[str, str] = {
    "GREEN": "green",
    "CAUTION": "yellow",
    "NOT-EXEC": "grey",
    "BLOCK": "red",
}
AGGREGATE_COLOR: dict[str, str] = {
    "READY": "green",
    "CAUTION": "yellow",
    "BLOCK": "red",
    "NOT-READY": "red",
}

MISSING_GLYPH = "."
MISSING_COLOR = "transparent"

DEFAULT_WINDOW_DAYS = 7
DEFAULT_STATE_DIR = "state/pre-cutover-daily-trend"
DEFAULT_HEATMAP_DIR = "state/per-welle-heatmap"

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------
# Data classes.
# ---------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class HeatmapCell:
    """One cell of the heatmap (one welle on one date).

    The cell carries both the raw verdict and the glyph/color so
    downstream consumers (Grafana ingest, ASCII renderer) don't
    each have to re-derive the same mapping.
    """

    date_iso: str
    row_key: str  # "welle-N" or "aggregate"
    welle: int | None
    verdict: str  # may be "" / "-" for missing
    glyph: str
    color: str

    def to_envelope(self) -> dict[str, Any]:
        return {
            "date_iso": self.date_iso,
            "row_key": self.row_key,
            "welle": self.welle,
            "verdict": self.verdict,
            "glyph": self.glyph,
            "color": self.color,
        }


@dataclasses.dataclass(frozen=True)
class HeatmapEnvelope:
    """Full heatmap roll-up across the window.

    Cells are addressed by (row_key, date_iso) and laid out as a
    rectangular grid. ``rows`` preserves the documented row order:
    welle-1 .. welle-7 then aggregate.
    """

    today_date_iso: str
    window_days: int
    window_dates: tuple[str, ...]
    rows: tuple[str, ...]
    cells: tuple[HeatmapCell, ...]
    summary_counts: dict[str, dict[str, int]]
    legend: dict[str, str]

    def to_envelope(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "today_date_iso": self.today_date_iso,
            "window_days": self.window_days,
            "window_dates": list(self.window_dates),
            "rows": list(self.rows),
            "cells": [c.to_envelope() for c in self.cells],
            "summary_counts": {
                k: dict(v) for k, v in self.summary_counts.items()
            },
            "legend": dict(self.legend),
        }


# ---------------------------------------------------------------------
# Pure-function logic.
# ---------------------------------------------------------------------


def window_dates(today_iso: str, window: int) -> tuple[str, ...]:
    """Return ``window`` ISO dates ending at ``today_iso`` (inclusive).

    Order: oldest -> newest. Mirrors the daily-trend-analyzer's
    own ``window_dates`` semantics so heatmap columns line up
    cell-for-cell with analyzer rows.
    """
    if window <= 0:
        return tuple()
    end = date.fromisoformat(today_iso)
    return tuple(
        (end - timedelta(days=i)).isoformat()
        for i in range(window - 1, -1, -1)
    )


def _parse_snapshot(blob: dict[str, Any], fallback_date_iso: str) -> dict[str, Any]:
    """Extract the date, aggregate and per_welle map from any
    snapshot shape the analyzer might persist.

    Accepts both the analyzer's persisted shape (``date_iso`` +
    ``per_welle``) and the upstream live-demo shape (``started_at_utc``
    + ``probes``). Returns a normalised dict:

        {
            "date_iso": "yyyy-mm-dd",
            "aggregate": "...",
            "per_welle": {1: "...", ..., 7: "..."},
        }

    Missing fields default to empty string / empty dict.
    """
    if not isinstance(blob, dict):
        return {"date_iso": fallback_date_iso, "aggregate": "", "per_welle": {}}

    # Analyzer's persisted shape.
    if "date_iso" in blob and "per_welle" in blob:
        per_welle_raw = blob.get("per_welle") or {}
        per_welle: dict[int, str] = {}
        for k, v in per_welle_raw.items():
            try:
                per_welle[int(k)] = str(v)
            except (TypeError, ValueError):
                continue
        return {
            "date_iso": str(blob.get("date_iso") or fallback_date_iso),
            "aggregate": str(blob.get("aggregate") or ""),
            "per_welle": per_welle,
        }

    # Live-demo shape.
    started = blob.get("started_at_utc") or blob.get("finished_at_utc") or ""
    if isinstance(started, str) and len(started) >= 10:
        date_iso = started[:10]
    else:
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
        per_welle[w] = str(p.get("verdict", ""))

    aggregate = str(
        blob.get("observed_aggregate") or blob.get("aggregate") or ""
    )
    return {
        "date_iso": date_iso or fallback_date_iso,
        "aggregate": aggregate,
        "per_welle": per_welle,
    }


def _glyph_for_welle(verdict: str) -> tuple[str, str]:
    """Return (glyph, color) for a per-Welle verdict.  Missing -> ('.', transparent)."""
    if verdict in VERDICT_GLYPH:
        return VERDICT_GLYPH[verdict], VERDICT_COLOR[verdict]
    return MISSING_GLYPH, MISSING_COLOR


def _glyph_for_aggregate(verdict: str) -> tuple[str, str]:
    """Return (glyph, color) for an aggregate verdict.  Missing -> ('.', transparent)."""
    if verdict in AGGREGATE_GLYPH:
        return AGGREGATE_GLYPH[verdict], AGGREGATE_COLOR[verdict]
    return MISSING_GLYPH, MISSING_COLOR


def build_heatmap(
    snapshots_by_date: dict[str, dict[str, Any]],
    today_iso: str,
    window: int = DEFAULT_WINDOW_DAYS,
) -> HeatmapEnvelope:
    """Build a HeatmapEnvelope from a date -> normalised snapshot map.

    ``snapshots_by_date`` keys are ISO dates; values are dicts shaped
    by ``_parse_snapshot``. Missing days are rendered as MISSING
    cells so the grid stays rectangular.
    """
    wdates = window_dates(today_iso, window)
    rows: list[str] = [f"welle-{w}" for w in ALL_WELLES] + ["aggregate"]
    cells: list[HeatmapCell] = []

    # Initialise summary counters (one bucket per row).
    summary_counts: dict[str, dict[str, int]] = {row: {} for row in rows}

    for w in ALL_WELLES:
        row_key = f"welle-{w}"
        for d in wdates:
            snap = snapshots_by_date.get(d)
            verdict = ""
            if snap is not None:
                verdict = str(snap.get("per_welle", {}).get(w, ""))
            glyph, color = _glyph_for_welle(verdict)
            cells.append(
                HeatmapCell(
                    date_iso=d,
                    row_key=row_key,
                    welle=w,
                    verdict=verdict,
                    glyph=glyph,
                    color=color,
                )
            )
            bucket = verdict if verdict else "MISSING"
            summary_counts[row_key][bucket] = (
                summary_counts[row_key].get(bucket, 0) + 1
            )

    for d in wdates:
        snap = snapshots_by_date.get(d)
        verdict = ""
        if snap is not None:
            verdict = str(snap.get("aggregate", ""))
        glyph, color = _glyph_for_aggregate(verdict)
        cells.append(
            HeatmapCell(
                date_iso=d,
                row_key="aggregate",
                welle=None,
                verdict=verdict,
                glyph=glyph,
                color=color,
            )
        )
        bucket = verdict if verdict else "MISSING"
        summary_counts["aggregate"][bucket] = (
            summary_counts["aggregate"].get(bucket, 0) + 1
        )

    legend = {
        "G": "GREEN (per-Welle)",
        "C": "CAUTION",
        "N": "NOT-EXEC",
        "B": "BLOCK",
        "R": "READY (aggregate)",
        "X": "NOT-READY (aggregate)",
        ".": "MISSING (no snapshot)",
    }

    return HeatmapEnvelope(
        today_date_iso=today_iso,
        window_days=window,
        window_dates=wdates,
        rows=tuple(rows),
        cells=tuple(cells),
        summary_counts=summary_counts,
        legend=legend,
    )


def cells_by_row(
    heatmap: HeatmapEnvelope,
) -> dict[str, list[HeatmapCell]]:
    """Group cells by row, preserving date order (oldest -> newest)."""
    out: dict[str, list[HeatmapCell]] = {row: [] for row in heatmap.rows}
    for cell in heatmap.cells:
        out.setdefault(cell.row_key, []).append(cell)
    for row, cs in out.items():
        cs.sort(key=lambda c: c.date_iso)
    return out


def render_ascii(heatmap: HeatmapEnvelope) -> str:
    """Render the heatmap as an ASCII grid for the operator console.

    Layout::

        Per-Welle Trend Heatmap (last 7 days ending 2026-05-19)

                 05-13 05-14 05-15 05-16 05-17 05-18 05-19
        welle-1    C     C     C     C     C     C     C
        welle-2    C     C     C     C     C     C     C
        welle-3    C     C     C     C     C     C     C
        welle-4    C     C     C     C     C     C     C
        welle-5    C     C     C     C     C     C     C
        welle-6    G     G     G     G     G     G     G
        welle-7    B     B     B     B     B     B     B
        AGG        B     B     B     B     B     B     B

        Legend: G=GREEN C=CAUTION N=NOT-EXEC B=BLOCK
                R=READY X=NOT-READY .=MISSING
    """
    grouped = cells_by_row(heatmap)

    # Column header (MM-DD only, to keep the grid narrow).
    col_labels = [d[5:] for d in heatmap.window_dates]
    col_width = 5  # "MM-DD" plus separator

    lines: list[str] = []
    lines.append(
        f"Per-Welle Trend Heatmap "
        f"(last {heatmap.window_days} days ending {heatmap.today_date_iso})"
    )
    lines.append("")

    row_label_width = max(len(r) for r in heatmap.rows + ("AGG",))
    # Indent the header to leave room for the row label column.
    header = " " * (row_label_width + 2)
    for lab in col_labels:
        header += f" {lab:<{col_width}}"
    lines.append(header)

    for row in heatmap.rows:
        # Pretty label: "aggregate" rendered as "AGG" for visual
        # symmetry with the analyzer's markdown table.
        label = "AGG" if row == "aggregate" else row
        row_line = f"{label:<{row_label_width + 2}}"
        for cell in grouped.get(row, []):
            row_line += f" {cell.glyph:<{col_width}}"
        lines.append(row_line)

    lines.append("")
    lines.append("Legend: G=GREEN C=CAUTION N=NOT-EXEC B=BLOCK")
    lines.append("        R=READY  X=NOT-READY .=MISSING")
    lines.append("")
    return "\n".join(lines)


def render_markdown(heatmap: HeatmapEnvelope) -> str:
    """Render the heatmap as a Markdown table.

    Designed to be appended verbatim to ``$GITHUB_STEP_SUMMARY``
    by the daily-probe workflow and to ``state/per-welle-heatmap/
    yyyy-mm-dd.md`` for the AR-Sitzung pre-cutover-review.
    """
    grouped = cells_by_row(heatmap)
    lines: list[str] = []
    lines.append(
        f"# Per-Welle Trend Heatmap -- {heatmap.today_date_iso}"
    )
    lines.append("")
    lines.append(
        f"Window: last {heatmap.window_days} days "
        f"({heatmap.window_dates[0]} -- {heatmap.window_dates[-1]})"
    )
    lines.append("")

    header = "| Row |"
    sep = "|---|"
    for d in heatmap.window_dates:
        header += f" {d[5:]} |"
        sep += "---|"
    lines.append(header)
    lines.append(sep)

    for row in heatmap.rows:
        label = "**AGG**" if row == "aggregate" else row
        row_line = f"| {label} |"
        for cell in grouped.get(row, []):
            row_line += f" `{cell.glyph}` |"
        lines.append(row_line)
    lines.append("")

    lines.append("## Legend")
    lines.append("")
    lines.append("| Glyph | Meaning |")
    lines.append("|---|---|")
    for glyph, meaning in heatmap.legend.items():
        lines.append(f"| `{glyph}` | {meaning} |")
    lines.append("")

    lines.append("## Summary counts (this window)")
    lines.append("")
    lines.append("| Row | Verdict | Days |")
    lines.append("|---|---|---|")
    for row in heatmap.rows:
        row_counts = heatmap.summary_counts.get(row, {})
        label = "AGG" if row == "aggregate" else row
        for verdict, days in sorted(row_counts.items()):
            lines.append(f"| {label} | {verdict} | {days} |")
    lines.append("")

    lines.append("---")
    lines.append(
        "_Heatmap generated by "
        "``scripts/observability/per-welle-trend-heatmap.py`` "
        "(Noa Tag-48). Source: "
        "``state/pre-cutover-daily-trend/yyyy-mm-dd.json``._"
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------
# --- I/O boundary ---
# ---------------------------------------------------------------------


def load_state_dir(state_dir: Path) -> dict[str, dict[str, Any]]:
    """Load all yyyy-mm-dd.json snapshots from the state directory.

    Returns a date-ISO -> normalised-snapshot map. Malformed files
    are silently skipped (logged to stderr) so a single bad file
    doesn't blank the heatmap.
    """
    out: dict[str, dict[str, Any]] = {}
    if not state_dir.is_dir():
        return out
    for entry in sorted(state_dir.iterdir()):
        if not entry.is_file():
            continue
        if not entry.name.endswith(".json"):
            continue
        stem = entry.stem
        try:
            date.fromisoformat(stem)
        except ValueError:
            continue
        try:
            blob = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(
                f"warning: skip malformed snapshot {entry}: {exc}",
                file=sys.stderr,
            )
            continue
        snap = _parse_snapshot(blob, fallback_date_iso=stem)
        out[snap["date_iso"] or stem] = snap
    return out


def write_outputs(
    heatmap: HeatmapEnvelope,
    output_json: Path | None,
    output_md: Path | None,
    output_ascii: Path | None,
) -> None:
    """Write the heatmap to JSON / Markdown / ASCII files.

    Each output is optional. Parent directories are created on
    demand. JSON is written sorted+indented for diff-stability.
    """
    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(heatmap.to_envelope(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if output_md is not None:
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(render_markdown(heatmap), encoding="utf-8")
    if output_ascii is not None:
        output_ascii.parent.mkdir(parents=True, exist_ok=True)
        output_ascii.write_text(render_ascii(heatmap), encoding="utf-8")


# ---------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------


def _today_utc_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="per-welle-trend-heatmap",
        description=(
            "Render a per-Welle verdict-trend heatmap from the "
            "daily-trend-analyzer state directory. Emits ASCII for "
            "the operator console and structured JSON for Grafana "
            "panel ingest."
        ),
    )
    p.add_argument(
        "--state-dir",
        default=DEFAULT_STATE_DIR,
        help=(
            "Directory containing yyyy-mm-dd.json daily envelopes "
            f"(default: {DEFAULT_STATE_DIR})."
        ),
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
        help="Write the heatmap JSON envelope to this path.",
    )
    p.add_argument(
        "--output-md",
        default=None,
        help="Write the heatmap Markdown rendering to this path.",
    )
    p.add_argument(
        "--output-ascii",
        default=None,
        help="Write the heatmap ASCII rendering to this path.",
    )
    p.add_argument(
        "--print-ascii",
        action="store_true",
        help="Print the ASCII grid to stdout (default if no outputs given).",
    )
    return p


def cli_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state_dir = Path(args.state_dir)
    today_iso = args.today or _today_utc_iso()

    if args.window_days <= 0:
        print(
            "error: --window-days must be > 0",
            file=sys.stderr,
        )
        return 2

    snapshots = load_state_dir(state_dir)
    heatmap = build_heatmap(snapshots, today_iso, window=args.window_days)

    write_outputs(
        heatmap,
        output_json=Path(args.output_json) if args.output_json else None,
        output_md=Path(args.output_md) if args.output_md else None,
        output_ascii=Path(args.output_ascii) if args.output_ascii else None,
    )

    # If no output file was requested, default to printing the
    # ASCII grid so the script is useful in interactive operator
    # consoles ("python3 per-welle-trend-heatmap.py" -> grid).
    no_outputs = not (args.output_json or args.output_md or args.output_ascii)
    if args.print_ascii or no_outputs:
        sys.stdout.write(render_ascii(heatmap))
        if not render_ascii(heatmap).endswith("\n"):
            sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
