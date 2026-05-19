#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Aggregate per-Welle rollback envelopes into a single rollback-run
manifest for the Phase-3-Marathon-Rollback workflow (Tag-56).

The J10 aggregator job in ``phase-3-marathon-rollback.yml`` collects
the seven per-Welle envelope-statuses and notes via env-vars and
calls this helper to compute the verdict + manifest envelope.

Verdict rule
------------

Each Welle's status is one of ``{green, yellow, red, skipped}``.

* ``READY``   - every executed Welle green; zero red, zero yellow.
                Skipped Wellen (start_at_welle != 'all') do not
                count against READY as long as the executed subset
                is fully green.
* ``PARTIAL`` - any yellow OR skipped Welle while another Welle is
                red or yellow. The system is mid-state; operator-
                hand intervention required. Note that allow_partial
                _rollback=true can produce PARTIAL even from skipped
                downstream Wellen.
* ``FAILED``  - any executed Welle red. The rollback orchestration
                broke; operator-hand intervention required.

Schema (v1)
-----------

  {
    "schema_version": 1,
    "kind": "marathon-rollback-manifest",
    "rollback_cycle_id": "rb-...",
    "actor": "<github.actor>",
    "reason": "<free-form audit text>",
    "mode": "stub" | "live",
    "dry_run": true | false,
    "start_at_welle": "all" | "w1".."w7",
    "allow_partial_rollback": true | false,
    "verdict": "READY" | "PARTIAL" | "FAILED",
    "welle_results": {"w7": "green", "w6": "green", ...},
    "welle_notes": [...],
    "counts": {"green": N, "yellow": N, "red": N, "skipped": N},
    "snapshot_restore_status": "planned" | "n/a" | "missing",
    "anchors": {...},
    "emitted_at_utc": "..."
  }

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

VALID_STATUSES = ("green", "yellow", "red", "skipped")

# Reverse-cutover-order: rollback walks W7 -> W6 -> ... -> W1.
WELLE_ORDER = ("w7", "w6", "w5", "w4", "w3", "w2", "w1")

WELLE_MODUL_MAP = {
    "w7": "recovery_workflow",
    "w6": "subscribe_loop",
    "w5": "lifecycle_state_machine",
    "w4": "state_backing",
    "w3": "bridge_audit_writer",
    "w2": "svid_workload_identity",
    "w1": "v907_verify",
}

ANCHORS = {
    "adr_rollback_strategie": (
        "decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md"
    ),
    "adr_doppel_welle_rollback": (
        "decisions/0066-phase-3c-beschleunigung-option-a-plus.md"
    ),
    "drill_suite": "tests/acceptance/phase_3c/rollback_drill/",
    "workflow": ".github/workflows/phase-3-marathon-rollback.yml",
    "runbook": "docs/ci/phase-3-marathon-rollback-runbook.md",
}


def _normalise_status(raw: str | None) -> str:
    if raw is None:
        return "skipped"
    v = raw.strip().lower()
    if v in VALID_STATUSES:
        return v
    if v == "" or v == "null":
        return "skipped"
    # Unknown values treated as red (loud failure mode).
    return "red"


def _normalise_bool(raw: str | None) -> bool:
    if raw is None:
        return False
    v = raw.strip().lower()
    return v in ("true", "1", "yes", "y")


def decide(welle_results: Mapping[str, str]) -> str:
    reds = sum(1 for v in welle_results.values() if v == "red")
    yellows = sum(1 for v in welle_results.values() if v == "yellow")
    greens = sum(1 for v in welle_results.values() if v == "green")
    skipped = sum(1 for v in welle_results.values() if v == "skipped")
    if reds >= 1:
        return "FAILED"
    # When every Welle is either green or skipped (and at least one
    # green), the executed subset rolled back cleanly. READY.
    if yellows == 0 and reds == 0 and greens >= 1:
        return "READY"
    # Only-skipped: no rollback happened at all. Not a useful
    # READY signal — treat as PARTIAL (operator should investigate).
    if greens == 0 and yellows == 0 and skipped == len(welle_results):
        return "PARTIAL"
    if yellows >= 1:
        return "PARTIAL"
    return "PARTIAL"


def derive_snapshot_restore_status(
    welle_results: Mapping[str, str], start_at_welle: str
) -> str:
    """Welle-4 (state_backing) is the only Welle that needs a
    snapshot-restore. Track the field here so the AR-Hand-notify
    job can surface it as a top-level status signal.
    """
    w4 = welle_results.get("w4", "skipped")
    if w4 == "skipped":
        return "n/a"
    if w4 == "green":
        return "planned"
    if w4 == "yellow":
        return "missing"
    return "missing"


def build_manifest(env: Mapping[str, str]) -> dict:
    welle_results = {
        w: _normalise_status(env.get(f"{w.upper()}_STATUS")) for w in WELLE_ORDER
    }
    notes_raw = env.get("WELLE_NOTES", "") or ""
    welle_notes = [n for n in notes_raw.split(";") if n]
    verdict = decide(welle_results)
    counts = {
        "green": sum(1 for v in welle_results.values() if v == "green"),
        "yellow": sum(1 for v in welle_results.values() if v == "yellow"),
        "red": sum(1 for v in welle_results.values() if v == "red"),
        "skipped": sum(1 for v in welle_results.values() if v == "skipped"),
    }
    start_at_welle = env.get("START_AT_WELLE", "all")
    snapshot_restore = derive_snapshot_restore_status(welle_results, start_at_welle)
    return {
        "schema_version": 1,
        "kind": "marathon-rollback-manifest",
        "rollback_cycle_id": env.get("ROLLBACK_CYCLE_ID"),
        "actor": env.get("ACTOR"),
        "reason": env.get("REASON"),
        "mode": env.get("MODE", "stub"),
        "dry_run": _normalise_bool(env.get("DRY_RUN", "true")),
        "start_at_welle": start_at_welle,
        "allow_partial_rollback": _normalise_bool(env.get("ALLOW_PARTIAL", "false")),
        "verdict": verdict,
        "welle_results": welle_results,
        "welle_modul_map": WELLE_MODUL_MAP,
        "welle_notes": welle_notes,
        "counts": counts,
        "snapshot_restore_status": snapshot_restore,
        "decision_rule": {
            "ready": "every executed Welle green; zero red, zero yellow",
            "partial": "any yellow OR only-skipped run; operator-hand follow-up required",
            "failed": "any executed Welle red",
        },
        "anchors": ANCHORS,
        "github_run_id": env.get("GITHUB_RUN_ID"),
        "github_sha": env.get("GITHUB_SHA"),
        "github_ref": env.get("GITHUB_REF"),
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--print-stdout", action="store_true")
    args = p.parse_args(argv[1:])

    manifest = build_manifest(os.environ)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.print_stdout:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
