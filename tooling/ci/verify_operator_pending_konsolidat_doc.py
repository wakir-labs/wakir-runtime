#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""
Tag-77 hermetic verifier for the Operator-Hand Pending-Items
Konsolidat Master-Doc.

Source doc:
  docs/operations/operator-hand-pending-items-konsolidat.md

The Konsolidat-Doc aggregates all Operator-Hand-Sandbox-Gap-Items
that emerged during the Tag-50..Tag-76 spawn corridor into a
single Pre-Cutover-Eve walkthrough checklist. It covers ten
operator-hand item clusters (I1..I10) across ten sections (§1..§10).

This verifier hermetically parses the doc and asserts:

* Ten Operator-Hand-Items I1..I10 are present, well-formed, and
  consistent.
* Each Item has the six required subfields (Owner, Timing,
  Prerequisites, Step-by-Step, Verification, Rollback).
* Ten sections §1..§10 are present.
* The §9 Verdict-Marker table lists the four canonical verdict
  markers (EVE-VERDICT-ALL-CLEAN, -PARTIAL-HOLD, -DEFER,
  -EMERGENCY-HOLD).
* The §9 AR-Hand-Touchpoint table lists TP-EVE-1..TP-EVE-3.
* The §10 AR-Vorzeichen "Halt vor Phase 4" verbatim text is
  reproduced unchanged from the Tag-65 AR-Signal.
* The Pre-Cutover-Eve date anchor (2026-06-26) is referenced.
* The Predecessor-Doc-References include the canonical recipe docs.

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

DEFAULT_DOC = "docs/operations/operator-hand-pending-items-konsolidat.md"

REQUIRED_ITEMS = [
    "I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9", "I10",
]
REQUIRED_ITEM_SUBFIELDS = [
    "Owner",
    "Timing",
    "Prerequisites",
    "Step-by-Step",
    "Verification",
    "Rollback",
]
REQUIRED_SECTIONS = [
    "§1", "§2", "§3", "§4", "§5", "§6", "§7", "§8", "§9", "§10",
]
REQUIRED_VERDICTS = [
    "EVE-VERDICT-ALL-CLEAN",
    "EVE-VERDICT-PARTIAL-HOLD",
    "EVE-VERDICT-DEFER",
    "EVE-VERDICT-EMERGENCY-HOLD",
]
REQUIRED_TOUCHPOINTS = ["TP-EVE-1", "TP-EVE-2", "TP-EVE-3"]
PRE_CUTOVER_EVE_DATE = "2026-06-26"
AR_VORZEICHEN_VERBATIM_TOKENS = [
    "Phase-3-Marathon ends at Welle-7 cutover",
    "explicit AR-Hand re-arm signal",
    "No Phase-4 substrate enters the planning",
]
REQUIRED_PREDECESSOR_PATHS = [
    "docs/operations/operator-hand-production-bringup-recipe.md",
    "docs/operations/operator-hand-cutover-eve-final-recipe.md",
    "docs/operations/g1-g2-last-mile-operator-checklist.md",
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


def _extract_item_block(text: str, item: str) -> str:
    """Extracts the text of an Item-Block (### Item I<N> -- ...)."""
    pattern = re.compile(
        rf"###\s+Item\s+{re.escape(item)}\s+--[^\n]*\n(.*?)"
        rf"(?=\n###\s|\n##\s|\Z)",
        re.DOTALL,
    )
    m = pattern.search(text)
    return m.group(1) if m else ""


def _has_subfield(block: str, name: str) -> bool:
    """Subfield-Marker like '**Owner**:' or '**Step-by-Step**:'."""
    return bool(re.search(rf"\*\*{re.escape(name)}\*\*\s*:", block))


def _section_index(text: str) -> Dict[str, Tuple[int, int]]:
    """Builds an index of §N section-headings."""
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


def _check_frontmatter(text: str, result: VerifyResult) -> None:
    if not text.startswith("---\n"):
        result.hard_fail("F1: frontmatter delimiter not at top")
        return
    end = text.find("\n---\n", 4)
    if end < 0:
        result.hard_fail("F2: frontmatter not closed")
        return
    fm = text[4:end]
    for key in (
        "title:",
        "status:",
        "owner:",
        "tag:",
        "audience:",
        "created:",
    ):
        if key not in fm:
            result.hard_fail(f"F3: frontmatter missing key '{key}'")
    if 'tag: "tag-77"' not in fm:
        result.hard_fail("F4: tag value must be tag-77")
    if 'owner: "kai"' not in fm:
        result.hard_fail("F5: owner must be kai")
    if 'status: "active"' not in fm:
        result.hard_fail("F6: status must be active")


def verify(doc_path: Path) -> VerifyResult:
    result = VerifyResult()
    if not doc_path.exists():
        result.hard_fail(f"doc not found at {doc_path}")
        return result
    text = _read_doc(doc_path)

    # F1..F6 -- frontmatter checks.
    _check_frontmatter(text, result)

    # H1, H2 -- per-item structural checks.
    for item in REQUIRED_ITEMS:
        block = _extract_item_block(text, item)
        if not block.strip():
            result.hard_fail(
                f"H1: item {item} section heading not found"
            )
            continue
        for sub in REQUIRED_ITEM_SUBFIELDS:
            if not _has_subfield(block, sub):
                result.hard_fail(
                    f"H2: item {item} missing required subfield "
                    f"'{sub}'"
                )

    # H3 -- ten sections §1..§10.
    sections = _section_index(text)
    for sec in REQUIRED_SECTIONS:
        if sec not in sections:
            result.hard_fail(f"H3: section {sec} not found")

    # H4 -- §9 Verdict-Marker table.
    if "§9" in sections:
        s9_text = text[sections["§9"][0]:sections["§9"][1]]
        for v in REQUIRED_VERDICTS:
            if v not in s9_text:
                result.hard_fail(
                    f"H4: §9 missing verdict marker '{v}'"
                )
        for tp in REQUIRED_TOUCHPOINTS:
            if tp not in s9_text:
                result.hard_fail(
                    f"H4: §9 missing touchpoint '{tp}'"
                )

    # H5 -- §10 AR-Vorzeichen verbatim tokens. We normalise the
    # text by stripping blockquote markers '> ' and collapsing
    # whitespace, so that multi-line quotes still match.
    if "§10" in sections:
        s10_text = text[sections["§10"][0]:sections["§10"][1]]
        normalised = re.sub(r"\s+", " ", s10_text.replace("> ", ""))
        for tok in AR_VORZEICHEN_VERBATIM_TOKENS:
            if tok not in normalised:
                result.hard_fail(
                    f"H5: §10 missing AR-Vorzeichen verbatim "
                    f"token '{tok}'"
                )

    # H6 -- Pre-Cutover-Eve date anchor.
    if PRE_CUTOVER_EVE_DATE not in text:
        result.hard_fail(
            f"H6: Pre-Cutover-Eve date anchor "
            f"'{PRE_CUTOVER_EVE_DATE}' not referenced"
        )

    # H7 -- Predecessor-Doc references.
    for p in REQUIRED_PREDECESSOR_PATHS:
        if p not in text:
            result.hard_fail(
                f"H7: required predecessor-doc reference "
                f"'{p}' missing"
            )

    # H8 -- Section-to-Item mapping (I1 in §1, etc.).
    item_section_map = {
        "I1": "§1",
        "I2": "§2",
        "I3": "§2",
        "I4": "§3",
        "I5": "§4",
        "I6": "§5",
        "I7": "§5",
        "I8": "§6",
        "I9": "§7",
        "I10": "§8",
    }
    for item, sec in item_section_map.items():
        if sec in sections:
            sec_text = text[sections[sec][0]:sections[sec][1]]
            if f"Item {item} --" not in sec_text:
                result.hard_fail(
                    f"H8: item {item} expected in section {sec}"
                )

    # S1 -- soft warning if the doc is shorter than 5000 chars
    # (likely under-substantiated).
    if len(text) < 5000:
        result.soft_warn(
            f"S1: doc length {len(text)} chars is below 5000 "
            f"chars threshold; may be under-substantiated"
        )

    return result


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Tag-77 verifier for the Operator-Hand Pending-Items "
            "Konsolidat Master-Doc."
        )
    )
    parser.add_argument(
        "--doc",
        default=DEFAULT_DOC,
        help=(
            "Path to the Konsolidat-Doc (default: "
            f"{DEFAULT_DOC})"
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root (default: cwd)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress soft warnings on stdout",
    )
    parser.add_argument(
        "--aggregate-verdict",
        action="store_true",
        help=(
            "Emit aggregate-verdict-state stub (Pre-Cutover-Eve "
            "verdict-roll-up mode)"
        ),
    )
    args = parser.parse_args(argv)
    doc_path = Path(args.repo_root) / args.doc
    if not doc_path.exists():
        print(
            f"verify_operator_pending_konsolidat_doc: "
            f"doc not found at {doc_path}",
            file=sys.stderr,
        )
        return 2
    res = verify(doc_path)
    for f in res.hard_failures:
        print(f"HARD-FAIL: {f}", file=sys.stderr)
    if not args.quiet:
        for w in res.soft_warnings:
            print(f"SOFT-WARN: {w}", file=sys.stderr)
    if args.aggregate_verdict:
        # In aggregate-verdict mode the helper additionally emits
        # a one-line state-summary on stdout. The actual closure-
        # record-reading is operator-hand-substrate and is not
        # part of the hermetic verifier.
        verdict = (
            "EVE-VERDICT-ALL-CLEAN"
            if res.ok
            else "EVE-VERDICT-PARTIAL-HOLD"
        )
        print(f"aggregate-verdict: {verdict}")
    if not res.ok:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
