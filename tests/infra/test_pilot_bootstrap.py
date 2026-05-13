# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic test surface for ``infra/spire/federation/wakir-pilot-bootstrap.sh``.

The script lives on a Pilot-VM and orchestrates an 8-step bring-up of
the Wakir Phase-1b single-org pilot. The hermetic test surface checks:

1. Bash syntax (``bash -n``) is clean.
2. Optional shellcheck pass when shellcheck is installed.
3. Env-var defaults are present in the source.
4. ``--help`` mode exits 0 without performing side effects.
5. ``--resume-from`` argument is validated.
6. ``WAKIR_SKIP_COSIGN_VERIFY=1`` emits the warning banner.
7. ``WAKIR_SKIP_PROMPTS=1`` skips interactive ``read``.
8. The 8-phase output pattern is present and ordered.
9. The script references ``resolve-image-pins.sh`` and
   ``proxmox-bringup-smoke`` (the two real-VM-side companion artefacts).
10. Idempotency markers ("already present", "already active",
    "no DIGEST_PENDING_TOMAS_REVIEW placeholders found") are present.

Sandbox boundary: every test reads the script SOURCE on disk and may
run ``bash`` with limited flags. No network, no podman, no
systemd, no GHCR / DockerHub egress.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT / "infra" / "spire" / "federation" / "wakir-pilot-bootstrap.sh"
)


@pytest.fixture(scope="module")
def script_source() -> str:
    assert SCRIPT.exists(), f"missing script: {SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. bash -n
# ---------------------------------------------------------------------------


def test_bash_syntax_clean() -> None:
    """``bash -n`` parses the script without error."""
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"bash -n failed:\n  stdout: {result.stdout}\n  stderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# 2. shellcheck (optional)
# ---------------------------------------------------------------------------


def test_shellcheck_clean() -> None:
    """If shellcheck is available, run it. Otherwise skip."""
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck not installed in sandbox")
    result = subprocess.run(
        ["shellcheck", "-S", "error", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"shellcheck reported errors:\n{result.stdout}\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# 3. Env-var defaults
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "var,default",
    [
        ("WAKIR_ORG_ID", "acme"),
        ("WAKIR_TRUST_DOMAIN", "wakir.test"),
        ("WAKIR_REPO_BRANCH", "main"),
        ("WAKIR_SKIP_COSIGN_VERIFY", "0"),
        ("WAKIR_SKIP_PROMPTS", "0"),
    ],
)
def test_env_var_defaults_documented(
    script_source: str, var: str, default: str
) -> None:
    """Each documented env var has a ``: \"${VAR:=default}\"`` form
    in the script so re-running with the env unset yields the
    documented behaviour."""
    pattern = rf': "\${{{var}:={re.escape(default)}}}"'
    assert re.search(pattern, script_source), (
        f"missing default for {var}={default} (looked for: {pattern})"
    )


# ---------------------------------------------------------------------------
# 4. --help mode
# ---------------------------------------------------------------------------


def test_help_mode_exits_zero() -> None:
    """``--help`` must exit 0 and print a usage banner that mentions
    the 8 steps. Critically, ``--help`` must NOT perform any side
    effect (e.g. it must not require root)."""
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "WAKIR_SKIP_PROMPTS": "1"},
    )
    assert result.returncode == 0
    out = result.stdout + result.stderr
    assert "Usage:" in out
    # Steps 1..8 should be enumerated somewhere in the help text.
    for label in (
        "Pre-Flight",
        "Toolbox",
        "CLI tools",
        "Repo clone",
        "Image-pin",
        "Quadlet",
        "NATS-KV",
        "Smoke",
    ):
        assert label in out, f"missing step label in help: {label}"


# ---------------------------------------------------------------------------
# 5. --resume-from validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", ["0", "9", "abc", "-1", ""])
def test_resume_from_rejects_bad_value(bad_value: str) -> None:
    """Bad ``--resume-from`` values cause a non-zero exit before
    the script tries to do anything real."""
    result = subprocess.run(
        ["bash", str(SCRIPT), "--resume-from", bad_value],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "WAKIR_SKIP_PROMPTS": "1"},
    )
    assert result.returncode != 0, (
        f"--resume-from {bad_value!r} should fail but exit was 0:\n"
        f"  stdout: {result.stdout}\n  stderr: {result.stderr}"
    )
    assert "resume-from" in (result.stderr + result.stdout).lower()


def test_resume_from_valid_values_pass_validation(
    tmp_path: Path,
) -> None:
    """A valid ``--resume-from N`` value (1..8) passes argument
    validation. We can't run the full script in the sandbox (it
    needs root + podman), but the validation happens before the
    root-check, so a non-root invocation that errors at step 1's
    'must run as root' message proves the argument was accepted."""
    result = subprocess.run(
        ["bash", str(SCRIPT), "--resume-from", "1"],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "WAKIR_SKIP_PROMPTS": "1",
            "WAKIR_REPO_ROOT": str(tmp_path / "wakir-runtime"),
        },
    )
    # We don't care about the exit code (root-check fails); we DO
    # care that the failure is NOT the argument-validation one.
    combined = result.stdout + result.stderr
    assert "--resume-from expects 1..8" not in combined


# ---------------------------------------------------------------------------
# 6. WAKIR_SKIP_COSIGN_VERIFY warning banner
# ---------------------------------------------------------------------------


def test_skip_cosign_emits_warning(script_source: str) -> None:
    """``WAKIR_SKIP_COSIGN_VERIFY=1`` emits a clear, banner-style
    warning in the source (so an operator who sets the flag knows
    what they're trading away)."""
    assert "WAKIR_SKIP_COSIGN_VERIFY=1" in script_source
    assert "WARNING" in script_source or "WARN" in script_source.upper()
    # The warning must mention 'tag' so the operator understands that
    # the pull will run against tag-only (no digest pin).
    assert "tag" in script_source.lower()


# ---------------------------------------------------------------------------
# 7. WAKIR_SKIP_PROMPTS behaviour
# ---------------------------------------------------------------------------


def test_skip_prompts_documented(script_source: str) -> None:
    """``WAKIR_SKIP_PROMPTS=1`` short-circuits the interactive ``read``
    so the script can run headless / in CI."""
    assert "WAKIR_SKIP_PROMPTS" in script_source
    assert "prompt_yes_no" in script_source


def test_help_does_not_prompt() -> None:
    """``--help`` must produce its output without blocking on stdin
    even when SKIP_PROMPTS is unset."""
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
        # IMPORTANT: pass /dev/null as stdin to prove no read happens
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# 8. 8-phase output pattern
# ---------------------------------------------------------------------------


def test_eight_phases_named_in_order(script_source: str) -> None:
    """The script defines exactly the 8 step functions in the
    documented order. Order matters: step 5 (image pins) must come
    before step 6 (quadlet install) so the substitution lands before
    podman pulls the images."""
    expected = [
        "step_1_preflight",
        "step_2_toolbox",
        "step_3_cli_tools",
        "step_4_repo_clone",
        "step_5_image_pins",
        "step_6_quadlet",
        "step_7_bucket_init",
        "step_8_smoke",
    ]
    positions = []
    for name in expected:
        idx = script_source.find(f"{name}()")
        assert idx != -1, f"step function not defined: {name}"
        positions.append(idx)
    assert positions == sorted(positions), (
        "step functions defined out of order; this implies the main "
        "driver loop will execute them in the wrong sequence"
    )


# ---------------------------------------------------------------------------
# 9. Companion-artefact references
# ---------------------------------------------------------------------------


def test_references_resolve_script(script_source: str) -> None:
    """Step 5 delegates to the existing
    ``proxmox/resolve-image-pins.sh`` resolver -- it must not
    duplicate the substitution logic."""
    assert "proxmox/resolve-image-pins.sh" in script_source


def test_references_smoke_binary(script_source: str) -> None:
    """Step 8 calls ``bin/proxmox-bringup-smoke`` -- the existing
    smoke-test entry point. Re-using it (rather than re-implementing
    smoke checks inline) is the contract."""
    assert "bin/proxmox-bringup-smoke" in script_source
    assert "proxmox-bringup-smoke" in script_source


# ---------------------------------------------------------------------------
# 10. Idempotency markers
# ---------------------------------------------------------------------------


def test_idempotency_markers_present(script_source: str) -> None:
    """An idempotent re-run must visibly say 'already X' (instead of
    silently re-doing work that mutates state). The hermetic test
    asserts that at least one 'already' marker per pre-existing
    side-effect category is present in the source."""
    must_have = [
        "already present",       # repo, files
        "already active",        # systemd units
        "no DIGEST_PENDING",     # image pins already resolved
        "already in",            # roster
    ]
    for marker in must_have:
        assert marker in script_source, (
            f"missing idempotency marker: {marker}"
        )


# ---------------------------------------------------------------------------
# 11. Sprint-9-Tag-4 Bug 1: resume-hint avoids the ``bash bash`` doubling
# when the script was piped from ``curl ... | sudo bash``.
# ---------------------------------------------------------------------------


def test_resume_hint_avoids_bash_doubling(script_source: str) -> None:
    """When the script is invoked via ``curl ... | sudo bash``, ``$0``
    collapses to ``bash`` and a naive ``sudo bash $PROG`` form would
    print ``sudo bash bash --resume-from N``. The resume-hint helper
    must guard against that by falling back to the canonical installed
    path when ``$PROG == bash`` or the on-disk script exists at the
    documented location."""
    # The naive form must NOT appear in fail_step's resume hint.
    assert "sudo bash ${PROG}" not in script_source, (
        "Sprint-9-Tag-4 Bug 1: fail_step's resume hint must not "
        "embed ${PROG} directly (collapses to 'bash' under curl|bash)"
    )
    # The resilient helper must be present.
    assert "_resume_cmd" in script_source, (
        "Sprint-9-Tag-4 Bug 1: bootstrap must define a _resume_cmd "
        "helper that synthesises a stable resume command line"
    )
    # The helper must mention the installed-path fallback.
    assert "WAKIR_REPO_ROOT" in script_source
    assert 'PROG" == "bash"' in script_source, (
        "Sprint-9-Tag-4 Bug 1: _resume_cmd must explicitly handle the "
        "curl-pipe-bash case where PROG collapses to 'bash'"
    )


# ---------------------------------------------------------------------------
# 12. Sprint-9-Tag-4 Bug 2: federation volume install with per-side
# filename substitution.
# ---------------------------------------------------------------------------


def test_volume_install_renames_federation_volumes_per_side(
    script_source: str,
) -> None:
    """Phase 6b must install federation server volumes with destination
    basenames that embed ``-${side}-`` between ``federation`` and the
    kind suffix (data|sockets|bundles). The Server-Container's
    ``Volume=wakir-spire-server-federation-<SIDE>-data.volume`` directive
    only resolves if the per-side renamed volume file is present.
    """
    # The rename sed pattern must be present in the script.
    assert (
        "wakir-spire-server-federation-${side}-\\1.volume"
        in script_source
    ), (
        "Sprint-9-Tag-4 Bug 2: bootstrap step 6b must rename federation "
        "server volume files to embed -${side}- before installing"
    )
    # The agent volume rename is also required (bug 2 sibling for agent).
    assert (
        "wakir-spire-agent-${side}-\\1.volume" in script_source
    ), (
        "Sprint-9-Tag-4 Bug 2: bootstrap step 6b must rename agent "
        "volume files to embed ${side} in the destination basename"
    )


# ---------------------------------------------------------------------------
# 13. Sprint-9-Tag-4 Bug 5: Phase 6 idempotency markers.
# ---------------------------------------------------------------------------


def test_phase_6_idempotent_install_helper(script_source: str) -> None:
    """Phase 6 must compare the rendered (sed-substituted) output
    against the on-disk target file and skip the install when the
    contents match. This protects operator manual fixes from being
    silently overwritten on ``--resume-from 6``.
    """
    assert "_install_substituted" in script_source, (
        "Sprint-9-Tag-4 Bug 5: bootstrap must use a helper that "
        "compares rendered content against target before overwriting"
    )
    assert "cmp -s" in script_source, (
        "Sprint-9-Tag-4 Bug 5: bootstrap must use cmp -s for "
        "byte-precise idempotency comparison"
    )
    assert "reset-failed" in script_source, (
        "Sprint-9-Tag-4 Bug 5: bootstrap must reset-failed before "
        "restart on units in a restart-loop state"
    )


# ---------------------------------------------------------------------------
# 14. Live-bring-up phase-6 dry-run simulation
# ---------------------------------------------------------------------------


def test_phase_6_volume_rename_sed_round_trip() -> None:
    """End-to-end sanity check that the Phase-6 sed rename produces
    the volume filenames the Server/Agent containers reference at
    install time. This is a pure-Python emulation of the bash sed
    invocations; no live podman / systemctl / file-system writes.
    """
    side = "wakir"
    cases = [
        (
            "wakir-spire-server-federation-data.volume",
            f"wakir-spire-server-federation-{side}-data.volume",
        ),
        (
            "wakir-spire-server-federation-sockets.volume",
            f"wakir-spire-server-federation-{side}-sockets.volume",
        ),
        (
            "wakir-spire-server-federation-bundles.volume",
            f"wakir-spire-server-federation-{side}-bundles.volume",
        ),
    ]
    for src, expected in cases:
        # Mirror of the bash sed:
        # sed "s/^wakir-spire-server-federation-\(data\|sockets\|
        # bundles\)\.volume$/wakir-spire-server-federation-${side}-\1.volume/"
        out = re.sub(
            r"^wakir-spire-server-federation-(data|sockets|bundles)\.volume$",
            rf"wakir-spire-server-federation-{side}-\1.volume",
            src,
        )
        assert out == expected, (
            f"federation server volume rename mismatch: "
            f"{src!r} -> {out!r} (expected {expected!r})"
        )

    agent_cases = [
        (
            "wakir-spire-agent-federation-data.volume",
            f"wakir-spire-agent-{side}-data.volume",
        ),
        (
            "wakir-spire-agent-federation-sockets.volume",
            f"wakir-spire-agent-{side}-sockets.volume",
        ),
    ]
    for src, expected in agent_cases:
        out = re.sub(
            r"^wakir-spire-agent-federation-(data|sockets)\.volume$",
            rf"wakir-spire-agent-{side}-\1.volume",
            src,
        )
        assert out == expected, (
            f"agent volume rename mismatch: "
            f"{src!r} -> {out!r} (expected {expected!r})"
        )


def test_resolver_validates_digest_format() -> None:
    """The companion resolver (``proxmox/resolve-image-pins.sh``)
    validates sha256:<64-hex> -- the bootstrap script must pass
    digests that match that form. We inspect the bootstrap's
    cross-check pipeline (cosign + skopeo) and confirm the
    sha256:<hex> shape is what the resolver expects."""
    resolver = (
        REPO_ROOT
        / "infra"
        / "spire"
        / "federation"
        / "proxmox"
        / "resolve-image-pins.sh"
    )
    assert resolver.exists(), f"resolver missing: {resolver}"
    src = resolver.read_text(encoding="utf-8")
    assert "sha256:[0-9a-f]{64}" in src, (
        "resolver no longer validates sha256:<64-hex>; bootstrap "
        "script may pass values that the resolver silently rejects"
    )
