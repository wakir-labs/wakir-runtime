#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Phase-3c Per-Welle Trend-Heatmap Prometheus-Textfile Emitter (Tag-49).

Context
-------

Tag-48 (Noa, PR #309) shipped the Per-Welle Trend-Heatmap renderer
(``scripts/observability/per-welle-trend-heatmap.py``) which consumes
the Tag-44 Daily-Trend-Analyzer state and emits ASCII + JSON + Markdown
heatmap envelopes into ``state/per-welle-heatmap/yyyy-mm-dd.json``.

Tag-48 also shipped the Grafana dashboard
(``dashboards/per-welle-trend-heatmap.json``) which already references
the gauge family ``persona_engine_per_welle_heatmap_*``. The runbook
of Tag-48 explicitly notes that the emitter that *populates* those
gauges from the JSON envelope is a Tag-49 follow-up. That is this
script.

Pipeline
--------

The Tag-49 emitter sits between Tag-48 JSON envelope and the Tag-48
Grafana panels::

    state/pre-cutover-daily-trend/yyyy-mm-dd.json    (Reza Tag-44)
                       |
                       v
    per-welle-trend-heatmap.py (Noa Tag-48)
                       |
                       v
    state/per-welle-heatmap/yyyy-mm-dd.json          (Tag-48 envelope)
                       |
                       v
    per-welle-heatmap-prom-emitter.py (THIS, Tag-49)
                       |
                       v
    /var/lib/prometheus/node-exporter/per-welle-heatmap.prom
                       |
                       v
    Grafana state-timeline panel (Tag-48 dashboard)

Metrics emitted
---------------

All gauges live under the ``persona_engine_per_welle_heatmap_*``
namespace so the Tag-48 dashboard finds them without any change.

* ``persona_engine_per_welle_heatmap_verdict{row_key, welle, verdict, glyph, color, date_iso}``
    Numeric encoding of the verdict for a (row, date) cell:

        0  -> GREEN     (per-Welle healthy)
        1  -> CAUTION   (per-Welle caution)
        2  -> NOT-EXEC  (per-Welle not executed)
        3  -> BLOCK     (per-Welle blocked)
        4  -> READY     (aggregate ready)
        5  -> NOT-READY (aggregate not ready)
        -1 -> MISSING   (no snapshot)

    The numeric mapping matches the Grafana panel's value-text mapping
    in ``dashboards/per-welle-trend-heatmap.json`` so cell colors line
    up without extra transforms.

* ``persona_engine_per_welle_heatmap_summary_count{row_key, verdict}``
    Number of days in the window where ``row_key`` had verdict
    ``verdict``. Cardinality is statically bounded: 8 rows
    (welle-1..7 + aggregate) x ~6 verdict buckets.

* ``persona_engine_per_welle_heatmap_stability_match_count{row_key}``
    Number of days in the window where the row's verdict matched
    the most-recent (newest-day) verdict. The stability indicator
    surfaces day-over-day drift: 7-of-7 = perfectly stable,
    <7-of-7 = flips happened.

* ``persona_engine_per_welle_heatmap_window_days``
    Trend window size (informational; matches the envelope's
    ``window_days`` field).

* ``persona_engine_per_welle_heatmap_render_timestamp_seconds``
    Unix timestamp (UTC seconds) of the envelope's ``today_date_iso``
    midnight + the emitter wall-clock. The Grafana annotation
    references ``changes(...)[1d]`` against this gauge to draw a
    re-render marker on the heatmap each morning.

Output format
-------------

Prometheus textfile-collector format, suitable for
``node_exporter --collector.textfile.directory=/var/lib/prometheus/
node-exporter/``. Each metric carries ``# HELP`` + ``# TYPE`` lines.
All gauges. Timestamps are millisecond unixtime per the textfile
spec.

Sandbox posture
---------------

Pure stdlib. No network, no podman, no live VM. Reads one JSON
envelope, writes one .prom text file (atomic via temp + rename).

Pure-function-vs-IO split
-------------------------

Everything above ``# --- I/O boundary ---`` is hermetic and unit-
testable with synthetic envelope dicts. The I/O wrappers
(``load_envelope``, ``write_textfile``) sit below.

Anchors
-------

* ADR-0065 Phase-3c cutover sequence.
* ADR-0066 Doppel-Welle KW-24/26/27 ordering.
* Reza Tag-44 PR #285 Pre-Cutover Daily-Trend-Analyzer.
* Noa Tag-48 PR #309 Per-Welle Trend-Heatmap Renderer + Dashboard.
* Tag-48 runbook explicit deferral of emitter to Tag-49 follow-up.

Author: Noa Bergstroem (SRE), Sprint-Tag-49, 2026-05-19.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


# ---------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------

SCHEMA_VERSION = "1.0"

# Numeric verdict encoding. Must match the Grafana state-timeline
# value-text mapping in dashboards/per-welle-trend-heatmap.json.
VERDICT_TO_NUMERIC: dict[str, int] = {
    "GREEN": 0,
    "CAUTION": 1,
    "NOT-EXEC": 2,
    "BLOCK": 3,
    "READY": 4,
    "NOT-READY": 5,
    # Anything else (including "" and "MISSING") -> sentinel:
    "MISSING": -1,
}

MISSING_NUMERIC = -1

DEFAULT_HEATMAP_DIR = "state/per-welle-heatmap"
DEFAULT_OUTPUT_PROM = "out/per-welle-heatmap.prom"


# ---------------------------------------------------------------------
# Pure-function logic.
# ---------------------------------------------------------------------


def _esc(value: Any) -> str:
    """Escape a Prometheus textfile label value.

    Per the Prometheus textfile spec: backslash, double-quote, and
    newline must be escaped. We additionally coerce to ``str`` so
    integer welles ("welle"=1) survive label rendering.
    """
    s = str(value)
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _numeric_for_verdict(verdict: str) -> int:
    """Return the numeric encoding for a verdict.

    Empty / unknown verdicts map to the MISSING sentinel so the
    Grafana panel's "transparent" mapping renders.
    """
    if not verdict:
        return MISSING_NUMERIC
    return VERDICT_TO_NUMERIC.get(verdict, MISSING_NUMERIC)


def _today_iso_to_unix(today_iso: str) -> float:
    """Convert a yyyy-mm-dd ISO date to a UTC midnight unix timestamp.

    Used to give the render-timestamp gauge a stable per-day value
    (so the Grafana annotation's ``changes(...)[1d]`` query fires
    exactly once per envelope-day).
    """
    try:
        dt = datetime.fromisoformat(today_iso).replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (TypeError, ValueError):
        return float(int(time.time()))


def _normalise_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Coerce the Tag-48 heatmap envelope into a stable shape.

    Returns a dict with keys::

        today_date_iso : str
        window_days    : int
        rows           : list[str]
        cells          : list[dict]   # one per (row, date) pair
        summary_counts : dict[row -> dict[verdict -> int]]

    Missing / malformed fields are coerced to sensible defaults so
    a partial envelope still produces a valid (if mostly-empty)
    textfile. This matches the pre-cutover-probe-failure-rate-tracker's
    "render what you can" robustness contract.
    """
    today_date_iso = str(envelope.get("today_date_iso") or "")
    try:
        window_days = int(envelope.get("window_days") or 0)
    except (TypeError, ValueError):
        window_days = 0
    rows_raw = envelope.get("rows") or []
    rows = [str(r) for r in rows_raw if isinstance(r, (str, int))]

    cells_raw = envelope.get("cells") or []
    cells: list[dict[str, Any]] = []
    for c in cells_raw:
        if not isinstance(c, dict):
            continue
        cells.append(
            {
                "date_iso": str(c.get("date_iso") or ""),
                "row_key": str(c.get("row_key") or ""),
                "welle": c.get("welle"),
                "verdict": str(c.get("verdict") or ""),
                "glyph": str(c.get("glyph") or "."),
                "color": str(c.get("color") or "transparent"),
            }
        )

    summary_raw = envelope.get("summary_counts") or {}
    summary_counts: dict[str, dict[str, int]] = {}
    if isinstance(summary_raw, dict):
        for row, buckets in summary_raw.items():
            if not isinstance(buckets, dict):
                continue
            row_key = str(row)
            row_counts: dict[str, int] = {}
            for verdict, count in buckets.items():
                try:
                    row_counts[str(verdict)] = int(count)
                except (TypeError, ValueError):
                    continue
            summary_counts[row_key] = row_counts

    return {
        "today_date_iso": today_date_iso,
        "window_days": window_days,
        "rows": rows,
        "cells": cells,
        "summary_counts": summary_counts,
    }


def compute_stability_match_counts(
    cells: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    """For each row, count days whose verdict matches the *latest* verdict.

    "Latest" = the cell with the maximum ``date_iso`` for that row.
    A perfectly stable row returns ``window_days``. A row that flipped
    yesterday returns 1 (only the most-recent day matches itself).

    Missing cells (verdict="") are ignored when picking the latest
    verdict but counted as non-match in the tally if the latest
    happens to be non-empty.

    Returns dict[row_key -> match_count]. Rows with no cells return
    0.
    """
    by_row: dict[str, list[dict[str, Any]]] = {}
    for c in cells:
        row = str(c.get("row_key") or "")
        if not row:
            continue
        by_row.setdefault(row, []).append(dict(c))

    out: dict[str, int] = {}
    for row, row_cells in by_row.items():
        if not row_cells:
            out[row] = 0
            continue
        row_cells.sort(key=lambda x: str(x.get("date_iso") or ""))
        latest_verdict = str(row_cells[-1].get("verdict") or "")
        if not latest_verdict:
            # No anchor verdict -> count all blanks as matches.
            out[row] = sum(
                1 for c in row_cells if not str(c.get("verdict") or "")
            )
            continue
        out[row] = sum(
            1
            for c in row_cells
            if str(c.get("verdict") or "") == latest_verdict
        )
    return out


def render_prometheus_textfile(
    envelope: Mapping[str, Any],
    *,
    timestamp_unixtime: float | None = None,
) -> str:
    """Render a Tag-48 heatmap envelope as Prometheus textfile.

    Pure function (no I/O). The output is a single utf-8 string
    terminated by a trailing newline.

    Schema::

        # HELP persona_engine_per_welle_heatmap_verdict ...
        # TYPE persona_engine_per_welle_heatmap_verdict gauge
        persona_engine_per_welle_heatmap_verdict{row_key="welle-1",
            welle="1",verdict="CAUTION",glyph="C",color="yellow",
            date_iso="2026-05-13"} 1 <ts_ms>
        ...
        # HELP persona_engine_per_welle_heatmap_summary_count ...
        # TYPE persona_engine_per_welle_heatmap_summary_count gauge
        persona_engine_per_welle_heatmap_summary_count{row_key="welle-1",
            verdict="CAUTION"} 7 <ts_ms>
        ...
        # HELP persona_engine_per_welle_heatmap_stability_match_count ...
        # TYPE persona_engine_per_welle_heatmap_stability_match_count gauge
        persona_engine_per_welle_heatmap_stability_match_count{
            row_key="welle-1"} 7 <ts_ms>
        ...
        # HELP persona_engine_per_welle_heatmap_window_days ...
        # TYPE persona_engine_per_welle_heatmap_window_days gauge
        persona_engine_per_welle_heatmap_window_days 7 <ts_ms>
        # HELP persona_engine_per_welle_heatmap_render_timestamp_seconds ...
        # TYPE persona_engine_per_welle_heatmap_render_timestamp_seconds gauge
        persona_engine_per_welle_heatmap_render_timestamp_seconds <today_unix> <ts_ms>

    The label set matches the Grafana dashboard's variable bindings
    in ``dashboards/per-welle-trend-heatmap.json`` (row_key, verdict)
    and adds ``welle`` / ``glyph`` / ``color`` / ``date_iso`` as
    free-form extra labels for tooltip rendering.
    """
    norm = _normalise_envelope(envelope)

    if timestamp_unixtime is None:
        timestamp_unixtime = time.time()
    ts_ms = int(timestamp_unixtime * 1000)

    lines: list[str] = []

    # ----- verdict gauge ----- ---------------------------------------
    lines.append(
        "# HELP persona_engine_per_welle_heatmap_verdict Numeric "
        "verdict for one (row_key,date) cell of the Phase-3c "
        "Per-Welle Trend-Heatmap. 0=GREEN, 1=CAUTION, 2=NOT-EXEC, "
        "3=BLOCK, 4=READY, 5=NOT-READY, -1=MISSING. Source: "
        "state/per-welle-heatmap/yyyy-mm-dd.json (Noa Tag-48 PR #309 "
        "renderer)."
    )
    lines.append("# TYPE persona_engine_per_welle_heatmap_verdict gauge")
    for cell in norm["cells"]:
        verdict = cell["verdict"]
        numeric = _numeric_for_verdict(verdict)
        welle_label = "" if cell["welle"] is None else str(cell["welle"])
        # Surface "MISSING" as the verdict label so the dashboard's
        # value-text mapping is symmetric with the cell glyph.
        verdict_label = verdict if verdict else "MISSING"
        lines.append(
            f'persona_engine_per_welle_heatmap_verdict{{'
            f'row_key="{_esc(cell["row_key"])}",'
            f'welle="{_esc(welle_label)}",'
            f'verdict="{_esc(verdict_label)}",'
            f'glyph="{_esc(cell["glyph"])}",'
            f'color="{_esc(cell["color"])}",'
            f'date_iso="{_esc(cell["date_iso"])}"'
            f'}} {numeric} {ts_ms}'
        )
    lines.append("")

    # ----- summary-count gauge ----------------------------------------
    lines.append(
        "# HELP persona_engine_per_welle_heatmap_summary_count Number "
        "of days in the heatmap window where ``row_key`` had verdict "
        "``verdict``. Cardinality is statically bounded: 8 rows "
        "(welle-1..7 + aggregate) x ~6 verdict buckets. Source: "
        "Tag-48 envelope summary_counts field."
    )
    lines.append("# TYPE persona_engine_per_welle_heatmap_summary_count gauge")
    for row_key in norm["rows"]:
        buckets = norm["summary_counts"].get(row_key, {})
        for verdict, count in sorted(buckets.items()):
            lines.append(
                f'persona_engine_per_welle_heatmap_summary_count{{'
                f'row_key="{_esc(row_key)}",'
                f'verdict="{_esc(verdict)}"'
                f'}} {int(count)} {ts_ms}'
            )
    lines.append("")

    # ----- stability gauge --------------------------------------------
    stab = compute_stability_match_counts(norm["cells"])
    lines.append(
        "# HELP persona_engine_per_welle_heatmap_stability_match_count "
        "Number of days in the window whose verdict matches the most-"
        "recent (newest-day) verdict for that row. Perfectly stable "
        "row returns window_days. <window_days indicates day-over-day "
        "verdict flips."
    )
    lines.append(
        "# TYPE persona_engine_per_welle_heatmap_stability_match_count gauge"
    )
    for row_key in norm["rows"]:
        match = stab.get(row_key, 0)
        lines.append(
            f'persona_engine_per_welle_heatmap_stability_match_count{{'
            f'row_key="{_esc(row_key)}"'
            f'}} {int(match)} {ts_ms}'
        )
    lines.append("")

    # ----- window-days informational gauge ----------------------------
    lines.append(
        "# HELP persona_engine_per_welle_heatmap_window_days Trend "
        "window size in days (matches the Tag-48 envelope window_days "
        "field). Informational; Grafana panel time-range follows the "
        "dashboard time-picker independently."
    )
    lines.append("# TYPE persona_engine_per_welle_heatmap_window_days gauge")
    lines.append(
        f"persona_engine_per_welle_heatmap_window_days "
        f"{int(norm['window_days'])} {ts_ms}"
    )
    lines.append("")

    # ----- render-timestamp gauge -------------------------------------
    today_unix = _today_iso_to_unix(norm["today_date_iso"])
    lines.append(
        "# HELP persona_engine_per_welle_heatmap_render_timestamp_seconds "
        "Unix-seconds value of the envelope's today_date_iso midnight "
        "UTC. Used by the Tag-48 Grafana annotation "
        "``changes(...)[1d]`` to draw a re-render marker on the "
        "heatmap each morning."
    )
    lines.append(
        "# TYPE persona_engine_per_welle_heatmap_render_timestamp_seconds gauge"
    )
    lines.append(
        f"persona_engine_per_welle_heatmap_render_timestamp_seconds "
        f"{today_unix:.0f} {ts_ms}"
    )
    lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------
# --- I/O boundary ---
# ---------------------------------------------------------------------


def load_envelope(path: Path) -> dict[str, Any]:
    """Load and parse a Tag-48 heatmap envelope file.

    Raises ``FileNotFoundError`` for a missing file (the CLI surfaces
    this as a non-zero exit so the workflow fails fast). Raises
    ``json.JSONDecodeError`` for malformed content.
    """
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def write_textfile(prom_text: str, output_path: Path) -> None:
    """Atomically write Prometheus textfile content to ``output_path``.

    Atomicity matters: ``node_exporter --collector.textfile`` scrapes
    the directory on a timer and a half-written file would surface
    a parse error in the textfile-collector's own metrics. The
    write-temp-then-rename pattern is the node-exporter docs'
    explicit recommendation.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=output_path.name + ".",
        suffix=".tmp",
        dir=str(output_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(prom_text)
        os.replace(tmp_name, output_path)
    except Exception:
        # Best-effort cleanup. The tmp file may already have been
        # renamed (in which case unlink is a no-op surrogate that
        # raises FileNotFoundError -- swallow).
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def resolve_envelope_path(
    heatmap_dir: Path, today_iso: str | None
) -> Path:
    """Resolve the envelope file path for a given day.

    If ``today_iso`` is None, the most recent (lexicographically
    largest) yyyy-mm-dd.json in ``heatmap_dir`` is used. This makes
    the emitter idempotent: a re-run on the same day picks the
    same envelope.
    """
    if today_iso:
        return heatmap_dir / f"{today_iso}.json"
    if not heatmap_dir.is_dir():
        raise FileNotFoundError(
            f"heatmap dir does not exist: {heatmap_dir}"
        )
    candidates = sorted(
        entry
        for entry in heatmap_dir.iterdir()
        if entry.is_file() and entry.suffix == ".json"
    )
    if not candidates:
        raise FileNotFoundError(
            f"no heatmap envelopes found in {heatmap_dir}"
        )
    return candidates[-1]


# ---------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="per-welle-heatmap-prom-emitter",
        description=(
            "Transform a Tag-48 per-Welle heatmap JSON envelope into a "
            "Prometheus textfile-collector .prom file. Output is "
            "compatible with node_exporter "
            "--collector.textfile.directory and the Tag-48 Grafana "
            "dashboard ``dashboards/per-welle-trend-heatmap.json``."
        ),
    )
    p.add_argument(
        "--heatmap-dir",
        default=DEFAULT_HEATMAP_DIR,
        help=(
            "Directory containing yyyy-mm-dd.json heatmap envelopes "
            f"(default: {DEFAULT_HEATMAP_DIR})."
        ),
    )
    p.add_argument(
        "--input-envelope",
        default=None,
        help=(
            "Explicit envelope path. If set, overrides --heatmap-dir / "
            "--today envelope resolution."
        ),
    )
    p.add_argument(
        "--today",
        default=None,
        help=(
            "Envelope day as yyyy-mm-dd. Default: most recent envelope "
            "in --heatmap-dir."
        ),
    )
    p.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_PROM,
        help=(
            f"Output .prom path (default: {DEFAULT_OUTPUT_PROM}). "
            "Conventional node_exporter scrape path: "
            "/var/lib/prometheus/node-exporter/per-welle-heatmap.prom"
        ),
    )
    p.add_argument(
        "--print",
        action="store_true",
        help="Also print the rendered textfile to stdout.",
    )
    return p


def cli_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.input_envelope:
        envelope_path = Path(args.input_envelope)
    else:
        envelope_path = resolve_envelope_path(
            Path(args.heatmap_dir), args.today
        )

    envelope = load_envelope(envelope_path)
    prom_text = render_prometheus_textfile(envelope)

    output_path = Path(args.output)
    write_textfile(prom_text, output_path)

    print(
        f"wrote {output_path} "
        f"(envelope={envelope_path}, "
        f"cells={len(envelope.get('cells') or [])})",
        file=sys.stderr,
    )
    if args.print:
        sys.stdout.write(prom_text)

    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
