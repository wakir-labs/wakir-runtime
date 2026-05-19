#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Verify the Tag-65 Wirelang-Spec v0.4.4 Reserve-Item Promotion-Sequencing doc.

Parses
``docs/operations/wirelang-spec-v0-4-4-promotion-sequencing.md``
and asserts the structural invariants of a doc-form-only
sequencing plan:

  - All seven sections (§1..§7) are present and in order.
  - §1 scope declares the doc-form-only posture, the
    sequence-promotion-only activation policy, and the KW-24
    cutover-T0 gate.
  - §2 carries one sub-section per RES-Dn item (§2.1..§2.5), and
    each sub-section names the three sub-fields:
    substrate-already-pinned, activation-trigger conditions,
    promotion-touch surface.
  - §3 declares a DAG (no cycles) over RES-D1..RES-D5 plus the
    cutover-T0 root, and labels the RES-D4 hard-edge on live
    OTS-anchor activation.
  - §4 declares a five-step promotion-schedule table with one
    row per RES-Dn item and a per-step rationale.
  - §5 has both §5.1 (common A1..A5) and §5.2 (per-item) blocks,
    and §5.1 enumerates all of A1, A2, A3, A4, A5.
  - §6 has §6.1, §6.2, §6.3, §6.4 (pre-merge, post-merge,
    triage-withdrawal, multi-item) sub-cases.
  - §7 declares Sandbox-Scope vs. Out-of-Sandbox-Scope, the
    Operator-Hand-Sandbox-Gap, and a cross-anchor block citing
    ADR-0007, ADR-0023a, ADR-0023b, ADR-0025 plus the relevant
    Tag-N PR pointers.
  - Doc carries the SPDX CC-BY-4.0 header and a `-- Reza`
    signature line.

Exit 0 on green, exit 1 on any failure with a clear stderr
message. Standard library only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DOC_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "operations"
    / "wirelang-spec-v0-4-4-promotion-sequencing.md"
)

REQUIRED_SECTIONS = ["1.", "2.", "3.", "4.", "5.", "6.", "7."]
REQUIRED_RES_D_SUBSECTIONS = ["2.1", "2.2", "2.3", "2.4", "2.5"]
REQUIRED_RES_D_TAGS = ["RES-D1", "RES-D2", "RES-D3", "RES-D4", "RES-D5"]
REQUIRED_S2_SUBFIELDS = (
    "Substrate already pinned",
    "Activation-trigger conditions",
    "Promotion-touch surface",
)
REQUIRED_S5_ACCEPTANCE_LETTERS = ["A1", "A2", "A3", "A4", "A5"]
REQUIRED_S6_SUBCASES = ["6.1", "6.2", "6.3", "6.4"]
REQUIRED_S7_BLOCKS = (
    "Sandbox-Scope",
    "Out-of-Sandbox-Scope",
    "Operator-Hand-Sandbox-Gap",
)
REQUIRED_ADR_ANCHORS = ("ADR-0007", "ADR-0023a", "ADR-0023b", "ADR-0025")
REQUIRED_TAG_PR_ANCHORS = ("Tag-58", "Tag-60", "Tag-63", "Tag-64")


def fail(msg: str) -> None:
    sys.stderr.write(f"verify_promotion_sequencing_doc: FAIL: {msg}\n")
    sys.exit(1)


def load_doc(path: Path) -> str:
    if not path.exists():
        fail(f"doc not found: {path}")
    return path.read_text(encoding="utf-8")


# REUSE-IgnoreStart
def check_spdx_and_signature(text: str) -> None:
    if "SPDX-License-Identifier: CC-BY-4.0" not in text:
        fail("doc must carry SPDX-License-Identifier: CC-BY-4.0 header")
    if not re.search(r"^-- Reza\s*$", text, re.MULTILINE):
        fail("doc must end with '-- Reza' signature line")
# REUSE-IgnoreEnd


def check_sections_present_and_ordered(text: str) -> None:
    last_idx = -1
    for section in REQUIRED_SECTIONS:
        idx = text.find(f"## {section}")
        if idx < 0:
            fail(f"missing top-level section header '## {section}'")
        if idx <= last_idx:
            fail(f"section '{section}' out of order (idx={idx} <= last={last_idx})")
        last_idx = idx


def split_sections(text: str) -> dict:
    """Return {section_marker: section_body} for ## N. headers."""
    result: dict = {}
    positions = []
    for section in REQUIRED_SECTIONS:
        idx = text.find(f"## {section}")
        positions.append((section, idx))
    positions.append(("__end__", len(text)))
    for i in range(len(REQUIRED_SECTIONS)):
        marker, start = positions[i]
        _, end = positions[i + 1]
        result[marker] = text[start:end]
    return result


def check_scope(section1: str) -> None:
    # Normalise whitespace for prose-phrase checks so that markdown
    # line-wrapping inside §1 cannot accidentally split a fixed phrase.
    normalised = re.sub(r"\s+", " ", section1)
    needles = (
        "doc-form only",
        "sequence-promotion-only",
        "KW-24 cutover-T0",
        "RES-D1 .. RES-D5",
        "Out of scope",
    )
    for needle in needles:
        if needle not in normalised:
            fail(f"§1 scope missing required phrase: '{needle}'")


def check_res_d_sections(section2: str) -> None:
    for sub in REQUIRED_RES_D_SUBSECTIONS:
        heading = f"### {sub}"
        if heading not in section2:
            fail(f"§2 missing sub-section heading '{heading}'")
    for tag in REQUIRED_RES_D_TAGS:
        if tag not in section2:
            fail(f"§2 missing reserve item reference '{tag}'")
    for field in REQUIRED_S2_SUBFIELDS:
        # Bold-marker variant in the doc is **field:**; allow either bold
        # or unbold occurrences, but the phrase must show up at least
        # five times (one per RES-Dn block).
        count = section2.count(field)
        if count < 5:
            fail(
                f"§2 sub-field '{field}' must appear at least 5 times "
                f"(once per RES-Dn block); found {count}"
            )


def check_dag(section3: str) -> None:
    if "Dependency-DAG" not in section3:
        fail("§3 must carry the phrase 'Dependency-DAG'")
    if "cutover-T0" not in section3:
        fail("§3 must reference 'cutover-T0' as the DAG root")
    for tag in REQUIRED_RES_D_TAGS:
        if tag not in section3:
            fail(f"§3 DAG missing node '{tag}'")
    # The RES-D4 hard-edge on live OTS is the load-bearing fact;
    # verify it shows up explicitly.
    if "HARD" not in section3 or "OTS" not in section3:
        fail("§3 must declare the RES-D4 HARD edge on live OTS-anchor")
    if "soft" not in section3.lower():
        fail("§3 must distinguish soft edges (RES-D1 -> RES-D5 family)")
    # No-cycles claim.
    if "no cycles" not in section3.lower():
        fail("§3 must claim 'no cycles' for the DAG")


def check_schedule(section4: str) -> None:
    if "Recommended Sequence-Order" not in section4:
        fail("§4 must carry the heading text 'Recommended Sequence-Order'")
    # Five rows in the table.
    for tag in REQUIRED_RES_D_TAGS:
        if tag not in section4:
            fail(f"§4 schedule row missing reserve item '{tag}'")
    # Per-step rationale strings.
    if "Rationale" not in section4:
        fail("§4 schedule table must have a 'Rationale' column header")
    # The schedule is explicitly non-binding.
    if "non-binding" not in section4:
        fail("§4 must declare the schedule 'non-binding'")
    # RES-D4 is explicitly the indefinite-defer step.
    if "indefinite-deferral" not in section4 and "indefinite-defer" not in section4:
        fail("§4 must mark RES-D4 as 'indefinite-deferral'/'indefinite-defer'")


def check_acceptance(section5: str) -> None:
    if "### 5.1" not in section5:
        fail("§5 must carry '### 5.1' common acceptance block")
    if "### 5.2" not in section5:
        fail("§5 must carry '### 5.2' per-item acceptance block")
    s51_idx = section5.find("### 5.1")
    s52_idx = section5.find("### 5.2")
    section51 = section5[s51_idx:s52_idx]
    section52 = section5[s52_idx:]
    for letter in REQUIRED_S5_ACCEPTANCE_LETTERS:
        if f"{letter}:" not in section51:
            fail(f"§5.1 missing acceptance letter '{letter}:'")
    for tag in REQUIRED_RES_D_TAGS:
        if f"**{tag}:**" not in section52:
            fail(f"§5.2 missing per-item entry for '**{tag}:**'")


def check_rollback(section6: str) -> None:
    for sub in REQUIRED_S6_SUBCASES:
        heading = f"### {sub}"
        if heading not in section6:
            fail(f"§6 missing rollback sub-case '{heading}'")
    # Forward-fix-or-revert is the load-bearing choice in §6.2.
    if "forward-fix" not in section6.lower():
        fail("§6 must mention 'forward-fix' option for post-merge regression")
    if "revert" not in section6.lower():
        fail("§6 must mention 'revert' option for post-merge regression")
    if "CEO-Triage" not in section6:
        fail("§6 must reference CEO-Triage as the rollback-arbiter")


def check_sandbox(section7: str) -> None:
    for block in REQUIRED_S7_BLOCKS:
        if block not in section7:
            fail(f"§7 must declare '{block}' explicitly")
    for adr in REQUIRED_ADR_ANCHORS:
        if adr not in section7:
            fail(f"§7 cross-anchor missing ADR pointer '{adr}'")
    for tag in REQUIRED_TAG_PR_ANCHORS:
        if tag not in section7:
            fail(f"§7 cross-anchor missing Tag-N pointer '{tag}'")
    # Doc-form-only posture is repeated for emphasis in §7.3.
    if "doc-form only" not in section7.lower() and "doc-form-only" not in section7.lower():
        fail("§7 must reiterate 'doc-form only' Sandbox posture")


def main() -> int:
    text = load_doc(DOC_PATH)
    check_spdx_and_signature(text)
    check_sections_present_and_ordered(text)
    sections = split_sections(text)
    check_scope(sections["1."])
    check_res_d_sections(sections["2."])
    check_dag(sections["3."])
    check_schedule(sections["4."])
    check_acceptance(sections["5."])
    check_rollback(sections["6."])
    check_sandbox(sections["7."])
    print(
        "verify_promotion_sequencing_doc: OK "
        "(7 sections, 5 RES-Dn entries, DAG no-cycles, 5-row schedule, "
        "A1..A5 acceptance + 5 per-item, 4 rollback sub-cases, "
        "Sandbox boundary explicit)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
