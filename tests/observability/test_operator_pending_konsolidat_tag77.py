# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-77 hermetic tests for the Operator-Hand Pending-Items
Konsolidat Master-Doc substrate (Pre-Cutover-Eve Aggregator-Master-
Reference for the Tag-50..Tag-76 spawn corridor).

Layout:
  * Tests A1..A12 exercise the doc itself
    (docs/operations/operator-hand-pending-items-konsolidat.md).
  * Tests B1..B10 exercise the verifier
    (tooling/ci/verify_operator_pending_konsolidat_doc.py) --
    including happy-path, structural-defect injection, and CLI
    behaviour.

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
    / "operator-hand-pending-items-konsolidat.md"
)
VERIFIER_PATH = (
    REPO_ROOT
    / "tooling"
    / "ci"
    / "verify_operator_pending_konsolidat_doc.py"
)


def _load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_operator_pending_konsolidat_doc", VERIFIER_PATH
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
    assert 'tag: "tag-77"' in fm, "tag value must be tag-77"
    assert 'owner: "kai"' in fm, "owner must be kai"
    assert 'status: "active"' in fm, "status must be active"


def test_a3_doc_references_all_ten_items():
    txt = DOC_PATH.read_text(encoding="utf-8")
    for n in range(1, 11):
        token = f"### Item I{n} --"
        assert token in txt, f"section heading for I{n} missing"


def test_a4_doc_has_ten_sections():
    txt = DOC_PATH.read_text(encoding="utf-8")
    for n in range(1, 11):
        token = f"## §{n} --"
        assert token in txt, f"section §{n} missing"


def test_a5_doc_lists_four_eve_verdict_markers():
    txt = DOC_PATH.read_text(encoding="utf-8")
    for v in (
        "EVE-VERDICT-ALL-CLEAN",
        "EVE-VERDICT-PARTIAL-HOLD",
        "EVE-VERDICT-DEFER",
        "EVE-VERDICT-EMERGENCY-HOLD",
    ):
        assert v in txt, f"verdict marker {v} missing"


def test_a6_doc_lists_three_ar_hand_touchpoints():
    txt = DOC_PATH.read_text(encoding="utf-8")
    for tp in ("TP-EVE-1", "TP-EVE-2", "TP-EVE-3"):
        assert tp in txt, f"touchpoint {tp} missing"


def test_a7_doc_references_pre_cutover_eve_date():
    """Pre-Cutover-Eve date 2026-06-26 must be referenced."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "2026-06-26" in txt, "Pre-Cutover-Eve date missing"


def test_a8_doc_reproduces_ar_vorzeichen_verbatim():
    import re as _re
    txt = DOC_PATH.read_text(encoding="utf-8")
    # Normalise blockquote markers and collapse whitespace to handle
    # the multi-line quoted AR-Signal verbatim.
    normalised = _re.sub(r"\s+", " ", txt.replace("> ", ""))
    for tok in (
        "Phase-3-Marathon ends at Welle-7 cutover",
        "explicit AR-Hand re-arm signal",
        "No Phase-4 substrate enters the planning",
    ):
        assert tok in normalised, (
            f"AR-Vorzeichen verbatim token '{tok}' missing"
        )


def test_a9_doc_lists_required_predecessor_doc_paths():
    txt = DOC_PATH.read_text(encoding="utf-8")
    for p in (
        "docs/operations/operator-hand-production-bringup-recipe.md",
        "docs/operations/operator-hand-cutover-eve-final-recipe.md",
        "docs/operations/g1-g2-last-mile-operator-checklist.md",
        "docs/operations/cross-substrate-parity-runbook.md",
        "docs/operations/wakir-protocol-cross-review-zone-3-handoff-plan.md",
    ):
        assert p in txt, f"predecessor-doc path '{p}' missing"


def test_a10_doc_each_item_has_six_subfields():
    """Each of I1..I10 must have Owner, Timing, Prerequisites,
    Step-by-Step, Verification, Rollback subfields."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    for n in range(1, 11):
        # Find the item block boundaries.
        item_marker = f"### Item I{n} --"
        idx = txt.find(item_marker)
        assert idx >= 0, f"I{n} not found"
        # Determine the end of the item block (next ### or ##).
        rest = txt[idx + len(item_marker):]
        next_heading = len(rest)
        for marker in ("\n### ", "\n## "):
            pos = rest.find(marker)
            if pos > 0 and pos < next_heading:
                next_heading = pos
        block = rest[:next_heading]
        for sub in (
            "**Owner**",
            "**Timing**",
            "**Prerequisites**",
            "**Step-by-Step**",
            "**Verification**",
            "**Rollback**",
        ):
            assert sub in block, (
                f"I{n} missing subfield {sub}"
            )


def test_a11_doc_explicit_phase_3_close_positioning():
    """Per the AR-Vorzeichen pin, the doc must explicitly mark
    itself as Phase-3-close, not Phase-4-open."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    assert "Phase-3-close" in txt, "Phase-3-close positioning missing"
    assert "Phase-4" in txt, "Phase-4 reference (for prohibition) missing"


def test_a12_doc_references_pr_numbers_in_frontmatter():
    """Related-PRs in frontmatter must include the key Tag-50..Tag-76
    PRs (#389, #395, #396, #411, #477)."""
    txt = DOC_PATH.read_text(encoding="utf-8")
    end = txt.find("\n---\n", 4)
    fm = txt[4:end]
    for pr in ('"#389"', '"#395"', '"#396"', '"#411"', '"#477"'):
        assert pr in fm, f"related_prs must include {pr}"


# ---- B: tests against the verifier helper ----------------------------


def test_b1_verifier_module_loads():
    mod = _load_verifier()
    assert hasattr(mod, "verify")
    assert hasattr(mod, "VerifyResult")
    assert hasattr(mod, "main")


def test_b2_verifier_ok_on_actual_doc(tmp_path):
    mod = _load_verifier()
    res = mod.verify(DOC_PATH)
    assert res.ok, (
        f"verifier reported hard failures on actual doc: "
        f"{res.hard_failures}"
    )


def test_b3_verifier_hard_fails_on_missing_doc(tmp_path):
    mod = _load_verifier()
    fake = tmp_path / "missing.md"
    res = mod.verify(fake)
    assert not res.ok
    assert any("doc not found" in f for f in res.hard_failures)


def test_b4_verifier_detects_missing_item(tmp_path):
    """Inject defect: remove the I7 item heading."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    broken = txt.replace(
        "### Item I7 -- OPEN-K3 Baseline-Metadata-Carry-Forward",
        "### Item IX7 -- broken-renamed",
    )
    p = tmp_path / "broken.md"
    p.write_text(broken, encoding="utf-8")
    res = mod.verify(p)
    assert not res.ok
    assert any("I7" in f for f in res.hard_failures)


def test_b5_verifier_detects_missing_subfield(tmp_path):
    """Inject defect: remove the **Owner** subfield from I3."""
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    # Find I3 block and strip its **Owner** subfield line.
    idx = txt.find("### Item I3 --")
    assert idx > 0
    # Find next item heading boundary.
    rest = txt[idx:]
    next_idx = rest.find("\n### Item I4")
    block = rest[:next_idx]
    broken_block = block.replace(
        "**Owner**: Operator-Hand", "Owner-stripped: Operator-Hand"
    )
    broken = txt[:idx] + broken_block + txt[idx + next_idx:]
    p = tmp_path / "broken.md"
    p.write_text(broken, encoding="utf-8")
    res = mod.verify(p)
    assert not res.ok
    assert any("Owner" in f and "I3" in f for f in res.hard_failures)


def test_b6_verifier_detects_missing_verdict_marker(tmp_path):
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    broken = txt.replace(
        "EVE-VERDICT-EMERGENCY-HOLD", "EVE-VERDICT-XXX-HOLD"
    )
    p = tmp_path / "broken.md"
    p.write_text(broken, encoding="utf-8")
    res = mod.verify(p)
    assert not res.ok
    assert any(
        "EVE-VERDICT-EMERGENCY-HOLD" in f
        for f in res.hard_failures
    )


def test_b7_verifier_detects_missing_touchpoint(tmp_path):
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    broken = txt.replace("TP-EVE-2", "TP-XXX-2")
    p = tmp_path / "broken.md"
    p.write_text(broken, encoding="utf-8")
    res = mod.verify(p)
    assert not res.ok
    assert any("TP-EVE-2" in f for f in res.hard_failures)


def test_b8_verifier_detects_missing_ar_vorzeichen_token(tmp_path):
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    broken = txt.replace(
        "Phase-3-Marathon ends at Welle-7 cutover",
        "Phase-3-Marathon ENDS at Welle-X cutover",
    )
    p = tmp_path / "broken.md"
    p.write_text(broken, encoding="utf-8")
    res = mod.verify(p)
    assert not res.ok
    assert any("AR-Vorzeichen" in f for f in res.hard_failures)


def test_b9_verifier_detects_missing_pre_cutover_eve_date(tmp_path):
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    broken = txt.replace("2026-06-26", "2026-09-99")
    p = tmp_path / "broken.md"
    p.write_text(broken, encoding="utf-8")
    res = mod.verify(p)
    assert not res.ok
    assert any("2026-06-26" in f for f in res.hard_failures)


def test_b10_verifier_cli_returns_zero_on_actual_doc():
    proc = subprocess.run(
        [
            sys.executable,
            str(VERIFIER_PATH),
            "--doc",
            "docs/operations/operator-hand-pending-items-konsolidat.md",
            "--repo-root",
            str(REPO_ROOT),
            "--quiet",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"verifier CLI returned non-zero on actual doc: "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )


def test_b11_verifier_cli_returns_two_on_missing_doc(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(VERIFIER_PATH),
            "--doc",
            "docs/operations/does-not-exist.md",
            "--repo-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2


def test_b12_verifier_cli_aggregate_verdict_mode_emits_marker():
    """In --aggregate-verdict mode the helper emits a one-line
    verdict-summary on stdout."""
    proc = subprocess.run(
        [
            sys.executable,
            str(VERIFIER_PATH),
            "--doc",
            "docs/operations/operator-hand-pending-items-konsolidat.md",
            "--repo-root",
            str(REPO_ROOT),
            "--quiet",
            "--aggregate-verdict",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "aggregate-verdict:" in proc.stdout
    assert "EVE-VERDICT-ALL-CLEAN" in proc.stdout


def test_b13_verifier_detects_wrong_tag_in_frontmatter(tmp_path):
    mod = _load_verifier()
    txt = DOC_PATH.read_text(encoding="utf-8")
    broken = txt.replace('tag: "tag-77"', 'tag: "tag-99"', 1)
    p = tmp_path / "broken.md"
    p.write_text(broken, encoding="utf-8")
    res = mod.verify(p)
    assert not res.ok
    assert any("tag-77" in f for f in res.hard_failures)
