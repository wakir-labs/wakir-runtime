#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-65 Cutover-Day-Morgen Verdict-Tile Prometheus textfile renderer.

The Tag-65 marathon-dashboard-kachel (``dashboards/cutover-day-
morgen-verdict-tile.json``) reads four Prometheus series:

* ``wakir_cutover_day_morgen_verdict_class``
    Integer-encoded trinary verdict
    (``0`` READY, ``1`` CAUTION, ``2`` BLOCK). The recording rule
    that emits this gauge from the AlertManager-side recording-rule
    table is shared with the Tag-64 trinary-routing alerts in
    ``dashboards/phase-3-marathon-alerts.yaml``. The Tag-65 helper
    can also emit this gauge from a static verdict-envelope so a
    Grafana-shaped render is possible without Prometheus.

* ``wakir_cutover_day_morgen_verdict_emitted_at_seconds``
    Unix-seconds of the verdict-envelope's ``emitted_at_utc``
    field. The dashboard panel-3 computes
    ``time() - <this gauge>`` to display the freshness-age.

* ``wakir_cutover_day_morgen_window_days_remaining``
    Calendar-days remaining in the KW-24..27 cutover window
    (2026-06-08 .. 2026-07-03 inclusive). Outside the window the
    gauge reads ``-1`` and the dashboard panel-2 surfaces
    ``out-of-window`` via value-mapping.

* ``wakir_cutover_day_morgen_substrate_class{substrate=...}``
    Per-substrate integer-encoded class (engine_composite /
    pyramide_composite / e2e_smoke). ``0`` green, ``1`` yellow,
    ``2`` red. Mirrors the ``step_results`` field of the Tag-64
    envelope.

Input
-----

The helper reads the Tag-64 Cutover-Day-Morgen Auto-Scheduler
verdict-envelope JSON emitted by
``tooling/ci/aggregate_cutover_day_morgen_verdict.py`` (default:
``out/cutover-day-morgen-verdict.json``). The envelope-schema is
documented in that helper's docstring; this helper consumes the
``verdict``, ``emitted_at_utc``, ``window.iso_week`` and
``step_results`` fields.

Output
------

A Prometheus textfile-collector-shaped block written to stdout (or
to ``--output`` if supplied). Stdlib only - no Prometheus client,
no NATS, no network.

Window math
-----------

The KW-24..27 window is defined as the four ISO weeks in 2026
whose ``isoweek`` ordinal is in ``{24, 25, 26, 27}``. The
``days_remaining`` value is the count of calendar-days from
``today_iso`` to ``end-of-KW-27 = 2026-07-03`` (the Friday of
KW-27 in 2026), inclusive of both endpoints; values clamp at
``[0, 28]`` inside the window. Outside the window the helper
returns ``-1``.

Hermetic envelope
-----------------

Stdlib only. ``today_iso`` is configurable via ``--today``
(default: today at UTC); window-end is a module-level constant.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


# ---- Verdict-class encoding ---------------------------------------------

# Mirror of the Tag-64 trinary recording-rule integer-encoding
# documented in dashboards/phase-3-marathon-alerts.yaml:
#   wakir_cutover_day_morgen_verdict_class == 0  -> READY
#   wakir_cutover_day_morgen_verdict_class == 1  -> CAUTION
#   wakir_cutover_day_morgen_verdict_class == 2  -> BLOCK
VERDICT_TO_CLASS: dict[str, int] = {
    "CUTOVER-DAY-MORGEN-READY": 0,
    "CUTOVER-DAY-MORGEN-CAUTION": 1,
    "CUTOVER-DAY-MORGEN-BLOCK": 2,
}

# Mirror of the per-substrate uniform trinary status from the
# Tag-64 aggregator. Keep keys lowercase to match the
# step_results mapping the aggregator emits.
STATUS_TO_CLASS: dict[str, int] = {
    "green": 0,
    "yellow": 1,
    "red": 2,
}

# Sentinel for unknown / missing values. ``-1`` is read by the
# Grafana value-mapping as "unknown" (the dashboard renders it as
# ``out-of-window`` for the window-days gauge; for verdict-class
# the dashboard hides values < 0). Centralising the sentinel keeps
# the test-suite's mapping unambiguous.
SENTINEL_UNKNOWN: int = -1


# ---- KW-24..27 window constants -----------------------------------------

# KW-24..27 in 2026 spans 2026-06-08 (Mon KW-24) through
# 2026-07-03 (Fri KW-27). The Tag-64 aggregator surfaces the
# window claim on the envelope's ``window.iso_week`` field; the
# Tag-65 helper derives the remaining-days from the window end-of-
# Friday-of-KW-27 vs. ``today_iso``.
CUTOVER_WINDOW_ISO_WEEKS: tuple[int, ...] = (24, 25, 26, 27)
WINDOW_START_ISO: str = "2026-06-08"  # Mon KW-24 2026
WINDOW_END_ISO: str = "2026-07-03"    # Fri KW-27 2026
WINDOW_DAYS_TOTAL: int = 28  # 4 ISO weeks (Mon..Sun) but window
                              # is 26 calendar days end-inclusive;
                              # the gauge max is 28 to keep the
                              # Grafana-display margin clean.


# ---- Series-name constants ----------------------------------------------

# All four series names are exposed as module-level constants so
# the test-suite can assert on the rendered textfile shape
# without re-typing the strings.
SERIES_VERDICT_CLASS: str = "wakir_cutover_day_morgen_verdict_class"
SERIES_EMITTED_AT_SECONDS: str = (
    "wakir_cutover_day_morgen_verdict_emitted_at_seconds"
)
SERIES_WINDOW_DAYS_REMAINING: str = (
    "wakir_cutover_day_morgen_window_days_remaining"
)
SERIES_IN_CUTOVER_WINDOW: str = (
    "wakir_cutover_day_morgen_in_cutover_window"
)
SERIES_SUBSTRATE_CLASS: str = (
    "wakir_cutover_day_morgen_substrate_class"
)


# ---- Envelope loading ----------------------------------------------------


def load_envelope(path: Path) -> dict[str, Any]:
    """Load a Tag-64 verdict-envelope from disk.

    Raises ``FileNotFoundError`` / ``ValueError`` on I/O or parse
    failure. The CLI catches these and exits non-zero; the unit
    tests exercise the raise-path directly.
    """
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"envelope at {path} is not a JSON object")
    return parsed


# ---- Verdict-class extraction --------------------------------------------


def verdict_to_class(verdict: str | None) -> int:
    """Map the aggregated verdict string to its integer class.

    Returns ``SENTINEL_UNKNOWN`` for unknown / missing verdicts.
    """
    if not isinstance(verdict, str):
        return SENTINEL_UNKNOWN
    return VERDICT_TO_CLASS.get(verdict, SENTINEL_UNKNOWN)


def substrate_status_to_class(status: str | None) -> int:
    """Map a per-substrate status to its integer class.

    Returns ``SENTINEL_UNKNOWN`` for unknown / missing statuses.
    """
    if not isinstance(status, str):
        return SENTINEL_UNKNOWN
    return STATUS_TO_CLASS.get(status, SENTINEL_UNKNOWN)


# ---- Timestamp extraction ------------------------------------------------


def emitted_at_to_unix(emitted_at_utc: str | None) -> int:
    """Convert an ISO-8601 ``emitted_at_utc`` to Unix-seconds.

    Accepts the ``YYYY-MM-DDTHH:MM:SS+00:00`` shape that the
    Tag-64 aggregator emits. Returns ``SENTINEL_UNKNOWN`` on parse
    failure or missing input.
    """
    if not isinstance(emitted_at_utc, str):
        return SENTINEL_UNKNOWN
    try:
        # ``datetime.fromisoformat`` handles ``+00:00`` directly
        # (Python 3.11+). The aggregator emits ``timespec=seconds``
        # so no fractional-second handling is required.
        parsed = datetime.fromisoformat(emitted_at_utc)
    except ValueError:
        return SENTINEL_UNKNOWN
    if parsed.tzinfo is None:
        # Defensive: assume UTC for naive timestamps.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


# ---- Window math ---------------------------------------------------------


def parse_today(today_arg: str | None) -> date:
    """Parse ``--today`` or default to UTC today.

    Accepts the ``YYYY-MM-DD`` shape only.
    """
    if today_arg is None:
        return datetime.now(timezone.utc).date()
    return date.fromisoformat(today_arg)


def window_days_remaining(
    today: date,
    *,
    window_end_iso: str = WINDOW_END_ISO,
) -> int:
    """Calendar-days remaining in the KW-24..27 window.

    Returns ``-1`` if ``today`` is after the window end. Inside
    the window: ``(window_end - today).days``, clamped at
    ``[0, WINDOW_DAYS_TOTAL]``. Before the window: the same
    formula yields a positive integer >= window-length; the
    helper clamps to ``WINDOW_DAYS_TOTAL`` so the gauge max
    is respected.
    """
    end = date.fromisoformat(window_end_iso)
    delta = (end - today).days
    if delta < 0:
        return -1
    if delta > WINDOW_DAYS_TOTAL:
        return WINDOW_DAYS_TOTAL
    return delta


def in_cutover_window(iso_week: int | None) -> int:
    """Return ``1`` iff ``iso_week`` is in KW-24..27 else ``0``.

    Returns ``0`` for ``None`` (no window claim).
    """
    if not isinstance(iso_week, int):
        return 0
    return 1 if iso_week in CUTOVER_WINDOW_ISO_WEEKS else 0


# ---- Render --------------------------------------------------------------


def _format_help_line(name: str, help_text: str, type_text: str) -> list[str]:
    return [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} {type_text}",
    ]


def render(
    envelope: Mapping[str, Any],
    *,
    today: date,
) -> str:
    """Render the verdict-tile Prometheus textfile block.

    Output is deterministic - the substrate ordering matches the
    Tag-64 aggregator's ``SUBSTRATES`` tuple, and the series order
    is the dashboard's panel order (verdict_class first).
    """
    verdict = envelope.get("verdict")
    verdict_class = verdict_to_class(verdict)
    emitted_at = envelope.get("emitted_at_utc")
    emitted_seconds = emitted_at_to_unix(emitted_at)
    window = envelope.get("window") or {}
    iso_week = window.get("iso_week") if isinstance(window, Mapping) else None
    days_remaining = window_days_remaining(today)
    in_window = in_cutover_window(iso_week)
    step_results = envelope.get("step_results") or {}
    if not isinstance(step_results, Mapping):
        step_results = {}

    lines: list[str] = []

    lines += _format_help_line(
        SERIES_VERDICT_CLASS,
        "Tag-64 Cutover-Day-Morgen trinary verdict class "
        "(0=READY, 1=CAUTION, 2=BLOCK, -1=unknown).",
        "gauge",
    )
    lines.append(f"{SERIES_VERDICT_CLASS} {verdict_class}")

    lines += _format_help_line(
        SERIES_EMITTED_AT_SECONDS,
        "Unix-seconds of the Tag-64 Cutover-Day-Morgen verdict-"
        "envelope emitted_at_utc field.",
        "gauge",
    )
    lines.append(f"{SERIES_EMITTED_AT_SECONDS} {emitted_seconds}")

    lines += _format_help_line(
        SERIES_WINDOW_DAYS_REMAINING,
        "Calendar-days remaining in the KW-24..27 cutover-window "
        "(2026-06-08..2026-07-03). -1 if outside the window.",
        "gauge",
    )
    lines.append(f"{SERIES_WINDOW_DAYS_REMAINING} {days_remaining}")

    lines += _format_help_line(
        SERIES_IN_CUTOVER_WINDOW,
        "Whether the envelope's window.iso_week is in KW-24..27 "
        "(1=in-window, 0=outside-or-unknown).",
        "gauge",
    )
    lines.append(f"{SERIES_IN_CUTOVER_WINDOW} {in_window}")

    # Substrate ordering: keep the Tag-64 aggregator's canonical
    # tuple (engine_composite -> pyramide_composite -> e2e_smoke).
    substrate_order: tuple[str, ...] = (
        "engine_composite",
        "pyramide_composite",
        "e2e_smoke",
    )
    lines += _format_help_line(
        SERIES_SUBSTRATE_CLASS,
        "Per-substrate trinary class for the Tag-64 Cutover-Day-"
        "Morgen verdict (0=green, 1=yellow, 2=red, -1=unknown). "
        "Labels: substrate.",
        "gauge",
    )
    for substrate in substrate_order:
        status = step_results.get(substrate)
        sub_class = substrate_status_to_class(status)
        lines.append(
            f'{SERIES_SUBSTRATE_CLASS}{{substrate="{substrate}"}} {sub_class}'
        )

    return "\n".join(lines) + "\n"


# ---- CLI -----------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="render_cutover_day_morgen_tile",
        description=(
            "Render the Tag-65 Cutover-Day-Morgen verdict-tile "
            "Prometheus textfile block from a Tag-64 Auto-"
            "Scheduler verdict-envelope JSON."
        ),
    )
    p.add_argument(
        "--envelope",
        type=Path,
        required=True,
        help="Path to the Tag-64 verdict-envelope JSON.",
    )
    p.add_argument(
        "--today",
        type=str,
        default=None,
        help=(
            "ISO date (YYYY-MM-DD) overriding the UTC today for "
            "window-days-remaining math. Used by the test-suite "
            "to obtain deterministic output."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Path to write the textfile-block. Default: stdout."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        envelope = load_envelope(args.envelope)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: cannot load envelope: {exc}", file=sys.stderr)
        return 2
    today = parse_today(args.today)
    block = render(envelope, today=today)
    if args.output is None:
        sys.stdout.write(block)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(block, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
