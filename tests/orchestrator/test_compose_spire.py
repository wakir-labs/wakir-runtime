# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for ``compose/spire.yaml`` (SPIFFE Z-A
Phase-2.1 Sprint-6 Tag-6 hermetic SPIRE-Server-Sidecar).

These tests are pure compose-parse + invariant assertions. They do
NOT:
  * Pull the SPIRE-Server image
  * Run a SPIRE-Server container
  * Issue or validate any SVID
  * Touch the host's podman/docker socket

They DO assert that:
  * The compose file parses, has the expected top-level shape, and
    declares a single ``spire-server`` service.
  * The image reference is the SPIRE upstream package at the
    documented Phase-2.1 tag form (tag-only acceptable, digest-pin
    acceptable as a future Cosign-Skizze follow-up).
  * The container uses the hermetic-only trust-domain
    ``example.test`` (NOT the production ``wakir.local`` or any
    ``*.wakir.dev`` literal).
  * The Mock/Stub config file is bind-mounted read-only at the
    expected path inside the container.
  * Named volumes for SPIRE-Server data and Unix-socket sharing are
    declared and the in-service mount-points match.
  * Hardening defaults (``cap_drop: ALL``, ``no-new-privileges:true``,
    ``restart: unless-stopped``) are present.
  * The health-probe shape uses the SPIRE-Server's own
    ``healthcheck`` subcommand (no host-side HTTP probe).
  * The compose unit shares the ``wakir-orchestrator`` bridge network
    with ``compose/nats.yaml`` so Sidecar-coexistence is a single-
    network-add operator step.
  * The Mock/Stub config file parses as HCL-like text, declares the
    hermetic trust-domain, and binds the gRPC server on 127.0.0.1.

Drift-detection: if a Phase-2.4 NATS-JWT-Auth integration patch lands
that changes the trust-domain to ``wakir.local`` (the Phase-2
production literal per the skizze §2), these tests will fail loudly
and force a co-edit — which is the intended drift-gate.
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
NATS_COMPOSE_FILE = REPO_ROOT / "compose" / "nats.yaml"
CONFIG_FILE = REPO_ROOT / "config" / "spire-server.conf"


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose_doc() -> dict:
    """Parse ``compose/spire.yaml`` once per test module."""
    with COMPOSE_FILE.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    assert isinstance(doc, dict), "compose/spire.yaml top-level must be a mapping"
    return doc


@pytest.fixture(scope="module")
def compose_text() -> str:
    """Raw text of the compose file for commentary-grep tests."""
    return COMPOSE_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def nats_compose_doc() -> dict:
    """Parse ``compose/nats.yaml`` for coexistence-invariant tests."""
    with NATS_COMPOSE_FILE.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def server_conf_text() -> str:
    """Raw text of ``config/spire-server.conf`` (HCL)."""
    return CONFIG_FILE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# 1 — compose-parse + top-level shape
# ---------------------------------------------------------------------


def test_compose_file_is_present_and_parses(compose_doc: dict) -> None:
    assert "services" in compose_doc, "compose file must declare services"
    assert "volumes" in compose_doc, "compose file must declare named volumes"
    assert "networks" in compose_doc, "compose file must declare a network"


def test_compose_has_single_phase_2_1_service_named_spire_server(
    compose_doc: dict,
) -> None:
    services = compose_doc["services"]
    assert isinstance(services, dict)
    assert list(services.keys()) == ["spire-server"], (
        "Phase-2.1 hermetic substrate must expose exactly one service "
        "('spire-server'); the SPIRE-Agent sidecar is a Phase-2.2 follow-up "
        "in its own service block."
    )


# ---------------------------------------------------------------------
# 2 — image-pin form (tag-only or digest-pinned)
# ---------------------------------------------------------------------


def test_spire_server_uses_upstream_ghcr_image(compose_doc: dict) -> None:
    image = compose_doc["services"]["spire-server"]["image"]
    # Three valid forms (Tag-8 rebase: Tag-7 Cosign-Pin-Form merged in):
    #   * tag-only:                ``ghcr.io/spiffe/spire-server:<semver>``
    #   * digest-pinned (real):    ``ghcr.io/spiffe/spire-server:<semver>@sha256:<64-hex>``
    #   * digest-pinned (pending): ``ghcr.io/spiffe/spire-server:<semver>@sha256:DIGEST_PENDING_TOMAS_REVIEW``
    # The pending-placeholder form is the Tag-8 default; Operator-Hand
    # substitutes a real 64-hex digest after ``cosign verify`` +
    # ``skopeo inspect`` (see ``docs/spire-server-phase-2-1.md`` §2).
    tag_only = re.fullmatch(
        r"ghcr\.io/spiffe/spire-server:\d+\.\d+\.\d+", image
    )
    digest_pin_real = re.fullmatch(
        r"ghcr\.io/spiffe/spire-server:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}",
        image,
    )
    digest_pin_placeholder = re.fullmatch(
        r"ghcr\.io/spiffe/spire-server:\d+\.\d+\.\d+@sha256:DIGEST_PENDING_TOMAS_REVIEW",
        image,
    )
    assert tag_only or digest_pin_real or digest_pin_placeholder, (
        f"image must be 'ghcr.io/spiffe/spire-server:<semver>' "
        f"(tag-only), digest-pinned (64-hex), or pending-placeholder "
        f"form; got: {image!r}"
    )


def test_spire_server_image_is_at_least_1_14(compose_doc: dict) -> None:
    """Phase-2.1 pins at minimum SPIRE v1.14 (the verified stable line
    at authoring time, v1.14.6 released 2026-04-27 per upstream
    releases page). A rollback below 1.14 must be explicit."""
    image = compose_doc["services"]["spire-server"]["image"]
    m = re.search(r"spire-server:(\d+)\.(\d+)\.(\d+)", image)
    assert m, f"could not parse semver out of image ref: {image!r}"
    major, minor, _patch = map(int, m.groups())
    assert (major, minor) >= (1, 14), (
        f"SPIRE v1.14 is the Phase-2.1 minimum; got {major}.{minor}"
    )


# ---------------------------------------------------------------------
# 3 — hermetic trust-domain (example.test, RFC 6761 reserved)
# ---------------------------------------------------------------------


def test_server_conf_declares_example_test_trust_domain(
    server_conf_text: str,
) -> None:
    """Mock/Stub config must use the IANA-reserved ``example.test``
    trust-domain. This is the hermetic-mode marker — any future
    operator who sees ``example.test`` knows this is NOT a production
    stand."""
    # HCL: ``trust_domain = "example.test"``
    assert re.search(
        r'trust_domain\s*=\s*"example\.test"', server_conf_text
    ), "Mock/Stub server.conf must declare trust_domain = \"example.test\""


def test_server_conf_does_not_use_production_trust_domains(
    server_conf_text: str,
) -> None:
    """Negative invariant: the active HCL ``trust_domain`` statement
    MUST NOT name the Phase-2 production trust-domain (``wakir.local``)
    or any ``*.wakir.dev`` literal. Commentary lines may reference
    them for context — what matters is the live config statement.

    This prevents the hermetic skeleton from ever issuing SVIDs that a
    production NATS-Server would accept."""
    # Strip HCL comments (lines starting with optional whitespace + ``#``).
    active_lines = [
        line
        for line in server_conf_text.splitlines()
        if not line.lstrip().startswith("#")
    ]
    active = "\n".join(active_lines)
    forbidden_in_active = [
        '"wakir.local"',
        '"wakir.dev"',
        ".wakir.dev",
    ]
    for needle in forbidden_in_active:
        assert needle not in active, (
            f"Mock/Stub server.conf active HCL must NOT reference "
            f"{needle!r}; hermetic mode uses example.test only "
            f"(commentary references are fine)"
        )


def test_compose_commentary_references_example_test_marker(
    compose_text: str,
) -> None:
    """The compose-file commentary must call out the hermetic-only
    trust-domain so an operator reading just the compose file
    understands the substrate is not for production bring-up."""
    assert "example.test" in compose_text, (
        "compose/spire.yaml commentary should reference the "
        "hermetic-only trust-domain example.test"
    )


# ---------------------------------------------------------------------
# 4 — config bind-mount + volumes
# ---------------------------------------------------------------------


def test_server_conf_bind_mount_is_readonly(compose_doc: dict) -> None:
    volumes = compose_doc["services"]["spire-server"]["volumes"]
    expected = "./config/spire-server.conf:/etc/spire/server/server.conf:ro"
    assert expected in volumes, (
        f"server.conf must be bind-mounted read-only at the documented "
        f"path; expected {expected!r} in {volumes!r}"
    )


def test_server_data_volume_is_named_and_declared(compose_doc: dict) -> None:
    volumes = compose_doc["services"]["spire-server"]["volumes"]
    assert "spire_server_data:/var/lib/spire/server" in volumes, (
        "SPIRE-Server data dir must be a named-volume mount at "
        "/var/lib/spire/server"
    )
    top_volumes = compose_doc.get("volumes", {})
    assert "spire_server_data" in top_volumes, (
        "named volume 'spire_server_data' must be declared at top level"
    )


def test_server_sockets_volume_is_named_and_declared(
    compose_doc: dict,
) -> None:
    """The /run/spire/sockets named volume is the Phase-2.2 sharing
    surface between the SPIRE-Server (and a future SPIRE-Agent) and
    persona-containers via the Workload-API. Declared early so
    Phase-2.2 follow-up patches do not need to re-architect mounts."""
    volumes = compose_doc["services"]["spire-server"]["volumes"]
    assert "spire_server_sockets:/run/spire/sockets" in volumes, (
        "Unix-socket dir must be a named-volume mount at "
        "/run/spire/sockets"
    )
    top_volumes = compose_doc.get("volumes", {})
    assert "spire_server_sockets" in top_volumes


# ---------------------------------------------------------------------
# 5 — hardening defaults
# ---------------------------------------------------------------------


def test_spire_server_has_hardened_defaults(compose_doc: dict) -> None:
    svc = compose_doc["services"]["spire-server"]
    assert svc.get("cap_drop") == ["ALL"], (
        "cap_drop ALL is mandatory Phase-2 hardening (mirrors NATS "
        "substrate Phase-1b convention)"
    )
    sec_opt = svc.get("security_opt", [])
    assert "no-new-privileges:true" in sec_opt, (
        "no-new-privileges must be set"
    )
    assert svc.get("restart") == "unless-stopped", (
        "Phase-2 SPIRE-Server must auto-restart on crash but not on "
        "operator-stop (mirrors NATS Phase-1b)"
    )


# ---------------------------------------------------------------------
# 6 — health-probe shape (spire-server self-check, no HTTP)
# ---------------------------------------------------------------------


def test_health_probe_uses_spire_server_healthcheck_subcommand(
    compose_doc: dict,
) -> None:
    """The SPIRE-Server image ships its own healthcheck subcommand.
    The hermetic probe MUST use that, not a host-side HTTP probe —
    SPIRE-Server has no HTTP endpoint by default in Phase-2."""
    health = compose_doc["services"]["spire-server"]["healthcheck"]
    assert isinstance(health, dict)
    test_cmd = health["test"]
    assert isinstance(test_cmd, list) and test_cmd[0] == "CMD", (
        "health probe must use CMD (exec) form, not CMD-SHELL — the "
        "SPIRE-Server binary is the probe, not a shell"
    )
    # The exec must invoke the spire-server binary's own healthcheck.
    joined = " ".join(test_cmd)
    assert "spire-server" in joined and "healthcheck" in joined, (
        f"health probe must call spire-server healthcheck; got: "
        f"{test_cmd!r}"
    )
    assert health.get("interval"), "health interval must be set"
    assert health.get("retries"), "health retries must be set"
    assert health.get("timeout"), "health timeout must be set"
    # Start-period must be set: SPIRE-Server bootstrap (CA gen + DB
    # init) takes ~10–20s on a cold start, so probe-failure-on-startup
    # without start_period would mark the container unhealthy mid-init.
    assert health.get("start_period"), (
        "health start_period must be set to absorb SPIRE bootstrap latency"
    )


# ---------------------------------------------------------------------
# 7 — NATS-substrate coexistence invariant
# ---------------------------------------------------------------------


def test_spire_and_nats_share_the_wakir_orchestrator_network(
    compose_doc: dict, nats_compose_doc: dict
) -> None:
    """The SPIRE-Server-Sidecar must share the user-defined bridge
    network with the NATS-Substrate so Phase-2.2+ persona-containers
    can resolve both services by their compose service names."""
    spire_networks = compose_doc["services"]["spire-server"]["networks"]
    nats_networks = nats_compose_doc["services"]["nats"]["networks"]
    assert "wakir" in spire_networks
    assert "wakir" in nats_networks

    spire_top = compose_doc["networks"]["wakir"]
    nats_top = nats_compose_doc["networks"]["wakir"]
    assert spire_top["name"] == nats_top["name"] == "wakir-orchestrator", (
        "SPIRE-Server and NATS must both name the network "
        "'wakir-orchestrator' — name-stability is the coexistence "
        "anchor; compose v2 reuses a pre-existing named network "
        "across compose files"
    )
    assert spire_top["driver"] == nats_top["driver"] == "bridge"


# ---------------------------------------------------------------------
# 8 — config-file shape (HCL declares the expected plugins)
# ---------------------------------------------------------------------


def test_server_conf_declares_phase_2_plugins(server_conf_text: str) -> None:
    """The Mock/Stub config must declare the three Phase-2 boring-
    default plugins (DataStore sql/sqlite3, KeyManager disk,
    NodeAttestor join_token). These pins keep the hermetic substrate
    minimal and force a co-edit when Phase-3 patches change them."""
    for needle in [
        'DataStore "sql"',
        'KeyManager "disk"',
        'NodeAttestor "join_token"',
    ]:
        assert needle in server_conf_text, (
            f"server.conf must declare the Phase-2 plugin: {needle!r}"
        )
    # SQLite3 specifically is the Phase-2 DataStore engine (not
    # Postgres / not in-memory).
    assert 'database_type     = "sqlite3"' in server_conf_text or (
        'database_type = "sqlite3"' in server_conf_text
    ), "DataStore must use sqlite3 in Phase-2"


def test_server_conf_pins_phase_2_jwt_ttl(server_conf_text: str) -> None:
    """JWT-SVID TTL must be 15m to match the constants module pin
    (PERSONA_HASH_SHORT_LEN-test-suite pin
    ``JWT_SVID_TTL_SECONDS_PHASE_2 = 15 * 60``)."""
    assert re.search(
        r'default_jwt_svid_ttl\s*=\s*"15m"', server_conf_text
    ), "server.conf must pin default_jwt_svid_ttl = \"15m\""


def test_server_conf_binds_on_loopback(server_conf_text: str) -> None:
    """The gRPC server must bind on 127.0.0.1 inside the container —
    no host-port mapping is declared in compose/spire.yaml, so this
    pin is the defence-in-depth: even if a future patch adds a ports:
    mapping accidentally, the server still binds loopback."""
    assert re.search(
        r'bind_address\s*=\s*"127\.0\.0\.1"', server_conf_text
    ), "server.conf must bind on 127.0.0.1"
    assert re.search(
        r'bind_port\s*=\s*"8081"', server_conf_text
    ), "server.conf must bind on port 8081 (SPIRE-Server boring-default)"
