# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for Tag-60 Cross-Repo-Drift-Allowlist-Audit (Noa).

Pins:

  * The YAML-subset parser accepts the empty `allow: []` baseline.
  * Stage-2 coverage math against the Tag-31 BASELINE_INVENTORY
    (clean=4, drift=6, total=10).
  * Stage-3 score formula
    `round(60 * coverage_ratio + 40 * trajectory_ratio)` is locked.
  * Stage-4 verdict thresholds (`>=90` ready, `>=60` caution, else
    blocked).
  * CLI exit-codes for the four `--fail-on` levels.
  * Workflow file exists with the four documented stages.

Sandbox boundary: pure-Python stdlib + pytest. No network, no
gh-CLI. The workflow YAML is read as text and grepped for stage
markers so this test never depends on a YAML library being
installed.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module loader (workspace runs without an installed package).
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "tooling" / "ci" / "audit_cross_repo_drift_allowlist.py"
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "cross-repo-drift-allowlist-audit.yml"
)
ALLOWLIST_PATH = REPO_ROOT / ".cross-repo-drift-allowlist.yaml"


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "audit_cross_repo_drift_allowlist", HELPER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


helper = _load_helper()


# ---------------------------------------------------------------------------
# Stage 1 — Parser tests.
# ---------------------------------------------------------------------------


def test_parse_allowlist_empty_inline() -> None:
    """`allow: []` parses to an empty list — the Tag-31 baseline."""
    entries = helper.parse_allowlist("allow: []\n")
    assert entries == []


def test_parse_allowlist_empty_omitted_value() -> None:
    """`allow:` with no following block parses as empty."""
    entries = helper.parse_allowlist("allow:\n")
    assert entries == []


def test_parse_allowlist_single_entry_round_trip() -> None:
    """A well-formed single entry round-trips through the parser."""
    text = (
        "allow:\n"
        "  - runtime: wirelang/canonical/caveat_set.py\n"
        "    protocol: wakir_protocol/canonical/caveat_set.py\n"
        "    reason: SPDX-header-only delta\n"
        "    follow_up: permanent\n"
    )
    entries = helper.parse_allowlist(text)
    assert len(entries) == 1
    assert entries[0] == {
        "runtime": "wirelang/canonical/caveat_set.py",
        "protocol": "wakir_protocol/canonical/caveat_set.py",
        "reason": "SPDX-header-only delta",
        "follow_up": "permanent",
    }


def test_parse_allowlist_rejects_missing_required_key() -> None:
    """An entry that omits `reason` must raise a parse error."""
    text = (
        "allow:\n"
        "  - runtime: a.py\n"
        "    protocol: b.py\n"
    )
    with pytest.raises(helper.AllowlistParseError):
        helper.parse_allowlist(text)


def test_parse_allowlist_rejects_unknown_key() -> None:
    """Unknown keys (potential typos) are rejected with a clear error."""
    text = (
        "allow:\n"
        "  - runtime: a.py\n"
        "    protocol: b.py\n"
        "    reason: x\n"
        "    note: y\n"  # not a valid key
    )
    with pytest.raises(helper.AllowlistParseError):
        helper.parse_allowlist(text)


def test_parse_allowlist_rejects_inline_scalar() -> None:
    """`allow: foo` (non-`[]` inline scalar) is malformed."""
    with pytest.raises(helper.AllowlistParseError):
        helper.parse_allowlist("allow: foo\n")


def test_parse_allowlist_rejects_missing_anchor() -> None:
    """A YAML doc with no `allow:` key is rejected."""
    with pytest.raises(helper.AllowlistParseError):
        helper.parse_allowlist("# nothing\nother_key: 1\n")


# ---------------------------------------------------------------------------
# Stage 2 — Coverage tests.
# ---------------------------------------------------------------------------


def test_coverage_baseline_empty_allowlist() -> None:
    """Tag-31 baseline: empty allowlist, inventory size 10 / drift 6."""
    cov = helper.compute_coverage([])
    assert cov["inventory_size"] == 10
    assert cov["clean_count"] == 4
    assert cov["drift_count_baseline"] == 6
    assert cov["allowlist_size"] == 0
    assert cov["allowlist_covers_inventory"] == 0
    # Two pairs are slated for SPDX-header-only allowlisting.
    assert len(cov["expected_allowlist_pairs"]) == 2
    assert cov["allowlist_completion"] == 0.0


def test_coverage_unknown_entry_is_flagged() -> None:
    """An allowlist entry not in the inventory is flagged as unknown."""
    bogus = [
        {
            "runtime": "made/up.py",
            "protocol": "also/fake.py",
            "reason": "typo test",
        }
    ]
    cov = helper.compute_coverage(bogus)
    assert cov["allowlist_size"] == 1
    assert cov["allowlist_covers_inventory"] == 0
    assert len(cov["unknown_allowlist_entries"]) == 1


def test_coverage_expected_pairs_complete() -> None:
    """When both SPDX-only pairs are allowlisted, completion is 1.0."""
    allow = [
        {
            "runtime": "wirelang/canonical/caveat_set.py",
            "protocol": "wakir_protocol/canonical/caveat_set.py",
            "reason": "spdx",
        },
        {
            "runtime": "wirelang/identity/aip_document.py",
            "protocol": "wakir_protocol/identity_substrate/aip_document.py",
            "reason": "spdx",
        },
    ]
    cov = helper.compute_coverage(allow)
    assert cov["allowlist_covers_inventory"] == 2
    assert cov["allowlist_completion"] == 1.0
    assert cov["unknown_allowlist_entries"] == []


# ---------------------------------------------------------------------------
# Stage 3 — Score-formula tests.
# ---------------------------------------------------------------------------


def test_score_baseline_is_76_for_tag_31_state() -> None:
    """Tag-31 baseline: coverage_ratio=1.0, trajectory=0.4 -> score=76."""
    cov = helper.compute_coverage([])
    info = helper.compute_readiness_score(cov)
    # 60 * 1.0 + 40 * 0.4 = 60 + 16 = 76.
    assert info["score"] == 76
    assert info["coverage_ratio"] == pytest.approx(1.0)
    assert info["trajectory_ratio"] == pytest.approx(0.4)
    assert info["strategies_assigned"] == 6


def test_score_perfect_when_all_drift_resolved() -> None:
    """A synthetic inventory with all-clean rows yields a 100 score."""
    inv = tuple(
        {"runtime": f"r{i}", "protocol": f"p{i}", "status": "clean", "strategy": ""}
        for i in range(5)
    )
    cov = helper.compute_coverage([], inventory=inv)
    info = helper.compute_readiness_score(cov, inventory=inv)
    # drift_count_baseline == 0 -> coverage_ratio defaults to 1.0,
    # clean_count == total -> trajectory_ratio == 1.0.
    assert info["score"] == 100


def test_score_zero_when_no_strategy_and_no_clean() -> None:
    """Worst case: all rows drift, no strategy assigned -> score=0."""
    inv = tuple(
        {"runtime": f"r{i}", "protocol": f"p{i}", "status": "drift", "strategy": ""}
        for i in range(4)
    )
    cov = helper.compute_coverage([], inventory=inv)
    info = helper.compute_readiness_score(cov, inventory=inv)
    assert info["score"] == 0


# ---------------------------------------------------------------------------
# Stage 4 — Verdict tests.
# ---------------------------------------------------------------------------


def test_verdict_thresholds() -> None:
    assert helper.compute_verdict(100) == helper.VERDICT_READY
    assert helper.compute_verdict(90) == helper.VERDICT_READY
    assert helper.compute_verdict(89) == helper.VERDICT_CAUTION
    assert helper.compute_verdict(76) == helper.VERDICT_CAUTION  # baseline
    assert helper.compute_verdict(60) == helper.VERDICT_CAUTION
    assert helper.compute_verdict(59) == helper.VERDICT_BLOCKED
    assert helper.compute_verdict(0) == helper.VERDICT_BLOCKED


# ---------------------------------------------------------------------------
# End-to-end: run_audit + CLI.
# ---------------------------------------------------------------------------


def test_run_audit_returns_full_report_shape() -> None:
    """Top-level driver returns a JSON-shape with the four stages."""
    report = helper.run_audit(ALLOWLIST_PATH)
    assert report["tag"] == "tag-60"
    assert report["owner"] == "noa"
    assert report["stage_1_parse"]["ok"] is True
    assert report["stage_2_coverage"]["inventory_size"] == 10
    assert report["stage_3_readiness_score"]["score"] == 76
    assert report["stage_4_verdict"] == helper.VERDICT_CAUTION


def test_cli_exit_zero_on_default_fail_mode() -> None:
    """`--fail-on never` (default) returns 0 even when verdict != READY."""
    proc = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--allowlist",
            str(ALLOWLIST_PATH),
        ],
        capture_output=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout.decode("utf-8"))
    assert payload["stage_4_verdict"] == helper.VERDICT_CAUTION


def test_cli_fail_on_caution_exits_nonzero_at_baseline() -> None:
    """`--fail-on caution` flags the Tag-31 baseline (verdict CAUTION)."""
    proc = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--allowlist",
            str(ALLOWLIST_PATH),
            "--fail-on",
            "caution",
        ],
        capture_output=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode == 1


def test_cli_missing_allowlist_returns_2() -> None:
    """Missing allowlist file is a hard-fatal (rc=2), not a CAUTION."""
    proc = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--allowlist",
            "/nonexistent/allowlist.yaml",
        ],
        capture_output=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode == 2


# ---------------------------------------------------------------------------
# Workflow file pin.
# ---------------------------------------------------------------------------


def test_workflow_file_present_and_documents_four_stages() -> None:
    """Pin the workflow's four documented stages.

    Greps the YAML as text — no PyYAML dependency. The four stage
    markers are required to be present so a refactor that drops a
    stage regresses HERE.
    """
    assert WORKFLOW_PATH.is_file(), (
        f"workflow file missing: {WORKFLOW_PATH}"
    )
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    for marker in (
        "Stage 1",
        "Stage 2",
        "Stage 3",
        "Stage 4",
        "audit_cross_repo_drift_allowlist.py",
    ):
        assert marker in text, f"workflow missing marker: {marker!r}"
