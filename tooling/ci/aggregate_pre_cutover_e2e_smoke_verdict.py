#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-63 Pre-Cutover-Final-Acceptance E2E-Smoke verdict aggregator (Amara).

The Tag-63 E2E-Smoke is the **hermetic end-to-end** Pre-Cutover-
Final-Acceptance probe. It walks the full pre-cutover acceptance
pipeline as a single full-flow run, from input-trigger through the
four Tag-57..62 stages, and emits a single ``E2E-READY`` /
``E2E-DRIFT`` / ``E2E-DEFECT`` verdict that operator-hand / AR-Hand
can read on the cutover-day morning to confirm the pre-cutover
substrate is end-to-end coherent (not just sub-gate coherent).

Anchor pattern
--------------

The "smoke-test-Day-1-on-Cutover-Tag" pattern from the live-VM
acceptance lineage (Tag-39/40 Welle-6/7) - run the full pipeline
once, hermetic, in a single CI job-chain, and surface a single
trinary verdict. This time the pipeline is *acceptance-CI* itself:
the Tag-57..62 sub-gates each emit a verdict; the E2E-Smoke walks
them in declared order and produces the aggregate.

Four E2E stages aggregated
--------------------------

* ``S1`` pyramide_compositum
    Tag-62 Pyramide-Acceptance Pre-Cutover-Compositum (PR #398).
    Probes ``tooling/ci/aggregate_pyramide_acceptance_pre_cutover.py``
    exists AND is importable AND its four canonical substrates
    (``run_order_doc``, ``layer_dag``, ``cross_run_stability``,
    ``drift_allowlist``) are present in the ``SUBSTRATES`` tuple.
    ``green`` on full match; ``yellow`` on partial-import-but-API-
    intact; ``red`` on helper missing or non-importable or
    SUBSTRATES tuple drift.

* ``S2`` engine_composite
    Tag-61/62 Persona-Engine Pre-Cutover Final Acceptance Composite
    (PR #399). Probes ``tooling/ci/aggregate_persona_engine_pre_
    cutover_final.py`` exists AND is importable AND the engine
    workflow YAML at ``.github/workflows/persona-engine-pre-cutover
    -final-acceptance-composite.yml`` exists. ``green`` on full
    match; ``yellow`` on workflow-missing-but-helper-present;
    ``red`` on aggregator helper missing or non-importable.

* ``S3`` cross_gates
    Cross-Gate substrate fan-out. Probes the three cross-gate
    workflows exist and parse:
      - Watch-Day-Practice-Run (Tag-55/56, Noa-SRE) at
        ``.github/workflows/phase-3c-watch-day-practice-run.yml``
      - Cross-Substrate-Parity-Gate (Tag-32/57) at
        ``.github/workflows/cross-substrate-parity-gate.yml``
      - Marathon-Final-Acceptance Live-Verify-Gate (Tag-40) at
        ``.github/workflows/marathon-final-acceptance-live-verify-
        gate.yml``
    ``green`` when all three workflows exist; ``yellow`` when 1-2
    exist; ``red`` when none exist or YAML parsing fails on any
    present workflow.

* ``S4`` final_sanity
    Tag-53 Pre-Cutover-Final-Sanity-Gate substrate (PR #353-era).
    Probes the workflow at ``.github/workflows/pre-cutover-final-
    sanity-gate.yml`` exists AND the aggregator at
    ``tooling/ci/aggregate_pre_cutover_final_sanity_gate_verdict
    .py`` exists AND is importable. ``green`` on full match;
    ``yellow`` on workflow-missing-but-helper-present; ``red`` on
    helper missing or non-importable.

Aggregated verdict
------------------

* ``E2E-READY``    - all four stages green.
* ``E2E-DRIFT``    - 1..N yellow, zero red.
* ``E2E-DEFECT``   - any red.

Same shape as Selin's Tag-61 G5 and Amara's Tag-62 G5 (any yellow
degrades, any red collapses). The four-stage scope is the union
of two compositum-aggregators plus two cross-gate substrates; we
do not introduce a redundancy-budget because the E2E surface is
already loose by virtue of being a smoke-test (it walks helpers,
it does not re-run their full test-bodies).

Empty / missing env-vars default to ``red`` (we assume an upstream
job failed entirely if its output is absent).

Exit code
---------

Always ``0``. The verdict-envelope's ``verdict`` field carries the
READY/DRIFT/DEFECT signal; the calling workflow translates that to
step-exit semantics.

Hermetic
--------

Stdlib only. No third-party imports. No subprocess invocations.
No filesystem-state mutation outside ``--output``.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This aggregator pins the Pre-Cutover-E2E-Smoke surface. It does
NOT modify persona definitions (Aisha-Domaene), WAT-core / V-907
logic (Tomas-Domaene, Zone-K), identity-substrate (Reza-Domaene,
Zone-L), container-infra (Kai-Domaene, Zone-J), or persona-engine
substrate (Selin-Domaene, Zone-O). Cross-review-markers:

* Zone-M: E2E-Smoke walks helpers owned by Engineering-Personae
  via Tomas (Matrix-Lead). The aggregator depends on those helpers
  but does not modify them.
* Zone-N: Henrik (Internal Audit) consumes the aggregated E2E-
  verdict as audit-evidence-input for the KW-24 Pre-Cutover-Final-
  Acceptance claim. Drift in the aggregator's rule is a Zone-N
  signal.
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

# Canonical stage-keys in documented E2E order. The workflow YAML
# emits ``S<n>_STATUS`` env-vars in this same order. The tuple here
# is the single source of truth; the test-suite enumerates from it.
STAGES: tuple[str, ...] = (
    "pyramide_compositum",
    "engine_composite",
    "cross_gates",
    "final_sanity",
)

# Cross-substrate links. Recorded on the envelope so an artifact-
# only consumer (KW-24 auto-scheduler, AR-Hand summariser, Henrik-
# Audit-sample) does not have to re-resolve paths.
CROSS_SUBSTRATE_LINKS: dict[str, str] = {
    "pyramide_compositum_aggregator": (
        "tooling/ci/aggregate_pyramide_acceptance_pre_cutover.py"
    ),
    "pyramide_compositum_workflow": (
        ".github/workflows/pyramide-acceptance-pre-cutover-compositum.yml"
    ),
    "engine_composite_aggregator": (
        "tooling/ci/aggregate_persona_engine_pre_cutover_final.py"
    ),
    "engine_composite_workflow": (
        ".github/workflows/"
        "persona-engine-pre-cutover-final-acceptance-composite.yml"
    ),
    "watch_day_workflow": (
        ".github/workflows/phase-3c-watch-day-practice-run.yml"
    ),
    "cross_substrate_parity_workflow": (
        ".github/workflows/cross-substrate-parity-gate.yml"
    ),
    "live_verify_workflow": (
        ".github/workflows/"
        "marathon-final-acceptance-live-verify-gate.yml"
    ),
    "final_sanity_workflow": (
        ".github/workflows/pre-cutover-final-sanity-gate.yml"
    ),
    "final_sanity_aggregator": (
        "tooling/ci/aggregate_pre_cutover_final_sanity_gate_verdict.py"
    ),
    "auto_scheduler_workflow": (
        ".github/workflows/phase-3-cutover-day-auto-scheduler.yml"
    ),
}

# Verdict labels (also exported for the workflow's status-line).
VERDICT_READY: str = "E2E-READY"
VERDICT_DRIFT: str = "E2E-DRIFT"
VERDICT_DEFECT: str = "E2E-DEFECT"

# Stage-lineage. Recorded on the envelope as audit-evidence-input.
STAGE_LINEAGE: dict[str, str] = {
    "pyramide_compositum": "Tag-62 PR #398 (Amara)",
    "engine_composite": "Tag-61/62 PR #392/#399 (Selin)",
    "cross_gates": "Tag-32/55/56/57 (Noa + Kai + Amara)",
    "final_sanity": "Tag-53 (Amara)",
}


def _normalise(raw: str | None) -> str:
    """Coerce an env-var value to a known status. Empty / unknown -> red.

    The aggregator never silently downgrades an unrecognised input;
    upstream-job-missing or upstream-job-broken collapses to red so
    the verdict surfaces the gap loudly.
    """
    if raw is None:
        return "red"
    v = raw.strip().lower()
    if v in VALID_STATUSES:
        return v
    if v == "":
        return "red"
    return "red"


def decide(steps: Mapping[str, str]) -> str:
    """Apply the Tag-63 E2E-Smoke decision rule.

    Same shape as Selin's Tag-61 G5 and Amara's Tag-62 G5 (any
    yellow degrades, any red collapses). The four-stage scope is
    the union of two compositum-aggregators plus two cross-gate
    substrates; we do not introduce a redundancy-budget because the
    E2E surface is already loose by virtue of being a smoke-test.
    """
    reds = sum(1 for v in steps.values() if v == "red")
    yellows = sum(1 for v in steps.values() if v == "yellow")
    greens = sum(1 for v in steps.values() if v == "green")
    if reds >= 1:
        return VERDICT_DEFECT
    if yellows >= 1:
        return VERDICT_DRIFT
    if greens == len(steps):
        return VERDICT_READY
    # Defensive default. With the normaliser above, every value is
    # in VALID_STATUSES, so this branch should be unreachable.
    return VERDICT_DEFECT


def _env_key(stage: str) -> str:
    """Map a stage key to its workflow env-var name.

    ``pyramide_compositum`` -> ``S1_STATUS`` (1-indexed by position
    in STAGES). Keeps a single ordering source of truth between the
    workflow YAML and the aggregator.
    """
    idx = STAGES.index(stage) + 1
    return f"S{idx}_STATUS"


def _note_key(stage: str) -> str:
    """Map a stage key to its note env-var name.

    ``pyramide_compositum`` -> ``S1_NOTE``.
    """
    idx = STAGES.index(stage) + 1
    return f"S{idx}_NOTE"


def _parse_stage_notes(raw: str | None) -> list[str]:
    """Parse the ``;``-separated ``<stage>:<note>`` list.

    Consumers (auto-scheduler, AR-Hand summary, Henrik-Audit
    sample) read records by stage-key prefix; we keep the raw
    split here.
    """
    if not raw:
        return []
    return [n for n in raw.split(";") if n]


def build_envelope(env: Mapping[str, str]) -> dict:
    """Build the verdict envelope from a workflow env-mapping."""
    steps = {
        stage: _normalise(env.get(_env_key(stage)))
        for stage in STAGES
    }
    reds = sum(1 for v in steps.values() if v == "red")
    yellows = sum(1 for v in steps.values() if v == "yellow")
    greens = sum(1 for v in steps.values() if v == "green")
    verdict = decide(steps)
    failed = [k for k, v in steps.items() if v != "green"]

    # Per-stage notes - either via the per-stage S<n>_NOTE env-var
    # or via the consolidated STAGE_NOTES list. We populate both
    # shapes on the envelope so downstream consumers can pick
    # whichever fits their parser.
    per_note: dict[str, str] = {}
    for stage in STAGES:
        note = env.get(_note_key(stage), "") or ""
        if note:
            per_note[stage] = note
    stage_notes = _parse_stage_notes(env.get("STAGE_NOTES"))

    return {
        "schema_version": 1,
        "workflow": "pre-cutover-final-acceptance-e2e-smoke",
        "tag": "tag-63",
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "github_run_id": env.get("GITHUB_RUN_ID"),
        "github_sha": env.get("GITHUB_SHA"),
        "github_ref": env.get("GITHUB_REF"),
        "verdict": verdict,
        "step_results": steps,
        "failed_steps": failed,
        "per_stage_notes": per_note,
        "stage_notes": stage_notes,
        "counts": {"green": greens, "yellow": yellows, "red": reds},
        "decision_rule": {
            "ready": (
                "all four E2E stages green "
                "(pyramide_compositum + engine_composite + "
                "cross_gates + final_sanity)"
            ),
            "drift": "1..N yellow, zero red",
            "defect": "any red",
        },
        "stage_lineage": STAGE_LINEAGE,
        "cross_substrate_links": CROSS_SUBSTRATE_LINKS,
        "cross_review_markers": [
            (
                "Zone-M: E2E-Smoke walks helpers owned by Engineering "
                "personae via Tomas (Matrix-Lead). Aggregator depends "
                "on helpers but does not modify them."
            ),
            (
                "Zone-N: Henrik (Internal Audit) consumes the "
                "aggregated E2E-verdict as audit-evidence-input for "
                "the KW-24 Pre-Cutover-Final-Acceptance claim. Drift "
                "in the aggregator's rule is a Zone-N signal."
            ),
        ],
    }


def main(argv: list[str]) -> int:
    """Aggregator entry-point."""
    p = argparse.ArgumentParser(
        description=(
            "Aggregate per-stage Tag-63 Pre-Cutover-Final-Acceptance "
            "E2E-Smoke results into a single verdict."
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
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI dispatch
    sys.exit(main(sys.argv))
