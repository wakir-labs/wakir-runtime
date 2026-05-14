# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic YAML validation for `e2e-vm-acceptance-gate.yml` (Tag-6).

Background
----------
The Sprint-9 Tag-5 workflow ``e2e-vm-acceptance-gate.yml`` was
introduced via PR #38 and then surfaced a 0-job-instant-failure
pattern on every push and PR. Cause: YAML 1.1's reserved-word
resolver treats bare ``on``, ``off``, ``yes``, ``no``, ``y``, ``n``
(and their case variants) as booleans. A bare ``on:`` key therefore
collapses to the boolean ``True`` instead of the string ``"on"``,
which means the trigger map is silently dropped and the workflow
runs with no jobs.

GitHub Actions normally tolerates this via a custom parser, but
the platform-side strict validator surfaces it as the observed
0-job pattern. The fix is to quote the key (``"on":``) so YAML 1.1
strict resolution produces a string.

Coverage
--------
* The workflow YAML parses cleanly under PyYAML's safe_load.
* The top-level key set contains the string ``"on"`` (NOT the
  boolean ``True``).
* The ``on`` map contains the expected triggers (``push``,
  ``pull_request``, ``workflow_dispatch``).
* The two jobs (``harness-logic``, ``real-vm``) are defined with
  the expected ``runs-on`` and ``needs`` topology.
* The ``real-vm`` job is correctly gated on
  ``workflow_dispatch + run_real_vm == 'true'``.

Sandbox boundary: pure-Python static-analysis of a checked-in YAML
file. No GitHub API call, no live runner.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "e2e-vm-acceptance-gate.yml"


def _load() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_yaml_parses() -> None:
    """The file must be valid YAML 1.1/1.2 under safe_load."""
    doc = _load()
    assert isinstance(doc, dict), f"top-level is not a mapping: {type(doc)}"


def test_top_level_on_key_is_string_not_boolean() -> None:
    """The `on:` key MUST be the string ``"on"``, not boolean True.

    This is the Bug E2E regression-pin: if anyone removes the quotes
    around ``"on":`` the YAML resolver will produce a Boolean key and
    this assertion fires. The 0-jobs workflow failure on GitHub
    Actions is the live consequence of the same regression.
    """
    doc = _load()
    keys = list(doc.keys())
    assert "on" in keys, (
        f"workflow YAML missing string `on` key; keys: {keys!r}. "
        "Did the quotes around `\"on\":` get dropped?"
    )
    assert True not in keys, (
        f"workflow YAML resolved `on` as boolean True; keys: {keys!r}. "
        "This is the YAML 1.1 reserved-word collapse — re-quote the key."
    )


def test_on_map_has_expected_triggers() -> None:
    doc = _load()
    on = doc["on"]
    assert isinstance(on, dict)
    assert set(on.keys()) >= {"push", "pull_request", "workflow_dispatch"}


def test_push_trigger_paths_include_smoke_and_bootstrap() -> None:
    """The path-filter must include the substance files we care about."""
    doc = _load()
    push_paths = doc["on"]["push"].get("paths", [])
    assert "bin/proxmox-bringup-smoke" in push_paths
    assert "infra/spire/federation/wakir-pilot-bootstrap.sh" in push_paths
    assert "tests/infra/test_vm_e2e_acceptance_gate.py" in push_paths


def test_pr_trigger_paths_match_push_trigger_paths() -> None:
    """push and pull_request should fire on the same path-filter."""
    doc = _load()
    push_paths = set(doc["on"]["push"].get("paths", []))
    pr_paths = set(doc["on"]["pull_request"].get("paths", []))
    assert push_paths == pr_paths, (
        f"push vs pull_request path-filter divergence:\n"
        f"  push-only: {push_paths - pr_paths}\n"
        f"  pr-only:   {pr_paths - push_paths}"
    )


def test_jobs_topology_is_harness_logic_then_real_vm() -> None:
    doc = _load()
    jobs = doc["jobs"]
    assert set(jobs.keys()) == {"harness-logic", "real-vm"}, list(jobs.keys())

    harness = jobs["harness-logic"]
    assert harness["runs-on"] == "ubuntu-latest"
    # harness-logic must NOT be gated — every PR/push runs it.
    assert "if" not in harness

    real_vm = jobs["real-vm"]
    # real-vm runs on the labelled self-hosted runner.
    runs_on = real_vm["runs-on"]
    if isinstance(runs_on, str):
        labels = [runs_on]
    else:
        labels = list(runs_on)
    assert "self-hosted" in labels
    assert "wakir-nested-kvm" in labels

    # real-vm depends on harness-logic.
    needs = real_vm.get("needs")
    if isinstance(needs, str):
        needs = [needs]
    assert needs == ["harness-logic"]


def test_real_vm_job_is_dispatch_gated() -> None:
    """real-vm must only run on explicit workflow_dispatch + flag.

    A misconfigured gate that auto-runs the real-vm lane on every
    push would burn the self-hosted runner queue and erode the
    acceptance-gate signal. The Sprint-9 Tag-5 design says: real-vm
    is Operator-Hand-triggered only.
    """
    doc = _load()
    real_vm_if = doc["jobs"]["real-vm"].get("if", "")
    assert "workflow_dispatch" in real_vm_if
    assert "run_real_vm" in real_vm_if
    assert "true" in real_vm_if


def test_harness_logic_runs_hermetic_pytest() -> None:
    """The harness-logic job must invoke the hermetic gate test suite."""
    doc = _load()
    steps = doc["jobs"]["harness-logic"]["steps"]
    run_commands = [s.get("run", "") for s in steps if "run" in s]
    # Find the step that invokes `python -m pytest` against the
    # acceptance-gate test file — there may be other `pytest`
    # tokens (e.g. `pip install pytest`) that we must skip.
    runner_step = next(
        (
            cmd for cmd in run_commands
            if "python -m pytest" in cmd or "python3 -m pytest" in cmd
        ),
        None,
    )
    assert runner_step is not None, (
        "harness-logic does not invoke `python -m pytest`; "
        f"commands seen: {run_commands!r}"
    )
    assert "tests/infra/test_vm_e2e_acceptance_gate.py" in runner_step


def test_workflow_does_not_set_global_jobs_permissions_to_write() -> None:
    """Defence-in-depth: the workflow declares read-only contents.

    Both lanes should run with `contents: read` and no write
    permissions; the artefact-upload step uses
    `actions/upload-artifact@v4` which only needs the implicit
    runner write to the actions-cache, not repo-write.
    """
    doc = _load()
    perms = doc.get("permissions", {})
    if isinstance(perms, str):
        # `permissions: read-all` is also fine.
        assert perms in {"read-all", "read"}, perms
        return
    assert perms.get("contents") == "read", perms
    # No accidental `write` grant.
    for key, value in perms.items():
        assert value != "write", (
            f"workflow grants {key}=write at the workflow scope; tighten."
        )
