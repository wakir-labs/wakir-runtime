#!/usr/bin/env python3
"""
Verify the Tag-62 wakir-protocol Cross-Review-Zone-3 hand-off plan doc.

Parses
docs/operations/wakir-protocol-cross-review-zone-3-handoff-plan.md
and asserts:

  - All 8 sections (§1..§8) are present in order.
  - §2 source-state table lists all 8 mirror seed files at their
    canonical runtime-side paths (4 Tag-59 alert-routing files +
    4 Tag-61 schema files).
  - §3 target-state table lists all 8 protocol-side canonical
    mirror paths and the runtime->protocol mapping per row.
  - §4 Operator-Hand recipe has 6 sub-sections §4.1..§4.6 and
    none of them is empty (>=2 content lines per stanza).
  - §4 recipe contains gh CLI invocations against
    `wakir-labs/wakir-protocol` and a branch name slug
    `reza/tag-62-cross-review-zone-3-handoff`.
  - §5 verification has 3 sub-sections §5.1..§5.3 and references
    `--post-resync` (runtime projection) AND the real protocol
    measurement.
  - §6 failure-modes covers Conflict, License-Header-Drift, and
    Path-Drift explicitly.
  - §7 sandbox-boundary delimits Sandbox-Scope vs.
    Out-of-Sandbox-Scope and mentions Operator-Hand-Sandbox-Gap.
  - §8 cross-anchor cites runtime PR #376 (Tag-59 Reza),
    PR #382 (Tag-60 Noa), PR #388 (Tag-61 Reza).
  - Doc carries a Reza signature line (-- Reza).

Exit 0 on green, exit 1 on any failure with a clear stderr
message. stdlib only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DOC_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "operations"
    / "wakir-protocol-cross-review-zone-3-handoff-plan.md"
)

REQUIRED_SECTIONS = ["§1", "§2", "§3", "§4", "§5", "§6", "§7", "§8"]

REQUIRED_RECIPE_STAGES = ["§4.1", "§4.2", "§4.3", "§4.4", "§4.5", "§4.6"]
REQUIRED_VERIFICATION_STAGES = ["§5.1", "§5.2", "§5.3"]

EXPECTED_TAG59_SEEDS = [
    "wirelang/specs/protocol-mirror-seed/docs/observability/pre-mortem-failure-mode-notify-catalog.md",
    "wirelang/specs/protocol-mirror-seed/dashboards/phase-3-marathon-alerts.yaml",
    "wirelang/specs/protocol-mirror-seed/dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml",
    "wirelang/specs/protocol-mirror-seed/scripts/observability/alert-rule-to-mira-notify-bridge.py",
]

EXPECTED_TAG61_SEEDS = [
    "wirelang/specs/protocol-mirror-seed/schemas/layer-0-transport.json",
    "wirelang/specs/protocol-mirror-seed/schemas/layer-1-wire.json",
    "wirelang/specs/protocol-mirror-seed/schemas/layer-2-semantic.json",
    "wirelang/specs/protocol-mirror-seed/schemas/aip-document.json",
]

ALL_SEEDS = EXPECTED_TAG59_SEEDS + EXPECTED_TAG61_SEEDS

EXPECTED_PROTOCOL_PATHS = [
    "wakir_protocol/docs/observability/pre-mortem-failure-mode-notify-catalog.md",
    "wakir_protocol/dashboards/phase-3-marathon-alerts.yaml",
    "wakir_protocol/dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml",
    "wakir_protocol/scripts/observability/alert-rule-to-mira-notify-bridge.py",
    "wakir_protocol/schemas/layer-0-transport.json",
    "wakir_protocol/schemas/layer-1-wire.json",
    "wakir_protocol/schemas/layer-2-semantic.json",
    "wakir_protocol/schemas/aip-document.json",
]

REQUIRED_FAILURE_MODES = ["Path-Drift", "License-Header-Drift", "Conflict"]

ANCHOR_PRS = ["#376", "#382", "#388"]

EXPECTED_BRANCH_SLUG = "reza/tag-62-cross-review-zone-3-handoff"


def fail(msg: str) -> None:
    sys.stderr.write(f"verify_protocol_handoff_plan_doc: FAIL: {msg}\n")
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
            fail(f"section {section} out of order (idx={idx} <= last={last_idx})")
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


def check_source_state_seeds(section2: str) -> None:
    """All 8 mirror seed files appear in §2 with their canonical paths."""
    for seed in ALL_SEEDS:
        if seed not in section2:
            fail(f"§2 source-state table missing seed path: {seed}")
    for pr in ("#376", "#388"):
        if pr not in section2:
            fail(f"§2 source-state must cite anchor PR {pr}")
    if "Apache-2.0" not in section2:
        fail("§2 source-state must declare Apache-2.0 SPDX posture for all seeds")


def check_target_state_paths(section3: str) -> None:
    """All 8 protocol-side canonical paths appear in §3."""
    for protocol_path in EXPECTED_PROTOCOL_PATHS:
        if protocol_path not in section3:
            fail(f"§3 target-state table missing protocol path: {protocol_path}")
    if "Apache-2.0" not in section3:
        fail("§3 target-state must reference Apache-2.0 SPDX banner discipline")


def check_recipe_stages_nonempty(section4: str) -> None:
    for stage in REQUIRED_RECIPE_STAGES:
        heading = f"### {stage}"
        idx = section4.find(heading)
        if idx < 0:
            fail(f"§4 recipe missing sub-section heading '{heading}'")
        rest = section4[idx + len(heading):]
        next_heading_idx = rest.find("\n### ")
        next_section_idx = rest.find("\n## ")
        candidates = [i for i in (next_heading_idx, next_section_idx) if i >= 0]
        end = min(candidates) if candidates else len(rest)
        body = rest[:end].strip()
        non_empty_lines = [
            ln for ln in body.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        if len(non_empty_lines) < 2:
            fail(
                f"§4 recipe stage '{stage}' body too thin "
                f"(needs >=2 non-empty content lines, got {len(non_empty_lines)})"
            )


def check_recipe_gh_and_branch(section4: str) -> None:
    if "gh pr create" not in section4:
        fail("§4 recipe must contain 'gh pr create' invocation")
    if "wakir-labs/wakir-protocol" not in section4:
        fail("§4 recipe must target 'wakir-labs/wakir-protocol' repo")
    if EXPECTED_BRANCH_SLUG not in section4:
        fail(f"§4 recipe must use branch slug '{EXPECTED_BRANCH_SLUG}'")
    if "gh pr merge" not in section4:
        fail("§4 recipe must include 'gh pr merge' step")


def check_verification_stages(section5: str) -> None:
    for stage in REQUIRED_VERIFICATION_STAGES:
        heading = f"### {stage}"
        if heading not in section5:
            fail(f"§5 verification missing sub-section '{heading}'")
    if "--post-resync" not in section5:
        fail("§5 verification must reference '--post-resync' flag (runtime projection)")
    if "ENFORCE-READY" not in section5 or "ENFORCE-Flip" not in section5:
        fail("§5 verification must reference ENFORCE-READY verdict and ENFORCE-Flip trigger")
    if "92" not in section5:
        fail("§5 verification must cite post-resync score 92")


def check_failure_modes(section6: str) -> None:
    for mode in REQUIRED_FAILURE_MODES:
        if mode not in section6:
            fail(f"§6 failure-modes missing '{mode}'")
        # Each mode must have Symptom + Recovery + Owner markers
        idx = section6.find(mode)
        rest = section6[idx:]
        next_block = rest.find("\n### ", 5)
        next_section = rest.find("\n## ", 5)
        candidates = [i for i in (next_block, next_section) if i >= 0]
        end = min(candidates) if candidates else len(rest)
        body = rest[:end]
        for kw in ("Symptom", "Recovery", "Owner"):
            if kw not in body:
                fail(f"§6 '{mode}' block missing '{kw}' marker")


def check_sandbox_boundary(section7: str) -> None:
    if "Sandbox-Scope" not in section7:
        fail("§7 must declare Sandbox-Scope explicitly")
    if "Out-of-Sandbox-Scope" not in section7:
        fail("§7 must declare Out-of-Sandbox-Scope explicitly")
    if "Operator-Hand-Sandbox-Gap" not in section7:
        fail("§7 must mention Operator-Hand-Sandbox-Gap")
    if "ADR-0023a" not in section7:
        fail("§7 must anchor to ADR-0023a (Sandbox-Boundary)")


def check_cross_anchor(section8: str) -> None:
    for pr in ANCHOR_PRS:
        if pr not in section8:
            fail(f"§8 cross-anchor missing PR {pr}")
    if "ADR-0062" not in section8:
        fail("§8 cross-anchor must reference ADR-0062")
    if "Cross-Review-Zone-3" not in section8:
        fail("§8 cross-anchor must reference Cross-Review-Zone-3")


def check_signature(text: str) -> None:
    if not re.search(r"^-- Reza\s*$", text, re.MULTILINE):
        fail("doc must end with '-- Reza' signature line")


def main() -> int:
    text = load_doc(DOC_PATH)
    check_sections_present_and_ordered(text)
    sections = split_sections(text)
    check_source_state_seeds(sections["§2"])
    check_target_state_paths(sections["§3"])
    check_recipe_stages_nonempty(sections["§4"])
    check_recipe_gh_and_branch(sections["§4"])
    check_verification_stages(sections["§5"])
    check_failure_modes(sections["§6"])
    check_sandbox_boundary(sections["§7"])
    check_cross_anchor(sections["§8"])
    check_signature(text)
    print(
        "verify_protocol_handoff_plan_doc: OK "
        "(8 sections, 8 seed files, 8 protocol paths, "
        "6 recipe stages, 3 verification stages, 3 failure modes, "
        "3 PR anchors)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
