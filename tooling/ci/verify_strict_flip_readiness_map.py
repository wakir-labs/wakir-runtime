#!/usr/bin/env python3
"""
Verify the Tag-58 Strict-Flip-Readiness-Map doc.

Parses docs/operations/strict-flip-readiness-map-tag58.md and asserts:
  - All 10 sections (§1..§10) are present in order.
    (§9 Tag-64-Append, §10 Tag-68-Append.)
  - §1 gate table covers G1..G6 with one of {BLOCKED, GREEN} statuses.
  - §2 7-day-calendar lists all 7 Day-N entries.
  - §3 G1-recipe covers all 5 wiring targets G1.1..G1.5.
  - §4 G2-recipe covers G2.1..G2.3.
  - §6 cutover-day sequence lists T0..T9 (10 steps).
  - §7 has Decision-A and Decision-B.
  - §8 mentions Operator-Hand-Sandbox-Gap.
  - §9 OPEN-J3 Carry-Forward sub-blocks §9.1..§9.5 present.
  - §10 Tag-68-Carry-Forward sub-blocks §10.1..§10.7 present and
    cover (Cutover-Eve-Recipe, Live-Smoke-DEFECT, Activation-Pre-
    Mortem, Welle-N-State-Files, OPEN-J3-Refresh, 7-Pool-Checks,
    Tag-68-Verdict).
  - No recipe-stage section body is empty.

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
    / "strict-flip-readiness-map-tag58.md"
)

REQUIRED_SECTIONS = [
    "§1",
    "§2",
    "§3",
    "§4",
    "§5",
    "§6",
    "§7",
    "§8",
    "§9",
    "§10",
]

REQUIRED_GATES = ["G1", "G2", "G3", "G4", "G5", "G6"]
REQUIRED_DAYS = ["Day-1", "Day-2", "Day-3", "Day-4", "Day-5", "Day-6", "Day-7"]
REQUIRED_G1_TARGETS = ["G1.1", "G1.2", "G1.3", "G1.4", "G1.5"]
REQUIRED_G2_PHASES = ["G2.1", "G2.2", "G2.3"]
REQUIRED_T_STEPS = [f"T{i}" for i in range(10)]
REQUIRED_DECISIONS = ["Decision-A", "Decision-B"]
REQUIRED_J3_STEPS = ["J3-A", "J3-B", "J3-C", "J3-D", "J3-E", "J3-F", "J3-G"]
REQUIRED_SECTION9_SUBS = ["§9.1", "§9.2", "§9.3", "§9.4", "§9.5"]
REQUIRED_SECTION10_SUBS = [
    "§10.1",
    "§10.2",
    "§10.3",
    "§10.4",
    "§10.5",
    "§10.6",
    "§10.7",
]
REQUIRED_POOL_CHECKS = [
    "cosign-verify-images",
    "hash-derivate-gate",
    "cross-substrate-parity-gate",
    "cosign-keyless-oidc-drift-probe",
    "cosign-strict-mode-readiness-check",
    "trust-root-snapshot-pin-verify",
    "pre-cutover-final-sanity-gate",
]
STATUS_PATTERN = re.compile(r"\*\*(BLOCKED|GREEN)\*\*")


def fail(msg: str) -> None:
    sys.stderr.write(f"verify_strict_flip_readiness_map: FAIL: {msg}\n")
    sys.exit(1)


def load_doc(path: Path) -> str:
    if not path.exists():
        fail(f"doc not found: {path}")
    return path.read_text(encoding="utf-8")


def check_sections_present_and_ordered(text: str) -> None:
    last_idx = -1
    for section in REQUIRED_SECTIONS:
        idx = text.find(f"## {section}")
        if idx < 0:
            fail(f"missing section header for {section}")
        if idx <= last_idx:
            fail(f"section {section} out of order")
        last_idx = idx


def split_sections(text: str) -> dict:
    """Return {section_marker: section_body} for §1..§8."""
    result: dict = {}
    positions = []
    for section in REQUIRED_SECTIONS:
        idx = text.find(f"## {section}")
        positions.append((section, idx))
    positions.append(("__end__", len(text)))
    for i in range(len(REQUIRED_SECTIONS)):
        marker, start = positions[i]
        _, end = positions[i + 1]
        body = text[start:end]
        result[marker] = body
    return result


def check_gate_table(section1: str) -> None:
    for gate in REQUIRED_GATES:
        if f"| {gate} |" not in section1:
            fail(f"§1 gate-table missing row for {gate}")
    statuses = STATUS_PATTERN.findall(section1)
    if len(statuses) < len(REQUIRED_GATES):
        fail(
            "§1 gate-table needs explicit **BLOCKED**/**GREEN** marker "
            f"per gate (found {len(statuses)})"
        )
    for status in statuses:
        if status not in ("BLOCKED", "GREEN"):
            fail(f"§1 gate-table has unknown status: {status}")


def check_seven_day_calendar(section2: str) -> None:
    for day in REQUIRED_DAYS:
        if day not in section2:
            fail(f"§2 7-day-calendar missing {day}")


def check_recipe_stages_nonempty(section: str, stages: list, label: str) -> None:
    for stage in stages:
        marker = f"### {label}.{stage.split('.', 1)[1]}" if "." in stage else None
        # Look for "### G1.1" or "### G2.1" style headings
        heading_pattern = f"### {stage}"
        idx = section.find(heading_pattern)
        if idx < 0:
            fail(f"recipe stage heading '### {stage}' not found")
        # Find next "### " or end-of-section
        rest = section[idx + len(heading_pattern):]
        next_heading_idx = rest.find("\n### ")
        next_section_idx = rest.find("\n## ")
        candidates = [i for i in (next_heading_idx, next_section_idx) if i >= 0]
        end = min(candidates) if candidates else len(rest)
        body = rest[:end].strip()
        # Body must contain at least one bullet or code-block line
        non_empty_lines = [
            ln for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#")
        ]
        if len(non_empty_lines) < 2:
            fail(
                f"recipe stage '{stage}' body too thin "
                f"(needs ≥2 non-empty content lines, got {len(non_empty_lines)})"
            )


def check_g1_recipe(section3: str) -> None:
    check_recipe_stages_nonempty(section3, REQUIRED_G1_TARGETS, "G1")
    if "G1-PR-Stack" not in section3:
        fail("§3 missing G1-PR-Stack subsection")


def check_g2_recipe(section4: str) -> None:
    check_recipe_stages_nonempty(section4, REQUIRED_G2_PHASES, "G2")
    if "G2-PR-Inhalt" not in section4:
        fail("§4 missing G2-PR-Inhalt subsection")


def check_hold_steady(section5: str) -> None:
    for gate in ["G3", "G4", "G5", "G6"]:
        if f"### {gate} " not in section5:
            fail(f"§5 missing Hold-Steady subsection for {gate}")


def check_cutover_sequence(section6: str) -> None:
    for t in REQUIRED_T_STEPS:
        if f"| {t} |" not in section6:
            fail(f"§6 cutover-day-sequence missing row {t}")


def check_failure_recovery(section7: str) -> None:
    for d in REQUIRED_DECISIONS:
        if f"### {d}" not in section7:
            fail(f"§7 missing {d} subsection")
        # Each decision must have a Symptom + Decision + Owner block
        idx = section7.find(f"### {d}")
        rest = section7[idx:]
        next_heading = rest.find("\n### ", 5)
        next_section = rest.find("\n## ", 5)
        candidates = [i for i in (next_heading, next_section) if i >= 0]
        end = min(candidates) if candidates else len(rest)
        body = rest[:end]
        for kw in ("Symptom", "Decision", "Owner"):
            if kw not in body:
                fail(f"§7 {d} block missing '{kw}' marker")


def check_sandbox_boundary(section8: str) -> None:
    if "Operator-Hand-Sandbox-Gap" not in section8:
        fail("§8 must mention Operator-Hand-Sandbox-Gap explicitly")
    if "Sandbox-Scope" not in section8 or "Out-of-Sandbox-Scope" not in section8:
        fail("§8 must explicitly delimit Sandbox-Scope vs. Out-of-Sandbox-Scope")


def check_section9_open_j3(section9: str) -> None:
    if "OPEN-J3" not in section9:
        fail("§9 must reference OPEN-J3 item explicitly")
    for sub in REQUIRED_SECTION9_SUBS:
        if f"### {sub}" not in section9:
            fail(f"§9 missing sub-section {sub}")
    for step in REQUIRED_J3_STEPS:
        if f"| {step} |" not in section9:
            fail(f"§9 missing J3 refresh-sequence step {step}")
    if "intentional-carry-forward" not in section9:
        fail("§9 must explicitly label OPEN-J3 as intentional-carry-forward")
    if "Containerfile.real" not in section9:
        fail("§9 must reference Containerfile.real substrate file")


def check_section10_tag68_carry_forward(section10: str) -> None:
    # Sub-sections present
    for sub in REQUIRED_SECTION10_SUBS:
        if f"### {sub}" not in section10:
            fail(f"§10 missing sub-section {sub}")
    # Tag-67 PR anchors required
    for pr_ref in ["#422", "#425", "#426", "#427", "#429"]:
        if pr_ref not in section10:
            fail(f"§10 must reference Tag-66/67 PR {pr_ref}")
    # Eve-Recipe Dry-Run CLEAN verdict
    if "CLEAN" not in section10:
        fail("§10.1 must reference Eve-Recipe Dry-Run CLEAN verdict")
    # Live-Smoke 4-Drift status
    if "4 Drift" not in section10 and "4 drifts" not in section10.lower():
        fail("§10.2 must reference 4 Drift-Stages from Tag-67 PR #425")
    if "DRIFT" not in section10 or "DEFECT" not in section10:
        fail("§10.2 must reference DRIFT/DEFECT tri-state verdict")
    # 7-Pool checks listed
    for chk in REQUIRED_POOL_CHECKS:
        if chk not in section10:
            fail(f"§10.6 must list pool-required check '{chk}'")
    # Tag-68 verdict matrix present
    if "Tag-68-Carry-Forward-Verdict" not in section10:
        fail("§10 must include a Tag-68-Carry-Forward-Verdict block")
    # OPEN-J3 carry-forward unchanged
    if "OPEN-J3" not in section10:
        fail("§10.5 must include an OPEN-J3 status-refresh entry")
    # Cutover-T0 date still anchored
    if "2026-06-08" not in section10:
        fail("§10 must keep the 2026-06-08 Cutover-T0 anchor")


def main() -> int:
    text = load_doc(DOC_PATH)
    check_sections_present_and_ordered(text)
    sections = split_sections(text)
    check_gate_table(sections["§1"])
    check_seven_day_calendar(sections["§2"])
    check_g1_recipe(sections["§3"])
    check_g2_recipe(sections["§4"])
    check_hold_steady(sections["§5"])
    check_cutover_sequence(sections["§6"])
    check_failure_recovery(sections["§7"])
    check_sandbox_boundary(sections["§8"])
    check_section9_open_j3(sections["§9"])
    check_section10_tag68_carry_forward(sections["§10"])
    print(
        "verify_strict_flip_readiness_map: OK "
        f"(10 sections, 6 gates, 7 days, 5+3 stages, 10 cutover steps, "
        f"2 decisions, 5 §9-subs + 7 J3-steps, 7 §10-subs + 7 pool-checks)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
