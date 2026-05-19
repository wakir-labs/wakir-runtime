#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""
Tag-75 hermetic verifier for the Operator-Hand Welle-7 Day-of-
Recipe-Patch doc.

Source doc:
  docs/operations/operator-hand-welle-7-eve-recipe-patch.md

Welle-7 is the fourth Phase-3c marathon welle with Pre-Auditor-
Section-11-Discipline (IIA-1130), after Welle-3 (Tag-71-Patch),
Welle-5 (Tag-73-Patch), and Welle-6 (Tag-74-Patch). Welle-7 is also
the Final-Sealing-Welle: Post-Welle-7 fires Layer-1-full + Layer-3-
full + Marathon-Final-Acceptance-Live-Verify-Gate to produce the
Global Acceptance-Verdict that gates the Phase-3-COMPLETE-marker
(per pre-cutover-acceptance-run-order.md §3.2 + §5.4 + §7.2).

Welle-7 carries two intertwined hot-spot axes plus the KW-27-
Doppel-Welle directional-cascade asymmetry AND the Final-Sealing-
Authority-Mandate which is unique to Welle-7:

* recovery-drill-live      (Recovery-Drill-Live indicator: drift
                            between canonical R1..R4 trace and live
                            state-backing-snapshot replay outcome)
* iia-1130-pre-auditor     (IIA-1130 Pre-Auditor Decision Tracking,
                            original case per Henrik Tag-39 Welle-
                            6+7-Pre-Audit-Bundle)

This verifier hermetically parses the doc and asserts the five
Pre-Auditor-Signaling-Steps P1..P5 are present, well-formed, and
consistent, plus the four Welle-7-specific Rollback-Pfade (including
the KW-27-Doppel-Welle-Decouple Final-Sealing-Variant) AND the
Welle-7-unique Final-Sealing-Authority semantics.

Exit codes
==========

* 0 -- doc structurally clean, all hard-checks pass.
* 1 -- one or more hard-checks failed (structural defect).
* 2 -- doc not found at expected path.

Hard-checks (exit-1 on miss)
============================

H1  All five Pre-Auditor-Signaling-Steps P1..P5 are present as
    `### P{n} --` section headings.
H2  Each step has the five required sub-fields: Time-Window,
    Action, Owner, Stop-on-Fail, Verdict-Marker.
H3  Each step has a Sandbox-OK flag (yes|no).
H4  Steps P1..P4 are Pre-Sequence (in §1); step P5 is Post-Sequence
    (in §3).
H5  Four Welle-7-specific Rollback-Pfade R-W7-A, R-W7-B, R-W7-C,
    R-W7-D are present (matching Welle-5/6 pattern; D captures the
    KW-27-Doppel-Welle-Decouple Final-Sealing-Variant).
H6  Three Welle-7-specific AR-Hand-Touchpoints TP-W7-1, TP-W7-2,
    TP-W7-3 are present.
H7  Aggregate Welle-7-Day Verdict-Roll-up table is present in §4
    and lists at minimum seven verdict markers including
    WELLE-7-VERDICT-CUTOVER-DONE-MARKER-FIRED,
    WELLE-7-VERDICT-NO-GO, WELLE-7-VERDICT-DOPPEL-DECOUPLE, AND
    WELLE-7-VERDICT-FINAL-SEALING-BLOCK (Final-Sealing-specific).
H8  Pre-Auditor-State-File path `state/welle-7-pre-auditor-
    decision.json` is referenced.
H9  IIA-1130 anchor reference is present.
H10 Henrik Tag-44 Pre-Mortem cross-link is present.
H11 Both hot-spot-axis names are referenced explicitly:
    'recovery-drill-live' AND 'iia-1130-pre-auditor'.
H12 The two Welle-7-specific state-files are referenced:
    `state/welle-7-recovery-drill-live.json` AND
    `state/phase-3-marathon-global-verdict.json` (Final-Sealing
    output target).
H13 Final-Sealing-Authority semantics referenced: doc must include
    the Final-Sealing-Authority concept (`final_sealing_authority`
    in state schema) AND the Phase-3-COMPLETE-Marker-fire-gate
    role of P5.
H14 Global-Acceptance-Verdict-Aggregator helper path is referenced:
    `tooling/ci/aggregate_pyramide_run_order_verdict.py`.

Soft-checks (warn-only, exit-0)
================================

S1  Welle-7-Day date is convergent (KW-27-Mi 2026-07-01, per Tag-57
    pre-cutover-acceptance-run-order). Doc should reference this
    explicitly.
S2  Welle-3-Recipe-Patch (Tag-71), Welle-5-Recipe-Patch (Tag-73),
    AND Welle-6-Recipe-Patch (Tag-74) are referenced as precedents.
S3  KW-27-Doppel-Welle constraint with Welle-6 partner is documented,
    including the cross-modul-out-of-band asymmetry vs. KW-26.
S4  Terminal-Welle property documented (no downstream propagation;
    cascade terminates at Welle-7).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

DEFAULT_DOC = "docs/operations/operator-hand-welle-7-eve-recipe-patch.md"

REQUIRED_P_STEPS = ["P1", "P2", "P3", "P4", "P5"]
REQUIRED_P_SUBFIELDS = [
    "Time-Window",
    "Action",
    "Owner",
    "Stop-on-Fail",
    "Verdict-Marker",
]
REQUIRED_R_PATHS = ["R-W7-A", "R-W7-B", "R-W7-C", "R-W7-D"]
REQUIRED_TP = ["TP-W7-1", "TP-W7-2", "TP-W7-3"]
REQUIRED_VERDICTS = [
    "WELLE-7-VERDICT-CUTOVER-DONE-MARKER-FIRED",
    "WELLE-7-VERDICT-NO-GO",
    "WELLE-7-VERDICT-DOPPEL-DECOUPLE",
    "WELLE-7-VERDICT-FINAL-SEALING-BLOCK",
]
PRE_AUDITOR_STATE_FILE = "state/welle-7-pre-auditor-decision.json"
RECOVERY_DRILL_LIVE_STATE_FILE = "state/welle-7-recovery-drill-live.json"
GLOBAL_VERDICT_STATE_FILE = "state/phase-3-marathon-global-verdict.json"
GLOBAL_VERDICT_AGGREGATOR_PATH = (
    "tooling/ci/aggregate_pyramide_run_order_verdict.py"
)
IIA_ANCHOR = "IIA-1130"
HOT_SPOT_AXES = ["recovery-drill-live", "iia-1130-pre-auditor"]
HENRIK_T44_REFERENCE_PATTERNS = [
    "henrik-tag-44-pre-mortem",
    "Tag-44 Pre-Mortem",
    "Henrik Tag-44 Pre-Mortem",
]
FINAL_SEALING_TOKENS = [
    "final_sealing_authority",
    "Phase-3-COMPLETE",
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

    # H5 -- four Welle-7-specific rollback paths.
    for rpath in REQUIRED_R_PATHS:
        if f"### {rpath} --" not in text:
            result.hard_fail(
                f"H5: rollback path {rpath} section heading not found"
            )

    # H6 -- three Welle-7-specific touchpoints.
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
        verdict_rows = [
            line
            for line in s4_text.splitlines()
            if "->" in line and "WELLE-7-VERDICT-" in line
        ]
        if len(verdict_rows) < 7:
            result.hard_fail(
                f"H7: aggregate verdict table needs >= 7 rows, found {len(verdict_rows)}"
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
    if not any(
        pat.lower() in text.lower() for pat in HENRIK_T44_REFERENCE_PATTERNS
    ):
        result.hard_fail(
            "H10: Henrik Tag-44 Pre-Mortem cross-link not found"
        )

    # H11 -- both hot-spot-axis names explicitly referenced.
    for axis in HOT_SPOT_AXES:
        if axis not in text:
            result.hard_fail(
                f"H11: hot-spot-axis name '{axis}' not explicitly referenced"
            )

    # H12 -- two Welle-7-specific state-files referenced.
    if RECOVERY_DRILL_LIVE_STATE_FILE not in text:
        result.hard_fail(
            f"H12: state file path {RECOVERY_DRILL_LIVE_STATE_FILE} not referenced"
        )
    if GLOBAL_VERDICT_STATE_FILE not in text:
        result.hard_fail(
            f"H12: state file path {GLOBAL_VERDICT_STATE_FILE} not referenced"
        )

    # H13 -- Final-Sealing-Authority semantics.
    for token in FINAL_SEALING_TOKENS:
        if token not in text:
            result.hard_fail(
                f"H13: Final-Sealing-Authority token '{token}' not referenced "
                f"(Welle-7-unique: P5 must gate the Phase-3-COMPLETE marker)"
            )

    # H14 -- Global-Acceptance-Verdict-Aggregator helper path.
    if GLOBAL_VERDICT_AGGREGATOR_PATH not in text:
        result.hard_fail(
            f"H14: Global-Verdict-Aggregator path "
            f"{GLOBAL_VERDICT_AGGREGATOR_PATH} not referenced"
        )

    # S1 -- convergent Welle-7-Day date check.
    if "2026-07-01" not in text or "KW-27" not in text:
        result.soft_warn(
            "S1: doc should reference Welle-7-Day convergent anchor "
            "(KW-27-Mi 2026-07-01, per Tag-57 pre-cutover-acceptance-run-order)"
        )

    # S2 -- precedent references.
    if (
        "Tag-71" not in text
        or "welle-3-eve-recipe-patch" not in text.lower()
    ):
        result.soft_warn(
            "S2: doc should reference Welle-3-Recipe-Patch (Tag-71) as precedent"
        )
    if (
        "Tag-73" not in text
        or "welle-5-eve-recipe-patch" not in text.lower()
    ):
        result.soft_warn(
            "S2: doc should reference Welle-5-Recipe-Patch (Tag-73) as precedent"
        )
    if (
        "Tag-74" not in text
        or "welle-6-eve-recipe-patch" not in text.lower()
    ):
        result.soft_warn(
            "S2: doc should reference Welle-6-Recipe-Patch (Tag-74) as precedent"
        )

    # S3 -- KW-27-Doppel-Welle constraint with Welle-6 + out-of-band
    # cross-modul asymmetry.
    if "Doppel-Welle" not in text or "Welle-6" not in text:
        result.soft_warn(
            "S3: doc should document KW-27-Doppel-Welle constraint with "
            "Welle-6 partner"
        )
    if "out-of-band" not in text.lower() and "out of band" not in text.lower():
        result.soft_warn(
            "S3: doc should document KW-27 cross-modul out-of-band "
            "asymmetry vs. KW-26"
        )

    # S4 -- Terminal-Welle property.
    if "terminal" not in text.lower():
        result.soft_warn(
            "S4: doc should explicitly document Welle-7 terminal-Welle "
            "property (no downstream propagation; cascade terminates here)"
        )

    return result


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Tag-75 verifier for Welle-7 Day-of-Recipe-Patch doc."
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

    print(f"verify_welle_7_recipe_patch_doc :: {doc_path}")
    print(f"  hard_failures: {len(result.hard_failures)}")
    for f in result.hard_failures:
        print(f"    FAIL :: {f}")
    print(f"  soft_warnings: {len(result.soft_warnings)}")
    for w in result.soft_warnings:
        print(f"    WARN :: {w}")

    if result.ok:
        print("VERDICT :: WELLE-7-RECIPE-PATCH-DOC-CLEAN")
        return 0
    print("VERDICT :: WELLE-7-RECIPE-PATCH-DOC-DEFECT")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
