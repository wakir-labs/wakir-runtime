# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the CI Aggregator (ADR-0068).

Coverage matrix
---------------

This module covers the pure-function core of
``scripts/ci/ci_aggregator.py`` (the ``decide_expected_set``,
``aggregate_verdicts``, ``render_summary_table``, ``backoff_schedule``,
and ``SubWorkflow.path_filter_triggers`` functions) plus the
workflow-yaml shape invariants that Mira-Hand-Folge needs to rely on
for the Branch-Protection migration.

What is **not** covered here
----------------------------

- The live-mode I/O wrappers (``fetch_pr_changed_files``,
  ``fetch_push_changed_files``, ``poll_workflow_run``). These call the
  GitHub-Actions REST API and are exercised in production by the
  aggregator's own self-run on the migration PR.
- End-to-end CI behaviour. That is gated by the first 2-3 follow-up
  PRs (Mira-Hand-Step-2 in the migration plan, see
  ``docs/ci/aggregator-workflow.md`` §Migration).

Sandbox boundary
----------------

Pure Python + the YAML on disk. No subprocess, no podman, no network.

Author: Tomás Reinhart (Dev-Engineering)
Anchor: ADR-0068 §"Folgeartefakte" — hermetic-tests requirement.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import List

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "ci" / "ci_aggregator.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci-aggregator.yml"


def _load_aggregator_module():
    """Import the aggregator script as a module without going through
    ``sys.path``. Keeps the test module independent of pyproject install
    state (the wirelang package install does not include
    ``scripts/`` under the importable surface).

    Note: we register the loaded module in ``sys.modules`` before
    executing it. Python 3.14's dataclasses machinery introspects
    ``sys.modules[cls.__module__]`` during ``@dataclass`` processing;
    failing to register the module first raises an obscure
    ``AttributeError: 'NoneType' object has no attribute '__dict__'``.
    """
    spec = importlib.util.spec_from_file_location("ci_aggregator", SCRIPT_PATH)
    assert spec is not None, f"could not load {SCRIPT_PATH}"
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["ci_aggregator"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def agg():
    return _load_aggregator_module()


@pytest.fixture(scope="module")
def workflow_yaml() -> dict:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    return yaml.safe_load(text)


# ---------------------------------------------------------------------------
# Test 1 — Inventory has exactly the six Required-Status-Check seeds.
# ---------------------------------------------------------------------------


def test_inventory_carries_six_required_seeds(agg) -> None:
    """The inventory must include all six existing Required-Status names
    so the Mira-Hand-Folge cleanup has a 1:1 mapping.

    Without this, removing the old Required-Names from Branch-Protection
    could leave a check uncovered.
    """
    required_check_names = {
        s.check_name for s in agg.SUB_WORKFLOWS if s.required
    }
    expected_required = {
        "License-Hygiene Gate (ADR-0061)",
        "wirelang suite with rfc8785 + jsonschema",
        "wirelang suite without rfc8785 / jsonschema (shadow)",
        "production-vs-sandbox drift envelope",
        "cross-repo drift (wakir-runtime ↔ wakir-protocol)",
        "Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)",
    }
    assert required_check_names == expected_required, (
        "inventory ``required=True`` rows must exactly match the six "
        "Branch-Protection Required-Status seeds; got "
        f"{required_check_names!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — All sub-workflows in inventory exist on disk.
# ---------------------------------------------------------------------------


def test_inventory_workflow_files_exist_on_disk(agg) -> None:
    """Every ``workflow_file`` in the inventory must exist under
    ``.github/workflows/``. Catches typos and dead references.
    """
    wf_dir = REPO_ROOT / ".github" / "workflows"
    for spec in agg.SUB_WORKFLOWS:
        path = wf_dir / spec.workflow_file
        assert path.exists(), (
            f"inventory references missing workflow {spec.workflow_file!r}"
        )


# ---------------------------------------------------------------------------
# Test 3 — decide_expected_set treats empty diff as "skip everything".
# ---------------------------------------------------------------------------


def test_decide_with_empty_diff_skips_everything(agg) -> None:
    """A PR with no changed files (rare; usually push-to-main with
    no diff) should mark every sub-workflow as ``skip-ok``."""
    verdicts = agg.decide_expected_set([])
    assert len(verdicts) == len(agg.SUB_WORKFLOWS)
    for v in verdicts:
        assert v.expected is False
        assert v.status == "skip-ok"


# ---------------------------------------------------------------------------
# Test 4 — A wirelang-only diff fires wirelang sub-workflows.
# ---------------------------------------------------------------------------


def test_wirelang_diff_fires_wirelang_subworkflows(agg) -> None:
    """A diff touching only ``wirelang/foo.py`` should mark the three
    tests.yml-derived check rows and license-gate as ``expected``,
    Phase-2 as ``expected`` (its filter includes ``wirelang/**``),
    cross-repo-drift as ``expected``."""
    verdicts = agg.decide_expected_set(["wirelang/persona/foo.py"])
    by_name = {v.spec.check_name: v for v in verdicts}
    assert by_name["wirelang suite with rfc8785 + jsonschema"].expected
    assert by_name["wirelang suite without rfc8785 / jsonschema (shadow)"].expected
    assert by_name["production-vs-sandbox drift envelope"].expected
    assert by_name["License-Hygiene Gate (ADR-0061)"].expected
    assert by_name["Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)"].expected
    assert by_name["cross-repo drift (wakir-runtime ↔ wakir-protocol)"].expected


# ---------------------------------------------------------------------------
# Test 5 — A docs-only diff fires license-gate + tests.yml but NOT Phase-2.
# ---------------------------------------------------------------------------


def test_docs_only_diff_skips_phase_2_gate(agg) -> None:
    """A docs-only diff (e.g. ``docs/operations/foo.md``) should fire
    license-gate (which includes ``docs/**``) and tests.yml (which
    includes ``docs/**``) but skip Phase-2 (which only covers
    ``docs/quality-gates/**``).

    This is the precise scenario that caused PR #232's Forever-Pending
    (Tag-35) and the rationale for ADR-0068.
    """
    verdicts = agg.decide_expected_set(["docs/operations/cutover-runbook.md"])
    by_name = {v.spec.check_name: v for v in verdicts}
    assert by_name["License-Hygiene Gate (ADR-0061)"].expected
    assert by_name["wirelang suite with rfc8785 + jsonschema"].expected
    assert not by_name[
        "Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)"
    ].expected, (
        "Phase-2 path-filter is only ``docs/quality-gates/**``; "
        "operator docs should not trigger it"
    )


# ---------------------------------------------------------------------------
# Test 6 — A diff under docs/quality-gates/ fires Phase-2.
# ---------------------------------------------------------------------------


def test_quality_gates_doc_fires_phase_2(agg) -> None:
    """Inverse of test 5: ``docs/quality-gates/foo.md`` should fire
    Phase-2 (filter explicitly includes it)."""
    verdicts = agg.decide_expected_set(["docs/quality-gates/phase-2.md"])
    by_name = {v.spec.check_name: v for v in verdicts}
    assert by_name[
        "Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)"
    ].expected


# ---------------------------------------------------------------------------
# Test 7 — A workflow-only diff fires every sub-workflow.
# ---------------------------------------------------------------------------


def test_workflow_yaml_diff_fires_subset(agg) -> None:
    """A diff touching ``.github/workflows/ci-aggregator.yml`` (a generic
    workflow file not covered by the narrowed Phase-2 or cross-repo-
    drift filters) should fire the four broadly-filtered sub-workflows
    (license-gate + tests.yml x3) but NOT Phase-2 (filter narrows to
    ``phase-2-validation-gate.yml``) and NOT cross-repo-drift (filter
    narrows to ``cross-repo-drift-audit.yml``).

    This distinguishes "broad workflow change" from "targeted workflow
    change" and documents the Phase-2 + cross-repo-drift narrowing.
    """
    verdicts = agg.decide_expected_set([".github/workflows/ci-aggregator.yml"])
    by_name = {v.spec.check_name: v for v in verdicts}
    assert by_name["License-Hygiene Gate (ADR-0061)"].expected
    assert by_name["wirelang suite with rfc8785 + jsonschema"].expected
    assert by_name["wirelang suite without rfc8785 / jsonschema (shadow)"].expected
    assert by_name["production-vs-sandbox drift envelope"].expected
    assert not by_name[
        "cross-repo drift (wakir-runtime ↔ wakir-protocol)"
    ].expected, (
        "cross-repo-drift path-filter narrows to its own workflow file; "
        "ci-aggregator.yml touch should not trigger it"
    )
    assert not by_name[
        "Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)"
    ].expected, (
        "Phase-2 path-filter narrows to its own workflow file; "
        "ci-aggregator.yml touch should not trigger it"
    )


# ---------------------------------------------------------------------------
# Test 8 — aggregate_verdicts: all-success => success.
# ---------------------------------------------------------------------------


def test_aggregate_all_success_is_success(agg) -> None:
    verdicts = agg.decide_expected_set(["wirelang/foo.py"])
    for v in verdicts:
        if v.expected:
            v.status = "success"
    assert agg.aggregate_verdicts(verdicts) == "success"


# ---------------------------------------------------------------------------
# Test 9 — aggregate_verdicts: one failure blocks.
# ---------------------------------------------------------------------------


def test_aggregate_one_failure_blocks(agg) -> None:
    verdicts = agg.decide_expected_set(["wirelang/foo.py"])
    flipped = False
    for v in verdicts:
        if v.expected:
            if not flipped:
                v.status = "failure"
                flipped = True
            else:
                v.status = "success"
    assert agg.aggregate_verdicts(verdicts) == "failure"


# ---------------------------------------------------------------------------
# Test 10 — aggregate_verdicts: skip-ok-only is success.
# ---------------------------------------------------------------------------


def test_aggregate_skip_ok_only_is_success(agg) -> None:
    """The aggregator's whole point: if no sub-workflow is expected to
    fire (changed-files set does not intersect any path-filter), the
    aggregator must return ``success``. This is the case that
    structurally eliminates Forever-Pending — a docs-cleanup PR that
    touches only README.md no longer hangs.
    """
    # README.md is in license-gate's path-globs but not in any other
    # path-glob set. Force a synthetic "no matches" by feeding a path
    # that matches nothing in the inventory.
    verdicts = agg.decide_expected_set(["unrelated-top-level-file.txt"])
    expected_count = sum(1 for v in verdicts if v.expected)
    assert expected_count == 0
    assert agg.aggregate_verdicts(verdicts) == "success"


# ---------------------------------------------------------------------------
# Test 11 — aggregate_verdicts: pending while waiting.
# ---------------------------------------------------------------------------


def test_aggregate_with_pending_is_pending(agg) -> None:
    """While at least one expected sub-workflow is still ``pending``
    and none have failed, the aggregator-level verdict is ``pending``.
    The live-mode polling loop converts ``pending`` to terminal status
    over time."""
    verdicts = agg.decide_expected_set(["wirelang/foo.py"])
    first_expected = next(v for v in verdicts if v.expected)
    # Leave ``first_expected`` as pending, mark all others success.
    for v in verdicts:
        if v.expected and v is not first_expected:
            v.status = "success"
    assert agg.aggregate_verdicts(verdicts) == "pending"


# ---------------------------------------------------------------------------
# Test 12 — aggregate_verdicts: missing is blocking.
# ---------------------------------------------------------------------------


def test_aggregate_missing_blocks(agg) -> None:
    """``missing`` status (workflow expected but never produced a run
    on the SHA) must block the aggregator. Otherwise a silent CI-runner
    outage could trick the aggregator into green."""
    verdicts = agg.decide_expected_set(["wirelang/foo.py"])
    flipped = False
    for v in verdicts:
        if v.expected:
            if not flipped:
                v.status = "missing"
                flipped = True
            else:
                v.status = "success"
    assert agg.aggregate_verdicts(verdicts) == "failure"


# ---------------------------------------------------------------------------
# Test 13 — backoff schedule respects cap.
# ---------------------------------------------------------------------------


def test_backoff_schedule_respects_cap(agg) -> None:
    sched = agg.backoff_schedule(
        base_seconds=5.0, cap_seconds=60.0, max_attempts=10
    )
    assert len(sched) == 10
    assert sched[0] == 5.0
    assert sched[1] == 10.0
    assert sched[2] == 20.0
    assert sched[3] == 40.0
    assert sched[4] == 60.0
    assert sched[5] == 60.0
    assert all(s <= 60.0 for s in sched)


# ---------------------------------------------------------------------------
# Test 14 — workflow YAML shape: ci-aggregator job display-name is stable.
# ---------------------------------------------------------------------------


def test_workflow_job_display_name_is_stable(workflow_yaml: dict) -> None:
    """The aggregator job's ``name:`` field is what Mira-Hand-Folge
    sets as the sole Required-Status-Check name in Branch-Protection.
    If this changes silently, the Required-Status reference would
    Forever-Pend until Branch-Protection is updated.

    Pin the value to ``ci-aggregator``. Any future rename requires a
    coordinated Mira-Hand-Folge update.
    """
    jobs = workflow_yaml["jobs"]
    assert "ci-aggregator" in jobs, (
        "the workflow must declare a job named ``ci-aggregator`` (its "
        "``name:`` field is the Branch-Protection Required-Status name)"
    )
    job = jobs["ci-aggregator"]
    assert job["name"] == "ci-aggregator", (
        f"job display-name pinned to ``ci-aggregator``; got {job['name']!r}"
    )


# ---------------------------------------------------------------------------
# Test 15 — workflow YAML has NO path-filter.
# ---------------------------------------------------------------------------


def test_workflow_has_no_top_level_path_filter(workflow_yaml: dict) -> None:
    """The aggregator must fire on every PR and every push. A
    path-filter at the workflow level would recreate the very
    Forever-Pending pattern the aggregator exists to eliminate.
    """
    on = workflow_yaml.get(True) or workflow_yaml.get("on")
    assert on is not None
    pr = on.get("pull_request") or {}
    push = on.get("push") or {}
    assert "paths" not in pr, (
        "aggregator must NOT declare ``on.pull_request.paths`` — the "
        "whole point is to fire on every PR regardless of changed-files"
    )
    assert "paths" not in push, (
        "aggregator must NOT declare ``on.push.paths`` — see test_15 "
        "rationale"
    )


# ---------------------------------------------------------------------------
# Test 16 — workflow YAML pins minimal permissions.
# ---------------------------------------------------------------------------


def test_workflow_permissions_are_minimal(workflow_yaml: dict) -> None:
    """The aggregator only reads. ``contents: read``, ``actions: read``,
    ``pull-requests: read`` is the minimum needed to poll workflow runs
    and read the PR's changed-files list. Catches accidental
    over-scoping.
    """
    perms = workflow_yaml["permissions"]
    assert perms.get("contents") == "read"
    assert perms.get("actions") == "read"
    assert perms.get("pull-requests") == "read"
    # No write permission should be present anywhere.
    for key, value in perms.items():
        assert value == "read", (
            f"permission {key!r} has non-read value {value!r}; "
            "aggregator must be read-only"
        )


# ---------------------------------------------------------------------------
# Test 17 — render_summary_table emits all rows.
# ---------------------------------------------------------------------------


def test_render_summary_table_emits_all_rows(agg) -> None:
    verdicts = agg.decide_expected_set(["wirelang/foo.py"])
    out = agg.render_summary_table(verdicts)
    for v in verdicts:
        # Each check name should appear in the table.
        assert v.spec.check_name in out, (
            f"check_name {v.spec.check_name!r} missing from summary"
        )
    assert "Aggregator Verdict:" in out
    assert "ADR-0068" in out  # ADR anchor must be cited.


# ---------------------------------------------------------------------------
# Test 18 — path_filter glob matching: directory-prefix glob.
# ---------------------------------------------------------------------------


def test_path_filter_directory_prefix_glob(agg) -> None:
    """``wirelang/**`` must match ``wirelang/foo/bar.py`` but not
    ``other/foo.py``. Mirrors GitHub-Actions ``paths:`` semantics."""
    spec = agg.SubWorkflow(
        workflow_file="x.yml",
        check_name="x",
        path_globs=("wirelang/**",),
    )
    assert spec.path_filter_triggers(["wirelang/persona/foo.py"])
    assert spec.path_filter_triggers(["wirelang/foo.py"])
    assert not spec.path_filter_triggers(["other/foo.py"])
    assert not spec.path_filter_triggers(["docs/foo.md"])


# ---------------------------------------------------------------------------
# Test 19 — path_filter glob matching: extension glob.
# ---------------------------------------------------------------------------


def test_path_filter_extension_glob(agg) -> None:
    """``**/*.py`` must match any .py file regardless of depth."""
    spec = agg.SubWorkflow(
        workflow_file="x.yml",
        check_name="x",
        path_globs=("**/*.py",),
    )
    assert spec.path_filter_triggers(["foo.py"])
    assert spec.path_filter_triggers(["a/b/c.py"])
    assert not spec.path_filter_triggers(["foo.md"])


# ---------------------------------------------------------------------------
# Test 20 — Multi-file diff: any-match triggers.
# ---------------------------------------------------------------------------


def test_path_filter_any_match_triggers(agg) -> None:
    """If even one file in the diff matches one glob, the path-filter
    triggers. Mirrors GitHub-Actions ``paths:`` semantics (OR, not AND).
    """
    spec = agg.SubWorkflow(
        workflow_file="x.yml",
        check_name="x",
        path_globs=("wirelang/**",),
    )
    assert spec.path_filter_triggers(
        ["unrelated.md", "wirelang/foo.py", "also-unrelated.txt"]
    )
    assert not spec.path_filter_triggers(
        ["unrelated.md", "other/foo.py", "also-unrelated.txt"]
    )


# ---------------------------------------------------------------------------
# Test 21 — Inventory glob lists are non-empty.
# ---------------------------------------------------------------------------


def test_inventory_path_globs_are_nonempty(agg) -> None:
    """Defensive: an empty ``path_globs`` tuple would cause
    ``path_filter_triggers`` to always return False, marking the
    sub-workflow as Forever-skip-ok. Catches accidental empty edits.
    """
    for spec in agg.SUB_WORKFLOWS:
        assert spec.path_globs, (
            f"sub-workflow {spec.check_name!r} has empty path_globs; "
            "this would make the aggregator always skip it"
        )


# ---------------------------------------------------------------------------
# Test 22 — Decide-only mode CLI smoke (sanity).
# ---------------------------------------------------------------------------


def test_decide_only_mode_cli_smoke(agg, tmp_path: Path) -> None:
    """Runs the aggregator's ``--mode=decide-only`` entrypoint with a
    fixture changed-files file and asserts the exit code + summary
    content. This is the bridge between the pure-function tests above
    and the workflow's actual invocation pattern.
    """
    changed = tmp_path / "changed.txt"
    changed.write_text("wirelang/foo.py\n", encoding="utf-8")
    summary = tmp_path / "summary.md"
    rc = agg.main(
        [
            "--mode=decide-only",
            f"--changed-files={changed}",
            f"--summary-path={summary}",
        ]
    )
    # decide-only: rc=0 iff no failure (success or pending). Fresh
    # decide returns pending (no I/O upgrade), so rc=0.
    assert rc == 0
    out = summary.read_text(encoding="utf-8")
    assert "wirelang suite with rfc8785 + jsonschema" in out
    assert "License-Hygiene Gate" in out
    assert "Aggregator Verdict:" in out
