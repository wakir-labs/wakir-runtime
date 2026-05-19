"""
Tag-64 OPEN-J3 Containerfile-Label Carry-Forward test-suite.

Tag-64-Decision: Carry-Forward (kein Pre-Cutover-Cleanup).
Quelle: Tag-63 Selin-Audit §D6 OPEN-J3 = intentional carry-forward,
blocker-for-cutover-image-build (KW-24 Kai-Hand-Image-Rebuild post
Cutover-T0). Tag-62-Release-Notes §1 Out-of-Scope.

Covers:
  - Strict-Flip-Readiness-Map §9 OPEN-J3-Append-Substanz.
  - Containerfile.real LABEL byte-stability (`0.5.2-final-pre-cutover`).
  - Forbidden premature `0.5.3` LABEL absence (drift-detection).
  - 7 OCI image LABEL keys present (ADR-0061 LABEL-Konvention).
  - §9.3 J3-A..J3-G refresh-sub-sequence (7 sub-T steps).
  - Audit-alignment (Tag-63 §D6 verdict MATCH-WITH-1-INTENTIONAL-
    CARRY-FORWARD).
  - Verifier helper exits 0 on current substrate.
  - Verifier helper exits 1 on simulated premature 0.5.3 refresh.
  - Tag-58 incumbent verifier still green (§1..§8 untouched).
  - Decision-Begründungs-3-Anker (Scope-Split, Domain-Boundary,
    Byte-Stability) im §9.2.
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
CONTAINERFILE_PATH = REPO_ROOT / "infra" / "persona-engine" / "Containerfile.real"
AUDIT_PATH = (
    REPO_ROOT
    / "reports"
    / "audit"
    / "persona-engine-0-5-3-production-readiness-2026-05-19.md"
)
VERIFIER_PATH = (
    REPO_ROOT
    / "tooling"
    / "ci"
    / "verify_open_j3_containerfile_label_carry_forward.py"
)
TAG58_VERIFIER_PATH = (
    REPO_ROOT / "tooling" / "ci" / "verify_strict_flip_readiness_map.py"
)


@pytest.fixture(scope="module")
def doc_text() -> str:
    assert DOC_PATH.exists(), f"doc missing: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def containerfile_text() -> str:
    assert CONTAINERFILE_PATH.exists(), f"containerfile missing: {CONTAINERFILE_PATH}"
    return CONTAINERFILE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def audit_text() -> str:
    assert AUDIT_PATH.exists(), f"audit missing: {AUDIT_PATH}"
    return AUDIT_PATH.read_text(encoding="utf-8")


def _run(cmd_path: Path, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(cmd_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _run_verifier_with_patched_containerfile(patched_cf: Path) -> subprocess.CompletedProcess:
    src = VERIFIER_PATH.read_text(encoding="utf-8")
    # Pin REPO_ROOT to the real repo so DOC_PATH + AUDIT_PATH still resolve;
    # only redirect CONTAINERFILE_PATH to the drifted fixture.
    patched = src.replace(
        "REPO_ROOT = Path(__file__).resolve().parents[2]",
        f'REPO_ROOT = Path(r"{REPO_ROOT}")',
    ).replace(
        'CONTAINERFILE_PATH = REPO_ROOT / "infra" / "persona-engine" / "Containerfile.real"',
        f'CONTAINERFILE_PATH = Path(r"{patched_cf}")',
    )
    assert 'CONTAINERFILE_PATH = Path(r"' in patched, "patch did not apply"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
        tmp.write(patched)
        tmp_path = tmp.name
    return subprocess.run(
        [sys.executable, tmp_path],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_01_doc_has_section9_open_j3_header(doc_text: str) -> None:
    assert "## §9 — OPEN-J3 Containerfile-Label Carry-Forward" in doc_text, (
        "Tag-58 readiness map missing the Tag-64 OPEN-J3 §9 append"
    )


def test_02_section9_all_five_subsections_present(doc_text: str) -> None:
    s9_start = doc_text.find("## §9 — OPEN-J3")
    s9 = doc_text[s9_start:]
    for sub in ["§9.1", "§9.2", "§9.3", "§9.4", "§9.5"]:
        assert f"### {sub}" in s9, f"§9 missing subsection {sub}"


def test_03_section9_decision_anchors_three_reasons(doc_text: str) -> None:
    s9_start = doc_text.find("## §9 — OPEN-J3")
    s9 = doc_text[s9_start:]
    # Decision-Begründungs-Anker: Scope-Split, Domain-Boundary, Byte-Stability.
    assert "Scope-Split-Disziplin" in s9, "§9.2 missing Scope-Split reason"
    assert "Domain-Boundary" in s9, "§9.2 missing Domain-Boundary reason"
    assert "Byte-Stability-Anker" in s9, "§9.2 missing Byte-Stability reason"


def test_04_section9_3_j3_sub_sequence_seven_steps(doc_text: str) -> None:
    s9_start = doc_text.find("## §9 — OPEN-J3")
    s9 = doc_text[s9_start:]
    for step in ["J3-A", "J3-B", "J3-C", "J3-D", "J3-E", "J3-F", "J3-G"]:
        assert f"| {step} |" in s9, f"§9.3 missing J3-sub-T step {step}"


def test_05_containerfile_carries_forward_0_5_2_label(containerfile_text: str) -> None:
    assert (
        'LABEL org.opencontainers.image.version="0.5.2-final-pre-cutover"'
        in containerfile_text
    ), "Containerfile.real must carry the 0.5.2-final-pre-cutover image-version LABEL"


def test_06_containerfile_does_not_have_premature_0_5_3_label(
    containerfile_text: str,
) -> None:
    assert (
        'LABEL org.opencontainers.image.version="0.5.3"' not in containerfile_text
    ), (
        "Containerfile.real must NOT carry a premature 0.5.3 image-version "
        "LABEL — refresh is a KW-24 cutover-image-build Kai-Hand-action "
        "(see §9.3 J3-A..J3-G)."
    )


def test_07_containerfile_has_all_seven_oci_label_keys(containerfile_text: str) -> None:
    required_keys = [
        "org.opencontainers.image.title",
        "org.opencontainers.image.description",
        "org.opencontainers.image.version",
        "org.opencontainers.image.licenses",
        "org.opencontainers.image.source",
        "org.opencontainers.image.url",
        "org.opencontainers.image.documentation",
    ]
    for key in required_keys:
        assert f"LABEL {key}=" in containerfile_text, (
            f"Containerfile.real missing OCI LABEL key {key} "
            f"(ADR-0061 LABEL-Konvention)"
        )


def test_08_containerfile_no_duplicate_label_keys(containerfile_text: str) -> None:
    label_keys = re.findall(r"^LABEL\s+([\w\.\-]+)=", containerfile_text, re.MULTILINE)
    duplicates = {k for k in label_keys if label_keys.count(k) > 1}
    assert not duplicates, f"Containerfile.real has duplicate LABEL keys: {sorted(duplicates)}"


def test_09_audit_report_references_open_j3_intentional_carry_forward(
    audit_text: str,
) -> None:
    assert "OPEN-J3" in audit_text, "Tag-63 audit report missing OPEN-J3 reference"
    assert (
        "intentional carry-forward" in audit_text
        or "intentional-carry-forward" in audit_text
    ), "Tag-63 audit OPEN-J3 must be marked intentional carry-forward"


def test_10_audit_report_d6_verdict_match_with_carry_forward(audit_text: str) -> None:
    assert "MATCH-WITH-1-INTENTIONAL-CARRY-FORWARD" in audit_text, (
        "Tag-63 audit §3.6 verdict MATCH-WITH-1-INTENTIONAL-CARRY-FORWARD "
        "missing — drift in audit-substrate"
    )


def test_11_section9_4_carry_forward_status_table(doc_text: str) -> None:
    s9_start = doc_text.find("## §9 — OPEN-J3")
    s9 = doc_text[s9_start:]
    # Key rows in the §9.4 status table.
    for row_marker in (
        "| Item-ID | OPEN-J3 |",
        "| Owner | Kai (Zone-J) |",
        "| Status | `intentional-carry-forward` |",
        "| Tag-64-Decision | Carry-Forward",
    ):
        assert row_marker in s9, f"§9.4 status-table missing row: {row_marker}"


def test_12_section9_references_audit_source_path(doc_text: str) -> None:
    s9_start = doc_text.find("## §9 — OPEN-J3")
    s9 = doc_text[s9_start:]
    assert (
        "reports/audit/persona-engine-0-5-3-production-readiness-2026-05-19.md" in s9
    ), "§9.1 must cite the Tag-63 audit source path verbatim"


def test_13_verifier_helper_exists_and_executable() -> None:
    assert VERIFIER_PATH.exists(), f"verifier missing: {VERIFIER_PATH}"
    assert VERIFIER_PATH.stat().st_mode & 0o111, "verifier not executable"


def test_14_verifier_exits_zero_on_current_substrate() -> None:
    result = _run(VERIFIER_PATH)
    assert result.returncode == 0, (
        f"OPEN-J3 verifier failed unexpectedly:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "OK" in result.stdout


def test_15_verifier_detects_premature_0_5_3_refresh(tmp_path: Path) -> None:
    """If someone prematurely refreshes the LABEL to 0.5.3 before
    KW-24 cutover-image-build, the verifier MUST catch it as drift."""
    cf = CONTAINERFILE_PATH.read_text(encoding="utf-8")
    drifted = cf.replace(
        'LABEL org.opencontainers.image.version="0.5.2-final-pre-cutover"',
        'LABEL org.opencontainers.image.version="0.5.3"',
    )
    drifted_cf = tmp_path / "Containerfile.real.drifted"
    drifted_cf.write_text(drifted, encoding="utf-8")
    result = _run_verifier_with_patched_containerfile(drifted_cf)
    assert result.returncode == 1, (
        "OPEN-J3 verifier must detect premature 0.5.3 LABEL refresh as drift"
    )
    # Verifier may report drift either as "premature 0.5.3" or as
    # "missing 0.5.2-final-pre-cutover carry-forward" — both are valid
    # drift signals. We accept either marker.
    err = result.stderr.lower()
    assert (
        "0.5.3" in result.stderr
        or "prematurely" in err
        or "carry-forward" in err
        or "0.5.2-final-pre-cutover" in result.stderr
    ), f"verifier drift-message lacks expected marker: {result.stderr!r}"


def test_16_tag58_incumbent_verifier_still_green() -> None:
    """Appending §9 must not break the Tag-58 §1..§8 invariants."""
    result = _run(TAG58_VERIFIER_PATH)
    assert result.returncode == 0, (
        f"Tag-58 verifier broke after Tag-64 §9 append:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_17_section9_signed_by_kai_tag64_append(doc_text: str) -> None:
    assert "Tag-58 Original, Tag-64-Append 2026-05-19" in doc_text, (
        "Doc footer must reflect the Tag-64-Append authorship trail"
    )
