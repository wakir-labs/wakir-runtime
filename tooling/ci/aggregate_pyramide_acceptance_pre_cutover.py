#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-62 Pyramide-Acceptance Pre-Cutover Compositum aggregator (Amara).

The Tag-62 compositum is the **aggregated** Pre-Cutover-Acceptance
verdict for the 6-Layer Acceptance-Pyramide. It walks the four
Tag-57/58/60/61 QA-substrate verdicts the pyramide has accumulated
during the Phase-3c marathon and emits a single aggregated
pre-cutover verdict that the KW-24 cutover-day auto-scheduler can
read alongside Selin's Tag-61 persona-engine compositum
(``persona-engine-pre-cutover-final-composite-verdict.json``) and
the broader Tag-53 ``pre-cutover-final-sanity-gate-verdict.json``.

Four sub-gate substrates aggregated
-----------------------------------

* ``G1`` run_order_doc
    Pre-Cutover-Acceptance-Run-Order-Doc + Verdict-Aggregator from
    Tag-57 PR #365. Probes ``docs/quality-gates/pre-cutover-
    acceptance-run-order.md`` exists AND
    ``tooling/ci/aggregate_pyramide_run_order_verdict.py`` exists
    AND is importable (the helper is the source-of-truth for the
    Pyramide verdict-envelope schema). ``green`` on full match;
    ``yellow`` on doc-missing-but-helper-present; ``red`` on helper
    missing or non-importable.

* ``G2`` layer_dag
    Layer-DAG-Verify-Gate verdict from Tag-58 PR #374. Reads the
    output of ``tooling/ci/verify_layer_dependency_dag.py --json``.
    ``green`` when the verdict is ``DAG-CONSISTENT``; ``yellow``
    when the verdict is ``DAG-DRIFT-ALLOWED`` (Tag-61 allowlist
    swallows residual extras); ``red`` on ``DAG-DRIFT-BLOCKED``,
    ``DAG-DRIFT``, ``DAG-CYCLE``, or ``DAG-PARSE-ERROR``.

* ``G3`` cross_run_stability
    Pyramide-Cross-Run-Stability-Pin verdict from Tag-60 PR #387.
    Reads the JSON output of
    ``tooling/ci/verify_pyramide_cross_run_stability.py``. ``green``
    when the verdict is ``CROSS-RUN-STABLE``; ``yellow`` reserved
    for soft-degradation paths (currently unused by the upstream
    helper but kept in the rule for forward-compat); ``red`` on
    ``CROSS-RUN-DRIFT`` or ``CROSS-RUN-ERROR``.

* ``G4`` drift_allowlist
    DAG-Drift-Allowlist-Mechanic from Tag-61 PR #393. Probes
    ``tooling/ci/layer-dag-drift-allowlist.json`` exists, parses,
    and carries the ``_schema`` + ``entries`` keys. The allowlist
    file is the source-of-truth for the Tag-61 verdict-vocabulary-
    extension. ``green`` when the file parses AND has zero entries
    (clean baseline); ``yellow`` when the file parses AND has 1..N
    entries (legitimate allowances are present but every one carries
    a follow-up obligation per Tag-61 contract); ``red`` when the
    file is missing, malformed, or has entries without follow-up.

Aggregated verdict
------------------

* ``ACCEPTANCE-PYRAMIDE-READY``    - all four substrates green.
* ``ACCEPTANCE-PYRAMIDE-DRIFT``    - 1..N substrates yellow, zero red.
* ``ACCEPTANCE-PYRAMIDE-DEFECT``   - any substrate red.

The threshold here is intentionally tight - **stricter than
Selin's Tag-61 persona-engine compositum** (G5 there allows any
yellow to degrade to DRIFT). For the Pyramide aggregator the rule
is the same shape (any yellow degrades, any red collapses), but
the yellow-tolerance scope is narrower: G4 specifically treats a
non-empty allowlist as yellow because every allowance carries a
follow-up obligation; we do not want a slowly-accumulating
allowlist to silently pass as READY.

Empty / missing env-vars default to ``red`` (we assume an upstream
job failed entirely if its output is absent).

Exit code
---------

Always ``0``. The verdict-envelope's ``verdict`` field carries the
READY/DRIFT/DEFECT signal; the calling workflow translates that to
step-exit semantics.

Hermetic
--------

Stdlib only.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This aggregator pins the QA-Pyramide CI surface. It does NOT
modify persona definitions (Aisha-Domaene), WAT-core / V-907
logic (Tomas-Domaene, Zone-K), identity-substrate (Reza-Domaene,
Zone-L), container-infra (Kai-Domaene, Zone-J), or persona-engine
substrate (Selin-Domaene, Zone-O). Cross-review-markers:

* Zone-M: Pyramide layer-test-substrate is co-owned with Engineering
  personae via Tomas (Matrix-Lead). The aggregator depends on the
  substrate but does not modify it.
* Zone-N: Henrik (Internal Audit) consumes the aggregated verdict
  as audit-evidence-input. Drift in the aggregator's rule is a
  Zone-N signal.
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

# Canonical substrate-keys in documented order. The workflow YAML
# emits ``G<n>_STATUS`` env-vars in this same order. The tuple here
# is the single source of truth; the test-suite enumerates from it.
SUBSTRATES: tuple[str, ...] = (
    "run_order_doc",
    "layer_dag",
    "cross_run_stability",
    "drift_allowlist",
)

# Cross-substrate playbook links. Recorded on the envelope so an
# artifact-only consumer (KW-24 auto-scheduler, AR-Hand summariser,
# Henrik-Audit-sample) does not have to re-resolve paths.
CROSS_SUBSTRATE_LINKS: dict[str, str] = {
    "run_order_doc_anchor": (
        "docs/quality-gates/pre-cutover-acceptance-run-order.md"
    ),
    "run_order_aggregator": (
        "tooling/ci/aggregate_pyramide_run_order_verdict.py"
    ),
    "layer_dag_helper": "tooling/ci/verify_layer_dependency_dag.py",
    "layer_dag_workflow": (
        ".github/workflows/pyramide-layer-dependency-verify-gate.yml"
    ),
    "cross_run_helper": (
        "tooling/ci/verify_pyramide_cross_run_stability.py"
    ),
    "cross_run_workflow": (
        ".github/workflows/pyramide-cross-run-stability-pin-gate.yml"
    ),
    "drift_allowlist_file": "tooling/ci/layer-dag-drift-allowlist.json",
    "drift_allowlist_suite": (
        "tests/ci/test_layer_dag_drift_allowlist_tag61.py"
    ),
    "pyramide_map_doc": (
        "docs/quality-gates/marathon-acceptance-pyramide.md"
    ),
    "selin_engine_compositum": (
        ".github/workflows/persona-engine-pre-cutover-final-acceptance-composite.yml"
    ),
    "tag_53_sanity_workflow": (
        ".github/workflows/pre-cutover-final-sanity-gate.yml"
    ),
    "auto_scheduler_workflow": (
        ".github/workflows/phase-3-cutover-day-auto-scheduler.yml"
    ),
}

# Verdict labels (also exported for the workflow's status-line).
VERDICT_READY: str = "ACCEPTANCE-PYRAMIDE-READY"
VERDICT_DRIFT: str = "ACCEPTANCE-PYRAMIDE-DRIFT"
VERDICT_DEFECT: str = "ACCEPTANCE-PYRAMIDE-DEFECT"

# Substrate-lineage. Recorded on the envelope as audit-evidence-input.
SUBSTRATE_LINEAGE: dict[str, str] = {
    "run_order_doc": "Tag-57 PR #365 (Amara)",
    "layer_dag": "Tag-58 PR #374 (Amara)",
    "cross_run_stability": "Tag-60 PR #387 (Amara)",
    "drift_allowlist": "Tag-61 PR #393 (Amara)",
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
    """Apply the Tag-62 decision rule.

    Same shape as Selin's Tag-61 G5 (any yellow degrades, any red
    collapses) but the four-substrate scope is narrow enough that
    mixed-signal results carry no redundancy-budget. The Pyramide
    aggregator must be tight: a yellow on the allowlist axis means
    we have un-cleared follow-up obligations on legitimate cross-
    imports, and a yellow on the run-order-doc axis means the doc-
    anchor is in flux. Both warrant DRIFT, not READY.
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


def _env_key(substrate: str) -> str:
    """Map a substrate key to its workflow env-var name.

    ``run_order_doc`` -> ``G1_STATUS`` (1-indexed by position in
    SUBSTRATES). Keeps a single ordering source of truth between
    the workflow YAML and the aggregator.
    """
    idx = SUBSTRATES.index(substrate) + 1
    return f"G{idx}_STATUS"


def _note_key(substrate: str) -> str:
    """Map a substrate key to its note env-var name.

    ``run_order_doc`` -> ``G1_NOTE``.
    """
    idx = SUBSTRATES.index(substrate) + 1
    return f"G{idx}_NOTE"


def _parse_substrate_notes(raw: str | None) -> list[str]:
    """Parse the ``;``-separated ``<substrate>:<note>`` list.

    Consumers (auto-scheduler, AR-Hand summary, Henrik-Audit
    sample) read records by substrate-key prefix; we keep the raw
    split here.
    """
    if not raw:
        return []
    return [n for n in raw.split(";") if n]


def build_envelope(env: Mapping[str, str]) -> dict:
    """Build the verdict envelope from a workflow env-mapping."""
    steps = {
        substrate: _normalise(env.get(_env_key(substrate)))
        for substrate in SUBSTRATES
    }
    reds = sum(1 for v in steps.values() if v == "red")
    yellows = sum(1 for v in steps.values() if v == "yellow")
    greens = sum(1 for v in steps.values() if v == "green")
    verdict = decide(steps)
    failed = [k for k, v in steps.items() if v != "green"]

    # Per-substrate notes - either via the per-substrate G<n>_NOTE
    # env-var or via the consolidated SUBSTRATE_NOTES list. We
    # populate both shapes on the envelope so downstream consumers
    # can pick whichever fits their parser.
    per_note: dict[str, str] = {}
    for substrate in SUBSTRATES:
        note = env.get(_note_key(substrate), "") or ""
        if note:
            per_note[substrate] = note
    substrate_notes = _parse_substrate_notes(env.get("SUBSTRATE_NOTES"))

    return {
        "schema_version": 1,
        "workflow": "pyramide-acceptance-pre-cutover-compositum",
        "tag": "tag-62",
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "github_run_id": env.get("GITHUB_RUN_ID"),
        "github_sha": env.get("GITHUB_SHA"),
        "github_ref": env.get("GITHUB_REF"),
        "verdict": verdict,
        "step_results": steps,
        "failed_steps": failed,
        "per_substrate_notes": per_note,
        "substrate_notes": substrate_notes,
        "counts": {"green": greens, "yellow": yellows, "red": reds},
        "decision_rule": {
            "ready": (
                "all four pyramide-acceptance substrates green "
                "(run_order_doc + layer_dag + cross_run_stability "
                "+ drift_allowlist)"
            ),
            "drift": "1..N yellow, zero red",
            "defect": "any red",
        },
        "substrate_lineage": SUBSTRATE_LINEAGE,
        "cross_substrate_links": CROSS_SUBSTRATE_LINKS,
        "cross_review_markers": [
            (
                "Zone-M: layer-test substrate co-owned with Engineering "
                "personae via Tomas (Matrix-Lead). Aggregator depends on "
                "substrate but does not modify it."
            ),
            (
                "Zone-N: Henrik (Internal Audit) consumes the aggregated "
                "verdict as audit-evidence-input. Drift in the aggregator's "
                "rule is a Zone-N signal."
            ),
        ],
    }


def main(argv: list[str]) -> int:
    """Aggregator entry-point."""
    p = argparse.ArgumentParser(
        description=(
            "Aggregate per-substrate Tag-62 pyramide-acceptance "
            "pre-cutover-compositum results into a single verdict."
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
