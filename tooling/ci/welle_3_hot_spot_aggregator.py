#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Welle-3 Hot-Spot Aggregator -- Tag-45 (Tomas / Henrik-Pre-Mortem-Folge).

Background
----------

Henrik's Tag-44 Pre-Mortem identifies Welle-3 (``bridge_audit_writer``
in its role as audit-stream-emitting oracle) as the #1 Cross-Welle
Hot-Spot for the KW-25..KW-27 cutover marathon. The Welle-3 audit-
trail-integrity status propagates downstream into Welle-4
(``state_backing``), Welle-5 (``lifecycle_state_machine``), and
Welle-7 (``recovery_workflow``) -- a red signal in Welle-3 must
pre-conditionally block the readiness of those three downstream
Wellen.

This aggregator runs the four Welle-3-specific hot-spot indicators
documented in ``docs/ci/welle-3-hot-spot-probe-runbook.md`` and
emits a single JSON verdict envelope that the driving workflow
(``.github/workflows/phase-3c-welle-3-hot-spot-probe.yml``)
converts to GitHub-Actions Job-Summary + notify-events feed.

The four checks
---------------

* **Check 1 -- Self-Reference-Trap-Pre-Detection** (Henrik Tag-39
  audit-loop hypothesis): verify the
  ``welle-3-bridge-audit-writer-cutover-smoke`` substrate does NOT
  consume its own emitted audit-stream as input -- otherwise the
  cutover-window opens a self-referencing audit-loop where the
  writer signs off on its own correctness. The probe scans the
  smoke-script + the Rust persona-engine-bridge-audit-writer crate
  for ``read_audit_stream`` / ``replay_own_emit`` patterns inside
  the cutover-window-marker block.

* **Check 2 -- Cross-Welle-Propagation-Risk-Indikator**: read the
  most recent Welle-3 audit-trail-integrity verdict from
  ``state/welle-3-audit-trail-integrity.json`` (produced by the
  weekly Welle-3-validation workflow). If red -> emit a propagation
  flag listing Welle-4 / Welle-5 / Welle-7 as
  ``pre_conditional_blocked``. The flag is data-only; the actual
  blocking happens in the downstream-Welle workflows that consume
  this aggregator's verdict.

* **Check 3 -- Independent-Oracle-Probe** (Henrik Tag-38 Caution):
  cross-validate the bridge-audit-writer output against the
  Phase-2-Acceptance-Gate cross-modul-stress aggregator. The
  ``doppelbetrieb-score-aggregator`` in ``--mode=cross-modul-stress``
  emits a structurally-independent rollup (cross-lang-pin-coverage,
  cross-modul-fixture-stability, cross-modul-rollup-integrity) that
  does NOT use bridge_audit_writer as oracle. If both oracles agree
  on the writer's health -> green; if they disagree -> red
  (mis-attribution risk).

* **Check 4 -- IIA-1130-Pre-Auditor-Decision-Tracking**: verify
  that an IIA-1130 Pre-Auditor-Decision file exists at
  ``state/welle-3-pre-auditor-decision.json`` (analog to the
  Welle-7 pattern from Tag-39 Henrik-Bundle). Welle-3 is one of
  the two Wellen where Henrik (Internal Audit) cannot sign-off
  himself because he is the substrate-author of the audit-stream
  hash contract; an AR-designated external Pre-Auditor is required.
  Until the AR designates one, this check is yellow (PENDING) by
  design.

Decision rule
-------------

For the four tri-state inputs ({green, yellow, red}):

* ``CLEAR``  -- all four green.
* ``CAUTION`` -- exactly one yellow, the other three green.
  No reds.
* ``BLOCK``  -- any red, OR two or more yellows.

Empty / missing env-vars default to ``red`` (loud-failure mode --
we assume the upstream check job did not run at all).

Cross-Welle-Propagation
-----------------------

When ``CHECK2_STATUS == red`` AND the input env-var
``WELLE_3_AUDIT_TRAIL_INTEGRITY`` reads ``red``, the verdict envelope
includes a ``cross_welle_propagation`` block listing the affected
downstream Wellen [4, 5, 7] as ``pre_conditional_blocked``. The
envelope's verdict is BLOCK in this case regardless of the other
three checks (audit-trail-integrity is a hard pre-condition).

Hermetic posture
----------------

stdlib only. No subprocess (the caller workflow runs the upstream
substance separately and pipes status into env-vars). No network.
No file-system writes outside ``--output`` and ``--notify-out``.

Output
------

* ``--output PATH`` -- write the verdict envelope JSON.
* ``--notify-out PATH`` -- when verdict is BLOCK or CAUTION (and the
  verdict differs from the previous-day's state, when known), append
  one JSON-line notify-event to this path. Append-mode; the file is
  the canonical notify-events.jsonl feed consumed by the
  Mira-Hand-Sichtung step in the driving workflow.

Exit code: always 0 (the verdict-envelope's ``verdict`` field carries
the BLOCK/CAUTION/CLEAR signal; the calling workflow translates that
to step-exit semantics).
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

# Downstream wellen pre-conditionally blocked by a red welle-3
# audit-trail-integrity. Documented in Henrik Tag-44 Pre-Mortem
# §Cross-Welle-Risiko-Matrix.
DOWNSTREAM_PROPAGATION_WELLEN = (4, 5, 7)


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
    check2_status: str, audit_trail_integrity: str
) -> dict | None:
    """Build the cross-welle-propagation block when applicable.

    Returns ``None`` when no propagation flag fires.
    """
    if check2_status == "red" and audit_trail_integrity == "red":
        return {
            "trigger": "welle-3-audit-trail-integrity-red",
            "pre_conditional_blocked": list(DOWNSTREAM_PROPAGATION_WELLEN),
            "rationale": (
                "Welle-3 bridge-audit-writer audit-trail-integrity "
                "red propagates as a pre-condition into Welle-4 / "
                "Welle-5 / Welle-7 per Henrik Tag-44 Pre-Mortem "
                "Cross-Welle-Risiko-Matrix."
            ),
        }
    return None


def build_envelope(env: Mapping[str, str]) -> dict:
    """Build the verdict envelope from the four env-var inputs.

    Inputs (env-vars):
      * CHECK1_STATUS -- self-reference-trap-pre-detection.
      * CHECK2_STATUS -- cross-welle-propagation-risk-indikator.
      * CHECK3_STATUS -- independent-oracle-probe.
      * CHECK4_STATUS -- iia-1130-pre-auditor-decision-tracking.
      * WELLE_3_AUDIT_TRAIL_INTEGRITY -- last-known audit-trail-
        integrity state (green|yellow|red); used to decide whether
        the cross-welle-propagation block fires.
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
        "check_2_cross_welle_propagation_risk": _normalise(
            env.get("CHECK2_STATUS")
        ),
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
        steps["check_2_cross_welle_propagation_risk"],
        _normalise(env.get("WELLE_3_AUDIT_TRAIL_INTEGRITY")),
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
        "workflow": "phase-3c-welle-3-hot-spot-probe",
        "welle": 3,
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
            "welle_3_validation_workflow": (
                ".github/workflows/phase-3c-welle-3-validation.yml"
            ),
            "bridge_audit_writer_runbook": (
                "docs/phase-3c/welle-3-bridge-audit-writer-runbook.md"
            ),
            "doppelbetrieb_score_aggregator": (
                "scripts/doppelbetrieb-score-aggregator.py"
            ),
            "henrik_pre_mortem_inbox": (
                "agents-workspaces/mira/inbox/"
                "2026-05-18-henrik-tag-44-pre-mortem-done.md"
            ),
            "welle_3_pre_auditor_decision_file": (
                "state/welle-3-pre-auditor-decision.json"
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
        # Already-stable CAUTION; don't spam notify on every run.
        return False
    event = {
        "schema_version": 1,
        "kind": "welle-3-hot-spot-probe",
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
            "Aggregate the four Welle-3 hot-spot indicator results "
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
