# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for Sprint-10 Tag-9 acceptance-script naming convergence.

Anlass — Sprint-10 Tag-9 substance review (Mira-CEO 2026-05-15
~23:35 CEST, Tag-9 Welle). After Bug-38 (Tag-8) fixed the
acceptance-script service-naming drift for Phase-2 and Phase-3, the
broader convention across the substrate was reviewed. Two findings:

1. **Acceptance entry-point at flat ``scripts/``.** The
   federation-specific acceptance lane sits at
   ``scripts/federation-live-vm-acceptance.sh``. The hermetic
   substrate convention is ``scripts/<subdir>/<canonical-name>.sh``
   (mirror of ``scripts/systemd/``, ``infra/spire/agent/quadlet/``).
   Tag-9 introduces ``scripts/acceptance/wakir-pilot-acceptance.sh``
   as the canonical dispatch entry-point: federation forwards to the
   existing federation lane, single-org runs the thin inline probe.

2. **Asymmetric unit-naming convention is intentional.** The Quadlet
   container-templates name them asymmetrically:

   * server: ``wakir-spire-server-federation-<SIDE>`` — has the
     ``-federation-`` substring because there is **only** a
     federation-mode SPIRE-Server container; single-org uses the
     base ``wakir-spire-server`` unit.
   * agent:  ``wakir-spire-agent-<SIDE>`` — no ``-federation-``
     substring because the agent runs in both single-org and
     federation mode against the same base name shape.

   This asymmetry was introduced in Sprint-10 Tag-3 and has been
   propagated consistently across bootstrap, smoke-CLI, quadlet
   templates, and the Tag-8 acceptance script. Tag-9 locks it in
   with hermetic tests so it cannot drift silently.

Test-Vector index
-----------------

Canonical acceptance dispatch (5 vectors):

* ``TV-ACC-CONV-01`` Canonical entry-point exists at
  ``scripts/acceptance/wakir-pilot-acceptance.sh`` and is executable.
* ``TV-ACC-CONV-02`` Canonical entry-point is bash-syntax-clean.
* ``TV-ACC-CONV-03`` Federation-mode dispatch forwards to the
  existing ``federation-live-vm-acceptance.sh`` with env-vars
  propagated (no logic clone, no drift surface).
* ``TV-ACC-CONV-04`` Single-org-mode dispatch runs the thin inline
  probe with bare unit names (no side-suffix, no
  ``-federation-`` substring).
* ``TV-ACC-CONV-05`` Unknown ``WAKIR_PILOT_MODE`` is rejected with a
  clear error (no silent fallthrough to either mode).

Asymmetric unit-naming convention (5 vectors):

* ``TV-NAME-CONV-01`` Federation server-Quadlet template
  ContainerName has ``-federation-`` substring.
* ``TV-NAME-CONV-02`` Federation agent-Quadlet template
  ContainerName does NOT have ``-federation-`` substring (asymmetric
  by design).
* ``TV-NAME-CONV-03`` Bootstrap script uses the asymmetric
  convention consistently in volume-name mapping (server volumes
  prefixed ``wakir-spire-server-federation-${side}-*``, agent
  volumes prefixed ``wakir-spire-agent-${side}-*``).
* ``TV-NAME-CONV-04`` Smoke CLI uses the asymmetric convention in
  the ``REQUIRED_UNITS`` array.
* ``TV-NAME-CONV-05`` Tag-8 Bug-38 acceptance script uses the
  asymmetric convention in Phase-2 unit probes.

-- Tomás
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CANONICAL = _REPO_ROOT / "scripts" / "acceptance" / "wakir-pilot-acceptance.sh"
_FED = _REPO_ROOT / "scripts" / "federation-live-vm-acceptance.sh"
_BOOTSTRAP = _REPO_ROOT / "infra" / "spire" / "federation" / "wakir-pilot-bootstrap.sh"
_SMOKE_CLI = _REPO_ROOT / "bin" / "proxmox-bringup-smoke"
_SERVER_QUADLET = (
    _REPO_ROOT
    / "infra"
    / "spire"
    / "federation"
    / "quadlet"
    / "wakir-spire-server-federation.container"
)
_AGENT_QUADLET = (
    _REPO_ROOT
    / "infra"
    / "spire"
    / "agent"
    / "quadlet"
    / "wakir-spire-agent-federation.container"
)


@pytest.fixture(scope="module")
def canonical_source() -> str:
    assert _CANONICAL.is_file(), f"canonical script not found: {_CANONICAL}"
    return _CANONICAL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def fed_source() -> str:
    assert _FED.is_file(), f"federation script not found: {_FED}"
    return _FED.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def bootstrap_source() -> str:
    assert _BOOTSTRAP.is_file(), f"bootstrap script not found: {_BOOTSTRAP}"
    return _BOOTSTRAP.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def smoke_source() -> str:
    assert _SMOKE_CLI.is_file(), f"smoke CLI not found: {_SMOKE_CLI}"
    return _SMOKE_CLI.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def server_quadlet_source() -> str:
    assert _SERVER_QUADLET.is_file(), (
        f"server quadlet template not found: {_SERVER_QUADLET}"
    )
    return _SERVER_QUADLET.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def agent_quadlet_source() -> str:
    assert _AGENT_QUADLET.is_file(), (
        f"agent quadlet template not found: {_AGENT_QUADLET}"
    )
    return _AGENT_QUADLET.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Canonical acceptance dispatch (TV-ACC-CONV-01..05).
# ---------------------------------------------------------------------------


def test_tv_acc_conv_01_canonical_entry_point_present_executable():
    """Canonical entry-point exists and is executable."""
    assert _CANONICAL.is_file(), (
        f"canonical entry-point missing: {_CANONICAL}"
    )
    mode = _CANONICAL.stat().st_mode
    assert mode & stat.S_IXUSR, (
        f"canonical entry-point not executable: mode=0o{mode & 0o777:o}"
    )


def test_tv_acc_conv_02_canonical_bash_syntax_clean():
    """``bash -n`` on the canonical script is clean."""
    result = subprocess.run(
        ["bash", "-n", str(_CANONICAL)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"bash -n failed for {_CANONICAL.name}: {result.stderr}"
    )


def test_tv_acc_conv_03_federation_dispatch_forwards_to_existing_lane(
    canonical_source: str,
) -> None:
    """Federation-mode dispatch forwards to the existing federation
    lane (no logic clone, no drift surface). The dispatch must
    exec into the federation script and propagate env-vars."""
    # The case-arm must reference the federation script path.
    fed_arm = re.search(
        r"federation\)(.*?)single-org\)",
        canonical_source,
        re.DOTALL,
    )
    assert fed_arm is not None, "federation case-arm not found"
    body = fed_arm.group(1)
    assert "federation-live-vm-acceptance.sh" in body, (
        "federation dispatch does not forward to "
        "federation-live-vm-acceptance.sh — possible logic clone risk"
    )
    # exec into the federation script (no sub-process drift surface).
    assert re.search(r"\bexec\s+env\b", body), (
        "federation dispatch does not use `exec env` "
        "— must replace the shell, not fork"
    )
    # Env-vars propagated explicitly.
    for var in (
        "WAKIR_SIDE",
        "WAKIR_PEER_SIDE",
        "WAKIR_PEER_HOST",
        "WAKIR_PILOT_MODE",
        "WAKIR_SKIP_COSIGN_VERIFY",
        "WAKIR_REPO_ROOT",
    ):
        assert f"{var}=" in body, (
            f"federation dispatch does not propagate {var}"
        )


def test_tv_acc_conv_04_single_org_dispatch_uses_bare_unit_names(
    canonical_source: str,
) -> None:
    """Single-org dispatch uses the bare unit names (no side suffix,
    no -federation- substring) consistent with the single-org Quadlet
    template."""
    single_arm = re.search(
        r"single-org\)(.*?)\*\)",
        canonical_source,
        re.DOTALL,
    )
    assert single_arm is not None, "single-org case-arm not found"
    body = single_arm.group(1)
    # Bare server + agent unit names.
    assert "wakir-spire-server.service" in body, (
        "single-org dispatch missing bare wakir-spire-server.service probe"
    )
    assert "wakir-spire-agent.service" in body, (
        "single-org dispatch missing bare wakir-spire-agent.service probe"
    )
    # No -federation- substring in the single-org probe.
    assert "wakir-spire-server-federation-" not in body, (
        "single-org dispatch leaks -federation- substring — convention "
        "violation (federation units should be in the federation arm only)"
    )


def test_tv_acc_conv_05_unknown_mode_rejected_with_clear_error(
    canonical_source: str,
) -> None:
    """Unknown ``WAKIR_PILOT_MODE`` is rejected via the default arm."""
    default_arm = re.search(
        r"\*\)(.*?)esac",
        canonical_source,
        re.DOTALL,
    )
    assert default_arm is not None, "default case-arm not found"
    body = default_arm.group(1)
    assert "fail" in body, (
        "default arm must call fail() — silent fallthrough not allowed"
    )
    assert "unknown" in body.lower(), (
        "default arm error message should mention 'unknown'"
    )


# ---------------------------------------------------------------------------
# Asymmetric unit-naming convention (TV-NAME-CONV-01..05).
# ---------------------------------------------------------------------------


def test_tv_name_conv_01_server_quadlet_has_federation_substring(
    server_quadlet_source: str,
) -> None:
    """The federation server Quadlet template's ContainerName carries
    the ``-federation-`` substring."""
    match = re.search(r"^ContainerName=(.+)$", server_quadlet_source, re.M)
    assert match is not None, "ContainerName= line not found"
    name = match.group(1).strip()
    assert "-federation-" in name, (
        f"server ContainerName must contain '-federation-': {name!r}"
    )
    assert name.endswith("<SIDE>"), (
        f"server ContainerName must end with '<SIDE>' placeholder: {name!r}"
    )


def test_tv_name_conv_02_agent_quadlet_no_federation_substring(
    agent_quadlet_source: str,
) -> None:
    """The federation agent Quadlet template's ContainerName does NOT
    carry the ``-federation-`` substring (asymmetric by design)."""
    match = re.search(r"^ContainerName=(.+)$", agent_quadlet_source, re.M)
    assert match is not None, "ContainerName= line not found"
    name = match.group(1).strip()
    assert "-federation-" not in name, (
        f"agent ContainerName must NOT contain '-federation-' "
        f"(asymmetric convention): {name!r}"
    )
    assert name == "wakir-spire-agent-<SIDE>", (
        f"agent ContainerName must be 'wakir-spire-agent-<SIDE>': {name!r}"
    )


def test_tv_name_conv_03_bootstrap_volume_mapping_asymmetric(
    bootstrap_source: str,
) -> None:
    """Bootstrap volume-name mapping follows the asymmetric convention:
    server volumes prefixed ``wakir-spire-server-federation-${side}-*``,
    agent volumes prefixed ``wakir-spire-agent-${side}-*``."""
    # Server volumes have -federation-.
    assert re.search(
        r'"wakir-spire-server-federation-\$\{side\}-data"',
        bootstrap_source,
    ), "server data volume name missing -federation- substring"
    assert re.search(
        r'"wakir-spire-server-federation-\$\{side\}-sockets"',
        bootstrap_source,
    ), "server sockets volume name missing -federation- substring"
    assert re.search(
        r'"wakir-spire-server-federation-\$\{side\}-bundles"',
        bootstrap_source,
    ), "server bundles volume name missing -federation- substring"

    # Agent data + sockets volumes do NOT have -federation-.
    assert re.search(
        r'"wakir-spire-agent-\$\{side\}-data"',
        bootstrap_source,
    ), "agent data volume name should be wakir-spire-agent-${side}-data"
    assert re.search(
        r'"wakir-spire-agent-\$\{side\}-sockets"',
        bootstrap_source,
    ), "agent sockets volume name should be wakir-spire-agent-${side}-sockets"

    # Agent volumes must not accidentally use the server prefix
    # except for the bundles cross-mount (agent reads server bundles).
    accidental_pattern = re.compile(
        r'"wakir-spire-agent-federation-\$\{side\}-'
    )
    assert not accidental_pattern.search(bootstrap_source), (
        "agent volume names must not include '-federation-' substring"
    )


def test_tv_name_conv_04_smoke_cli_required_units_asymmetric(
    smoke_source: str,
) -> None:
    """Smoke CLI ``REQUIRED_UNITS`` follows the asymmetric convention."""
    # Server unit has -federation-.
    assert re.search(
        r'"wakir-spire-server-federation-\$\{SIDE\}\.service"',
        smoke_source,
    ), "smoke CLI server unit missing -federation- substring"
    # Agent unit does NOT have -federation-.
    assert re.search(
        r'"wakir-spire-agent-\$\{SIDE\}\.service"',
        smoke_source,
    ), "smoke CLI agent unit should be wakir-spire-agent-${SIDE}.service"
    # Asymmetry: agent must not accidentally pick up -federation-.
    assert not re.search(
        r'wakir-spire-agent-federation-\$\{SIDE\}\.service',
        smoke_source,
    ), "smoke CLI agent unit must not include '-federation-' substring"


def test_tv_name_conv_05_tag_8_acceptance_script_asymmetric(
    fed_source: str,
) -> None:
    """Tag-8 federation acceptance script uses the asymmetric
    convention in Phase-2 unit probes (regression-lock)."""
    # Server unit assignment with -federation-.
    assert re.search(
        r'server_unit="wakir-spire-server-federation-\$\{WAKIR_SIDE\}\.service"',
        fed_source,
    ), "acceptance script server_unit assignment missing -federation-"
    # Agent unit assignment without -federation-.
    assert re.search(
        r'agent_unit="wakir-spire-agent-\$\{WAKIR_SIDE\}\.service"',
        fed_source,
    ), "acceptance script agent_unit must be wakir-spire-agent-${WAKIR_SIDE}.service"
    # Agent must not pick up -federation- by accident.
    assert not re.search(
        r'agent_unit="wakir-spire-agent-federation-',
        fed_source,
    ), "acceptance script agent_unit must NOT include '-federation-'"
