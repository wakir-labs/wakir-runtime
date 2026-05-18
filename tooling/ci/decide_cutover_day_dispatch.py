#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""decide_cutover_day_dispatch - Tag-44 cutover-day auto-scheduler
decision-tree.

Background
----------

The Phase-3c cutover marathon (ADR-0065 + ADR-0066) flips the
persona-engine default backend in seven Wellen over four ISO-weeks::

    KW-24 Mo   Welle-1 + Welle-2    doppel
    KW-25 Mo   Welle-3              solo (Henrik caution-path)
    KW-26 Mo   Welle-4 + Welle-5    doppel
    KW-27 Mo   Welle-6 + Welle-7    doppel + Phase-3-COMPLETE marker

The Tomas Tag-44 auto-scheduler
(``.github/workflows/phase-3-cutover-day-auto-scheduler.yml``) wakes
up every Monday 07:00 UTC during KW 20..30 and decides what to
dispatch based on which calendar-week we are in. This module is the
hermetic decision-tree behind that workflow.

Design
------

A pure-function decision pipeline split into three stages:

1.  ``decide_week_action(iso_week)`` maps an ISO calendar week to one
    of four ``WeekAction`` shapes (Welle-1+2, Welle-3, Welle-4+5,
    Welle-6+7), or ``PROBE_ONLY`` for any other week.

2.  ``evaluate_gates(gate_inputs)`` consumes three pre-trigger gate
    inputs (Reza Tag-44 daily-driver trend, Tomas Tag-41 pre-cutover-
    sanity verdict, AR-Hand ratification flag) and returns a
    ``GateVerdict`` of ``PROCEED`` / ``DRY_RUN_ONLY`` / ``BLOCK``.

3.  ``build_dispatch_plan(week_action, gate_verdict, now_iso)``
    composes the two upstream verdicts into a JSON-serialisable
    dispatch-plan envelope which the workflow yaml then renders into
    a series of ``gh workflow run`` invocations.

The CLI surface is::

    python3 tooling/ci/decide_cutover_day_dispatch.py \\
        --iso-week 24 \\
        --reza-trend-path state/reza-tag-44-trend.json \\
        --sanity-verdict-path artifacts/pre-cutover-sanity-verdict.json \\
        --ar-hand-flag-path state/ar-hand-cutover-day-flag.json \\
        --now-iso 2026-06-08T07:00:00+00:00 \\
        --output out/cutover-day-dispatch-plan.json

The output JSON has the shape::

    {
      "version": "1.0",
      "now_iso": "2026-06-08T07:00:00+00:00",
      "iso_week": 24,
      "week_action": {
        "kind": "WELLE_1_PLUS_2",
        "wellen": [1, 2],
        "complete_marker": false
      },
      "gate_verdict": {
        "kind": "PROCEED",
        "reza_trend": "green",
        "sanity_verdict": "READY",
        "ar_hand_ratified": true,
        "missing_inputs": []
      },
      "dispatch": {
        "mode": "TRIGGER",
        "workflows": [
          "phase-3c-welle-1-validation.yml",
          "phase-3c-welle-2-validation.yml"
        ],
        "tracker_updates": [
          {"welle": 1, "state": "cutover-running", "note": "auto-scheduler KW-24"},
          {"welle": 2, "state": "cutover-running", "note": "auto-scheduler KW-24"}
        ],
        "trigger_complete_marker": false
      },
      "notify": {
        "headline": "Phase-3c KW-24 Cutover-Day: Welle-1+2 TRIGGER",
        "lines": [...]
      }
    }

Sandbox boundary: stdlib-only. No network, no subprocess, no
filesystem writes (the CLI writes the plan-envelope, nothing else).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0"

# ADR-0066 cutover-plan: ISO-week -> (Welle-list, complete-marker-flag).
CUTOVER_WEEK_PLAN: Dict[int, Tuple[List[int], bool]] = {
    24: ([1, 2], False),
    25: ([3], False),
    26: ([4, 5], False),
    27: ([6, 7], True),
}

WELLE_VALIDATION_WORKFLOWS: Dict[int, str] = {
    n: f"phase-3c-welle-{n}-validation.yml" for n in range(1, 8)
}

COMPLETE_MARKER_WORKFLOW = "phase-3-complete-marker.yml"

PRE_CUTOVER_PROBE_WORKFLOW = "phase-3c-pre-cutover-sanity.yml"


# ---------------------------------------------------------------------------
# Stage 1: week-action decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WeekAction:
    """What kind of cutover does this ISO-week call for?"""

    kind: str  # "WELLE_1_PLUS_2", "WELLE_3", "WELLE_4_PLUS_5",
    # "WELLE_6_PLUS_7", or "PROBE_ONLY"
    wellen: Tuple[int, ...]
    complete_marker: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "wellen": list(self.wellen),
            "complete_marker": self.complete_marker,
        }


def decide_week_action(iso_week: int) -> WeekAction:
    """Map an ISO calendar week to its WeekAction shape.

    KW-24 -> Welle-1+2 doppel.
    KW-25 -> Welle-3 solo (Henrik caution-path).
    KW-26 -> Welle-4+5 doppel.
    KW-27 -> Welle-6+7 doppel + Phase-3-COMPLETE marker.
    any other week -> PROBE_ONLY (Reza Tag-44 daily-driver re-probe).
    """
    if iso_week not in CUTOVER_WEEK_PLAN:
        return WeekAction(kind="PROBE_ONLY", wellen=(), complete_marker=False)

    wellen, complete_marker = CUTOVER_WEEK_PLAN[iso_week]
    if iso_week == 24:
        kind = "WELLE_1_PLUS_2"
    elif iso_week == 25:
        kind = "WELLE_3"
    elif iso_week == 26:
        kind = "WELLE_4_PLUS_5"
    else:  # iso_week == 27
        kind = "WELLE_6_PLUS_7"
    return WeekAction(
        kind=kind, wellen=tuple(wellen), complete_marker=complete_marker
    )


# ---------------------------------------------------------------------------
# Stage 2: gate evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateInputs:
    """Three gate-input observations.

    * ``reza_trend``: one of ``"green"``, ``"yellow"``, ``"red"``, or
      ``"missing"``. Sourced from Reza Tag-44 daily-driver trend file.
    * ``sanity_verdict``: one of ``"READY"``, ``"CAUTION"``,
      ``"BLOCK"``, or ``"missing"``. Sourced from the Tomas Tag-41
      pre-cutover-sanity verdict-envelope artifact.
    * ``ar_hand_ratified``: ``True``/``False`` from the AR-Hand
      cutover-day flag-file. ``False`` means "no flag found" or "flag
      explicitly set to false".
    """

    reza_trend: str
    sanity_verdict: str
    ar_hand_ratified: bool


@dataclass(frozen=True)
class GateVerdict:
    """Composite gate decision.

    * ``PROCEED``: all three gates green/ready/ratified -> real
      dispatch.
    * ``DRY_RUN_ONLY``: AR-Hand-flag missing OR sanity-verdict is
      CAUTION OR reza-trend is yellow. We render the plan but the
      workflow will emit it as dry-run only without dispatching.
    * ``BLOCK``: sanity-verdict is BLOCK or any input is missing
      (defaults to red) -> no dispatch, plan emitted as block.
    """

    kind: str  # PROCEED | DRY_RUN_ONLY | BLOCK
    reza_trend: str
    sanity_verdict: str
    ar_hand_ratified: bool
    missing_inputs: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "reza_trend": self.reza_trend,
            "sanity_verdict": self.sanity_verdict,
            "ar_hand_ratified": self.ar_hand_ratified,
            "missing_inputs": list(self.missing_inputs),
        }


def evaluate_gates(inputs: GateInputs) -> GateVerdict:
    """Compose three gate inputs into a tri-state verdict.

    Rules:
        1. ``sanity_verdict == "BLOCK"`` -> BLOCK.
        2. Any input missing -> BLOCK (with ``missing_inputs`` set).
        3. ``sanity_verdict == "CAUTION"`` OR ``reza_trend == "yellow"``
           OR ``ar_hand_ratified is False`` -> DRY_RUN_ONLY.
        4. ``reza_trend == "red"`` -> BLOCK.
        5. Otherwise (``green`` + ``READY`` + ``True``) -> PROCEED.
    """
    missing: List[str] = []
    if inputs.reza_trend == "missing":
        missing.append("reza_trend")
    if inputs.sanity_verdict == "missing":
        missing.append("sanity_verdict")

    if inputs.sanity_verdict == "BLOCK":
        return GateVerdict(
            kind="BLOCK",
            reza_trend=inputs.reza_trend,
            sanity_verdict=inputs.sanity_verdict,
            ar_hand_ratified=inputs.ar_hand_ratified,
            missing_inputs=tuple(missing),
        )
    if inputs.reza_trend == "red":
        return GateVerdict(
            kind="BLOCK",
            reza_trend=inputs.reza_trend,
            sanity_verdict=inputs.sanity_verdict,
            ar_hand_ratified=inputs.ar_hand_ratified,
            missing_inputs=tuple(missing),
        )
    if missing:
        return GateVerdict(
            kind="BLOCK",
            reza_trend=inputs.reza_trend,
            sanity_verdict=inputs.sanity_verdict,
            ar_hand_ratified=inputs.ar_hand_ratified,
            missing_inputs=tuple(missing),
        )

    degrade = (
        inputs.sanity_verdict == "CAUTION"
        or inputs.reza_trend == "yellow"
        or not inputs.ar_hand_ratified
    )
    if degrade:
        return GateVerdict(
            kind="DRY_RUN_ONLY",
            reza_trend=inputs.reza_trend,
            sanity_verdict=inputs.sanity_verdict,
            ar_hand_ratified=inputs.ar_hand_ratified,
            missing_inputs=tuple(missing),
        )

    return GateVerdict(
        kind="PROCEED",
        reza_trend=inputs.reza_trend,
        sanity_verdict=inputs.sanity_verdict,
        ar_hand_ratified=inputs.ar_hand_ratified,
        missing_inputs=tuple(missing),
    )


# ---------------------------------------------------------------------------
# Stage 3: dispatch-plan composition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispatchPlan:
    mode: str  # TRIGGER | DRY_RUN | BLOCK | PROBE
    workflows: Tuple[str, ...]
    tracker_updates: Tuple[Dict[str, Any], ...]
    trigger_complete_marker: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "workflows": list(self.workflows),
            "tracker_updates": [dict(u) for u in self.tracker_updates],
            "trigger_complete_marker": self.trigger_complete_marker,
        }


def _tracker_update(welle: int, iso_week: int) -> Dict[str, Any]:
    return {
        "welle": welle,
        "state": "cutover-running",
        "note": f"auto-scheduler KW-{iso_week}",
    }


def build_dispatch_plan(
    week_action: WeekAction,
    gate_verdict: GateVerdict,
    iso_week: int,
) -> DispatchPlan:
    """Compose the workflow-set and tracker-updates list.

    Mapping:
      * (PROBE_ONLY, *)              -> PROBE: pre-cutover-sanity only.
      * (cutover-week, BLOCK)        -> BLOCK: empty workflows.
      * (cutover-week, DRY_RUN_ONLY) -> DRY_RUN: workflows listed but
        the workflow yaml will NOT call ``gh workflow run``.
      * (cutover-week, PROCEED)      -> TRIGGER: real dispatch.

    The complete-marker workflow is only ever appended for KW-27
    PROCEED (Welle-6+7 doppel).
    """
    if week_action.kind == "PROBE_ONLY":
        return DispatchPlan(
            mode="PROBE",
            workflows=(PRE_CUTOVER_PROBE_WORKFLOW,),
            tracker_updates=(),
            trigger_complete_marker=False,
        )

    if gate_verdict.kind == "BLOCK":
        return DispatchPlan(
            mode="BLOCK",
            workflows=(),
            tracker_updates=(),
            trigger_complete_marker=False,
        )

    workflows: List[str] = [
        WELLE_VALIDATION_WORKFLOWS[n] for n in week_action.wellen
    ]
    tracker_updates: List[Dict[str, Any]] = [
        _tracker_update(n, iso_week) for n in week_action.wellen
    ]
    trigger_marker = week_action.complete_marker and gate_verdict.kind == "PROCEED"
    if trigger_marker:
        workflows.append(COMPLETE_MARKER_WORKFLOW)

    mode = "TRIGGER" if gate_verdict.kind == "PROCEED" else "DRY_RUN"

    return DispatchPlan(
        mode=mode,
        workflows=tuple(workflows),
        tracker_updates=tuple(tracker_updates),
        trigger_complete_marker=trigger_marker,
    )


# ---------------------------------------------------------------------------
# Notify-cascade rendering
# ---------------------------------------------------------------------------


def render_notify(
    iso_week: int,
    week_action: WeekAction,
    gate_verdict: GateVerdict,
    plan: DispatchPlan,
) -> Dict[str, Any]:
    """Compose a notify-cascade payload for the Slack-mock / notify-stream."""
    if plan.mode == "PROBE":
        headline = (
            f"Phase-3c Pre-Cutover-Probe KW-{iso_week} (non-cutover week)"
        )
        lines = [
            "No cutover scheduled this ISO-week.",
            f"Probe dispatch: {PRE_CUTOVER_PROBE_WORKFLOW}",
        ]
    elif plan.mode == "BLOCK":
        headline = (
            f"Phase-3c KW-{iso_week} Cutover-Day: BLOCK "
            f"({week_action.kind})"
        )
        lines = [
            f"Sanity verdict: {gate_verdict.sanity_verdict}",
            f"Reza trend: {gate_verdict.reza_trend}",
            f"AR-Hand ratified: {gate_verdict.ar_hand_ratified}",
        ]
        if gate_verdict.missing_inputs:
            lines.append(
                "Missing inputs: " + ", ".join(gate_verdict.missing_inputs)
            )
        lines.append("No workflow dispatches performed.")
    elif plan.mode == "DRY_RUN":
        headline = (
            f"Phase-3c KW-{iso_week} Cutover-Day: DRY-RUN-ONLY "
            f"({week_action.kind})"
        )
        lines = [
            f"Sanity verdict: {gate_verdict.sanity_verdict}",
            f"Reza trend: {gate_verdict.reza_trend}",
            f"AR-Hand ratified: {gate_verdict.ar_hand_ratified}",
            "Would-trigger workflows (not executed):",
        ]
        for wf in plan.workflows:
            lines.append(f"  - {wf}")
    else:  # TRIGGER
        headline = (
            f"Phase-3c KW-{iso_week} Cutover-Day: TRIGGER "
            f"({week_action.kind})"
        )
        lines = [
            f"Sanity verdict: {gate_verdict.sanity_verdict}",
            f"Reza trend: {gate_verdict.reza_trend}",
            f"AR-Hand ratified: {gate_verdict.ar_hand_ratified}",
            "Triggered workflows:",
        ]
        for wf in plan.workflows:
            lines.append(f"  - {wf}")
        if plan.trigger_complete_marker:
            lines.append("Phase-3-COMPLETE marker triggered (KW-27 final).")

    return {"headline": headline, "lines": lines}


# ---------------------------------------------------------------------------
# Input-file parsers
# ---------------------------------------------------------------------------


def parse_reza_trend(path: Optional[Path]) -> str:
    """Parse Reza Tag-44 daily-driver trend file.

    Expected JSON shape::

        {"trend": "green"|"yellow"|"red", ...}

    Returns ``"missing"`` if the file does not exist or has no
    ``trend`` field. Returns ``"red"`` if the trend value is not one
    of the documented enum-values (defensive default).
    """
    if path is None or not path.is_file():
        return "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "red"
    trend = data.get("trend") if isinstance(data, dict) else None
    if trend in ("green", "yellow", "red"):
        return trend
    return "missing" if trend is None else "red"


def parse_sanity_verdict(path: Optional[Path]) -> str:
    """Parse Tomas Tag-41 pre-cutover-sanity verdict-envelope.

    Expected JSON shape (see ``aggregate_pre_cutover_sanity_verdict.py``)::

        {"verdict": "READY"|"CAUTION"|"BLOCK", ...}
    """
    if path is None or not path.is_file():
        return "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "BLOCK"
    verdict = data.get("verdict") if isinstance(data, dict) else None
    if verdict in ("READY", "CAUTION", "BLOCK"):
        return verdict
    return "missing" if verdict is None else "BLOCK"


def parse_ar_hand_flag(path: Optional[Path]) -> bool:
    """Parse AR-Hand cutover-day flag-file.

    Expected JSON shape::

        {"ar_hand_ratified": true, "ratified_at": "...", "quote": "..."}

    A missing file, an unreadable file, or a flag explicitly set to
    ``false`` all map to ``False``. Only a clean ``true`` returns
    ``True``.
    """
    if path is None or not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    return data.get("ar_hand_ratified") is True


# ---------------------------------------------------------------------------
# Top-level envelope
# ---------------------------------------------------------------------------


def build_envelope(
    iso_week: int,
    inputs: GateInputs,
    now_iso: str,
) -> Dict[str, Any]:
    week_action = decide_week_action(iso_week)
    gate_verdict = evaluate_gates(inputs)
    plan = build_dispatch_plan(week_action, gate_verdict, iso_week)
    notify = render_notify(iso_week, week_action, gate_verdict, plan)
    return {
        "version": SCHEMA_VERSION,
        "now_iso": now_iso,
        "iso_week": iso_week,
        "week_action": week_action.to_dict(),
        "gate_verdict": gate_verdict.to_dict(),
        "dispatch": plan.to_dict(),
        "notify": notify,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="decide_cutover_day_dispatch",
        description=(
            "Tag-44 Phase-3 cutover-day auto-scheduler decision-tree."
        ),
    )
    p.add_argument(
        "--iso-week",
        type=int,
        required=True,
        help="Current ISO calendar week (1..53).",
    )
    p.add_argument(
        "--reza-trend-path",
        type=Path,
        default=None,
        help=(
            "Path to Reza Tag-44 daily-driver trend JSON file. "
            "Missing/unreadable file => 'missing' (gates to BLOCK)."
        ),
    )
    p.add_argument(
        "--sanity-verdict-path",
        type=Path,
        default=None,
        help=(
            "Path to Tomas Tag-41 pre-cutover-sanity verdict JSON "
            "artifact. Missing/unreadable file => 'missing'."
        ),
    )
    p.add_argument(
        "--ar-hand-flag-path",
        type=Path,
        default=None,
        help=(
            "Path to AR-Hand cutover-day ratification flag JSON. "
            "Missing/false => DRY_RUN_ONLY."
        ),
    )
    p.add_argument(
        "--now-iso",
        type=str,
        default="",
        help="ISO-8601 'now' timestamp for the envelope.",
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output path for the dispatch-plan JSON envelope.",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    inputs = GateInputs(
        reza_trend=parse_reza_trend(args.reza_trend_path),
        sanity_verdict=parse_sanity_verdict(args.sanity_verdict_path),
        ar_hand_ratified=parse_ar_hand_flag(args.ar_hand_flag_path),
    )
    envelope = build_envelope(args.iso_week, inputs, args.now_iso)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    # Pretty-print to stdout for the step-summary.
    print(json.dumps(envelope, indent=2, sort_keys=True))
    # Exit codes mirror the gate verdict so the workflow can branch:
    #   0 = TRIGGER or PROBE
    #   1 = DRY_RUN_ONLY (degraded; workflow continues, skips dispatch)
    #   2 = BLOCK
    mode = envelope["dispatch"]["mode"]
    if mode in ("TRIGGER", "PROBE"):
        return 0
    if mode == "DRY_RUN":
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
