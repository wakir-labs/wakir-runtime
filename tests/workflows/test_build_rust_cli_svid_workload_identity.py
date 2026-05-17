# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic workflow-structure tests for
``.github/workflows/build-rust-cli-svid-workload-identity.yml``.

Tag-29 Mini-Welle, ADR-0066 Welle-2 pre-cutover image. The workflow
is the substrate that publishes the
``wakir-persona-engine-svid-workload-identity`` Rust-CLI container
image. These tests assert the workflow STRUCTURE remains correct,
so a future edit that drops a required step (or relaxes the
substrate-fence) regresses with a clear hermetic-test failure
rather than a silent supply-chain provenance drift.

Sandbox boundary
----------------
Tests parse YAML on disk only. No actions runner, no GHCR egress,
no cargo exec, no cosign exec. Compatible with the claude-dev
sandbox (no podman-socket needed). Parity with the Tag-26 V907-
verify test surface (PR #194).

Scope of invariants
-------------------
- Trigger surface: push-to-main path-filtered + workflow_dispatch
  with version_tag + push inputs.
- Permission scopes: least-privilege (contents:read, packages:write,
  id-token:write — nothing else).
- Build steps: cargo build (substrate-CI smoke), buildah build,
  conditional push, cosign sign.
- Image tag format: substrate-fence regex on workflow_dispatch
  version_tag input.
- Cosign-signing step ordering: must run AFTER push, AFTER
  cosign-login.
- Digest artefact upload: emitted on push=true.
- No echter Image-Push in CI (the dry-run-on-push-to-main posture).
- Base-layer digest cross-check (skopeo + crane).
- Containerfile invariants (two FROM lines, distroless-cc-debian12,
  nonroot user).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "build-rust-cli-svid-workload-identity.yml"
)
CONTAINERFILE = (
    REPO_ROOT
    / "infra"
    / "svid-workload-identity-rust-cli"
    / "Containerfile"
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW.is_file(), f"missing workflow: {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_yaml(workflow_text: str) -> dict:
    # YAML parses the leading ``on:`` mapping key as boolean True;
    # we only introspect ``jobs`` + ``permissions`` + ``name`` so
    # ``safe_load`` is sufficient.
    return yaml.safe_load(workflow_text)


@pytest.fixture(scope="module")
def build_steps(workflow_yaml: dict) -> list[dict]:
    jobs = workflow_yaml.get("jobs", {})
    build = jobs.get("build")
    assert build is not None, "workflow missing 'build' job"
    steps = build.get("steps")
    assert isinstance(steps, list) and steps, "build job has no steps"
    return steps


@pytest.fixture(scope="module")
def on_block(workflow_yaml: dict) -> dict:
    # YAML safe_load maps the unquoted ``on:`` key to Python's
    # boolean ``True`` (the YAML 1.1 truthy alias). The actual
    # trigger dict is therefore under ``workflow_yaml[True]``.
    block = workflow_yaml.get(True) or workflow_yaml.get("on")
    assert isinstance(block, dict), "workflow missing 'on' trigger block"
    return block


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _step_index(steps: list[dict], name: str) -> int:
    for i, s in enumerate(steps):
        if s.get("name") == name:
            return i
    raise AssertionError(f"step not found: {name!r}")


# ======================================================================
# Trigger-surface invariants
# ======================================================================


def test_workflow_name(workflow_yaml: dict) -> None:
    assert (
        workflow_yaml.get("name")
        == "build-rust-cli-svid-workload-identity"
    )


def test_trigger_has_push_and_workflow_dispatch(on_block: dict) -> None:
    # Hybrid trigger: push-to-main (substrate-CI dry-run) +
    # workflow_dispatch (Operator-Hand publish). Parity with Tag-26
    # V907-verify (PR #194).
    assert "push" in on_block, "missing push trigger"
    assert "workflow_dispatch" in on_block, "missing workflow_dispatch trigger"


def test_push_trigger_main_only(on_block: dict) -> None:
    push = on_block["push"]
    assert push.get("branches") == ["main"], (
        "push trigger must be main-only — substrate-CI dry-run posture"
    )


def test_push_trigger_path_filtered(on_block: dict) -> None:
    push = on_block["push"]
    paths = push.get("paths")
    assert isinstance(paths, list) and paths, (
        "push trigger must be path-filtered"
    )
    # Must include the crate path so changes to the binary or library
    # trigger a substrate-CI rebuild.
    assert any(
        "persona-engine-svid-workload-identity" in p for p in paths
    ), (
        "push trigger must include the svid-workload-identity crate path"
    )
    # Must include the Containerfile so changes to base-layer pins
    # trigger a rebuild.
    assert any(
        "svid-workload-identity-rust-cli/Containerfile" in p for p in paths
    ), "push trigger must include the svid-workload-identity Containerfile path"


def test_workflow_dispatch_push_default_false(on_block: dict) -> None:
    wd = on_block["workflow_dispatch"]
    inputs = wd.get("inputs", {})
    assert "push" in inputs, "workflow_dispatch must accept push input"
    # Default MUST be 'false' — keep the publish path explicit.
    assert inputs["push"].get("default") == "false", (
        "workflow_dispatch push input default must be 'false' "
        "(Operator-Hand opt-in; parity with Tag-26 V907-verify)"
    )


# ======================================================================
# Permission-scope invariants — least-privilege posture
# ======================================================================


def test_permissions_least_privilege(workflow_yaml: dict) -> None:
    # Least-privilege regression guard: refuse drift to broader
    # scopes (actions:write, security-events:write, etc.). Parity
    # with Tag-26 V907-verify least-privilege contract.
    perms = workflow_yaml.get("permissions")
    assert isinstance(perms, dict), (
        "workflow must declare top-level permissions"
    )
    assert perms.get("contents") == "read", (
        "permissions.contents must be 'read' (least-privilege)"
    )
    assert perms.get("packages") == "write", (
        "permissions.packages must be 'write' (buildah push + cosign "
        "signature upload)"
    )
    assert perms.get("id-token") == "write", (
        "permissions.id-token must be 'write' (Sigstore-keyless OIDC)"
    )
    allowed = {"contents", "packages", "id-token"}
    extra = set(perms.keys()) - allowed
    assert not extra, f"unexpected permission scopes: {sorted(extra)}"


# ======================================================================
# Build-step ordering invariants
# ======================================================================


def test_cargo_build_targets_svid_crate_and_binary(
    build_steps: list[dict],
) -> None:
    idx = _step_index(
        build_steps, "Cargo build (substrate-CI smoke, --release)"
    )
    run = build_steps[idx].get("run", "")
    assert "cargo build --release" in run, (
        "cargo build must use --release"
    )
    assert "-p persona-engine-svid-workload-identity" in run, (
        "cargo build must target the svid-workload-identity crate explicitly"
    )
    assert "--bin wakir-persona-engine-svid-workload-identity" in run, (
        "cargo build must target the wakir-persona-engine-svid-"
        "workload-identity binary explicitly"
    )


def test_buildah_after_cargo(build_steps: list[dict]) -> None:
    cargo_idx = _step_index(
        build_steps, "Cargo build (substrate-CI smoke, --release)"
    )
    buildah_idx = _step_index(build_steps, "Build image with buildah")
    assert cargo_idx < buildah_idx, (
        "cargo substrate-CI smoke must run before buildah build"
    )


# ======================================================================
# Cosign-signing invariants
# ======================================================================


def test_cosign_signing_order(build_steps: list[dict]) -> None:
    # Order MUST be: Push → Cosign login → Sigstore sign. The
    # earlier Sprint-9 Tag-5 UNAUTHORIZED regressions came from
    # reordering these.
    push_idx = _step_index(build_steps, "Push to GHCR")
    login_idx = _step_index(build_steps, "Cosign login to GHCR")
    sign_idx = _step_index(build_steps, "Sigstore-keyless sign")
    assert push_idx < login_idx < sign_idx, (
        "Cosign step ordering regressed; must be Push → login → sign"
    )


def test_cosign_installer_present(build_steps: list[dict]) -> None:
    _step_index(build_steps, "Install cosign (Sigstore-keyless)")


# ======================================================================
# Image-tag substrate-fence invariants
# ======================================================================


def test_version_tag_format_fence_present(workflow_text: str) -> None:
    # The "Resolve effective version_tag + push-flag" step must
    # validate workflow_dispatch version_tag against the
    # ``MAJOR.MINOR.PATCH-pilot`` regex (Sprint-Pengine-13 substrate-
    # fence pattern). Searching the raw workflow text is robust
    # against minor YAML reformatting.
    assert (
        "^[0-9]+\\.[0-9]+\\.[0-9]+-pilot$" in workflow_text
    ), "version_tag substrate-fence regex missing"
    assert "exit 64" in workflow_text, (
        "version_tag fence does not exit 64 on drift"
    )


# ======================================================================
# Push-conditional invariants — no echter Image-Push from substrate-CI
# ======================================================================


def test_push_step_conditional(build_steps: list[dict]) -> None:
    # The Push to GHCR step must be guarded by an ``if:`` that
    # references inputs.push == 'true' (via the upstream
    # steps.inputs.outputs.push). No echter Image-Push from
    # substrate-CI.
    idx = _step_index(build_steps, "Push to GHCR")
    cond = build_steps[idx].get("if", "")
    assert "push == 'true'" in cond, (
        "Push to GHCR step must be conditional on push=='true' "
        "(no auto-publish on substrate-CI lane)"
    )


def test_cosign_sign_conditional(build_steps: list[dict]) -> None:
    idx = _step_index(build_steps, "Sigstore-keyless sign")
    cond = build_steps[idx].get("if", "")
    assert "push == 'true'" in cond, (
        "Sigstore sign step must be conditional on push=='true' "
        "(no auto-sign on substrate-CI lane)"
    )


def test_buildah_unconditional(build_steps: list[dict]) -> None:
    # The buildah build step itself MUST run unconditionally (so the
    # substrate-CI lane verifies the Containerfile actually builds).
    idx = _step_index(build_steps, "Build image with buildah")
    cond = build_steps[idx].get("if")
    assert cond is None, (
        "Build image with buildah must be unconditional (substrate-CI "
        "lane needs to verify the Containerfile actually builds)"
    )


# ======================================================================
# Digest-artefact invariants
# ======================================================================


def test_digest_artifact_upload_conditional(build_steps: list[dict]) -> None:
    idx = _step_index(build_steps, "Upload digest artifact")
    cond = build_steps[idx].get("if", "")
    assert "push == 'true'" in cond, (
        "digest artefact upload must only fire on the publish path"
    )
    uses = build_steps[idx].get("uses", "")
    assert uses.startswith("actions/upload-artifact@v4"), (
        "digest artefact upload must use actions/upload-artifact@v4"
    )


# ======================================================================
# Base-layer digest cross-check invariants
# ======================================================================


def test_base_digest_resolvers_present(build_steps: list[dict]) -> None:
    _step_index(
        build_steps, "Resolve rust:1.85-slim-bookworm base-layer digest"
    )
    _step_index(
        build_steps,
        "Resolve distroless/cc-debian12:nonroot base-layer digest",
    )


def test_skopeo_crane_cross_check_in_rust_resolver(
    build_steps: list[dict],
) -> None:
    # The rust base-layer resolver must cross-check skopeo vs crane
    # digests and refuse to proceed if they disagree (registry-
    # inconsistency guard, parity with Tag-26 V907-verify).
    idx = _step_index(
        build_steps, "Resolve rust:1.85-slim-bookworm base-layer digest"
    )
    run = build_steps[idx].get("run", "")
    assert "SKOPEO_DIGEST" in run and "CRANE_DIGEST" in run, (
        "rust base-layer resolver must cross-check skopeo vs crane"
    )
    assert "exit 2" in run, (
        "rust base-layer resolver must exit 2 on skopeo/crane "
        "disagreement"
    )


def test_placeholder_substitution_step_refuses_residue(
    build_steps: list[dict],
) -> None:
    # The "Materialise pinned base-layer digests" step must refuse
    # to proceed if any DIGEST_PENDING_KAI_REVIEW placeholder is
    # left after substitution (substrate-fence parity with Tag-26
    # V907-verify).
    idx = _step_index(
        build_steps,
        "Materialise pinned base-layer digests in Containerfile",
    )
    run = build_steps[idx].get("run", "")
    assert "DIGEST_PENDING_KAI_REVIEW" in run, (
        "substitution step must reference the placeholder sentinel"
    )
    assert "exit 1" in run, (
        "substitution step must exit 1 if any placeholder remains"
    )


# ======================================================================
# Containerfile presence invariants (substrate-cross-check)
# ======================================================================


def test_containerfile_present_on_disk() -> None:
    assert CONTAINERFILE.is_file(), f"missing Containerfile: {CONTAINERFILE}"


def test_containerfile_has_two_stage_build() -> None:
    txt = CONTAINERFILE.read_text(encoding="utf-8")
    from_lines = [l for l in txt.splitlines() if l.startswith("FROM ")]
    assert len(from_lines) == 2, (
        f"Containerfile must have exactly 2 FROM lines (builder + "
        f"runtime), got {len(from_lines)}: {from_lines}"
    )


def test_containerfile_runtime_is_distroless() -> None:
    txt = CONTAINERFILE.read_text(encoding="utf-8")
    assert "gcr.io/distroless/cc-debian12:nonroot" in txt, (
        "Containerfile runtime stage must be distroless-cc-debian12:nonroot"
    )


def test_containerfile_drops_root_in_runtime() -> None:
    txt = CONTAINERFILE.read_text(encoding="utf-8")
    assert "USER nonroot:nonroot" in txt, (
        "Containerfile runtime must run as the distroless nonroot user"
    )


def test_containerfile_entrypoint_targets_svid_binary() -> None:
    txt = CONTAINERFILE.read_text(encoding="utf-8")
    assert (
        'ENTRYPOINT ["/usr/local/bin/wakir-persona-engine-svid-workload-identity"]'
        in txt
    ), (
        "Containerfile ENTRYPOINT must target the canonical in-image "
        "binary path /usr/local/bin/wakir-persona-engine-svid-workload-identity"
    )
