#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-78 hermetic Operator-Items Health-Check helper.

This helper drives the daily ``operator-items-health-check`` workflow.
It reads the Tag-77 Konsolidat Master-Doc

    docs/operations/operator-hand-pending-items-konsolidat.md

extracts the ten Operator-Hand-Items I1..I10 with their declared
**Prerequisites** blocks, evaluates each prerequisite against the
repo HEAD (file-existence, workflow-presence, helper-presence,
predecessor-doc-presence), and emits a per-item status plus a
single aggregate envelope:

* ``OPERATOR-ITEMS-READY``    -- all ten items green.
* ``OPERATOR-ITEMS-CAUTION``  -- 1..2 items yellow, zero red.
* ``OPERATOR-ITEMS-BLOCKED``  -- any item red, OR 3+ yellow.

The helper is strictly hermetic: stdlib + filesystem only. It does
**not** actually run any operator-hand step, it does **not** hit
the GitHub API, it does **not** invoke ``cosign``, ``podman``,
``systemctl``, ``gh``, or any other live tool. Per item, it only
evaluates the *static* pre-conditions that can be verified by
inspecting the runtime-repo working-tree.

Trigger surface
===============

The workflow that wraps this helper runs:

* ``workflow_dispatch`` -- operator-hand / AR-Hand manual.
* ``schedule: cron "0 6 * * *"`` -- daily 06:00 UTC.

It is intentionally **not** a required status check on PRs --
analogous to ``pre-cutover-final-sanity-gate.yml`` (Tag-53), it
gates a calendar-window (Pre-Cutover-Eve 2026-06-26 Fr), not
individual PRs.

Per-item check matrix
=====================

Each Item I1..I10 carries its own ``check_recipe``. The recipe
combines four primitives:

* ``doc(<path>)``      -- predecessor-doc must exist on HEAD.
* ``workflow(<name>)`` -- workflow file ``.github/workflows/<name>``
                          must exist on HEAD.
* ``helper(<path>)``   -- helper script must exist on HEAD.
* ``state-prep(<path>)``
                       -- a state-prep directory or marker file must
                          exist on HEAD (e.g. ``state/branch-
                          protection-pre-activation-snapshot.json``
                          parent dir for the rollback-snapshot
                          target).

A missing primitive emits ``red`` for that item; a partially-
satisfied recipe emits ``yellow`` with a note. Live-VM-only
primitives (``cosign verify``, ``systemctl restart``, ``gh api
PUT``) are **never** checked by this helper -- those are by
construction Operator-Hand and visible only on the Live-VM.

Item I10 (OTS-Stamping) is a meta-item: it depends on Items I1..I9
having produced commits, which the helper cannot observe pre-
Cutover-Eve. The helper checks **only** that the OTS-stamping
helper script and the OTS-pipeline workflow are present on HEAD.

Exit codes
==========

* 0 -- envelope is READY or CAUTION.
* 1 -- envelope is BLOCKED.
* 2 -- master-doc not found.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

DEFAULT_MASTER_DOC = (
    "docs/operations/operator-hand-pending-items-konsolidat.md"
)

# ---------------------------------------------------------------------
# Per-Item check recipes.
#
# Each entry maps an Item-ID (I1..I10) to a list of (kind, target)
# tuples. Kinds:
#
#   "doc"       -- predecessor-doc file must exist on HEAD.
#   "workflow"  -- .github/workflows/<target> must exist on HEAD.
#   "helper"    -- helper script must exist on HEAD.
#   "state-dir" -- parent directory of a state-snapshot target must
#                  exist on HEAD (rollback-prep).
#
# The recipes are kept conservative: they encode only the
# prerequisites that can be hermetically verified from the repo
# working-tree. Live-VM-only prerequisites (cosign installs,
# GitHub-API tokens, systemctl restarts) are intentionally OUT of
# scope.
# ---------------------------------------------------------------------

ITEM_CHECK_RECIPES: Dict[str, List[Tuple[str, str]]] = {
    "I1": [
        ("doc", "docs/operations/branch-protection-required-status-checks.md"),
        ("doc", "docs/operations/branch-protection-required-checks-tag61-addendum.md"),
        ("doc", "docs/operations/branch-protection-required-checks-tag64-companion.md"),
        ("helper", "tooling/ci/bulk_activate_required_checks.py"),
    ],
    "I2": [
        ("doc", "docs/operations/g1-g2-last-mile-operator-checklist.md"),
        ("doc", "docs/operations/cosign-g1-g2-operator-setup.md"),
        ("workflow", "cosign-verify-images.yml"),
    ],
    "I3": [
        ("helper", "tooling/ci/snapshot_trust_root.py"),
        ("state-dir", "state/trust-root-snapshots/"),
    ],
    "I4": [
        ("doc", "docs/operations/cross-substrate-parity-runbook.md"),
        ("helper", "tooling/ci/bulk_activate_required_checks.py"),
        ("workflow", "cross-substrate-parity-gate.yml"),
    ],
    "I5": [
        ("doc", "docs/operations/persona-engine-image-build.md"),
        ("workflow", "build-wakir-persona-engine.yml"),
        ("workflow", "cosign-verify-images.yml"),
    ],
    "I6": [
        ("doc", "docs/operations/open-j3-v907-base-image-digest-label.md"),
        ("doc", "docs/operations/open-k3-v907-baseline-metadata-carry-forward.md"),
        ("workflow", "build-wakir-persona-engine.yml"),
        ("state-dir", "state/open-closure-records/"),
    ],
    "I7": [
        ("doc", "docs/operations/open-k3-v907-baseline-metadata-carry-forward.md"),
        ("helper", "tooling/ci/refresh_baseline_metadata.py"),
        ("state-dir", "state/baseline-metadata/"),
    ],
    "I8": [
        ("doc", "docs/operations/adr-cross-repo-migration-pattern.md"),
    ],
    "I9": [
        ("doc", "docs/operations/wakir-protocol-cross-review-zone-3-handoff-plan.md"),
        ("state-dir", "state/cross-review-consensus/"),
    ],
    "I10": [
        ("helper", "tooling/ots/stamp_commit.py"),
        ("helper", "tooling/ots/verify_ots_stamp.py"),
        ("state-dir", "state/ots-stamps/"),
    ],
}

ALL_ITEMS = [f"I{n}" for n in range(1, 11)]

# Verdict envelope markers (Tag-78 contract).
VERDICT_READY = "OPERATOR-ITEMS-READY"
VERDICT_CAUTION = "OPERATOR-ITEMS-CAUTION"
VERDICT_BLOCKED = "OPERATOR-ITEMS-BLOCKED"


# ---------------------------------------------------------------------
# Per-Item evaluation.
# ---------------------------------------------------------------------


@dataclass
class ItemStatus:
    item: str
    status: str  # "green" | "yellow" | "red"
    missing: List[Tuple[str, str]] = field(default_factory=list)
    note: str = ""


def _path_exists(repo_root: Path, rel: str) -> bool:
    p = (repo_root / rel).resolve()
    return p.exists()


def _evaluate_item(
    item: str,
    recipe: Sequence[Tuple[str, str]],
    repo_root: Path,
) -> ItemStatus:
    """Evaluate a single item-recipe against the repo working-tree.

    Decision rule (per item):

      * All recipe-primitives present -> ``green``.
      * 1 missing primitive AND recipe-length >= 3 -> ``yellow``
        (partial-substrate, operator-hand may still proceed with
        workaround).
      * Any missing primitive on recipe-length < 3 -> ``red``.
      * 2+ missing primitives -> ``red``.
    """
    missing: List[Tuple[str, str]] = []
    for kind, target in recipe:
        if kind == "workflow":
            rel = f".github/workflows/{target}"
        else:
            rel = target
        if not _path_exists(repo_root, rel):
            missing.append((kind, target))

    if not missing:
        return ItemStatus(item=item, status="green")

    if len(missing) >= 2:
        note = (
            f"{len(missing)} prerequisites missing "
            f"(recipe-length {len(recipe)})"
        )
        return ItemStatus(
            item=item, status="red", missing=missing, note=note
        )

    # Exactly one missing.
    if len(recipe) >= 3:
        note = (
            f"1 prerequisite missing of {len(recipe)} "
            f"(partial-substrate, operator-hand workaround "
            f"possible)"
        )
        return ItemStatus(
            item=item, status="yellow", missing=missing, note=note
        )
    # Short recipe (<=2 primitives) with one missing -> red.
    note = (
        f"1 prerequisite missing of {len(recipe)} "
        f"(short-recipe, no workaround margin)"
    )
    return ItemStatus(
        item=item, status="red", missing=missing, note=note
    )


# ---------------------------------------------------------------------
# Master-doc parse (Stage 1).
# ---------------------------------------------------------------------


def _read_master_doc(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_master_doc_items(doc_text: str) -> List[str]:
    """Return the Item-IDs declared in the master-doc.

    Parses ``### Item I<N> -- ...`` lines and returns the IDs in
    document order. Used by Stage 1 of the workflow to confirm the
    helper's static ``ITEM_CHECK_RECIPES`` keys are in sync with
    the master-doc.
    """
    found: List[str] = []
    for m in re.finditer(r"###\s+Item\s+(I\d+)\s+--", doc_text):
        found.append(m.group(1))
    return found


def parse_master_doc_prerequisites(
    doc_text: str, item: str
) -> List[str]:
    """Return the **Prerequisites** bullet-list text for one item.

    This is used for soft-cross-check between the static recipes
    and the master-doc narrative. The actual evaluation uses the
    static recipe (more deterministic than free-text bullets).
    """
    # Match the item-block from "### Item I<N> --" up to the next
    # heading at the same or coarser level.
    block_pattern = re.compile(
        rf"###\s+Item\s+{re.escape(item)}\s+--[^\n]*\n"
        rf"(.*?)(?=\n###\s|\n##\s|\Z)",
        re.DOTALL,
    )
    bm = block_pattern.search(doc_text)
    if not bm:
        return []
    block = bm.group(1)
    # Within the block, locate the Prerequisites section.
    pre_pattern = re.compile(
        r"\*\*Prerequisites\*\*\s*:\s*\n(.*?)"
        r"(?=\n\*\*Step-by-Step\*\*|\n\*\*Verification\*\*"
        r"|\n\*\*Rollback\*\*|\n###\s|\n##\s|\Z)",
        re.DOTALL,
    )
    pm = pre_pattern.search(block)
    if not pm:
        return []
    body = pm.group(1)
    bullets: List[str] = []
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("* "):
            bullets.append(s[2:].strip())
    return bullets


# ---------------------------------------------------------------------
# Stage 2 -- per-item check loop.
# ---------------------------------------------------------------------


def check_all_items(repo_root: Path) -> List[ItemStatus]:
    out: List[ItemStatus] = []
    for item in ALL_ITEMS:
        recipe = ITEM_CHECK_RECIPES.get(item, [])
        if not recipe:
            out.append(
                ItemStatus(
                    item=item,
                    status="yellow",
                    note="recipe undefined",
                )
            )
            continue
        out.append(_evaluate_item(item, recipe, repo_root))
    return out


# ---------------------------------------------------------------------
# Stage 3 -- aggregate envelope.
# ---------------------------------------------------------------------


def aggregate_verdict(statuses: Sequence[ItemStatus]) -> str:
    """Reduce ten per-item statuses to one envelope verdict."""
    reds = sum(1 for s in statuses if s.status == "red")
    yellows = sum(1 for s in statuses if s.status == "yellow")
    if reds > 0:
        return VERDICT_BLOCKED
    if yellows >= 3:
        return VERDICT_BLOCKED
    if yellows >= 1:
        return VERDICT_CAUTION
    return VERDICT_READY


def build_envelope(
    statuses: Sequence[ItemStatus],
    *,
    master_doc_items: Optional[Sequence[str]] = None,
    eve_date: str = "2026-06-26",
) -> Dict[str, object]:
    """Produce the verdict-envelope JSON-serialisable dict."""
    verdict = aggregate_verdict(statuses)
    per_item: List[Dict[str, object]] = []
    for s in statuses:
        per_item.append(
            {
                "item": s.item,
                "status": s.status,
                "missing": [
                    {"kind": k, "target": t} for (k, t) in s.missing
                ],
                "note": s.note,
            }
        )
    sync_ok = True
    sync_note = ""
    if master_doc_items is not None:
        if list(master_doc_items) != ALL_ITEMS:
            sync_ok = False
            sync_note = (
                f"master-doc items {list(master_doc_items)} "
                f"do not match helper recipes {ALL_ITEMS}"
            )
    counts = {
        "green": sum(1 for s in statuses if s.status == "green"),
        "yellow": sum(1 for s in statuses if s.status == "yellow"),
        "red": sum(1 for s in statuses if s.status == "red"),
    }
    return {
        "envelope": "operator-items-health-check",
        "version": 1,
        "tag": "tag-78",
        "pre_cutover_eve_date": eve_date,
        "verdict": verdict,
        "counts": counts,
        "items": per_item,
        "master_doc_sync": {
            "ok": sync_ok,
            "note": sync_note,
        },
    }


# ---------------------------------------------------------------------
# CLI entry-point.
# ---------------------------------------------------------------------


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Tag-78 hermetic Operator-Items Health-Check helper "
            "(daily Pre-Cutover-Eve readiness probe)."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root (default: cwd)",
    )
    parser.add_argument(
        "--master-doc",
        default=DEFAULT_MASTER_DOC,
        help=(
            "Path to the Tag-77 master-doc (default: "
            f"{DEFAULT_MASTER_DOC})"
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Write JSON envelope to this path (default: stdout "
            "only)"
        ),
    )
    parser.add_argument(
        "--eve-date",
        default="2026-06-26",
        help="Pre-Cutover-Eve anchor date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-item diagnostics on stderr",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    doc_path = repo_root / args.master_doc
    if not doc_path.exists():
        print(
            f"health_check_operator_items: master-doc not found "
            f"at {doc_path}",
            file=sys.stderr,
        )
        return 2

    doc_text = _read_master_doc(doc_path)
    parsed_items = parse_master_doc_items(doc_text)
    statuses = check_all_items(repo_root)
    envelope = build_envelope(
        statuses,
        master_doc_items=parsed_items,
        eve_date=args.eve_date,
    )

    if not args.quiet:
        for s in statuses:
            line = f"  {s.item}: {s.status}"
            if s.note:
                line += f" ({s.note})"
            print(line, file=sys.stderr)
            for kind, target in s.missing:
                print(
                    f"    - missing {kind}: {target}",
                    file=sys.stderr,
                )

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(envelope, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if not args.quiet:
            print(f"wrote envelope to {out_path}", file=sys.stderr)

    print(json.dumps(envelope, sort_keys=True))

    if envelope["verdict"] == VERDICT_BLOCKED:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
