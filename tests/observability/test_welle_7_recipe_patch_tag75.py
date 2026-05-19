# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-75 hermetic tests for the Welle-7 Day-of-Recipe-Patch
substrate (Operator-Hand companion doc to the Tag-66 Eve-Recipe,
following the Welle-3 Tag-71-Patch, Welle-5 Tag-73-Patch, and
Welle-6 Tag-74-Patch precedents). Welle-7 is the Final-Sealing-
Welle of Phase-3c -- the unique semantics are tested in addition
to the parallel structure with Welle-3/5/6.

Layout:
  * Tests A1..A11 exercise the doc itself
    (docs/operations/operator-hand-welle-7-eve-recipe-patch.md).
  * Tests B1..B19 exercise the verifier
    (tooling/ci/verify_welle_7_recipe_patch_doc.py) -- including
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
    / "operator-hand-welle-7-eve-recipe-patch.md"
)
VERIFIER_PATH = (
    REPO_ROOT / "tooling" / "ci" / "verify_welle_7_recipe_patch_doc.py"
)


def _load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_welle_7_recipe_patch_doc", VERIFIER_PATH
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
    assert 'tag: "tag-75"' in fm, "tag value must be tag-75"
    assert 'owner: "kai"' in fm, "owner must be kai"


def test_a3_doc_references_all_five_p_steps():
    txt = DOC_PATH.read_text(encoding="utf-8")
    for step in ("P1", "P2", "P3", "P4", "P5"):
        assert f"### {step} --" in txt, f"section heading for {step} missing"


def test_a4_doc_lists_iia_1130_and_henrik_t44():
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "IIA-1130" in txt, "IIA-1130 anchor missing"
    assert "Tag-44" in txt and "Pre-Mortem" in txt, (
        "Henrik Tag-44 Pre-Mortem reference missing"
    )


def test_a5_doc_lists_four_welle_7_rollback_paths():
    txt = DOC_PATH.read_text(encoding="utf-8")
    for r in ("R-W7-A", "R-W7-B", "R-W7-C", "R-W7-D"):
        assert f"### {r} --" in txt, f"rollback path {r} missing"


def test_a6_doc_lists_three_ar_hand_touchpoints():
    txt = DOC_PATH.read_text(encoding="utf-8")
    for tp in ("TP-W7-1", "TP-W7-2", "TP-W7-3"):
        assert f"### {tp} --" in txt, f"touchpoint {tp} missing"


def test_a7_doc_explicitly_names_both_hot_spot_axes():
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "recovery-drill-live" in txt, (
        "recovery-drill-live axis name missing"
    )
    assert "iia-1130-pre-auditor" in txt, (
        "iia-1130-pre-auditor axis name missing"
    )


def test_a8_doc_references_kw27_doppel_welle_and_welle_6_partner():
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "KW-27" in txt, "KW-27 anchor missing"
    assert "Doppel-Welle" in txt, "Doppel-Welle wording missing"
    assert "Welle-6" in txt, "Welle-6 partner reference missing"


def test_a9_doc_documents_cross_modul_out_of_band_asymmetry():
    """Welle-7/KW-27 asymmetry vs. Welle-4-5/KW-26: cross-modul
    handled out-of-band (Phase-2-Acceptance-Gate daily rollup), not
    inline."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "out-of-band" in txt.lower() or "out of band" in txt.lower(), (
        "KW-27 out-of-band cross-modul asymmetry must be documented"
    )
    assert "Phase-2-Acceptance-Gate" in txt or "Phase-2 Acceptance Gate" in txt, (
        "Phase-2-Acceptance-Gate rollup substrate must be referenced"
    )


def test_a10_doc_documents_final_sealing_semantics():
    """Welle-7-unique: P5 is the Final-Sealing-step that gates the
    Phase-3-COMPLETE-marker fire. Doc must document this explicitly
    AND reference the Global-Acceptance-Verdict-Aggregator."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "Final-Sealing" in txt, "Final-Sealing concept must be documented"
    assert "Phase-3-COMPLETE" in txt, (
        "Phase-3-COMPLETE-marker gate role of P5 must be documented"
    )
    assert "final_sealing_authority" in txt, (
        "final_sealing_authority schema field must be referenced"
    )
    assert "final_sealing_intent" in txt, (
        "final_sealing_intent schema field (P3 commit) must be referenced"
    )
    assert "final_sealing_decision" in txt, (
        "final_sealing_decision schema field (P5 commit) must be referenced"
    )


def test_a11_doc_documents_terminal_welle_property():
    """Welle-7 is the terminal Welle: no downstream propagation;
    the cascade ends here. Doc must capture this distinguishing
    constraint vs. Welle-3/5/6."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "terminal" in txt.lower(), (
        "Welle-7 terminal-Welle property must be documented"
    )


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


def test_b4_verifier_detects_missing_p_step(tmp_path):
    """Strip P3 section and verify H1 fires."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    import re

    mutated = re.sub(
        r"###\s+P3\s+--[^\n]*\n(.*?)(?=\n###\s|\n##\s)",
        "",
        txt,
        count=1,
        flags=re.DOTALL,
    )
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("P3" in f and "H1" in f for f in result.hard_failures)


def test_b5_verifier_detects_missing_subfield(tmp_path):
    """Remove Owner subfield from P1, verify H2 fires for P1."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace(
        "**Owner**: Operator-Hand (Mira).", "", 1
    )
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("P1" in f and "Owner" in f for f in result.hard_failures)


def test_b6_verifier_detects_missing_rollback_path(tmp_path):
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace("### R-W7-D --", "### R-DELETED --", 1)
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("R-W7-D" in f and "H5" in f for f in result.hard_failures)


def test_b7_verifier_detects_missing_iia_anchor(tmp_path):
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace("IIA-1130", "IIA-XXXX")
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("H9" in f and "IIA-1130" in f for f in result.hard_failures)


def test_b8_verifier_detects_missing_state_file_path(tmp_path):
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace(
        "state/welle-7-pre-auditor-decision.json",
        "state/some-other-file.json",
    )
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("H8" in f for f in result.hard_failures)


def test_b9_verifier_detects_short_verdict_table(tmp_path):
    """Remove enough verdict rows so H7 row-count fails."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")

    lines = txt.splitlines()
    seen = 0
    out = []
    for line in lines:
        if "WELLE-7-VERDICT-" in line and "->" in line:
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


def test_b10_verifier_detects_missing_hot_spot_axis(tmp_path):
    """Strip references to one hot-spot axis, verify H11 fires."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace("recovery-drill-live", "REMOVED-AXIS-A")
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any(
        "H11" in f and "recovery-drill-live" in f for f in result.hard_failures
    )


def test_b11_verifier_detects_missing_axis_state_file(tmp_path):
    """Strip recovery-drill-live state-file ref, verify H12 fires."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace(
        "state/welle-7-recovery-drill-live.json",
        "state/some-irrelevant-file.json",
    )
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("H12" in f for f in result.hard_failures)


def test_b12_verifier_detects_missing_global_verdict_file(tmp_path):
    """Strip Global-Verdict-state-file ref, verify H12 fires."""
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
    assert any("H12" in f for f in result.hard_failures)


def test_b13_verifier_detects_missing_final_sealing_token(tmp_path):
    """Strip Final-Sealing-Authority schema token, verify H13 fires."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace("final_sealing_authority", "removed_token_xxx")
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any(
        "H13" in f and "final_sealing_authority" in f
        for f in result.hard_failures
    )


def test_b14_verifier_detects_missing_global_aggregator_path(tmp_path):
    """Strip Global-Acceptance-Verdict-Aggregator helper-path,
    verify H14 fires."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace(
        "tooling/ci/aggregate_pyramide_run_order_verdict.py",
        "tooling/ci/removed_aggregator.py",
    )
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("H14" in f for f in result.hard_failures)


def test_b15_verifier_cli_exit_zero_on_real_doc():
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
    assert "WELLE-7-RECIPE-PATCH-DOC-CLEAN" in proc.stdout


def test_b16_verifier_cli_exit_two_on_missing_doc(tmp_path):
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


def test_b17_verifier_constants_match_doc_substrate():
    """Wenn der Spec sich aendert, soll dieser Test bewusst brechen."""
    mod = _load_verifier()
    assert mod.REQUIRED_P_STEPS == ["P1", "P2", "P3", "P4", "P5"]
    assert "Time-Window" in mod.REQUIRED_P_SUBFIELDS
    assert "Owner" in mod.REQUIRED_P_SUBFIELDS
    assert "Verdict-Marker" in mod.REQUIRED_P_SUBFIELDS
    assert (
        mod.PRE_AUDITOR_STATE_FILE == "state/welle-7-pre-auditor-decision.json"
    )
    assert (
        mod.RECOVERY_DRILL_LIVE_STATE_FILE
        == "state/welle-7-recovery-drill-live.json"
    )
    assert (
        mod.GLOBAL_VERDICT_STATE_FILE
        == "state/phase-3-marathon-global-verdict.json"
    )
    assert (
        mod.GLOBAL_VERDICT_AGGREGATOR_PATH
        == "tooling/ci/aggregate_pyramide_run_order_verdict.py"
    )
    assert mod.IIA_ANCHOR == "IIA-1130"
    assert mod.HOT_SPOT_AXES == [
        "recovery-drill-live",
        "iia-1130-pre-auditor",
    ]
    assert mod.REQUIRED_R_PATHS == [
        "R-W7-A",
        "R-W7-B",
        "R-W7-C",
        "R-W7-D",
    ]
    assert mod.REQUIRED_TP == ["TP-W7-1", "TP-W7-2", "TP-W7-3"]
    assert "WELLE-7-VERDICT-FINAL-SEALING-BLOCK" in mod.REQUIRED_VERDICTS


def test_b18_doc_documents_convergent_date_anchor():
    """The Welle-7-Day date is convergent post-ADR-0066 + Tag-57
    (KW-27-Mi 2026-07-01). Doc must reference this anchor."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "2026-07-01" in txt, (
        "Welle-7-Day convergent anchor (2026-07-01 per Tag-57 "
        "pre-cutover-acceptance-run-order) must be referenced"
    )
    assert "KW-27" in txt


def test_b19_doc_lists_helper_substrate_paths():
    """§7 Helper-Substrat must reference the Tag-75 verifier path,
    the Tag-75 test path, AND the Global-Acceptance-Verdict-
    Aggregator helper path -- doc-to-substrate closure."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "tooling/ci/verify_welle_7_recipe_patch_doc.py" in txt
    assert "tests/observability/test_welle_7_recipe_patch_tag75.py" in txt
    assert "tooling/ci/welle_7_hot_spot_aggregator.py" in txt
    assert "tooling/ci/aggregate_pyramide_run_order_verdict.py" in txt


def test_b20_doc_references_welle_3_5_6_patches_as_precedents():
    """Welle-7-Patch must reference Welle-3-Patch (Tag-71),
    Welle-5-Patch (Tag-73), AND Welle-6-Patch (Tag-74) as template
    precedents -- this is a hard requirement of the Tag-75 brief
    (sequential cascade across all four IIA-1130 Wellen)."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "Tag-71" in txt, "Welle-3-Patch (Tag-71) precedent must be referenced"
    assert "Tag-73" in txt, "Welle-5-Patch (Tag-73) precedent must be referenced"
    assert "Tag-74" in txt, "Welle-6-Patch (Tag-74) precedent must be referenced"
    assert "operator-hand-welle-3-eve-recipe-patch.md" in txt.lower(), (
        "Welle-3-Patch doc-path must be referenced"
    )
    assert "operator-hand-welle-5-eve-recipe-patch.md" in txt.lower(), (
        "Welle-5-Patch doc-path must be referenced"
    )
    assert "operator-hand-welle-6-eve-recipe-patch.md" in txt.lower(), (
        "Welle-6-Patch doc-path must be referenced"
    )


def test_b21_doc_lists_axis_asymmetric_branch():
    """P3 verdict must include AXIS-ASYMMETRIC branch (one axis
    APPROVED + one REJECTED). Welle-7 retains the dual-axis pattern
    shared with Welle-5/6 (vs. single-axis Welle-3)."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "AXIS-ASYMMETRIC" in txt, (
        "P3 axis-asymmetric branch must be documented "
        "(one axis APPROVED, one REJECTED)"
    )
    assert "WELLE-7-P3-AXIS-ASYMMETRIC" in txt


def test_b22_doc_documents_marker_fire_irreversibility():
    """Welle-7-unique: P5 fires (or blocks) the Phase-3-COMPLETE
    marker, which is irreversible (only revisable by formal
    Phase-3-RE-OPEN-ADR). Doc must capture this in §5 (Rollback-
    Pfade)."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "irreversib" in txt.lower() or "IRREVERSIBEL" in txt, (
        "Welle-7 marker-fire irreversibility must be documented in "
        "Rollback-Pfade (§5)"
    )


def test_b23_doc_documents_directional_cascade_with_welle_6_partner():
    """KW-27 cascade is directional (Welle-6 -> Welle-7). Doc must
    capture this -- a Welle-6-red can propagate into Welle-7-
    Recovery-Workflow as Replay-Divergenz, AND a Welle-7-solo (after
    Welle-6-decouple) requires strict isolation conditions."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    has_directional = (
        "directional" in txt.lower()
        or "Welle-6 -> Welle-7" in txt
        or "Welle-6 → Welle-7" in txt
    )
    assert has_directional, (
        "KW-27 directional cascade (Welle-6 -> Welle-7) must be documented"
    )


def test_b24_doc_documents_phase_3_complete_marker_no_fire_paths():
    """The Rollback-Pfade must explicitly enumerate Phase-3-COMPLETE
    NO-FIRE states for each rollback branch (designation-pending,
    rejected, defect). This is Welle-7-unique because Welle-3/5/6
    don't gate a marker."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    no_fire_count = txt.count("NO-FIRE")
    assert no_fire_count >= 3, (
        f"At least 3 Phase-3-COMPLETE NO-FIRE state references expected "
        f"in Rollback-Pfade, found {no_fire_count}"
    )
