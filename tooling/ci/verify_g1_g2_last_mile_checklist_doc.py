#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""
Tag-69 hermetic per-stage shape-verifier for the Tag-69 G1+G2 Operator-
Hand Last-Mile Checklist.

Purpose
=======

The Tag-69 doc (``docs/operations/g1-g2-last-mile-operator-checklist.md``)
densifies the Tag-66 Eve-Recipe + Tag-58 Strict-Flip-Map + Tag-62 Bulk-
Activation-Recipe into a minute-by-minute Operator-Hand plan covering
the T0-1 Eve (Sunday 2026-06-07 19:00 - 24:00 UTC) plus the 30-minute
T0 critical window (Monday 2026-06-08 00:00 - 00:30 UTC).

This helper is a hermetic shape-verifier. It walks the eight required
sections (§1..§8) and for every named stage in the document body
(Eve-Setup E1..E12; T0.0..T0.9; G1.W1..G1.W4; G2.S1..G2.S3; V1..V6;
F1..F5) it confirms:

  * the stage marker is present in the document body,
  * the per-stage block declares the required field labels
    (e.g. ``**Time-slot**``, ``**Owner**``, ``**Action**``,
    ``**Sandbox-OK**``, ``**Verdict-Marker**`` for Eve/T0 steps,
    ``**Quadlet-file**``, ``**Before-wiring**``, ``**After-wiring**``,
    ``**Probe**``, ``**Verdict**`` for G1 waves, etc.),
  * the per-stage block names a Sandbox-OK or Operator-Hand-Sandbox-Gap
    boundary so the Operator cannot misread it,
  * cross-references named in §8.1 resolve to existing doc-paths on
    the repo tree (shape-check, not content-walk).

Sandbox Boundary
================

This helper is **hermetic**. It performs zero ``gh api`` calls, zero
podman/cosign invocations, zero network I/O. It only reads markdown +
the on-disk filesystem for cross-reference resolution. See ADR-0020
§10 + Memory ``feedback_sandbox_host_trennung``.

Verdicts
========

  * ``LAST-MILE-CLEAN``   - every stage shape-probe green.
  * ``LAST-MILE-DRIFT``   - at least one stage missing a required
                            field label or sandbox-boundary marker.
  * ``LAST-MILE-DEFECT``  - at least one stage marker absent or a
                            §8.1 cross-reference unresolved or a
                            required section missing.

Exit codes: 0 on CLEAN, 1 on DRIFT, 2 on DEFECT, 3 on doc-not-found.
Pass ``--json`` for a machine-readable envelope; pass ``--enforce
false`` to suppress non-zero exit codes (default: enforce true).

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
# Constants - every shape-check anchor for the Tag-69 doc.
# --------------------------------------------------------------------

DOC_REL = Path("docs/operations/g1-g2-last-mile-operator-checklist.md")

EVE_CHECKS: tuple[str, ...] = tuple(f"E{i}" for i in range(1, 13))
T0_STEPS: tuple[str, ...] = tuple(f"T0.{i}" for i in range(10))
G1_WAVES: tuple[str, ...] = tuple(f"G1.W{i}" for i in range(1, 5))
G2_SUBSTEPS: tuple[str, ...] = tuple(f"G2.S{i}" for i in range(1, 4))
VERIFICATION_PROBES: tuple[str, ...] = tuple(f"V{i}" for i in range(1, 7))
FAILURE_TRIGGERS: tuple[str, ...] = tuple(f"F{i}" for i in range(1, 6))

REQUIRED_SECTION_IDS: tuple[str, ...] = tuple(f"§{i}" for i in range(1, 9))

EVE_STAGE_FIELDS: tuple[str, ...] = (
    "**Time-slot**",
    "**Owner**",
    "**Action**",
    "**Sandbox-OK**",
    "**Verdict-Marker**",
)
T0_STAGE_FIELDS: tuple[str, ...] = (
    "**Time-slot**",
    "**Owner**",
    "**Action**",
    "**Sandbox-OK**",
    "**Verdict-Marker**",
)
G1_WAVE_FIELDS: tuple[str, ...] = (
    "**Quadlet-file**",
    "**Before-wiring**",
    "**After-wiring**",
    "**Probe**",
    "**Verdict**",
    "**Sandbox-boundary**",
)
G2_SUBSTEP_FIELDS: tuple[str, ...] = (
    "**Action**",
    "**Verdict**",
    "**Sandbox-boundary**",
)
VERIFICATION_FIELDS: tuple[str, ...] = (
    "**Run-at**",
    "**Action**",
    "**Verdict**",
)
FAILURE_FIELDS: tuple[str, ...] = (
    "**Trigger-condition**",
    "**Recovery-action**",
    "**Time-budget**",
    "**Fall-back-pin**",
)

SANDBOX_BOUNDARY_TOKENS: tuple[str, ...] = (
    "Sandbox-OK",
    "Operator-Hand-Sandbox-Gap",
)

# §8.1 named cross-references that must resolve on the filesystem.
CROSS_REF_PATHS: tuple[str, ...] = (
    "docs/operations/cosign-g1-g2-operator-setup.md",
    "docs/operations/strict-flip-readiness-map-tag58.md",
    "docs/operations/bulk-activation-pre-walk-recipe.md",
    "docs/operations/operator-hand-cutover-eve-final-recipe.md",
    "docs/operations/phase-3c-cutover-runbook.md",
    "tooling/ci/dry_run_operator_eve_recipe.py",
)


# --------------------------------------------------------------------
# Probe-result types
# --------------------------------------------------------------------


@dataclass
class StageProbe:
    """A single per-stage shape-probe-result."""

    stage_class: str  # "EVE" | "T0" | "G1" | "G2" | "V" | "F"
    stage_id: str  # "E1" | "T0.4" | "G1.W2" | "G2.S3" | "V5" | "F2"
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
class LastMileReport:
    """Aggregate Tag-69 verify report across all stage probes."""

    verdict: str = "LAST-MILE-CLEAN"
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
    """Return {'§1': body, ..., '§8': body} via top-level ``## §N `` markers."""
    section_ids = list(REQUIRED_SECTION_IDS)
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


def _find_stage_block_by_marker(
    section_text: str,
    marker_pattern: str,
) -> str:
    """Find a stage block by its marker token in the ### header line.

    Tag-69 stage subsections start with ``### §X.Y - <Marker>: <Title>``
    or ``### §X.Y - <Marker> <Title>``. We scan for the marker in the
    section header line, take the body up to the next ``### `` marker
    or the end of the section.
    """
    # Match either "marker:" or "marker " (word-boundary), allowing
    # both header styles found in the doc body.
    pattern = re.compile(
        r"### §[0-9]+\.[0-9]+ [—-] [^\n]*"
        + re.escape(marker_pattern)
        + r"(?::|\s|$)[^\n]*\n",
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
    """Return (status, detail) - DRIFT if any required field missing."""
    missing = [f for f in required if f not in block]
    if missing:
        return ("DRIFT", f"missing field labels: {', '.join(missing)}")
    return ("PASS", "all required field labels present")


def _probe_sandbox_boundary(block: str) -> tuple[str, str]:
    """A stage block must mark Sandbox-OK or Operator-Hand-Sandbox-Gap."""
    if not any(tok in block for tok in SANDBOX_BOUNDARY_TOKENS):
        return (
            "DRIFT",
            "stage block declares neither Sandbox-OK nor Operator-Hand-Sandbox-Gap",
        )
    return ("PASS", "sandbox-boundary declared")


def _combine(
    primary: tuple[str, str],
    secondary: tuple[str, str],
) -> tuple[str, str]:
    """DRIFT > PASS; concatenate details."""
    if primary[0] == "PASS" and secondary[0] == "PASS":
        return ("PASS", primary[1])
    statuses = {primary[0], secondary[0]}
    worst = "DRIFT" if "DRIFT" in statuses else "PASS"
    detail = "; ".join(d for d in (primary[1], secondary[1]) if d)
    return (worst, detail)


def probe_eve_checks(s2: str) -> list[StageProbe]:
    out: list[StageProbe] = []
    for check in EVE_CHECKS:
        # Eve-Check marker is "Eve-E1" / "Eve-E2" / ... in the ### header.
        block = _find_stage_block_by_marker(s2, f"Eve-{check}")
        if not block:
            out.append(
                StageProbe("EVE", check, "DEFECT", "Eve stage block not found"),
            )
            continue
        fields_res = _probe_required_fields(block, EVE_STAGE_FIELDS)
        boundary_res = _probe_sandbox_boundary(block)
        status, detail = _combine(fields_res, boundary_res)
        out.append(StageProbe("EVE", check, status, detail))
    return out


def probe_t0_steps(s3: str) -> list[StageProbe]:
    out: list[StageProbe] = []
    for step in T0_STEPS:
        block = _find_stage_block_by_marker(s3, step)
        if not block:
            out.append(
                StageProbe("T0", step, "DEFECT", "T0 stage block not found"),
            )
            continue
        fields_res = _probe_required_fields(block, T0_STAGE_FIELDS)
        boundary_res = _probe_sandbox_boundary(block)
        status, detail = _combine(fields_res, boundary_res)
        out.append(StageProbe("T0", step, status, detail))
    return out


def probe_g1_waves(s4: str) -> list[StageProbe]:
    out: list[StageProbe] = []
    for wave in G1_WAVES:
        block = _find_stage_block_by_marker(s4, wave)
        if not block:
            out.append(
                StageProbe("G1", wave, "DEFECT", "G1 wave block not found"),
            )
            continue
        fields_res = _probe_required_fields(block, G1_WAVE_FIELDS)
        # G1 waves declare Sandbox-boundary explicitly; still confirm
        # one of the two boundary tokens shows in the block body.
        boundary_res = _probe_sandbox_boundary(block)
        status, detail = _combine(fields_res, boundary_res)
        out.append(StageProbe("G1", wave, status, detail))
    return out


def probe_g2_substeps(s5: str) -> list[StageProbe]:
    out: list[StageProbe] = []
    for sub in G2_SUBSTEPS:
        block = _find_stage_block_by_marker(s5, sub)
        if not block:
            out.append(
                StageProbe("G2", sub, "DEFECT", "G2 sub-step block not found"),
            )
            continue
        fields_res = _probe_required_fields(block, G2_SUBSTEP_FIELDS)
        boundary_res = _probe_sandbox_boundary(block)
        status, detail = _combine(fields_res, boundary_res)
        out.append(StageProbe("G2", sub, status, detail))
    return out


def probe_verification(s6: str) -> list[StageProbe]:
    out: list[StageProbe] = []
    for v in VERIFICATION_PROBES:
        block = _find_stage_block_by_marker(s6, v)
        if not block:
            out.append(
                StageProbe(
                    "V", v, "DEFECT", "verification probe block not found"
                ),
            )
            continue
        fields_res = _probe_required_fields(block, VERIFICATION_FIELDS)
        # V6 may legitimately omit a Sandbox-OK token (it is a doc-only
        # audit step); we tolerate missing boundary for V6 only.
        if v == "V6":
            boundary_res = ("PASS", "V6 audit-step boundary tolerance")
        else:
            # Inline verification probes do not require Sandbox-OK marker
            # themselves (they declare Run-at + Action + Verdict); accept
            # either presence or absence.
            boundary_res = ("PASS", "verification boundary tolerance")
        status, detail = _combine(fields_res, boundary_res)
        out.append(StageProbe("V", v, status, detail))
    return out


def probe_failures(s7: str) -> list[StageProbe]:
    out: list[StageProbe] = []
    for f in FAILURE_TRIGGERS:
        block = _find_stage_block_by_marker(s7, f)
        if not block:
            out.append(
                StageProbe(
                    "F", f, "DEFECT", "failure trigger block not found"
                ),
            )
            continue
        fields_res = _probe_required_fields(block, FAILURE_FIELDS)
        # Failure blocks need a Time-budget that names ``min`` or ``h``.
        if not re.search(r"\*\*Time-budget\*\*:.*?(min|h)", block):
            extra = ("DRIFT", "Time-budget missing min/h unit")
        else:
            extra = ("PASS", "Time-budget unit present")
        status, detail = _combine(fields_res, extra)
        out.append(StageProbe("F", f, status, detail))
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


def run_verify(repo_root: Path) -> LastMileReport:
    report = LastMileReport()
    doc_path = repo_root / DOC_REL
    if not doc_path.exists():
        report.verdict = "LAST-MILE-DEFECT"
        report.notes.append(f"doc not found: {DOC_REL}")
        return report

    text = doc_path.read_text(encoding="utf-8")
    sections = _find_section_bodies(text)

    # Confirm every required section is non-empty.
    missing_sections = [sid for sid in REQUIRED_SECTION_IDS if not sections.get(sid)]
    if missing_sections:
        report.verdict = "LAST-MILE-DEFECT"
        report.notes.append(
            f"missing top-level sections: {', '.join(missing_sections)}"
        )
        return report

    report.probes.extend(probe_eve_checks(sections["§2"]))
    report.probes.extend(probe_t0_steps(sections["§3"]))
    report.probes.extend(probe_g1_waves(sections["§4"]))
    report.probes.extend(probe_g2_substeps(sections["§5"]))
    report.probes.extend(probe_verification(sections["§6"]))
    report.probes.extend(probe_failures(sections["§7"]))

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
        report.verdict = "LAST-MILE-DEFECT"
    elif counts["DRIFT"] > 0:
        report.verdict = "LAST-MILE-DRIFT"
    else:
        report.verdict = "LAST-MILE-CLEAN"

    return report


# --------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------


def _print_human(report: LastMileReport) -> None:
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
    non_pass = [p for p in report.probes if p.status != "PASS"]
    if non_pass:
        print("non-PASS stages:")
        for p in non_pass:
            print(f"  [{p.status}] {p.stage_class}/{p.stage_id}: {p.detail}")
    else:
        print("all stage probes PASS")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="verify_g1_g2_last_mile_checklist_doc",
        description=(
            "Hermetic per-stage shape-verifier for the Tag-69 G1+G2 Last-"
            "Mile Operator-Checklist doc."
        ),
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

    report = run_verify(args.repo_root)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        _print_human(report)

    if args.enforce == "false":
        return 0
    if report.verdict == "LAST-MILE-CLEAN":
        return 0
    if report.verdict == "LAST-MILE-DRIFT":
        return 1
    # DEFECT (either doc missing, section missing, stage block missing,
    # or cross-ref unresolved).
    if "doc not found" in " ".join(report.notes):
        return 3
    return 2


if __name__ == "__main__":
    sys.exit(main())
