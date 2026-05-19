#!/usr/bin/env python3
# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-61 Pre-Cutover-Final-Acceptance-Compositum aggregator (Selin).

The Tag-61 compositum is the **final** persona-engine pre-cutover
acceptance probe. It walks the four Tag-58/59/60 substrate verdicts
the engine 0.5.3-rc1 RC has accumulated and emits a single
aggregated pre-cutover verdict that the KW-24 cutover-day auto-
scheduler can read alongside the broader Tag-53
``pre-cutover-final-sanity-gate-verdict.json``.

Four sub-gate substrates aggregated
-----------------------------------

* ``G1`` v907_pin
    V-907 persona-hash-pin verdict from Tag-59 PR #379. Reads the
    output of ``tooling/ci/verify_v907_persona_hash_pin.py``. The
    underlying envelope emits ``HASH-PIN-INTACT`` or
    ``HASH-PIN-DRIFT``. The workflow normalises that to
    ``green`` / ``red`` (no yellow path on this axis -- a hash-pin
    is binary: it matches or it does not).

* ``G2`` drift_scanner
    Engine-version-drift full-coverage scanner verdict from Tag-60
    PR #384. Reads the JSON output of
    ``tooling/ci/scan_engine_version_drift.py --json``. ``green``
    when ``findings_unallowlisted`` is empty AND
    ``findings_allowlisted`` is empty; ``yellow`` when only
    allowlisted hits exist (legitimate historical literals are
    present but no new drift); ``red`` on any un-allowlisted
    finding.

* ``G3`` version_bump_coverage
    Engine 0.5.3-rc1 version-bump-coverage verdict from Tag-58
    PR #372 substrate. Probes the canonical anchor at
    ``wirelang/persona_engine/__version__.py`` matches the
    expected active version, AND the 0.5.3-rc1 release-notes file
    is present. ``green`` on full match; ``yellow`` on anchor-
    matches-but-release-notes-missing; ``red`` on anchor-mismatch.

* ``G4`` manifest_readiness
    Manifest + pin-pack readiness from Tag-52/Tag-58 substrate.
    Probes ``wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md``
    and ``infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml``
    exist on HEAD AND the pin-pack carries
    ``manifest_version: "0.5.2-final-pre-cutover"``. ``green`` on
    full match; ``yellow`` on partial; ``red`` on missing.

Aggregated verdict
------------------

* ``PRE-CUTOVER-READY``   - all four substrates green.
* ``PRE-CUTOVER-DRIFT``   - 1..N substrates yellow, zero red.
* ``PRE-CUTOVER-DEFECT``  - any substrate red.

The threshold here is intentionally tighter than the Tag-53
``pre-cutover-final-sanity-gate`` aggregator. Tag-53 covers seven
broad-marathon substrates with operator-hand redundancy across
them; Tag-61 covers four narrow persona-engine-only substrates,
and any yellow on any one of them indicates the 0.5.3-rc1 RC is
not pristine for cutover. The KW-24 auto-scheduler treats DRIFT
as ``yellow-degraded`` (allowed-with-recorded-note) and DEFECT
as ``hard-block``.

Empty / missing env-vars default to ``red`` (we assume an
upstream job failed entirely if its output is absent).

Exit code
---------

Always ``0``. The verdict-envelope's ``verdict`` field carries
the READY/DRIFT/DEFECT signal; the calling workflow translates
that to step-exit semantics.

Hermetic
--------

stdlib only.

Scope discipline (Selin, ADR-0036/0043/0065/0066)
------------------------------------------------

This aggregator pins the persona-engine CI surface. It does NOT
modify persona definitions (Aisha-Domaene), WAT-core / V-907
logic (Tomas-Domaene, Zone-K), identity-substrate (Reza-Domaene,
Zone-L), or container-infra (Kai-Domaene, Zone-J).
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
    "v907_pin",
    "drift_scanner",
    "version_bump_coverage",
    "manifest_readiness",
)

# Operator-playbook cross-substrate links. Recorded on the envelope
# so an artifact-only consumer (KW-24 auto-scheduler, AR-Hand
# summariser) does not have to re-resolve paths.
CROSS_SUBSTRATE_LINKS: dict[str, str] = {
    "v907_verifier": "tooling/ci/verify_v907_persona_hash_pin.py",
    "v907_baseline": "wirelang/persona_engine/v907-hash-baseline.json",
    "v907_workflow": ".github/workflows/v907-persona-hash-pin-build-step.yml",
    "drift_scanner_script": "tooling/ci/scan_engine_version_drift.py",
    "drift_scanner_allowlist": "tooling/ci/engine-version-drift-allowlist.json",
    "version_anchor_module": "wirelang/persona_engine/__version__.py",
    "release_notes_doc": "docs/persona-engine/0-5-3-rc1-release-notes.md",
    "manifest_doc": (
        "wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md"
    ),
    "pin_pack_yaml": (
        "infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml"
    ),
    "tag_53_sanity_workflow": (
        ".github/workflows/pre-cutover-final-sanity-gate.yml"
    ),
    "auto_scheduler_workflow": (
        ".github/workflows/phase-3-cutover-day-auto-scheduler.yml"
    ),
}

# The active persona-engine version string. Bump in lockstep with
# wirelang/persona_engine/__version__.py when the next RC opens.
# Tag-62 (2026-05-19, Selin): rc1-suffix-drop final promotion.
EXPECTED_ACTIVE_VERSION: str = "0.5.3"


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
    """Apply the Tag-61 decision rule.

    Tighter than Tag-53: any yellow degrades the verdict; any red
    collapses to DEFECT. The four-substrate scope is narrow enough
    that mixed-signal results carry no redundancy-budget.
    """
    reds = sum(1 for v in steps.values() if v == "red")
    yellows = sum(1 for v in steps.values() if v == "yellow")
    greens = sum(1 for v in steps.values() if v == "green")
    if reds >= 1:
        return "PRE-CUTOVER-DEFECT"
    if yellows >= 1:
        return "PRE-CUTOVER-DRIFT"
    if greens == len(steps):
        return "PRE-CUTOVER-READY"
    # Defensive default. With the normaliser above, every value is
    # in VALID_STATUSES, so this branch should be unreachable.
    return "PRE-CUTOVER-DEFECT"


def _env_key(substrate: str) -> str:
    """Map a substrate key to its workflow env-var name.

    ``v907_pin`` -> ``G1_STATUS`` (1-indexed by position in
    SUBSTRATES). Keeps a single ordering source of truth between
    the workflow YAML and the aggregator.
    """
    idx = SUBSTRATES.index(substrate) + 1
    return f"G{idx}_STATUS"


def _note_key(substrate: str) -> str:
    """Map a substrate key to its note env-var name.

    ``v907_pin`` -> ``G1_NOTE``.
    """
    idx = SUBSTRATES.index(substrate) + 1
    return f"G{idx}_NOTE"


def _parse_substrate_notes(raw: str | None) -> list[str]:
    """Parse the ``;``-separated ``<substrate>:<note>`` list.

    Consumers (auto-scheduler, AR-Hand summary) read records by
    substrate-key prefix; we keep the raw split here.
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

    # Per-substrate notes — either via the per-substrate G<n>_NOTE
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
        "workflow": "persona-engine-pre-cutover-final-acceptance-composite",
        "tag": "tag-61",
        "engine_version": EXPECTED_ACTIVE_VERSION,
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
                "all four persona-engine substrates green "
                "(v907_pin + drift_scanner + version_bump_coverage "
                "+ manifest_readiness)"
            ),
            "drift": "1..N yellow, zero red",
            "defect": "any red",
        },
        "substrate_lineage": {
            "v907_pin": "Tag-59 PR #379 (Selin)",
            "drift_scanner": "Tag-60 PR #384 (Selin)",
            "version_bump_coverage": "Tag-58 PR #372 (Selin)",
            "manifest_readiness": (
                "Tag-52 PR #336 + Tag-58 PR #372 (Selin)"
            ),
        },
        "cross_substrate_links": CROSS_SUBSTRATE_LINKS,
    }


def main(argv: list[str]) -> int:
    """Aggregator entry-point."""
    p = argparse.ArgumentParser(
        description=(
            "Aggregate per-substrate Tag-61 persona-engine pre-cutover "
            "final-acceptance-compositum results into a single verdict."
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
