# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic CI-substrate tests for the Tag-56 Marathon-Final-Acceptance
Live-Verify Gate workflow
(``.github/workflows/marathon-final-acceptance-live-verify-gate.yml``).

Auftrag-Anker
-------------

* Tag-56 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode, AR-persistent):
  promote the Tag-55 Live-Verify-Audit
  (``tests/quality_gates/test_marathon_final_acceptance_live_verify.py``,
  75 hermetic tests) into a verpflichtenden CI-Gate that fires on any
  drift across the six Pyramide-layer-substrates and the eight surface-
  sources the audit introspects.

Scope (gate-introspection vs. live-verify)
------------------------------------------

The live-verify audit (Tag-55, 75 tests) verifies that the consolidated
Final-Acceptance doc's surface-claims match the actual main-tip
substrate. THIS module (Tag-56) verifies the CI-gate workflow that
wraps the audit — that the gate's path-filter covers every drift-source
the audit reads, that its job-display-name matches the contracted
Required-Status-Check-Name, and that its sandbox-boundary stays
hermetic.

Test scope
----------

* Workflow YAML structural shape:
  - Single job with the documented Required-Status-Check-Name.
  - ``runs-on: ubuntu-latest`` + ``timeout-minutes`` set.
  - ``permissions: contents: read`` (read-only sandbox).
  - ``concurrency.group`` set + ``cancel-in-progress: false`` (a
    drift-detection gate must not cancel mid-run).
  - Three trigger sources: push (main), pull_request, workflow_dispatch.

* Path-filter coverage (the contract this gate enforces):
  - Push + PR path-filter must list ALL six Layer-1..6 test files
    that the audit's Surface-2 introspects.
  - Push + PR path-filter must list ALL six companion docs that
    Surface-2..5 + Surface-Pre cite.
  - Push + PR path-filter must list both workflow-files the audit
    introspects (marker + sanity-gate).
  - Push + PR path-filter must list the consolidated doc, the
    live-verify audit itself, and the gate-workflow self.
  - Push and PR path-filters must be identical (no drift between
    push-gating and PR-gating).

* Step shape:
  - Stage 1 runs ``pytest tests/quality_gates/test_marathon_final_acceptance_live_verify.py``.
  - Stage 2 ``if: always()`` emits a surface-shape snapshot to
    ``GITHUB_STEP_SUMMARY``.
  - Python 3.13 setup (production-lane parity).
  - pytest and PyYAML installed.

* Sandbox boundary: pure file-system read + yaml parse. No
  subprocess, no podman, no live-VM, no GitHub API.

Hermetic-tests
--------------

Auftrag minimum: >= 10 hermetic tests. This module ships >= 18.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "marathon-final-acceptance-live-verify-gate.yml"
)
LIVE_VERIFY_PATH = (
    REPO_ROOT
    / "tests"
    / "quality_gates"
    / "test_marathon_final_acceptance_live_verify.py"
)
CONSOLIDATED_DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "quality-gates"
    / "phase-3-marathon-final-acceptance.md"
)


# The six Pyramide-Layer-substrate test files the Tag-55 live-verify
# audit introspects (Surface-2 of the consolidated doc).
LAYER_TEST_FILES = (
    "tests/phase_3c/test_phase_3_final_regression.py",
    "tests/phase_3c/test_cutover_day_e2e_drill.py",
    "tests/phase_3c/test_marathon_schluss_acceptance_drill.py",
    "tests/phase_3c/test_marathon_anti_patterns.py",
    "tests/phase_3c/test_pre_mortem_failure_mode_coverage_audit.py",
    "tests/phase_3c/test_defence_in_depth_layer_6.py",
)

# The six Companion docs the live-verify audit reads (Surface-2..5 +
# Surface-Pre).
COMPANION_DOCS = (
    "docs/quality-gates/marathon-acceptance-pyramide.md",
    "docs/quality-gates/phase-3-marathon-anti-patterns.md",
    "docs/quality-gates/pre-mortem-failure-mode-coverage.md",
    "docs/quality-gates/phase-3-marathon-schluss-acceptance.md",
    "docs/observability/sli-slo-phase-3-marathon.md",
    "docs/ci/pre-cutover-final-sanity-gate-runbook.md",
)

# The two workflow files the live-verify audit YAML-introspects.
INTROSPECTED_WORKFLOWS = (
    ".github/workflows/phase-3-complete-marker.yml",
    ".github/workflows/pre-cutover-final-sanity-gate.yml",
)

# The consolidated doc + live-verify audit + gate-workflow self.
SELF_REFERENCES = (
    "docs/quality-gates/phase-3-marathon-final-acceptance.md",
    "tests/quality_gates/test_marathon_final_acceptance_live_verify.py",
    ".github/workflows/marathon-final-acceptance-live-verify-gate.yml",
)

REQUIRED_PATHS = (
    LAYER_TEST_FILES + COMPANION_DOCS + INTROSPECTED_WORKFLOWS + SELF_REFERENCES
)

REQUIRED_STATUS_CHECK_NAME = (
    "marathon-final-acceptance live-verify (75 tests, 8 surfaces)"
)


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW_PATH.is_file(), f"workflow missing: {WORKFLOW_PATH}"
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_yaml(workflow_text: str) -> dict:
    data = yaml.safe_load(workflow_text)
    assert isinstance(data, dict)
    return data


def _on_block(workflow_yaml: dict) -> dict:
    # PyYAML parses the bare ``on:`` key as Python ``True`` (YAML 1.1
    # boolean coercion). Tolerate both shapes.
    on = workflow_yaml.get("on", workflow_yaml.get(True))
    assert isinstance(on, dict), "workflow.on must be a mapping"
    return on


# ---------------------------------------------------------------------------
# Pre-conditions: substrate exists.
# ---------------------------------------------------------------------------


def test_workflow_file_exists() -> None:
    assert WORKFLOW_PATH.is_file(), f"gate workflow missing: {WORKFLOW_PATH}"


def test_live_verify_audit_exists() -> None:
    # The gate would be a nullary check if the audit it wraps were
    # absent.
    assert LIVE_VERIFY_PATH.is_file(), (
        f"Tag-55 live-verify audit missing: {LIVE_VERIFY_PATH}"
    )


def test_consolidated_doc_exists() -> None:
    # The Tag-54 consolidated doc is the audit's input surface.
    assert CONSOLIDATED_DOC_PATH.is_file(), (
        f"Tag-54 consolidated doc missing: {CONSOLIDATED_DOC_PATH}"
    )


# ---------------------------------------------------------------------------
# Workflow shape: triggers, permissions, concurrency, job-display-name.
# ---------------------------------------------------------------------------


def test_workflow_name(workflow_yaml: dict) -> None:
    assert workflow_yaml.get("name") == "marathon-final-acceptance-live-verify-gate"


def test_workflow_has_all_three_trigger_sources(workflow_yaml: dict) -> None:
    on = _on_block(workflow_yaml)
    assert "push" in on, "push trigger missing"
    assert "pull_request" in on, "pull_request trigger missing"
    assert "workflow_dispatch" in on, "workflow_dispatch trigger missing"


def test_push_trigger_is_main_branch_only(workflow_yaml: dict) -> None:
    on = _on_block(workflow_yaml)
    branches = on["push"].get("branches", [])
    assert branches == ["main"], (
        f"push trigger should be main-only, got {branches!r}"
    )


def test_workflow_permissions_read_only(workflow_yaml: dict) -> None:
    perms = workflow_yaml.get("permissions", {})
    assert perms == {"contents": "read"}, (
        f"sandbox-boundary: permissions must be contents:read, got {perms!r}"
    )


def test_workflow_has_concurrency_group(workflow_yaml: dict) -> None:
    conc = workflow_yaml.get("concurrency", {})
    assert isinstance(conc, dict), "concurrency block must be a mapping"
    assert "group" in conc, "concurrency.group missing"
    # Drift-detection gates must not cancel mid-run; otherwise a
    # rapid follow-up push silences the gate signal.
    assert conc.get("cancel-in-progress") is False, (
        "drift-detection gates must set cancel-in-progress: false"
    )


def test_single_job_display_name_matches_required_status_check(
    workflow_yaml: dict,
) -> None:
    jobs = workflow_yaml.get("jobs", {})
    assert len(jobs) == 1, f"gate must have exactly one job, got {list(jobs)!r}"
    (job_id, job) = next(iter(jobs.items()))
    assert job_id == "marathon-final-acceptance-live-verify-gate"
    # Per feedback_branch_protection_check_names.md, the
    # Required-Status-Check-Name is the job display-name.
    assert job.get("name") == REQUIRED_STATUS_CHECK_NAME, (
        f"job display-name must equal Required-Status-Check-Name "
        f"{REQUIRED_STATUS_CHECK_NAME!r}, got {job.get('name')!r}"
    )


def test_job_runs_on_ubuntu_latest(workflow_yaml: dict) -> None:
    jobs = workflow_yaml["jobs"]
    (job,) = jobs.values()
    assert job.get("runs-on") == "ubuntu-latest"


def test_job_has_timeout(workflow_yaml: dict) -> None:
    jobs = workflow_yaml["jobs"]
    (job,) = jobs.values()
    timeout = job.get("timeout-minutes")
    assert isinstance(timeout, int) and 1 <= timeout <= 30, (
        f"job timeout must be a sane minute-count, got {timeout!r}"
    )


# ---------------------------------------------------------------------------
# Path-filter coverage: the contract this gate enforces.
# ---------------------------------------------------------------------------


def _paths_for(on_block: dict, trigger: str) -> list[str]:
    sub = on_block.get(trigger, {})
    if not isinstance(sub, dict):
        return []
    return list(sub.get("paths", []) or [])


@pytest.mark.parametrize("layer_path", LAYER_TEST_FILES)
def test_push_path_filter_covers_layer_substrate(
    workflow_yaml: dict, layer_path: str
) -> None:
    paths = _paths_for(_on_block(workflow_yaml), "push")
    assert layer_path in paths, (
        f"push path-filter must cover Pyramide-Layer substrate {layer_path!r} "
        f"so Tag-55 Surface-2 drift triggers a re-verify"
    )


@pytest.mark.parametrize("layer_path", LAYER_TEST_FILES)
def test_pr_path_filter_covers_layer_substrate(
    workflow_yaml: dict, layer_path: str
) -> None:
    paths = _paths_for(_on_block(workflow_yaml), "pull_request")
    assert layer_path in paths, (
        f"PR path-filter must cover Pyramide-Layer substrate {layer_path!r} "
        f"so Tag-55 Surface-2 drift triggers a re-verify"
    )


@pytest.mark.parametrize("companion", COMPANION_DOCS)
def test_push_path_filter_covers_companion_doc(
    workflow_yaml: dict, companion: str
) -> None:
    paths = _paths_for(_on_block(workflow_yaml), "push")
    assert companion in paths, (
        f"push path-filter must cover companion doc {companion!r} "
        f"so Tag-55 Surface-2..5+Pre drift triggers a re-verify"
    )


@pytest.mark.parametrize("companion", COMPANION_DOCS)
def test_pr_path_filter_covers_companion_doc(
    workflow_yaml: dict, companion: str
) -> None:
    paths = _paths_for(_on_block(workflow_yaml), "pull_request")
    assert companion in paths


@pytest.mark.parametrize("wf_path", INTROSPECTED_WORKFLOWS)
def test_push_path_filter_covers_introspected_workflow(
    workflow_yaml: dict, wf_path: str
) -> None:
    paths = _paths_for(_on_block(workflow_yaml), "push")
    assert wf_path in paths, (
        f"push path-filter must cover introspected workflow {wf_path!r} "
        f"so Tag-55 Surface-1+Pre drift triggers a re-verify"
    )


@pytest.mark.parametrize("wf_path", INTROSPECTED_WORKFLOWS)
def test_pr_path_filter_covers_introspected_workflow(
    workflow_yaml: dict, wf_path: str
) -> None:
    paths = _paths_for(_on_block(workflow_yaml), "pull_request")
    assert wf_path in paths


@pytest.mark.parametrize("self_ref", SELF_REFERENCES)
def test_push_path_filter_covers_self_references(
    workflow_yaml: dict, self_ref: str
) -> None:
    paths = _paths_for(_on_block(workflow_yaml), "push")
    assert self_ref in paths, (
        f"push path-filter must cover {self_ref!r} (consolidated doc / "
        f"live-verify audit / gate self) so any of its drift re-runs the gate"
    )


@pytest.mark.parametrize("self_ref", SELF_REFERENCES)
def test_pr_path_filter_covers_self_references(
    workflow_yaml: dict, self_ref: str
) -> None:
    paths = _paths_for(_on_block(workflow_yaml), "pull_request")
    assert self_ref in paths


def test_push_and_pr_path_filters_are_identical(workflow_yaml: dict) -> None:
    # Drift between push-gating and PR-gating would let a PR slip
    # through on a Surface the merged push then catches.
    on = _on_block(workflow_yaml)
    push_paths = sorted(_paths_for(on, "push"))
    pr_paths = sorted(_paths_for(on, "pull_request"))
    assert push_paths == pr_paths, (
        "push and PR path-filters must be identical; "
        f"push-only={sorted(set(push_paths) - set(pr_paths))!r} "
        f"pr-only={sorted(set(pr_paths) - set(push_paths))!r}"
    )


def test_path_filter_is_complete_against_required_set(workflow_yaml: dict) -> None:
    # Aggregated assertion: every entry in REQUIRED_PATHS must
    # appear in BOTH push and PR path-filters.
    on = _on_block(workflow_yaml)
    push = set(_paths_for(on, "push"))
    pr = set(_paths_for(on, "pull_request"))
    missing_push = [p for p in REQUIRED_PATHS if p not in push]
    missing_pr = [p for p in REQUIRED_PATHS if p not in pr]
    assert not missing_push, f"push path-filter incomplete: {missing_push!r}"
    assert not missing_pr, f"PR path-filter incomplete: {missing_pr!r}"


# ---------------------------------------------------------------------------
# Step shape: pytest invocation + summary diagnostic.
# ---------------------------------------------------------------------------


def test_job_runs_live_verify_pytest_target(workflow_yaml: dict) -> None:
    jobs = workflow_yaml["jobs"]
    (job,) = jobs.values()
    steps = job.get("steps", [])
    run_texts = " ".join(s.get("run", "") for s in steps if isinstance(s, dict))
    assert (
        "pytest tests/quality_gates/test_marathon_final_acceptance_live_verify.py"
        in run_texts
    ), "Stage 1 must invoke the Tag-55 live-verify audit by exact pytest target path"


def test_job_has_summary_diagnostic_step(workflow_yaml: dict) -> None:
    jobs = workflow_yaml["jobs"]
    (job,) = jobs.values()
    steps = job.get("steps", [])
    # Look for a step whose ``if`` is ``always()`` and which writes to
    # ``GITHUB_STEP_SUMMARY``.
    found = False
    for s in steps:
        if not isinstance(s, dict):
            continue
        if s.get("if") == "always()" and "GITHUB_STEP_SUMMARY" in s.get("run", ""):
            found = True
            break
    assert found, (
        "Stage 2 surface-shape snapshot must exist as an if: always() "
        "step writing GITHUB_STEP_SUMMARY"
    )


def test_job_uses_python_3_13(workflow_yaml: dict) -> None:
    # Production-lane parity (tests.yml / hash-derivate-gate / license-gate).
    jobs = workflow_yaml["jobs"]
    (job,) = jobs.values()
    steps = job.get("steps", [])
    found = False
    for s in steps:
        if not isinstance(s, dict):
            continue
        if s.get("uses", "").startswith("actions/setup-python@"):
            with_ = s.get("with", {})
            if str(with_.get("python-version")) == "3.13":
                found = True
                break
    assert found, "Python 3.13 setup step missing (production-lane parity)"


def test_job_installs_pytest_and_pyyaml(workflow_yaml: dict) -> None:
    jobs = workflow_yaml["jobs"]
    (job,) = jobs.values()
    steps = job.get("steps", [])
    run_texts = " ".join(s.get("run", "") for s in steps if isinstance(s, dict))
    assert "pytest>=8.0" in run_texts, "pytest>=8.0 install missing"
    assert "PyYAML>=6.0" in run_texts, "PyYAML>=6.0 install missing"


# ---------------------------------------------------------------------------
# Cardinality / sanity invariants.
# ---------------------------------------------------------------------------


def test_layer_substrate_files_actually_exist() -> None:
    # A path-filter that references non-existent files would never
    # trigger. The gate's drift-coverage is only as good as the
    # substrate it filters on.
    missing = [p for p in LAYER_TEST_FILES if not (REPO_ROOT / p).is_file()]
    assert not missing, f"Layer test-files missing on tree: {missing!r}"


def test_companion_docs_actually_exist() -> None:
    missing = [p for p in COMPANION_DOCS if not (REPO_ROOT / p).is_file()]
    assert not missing, f"Companion docs missing on tree: {missing!r}"


def test_introspected_workflows_actually_exist() -> None:
    missing = [
        p for p in INTROSPECTED_WORKFLOWS if not (REPO_ROOT / p).is_file()
    ]
    assert not missing, f"Introspected workflows missing on tree: {missing!r}"


def test_required_status_check_name_in_workflow_text(workflow_text: str) -> None:
    # Belt-and-braces: even if YAML parsing changes, the literal
    # Required-Status-Check-Name string must be present so an operator
    # can grep for it during branch-protection setup.
    assert REQUIRED_STATUS_CHECK_NAME in workflow_text, (
        f"Required-Status-Check-Name {REQUIRED_STATUS_CHECK_NAME!r} "
        f"must appear verbatim in the workflow file"
    )
