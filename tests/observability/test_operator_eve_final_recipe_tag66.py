# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""
Tag-66 Operator-Hand Cutover-Eve Final-Recipe doc + verifier test-suite.

Covers (>= 12 tests required by Tag-66 brief; suite carries 16):

  - Doc existence + structural integrity (front-matter, owner, tag).
  - All 9 sections (§1..§9) present in order.
  - §1 scope-table covers Eve + T0..T0+6 (8 touch-days).
  - §2 Eve-Checklist covers E1..E12 with Verdict-Marker discipline.
  - §3 T0-Sequence covers T0.0..T0.9 (10 steps) and surfaces
    POST-ACTIVATE-CLEAN as the Walking-Skeleton handshake.
  - §4 Welle-Day-by-Day covers T0+1..T0+6 with Welle-2..Welle-7.
  - §4 closes with Marathon-Final-Bilanz at T0+6.
  - §5 covers R1..R5 rollback-paths.
  - §6 covers TP1..TP6 AR-touchpoints.
  - §7 cross-reference matrix names all four prior substrates.
  - §8 sandbox-boundary uses Operator-Hand-Sandbox-Gap term
    and references the feedback_sandbox_host_trennung memory.
  - §9 quotes the AR-Vorzeichen "Halt vor Phase 4" and pins both
    PHASE-4-HOLD-VOR-RE-ARM (current state) and PHASE-4-RE-ARMED
    (re-arm trigger).
  - Verifier helper exists, is executable, exits 0 on current doc.
  - Verifier helper fails when §3 (T0-sequence) is corrupted.
  - Verifier helper fails when §9 Phase-4 freeze-pin is removed.
  - Cross-references back to Tag-58, Tag-62, Tag-64 substrates exist
    in the document body (not only in front-matter).
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = (
    REPO_ROOT / "docs" / "operations" / "operator-hand-cutover-eve-final-recipe.md"
)
VERIFIER_PATH = (
    REPO_ROOT / "tooling" / "ci" / "verify_operator_eve_final_recipe_doc.py"
)


@pytest.fixture(scope="module")
def doc_text() -> str:
    assert DOC_PATH.exists(), f"doc missing: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


def _run_verifier(doc_override: Path | None = None) -> subprocess.CompletedProcess:
    if doc_override is not None:
        wrapper_src = VERIFIER_PATH.read_text(encoding="utf-8")
        patched = wrapper_src.replace(
            'DOC_PATH = (\n    Path(__file__).resolve().parents[2]\n'
            '    / "docs"\n    / "operations"\n'
            '    / "operator-hand-cutover-eve-final-recipe.md"\n)',
            f'DOC_PATH = Path(r"{doc_override}")',
        )
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(patched)
            tmp_path = tmp.name
        return subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    return subprocess.run(
        [sys.executable, str(VERIFIER_PATH)],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_01_doc_exists_and_substantive(doc_text: str) -> None:
    assert len(doc_text) > 3000, "Eve-Doc looks suspiciously short"


def test_02_doc_frontmatter_owner_and_tag(doc_text: str) -> None:
    assert 'owner: "kai"' in doc_text
    assert 'tag: "tag-66"' in doc_text


def test_03_all_nine_sections_present_in_order(doc_text: str) -> None:
    positions = []
    for section in ["§1", "§2", "§3", "§4", "§5", "§6", "§7", "§8", "§9"]:
        idx = doc_text.find(f"## {section} ")
        assert idx >= 0, f"missing section header {section}"
        positions.append(idx)
    assert positions == sorted(positions), "sections out of order"


def test_04_section1_scope_table_eight_touch_days(doc_text: str) -> None:
    s1_start = doc_text.find("## §1 ")
    s2_start = doc_text.find("## §2 ")
    s1 = doc_text[s1_start:s2_start]
    for row in ["Eve", "T0", "T0+1", "T0+2", "T0+3", "T0+4", "T0+5", "T0+6"]:
        assert f"| {row} |" in s1, f"§1 scope-table missing row '{row}'"
    assert "2026-05-29" in s1, "§1 must name Cutover-Eve date"
    assert "2026-06-08" in s1, "§1 must name Cutover-T0 date"


def test_05_section2_twelve_eve_checks_with_verdicts(doc_text: str) -> None:
    s2_start = doc_text.find("## §2 ")
    s3_start = doc_text.find("## §3 ")
    s2 = doc_text[s2_start:s3_start]
    for n in range(1, 13):
        marker = f"Eve-Check E{n}"
        assert marker in s2, f"§2 missing {marker}"
    verdict_count = len(re.findall(r"\*\*Verdict-Marker\*\*", s2))
    assert verdict_count >= 12, (
        f"§2 needs >= 12 Verdict-Marker entries, got {verdict_count}"
    )
    assert "EVE-VERDICT-GO" in s2 and "EVE-VERDICT-HOLD" in s2, (
        "§2 must define EVE-VERDICT-GO / EVE-VERDICT-HOLD aggregate"
    )


def test_06_section3_t0_sequence_ten_steps(doc_text: str) -> None:
    s3_start = doc_text.find("## §3 ")
    s4_start = doc_text.find("## §4 ")
    s3 = doc_text[s3_start:s4_start]
    for i in range(10):
        assert f"T0.{i}" in s3, f"§3 missing T0-step T0.{i}"
        # Each T0.N step has a numbered §3.M subsection (T0.0→§3.1, ...).
        assert f"§3.{i + 1}" in s3, f"§3 missing subsection §3.{i + 1}"
    assert "Strict-Flip-PR" in s3, "§3 must reference Strict-Flip-PR merge"
    assert "Walking-Skeleton" in s3, "§3 must reference Walking-Skeleton verify"
    assert "POST-ACTIVATE-CLEAN" in s3, (
        "§3 must surface POST-ACTIVATE-CLEAN as Walking-Skeleton handshake"
    )


def test_07_section4_welle_day_by_day_six_days(doc_text: str) -> None:
    s4_start = doc_text.find("## §4 ")
    s5_start = doc_text.find("## §5 ")
    s4 = doc_text[s4_start:s5_start]
    for n in range(1, 7):
        assert f"§4.{n}" in s4, f"§4 missing subsection §4.{n}"
        assert f"T0+{n}" in s4, f"§4 missing day-marker T0+{n}"
    for welle_n in range(2, 8):
        assert f"Welle-{welle_n}" in s4, f"§4 missing Welle-{welle_n} reference"
    assert "Weekend-Hold" in s4, "§4 must define KW-24 Weekend-Hold"
    assert "Marathon-Final-Bilanz" in s4, (
        "§4 must close with Marathon-Final-Bilanz at T0+6"
    )


def test_08_section5_five_rollback_paths(doc_text: str) -> None:
    s5_start = doc_text.find("## §5 ")
    s6_start = doc_text.find("## §6 ")
    s5 = doc_text[s5_start:s6_start]
    for n in range(1, 6):
        assert f"§5.{n}" in s5, f"§5 missing subsection §5.{n}"
        assert f"R{n}" in s5, f"§5 missing rollback-path R{n}"
    for marker in ("**Trigger**", "**Owner**", "**Recovery**", "**Time-budget**"):
        count = s5.count(marker)
        assert count >= 5, f"§5 needs >= 5 '{marker}', got {count}"


def test_09_section6_six_ar_touchpoints(doc_text: str) -> None:
    s6_start = doc_text.find("## §6 ")
    s7_start = doc_text.find("## §7 ")
    s6 = doc_text[s6_start:s7_start]
    for n in range(1, 7):
        assert f"§6.{n}" in s6, f"§6 missing subsection §6.{n}"
        assert f"TP{n}" in s6, f"§6 missing touchpoint TP{n}"
    for marker in ("**Question**", "**Stop-on-Fail**", "**AR-Hand**"):
        count = s6.count(marker)
        assert count >= 6, f"§6 needs >= 6 '{marker}', got {count}"


def test_10_section7_cross_reference_matrix(doc_text: str) -> None:
    s7_start = doc_text.find("## §7 ")
    s8_start = doc_text.find("## §8 ")
    s7 = doc_text[s7_start:s8_start]
    for n in range(1, 5):
        assert f"§7.{n}" in s7, f"§7 missing subtable §7.{n}"
    for ref in [
        "strict-flip-readiness-map-tag58.md",
        "bulk-activation-pre-walk-recipe.md",
        "branch-protection-required-checks-tag64-companion.md",
        "open-k3-v907-baseline-metadata-carry-forward.md",
        "phase-3c-welle-1-runbook.md",
        "phase-3c-welle-7-runbook.md",
    ]:
        assert ref in s7, f"§7 must cross-reference {ref}"


def test_11_section8_sandbox_boundary_explicit(doc_text: str) -> None:
    s8_start = doc_text.find("## §8 ")
    s9_start = doc_text.find("## §9 ")
    s8 = doc_text[s8_start:s9_start]
    assert "Sandbox-Scope" in s8, "§8 missing Sandbox-Scope block"
    assert "Out-of-Sandbox-Scope" in s8, "§8 missing Out-of-Sandbox-Scope block"
    assert "Operator-Hand-Sandbox-Gap" in s8, (
        "§8 must use Operator-Hand-Sandbox-Gap term"
    )
    assert "BULK_ACTIVATE_OPERATOR_HAND" in s8, (
        "§8 must mention BULK_ACTIVATE_OPERATOR_HAND gate"
    )
    assert "feedback_sandbox_host_trennung" in s8, (
        "§8 must reference feedback_sandbox_host_trennung memory"
    )


def test_12_section9_phase4_halt_signal_pinned(doc_text: str) -> None:
    s9_start = doc_text.find("## §9 ")
    s9 = doc_text[s9_start:]
    assert "Halt vor Phase 4" in s9, (
        "§9 must quote the AR-Vorzeichen 'Halt vor Phase 4'"
    )
    assert "PHASE-4-HOLD-VOR-RE-ARM" in s9, (
        "§9 must pin PHASE-4-HOLD-VOR-RE-ARM as canonical state"
    )
    assert "PHASE-4-RE-ARMED" in s9, (
        "§9 must specify PHASE-4-RE-ARMED as AR re-arm trigger"
    )
    for n in range(1, 7):
        assert f"§9.{n}" in s9, f"§9 missing sub-anchor §9.{n}"
    # Phase-3-Close items permitted under the pin: at least two named.
    assert "Marathon-Final-Bilanz" in s9, (
        "§9 must permit Marathon-Final-Bilanz under the pin"
    )
    assert "Post-Mortem" in s9, "§9 must permit Phase-3-Post-Mortem under the pin"


def test_13_verifier_helper_exists_and_executable() -> None:
    assert VERIFIER_PATH.exists(), f"verifier missing: {VERIFIER_PATH}"
    assert VERIFIER_PATH.stat().st_mode & 0o111, "verifier not executable"


def test_14_verifier_exits_zero_on_current_doc() -> None:
    result = _run_verifier()
    assert result.returncode == 0, (
        f"verifier failed unexpectedly:\nstdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    assert "OK" in result.stdout


def test_15_verifier_fails_when_t0_sequence_corrupted(tmp_path: Path) -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    # Remove the T0.5 step heading to simulate corruption.
    broken = doc.replace("### §3.6 — T0.5", "### §3.6 — __CORRUPT__")
    broken_doc = tmp_path / "broken-t0.md"
    broken_doc.write_text(broken, encoding="utf-8")
    result = _run_verifier(doc_override=broken_doc)
    assert result.returncode == 1, "verifier must fail when T0.5 disappears"
    assert (
        "T0-step" in result.stderr
        or "T0.5" in result.stderr
        or "T0" in result.stderr
    ), f"verifier stderr expected to mention T0-step: {result.stderr}"


def test_16_verifier_fails_when_phase4_pin_removed(tmp_path: Path) -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    # Remove the PHASE-4-HOLD-VOR-RE-ARM pin entirely.
    broken = doc.replace("PHASE-4-HOLD-VOR-RE-ARM", "PHASE-4-PIN-REMOVED")
    broken_doc = tmp_path / "broken-phase4.md"
    broken_doc.write_text(broken, encoding="utf-8")
    result = _run_verifier(doc_override=broken_doc)
    assert result.returncode == 1, (
        "verifier must fail when Phase-4 freeze-pin is removed"
    )
    assert "PHASE-4-HOLD-VOR-RE-ARM" in result.stderr or "Phase-4" in result.stderr
