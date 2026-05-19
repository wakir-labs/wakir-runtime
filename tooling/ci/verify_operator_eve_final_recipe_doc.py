#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""
Verify the Tag-66 Operator-Hand-Cutover-Eve Final-Recipe doc.

Parses docs/operations/operator-hand-cutover-eve-final-recipe.md and
asserts the consolidated day-by-day plan is structurally complete:

  - All 9 sections (§1..§9) present in order.
  - §1 scope table covers Eve + T0..T0+6 (8 Operator-Touch-Days).
  - §2 Pre-Cutover-Eve-Checklist covers E1..E12 (12 checks).
  - §3 Cutover-T0-Sequence covers T0.0..T0.9 (10 steps).
  - §4 Welle-Day-by-Day covers T0+1..T0+6 (6 sub-sections).
  - §5 Rollback-Trigger-Pfade covers R1..R5 (5 paths).
  - §6 AR-Hand-Touchpoint-Checklist covers TP1..TP6 (6 touchpoints).
  - §7 Cross-Reference matrix has at least 4 sub-tables.
  - §8 Sandbox-Boundary explicit Sandbox-Scope + Out-of-Sandbox-Scope.
  - §9 AR-Vorzeichen "Halt vor Phase 4" + PHASE-4-HOLD-VOR-RE-ARM
    pin + PHASE-4-RE-ARMED trigger.

Exit 0 on green, exit 1 on any failure with a clear stderr message.
stdlib only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DOC_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "operations"
    / "operator-hand-cutover-eve-final-recipe.md"
)

REQUIRED_SECTIONS = ["§1", "§2", "§3", "§4", "§5", "§6", "§7", "§8", "§9"]

REQUIRED_EVE_CHECKS = [f"E{i}" for i in range(1, 13)]  # E1..E12
REQUIRED_T0_STEPS = [f"T0.{i}" for i in range(10)]  # T0.0..T0.9
REQUIRED_WELLE_DAYS = [f"T0+{i}" for i in range(1, 7)]  # T0+1..T0+6
REQUIRED_ROLLBACKS = [f"R{i}" for i in range(1, 6)]  # R1..R5
REQUIRED_TOUCHPOINTS = [f"TP{i}" for i in range(1, 7)]  # TP1..TP6

# Section 4 covers T0+1..T0+6: detect §4.1..§4.6 sub-headings.
REQUIRED_S4_SUBSECTIONS = [f"§4.{i}" for i in range(1, 7)]

# Section 5 covers R1..R5 sub-headings explicitly.
REQUIRED_S5_SUBSECTIONS = [f"§5.{i}" for i in range(1, 6)]

# Section 6 covers TP1..TP6.
REQUIRED_S6_SUBSECTIONS = [f"§6.{i}" for i in range(1, 7)]

# Section 7 has four cross-ref subtables (§7.1..§7.4).
REQUIRED_S7_SUBSECTIONS = [f"§7.{i}" for i in range(1, 5)]

# Section 9 must have at least 6 sub-anchors (§9.1..§9.6).
REQUIRED_S9_SUBSECTIONS = [f"§9.{i}" for i in range(1, 7)]


def fail(msg: str) -> None:
    sys.stderr.write(f"verify_operator_eve_final_recipe_doc: FAIL: {msg}\n")
    sys.exit(1)


def load_doc(path: Path) -> str:
    if not path.exists():
        fail(f"doc not found: {path}")
    return path.read_text(encoding="utf-8")


def check_sections_present_and_ordered(text: str) -> None:
    last_idx = -1
    for section in REQUIRED_SECTIONS:
        # Section headers use "## §N — ..." format.
        idx = text.find(f"## {section} ")
        if idx < 0:
            fail(f"missing section header for {section}")
        if idx <= last_idx:
            fail(f"section {section} out of order")
        last_idx = idx


def split_sections(text: str) -> dict:
    """Return {section_marker: section_body} for §1..§9."""
    result: dict = {}
    positions = []
    for section in REQUIRED_SECTIONS:
        idx = text.find(f"## {section} ")
        positions.append((section, idx))
    positions.append(("__end__", len(text)))
    for i in range(len(REQUIRED_SECTIONS)):
        marker, start = positions[i]
        _, end = positions[i + 1]
        body = text[start:end]
        result[marker] = body
    return result


def check_section1_scope_table(s1: str) -> None:
    """§1.1 scope-table covers Eve + T0..T0+6."""
    expected_rows = ["Eve", "T0", "T0+1", "T0+2", "T0+3", "T0+4", "T0+5", "T0+6"]
    for row in expected_rows:
        if f"| {row} |" not in s1:
            fail(f"§1 scope-table missing row for '{row}'")
    if "2026-05-29" not in s1:
        fail("§1 must name the Cutover-Eve date 2026-05-29")
    if "2026-06-08" not in s1:
        fail("§1 must name the Cutover-T0 date 2026-06-08")


def check_section2_eve_checklist(s2: str) -> None:
    """§2 has E1..E12 sub-checks."""
    for check in REQUIRED_EVE_CHECKS:
        marker = f"Eve-Check {check}"
        if marker not in s2:
            fail(f"§2 missing eve-check '{marker}'")
    # Each check must show a Verdict-Marker line.
    verdict_count = len(re.findall(r"\*\*Verdict-Marker\*\*", s2))
    if verdict_count < 12:
        fail(f"§2 needs >= 12 Verdict-Marker entries, got {verdict_count}")
    # The aggregated GO/HOLD verdict must be present.
    if "EVE-VERDICT-GO" not in s2 or "EVE-VERDICT-HOLD" not in s2:
        fail("§2 must define EVE-VERDICT-GO / EVE-VERDICT-HOLD aggregate")


def check_section3_t0_sequence(s3: str) -> None:
    """§3 covers T0.0..T0.9 sub-steps."""
    for step in REQUIRED_T0_STEPS:
        marker = f"§3.{int(step.split('.')[1]) + 1}"
        # Each T0.N step is in a numbered §3.M subsection
        # (T0.0 → §3.1, T0.1 → §3.2, ..., T0.9 → §3.10).
        if marker not in s3:
            fail(
                f"§3 missing subsection {marker} for T0-step {step}"
            )
        if step not in s3:
            fail(f"§3 missing T0-step '{step}'")
    # Strict-Flip-PR and Walking-Skeleton anchors must appear.
    if "Strict-Flip-PR" not in s3:
        fail("§3 must reference the Strict-Flip-PR merge step")
    if "Walking-Skeleton" not in s3:
        fail("§3 must reference Walking-Skeleton Post-Activate-Verify")
    if "POST-ACTIVATE-CLEAN" not in s3:
        fail("§3 must surface POST-ACTIVATE-CLEAN as the T0.4 success marker")


def check_section4_welle_day_by_day(s4: str) -> None:
    """§4 has T0+1..T0+6 sub-sections covering Welle-2..Welle-7."""
    for sub in REQUIRED_S4_SUBSECTIONS:
        if sub not in s4:
            fail(f"§4 missing subsection {sub}")
    for day in REQUIRED_WELLE_DAYS:
        if day not in s4:
            fail(f"§4 missing day marker '{day}'")
    # Welle-2..Welle-7 must be named.
    for welle_n in range(2, 8):
        if f"Welle-{welle_n}" not in s4:
            fail(f"§4 missing Welle-{welle_n} reference")
    # Weekend-Hold and Marathon-Final-Bilanz anchors.
    if "Weekend-Hold" not in s4:
        fail("§4 must define the KW-24 weekend Weekend-Hold")
    if "Marathon-Final-Bilanz" not in s4:
        fail("§4 must close with Marathon-Final-Bilanz at T0+6")


def check_section5_rollback_paths(s5: str) -> None:
    """§5 has R1..R5 sub-paths each with Trigger + Owner + Recovery."""
    for sub in REQUIRED_S5_SUBSECTIONS:
        if sub not in s5:
            fail(f"§5 missing subsection {sub}")
    for rb in REQUIRED_ROLLBACKS:
        if rb not in s5:
            fail(f"§5 missing rollback-path '{rb}'")
    # Each rollback subsection must show Trigger, Owner, Recovery, Time-budget.
    for marker in ("**Trigger**", "**Owner**", "**Recovery**", "**Time-budget**"):
        count = s5.count(marker)
        if count < 5:
            fail(f"§5 needs >= 5 '{marker}' entries (R1..R5), got {count}")


def check_section6_ar_touchpoints(s6: str) -> None:
    """§6 has TP1..TP6 each with Question + Stop-on-Fail + AR-Hand."""
    for sub in REQUIRED_S6_SUBSECTIONS:
        if sub not in s6:
            fail(f"§6 missing subsection {sub}")
    for tp in REQUIRED_TOUCHPOINTS:
        if tp not in s6:
            fail(f"§6 missing touchpoint '{tp}'")
    for marker in ("**Question**", "**Stop-on-Fail**", "**AR-Hand**"):
        count = s6.count(marker)
        if count < 6:
            fail(f"§6 needs >= 6 '{marker}' entries (TP1..TP6), got {count}")


def check_section7_cross_references(s7: str) -> None:
    """§7 has at least 4 cross-ref subtables."""
    for sub in REQUIRED_S7_SUBSECTIONS:
        if sub not in s7:
            fail(f"§7 missing subtable {sub}")
    # Must reference the three named prior recipes:
    required_refs = [
        "strict-flip-readiness-map-tag58.md",
        "bulk-activation-pre-walk-recipe.md",
        "branch-protection-required-checks-tag64-companion.md",
        "open-k3-v907-baseline-metadata-carry-forward.md",
        "phase-3c-welle-1-runbook.md",
        "phase-3c-welle-7-runbook.md",
    ]
    for ref in required_refs:
        if ref not in s7:
            fail(f"§7 missing cross-reference to {ref}")


def check_section8_sandbox_boundary(s8: str) -> None:
    if "Sandbox-Scope" not in s8:
        fail("§8 must mark Sandbox-Scope block")
    if "Out-of-Sandbox-Scope" not in s8:
        fail("§8 must mark Out-of-Sandbox-Scope block")
    if "Operator-Hand-Sandbox-Gap" not in s8:
        fail("§8 must use the Operator-Hand-Sandbox-Gap term")
    if "BULK_ACTIVATE_OPERATOR_HAND" not in s8:
        fail("§8 must mention the BULK_ACTIVATE_OPERATOR_HAND env-var gate")
    if "feedback_sandbox_host_trennung" not in s8:
        fail("§8 must reference the feedback_sandbox_host_trennung memory")


def check_section9_phase4_freeze(s9: str) -> None:
    for sub in REQUIRED_S9_SUBSECTIONS:
        if sub not in s9:
            fail(f"§9 missing subsection {sub}")
    if "Halt vor Phase 4" not in s9:
        fail("§9 must quote the AR-Vorzeichen 'Halt vor Phase 4'")
    if "PHASE-4-HOLD-VOR-RE-ARM" not in s9:
        fail("§9 must pin PHASE-4-HOLD-VOR-RE-ARM as canonical state")
    if "PHASE-4-RE-ARMED" not in s9:
        fail("§9 must specify PHASE-4-RE-ARMED as the AR-re-arm marker")
    # Phase-3-Close items permitted: at least 3 named.
    if "Marathon-Final-Bilanz" not in s9:
        fail("§9 must permit Marathon-Final-Bilanz as Phase-3-Close")
    if "Post-Mortem" not in s9:
        fail("§9 must permit Phase-3-Post-Mortem as Phase-3-Close")


def main() -> int:
    text = load_doc(DOC_PATH)
    check_sections_present_and_ordered(text)
    sections = split_sections(text)
    check_section1_scope_table(sections["§1"])
    check_section2_eve_checklist(sections["§2"])
    check_section3_t0_sequence(sections["§3"])
    check_section4_welle_day_by_day(sections["§4"])
    check_section5_rollback_paths(sections["§5"])
    check_section6_ar_touchpoints(sections["§6"])
    check_section7_cross_references(sections["§7"])
    check_section8_sandbox_boundary(sections["§8"])
    check_section9_phase4_freeze(sections["§9"])
    print(
        "verify_operator_eve_final_recipe_doc: OK "
        "(9 sections, 12 Eve-checks, 10 T0-steps, 6 Welle-days, "
        "5 rollbacks, 6 AR-touchpoints, 4 cross-ref tables, "
        "sandbox-boundary explicit, Phase-4 freeze-pin marked)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
