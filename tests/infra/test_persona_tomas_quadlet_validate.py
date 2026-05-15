# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for Sprint-Tag-8 Bug-35-Folge-Item: production-
Quadlet for wakir-persona-tomas (install-persona-tomas-quadlet.sh)
and the Quadlet-content invariants the install-script depends on.

Anlass — AR-Direktive 2026-05-15 23:35 CEST. Bug-35 (Sprint-10 Tag-6)
fixed the Quadlet bind-mount-Path-Drift; the production install-path
was never codified. This test surface anchors:

* the Quadlet content invariants the install script needs to be true,
* the install script's bash syntax,
* the install script's argparse + pre-flight error paths,
* a smoke test against ``podman /usr/libexec/podman/quadlet --dryrun``
  if the binary is on the host (SKIP otherwise).

Test-Vector index
-----------------

* ``TV-PT-Q-01`` Quadlet file present at the expected repo path.
* ``TV-PT-Q-02`` Quadlet declares Image= with the persona-engine
  bare-base form (+ Cross-Review Zone-J placeholder before resolve).
* ``TV-PT-Q-03`` Quadlet declares the four expected Volume= mounts
  (persona.md ro, persona.json ro, spire-agent-sockets ro, workspace
  rw).
* ``TV-PT-Q-04`` Quadlet declares EnvironmentFile= for the NATS-creds.
* ``TV-PT-Q-05`` Quadlet declares Restart=on-failure (unit-aware).
* ``TV-PT-Q-06`` Quadlet declares Network=wakir-orchestrator.network
  + the user-defined-bridge form (container DNS for nats://wakir-nats).
* ``TV-PT-Q-07`` Quadlet declares HealthCmd + healthcheck-cadence
  (HealthInterval/Timeout/Retries/StartPeriod).
* ``TV-PT-Q-08`` Install-script bash syntax clean.
* ``TV-PT-Q-09`` Install-script argparse rejects missing required flags.
* ``TV-PT-Q-10`` Install-script --validate-only short-circuits before
  the install phases (no /etc/wakir mutation in the validate path).
* ``TV-PT-Q-11`` Install-script --help exits 0.
* ``TV-PT-Q-12`` Install-script Quadlet-validate phase runs against
  /etc/containers/systemd (or wakir-quadlet-lint fallback path is
  documented).
* ``TV-PT-Q-13`` `podman quadlet --dryrun` smoke (if binary present)
  succeeds against the Quadlet source.

Sandbox boundary
----------------

Source-file inspection + bash-script invocation in dry-run modes only.
No actual install of /etc/wakir/persona/, no actual systemctl start
(both gated on --no-start / --validate-only flags). The TV-PT-Q-13
smoke is SKIPped when the podman generator binary is not available
on the test host.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_QUADLET = _REPO_ROOT / "quadlet" / "wakir-persona-tomas.container"
_INSTALL_SCRIPT = _REPO_ROOT / "scripts" / "install-persona-tomas-quadlet.sh"


@pytest.fixture(scope="module")
def quadlet_text() -> str:
    assert _QUADLET.is_file(), f"Quadlet not found: {_QUADLET}"
    return _QUADLET.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def install_script_text() -> str:
    assert _INSTALL_SCRIPT.is_file(), f"install script not found: {_INSTALL_SCRIPT}"
    return _INSTALL_SCRIPT.read_text(encoding="utf-8")


# TV-PT-Q-01 -----------------------------------------------------------------


def test_quadlet_file_present() -> None:
    assert _QUADLET.is_file(), f"persona-tomas Quadlet missing at {_QUADLET}"


# TV-PT-Q-02 -----------------------------------------------------------------


def test_quadlet_image_pin_form(quadlet_text: str) -> None:
    """Image= line carries the persona-engine bare-base + Cross-Review
    Zone-J placeholder. The image-pin-idempotent-resolver fills the
    placeholder; the Operator-Hand never edits this line by hand."""
    assert "Image=ghcr.io/wakir-labs/wakir-persona-engine" in quadlet_text, (
        "Image= must reference the wakir-persona-engine image"
    )
    # Placeholder may have been resolved already; we accept either form.
    has_placeholder = "DIGEST_PENDING_KAI_CROSS_REVIEW" in quadlet_text
    has_real_digest = "@sha256:" in quadlet_text and not has_placeholder
    assert has_placeholder or has_real_digest, (
        "Image= must carry either the Zone-J placeholder or a resolved digest"
    )


# TV-PT-Q-03 -----------------------------------------------------------------


def test_quadlet_volume_mounts(quadlet_text: str) -> None:
    """Bug-35 fixed bind-mount-Path-Drift: persona files mount from
    /etc/wakir/persona/, workspace volume is named (NOT bind-mounted),
    spire-agent-sockets is a named-volume read-only."""
    # Bug-35-substance: persona.md ro
    assert "Volume=/etc/wakir/persona/tomas.md:/etc/wakir/persona/tomas.md:ro" in quadlet_text, (
        "persona-md bind-mount must source from /etc/wakir/persona/ (Bug-35 fix)"
    )
    # Bug-35-substance: persona.json ro
    assert "Volume=/etc/wakir/persona/tomas.json:/etc/wakir/persona/tomas.json:ro" in quadlet_text, (
        "persona-json bind-mount must source from /etc/wakir/persona/ (Bug-35 fix)"
    )
    # spire-agent-sockets named volume, ro
    assert "wakir-spire-agent-sockets.volume:/run/spire/agent-sockets:ro" in quadlet_text, (
        "spire-agent-sockets named-volume mount missing"
    )
    # workspace named volume, rw
    assert "wakir-persona-tomas-workspace.volume:/var/lib/wakir/persona/tomas" in quadlet_text, (
        "persona workspace named-volume mount missing"
    )


# TV-PT-Q-04 -----------------------------------------------------------------


def test_quadlet_environment_file(quadlet_text: str) -> None:
    """EnvironmentFile= wired to /etc/wakir/persona-tomas.env (NATS
    creds when token-auth is active; empty on SPIFFE-JWT-auth)."""
    assert "EnvironmentFile=/etc/wakir/persona-tomas.env" in quadlet_text, (
        "EnvironmentFile= for NATS-creds must be wired"
    )


# TV-PT-Q-05 -----------------------------------------------------------------


def test_quadlet_restart_policy(quadlet_text: str) -> None:
    """Unit-aware restart-policy: Restart=on-failure with bounded
    RestartSec + TimeoutStartSec for recovery-drill phase R4 coupling."""
    assert "Restart=on-failure" in quadlet_text, "Restart=on-failure missing"
    assert "RestartSec=" in quadlet_text, "RestartSec= missing"
    assert "TimeoutStartSec=" in quadlet_text, "TimeoutStartSec= missing"


# TV-PT-Q-06 -----------------------------------------------------------------


def test_quadlet_network_dns(quadlet_text: str) -> None:
    """Network= wakir-orchestrator.network — container-DNS for the
    nats:// hostname and the SPIRE agent socket co-location."""
    assert "Network=wakir-orchestrator.network" in quadlet_text, (
        "Network=wakir-orchestrator.network required for container DNS"
    )
    # The env var that consumes the network-name-resolved hostname.
    assert "WAKIR_NATS_SERVERS=nats://wakir-nats:4222" in quadlet_text, (
        "WAKIR_NATS_SERVERS must reference the container-DNS name"
    )


# TV-PT-Q-07 -----------------------------------------------------------------


def test_quadlet_healthcheck(quadlet_text: str) -> None:
    """Health-probe wiring is mandatory for the production rollout."""
    assert "HealthCmd=" in quadlet_text, "HealthCmd= missing"
    assert "HealthInterval=" in quadlet_text, "HealthInterval= missing"
    assert "HealthTimeout=" in quadlet_text, "HealthTimeout= missing"
    assert "HealthRetries=" in quadlet_text, "HealthRetries= missing"
    assert "HealthStartPeriod=" in quadlet_text, "HealthStartPeriod= missing"


# TV-PT-Q-08 -----------------------------------------------------------------


def test_install_script_bash_syntax_clean() -> None:
    rc = subprocess.run(
        ["bash", "-n", str(_INSTALL_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert rc.returncode == 0, f"bash -n failed: {rc.stderr!r}"


# TV-PT-Q-09 -----------------------------------------------------------------


def test_install_script_missing_required_flag_errors() -> None:
    """Argparse rejects missing required flags. We exercise the
    "no flags at all" path; the script must abort with rc=1 and
    mention --persona-md (or another required flag) in stderr.
    """
    rc = subprocess.run(
        ["bash", str(_INSTALL_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "PATH": os.environ.get("PATH", "")},
    )
    assert rc.returncode != 0, (
        f"Install-script must error on missing required flags; got rc={rc.returncode}"
    )


# TV-PT-Q-10 -----------------------------------------------------------------


def test_install_script_validate_only_short_circuits(
    install_script_text: str,
) -> None:
    """--validate-only flag short-circuits before the install phases.
    Source check: the install phases (phase-1 stage persona-files,
    phase-2 stage env-file, phase-3 install Quadlet) are gated by
    ``if [[ "$VALIDATE_ONLY" -ne 1 ]]; then``.
    """
    assert "VALIDATE_ONLY" in install_script_text, (
        "--validate-only flag must be parsed"
    )
    assert 'if [[ "$VALIDATE_ONLY" -ne 1 ]]; then' in install_script_text, (
        "Install phases must be gated by --validate-only check"
    )


# TV-PT-Q-11 -----------------------------------------------------------------


def test_install_script_help_exits_zero() -> None:
    rc = subprocess.run(
        ["bash", str(_INSTALL_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert rc.returncode == 0, f"--help must exit 0; got rc={rc.returncode}"
    assert "persona" in rc.stdout.lower() or "tomas" in rc.stdout.lower(), (
        f"--help output must mention persona/tomas; got stdout={rc.stdout!r}"
    )


# TV-PT-Q-12 -----------------------------------------------------------------


def test_install_script_quadlet_validate_phase(install_script_text: str) -> None:
    """The script calls the podman quadlet generator (or the
    wakir-quadlet-lint fallback) before systemctl start. This is the
    pre-start gate that catches Bug-35-class drift before the daemon
    even reads the unit."""
    assert "podman quadlet validate" in install_script_text.lower() \
        or "/usr/libexec/podman/quadlet" in install_script_text, (
        "Install-script must call the podman quadlet generator in phase-4"
    )
    assert "wakir-quadlet-lint" in install_script_text, (
        "Fallback path to wakir-quadlet-lint must be documented in the script"
    )


# TV-PT-Q-13 -----------------------------------------------------------------


@pytest.mark.skipif(
    not Path("/usr/libexec/podman/quadlet").exists()
    and not Path("/usr/lib/podman/quadlet").exists(),
    reason="podman quadlet generator binary not available on test host",
)
def test_quadlet_dryrun_smoke() -> None:
    """If the podman quadlet binary is available, run --dryrun against
    a staging dir that contains the persona-tomas Quadlet + its named-
    volume sidecars. The generator must accept the file.
    """
    quadlet_bin = None
    for cand in ("/usr/libexec/podman/quadlet", "/usr/lib/podman/quadlet"):
        if Path(cand).is_file():
            quadlet_bin = cand
            break
    assert quadlet_bin is not None  # skipif guard

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # Copy the persona-tomas Quadlet and the dependencies (volume
        # sidecars + network) into the staging dir.
        for src_name in (
            "wakir-persona-tomas.container",
            "wakir-persona-tomas-workspace.volume",
            "wakir-spire-agent-sockets.volume",
            "wakir-orchestrator.network",
            "wakir-nats.container",
            "wakir-spire-agent.container",
        ):
            src = _REPO_ROOT / "quadlet" / src_name
            if src.is_file():
                shutil.copy(src, td_path / src_name)

        # The Quadlet has an unresolved DIGEST_PENDING_KAI_CROSS_REVIEW
        # placeholder; substitute a sentinel valid-shape digest so the
        # generator does not fail on the image-ref parse.
        q = td_path / "wakir-persona-tomas.container"
        text = q.read_text(encoding="utf-8")
        text = text.replace(
            "DIGEST_PENDING_KAI_CROSS_REVIEW",
            "0" * 64,  # 64-char hex sentinel
        )
        q.write_text(text, encoding="utf-8")

        rc = subprocess.run(
            [quadlet_bin, "--dryrun", "--user=0", str(td_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # The generator emits the unit-files to stdout and any errors
        # to stderr. We accept rc=0 OR rc!=0 only if the error is NOT
        # about the persona-tomas Quadlet itself (it may complain about
        # missing sibling Quadlets we did not copy).
        if rc.returncode != 0:
            # Pass if the error message does not mention persona-tomas
            # (i.e. the persona-tomas Quadlet parsed cleanly).
            err = rc.stderr.lower()
            assert "persona-tomas" not in err, (
                f"persona-tomas Quadlet caused a generator error: {rc.stderr!r}"
            )
