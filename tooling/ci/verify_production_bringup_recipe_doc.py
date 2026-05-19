#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""
Tag-76 hermetic verifier for the Operator-Hand Production-Bringup
Recipe doc.

Source doc:
  docs/operations/operator-hand-production-bringup-recipe.md

The Production-Bringup-Recipe is the Day-after-Welle-7-Sign-off
Operator-Hand companion to the Tag-66 Eve-Recipe and the Tag-75
Welle-7-Day-Patch. It covers Day-1 (2026-07-04 Sa) through Day-7
(2026-07-10 Fr) -- the seven operative days that follow Welle-7-
Sign-off (2026-07-03 Fr).

This verifier hermetically parses the doc and asserts:

* Five Production-Bringup-Steps B1..B5 are present, well-formed,
  and consistent.
* Four Rollback-Pfade R-PB-A..R-PB-D are present.
* Three AR-Hand-Touchpoints TP-PB-1..TP-PB-3 are present.
* The Day-1..Day-7 date anchors are referenced verbatim.
* The AR-Vorzeichen "Halt vor Phase 4" verbatim text from Tag-65
  is reproduced unchanged in section 9.1.
* The Aggregate-Verdict-Roll-up table in section 7 lists the
  canonical verdict markers.
* The Phase-3-COMPLETE-marker-fire-step (B1) and the Phase-4-
  freeze-pin governance (section 9) are both present.

Exit codes
==========

* 0 -- doc structurally clean, all hard-checks pass.
* 1 -- one or more hard-checks failed (structural defect).
* 2 -- doc not found at expected path.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

DEFAULT_DOC = "docs/operations/operator-hand-production-bringup-recipe.md"

REQUIRED_B_STEPS = ["B1", "B2", "B3", "B4", "B5"]
REQUIRED_B_SUBFIELDS = [
    "Time-Window",
    "Action",
    "Owner",
    "Stop-on-Fail",
    "Verdict-Marker",
]
REQUIRED_R_PATHS = ["R-PB-A", "R-PB-B", "R-PB-C", "R-PB-D"]
REQUIRED_TP = ["TP-PB-1", "TP-PB-2", "TP-PB-3"]
REQUIRED_VERDICTS = [
    "PB-VERDICT-PHASE-3-CLOSED-CLEAN",
    "PB-VERDICT-PHASE-3-NO-FIRE",
    "PB-VERDICT-PHASE-3-DEFERRED",
    "PB-VERDICT-PHASE-3-DEFECT-WINDOW",
]
DAY_N_DATES = [
    "2026-07-04",  # Day-1 Sa
    "2026-07-05",  # Day-2 So
    "2026-07-06",  # Day-3 Mo
    "2026-07-07",  # Day-4 Di
    "2026-07-08",  # Day-5 Mi
    "2026-07-09",  # Day-6 Do
    "2026-07-10",  # Day-7 Fr
]
PHASE_3_COMPLETE_MARKER_FILE = "state/phase-3-complete-marker.json"
GLOBAL_VERDICT_STATE_FILE = "state/phase-3-marathon-global-verdict.json"
PHASE_4_HOLD_MARKER = "PHASE-4-HOLD-VOR-RE-ARM"
TAG66_EVE_RECIPE_PATH = "operator-hand-cutover-eve-final-recipe.md"
TAG75_WELLE7_PATCH_PATH = "operator-hand-welle-7-eve-recipe-patch.md"
AR_VORZEICHEN_VERBATIM_TOKENS = [
    "Phase-3-Marathon ends at Welle-7 cutover",
    "explicit AR-Hand re-arm signal",
    "no Phase-4 substrate enters the planning",
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


def _extract_b_step_block(text: str, step: str) -> str:
    pattern = re.compile(
        rf"###\s+{re.escape(step)}\s+--[^\n]*\n(.*?)(?=\n###\s|\n##\s|\Z)",
        re.DOTALL,
    )
    m = pattern.search(text)
    return m.group(1) if m else ""


def _has_subfield(block: str, name: str) -> bool:
    return bool(re.search(rf"\*\*{re.escape(name)}\*\*", block))


def _has_sandbox_flag(block: str) -> bool:
    return bool(re.search(r"\*\*Sandbox-OK\*\*\s*:\s*(yes|no)", block))


def _section_index(text: str) -> Dict[str, Tuple[int, int]]:
    headings = list(re.finditer(r"^##\s+\S\d+[^\n]*$", text, re.MULTILINE))
    # Filter to actual section-headings starting with the section
    # marker U+00A7.
    out: Dict[str, Tuple[int, int]] = {}
    section_headings: List[re.Match] = []
    for h in re.finditer(r"^##\s+(§\d+)[^\n]*$", text, re.MULTILINE):
        section_headings.append(h)
    for i, h in enumerate(section_headings):
        key = h.group(1)
        start = h.start()
        end = (
            section_headings[i + 1].start()
            if i + 1 < len(section_headings)
            else len(text)
        )
        out[key] = (start, end)
    return out


def verify(doc_path: Path) -> VerifyResult:
    result = VerifyResult()
    if not doc_path.exists():
        result.hard_fail(f"doc not found at {doc_path}")
        return result
    text = _read_doc(doc_path)

    # H1, H2, H3 -- per-step structural checks.
    for step in REQUIRED_B_STEPS:
        block = _extract_b_step_block(text, step)
        if not block.strip():
            result.hard_fail(f"H1: step {step} section heading not found")
            continue
        for sub in REQUIRED_B_SUBFIELDS:
            if not _has_subfield(block, sub):
                result.hard_fail(
                    f"H2: step {step} missing required subfield '{sub}'"
                )
        if not _has_sandbox_flag(block):
            result.hard_fail(f"H3: step {step} missing Sandbox-OK flag")

    # H4 -- step-to-section mapping.
    sections = _section_index(text)
    for required_section in ("§1", "§2", "§3", "§4"):
        if required_section not in sections:
            result.hard_fail(
                f"H4: section {required_section} not found"
            )

    if all(
        s in sections for s in ("§1", "§2", "§3", "§4")
    ):
        s1_text = text[sections["§1"][0]:sections["§1"][1]]
        s2_text = text[sections["§2"][0]:sections["§2"][1]]
        s3_text = text[sections["§3"][0]:sections["§3"][1]]
        s4_text = text[sections["§4"][0]:sections["§4"][1]]
        if "### B1 --" not in s1_text:
            result.hard_fail(
                "H4: B1 expected in section 1 (Phase-3-COMPLETE-Marker-Fire-Step)"
            )
        if "### B2 --" not in s2_text:
            result.hard_fail(
                "H4: B2 expected in section 2 (Stability-Window)"
            )
        if "### B3 --" not in s3_text:
            result.hard_fail(
                "H4: B3 expected in section 3 (J3-K3-Closure)"
            )
        if "### B4 --" not in s4_text:
            result.hard_fail(
                "H4: B4 expected in section 4 (Marathon-Final-Bilanz-Day)"
            )
        if "### B5 --" not in s4_text:
            result.hard_fail(
                "H4: B5 expected in section 4 (Marathon-Final-Bilanz-Day)"
            )

    # H5 -- four Production-Bringup rollback paths.
    for rpath in REQUIRED_R_PATHS:
        if f"### {rpath} --" not in text:
            result.hard_fail(
                f"H5: rollback path {rpath} section heading not found"
            )

    # H6 -- three Production-Bringup touchpoints.
    for tp in REQUIRED_TP:
        if f"### {tp} --" not in text:
            result.hard_fail(
                f"H6: AR-Hand-Touchpoint {tp} section heading not found"
            )

    # H7 -- aggregate verdict table in section 7.
    if "§7" not in sections:
        result.hard_fail("H7: section 7 (Aggregate-Verdict-Roll-up) not found")
    else:
        s7_start, s7_end = sections["§7"]
        s7_text = text[s7_start:s7_end]
        for verdict in REQUIRED_VERDICTS:
            if verdict not in s7_text:
                result.hard_fail(
                    f"H7: verdict marker {verdict} not in section 7"
                )
        verdict_rows = [
            line
            for line in s7_text.splitlines()
            if "->" in line and "PB-VERDICT-" in line
        ]
        if len(verdict_rows) < 7:
            result.hard_fail(
                f"H7: aggregate verdict table needs >= 7 rows, "
                f"found {len(verdict_rows)}"
            )

    # H8 -- all seven Day-N date anchors.
    for date_str in DAY_N_DATES:
        if date_str not in text:
            result.hard_fail(
                f"H8: Day-N date anchor {date_str} not referenced"
            )

    # H9 -- AR-Vorzeichen verbatim tokens.
    for token in AR_VORZEICHEN_VERBATIM_TOKENS:
        if token not in text:
            result.hard_fail(
                f"H9: AR-Vorzeichen 'Halt vor Phase 4' verbatim token "
                f"'{token}' not reproduced (Tag-65 verbatim must appear in section 9.1)"
            )

    # H10 -- Phase-3-COMPLETE-marker state file path.
    if PHASE_3_COMPLETE_MARKER_FILE not in text:
        result.hard_fail(
            f"H10: marker state file path {PHASE_3_COMPLETE_MARKER_FILE} not referenced"
        )

    # H11 -- Phase-3-marathon-global-verdict state file path.
    if GLOBAL_VERDICT_STATE_FILE not in text:
        result.hard_fail(
            f"H11: global-verdict state file path {GLOBAL_VERDICT_STATE_FILE} "
            f"not referenced (Welle-7-Day P5 hand-off input)"
        )

    # H12 -- Tag-75 Welle-7-Day Patch cross-link + P5 reference.
    if TAG75_WELLE7_PATCH_PATH not in text:
        result.hard_fail(
            f"H12: Tag-75 Welle-7-Day Patch cross-link "
            f"({TAG75_WELLE7_PATCH_PATH}) not referenced"
        )
    if "P5" not in text:
        result.hard_fail(
            "H12: Welle-7-Day P5 step name not referenced "
            "(Tag-75 P5 produces the global-verdict input to B1)"
        )

    # H13 -- PHASE-4-HOLD-VOR-RE-ARM substrate-marker.
    if PHASE_4_HOLD_MARKER not in text:
        result.hard_fail(
            f"H13: substrate-marker {PHASE_4_HOLD_MARKER} not referenced"
        )

    # H14 -- Tag-66 Eve-Recipe cross-link.
    if TAG66_EVE_RECIPE_PATH not in text:
        result.hard_fail(
            f"H14: Tag-66 Eve-Recipe cross-link "
            f"({TAG66_EVE_RECIPE_PATH}) not referenced "
            "(Eve-Recipe section 9 is the governance-pin source)"
        )

    # S1 -- Welle-7-Sign-off-Freitag anchor.
    if "2026-07-03" not in text:
        result.soft_warn(
            "S1: Welle-7-Sign-off-Freitag anchor 2026-07-03 not referenced"
        )

    # S2 -- four IIA-1130 Welle-Patches references.
    for tag_n in ("Tag-71", "Tag-73", "Tag-74", "Tag-75"):
        if tag_n not in text:
            result.soft_warn(
                f"S2: precedent Welle-Patch {tag_n} not referenced"
            )

    # S3 -- Aggregator helper path (Tag-77 follow-on).
    if "tooling/ci/aggregate_production_bringup_verdict.py" not in text:
        result.soft_warn(
            "S3: Tag-77 aggregator helper path "
            "tooling/ci/aggregate_production_bringup_verdict.py not referenced"
        )

    # S4 -- Day-7 Marathon-Final-Bilanz inbox path.
    if "2026-07-10-marathon-final-bilanz.md" not in text:
        result.soft_warn(
            "S4: Day-7 Marathon-Final-Bilanz inbox path "
            "2026-07-10-marathon-final-bilanz.md not referenced"
        )

    return result


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Tag-76 verifier for Production-Bringup-Recipe doc."
    )
    parser.add_argument(
        "--doc",
        type=Path,
        default=Path(DEFAULT_DOC),
        help=f"path to the recipe doc (default: {DEFAULT_DOC})",
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

    print(f"verify_production_bringup_recipe_doc :: {doc_path}")
    print(f"  hard_failures: {len(result.hard_failures)}")
    for f in result.hard_failures:
        print(f"    FAIL :: {f}")
    print(f"  soft_warnings: {len(result.soft_warnings)}")
    for w in result.soft_warnings:
        print(f"    WARN :: {w}")

    if result.ok:
        print("VERDICT :: PRODUCTION-BRINGUP-RECIPE-DOC-CLEAN")
        return 0
    print("VERDICT :: PRODUCTION-BRINGUP-RECIPE-DOC-DEFECT")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
