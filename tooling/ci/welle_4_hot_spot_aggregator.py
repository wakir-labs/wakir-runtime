#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Welle-4 Hot-Spot Aggregator -- Tag-48 (Tomas / Henrik-Pre-Mortem-Folge).

Background
----------

Henrik's Tag-44 + Tag-45 Pre-Mortem-Mitigation-Map identifies Welle-4
(``state_backing`` in its role as the canonical persistence layer
for persona-engine durable state) as the **#2 Cross-Welle Hot-Spot**
for the KW-25..KW-27 cutover marathon.

The #1 Hot-Spot (Welle-3 ``bridge_audit_writer``) is covered by
``tooling/ci/welle_3_hot_spot_aggregator.py`` (Tag-45 PR #288). This
Welle-4 aggregator follows the same four-check pattern and emits the
same envelope shape; the welle-specific differences are documented
below.

Welle-4 hot-spot characterisation
---------------------------------

The structural risk for Welle-4 is **state_backing Persistence-Drift**:
the state_backing crate is the substrate behind the durable-state
contract of every other welle. A silent persistence-drift (e.g.
serialiser-format skew, snapshot-replay divergence, fsync-ordering
regression) cascades into Welle-5 (``lifecycle_state_machine``, which
reads/writes durable FSM state) and Welle-7 (``recovery_workflow``,
which replays state_backing snapshots).

Welle-4 audit-trail-integrity propagates downstream into Welle-5 and
Welle-7 (per Henrik Tag-44+45 Cross-Welle-Risiko-Matrix). Welle-6
(``subscribe_loop``) is structurally NATS-substrate and does NOT
depend on state_backing persistence in the cutover-window.

The four checks
---------------

* **Check 1 -- Self-Reference-Trap-Pre-Detection**: verify the
  Welle-4 cutover-smoke substrate
  (``scripts/phase-3c/welle-4-state-backing-cutover-smoke.{py,sh}``
  and the ``persona-engine-state-backing`` crate) does NOT consume
  its own emitted state-snapshot as input during the cutover-window.
  Patterns: ``replay_own_snapshot``, ``read_state_snapshot_for_self``,
  ``self_referential_persistence_loop``, ``state_backing_self_oracle``.

* **Check 2 -- state_backing-Persistence-Drift indicator**: read
  ``state/welle-4-persistence-drift.json`` (produced by the weekly
  Welle-4-validation workflow). Tri-state mirrors the
  ``persistence_drift`` field. When red, propagation block fires for
  downstream Welle-{5, 7}.

* **Check 3 -- Independent-Oracle-Probe** (Henrik Tag-38 Caution):
  cross-validate the state_backing output against
  ``doppelbetrieb-score-aggregator.py --mode=cross-modul-stress``,
  whose three axes are structurally-independent of state_backing.
  Disagreement -> red (mis-attribution risk).

* **Check 4 -- IIA-1130-Pre-Auditor-Decision-Tracking**: verify
  ``state/welle-4-pre-auditor-decision.json`` exists, parses, has
  required fields, and decision is APPROVED. Welle-4 is on Henrik's
  IIA-1130 list per Tag-45 Mitigation-Map (persistence-substrate
  has the same self-audit-conflict pattern as the audit-stream-
  substrate of Welle-3).

Decision rule + envelope schema match the Welle-3 aggregator exactly
to keep the seven aggregators interchangeable for the Tag-44 daily-
probe rollup consumer.

Hermetic posture
----------------

stdlib only. No subprocess (the caller workflow runs the upstream
substance separately and pipes status into env-vars). No network.
No file-system writes outside ``--output`` and ``--notify-out``.

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

# Downstream wellen pre-conditionally blocked by a red welle-4
# persistence-drift. Documented in Henrik Tag-44+45 Pre-Mortem
# Mitigation-Map Cross-Welle-Risiko-Matrix.
DOWNSTREAM_PROPAGATION_WELLEN = (5, 7)


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
    check2_status: str, persistence_drift: str
) -> dict | None:
    """Build the cross-welle-propagation block when applicable.

    Returns ``None`` when no propagation flag fires.
    """
    if check2_status == "red" and persistence_drift == "red":
        return {
            "trigger": "welle-4-persistence-drift-red",
            "pre_conditional_blocked": list(DOWNSTREAM_PROPAGATION_WELLEN),
            "rationale": (
                "Welle-4 state_backing persistence-drift red "
                "propagates as a pre-condition into Welle-5 and "
                "Welle-7 per Henrik Tag-44+45 Pre-Mortem "
                "Cross-Welle-Risiko-Matrix."
            ),
        }
    return None


def build_envelope(env: Mapping[str, str]) -> dict:
    """Build the verdict envelope from the four env-var inputs.

    Inputs (env-vars):
      * CHECK1_STATUS -- self-reference-trap-pre-detection.
      * CHECK2_STATUS -- state_backing-persistence-drift indicator.
      * CHECK3_STATUS -- independent-oracle-probe.
      * CHECK4_STATUS -- iia-1130-pre-auditor-decision-tracking.
      * WELLE_4_PERSISTENCE_DRIFT -- last-known persistence-drift
        state (green|yellow|red); used to decide whether the
        cross-welle-propagation block fires.
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
        "check_2_state_backing_persistence_drift": _normalise(
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
        steps["check_2_state_backing_persistence_drift"],
        _normalise(env.get("WELLE_4_PERSISTENCE_DRIFT")),
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
        "workflow": "phase-3c-welle-4-hot-spot-probe",
        "welle": 4,
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
            "welle_4_validation_workflow": (
                ".github/workflows/phase-3c-welle-4-validation.yml"
            ),
            "state_backing_crate": (
                "wirelang-rust/crates/persona-engine-state-backing"
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
            "welle_4_pre_auditor_decision_file": (
                "state/welle-4-pre-auditor-decision.json"
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
        "kind": "welle-4-hot-spot-probe",
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
            "Aggregate the four Welle-4 hot-spot indicator results "
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
