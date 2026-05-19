#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""
Tag-71 hermetic verifier for the Operator-Hand Welle-3 Day-of-
Recipe-Patch doc.

Source doc:
  docs/operations/operator-hand-welle-3-eve-recipe-patch.md

Welle-3 is the only Phase-3c marathon welle with Pre-Auditor-
Section-11-Discipline (IIA-1130). This verifier hermetically
parses the doc and asserts the five Pre-Auditor-Signaling-Steps
P1..P5 are present, well-formed, and consistent.

Exit codes
==========

* 0 -- doc structurally clean, all hard-checks pass.
* 1 -- one or more hard-checks failed (structural defect).
* 2 -- doc not found at expected path.

Hard-checks (exit-1 on miss)
============================

H1  All five Pre-Auditor-Signaling-Steps P1..P5 are present as
    `### P{n} --` section headings.
H2  Each step has the four required sub-fields: Time-Window,
    Action, Owner, Stop-on-Fail, Verdict-Marker.
H3  Each step has a Sandbox-OK flag (yes|no).
H4  Steps P1..P4 are Pre-Sequence (in §1); step P5 is Post-Sequence
    (in §3).
H5  Three Welle-3-specific Rollback-Pfade R-W3-A, R-W3-B, R-W3-C
    are present.
H6  Three Welle-3-specific AR-Hand-Touchpoints TP-W3-1, TP-W3-2,
    TP-W3-3 are present.
H7  Aggregate Welle-3-Day Verdict-Roll-up table is present in §4
    and lists at minimum six verdict markers including
    WELLE-3-VERDICT-CUTOVER-DONE and WELLE-3-VERDICT-NO-GO.
H8  Pre-Auditor-State-File path `state/welle-3-pre-auditor-
    decision.json` is referenced.
H9  IIA-1130 anchor reference is present.
H10 Henrik Tag-44 Pre-Mortem cross-link is present.

Soft-checks (warn-only, exit-0)
================================

S1  Welle-3-Day exact date is intentionally ambiguous (Tag-66 vs.
    ADR-0066 vs. Brief Tag-71). Doc should document this
    explicitly.
S2  Doc lists the three time-anchor candidates.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

DEFAULT_DOC = "docs/operations/operator-hand-welle-3-eve-recipe-patch.md"

REQUIRED_P_STEPS = ["P1", "P2", "P3", "P4", "P5"]
REQUIRED_P_SUBFIELDS = [
    "Time-Window",
    "Action",
    "Owner",
    "Stop-on-Fail",
    "Verdict-Marker",
]
REQUIRED_R_PATHS = ["R-W3-A", "R-W3-B", "R-W3-C"]
REQUIRED_TP = ["TP-W3-1", "TP-W3-2", "TP-W3-3"]
REQUIRED_VERDICTS = [
    "WELLE-3-VERDICT-CUTOVER-DONE",
    "WELLE-3-VERDICT-NO-GO",
]
PRE_AUDITOR_STATE_FILE = "state/welle-3-pre-auditor-decision.json"
IIA_ANCHOR = "IIA-1130"
HENRIK_T44_REFERENCE_PATTERNS = [
    "henrik-tag-44-pre-mortem",
    "Tag-44 Pre-Mortem",
    "Henrik Tag-44 Pre-Mortem",
]


class VerifyResult:
    def __init__(self) -> None:
        self.hard_failures: List[str] = []
        self.soft_warnings: List[str] = []

    def hard_fail(self, msg: str) -> None:
        self.hard_failures.append(msg)

    def soft_warn(self, msg: str) -> None:
        self.soft_warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.hard_failures


def _read_doc(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_p_step_block(text: str, step: str) -> str:
    """Return the block text from `### {step} --` up to the next
    `### ` heading or section divider."""
    pattern = re.compile(
        rf"###\s+{re.escape(step)}\s+--[^\n]*\n(.*?)(?=\n###\s|\n##\s|\Z)",
        re.DOTALL,
    )
    m = pattern.search(text)
    return m.group(1) if m else ""


def _has_subfield(block: str, name: str) -> bool:
    # Subfields appear as **Time-Window**, **Action**, etc.
    return bool(re.search(rf"\*\*{re.escape(name)}\*\*", block))


def _has_sandbox_flag(block: str) -> bool:
    return bool(re.search(r"\*\*Sandbox-OK\*\*\s*:\s*(yes|no)", block))


def _section_index(text: str) -> Dict[str, Tuple[int, int]]:
    """Return mapping from section heading like '§1' to (start, end)
    character offsets in the doc."""
    headings = list(re.finditer(r"^##\s+(§\d+)[^\n]*$", text, re.MULTILINE))
    out: Dict[str, Tuple[int, int]] = {}
    for i, h in enumerate(headings):
        start = h.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        out[h.group(1)] = (start, end)
    return out


def verify(doc_path: Path) -> VerifyResult:
    result = VerifyResult()
    if not doc_path.exists():
        result.hard_fail(f"doc not found at {doc_path}")
        return result
    text = _read_doc(doc_path)

    # H1, H2, H3 -- per-step structural checks.
    for step in REQUIRED_P_STEPS:
        block = _extract_p_step_block(text, step)
        if not block.strip():
            result.hard_fail(f"H1: step {step} section heading not found")
            continue
        for sub in REQUIRED_P_SUBFIELDS:
            if not _has_subfield(block, sub):
                result.hard_fail(
                    f"H2: step {step} missing required subfield '{sub}'"
                )
        if not _has_sandbox_flag(block):
            result.hard_fail(f"H3: step {step} missing Sandbox-OK flag")

    # H4 -- P1..P4 in §1, P5 in §3.
    sections = _section_index(text)
    if "§1" not in sections:
        result.hard_fail("H4: §1 (Pre-Sequence) section not found")
    if "§3" not in sections:
        result.hard_fail("H4: §3 (Post-Sequence) section not found")
    if "§1" in sections and "§3" in sections:
        s1_start, s1_end = sections["§1"]
        s3_start, s3_end = sections["§3"]
        s1_text = text[s1_start:s1_end]
        s3_text = text[s3_start:s3_end]
        for step in ["P1", "P2", "P3", "P4"]:
            if f"### {step} --" not in s1_text:
                result.hard_fail(
                    f"H4: step {step} expected in §1 Pre-Sequence"
                )
        if "### P5 --" not in s3_text:
            result.hard_fail("H4: step P5 expected in §3 Post-Sequence")

    # H5 -- three Welle-3-specific rollback paths.
    for rpath in REQUIRED_R_PATHS:
        if f"### {rpath} --" not in text:
            result.hard_fail(
                f"H5: rollback path {rpath} section heading not found"
            )

    # H6 -- three Welle-3-specific touchpoints.
    for tp in REQUIRED_TP:
        if f"### {tp} --" not in text:
            result.hard_fail(
                f"H6: AR-Hand-Touchpoint {tp} section heading not found"
            )

    # H7 -- aggregate verdict table.
    if "§4" not in sections:
        result.hard_fail("H7: §4 (Aggregate-Verdict-Roll-up) not found")
    else:
        s4_start, s4_end = sections["§4"]
        s4_text = text[s4_start:s4_end]
        for verdict in REQUIRED_VERDICTS:
            if verdict not in s4_text:
                result.hard_fail(
                    f"H7: verdict marker {verdict} not in §4"
                )
        # Count verdict-rows: lines starting with | and containing ->
        verdict_rows = [
            line for line in s4_text.splitlines() if "->" in line and "WELLE-3-VERDICT-" in line
        ]
        if len(verdict_rows) < 6:
            result.hard_fail(
                f"H7: aggregate verdict table needs >= 6 rows, found {len(verdict_rows)}"
            )

    # H8 -- pre-auditor state file path.
    if PRE_AUDITOR_STATE_FILE not in text:
        result.hard_fail(
            f"H8: state file path {PRE_AUDITOR_STATE_FILE} not referenced"
        )

    # H9 -- IIA-1130 anchor.
    if IIA_ANCHOR not in text:
        result.hard_fail(f"H9: {IIA_ANCHOR} anchor not referenced")

    # H10 -- Henrik Tag-44 Pre-Mortem reference.
    if not any(pat.lower() in text.lower() for pat in HENRIK_T44_REFERENCE_PATTERNS):
        result.hard_fail(
            "H10: Henrik Tag-44 Pre-Mortem cross-link not found"
        )

    # S1, S2 -- soft date-ambiguity check.
    if "Tag-66" not in text or "ADR-0066" not in text or "Brief Tag-71" not in text:
        result.soft_warn(
            "S2: doc should reference all three Welle-3-Day-Date anchors "
            "(Tag-66 Mi, ADR-0066 KW-25-Mo, Brief Tag-71 Fr)"
        )

    return result


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Tag-71 verifier for Welle-3 Day-of-Recipe-Patch doc."
    )
    parser.add_argument(
        "--doc",
        type=Path,
        default=Path(DEFAULT_DOC),
        help=f"path to the recipe-patch doc (default: {DEFAULT_DOC})",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="repo root (default: cwd)",
    )
    args = parser.parse_args(argv)

    doc_path = args.doc
    if not doc_path.is_absolute():
        doc_path = args.repo_root / doc_path

    result = verify(doc_path)

    if not doc_path.exists():
        print(f"DOC-NOT-FOUND :: {doc_path}", file=sys.stderr)
        return 2

    print(f"verify_welle_3_recipe_patch_doc :: {doc_path}")
    print(f"  hard_failures: {len(result.hard_failures)}")
    for f in result.hard_failures:
        print(f"    FAIL :: {f}")
    print(f"  soft_warnings: {len(result.soft_warnings)}")
    for w in result.soft_warnings:
        print(f"    WARN :: {w}")

    if result.ok:
        print("VERDICT :: WELLE-3-RECIPE-PATCH-DOC-CLEAN")
        return 0
    print("VERDICT :: WELLE-3-RECIPE-PATCH-DOC-DEFECT")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
