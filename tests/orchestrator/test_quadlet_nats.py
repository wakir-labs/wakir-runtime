# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Hermetic parity tests for the Phase-2 Sprint-6 Quadlet dual-track
# unit files (quadlet/wakir-nats.container, wakir-orchestrator.network,
# wakir-nats-jetstream-data.volume) against the primary compose contract
# surface compose/nats.yaml.
#
# Goal: drift-detection. When the compose image digest pin changes, or
# the port/volume/network shape changes, the Quadlet files must follow
# in the same commit. These tests fail hermetically if drift is
# introduced; no container engine, no systemd, no live NATS.
#
# Scope: byte-precise parity for fields that operators see (image
# digest, container name, port publication, volume mount, network
# attach, capability drop, no-new-privileges, health-probe endpoint).
# Restart-policy nuance (compose unless-stopped vs systemd on-failure)
# is documented in the Skizze §3 equivalence-stamps table and not
# byte-asserted here — the test only asserts that both surfaces
# declare *some* restart-on-failure policy.

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
COMPOSE_FILE = REPO_ROOT / "compose" / "nats.yaml"
QUADLET_DIR = REPO_ROOT / "quadlet"
QUADLET_CONTAINER = QUADLET_DIR / "wakir-nats.container"
QUADLET_NETWORK = QUADLET_DIR / "wakir-orchestrator.network"
QUADLET_VOLUME = QUADLET_DIR / "wakir-nats-jetstream-data.volume"


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


def _read_ini(path: Path) -> configparser.ConfigParser:
    """Parse a Quadlet unit file with the systemd ini-style parser.

    Quadlet units allow duplicate keys in a single section (e.g. two
    PublishPort= lines, two WantedBy= entries). ConfigParser's
    ``strict=False`` permits the duplicates; the parsed value of a
    duplicated key is the *last* occurrence, so duplicate-aware fields
    need a raw-text re-parse via _section_lines() below.
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
    """Return every value for a given key in a given section.

    Quadlet allows duplicate-key entries (e.g. multiple PublishPort=
    lines map to multiple port publications). The standard ConfigParser
    last-write-wins semantics drop duplicates, so this helper does a
    raw text scan that respects section boundaries.
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


@pytest.fixture(scope="module")
def compose_doc() -> dict:
    with COMPOSE_FILE.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    assert isinstance(doc, dict)
    return doc


@pytest.fixture(scope="module")
def quadlet_container() -> configparser.ConfigParser:
    return _read_ini(QUADLET_CONTAINER)


@pytest.fixture(scope="module")
def quadlet_network() -> configparser.ConfigParser:
    return _read_ini(QUADLET_NETWORK)


@pytest.fixture(scope="module")
def quadlet_volume() -> configparser.ConfigParser:
    return _read_ini(QUADLET_VOLUME)


# ---------------------------------------------------------------------
# 1 — File presence + parse
# ---------------------------------------------------------------------


def test_quadlet_unit_files_are_present() -> None:
    assert QUADLET_CONTAINER.exists(), (
        "quadlet/wakir-nats.container is missing — dual-track contract "
        "requires the runnable unit file alongside compose/nats.yaml"
    )
    assert QUADLET_NETWORK.exists(), (
        "quadlet/wakir-orchestrator.network is missing"
    )
    assert QUADLET_VOLUME.exists(), (
        "quadlet/wakir-nats-jetstream-data.volume is missing"
    )


def test_quadlet_container_has_expected_sections(
    quadlet_container: configparser.ConfigParser,
) -> None:
    # Quadlet [Container] is mandatory; [Unit], [Service], [Install]
    # are conventional and the operator install flow depends on them.
    assert "Unit" in quadlet_container.sections()
    assert "Container" in quadlet_container.sections()
    assert "Service" in quadlet_container.sections()
    assert "Install" in quadlet_container.sections()


# ---------------------------------------------------------------------
# 2 — Image digest pin parity (the load-bearing assertion)
# ---------------------------------------------------------------------


def test_quadlet_image_matches_compose_digest_pin(
    compose_doc: dict, quadlet_container: configparser.ConfigParser
) -> None:
    """The Quadlet Image= directive MUST stay byte-precise-aligned with
    compose services.nats.image. This is the Sprint-4 Tag-3 Cross-Review
    Zone-C digest-pin contract; drift between the two surfaces would
    let an operator on the Quadlet path pull a different image than the
    operator on the compose path.

    Compose form: ``nats:2.11-alpine@sha256:<64-hex>`` (or tag-only as
    accepted by test_compose_nats.py).
    Quadlet form: ``docker.io/library/nats:2.11-alpine@sha256:<64-hex>``
    (the Quadlet directive prefers fully-qualified registry references;
    the registry+library prefix is the docker.io canonical form).
    """
    compose_image = compose_doc["services"]["nats"]["image"]
    quadlet_image = quadlet_container.get("Container", "Image")

    # Strip the docker.io/library/ prefix if present — Quadlet uses
    # fully-qualified refs; compose accepts the short form.
    quadlet_short = quadlet_image
    for prefix in ("docker.io/library/", "docker.io/", "library/"):
        if quadlet_short.startswith(prefix):
            quadlet_short = quadlet_short[len(prefix):]
            break

    assert quadlet_short == compose_image, (
        f"Quadlet Image= and compose services.nats.image must match "
        f"byte-precise (digest pin parity). "
        f"compose: {compose_image!r}, quadlet (short): {quadlet_short!r}"
    )

    # Belt-and-braces: extract the digest from both sides and compare.
    digest_pattern = re.compile(r"@sha256:([0-9a-f]{64})$")
    compose_match = digest_pattern.search(compose_image)
    quadlet_match = digest_pattern.search(quadlet_image)
    # Compose may be tag-only or digest-pinned per test_compose_nats.py.
    # If compose is digest-pinned, Quadlet must be too with the same hash.
    if compose_match:
        assert quadlet_match, (
            "compose is digest-pinned but Quadlet is not — parity broken"
        )
        assert compose_match.group(1) == quadlet_match.group(1), (
            f"digest-pin drift: compose={compose_match.group(1)} "
            f"vs quadlet={quadlet_match.group(1)}"
        )


# ---------------------------------------------------------------------
# 3 — Container name parity
# ---------------------------------------------------------------------


def test_quadlet_container_name_matches_compose(
    compose_doc: dict, quadlet_container: configparser.ConfigParser
) -> None:
    compose_name = compose_doc["services"]["nats"]["container_name"]
    quadlet_name = quadlet_container.get("Container", "ContainerName")
    assert compose_name == quadlet_name, (
        f"compose container_name {compose_name!r} != "
        f"Quadlet ContainerName {quadlet_name!r}"
    )


# ---------------------------------------------------------------------
# 4 — Port publication parity (loopback-only + 4222 + 8222)
# ---------------------------------------------------------------------


def test_quadlet_ports_are_loopback_only_and_match_compose(
    compose_doc: dict,
) -> None:
    """PublishPort= directives must be loopback-only (same invariant as
    compose ports:) and must include both client port 4222 and
    monitoring port 8222.
    """
    publish_ports = _section_lines(QUADLET_CONTAINER, "Container", "PublishPort")
    assert publish_ports, "Quadlet must declare PublishPort= directives"

    for port in publish_ports:
        assert port.startswith("127.0.0.1:"), (
            f"Phase-1 invariant: Quadlet PublishPort must bind to "
            f"127.0.0.1 (loopback-only); got: {port!r}"
        )

    quadlet_host_ports = {p.split(":")[1] for p in publish_ports}
    assert "4222" in quadlet_host_ports, "client port 4222 must be published"
    assert "8222" in quadlet_host_ports, "monitoring port 8222 must be published"

    # Cross-check: every compose port must have a Quadlet PublishPort.
    compose_ports = compose_doc["services"]["nats"]["ports"]
    compose_host_ports = {entry.split(":")[1] for entry in compose_ports}
    assert quadlet_host_ports == compose_host_ports, (
        f"port-publication drift: compose={compose_host_ports} vs "
        f"quadlet={quadlet_host_ports}"
    )


# ---------------------------------------------------------------------
# 5 — JetStream + store_dir command-line parity
# ---------------------------------------------------------------------


def test_quadlet_exec_enables_jetstream_with_documented_store_dir(
    compose_doc: dict, quadlet_container: configparser.ConfigParser
) -> None:
    exec_line = quadlet_container.get("Container", "Exec")
    assert "--jetstream" in exec_line, (
        "JetStream must be enabled on the Quadlet Exec= line"
    )
    assert "--store_dir=/data/jetstream" in exec_line, (
        "--store_dir must be /data/jetstream (matches Volume= mount)"
    )

    # Cross-check against compose command:.
    compose_cmd = compose_doc["services"]["nats"]["command"]
    assert "--jetstream" in compose_cmd
    assert "--store_dir=/data/jetstream" in compose_cmd


# ---------------------------------------------------------------------
# 6 — Volume mount parity
# ---------------------------------------------------------------------


def test_quadlet_volume_mount_matches_compose(
    compose_doc: dict, quadlet_container: configparser.ConfigParser
) -> None:
    quadlet_volume_decl = quadlet_container.get("Container", "Volume")
    # Quadlet form: ``<name>.volume:/mountpoint:Z``.
    # Sprint-9-Tag-8 Bug-20: ``:Z`` SELinux-relabel flag is mandatory
    # on FCOS-enforced hosts; compose-yaml has no equivalent because
    # docker-compose carries volume-driver options elsewhere. Quadlet
    # is the canonical install path on the pilot.
    assert quadlet_volume_decl == "wakir-nats-jetstream-data.volume:/data/jetstream:Z", (
        f"Quadlet Volume= must reference wakir-nats-jetstream-data.volume "
        f"sidecar mounted at /data/jetstream with the SELinux-relabel "
        f"flag :Z; got: {quadlet_volume_decl!r}"
    )

    # Cross-check: compose volumes: short form must alias to the same
    # named volume and mountpoint.
    compose_volumes = compose_doc["services"]["nats"]["volumes"]
    expected_compose = "jetstream_data:/data/jetstream"
    assert expected_compose in compose_volumes, (
        f"compose must mount jetstream_data:/data/jetstream; got {compose_volumes!r}"
    )

    # And both must point to the same operator-visible volume name.
    compose_top_volumes = compose_doc.get("volumes", {})
    compose_volume_name = compose_top_volumes["jetstream_data"]["name"]
    assert compose_volume_name == "wakir-nats-jetstream-data", (
        f"compose top-level volume name must be wakir-nats-jetstream-data "
        f"(byte-precise alias to Quadlet); got: {compose_volume_name!r}"
    )


def test_quadlet_volume_sidecar_declares_matching_volume_name(
    quadlet_volume: configparser.ConfigParser,
) -> None:
    volume_name = quadlet_volume.get("Volume", "VolumeName")
    assert volume_name == "wakir-nats-jetstream-data", (
        f"Quadlet volume sidecar must declare VolumeName=wakir-nats-jetstream-data "
        f"to match the compose volumes.jetstream_data.name; got: {volume_name!r}"
    )


# ---------------------------------------------------------------------
# 7 — Network attach parity
# ---------------------------------------------------------------------


def test_quadlet_network_attach_matches_compose(
    compose_doc: dict, quadlet_container: configparser.ConfigParser
) -> None:
    quadlet_network_decl = quadlet_container.get("Container", "Network")
    assert quadlet_network_decl == "wakir-orchestrator.network", (
        f"Quadlet Network= must reference wakir-orchestrator.network "
        f"sidecar; got: {quadlet_network_decl!r}"
    )

    # Cross-check: compose networks: must alias to wakir-orchestrator.
    compose_top_networks = compose_doc.get("networks", {})
    compose_net_name = compose_top_networks["wakir"]["name"]
    assert compose_net_name == "wakir-orchestrator", (
        f"compose networks.wakir.name must be wakir-orchestrator "
        f"(byte-precise alias to Quadlet); got: {compose_net_name!r}"
    )


def test_quadlet_network_sidecar_declares_matching_network_name(
    quadlet_network: configparser.ConfigParser,
) -> None:
    network_name = quadlet_network.get("Network", "NetworkName")
    assert network_name == "wakir-orchestrator", (
        f"Quadlet network sidecar must declare NetworkName=wakir-orchestrator; "
        f"got: {network_name!r}"
    )
    driver = quadlet_network.get("Network", "Driver")
    assert driver == "bridge", (
        f"Phase-1 substrate uses bridge driver (matches compose networks.wakir.driver); "
        f"got: {driver!r}"
    )


# ---------------------------------------------------------------------
# 8 — Hardening parity
# ---------------------------------------------------------------------


def test_quadlet_drops_all_capabilities_like_compose(
    compose_doc: dict, quadlet_container: configparser.ConfigParser
) -> None:
    compose_cap_drop = compose_doc["services"]["nats"]["cap_drop"]
    assert compose_cap_drop == ["ALL"]

    quadlet_drop = quadlet_container.get("Container", "DropCapability")
    assert quadlet_drop == "ALL", (
        f"Quadlet DropCapability= must be ALL to match compose cap_drop; "
        f"got: {quadlet_drop!r}"
    )


def test_quadlet_no_new_privileges_like_compose(
    compose_doc: dict, quadlet_container: configparser.ConfigParser
) -> None:
    compose_sec = compose_doc["services"]["nats"]["security_opt"]
    assert "no-new-privileges:true" in compose_sec

    quadlet_nnp = quadlet_container.get("Container", "NoNewPrivileges")
    # systemd-ini boolean form accepts true/yes/1
    assert quadlet_nnp.lower() in {"true", "yes", "1"}, (
        f"Quadlet NoNewPrivileges= must be truthy; got: {quadlet_nnp!r}"
    )


# ---------------------------------------------------------------------
# 9 — Health probe parity
# ---------------------------------------------------------------------


def test_quadlet_healthcmd_hits_jsz_endpoint_like_compose(
    compose_doc: dict, quadlet_container: configparser.ConfigParser
) -> None:
    """Both surfaces must hit /jsz, not bare / — a JetStream-disabled
    NATS would answer on / but fail on /jsz, so probing / is a known
    false-positive-green failure mode that test_compose_nats.py
    explicitly forbids.
    """
    compose_health = compose_doc["services"]["nats"]["healthcheck"]
    compose_probe = compose_health["test"][1]
    assert "/jsz" in compose_probe

    quadlet_health_cmd = quadlet_container.get("Container", "HealthCmd")
    assert "/jsz" in quadlet_health_cmd, (
        f"Quadlet HealthCmd= must probe /jsz (JetStream introspection); "
        f"got: {quadlet_health_cmd!r}"
    )


def test_quadlet_health_probe_timing_fields_are_present(
    quadlet_container: configparser.ConfigParser,
) -> None:
    """The four timing knobs match the compose healthcheck shape.
    Hermetic check: presence + valid duration string. The exact values
    are documented in the Skizze §3 equivalence-stamps table.
    """
    duration_re = re.compile(r"^\d+(s|m|h|ms)$")
    for key in ("HealthInterval", "HealthTimeout", "HealthRetries", "HealthStartPeriod"):
        value = quadlet_container.get("Container", key)
        assert value, f"Quadlet [Container] {key}= must be set"
        if key == "HealthRetries":
            assert value.isdigit(), f"{key} must be an integer; got: {value!r}"
        else:
            assert duration_re.match(value), (
                f"{key} must be a systemd-style duration "
                f"(e.g. '10s', '3s'); got: {value!r}"
            )


# ---------------------------------------------------------------------
# 10 — Restart policy presence (nuance-tolerant)
# ---------------------------------------------------------------------


def test_quadlet_declares_restart_policy(
    quadlet_container: configparser.ConfigParser,
) -> None:
    """Compose declares ``restart: unless-stopped``; systemd's closest
    equivalent is ``Restart=on-failure`` (per Skizze §3 nuance note).
    The parity test is intentionally tolerant — both ``on-failure`` and
    ``always`` are operator-acceptable choices documented in the Skizze.
    """
    restart = quadlet_container.get("Service", "Restart")
    assert restart in {"on-failure", "always"}, (
        f"Quadlet [Service] Restart= must be on-failure or always to "
        f"match compose unless-stopped semantics; got: {restart!r}"
    )


# ---------------------------------------------------------------------
# 11 — Compose remains the primary contract surface
# ---------------------------------------------------------------------


def test_compose_file_still_exists_alongside_quadlet() -> None:
    """Scenario-B dual-track invariant: compose remains the primary
    contract surface. Deleting compose/nats.yaml would make this a
    Scenario-C (Quadlet primary) commit and requires a documented
    Phase-3-trigger decision, not a DevOps-solo box.
    """
    assert COMPOSE_FILE.exists(), (
        "compose/nats.yaml is the primary Phase-2 contract surface and "
        "MUST stay alongside the Quadlet dual-track. Removing it requires "
        "a Phase-3-trigger decision (Scenario C in the Skizze)."
    )
