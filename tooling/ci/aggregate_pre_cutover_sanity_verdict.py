#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Decision-aggregator for ``phase-3c-pre-cutover-sanity.yml``.

Reads the four per-step tri-state results from the environment
(``STEP1_STATUS`` ... ``STEP4_STATUS``, each one of
``{green, yellow, red}``) and emits a single Marathon-Readiness
verdict-envelope JSON file.

Decision rule
-------------

* ``READY``   - all four steps green.
* ``CAUTION`` - exactly one step yellow, the other three green.
* ``BLOCK``   - any step red, OR two or more steps yellow.

Empty / missing env-vars default to ``red`` (we assume an upstream
job failed entirely if its output is absent). The ``INVENTORY_MISSING``
env-var, when non-empty, is a comma-separated list of inventory
items the Step-1 probe reported as missing; we record it on the
verdict-envelope.

Exit code
---------

Always ``0``. The verdict-envelope's ``verdict`` field carries
the BLOCK/CAUTION/READY signal; the calling workflow translates
that to step-exit semantics.

Hermetic
--------

stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


VALID_STATUSES = ("green", "yellow", "red")


def _normalise(raw: str | None) -> str:
    """Coerce an env-var value to a known status. Empty -> red."""
    if raw is None:
        return "red"
    v = raw.strip().lower()
    if v in VALID_STATUSES:
        return v
    if v == "":
        return "red"
    # Unknown values are treated as red (loud failure mode).
    return "red"


def decide(steps: Mapping[str, str]) -> str:
    reds = sum(1 for v in steps.values() if v == "red")
    yellows = sum(1 for v in steps.values() if v == "yellow")
    greens = sum(1 for v in steps.values() if v == "green")
    if reds >= 1:
        return "BLOCK"
    if yellows >= 2:
        return "BLOCK"
    if yellows == 1:
        return "CAUTION"
    if greens == len(steps):
        return "READY"
    return "BLOCK"


def build_envelope(env: Mapping[str, str]) -> dict:
    steps = {
        "step_1_substanz_inventory_check": _normalise(env.get("STEP1_STATUS")),
        "step_2_cross_welle_generalprobe_dry_run": _normalise(env.get("STEP2_STATUS")),
        "step_3_marathon_tracker_state_check": _normalise(env.get("STEP3_STATUS")),
        "step_4_marker_workflow_dry_run": _normalise(env.get("STEP4_STATUS")),
    }
    reds = sum(1 for v in steps.values() if v == "red")
    yellows = sum(1 for v in steps.values() if v == "yellow")
    greens = sum(1 for v in steps.values() if v == "green")
    verdict = decide(steps)
    failed = [k for k, v in steps.items() if v != "green"]
    missing_raw = env.get("INVENTORY_MISSING", "") or ""
    inventory_missing = (
        [item for item in missing_raw.split(",") if item] if missing_raw else []
    )
    return {
        "schema_version": 1,
        "workflow": "phase-3c-pre-cutover-sanity",
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "github_run_id": env.get("GITHUB_RUN_ID"),
        "github_sha": env.get("GITHUB_SHA"),
        "github_ref": env.get("GITHUB_REF"),
        "verdict": verdict,
        "step_results": steps,
        "failed_steps": failed,
        "inventory_missing": inventory_missing,
        "counts": {"green": greens, "yellow": yellows, "red": reds},
        "cross_substrate_links": {
            "cross_welle_generalprobe": "scripts/phase-3c/cross-welle-cutover-generalprobe.py",
            "marathon_aggregat_tracker": "scripts/phase-3c/marathon-aggregat-tracker.py",
            "phase_3_complete_marker": ".github/workflows/phase-3-complete-marker.yml",
            "live_vm_cutover_drill": "scripts/phase-3c/live-vm-cutover-drill.sh",
            "phase_3_final_regression_suite": "tests/e2e/test_phase_3_final_regression_suite.py",
        },
    }


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="Aggregate per-step pre-cutover-sanity results."
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the verdict-envelope JSON.",
    )
    p.add_argument(
        "--print-stdout",
        action="store_true",
        help="Also print the envelope to stdout.",
    )
    args = p.parse_args(argv[1:])

    envelope = build_envelope(os.environ)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.print_stdout:
        print(json.dumps(envelope, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
