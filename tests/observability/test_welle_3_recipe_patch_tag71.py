# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-71 hermetic tests for the Welle-3 Day-of-Recipe-Patch
substrate (Operator-Hand companion doc to the Tag-66 Eve-Recipe).

Layout:
  * Tests A1..A6 exercise the doc itself
    (docs/operations/operator-hand-welle-3-eve-recipe-patch.md).
  * Tests B1..B10 exercise the verifier
    (tooling/ci/verify_welle_3_recipe_patch_doc.py) -- including
    happy-path, structural-defect injection, and CLI behaviour.

All tests are hermetic: no network, no subprocess outside the
verifier itself, stdlib + pytest only.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "operations" / "operator-hand-welle-3-eve-recipe-patch.md"
VERIFIER_PATH = REPO_ROOT / "tooling" / "ci" / "verify_welle_3_recipe_patch_doc.py"


def _load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_welle_3_recipe_patch_doc", VERIFIER_PATH
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
    # locate closing ---
    end = txt.find("\n---\n", 4)
    assert end > 0, "frontmatter not closed"
    fm = txt[4:end]
    for key in ("title:", "status:", "owner:", "tag:", "audience:"):
        assert key in fm, f"frontmatter missing key {key}"
    assert 'tag: "tag-71"' in fm, "tag value must be tag-71"
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


def test_a5_doc_lists_three_welle_3_rollback_paths():
    txt = DOC_PATH.read_text(encoding="utf-8")
    for r in ("R-W3-A", "R-W3-B", "R-W3-C"):
        assert f"### {r} --" in txt, f"rollback path {r} missing"


def test_a6_doc_lists_three_ar_hand_touchpoints():
    txt = DOC_PATH.read_text(encoding="utf-8")
    for tp in ("TP-W3-1", "TP-W3-2", "TP-W3-3"):
        assert f"### {tp} --" in txt, f"touchpoint {tp} missing"


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
    # Remove the P3 section (from `### P3 --` up to next `### `).
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
    # Strip only the first `**Owner**:` line (which is inside P1).
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
    mutated = txt.replace("### R-W3-B --", "### R-DELETED --", 1)
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("R-W3-B" in f and "H5" in f for f in result.hard_failures)


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
        "state/welle-3-pre-auditor-decision.json", "state/some-other-file.json"
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
    import re

    # Replace verdict rows except the first two with empty.
    # Each row matches `| ... -> ``WELLE-3-VERDICT-...``...|`
    lines = txt.splitlines()
    seen = 0
    out = []
    for line in lines:
        if "WELLE-3-VERDICT-" in line and "->" in line:
            seen += 1
            if seen > 2:
                continue
        out.append(line)
    mutated = "\n".join(out)
    p = tmp_path / "patch.md"
    p.write_text(mutated, encoding="utf-8")
    result = mod.verify(p)
    assert not result.ok
    assert any("H7" in f for f in result.hard_failures)


def test_b10_verifier_cli_exit_zero_on_real_doc():
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
    assert "WELLE-3-RECIPE-PATCH-DOC-CLEAN" in proc.stdout


def test_b11_verifier_cli_exit_two_on_missing_doc(tmp_path):
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


def test_b12_verifier_constants_match_doc_substrate():
    """Wenn der Spec sich aendert, soll diese Test bewusst brechen."""
    mod = _load_verifier()
    assert mod.REQUIRED_P_STEPS == ["P1", "P2", "P3", "P4", "P5"]
    assert "Time-Window" in mod.REQUIRED_P_SUBFIELDS
    assert "Owner" in mod.REQUIRED_P_SUBFIELDS
    assert "Verdict-Marker" in mod.REQUIRED_P_SUBFIELDS
    assert mod.PRE_AUDITOR_STATE_FILE == "state/welle-3-pre-auditor-decision.json"
    assert mod.IIA_ANCHOR == "IIA-1130"


def test_b13_doc_documents_date_ambiguity():
    """All three Welle-3-Day date anchors must be referenced
    explicitly in the doc -- this is a hard requirement of the
    Tag-71 brief (Welle-3 date is intentionally fluid)."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "Tag-66" in txt
    assert "ADR-0066" in txt
    assert "Brief Tag-71" in txt
    assert "2026-06-08" in txt, "T0 anchor must be referenced"


def test_b14_doc_lists_helper_substrate_paths():
    """§7 Helper-Substrat must reference the Tag-71 verifier path
    and the Tag-71 test path -- doc-to-substrate closure."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "tooling/ci/verify_welle_3_recipe_patch_doc.py" in txt
    assert "tests/observability/test_welle_3_recipe_patch_tag71.py" in txt
    assert "tooling/ci/welle_3_hot_spot_aggregator.py" in txt
