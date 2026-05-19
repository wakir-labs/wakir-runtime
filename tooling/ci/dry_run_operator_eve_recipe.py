#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""
Tag-67 hermetic Dry-Run Probe for the Tag-66 Operator-Hand Cutover-Eve
Final-Recipe.

Purpose
=======

Tag-66 PR #422 landed a single consolidated 864-line day-by-day plan
spanning Cutover-Eve (KW-23 Fr) through T0+6 (KW-25 Di). The Tag-66
verifier (``verify_operator_eve_final_recipe_doc.py``) is a structural
gate — it checks that the 9 sections + sub-anchors exist. It does **not**
walk the per-stage substance: each Eve-Check, T0-step, Welle-Day,
Rollback-Path, and AR-Touchpoint should declare *Owner*, *Action*,
*Sandbox-OK* and a *Verdict-Marker* in a stable shape that the
Operator can mentally trust on Eve-morning at 06:00 CEST.

This Tag-67 helper closes that gap. It is a hermetic per-stage shape-
checker. For every stage in the Tag-66 recipe it executes a **shape-
probe** that confirms:

  * the stage marker (E1..E12 | T0.0..T0.9 | T0+1..T0+6 | R1..R5 | TP1..TP6)
    is present in the document body,
  * the per-stage block declares the required field labels
    (``**Owner**``, ``**Action**``, ``**Sandbox-OK**``, ``**Verdict-Marker**``
    for Eve-Checks and T0-Steps; ``**Trigger**`` / ``**Recovery**`` /
    ``**Time-budget**`` for Rollbacks; ``**Question**`` / ``**Stop-on-
    Fail**`` / ``**AR-Hand**`` for AR-Touchpoints),
  * the per-stage block names a Sandbox-OK or Operator-Hand-Sandbox-Gap
    boundary so the Operator cannot misread it,
  * cross-references named in §7 resolve to existing doc-paths on the
    repo tree (shape-check, not content-walk).

Sandbox Boundary
================

This helper is **hermetic**. It performs zero ``gh api`` calls, zero
podman/cosign invocations, zero network I/O. It only reads markdown +
the on-disk filesystem for cross-reference resolution. See ADR-0020
§10 + Memory ``feedback_sandbox_host_trennung``.

Verdicts
========

  * ``EVE-DRY-RUN-CLEAN``   — every stage shape-probe green.
  * ``EVE-DRY-RUN-DRIFT``   — at least one stage missing a required
                              field label or sandbox-boundary marker.
  * ``EVE-DRY-RUN-DEFECT``  — at least one stage marker absent or a
                              §7 cross-reference unresolved.

Exit codes: 0 on CLEAN, 1 on DRIFT, 2 on DEFECT, 3 on doc-not-found.
Pass ``--json`` for a machine-readable envelope; pass ``--enforce`` to
turn DRIFT into a non-zero exit (default: enforce on).

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# --------------------------------------------------------------------
# Constants — every shape-check anchor for the Tag-66 recipe
# --------------------------------------------------------------------

DOC_REL = Path("docs/operations/operator-hand-cutover-eve-final-recipe.md")

EVE_CHECKS: tuple[str, ...] = tuple(f"E{i}" for i in range(1, 13))
T0_STEPS: tuple[str, ...] = tuple(f"T0.{i}" for i in range(10))
WELLE_DAYS: tuple[str, ...] = tuple(f"T0+{i}" for i in range(1, 7))
WELLE_NUMBERS: tuple[int, ...] = tuple(range(1, 8))
ROLLBACK_PATHS: tuple[str, ...] = tuple(f"R{i}" for i in range(1, 6))
AR_TOUCHPOINTS: tuple[str, ...] = tuple(f"TP{i}" for i in range(1, 7))

EVE_STAGE_FIELDS: tuple[str, ...] = (
    "**Owner**",
    "**Action**",
    "**Sandbox-OK**",
    "**Verdict-Marker**",
)
T0_STAGE_FIELDS: tuple[str, ...] = (
    "**Time**",
    "**Owner**",
    "**Action**",
    "**Sandbox-OK**",
)
ROLLBACK_FIELDS: tuple[str, ...] = (
    "**Trigger**",
    "**Owner**",
    "**Recovery**",
    "**Time-budget**",
    "**Fall-back-pin**",
)
AR_TOUCHPOINT_FIELDS: tuple[str, ...] = (
    "**Question**",
    "**Stop-on-Fail**",
    "**AR-Hand**",
)
WELLE_DAY_REQUIRED_FIELDS: tuple[str, ...] = (
    "**Stand-up**",
    "**Dashboard-Update**",
)
# T0+6 closes with "AR Final Sign-off" instead of "AR Sign-off"; the
# welle-day probe accepts either form (see probe_welle_days).
WELLE_DAY_AR_FIELD_VARIANTS: tuple[str, ...] = (
    "**AR Sign-off**",
    "**AR Final Sign-off**",
)

SANDBOX_BOUNDARY_TOKENS: tuple[str, ...] = (
    "Sandbox-OK",
    "Operator-Hand-Sandbox-Gap",
)

# §7 named cross-references that must resolve on the filesystem.
CROSS_REF_PATHS: tuple[str, ...] = (
    "docs/operations/strict-flip-readiness-map-tag58.md",
    "docs/operations/bulk-activation-pre-walk-recipe.md",
    "docs/operations/branch-protection-required-checks-tag64-companion.md",
    "docs/operations/open-k3-v907-baseline-metadata-carry-forward.md",
    "docs/operations/phase-3c-cutover-runbook.md",
    "docs/operations/phase-3c-welle-1-runbook.md",
    "docs/operations/phase-3c-welle-2-runbook.md",
    "docs/operations/phase-3c-welle-3-runbook.md",
    "docs/operations/phase-3c-welle-4-runbook.md",
    "docs/operations/phase-3c-welle-5-runbook.md",
    "docs/operations/phase-3c-welle-6-runbook.md",
    "docs/operations/phase-3c-welle-7-runbook.md",
    "docs/operations/cosign-strict-mode-activation.md",
    "docs/operations/bulk-activation-subsumption-check-8-coordination.md",
    "docs/operations/phase-3c-welle-status-dashboard-runbook.md",
)


# --------------------------------------------------------------------
# Probe-Result types
# --------------------------------------------------------------------


@dataclass
class StageProbe:
    """A single per-stage shape-probe-result."""

    stage_class: str  # "EVE" | "T0" | "WELLE" | "ROLLBACK" | "AR-TP"
    stage_id: str  # "E1" | "T0.4" | "T0+1" | "R2" | "TP3"
    status: str  # "PASS" | "DRIFT" | "DEFECT"
    detail: str

    def to_dict(self) -> dict:
        return {
            "stage_class": self.stage_class,
            "stage_id": self.stage_id,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class DryRunReport:
    """Aggregate dry-run report across all stage probes."""

    verdict: str = "EVE-DRY-RUN-CLEAN"
    probes: list[StageProbe] = field(default_factory=list)
    cross_ref_misses: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "counts": self.counts,
            "probes": [p.to_dict() for p in self.probes],
            "cross_ref_misses": self.cross_ref_misses,
            "notes": self.notes,
        }


# --------------------------------------------------------------------
# Doc parsing helpers
# --------------------------------------------------------------------


def _find_section_bodies(text: str) -> dict[str, str]:
    """Return {'§1': body, ..., '§9': body} via top-level ``## §N `` markers."""
    section_ids = [f"§{i}" for i in range(1, 10)]
    positions: list[tuple[str, int]] = []
    for sid in section_ids:
        idx = text.find(f"## {sid} ")
        positions.append((sid, idx))
    positions.append(("__end__", len(text)))
    out: dict[str, str] = {}
    for i, (sid, start) in enumerate(positions[:-1]):
        if start < 0:
            out[sid] = ""
            continue
        _, end = positions[i + 1]
        if end < 0:
            end = len(text)
        out[sid] = text[start:end]
    return out


def _find_subsection_body(section_text: str, sub_marker: str) -> str:
    """Return the body of a ``### §X.Y `` subsection within a section text."""
    start = section_text.find(f"### {sub_marker} ")
    if start < 0:
        return ""
    # Find the next "### §" or end-of-section.
    next_idx = section_text.find("\n### §", start + 1)
    if next_idx < 0:
        return section_text[start:]
    return section_text[start:next_idx]


def _find_stage_block_by_marker(
    section_text: str,
    marker_pattern: str,
) -> str:
    """Find a block of text containing a stage marker (e.g. "T0.4:" or "R1:").

    Tag-66 stage subsections start with ``### §X.Y — <Marker>: <Title>``
    or ``### §X.Y — <Marker>`` (touch-point form: ``TP1 — Eve-Verdict``).
    We scan for the marker after the section-prefix, take the body up to
    the next ``### `` marker (case-sensitive intentional — recipe is in
    English ASCII for the §-headings).
    """
    pattern = re.compile(
        r"### §[0-9]+\.[0-9]+ — [^\n]*" + re.escape(marker_pattern) + r"[^\n]*\n",
        re.MULTILINE,
    )
    m = pattern.search(section_text)
    if not m:
        return ""
    start = m.start()
    next_match = re.search(r"\n### §", section_text[start + 1:])
    if next_match:
        end = start + 1 + next_match.start()
    else:
        end = len(section_text)
    return section_text[start:end]


# --------------------------------------------------------------------
# Per-stage shape-probes
# --------------------------------------------------------------------


def _probe_required_fields(
    block: str,
    required: Iterable[str],
) -> tuple[str, str]:
    """Return (status, detail) — DRIFT if any required field missing."""
    missing = [f for f in required if f not in block]
    if missing:
        return ("DRIFT", f"missing field labels: {', '.join(missing)}")
    return ("PASS", "all required field labels present")


def _probe_sandbox_boundary(block: str) -> tuple[str, str]:
    """A stage-block must mark either Sandbox-OK or Operator-Hand-Sandbox-Gap."""
    if not any(tok in block for tok in SANDBOX_BOUNDARY_TOKENS):
        return (
            "DRIFT",
            "stage block declares neither Sandbox-OK nor Operator-Hand-Sandbox-Gap",
        )
    return ("PASS", "sandbox-boundary declared")


def _combine(
    primary: tuple[str, str],
    boundary: tuple[str, str],
) -> tuple[str, str]:
    """DRIFT > PASS; concatenate details."""
    if primary[0] == "PASS" and boundary[0] == "PASS":
        return ("PASS", primary[1])
    statuses = {primary[0], boundary[0]}
    worst = "DRIFT" if "DRIFT" in statuses else "PASS"
    detail = "; ".join(d for d in (primary[1], boundary[1]) if d)
    return (worst, detail)


def probe_eve_checks(s2: str) -> list[StageProbe]:
    out: list[StageProbe] = []
    for check in EVE_CHECKS:
        # Eve-Check marker is "Eve-Check E1" in the ### header.
        block = _find_stage_block_by_marker(s2, f"Eve-Check {check}:")
        if not block:
            out.append(
                StageProbe("EVE", check, "DEFECT", "stage block not found"),
            )
            continue
        fields_res = _probe_required_fields(block, EVE_STAGE_FIELDS)
        boundary_res = _probe_sandbox_boundary(block)
        # E12 is the verdict roll-up — it has Verdict-Marker but no
        # per-stage Action-shape; still required-fields apply.
        status, detail = _combine(fields_res, boundary_res)
        out.append(StageProbe("EVE", check, status, detail))
    return out


def probe_t0_steps(s3: str) -> list[StageProbe]:
    out: list[StageProbe] = []
    for step in T0_STEPS:
        # T0-step header form: "### §3.M — T0.N: <title>" or
        # "### §3.M — T0 Pre-Window-Stand-up (T0.0)".
        # Use two patterns.
        block = _find_stage_block_by_marker(s3, f"{step}:")
        if not block:
            block = _find_stage_block_by_marker(s3, f"({step})")
        if not block:
            out.append(
                StageProbe("T0", step, "DEFECT", "stage block not found"),
            )
            continue
        fields_res = _probe_required_fields(block, T0_STAGE_FIELDS)
        boundary_res = _probe_sandbox_boundary(block)
        status, detail = _combine(fields_res, boundary_res)
        out.append(StageProbe("T0", step, status, detail))
    return out


def probe_welle_days(s4: str) -> list[StageProbe]:
    out: list[StageProbe] = []
    for day in WELLE_DAYS:
        block = _find_stage_block_by_marker(s4, f"{day} ")
        if not block:
            out.append(
                StageProbe("WELLE", day, "DEFECT", "welle-day block not found"),
            )
            continue
        # Stand-up + Dashboard-Update are stable per-day labels.
        primary = _probe_required_fields(block, WELLE_DAY_REQUIRED_FIELDS)
        # AR sign-off has two stable forms: ``AR Sign-off`` (mid-week
        # On-Call mode + pair-mode days) and ``AR Final Sign-off``
        # (T0+6 close-out only). At least one must be present.
        if any(v in block for v in WELLE_DAY_AR_FIELD_VARIANTS):
            ar_res = ("PASS", "AR sign-off label present")
        else:
            ar_res = (
                "DRIFT",
                "missing AR sign-off label "
                f"({', '.join(WELLE_DAY_AR_FIELD_VARIANTS)})",
            )
        # Welle-day blocks don't have explicit Sandbox-OK markers inline —
        # they reference per-Welle runbooks. We instead verify the
        # ``runbook.md`` cross-reference is present.
        if "runbook.md" not in block:
            boundary_res = (
                "DRIFT",
                "welle-day block missing per-welle runbook cross-reference",
            )
        else:
            boundary_res = ("PASS", "per-welle runbook cross-reference present")
        # Combine primary + ar + boundary.
        merged = _combine(primary, ar_res)
        status, detail = _combine(merged, boundary_res)
        out.append(StageProbe("WELLE", day, status, detail))
    return out


def probe_rollbacks(s5: str) -> list[StageProbe]:
    out: list[StageProbe] = []
    for rb in ROLLBACK_PATHS:
        block = _find_stage_block_by_marker(s5, f"Rollback-Path {rb}:")
        if not block:
            out.append(
                StageProbe("ROLLBACK", rb, "DEFECT", "rollback block not found"),
            )
            continue
        fields_res = _probe_required_fields(block, ROLLBACK_FIELDS)
        # Rollback blocks need a Time-budget that names ``min`` or ``h``.
        if not re.search(r"\*\*Time-budget\*\*:.*(min|h)", block):
            extra = ("DRIFT", "Time-budget missing min/h unit")
        else:
            extra = ("PASS", "Time-budget unit present")
        status, detail = _combine(fields_res, extra)
        out.append(StageProbe("ROLLBACK", rb, status, detail))
    return out


def probe_ar_touchpoints(s6: str) -> list[StageProbe]:
    out: list[StageProbe] = []
    for tp in AR_TOUCHPOINTS:
        block = _find_stage_block_by_marker(s6, f"{tp}:")
        if not block:
            out.append(
                StageProbe("AR-TP", tp, "DEFECT", "AR touchpoint block not found"),
            )
            continue
        fields_res = _probe_required_fields(block, AR_TOUCHPOINT_FIELDS)
        # AR-touchpoint must declare a date in 2026-MM-DD form.
        if not re.search(r"2026-\d{2}-\d{2}", block):
            extra = ("DRIFT", "AR touchpoint missing 2026-MM-DD calendar anchor")
        else:
            extra = ("PASS", "calendar anchor present")
        status, detail = _combine(fields_res, extra)
        out.append(StageProbe("AR-TP", tp, status, detail))
    return out


# --------------------------------------------------------------------
# Cross-reference resolution
# --------------------------------------------------------------------


def probe_cross_refs(repo_root: Path) -> list[str]:
    """Return a list of cross-ref paths that do NOT resolve on disk."""
    misses: list[str] = []
    for rel in CROSS_REF_PATHS:
        p = repo_root / rel
        if not p.exists():
            misses.append(rel)
    return misses


# --------------------------------------------------------------------
# Top-level orchestration
# --------------------------------------------------------------------


def run_dry_run(repo_root: Path) -> DryRunReport:
    report = DryRunReport()
    doc_path = repo_root / DOC_REL
    if not doc_path.exists():
        report.verdict = "EVE-DRY-RUN-DEFECT"
        report.notes.append(f"doc not found: {DOC_REL}")
        return report

    text = doc_path.read_text(encoding="utf-8")
    sections = _find_section_bodies(text)

    s2 = sections.get("§2", "")
    s3 = sections.get("§3", "")
    s4 = sections.get("§4", "")
    s5 = sections.get("§5", "")
    s6 = sections.get("§6", "")

    if not all((s2, s3, s4, s5, s6)):
        report.verdict = "EVE-DRY-RUN-DEFECT"
        missing = [
            sid
            for sid, body in (("§2", s2), ("§3", s3), ("§4", s4), ("§5", s5), ("§6", s6))
            if not body
        ]
        report.notes.append(f"missing top-level sections: {', '.join(missing)}")
        return report

    report.probes.extend(probe_eve_checks(s2))
    report.probes.extend(probe_t0_steps(s3))
    report.probes.extend(probe_welle_days(s4))
    report.probes.extend(probe_rollbacks(s5))
    report.probes.extend(probe_ar_touchpoints(s6))

    report.cross_ref_misses = probe_cross_refs(repo_root)

    # Roll-up counts.
    counts = {"PASS": 0, "DRIFT": 0, "DEFECT": 0}
    for p in report.probes:
        counts[p.status] = counts.get(p.status, 0) + 1
    counts["TOTAL"] = len(report.probes)
    counts["CROSS_REF_MISSES"] = len(report.cross_ref_misses)
    report.counts = counts

    # Verdict.
    if counts["DEFECT"] > 0 or counts["CROSS_REF_MISSES"] > 0:
        report.verdict = "EVE-DRY-RUN-DEFECT"
    elif counts["DRIFT"] > 0:
        report.verdict = "EVE-DRY-RUN-DRIFT"
    else:
        report.verdict = "EVE-DRY-RUN-CLEAN"

    return report


# --------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------


def _print_human(report: DryRunReport) -> None:
    print(f"verdict: {report.verdict}")
    print(f"counts:  {report.counts}")
    if report.notes:
        print("notes:")
        for n in report.notes:
            print(f"  - {n}")
    if report.cross_ref_misses:
        print("cross_ref_misses:")
        for m in report.cross_ref_misses:
            print(f"  - {m}")
    drift_or_defect = [p for p in report.probes if p.status != "PASS"]
    if drift_or_defect:
        print("non-PASS stages:")
        for p in drift_or_defect:
            print(f"  [{p.status}] {p.stage_class}/{p.stage_id}: {p.detail}")
    else:
        print("all stage probes PASS")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="dry_run_operator_eve_recipe",
        description="Hermetic per-stage shape-checker for Tag-66 Eve-Recipe.",
    )
    ap.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repo root (default: parents[2] of this script).",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON envelope instead of human-readable output.",
    )
    ap.add_argument(
        "--enforce",
        choices=("true", "false"),
        default="true",
        help="If 'true' (default), exit non-zero on DRIFT/DEFECT.",
    )
    args = ap.parse_args(argv)

    report = run_dry_run(args.repo_root)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        _print_human(report)

    if args.enforce == "false":
        return 0
    if report.verdict == "EVE-DRY-RUN-CLEAN":
        return 0
    if report.verdict == "EVE-DRY-RUN-DRIFT":
        return 1
    # DEFECT (either doc missing, section missing, stage block missing,
    # or cross-ref unresolved).
    if "doc not found" in " ".join(report.notes):
        return 3
    return 2


if __name__ == "__main__":
    sys.exit(main())
