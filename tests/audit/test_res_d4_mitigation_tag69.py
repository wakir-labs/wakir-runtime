# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-69 tests for the RES-D4 High-Residual Mitigation
Deep-Dive doc.
=========================================================================

Two-axis coverage:

  Axis A -- Doc-shape invariants over the live Tag-69 doc
            ``docs/operations/res-d4-high-residual-mitigation-deep-dive.md``
            (skip-if-absent for portability).
  Axis B -- Helper smoke-tests via subprocess against
            ``tooling/audit/verify_res_d4_mitigation_doc.py``,
            optionally driven through hermetic fixture variants
            in ``tmp_path`` for malformed-doc detection.

Test inventory (>=12 hermetic, all stdlib + pytest):

  T01  Doc file exists at the expected path.
  T02  Doc carries the doc-license SPDX header (CC-BY-4.0 posture).
  T03  Doc declares the Tag-69 title with the ``RES-D4`` marker
       and the ``Mitigation Deep-Dive`` framing in the top-level
       ``#`` heading.
  T04  Doc carries eight in-scope sections (§1..§8) in order, plus
       a §9 cross-anchor citations section.
  T05  §1 scope declares the doc-form-only posture, the
       informative-skizze posture (GOVERNANCE.md §10), the
       RES-D4-single-item focus, the joint-necessity framing, and
       the deep-dive-specific phrases (hard dep, mitigation
       strategy, re-evaluation trigger, sandbox-boundary).
  T06  §2 hard-dep inventory enumerates HD-1, HD-2, HD-3 with the
       three dep names (Live OTS-Calendar / Peer-Roster /
       Audit-Coverage) and cross-anchors all ten Tag-67 §5
       failure-mode codes (A1..A5, B1..B5).
  T07  §3 mitigation strategies carry sub-sections §3.1, §3.2,
       §3.3, §3.4, and each of §3.1..§3.3 carries the five-axis
       classifier labels (Hard-dep code, Cross-anchored failure
       modes, Mitigation strategy, Pre-conditions, Post-mitigation
       residual).
  T08  §4 indefinite-deferral justification enumerates seven
       re-evaluation triggers T1..T7 as table-row entries.
  T09  §5 cross-anchor cites both Tag-67 and Tag-65 as upstream
       artifacts, and restates the Tag-65 §3 HARD-edge framing
       with the three hard-deps.
  T10  §6 (OTS-substrate-prep) AND §7 (peer-roster-prep) are
       explicitly marked ``audit-only``.
  T11  §8 sandbox-boundary recital carries the three sub-sections
       §8.1 (no live-OTS), §8.2 (no AR-authorisation), §8.3 (no
       promotion-PR opening).
  T12  Doc ends with a ``-- Reza`` signature line.
  T13  Helper subprocess: verify_res_d4_mitigation_doc.py exits 0
       on the live Tag-69 doc.
  T14  Helper subprocess: when the doc is mutilated (§4 removed),
       the helper exits non-zero with a diagnostic naming the
       missing section.
  T15  RES-D4 high-residual cross-anchor invariant: the deep-dive
       must reference the Tag-67 §5.2 ``high``-residual rating and
       the A1 + B2 + B5 conjunction as the dominant residual
       driver origin.
  T16  Upstream-authority audit-trail invariant: the doc must cite
       Tag-67 (pre-mortem), Tag-65 (promotion-sequencing), and the
       Tag-68 #432 PR (pre-mortem coverage extension) as upstream
       authorities in §9 cross-anchor.
  T17  Indefinite-deferral discipline: the doc must declare
       ``indefinite-deferral`` as the default AND must NOT
       recommend that the deferral be lifted (sandbox-discipline:
       the deep-dive is a planning artifact, not an advocacy
       artifact).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_REL = "docs/operations/res-d4-high-residual-mitigation-deep-dive.md"
DOC_PATH = REPO_ROOT / DOC_REL
HELPER_REL = "tooling/audit/verify_res_d4_mitigation_doc.py"
HELPER_PATH = REPO_ROOT / HELPER_REL


REQUIRED_TOP_SECTIONS = (
    "## 1.", "## 2.", "## 3.", "## 4.",
    "## 5.", "## 6.", "## 7.", "## 8.",
)
REQUIRED_HARD_DEPS = ("HD-1", "HD-2", "HD-3")
REQUIRED_TRIGGERS = ("T1", "T2", "T3", "T4", "T5", "T6", "T7")
REQUIRED_RES_D4_FAILURE_CODES = (
    "A1", "A2", "A3", "A4", "A5",
    "B1", "B2", "B3", "B4", "B5",
)
REQUIRED_ADR_ANCHORS = (
    "ADR-0007", "ADR-0014", "ADR-0023a", "ADR-0023b", "ADR-0025",
)
REQUIRED_TAG_PR_ANCHORS = (
    "Tag-44", "Tag-58", "Tag-60",
    "Tag-63", "Tag-64", "Tag-65", "Tag-66", "Tag-67", "Tag-68",
)
REQUIRED_DEP_NAMES = (
    "Live OTS-Calendar",
    "Peer-Roster",
    "Audit-Coverage",
)
REQUIRED_S3_LABELS = (
    "Hard-dep code",
    "Cross-anchored failure modes",
    "Mitigation strategy",
    "Pre-conditions",
    "Post-mitigation residual",
)
REQUIRED_S8_SUBS = ("### 8.1", "### 8.2", "### 8.3")
REQUIRED_S3_SUBS = ("### 3.1", "### 3.2", "### 3.3", "### 3.4")


# --------------------------------------------------------------- #
# Live-doc fixtures                                                #
# --------------------------------------------------------------- #


def _load_doc() -> str:
    if not DOC_PATH.exists():
        pytest.skip(f"Tag-69 doc not present at {DOC_REL}")
    return DOC_PATH.read_text(encoding="utf-8")


def _split_top_sections(text: str) -> dict:
    """Return {marker: body} for §1..§8 top-level headers."""
    out: dict = {}
    positions = []
    for marker in REQUIRED_TOP_SECTIONS:
        idx = text.find(marker)
        positions.append((marker, idx))
    # End-bound the last section at the §9 cross-anchor header.
    s9_idx = text.find("## 9.")
    end_idx = s9_idx if s9_idx >= 0 else len(text)
    positions.append(("__end__", end_idx))
    for i in range(len(REQUIRED_TOP_SECTIONS)):
        marker, start = positions[i]
        _, end = positions[i + 1]
        out[marker] = text[start:end] if start >= 0 else ""
    return out


# --------------------------------------------------------------- #
# Axis A -- doc-shape invariants                                  #
# --------------------------------------------------------------- #


def test_t01_doc_file_exists():
    assert DOC_PATH.exists(), f"Tag-69 doc missing at {DOC_REL}"


# REUSE-IgnoreStart
def test_t02_doc_carries_cc_by_4_0_spdx_header():
    text = _load_doc()
    assert "SPDX-License-Identifier: CC-BY-4.0" in text, (
        "Tag-69 doc must carry CC-BY-4.0 SPDX header"
    )
# REUSE-IgnoreEnd


def test_t03_doc_title_carries_tag69_and_res_d4_mitigation():
    text = _load_doc()
    first_h1 = None
    for line in text.splitlines():
        if line.startswith("# "):
            first_h1 = line
            break
    assert first_h1 is not None, "doc must contain a top-level '# ' title"
    assert "Tag-69" in first_h1, f"title missing 'Tag-69': {first_h1!r}"
    assert "RES-D4" in first_h1, f"title missing 'RES-D4': {first_h1!r}"
    assert (
        "Mitigation" in first_h1 or "mitigation" in first_h1
    ), f"title missing 'Mitigation': {first_h1!r}"
    assert (
        "Deep-Dive" in first_h1
        or "Deep Dive" in first_h1
        or "deep-dive" in first_h1
    ), f"title missing 'Deep-Dive' marker: {first_h1!r}"


def test_t04_eight_top_sections_plus_cross_anchor():
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
    # §9 cross-anchor must follow §8.
    s9_idx = text.find("## 9.")
    assert s9_idx > last, (
        "§9 cross-anchor citation section must follow §8"
    )


def test_t05_scope_declares_doc_form_only_and_joint_necessity():
    text = _load_doc()
    sections = _split_top_sections(text)
    s1 = sections["## 1."]
    normalised = re.sub(r"\s+", " ", s1)
    for needle in (
        "doc-form only",
        "informative skizze",
        "RES-D4",
        "Out of scope",
        "joint-necessity",
    ):
        assert needle in normalised, (
            f"§1 scope missing posture phrase '{needle}'"
        )
    lowered = normalised.lower()
    for needle in (
        "hard dep",
        "mitigation strategy",
        "re-evaluation trigger",
        "sandbox-boundary",
    ):
        assert needle in lowered, (
            f"§1 scope missing deep-dive phrase '{needle}'"
        )


def test_t06_hard_dep_inventory_and_failure_code_cross_anchor():
    text = _load_doc()
    sections = _split_top_sections(text)
    s2 = sections["## 2."]
    for hd in REQUIRED_HARD_DEPS:
        assert hd in s2, f"§2 hard-dep inventory missing '{hd}'"
    for name in REQUIRED_DEP_NAMES:
        assert name in s2, f"§2 hard-dep inventory missing dep name '{name}'"
    # All ten Tag-67 §5 failure-mode codes must be cross-anchored
    # collectively in the §2 inventory.
    for code in REQUIRED_RES_D4_FAILURE_CODES:
        assert code in s2, (
            f"§2 hard-dep inventory must cross-anchor failure-mode "
            f"code '{code}' from Tag-67 §5"
        )


def test_t07_mitigation_strategies_carry_five_axis_classifier():
    text = _load_doc()
    sections = _split_top_sections(text)
    s3 = sections["## 3."]
    for sub in REQUIRED_S3_SUBS:
        assert sub in s3, f"§3 missing sub-section '{sub}'"
    for label in REQUIRED_S3_LABELS:
        count = s3.count(label)
        assert count >= 3, (
            f"§3 five-axis classifier label '{label}' must appear in "
            f"each of §3.1..§3.3 (found {count}, expected >=3)"
        )
    # §3.4 aggregate must reference 'high' -> 'medium' transition.
    assert "high" in s3 and "medium" in s3, (
        "§3.4 must state the joint-clearance 'high' -> 'medium' "
        "residual transition"
    )


def test_t08_re_evaluation_triggers_t1_through_t7():
    text = _load_doc()
    sections = _split_top_sections(text)
    s4 = sections["## 4."]
    assert "indefinite-deferral" in s4.lower(), (
        "§4 must declare 'indefinite-deferral' as the default"
    )
    for trigger in REQUIRED_TRIGGERS:
        assert f"| {trigger} |" in s4, (
            f"§4 must enumerate re-evaluation trigger '{trigger}' "
            f"as a table-row entry"
        )


def test_t09_cross_anchor_and_hard_edge_restatement():
    text = _load_doc()
    sections = _split_top_sections(text)
    s5 = sections["## 5."]
    for upstream in ("Tag-67", "Tag-65"):
        assert upstream in s5, (
            f"§5 must cite upstream '{upstream}' artifact"
        )
    assert (
        "HARD edge" in s5 or "HARD-edge" in s5
    ), "§5 must restate the Tag-65 §3 HARD-edge framing"
    for hd in REQUIRED_HARD_DEPS:
        assert hd in s5, (
            f"§5 HARD-edge restatement must name hard-dep '{hd}'"
        )


def test_t10_substrate_prep_marked_audit_only():
    text = _load_doc()
    sections = _split_top_sections(text)
    for marker in ("## 6.", "## 7."):
        body = sections[marker].lower()
        assert (
            "audit-only" in body or "audit only" in body
        ), f"{marker} substrate-prep must be marked 'audit-only' explicitly"


def test_t11_sandbox_boundary_three_sub_sections():
    text = _load_doc()
    sections = _split_top_sections(text)
    s8 = sections["## 8."]
    for sub in REQUIRED_S8_SUBS:
        assert sub in s8, f"§8 missing sandbox-boundary sub-section '{sub}'"
    lowered = s8.lower()
    for needle in (
        "no live-ots",
        "no ar-authorisation",
        "no promotion-pr",
    ):
        assert needle in lowered, (
            f"§8 sandbox-boundary recital missing phrase: '{needle}'"
        )


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
    assert "verify_res_d4_mitigation_doc: OK" in result.stdout


def test_t14_helper_subprocess_red_on_mutilated_fixture(tmp_path: Path):
    """Run the helper against a worktree-shaped clone where §4 is
    mutilated (top-level header rewritten)."""
    if not HELPER_PATH.exists():
        pytest.skip(f"helper missing at {HELPER_REL}")
    if not DOC_PATH.exists():
        pytest.skip(f"doc missing at {DOC_REL}")
    tmp_root = tmp_path / "wakir-runtime-mirror"
    (tmp_root / "tooling" / "audit").mkdir(parents=True)
    (tmp_root / "docs" / "operations").mkdir(parents=True)
    shutil.copy2(HELPER_PATH, tmp_root / HELPER_REL)
    full_text = DOC_PATH.read_text(encoding="utf-8")
    # Mutilate: drop the §4 indefinite-deferral header AND its sub-section
    # anchors (the helper's substring-find on '## 4.' would otherwise
    # match '### 4.x' sub-section headings; we strip both).
    mutilated = (
        full_text
        .replace(
            "## 4. Indefinite-Deferral",
            "## (mutilated) Section Removed Indefinite-Deferral",
        )
        .replace("### 4.1", "### (mut)")
        .replace("### 4.2", "### (mut)")
        .replace("### 4.3", "### (mut)")
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


def test_t15_high_residual_cross_anchor_to_tag67():
    """The deep-dive must reference Tag-67 §5.2 'high' residual rating
    and the A1 + B2 + B5 conjunction as the dominant driver."""
    text = _load_doc()
    lowered = text.lower()
    assert "high" in lowered, "doc must reference 'high' residual rating"
    # The conjunction A1 + B2 + B5 (Tag-67 §5.2) must be cited.
    # The deep-dive cites the conjunction in §1 (introduction) and §2 inventory.
    assert "A1" in text and "B2" in text and "B5" in text, (
        "doc must cite the Tag-67 §5.2 A1 + B2 + B5 conjunction"
    )


def test_t16_upstream_authority_audit_trail():
    """The doc must cite Tag-67 (pre-mortem), Tag-65 (promotion-
    sequencing), and Tag-68 PR #432 (pre-mortem coverage) as
    upstream authorities."""
    text = _load_doc()
    assert "Tag-67" in text, (
        "doc must cite Tag-67 as upstream pre-mortem authority"
    )
    assert "Tag-65" in text, (
        "doc must cite Tag-65 as upstream sequencing-authority"
    )
    assert "Tag-68" in text, (
        "doc must cite Tag-68 as upstream coverage-extension authority"
    )
    assert "#432" in text, (
        "doc must cite Tag-68 PR #432 explicitly (audit-trail)"
    )


def test_t17_indefinite_deferral_discipline():
    """The doc must declare 'indefinite-deferral' as the default AND
    must NOT recommend lifting the deferral (advocacy discipline)."""
    text = _load_doc()
    lowered = text.lower()
    assert "indefinite-deferral" in lowered, (
        "doc must declare 'indefinite-deferral' as the default"
    )
    # The doc must NOT advocate to lift the deferral. We check that
    # the explicit "what this section does NOT do" disclaimer is
    # present in §4.3 and that no phrase like "recommend lifting"
    # or "recommend promotion" appears.
    forbidden_phrases = (
        "recommend lifting",
        "recommend promotion",
        "lift the deferral",
        "accelerate promotion",
    )
    for phrase in forbidden_phrases:
        assert phrase not in lowered, (
            f"doc must not advocate '{phrase}' "
            f"(deep-dive is planning, not advocacy)"
        )


def test_t18_doc_form_only_posture_disclaim_audit_verdict():
    """Deep-dive is informative skizze per GOVERNANCE.md §10, NOT
    an audit-verdict. The doc must disclaim that classification."""
    text = _load_doc()
    lowered = text.lower()
    assert "informative skizze" in lowered, (
        "doc must declare 'informative skizze' posture"
    )
    assert "audit-verdict" in lowered or "audit verdict" in lowered, (
        "doc must mention 'audit-verdict' in its scope/out-of-scope "
        "framing (to disclaim it)"
    )


def test_t19_governance_md_section_10_referenced():
    """The informative-skizze posture cites GOVERNANCE.md §10 as the
    governance-anchor."""
    text = _load_doc()
    assert "GOVERNANCE.md" in text or "GOVERNANCE" in text, (
        "doc must reference GOVERNANCE.md (informative-skizze posture)"
    )
    assert "§10" in text or "section 10" in text.lower(), (
        "doc must reference GOVERNANCE.md §10 specifically"
    )


def test_t20_helper_path_constant_resolves():
    """Sanity: HELPER_REL constant resolves to the file actually
    shipped in this PR."""
    assert HELPER_PATH.exists(), (
        f"Tag-69 helper expected at {HELPER_REL}"
    )
    helper_text = HELPER_PATH.read_text(encoding="utf-8")
    assert "verify_res_d4_mitigation_doc" in helper_text
    # Helper must be stdlib-only (no third-party imports).
    forbidden_imports = ("import yaml", "import requests", "import pytest")
    for f in forbidden_imports:
        assert f not in helper_text, (
            f"helper must be stdlib-only; found '{f}'"
        )
