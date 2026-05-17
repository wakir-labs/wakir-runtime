# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic workflow-structure tests for the Tag-32 Mini-Welle
ADR-0066 Welle-4-7 image-build bundle.

Workflows under test:

  * ``.github/workflows/build-rust-cli-state-backing.yml``
    (ADR-0066 Welle-4 ``state_backing`` pre-cutover image)
  * ``.github/workflows/build-rust-cli-lifecycle-state-machine.yml``
    (ADR-0066 Welle-5 ``lifecycle_state_machine`` pre-cutover image)
  * ``.github/workflows/build-rust-cli-subscribe-loop.yml``
    (ADR-0066 Welle-6 ``subscribe_loop`` pre-cutover image)
  * ``.github/workflows/build-rust-cli-recovery-workflow.yml``
    (ADR-0066 Welle-7 ``recovery_workflow`` pre-cutover image)

These tests assert the workflow STRUCTURE remains correct, so a
future edit that drops a required step (or relaxes the substrate-
fence) regresses with a clear hermetic-test failure rather than a
silent supply-chain provenance drift. Parity with the Tag-26 V907-
verify test surface (PR #194) and Tag-29 SVID-workload-identity
test surface (PR #201).

Sandbox boundary
----------------
Tests parse YAML on disk only. No actions runner, no GHCR egress,
no cargo exec, no cosign exec. Compatible with the claude-dev
sandbox.

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
  nonroot user, ENTRYPOINT targets the binary).
- Cosign-Policy + Quadlet inventory cross-substrate parity: the four
  new standalone-image entries appear in both files in lock-step.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


# ----------------------------------------------------------------------
# Per-welle fixture matrix
# ----------------------------------------------------------------------
#
# Each welle has the same shape: a workflow YAML + a Containerfile + a
# Rust crate + an in-image binary name + a Containerfile parent dir.
# The matrix is the single source of truth the parameterised tests
# iterate over.

WELLE_MATRIX = [
    # welle_id, workflow_name, crate_dir, containerfile_dir, binary_name
    (
        "welle-4",
        "build-rust-cli-state-backing",
        "persona-engine-state-backing",
        "state-backing-rust-cli",
        "wakir-persona-engine-state-backing",
    ),
    (
        "welle-5",
        "build-rust-cli-lifecycle-state-machine",
        "persona-engine-fsm",
        "lifecycle-state-machine-rust-cli",
        "wakir-persona-engine-lifecycle-state-machine",
    ),
    (
        "welle-6",
        "build-rust-cli-subscribe-loop",
        "persona-engine-subscribe-loop",
        "subscribe-loop-rust-cli",
        "wakir-persona-engine-subscribe-loop",
    ),
    (
        "welle-7",
        "build-rust-cli-recovery-workflow",
        "persona-engine-recovery",
        "recovery-workflow-rust-cli",
        "wakir-persona-engine-recovery-workflow",
    ),
]


@pytest.fixture(
    params=WELLE_MATRIX,
    ids=[m[0] for m in WELLE_MATRIX],
)
def welle(request) -> dict:
    welle_id, workflow_name, crate_dir, containerfile_dir, binary_name = (
        request.param
    )
    workflow_path = (
        REPO_ROOT / ".github" / "workflows" / f"{workflow_name}.yml"
    )
    containerfile_path = (
        REPO_ROOT / "infra" / containerfile_dir / "Containerfile"
    )
    return {
        "welle_id": welle_id,
        "workflow_name": workflow_name,
        "crate_dir": crate_dir,
        "containerfile_dir": containerfile_dir,
        "binary_name": binary_name,
        "workflow_path": workflow_path,
        "containerfile_path": containerfile_path,
    }


@pytest.fixture
def workflow_text(welle: dict) -> str:
    p = welle["workflow_path"]
    assert p.is_file(), f"missing workflow: {p}"
    return p.read_text(encoding="utf-8")


@pytest.fixture
def workflow_yaml(workflow_text: str) -> dict:
    # YAML parses the leading ``on:`` mapping key as boolean True;
    # safe_load is sufficient because we only inspect ``jobs`` +
    # ``permissions`` + ``name``.
    return yaml.safe_load(workflow_text)


@pytest.fixture
def build_steps(workflow_yaml: dict) -> list[dict]:
    jobs = workflow_yaml.get("jobs", {})
    build = jobs.get("build")
    assert build is not None, "workflow missing 'build' job"
    steps = build.get("steps")
    assert isinstance(steps, list) and steps, "build job has no steps"
    return steps


@pytest.fixture
def on_block(workflow_yaml: dict) -> dict:
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
# Trigger-surface invariants  (4 welle × 4 trigger tests = 16 tests)
# ======================================================================


def test_workflow_name(welle: dict, workflow_yaml: dict) -> None:
    assert workflow_yaml.get("name") == welle["workflow_name"], (
        f"workflow name mismatch for {welle['welle_id']}"
    )


def test_trigger_has_push_and_workflow_dispatch(on_block: dict) -> None:
    # Hybrid trigger: push-to-main (substrate-CI dry-run) +
    # workflow_dispatch (Operator-Hand publish).
    assert "push" in on_block, "missing push trigger"
    assert "workflow_dispatch" in on_block, "missing workflow_dispatch trigger"


def test_push_trigger_main_only(on_block: dict) -> None:
    push = on_block["push"]
    assert push.get("branches") == ["main"], (
        "push trigger must be main-only — substrate-CI dry-run posture"
    )


def test_push_trigger_path_filtered(welle: dict, on_block: dict) -> None:
    push = on_block["push"]
    paths = push.get("paths")
    assert isinstance(paths, list) and paths, (
        "push trigger must be path-filtered"
    )
    assert any(welle["crate_dir"] in p for p in paths), (
        f"push trigger must include the {welle['crate_dir']} crate path"
    )
    assert any(
        f"{welle['containerfile_dir']}/Containerfile" in p for p in paths
    ), f"push trigger must include the {welle['welle_id']} Containerfile path"


def test_workflow_dispatch_push_default_false(on_block: dict) -> None:
    wd = on_block["workflow_dispatch"]
    inputs = wd.get("inputs", {})
    assert "push" in inputs, "workflow_dispatch must accept push input"
    assert inputs["push"].get("default") == "false", (
        "workflow_dispatch push input default must be 'false' "
        "(Operator-Hand opt-in)"
    )


# ======================================================================
# Permission-scope invariants — least-privilege posture
# ======================================================================


def test_permissions_least_privilege(workflow_yaml: dict) -> None:
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


def test_cargo_build_targets_crate_and_binary(
    welle: dict, build_steps: list[dict]
) -> None:
    idx = _step_index(
        build_steps, "Cargo build (substrate-CI smoke, --release)"
    )
    run = build_steps[idx].get("run", "")
    assert "cargo build --release" in run, (
        "cargo build must use --release"
    )
    assert f"-p {welle['crate_dir']}" in run, (
        f"cargo build must target the {welle['crate_dir']} crate explicitly"
    )
    assert f"--bin {welle['binary_name']}" in run, (
        f"cargo build must target the {welle['binary_name']} binary explicitly"
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
    # Order MUST be: Push → Cosign login → Sigstore sign.
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
    # The buildah build step itself MUST run unconditionally.
    idx = _step_index(build_steps, "Build image with buildah")
    cond = build_steps[idx].get("if")
    assert cond is None, (
        "Build image with buildah must be unconditional (substrate-CI "
        "lane needs to verify the Containerfile actually builds)"
    )


# ======================================================================
# Digest-artefact invariants
# ======================================================================


def test_digest_artifact_upload_conditional(
    welle: dict, build_steps: list[dict]
) -> None:
    idx = _step_index(build_steps, "Upload digest artifact")
    cond = build_steps[idx].get("if", "")
    assert "push == 'true'" in cond, (
        "digest artefact upload must only fire on the publish path"
    )
    uses = build_steps[idx].get("uses", "")
    assert uses.startswith("actions/upload-artifact@v4"), (
        "digest artefact upload must use actions/upload-artifact@v4"
    )
    name = build_steps[idx].get("with", {}).get("name", "")
    assert name == f"{welle['binary_name']}-digest", (
        f"digest artefact name must be {welle['binary_name']}-digest, "
        f"got {name!r}"
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


def test_containerfile_present_on_disk(welle: dict) -> None:
    p = welle["containerfile_path"]
    assert p.is_file(), f"missing Containerfile: {p}"


def test_containerfile_has_two_stage_build(welle: dict) -> None:
    txt = welle["containerfile_path"].read_text(encoding="utf-8")
    from_lines = [l for l in txt.splitlines() if l.startswith("FROM ")]
    assert len(from_lines) == 2, (
        f"Containerfile must have exactly 2 FROM lines (builder + "
        f"runtime), got {len(from_lines)}: {from_lines}"
    )


def test_containerfile_runtime_is_distroless(welle: dict) -> None:
    txt = welle["containerfile_path"].read_text(encoding="utf-8")
    assert "gcr.io/distroless/cc-debian12:nonroot" in txt, (
        "Containerfile runtime stage must be distroless-cc-debian12:nonroot"
    )


def test_containerfile_drops_root_in_runtime(welle: dict) -> None:
    txt = welle["containerfile_path"].read_text(encoding="utf-8")
    assert "USER nonroot:nonroot" in txt, (
        "Containerfile runtime must run as the distroless nonroot user"
    )


def test_containerfile_entrypoint_targets_binary(welle: dict) -> None:
    txt = welle["containerfile_path"].read_text(encoding="utf-8")
    expected = f'ENTRYPOINT ["/usr/local/bin/{welle["binary_name"]}"]'
    assert expected in txt, (
        f"Containerfile ENTRYPOINT must target the canonical in-image "
        f"binary path /usr/local/bin/{welle['binary_name']}"
    )


# ======================================================================
# Cosign-Policy + Quadlet cross-substrate parity (single, non-
# parameterised tests; assert the four standalone-image entries
# land in both files in lock-step)
# ======================================================================


COSIGN_POLICY = REPO_ROOT / "policies" / "cosign-policy-phase-3b.yaml"
QUADLET_INSTALLER = REPO_ROOT / "quadlet" / "wakir-rust-cli.container"


@pytest.fixture(scope="module")
def cosign_policy_yaml() -> dict:
    return yaml.safe_load(COSIGN_POLICY.read_text(encoding="utf-8"))


def test_cosign_policy_has_standalone_images_block(
    cosign_policy_yaml: dict,
) -> None:
    standalone = cosign_policy_yaml.get("standalone_images")
    assert isinstance(standalone, list), (
        "cosign-policy must have a top-level `standalone_images` list "
        "for the Tag-32 Welle-4-7 image-build bundle"
    )
    assert len(standalone) == 4, (
        f"standalone_images must have exactly 4 entries "
        f"(Welle-4-7), got {len(standalone)}"
    )


def test_cosign_policy_standalone_image_welle_ids(
    cosign_policy_yaml: dict,
) -> None:
    standalone = cosign_policy_yaml["standalone_images"]
    welle_ids = sorted(entry["welle_id"] for entry in standalone)
    assert welle_ids == ["welle-4", "welle-5", "welle-6", "welle-7"], (
        f"standalone_images must cover Welle-4 through Welle-7, "
        f"got {welle_ids}"
    )


def test_cosign_policy_standalone_image_digest_placeholders(
    cosign_policy_yaml: dict,
) -> None:
    # Each standalone-image entry must declare the canonical placeholder
    # ``sha256:DIGEST_PENDING_KAI_CROSS_REVIEW`` digest slot — pinned
    # via the resolve-image-pins-ci.yml workflow Operator-Hand
    # after the Sigstore-keyless signature lands.
    standalone = cosign_policy_yaml["standalone_images"]
    for entry in standalone:
        assert (
            entry["expected_image_digest"]
            == "sha256:DIGEST_PENDING_KAI_CROSS_REVIEW"
        ), (
            f"standalone-image {entry['name']} must declare the canonical "
            f"DIGEST_PENDING_KAI_CROSS_REVIEW placeholder, got "
            f"{entry['expected_image_digest']!r}"
        )


def test_cosign_policy_standalone_image_build_workflows_exist(
    cosign_policy_yaml: dict,
) -> None:
    # Each standalone-image entry's ``build_workflow`` path must point
    # to a workflow that actually exists on disk in this PR.
    standalone = cosign_policy_yaml["standalone_images"]
    for entry in standalone:
        wf = REPO_ROOT / entry["build_workflow"]
        assert wf.is_file(), (
            f"standalone-image {entry['name']} declares build_workflow "
            f"{entry['build_workflow']} that does not exist on disk"
        )


def test_cosign_policy_standalone_image_containerfiles_exist(
    cosign_policy_yaml: dict,
) -> None:
    standalone = cosign_policy_yaml["standalone_images"]
    for entry in standalone:
        cf = REPO_ROOT / entry["containerfile"]
        assert cf.is_file(), (
            f"standalone-image {entry['name']} declares containerfile "
            f"{entry['containerfile']} that does not exist on disk"
        )


def test_quadlet_installer_describes_twelve_binaries() -> None:
    txt = QUADLET_INSTALLER.read_text(encoding="utf-8")
    assert "Twelve binaries installed" in txt, (
        "Quadlet installer must declare 12 binaries (Tag-32 update)"
    )
    assert "12 binaries" in txt, (
        "Quadlet [Unit] Description must mention `12 binaries`"
    )


def test_quadlet_installer_includes_welle_4_7_aliases() -> None:
    txt = QUADLET_INSTALLER.read_text(encoding="utf-8")
    # The four standalone-image binary-name aliases the Tag-32 update
    # adds: state-backing-welle4 (alias to existing carrier),
    # lifecycle-state-machine (new name for fsm), subscribe-loop-welle6
    # (alias to existing carrier), recovery-workflow (new name for
    # recovery).
    for alias in [
        "wakir-persona-engine-state-backing-welle4",
        "wakir-persona-engine-lifecycle-state-machine",
        "wakir-persona-engine-subscribe-loop-welle6",
        "wakir-persona-engine-recovery-workflow",
    ]:
        assert alias in txt, (
            f"Quadlet installer must reference Welle-4-7 alias {alias}"
        )


def test_quadlet_installer_for_loop_still_eight_originals() -> None:
    # The 8 pre-Tag-32 carrier-image binaries must still be the
    # for-loop body (the 4 new aliases are installed via explicit
    # `install` invocations after the loop). Regression-guard against
    # someone accidentally adding the alias names to the for-loop
    # itself, which would fail at runtime when the carrier image does
    # not contain those binaries directly.
    txt = QUADLET_INSTALLER.read_text(encoding="utf-8")
    for original in [
        "wakir-persona-engine-recovery",
        "wakir-persona-engine-state-backing",
        "wakir-persona-engine-fsm",
        "wakir-persona-engine-v907-verify",
        "wakir-persona-engine-bridge-diff",
        "wakir-persona-engine-subscribe-loop",
        "wakir-persona-engine-anchor-emitter",
        "wakir-persona-engine-svid-workload-identity",
    ]:
        assert original in txt, (
            f"Quadlet installer regressed: missing pre-Tag-32 binary {original}"
        )


def test_cross_substrate_parity_cosign_and_quadlet_welle_4_7() -> None:
    # The four Tag-32 standalone-image binary names listed in the
    # cosign-policy ``standalone_images`` block must each appear in
    # the Quadlet installer file (either as a direct install target
    # or as an alias). This is the cross-substrate-parity gate the
    # Sprint-Auftrag requires.
    cosign_yaml = yaml.safe_load(
        COSIGN_POLICY.read_text(encoding="utf-8")
    )
    quadlet_txt = QUADLET_INSTALLER.read_text(encoding="utf-8")
    for entry in cosign_yaml["standalone_images"]:
        binary = entry["binary_name"]
        assert binary in quadlet_txt, (
            f"cross-substrate parity violated: standalone-image "
            f"binary {binary} listed in cosign-policy but not in "
            f"Quadlet installer"
        )
