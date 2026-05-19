# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
# REUSE-IgnoreStart
"""Tests for the Tag-63 REUSE-Wrap Enforce-Flip Actual-Execution-Plan.

Anchors
-------

* Plan-doc (extended in Tag-63):
  ``docs/operations/reuse-wrap-enforce-flip-readiness-plan.md`` --
  new sections §7 (Actual-Flip-Execution-Recipe), §8
  (Rollback-Procedure), §9 (Cross-Anchors).
* Workflow (new in Tag-63):
  ``.github/workflows/reuse-wrap-enforce-flip-stability-window-probe.yml``.
* Rollback-mock (new in Tag-63):
  ``tooling/ci/mock_reuse_lint_rollback.py``.
* Predecessor test:
  ``tests/ci/test_reuse_lint_enforce_flip_readiness_tag62.py``
  (PR #394, Tag-62 substance).

What this suite pins down
-------------------------

1. The plan-doc has the three new section anchors (§7, §8, §9)
   with their canonical sub-anchors.
2. The plan-doc cross-references PR #389 (Kai) and PR #396 (Kai)
   in §9.
3. The new stability-window-probe workflow exists and has the
   three documented stages.
4. The rollback-mock exposes the four canonical verdicts and
   the ``decide_rollback`` pure function.
5. The rollback-mock decision-matrix is correct across every
   (enforce_state x run-history) combination called out in §8.1.
6. CLI integration: the mock's ``--mode self-verify`` exits 0
   and its ``--mode decide`` JSON-format round-trips cleanly.
7. Edge-cases: empty run-history, malformed enforce-state,
   negative flake-budget, mixed conclusions, shorthand parser.

Hermetic
--------

stdlib + pytest. No subprocess into the network. The mock is
loaded as a module (same pattern as the Tag-62 test).
"""

# REUSE-IgnoreEnd

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "reuse-wrap-enforce-flip-readiness-plan.md"
)
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "reuse-wrap-enforce-flip-stability-window-probe.yml"
)
MOCK_PATH = REPO_ROOT / "tooling" / "ci" / "mock_reuse_lint_rollback.py"


def _load_mock():
    """Load the rollback-mock as a module (same pattern as Tag-62 test)."""
    mod_name = "mock_reuse_lint_rollback_tag63"
    spec = importlib.util.spec_from_file_location(mod_name, MOCK_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mock():
    return _load_mock()


# ---------------------------------------------------------------------------
# 1. Plan-doc additions exist
# ---------------------------------------------------------------------------

def test_plan_doc_has_section_seven_anchor():
    text = PLAN_DOC_PATH.read_text(encoding="utf-8")
    assert "## §7 - Actual-Flip-Execution-Recipe (Tag-63)" in text


def test_plan_doc_has_section_eight_anchor():
    text = PLAN_DOC_PATH.read_text(encoding="utf-8")
    assert "## §8 - Rollback-Procedure (Tag-63 deepening of §6)" in text


def test_plan_doc_has_section_nine_anchor():
    text = PLAN_DOC_PATH.read_text(encoding="utf-8")
    assert "## §9 - Cross-Anchors" in text


def test_plan_doc_section_seven_has_five_subsections():
    """§7.1 through §7.5 must each be present."""
    text = PLAN_DOC_PATH.read_text(encoding="utf-8")
    required = ("### §7.1", "### §7.2", "### §7.3", "### §7.4", "### §7.5")
    missing = [s for s in required if s not in text]
    assert missing == [], f"§7 missing sub-anchors: {missing}"


def test_plan_doc_section_eight_has_four_subsections():
    """§8.1 through §8.4 must each be present."""
    text = PLAN_DOC_PATH.read_text(encoding="utf-8")
    required = ("### §8.1", "### §8.2", "### §8.3", "### §8.4")
    missing = [s for s in required if s not in text]
    assert missing == [], f"§8 missing sub-anchors: {missing}"


def test_plan_doc_section_nine_cross_refs_kai_prs():
    """§9.1 must cite #389, §9.2 must cite #396."""
    text = PLAN_DOC_PATH.read_text(encoding="utf-8")
    assert "### §9.1 - Kai PR #389" in text
    assert "### §9.2 - Kai PR #396" in text


# ---------------------------------------------------------------------------
# 2. Stability-window-probe workflow exists + has the three stages
# ---------------------------------------------------------------------------

def test_stability_window_probe_workflow_exists():
    assert WORKFLOW_PATH.is_file(), (
        f"Tag-63 stability-window-probe workflow missing at {WORKFLOW_PATH}"
    )


def test_stability_window_probe_workflow_is_dispatch_only():
    """The probe is operator-tool, not per-PR; trigger must be dispatch."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    # And no pull_request / push triggers.
    assert "pull_request:" not in text
    assert "push:" not in text


def test_stability_window_probe_workflow_has_three_stages():
    """Stages 1/2/3 must each be present by name."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "Stage 1 - Probe N consecutive readiness runs" in text
    assert "Stage 2 - Self-verify rollback mock substrate" in text
    assert "Stage 3 - Aggregate stability-window verdict" in text


def test_stability_window_probe_workflow_emits_three_verdicts():
    """The aggregator must reference all three canonical verdicts."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "STABILITY-WINDOW-CONFIRMED" in text
    assert "STABILITY-WINDOW-NOT-YET" in text
    assert "STABILITY-WINDOW-DEFECT" in text


# ---------------------------------------------------------------------------
# 3. Rollback-mock exposes the four canonical verdicts
# ---------------------------------------------------------------------------

def test_mock_exposes_decide_rollback_callable(mock):
    assert callable(mock.decide_rollback)


def test_mock_exposes_rollback_verdict_dataclass(mock):
    """The dataclass should have the documented seven fields."""
    rv = mock.RollbackVerdict(
        verdict="MOCK-ROLLBACK-NO-OP",
        enforce_state="0",
        runs_seen=0,
        runs_red=0,
        runs_green=0,
        flake_budget=0,
        reason="test",
    )
    assert rv.verdict == "MOCK-ROLLBACK-NO-OP"
    assert rv.runs_seen == 0


# ---------------------------------------------------------------------------
# 4. Decision matrix -- canonical paths
# ---------------------------------------------------------------------------

def test_mock_no_op_when_enforce_off(mock):
    """enforce_state=0 always yields NO-OP regardless of runs."""
    v = mock.decide_rollback(
        enforce_state="0",
        recent_main_runs=[
            {"conclusion": "failure", "head_sha": "a"},
            {"conclusion": "failure", "head_sha": "b"},
        ],
    )
    assert v.verdict == "MOCK-ROLLBACK-NO-OP"


def test_mock_hold_when_all_green(mock):
    v = mock.decide_rollback(
        enforce_state="1",
        recent_main_runs=[
            {"conclusion": "success", "head_sha": "a"},
            {"conclusion": "success", "head_sha": "b"},
            {"conclusion": "success", "head_sha": "c"},
        ],
    )
    assert v.verdict == "MOCK-ROLLBACK-HOLD"
    assert v.runs_green == 3
    assert v.runs_red == 0


def test_mock_hold_when_red_within_budget(mock):
    """One red run with flake_budget=1 stays HOLD."""
    v = mock.decide_rollback(
        enforce_state="1",
        recent_main_runs=[
            {"conclusion": "failure", "head_sha": "a"},
            {"conclusion": "success", "head_sha": "b"},
            {"conclusion": "success", "head_sha": "c"},
        ],
        flake_budget=1,
    )
    assert v.verdict == "MOCK-ROLLBACK-HOLD"
    assert v.runs_red == 1


def test_mock_recommend_when_red_exceeds_budget(mock):
    """Two reds with flake_budget=1 yields RECOMMEND."""
    v = mock.decide_rollback(
        enforce_state="1",
        recent_main_runs=[
            {"conclusion": "failure", "head_sha": "a"},
            {"conclusion": "failure", "head_sha": "b"},
            {"conclusion": "success", "head_sha": "c"},
        ],
        flake_budget=1,
    )
    assert v.verdict == "MOCK-ROLLBACK-RECOMMEND"
    assert v.runs_red == 2


def test_mock_escalate_when_all_red(mock):
    """All recent runs red => ESCALATE (not RECOMMEND)."""
    v = mock.decide_rollback(
        enforce_state="1",
        recent_main_runs=[
            {"conclusion": "failure", "head_sha": "a"},
            {"conclusion": "failure", "head_sha": "b"},
            {"conclusion": "failure", "head_sha": "c"},
        ],
    )
    assert v.verdict == "MOCK-ROLLBACK-ESCALATE"


def test_mock_hold_when_no_settled_runs(mock):
    """Empty history with enforce_state=1 yields HOLD, not ESCALATE."""
    v = mock.decide_rollback(
        enforce_state="1",
        recent_main_runs=[],
    )
    assert v.verdict == "MOCK-ROLLBACK-HOLD"
    assert v.runs_seen == 0


# ---------------------------------------------------------------------------
# 5. Decision matrix -- edge cases
# ---------------------------------------------------------------------------

def test_mock_ignores_in_progress_runs(mock):
    """``in_progress`` and ``neutral`` are neither green nor red."""
    v = mock.decide_rollback(
        enforce_state="1",
        recent_main_runs=[
            {"conclusion": "in_progress", "head_sha": "a"},
            {"conclusion": "neutral", "head_sha": "b"},
        ],
    )
    # No settled runs => HOLD (same as empty history)
    assert v.verdict == "MOCK-ROLLBACK-HOLD"
    assert v.runs_seen == 0


def test_mock_treats_timed_out_as_red(mock):
    """timed_out and cancelled count as red, per Stage 3 contract."""
    v = mock.decide_rollback(
        enforce_state="1",
        recent_main_runs=[
            {"conclusion": "timed_out", "head_sha": "a"},
            {"conclusion": "cancelled", "head_sha": "b"},
        ],
    )
    # Two reds, all-red, >=2 samples => ESCALATE
    assert v.verdict == "MOCK-ROLLBACK-ESCALATE"


def test_mock_rejects_invalid_enforce_state(mock):
    with pytest.raises(ValueError, match="invalid enforce_state"):
        mock.decide_rollback(
            enforce_state="2",
            recent_main_runs=[],
        )


def test_mock_rejects_negative_flake_budget(mock):
    with pytest.raises(ValueError, match="flake_budget must be >= 0"):
        mock.decide_rollback(
            enforce_state="1",
            recent_main_runs=[],
            flake_budget=-1,
        )


# ---------------------------------------------------------------------------
# 6. CLI integration -- self-verify exits 0
# ---------------------------------------------------------------------------

def test_mock_cli_self_verify_exits_zero():
    proc = subprocess.run(
        [sys.executable, str(MOCK_PATH), "--mode", "self-verify"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "self-verify OK" in proc.stdout


def test_mock_cli_decide_text_format_renders_verdict():
    proc = subprocess.run(
        [
            sys.executable,
            str(MOCK_PATH),
            "--mode", "decide",
            "--enforce-state", "1",
            "--runs", "success,success,success",
            "--flake-budget", "0",
            "--format", "text",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "MOCK-ROLLBACK-HOLD" in proc.stdout
    assert "all settled main runs are green" in proc.stdout


def test_mock_cli_decide_json_format_round_trips():
    proc = subprocess.run(
        [
            sys.executable,
            str(MOCK_PATH),
            "--mode", "decide",
            "--enforce-state", "1",
            "--runs", "failure,failure",
            "--flake-budget", "0",
            "--format", "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["verdict"] == "MOCK-ROLLBACK-ESCALATE"
    assert payload["enforce_state"] == "1"
    assert payload["runs_red"] == 2
    assert payload["runs_green"] == 0


def test_mock_cli_accepts_json_list_runs():
    """The --runs argument also accepts a JSON list literal."""
    runs_json = json.dumps([
        {"conclusion": "success", "head_sha": "abc"},
        {"conclusion": "failure", "head_sha": "def"},
    ])
    proc = subprocess.run(
        [
            sys.executable,
            str(MOCK_PATH),
            "--mode", "decide",
            "--enforce-state", "1",
            "--runs", runs_json,
            "--flake-budget", "0",
            "--format", "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    # 1 green, 1 red, budget 0 => RECOMMEND
    assert payload["verdict"] == "MOCK-ROLLBACK-RECOMMEND"
