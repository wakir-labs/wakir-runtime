# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-65 tests for the Wirelang-Spec v0.4.4 Reserve-Item
Promotion-Sequencing doc.
=========================================================================

Two-axis coverage:

  Axis A -- Doc-shape invariants over the live Tag-65 doc
            ``docs/operations/wirelang-spec-v0-4-4-promotion-sequencing.md``
            (skip-if-absent for portability).
  Axis B -- Helper smoke-tests via subprocess against
            ``tooling/audit/verify_promotion_sequencing_doc.py``,
            optionally driven through hermetic fixture variants
            in ``tmp_path`` for malformed-doc detection.

Test inventory (>=12 hermetic, all stdlib + pytest):

  T01  Doc file exists at the expected path.
  T02  Doc carries the doc-license SPDX header (CC-BY-4.0 posture).
  T03  Doc declares the Tag-65 title with the
       ``Promotion-Sequencing`` and ``Tag-65`` markers in the
       top-level ``#`` heading.
  T04  Doc carries seven top-level sections (§1..§7) in order.
  T05  §1 scope declares the doc-form-only posture, the
       sequence-promotion-only activation policy, and the KW-24
       cutover-T0 gate.
  T06  §2 has one sub-section per RES-Dn item (§2.1..§2.5) and
       each cites the three sub-fields (substrate-already-pinned,
       activation-trigger conditions, promotion-touch surface).
  T07  §3 dependency-DAG references all five RES-Dn items, marks
       the RES-D4 HARD edge on live OTS-anchor activation, and
       distinguishes soft edges (RES-D1 -> RES-D5).
  T08  §4 promotion-schedule table contains a row per RES-Dn item
       and labels RES-D4 as ``indefinite-deferral`` / equivalent.
  T09  §5 has both §5.1 (common A1..A5) and §5.2 (per-item
       RES-D1..D5) blocks; A1..A5 letters all appear in §5.1.
  T10  §6 has §6.1..§6.4 rollback sub-cases and names both the
       forward-fix and the revert paths.
  T11  §7 declares Sandbox-Scope, Out-of-Sandbox-Scope, the
       Operator-Hand-Sandbox-Gap recap, and cross-anchor pointers
       to ADR-0007, ADR-0023a, ADR-0023b, ADR-0025.
  T12  Doc ends with a ``-- Reza`` signature line.
  T13  Helper subprocess: verify_promotion_sequencing_doc.py exits
       0 on the live Tag-65 doc.
  T14  Helper subprocess: when the doc is replaced by a stripped
       fixture (missing §3), the helper exits non-zero with a
       diagnostic message naming the missing section.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_REL = "docs/operations/wirelang-spec-v0-4-4-promotion-sequencing.md"
DOC_PATH = REPO_ROOT / DOC_REL
HELPER_REL = "tooling/audit/verify_promotion_sequencing_doc.py"
HELPER_PATH = REPO_ROOT / HELPER_REL


REQUIRED_TOP_SECTIONS = ("## 1.", "## 2.", "## 3.", "## 4.",
                         "## 5.", "## 6.", "## 7.")
REQUIRED_RES_D_TAGS = ("RES-D1", "RES-D2", "RES-D3", "RES-D4", "RES-D5")
REQUIRED_RES_D_SUBSECTIONS = ("### 2.1", "### 2.2", "### 2.3",
                               "### 2.4", "### 2.5")
REQUIRED_S6_SUBCASES = ("### 6.1", "### 6.2", "### 6.3", "### 6.4")
REQUIRED_ADR_ANCHORS = ("ADR-0007", "ADR-0023a", "ADR-0023b", "ADR-0025")
REQUIRED_S5_ACCEPTANCE_LETTERS = ("A1:", "A2:", "A3:", "A4:", "A5:")


# --------------------------------------------------------------- #
# Live-doc fixtures                                                #
# --------------------------------------------------------------- #


def _load_doc() -> str:
    if not DOC_PATH.exists():
        pytest.skip(f"Tag-65 doc not present at {DOC_REL}")
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
    assert DOC_PATH.exists(), f"Tag-65 doc missing at {DOC_REL}"


# REUSE-IgnoreStart
def test_t02_doc_carries_cc_by_4_0_spdx_header():
    text = _load_doc()
    assert "SPDX-License-Identifier: CC-BY-4.0" in text, (
        "Tag-65 doc must carry CC-BY-4.0 SPDX header"
    )
# REUSE-IgnoreEnd


def test_t03_doc_title_carries_tag65_and_promotion_sequencing():
    text = _load_doc()
    # The first '#' heading is the title.
    first_h1 = None
    for line in text.splitlines():
        if line.startswith("# "):
            first_h1 = line
            break
    assert first_h1 is not None, "doc must contain a top-level '# ' title"
    assert "Tag-65" in first_h1, f"title missing 'Tag-65': {first_h1!r}"
    assert "Promotion-Sequencing" in first_h1, (
        f"title missing 'Promotion-Sequencing': {first_h1!r}"
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


def test_t05_scope_declares_doc_form_only_and_kw24_gate():
    text = _load_doc()
    sections = _split_top_sections(text)
    s1 = sections["## 1."]
    # Normalise wrap to make fixed-phrase checks resilient.
    normalised = re.sub(r"\s+", " ", s1)
    assert "doc-form only" in normalised
    assert "sequence-promotion-only" in normalised
    assert "KW-24 cutover-T0" in normalised
    assert "RES-D1 .. RES-D5" in normalised
    assert "Out of scope" in normalised


def test_t06_res_d_subsections_present_with_three_subfields():
    text = _load_doc()
    sections = _split_top_sections(text)
    s2 = sections["## 2."]
    for sub in REQUIRED_RES_D_SUBSECTIONS:
        assert sub in s2, f"§2 missing sub-section heading '{sub}'"
    for tag in REQUIRED_RES_D_TAGS:
        assert tag in s2, f"§2 missing reserve item tag '{tag}'"
    # Three sub-field labels must each occur at least 5 times
    # (one per RES-Dn block).
    for label in ("Substrate already pinned",
                  "Activation-trigger conditions",
                  "Promotion-touch surface"):
        count = s2.count(label)
        assert count >= 5, (
            f"§2 sub-field label '{label}' appears {count} times "
            f"(expected >=5, one per RES-Dn block)"
        )


def test_t07_dag_lists_all_items_marks_hard_and_soft_edges():
    text = _load_doc()
    sections = _split_top_sections(text)
    s3 = sections["## 3."]
    assert "Dependency-DAG" in s3, "§3 must carry 'Dependency-DAG'"
    for tag in REQUIRED_RES_D_TAGS:
        assert tag in s3, f"§3 DAG node missing '{tag}'"
    assert "HARD" in s3 and "OTS" in s3, (
        "§3 must declare the RES-D4 HARD edge on live OTS-anchor"
    )
    assert "soft" in s3.lower(), (
        "§3 must distinguish soft edges (RES-D1 -> RES-D5)"
    )
    assert "no cycles" in s3.lower(), "§3 must claim DAG 'no cycles'"


def test_t08_schedule_has_row_per_res_d_and_marks_res_d4_indefinite():
    text = _load_doc()
    sections = _split_top_sections(text)
    s4 = sections["## 4."]
    assert "Recommended Sequence-Order" in s4
    for tag in REQUIRED_RES_D_TAGS:
        assert tag in s4, f"§4 schedule missing row for '{tag}'"
    assert "Rationale" in s4, "§4 schedule must have 'Rationale' column"
    assert "non-binding" in s4, "§4 must mark schedule non-binding"
    assert (
        "indefinite-deferral" in s4
        or "indefinite-defer" in s4
    ), "§4 must mark RES-D4 as 'indefinite-deferral'"


def test_t09_acceptance_has_common_and_per_item_blocks():
    text = _load_doc()
    sections = _split_top_sections(text)
    s5 = sections["## 5."]
    assert "### 5.1" in s5
    assert "### 5.2" in s5
    s51_idx = s5.find("### 5.1")
    s52_idx = s5.find("### 5.2")
    s51 = s5[s51_idx:s52_idx]
    s52 = s5[s52_idx:]
    for letter in REQUIRED_S5_ACCEPTANCE_LETTERS:
        assert letter in s51, f"§5.1 missing letter '{letter}'"
    for tag in REQUIRED_RES_D_TAGS:
        assert f"**{tag}:**" in s52, (
            f"§5.2 missing per-item entry '**{tag}:**'"
        )


def test_t10_rollback_has_four_subcases_and_both_paths():
    text = _load_doc()
    sections = _split_top_sections(text)
    s6 = sections["## 6."]
    for sub in REQUIRED_S6_SUBCASES:
        assert sub in s6, f"§6 missing rollback sub-case '{sub}'"
    assert "forward-fix" in s6.lower(), "§6 must mention 'forward-fix'"
    assert "revert" in s6.lower(), "§6 must mention 'revert'"
    assert "CEO-Triage" in s6, "§6 must reference CEO-Triage as arbiter"


def test_t11_sandbox_boundary_blocks_and_adr_cross_anchors():
    text = _load_doc()
    sections = _split_top_sections(text)
    s7 = sections["## 7."]
    for block in ("Sandbox-Scope",
                  "Out-of-Sandbox-Scope",
                  "Operator-Hand-Sandbox-Gap"):
        assert block in s7, f"§7 must declare '{block}' explicitly"
    for adr in REQUIRED_ADR_ANCHORS:
        assert adr in s7, f"§7 cross-anchor missing '{adr}'"
    # Tag-N PR pointers.
    for tag in ("Tag-58", "Tag-60", "Tag-63", "Tag-64"):
        assert tag in s7, f"§7 cross-anchor missing '{tag}'"


def test_t12_doc_signed_by_reza():
    text = _load_doc()
    assert re.search(r"^-- Reza\s*$", text, re.MULTILINE), (
        "doc must end with '-- Reza' signature line"
    )


# --------------------------------------------------------------- #
# Axis B -- helper subprocess green/red                           #
# --------------------------------------------------------------- #


def test_t13_helper_subprocess_green_on_live_doc():
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
    assert "verify_promotion_sequencing_doc: OK" in result.stdout


def test_t14_helper_subprocess_red_on_mutilated_fixture(tmp_path: Path):
    """Run the helper against a worktree-shaped clone where the doc
    is mutilated (§3 removed). Helper must exit non-zero with a
    clear diagnostic."""
    if not HELPER_PATH.exists():
        pytest.skip(f"helper missing at {HELPER_REL}")
    if not DOC_PATH.exists():
        pytest.skip(f"doc missing at {DOC_REL}")
    # Build a minimal mirror of the repo skeleton in tmp_path so the
    # helper's path-resolution finds a doc to read.
    tmp_root = tmp_path / "wakir-runtime-mirror"
    (tmp_root / "tooling" / "audit").mkdir(parents=True)
    (tmp_root / "docs" / "operations").mkdir(parents=True)
    shutil.copy2(HELPER_PATH, tmp_root / HELPER_REL)
    # Mutilate the doc: drop the §3 section header to trigger
    # section-order failure.
    full_text = DOC_PATH.read_text(encoding="utf-8")
    mutilated = full_text.replace("## 3. Dependency-DAG between Items",
                                  "## (mutilated) Section Removed")
    (tmp_root / DOC_REL).write_text(mutilated, encoding="utf-8")
    # Run the mirrored helper.
    result = subprocess.run(
        [sys.executable, str(tmp_root / HELPER_REL)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, (
        "helper must exit non-zero when §3 is removed; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "FAIL" in result.stderr, (
        f"helper must emit FAIL diagnostic; stderr={result.stderr!r}"
    )


# --------------------------------------------------------------- #
# Bonus -- back-compat smoke: doc does not edit the v0.4.4-draft  #
# --------------------------------------------------------------- #


def test_t15_doc_does_not_edit_v044_draft_frontmatter():
    """The Tag-65 doc must not (a) touch v0.4.4-draft.md frontmatter
    by impersonation, (b) mention `status: pre-cutover-freeze`
    inside its own frontmatter. The latter would confuse the
    Tag-58 freeze-seal probe."""
    text = _load_doc()
    # Locate the in-doc frontmatter (if present); the Tag-65 doc has
    # no machine-readable frontmatter, so this is a content-form
    # invariant: the strings below must not appear before the first
    # '## ' top-level section.
    first_section_idx = text.find("\n## 1.")
    assert first_section_idx > 0, "doc must have a '## 1.' section anchor"
    preamble = text[:first_section_idx]
    assert "status: pre-cutover-freeze" not in preamble, (
        "preamble must not impersonate v0.4.3 freeze-marker frontmatter"
    )
    # The body MAY cite that string as a cross-reference; only the
    # preamble is restricted.


def test_t16_doc_cites_tag63_and_tag64_pr_numbers():
    text = _load_doc()
    # The follow-on lineage is part of the audit-trail.
    assert "#403" in text, "doc must cite Tag-63 PR #403"
    assert "#407" in text, "doc must cite Tag-64 PR #407"
