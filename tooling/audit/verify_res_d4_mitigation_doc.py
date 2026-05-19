#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Verify the Tag-69 RES-D4 High-Residual Mitigation Deep-Dive doc.

Parses
``docs/operations/res-d4-high-residual-mitigation-deep-dive.md``
and asserts the structural invariants of a doc-form-only,
single-RES-Dn-item deep-dive (downstream of the Tag-67
activation pre-mortem §5):

  - All eight sections (§1..§8) are present and in order.
  - §1 scope declares the doc-form-only posture, the informative-
    skizze posture (GOVERNANCE.md §10), the RES-D4-single-item
    focus, and the joint-necessity framing of the three hard-deps.
  - §2 hard-dep inventory enumerates HD-1, HD-2, HD-3 with
    Tag-67 §5 cross-anchored failure-mode codes.
  - §3 mitigation strategies carry one decomposition table per
    hard-dep (3.1, 3.2, 3.3) and an aggregate §3.4.
  - §4 indefinite-deferral justification enumerates re-evaluation
    triggers T1..T7.
  - §5 cross-anchor to Tag-67 + Tag-65 + HARD-edge restatement.
  - §6 OTS-anchor substrate preparation is marked audit-only.
  - §7 peer-roster substrate preparation is marked audit-only.
  - §8 sandbox-boundary carries the three boundaries (no live-OTS,
    no AR-authorisation, no promotion-PR opening).
  - §9 cross-anchor cites ADR-0007, ADR-0014, ADR-0023a,
    ADR-0023b, ADR-0025, GOVERNANCE.md, and Tag-44 / Tag-58 /
    Tag-60 / Tag-63 / Tag-64 / Tag-65 / Tag-66 / Tag-67 / Tag-68
    Tag-N pointers.
  - Doc carries the SPDX CC-BY-4.0 header and a ``-- Reza``
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
    / "res-d4-high-residual-mitigation-deep-dive.md"
)

REQUIRED_SECTIONS = [
    "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.",
]
REQUIRED_HARD_DEPS = ("HD-1", "HD-2", "HD-3")
REQUIRED_TRIGGERS = ("T1", "T2", "T3", "T4", "T5", "T6", "T7")
REQUIRED_RES_D4_FAILURE_CODES = (
    "A1", "A2", "A3", "A4", "A5",
    "B1", "B2", "B3", "B4", "B5",
)
REQUIRED_ADR_ANCHORS = (
    "ADR-0007", "ADR-0014", "ADR-0023a", "ADR-0023b", "ADR-0025",
)
REQUIRED_TAG_PR_ANCHORS = (
    "Tag-44", "Tag-58", "Tag-60",
    "Tag-63", "Tag-64", "Tag-65", "Tag-66", "Tag-67", "Tag-68",
)
REQUIRED_SUB_SECTIONS_S3 = (
    "### 3.1", "### 3.2", "### 3.3", "### 3.4",
)
REQUIRED_SUB_SECTIONS_S8 = (
    "### 8.1", "### 8.2", "### 8.3",
)


def fail(msg: str) -> None:
    sys.stderr.write(f"verify_res_d4_mitigation_doc: FAIL: {msg}\n")
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


def check_title(text: str) -> None:
    first_h1 = None
    for line in text.splitlines():
        if line.startswith("# "):
            first_h1 = line
            break
    if first_h1 is None:
        fail("doc must contain a top-level '# ' title")
    if "Tag-69" not in first_h1:
        fail(f"title missing 'Tag-69': {first_h1!r}")
    if "RES-D4" not in first_h1:
        fail(f"title missing 'RES-D4': {first_h1!r}")
    if "Mitigation" not in first_h1 and "mitigation" not in first_h1:
        fail(f"title missing 'Mitigation': {first_h1!r}")


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
        "RES-D4",
        "Out of scope",
        "joint-necessity",
    )
    for needle in case_sensitive_needles:
        if needle not in normalised:
            fail(f"§1 scope missing required phrase: '{needle}'")
    lowered = normalised.lower()
    case_insensitive_needles = (
        "hard dep",
        "mitigation strategy",
        "re-evaluation trigger",
        "sandbox-boundary",
    )
    for needle in case_insensitive_needles:
        if needle not in lowered:
            fail(
                f"§1 scope missing required deep-dive phrase: '{needle}'"
            )


def check_hard_dep_inventory(section2: str) -> None:
    for hd in REQUIRED_HARD_DEPS:
        if hd not in section2:
            fail(f"§2 hard-dep inventory missing '{hd}'")
    # Tag-67 §5 cross-anchored failure-mode codes must appear in
    # the hard-dep inventory (collectively, not per-row).
    missing_codes = [
        c for c in REQUIRED_RES_D4_FAILURE_CODES if c not in section2
    ]
    if missing_codes:
        fail(
            "§2 hard-dep inventory must cross-anchor all ten Tag-67 §5 "
            f"failure-mode codes; missing: {missing_codes}"
        )
    # Required hard-dep names.
    for needle in ("Live OTS-Calendar", "Peer-Roster", "Audit-Coverage"):
        if needle not in section2:
            fail(f"§2 hard-dep inventory missing dep name '{needle}'")


def check_mitigation_strategies(section3: str) -> None:
    for sub in REQUIRED_SUB_SECTIONS_S3:
        if sub not in section3:
            fail(f"§3 missing sub-section '{sub}'")
    # Each of §3.1, §3.2, §3.3 must carry the Mitigation strategy /
    # Pre-conditions / Post-mitigation residual labels.
    for label in (
        "Mitigation strategy",
        "Pre-conditions",
        "Post-mitigation residual",
        "Cross-anchored failure modes",
    ):
        # Count occurrences: each of §3.1, §3.2, §3.3 should carry
        # one. Allow >=3 to tolerate inline references.
        count = section3.count(label)
        if count < 3:
            fail(
                f"§3 must carry '{label}' in each of §3.1..§3.3 "
                f"(found {count}, expected >=3)"
            )
    # The aggregate §3.4 must explicitly compare against `high` and
    # `medium` ratings.
    if "high" not in section3 or "medium" not in section3:
        fail(
            "§3 must reference 'high' and 'medium' residual ratings "
            "for the joint-clearance transition"
        )


def check_deferral_and_triggers(section4: str) -> None:
    if "indefinite-deferral" not in section4.lower():
        fail("§4 must declare 'indefinite-deferral' as the default")
    for trigger in REQUIRED_TRIGGERS:
        # Triggers appear as table-row first-column entries.
        if f"| {trigger} |" not in section4:
            fail(
                f"§4 must enumerate re-evaluation trigger '{trigger}' "
                f"as a table-row entry"
            )
    # The "does NOT do" disclaimer block keeps the deep-dive scoped.
    if "does NOT do" not in section4 and "does not" not in section4.lower():
        fail("§4 must carry an explicit 'does NOT do' scope disclaimer")


def check_cross_anchor_and_hard_edge(section5: str) -> None:
    if "HARD edge" not in section5 and "HARD-edge" not in section5:
        fail("§5 must restate the Tag-65 §3 HARD-edge framing")
    # Tag-67 and Tag-65 must both be cited in §5.
    for upstream in ("Tag-67", "Tag-65"):
        if upstream not in section5:
            fail(f"§5 must cite upstream '{upstream}' artifact")
    # Hard-dep conjunction restatement.
    for hd in REQUIRED_HARD_DEPS:
        if hd not in section5:
            fail(
                f"§5 HARD-edge restatement must name hard-dep '{hd}'"
            )


def check_substrate_audit_only(section: str, label: str) -> None:
    lowered = section.lower()
    if "audit-only" not in lowered and "audit only" not in lowered:
        fail(f"{label} must be marked 'audit-only' explicitly")


def check_sandbox_boundary(section8: str) -> None:
    for sub in REQUIRED_SUB_SECTIONS_S8:
        if sub not in section8:
            fail(f"§8 missing sandbox-boundary sub-section '{sub}'")
    # Explicit boundary phrases.
    lowered = section8.lower()
    for needle in (
        "no live-ots",
        "no ar-authorisation",
        "no promotion-pr",
    ):
        if needle not in lowered:
            fail(
                f"§8 sandbox-boundary recital missing phrase: '{needle}'"
            )


def check_final_cross_anchor(text: str) -> None:
    """The §9 cross-anchor block (after §8) is the citation list."""
    # §9 is below the last "## 8." section; find the §9 heading.
    s9_idx = text.find("## 9.")
    if s9_idx < 0:
        fail("doc must carry §9 'Cross-Anchor (Citations)' section")
    s9 = text[s9_idx:]
    for adr in REQUIRED_ADR_ANCHORS:
        if adr not in s9:
            fail(f"§9 cross-anchor missing ADR pointer '{adr}'")
    for tag in REQUIRED_TAG_PR_ANCHORS:
        if tag not in s9:
            fail(f"§9 cross-anchor missing Tag-N pointer '{tag}'")
    if "GOVERNANCE" not in s9:
        fail(
            "§9 cross-anchor must reference GOVERNANCE.md "
            "(informative-skizze posture)"
        )


def main() -> int:
    text = load_doc(DOC_PATH)
    check_spdx_and_signature(text)
    check_title(text)
    check_sections_present_and_ordered(text)
    sections = split_sections(text)
    check_scope(sections["1."])
    check_hard_dep_inventory(sections["2."])
    check_mitigation_strategies(sections["3."])
    check_deferral_and_triggers(sections["4."])
    check_cross_anchor_and_hard_edge(sections["5."])
    check_substrate_audit_only(sections["6."], "§6 OTS-substrate-prep")
    check_substrate_audit_only(sections["7."], "§7 peer-roster-prep")
    check_sandbox_boundary(sections["8."])
    check_final_cross_anchor(text)
    print(
        "verify_res_d4_mitigation_doc: OK "
        "(8 in-scope sections + §9 cross-anchor, 3 hard-deps, "
        "7 re-evaluation triggers, audit-only substrate prep, "
        "sandbox-boundary recital intact)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
