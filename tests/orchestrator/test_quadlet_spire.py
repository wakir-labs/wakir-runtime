# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Hermetic parity tests for the Phase-2 Sprint-6 Tag-11 Quadlet dual-
# track SPIRE unit files (quadlet/wakir-spire-server.container,
# quadlet/wakir-spire-agent.container, plus four volume sidecars)
# against the primary compose contract surface compose/spire.yaml.
#
# Goal: drift-detection. When the compose image digest pin changes, or
# the volume / hardening / health-probe shape changes, the Quadlet
# files must follow in the same commit. These tests fail hermetically
# if drift is introduced; no container engine, no systemd, no live
# SPIRE-Server, no live SPIRE-Agent, no live SVID issuance.
#
# Scope: byte-precise parity for fields that operators see (image
# digest pin form, container name, port publication, volume mount,
# network attach, capability drop, no-new-privileges, read-only
# rootfs, user, tmpfs, health-probe subcommand). Restart-policy nuance
# (compose unless-stopped vs systemd on-failure) is documented in the
# wakir-nats.container parity test and reused here; the test only
# asserts that both surfaces declare *some* restart-on-failure policy.
#
# Pattern: mirrors the Tag-1 NATS quadlet parity convention from
# tests/orchestrator/test_quadlet_nats.py.

from __future__ import annotations

import configparser
import re
from pathlib import Path

import pytest

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - pyyaml is a dev-dep
    pytest.skip("pyyaml not installed", allow_module_level=True)


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "compose" / "spire.yaml"
QUADLET_DIR = REPO_ROOT / "quadlet"
QUADLET_SERVER = QUADLET_DIR / "wakir-spire-server.container"
QUADLET_AGENT = QUADLET_DIR / "wakir-spire-agent.container"
QUADLET_SERVER_DATA = QUADLET_DIR / "wakir-spire-server-data.volume"
QUADLET_SERVER_SOCKETS = QUADLET_DIR / "wakir-spire-server-sockets.volume"
QUADLET_AGENT_DATA = QUADLET_DIR / "wakir-spire-agent-data.volume"
QUADLET_AGENT_SOCKETS = QUADLET_DIR / "wakir-spire-agent-sockets.volume"


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _read_ini(path: Path) -> configparser.ConfigParser:
    """Parse a Quadlet unit file with the systemd ini-style parser.

    Quadlet units allow duplicate keys in a single section (e.g. multiple
    Volume= lines). ConfigParser's ``strict=False`` permits duplicates;
    the parsed value of a duplicated key is the *last* occurrence, so
    duplicate-aware fields are re-parsed via ``_section_lines`` below.
    """
    parser = configparser.ConfigParser(
        strict=False,
        interpolation=None,
        comment_prefixes=("#", ";"),
        allow_no_value=True,
    )
    parser.read(path, encoding="utf-8")
    return parser


def _section_lines(path: Path, section: str, key: str) -> list[str]:
    """Return every value for ``key`` in ``section`` of a Quadlet unit.

    Quadlet allows duplicate-key entries (multiple ``Volume=`` lines
    map to multiple bind-mounts / named-volumes). The standard
    ConfigParser last-write-wins semantics drop duplicates, so this
    helper does a raw text scan that respects section boundaries.
    """
    text = path.read_text(encoding="utf-8")
    values: list[str] = []
    in_target_section = False
    section_marker = f"[{section}]"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_target_section = line == section_marker
            continue
        if not in_target_section:
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            values.append(v.strip())
    return values


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose_doc() -> dict:
    with COMPOSE_FILE.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    assert isinstance(doc, dict)
    return doc


@pytest.fixture(scope="module")
def server_unit() -> configparser.ConfigParser:
    return _read_ini(QUADLET_SERVER)


@pytest.fixture(scope="module")
def agent_unit() -> configparser.ConfigParser:
    return _read_ini(QUADLET_AGENT)


# ---------------------------------------------------------------------
# 1 — File presence + section shape
# ---------------------------------------------------------------------


def test_quadlet_spire_unit_files_are_present() -> None:
    """Dual-track contract: runnable Quadlet companions alongside the
    compose surface for both SPIRE-Server and SPIRE-Agent plus the
    four named-volume sidecars (two for server: data + sockets; two
    for agent: data + sockets)."""
    assert QUADLET_SERVER.exists(), "quadlet/wakir-spire-server.container is missing"
    assert QUADLET_AGENT.exists(), "quadlet/wakir-spire-agent.container is missing"
    assert QUADLET_SERVER_DATA.exists(), "wakir-spire-server-data.volume missing"
    assert QUADLET_SERVER_SOCKETS.exists(), "wakir-spire-server-sockets.volume missing"
    assert QUADLET_AGENT_DATA.exists(), "wakir-spire-agent-data.volume missing"
    assert QUADLET_AGENT_SOCKETS.exists(), "wakir-spire-agent-sockets.volume missing"


@pytest.mark.parametrize("unit_fixture", ["server_unit", "agent_unit"])
def test_quadlet_spire_unit_has_expected_sections(
    request: pytest.FixtureRequest, unit_fixture: str
) -> None:
    unit = request.getfixturevalue(unit_fixture)
    assert "Unit" in unit.sections()
    assert "Container" in unit.sections()
    assert "Service" in unit.sections()
    assert "Install" in unit.sections()


# ---------------------------------------------------------------------
# 2 — Image digest pin parity (Cosign-Digest-Pin form, Pfad B)
# ---------------------------------------------------------------------

# Accepts either the placeholder token DIGEST_PENDING_TOMAS_REVIEW
# (pre-Cross-Review-Zone-C-ack) or a 64-hex sha256 digest. Same
# acceptance pattern as the compose-side test_compose_spire_cosign_pin
# suite (Tag-8 rebase).
_DIGEST_OR_PLACEHOLDER = re.compile(
    r"@sha256:(?:[0-9a-f]{64}|DIGEST_PENDING_TOMAS_REVIEW)$"
)


def test_quadlet_spire_server_image_matches_compose(
    compose_doc: dict, server_unit: configparser.ConfigParser
) -> None:
    compose_image = compose_doc["services"]["spire-server"]["image"]
    quadlet_image = server_unit.get("Container", "Image")
    assert compose_image == quadlet_image, (
        f"Quadlet SPIRE-Server Image= must match compose byte-precise. "
        f"compose: {compose_image!r}, quadlet: {quadlet_image!r}"
    )
    assert _DIGEST_OR_PLACEHOLDER.search(quadlet_image), (
        f"Quadlet SPIRE-Server image must carry Cosign-Digest-Pin form "
        f"(sha256:<64-hex> or placeholder); got: {quadlet_image!r}"
    )


def test_quadlet_spire_agent_image_matches_compose(
    compose_doc: dict, agent_unit: configparser.ConfigParser
) -> None:
    compose_image = compose_doc["services"]["spire-agent"]["image"]
    quadlet_image = agent_unit.get("Container", "Image")
    assert compose_image == quadlet_image, (
        f"Quadlet SPIRE-Agent Image= must match compose byte-precise. "
        f"compose: {compose_image!r}, quadlet: {quadlet_image!r}"
    )
    assert _DIGEST_OR_PLACEHOLDER.search(quadlet_image), (
        f"Quadlet SPIRE-Agent image must carry Cosign-Digest-Pin form; "
        f"got: {quadlet_image!r}"
    )


def test_quadlet_spire_version_parity_server_and_agent(
    server_unit: configparser.ConfigParser,
    agent_unit: configparser.ConfigParser,
) -> None:
    """SPIRE-Server and SPIRE-Agent are released as a paired binary set
    upstream; the version-tag MUST match between the two Quadlet units.
    Parity with the compose-side check in test_compose_spire_agent.py."""
    version_re = re.compile(r":([0-9]+\.[0-9]+\.[0-9]+)@")
    server_match = version_re.search(server_unit.get("Container", "Image"))
    agent_match = version_re.search(agent_unit.get("Container", "Image"))
    assert server_match, "SPIRE-Server image must have a SemVer tag"
    assert agent_match, "SPIRE-Agent image must have a SemVer tag"
    assert server_match.group(1) == agent_match.group(1), (
        f"Server/Agent version drift: server={server_match.group(1)} "
        f"vs agent={agent_match.group(1)}"
    )


# ---------------------------------------------------------------------
# 3 — Container name parity
# ---------------------------------------------------------------------


def test_quadlet_spire_server_container_name(
    compose_doc: dict, server_unit: configparser.ConfigParser
) -> None:
    compose_name = compose_doc["services"]["spire-server"]["container_name"]
    quadlet_name = server_unit.get("Container", "ContainerName")
    assert compose_name == quadlet_name == "wakir-spire-server"


def test_quadlet_spire_agent_container_name(
    compose_doc: dict, agent_unit: configparser.ConfigParser
) -> None:
    compose_name = compose_doc["services"]["spire-agent"]["container_name"]
    quadlet_name = agent_unit.get("Container", "ContainerName")
    assert compose_name == quadlet_name == "wakir-spire-agent"


# ---------------------------------------------------------------------
# 4 — Port publication parity (loopback-only)
# ---------------------------------------------------------------------


def test_quadlet_spire_server_port_is_loopback_only(
    compose_doc: dict,
) -> None:
    """Mirror of compose 127.0.0.1:8081:8081 (Tag-8 explicit ports
    addition). The hermetic Phase-2.1 substrate must NEVER expose the
    SPIRE-Server gRPC to a non-loopback interface."""
    publish_ports = _section_lines(QUADLET_SERVER, "Container", "PublishPort")
    assert publish_ports, "SPIRE-Server Quadlet must declare PublishPort="
    for port in publish_ports:
        assert port.startswith("127.0.0.1:"), (
            f"Phase-2.1 invariant: SPIRE-Server PublishPort MUST bind "
            f"loopback-only; got: {port!r}"
        )
    quadlet_host_ports = {p.split(":")[1] for p in publish_ports}
    assert "8081" in quadlet_host_ports, "gRPC port 8081 must be published"

    compose_ports = compose_doc["services"]["spire-server"]["ports"]
    compose_host_ports = {entry.split(":")[1] for entry in compose_ports}
    assert quadlet_host_ports == compose_host_ports, (
        f"port-publication drift: compose={compose_host_ports} vs "
        f"quadlet={quadlet_host_ports}"
    )


def test_quadlet_spire_agent_does_not_publish_ports() -> None:
    """The SPIRE-Agent does not bind a TCP port — it serves the
    Workload-API on a Unix-socket and reaches the SPIRE-Server via
    a shared volume. Parity with the compose surface where the
    spire-agent service block has no ``ports:`` field."""
    publish_ports = _section_lines(QUADLET_AGENT, "Container", "PublishPort")
    assert not publish_ports, (
        f"SPIRE-Agent must NOT publish any host port (parity with "
        f"compose); got: {publish_ports!r}"
    )


# ---------------------------------------------------------------------
# 5 — Exec command parity
# ---------------------------------------------------------------------


def test_quadlet_spire_server_exec_points_to_server_conf(
    compose_doc: dict, server_unit: configparser.ConfigParser
) -> None:
    exec_line = server_unit.get("Container", "Exec")
    assert "run" in exec_line
    assert "/etc/spire/server/server.conf" in exec_line
    compose_cmd = compose_doc["services"]["spire-server"]["command"]
    assert "run" in compose_cmd
    assert "/etc/spire/server/server.conf" in compose_cmd


def test_quadlet_spire_agent_exec_points_to_agent_conf(
    compose_doc: dict, agent_unit: configparser.ConfigParser
) -> None:
    exec_line = agent_unit.get("Container", "Exec")
    assert "run" in exec_line
    assert "/etc/spire/agent/agent.conf" in exec_line
    compose_cmd = compose_doc["services"]["spire-agent"]["command"]
    assert "run" in compose_cmd
    assert "/etc/spire/agent/agent.conf" in compose_cmd


# ---------------------------------------------------------------------
# 6 — Volume mount parity
# ---------------------------------------------------------------------


def test_quadlet_spire_server_volumes_match_compose(
    compose_doc: dict,
) -> None:
    """Server must mount: (1) read-only config bind-mount,
    (2) spire-server-data named-volume at /var/lib/spire/server,
    (3) spire-server-sockets shared-named-volume at /run/spire/sockets.
    Parity with compose services.spire-server.volumes."""
    quadlet_volumes = _section_lines(QUADLET_SERVER, "Container", "Volume")
    assert len(quadlet_volumes) == 3, (
        f"SPIRE-Server Quadlet must declare exactly 3 Volume= entries "
        f"(config bind, data volume, sockets volume); got: {quadlet_volumes!r}"
    )

    # Config bind-mount: host-path:container-path:ro[,...]
    config_mounts = [v for v in quadlet_volumes if "server.conf" in v]
    assert len(config_mounts) == 1, "config bind-mount missing"
    assert ":/etc/spire/server/server.conf:" in config_mounts[0]
    assert "ro" in config_mounts[0].split(":")[-1].split(","), (
        f"config bind-mount must be read-only; got: {config_mounts[0]!r}"
    )

    # Named-volume: wakir-spire-server-data.volume sidecar
    data_mounts = [v for v in quadlet_volumes if "wakir-spire-server-data.volume" in v]
    assert data_mounts == ["wakir-spire-server-data.volume:/var/lib/spire/server"], (
        f"server data named-volume mount drift; got: {data_mounts!r}"
    )

    # Named-volume: wakir-spire-server-sockets.volume sidecar
    sock_mounts = [v for v in quadlet_volumes if "wakir-spire-server-sockets.volume" in v]
    assert sock_mounts == ["wakir-spire-server-sockets.volume:/run/spire/sockets"], (
        f"server sockets named-volume mount drift; got: {sock_mounts!r}"
    )

    # Cross-check: compose top-level volumes must publish the same
    # operator-visible volume names so `podman volume ls` is
    # lifecycle-path-agnostic.
    compose_top_volumes = compose_doc.get("volumes", {})
    assert compose_top_volumes["spire_server_data"]["name"] == "wakir-spire-server-data"
    assert compose_top_volumes["spire_server_sockets"]["name"] == "wakir-spire-server-sockets"


def test_quadlet_spire_agent_volumes_match_compose(
    compose_doc: dict,
) -> None:
    """Agent must mount: (1) read-only config bind, (2) agent-data
    named-volume, (3) shared server-sockets volume for Admin-API,
    (4) dedicated agent-sockets volume for Workload-API."""
    quadlet_volumes = _section_lines(QUADLET_AGENT, "Container", "Volume")
    assert len(quadlet_volumes) == 4, (
        f"SPIRE-Agent Quadlet must declare exactly 4 Volume= entries "
        f"(config, data, server-sockets, agent-sockets); got: {quadlet_volumes!r}"
    )

    config_mounts = [v for v in quadlet_volumes if "agent.conf" in v]
    assert len(config_mounts) == 1, "agent config bind-mount missing"
    assert ":/etc/spire/agent/agent.conf:" in config_mounts[0]
    assert "ro" in config_mounts[0].split(":")[-1].split(",")

    data_mounts = [v for v in quadlet_volumes if "wakir-spire-agent-data.volume" in v]
    assert data_mounts == ["wakir-spire-agent-data.volume:/var/lib/spire/agent"]

    # Shared with server — same path inside the container so the gRPC
    # Unix-socket the server creates is reachable by the agent at the
    # same address.
    server_sock_mounts = [v for v in quadlet_volumes if "wakir-spire-server-sockets.volume" in v]
    assert server_sock_mounts == [
        "wakir-spire-server-sockets.volume:/run/spire/sockets"
    ], (
        f"agent must mount the shared server-sockets volume at the same "
        f"path as the server; got: {server_sock_mounts!r}"
    )

    # Dedicated Workload-API socket-share volume.
    agent_sock_mounts = [v for v in quadlet_volumes if "wakir-spire-agent-sockets.volume" in v]
    assert agent_sock_mounts == [
        "wakir-spire-agent-sockets.volume:/run/spire/agent-sockets"
    ]

    # Cross-check compose-side names.
    compose_top_volumes = compose_doc.get("volumes", {})
    assert compose_top_volumes["spire_agent_data"]["name"] == "wakir-spire-agent-data"
    assert compose_top_volumes["spire_agent_sockets"]["name"] == "wakir-spire-agent-sockets"


def test_quadlet_volume_sidecars_declare_matching_volume_names() -> None:
    """Each Quadlet volume sidecar's VolumeName= MUST match the
    compose top-level volumes.<key>.name so `podman volume ls` shows
    the same name string regardless of which lifecycle path created
    it."""
    cases = [
        (QUADLET_SERVER_DATA, "wakir-spire-server-data"),
        (QUADLET_SERVER_SOCKETS, "wakir-spire-server-sockets"),
        (QUADLET_AGENT_DATA, "wakir-spire-agent-data"),
        (QUADLET_AGENT_SOCKETS, "wakir-spire-agent-sockets"),
    ]
    for path, expected in cases:
        parser = _read_ini(path)
        volume_name = parser.get("Volume", "VolumeName")
        assert volume_name == expected, (
            f"Quadlet volume sidecar {path.name} must declare "
            f"VolumeName={expected}; got: {volume_name!r}"
        )


# ---------------------------------------------------------------------
# 7 — Network attach parity (shared with NATS substrate)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("unit_fixture", ["server_unit", "agent_unit"])
def test_quadlet_spire_units_attach_to_orchestrator_network(
    request: pytest.FixtureRequest, unit_fixture: str
) -> None:
    """Both server and agent must attach to the shared
    ``wakir-orchestrator.network`` sidecar so SPIRE-Server,
    SPIRE-Agent, and the NATS substrate coexist on the same user-
    defined bridge network (parity with compose networks.wakir)."""
    unit = request.getfixturevalue(unit_fixture)
    network = unit.get("Container", "Network")
    assert network == "wakir-orchestrator.network", (
        f"SPIRE Quadlet unit must attach to wakir-orchestrator.network; "
        f"got: {network!r}"
    )


def test_compose_spire_uses_same_orchestrator_network_name(
    compose_doc: dict,
) -> None:
    compose_top_networks = compose_doc.get("networks", {})
    compose_net_name = compose_top_networks["wakir"]["name"]
    assert compose_net_name == "wakir-orchestrator", (
        f"compose networks.wakir.name must be wakir-orchestrator "
        f"(byte-precise alias to Quadlet); got: {compose_net_name!r}"
    )


# ---------------------------------------------------------------------
# 8 — Hardening parity (cap_drop ALL, no-new-privileges, read-only, user)
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "unit_fixture,service_key",
    [
        ("server_unit", "spire-server"),
        ("agent_unit", "spire-agent"),
    ],
)
def test_quadlet_spire_drops_all_capabilities(
    request: pytest.FixtureRequest,
    compose_doc: dict,
    unit_fixture: str,
    service_key: str,
) -> None:
    unit = request.getfixturevalue(unit_fixture)
    compose_cap_drop = compose_doc["services"][service_key]["cap_drop"]
    assert compose_cap_drop == ["ALL"]
    quadlet_drop = unit.get("Container", "DropCapability")
    assert quadlet_drop == "ALL", (
        f"Quadlet DropCapability= must be ALL to match compose cap_drop; "
        f"got: {quadlet_drop!r}"
    )


@pytest.mark.parametrize(
    "unit_fixture,service_key",
    [
        ("server_unit", "spire-server"),
        ("agent_unit", "spire-agent"),
    ],
)
def test_quadlet_spire_no_new_privileges(
    request: pytest.FixtureRequest,
    compose_doc: dict,
    unit_fixture: str,
    service_key: str,
) -> None:
    unit = request.getfixturevalue(unit_fixture)
    compose_sec = compose_doc["services"][service_key]["security_opt"]
    assert "no-new-privileges:true" in compose_sec
    quadlet_nnp = unit.get("Container", "NoNewPrivileges")
    assert quadlet_nnp.lower() in {"true", "yes", "1"}, (
        f"Quadlet NoNewPrivileges= must be truthy; got: {quadlet_nnp!r}"
    )


@pytest.mark.parametrize(
    "unit_fixture,service_key",
    [
        ("server_unit", "spire-server"),
        ("agent_unit", "spire-agent"),
    ],
)
def test_quadlet_spire_read_only_rootfs(
    request: pytest.FixtureRequest,
    compose_doc: dict,
    unit_fixture: str,
    service_key: str,
) -> None:
    unit = request.getfixturevalue(unit_fixture)
    assert compose_doc["services"][service_key]["read_only"] is True
    quadlet_ro = unit.get("Container", "ReadOnly")
    assert quadlet_ro.lower() in {"true", "yes", "1"}, (
        f"Quadlet ReadOnly= must be truthy; got: {quadlet_ro!r}"
    )


@pytest.mark.parametrize(
    "unit_fixture,service_key",
    [
        ("server_unit", "spire-server"),
        ("agent_unit", "spire-agent"),
    ],
)
def test_quadlet_spire_runs_as_non_root_uid(
    request: pytest.FixtureRequest,
    compose_doc: dict,
    unit_fixture: str,
    service_key: str,
) -> None:
    """Compose declares ``user: "1000:1000"``; Quadlet splits into
    User= + Group= directives. Both surfaces must run as uid 1000."""
    unit = request.getfixturevalue(unit_fixture)
    compose_user = compose_doc["services"][service_key]["user"]
    assert compose_user == "1000:1000"
    quadlet_user = unit.get("Container", "User")
    quadlet_group = unit.get("Container", "Group")
    assert quadlet_user == "1000"
    assert quadlet_group == "1000"


@pytest.mark.parametrize(
    "unit_fixture,service_key",
    [
        ("server_unit", "spire-server"),
        ("agent_unit", "spire-agent"),
    ],
)
def test_quadlet_spire_tmpfs_for_runtime_paths(
    request: pytest.FixtureRequest,
    compose_doc: dict,
    unit_fixture: str,
    service_key: str,
) -> None:
    """The hermetic posture mounts /run/spire as tmpfs so the read-
    only rootfs stays strictly read-only. Parity with compose
    ``tmpfs:`` list."""
    _ = request.getfixturevalue(unit_fixture)  # fixture activation
    compose_tmpfs = compose_doc["services"][service_key]["tmpfs"]
    assert any("/run/spire" in entry for entry in compose_tmpfs)
    path = QUADLET_SERVER if "server" in unit_fixture else QUADLET_AGENT
    quadlet_tmpfs = _section_lines(path, "Container", "Tmpfs")
    assert quadlet_tmpfs, f"Quadlet {path.name} must declare a Tmpfs= directive"
    assert any(entry.startswith("/run/spire") for entry in quadlet_tmpfs), (
        f"Quadlet Tmpfs= must include /run/spire; got: {quadlet_tmpfs!r}"
    )


# ---------------------------------------------------------------------
# 9 — Health probe parity (spire-{server,agent} healthcheck subcommand)
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "unit_fixture,service_key,binary",
    [
        ("server_unit", "spire-server", "/opt/spire/bin/spire-server"),
        ("agent_unit", "spire-agent", "/opt/spire/bin/spire-agent"),
    ],
)
def test_quadlet_spire_healthcheck_hits_binary_subcommand(
    request: pytest.FixtureRequest,
    compose_doc: dict,
    unit_fixture: str,
    service_key: str,
    binary: str,
) -> None:
    """Both surfaces probe via the SPIRE binary's own ``healthcheck``
    subcommand — hermetic-friendly, no HTTP endpoint, no host probe.
    A SPIRE process not responsive on its admin socket fails the probe
    (avoids false-positive-green that an HTTP / probe would give)."""
    unit = request.getfixturevalue(unit_fixture)
    compose_health = compose_doc["services"][service_key]["healthcheck"]
    compose_probe = compose_health["test"]
    assert "CMD" in compose_probe
    assert binary in compose_probe
    assert "healthcheck" in compose_probe

    quadlet_health_cmd = unit.get("Container", "HealthCmd")
    assert binary in quadlet_health_cmd
    assert "healthcheck" in quadlet_health_cmd


@pytest.mark.parametrize("unit_fixture", ["server_unit", "agent_unit"])
def test_quadlet_spire_health_timing_fields(
    request: pytest.FixtureRequest, unit_fixture: str
) -> None:
    unit = request.getfixturevalue(unit_fixture)
    duration_re = re.compile(r"^\d+(s|m|h|ms)$")
    for key in ("HealthInterval", "HealthTimeout", "HealthRetries", "HealthStartPeriod"):
        value = unit.get("Container", key)
        assert value, f"Quadlet [Container] {key}= must be set"
        if key == "HealthRetries":
            assert value.isdigit(), f"{key} must be an integer; got: {value!r}"
        else:
            assert duration_re.match(value), (
                f"{key} must be a systemd-style duration "
                f"(e.g. '10s', '5s', '30s'); got: {value!r}"
            )


# ---------------------------------------------------------------------
# 10 — Restart policy presence (nuance-tolerant)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("unit_fixture", ["server_unit", "agent_unit"])
def test_quadlet_spire_declares_restart_policy(
    request: pytest.FixtureRequest, unit_fixture: str
) -> None:
    """Compose declares ``restart: unless-stopped``; systemd's closest
    equivalent is ``Restart=on-failure``. Parity with the Tag-1
    NATS quadlet pattern (both on-failure and always are operator-
    acceptable per the Skizze §3 equivalence table)."""
    unit = request.getfixturevalue(unit_fixture)
    restart = unit.get("Service", "Restart")
    assert restart in {"on-failure", "always"}, (
        f"Quadlet [Service] Restart= must be on-failure or always; "
        f"got: {restart!r}"
    )


# ---------------------------------------------------------------------
# 11 — Server <-> Agent boot-ordering hint
# ---------------------------------------------------------------------


def test_quadlet_spire_agent_unit_orders_after_spire_server(
    agent_unit: configparser.ConfigParser,
) -> None:
    """systemd has no direct equivalent of compose's
    ``depends_on: condition: service_healthy``; the closest-equivalent
    is ``After=`` + ``Requires=`` so the agent's restart-on-failure
    policy converges once the server's healthcheck passes. This is
    documented in the agent unit header."""
    after = agent_unit.get("Unit", "After")
    requires = agent_unit.get("Unit", "Requires")
    assert "wakir-spire-server.service" in after, (
        f"SPIRE-Agent Quadlet [Unit] After= must include "
        f"wakir-spire-server.service; got: {after!r}"
    )
    assert "wakir-spire-server.service" in requires, (
        f"SPIRE-Agent Quadlet [Unit] Requires= must include "
        f"wakir-spire-server.service; got: {requires!r}"
    )


# ---------------------------------------------------------------------
# 12 — Compose remains the primary contract surface
# ---------------------------------------------------------------------


def test_compose_spire_file_still_exists_alongside_quadlet() -> None:
    """Scenario-B dual-track invariant: compose remains the primary
    contract surface. Deleting compose/spire.yaml would make this a
    Scenario-C (Quadlet primary) commit and requires a documented
    Phase-3-trigger decision, not a DevOps-solo box."""
    assert COMPOSE_FILE.exists(), (
        "compose/spire.yaml is the primary Phase-2.1/2.2 contract "
        "surface and MUST stay alongside the Quadlet dual-track."
    )
