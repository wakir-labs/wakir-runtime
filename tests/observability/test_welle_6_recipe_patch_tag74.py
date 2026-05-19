# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-74 hermetic tests for the Welle-6 Day-of-Recipe-Patch
substrate (Operator-Hand companion doc to the Tag-66 Eve-Recipe,
following the Welle-3 Tag-71-Patch and Welle-5 Tag-73-Patch
precedents).

Layout:
  * Tests A1..A9 exercise the doc itself
    (docs/operations/operator-hand-welle-6-eve-recipe-patch.md).
  * Tests B1..B19 exercise the verifier
    (tooling/ci/verify_welle_6_recipe_patch_doc.py) -- including
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
    / "operator-hand-welle-6-eve-recipe-patch.md"
)
VERIFIER_PATH = (
    REPO_ROOT / "tooling" / "ci" / "verify_welle_6_recipe_patch_doc.py"
)


def _load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_welle_6_recipe_patch_doc", VERIFIER_PATH
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
    assert 'tag: "tag-74"' in fm, "tag value must be tag-74"
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


def test_a5_doc_lists_four_welle_6_rollback_paths():
    txt = DOC_PATH.read_text(encoding="utf-8")
    for r in ("R-W6-A", "R-W6-B", "R-W6-C", "R-W6-D"):
        assert f"### {r} --" in txt, f"rollback path {r} missing"


def test_a6_doc_lists_three_ar_hand_touchpoints():
    txt = DOC_PATH.read_text(encoding="utf-8")
    for tp in ("TP-W6-1", "TP-W6-2", "TP-W6-3"):
        assert f"### {tp} --" in txt, f"touchpoint {tp} missing"


def test_a7_doc_explicitly_names_both_hot_spot_axes():
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "nats-subscribe-mode" in txt, "nats-subscribe-mode axis name missing"
    assert "subscribe-loop-cascade" in txt, (
        "subscribe-loop-cascade axis name missing"
    )


def test_a8_doc_references_kw27_doppel_welle_and_welle_7_partner():
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "KW-27" in txt, "KW-27 anchor missing"
    assert "Doppel-Welle" in txt, "Doppel-Welle wording missing"
    assert "Welle-7" in txt, "Welle-7 partner reference missing"


def test_a9_doc_documents_cross_modul_out_of_band_asymmetry():
    """Welle-6/KW-27 asymmetry vs. Welle-5/KW-26: cross-modul handled
    out-of-band (Phase-2-Acceptance-Gate daily rollup), not inline."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "out-of-band" in txt.lower() or "out of band" in txt.lower(), (
        "KW-27 out-of-band cross-modul asymmetry must be documented"
    )
    assert "Phase-2-Acceptance-Gate" in txt or "Phase-2 Acceptance Gate" in txt, (
        "Phase-2-Acceptance-Gate rollup substrate must be referenced"
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
    # soft warnings allowed -- the spec accepts them
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
    # Strip only the first `**Owner**: Operator-Hand (Mira).` line
    # (which is inside P1).
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
    mutated = txt.replace("### R-W6-D --", "### R-DELETED --", 1)
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("R-W6-D" in f and "H5" in f for f in result.hard_failures)


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
        "state/welle-6-pre-auditor-decision.json",
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
        if "WELLE-6-VERDICT-" in line and "->" in line:
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
    mutated = txt.replace("nats-subscribe-mode", "REMOVED-AXIS-A")
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any(
        "H11" in f and "nats-subscribe-mode" in f for f in result.hard_failures
    )


def test_b11_verifier_detects_missing_axis_state_file(tmp_path):
    """Strip cascade-into-welle-7-drift state-file ref, verify H12
    fires."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    mutated = txt.replace(
        "state/welle-6-cascade-into-welle-7-drift.json",
        "state/some-irrelevant-file.json",
    )
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("H12" in f for f in result.hard_failures)


def test_b12_verifier_cli_exit_zero_on_real_doc():
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
    assert "WELLE-6-RECIPE-PATCH-DOC-CLEAN" in proc.stdout


def test_b13_verifier_cli_exit_two_on_missing_doc(tmp_path):
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


def test_b14_verifier_constants_match_doc_substrate():
    """Wenn der Spec sich aendert, soll dieser Test bewusst brechen."""
    mod = _load_verifier()
    assert mod.REQUIRED_P_STEPS == ["P1", "P2", "P3", "P4", "P5"]
    assert "Time-Window" in mod.REQUIRED_P_SUBFIELDS
    assert "Owner" in mod.REQUIRED_P_SUBFIELDS
    assert "Verdict-Marker" in mod.REQUIRED_P_SUBFIELDS
    assert (
        mod.PRE_AUDITOR_STATE_FILE == "state/welle-6-pre-auditor-decision.json"
    )
    assert (
        mod.NATS_SUBSCRIBE_MODE_STATE_FILE
        == "state/welle-6-subscribe-mode-live.json"
    )
    assert (
        mod.CASCADE_DRIFT_STATE_FILE
        == "state/welle-6-cascade-into-welle-7-drift.json"
    )
    assert mod.IIA_ANCHOR == "IIA-1130"
    assert mod.HOT_SPOT_AXES == [
        "nats-subscribe-mode",
        "subscribe-loop-cascade",
    ]
    assert mod.REQUIRED_R_PATHS == [
        "R-W6-A",
        "R-W6-B",
        "R-W6-C",
        "R-W6-D",
    ]
    assert mod.REQUIRED_TP == ["TP-W6-1", "TP-W6-2", "TP-W6-3"]


def test_b15_doc_documents_convergent_date_anchor():
    """The Welle-6-Day date is convergent post-ADR-0066 (KW-27-Mi
    2026-06-24). Doc must reference this anchor."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "2026-06-24" in txt, "Welle-6-Day convergent anchor must be referenced"
    assert "KW-27" in txt


def test_b16_doc_lists_helper_substrate_paths():
    """§7 Helper-Substrat must reference the Tag-74 verifier path
    and the Tag-74 test path -- doc-to-substrate closure."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "tooling/ci/verify_welle_6_recipe_patch_doc.py" in txt
    assert "tests/observability/test_welle_6_recipe_patch_tag74.py" in txt
    assert "tooling/ci/welle_6_hot_spot_aggregator.py" in txt


def test_b17_doc_references_welle_3_and_welle_5_patches_as_precedents():
    """Welle-6-Patch must reference BOTH the Welle-3-Patch (Tag-71)
    AND the Welle-5-Patch (Tag-73) as template precedents -- this is
    a hard requirement of the Tag-74 brief (sequential cascade)."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "Tag-71" in txt, "Welle-3-Patch (Tag-71) precedent must be referenced"
    assert "Tag-73" in txt, "Welle-5-Patch (Tag-73) precedent must be referenced"
    assert "operator-hand-welle-3-eve-recipe-patch.md" in txt.lower(), (
        "Welle-3-Patch doc-path must be referenced"
    )
    assert "operator-hand-welle-5-eve-recipe-patch.md" in txt.lower(), (
        "Welle-5-Patch doc-path must be referenced"
    )


def test_b18_doc_lists_axis_asymmetric_branch():
    """P3 verdict must include AXIS-ASYMMETRIC branch (one axis
    APPROVED + one REJECTED). This is the structural difference vs.
    the Welle-3-single-axis pattern, shared with Welle-5."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "AXIS-ASYMMETRIC" in txt, (
        "P3 axis-asymmetric branch must be documented "
        "(one axis APPROVED, one REJECTED)"
    )
    assert "WELLE-6-P3-AXIS-ASYMMETRIC" in txt


def test_b19_doc_documents_directional_cascade_asymmetry_vs_welle_5():
    """KW-27 cascade is directional (Welle-6 -> Welle-7); unlike the
    symmetric KW-26 Welle-4/Welle-5 coupling. Doc must capture this
    distinguishing constraint, e.g. that a Welle-7-red post-merge
    signals upstream Welle-6 substrate defect."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    # The directionality token: "directional" or "Welle-6 -> Welle-7"
    # or "Welle-6 → Welle-7" or the explicit cascade-into-welle-7
    has_directional = (
        "directional" in txt.lower()
        or "Welle-6 -> Welle-7" in txt
        or "Welle-6 → Welle-7" in txt
        or "cascade-into-welle-7" in txt
        or "cascade-into-Welle-7" in txt
    )
    assert has_directional, (
        "KW-27 directional cascade (Welle-6 -> Welle-7) must be documented "
        "to distinguish from KW-26 symmetric coupling"
    )
