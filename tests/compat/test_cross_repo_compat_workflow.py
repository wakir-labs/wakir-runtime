# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Pins for ``.github/workflows/cross-repo-compat.yml``.

The job display name is a branch-protection required context; a
rename without a protection update leaves every PR pending forever.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "cross-repo-compat.yml"
DOC = REPO_ROOT / "docs" / "ci" / "branch-protection-required-checks.md"

CHECK_NAME = "cross-repo compatibility (protocol ↔ runtime ↔ verify)"
REMOVED_WORKFLOWS = (
    "cross-repo-drift-audit.yml",
    "cross-repo-drift-allowlist-audit.yml",
)
SHA_PIN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_job_display_name_is_verbatim(workflow):
    names = [job.get("name") for job in workflow["jobs"].values()]
    assert names == [CHECK_NAME]
    assert "↔" in CHECK_NAME  # U+2194 LEFT RIGHT ARROW, GitHub matches literally


def test_triggers_have_no_path_filter(workflow):
    on = workflow[True] if True in workflow else workflow["on"]
    assert "pull_request" in on
    assert "push" in on and on["push"]["branches"] == ["main"]
    for trigger in ("pull_request", "push"):
        assert not (on[trigger] or {}).get("paths"), f"{trigger} must not be path-filtered"
        assert not (on[trigger] or {}).get("paths-ignore")


def test_permissions_are_read_only(workflow):
    assert workflow["permissions"] == {"contents": "read"}


def test_actions_are_pinned_by_commit_sha(workflow):
    uses = [step["uses"] for job in workflow["jobs"].values() for step in job["steps"] if "uses" in step]
    assert uses, "expected at least one `uses:` step"
    for ref in uses:
        assert SHA_PIN.match(ref), f"action not pinned by 40-hex SHA: {ref}"


def test_gate_steps_present(workflow):
    steps = " ".join(step.get("run", "") for job in workflow["jobs"].values() for step in job["steps"])
    assert "wakir-protocol.git" in steps and "wakir-verify.git" in steps
    assert "--depth=1" in steps
    assert "make demo-proof" in steps
    assert "tooling/compat/check_compat.py" in steps
    assert "pytest tests/compat" in steps


def test_replaced_workflows_are_gone():
    for name in REMOVED_WORKFLOWS:
        assert not (WORKFLOW.parent / name).exists(), f"{name} should have been removed"


def test_required_checks_doc_lists_new_context():
    text = DOC.read_text(encoding="utf-8")
    assert f"`{CHECK_NAME}`" in text
    assert "cross-repo-compat.yml" in text
