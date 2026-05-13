# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic workflow-structure tests for
``.github/workflows/build-wakir-provisioner.yml``.

Phase-2 Sprint-9 Tag-5 CI-hygiene: three consecutive live Operator-
Hand runs of the build workflow failed at the Sigstore-keyless sign
step with ``UNAUTHORIZED: unauthenticated``. Root cause: the buildah
login step authenticated the buildah client only; cosign carried no
GHCR credentials when it tried to push the signature blob.

The fix is an explicit ``cosign login`` step inserted between the
push and the sign step (see ``docs/ci-cosign-ghcr-auth.md`` for the
full diagnosis).

These tests assert the workflow STRUCTURE remains correct, so a
future edit that drops the cosign-login step (or re-orders it past
the sign step) regresses with a clear hermetic-test failure rather
than another live-run UNAUTHORIZED error.

Sandbox boundary: tests parse YAML on disk only. No actions runner,
no GHCR egress, no cosign exec.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-wakir-provisioner.yml"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW.is_file(), f"missing workflow: {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_yaml(workflow_text: str) -> dict:
    # The workflow has a leading ``on:`` mapping key that YAML parses
    # as boolean True; using ``yaml.safe_load`` is fine for our
    # purposes because we only introspect the ``jobs`` subtree.
    return yaml.safe_load(workflow_text)


@pytest.fixture(scope="module")
def build_steps(workflow_yaml: dict) -> list[dict]:
    jobs = workflow_yaml.get("jobs", {})
    build = jobs.get("build")
    assert build is not None, "workflow missing 'build' job"
    steps = build.get("steps")
    assert isinstance(steps, list) and steps, "build job has no steps"
    return steps


# ----------------------------------------------------------------------
# Permission scope invariants — least-privilege posture.
# ----------------------------------------------------------------------

def test_permissions_block_present(workflow_yaml: dict) -> None:
    perms = workflow_yaml.get("permissions")
    assert isinstance(perms, dict), "workflow must declare top-level permissions"


def test_permissions_contents_read(workflow_yaml: dict) -> None:
    assert workflow_yaml["permissions"].get("contents") == "read"


def test_permissions_packages_write(workflow_yaml: dict) -> None:
    # Required for buildah push AND for cosign signature push.
    assert workflow_yaml["permissions"].get("packages") == "write"


def test_permissions_id_token_write(workflow_yaml: dict) -> None:
    # Required for Sigstore-keyless OIDC token mint (cosign sign).
    assert workflow_yaml["permissions"].get("id-token") == "write"


def test_no_extra_permission_scopes(workflow_yaml: dict) -> None:
    # Least-privilege regression guard: refuse drift to broader
    # scopes like ``actions: write`` or ``security-events: write``.
    allowed = {"contents", "packages", "id-token"}
    actual = set(workflow_yaml["permissions"].keys())
    extra = actual - allowed
    assert not extra, f"unexpected permission scopes: {sorted(extra)}"


# ----------------------------------------------------------------------
# Cosign-login step invariants — Sprint-9 Tag-5 fix anchor.
# ----------------------------------------------------------------------

def _step_index(steps: list[dict], name: str) -> int:
    for i, s in enumerate(steps):
        if s.get("name") == name:
            return i
    raise AssertionError(f"step not found: {name!r}")


def test_cosign_login_step_present(build_steps: list[dict]) -> None:
    # The fix step that closes the UNAUTHORIZED gap.
    _step_index(build_steps, "Cosign login to GHCR")


def test_cosign_login_runs_before_sign(build_steps: list[dict]) -> None:
    login_idx = _step_index(build_steps, "Cosign login to GHCR")
    sign_idx = _step_index(build_steps, "Sigstore-keyless sign")
    assert login_idx < sign_idx, (
        "Cosign login MUST precede Sigstore-keyless sign; reordering "
        "regresses the Sprint-9 Tag-5 UNAUTHORIZED fix"
    )


def test_cosign_login_runs_after_push(build_steps: list[dict]) -> None:
    # No point in logging in before there's an image to sign.
    login_idx = _step_index(build_steps, "Cosign login to GHCR")
    push_idx = _step_index(build_steps, "Push to GHCR")
    assert push_idx < login_idx


def test_cosign_login_gated_by_push_input(build_steps: list[dict]) -> None:
    step = build_steps[_step_index(build_steps, "Cosign login to GHCR")]
    cond = step.get("if", "")
    assert "github.event.inputs.push" in cond and "true" in cond, (
        "Cosign login MUST be gated the same as Push / Sign "
        "(dry-run build must not attempt a real GHCR auth)"
    )


def test_cosign_login_uses_password_stdin(build_steps: list[dict]) -> None:
    # Refuse inline-password leakage to the run log.
    step = build_steps[_step_index(build_steps, "Cosign login to GHCR")]
    run = step.get("run", "")
    assert "--password-stdin" in run, (
        "cosign login MUST use --password-stdin; inline -p leaks the "
        "GITHUB_TOKEN into the workflow log"
    )
    # No raw ``-p`` or ``--password`` followed by anything other than
    # ``-stdin``.
    assert not re.search(r"\s-p\s", run), \
        "cosign login uses raw -p flag — would leak credential"
    assert not re.search(r"--password\s", run), \
        "cosign login uses inline --password — would leak credential"


def test_cosign_login_uses_github_token(build_steps: list[dict]) -> None:
    step = build_steps[_step_index(build_steps, "Cosign login to GHCR")]
    env = step.get("env", {}) or {}
    run = step.get("run", "")
    # Either via env (preferred — keeps the token off the run script
    # body) or via direct expansion. We accept both, refuse neither.
    token_in_env = any(
        "secrets.GITHUB_TOKEN" in str(v) for v in env.values()
    )
    token_in_run = "secrets.GITHUB_TOKEN" in run
    assert token_in_env or token_in_run, (
        "Cosign login must pass secrets.GITHUB_TOKEN (env-preferred)"
    )


def test_cosign_login_uses_github_actor(build_steps: list[dict]) -> None:
    step = build_steps[_step_index(build_steps, "Cosign login to GHCR")]
    run = step.get("run", "")
    assert "github.actor" in run


def test_cosign_login_targets_ghcr(build_steps: list[dict]) -> None:
    step = build_steps[_step_index(build_steps, "Cosign login to GHCR")]
    run = step.get("run", "")
    assert "cosign login ghcr.io" in run, (
        "Cosign login must target ghcr.io explicitly"
    )


# ----------------------------------------------------------------------
# Sign-step invariants — guard against drift away from --yes.
# ----------------------------------------------------------------------

def test_sign_step_uses_yes_flag(build_steps: list[dict]) -> None:
    step = build_steps[_step_index(build_steps, "Sigstore-keyless sign")]
    run = step.get("run", "")
    # ``cosign sign --yes`` skips the interactive consent prompt for
    # the Sigstore TOS; without it the sign step blocks forever in
    # a non-tty CI environment.
    assert "cosign sign --yes" in run or "cosign sign  --yes" in run


def test_sign_step_gated_by_push_input(build_steps: list[dict]) -> None:
    step = build_steps[_step_index(build_steps, "Sigstore-keyless sign")]
    cond = step.get("if", "")
    assert "github.event.inputs.push" in cond and "true" in cond


# ----------------------------------------------------------------------
# Docs cross-reference — keep the diagnosis discoverable.
# ----------------------------------------------------------------------

def test_workflow_references_diagnosis_doc(workflow_text: str) -> None:
    assert "docs/ci-cosign-ghcr-auth.md" in workflow_text, (
        "Workflow should reference the cosign-ghcr-auth diagnosis "
        "doc in a comment so the next editor finds it"
    )


def test_diagnosis_doc_present() -> None:
    doc = REPO_ROOT / "docs" / "ci-cosign-ghcr-auth.md"
    assert doc.is_file(), f"missing diagnosis doc: {doc}"
    text = doc.read_text(encoding="utf-8")
    # Sanity: doc must explain the UNAUTHORIZED symptom verbatim.
    assert "UNAUTHORIZED" in text
    assert "cosign login" in text
