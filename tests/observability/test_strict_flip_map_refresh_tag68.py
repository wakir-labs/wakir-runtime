# SPDX-License-Identifier: Apache-2.0
"""
Tag-68 Strict-Flip-Readiness-Map Refresh test-suite.

Pins the Tag-68-Append (§10 Tag-67-Carry-Forward-Update) onto the
Tag-58 Strict-Flip-Readiness-Map doc. Covers:

  - §10 header + sub-section structure §10.1..§10.7.
  - Cross-Anchor to Tag-66 PR #422 (Eve-Recipe) + Tag-67 PRs
    #425/#426/#427/#429.
  - Eve-Recipe Dry-Run verdict CLEAN.
  - Live-Smoke-Probe 4-Drift-DEFECT-carry-forward.
  - Activation-Pre-Mortem Reza-Owner anchor (Zone B).
  - Welle-N State-File byte-stable pin (Tag-67 PR #429).
  - OPEN-J3 carry-forward status unchanged (Tag-58..Tag-67).
  - 7-Pool Required-Status-Check list complete with on-main state.
  - Tag-68-Verdict matrix consistency vs. §1 gate-status.
  - Verifier helper covers §10 and fails on missing §10-sub-block.
  - Sandbox-Boundary (§8) still intact and references Tag-68 work.

Eighteen tests total.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "operations" / "strict-flip-readiness-map-tag58.md"
VERIFIER_PATH = REPO_ROOT / "tooling" / "ci" / "verify_strict_flip_readiness_map.py"

POOL_CHECKS = [
    "cosign-verify-images",
    "hash-derivate-gate",
    "cross-substrate-parity-gate",
    "cosign-keyless-oidc-drift-probe",
    "cosign-strict-mode-readiness-check",
    "trust-root-snapshot-pin-verify",
    "pre-cutover-final-sanity-gate",
]


@pytest.fixture(scope="module")
def doc_text() -> str:
    assert DOC_PATH.exists(), f"doc missing: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def section10(doc_text: str) -> str:
    s10_start = doc_text.find("## §10")
    assert s10_start > 0, "doc missing §10 header"
    # §10 is the last numbered section before the trailing rule + signature.
    rule_idx = doc_text.find("\n---\n", s10_start)
    end = rule_idx if rule_idx > 0 else len(doc_text)
    return doc_text[s10_start:end]


def _run_verifier(doc_override: Path | None = None) -> subprocess.CompletedProcess:
    if doc_override is not None:
        wrapper_src = VERIFIER_PATH.read_text(encoding="utf-8")
        patched = wrapper_src.replace(
            'DOC_PATH = (\n    Path(__file__).resolve().parents[2]\n'
            '    / "docs"\n    / "operations"\n    / "strict-flip-readiness-map-tag58.md"\n)',
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


def test_01_section10_header_present(doc_text: str) -> None:
    assert "## §10 — Tag-67-Carry-Forward-Update" in doc_text, (
        "doc must include §10 Tag-67-Carry-Forward-Update header"
    )


def test_02_section10_all_seven_sub_sections(section10: str) -> None:
    for sub in [
        "§10.1",
        "§10.2",
        "§10.3",
        "§10.4",
        "§10.5",
        "§10.6",
        "§10.7",
    ]:
        assert f"### {sub}" in section10, f"§10 missing sub-section {sub}"


def test_03_section10_carry_forward_source_table(section10: str) -> None:
    # Cross-anchor table lists Tag-58..Tag-67 PR sources.
    for pr_ref in ["#369", "#408", "#422", "#425", "#426", "#427", "#429"]:
        assert pr_ref in section10, (
            f"§10 carry-forward source-table missing PR ref {pr_ref}"
        )


def test_04_section10_1_eve_recipe_clean_dry_run(section10: str) -> None:
    s101_start = section10.find("### §10.1")
    s102_start = section10.find("### §10.2")
    assert 0 < s101_start < s102_start
    block = section10[s101_start:s102_start]
    assert "PR #422" in block, "§10.1 must anchor Tag-66 PR #422 (Eve-Recipe)"
    assert "PR #426" in block, "§10.1 must anchor Tag-67 PR #426 (Dry-Run)"
    assert "CLEAN" in block, "§10.1 must record Dry-Run-Verdict CLEAN"
    assert "operator-hand-cutover-eve-final-recipe.md" in block, (
        "§10.1 must reference the Eve-Recipe doc path"
    )


def test_05_section10_2_live_smoke_four_drifts(section10: str) -> None:
    s102_start = section10.find("### §10.2")
    s103_start = section10.find("### §10.3")
    assert 0 < s102_start < s103_start
    block = section10[s102_start:s103_start]
    assert "PR #425" in block, "§10.2 must anchor Noa Tag-67 PR #425"
    assert "4 Drift" in block, "§10.2 must record 4 Drift-Stages"
    assert "DRIFT" in block and "DEFECT" in block, (
        "§10.2 must reference DRIFT and DEFECT verdict markers"
    )
    # Stage-2..Stage-5 named explicitly as affected
    for stage in ["Stage-2", "Stage-3", "Stage-4", "Stage-5"]:
        assert stage in block, f"§10.2 must name affected {stage}"


def test_06_section10_3_pre_mortem_reza_anchor(section10: str) -> None:
    s103_start = section10.find("### §10.3")
    s104_start = section10.find("### §10.4")
    assert 0 < s103_start < s104_start
    block = section10[s103_start:s104_start]
    assert "PR #427" in block, "§10.3 must anchor Reza Tag-67 PR #427"
    assert "Reza" in block, "§10.3 must name Reza as owner"
    assert "Zone B" in block, "§10.3 must cross-anchor to Zone B"
    assert "v0.4.4" in block, "§10.3 must reference Wirelang-Spec v0.4.4"


def test_07_section10_4_welle_n_state_files(section10: str) -> None:
    s104_start = section10.find("### §10.4")
    s105_start = section10.find("### §10.5")
    assert 0 < s104_start < s105_start
    block = section10[s104_start:s105_start]
    assert "PR #429" in block, "§10.4 must anchor Amara Tag-67 PR #429"
    assert "welle-1.json" in block and "welle-7.json" in block, (
        "§10.4 must reference welle-1..7 state-file paths"
    )
    assert "BYTE-STABLE-PRE-CUTOVER-T0" in block or "byte-stable" in block.lower(), (
        "§10.4 must record byte-stable pin-status"
    )


def test_08_section10_5_open_j3_carry_forward_unchanged(section10: str) -> None:
    s105_start = section10.find("### §10.5")
    s106_start = section10.find("### §10.6")
    assert 0 < s105_start < s106_start
    block = section10[s105_start:s106_start]
    assert "OPEN-J3" in block, "§10.5 must reference OPEN-J3 item"
    assert "intentional-carry-forward" in block, (
        "§10.5 must record carry-forward status as intentional"
    )
    assert "J3-A" in block and "J3-G" in block, (
        "§10.5 must reference the J3-A..J3-G refresh sub-sequence"
    )
    # Cross-anchor to §9 + §6 T7
    assert "§9" in block, "§10.5 must cross-reference §9 (Tag-64-Append)"
    assert "T7" in block, "§10.5 must cross-reference §6 T7 sequence step"


def test_09_section10_6_seven_pool_checks_complete(section10: str) -> None:
    s106_start = section10.find("### §10.6")
    s107_start = section10.find("### §10.7")
    assert 0 < s106_start < s107_start
    block = section10[s106_start:s107_start]
    for chk in POOL_CHECKS:
        assert chk in block, f"§10.6 missing pool-required check '{chk}'"
    # All 7 pool checks listed
    assert "7-Pool" in block or "7 Pool" in block, (
        "§10.6 must reference the 7-Pool Required-Status-Check target"
    )
    # Branch-Protection activation pending
    assert "pending-T0" in block, (
        "§10.6 must mark Branch-Protection activation as pending-T0"
    )


def test_10_section10_6_eight_pool_extension_note(section10: str) -> None:
    s106_start = section10.find("### §10.6")
    s107_start = section10.find("### §10.7")
    block = section10[s106_start:s107_start]
    # Tag-64 OPEN-J3 8-check extension is annotated, not part of 7-pool.
    assert "8-Pool" in block or "8. Check" in block or "8th" in block.lower() \
        or "post-Cutover-T0" in block, (
        "§10.6 must annotate the 8-Pool extension as post-Cutover-T0 Kai-Hand"
    )


def test_11_section10_7_tag68_verdict_matrix(section10: str) -> None:
    s107_start = section10.find("### §10.7")
    assert s107_start > 0
    block = section10[s107_start:]
    # Verdict matrix mentions all carry-forward axes.
    for axis in [
        "G1",
        "G2",
        "G3..G6",
        "Cutover-Eve-Recipe",
        "Live-Smoke-Probe",
        "Activation-Pre-Mortem",
        "Welle-N State-Files",
        "OPEN-J3",
        "7-Pool",
    ]:
        assert axis in block, f"§10.7 verdict-matrix missing axis '{axis}'"
    assert "BLOCKED" in block, "§10.7 must keep G1+G2 BLOCKED status"
    assert "GREEN" in block, "§10.7 must keep G3..G6 GREEN status"


def test_12_section10_no_cutover_slip(section10: str) -> None:
    # Tag-68 verdict should NOT slip the KW-24 cutover date.
    s107_start = section10.find("### §10.7")
    block = section10[s107_start:]
    assert "2026-06-08" in block, "§10.7 must keep 2026-06-08 as T0-date"
    assert "Kein Phase-3-Cutover-Slip" in block or "no slip" in block.lower(), (
        "§10.7 must explicitly state no Phase-3-Cutover-Slip"
    )


def test_13_section10_signature_updated(doc_text: str) -> None:
    assert "Tag-68-Append" in doc_text, (
        "doc signature must record the Tag-68-Append carry-forward edit"
    )
    # Signature line should also still keep Tag-58 + Tag-64 anchors.
    assert "Tag-58 Original" in doc_text, (
        "doc signature must keep Tag-58 Original anchor"
    )
    assert "Tag-64-Append" in doc_text, (
        "doc signature must keep Tag-64-Append anchor"
    )


def test_14_verifier_recognises_section10(doc_text: str) -> None:
    result = _run_verifier()
    assert result.returncode == 0, (
        f"verifier must pass with §10 present:\n{result.stdout}\n{result.stderr}"
    )
    assert "10 sections" in result.stdout, (
        "verifier OK-message must announce 10 sections post Tag-68"
    )


def test_15_verifier_fails_when_section10_removed(tmp_path: Path) -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    # Drop the entire §10 block to simulate regression.
    s10_idx = doc.find("## §10 — Tag-67-Carry-Forward-Update")
    assert s10_idx > 0
    # Strip from §10 through end-of-doc; keep the trailing signature line so
    # the doc still ends gracefully.
    sig_idx = doc.rfind("— Kai (Tag-58 Original")
    broken = doc[:s10_idx] + doc[sig_idx:] if sig_idx > s10_idx else doc[:s10_idx]
    broken_doc = tmp_path / "broken_no_s10.md"
    broken_doc.write_text(broken, encoding="utf-8")
    result = _run_verifier(doc_override=broken_doc)
    assert result.returncode == 1, "verifier must fail when §10 is missing"
    assert "§10" in result.stderr or "missing section" in result.stderr.lower()


def test_16_verifier_fails_when_pool_check_missing(tmp_path: Path) -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    # Surgically drop the §10.6 pool-check `pre-cutover-final-sanity-gate`.
    # That string only occurs once in the doc (in §10.6), so the test
    # is unambiguous.
    target = "pre-cutover-final-sanity-gate"
    assert doc.count(target) == 1, (
        "test pre-condition: pre-cutover-final-sanity-gate occurs exactly once "
        "in the doc; if this changes, pick a different §10.6-unique pool-check"
    )
    broken = doc.replace(target, "REMOVED-FOR-TEST")
    broken_doc = tmp_path / "broken_pool.md"
    broken_doc.write_text(broken, encoding="utf-8")
    result = _run_verifier(doc_override=broken_doc)
    assert result.returncode == 1, "verifier must fail when pool-check missing"
    assert target in result.stderr or "pool-required" in result.stderr.lower()


def test_17_existing_tag58_invariants_preserved(doc_text: str) -> None:
    """Tag-68 must not regress Tag-58 + Tag-64 invariants."""
    # Gate-table still G1..G6 with 2 BLOCKED + 4 GREEN in §1 slice.
    s1_start = doc_text.find("## §1")
    s2_start = doc_text.find("## §2")
    s1 = doc_text[s1_start:s2_start]
    blocked = len(re.findall(r"\*\*BLOCKED\*\*", s1))
    green = len(re.findall(r"\*\*GREEN\*\*", s1))
    assert blocked == 2, f"§1 gate-table must keep 2 BLOCKED (got {blocked})"
    assert green == 4, f"§1 gate-table must keep 4 GREEN (got {green})"
    # §9 OPEN-J3 sub-blocks still intact.
    s9_start = doc_text.find("## §9")
    s10_start = doc_text.find("## §10")
    s9 = doc_text[s9_start:s10_start]
    for sub in ["§9.1", "§9.2", "§9.3", "§9.4", "§9.5"]:
        assert f"### {sub}" in s9, f"§9 sub-section {sub} regressed"


def test_18_section10_no_sandbox_violation_claim(section10: str) -> None:
    """§10 must not claim Mira-Sandbox ran any out-of-scope operation."""
    # Live-Smoke = Operator-Hand; Eve-Recipe Run = Operator-Hand;
    # Sandbox is OK for Recipe-Authoring + Dry-Run-Probe.
    forbidden = [
        "Sandbox executed",
        "podman-Socket-Zugriff",
        "Live-Cosign-Sign",
        "Live-Trust-Root-Pull",
    ]
    for phrase in forbidden:
        assert phrase not in section10, (
            f"§10 must not claim Sandbox executed '{phrase}'"
        )
    # Eve-Recipe + Dry-Run must be marked as in-Sandbox; Live-Execution must
    # be marked as Operator-Hand.
    s101_start = section10.find("### §10.1")
    s102_start = section10.find("### §10.2")
    block = section10[s101_start:s102_start]
    assert "Operator-Hand" in block, (
        "§10.1 must mark Live-Execution as Operator-Hand"
    )
