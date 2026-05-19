#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Verify the Tag-67 Wirelang-Spec v0.4.4 Activation Pre-Mortem doc.

Parses
``docs/operations/wirelang-spec-v0-4-4-activation-pre-mortem.md``
and asserts the structural invariants of a doc-form-only
pre-mortem (Tag-44 form-anchor pattern applied to the per-RES-Dn
activation axis):

  - All seven sections (§1..§7) are present and in order.
  - §1 scope declares the doc-form-only posture, the informative-
    skizze posture (GOVERNANCE.md §10), the failure-mode/likelihood/
    impact/mitigation/detection table layout, and the
    five-RES-Dn coverage.
  - §2..§6 each carry one RES-Dn failure-mode-inventory section,
    name the corresponding RES-D tag, include a per-item residual-
    risk sub-section, and enumerate ten failure-mode codes
    (A1..A5, B1..B5).
  - §7 carries the aggregate-risk-map: cross-item failure-mode
    aggregation, cross-item hot spots, residual-risk distribution,
    and a cross-anchor block citing ADR-0007, ADR-0014, ADR-0023a,
    ADR-0023b, ADR-0025 plus the Tag-44 form-anchor citation and
    the Tag-58 / Tag-60 / Tag-63 / Tag-64 / Tag-65 / Tag-66 Tag-N
    PR pointers.
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
    / "wirelang-spec-v0-4-4-activation-pre-mortem.md"
)

REQUIRED_SECTIONS = ["1.", "2.", "3.", "4.", "5.", "6.", "7."]
REQUIRED_RES_D_SECTION_FOR_ITEM = {
    "RES-D1": "2.",
    "RES-D2": "3.",
    "RES-D3": "4.",
    "RES-D4": "5.",
    "RES-D5": "6.",
}
REQUIRED_RES_D_TAGS = ["RES-D1", "RES-D2", "RES-D3", "RES-D4", "RES-D5"]
REQUIRED_FAILURE_CODES = ["A1", "A2", "A3", "A4", "A5",
                          "B1", "B2", "B3", "B4", "B5"]
REQUIRED_ADR_ANCHORS = (
    "ADR-0007", "ADR-0014", "ADR-0023a", "ADR-0023b", "ADR-0025",
)
REQUIRED_TAG_PR_ANCHORS = (
    "Tag-44", "Tag-58", "Tag-60", "Tag-63", "Tag-64", "Tag-65", "Tag-66",
)
REQUIRED_S7_BLOCKS = (
    "Cross-item failure-mode aggregation",
    "Cross-item hot spots",
    "Residual-risk distribution",
    "Cross-anchor",
)
REQUIRED_TABLE_HEADERS = (
    "Failure mode",
    "Likelihood",
    "Impact",
    "Mitigation anchor",
    "Detection path",
)


def fail(msg: str) -> None:
    sys.stderr.write(f"verify_activation_pre_mortem_doc: FAIL: {msg}\n")
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
            fail(
                f"section '{section}' out of order "
                f"(idx={idx} <= last={last_idx})"
            )
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
    normalised = re.sub(r"\s+", " ", section1)
    case_sensitive_needles = (
        "doc-form only",
        "informative skizze",
        "RES-D1 .. RES-D5",
        "Out of scope",
    )
    for needle in case_sensitive_needles:
        if needle not in normalised:
            fail(f"§1 scope missing required phrase: '{needle}'")
    # The four-axis classifier (likelihood / impact / mitigation /
    # detection) is introduced in §1 in lowercase prose; the table
    # headers in §2..§6 use the capitalised form. Allow either.
    lowered = normalised.lower()
    case_insensitive_needles = (
        "failure-mode",
        "likelihood",
        "impact",
        "mitigation",
        "detection",
    )
    for needle in case_insensitive_needles:
        if needle not in lowered:
            fail(
                f"§1 scope missing required four-axis classifier "
                f"phrase: '{needle}'"
            )


def check_res_d_section(
    section_body: str, tag: str, section_marker: str,
) -> None:
    """Each §2..§6 must:
    - cite its RES-D tag in the heading,
    - include all ten failure-mode codes (A1..A5, B1..B5),
    - carry the five table-header columns at least once,
    - carry a residual-risk sub-section.
    """
    if tag not in section_body:
        fail(f"§{section_marker} missing RES-D tag '{tag}'")
    for code in REQUIRED_FAILURE_CODES:
        # codes appear in table rows; check for code as a leading
        # cell entry (`| A1 |` pattern) to avoid false positives on
        # narrative mentions in other sections.
        if f"| {code} |" not in section_body:
            fail(
                f"§{section_marker} ({tag}) missing failure-mode "
                f"row marker '| {code} |'"
            )
    for header in REQUIRED_TABLE_HEADERS:
        if header not in section_body:
            fail(
                f"§{section_marker} ({tag}) missing table header "
                f"column '{header}'"
            )
    # Residual-risk sub-section: heading variant `### N.2 ... residual
    # risk` is the convention.
    if "residual risk" not in section_body.lower():
        fail(
            f"§{section_marker} ({tag}) missing residual-risk "
            f"sub-section"
        )


def check_aggregate_risk_map(section7: str) -> None:
    if "Aggregate-Risk-Map" not in section7:
        fail("§7 must carry the heading 'Aggregate-Risk-Map'")
    for block in REQUIRED_S7_BLOCKS:
        if block not in section7:
            fail(f"§7 must declare '{block}' explicitly")
    for adr in REQUIRED_ADR_ANCHORS:
        if adr not in section7:
            fail(f"§7 cross-anchor missing ADR pointer '{adr}'")
    for tag in REQUIRED_TAG_PR_ANCHORS:
        if tag not in section7:
            fail(f"§7 cross-anchor missing Tag-N pointer '{tag}'")
    # All five RES-Dn items must appear in the residual-risk
    # distribution table.
    for tag in REQUIRED_RES_D_TAGS:
        if tag not in section7:
            fail(f"§7 must reference RES-Dn item '{tag}' in aggregation")
    # GOVERNANCE.md §10 informative-skizze posture is referenced.
    if "GOVERNANCE" not in section7:
        fail(
            "§7 cross-anchor must reference GOVERNANCE.md §10 "
            "(informative-skizze posture)"
        )


def main() -> int:
    text = load_doc(DOC_PATH)
    check_spdx_and_signature(text)
    check_sections_present_and_ordered(text)
    sections = split_sections(text)
    check_scope(sections["1."])
    for tag, marker in REQUIRED_RES_D_SECTION_FOR_ITEM.items():
        check_res_d_section(sections[marker], tag, marker)
    check_aggregate_risk_map(sections["7."])
    print(
        "verify_activation_pre_mortem_doc: OK "
        "(7 sections, 5 RES-Dn per-item failure-mode inventories, "
        "10 failure-mode codes per item, aggregate-risk-map with "
        "cross-item hot spots and residual-risk distribution)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
