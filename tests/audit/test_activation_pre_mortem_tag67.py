# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-67 tests for the Wirelang-Spec v0.4.4 Activation
Pre-Mortem doc.
=========================================================================

Two-axis coverage:

  Axis A -- Doc-shape invariants over the live Tag-67 doc
            ``docs/operations/wirelang-spec-v0-4-4-activation-pre-mortem.md``
            (skip-if-absent for portability).
  Axis B -- Helper smoke-tests via subprocess against
            ``tooling/audit/verify_activation_pre_mortem_doc.py``,
            optionally driven through hermetic fixture variants
            in ``tmp_path`` for malformed-doc detection.

Test inventory (>=12 hermetic, all stdlib + pytest):

  T01  Doc file exists at the expected path.
  T02  Doc carries the doc-license SPDX header (CC-BY-4.0 posture).
  T03  Doc declares the Tag-67 title with the ``Activation
       Pre-Mortem`` marker in the top-level ``#`` heading.
  T04  Doc carries seven top-level sections (§1..§7) in order.
  T05  §1 scope declares the doc-form-only posture, the
       informative-skizze posture (GOVERNANCE.md §10), the
       five-RES-Dn coverage statement, and the four-axis
       classifier (failure-mode / likelihood / impact /
       mitigation / detection) for table rows.
  T06  §2..§6 each carry a RES-Dn-specific failure-mode-inventory
       sub-section, name the RES-D tag, and include the five
       table-header columns.
  T07  Each of §2..§6 enumerates ten failure-mode codes
       (A1..A5, B1..B5) as table-row markers.
  T08  Each of §2..§6 carries a residual-risk sub-section.
  T09  §7 aggregate-risk-map carries the four required blocks
       (cross-item failure-mode aggregation, cross-item hot
       spots, residual-risk distribution, cross-anchor).
  T10  §7 cross-anchor cites ADR-0007, ADR-0014, ADR-0023a,
       ADR-0023b, ADR-0025, GOVERNANCE.md, and Tag-44 / Tag-58 /
       Tag-60 / Tag-63 / Tag-64 / Tag-65 / Tag-66 Tag-N pointers.
  T11  Doc ends with a ``-- Reza`` signature line.
  T12  Helper subprocess: verify_activation_pre_mortem_doc.py
       exits 0 on the live Tag-67 doc.
  T13  Helper subprocess: when the doc is replaced by a stripped
       fixture (§4 removed), the helper exits non-zero with a
       diagnostic naming the missing section.
  T14  RES-D4 high-risk-flag invariant: the doc must explicitly
       call RES-D4's residual rating ``high`` and reference live
       OTS-anchor activation as the dominant residual driver.
  T15  Doc cites Tag-65 promotion-sequencing doc as upstream
       sequencing-authority and Tag-66 PR #421 as upstream
       OTS-probe-coverage authority (audit-trail invariant).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_REL = "docs/operations/wirelang-spec-v0-4-4-activation-pre-mortem.md"
DOC_PATH = REPO_ROOT / DOC_REL
HELPER_REL = "tooling/audit/verify_activation_pre_mortem_doc.py"
HELPER_PATH = REPO_ROOT / HELPER_REL


REQUIRED_TOP_SECTIONS = (
    "## 1.", "## 2.", "## 3.", "## 4.",
    "## 5.", "## 6.", "## 7.",
)
REQUIRED_RES_D_FOR_SECTION = {
    "## 2.": "RES-D1",
    "## 3.": "RES-D2",
    "## 4.": "RES-D3",
    "## 5.": "RES-D4",
    "## 6.": "RES-D5",
}
REQUIRED_FAILURE_CODES = (
    "A1", "A2", "A3", "A4", "A5",
    "B1", "B2", "B3", "B4", "B5",
)
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


# --------------------------------------------------------------- #
# Live-doc fixtures                                                #
# --------------------------------------------------------------- #


def _load_doc() -> str:
    if not DOC_PATH.exists():
        pytest.skip(f"Tag-67 doc not present at {DOC_REL}")
    return DOC_PATH.read_text(encoding="utf-8")


def _split_top_sections(text: str) -> dict:
    """Return {marker: body} for §1..§7 top-level headers."""
    out: dict = {}
    positions = []
    for marker in REQUIRED_TOP_SECTIONS:
        idx = text.find(marker)
        positions.append((marker, idx))
    positions.append(("__end__", len(text)))
    for i in range(len(REQUIRED_TOP_SECTIONS)):
        marker, start = positions[i]
        _, end = positions[i + 1]
        out[marker] = text[start:end] if start >= 0 else ""
    return out


# --------------------------------------------------------------- #
# Axis A -- doc-shape invariants                                  #
# --------------------------------------------------------------- #


def test_t01_doc_file_exists():
    assert DOC_PATH.exists(), f"Tag-67 doc missing at {DOC_REL}"


# REUSE-IgnoreStart
def test_t02_doc_carries_cc_by_4_0_spdx_header():
    text = _load_doc()
    assert "SPDX-License-Identifier: CC-BY-4.0" in text, (
        "Tag-67 doc must carry CC-BY-4.0 SPDX header"
    )
# REUSE-IgnoreEnd


def test_t03_doc_title_carries_tag67_and_activation_pre_mortem():
    text = _load_doc()
    first_h1 = None
    for line in text.splitlines():
        if line.startswith("# "):
            first_h1 = line
            break
    assert first_h1 is not None, "doc must contain a top-level '# ' title"
    assert "Tag-67" in first_h1, f"title missing 'Tag-67': {first_h1!r}"
    assert "Activation Pre-Mortem" in first_h1, (
        f"title missing 'Activation Pre-Mortem': {first_h1!r}"
    )


def test_t04_seven_top_level_sections_in_order():
    text = _load_doc()
    last = -1
    for marker in REQUIRED_TOP_SECTIONS:
        idx = text.find(marker)
        assert idx >= 0, f"missing top-level section marker '{marker}'"
        assert idx > last, (
            f"section '{marker}' out of order "
            f"(idx={idx} <= last={last})"
        )
        last = idx


def test_t05_scope_declares_doc_form_only_and_four_axis_classifier():
    text = _load_doc()
    sections = _split_top_sections(text)
    s1 = sections["## 1."]
    normalised = re.sub(r"\s+", " ", s1)
    # Posture phrases (case-sensitive).
    for needle in (
        "doc-form only",
        "informative skizze",
        "RES-D1 .. RES-D5",
        "Out of scope",
    ):
        assert needle in normalised, (
            f"§1 scope missing posture phrase '{needle}'"
        )
    # Four-axis classifier (case-insensitive: §1 introduces in
    # lowercase prose, table headers capitalise).
    lowered = normalised.lower()
    for needle in (
        "failure-mode",
        "likelihood",
        "impact",
        "mitigation",
        "detection",
    ):
        assert needle in lowered, (
            f"§1 scope missing classifier '{needle}'"
        )


def test_t06_per_item_sections_carry_tag_and_table_columns():
    text = _load_doc()
    sections = _split_top_sections(text)
    for marker, tag in REQUIRED_RES_D_FOR_SECTION.items():
        section_body = sections[marker]
        assert tag in section_body, (
            f"§{marker} must reference its RES-D tag '{tag}'"
        )
        for header in REQUIRED_TABLE_HEADERS:
            assert header in section_body, (
                f"§{marker} ({tag}) missing table header column "
                f"'{header}'"
            )


def test_t07_per_item_sections_enumerate_ten_failure_codes():
    text = _load_doc()
    sections = _split_top_sections(text)
    for marker, tag in REQUIRED_RES_D_FOR_SECTION.items():
        section_body = sections[marker]
        for code in REQUIRED_FAILURE_CODES:
            assert f"| {code} |" in section_body, (
                f"§{marker} ({tag}) missing failure-mode row "
                f"marker '| {code} |'"
            )


def test_t08_per_item_sections_carry_residual_risk_subsection():
    text = _load_doc()
    sections = _split_top_sections(text)
    for marker, tag in REQUIRED_RES_D_FOR_SECTION.items():
        section_body = sections[marker]
        assert "residual risk" in section_body.lower(), (
            f"§{marker} ({tag}) missing residual-risk sub-section"
        )


def test_t09_aggregate_risk_map_blocks_present():
    text = _load_doc()
    sections = _split_top_sections(text)
    s7 = sections["## 7."]
    assert "Aggregate-Risk-Map" in s7, (
        "§7 must carry the heading 'Aggregate-Risk-Map'"
    )
    for block in REQUIRED_S7_BLOCKS:
        assert block in s7, (
            f"§7 must declare '{block}' explicitly"
        )


def test_t10_cross_anchor_cites_required_adrs_and_tags():
    text = _load_doc()
    sections = _split_top_sections(text)
    s7 = sections["## 7."]
    for adr in REQUIRED_ADR_ANCHORS:
        assert adr in s7, f"§7 cross-anchor missing ADR '{adr}'"
    for tag in REQUIRED_TAG_PR_ANCHORS:
        assert tag in s7, f"§7 cross-anchor missing Tag-N '{tag}'"
    assert "GOVERNANCE" in s7, (
        "§7 cross-anchor must reference GOVERNANCE.md §10"
    )


def test_t11_doc_signed_by_reza():
    text = _load_doc()
    assert re.search(r"^-- Reza\s*$", text, re.MULTILINE), (
        "doc must end with '-- Reza' signature line"
    )


# --------------------------------------------------------------- #
# Axis B -- helper subprocess green/red                           #
# --------------------------------------------------------------- #


def test_t12_helper_subprocess_green_on_live_doc():
    if not HELPER_PATH.exists():
        pytest.skip(f"helper missing at {HELPER_REL}")
    if not DOC_PATH.exists():
        pytest.skip(f"doc missing at {DOC_REL}")
    result = subprocess.run(
        [sys.executable, str(HELPER_PATH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"helper failed on live doc: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    assert "verify_activation_pre_mortem_doc: OK" in result.stdout


def test_t13_helper_subprocess_red_on_mutilated_fixture(tmp_path: Path):
    """Run the helper against a worktree-shaped clone where the doc
    is mutilated (§4 RES-D3 section removed)."""
    if not HELPER_PATH.exists():
        pytest.skip(f"helper missing at {HELPER_REL}")
    if not DOC_PATH.exists():
        pytest.skip(f"doc missing at {DOC_REL}")
    tmp_root = tmp_path / "wakir-runtime-mirror"
    (tmp_root / "tooling" / "audit").mkdir(parents=True)
    (tmp_root / "docs" / "operations").mkdir(parents=True)
    shutil.copy2(HELPER_PATH, tmp_root / HELPER_REL)
    full_text = DOC_PATH.read_text(encoding="utf-8")
    # Mutilate: drop the §4 RES-D3 top-level header AND its sub-section
    # anchors (the helper's substring-find on '## 4.' would otherwise
    # match the '### 4.x' sub-section headings; we strip both).
    mutilated = (
        full_text
        .replace("## 4. RES-D3", "## (mutilated) Section Removed RES-D3")
        .replace("### 4.1", "### (mut)")
        .replace("### 4.2", "### (mut)")
    )
    (tmp_root / DOC_REL).write_text(mutilated, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(tmp_root / HELPER_REL)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        "helper must exit non-zero when §4 is removed; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "FAIL" in result.stderr, (
        f"helper must emit FAIL diagnostic; stderr={result.stderr!r}"
    )


# --------------------------------------------------------------- #
# Bonus invariants                                                #
# --------------------------------------------------------------- #


def test_t14_res_d4_residual_rating_explicitly_high():
    """RES-D4 is the only item rated 'high' residual risk; the doc
    must say so explicitly and cite live-OTS-anchor activation as
    the dominant driver. This is the load-bearing risk-map fact."""
    text = _load_doc()
    sections = _split_top_sections(text)
    # RES-D4 lives under §5; the residual-risk sub-section is §5.2.
    s5 = sections["## 5."]
    assert "RES-D4" in s5
    # The word 'high' must appear in the RES-D4 residual-risk text.
    s5_lower = s5.lower()
    residual_idx = s5_lower.find("residual risk")
    assert residual_idx >= 0, "§5 must carry a residual-risk sub-section"
    residual_block = s5_lower[residual_idx:]
    assert "high" in residual_block, (
        "§5.2 must call RES-D4's residual rating 'high'"
    )
    assert "ots" in residual_block, (
        "§5.2 must reference live OTS-anchor activation as the "
        "dominant residual driver"
    )
    # The aggregate-map (§7) must also reflect 'high' for RES-D4.
    s7 = sections["## 7."]
    # Find the residual-risk-distribution table block.
    distribution_idx = s7.find("Residual-risk distribution")
    assert distribution_idx >= 0, (
        "§7 must carry 'Residual-risk distribution' heading"
    )
    distribution_block = s7[distribution_idx:]
    # The RES-D4 row must mark 'high'.
    res_d4_row_idx = distribution_block.find("RES-D4")
    assert res_d4_row_idx >= 0, (
        "§7 distribution block must list RES-D4"
    )
    # Slice a reasonable window after the RES-D4 mention to read
    # the rating cell.
    window = distribution_block[res_d4_row_idx:res_d4_row_idx + 200]
    assert "high" in window.lower(), (
        "§7 distribution row for RES-D4 must mark 'high' residual "
        "rating"
    )


def test_t15_doc_cites_tag65_and_tag66_upstream_authorities():
    text = _load_doc()
    # Tag-65 is the upstream sequencing-authority; Tag-66 PR #421 is
    # the upstream OTS-probe-coverage authority. Both must be cited.
    assert "Tag-65" in text, (
        "doc must cite Tag-65 as upstream sequencing-authority"
    )
    assert "Tag-66" in text, (
        "doc must cite Tag-66 as upstream OTS-probe-coverage authority"
    )
    assert "#421" in text, (
        "doc must cite Tag-66 PR #421 explicitly (audit-trail)"
    )


def test_t16_doc_form_only_posture_not_audit_verdict():
    """Pre-mortem is informative skizze per GOVERNANCE.md §10, NOT
    an audit-verdict. The doc must explicitly disclaim that
    classification."""
    text = _load_doc()
    lowered = text.lower()
    assert "informative skizze" in lowered, (
        "doc must declare 'informative skizze' posture"
    )
    # The doc should not classify itself as an 'audit verdict' or
    # 'finding'. We check that the explicit out-of-scope text exists.
    assert "audit-verdict" in lowered or "audit verdict" in lowered, (
        "doc must mention 'audit-verdict' in its scope/out-of-scope "
        "framing (to disclaim it)"
    )


def test_t17_aggregate_hot_spots_call_rollback_atomicity():
    """The aggregate-risk-map §7.2 must call out the rollback-
    atomicity hot spot — four of five items share a B4 mode that
    rolls back non-atomically."""
    text = _load_doc()
    sections = _split_top_sections(text)
    s7 = sections["## 7."]
    hot_idx = s7.find("Cross-item hot spots")
    assert hot_idx >= 0
    hot_block = s7[hot_idx:]
    assert "Rollback-atomicity" in hot_block or "rollback-atomicity" in hot_block.lower(), (
        "§7.2 must call out the rollback-atomicity hot spot"
    )
