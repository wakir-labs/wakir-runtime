#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Aggregator + per-scenario pinning helper for the Tag-56 Watch-Day-
Practice-Run CI workflow (`.github/workflows/phase-3c-watch-day-
practice-run.yml`).

Three modes (selected by ``--mode``):

* ``pin`` - Per-scenario verdict + red-blocker pinning. Reads the
  practice-run JSON report (``--report``) and asserts each scenario
  reached its expected verdict and expected red-blocker tuple. Exit
  0 on full match, 2 if any scenario diverges (treated as ``yellow``
  in the workflow because the substrate ran but the regression-pin
  caught drift), 1 on internal errors (report missing / malformed).

* ``sequence`` - Slot-sequence-validation per scenario. Asserts each
  scenario's ``sequence_validation_ok`` is ``true``. Same exit-code
  convention as ``pin``.

* ``aggregate`` - Tri-state decision-aggregation (READY/CAUTION/
  BLOCK). Reads ``STEP1_STATUS``..``STEP4_STATUS`` from the
  environment and emits a JSON verdict-envelope to ``--output``.
  Verdict rules:
    * READY    - all four steps green.
    * CAUTION  - exactly one step yellow, the rest green.
    * BLOCK    - any step red, or 2+ yellow.

The module is intentionally pure-stdlib: it is invoked from the
CI workflow with no third-party dependencies installed. The tests
in ``tests/ci/test_phase_3c_watch_day_practice_run_workflow.py``
walk the full truth-table.

Anchor: Tag-56 Noa-SRE Watch-Day-Practice-Run CI-Gate.
Predecessors:
  Tag-54 spec + verdict (PR #347),
  Tag-55 practice-run simulator (PR #353).
Author: Noa Bergstroem (SRE)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Truth-table constants. Single-sourced here so the workflow YAML
# and the tests stay aligned.
# ---------------------------------------------------------------------------

STEP_KEYS: tuple[str, ...] = (
    "STEP1_STATUS",
    "STEP2_STATUS",
    "STEP3_STATUS",
    "STEP4_STATUS",
)

VALID_STATUSES: frozenset[str] = frozenset({"green", "yellow", "red"})

VERDICT_READY = "READY"
VERDICT_CAUTION = "CAUTION"
VERDICT_BLOCK = "BLOCK"


# ---------------------------------------------------------------------------
# Exit codes (kept stable so the workflow's bash dispatch can rely
# on them).
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_ERROR = 1       # internal error (report missing / malformed)
EXIT_DIVERGED = 2    # substrate ran but regression-pin caught drift


# ---------------------------------------------------------------------------
# Mode: pin
# ---------------------------------------------------------------------------


def _load_report(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        print(f"::error::report missing: {path}", file=sys.stderr)
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"::error::report malformed: {exc}", file=sys.stderr)
        return None


def mode_pin(report_path: Path) -> int:
    """Per-scenario verdict + red-blocker pinning."""
    report = _load_report(report_path)
    if report is None:
        return EXIT_ERROR
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        print("::error::report contains no scenarios", file=sys.stderr)
        return EXIT_ERROR
    diverged: list[str] = []
    for sc in scenarios:
        name = sc.get("scenario", "<unknown>")
        if sc.get("computed_verdict") != sc.get("expected_verdict"):
            diverged.append(
                f"{name}: verdict {sc.get('computed_verdict')!r} "
                f"!= expected {sc.get('expected_verdict')!r}"
            )
            continue
        computed_blockers = tuple(sc.get("computed_red_blockers") or ())
        expected_blockers = tuple(sc.get("expected_red_blockers") or ())
        if computed_blockers != expected_blockers:
            diverged.append(
                f"{name}: red_blockers {list(computed_blockers)!r} "
                f"!= expected {list(expected_blockers)!r}"
            )
    if diverged:
        print("::warning::per-scenario verdict-pin caught drift:", file=sys.stderr)
        for d in diverged:
            print(f"  - {d}", file=sys.stderr)
        return EXIT_DIVERGED
    print(f"per-scenario verdict-pin: all {len(scenarios)} scenarios match")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Mode: sequence
# ---------------------------------------------------------------------------


def mode_sequence(report_path: Path) -> int:
    """Slot-sequence-validation per scenario."""
    report = _load_report(report_path)
    if report is None:
        return EXIT_ERROR
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        print("::error::report contains no scenarios", file=sys.stderr)
        return EXIT_ERROR
    diverged: list[str] = []
    for sc in scenarios:
        name = sc.get("scenario", "<unknown>")
        if not sc.get("sequence_validation_ok", False):
            errors = sc.get("sequence_validation_errors") or []
            diverged.append(f"{name}: {errors!r}")
    if diverged:
        print(
            "::warning::slot-sequence-validation caught drift:", file=sys.stderr
        )
        for d in diverged:
            print(f"  - {d}", file=sys.stderr)
        return EXIT_DIVERGED
    print(
        f"slot-sequence-validation: all {len(scenarios)} scenarios well-formed"
    )
    return EXIT_OK


# ---------------------------------------------------------------------------
# Mode: aggregate
# ---------------------------------------------------------------------------


def normalize_status(raw: str | None) -> str:
    """Map a raw env-string to a known status. Empty/unknown -> red."""
    if raw is None:
        return "red"
    raw = raw.strip().lower()
    if raw in VALID_STATUSES:
        return raw
    return "red"


def compute_verdict(statuses: dict[str, str]) -> str:
    """Compute the tri-state verdict from the four step-statuses."""
    s = [statuses[k] for k in STEP_KEYS]
    reds = sum(1 for x in s if x == "red")
    yellows = sum(1 for x in s if x == "yellow")
    greens = sum(1 for x in s if x == "green")
    if reds == 0 and yellows == 0 and greens == 4:
        return VERDICT_READY
    if reds == 0 and yellows == 1:
        return VERDICT_CAUTION
    return VERDICT_BLOCK


def build_envelope(
    statuses: dict[str, str], missing: str
) -> dict[str, Any]:
    verdict = compute_verdict(statuses)
    return {
        "verdict": verdict,
        "steps": {
            "step1_inventory": statuses["STEP1_STATUS"],
            "step2_hermetic_practice_run": statuses["STEP2_STATUS"],
            "step3_per_scenario_verdict_pinning": statuses["STEP3_STATUS"],
            "step4_slot_sequence_validation": statuses["STEP4_STATUS"],
        },
        "inventory_missing": [m for m in (missing or "").split(",") if m],
        "schema_version": 1,
    }


def mode_aggregate(output_path: Path) -> int:
    statuses = {k: normalize_status(os.environ.get(k)) for k in STEP_KEYS}
    missing = os.environ.get("INVENTORY_MISSING", "")
    envelope = build_envelope(statuses, missing)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(envelope, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"verdict={envelope['verdict']}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aggregate_watch_day_practice_run_verdict",
        description=(
            "Aggregator + per-scenario pinning helper for the Tag-56 "
            "Watch-Day-Practice-Run CI workflow."
        ),
    )
    p.add_argument(
        "--mode",
        choices=("pin", "sequence", "aggregate"),
        required=True,
        help="Which step the helper runs for.",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=Path("out/watch-day-practice-run-report.json"),
        help="Path to the practice-run JSON report (for pin/sequence modes).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("out/watch-day-practice-run-verdict.json"),
        help="Output path for the aggregated verdict envelope.",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.mode == "pin":
        return mode_pin(args.report)
    if args.mode == "sequence":
        return mode_sequence(args.report)
    if args.mode == "aggregate":
        return mode_aggregate(args.output)
    parser.error(f"unknown mode: {args.mode}")
    return EXIT_ERROR  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
