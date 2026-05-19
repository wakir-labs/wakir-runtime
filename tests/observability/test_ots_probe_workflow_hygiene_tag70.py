# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""
Tag-70 hermetic test-suite for the OTS Pre-Anchor Activation Probe
workflow hygiene.

Side-finding context
====================

Tomás-Tag-69 PR #439 surfaced that ``ots-pre-anchor-activation-probe.yml``
has been failing since Tag-62 push 26094551884 with the runtime error::

    /opt/hostedtoolcache/Python/3.11.15/x64/bin/python3: No module named pytest

The workflow's hermetic test-suite step calls ``python3 -m pytest`` but
``actions/setup-python@v5`` only provisions the CPython interpreter — it
does not install ``pytest``. The workflow is non-required (does not gate
PR merge), but a perma-red non-required check is exactly the kind of
alert-fatigue noise SRE owns to eradicate.

Tag-70 Noa minimal-fix: add an explicit ``Install pytest + PyYAML``
step between ``setup-python`` and ``Stage 1``. Pin pytest to
``>=7,<9`` and PyYAML to ``>=6,<7`` to avoid unannounced major-version
drift while keeping the floor compatible with the rest of the repo's
pytest invocations.

The first iteration of the fix shipped ``pytest`` only; a follow-up
runner trace surfaced that the existing Tag-59 test-suite also
imports ``yaml`` (PyYAML, non-stdlib). Including PyYAML in the same
install step keeps the fix minimal (one step, one install command).

Substance brief (>= 10 tests; suite carries 13)
================================================

  1. Workflow file exists at the documented path.
  2. Workflow YAML parses cleanly.
  3. Workflow declares exactly one job ``ots-pre-anchor-activation-probe``.
  4. The job's steps include a step named ``Install pytest …`` (Tag-70
     fix marker).
  5. The Install-pytest step appears AFTER ``actions/setup-python@v5`` and
     BEFORE the ``Run hermetic Tag-59 test-suite`` step (ordering invariant
     — pytest must exist before the test-step runs).
  6. The Install-pytest step pins a version range ``pytest>=7,<9`` (no
     unbounded ``pip install pytest``).
  7. The Install-pytest step runs ``python3 -m pip install --upgrade pip``
     (clean baseline, deterministic).
  8. The hermetic test-suite step still invokes
     ``python3 -m pytest tests/ci/test_ots_pre_anchor_activation_probe_tag59.py``
     (the bug-target line is preserved verbatim — fix did not refactor
     the call shape).
  9. Stages 1/2/3 of the probe remain stdlib-only (no pip install nor
     pytest import in their ``run:`` bodies — hygiene invariant).
 10. The probe permissions block remains ``contents: read`` (least-priv;
     the pytest-install fix did not widen the security envelope).
 11. The workflow ``on:`` triggers still include
     ``.github/workflows/ots-pre-anchor-activation-probe.yml`` under both
     ``push`` and ``pull_request`` paths (so this very fix re-runs the
     workflow on PR + merge — without that path-filter the green
     re-verify never fires).
 12. Workflow file is REUSE-compliant (carries an SPDX identifier in the
     first 4 lines).
 13. Suite is hermetic: no network-I/O imports (urllib, requests, httpx,
     socket, subprocess outside conftest).

Suite is hermetic: zero network, zero podman, zero gh api, zero cosign.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "ots-pre-anchor-activation-probe.yml"
)
TEST_FILE = pathlib.Path(__file__)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW_PATH.is_file(), f"missing workflow: {WORKFLOW_PATH}"
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_doc(workflow_text: str) -> dict:
    doc = yaml.safe_load(workflow_text)
    assert isinstance(doc, dict), "workflow root must be a mapping"
    return doc


@pytest.fixture(scope="module")
def probe_job(workflow_doc: dict) -> dict:
    jobs = workflow_doc.get("jobs")
    assert isinstance(jobs, dict) and jobs, "workflow must declare jobs"
    assert list(jobs.keys()) == ["ots-pre-anchor-activation-probe"], (
        "Tag-70 invariant: exactly one job named "
        "'ots-pre-anchor-activation-probe'"
    )
    job = jobs["ots-pre-anchor-activation-probe"]
    assert isinstance(job, dict), "job must be a mapping"
    return job


@pytest.fixture(scope="module")
def step_names(probe_job: dict) -> list[str]:
    steps = probe_job.get("steps")
    assert isinstance(steps, list) and steps, "job must declare steps"
    return [s.get("name", "") for s in steps]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_01_workflow_file_exists() -> None:
    assert WORKFLOW_PATH.is_file(), (
        f"Tag-70 invariant: workflow must live at "
        f"'.github/workflows/ots-pre-anchor-activation-probe.yml' "
        f"(got {WORKFLOW_PATH})"
    )


def test_02_workflow_yaml_parses(workflow_doc: dict) -> None:
    # Bool-True is YAML 1.1 sugar for ``on:`` — accept either form.
    assert "jobs" in workflow_doc, "workflow must have a 'jobs' key"
    assert ("on" in workflow_doc) or (True in workflow_doc), (
        "workflow must have an 'on:' trigger block"
    )


def test_03_exactly_one_probe_job(probe_job: dict) -> None:
    assert probe_job.get("runs-on") == "ubuntu-latest"
    assert probe_job.get("name") == "OTS Pre-Anchor Activation Probe (Tag-59)"


def test_04_install_pytest_step_present(step_names: list[str]) -> None:
    matches = [n for n in step_names if n.lower().startswith("install pytest")]
    assert len(matches) == 1, (
        f"Tag-70 fix marker missing: expected exactly one step whose name "
        f"starts with 'Install pytest', got {matches!r} in {step_names!r}"
    )


def test_05_install_pytest_step_ordered_correctly(probe_job: dict) -> None:
    steps = probe_job["steps"]
    names = [s.get("name", "") for s in steps]
    setup_idx = next(
        (i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith(
            "actions/setup-python@"
        )),
        -1,
    )
    install_idx = next(
        (i for i, n in enumerate(names) if n.lower().startswith("install pytest")),
        -1,
    )
    test_step_idx = next(
        (i for i, n in enumerate(names) if n == "Run hermetic Tag-59 test-suite"),
        -1,
    )
    assert setup_idx >= 0, "missing actions/setup-python step"
    assert install_idx >= 0, "missing Install pytest step"
    assert test_step_idx >= 0, "missing 'Run hermetic Tag-59 test-suite' step"
    assert setup_idx < install_idx < test_step_idx, (
        f"ordering invariant violated: setup-python @ {setup_idx}, "
        f"install-pytest @ {install_idx}, test-step @ {test_step_idx}"
    )


def test_06_pytest_version_pin(probe_job: dict) -> None:
    steps = probe_job["steps"]
    install_step = next(
        s for s in steps if s.get("name", "").lower().startswith("install pytest")
    )
    run_body = install_step.get("run", "")
    assert "pytest>=7,<9" in run_body, (
        "Tag-70 invariant: pytest must be pinned to '>=7,<9' "
        "(prevents unannounced major-version drift). "
        f"run-body was:\n{run_body}"
    )
    assert "PyYAML>=6,<7" in run_body, (
        "Tag-70 invariant: PyYAML must be pinned to '>=6,<7' "
        "(Tag-59 test-suite imports yaml; PyYAML is non-stdlib). "
        f"run-body was:\n{run_body}"
    )
    # Hard guard against unbounded install.
    assert re.search(r"pip install\s+pytest\s*$", run_body, re.MULTILINE) is None, (
        "Tag-70 invariant: no unbounded 'pip install pytest' line "
        "(version range must be quoted)"
    )


def test_07_install_pytest_upgrades_pip(probe_job: dict) -> None:
    steps = probe_job["steps"]
    install_step = next(
        s for s in steps if s.get("name", "").lower().startswith("install pytest")
    )
    run_body = install_step.get("run", "")
    assert "pip install --upgrade pip" in run_body, (
        "Tag-70 hygiene: install-step must upgrade pip first for a "
        "deterministic resolver baseline"
    )
    assert "python3 -m pytest --version" in run_body, (
        "Tag-70 hygiene: install-step must self-verify by printing "
        "pytest --version (smoke-evidence in the workflow log)"
    )
    assert "import yaml" in run_body and "yaml.__version__" in run_body, (
        "Tag-70 hygiene: install-step must self-verify PyYAML by "
        "printing yaml.__version__ (smoke-evidence in the workflow log)"
    )


def test_08_bug_target_line_preserved(probe_job: dict) -> None:
    steps = probe_job["steps"]
    test_step = next(
        s for s in steps if s.get("name") == "Run hermetic Tag-59 test-suite"
    )
    run_body = test_step.get("run", "")
    expected = (
        "python3 -m pytest "
        "tests/ci/test_ots_pre_anchor_activation_probe_tag59.py -v"
    )
    assert expected in run_body, (
        f"Tag-70 minimal-fix invariant: the bug-target call shape "
        f"{expected!r} must be preserved verbatim — fix must NOT refactor "
        f"the call. Got:\n{run_body}"
    )


def test_09_stages_remain_stdlib_only(probe_job: dict) -> None:
    steps = probe_job["steps"]
    stage_steps = [
        s for s in steps if str(s.get("name", "")).startswith("Stage ")
    ]
    assert stage_steps, "expected at least one 'Stage N — ...' step"
    for s in stage_steps:
        body = s.get("run", "") or ""
        assert "pip install" not in body, (
            f"Tag-70 hygiene: stage step {s.get('name')!r} must remain "
            f"stdlib-only (no pip install in body)"
        )
        assert "import pytest" not in body, (
            f"Tag-70 hygiene: stage step {s.get('name')!r} must not "
            f"import pytest"
        )


def test_10_permissions_unchanged(workflow_doc: dict) -> None:
    perms = workflow_doc.get("permissions")
    assert perms == {"contents": "read"}, (
        f"Tag-70 invariant: permissions block must remain "
        f"{{contents: read}} (least-privilege). Got {perms!r}"
    )


def test_11_workflow_self_path_filter(workflow_doc: dict) -> None:
    trigger_block = workflow_doc.get("on", workflow_doc.get(True))
    assert isinstance(trigger_block, dict), "'on:' block must be a mapping"
    self_path = ".github/workflows/ots-pre-anchor-activation-probe.yml"
    push_paths = trigger_block.get("push", {}).get("paths", []) or []
    pr_paths = trigger_block.get("pull_request", {}).get("paths", []) or []
    assert self_path in push_paths, (
        f"Tag-70 invariant: workflow must self-trigger on push when "
        f"'{self_path}' changes (otherwise this very fix never re-runs)"
    )
    assert self_path in pr_paths, (
        f"Tag-70 invariant: workflow must self-trigger on pull_request "
        f"when '{self_path}' changes"
    )


# REUSE-IgnoreStart
def test_12_workflow_is_reuse_compliant(workflow_text: str) -> None:
    head = "\n".join(workflow_text.splitlines()[:4])
    marker = "SPDX-" + "License-Identifier: Apache-2.0"
    assert marker in head, (
        "REUSE: workflow must declare the SPDX license identifier "
        "(Apache-2.0) in the first 4 lines"
    )
# REUSE-IgnoreEnd


def test_13_test_suite_is_hermetic() -> None:
    src = TEST_FILE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    banned = {
        "urllib",
        "urllib.request",
        "urllib3",
        "requests",
        "httpx",
        "socket",
        "http.client",
    }
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                seen.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                seen.add(node.module.split(".")[0])
    leaks = seen & banned
    assert not leaks, (
        f"Tag-70 hermetic invariant: test-suite imports network-I/O "
        f"modules {leaks!r}"
    )
