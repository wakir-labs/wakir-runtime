#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""
Verify the Tag-77 Operator-Hand OTS-Live-Stamping Setup-Recipe doc.

Parses ``docs/operations/ots-live-stamping-operator-setup.md`` and
asserts the consolidated activation-recipe is structurally complete:

  - All 8 sections (§1..§8) present in order with verbatim headings.
  - §1 carries a scope-table covering Pre-Eve / Eve / Eve+1 / T0 /
    T0+0.5h / T0..T0+6 (6 rows) and explicitly names the cutover
    dates 2026-06-07 (Eve) + 2026-06-08 (T0).
  - §2 documents three probe-verification surfaces:
      §2.1 Manifest-Hash Pre-Activation-Probe,
      §2.2 Phase-3-COMPLETE-Marker,
      §2.3 Probe-Verdict-Aggregate.
    Required tokens: ``PROBE-READY``, ``ar_authorisation_required``,
    ``phase-3-complete-marker``,
    ``welle_1_7_kind_disjointness_pin_ok``,
    ``PRE-EVE-PROBE-GREEN``.
  - §3 carries the AR-authorisation gate: three sub-sections
    §3.1..§3.3 + no-AR-no-flip pin token
    ``MUST NOT`` + AR-authorisation-marker filename pattern.
  - §4 carries the WAKIR_OTS_LIVE_EMIT toggle:
      §4.1 Pre-Toggle-Verification (unset/0 + fixture URL check),
      §4.2 Toggle-Export (export WAKIR_OTS_LIVE_EMIT=1 +
        WAKIR_OTS_CALENDAR_URL + ots CLI presence check),
      §4.3 Toggle-Audit-Record (operator-hand-audit-log.jsonl).
  - §5 carries the First-Live-Stamp test with four sub-steps
    §5.1..§5.4 (Stamp / Wait / Verify / Audit-Record). Must
    reference ``ots stamp``, ``ots upgrade``, ``ots verify``,
    "Bitcoin block".
  - §6 carries Marker-Chain-Verifikation with §6.1..§6.4
    (Welle-1..7 stamp-sequence, chain-hash, cross-substrate-parity,
    audit-evidence-bundle). Must mention all seven welle numbers
    1..7 and Phase-3-COMPLETE-Marker chain.
  - §7 carries the Rollback-Pfad with §7.1..§7.4 and five rollback
    triggers R1..R5 (Calendar-Down, Verify-Failure, Chain-Drift,
    Parity-Mismatch, AR-Recall).
  - §8 carries Sandbox-Boundary with §8.1..§8.5
    (Sandbox-Scope, Out-of-Sandbox-Scope, Operator-Hand-Sandbox-Gap,
    ADR-Anchors, Cross-Anchor-PRs). Must reference
    ``feedback_sandbox_host_trennung`` and ADR-0023a explicitly.
  - Doc signed off with ``-- Tomás``.

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
    / "ots-live-stamping-operator-setup.md"
)

REQUIRED_SECTIONS = ["§1", "§2", "§3", "§4", "§5", "§6", "§7", "§8"]

REQUIRED_S1_ROWS = [
    "| Pre-Eve |",
    "| Eve |",
    "| Eve+1 |",
    "| T0 |",
    "| T0+0.5h |",
    "| T0..T0+6 |",
]

REQUIRED_S2_SUBSECTIONS = ["§2.1", "§2.2", "§2.3"]
REQUIRED_S2_TOKENS = [
    "PROBE-READY",
    "ar_authorisation_required",
    "phase-3-complete-marker",
    "welle_1_7_kind_disjointness_pin_ok",
    "PRE-EVE-PROBE-GREEN",
]

REQUIRED_S3_SUBSECTIONS = ["§3.1", "§3.2", "§3.3"]
REQUIRED_S4_SUBSECTIONS = ["§4.1", "§4.2", "§4.3"]
REQUIRED_S5_SUBSECTIONS = ["§5.1", "§5.2", "§5.3", "§5.4"]
REQUIRED_S6_SUBSECTIONS = ["§6.1", "§6.2", "§6.3", "§6.4"]
REQUIRED_S7_SUBSECTIONS = ["§7.1", "§7.2", "§7.3", "§7.4"]
REQUIRED_S8_SUBSECTIONS = ["§8.1", "§8.2", "§8.3", "§8.4", "§8.5"]

REQUIRED_ROLLBACK_TRIGGERS = [
    "R1-Calendar-Down",
    "R2-Verify-Failure",
    "R3-Chain-Drift",
    "R4-Parity-Mismatch",
    "R5-AR-Recall",
]

REQUIRED_ADR_ANCHORS = [
    "ADR-0007",
    "ADR-0023a",
    "ADR-0044",
    "ADR-0066",
]

REQUIRED_CROSS_ANCHOR_PRS = ["#366", "#371", "#382", "#440", "#484"]


def fail(msg: str) -> None:
    sys.stderr.write(f"verify_ots_live_setup_doc: FAIL: {msg}\n")
    sys.exit(1)


def load_doc(path: Path) -> str:
    if not path.exists():
        fail(f"doc not found: {path}")
    return path.read_text(encoding="utf-8")


def check_sections_present_and_ordered(text: str) -> None:
    last_idx = -1
    for section in REQUIRED_SECTIONS:
        idx = text.find(f"## {section} ")
        if idx < 0:
            fail(f"missing section header for {section}")
        if idx <= last_idx:
            fail(
                f"section {section} out of order "
                f"(idx={idx} <= last={last_idx})"
            )
        last_idx = idx


def split_sections(text: str) -> dict:
    """Return {section_marker: section_body} for §1..§8."""
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


def check_section1_scope(s1: str) -> None:
    if "### §1.1" not in s1:
        fail("§1.1 Activation-Pfad subsection missing")
    if "### §1.2" not in s1:
        fail("§1.2 Scope-Table subsection missing")
    if "### §1.3" not in s1:
        fail("§1.3 Non-Scope subsection missing")
    for row in REQUIRED_S1_ROWS:
        if row not in s1:
            fail(f"§1.2 scope-table missing row '{row.strip()}'")
    if "2026-06-07" not in s1:
        fail("§1 must name Cutover-Eve date 2026-06-07")
    if "2026-06-08" not in s1:
        fail("§1 must name Cutover-T0 date 2026-06-08")
    if "KW-24" not in s1:
        fail("§1 must reference KW-24 cutover gate")


def check_section2_probe_verification(s2: str) -> None:
    for sub in REQUIRED_S2_SUBSECTIONS:
        if sub not in s2:
            fail(f"§2 missing subsection {sub}")
    for token in REQUIRED_S2_TOKENS:
        if token not in s2:
            fail(f"§2 missing required token '{token}'")
    if "pre-activation-probe" not in s2:
        fail("§2 must reference the pre-activation-probe mode")
    if "emit_manifest_hash_ots_marker.py" not in s2:
        fail("§2 must reference the emit_manifest_hash_ots_marker.py helper")


def check_section3_ar_authorisation(s3: str) -> None:
    for sub in REQUIRED_S3_SUBSECTIONS:
        if sub not in s3:
            fail(f"§3 missing subsection {sub}")
    if "MUST NOT" not in s3:
        fail("§3.3 must contain MUST NOT pin for no-AR-no-flip")
    if "ar-hand/inbox/" not in s3:
        fail("§3.2 must reference ar-hand/inbox/ filename pattern")
    if "ots-live-emit-activation-authorisation" not in s3:
        fail(
            "§3.2 must name the AR-authorisation marker filename "
            "pattern 'ots-live-emit-activation-authorisation'"
        )
    if "ADR-0023a" not in s3:
        fail("§3.3 must anchor to ADR-0023a (Sandbox-Boundary)")


def check_section4_toggle_sequence(s4: str) -> None:
    for sub in REQUIRED_S4_SUBSECTIONS:
        if sub not in s4:
            fail(f"§4 missing subsection {sub}")
    if "export WAKIR_OTS_LIVE_EMIT=1" not in s4:
        fail("§4.2 must contain 'export WAKIR_OTS_LIVE_EMIT=1' verbatim")
    if "WAKIR_OTS_CALENDAR_URL" not in s4:
        fail("§4.2 must reference WAKIR_OTS_CALENDAR_URL env-flag")
    if "command -v ots" not in s4:
        fail("§4.2 must contain ots CLI presence check 'command -v ots'")
    if "operator-hand-audit-log.jsonl" not in s4:
        fail("§4.3 must reference operator-hand-audit-log.jsonl")
    if "shell-scope export only" not in s4:
        fail("§4.2 must pin shell-scope-export-only discipline")
    if ".env" not in s4:
        fail("§4.2 must explicitly forbid .env persistence")


def check_section5_first_live_stamp(s5: str) -> None:
    for sub in REQUIRED_S5_SUBSECTIONS:
        if sub not in s5:
            fail(f"§5 missing subsection {sub}")
    for cmd in ("ots stamp", "ots upgrade", "ots verify"):
        if cmd not in s5:
            fail(f"§5 must reference '{cmd}' invocation")
    if "Bitcoin" not in s5:
        fail("§5 must mention Bitcoin block-anchor verification")
    if "phase-3-complete-marker" not in s5.lower():
        fail("§5 must reference the phase-3-complete-marker target")
    if "rollback" not in s5.lower():
        fail("§5 must point to rollback path on verify failure")


def check_section6_marker_chain(s6: str) -> None:
    for sub in REQUIRED_S6_SUBSECTIONS:
        if sub not in s6:
            fail(f"§6 missing subsection {sub}")
    for n in range(1, 8):
        if f"Welle-{n}" not in s6:
            fail(f"§6 must reference Welle-{n}")
    if "welle_1_7_marker_chain" not in s6:
        fail("§6.2 must reference welle_1_7_marker_chain field")
    if "cross_substrate_parity_markers" not in s6:
        fail("§6.3 must reference cross_substrate_parity_markers field")
    if "tar czf" not in s6:
        fail("§6.4 must contain tarball-bundle invocation 'tar czf'")


def check_section7_rollback(s7: str) -> None:
    for sub in REQUIRED_S7_SUBSECTIONS:
        if sub not in s7:
            fail(f"§7 missing subsection {sub}")
    for trigger in REQUIRED_ROLLBACK_TRIGGERS:
        if trigger not in s7:
            fail(f"§7.1 missing rollback trigger '{trigger}'")
    if "unset WAKIR_OTS_LIVE_EMIT" not in s7:
        fail("§7.2 must contain 'unset WAKIR_OTS_LIVE_EMIT' verbatim")
    if "rollback-quarantine" not in s7:
        fail("§7.2 must quarantine partial .ots proof files")
    if "re-arm marker" not in s7:
        fail("§7.4 must require a re-arm marker for re-activation")


def check_section8_sandbox_boundary(s8: str) -> None:
    for sub in REQUIRED_S8_SUBSECTIONS:
        if sub not in s8:
            fail(f"§8 missing subsection {sub}")
    if "Sandbox-Scope" not in s8:
        fail("§8.1 must declare Sandbox-Scope explicitly")
    if "Out-of-Sandbox-Scope" not in s8:
        fail("§8.2 must declare Out-of-Sandbox-Scope explicitly")
    if "Operator-Hand-Sandbox-Gap" not in s8:
        fail("§8.3 must use Operator-Hand-Sandbox-Gap term")
    if "feedback_sandbox_host_trennung" not in s8:
        fail("§8.3 must reference feedback_sandbox_host_trennung memory")
    for adr in REQUIRED_ADR_ANCHORS:
        if adr not in s8:
            fail(f"§8.4 missing ADR anchor '{adr}'")
    for pr in REQUIRED_CROSS_ANCHOR_PRS:
        if pr not in s8:
            fail(f"§8.5 missing cross-anchor PR '{pr}'")


def check_signature(text: str) -> None:
    if not re.search(r"^-- Tom[áa]s\s*$", text, re.MULTILINE):
        fail("doc must end with '-- Tomás' signature line")


def check_frontmatter(text: str) -> None:
    fm = re.search(r"(?s)^---\n(.*?)\n---\n", text)
    if fm is None:
        # Tolerate a leading HTML comment before the frontmatter.
        fm = re.search(r"(?s)-->\s*\n---\n(.*?)\n---\n", text)
    if fm is None:
        fail("YAML frontmatter block missing")
    body = fm.group(1)
    for key in ('title:', 'status:', 'owner:', 'tag:'):
        if key not in body:
            fail(f"frontmatter missing required key '{key}'")
    if '"tomas"' not in body:
        fail("frontmatter owner must be tomas")
    if '"tag-77"' not in body:
        fail("frontmatter tag must be tag-77")


def main() -> int:
    text = load_doc(DOC_PATH)
    check_frontmatter(text)
    check_sections_present_and_ordered(text)
    sections = split_sections(text)
    check_section1_scope(sections["§1"])
    check_section2_probe_verification(sections["§2"])
    check_section3_ar_authorisation(sections["§3"])
    check_section4_toggle_sequence(sections["§4"])
    check_section5_first_live_stamp(sections["§5"])
    check_section6_marker_chain(sections["§6"])
    check_section7_rollback(sections["§7"])
    check_section8_sandbox_boundary(sections["§8"])
    check_signature(text)
    print(
        "verify_ots_live_setup_doc: OK "
        "(8 sections, scope-table 6 rows, probe-verification "
        "3 subsections, AR-authorisation gate, toggle sequence "
        "3 subsections, first-live-stamp 4 subsections, "
        "marker-chain 4 subsections + Welle-1..7, rollback "
        "5 triggers, sandbox-boundary explicit, frontmatter pinned)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
