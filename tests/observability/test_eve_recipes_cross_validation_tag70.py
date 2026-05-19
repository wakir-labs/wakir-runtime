# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""
Tag-70 hermetic test-suite for the Eve-Recipes Cross-Validation Probe.

These tests exercise ``tooling/ci/cross_validate_eve_recipes.py``
against the two Operator-Hand Cutover-Eve recipes that share the
T0 = 2026-06-08 time-domain:

  * Tag-66 :: ``docs/operations/operator-hand-cutover-eve-final-recipe.md``
  * Tag-69 :: ``docs/operations/g1-g2-last-mile-operator-checklist.md``

The suite is **hermetic**: no ``gh api`` calls, no podman/cosign
invocations, no network I/O. All test fixtures are on-disk markdown.
Stdlib-only helper module.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Allow importing the helper module directly for unit-tests.
REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "tooling" / "ci" / "cross_validate_eve_recipes.py"
TAG66_DOC = REPO_ROOT / "docs" / "operations" / "operator-hand-cutover-eve-final-recipe.md"
TAG69_DOC = REPO_ROOT / "docs" / "operations" / "g1-g2-last-mile-operator-checklist.md"

sys.path.insert(0, str(HELPER_PATH.parent))
import cross_validate_eve_recipes as helper  # noqa: E402


# --------------------------------------------------------------------
# Test 1: helper module imports cleanly + exposes the public API.
# --------------------------------------------------------------------

def test_01_helper_module_public_api() -> None:
    """Helper exposes ``run_all_checks``, ``main``, the envelope class,
    and the documented constants."""
    assert hasattr(helper, "run_all_checks"), "run_all_checks missing"
    assert hasattr(helper, "main"), "main missing"
    assert hasattr(helper, "CrossValidationEnvelope")
    assert hasattr(helper, "CheckResult")
    assert helper.SHARED_T0_DATE == "2026-06-08", (
        "T0 calendar date must be 2026-06-08"
    )
    assert helper.TAG66_EVE_DATE == "2026-05-29"
    assert helper.TAG69_EVE_DATE == "2026-06-07"


# --------------------------------------------------------------------
# Test 2: both docs exist on disk.
# --------------------------------------------------------------------

def test_02_both_recipe_docs_present() -> None:
    """Both Operator-Hand recipe docs must exist on disk."""
    assert TAG66_DOC.is_file(), f"missing: {TAG66_DOC}"
    assert TAG69_DOC.is_file(), f"missing: {TAG69_DOC}"


# --------------------------------------------------------------------
# Test 3: helper produces a CLEAN verdict against the live docs.
# --------------------------------------------------------------------

def test_03_cross_validation_clean_on_live_docs() -> None:
    """The probe must return CROSS-VALIDATION-CLEAN against the
    current Tag-66 + Tag-69 doc-pair."""
    env = helper.run_all_checks(REPO_ROOT)
    assert env.verdict == "CROSS-VALIDATION-CLEAN", (
        f"expected CLEAN, got {env.verdict}; "
        f"failed checks: "
        f"{[c.name for c in env.checks if not c.passed]}"
    )
    assert env.rc == 0


# --------------------------------------------------------------------
# Test 4: time-anchor cross-checks pass.
# --------------------------------------------------------------------

def test_04_time_anchors_pass() -> None:
    """T0 date + per-doc Eve-dates + UTC<->CEST conversion anchor."""
    env = helper.run_all_checks(REPO_ROOT)
    time_anchor_checks = [
        c for c in env.checks
        if c.name.startswith("shared_t0_date_")
        or c.name.startswith("tag66_eve_date")
        or c.name.startswith("tag69_eve_date")
        or c.name.startswith("tag69_utc_cest_token_")
    ]
    assert len(time_anchor_checks) >= 6
    for c in time_anchor_checks:
        assert c.passed, f"time-anchor check failed: {c.name} -- {c.detail}"


# --------------------------------------------------------------------
# Test 5: every Eve-step E1..E12 is named in both docs.
# --------------------------------------------------------------------

def test_05_eve_steps_named_in_both_docs() -> None:
    """Eve-steps E1..E12 must be named in both Tag-66 and Tag-69 in
    either verdict-marker form or section-heading form."""
    env = helper.run_all_checks(REPO_ROOT)
    eve_checks = [c for c in env.checks if c.name.startswith("eve_step_E")]
    assert len(eve_checks) == 12, "expected exactly 12 Eve-step checks"
    for c in eve_checks:
        assert c.passed, f"Eve-step check failed: {c.name} -- {c.detail}"


# --------------------------------------------------------------------
# Test 6: every T0-step T0.0..T0.9 is named in both docs.
# --------------------------------------------------------------------

def test_06_t0_steps_named_in_both_docs() -> None:
    """T0-steps T0.0..T0.9 must be named in both Tag-66 and Tag-69."""
    env = helper.run_all_checks(REPO_ROOT)
    t0_checks = [c for c in env.checks if c.name.startswith("t0_step_T0_")]
    assert len(t0_checks) == 10, "expected exactly 10 T0-step checks"
    for c in t0_checks:
        assert c.passed, f"T0-step check failed: {c.name} -- {c.detail}"


# --------------------------------------------------------------------
# Test 7: verdict roll-up terminals exist in both docs.
# --------------------------------------------------------------------

def test_07_verdict_rollup_terminals() -> None:
    """Tag-66 emits ``EVE-VERDICT-GO``; Tag-69 emits
    ``EVE-VERDICT-GO-LAST-MILE``. Both must be present."""
    env = helper.run_all_checks(REPO_ROOT)
    rollup_checks = [
        c for c in env.checks
        if c.name in (
            "tag66_verdict_rollup_terminal",
            "tag69_verdict_rollup_terminal",
        )
    ]
    assert len(rollup_checks) == 2
    for c in rollup_checks:
        assert c.passed, f"rollup terminal missing: {c.name}"


# --------------------------------------------------------------------
# Test 8: shared action subjects present in both docs.
# --------------------------------------------------------------------

def test_08_shared_action_subjects_present() -> None:
    """Strict-Flip-PR, Trust-Root, AR-pair, Rollback - all four must
    appear in both docs."""
    env = helper.run_all_checks(REPO_ROOT)
    subject_checks = [
        c for c in env.checks if c.name.startswith("shared_subject_")
    ]
    assert len(subject_checks) == 4, "expected 4 shared-subject checks"
    for c in subject_checks:
        assert c.passed, f"shared subject missing: {c.name} -- {c.detail}"


# --------------------------------------------------------------------
# Test 9: sandbox-boundary disclaimer in both intro blocks.
# --------------------------------------------------------------------

def test_09_sandbox_boundary_disclaimer_in_both_intros() -> None:
    """Both Tag-66 and Tag-69 intros must declare doc-form-only /
    Operator-Hand-Sandbox-Gap per ADR-0020 §10."""
    env = helper.run_all_checks(REPO_ROOT)
    sandbox_checks = [
        c for c in env.checks
        if c.name.endswith("sandbox_boundary_disclaimer")
    ]
    assert len(sandbox_checks) == 2
    for c in sandbox_checks:
        assert c.passed, f"sandbox disclaimer missing: {c.name}"


# --------------------------------------------------------------------
# Test 10: cross-reference closure (Tag-69 -> Tag-66, Tag-66 -> Tag-69).
# --------------------------------------------------------------------

def test_10_cross_reference_closure() -> None:
    """Tag-69 frontmatter must list Tag-66 (hard); Tag-66 frontmatter
    must list Tag-69 forward-link (soft, but enforced after Tag-70
    PR lands)."""
    env = helper.run_all_checks(REPO_ROOT)
    xref_checks = [
        c for c in env.checks
        if c.name in (
            "tag69_frontmatter_lists_tag66_predecessor",
            "tag66_frontmatter_forward_link_tag69",
        )
    ]
    assert len(xref_checks) == 2
    for c in xref_checks:
        assert c.passed, f"cross-ref check failed: {c.name} -- {c.detail}"


# --------------------------------------------------------------------
# Test 11: JSON envelope is well-formed.
# --------------------------------------------------------------------

def test_11_json_envelope_well_formed() -> None:
    """Running the helper with --json emits a valid JSON envelope
    with the documented schema."""
    proc = subprocess.run(
        [sys.executable, str(HELPER_PATH), "--json", "--enforce", "false"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    payload = json.loads(proc.stdout)
    assert "verdict" in payload
    assert "rc" in payload
    assert "tag66_path" in payload
    assert "tag69_path" in payload
    assert "checks" in payload
    assert "summary" in payload
    assert payload["summary"]["total"] == len(payload["checks"])
    assert payload["summary"]["passed"] + \
        payload["summary"]["hard_failed"] + \
        payload["summary"]["soft_failed"] == payload["summary"]["total"]


# --------------------------------------------------------------------
# Test 12: helper source imports NO network modules (hermetic).
# --------------------------------------------------------------------

def test_12_helper_source_imports_no_network() -> None:
    """The helper must NOT import ``socket``, ``urllib``, ``requests``
    or ``http`` -- the Tag-70 probe is hermetic. ADR-0020 §10 +
    Memory ``feedback_sandbox_host_trennung`` +
    ``feedback_live_bringup_sandbox_gap``."""
    src = HELPER_PATH.read_text(encoding="utf-8")
    # Strip lines that are inside docstrings: simple but tight.
    # We forbid the exact tokens as imports.
    forbidden = ("import socket", "import urllib", "import requests",
                 "import http", "from socket", "from urllib",
                 "from requests", "from http")
    for tok in forbidden:
        assert tok not in src, (
            f"helper must not import network module; found: '{tok}'"
        )


# --------------------------------------------------------------------
# Test 13: helper CLI exit-code on enforce=true.
# --------------------------------------------------------------------

def test_13_helper_cli_exit_code_enforce_true() -> None:
    """When the live doc-pair is CLEAN, helper exits 0 even with
    --enforce true."""
    proc = subprocess.run(
        [sys.executable, str(HELPER_PATH), "--enforce", "true"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"expected rc=0 on CLEAN with enforce=true; "
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )


# --------------------------------------------------------------------
# Test 14: synthetic DEFECT scenario - missing T0 anchor in Tag-66.
# --------------------------------------------------------------------

def test_14_synthetic_defect_missing_t0_date(tmp_path: Path) -> None:
    """Build a synthetic repo-root where Tag-66 is missing the
    shared T0 date; expect CROSS-VALIDATION-DEFECT."""
    docs_dir = tmp_path / "docs" / "operations"
    docs_dir.mkdir(parents=True)
    # Tag-66 with all anchors EXCEPT shared T0 date.
    tag66_text = TAG66_DOC.read_text(encoding="utf-8")
    mangled = tag66_text.replace("2026-06-08", "YYYY-MM-DD")
    (docs_dir / "operator-hand-cutover-eve-final-recipe.md").write_text(mangled)
    (docs_dir / "g1-g2-last-mile-operator-checklist.md").write_text(
        TAG69_DOC.read_text(encoding="utf-8")
    )

    env = helper.run_all_checks(tmp_path)
    assert env.verdict == "CROSS-VALIDATION-DEFECT", (
        f"expected DEFECT on missing T0-date, got {env.verdict}"
    )
    assert env.rc == 2
    failing = [c for c in env.checks if not c.passed]
    assert any(
        c.name == "shared_t0_date_in_tag66" for c in failing
    ), "expected shared_t0_date_in_tag66 to fail"


# --------------------------------------------------------------------
# Test 15: synthetic DRIFT scenario - missing forward-link only.
# --------------------------------------------------------------------

def test_15_synthetic_drift_missing_forward_link(tmp_path: Path) -> None:
    """Build a synthetic repo-root where Tag-66 lacks the forward-
    link to Tag-69; expect CROSS-VALIDATION-DRIFT (soft-fail)."""
    docs_dir = tmp_path / "docs" / "operations"
    docs_dir.mkdir(parents=True)

    tag66_text = TAG66_DOC.read_text(encoding="utf-8")
    # Strip the forward-link line; keep everything else.
    mangled = re.sub(
        r"^\s*-\s*\"docs/operations/g1-g2-last-mile-operator-checklist\.md\"\s*$\n",
        "",
        tag66_text,
        flags=re.MULTILINE,
    )
    (docs_dir / "operator-hand-cutover-eve-final-recipe.md").write_text(mangled)
    (docs_dir / "g1-g2-last-mile-operator-checklist.md").write_text(
        TAG69_DOC.read_text(encoding="utf-8")
    )

    env = helper.run_all_checks(tmp_path)
    assert env.verdict == "CROSS-VALIDATION-DRIFT", (
        f"expected DRIFT on missing forward-link, got {env.verdict}"
    )
    assert env.rc == 1
    failing = [c for c in env.checks if not c.passed]
    assert len(failing) == 1
    assert failing[0].name == "tag66_frontmatter_forward_link_tag69"
    assert failing[0].severity == "soft"


# --------------------------------------------------------------------
# Test 16: synthetic DOC-NOT-FOUND scenario.
# --------------------------------------------------------------------

def test_16_synthetic_doc_not_found(tmp_path: Path) -> None:
    """When neither doc is present, verdict is DOC-NOT-FOUND
    (rc=3)."""
    env = helper.run_all_checks(tmp_path)
    assert env.verdict == "DOC-NOT-FOUND"
    assert env.rc == 3


# --------------------------------------------------------------------
# Test 17: helper section-heading namespace probe.
# --------------------------------------------------------------------

def test_17_eve_step_present_and_t0_step_present_helpers() -> None:
    """Unit-test the namespace-probe helpers directly."""
    # Verdict-marker form.
    assert helper._eve_step_present("EVE-E5-READY foo", 5)
    # Section-heading form.
    assert helper._eve_step_present("### §2.1 — Eve-Check E1: ...", 1)
    assert helper._eve_step_present("### §2.6 — Eve-E6: AR-Pair", 6)
    # Negative.
    assert not helper._eve_step_present("nothing here", 7)
    # T0 marker variants.
    assert helper._t0_step_present("T0.0-WINDOW-OPEN", 0)
    assert helper._t0_step_present("### §3.2 — T0.1: G1.W1", 1)
    assert helper._t0_step_present("(T0.0)", 0)
    assert not helper._t0_step_present("nothing here", 5)
