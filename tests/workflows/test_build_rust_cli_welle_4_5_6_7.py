# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic workflow-structure tests for the four Tag-33 Mini-Welle
build-rust-cli workflows (ADR-0066 Welle-4..7 image-build bundle):

  * ``.github/workflows/build-rust-cli-state-backing.yml`` (Welle-4)
  * ``.github/workflows/build-rust-cli-lifecycle-state-machine.yml``
    (Welle-5)
  * ``.github/workflows/build-rust-cli-subscribe-loop.yml`` (Welle-6)
  * ``.github/workflows/build-rust-cli-recovery-workflow.yml``
    (Welle-7)

Each workflow is the substrate that publishes one of the four
dedicated single-binary Rust-CLI container images for the ADR-0066
Welle-4..7 cutover steps. These tests assert the workflow STRUCTURE
remains correct across all four files in lock-step, so a future edit
that drops a required step (or relaxes the substrate-fence) in ONE
workflow regresses with a clear hermetic-test failure rather than a
silent supply-chain provenance drift in a single Welle.

Sandbox boundary
----------------
Tests parse YAML on disk only. No actions runner, no GHCR egress,
no cargo exec, no cosign exec. Compatible with the claude-dev
sandbox (no podman-socket needed). Parity with the Tag-26 V907-
verify test surface (PR #194), Tag-29 SVID-workload-identity test
surface (PR #201) and Tag-31 bridge-audit-writer test surface
(PR #210).

Scope of invariants (per workflow + cross-workflow)
---------------------------------------------------
- Workflow name matches the file basename.
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
- No real Image-Push in CI (the dry-run-on-push-to-main posture).
- Base-layer digest cross-check (skopeo + crane).
- Containerfile invariants (two FROM lines, distroless-cc-debian12,
  nonroot user).
- Cross-workflow uniformity: all four workflows share the same
  step-name set and the same step ordering.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

# Welle-4..7 workflow + Containerfile + crate + binary mapping. Each
# tuple element is (welle_n, workflow_filename, containerfile_dir,
# crate_path_segment, binary_name).
WELLE_4_7_BUNDLE = [
    (
        4,
        "build-rust-cli-state-backing.yml",
        "state-backing-rust-cli",
        "persona-engine-state-backing",
        "wakir-persona-engine-state-backing",
    ),
    (
        5,
        "build-rust-cli-lifecycle-state-machine.yml",
        "lifecycle-state-machine-rust-cli",
        "persona-engine-fsm",
        "wakir-persona-engine-fsm",
    ),
    (
        6,
        "build-rust-cli-subscribe-loop.yml",
        "subscribe-loop-rust-cli",
        "persona-engine-subscribe-loop",
        "wakir-persona-engine-subscribe-loop",
    ),
    (
        7,
        "build-rust-cli-recovery-workflow.yml",
        "recovery-workflow-rust-cli",
        "persona-engine-recovery",
        "wakir-persona-engine-recovery",
    ),
]


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _load_yaml(filename: str) -> dict:
    workflow_path = REPO_ROOT / ".github" / "workflows" / filename
    assert workflow_path.is_file(), f"missing workflow: {workflow_path}"
    return yaml.safe_load(workflow_path.read_text(encoding="utf-8"))


def _on_block(workflow_yaml: dict) -> dict:
    # YAML safe_load maps the unquoted ``on:`` key to Python's boolean
    # ``True`` (the YAML 1.1 truthy alias). The actual trigger dict is
    # therefore under ``workflow_yaml[True]``.
    block = workflow_yaml.get(True) or workflow_yaml.get("on")
    assert isinstance(block, dict), "workflow missing 'on' trigger block"
    return block


def _build_steps(workflow_yaml: dict) -> list[dict]:
    jobs = workflow_yaml.get("jobs", {})
    build = jobs.get("build")
    assert build is not None, "workflow missing 'build' job"
    steps = build.get("steps")
    assert isinstance(steps, list) and steps, "build job has no steps"
    return steps


def _step_index(steps: list[dict], name: str) -> int:
    for i, s in enumerate(steps):
        if s.get("name") == name:
            return i
    raise AssertionError(f"step not found: {name!r}")


# ======================================================================
# Per-workflow parametrised tests (4 workflows × N invariants)
# ======================================================================


@pytest.mark.parametrize(
    "welle_n,workflow_filename,containerfile_dir,crate_path_segment,binary_name",
    WELLE_4_7_BUNDLE,
    ids=[f"welle-{w}" for w, *_ in WELLE_4_7_BUNDLE],
)
class TestWelle4to7Workflow:
    """Parametrised invariants applied to all four Welle-4..7
    workflows.
    """

    # ------------------------------------------------------------------
    # Trigger-surface invariants
    # ------------------------------------------------------------------

    def test_workflow_name_matches_filename(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        wf = _load_yaml(workflow_filename)
        expected_name = workflow_filename.removesuffix(".yml")
        assert wf.get("name") == expected_name, (
            f"workflow {workflow_filename} name drift: "
            f"expected {expected_name!r}, got {wf.get('name')!r}"
        )

    def test_trigger_has_push_and_workflow_dispatch(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        on = _on_block(_load_yaml(workflow_filename))
        assert "push" in on, "missing push trigger"
        assert (
            "workflow_dispatch" in on
        ), "missing workflow_dispatch trigger"

    def test_push_trigger_main_only(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        on = _on_block(_load_yaml(workflow_filename))
        assert on["push"].get("branches") == ["main"], (
            "push trigger must be main-only — substrate-CI dry-run "
            "posture"
        )

    def test_push_trigger_path_filtered_to_crate(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        on = _on_block(_load_yaml(workflow_filename))
        paths = on["push"].get("paths")
        assert isinstance(paths, list) and paths, (
            "push trigger must be path-filtered"
        )
        assert any(crate_path_segment in p for p in paths), (
            f"push trigger must include the {crate_path_segment} crate "
            f"path; got {paths}"
        )
        assert any(
            f"{containerfile_dir}/Containerfile" in p for p in paths
        ), (
            f"push trigger must include the {containerfile_dir} "
            f"Containerfile path; got {paths}"
        )

    def test_workflow_dispatch_push_default_false(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        on = _on_block(_load_yaml(workflow_filename))
        wd = on["workflow_dispatch"]
        inputs = wd.get("inputs", {})
        assert (
            "push" in inputs
        ), "workflow_dispatch must accept push input"
        assert inputs["push"].get("default") == "false", (
            "workflow_dispatch push input default must be 'false' "
            "(Operator-Hand opt-in)"
        )

    def test_workflow_dispatch_version_tag_default(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        on = _on_block(_load_yaml(workflow_filename))
        wd = on["workflow_dispatch"]
        inputs = wd.get("inputs", {})
        assert (
            "version_tag" in inputs
        ), "workflow_dispatch must accept version_tag input"
        # Default tag is the same MAJOR.MINOR.PATCH-pilot shape across
        # the four Welle workflows for operator-facing predictability.
        assert inputs["version_tag"].get("default") == "0.1.0-pilot", (
            "workflow_dispatch version_tag default must be "
            "'0.1.0-pilot' (parity with prior image-build workflows)"
        )

    # ------------------------------------------------------------------
    # Permission-scope invariants — least-privilege posture
    # ------------------------------------------------------------------

    def test_permissions_least_privilege(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        wf = _load_yaml(workflow_filename)
        perms = wf.get("permissions")
        assert isinstance(
            perms, dict
        ), "workflow must declare top-level permissions"
        assert perms.get("contents") == "read", (
            "permissions.contents must be 'read' (least-privilege)"
        )
        assert perms.get("packages") == "write", (
            "permissions.packages must be 'write' (buildah push + "
            "cosign signature upload)"
        )
        assert perms.get("id-token") == "write", (
            "permissions.id-token must be 'write' (Sigstore-keyless "
            "OIDC)"
        )
        allowed = {"contents", "packages", "id-token"}
        extra = set(perms.keys()) - allowed
        assert not extra, f"unexpected permission scopes: {sorted(extra)}"

    # ------------------------------------------------------------------
    # Build-step ordering invariants
    # ------------------------------------------------------------------

    def test_build_steps_in_order(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        steps = _build_steps(_load_yaml(workflow_filename))
        # The canonical step-name order across all four Welle-4..7
        # workflows (parity with PR #194 + PR #201 + PR #210).
        EXPECTED_STEP_NAMES = [
            "Checkout",
            "Resolve effective version_tag + push-flag",
            "Install Rust toolchain (substrate-CI smoke)",
            "Cargo build (substrate-CI smoke, --release)",
            "Install crane (digest cross-resolver)",
            "Install skopeo + jq",
            "Install cosign (Sigstore-keyless)",
            "Resolve rust:1.85-slim-bookworm base-layer digest",
            "Resolve distroless/cc-debian12:nonroot base-layer digest",
            "Materialise pinned base-layer digests in Containerfile",
            "Build image with buildah",
            "Login to GHCR",
            "Push to GHCR",
            "Cosign login to GHCR",
            "Sigstore-keyless sign",
            "Emit sha256-digest as artifact",
            "Upload digest artifact",
            "Emit workflow summary",
        ]
        observed = [s.get("name") for s in steps]
        for name in EXPECTED_STEP_NAMES:
            assert name in observed, (
                f"required step missing in {workflow_filename}: "
                f"{name!r}"
            )
        # And the relative ordering must match for the steps we
        # require (no re-ordering allowed; the post-push step ordering
        # is supply-chain provenance critical).
        indices = [observed.index(n) for n in EXPECTED_STEP_NAMES]
        assert indices == sorted(indices), (
            f"step ordering drift in {workflow_filename}: "
            f"observed indices {indices}"
        )

    def test_cosign_sign_runs_after_push(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        steps = _build_steps(_load_yaml(workflow_filename))
        push_idx = _step_index(steps, "Push to GHCR")
        sign_idx = _step_index(steps, "Sigstore-keyless sign")
        cosign_login_idx = _step_index(steps, "Cosign login to GHCR")
        assert push_idx < cosign_login_idx, (
            "cosign-login must run AFTER push (we sign the pushed "
            "digest)"
        )
        assert cosign_login_idx < sign_idx, (
            "cosign-sign must run AFTER cosign-login (login provides "
            "the GHCR creds the sign step uses to upload the "
            "signature)"
        )

    def test_buildah_uses_correct_containerfile_path(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        steps = _build_steps(_load_yaml(workflow_filename))
        buildah = steps[_step_index(steps, "Build image with buildah")]
        run = buildah.get("run", "")
        expected_path = f"infra/{containerfile_dir}/Containerfile"
        assert expected_path in run, (
            f"buildah step must reference {expected_path}; got "
            f"step.run={run!r}"
        )

    def test_cargo_build_uses_correct_crate_and_binary(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        steps = _build_steps(_load_yaml(workflow_filename))
        cargo = steps[
            _step_index(
                steps, "Cargo build (substrate-CI smoke, --release)"
            )
        ]
        run = cargo.get("run", "")
        assert f"-p {crate_path_segment}" in run, (
            f"cargo build step must build crate {crate_path_segment}; "
            f"got step.run={run!r}"
        )
        assert f"--bin {binary_name}" in run, (
            f"cargo build step must build binary {binary_name}; got "
            f"step.run={run!r}"
        )

    # ------------------------------------------------------------------
    # Substrate-fence invariants
    # ------------------------------------------------------------------

    def test_version_tag_substrate_fence(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        steps = _build_steps(_load_yaml(workflow_filename))
        gate = steps[
            _step_index(
                steps, "Resolve effective version_tag + push-flag"
            )
        ]
        run = gate.get("run", "")
        # The semver-suffixed substrate-fence regex is the same shape
        # across all four Welle-4..7 workflows (and the prior three
        # image-build workflows). Parity with PR #194 / #201 / #210.
        assert (
            r"^[0-9]+\.[0-9]+\.[0-9]+-pilot$" in run
        ), (
            "version_tag substrate-fence regex missing — must reject "
            "free-form tags on workflow_dispatch"
        )

    def test_base_layer_digest_cross_check(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        steps = _build_steps(_load_yaml(workflow_filename))
        rust_step = steps[
            _step_index(
                steps, "Resolve rust:1.85-slim-bookworm base-layer digest"
            )
        ]
        distroless_step = steps[
            _step_index(
                steps,
                "Resolve distroless/cc-debian12:nonroot base-layer digest",
            )
        ]
        for step, label in (
            (rust_step, "rust"),
            (distroless_step, "distroless"),
        ):
            run = step.get("run", "")
            assert (
                "skopeo inspect" in run
            ), f"{label} digest step must call skopeo inspect"
            assert (
                "crane digest" in run
            ), f"{label} digest step must cross-check with crane"
            assert (
                "exit 2" in run
            ), f"{label} digest step must refuse on skopeo/crane disagreement"

    def test_no_real_image_push_on_push_to_main(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        """The dry-run-on-push-to-main posture: when the workflow is
        triggered by a push to main (not by workflow_dispatch), the
        ``Push to GHCR`` / ``Cosign login`` / ``Sigstore-keyless
        sign`` / ``Emit digest artefact`` / ``Upload digest artefact``
        steps must all be ``if`` -gated on
        ``steps.inputs.outputs.push == 'true'``. A drift here would
        publish an image on every commit, defeating the Operator-
        Hand boundary.
        """
        steps = _build_steps(_load_yaml(workflow_filename))
        for gated_step_name in (
            "Login to GHCR",
            "Push to GHCR",
            "Cosign login to GHCR",
            "Sigstore-keyless sign",
            "Emit sha256-digest as artifact",
            "Upload digest artifact",
        ):
            step = steps[_step_index(steps, gated_step_name)]
            cond = step.get("if", "")
            assert (
                "steps.inputs.outputs.push == 'true'" in cond
            ), (
                f"step {gated_step_name!r} must be if-gated on "
                f"workflow_dispatch push=true; got {cond!r}"
            )


# ======================================================================
# Per-Containerfile invariants
# ======================================================================


@pytest.mark.parametrize(
    "welle_n,workflow_filename,containerfile_dir,crate_path_segment,binary_name",
    WELLE_4_7_BUNDLE,
    ids=[f"welle-{w}-containerfile" for w, *_ in WELLE_4_7_BUNDLE],
)
class TestWelle4to7Containerfile:
    """Parametrised invariants applied to all four Welle-4..7
    Containerfiles.
    """

    def test_containerfile_exists(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        path = REPO_ROOT / "infra" / containerfile_dir / "Containerfile"
        assert path.is_file(), f"Containerfile missing: {path}"

    def test_containerfile_has_two_from_lines(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        path = REPO_ROOT / "infra" / containerfile_dir / "Containerfile"
        text = path.read_text(encoding="utf-8")
        from_lines = [
            line
            for line in text.splitlines()
            if line.strip().startswith("FROM ")
        ]
        assert len(from_lines) == 2, (
            f"{path} must declare exactly 2 FROM lines (builder + "
            f"runtime); found {len(from_lines)}: {from_lines}"
        )

    def test_containerfile_uses_rust_1_85_builder(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        path = REPO_ROOT / "infra" / containerfile_dir / "Containerfile"
        text = path.read_text(encoding="utf-8")
        assert (
            "rust:1.85-slim-bookworm@sha256:DIGEST_PENDING_KAI_REVIEW"
            in text
        ), (
            f"{path} must FROM rust:1.85-slim-bookworm with the "
            f"DIGEST_PENDING_KAI_REVIEW placeholder"
        )

    def test_containerfile_uses_distroless_cc_nonroot(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        path = REPO_ROOT / "infra" / containerfile_dir / "Containerfile"
        text = path.read_text(encoding="utf-8")
        assert (
            "distroless/cc-debian12:nonroot@sha256:"
            "DIGEST_PENDING_KAI_REVIEW"
            in text
        ), (
            f"{path} must FROM distroless/cc-debian12:nonroot with the "
            f"DIGEST_PENDING_KAI_REVIEW placeholder"
        )

    def test_containerfile_user_nonroot(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        path = REPO_ROOT / "infra" / containerfile_dir / "Containerfile"
        text = path.read_text(encoding="utf-8")
        assert (
            "USER nonroot:nonroot" in text
        ), f"{path} must drop privileges to nonroot:nonroot"

    def test_containerfile_busl_licence_header(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        path = REPO_ROOT / "infra" / containerfile_dir / "Containerfile"
        text = path.read_text(encoding="utf-8")
        # REUSE-IgnoreStart
        spdx_busl_marker = "SPDX-License-Identifier: " + "BUSL-1.1"
        # REUSE-IgnoreEnd
        assert spdx_busl_marker in text, (
            f"{path} must declare BUSL-1.1 SPDX header"
        )

    def test_containerfile_builds_correct_binary(
        self,
        welle_n: int,
        workflow_filename: str,
        containerfile_dir: str,
        crate_path_segment: str,
        binary_name: str,
    ) -> None:
        path = REPO_ROOT / "infra" / containerfile_dir / "Containerfile"
        text = path.read_text(encoding="utf-8")
        assert (
            f"-p {crate_path_segment}" in text
        ), f"{path} must `cargo build` crate {crate_path_segment}"
        assert (
            f"--bin {binary_name}" in text
        ), f"{path} must `cargo build` binary {binary_name}"
        # And the COPY --from=builder line must reference the same
        # binary path under target/release/.
        assert (
            f"target/release/{binary_name}" in text
        ), f"{path} must COPY target/release/{binary_name}"


# ======================================================================
# Cross-workflow uniformity (single-test invariants spanning the four)
# ======================================================================


def test_all_four_workflows_share_same_step_set() -> None:
    """The four Welle-4..7 workflows MUST share the exact same set of
    step names (cross-workflow regression guard — a future edit that
    adds a step to one Welle workflow but forgets the other three is
    a supply-chain provenance drift this test catches at policy-
    author time).
    """
    step_sets: dict[str, set[str]] = {}
    for _welle_n, wf_filename, *_rest in WELLE_4_7_BUNDLE:
        steps = _build_steps(_load_yaml(wf_filename))
        step_sets[wf_filename] = {
            s.get("name") for s in steps if s.get("name")
        }
    reference = step_sets[WELLE_4_7_BUNDLE[0][1]]
    for wf_filename, names in step_sets.items():
        assert names == reference, (
            f"step-name set drift in {wf_filename}: "
            f"missing={sorted(reference - names)}, "
            f"extra={sorted(names - reference)}"
        )


def test_all_four_workflows_have_unique_image_names() -> None:
    """Each Welle-4..7 workflow MUST emit a unique GHCR image name
    (`wakir-persona-engine-<binary>`). A typo that produced two
    workflows pushing to the same image repository would silently
    overwrite digests across cutover-step pin-rotations.
    """
    image_names: dict[str, str] = {}
    for _welle_n, wf_filename, _cf_dir, _crate, binary_name in WELLE_4_7_BUNDLE:
        # The buildah step constructs the image name from
        # github.repository_owner + binary name. We check the binary
        # name segment.
        steps = _build_steps(_load_yaml(wf_filename))
        buildah = steps[_step_index(steps, "Build image with buildah")]
        run = buildah.get("run", "")
        # Substring match — the image reference is
        # ``ghcr.io/${{ github.repository_owner }}/wakir-persona-engine-XYZ``
        # and the binary_name parameter is exactly that XYZ part.
        assert binary_name in run, (
            f"workflow {wf_filename} buildah step must reference image "
            f"name {binary_name}; got step.run substring "
            f"check failed"
        )
        image_names[wf_filename] = binary_name
    # And no two workflows ship the same image name.
    distinct = set(image_names.values())
    assert len(distinct) == len(image_names), (
        f"duplicate GHCR image names across Welle-4..7 workflows: "
        f"{image_names}"
    )
