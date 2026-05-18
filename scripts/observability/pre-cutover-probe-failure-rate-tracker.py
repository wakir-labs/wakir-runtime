#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Pre-Cutover-Probe-Failure-Rate-Tracker (Tag-42 Noa-SRE).

Context
-------

ADR-0066 (Phase-3c Beschleunigung, KW-24..27) bundles seven Welle-
cutovers from the persona-engine Python-default to the Rust-default.
Each Welle has a Pre-Cutover-Sanity-Probe driver under
``scripts/phase-3c/welle-N-pre-cutover-probe.sh`` (Welle-1 PR #267
Reza-Tag-41, Welle-2..7 in follow-on tags). Each probe emits one of
five verdicts at exit:

  - ``GREEN``      — all axes matched, cutover GO.
  - ``CAUTION``    — at least one yellow axis, operator review required.
  - ``BLOCK``      — at least one red axis, cutover NO-GO.
  - ``NOT-EXEC``   — probe could not run (precondition missing).
  - ``PENDING``    — probe scheduled but not yet executed.

The probes run on a daily schedule plus on-demand pre-cutover. Over
the ~3-day Pre-Cutover-window per Welle the operator needs:

  1. **Per-Welle current verdict** — which Wellen are GREEN today?
  2. **Per-Welle verdict-history** — was Welle-N GREEN yesterday too,
     or did it just flip? Stability over the Pre-Cutover-window is
     the AR-Hand-Sign-Off-Pre-Condition (ADR-0066 §AR-Hand-Gate).
  3. **Aggregate Marathon-Readiness-Score** (0-100%) — single
     number for the AR-Sitzung "is the marathon ready to start?"
  4. **Welle-Coupling-Indikatoren** — Welle-3-Sign-Off is the
     pre-condition for Welle-7 R2-replay; Welle-4-Cutover-Done is the
     pre-condition for Welle-7 State-Backing-Read. Surface those
     dependencies as boolean panels.
  5. **Henrik-Pre-Audit-Sign-Off-Status** per Welle (sourced from
     Tag-39 + Tag-40 specs; absence == not-yet-signed-off).
  6. **Cutover-Day-Window-Empfehlung** — per-Welle date+time slot
     derived from Kai's Runbook §10 (working-hours-overlap, on-call
     coverage, Doppel-Welle-spacing).

This tracker is a read-only roll-up: it consumes the persisted
probe-output JSON files in ``reports/live-vm/*-pre-cutover-probe.md``
(or a fixture path in hermetic-test mode), aggregates into rollups +
verdict-history, and emits JSON + Prometheus textfile + a Markdown
operator summary.

Sandbox boundary
----------------

When invoked with ``--mode=fixture`` and a ``--fixture-probes`` path,
the script reads a pre-computed probe-history JSON and skips
filesystem-walks of the live-vm reports directory. This is the mode
the hermetic test suite uses.

Pure-function-vs-IO split
-------------------------

Everything above the ``# --- I/O boundary ---`` marker is pure-
function, hermetic-test target. The I/O wrappers
(``walk_probe_reports``) are isolated at the bottom.

Anchors
-------

* ADR-0066 §AR-Hand-Gate — Pre-Cutover-Probe stability over the
  ~3-day window is a Pre-Condition for AR-Hand-Sign-Off.
* ADR-0065 §Cutover-Plan — defines the seven Welle ordering.
* Tag-41 PR #267 (Reza) — Welle-1 Pre-Cutover-Sanity-Probe reference
  implementation; the verdict-axis schema this tracker consumes.
* Tag-39 + Tag-40 Henrik-Pre-Audit-Sign-Off specs — source for
  the Henrik-Sign-Off-Status panel.
* Sister-script: ``aggregator-failure-rate-tracker.py`` (PR #251,
  Tag-38). Tag-42 inherits its Prometheus-textfile format and
  fixture-mode pattern.

Author: Noa Bergstroem (SRE)
Tag: 42 (KW-22)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The seven Welle slugs in cutover order (ADR-0066). The tracker
#: emits one rollup row per Welle, in this order, so dashboards can
#: index by position.
WELLE_SLUGS: Tuple[str, ...] = (
    "welle-1",
    "welle-2",
    "welle-3",
    "welle-4",
    "welle-5",
    "welle-6",
    "welle-7",
)

#: The five allowed probe-verdict values. Anything else is rejected at
#: parse-time so a typo in a probe-output cannot silently desync the
#: dashboard.
ALLOWED_VERDICTS: Tuple[str, ...] = (
    "GREEN",
    "CAUTION",
    "BLOCK",
    "NOT-EXEC",
    "PENDING",
)

#: Numeric mapping for Prometheus emission (Prometheus only accepts
#: float gauges). Same encoding the cross-welle dashboard already
#: uses for ``persona_engine_phase_3c_welle_state``.
VERDICT_TO_NUMERIC: Mapping[str, float] = {
    "GREEN": 0.0,
    "CAUTION": 1.0,
    "BLOCK": 2.0,
    "PENDING": 3.0,
    "NOT-EXEC": 4.0,
}

#: Marathon-Readiness scoring weights. Sums to 1.0; a single Welle
#: with verdict GREEN contributes ``(1/7) * 100`` percentage points.
#:
#: Penalties: CAUTION halves the contribution, BLOCK zeros it,
#: PENDING/NOT-EXEC contribute zero. Henrik-Sign-Off is an
#: independent additive bonus capped at 100%.
MARATHON_READINESS_GREEN_PER_WELLE = (1.0 / 7.0) * 100.0
MARATHON_READINESS_CAUTION_FRACTION = 0.5
MARATHON_READINESS_HENRIK_SIGNOFF_BONUS = 5.0  # absolute pp per Welle

#: Welle-Coupling-Pre-Conditions. ADR-0066 §Coupling-Matrix:
#:
#:   - Welle-7 (recovery_workflow) **R2/State-Backing-Read** needs
#:     Welle-4 (state_backing) Cutover-Done.
#:   - Welle-7 **R1/Bridge-Audit-Replay** needs Welle-3
#:     (bridge_audit_writer) Sign-Off.
#:   - Welle-6 (subscribe_loop) needs Welle-2 (svid_workload_identity)
#:     Cutover-Done (subscribe uses SVID).
#:   - Welle-5 (lifecycle_state_machine) needs Welle-4 Cutover-Done
#:     (lifecycle reads state_backing).
COUPLING: Mapping[str, Tuple[Tuple[str, str], ...]] = {
    "welle-5": (("welle-4", "Cutover-Done"),),
    "welle-6": (("welle-2", "Cutover-Done"),),
    "welle-7": (
        ("welle-3", "Sign-Off"),
        ("welle-4", "Cutover-Done"),
    ),
}

DEFAULT_PROMETHEUS_TEXTFILE_PATH = (
    "/var/lib/prometheus/node-exporter/wakir_pre_cutover_probe.prom"
)

#: Cutover-Day-Window-Empfehlung per Welle. ADR-0066 §Marathon-KW-24..27
#: + Kai-Runbook §10 (working-hours overlap, on-call coverage). The
#: recommendations are RFC3339 dates in TZ Europe/Berlin; the operator
#: dashboard renders these as a static table panel.
CUTOVER_DAY_WINDOWS: Mapping[str, Mapping[str, str]] = {
    "welle-1": {"week": "KW-24", "date": "2026-06-09", "slot": "10:00-12:00 CEST"},
    "welle-2": {"week": "KW-24", "date": "2026-06-11", "slot": "10:00-12:00 CEST"},
    "welle-3": {"week": "KW-25", "date": "2026-06-16", "slot": "10:00-13:00 CEST"},
    "welle-4": {"week": "KW-26", "date": "2026-06-23", "slot": "10:00-12:00 CEST"},
    "welle-5": {"week": "KW-26", "date": "2026-06-25", "slot": "14:00-16:00 CEST"},
    "welle-6": {"week": "KW-27", "date": "2026-06-30", "slot": "10:00-12:00 CEST"},
    "welle-7": {"week": "KW-27", "date": "2026-07-02", "slot": "10:00-14:00 CEST"},
}


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeRun:
    """One executed pre-cutover-probe.

    A probe writes its summary to
    ``reports/live-vm/YYYY-MM-DD-welle-N-pre-cutover-probe.md`` with
    the verdict in a known frontmatter-style header. The parser
    ``parse_probe_report`` reads that header.
    """

    welle: str
    timestamp_unixtime: float
    verdict: str  # one of ALLOWED_VERDICTS
    operator: str  # who ran the probe (Reza, Selin, ...)
    detail: str  # free-form one-line summary


@dataclass(frozen=True)
class HenrikSignOff:
    """One Henrik-Pre-Audit-Sign-Off record per Welle.

    Source: Tag-39 + Tag-40 audit-spec deliverables. Absence means
    "not yet signed off".
    """

    welle: str
    signed_off: bool
    timestamp_unixtime: Optional[float]
    detail: str


@dataclass
class WelleRollup:
    """Per-Welle roll-up of probe-history + Henrik-Sign-Off.

    Mutable on construction so the rollup engine can incrementally
    fill in fields; consumers (renderers) only read.
    """

    welle: str
    current_verdict: str = "PENDING"
    history: List[ProbeRun] = field(default_factory=list)
    henrik_signed_off: bool = False
    henrik_signoff_timestamp: Optional[float] = None
    cutover_window: Mapping[str, str] = field(default_factory=dict)
    coupling_pre_conditions_met: bool = True
    coupling_blockers: List[str] = field(default_factory=list)

    @property
    def stability_consecutive_green(self) -> int:
        """Count of consecutive GREEN verdicts from most-recent backward.

        Stability is the AR-Hand-Sign-Off-Pre-Condition: at least
        three consecutive GREEN probe-runs before AR-Hand. The exact
        threshold is operator-configurable; this property exposes the
        raw count and lets the dashboard panel apply the threshold.
        """
        # History is stored most-recent-first by the rollup engine.
        count = 0
        for run in self.history:
            if run.verdict == "GREEN":
                count += 1
            else:
                break
        return count


# ---------------------------------------------------------------------------
# Pure-function rollups (hermetic-test target)
# ---------------------------------------------------------------------------


def rollup_per_welle(
    probes: Sequence[ProbeRun],
    henrik_signoffs: Sequence[HenrikSignOff],
    *,
    welle_slugs: Sequence[str] = WELLE_SLUGS,
    cutover_windows: Mapping[str, Mapping[str, str]] = CUTOVER_DAY_WINDOWS,
    coupling: Mapping[str, Tuple[Tuple[str, str], ...]] = COUPLING,
) -> List[WelleRollup]:
    """Compute per-Welle rollups from raw probe-history + Henrik records.

    Pure function. The hermetic test
    ``test_rollup_per_welle_*`` feeds this with synthetic inputs and
    asserts the output shape.

    Args:
        probes: all probe runs in any order. The rollup sorts per-
            Welle most-recent-first internally.
        henrik_signoffs: Henrik-Pre-Audit-Sign-Off records, one per
            Welle (or fewer; absence == not-signed-off).
        welle_slugs: Welle ordering (default ``WELLE_SLUGS``).
        cutover_windows: per-Welle window-recommendation map.
        coupling: per-Welle pre-condition map.

    Returns:
        One ``WelleRollup`` per slug in ``welle_slugs`` order, even
        for Wellen with zero probe-runs (current_verdict = PENDING).
    """
    by_welle: Dict[str, List[ProbeRun]] = {w: [] for w in welle_slugs}
    for p in probes:
        if p.welle in by_welle:
            by_welle[p.welle].append(p)
    henrik_by_welle: Dict[str, HenrikSignOff] = {
        h.welle: h for h in henrik_signoffs
    }

    # First pass: per-Welle current_verdict + history.
    rollups: Dict[str, WelleRollup] = {}
    for welle in welle_slugs:
        history = sorted(
            by_welle[welle], key=lambda p: p.timestamp_unixtime, reverse=True
        )
        current = history[0].verdict if history else "PENDING"
        henrik = henrik_by_welle.get(welle)
        rollups[welle] = WelleRollup(
            welle=welle,
            current_verdict=current,
            history=history,
            henrik_signed_off=bool(henrik and henrik.signed_off),
            henrik_signoff_timestamp=(henrik.timestamp_unixtime if henrik else None),
            cutover_window=dict(cutover_windows.get(welle, {})),
        )

    # Second pass: coupling pre-conditions. Needs first-pass output.
    for welle in welle_slugs:
        deps = coupling.get(welle, ())
        blockers: List[str] = []
        for dep_welle, dep_condition in deps:
            dep_rollup = rollups.get(dep_welle)
            if dep_rollup is None:
                blockers.append(f"{dep_welle}-rollup-missing")
                continue
            # Cutover-Done condition: dep welle current_verdict == GREEN
            # AND henrik_signed_off. Sign-Off condition: henrik only.
            if dep_condition == "Cutover-Done":
                if dep_rollup.current_verdict != "GREEN":
                    blockers.append(f"{dep_welle}-verdict={dep_rollup.current_verdict}")
                if not dep_rollup.henrik_signed_off:
                    blockers.append(f"{dep_welle}-henrik-unsigned")
            elif dep_condition == "Sign-Off":
                if not dep_rollup.henrik_signed_off:
                    blockers.append(f"{dep_welle}-henrik-unsigned")
            else:
                blockers.append(
                    f"{dep_welle}-unknown-condition={dep_condition}"
                )
        rollups[welle].coupling_blockers = blockers
        rollups[welle].coupling_pre_conditions_met = not blockers

    return [rollups[w] for w in welle_slugs]


def compute_marathon_readiness_score(
    rollups: Sequence[WelleRollup],
    *,
    green_per_welle: float = MARATHON_READINESS_GREEN_PER_WELLE,
    caution_fraction: float = MARATHON_READINESS_CAUTION_FRACTION,
    henrik_bonus: float = MARATHON_READINESS_HENRIK_SIGNOFF_BONUS,
) -> float:
    """Compute the 0-100% Marathon-Readiness aggregate score.

    Pure function. Formula:

      score = sum over wellen of [
        (GREEN  -> green_per_welle) |
        (CAUTION -> green_per_welle * caution_fraction) |
        (other  -> 0)
      ] + sum over wellen of [
        (henrik_signed_off -> henrik_bonus) | (else -> 0)
      ]

    Capped at 100.0. Henrik-Bonus is a separate axis so the AR can
    see e.g. "85% verdict-readiness + 15% Henrik = 100%" vs.
    "100% verdict-readiness + 0% Henrik = 100% but unsigned".

    Args:
        rollups: per-Welle rollups produced by ``rollup_per_welle``.
        green_per_welle: contribution of a single GREEN Welle (default
            14.28pp = 100/7).
        caution_fraction: CAUTION verdict fraction of GREEN-contribution.
        henrik_bonus: absolute pp per Henrik-Sign-Off (default 5pp).

    Returns:
        Float in [0.0, 100.0].
    """
    score = 0.0
    for r in rollups:
        if r.current_verdict == "GREEN":
            score += green_per_welle
        elif r.current_verdict == "CAUTION":
            score += green_per_welle * caution_fraction
        # BLOCK / PENDING / NOT-EXEC contribute 0.
        if r.henrik_signed_off:
            score += henrik_bonus
    return min(100.0, max(0.0, score))


def render_prometheus_textfile(
    rollups: Sequence[WelleRollup],
    *,
    marathon_score: float,
    timestamp_unixtime: Optional[float] = None,
) -> str:
    """Render per-Welle rollups + Marathon-Score as Prometheus textfile.

    Pure function. Output schema:

      # HELP wakir_pre_cutover_probe_verdict ...
      # TYPE wakir_pre_cutover_probe_verdict gauge
      wakir_pre_cutover_probe_verdict{welle="welle-1"} 0
      ...
      # HELP wakir_pre_cutover_probe_history_count Total recorded probes per Welle
      ...
      # HELP wakir_pre_cutover_probe_stability_consecutive_green ...
      ...
      # HELP wakir_pre_cutover_henrik_signoff ...
      ...
      # HELP wakir_pre_cutover_coupling_pre_conditions_met ...
      ...
      # HELP wakir_marathon_readiness_score 0-100%
      # TYPE wakir_marathon_readiness_score gauge
      wakir_marathon_readiness_score 71.42

    Each metric is labelled with welle="..." except marathon_readiness
    which is a scalar. The textfile is scraped by Prometheus's
    ``node-exporter --collector.textfile`` at the conventional
    ``/var/lib/prometheus/node-exporter/`` path.
    """
    if timestamp_unixtime is None:
        timestamp_unixtime = time.time()
    ts_ms = int(timestamp_unixtime * 1000)
    lines: List[str] = []

    lines.append(
        "# HELP wakir_pre_cutover_probe_verdict Current Pre-Cutover-Probe "
        "verdict per Welle. 0=GREEN, 1=CAUTION, 2=BLOCK, 3=PENDING, "
        "4=NOT-EXEC. Source: scripts/phase-3c/welle-N-pre-cutover-probe.sh "
        "exit-code + report. Tag-42 ADR-0066 AR-Hand-Gate observability."
    )
    lines.append("# TYPE wakir_pre_cutover_probe_verdict gauge")
    for r in rollups:
        val = VERDICT_TO_NUMERIC.get(r.current_verdict, 4.0)
        lines.append(
            f'wakir_pre_cutover_probe_verdict{{welle="{_esc(r.welle)}"}} '
            f"{val:.0f} {ts_ms}"
        )
    lines.append("")

    lines.append(
        "# HELP wakir_pre_cutover_probe_history_count Total recorded "
        "probe runs per Welle within the consumed history window."
    )
    lines.append("# TYPE wakir_pre_cutover_probe_history_count gauge")
    for r in rollups:
        lines.append(
            f'wakir_pre_cutover_probe_history_count{{welle="{_esc(r.welle)}"}} '
            f"{len(r.history)} {ts_ms}"
        )
    lines.append("")

    lines.append(
        "# HELP wakir_pre_cutover_probe_stability_consecutive_green "
        "Consecutive GREEN verdicts from most-recent backward. "
        "AR-Hand-Sign-Off-Pre-Condition: >= 3."
    )
    lines.append("# TYPE wakir_pre_cutover_probe_stability_consecutive_green gauge")
    for r in rollups:
        lines.append(
            f'wakir_pre_cutover_probe_stability_consecutive_green'
            f'{{welle="{_esc(r.welle)}"}} '
            f"{r.stability_consecutive_green} {ts_ms}"
        )
    lines.append("")

    lines.append(
        "# HELP wakir_pre_cutover_henrik_signoff Henrik-Pre-Audit-Sign-Off "
        "status per Welle. 1=signed, 0=unsigned. Source: Tag-39 + Tag-40 "
        "audit-spec deliverables."
    )
    lines.append("# TYPE wakir_pre_cutover_henrik_signoff gauge")
    for r in rollups:
        lines.append(
            f'wakir_pre_cutover_henrik_signoff{{welle="{_esc(r.welle)}"}} '
            f"{1 if r.henrik_signed_off else 0} {ts_ms}"
        )
    lines.append("")

    lines.append(
        "# HELP wakir_pre_cutover_coupling_pre_conditions_met "
        "Welle-Coupling-Pre-Conditions met (e.g. Welle-7 needs Welle-4 "
        "Cutover-Done). 1=met, 0=blocked."
    )
    lines.append("# TYPE wakir_pre_cutover_coupling_pre_conditions_met gauge")
    for r in rollups:
        lines.append(
            f'wakir_pre_cutover_coupling_pre_conditions_met'
            f'{{welle="{_esc(r.welle)}"}} '
            f"{1 if r.coupling_pre_conditions_met else 0} {ts_ms}"
        )
    lines.append("")

    lines.append(
        "# HELP wakir_marathon_readiness_score Aggregate 0-100% "
        "Marathon-Readiness across the seven Wellen. Formula: 7x14.28pp "
        "verdict-weighted (GREEN=full, CAUTION=half, BLOCK/PENDING/"
        "NOT-EXEC=0) + 7x5pp Henrik-Sign-Off-Bonus, capped at 100."
    )
    lines.append("# TYPE wakir_marathon_readiness_score gauge")
    lines.append(
        f"wakir_marathon_readiness_score {marathon_score:.2f} {ts_ms}"
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _esc(s: str) -> str:
    """Prometheus-textfile label-value escape (matches sister tracker)."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def render_json_rollup(
    rollups: Sequence[WelleRollup],
    *,
    marathon_score: float,
    timestamp_unixtime: Optional[float] = None,
) -> str:
    """Render per-Welle rollups as operator-readable JSON."""
    if timestamp_unixtime is None:
        timestamp_unixtime = time.time()
    out = {
        "schema_version": 1,
        "anchor": "ADR-0066 §AR-Hand-Gate (Tag-42 Noa-SRE)",
        "timestamp_unixtime": timestamp_unixtime,
        "marathon_readiness_score": marathon_score,
        "wellen": [],
    }
    for r in rollups:
        out["wellen"].append(
            {
                "welle": r.welle,
                "current_verdict": r.current_verdict,
                "history_count": len(r.history),
                "stability_consecutive_green": r.stability_consecutive_green,
                "henrik_signed_off": r.henrik_signed_off,
                "henrik_signoff_timestamp": r.henrik_signoff_timestamp,
                "cutover_window": dict(r.cutover_window),
                "coupling_pre_conditions_met": r.coupling_pre_conditions_met,
                "coupling_blockers": list(r.coupling_blockers),
                "history": [
                    {
                        "timestamp_unixtime": p.timestamp_unixtime,
                        "verdict": p.verdict,
                        "operator": p.operator,
                        "detail": p.detail,
                    }
                    for p in r.history
                ],
            }
        )
    return json.dumps(out, indent=2, sort_keys=True) + "\n"


def render_markdown_summary(
    rollups: Sequence[WelleRollup],
    *,
    marathon_score: float,
    timestamp_unixtime: Optional[float] = None,
) -> str:
    """Render an operator-readable Markdown summary.

    Pure function. The Markdown is the one-pager the AR-Sitzung uses
    for the "is the marathon ready?" question.
    """
    if timestamp_unixtime is None:
        timestamp_unixtime = time.time()
    lines: List[str] = []
    lines.append("# Pre-Cutover-Probe-Status (Marathon-Readiness)")
    lines.append("")
    lines.append(f"_Snapshot: unixtime {timestamp_unixtime:.0f}_")
    lines.append("")
    lines.append(f"**Marathon-Readiness-Score: {marathon_score:.1f}%**")
    lines.append("")
    lines.append("| Welle | Verdict | Stability | Henrik | Coupling | Cutover-Window |")
    lines.append("|---|---|---|---|---|---|")
    for r in rollups:
        henrik = "signed" if r.henrik_signed_off else "unsigned"
        coupling = "met" if r.coupling_pre_conditions_met else (
            "blocked: " + ", ".join(r.coupling_blockers)
        )
        win = r.cutover_window
        win_str = (
            f"{win.get('week', '?')} {win.get('date', '?')} "
            f"{win.get('slot', '?')}"
        )
        lines.append(
            f"| {r.welle} | {r.current_verdict} | "
            f"{r.stability_consecutive_green}x GREEN | "
            f"{henrik} | {coupling} | {win_str} |"
        )
    lines.append("")
    lines.append(
        "_Source: scripts/observability/pre-cutover-probe-failure-rate-"
        "tracker.py (Tag-42 Noa-SRE). Per-Welle probe sources: "
        "scripts/phase-3c/welle-N-pre-cutover-probe.sh._"
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Probe-report parser (pure function — operates on the markdown text)
# ---------------------------------------------------------------------------

#: Regex that extracts the verdict line from the Welle-1 probe report
#: format (Reza Tag-41). Tolerates leading whitespace and any-case
#: ``AGGREGATE:``. Anchored to one of the five allowed verdicts.
_VERDICT_LINE = re.compile(
    r"^\s*\|?\s*AGGREGATE:?\s*\|?\s*(GREEN|CAUTION|BLOCK|NOT-EXEC|PENDING)\b",
    re.IGNORECASE | re.MULTILINE,
)

#: Welle slug regex matching the report filename convention
#: ``YYYY-MM-DD-welle-N-pre-cutover-probe.md``.
_FILENAME_PATTERN = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})-(?P<welle>welle-[1-7])-pre-cutover-probe(?:-[a-z0-9-]+)?\.md$"
)


def parse_probe_report(
    text: str, *, filename: str, default_operator: str = "unknown"
) -> Optional[ProbeRun]:
    """Parse one probe-report markdown into a ProbeRun.

    Pure function. Returns ``None`` if the verdict cannot be located
    (e.g. the file is a stub, or a probe-not-yet-run placeholder).

    Args:
        text: full markdown content of the report.
        filename: basename of the report file (no path). Used to
            extract Welle slug + date.
        default_operator: fallback operator name if the report has no
            ``Operator:`` line. Empty / unknown is acceptable; the
            dashboard does not key on operator.
    """
    m_name = _FILENAME_PATTERN.search(filename)
    if not m_name:
        return None
    welle = m_name.group("welle")
    date_iso = m_name.group("date")
    try:
        from datetime import datetime, timezone

        ts = datetime.fromisoformat(date_iso + "T00:00:00+00:00").timestamp()
    except (ValueError, TypeError):
        return None

    m_verdict = _VERDICT_LINE.search(text)
    if not m_verdict:
        return None
    verdict = m_verdict.group(1).upper()
    if verdict not in ALLOWED_VERDICTS:
        return None

    # Optional operator-extract. Look for a line ``Operator: NAME``.
    operator = default_operator
    for line in text.splitlines():
        s = line.strip()
        if s.lower().startswith("operator:"):
            operator = s.split(":", 1)[1].strip() or default_operator
            break

    # Optional one-line detail.
    detail = ""
    for line in text.splitlines():
        s = line.strip()
        if s.lower().startswith("summary:"):
            detail = s.split(":", 1)[1].strip()
            break

    return ProbeRun(
        welle=welle,
        timestamp_unixtime=ts,
        verdict=verdict,
        operator=operator,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# I/O boundary
# ---------------------------------------------------------------------------


def walk_probe_reports(reports_dir: Path) -> List[ProbeRun]:
    """Walk ``reports/live-vm/`` for probe-report markdowns and parse.

    Non-pure: filesystem I/O. The hermetic tests substitute a fixture
    directory via tmp_path.
    """
    out: List[ProbeRun] = []
    if not reports_dir.is_dir():
        return out
    for entry in sorted(reports_dir.iterdir()):
        if not entry.is_file():
            continue
        if not _FILENAME_PATTERN.search(entry.name):
            continue
        try:
            text = entry.read_text(encoding="utf-8")
        except OSError:
            continue
        run = parse_probe_report(text, filename=entry.name)
        if run is not None:
            out.append(run)
    return out


def load_henrik_signoffs_from_file(path: Path) -> List[HenrikSignOff]:
    """Load Henrik-Pre-Audit-Sign-Off records from a JSON file.

    Schema::

        [{"welle": "welle-1", "signed_off": true,
          "timestamp_unixtime": 1718000000.0, "detail": "..."}, ...]

    Returns empty list when the file is missing (Henrik has not yet
    published any sign-offs).
    """
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: List[HenrikSignOff] = []
    for entry in raw:
        out.append(
            HenrikSignOff(
                welle=str(entry.get("welle", "")),
                signed_off=bool(entry.get("signed_off", False)),
                timestamp_unixtime=entry.get("timestamp_unixtime"),
                detail=str(entry.get("detail", "")),
            )
        )
    return out


def load_fixture_probes(path: Path) -> Tuple[List[ProbeRun], List[HenrikSignOff]]:
    """Load a fixture JSON containing both probes and henrik sign-offs.

    Schema::

        {
          "probes": [{"welle": "...", "timestamp_unixtime": 0.0,
                      "verdict": "...", "operator": "...",
                      "detail": "..."}, ...],
          "henrik_signoffs": [{"welle": "...", "signed_off": true,
                                "timestamp_unixtime": 0.0,
                                "detail": "..."}, ...]
        }
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    probes = [
        ProbeRun(
            welle=str(p.get("welle", "")),
            timestamp_unixtime=float(p.get("timestamp_unixtime", 0.0)),
            verdict=str(p.get("verdict", "PENDING")),
            operator=str(p.get("operator", "unknown")),
            detail=str(p.get("detail", "")),
        )
        for p in raw.get("probes", [])
    ]
    signoffs = [
        HenrikSignOff(
            welle=str(h.get("welle", "")),
            signed_off=bool(h.get("signed_off", False)),
            timestamp_unixtime=h.get("timestamp_unixtime"),
            detail=str(h.get("detail", "")),
        )
        for h in raw.get("henrik_signoffs", [])
    ]
    return probes, signoffs


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pre-cutover-probe-failure-rate-tracker",
        description=(
            "Pre-Cutover-Probe-Failure-Rate-Tracker (Tag-42 Noa-SRE). "
            "Aggregates per-Welle probe verdicts into the Marathon-"
            "Readiness-Score and emits JSON + Prometheus textfile + "
            "Markdown summary."
        ),
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=Path("reports/live-vm"),
        help="Directory containing welle-N-pre-cutover-probe.md reports.",
    )
    parser.add_argument(
        "--henrik-signoff-file",
        type=Path,
        default=Path("reports/audit/henrik-pre-audit-signoffs.json"),
        help="JSON file with Henrik-Pre-Audit-Sign-Off records.",
    )
    parser.add_argument(
        "--mode",
        choices=("live", "fixture"),
        default="live",
        help=(
            "``live``: walk --reports-dir + read --henrik-signoff-file. "
            "``fixture``: read --fixture-probes (hermetic-test)."
        ),
    )
    parser.add_argument(
        "--fixture-probes",
        type=Path,
        default=None,
        help="Path to combined fixture JSON (mode=fixture).",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Write JSON rollup to this path. If omitted, writes to stdout.",
    )
    parser.add_argument(
        "--prometheus-output",
        type=Path,
        default=None,
        help=(
            "Write Prometheus textfile to this path. Conventional value: "
            f"{DEFAULT_PROMETHEUS_TEXTFILE_PATH}"
        ),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=None,
        help="Write Markdown operator-summary to this path.",
    )
    parser.add_argument(
        "--fail-on-block",
        action="store_true",
        help=(
            "Exit non-zero if any Welle current_verdict is BLOCK. "
            "Operator semantics: a non-zero exit blocks the AR-Hand "
            "marathon-go-decision script."
        ),
    )
    args = parser.parse_args(argv)

    if args.mode == "fixture":
        if not args.fixture_probes:
            print(
                "ERROR: --fixture-probes required in mode=fixture.",
                file=sys.stderr,
            )
            return 2
        probes, signoffs = load_fixture_probes(args.fixture_probes)
    else:
        probes = walk_probe_reports(args.reports_dir)
        signoffs = load_henrik_signoffs_from_file(args.henrik_signoff_file)

    print(
        f"Loaded {len(probes)} probe runs across {len({p.welle for p in probes})} "
        f"Wellen + {len(signoffs)} Henrik-Sign-Off records (mode={args.mode}).",
        file=sys.stderr,
    )

    rollups = rollup_per_welle(probes, signoffs)
    marathon_score = compute_marathon_readiness_score(rollups)

    ts = time.time()
    json_text = render_json_rollup(
        rollups, marathon_score=marathon_score, timestamp_unixtime=ts
    )
    if args.json_output:
        args.json_output.write_text(json_text, encoding="utf-8")
        print(f"Wrote JSON rollup to {args.json_output}", file=sys.stderr)
    else:
        sys.stdout.write(json_text)

    if args.prometheus_output:
        prom_text = render_prometheus_textfile(
            rollups, marathon_score=marathon_score, timestamp_unixtime=ts
        )
        args.prometheus_output.write_text(prom_text, encoding="utf-8")
        print(
            f"Wrote Prometheus textfile to {args.prometheus_output}",
            file=sys.stderr,
        )

    if args.markdown_output:
        md_text = render_markdown_summary(
            rollups, marathon_score=marathon_score, timestamp_unixtime=ts
        )
        args.markdown_output.write_text(md_text, encoding="utf-8")
        print(
            f"Wrote Markdown summary to {args.markdown_output}",
            file=sys.stderr,
        )

    if args.fail_on_block:
        blocked = [r.welle for r in rollups if r.current_verdict == "BLOCK"]
        if blocked:
            print(
                f"BLOCK verdict on: {', '.join(blocked)}. Marathon-Go-"
                f"Decision blocked.",
                file=sys.stderr,
            )
            return 1

    print(
        f"Marathon-Readiness-Score: {marathon_score:.1f}%. "
        f"Per-Welle: "
        + ", ".join(f"{r.welle}={r.current_verdict}" for r in rollups),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
