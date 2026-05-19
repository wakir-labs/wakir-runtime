#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-78 Marathon-Final-Smoke Stability-Window aggregator (Amara).

Purpose
-------

The Tag-78 Marathon-Final-Smoke Stability-Window-Probe answers the
question: "if we were to run the Tag-77 Marathon-Final-Smoke-E2E
aggregator (PR #489, eleven-stage umbrella over Tag-69..Tag-76)
three times back-to-back on the current main-tip, would all three
runs return ``MARATHON-FINAL-INTACT``?" If yes, the operator has a
defensible signal that the Phase-3-Marathon-Polish substrate is
stable across consecutive invocations -- the precondition for
treating the Tag-77 umbrella as a reliable Pre-Cutover-Pre-Run
signal in the run-up to the Tag-79 Marathon-Final-Acceptance-
Sign-Off gate.

The probe is informational. The actual Cutover-Wednesday Welle-N
dispatch on 2026-06-10 / 06-17 / 06-24 / 07-01 remains operator-
hand. This probe just provides the Stability-Window-CONFIRMED
checkpoint that mirrors the Tag-63/65/69 pattern at the Marathon-
Umbrella level.

Anchor pattern
--------------

Tag-59 OTS N-Run-Pattern (3 consecutive runs)
  -> Tag-63 REUSE-Wrap Stability-Window-Probe (PR #404, Tomas)
  -> Tag-65 E2E-Smoke Stability-Window-Probe (Amara)
  -> Tag-69 Live-Smoke Stability-Window-Probe (Noa)
  -> Tag-78 Marathon-Final-Smoke Stability-Window-Probe
     (this aggregator, Amara).

All five share the trinary verdict shape (CONFIRMED / NOT-YET /
DEFECT) and the same "informational, not Required-Status-Check"
posture. The probe's own job-step exits non-zero only on DEFECT
(probe-substrate broken); NOT-YET is a green-step + verdict-as-
payload signal.

Trinary stability-window verdict
--------------------------------

* ``STABILITY-WINDOW-CONFIRMED``
    all N runs returned ``MARATHON-FINAL-INTACT``. The Tag-77
    umbrella aggregator is deterministically green-given-green-
    input across consecutive invocations; the operator may treat
    the umbrella as a reliable Pre-Cutover-Pre-Run signal.

* ``STABILITY-WINDOW-NOT-YET``
    at least one run returned ``MARATHON-FINAL-DRIFT`` (1+ yellow,
    0 red across the ten upstream substrate inputs) or
    ``MARATHON-FINAL-DEFECT`` (1+ red OR envelope missing), but no
    run crashed the probe substrate. Operator inspects the failing
    run, does not promote the umbrella to "reliable".

* ``STABILITY-WINDOW-DEFECT``
    at least one run produced a non-parseable verdict (missing
    envelope, malformed JSON, unknown verdict-string) or the
    probe substrate itself crashed. Operator files a bug; this
    is a defect in the stability-window-probe, not in the Tag-77
    Marathon-Final-Smoke aggregator.

Decision rule
-------------

The decision rule is deliberately stricter than the Tag-77
umbrella's own rule. The Tag-77 umbrella allows
``MARATHON-FINAL-DRIFT`` (1+ stage yellow) as an informational
degradation -- the operator reads per-stage notes and proceeds
with eyes open. The Tag-78 Stability-Window-Probe requires
``MARATHON-FINAL-INTACT`` (all ten upstream stages green) on
every consecutive run -- because the question being asked is
"is the umbrella substrate stable enough to use as a Pre-Cutover
Pre-Run signal?" Anything less than three-in-a-row INTACT is a
NOT-YET signal.

Empty / missing per-run envelopes default to ``defect``.

Exit code
---------

Always ``0`` unless ``STABILITY-WINDOW-DEFECT`` (non-zero only if
the probe substrate itself is broken). The verdict-envelope's
``verdict`` field carries CONFIRMED/NOT-YET/DEFECT.

Hermetic
--------

Stdlib only. No third-party imports. No subprocess invocations
into the aggregator from inside this helper (the calling workflow
performs the per-run aggregator invocations and feeds the result
back via env-vars). No filesystem-state mutation outside ``--output``.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This aggregator pins the Tag-78 Marathon-Final-Smoke-Stability-
Window-Probe surface. It does NOT modify the underlying Tag-77
Marathon-Final-Smoke aggregator (PR #489, Amara), the Tag-76
Cross-Welle-Stability-Pin (PR #483, Amara), the Tag-76 Marathon-
Closeout-Aggregator (PR #479, Reza), the Tag-76 Phase-3-COMPLETE-
Marker-Audit-Bundle (PR #484, Tomas), persona definitions (Aisha-
Domaene), WAT-core / V-907 logic (Tomas-Domaene, Zone-K),
identity-substrate (Reza-Domaene, Zone-L), container-infra (Kai-
Domaene, Zone-J), or persona-engine substrate (Selin-Domaene,
Zone-O).

Cross-review-markers:

* Zone-M: Stability-Window-Probe walks the Tag-77 Marathon-Final-
  Smoke aggregator owned by Amara herself; the probe depends on
  the Tag-77 verdict-envelope shape but does not modify the
  Tag-77 aggregator. Cross-component because the Tag-77 umbrella
  consumes ten substrate envelopes owned by Amara + Reza + Tomas
  (+ audit-anchor stand-ins from Tomas+Selin for Welle-1/2).
* Zone-N: Henrik (Internal Audit) consumes the Stability-Window
  verdict as audit-evidence-input for the Phase-3-Marathon-
  Polish-Phase Pre-Cutover-Readiness claim. Drift in the
  decision-rule is a Zone-N signal.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


# Valid verdicts emitted by the underlying Tag-77 Marathon-Final-
# Smoke aggregator (aggregate_marathon_final_smoke.py,
# VERDICT_INTACT / VERDICT_DRIFT / VERDICT_DEFECT). Anything else
# collapses to defect.
VALID_MARATHON_FINAL_VERDICTS: tuple[str, ...] = (
    "MARATHON-FINAL-INTACT",
    "MARATHON-FINAL-DRIFT",
    "MARATHON-FINAL-DEFECT",
)


# Per-run status categories for stability-window classification.
PER_RUN_STATUSES: tuple[str, ...] = ("ready", "not-ready", "defect")


# Trinary stability-window verdict labels.
VERDICT_CONFIRMED: str = "STABILITY-WINDOW-CONFIRMED"
VERDICT_NOT_YET: str = "STABILITY-WINDOW-NOT-YET"
VERDICT_DEFECT: str = "STABILITY-WINDOW-DEFECT"


# Cross-substrate links. Recorded on the envelope so an artifact-
# only consumer (Henrik-Audit-sample, AR-Hand summary, Phase-3-
# Marathon-Polish-Phase Pre-Cutover-Readiness summariser) does not
# have to re-resolve paths.
CROSS_SUBSTRATE_LINKS: dict[str, str] = {
    "marathon_final_smoke_aggregator": (
        "tooling/ci/aggregate_marathon_final_smoke.py"
    ),
    "marathon_final_smoke_workflow": (
        ".github/workflows/marathon-final-smoke-e2e.yml"
    ),
    "stability_window_probe_workflow": (
        ".github/workflows/marathon-final-stability-window-probe.yml"
    ),
    "reuse_wrap_stability_window_anchor": (
        ".github/workflows/"
        "reuse-wrap-enforce-flip-stability-window-probe.yml"
    ),
    "e2e_smoke_stability_window_anchor": (
        ".github/workflows/e2e-smoke-stability-window-probe.yml"
    ),
    "live_smoke_stability_window_anchor": (
        ".github/workflows/live-smoke-stability-window-probe.yml"
    ),
    "cross_welle_stability_pin_anchor": (
        "tooling/ci/aggregate_cross_welle_stability.py"
    ),
    "marathon_closeout_aggregator_anchor": (
        "tooling/audit/verify_marathon_closeout.py"
    ),
    "phase_3_complete_marker_audit_bundle_anchor": (
        "tooling/ci/wire_phase_3_complete_audit_bundle.py"
    ),
    "pre_cutover_run_order_doc": (
        "docs/quality-gates/pre-cutover-acceptance-run-order.md"
    ),
}


# Pattern lineage. Recorded on the envelope as audit-evidence-input.
PATTERN_LINEAGE: dict[str, str] = {
    "n_run_pattern": "Tag-59 OTS N-Run Pattern (3 consecutive runs)",
    "reuse_wrap_anchor": "Tag-63 PR #404 (Tomas)",
    "e2e_smoke_anchor": "Tag-65 (Amara)",
    "live_smoke_anchor": "Tag-69 (Noa)",
    "marathon_final_smoke_anchor": "Tag-77 PR #489 (Amara)",
    "current_owner": "Tag-78 Amara (this aggregator)",
}


def _classify_marathon_final_verdict(verdict: str | None) -> str:
    """Map a Tag-77 Marathon-Final-Smoke verdict-string to a category.

    * ``MARATHON-FINAL-INTACT``  -> ``ready``
    * ``MARATHON-FINAL-DRIFT``   -> ``not-ready`` (1+ yellow upstream)
    * ``MARATHON-FINAL-DEFECT``  -> ``not-ready`` (red upstream)
    * anything else              -> ``defect`` (probe substrate broken)

    Notice DRIFT and DEFECT *both* collapse to ``not-ready`` rather
    than ``defect``; ``defect`` is reserved for cases where the
    stability-window-probe itself cannot parse a per-run envelope
    (missing JSON, malformed JSON, unknown verdict-string). The
    Tag-77 umbrella's own DEFECT verdict is a valid -- if undesirable
    -- upstream signal that the operator should inspect and not
    treat the umbrella as a reliable Pre-Cutover-Pre-Run signal.
    """
    if verdict is None:
        return "defect"
    v = verdict.strip()
    if v == "MARATHON-FINAL-INTACT":
        return "ready"
    if v in ("MARATHON-FINAL-DRIFT", "MARATHON-FINAL-DEFECT"):
        return "not-ready"
    return "defect"


def _parse_run_env(env: Mapping[str, str], idx: int) -> dict:
    """Read per-run env-vars for run-index ``idx`` (1-based).

    Each run contributes three env-vars set by the workflow:

    * ``RUN_<idx>_VERDICT`` -- the Tag-77 Marathon-Final verdict
                               (``MARATHON-FINAL-INTACT`` / DRIFT /
                               DEFECT / empty on missing upstream)
    * ``RUN_<idx>_NOTE``    -- optional human-readable note
    * ``RUN_<idx>_EXIT``    -- the exit-code of the per-run
                               aggregator invocation (``"0"`` on
                               clean exit; anything else collapses
                               the run to ``defect``)
    """
    verdict_raw = env.get(f"RUN_{idx}_VERDICT", "")
    note_raw = env.get(f"RUN_{idx}_NOTE", "")
    exit_raw = env.get(f"RUN_{idx}_EXIT", "0")
    # If the helper non-zero-exited, classify as defect even if a
    # verdict-string happened to be set; the helper's own failure
    # is a stability-window-probe-substrate defect, not an upstream
    # Tag-77 signal.
    if exit_raw.strip() != "0":
        category = "defect"
    else:
        category = _classify_marathon_final_verdict(verdict_raw)
    return {
        "run_index": idx,
        "verdict": verdict_raw,
        "note": note_raw,
        "exit": exit_raw,
        "category": category,
    }


def decide(per_run: list[dict], run_count: int) -> str:
    """Apply the Tag-78 stability-window decision rule.

    * any ``defect`` -> ``STABILITY-WINDOW-DEFECT``
    * all ``ready`` AND len == run_count -> ``STABILITY-WINDOW-CONFIRMED``
    * otherwise -> ``STABILITY-WINDOW-NOT-YET``

    The rule is deliberately stricter than the Tag-77 umbrella's
    own rule: ANY ``not-ready`` (MARATHON-FINAL-DRIFT or DEFECT)
    collapses the window to NOT-YET. The Pre-Cutover-Pre-Run-
    reliability question demands all three runs INTACT; degraded-
    but-not-broken is not enough.
    """
    defects = sum(1 for r in per_run if r["category"] == "defect")
    readys = sum(1 for r in per_run if r["category"] == "ready")
    if defects >= 1:
        return VERDICT_DEFECT
    if readys == run_count and len(per_run) == run_count:
        return VERDICT_CONFIRMED
    return VERDICT_NOT_YET


def _coerce_run_count(env: Mapping[str, str]) -> int:
    """Read and validate the ``RUN_COUNT`` env-var.

    Defaults to 3 (the Tag-59 OTS N-Run pattern). Bounded to
    [1, 10] same as the REUSE-Wrap / E2E-Smoke / Live-Smoke
    Stability-Window-Probes. Bad input collapses to 3
    (informational, not a workflow-step-fail).
    """
    raw = env.get("RUN_COUNT", "3")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 3
    if n < 1:
        return 1
    if n > 10:
        return 10
    return n


def build_envelope(env: Mapping[str, str]) -> dict:
    """Build the stability-window verdict envelope.

    The envelope shape is consumer-stable: Henrik-Audit-sample,
    AR-Hand summariser, and the Phase-3-Marathon-Polish-Phase Pre-
    Cutover-Readiness claim all read the same fields. Schema-
    version is incremented if the shape changes in a breaking way.
    """
    run_count = _coerce_run_count(env)
    per_run: list[dict] = []
    for i in range(1, run_count + 1):
        per_run.append(_parse_run_env(env, i))
    verdict = decide(per_run, run_count)
    ready_count = sum(1 for r in per_run if r["category"] == "ready")
    not_ready_count = sum(1 for r in per_run if r["category"] == "not-ready")
    defect_count = sum(1 for r in per_run if r["category"] == "defect")
    return {
        "schema_version": 1,
        "workflow": "marathon-final-stability-window-probe",
        "tag": "tag-78",
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "github_run_id": env.get("GITHUB_RUN_ID"),
        "github_sha": env.get("GITHUB_SHA"),
        "github_ref": env.get("GITHUB_REF"),
        "verdict": verdict,
        "run_count": run_count,
        "per_run": per_run,
        "counts": {
            "ready": ready_count,
            "not_ready": not_ready_count,
            "defect": defect_count,
        },
        "decision_rule": {
            "confirmed": (
                f"all {run_count} runs returned MARATHON-FINAL-INTACT "
                "-- operator may treat the Tag-77 umbrella as a "
                "reliable Pre-Cutover-Pre-Run signal for the Phase-3-"
                "Marathon-Polish-Phase Pre-Cutover-Readiness claim"
            ),
            "not_yet": (
                "at least one run returned MARATHON-FINAL-DRIFT or "
                "MARATHON-FINAL-DEFECT; operator inspects per-stage "
                "notes, does not promote umbrella to reliable"
            ),
            "defect": (
                "at least one run produced a non-parseable verdict or "
                "the probe substrate itself crashed; operator files "
                "a bug, this is a defect in the stability-window-probe"
            ),
        },
        "pattern_lineage": PATTERN_LINEAGE,
        "cross_substrate_links": CROSS_SUBSTRATE_LINKS,
        "cross_review_markers": [
            (
                "Zone-M: Stability-Window-Probe walks the Tag-77 "
                "Marathon-Final-Smoke umbrella owned by Amara; the "
                "probe depends on the Tag-77 verdict-envelope shape "
                "but does not modify the Tag-77 aggregator. Cross-"
                "component because the Tag-77 umbrella consumes ten "
                "substrate envelopes owned by Amara + Reza + Tomas "
                "(+ audit-anchor stand-ins from Tomas+Selin for "
                "Welle-1/2)."
            ),
            (
                "Zone-N: Henrik (Internal Audit) consumes the "
                "Stability-Window verdict as audit-evidence-input "
                "for the Phase-3-Marathon-Polish-Phase Pre-Cutover-"
                "Readiness claim. Drift in the decision-rule is a "
                "Zone-N signal."
            ),
        ],
    }


def main(argv: list[str]) -> int:
    """Aggregator entry-point."""
    p = argparse.ArgumentParser(
        description=(
            "Aggregate per-run Tag-78 Marathon-Final-Smoke stability-"
            "window results into a single verdict."
        )
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
        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.print_stdout:
        print(json.dumps(envelope, indent=2, sort_keys=True))
    # Always 0; the verdict is the payload. The calling workflow
    # decides whether STABILITY-WINDOW-DEFECT collapses the job-
    # exit (mirroring the Tag-63 REUSE-Wrap + Tag-65 E2E-Smoke +
    # Tag-69 Live-Smoke Stability-Window-Probes which exit 1 only
    # on DEFECT).
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI dispatch
    sys.exit(main(sys.argv))
