# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic YAML validation for `e2e-vm-acceptance-gate.yml`.

Background
----------
The workflow ``e2e-vm-acceptance-gate.yml`` was
introduced via PR #38 and then surfaced a 0-job-instant-failure
pattern on every push and PR. The GitHub Actions validator annotation
identified two distinct problems we close in this patch:

1. **Real bug** — ``${{ runner.temp }}`` was referenced inside the
   since-withdrawn real-VM job's job-level ``env:`` block. The
   ``runner.*`` context is only valid inside steps and
   ``defaults.run``; at job-level it raises
   ``Unrecognized named-value: 'runner'`` and the validator drops the
   entire workflow definition to 0 jobs. The job that carried the
   defect is gone (see below), but the defect class is not
   job-specific, so the pin below now covers every job in the file.

2. **Hygiene defence** — the bare top-level key ``on:`` is a YAML 1.1
   reserved-word that PyYAML's safe-mode resolver collapses to the
   boolean ``True``. GitHub Actions itself tolerates the bare form
   (YAML 1.2-style), but external linters and any python-yaml-based
   pre-merge check would have flagged it. We quote the key
   (``"on":``) so both resolver-paths agree.

The withdrawn real-VM job
------------------------
The workflow carried a second job that booted a disposable
Fedora-CoreOS VM on a self-hosted runner selected by a nested-KVM
label. Measured on 2026-09-22: no runner in the repository carries
that label, and the repository has no self-hosted runners at all. The
job could therefore never be scheduled — it stood at ``skipping`` on
every pull request while the workflow reported ``success`` from the
hermetic job alone. It was withdrawn under ADR-0077.

The tests that pinned that job's shape are gone with it. What replaces
them is a pin in the other direction: no job in this workflow may
select a self-hosted runner. Re-introducing one is a decision about
infrastructure that must be taken deliberately and with a runner that
exists, not by editing a YAML file back into a shape that grades
nothing.

Coverage
--------
* The workflow YAML parses cleanly under PyYAML's safe_load.
* The top-level key set contains the string ``"on"`` (NOT the
  boolean ``True``).
* The ``on`` map contains the expected triggers (``push``,
  ``pull_request``, ``workflow_dispatch``).
* The job set is exactly ``{harness-logic}``, ungated, on
  ``ubuntu-latest``.
* No job selects a self-hosted runner.
* No job-level ``env:`` block references ``runner.*`` — the
  validator-killing pattern from PR #38 is pinned out for every job,
  not only for the one that once carried it.

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
        f" push-only: {push_paths - pr_paths}\n"
        f" pr-only: {pr_paths - push_paths}"
    )


def test_jobs_topology_is_the_hermetic_lane_only() -> None:
    doc = _load()
    jobs = doc["jobs"]
    assert set(jobs.keys()) == {"harness-logic"}, list(jobs.keys())

    harness = jobs["harness-logic"]
    assert harness["runs-on"] == "ubuntu-latest"
    # harness-logic must NOT be gated — every PR/push runs it.
    assert "if" not in harness


def test_no_job_selects_a_self_hosted_runner() -> None:
    """ADR-0077 pin: this workflow may not schedule onto a runner label.

    The withdrawn real-VM job selected ``[self-hosted, wakir-nested-kvm]``
    and no runner carried that label, so it never ran while the workflow
    reported success from the hermetic job beside it. A job that cannot
    be scheduled does not fail — it waits, and a waiting job under an
    ``if:`` that is false reads as ``skipping``. That is the shape this
    assertion refuses to let back in silently.

    Re-introducing a self-hosted lane is legitimate; doing it needs a
    runner that exists, and then this test is the place where that fact
    is recorded.
    """
    doc = _load()
    offenders: list[str] = []
    for name, job in doc["jobs"].items():
        runs_on = job.get("runs-on")
        labels = [runs_on] if isinstance(runs_on, str) else list(runs_on or [])
        if isinstance(runs_on, dict):
            labels = list(runs_on.get("labels", []))
        if any("self-hosted" in str(label) for label in labels):
            offenders.append(f"{name}: {runs_on!r}")
    assert not offenders, (
        "job(s) select a self-hosted runner, but this repository has no "
        "self-hosted runners (measured 2026-09-22). Such a job cannot be "
        "scheduled and its absence looks like a pass. See ADR-0077:\n  "
        + "\n  ".join(offenders)
    )


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


def test_no_job_level_env_references_runner_context() -> None:
    """Regression-pin: job-level `env:` must not contain `${{ runner.* }}`.

    The validator error from PR #38 was
    ``Unrecognized named-value: 'runner'``, pointing at
    ``${{ runner.temp }}/wakir-e2e`` inside a job-level ``env:``
    block. The ``runner.*`` context is only available inside steps
    and ``defaults.run``; using it at job-level collapses the entire
    workflow definition to 0 jobs — and a workflow with 0 jobs is
    another shape of a gate that grades nothing.

    The job that carried the original defect has been withdrawn under
    ADR-0077. The pin stays and now covers every job in the file,
    because the defect was never a property of that one job.
    """
    doc = _load()
    for job_name, job in doc["jobs"].items():
        job_env = job.get("env", {}) or {}
        for key, value in job_env.items():
            text = str(value)
            assert "runner." not in text, (
                f"{job_name} job-level env.{key} references runner.* "
                f"({value!r}); move this into a step. The validator "
                f"will reject the workflow with "
                f"'Unrecognized named-value: runner' and 0 jobs will run."
            )


def test_workflow_does_not_set_global_jobs_permissions_to_write() -> None:
    """Defence-in-depth: the workflow declares read-only contents.

    The lane runs with `contents: read` and no write permissions.
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
