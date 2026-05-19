#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Emit the audit-trail marker for a Phase-3-Marathon-Rollback fire.

The audit-marker is the first artifact a rollback emits, BEFORE any
per-Welle backend-switch. The marker captures the operator-intent
(actor, reason, mode, dry_run, start_at_welle) and the rollback-
cycle-id so Henrik (Internal Audit) can count attempted vs. completed
rollbacks against the ADR-0065 §Rollback-Strategie SLA budget even
if the workflow itself crashes mid-run.

Schema (v1)
-----------

  {
    "schema_version": 1,
    "kind": "marathon-rollback-audit-marker",
    "rollback_cycle_id": "rb-20260519T120000-1-abc1234",
    "actor": "<github.actor>",
    "reason": "<free-form audit text>",
    "mode": "stub" | "live",
    "dry_run": true | false,
    "start_at_welle": "all" | "w1".."w7",
    "emitted_at_utc": "2026-05-19T12:00:00+00:00",
    "anchors": {
      "adr_rollback_strategie": "decisions/0065-...",
      "adr_doppel_welle_rollback": "decisions/0066-...",
      "drill_suite": "tests/acceptance/phase_3c/rollback_drill/"
    }
  }

Hermetic
--------

stdlib only. No I/O outside the --output path.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

ANCHORS = {
    "adr_rollback_strategie": (
        "decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md"
    ),
    "adr_doppel_welle_rollback": (
        "decisions/0066-phase-3c-beschleunigung-option-a-plus.md"
    ),
    "drill_suite": "tests/acceptance/phase_3c/rollback_drill/",
}

VALID_MODES = ("stub", "live")
VALID_WELLE_GATES = ("all", "w1", "w2", "w3", "w4", "w5", "w6", "w7")


def _normalise_bool(raw: str) -> bool:
    v = (raw or "").strip().lower()
    if v in ("true", "1", "yes", "y"):
        return True
    if v in ("false", "0", "no", "n", ""):
        return False
    raise ValueError(f"cannot coerce {raw!r} to bool")


def build_marker(
    cycle_id: str,
    actor: str,
    reason: str,
    mode: str,
    dry_run: bool,
    start_at_welle: str,
) -> dict:
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode {mode!r}; expected one of {VALID_MODES}")
    if start_at_welle not in VALID_WELLE_GATES:
        raise ValueError(
            f"invalid start_at_welle {start_at_welle!r}; expected one of {VALID_WELLE_GATES}"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "marathon-rollback-audit-marker",
        "rollback_cycle_id": cycle_id,
        "actor": actor,
        "reason": reason,
        "mode": mode,
        "dry_run": dry_run,
        "start_at_welle": start_at_welle,
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "anchors": ANCHORS,
    }


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cycle-id", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--mode", required=True, choices=VALID_MODES)
    p.add_argument("--dry-run", required=True)
    p.add_argument("--start-at-welle", required=True, choices=VALID_WELLE_GATES)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv[1:])

    marker = build_marker(
        cycle_id=args.cycle_id,
        actor=args.actor,
        reason=args.reason,
        mode=args.mode,
        dry_run=_normalise_bool(args.dry_run),
        start_at_welle=args.start_at_welle,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
