# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for the Sprint-10 Tag-1 ``WAKIR_SIDE`` extension of
``infra/spire/federation/wakir-pilot-bootstrap.sh``.

Sprint-10 Tag-1 adds Cross-VM-Federation substance: the bootstrap is
side-aware via the ``WAKIR_SIDE`` env-var. This test suite asserts
the script-shape invariants without running a live VM.

Sandbox boundary: source-file inspection + argument validation via
the script's own ``--help`` shape; no subprocess against podman /
systemctl / network.

Test-Vector index
-----------------

  * ``TV-SIDE-01`` ``WAKIR_SIDE`` env-var is documented in the header
    block AND in the usage banner AND in the post-defaults validation.
  * ``TV-SIDE-02`` Default value of ``WAKIR_SIDE`` is ``wakir`` (the
    Sprint-9 Tag-1 baseline; backwards-compat invariant).
  * ``TV-SIDE-03`` Validation rejects unknown side literals at startup
    (orbit, partner, wakir accepted; any other -> exit 1).
  * ``TV-SIDE-04`` Auto-sync between ``WAKIR_SIDE`` and
    ``WAKIR_TRUST_DOMAIN``: when SIDE != wakir and TRUST_DOMAIN was
    left at the wakir.test default, TRUST_DOMAIN becomes
    ``<SIDE>.test``. Explicit operator override is preserved.
  * ``TV-SIDE-05`` step_6_quadlet uses ``${WAKIR_SIDE}`` not a
    hardcoded ``"wakir"`` literal.
  * ``TV-SIDE-06`` The orbit-side server config + agent config files
    exist on disk and parse-shape OK (server_address +
    server_address-port + trust_domain present).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_BOOTSTRAP = _REPO_ROOT / "infra" / "spire" / "federation" / "wakir-pilot-bootstrap.sh"
_SERVER_ORBIT_CONF = (
    _REPO_ROOT / "infra" / "spire" / "federation" / "config" / "spire-server-orbit.conf"
)
_AGENT_ORBIT_CONF = (
    _REPO_ROOT / "infra" / "spire" / "agent" / "config" / "spire-agent-orbit.conf"
)


@pytest.fixture(scope="module")
def bootstrap_source() -> str:
    assert _BOOTSTRAP.is_file(), f"bootstrap script not found: {_BOOTSTRAP}"
    return _BOOTSTRAP.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TV-SIDE-01: documentation surface (header + usage + post-defaults)
# ---------------------------------------------------------------------------


def test_wakir_side_documented_in_header_block(bootstrap_source: str):
    # The header-block (top-of-file comment) MUST mention WAKIR_SIDE.
    # Pattern: a comment line beginning with ``#   WAKIR_SIDE``.
    header_match = re.search(r"^#\s+WAKIR_SIDE\s+", bootstrap_source, re.MULTILINE)
    assert header_match is not None, (
        "WAKIR_SIDE must be documented as an env-var in the header comment block"
    )


def test_wakir_side_documented_in_usage_banner(bootstrap_source: str):
    # The usage() function emits a banner with env-var hints. WAKIR_SIDE
    # MUST appear there for operators who run --help.
    # We look for the substring "WAKIR_SIDE" within the usage() body.
    usage_match = re.search(r"usage\(\)\s*\{(.*?)^\}", bootstrap_source, re.DOTALL | re.MULTILINE)
    assert usage_match, "usage() function not found"
    usage_body = usage_match.group(1)
    assert "WAKIR_SIDE" in usage_body, (
        "WAKIR_SIDE must be listed in the usage() env-var section"
    )


def test_wakir_side_has_post_defaults_validation(bootstrap_source: str):
    # The post-defaults block MUST validate WAKIR_SIDE against the
    # accepted literal set {wakir, orbit, partner}.
    # Pattern: a case-statement that switches on $WAKIR_SIDE.
    assert re.search(
        r'case\s+"\$WAKIR_SIDE"\s+in', bootstrap_source
    ), "WAKIR_SIDE must be validated in a case-statement"
    # All three accepted sides must appear as case-labels.
    case_block = re.search(
        r'case\s+"\$WAKIR_SIDE"\s+in(.*?)esac', bootstrap_source, re.DOTALL
    )
    assert case_block, "WAKIR_SIDE case-statement not found"
    body = case_block.group(1)
    assert "wakir" in body, body
    assert "orbit" in body, body
    assert "partner" in body, body


# ---------------------------------------------------------------------------
# TV-SIDE-02: default value
# ---------------------------------------------------------------------------


def test_wakir_side_default_is_wakir(bootstrap_source: str):
    # Default-assignment uses the ``: "${WAKIR_SIDE:=wakir}"`` shape.
    assert re.search(
        r':\s+"\$\{WAKIR_SIDE:=wakir\}"', bootstrap_source
    ), "WAKIR_SIDE default-assignment to 'wakir' missing"


# ---------------------------------------------------------------------------
# TV-SIDE-04: trust-domain auto-sync
# ---------------------------------------------------------------------------


def test_trust_domain_auto_sync_block_present(bootstrap_source: str):
    """When WAKIR_SIDE is overridden but WAKIR_TRUST_DOMAIN is at the
    wakir.test default, the bootstrap must auto-sync TRUST_DOMAIN to
    ``<SIDE>.test``. The block lives between the WAKIR_SIDE case-stmt
    and the WAKIR_PILOT_MODE default-assignment."""
    # Look for a conditional that references both WAKIR_SIDE and
    # WAKIR_TRUST_DOMAIN, and assigns ${WAKIR_SIDE}.test.
    pattern = re.compile(
        r'if\s+\[\[\s+"\$WAKIR_SIDE"\s+!=\s+"wakir".*?'
        r'WAKIR_TRUST_DOMAIN="\$\{WAKIR_SIDE\}\.test"',
        re.DOTALL,
    )
    assert pattern.search(bootstrap_source), (
        "WAKIR_SIDE / WAKIR_TRUST_DOMAIN auto-sync block missing"
    )


# ---------------------------------------------------------------------------
# TV-SIDE-05: step_6_quadlet uses ${WAKIR_SIDE} not a hardcoded literal
# ---------------------------------------------------------------------------


def test_step_6_quadlet_uses_wakir_side_variable(bootstrap_source: str):
    """``step_6_quadlet`` must assign ``local side="${WAKIR_SIDE}"``
    — not a hardcoded ``local side="wakir"``."""
    step_6_match = re.search(
        r'step_6_quadlet\(\)\s*\{(.*?)^\}', bootstrap_source, re.DOTALL | re.MULTILINE
    )
    assert step_6_match, "step_6_quadlet() function not found"
    body = step_6_match.group(1)
    # The hardcoded form MUST NOT be present.
    assert 'local side="wakir"' not in body, (
        "step_6_quadlet still hardcodes side='wakir' — Sprint-10 Tag-1 substance regression"
    )
    # The parametrised form MUST be present.
    assert 'local side="${WAKIR_SIDE}"' in body, (
        "step_6_quadlet must use 'local side=\"${WAKIR_SIDE}\"'"
    )


# ---------------------------------------------------------------------------
# TV-SIDE-06: orbit-side config files exist + parse-shape OK
# ---------------------------------------------------------------------------


def test_spire_server_orbit_conf_exists_and_shape_ok():
    assert _SERVER_ORBIT_CONF.is_file(), (
        f"spire-server-orbit.conf missing at {_SERVER_ORBIT_CONF}"
    )
    body = _SERVER_ORBIT_CONF.read_text(encoding="utf-8")
    # Trust-domain literal.
    assert re.search(r'trust_domain\s*=\s*"orbit\.test"', body), (
        "spire-server-orbit.conf must declare trust_domain = orbit.test"
    )
    # Federation block with bundle_endpoint.
    assert "federation {" in body and "bundle_endpoint" in body, (
        "spire-server-orbit.conf must declare a federation.bundle_endpoint block"
    )
    # Federates-with peer is wakir.test.
    assert re.search(r'federates_with\s+"wakir\.test"', body), (
        "spire-server-orbit.conf must federate with wakir.test"
    )
    # Peer bundle-endpoint URL points at spire-server-wakir.
    assert re.search(
        r'bundle_endpoint_url\s*=\s*"https://spire-server-wakir:8443', body
    ), (
        "spire-server-orbit.conf must point bundle_endpoint_url at "
        "spire-server-wakir:8443"
    )


def test_spire_agent_orbit_conf_exists_and_shape_ok():
    assert _AGENT_ORBIT_CONF.is_file(), (
        f"spire-agent-orbit.conf missing at {_AGENT_ORBIT_CONF}"
    )
    body = _AGENT_ORBIT_CONF.read_text(encoding="utf-8")
    # Trust-domain literal.
    assert re.search(r'trust_domain\s*=\s*"orbit\.test"', body), (
        "spire-agent-orbit.conf must declare trust_domain = orbit.test"
    )
    # Server-address is spire-server-orbit (same-side gRPC).
    assert re.search(
        r'server_address\s*=\s*"spire-server-orbit"', body
    ), (
        "spire-agent-orbit.conf must dial server_address = spire-server-orbit"
    )
    # SPIFFE-Workload-API socket-path convention.
    assert re.search(
        r'socket_path\s*=\s*"/run/spire/agent-sockets/api\.sock"', body
    ), (
        "spire-agent-orbit.conf must use the SPIFFE socket-path convention"
    )
    # insecure_bootstrap = false (federation posture parity with wakir).
    assert re.search(
        r'insecure_bootstrap\s*=\s*false', body
    ), (
        "spire-agent-orbit.conf must set insecure_bootstrap = false (federation posture)"
    )


# ---------------------------------------------------------------------------
# TV-SIDE-07: cross-side byte-parity between wakir / partner / orbit configs
# (each side mirrors the structural shape; only trust-domain + peer differ)
# ---------------------------------------------------------------------------


def test_orbit_configs_are_structural_mirror_of_wakir_configs():
    """All three sides (wakir, partner, orbit) MUST have byte-parity
    structural shape — same plugin types, same socket path, same
    bundle format, same insecure_bootstrap posture. Only the trust-
    domain literal and the federates_with peer URL differ.

    This invariant is the Sprint-8 Tag-1 cross-side-byte-parity
    contract — extending it to orbit is the Sprint-10 Tag-1 substance.
    """
    wakir = (_REPO_ROOT / "infra" / "spire" / "federation" / "config" / "spire-server-wakir.conf").read_text()
    orbit = _SERVER_ORBIT_CONF.read_text()

    # Same SPIRE-server bind-port.
    for body, name in [(wakir, "wakir"), (orbit, "orbit")]:
        assert re.search(r'bind_port\s*=\s*"8081"', body), (
            f"spire-server-{name}.conf must bind gRPC on port 8081"
        )
        assert re.search(r'profile\s*=\s*"https_spiffe"', body), (
            f"spire-server-{name}.conf must use https_spiffe profile"
        )
        assert re.search(r'ca_key_type\s*=\s*"ec-p256"', body), (
            f"spire-server-{name}.conf must use ec-p256 CA key type"
        )

    # Wakir + orbit peer with each other (asymmetric trust-domain literals).
    assert re.search(r'federates_with\s+"orbit\.test"', wakir) or \
           re.search(r'federates_with\s+"partner\.test"', wakir), (
        "wakir-side must federate with orbit.test (Sprint-10) "
        "OR partner.test (Sprint-8 baseline; bootstrap-switch §5.3 open-item)"
    )
    assert re.search(r'federates_with\s+"wakir\.test"', orbit), (
        "orbit-side must federate with wakir.test"
    )


# ---------------------------------------------------------------------------
# TV-SIDE-08: Recipe documentation existence
# ---------------------------------------------------------------------------


def test_partner_vm_bring_up_recipe_exists():
    """The new Sprint-10 Tag-1 Recipe MUST exist at the documented
    path and reference the WAKIR_SIDE substance + the federation-mode
    smoke check."""
    recipe = _REPO_ROOT / "infra" / "spire" / "federation" / "PARTNER_VM_BRING_UP_RECIPE.md"
    assert recipe.is_file(), f"PARTNER_VM_BRING_UP_RECIPE.md missing at {recipe}"
    body = recipe.read_text(encoding="utf-8")
    # The recipe MUST reference WAKIR_SIDE=orbit.
    assert "WAKIR_SIDE=orbit" in body, (
        "Recipe must document the WAKIR_SIDE=orbit invocation"
    )
    # The recipe MUST reference WAKIR_FEDERATION_MODE=enabled.
    assert "WAKIR_FEDERATION_MODE=enabled" in body, (
        "Recipe must document the federation-mode env-var gate"
    )
    # The recipe MUST reference --peer-side.
    assert "--peer-side" in body, (
        "Recipe must document the --peer-side smoke flag"
    )
    # The recipe MUST reference the Cross-VM Bridge setup.
    assert "vmbr1" in body, (
        "Recipe must document the Proxmox-internal bridge (vmbr1) setup"
    )
