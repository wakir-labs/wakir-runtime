# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-76 hermetic tests for the Operator-Hand Production-Bringup
Recipe substrate (Day-after-Welle-7-Sign-off companion-doc to the
Tag-66 Eve-Recipe and the Tag-75 Welle-7-Day-Patch).

Layout:
  * Tests A1..A12 exercise the doc itself
    (docs/operations/operator-hand-production-bringup-recipe.md).
  * Tests B1..B18 exercise the verifier
    (tooling/ci/verify_production_bringup_recipe_doc.py) -- including
    happy-path, structural-defect injection, and CLI behaviour.

All tests are hermetic: no network, no subprocess outside the
verifier itself, stdlib + pytest only.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "operator-hand-production-bringup-recipe.md"
)
VERIFIER_PATH = (
    REPO_ROOT
    / "tooling"
    / "ci"
    / "verify_production_bringup_recipe_doc.py"
)


def _load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_production_bringup_recipe_doc", VERIFIER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- A: tests against the actual doc ---------------------------------


def test_a1_doc_exists():
    assert DOC_PATH.is_file(), f"doc missing at {DOC_PATH}"


def test_a2_doc_has_yaml_frontmatter_with_required_keys():
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert txt.startswith("---\n"), "frontmatter delimiter not at top"
    end = txt.find("\n---\n", 4)
    assert end > 0, "frontmatter not closed"
    fm = txt[4:end]
    for key in ("title:", "status:", "owner:", "tag:", "audience:"):
        assert key in fm, f"frontmatter missing key {key}"
    assert 'tag: "tag-76"' in fm, "tag value must be tag-76"
    assert 'owner: "kai"' in fm, "owner must be kai"


def test_a3_doc_references_all_five_b_steps():
    txt = DOC_PATH.read_text(encoding="utf-8")
    for step in ("B1", "B2", "B3", "B4", "B5"):
        assert f"### {step} --" in txt, f"section heading for {step} missing"


def test_a4_doc_lists_four_production_bringup_rollback_paths():
    txt = DOC_PATH.read_text(encoding="utf-8")
    for r in ("R-PB-A", "R-PB-B", "R-PB-C", "R-PB-D"):
        assert f"### {r} --" in txt, f"rollback path {r} missing"


def test_a5_doc_lists_three_ar_hand_touchpoints():
    txt = DOC_PATH.read_text(encoding="utf-8")
    for tp in ("TP-PB-1", "TP-PB-2", "TP-PB-3"):
        assert f"### {tp} --" in txt, f"touchpoint {tp} missing"


def test_a6_doc_documents_all_seven_day_n_date_anchors():
    """Day-1 (2026-07-04 Sa) through Day-7 (2026-07-10 Fr) anchors
    must all be present verbatim."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    for date_str in (
        "2026-07-04",
        "2026-07-05",
        "2026-07-06",
        "2026-07-07",
        "2026-07-08",
        "2026-07-09",
        "2026-07-10",
    ):
        assert date_str in txt, f"Day-N date anchor {date_str} missing"


def test_a7_doc_reproduces_ar_vorzeichen_verbatim():
    """The Tag-65 AR-Vorzeichen 'Halt vor Phase 4' verbatim quote
    MUST be reproduced unchanged in section 9.1. Three distinctive
    substrings must all appear."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    for token in (
        "Phase-3-Marathon ends at Welle-7 cutover",
        "explicit AR-Hand re-arm signal",
        "no Phase-4 substrate enters the planning",
    ):
        assert token in txt, (
            f"AR-Vorzeichen verbatim token '{token}' missing"
        )


def test_a8_doc_documents_phase_3_complete_marker_fire_step():
    """B1 (Day-1) is the Phase-3-COMPLETE-marker-fire-step.
    The fire-state-file path AND the global-verdict-input file
    must be referenced."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "state/phase-3-complete-marker.json" in txt
    assert "state/phase-3-marathon-global-verdict.json" in txt
    assert "FIRE_PHASE_3_COMPLETE_MARKER" in txt
    assert "BLOCK_PHASE_3_COMPLETE_MARKER" in txt


def test_a9_doc_documents_phase_4_hold_pin():
    """PHASE-4-HOLD-VOR-RE-ARM substrate-marker must be referenced
    AND the AR-Re-Arm trigger marker PHASE-4-RE-ARMED must be
    referenced."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "PHASE-4-HOLD-VOR-RE-ARM" in txt
    assert "PHASE-4-RE-ARMED" in txt


def test_a10_doc_documents_phase_3_close_items_permitted_list():
    """Section 9.3 must enumerate the five permitted Phase-3-close
    items per the Tag-66 Eve-Recipe §9.3 + Day-7-extension."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "Phase-3-Close Items Permitted" in txt or (
        "Phase-3-close" in txt and "Permitted" in txt
    )
    # The five items: marker-fire, daily-stability, J3/K3-closure,
    # Marathon-Final-Bilanz, Post-Mortem-Anstoss.
    assert "Marker-Fire" in txt
    assert "Stability-Probe" in txt
    assert "OPEN-J3" in txt and "OPEN-K3" in txt
    assert "Marathon-Final-Bilanz" in txt
    assert "Post-Mortem" in txt


def test_a11_doc_cross_links_tag66_and_tag75_predecessors():
    """Tag-66 Eve-Recipe AND Tag-75 Welle-7-Day Patch must both be
    referenced as predecessors (governance-pin source AND P5-input
    source respectively)."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "operator-hand-cutover-eve-final-recipe.md" in txt
    assert "operator-hand-welle-7-eve-recipe-patch.md" in txt
    # P5 step must be named (the Tag-75 hand-off interface).
    assert "P5" in txt


def test_a12_doc_documents_aggregate_verdict_roll_up():
    """Section 7 must list the canonical PB-VERDICT markers and
    must include both happy-path and red-path verdicts."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "PB-VERDICT-PHASE-3-CLOSED-CLEAN" in txt
    assert "PB-VERDICT-PHASE-3-NO-FIRE" in txt
    assert "PB-VERDICT-PHASE-3-DEFERRED" in txt
    assert "PB-VERDICT-PHASE-3-DEFECT-WINDOW" in txt


# ---- B: tests against the verifier -----------------------------------


def test_b1_verifier_module_importable():
    mod = _load_verifier()
    assert hasattr(mod, "verify"), "verify() callable missing"
    assert hasattr(mod, "VerifyResult"), "VerifyResult class missing"


def test_b2_verifier_clean_on_real_doc():
    mod = _load_verifier()
    result = mod.verify(DOC_PATH)
    assert result.ok, (
        f"verifier reports hard failures on real doc: {result.hard_failures}"
    )
    assert result.hard_failures == []
    assert isinstance(result.soft_warnings, list)


def test_b3_verifier_reports_doc_not_found(tmp_path):
    mod = _load_verifier()
    missing = tmp_path / "nope.md"
    result = mod.verify(missing)
    assert not result.ok
    assert any("doc not found" in f for f in result.hard_failures)


def test_b4_verifier_detects_missing_b_step(tmp_path):
    """Strip B3 section and verify H1 fires."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    import re

    mutated = re.sub(
        r"###\s+B3\s+--[^\n]*\n(.*?)(?=\n###\s|\n##\s)",
        "",
        txt,
        count=1,
        flags=re.DOTALL,
    )
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("B3" in f and "H1" in f for f in result.hard_failures)


def test_b5_verifier_detects_missing_subfield(tmp_path):
    """Remove Owner subfield from B1, verify H2 fires for B1."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace(
        "**Owner**: Operator-Hand (Mira), AR-pair-mode standby.",
        "",
        1,
    )
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("B1" in f and "Owner" in f for f in result.hard_failures)


def test_b6_verifier_detects_missing_rollback_path(tmp_path):
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace("### R-PB-D --", "### R-DELETED --", 1)
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("R-PB-D" in f and "H5" in f for f in result.hard_failures)


def test_b7_verifier_detects_missing_touchpoint(tmp_path):
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace("### TP-PB-2 --", "### TP-DELETED --", 1)
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("TP-PB-2" in f and "H6" in f for f in result.hard_failures)


def test_b8_verifier_detects_missing_day_n_anchor(tmp_path):
    """Strip Day-4 date anchor 2026-07-07, verify H8 fires."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace("2026-07-07", "0000-00-00")
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any(
        "H8" in f and "2026-07-07" in f for f in result.hard_failures
    )


def test_b9_verifier_detects_tampered_ar_vorzeichen(tmp_path):
    """Replace one of the verbatim AR-Vorzeichen tokens, verify H9
    fires. This is the governance-critical hard-check: the verbatim
    quote may not be paraphrased."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace(
        "explicit AR-Hand re-arm signal",
        "implicit AR-Hand re-arm signal",
    )
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any(
        "H9" in f and "explicit AR-Hand re-arm signal" in f
        for f in result.hard_failures
    )


def test_b10_verifier_detects_missing_marker_state_file(tmp_path):
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace(
        "state/phase-3-complete-marker.json",
        "state/some-other-file.json",
    )
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("H10" in f for f in result.hard_failures)


def test_b11_verifier_detects_missing_phase_4_hold_marker(tmp_path):
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace(
        "PHASE-4-HOLD-VOR-RE-ARM", "PHASE-4-RELEASED-EARLY"
    )
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any(
        "H13" in f and "PHASE-4-HOLD-VOR-RE-ARM" in f
        for f in result.hard_failures
    )


def test_b12_verifier_detects_short_verdict_table(tmp_path):
    """Remove enough verdict rows so H7 row-count fails."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")

    lines = txt.splitlines()
    seen = 0
    out = []
    for line in lines:
        if "PB-VERDICT-" in line and "->" in line:
            seen += 1
            if seen > 3:
                continue
        out.append(line)
    mutated = "\n".join(out)
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("H7" in f for f in result.hard_failures)


def test_b13_verifier_cli_exit_zero_on_real_doc():
    """CLI smoke -- exit-0 with real doc via --doc flag."""
    proc = subprocess.run(
        [
            sys.executable,
            str(VERIFIER_PATH),
            "--doc",
            str(DOC_PATH),
            "--repo-root",
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"CLI exit non-zero on real doc: rc={proc.returncode}, "
        f"stdout={proc.stdout!r}, stderr={proc.stderr!r}"
    )
    assert "PRODUCTION-BRINGUP-RECIPE-DOC-CLEAN" in proc.stdout


def test_b14_verifier_cli_exit_two_on_missing_doc(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(VERIFIER_PATH),
            "--doc",
            str(tmp_path / "nope.md"),
            "--repo-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2, (
        f"CLI did not return 2 on missing doc: rc={proc.returncode}, "
        f"stderr={proc.stderr!r}"
    )
    assert "DOC-NOT-FOUND" in proc.stderr


def test_b15_verifier_constants_match_doc_substrate():
    """If the spec changes, this test should break deliberately."""
    mod = _load_verifier()
    assert mod.REQUIRED_B_STEPS == ["B1", "B2", "B3", "B4", "B5"]
    assert "Time-Window" in mod.REQUIRED_B_SUBFIELDS
    assert "Owner" in mod.REQUIRED_B_SUBFIELDS
    assert "Verdict-Marker" in mod.REQUIRED_B_SUBFIELDS
    assert mod.PHASE_3_COMPLETE_MARKER_FILE == "state/phase-3-complete-marker.json"
    assert mod.GLOBAL_VERDICT_STATE_FILE == "state/phase-3-marathon-global-verdict.json"
    assert mod.PHASE_4_HOLD_MARKER == "PHASE-4-HOLD-VOR-RE-ARM"
    assert mod.REQUIRED_R_PATHS == [
        "R-PB-A",
        "R-PB-B",
        "R-PB-C",
        "R-PB-D",
    ]
    assert mod.REQUIRED_TP == ["TP-PB-1", "TP-PB-2", "TP-PB-3"]
    assert "PB-VERDICT-PHASE-3-NO-FIRE" in mod.REQUIRED_VERDICTS
    assert mod.DAY_N_DATES == [
        "2026-07-04",
        "2026-07-05",
        "2026-07-06",
        "2026-07-07",
        "2026-07-08",
        "2026-07-09",
        "2026-07-10",
    ]


def test_b16_verifier_detects_missing_global_verdict_file(tmp_path):
    """Strip global-verdict-state-file path, verify H11 fires."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace(
        "state/phase-3-marathon-global-verdict.json",
        "state/some-other-global.json",
    )
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("H11" in f for f in result.hard_failures)


def test_b17_verifier_detects_missing_tag66_eve_recipe_crosslink(tmp_path):
    """Strip Tag-66 Eve-Recipe cross-link, verify H14 fires."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace(
        "operator-hand-cutover-eve-final-recipe.md",
        "deleted-doc-path.md",
    )
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("H14" in f for f in result.hard_failures)


def test_b18_verifier_detects_missing_welle7_patch_crosslink(tmp_path):
    """Strip Tag-75 Welle-7-Day Patch cross-link, verify H12 fires."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace(
        "operator-hand-welle-7-eve-recipe-patch.md",
        "deleted-doc-path.md",
    )
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("H12" in f for f in result.hard_failures)
