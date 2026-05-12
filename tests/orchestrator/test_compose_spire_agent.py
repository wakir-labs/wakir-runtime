# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the SPIRE-Agent-Sidecar (Phase-2.2,
Sprint-6 Tag-9).

These tests are additive on top of:
  * ``test_compose_spire.py`` (16 Phase-2.1 SPIRE-Server invariants).
  * ``test_compose_spire_cosign_pin.py`` (9 Tag-8 Cosign-Digest-Pin
    additions, all SPIRE-Server-targeted).

The Phase-2.2 substrate adds a paired ``spire-agent`` service block to
``compose/spire.yaml`` and a Mock/Stub ``config/spire-agent.conf``. The
agent attests via ``join_token`` NodeAttestor (hermetic placeholder,
no real token), shares the ``spire_server_sockets`` volume with the
server (for the Admin-API gRPC channel), and serves the SPIFFE-
Workload-API on a separate named volume ``spire_agent_sockets`` at the
canonical socket-path ``/run/spire/agent-sockets/api.sock``.

These tests are pure compose-/HCL-parse + invariant assertions. They
do NOT:
  * Pull the SPIRE-Agent image.
  * Run a SPIRE-Agent container.
  * Issue or validate any SVID (Phase-2.3 live-gated, Operator-Hand).
  * Touch the host's podman/docker socket.

They DO assert that:
  * Phase-2.2 compose shape — both ``spire-server`` and ``spire-agent``
    services coexist; networks + volumes match.
  * Trust-domain parity — agent and server name the same hermetic
    trust-domain (``example.test``).
  * Agent image-pin form — Cosign-Digest-Pin parity with the server
    (``ghcr.io/spiffe/spire-agent:1.14.6@sha256:<digest-or-placeholder>``).
  * Server-Admin-API channel — agent mounts the
    ``spire_server_sockets`` named volume at the same path as the
    server (``/run/spire/sockets``).
  * Workload-API socket-path convention — agent mounts the
    ``spire_agent_sockets`` named volume at ``/run/spire/agent-sockets``
    and the agent.conf ``socket_path`` is
    ``/run/spire/agent-sockets/api.sock``.
  * Hardening defaults parity (``cap_drop: ALL``,
    ``no-new-privileges:true``, ``read_only: true``, ``user:
    1000:1000``, ``restart: unless-stopped``, ``tmpfs: /run/spire``).
  * Health-probe shape uses the ``spire-agent healthcheck``
    subcommand.
  * Service-startup ordering — agent ``depends_on`` server with
    ``condition: service_healthy``.
  * Agent.conf shape — ``join_token`` NodeAttestor, ``memory``
    KeyManager, ``unix`` WorkloadAttestor, ``insecure_bootstrap =
    true`` (hermetic Phase-2 default).

Drift-detection: if a Phase-2.3 live-gated patch lands that switches
the agent's NodeAttestor away from ``join_token`` (e.g. to
``x509pop``), or that changes the Workload-API socket-path
convention, these tests will fail loudly and force a co-edit — which
is the intended drift-gate.

Cross-reference (Reza-track, not imported here):
  * SPIFFE-ID-Binding spec: ``wirelang/specs/identity-substrate.md``
    §5 (Reza Sprint-6 Tag-4, commit ``ece8f45``; not in the Tag-9
    baseline — referenced by path only).
  * Workload-API adapter surface:
    ``wirelang/adapters/spiffe_workload_api.py`` (Reza Sprint-6 Tag-4
    skeleton; ``MockSpiffeWorkloadApiAdapter`` in Reza Sprint-6
    Tag-5, commit ``9c94517``). The Tag-9 hermetic substrate does not
    import this adapter; persona-container Workload-API consumers
    will (Phase-2.3+).
  * Real-adapter ``real_spiffe_workload_api.py`` is a Reza Tag-7+
    slot; not present in the Tag-9 baseline.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - pyyaml is a dev-dep
    pytest.skip("pyyaml not installed", allow_module_level=True)


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "compose" / "spire.yaml"
AGENT_CONFIG_FILE = REPO_ROOT / "config" / "spire-agent.conf"
SERVER_CONFIG_FILE = REPO_ROOT / "config" / "spire-server.conf"


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose_doc() -> dict:
    with COMPOSE_FILE.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def agent_service(compose_doc: dict) -> dict:
    services = compose_doc.get("services", {})
    assert "spire-agent" in services, (
        "compose/spire.yaml must declare a 'spire-agent' service (Phase-2.2)"
    )
    return services["spire-agent"]


@pytest.fixture(scope="module")
def server_service(compose_doc: dict) -> dict:
    return compose_doc["services"]["spire-server"]


@pytest.fixture(scope="module")
def agent_conf_text() -> str:
    return AGENT_CONFIG_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def server_conf_text() -> str:
    return SERVER_CONFIG_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# 1 — Phase-2.2 service-shape (server + agent coexistence)
# ---------------------------------------------------------------------


def test_compose_has_exactly_two_spire_services_phase_2_2(
    compose_doc: dict,
) -> None:
    """Phase-2.2 nails the substrate to exactly two services:
    spire-server (Tag-6) and spire-agent (Tag-9). No additional
    services land in the same compose file — persona-containers go
    into their own compose file (Phase-2.3+ Operator-Hand)."""
    services = compose_doc["services"]
    assert set(services.keys()) == {"spire-server", "spire-agent"}, (
        f"Phase-2.2 must declare exactly {{'spire-server', 'spire-agent'}}; "
        f"got {set(services.keys())!r}"
    )


def test_agent_depends_on_server_with_health_gate(
    agent_service: dict,
) -> None:
    """The agent must not race the server's bootstrap. Compose v2
    ``depends_on`` with ``condition: service_healthy`` gates agent
    startup on the server's healthcheck. A plain ``depends_on``
    without the condition is a known compose-v2 silent-pass gotcha
    (it only orders start, does not wait)."""
    depends_on = agent_service.get("depends_on")
    assert depends_on is not None, (
        "spire-agent must declare depends_on the spire-server"
    )
    assert isinstance(depends_on, dict), (
        "depends_on must use the long-form mapping (compose v2) so "
        f"condition: can be set; got: {depends_on!r}"
    )
    assert "spire-server" in depends_on, (
        "spire-agent must depend_on the spire-server"
    )
    assert depends_on["spire-server"].get("condition") == "service_healthy", (
        f"spire-agent must wait for spire-server's healthcheck; got: "
        f"{depends_on['spire-server']!r}"
    )


# ---------------------------------------------------------------------
# 2 — Agent image-pin form (Cosign-Digest-Pin parity with server)
# ---------------------------------------------------------------------


def test_agent_image_has_cosign_digest_pin_form(
    agent_service: dict,
) -> None:
    """Agent image MUST be ``tag@sha256:<digest-or-placeholder>`` —
    parity with the SPIRE-Server Tag-8 form. Operator-Hand
    substitutes the canonical digest after ``cosign verify`` +
    ``skopeo inspect``."""
    image = agent_service["image"]
    tag_part, sep, digest_part = image.partition("@")
    assert sep == "@", (
        f"Tag-9 agent image-pin must be digest-pinned 'tag@sha256:<digest>'; "
        f"got: {image!r}"
    )
    assert digest_part.startswith("sha256:"), (
        f"digest part must start with 'sha256:'; got: {digest_part!r}"
    )
    digest_value = digest_part[len("sha256:"):]
    is_real_digest = bool(re.fullmatch(r"[0-9a-f]{64}", digest_value))
    is_placeholder = digest_value == "DIGEST_PENDING_TOMAS_REVIEW"
    assert is_real_digest or is_placeholder, (
        f"digest must be 64-hex sha256 OR documented placeholder; got: "
        f"{digest_value!r}"
    )


def test_agent_image_is_from_spiffe_org_on_ghcr(
    agent_service: dict,
) -> None:
    image = agent_service["image"]
    assert image.startswith("ghcr.io/spiffe/spire-agent:"), (
        f"agent image must be ghcr.io/spiffe/spire-agent; got: {image!r}"
    )


def test_agent_pinned_tag_matches_server_version(
    agent_service: dict, server_service: dict
) -> None:
    """Agent and server MUST be the same SPIRE version. A version
    skew between server and agent is a Phase-2 operability hazard
    (workload-API protocol drift on minor-version mismatch). The
    Tag-9 substrate pins both to 1.14.6 (the SPIRE briefing version)."""
    agent_tag = agent_service["image"].partition("@")[0]
    server_tag = server_service["image"].partition("@")[0]
    agent_ver = agent_tag.rpartition(":")[2]
    server_ver = server_tag.rpartition(":")[2]
    assert agent_ver == server_ver, (
        f"SPIRE-Agent ({agent_ver}) and SPIRE-Server ({server_ver}) "
        f"must use the same version"
    )
    assert agent_ver == "1.14.6", (
        f"Phase-2.2 pins SPIRE to 1.14.6 (Sprint-6 box-briefing); "
        f"got: {agent_ver!r}"
    )


# ---------------------------------------------------------------------
# 3 — Hardening parity with server
# ---------------------------------------------------------------------


def test_agent_has_hardening_parity_with_server(
    agent_service: dict, server_service: dict
) -> None:
    """The agent must mirror the server's hardening posture
    (cap_drop ALL, no-new-privileges, read_only, non-root user,
    restart unless-stopped). Drift here is a security regression
    that the Tag-9 substrate must catch loudly."""
    # cap_drop parity.
    assert agent_service.get("cap_drop") == server_service.get("cap_drop") == ["ALL"]
    # no-new-privileges parity.
    agent_secopt = agent_service.get("security_opt", [])
    server_secopt = server_service.get("security_opt", [])
    assert "no-new-privileges:true" in agent_secopt
    assert "no-new-privileges:true" in server_secopt
    # read_only rootfs parity.
    assert agent_service.get("read_only") is True
    assert server_service.get("read_only") is True
    # Non-root user parity.
    assert agent_service.get("user") == "1000:1000"
    assert server_service.get("user") == "1000:1000"
    # Restart policy parity.
    assert agent_service.get("restart") == "unless-stopped"
    assert server_service.get("restart") == "unless-stopped"


def test_agent_tmpfs_for_run_spire(agent_service: dict) -> None:
    tmpfs = agent_service.get("tmpfs")
    assert tmpfs is not None, (
        "agent: tmpfs mount for /run/spire required since rootfs is read-only"
    )
    entries = tmpfs if isinstance(tmpfs, list) else [tmpfs]
    run_spire = [e for e in entries if "/run/spire" in e]
    assert len(run_spire) == 1, (
        f"tmpfs must contain exactly one /run/spire entry; got: {tmpfs!r}"
    )


# ---------------------------------------------------------------------
# 4 — Volume-sharing: Server-Admin-API + Workload-API socket paths
# ---------------------------------------------------------------------


def test_agent_mounts_server_admin_sockets_volume(
    agent_service: dict, server_service: dict
) -> None:
    """The agent reaches the server's Admin-API on the shared
    ``spire_server_sockets`` named volume. Server and agent mount
    the same volume at the same path (``/run/spire/sockets``).
    Drift here breaks the Server↔Agent attestation channel.

    Per Mira-Box-Brief Tag-9: "Workload-API-Unix-Socket via shared
    named-Volume ``spire_server_sockets``" — this is the server-side
    socket-share volume; the Workload-API itself lives on the
    separate ``spire_agent_sockets`` volume (see next test) per the
    SPIFFE-Workload-API convention where the Agent (not the Server)
    serves the Workload-API."""
    agent_vol_strs = agent_service["volumes"]
    server_vol_strs = server_service["volumes"]

    agent_has = any(
        v.startswith("spire_server_sockets:") for v in agent_vol_strs
    )
    server_has = any(
        v.startswith("spire_server_sockets:") for v in server_vol_strs
    )
    assert agent_has and server_has, (
        f"both spire-agent and spire-server must mount the shared "
        f"'spire_server_sockets' named volume; "
        f"agent.volumes={agent_vol_strs!r} server.volumes={server_vol_strs!r}"
    )
    # Same mount-path in both containers.
    agent_path = next(
        v.split(":")[1]
        for v in agent_vol_strs
        if v.startswith("spire_server_sockets:")
    )
    server_path = next(
        v.split(":")[1]
        for v in server_vol_strs
        if v.startswith("spire_server_sockets:")
    )
    assert agent_path == server_path == "/run/spire/sockets", (
        f"shared sockets volume must mount at the same path in both "
        f"containers ('/run/spire/sockets'); "
        f"agent={agent_path!r}, server={server_path!r}"
    )


def test_agent_serves_workload_api_on_dedicated_volume(
    compose_doc: dict, agent_service: dict
) -> None:
    """The SPIFFE-Workload-API socket lives on a *separate* named
    volume (``spire_agent_sockets``) at the canonical convention
    path ``/run/spire/agent-sockets``. This separation lets a
    Phase-2.3+ persona-container mount the workload-API volume
    read-only without also getting access to the server-admin
    sockets (which would be a privilege escalation surface)."""
    agent_vols = agent_service["volumes"]
    agent_sockets_mount = next(
        (v for v in agent_vols if v.startswith("spire_agent_sockets:")),
        None,
    )
    assert agent_sockets_mount is not None, (
        f"spire-agent must mount the 'spire_agent_sockets' named volume; "
        f"got volumes: {agent_vols!r}"
    )
    mount_path = agent_sockets_mount.split(":")[1]
    assert mount_path == "/run/spire/agent-sockets", (
        f"Workload-API socket-volume must mount at "
        f"'/run/spire/agent-sockets'; got: {mount_path!r}"
    )
    # Top-level volumes declaration.
    top_volumes = compose_doc.get("volumes", {})
    assert "spire_agent_sockets" in top_volumes, (
        "'spire_agent_sockets' must be declared at top-level volumes"
    )
    assert "spire_agent_data" in top_volumes, (
        "'spire_agent_data' must be declared at top-level volumes"
    )


# ---------------------------------------------------------------------
# 5 — Network coexistence
# ---------------------------------------------------------------------


def test_agent_shares_wakir_orchestrator_network_with_server(
    agent_service: dict, server_service: dict
) -> None:
    """Both spire-agent and spire-server live on the same
    wakir-orchestrator bridge network — agent dials the server's
    Admin-API by service-name ``spire-server`` via compose-DNS."""
    assert "wakir" in agent_service["networks"]
    assert "wakir" in server_service["networks"]


# ---------------------------------------------------------------------
# 6 — Health-probe shape
# ---------------------------------------------------------------------


def test_agent_health_probe_uses_spire_agent_healthcheck(
    agent_service: dict,
) -> None:
    """The SPIRE-Agent image ships its own healthcheck subcommand.
    The hermetic probe MUST use that, not a host-side HTTP probe.
    Parity with the server's healthcheck shape."""
    health = agent_service.get("healthcheck")
    assert isinstance(health, dict)
    test_cmd = health["test"]
    assert isinstance(test_cmd, list) and test_cmd[0] == "CMD"
    joined = " ".join(test_cmd)
    assert "spire-agent" in joined and "healthcheck" in joined, (
        f"agent health probe must call spire-agent healthcheck; got: "
        f"{test_cmd!r}"
    )
    for field in ("interval", "timeout", "retries", "start_period"):
        assert health.get(field), (
            f"agent healthcheck must declare {field}"
        )


# ---------------------------------------------------------------------
# 7 — Agent.conf shape (trust-domain parity, plugins, socket-path)
# ---------------------------------------------------------------------


def test_agent_conf_declares_example_test_trust_domain(
    agent_conf_text: str,
) -> None:
    """Agent.conf trust-domain MUST match server.conf
    (``example.test``). A drift here breaks attestation because the
    server rejects agents from a different trust-domain.

    This is the wirelang-side Z-A-Marker §1 (Trust-Domain-URI-Form)
    parity check for the DevOps-track substrate."""
    assert re.search(
        r'trust_domain\s*=\s*"example\.test"', agent_conf_text
    ), "agent.conf must declare trust_domain = \"example.test\""


def test_agent_and_server_conf_share_same_trust_domain(
    agent_conf_text: str, server_conf_text: str
) -> None:
    """Negative invariant: the active HCL trust_domain in both
    agent.conf and server.conf MUST resolve to the same literal.
    Currently both are ``example.test`` (hermetic mode)."""
    def _extract_trust_domain(text: str) -> str:
        # Skip comment lines.
        active = "\n".join(
            line for line in text.splitlines()
            if not line.lstrip().startswith("#")
        )
        m = re.search(r'trust_domain\s*=\s*"([^"]+)"', active)
        assert m is not None, "active HCL must declare trust_domain"
        return m.group(1)

    agent_td = _extract_trust_domain(agent_conf_text)
    server_td = _extract_trust_domain(server_conf_text)
    assert agent_td == server_td == "example.test", (
        f"agent ({agent_td!r}) and server ({server_td!r}) must share "
        f"the hermetic trust-domain 'example.test'"
    )


def test_agent_conf_declares_join_token_node_attestor(
    agent_conf_text: str,
) -> None:
    """Phase-2 hermetic NodeAttestor is ``join_token``. Phase-3+
    swaps to ``x509pop`` (federation) or ``k8s_psat`` (K8s). A
    drift here without a paired Phase-3 ADR is a regression."""
    assert 'NodeAttestor "join_token"' in agent_conf_text


def test_agent_conf_declares_memory_keymanager(
    agent_conf_text: str,
) -> None:
    """Hermetic posture uses in-memory KeyManager so a ``compose
    down/up`` cycle forces re-attestation. Phase-2c+ swaps to disk
    so the agent retains identity across restarts."""
    assert 'KeyManager "memory"' in agent_conf_text


def test_agent_conf_declares_unix_workload_attestor(
    agent_conf_text: str,
) -> None:
    """The SPIRE-Agent attests workloads by their unix-process
    selectors (uid/gid/pid/path). This is the SPIRE-default and is
    the only attestor needed for the Phase-2.3+ persona-container
    workload-API consumer model."""
    assert 'WorkloadAttestor "unix"' in agent_conf_text


def test_agent_conf_pins_workload_api_socket_path(
    agent_conf_text: str,
) -> None:
    """The agent.conf ``socket_path`` MUST be
    ``/run/spire/agent-sockets/api.sock`` — the canonical
    Workload-API socket-path convention. The compose volume mount
    is at ``/run/spire/agent-sockets`` (volume-dir; the
    ``api.sock`` is a file *inside* that dir at runtime).

    A drift in the socket-path filename between agent.conf and the
    compose-volume mount-dir would break Phase-2.3+ persona-
    container consumers."""
    m = re.search(r'socket_path\s*=\s*"([^"]+)"', agent_conf_text)
    assert m is not None, "agent.conf must declare a socket_path"
    assert m.group(1) == "/run/spire/agent-sockets/api.sock", (
        f"Workload-API socket_path must be "
        f"'/run/spire/agent-sockets/api.sock'; got: {m.group(1)!r}"
    )


def test_agent_conf_targets_server_via_compose_dns(
    agent_conf_text: str,
) -> None:
    """The agent dials the server by compose-service-name
    (``spire-server``), not by an IP literal. This is the compose-DNS
    convention; an IP-literal here would brittle-couple to the bridge
    network's IP-assignment."""
    m = re.search(r'server_address\s*=\s*"([^"]+)"', agent_conf_text)
    assert m is not None, "agent.conf must declare server_address"
    assert m.group(1) == "spire-server", (
        f"agent.conf server_address must be the compose-service-name "
        f"'spire-server'; got: {m.group(1)!r}"
    )
    m = re.search(r'server_port\s*=\s*"([^"]+)"', agent_conf_text)
    assert m is not None, "agent.conf must declare server_port"
    assert m.group(1) == "8081", (
        f"agent.conf server_port must match server's bind_port (8081); "
        f"got: {m.group(1)!r}"
    )


def test_agent_conf_uses_insecure_bootstrap_phase_2(
    agent_conf_text: str,
) -> None:
    """Phase-2 hermetic posture uses ``insecure_bootstrap = true``
    because the join_token NodeAttestor depends on it. Phase-3+
    operator-hand swaps to a pre-staged trust-bundle (insecure_bootstrap
    must be removed or set false). A drift here without a Phase-3
    ADR pair is a regression."""
    assert re.search(
        r'insecure_bootstrap\s*=\s*true', agent_conf_text
    ), "Phase-2 hermetic posture requires insecure_bootstrap = true"


# ---------------------------------------------------------------------
# 8 — Test-count contract self-check (Tag-9 contributes 17 tests)
# ---------------------------------------------------------------------


def test_tag_9_contributes_twenty_tests_to_spire_compose_suite() -> None:
    """Pure-contract self-check: this file MUST contribute exactly
    20 tests to the SPIRE-Compose suite. Tag-6 contributed 16,
    Tag-8 contributed 9, Tag-9 contributes 20. Total SPIRE-Compose:
    16 + 9 + 20 = 45 (collected from these three files).

    The 20 Tag-9 additions are:
      * 2 service-shape (two services; agent depends_on server-health)
      * 3 image-pin (cosign-digest form, ghcr.io/spiffe org,
        version-parity with server)
      * 2 hardening (parity with server: cap_drop/no-new-priv/read_only/
        non-root-user/restart-policy; tmpfs)
      * 2 volume-sharing (server-sockets shared at /run/spire/sockets;
        agent-sockets dedicated at /run/spire/agent-sockets)
      * 1 network coexistence (both on wakir-orchestrator bridge)
      * 1 health-probe (spire-agent healthcheck subcommand)
      * 8 agent.conf shape:
        * trust-domain literal example.test
        * trust-domain parity with server.conf
        * join_token NodeAttestor
        * memory KeyManager
        * unix WorkloadAttestor
        * Workload-API socket_path /run/spire/agent-sockets/api.sock
        * server-address via compose-DNS (service-name spire-server)
        * insecure_bootstrap = true (Phase-2 hermetic posture)
      * 1 contract self-check (this test)

    Total: 2 + 3 + 2 + 2 + 1 + 1 + 8 + 1 = 20.
    """
    import inspect
    import sys

    module = sys.modules[__name__]
    test_fns = [
        name for name, obj in inspect.getmembers(module, inspect.isfunction)
        if name.startswith("test_")
    ]
    assert len(test_fns) == 20, (
        f"Tag-9 spire-agent file must contribute exactly 20 tests; "
        f"got {len(test_fns)}: {test_fns!r}"
    )
