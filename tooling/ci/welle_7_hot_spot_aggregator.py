#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Welle-7 Hot-Spot Aggregator -- Tag-48 (Tomas / Henrik-Pre-Mortem-Folge).

Background
----------

Henrik's Tag-44 + Tag-45 Pre-Mortem-Mitigation-Map identifies Welle-7
(``recovery_workflow`` / ``persona-engine-recovery``+
``persona-engine-recovery-replay`` in its role as the canonical
disaster-recovery and R1..R4 replay substrate) as a **terminal
propagation-target Hot-Spot** for the KW-25..KW-27 cutover marathon.

Welle-7 is the terminal Welle in the cutover sequence; it is on the
receiving end of propagation from Welle-3, Welle-4, Welle-5, and
Welle-6. A red signal in any upstream Welle pre-conditionally blocks
Welle-7 readiness.

Welle-7 hot-spot characterisation
---------------------------------

The structural risk for Welle-7 is **Recovery-Drill-Live + IIA-1130-
Pre-Auditor-Decision-Tracking**. Two intertwined dimensions:

(a) Recovery-Drill-Live: the recovery-workflow replays the
   R1..R4 canonical traces against live state-backing snapshots. A
   drift between the canonical trace and the live replay outcome is
   the worst-case signal Henrik flagged -- it means the production
   recovery story will fail when needed. The cutover-window introduces
   a live-drill variant beyond the static R1..R4 hermetic suite.

(b) IIA-1130 Pre-Auditor: Welle-7 was the original IIA-1130 case
   (Henrik Tag-39 Welle-6+7-Pre-Audit-Bundle). The audit-stream-
   contract author cannot self-certify the recovery story; an AR-
   designated external Pre-Auditor is mandatory.

The four checks
---------------

* **Check 1 -- Self-Reference-Trap-Pre-Detection**: verify the
  Welle-7 cutover-smoke substrate
  (``scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.{py,sh}``
  and the ``persona-engine-recovery`` + ``persona-engine-recovery-
  replay`` crates) does NOT consume their own emitted recovery-trace
  as input during the cutover-window. Patterns:
  ``replay_own_recovery_trace``, ``read_recovery_emit_for_self``,
  ``self_referential_recovery_loop``, ``recovery_self_oracle``.

* **Check 2 -- Recovery-Drill-Live indicator**: read
  ``state/welle-7-recovery-drill-live.json`` (produced by the weekly
  Welle-7-validation workflow's live-R1..R4-drill step). The schema
  field ``recovery_drill_status`` maps to the tri-state. Welle-7 has
  NO downstream propagation block (terminal Welle); a red Check-2
  blocks Welle-7 itself but cascades nowhere else.

* **Check 3 -- Independent-Oracle-Probe** (Henrik Tag-38 Caution):
  cross-validate the recovery-workflow output against
  ``doppelbetrieb-score-aggregator.py --mode=cross-modul-stress``.
  Disagreement -> red (mis-attribution risk).

* **Check 4 -- IIA-1130-Pre-Auditor-Decision-Tracking**: verify
  ``state/welle-7-pre-auditor-decision.json`` exists, parses, has
  required fields, and decision is APPROVED. Welle-7 is the ORIGINAL
  IIA-1130 case per Tag-39 Henrik-Bundle. Until the AR designates
  the external Pre-Auditor, this check is yellow (PENDING) by design.

Decision rule + envelope schema match the Welle-3 aggregator exactly
to keep the seven aggregators interchangeable for the Tag-44 daily-
probe rollup consumer.

Terminal-Welle propagation note
-------------------------------

Unlike Welle-3/4/5/6 aggregators, Welle-7 has an EMPTY
``DOWNSTREAM_PROPAGATION_WELLEN`` tuple. The
``cross_welle_propagation`` block therefore never fires from this
aggregator's perspective. The envelope still includes the field
(set to ``null``) to keep the schema identical to the upstream
aggregators -- callers must not rely on its presence to detect
propagation; they must check the ``trigger`` field.

Hermetic posture
----------------

stdlib only. No subprocess (the caller workflow runs the upstream
substance separately and pipes status into env-vars). No network.
No file-system writes outside ``--output`` and ``--notify-out``.

Exit code: always 0.
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

# Welle-7 is the terminal Welle; no downstream propagation.
# Constant kept for schema-symmetry with the upstream aggregators.
DOWNSTREAM_PROPAGATION_WELLEN: tuple[int, ...] = ()


def _normalise(raw: str | None) -> str:
    """Coerce an env-var value to a known tri-state status.

    Empty / unset / unknown -> ``red`` (loud-failure mode).
    """
    if raw is None:
        return "red"
    v = raw.strip().lower()
    if v in VALID_STATUSES:
        return v
    return "red"


def decide(steps: Mapping[str, str]) -> str:
    """Pure decision-rule -- see module docstring for the truth-table."""
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
        return "CLEAR"
    return "BLOCK"


def _propagation_block(
    check2_status: str, recovery_drill_live: str
) -> dict | None:
    """Build the cross-welle-propagation block when applicable.

    Welle-7 is terminal -- propagation never fires from here. Returns
    ``None`` always.
    """
    # Welle-7 is the terminal welle; explicit no-op for schema symmetry.
    return None


def build_envelope(env: Mapping[str, str]) -> dict:
    """Build the verdict envelope from the four env-var inputs.

    Inputs (env-vars):
      * CHECK1_STATUS -- self-reference-trap-pre-detection.
      * CHECK2_STATUS -- Recovery-Drill-Live indicator.
      * CHECK3_STATUS -- independent-oracle-probe.
      * CHECK4_STATUS -- iia-1130-pre-auditor-decision-tracking.
      * WELLE_7_RECOVERY_DRILL_LIVE -- last-known recovery-drill-live
        state (green|yellow|red); recorded on the envelope. Welle-7
        is terminal -- no propagation fires.
      * INDEPENDENT_ORACLE_DISAGREEMENTS -- comma-separated list of
        axis-names where the two oracles disagreed; recorded on the
        envelope for forensic traceability.
      * PRE_AUDITOR_STATE -- one of ``present|pending|missing``;
        recorded on the envelope as the IIA-1130 status detail.
    """
    steps = {
        "check_1_self_reference_trap_pre_detection": _normalise(
            env.get("CHECK1_STATUS")
        ),
        "check_2_recovery_drill_live": _normalise(env.get("CHECK2_STATUS")),
        "check_3_independent_oracle_probe": _normalise(env.get("CHECK3_STATUS")),
        "check_4_iia_1130_pre_auditor_decision": _normalise(
            env.get("CHECK4_STATUS")
        ),
    }
    reds = sum(1 for v in steps.values() if v == "red")
    yellows = sum(1 for v in steps.values() if v == "yellow")
    greens = sum(1 for v in steps.values() if v == "green")
    verdict = decide(steps)
    failed = [k for k, v in steps.items() if v != "green"]

    propagation = _propagation_block(
        steps["check_2_recovery_drill_live"],
        _normalise(env.get("WELLE_7_RECOVERY_DRILL_LIVE")),
    )

    disagreements_raw = env.get("INDEPENDENT_ORACLE_DISAGREEMENTS", "") or ""
    disagreements = [
        item for item in disagreements_raw.split(",") if item
    ]

    pre_auditor_state = (env.get("PRE_AUDITOR_STATE") or "missing").strip().lower()
    if pre_auditor_state not in ("present", "pending", "missing"):
        pre_auditor_state = "missing"

    envelope = {
        "schema_version": 1,
        "workflow": "phase-3c-welle-7-hot-spot-probe",
        "welle": 7,
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "github_run_id": env.get("GITHUB_RUN_ID"),
        "github_sha": env.get("GITHUB_SHA"),
        "github_ref": env.get("GITHUB_REF"),
        "verdict": verdict,
        "check_results": steps,
        "failed_checks": failed,
        "counts": {"green": greens, "yellow": yellows, "red": reds},
        "independent_oracle_disagreements": disagreements,
        "pre_auditor_state": pre_auditor_state,
        "cross_welle_propagation": propagation,
        "cross_substrate_links": {
            "welle_7_validation_workflow": (
                ".github/workflows/phase-3c-welle-7-validation.yml"
            ),
            "recovery_crate": (
                "wirelang-rust/crates/persona-engine-recovery"
            ),
            "recovery_replay_crate": (
                "wirelang-rust/crates/persona-engine-recovery-replay"
            ),
            "doppelbetrieb_score_aggregator": (
                "scripts/doppelbetrieb-score-aggregator.py"
            ),
            "henrik_pre_mortem_inbox": (
                "agents-workspaces/mira/inbox/"
                "2026-05-18-henrik-tag-44-pre-mortem-done.md"
            ),
            "henrik_mitigation_map_inbox": (
                "agents-workspaces/mira/inbox/"
                "2026-05-18-henrik-tag-45-mitigation-map-done.md"
            ),
            "welle_7_pre_auditor_decision_file": (
                "state/welle-7-pre-auditor-decision.json"
            ),
        },
    }
    return envelope


def _emit_notify_event(
    envelope: dict, notify_path: Path, prev_verdict: str | None
) -> bool:
    """Append a notify-event JSON-line when warranted.

    A notify-event fires when:
      * verdict is BLOCK (always notify, every run -- forensic trail).
      * verdict is CAUTION AND prev_verdict != "CAUTION" (transition).

    Returns True if a line was appended, False otherwise.
    """
    verdict = envelope["verdict"]
    if verdict == "CLEAR":
        return False
    if verdict == "CAUTION" and prev_verdict == "CAUTION":
        return False
    event = {
        "schema_version": 1,
        "kind": "welle-7-hot-spot-probe",
        "emitted_at_utc": envelope["emitted_at_utc"],
        "verdict": verdict,
        "failed_checks": envelope["failed_checks"],
        "cross_welle_propagation": envelope.get("cross_welle_propagation"),
        "github_run_id": envelope.get("github_run_id"),
        "github_sha": envelope.get("github_sha"),
    }
    notify_path.parent.mkdir(parents=True, exist_ok=True)
    with notify_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")
    return True


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description=(
            "Aggregate the four Welle-7 hot-spot indicator results "
            "into a single verdict envelope."
        )
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the verdict-envelope JSON.",
    )
    p.add_argument(
        "--notify-out",
        type=Path,
        default=None,
        help=(
            "Optional path for append-mode notify-events.jsonl. "
            "When verdict is BLOCK or CAUTION (and the previous "
            "verdict differs), one JSON-line event is appended."
        ),
    )
    p.add_argument(
        "--prev-verdict",
        default=None,
        help=(
            "Previous run's verdict (CLEAR|CAUTION|BLOCK) for the "
            "notify-event transition rule. Optional; default None."
        ),
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
        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if args.notify_out is not None:
        _emit_notify_event(envelope, args.notify_out, args.prev_verdict)

    if args.print_stdout:
        print(json.dumps(envelope, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
