"""
Tag-58 Strict-Flip-Readiness-Map doc + verifier test-suite.

Covers:
  - Doc existence + structural integrity.
  - All 8 sections (§1..§8) present in order.
  - §1 gate-table covers G1..G6 with explicit BLOCKED/GREEN markers.
  - §1 records exactly 2 BLOCKED (G1, G2) + 4 GREEN (G3..G6).
  - §2 7-day-calendar lists Day-1..Day-7 with operator-hand-sandbox-gap marker.
  - §3 lists G1.1..G1.5 (4 wellen + pilot persona).
  - §4 lists G2.1..G2.3 with trust-root snapshot files.
  - §5 hold-steady probes for G3..G6.
  - §6 cutover-day sequence T0..T9 (10 steps).
  - §7 Decision-A (G1-fail Welle-1) + Decision-B (G2-fail Welle-2).
  - §8 sandbox-boundary explicit scope/out-of-scope.
  - Verifier helper exists, is executable, exits 0 on current doc.
  - Verifier helper fails when sections are removed.
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


@pytest.fixture(scope="module")
def doc_text() -> str:
    assert DOC_PATH.exists(), f"doc missing: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


def _run_verifier(doc_override: Path | None = None) -> subprocess.CompletedProcess:
    env = None
    if doc_override is not None:
        # Run by patching the doc-path through a wrapper invocation.
        # Verifier reads a fixed path; for failure-mode tests we copy the
        # verifier into a temp dir with a patched DOC_PATH constant.
        wrapper_src = VERIFIER_PATH.read_text(encoding="utf-8")
        patched = wrapper_src.replace(
            'DOC_PATH = (\n    Path(__file__).resolve().parents[2]\n'
            '    / "docs"\n    / "operations"\n    / "strict-flip-readiness-map-tag58.md"\n)',
            f'DOC_PATH = Path(r"{doc_override}")',
        )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False
        ) as tmp:
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


def test_01_doc_exists(doc_text: str) -> None:
    assert len(doc_text) > 1000, "doc looks suspiciously short"


def test_02_doc_frontmatter_owner_and_tag(doc_text: str) -> None:
    assert 'owner: "kai"' in doc_text
    assert 'tag: "tag-58"' in doc_text


def test_03_all_eight_sections_present_in_order(doc_text: str) -> None:
    positions = []
    for section in ["§1", "§2", "§3", "§4", "§5", "§6", "§7", "§8"]:
        idx = doc_text.find(f"## {section}")
        assert idx >= 0, f"missing section header {section}"
        positions.append(idx)
    assert positions == sorted(positions), "sections out of order"


def test_04_section1_gate_table_all_six_gates(doc_text: str) -> None:
    for gate in ["G1", "G2", "G3", "G4", "G5", "G6"]:
        assert f"| {gate} |" in doc_text, f"§1 table missing row for {gate}"


def test_05_section1_two_blocked_four_green(doc_text: str) -> None:
    # Slice just §1 to avoid double-counting elsewhere.
    s1_start = doc_text.find("## §1")
    s2_start = doc_text.find("## §2")
    s1 = doc_text[s1_start:s2_start]
    blocked = len(re.findall(r"\*\*BLOCKED\*\*", s1))
    green = len(re.findall(r"\*\*GREEN\*\*", s1))
    assert blocked == 2, f"expected exactly 2 **BLOCKED**, got {blocked}"
    assert green == 4, f"expected exactly 4 **GREEN**, got {green}"


def test_06_section2_seven_day_calendar(doc_text: str) -> None:
    s2_start = doc_text.find("## §2")
    s3_start = doc_text.find("## §3")
    s2 = doc_text[s2_start:s3_start]
    for day in ["Day-1", "Day-2", "Day-3", "Day-4", "Day-5", "Day-6", "Day-7"]:
        assert day in s2, f"§2 missing {day}"
    assert "Operator-Hand-Sandbox-Gap" in s2, (
        "§2 must mark operator-hand items as Operator-Hand-Sandbox-Gap"
    )


def test_07_section3_g1_recipe_five_targets(doc_text: str) -> None:
    s3_start = doc_text.find("## §3")
    s4_start = doc_text.find("## §4")
    s3 = doc_text[s3_start:s4_start]
    for target in ["G1.1", "G1.2", "G1.3", "G1.4", "G1.5"]:
        assert f"### {target}" in s3, f"§3 missing target {target}"
    # Quadlet + Pilot-Persona references
    assert "Quadlet" in s3, "§3 must reference Quadlet"
    assert "Pilot-Persona" in s3 or "mira-pilot" in s3, (
        "§3 must reference Pilot-Persona / mira-pilot"
    )
    assert "cosign verify --strict" in s3, (
        "§3 must show the cosign verify --strict invocation"
    )


def test_08_section4_g2_recipe_three_phases(doc_text: str) -> None:
    s4_start = doc_text.find("## §4")
    s5_start = doc_text.find("## §5")
    s4 = doc_text[s4_start:s5_start]
    for phase in ["G2.1", "G2.2", "G2.3"]:
        assert f"### {phase}" in s4, f"§4 missing phase {phase}"
    for fname in ["root.json", "fulcio.pub", "rekor.pub"]:
        assert fname in s4, f"§4 missing trust-root file reference: {fname}"
    assert "MANIFEST.sha256" in s4, "§4 must reference SHA-256 MANIFEST"


def test_09_section5_hold_steady_g3_to_g6(doc_text: str) -> None:
    s5_start = doc_text.find("## §5")
    s6_start = doc_text.find("## §6")
    s5 = doc_text[s5_start:s6_start]
    for gate in ["G3", "G4", "G5", "G6"]:
        assert f"### {gate} " in s5, f"§5 missing Hold-Steady for {gate}"
    assert "Daily-Cron" in s5 or "daily-cron" in s5.lower(), (
        "§5 must reference Daily-Cron monitoring"
    )


def test_10_section6_cutover_day_t0_to_t9(doc_text: str) -> None:
    s6_start = doc_text.find("## §6")
    s7_start = doc_text.find("## §7")
    s6 = doc_text[s6_start:s7_start]
    for t in [f"T{i}" for i in range(10)]:
        assert f"| {t} |" in s6, f"§6 missing cutover-day step {t}"
    assert "2026-06-08" in s6, "§6 must name the cutover-day date"


def test_11_section7_two_decisions(doc_text: str) -> None:
    s7_start = doc_text.find("## §7")
    s8_start = doc_text.find("## §8")
    s7 = doc_text[s7_start:s8_start]
    assert "### Decision-A" in s7, "§7 missing Decision-A"
    assert "### Decision-B" in s7, "§7 missing Decision-B"
    assert "Welle-1" in s7 and "Welle-2" in s7, (
        "§7 must reference both Welle-1 (G1-fail) and Welle-2 (G2-fail)"
    )
    assert "KW-25" in s7, (
        "§7 must name the fallback cutover-week (KW-25) for rollback path"
    )


def test_12_section8_sandbox_boundary_explicit(doc_text: str) -> None:
    s8_start = doc_text.find("## §8")
    s8 = doc_text[s8_start:]
    assert "Sandbox-Scope" in s8, "§8 missing Sandbox-Scope block"
    assert "Out-of-Sandbox-Scope" in s8, "§8 missing Out-of-Sandbox-Scope block"
    assert "Operator-Hand-Sandbox-Gap" in s8, (
        "§8 must explicitly use Operator-Hand-Sandbox-Gap term"
    )
    assert "Host-podman-Socket" in s8 or "podman" in s8.lower(), (
        "§8 must reference podman-socket sandbox-boundary"
    )


def test_13_verifier_helper_exists_and_executable() -> None:
    assert VERIFIER_PATH.exists(), f"verifier missing: {VERIFIER_PATH}"
    assert VERIFIER_PATH.stat().st_mode & 0o111, "verifier not executable"


def test_14_verifier_exits_zero_on_current_doc() -> None:
    result = _run_verifier()
    assert result.returncode == 0, (
        f"verifier failed unexpectedly:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "OK" in result.stdout


def test_15_verifier_fails_when_section_removed(tmp_path: Path) -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    # Remove §7 header to simulate corruption.
    broken = doc.replace("## §7 — Failure-Recovery-Decisions", "## __corrupt__")
    broken_doc = tmp_path / "broken.md"
    broken_doc.write_text(broken, encoding="utf-8")
    result = _run_verifier(doc_override=broken_doc)
    assert result.returncode == 1, "verifier must fail on missing §7"
    assert "§7" in result.stderr or "missing section" in result.stderr.lower()


def test_16_verifier_fails_on_empty_recipe_stage(tmp_path: Path) -> None:
    doc = DOC_PATH.read_text(encoding="utf-8")
    # Strip body of G1.1 to leave heading orphan.
    g1_1_idx = doc.find("### G1.1 Welle-1-Quadlet")
    g1_2_idx = doc.find("### G1.2 Welle-2-Quadlet")
    assert g1_1_idx > 0 and g1_2_idx > g1_1_idx
    head = doc[:g1_1_idx]
    heading_line_end = doc.find("\n", g1_1_idx) + 1
    tail = doc[g1_2_idx:]
    broken = head + doc[g1_1_idx:heading_line_end] + "\n" + tail
    broken_doc = tmp_path / "broken.md"
    broken_doc.write_text(broken, encoding="utf-8")
    result = _run_verifier(doc_override=broken_doc)
    assert result.returncode == 1, "verifier must fail on empty recipe stage"
    assert "G1.1" in result.stderr or "too thin" in result.stderr.lower()


def test_17_doc_links_back_to_tag56_setup_guide(doc_text: str) -> None:
    assert "cosign-g1-g2-operator-setup.md" in doc_text, (
        "doc must reference the Tag-56 G1/G2 setup-guide"
    )


def test_18_doc_targets_kw24_cutover(doc_text: str) -> None:
    assert "KW-24" in doc_text, "doc must explicitly target KW-24 cutover"
    assert "2026-06-08" in doc_text, (
        "doc must name 2026-06-08 as cutover-day-T0"
    )
