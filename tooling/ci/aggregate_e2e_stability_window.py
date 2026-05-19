#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-65 E2E-Smoke Stability-Window aggregator (Amara).

Purpose
-------

The Tag-65 E2E-Stability-Window-Probe answers the question:
"if we were to run the Tag-63 Pre-Cutover-Final-Acceptance E2E-
Smoke (PR #400) three times back-to-back on the current main-tip,
would all three runs return ``E2E-READY``?" If yes, the workflow
is eligible for Required-Status-Check promotion per the Tag-64
Required-Status-Check-Wiring-Companion (PR #411, §4 Risk-Map
position #8). If no, the operator inspects and does not promote.

The actual Required-Status-Check pin remains operator-hand (Tag-64
plan-doc §6 Sandbox-Boundary). This probe just provides a
defensible Pre-Run signal -- it is the QA-side analog of the
Tag-63 Tomas-Pattern (REUSE-Wrap Stability-Window-Probe, PR #404)
applied to the E2E-Smoke instead of REUSE-Wrap-Lint.

Anchor pattern
--------------

Tag-59 OTS N-Run-Pattern (3 consecutive runs) -> Tag-63 REUSE-
Wrap Stability-Window-Probe (PR #404, Tomas) -> Tag-65 E2E-Smoke
Stability-Window-Probe (this aggregator, Amara). All three share
the trinary verdict shape (CONFIRMED / NOT-YET / DEFECT) and the
same "informational, not Required-Status-Check" posture.

Trinary stability-window verdict
--------------------------------

* ``STABILITY-WINDOW-CONFIRMED``
    all N runs returned ``E2E-READY``. The operator has a
    defensible signal to proceed with Required-Status-Check
    promotion per Tag-64 plan-doc §2.

* ``STABILITY-WINDOW-NOT-YET``
    at least one run returned ``E2E-DRIFT`` (yellow upstream) or
    ``E2E-DEFECT`` (red upstream), but no run crashed the
    aggregator. Operator inspects the failing run, does not
    promote.

* ``STABILITY-WINDOW-DEFECT``
    at least one run produced a non-parseable verdict (missing
    envelope, malformed JSON, unknown verdict-string) or the
    probe substrate itself crashed. Operator files a bug; this
    is a defect in the stability-window-probe, not in E2E-Smoke.

Decision rule
-------------

The decision rule is deliberately stricter than the underlying
E2E-Smoke's rule. The E2E-Smoke allows ``E2E-DRIFT`` (yellow) as
an informational degradation. The Stability-Window-Probe requires
``E2E-READY`` (all green) on every consecutive run -- because the
question being asked is "is the substrate stable enough to
promote to Required-Status-Check?" Anything less than three-in-
a-row green is a NOT-YET signal.

Empty / missing per-run envelopes default to ``defect``.

Exit code
---------

Always ``0`` unless ``STABILITY-WINDOW-DEFECT`` (non-zero only if
the probe substrate itself is broken). The verdict-envelope's
``verdict`` field carries CONFIRMED/NOT-YET/DEFECT.

Hermetic
--------

Stdlib only. No third-party imports. No subprocess invocations.
No filesystem-state mutation outside ``--output``.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This aggregator pins the Tag-65 E2E-Stability-Window-Probe
surface. It does NOT modify the underlying Tag-63 E2E-Smoke
aggregator (PR #400), persona definitions (Aisha-Domaene), WAT-
core / V-907 logic (Tomas-Domaene, Zone-K), identity-substrate
(Reza-Domaene, Zone-L), container-infra (Kai-Domaene, Zone-J),
or persona-engine substrate (Selin-Domaene, Zone-O).

Cross-review-markers:

* Zone-M: Stability-Window-Probe walks the Tag-63 E2E-Smoke
  workflow owned by Amara herself; the aggregator depends on
  the E2E-Smoke verdict-envelope shape but does not modify the
  E2E-Smoke aggregator.
* Zone-N: Henrik (Internal Audit) consumes the Stability-Window
  verdict as audit-evidence-input for the Required-Status-Check
  promotion claim (Tag-64 §4 Position #8). Drift in the
  stability-window decision-rule is a Zone-N signal.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


# Valid verdicts emitted by the underlying Tag-63 E2E-Smoke
# aggregator. Anything else collapses to defect.
VALID_E2E_VERDICTS: tuple[str, ...] = (
    "E2E-READY",
    "E2E-DRIFT",
    "E2E-DEFECT",
)


# Per-run status categories for stability-window classification.
PER_RUN_STATUSES: tuple[str, ...] = ("ready", "not-ready", "defect")


# Trinary stability-window verdict labels.
VERDICT_CONFIRMED: str = "STABILITY-WINDOW-CONFIRMED"
VERDICT_NOT_YET: str = "STABILITY-WINDOW-NOT-YET"
VERDICT_DEFECT: str = "STABILITY-WINDOW-DEFECT"


# Cross-substrate links. Recorded on the envelope so an artifact-
# only consumer (Henrik-Audit-sample, AR-Hand summary, KW-24
# Promotion-Pre-Run summariser) does not have to re-resolve paths.
CROSS_SUBSTRATE_LINKS: dict[str, str] = {
    "e2e_smoke_aggregator": (
        "tooling/ci/aggregate_pre_cutover_e2e_smoke_verdict.py"
    ),
    "e2e_smoke_workflow": (
        ".github/workflows/pre-cutover-final-acceptance-e2e-smoke.yml"
    ),
    "stability_window_probe_workflow": (
        ".github/workflows/e2e-smoke-stability-window-probe.yml"
    ),
    "reuse_wrap_stability_window_anchor": (
        ".github/workflows/"
        "reuse-wrap-enforce-flip-stability-window-probe.yml"
    ),
    "tag64_required_check_companion_doc": (
        "docs/operations/branch-protection-required-checks-tag64-companion.md"
    ),
}


# Pattern lineage. Recorded on the envelope as audit-evidence-input.
PATTERN_LINEAGE: dict[str, str] = {
    "n_run_pattern": "Tag-59 OTS N-Run Pattern (3 consecutive runs)",
    "reuse_wrap_anchor": "Tag-63 PR #404 (Tomas)",
    "e2e_smoke_anchor": "Tag-63 PR #400 (Amara)",
    "required_check_pool_anchor": "Tag-64 PR #411 (Amara) §4 #8",
    "current_owner": "Tag-65 Amara (this aggregator)",
}


def _classify_e2e_verdict(verdict: str | None) -> str:
    """Map an E2E-Smoke verdict-string to a stability-window category.

    * ``E2E-READY``   -> ``ready``
    * ``E2E-DRIFT``   -> ``not-ready`` (yellow upstream, not eligible)
    * ``E2E-DEFECT``  -> ``not-ready`` (red upstream, not eligible)
    * anything else   -> ``defect`` (probe substrate broken)

    Notice E2E-DRIFT and E2E-DEFECT *both* collapse to ``not-ready``
    rather than ``defect``; ``defect`` is reserved for cases where
    the stability-window-probe itself cannot parse a per-run
    envelope (missing JSON, malformed JSON, unknown verdict-string).
    The E2E-Smoke's own DEFECT verdict is a valid -- if undesirable
    -- upstream signal that the operator should inspect and not
    promote.
    """
    if verdict is None:
        return "defect"
    v = verdict.strip()
    if v == "E2E-READY":
        return "ready"
    if v in ("E2E-DRIFT", "E2E-DEFECT"):
        return "not-ready"
    return "defect"


def _parse_run_env(env: Mapping[str, str], idx: int) -> dict:
    """Read per-run env-vars for run-index ``idx`` (1-based).

    Each run contributes three env-vars set by the workflow:

    * ``RUN_<idx>_VERDICT`` -- the E2E-Smoke verdict string
                               (``E2E-READY`` / DRIFT / DEFECT /
                               empty on missing upstream)
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
    # E2E-Smoke signal.
    if exit_raw.strip() != "0":
        category = "defect"
    else:
        category = _classify_e2e_verdict(verdict_raw)
    return {
        "run_index": idx,
        "verdict": verdict_raw,
        "note": note_raw,
        "exit": exit_raw,
        "category": category,
    }


def decide(per_run: list[dict], run_count: int) -> str:
    """Apply the Tag-65 stability-window decision rule.

    * any ``defect`` -> ``STABILITY-WINDOW-DEFECT``
    * all ``ready`` AND len == run_count -> ``STABILITY-WINDOW-CONFIRMED``
    * otherwise -> ``STABILITY-WINDOW-NOT-YET``

    The rule is deliberately stricter than the E2E-Smoke's own
    rule: ANY ``not-ready`` (E2E-DRIFT or E2E-DEFECT) collapses
    the window to NOT-YET. The promotion-question demands all
    three runs green; degraded-but-not-broken is not enough.
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
    [1, 10] same as the REUSE-Wrap Stability-Window-Probe at
    ``.github/workflows/reuse-wrap-enforce-flip-stability-window-
    probe.yml``. Bad input collapses to 3 (informational, not a
    workflow-step-fail).
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
    AR-Hand summariser, and the KW-24 promotion-pre-run claim all
    read the same fields. Schema-version is incremented if the
    shape changes in a breaking way.
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
        "workflow": "e2e-smoke-stability-window-probe",
        "tag": "tag-65",
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
                f"all {run_count} runs returned E2E-READY -- operator may "
                "proceed with Required-Status-Check promotion per "
                "Tag-64 plan-doc §2"
            ),
            "not_yet": (
                "at least one run returned E2E-DRIFT or E2E-DEFECT; "
                "operator inspects, no promotion"
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
                "Zone-M: Stability-Window-Probe walks the Tag-63 E2E-"
                "Smoke workflow owned by Amara; aggregator depends on "
                "the E2E-Smoke verdict-envelope shape but does not "
                "modify the E2E-Smoke aggregator."
            ),
            (
                "Zone-N: Henrik (Internal Audit) consumes the Stability"
                "-Window verdict as audit-evidence-input for the "
                "Required-Status-Check promotion claim (Tag-64 §4 "
                "Position #8). Drift in the decision-rule is a "
                "Zone-N signal."
            ),
        ],
    }


def main(argv: list[str]) -> int:
    """Aggregator entry-point."""
    p = argparse.ArgumentParser(
        description=(
            "Aggregate per-run Tag-65 E2E-Smoke stability-window "
            "results into a single verdict."
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
    # exit (mirroring the REUSE-Wrap Stability-Window-Probe at
    # .github/workflows/reuse-wrap-enforce-flip-stability-window-
    # probe.yml which exits 1 only on DEFECT).
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI dispatch
    sys.exit(main(sys.argv))
