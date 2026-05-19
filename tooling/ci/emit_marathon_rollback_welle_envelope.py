#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Emit a per-Welle rollback envelope for the Phase-3-Marathon-
Rollback workflow.

Each per-Welle job in ``phase-3-marathon-rollback.yml`` calls this
helper to write a deterministic envelope file. The aggregator
(``aggregate_marathon_rollback_manifest.py``) reads the seven
envelopes (Welle-1..Welle-7) and stitches them into a single
rollback-run manifest.

Schema (v1)
-----------

  {
    "schema_version": 1,
    "kind": "marathon-rollback-welle-envelope",
    "welle": 4,
    "modul": "state_backing",
    "rollback_cycle_id": "rb-...",
    "mode": "stub" | "live",
    "dry_run": true | false,
    "status": "green" | "yellow" | "red",
    "note": "<short diagnostic>",
    "target_backend": "python",
    "with_snapshot_restore": true | false,
    "snapshot_restore_planned": true | false,
    "anchors": {
      "rollback_drill_test": "tests/acceptance/phase_3c/rollback_drill/test_rollback_drill_<modul>.py"
    },
    "emitted_at_utc": "..."
  }

Status semantics
----------------

* ``green`` — stub-mode dry_run completes; planned action is well-
  formed; envelope is ready for aggregator consumption.
* ``yellow`` — stub-mode dry_run completes but with a documented
  caveat (e.g. live-mode flag set in stub-mode dry-run: refuses to
  cross-mode-leak).
* ``red`` — stub-mode dry_run could not even plan the action (e.g.
  unknown modul, invalid welle-id).

Stub-mode posture
-----------------

The envelope NEVER actually flips a Quadlet-ENV-Flag. It only
records the planned action. Live-mode is reserved for the operator-
hand fire on the Pilot-VM box and goes through a different code-
path (NOT this script). This file is the CI-hermetic stub.

Hermetic
--------

stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

VALID_MODES = ("stub", "live")
VALID_WELLEN = (1, 2, 3, 4, 5, 6, 7)

# Canonical Welle <-> Modul binding from ADR-0065 §Verifikations-Plan +
# the rollback-drill conftest inventory.
WELLE_MODUL_MAP = {
    1: "v907_verify",
    2: "svid_workload_identity",
    3: "bridge_audit_writer",
    4: "state_backing",
    5: "lifecycle_state_machine",
    6: "subscribe_loop",
    7: "recovery_workflow",
}


def _normalise_bool(raw: str) -> bool:
    v = (raw or "").strip().lower()
    if v in ("true", "1", "yes", "y"):
        return True
    if v in ("false", "0", "no", "n", ""):
        return False
    raise ValueError(f"cannot coerce {raw!r} to bool")


def build_envelope(
    welle: int,
    modul: str,
    cycle_id: str,
    mode: str,
    dry_run: bool,
    with_snapshot_restore: bool,
) -> dict:
    if welle not in VALID_WELLEN:
        raise ValueError(f"invalid welle {welle!r}; expected one of {VALID_WELLEN}")
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode {mode!r}; expected one of {VALID_MODES}")
    expected_modul = WELLE_MODUL_MAP[welle]
    if modul != expected_modul:
        # Hard fail: a drifted welle<->modul binding would silently
        # rollback the wrong component. Emit red status with a clear
        # note so the aggregator can BLOCK the whole run.
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "marathon-rollback-welle-envelope",
            "welle": welle,
            "modul": modul,
            "rollback_cycle_id": cycle_id,
            "mode": mode,
            "dry_run": dry_run,
            "status": "red",
            "note": (
                f"welle<->modul binding drift: expected {expected_modul!r} "
                f"for welle-{welle}, got {modul!r}"
            ),
            "target_backend": None,
            "with_snapshot_restore": with_snapshot_restore,
            "snapshot_restore_planned": False,
            "anchors": {
                "rollback_drill_test": (
                    "tests/acceptance/phase_3c/rollback_drill/"
                    f"test_rollback_drill_{expected_modul}.py"
                )
            },
            "emitted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    # Welle-4 (state_backing) is the only Welle that requires a
    # snapshot-restore in addition to the ENV-Flag-Switch. If the
    # workflow forgot to pass --with-snapshot-restore=true for
    # Welle-4, emit yellow with a clear note (CAUTION-path).
    snapshot_restore_planned = with_snapshot_restore
    status = "green"
    note = ""
    if welle == 4 and not with_snapshot_restore:
        status = "yellow"
        note = "Welle-4 rollback requires --with-snapshot-restore=true (state_backing)"
    elif welle != 4 and with_snapshot_restore:
        status = "yellow"
        note = (
            f"--with-snapshot-restore=true set for welle-{welle} ({modul}); "
            "only Welle-4 (state_backing) consumes this flag"
        )
        snapshot_restore_planned = False
    # Live-mode in CI hermetic env is documented yellow — the
    # workflow's J1 guard refuses live-mode on ubuntu-latest, but
    # the envelope still records the intent.
    if mode == "live":
        status = "yellow" if status == "green" else status
        if not note:
            note = "live-mode envelope emitted; J1 guard refuses execution on non-self-hosted runner"

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "marathon-rollback-welle-envelope",
        "welle": welle,
        "modul": modul,
        "rollback_cycle_id": cycle_id,
        "mode": mode,
        "dry_run": dry_run,
        "status": status,
        "note": note,
        "target_backend": "python",
        "with_snapshot_restore": with_snapshot_restore,
        "snapshot_restore_planned": snapshot_restore_planned,
        "anchors": {
            "rollback_drill_test": (
                "tests/acceptance/phase_3c/rollback_drill/"
                f"test_rollback_drill_{modul}.py"
            )
        },
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--welle", type=int, required=True, choices=list(VALID_WELLEN))
    p.add_argument("--modul", required=True)
    p.add_argument("--cycle-id", required=True)
    p.add_argument("--mode", required=True, choices=VALID_MODES)
    p.add_argument("--dry-run", required=True)
    p.add_argument(
        "--with-snapshot-restore",
        default="false",
        help="Welle-4-only flag; emits snapshot-restore-planned field",
    )
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv[1:])

    envelope = build_envelope(
        welle=args.welle,
        modul=args.modul,
        cycle_id=args.cycle_id,
        mode=args.mode,
        dry_run=_normalise_bool(args.dry_run),
        with_snapshot_restore=_normalise_bool(args.with_snapshot_restore),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
