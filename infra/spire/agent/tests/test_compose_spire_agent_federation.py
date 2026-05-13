# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the Sprint-8 Tag-2 SPIRE-Agent-
Federation substrate
(``infra/spire/agent/compose/spire-agent-federation.yaml``).

Pure compose-parse + invariant assertions. No image pull, no
container run, no SVID issuance, no podman/docker socket touch.

Asserts:
  * Two services (``spire-agent-wakir``, ``spire-agent-partner``) with
    Cosign-Digest-Pin parity (mirror of Sprint-8 Tag-1 federation
    server convention).
  * Both agents join the EXTERNAL ``wakir-federation`` bridge network
    (declared external from Sprint-8 Tag-1 federation substrate, NOT
    re-created here).
  * Both agents mount the federated-bundles ingest volume read-only
    (the Sprint-8 Tag-1 server-side bundles volume, declared external).
  * Workload-API sockets volume present at the canonical SPIFFE-spec
    path ``/run/spire/agent-sockets``.
  * Hardening posture parity with Sprint-6 Tag-9 (cap_drop ALL,
    no-new-privileges, read_only, non-root, tmpfs /run/spire,
    healthcheck via spire-agent self-check subcommand).
  * Per-side data + sockets volumes are INTERNAL (created by this
    compose unit); only the bundles volume + the federation network
    are external.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    pytest.skip("pyyaml not installed", allow_module_level=True)


HERE = Path(__file__).resolve().parent
AGENT_DIR = HERE.parent
COMPOSE_FILE = AGENT_DIR / "compose" / "spire-agent-federation.yaml"


@pytest.fixture(scope="module")
def compose_doc() -> dict:
    with COMPOSE_FILE.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    assert isinstance(doc, dict), (
        "compose/spire-agent-federation.yaml top-level must be a mapping"
    )
    return doc


@pytest.fixture(scope="module")
def services(compose_doc: dict) -> dict:
    svcs = compose_doc.get("services")
    assert isinstance(svcs, dict), "services: must be a mapping"
    return svcs


# ---------------------------------------------------------------------
# Service shape
# ---------------------------------------------------------------------


def test_two_agent_services_present(services: dict) -> None:
    assert set(services.keys()) == {
        "spire-agent-wakir",
        "spire-agent-partner",
    }, (
        "exactly two agent services expected: spire-agent-wakir + "
        "spire-agent-partner"
    )


@pytest.mark.parametrize(
    "svc_name", ["spire-agent-wakir", "spire-agent-partner"]
)
def test_image_pin_form(services: dict, svc_name: str) -> None:
    img = services[svc_name].get("image")
    assert isinstance(img, str), f"{svc_name}.image must be a string"
    # Cosign-Digest-Pin parity with Sprint-8 Tag-1 federation server:
    # ghcr.io/spiffe/spire-agent:1.14.6@sha256:<digest-or-placeholder>
    pattern = (
        r"^ghcr\.io/spiffe/spire-agent:1\.14\.\d+"
        r"@sha256:([0-9a-f]{64}|DIGEST_PENDING_TOMAS_REVIEW)$"
    )
    assert re.match(pattern, img), (
        f"{svc_name}.image must follow Cosign-Digest-Pin form; got {img!r}"
    )


@pytest.mark.parametrize(
    "svc_name", ["spire-agent-wakir", "spire-agent-partner"]
)
def test_hardening_posture(services: dict, svc_name: str) -> None:
    svc = services[svc_name]
    assert svc.get("read_only") is True, (
        f"{svc_name}.read_only must be true"
    )
    assert svc.get("user") == "1000:1000", (
        f"{svc_name}.user must be 1000:1000 (non-root)"
    )
    cap_drop = svc.get("cap_drop") or []
    assert "ALL" in cap_drop, f"{svc_name}.cap_drop must include ALL"
    sec_opt = svc.get("security_opt") or []
    assert any("no-new-privileges:true" in opt for opt in sec_opt), (
        f"{svc_name}.security_opt must include no-new-privileges:true"
    )
    tmpfs = svc.get("tmpfs") or []
    assert any("/run/spire" in entry for entry in tmpfs), (
        f"{svc_name}.tmpfs must mount /run/spire"
    )


@pytest.mark.parametrize(
    "svc_name", ["spire-agent-wakir", "spire-agent-partner"]
)
def test_healthcheck_uses_spire_agent_self_check(
    services: dict, svc_name: str
) -> None:
    health = services[svc_name].get("healthcheck")
    assert isinstance(health, dict), (
        f"{svc_name}.healthcheck must be a mapping"
    )
    test_cmd = health.get("test") or []
    assert "CMD" in test_cmd, f"{svc_name}.healthcheck.test must use CMD form"
    assert any("spire-agent" in part for part in test_cmd), (
        f"{svc_name}.healthcheck must invoke spire-agent (self-check)"
    )
    assert any("healthcheck" in part for part in test_cmd), (
        f"{svc_name}.healthcheck must invoke the healthcheck subcommand"
    )


# ---------------------------------------------------------------------
# Volume + network wiring
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "svc_name,expected_bundles_volume,expected_config_file,expected_data_volume",
    [
        (
            "spire-agent-wakir",
            "spire_server_wakir_bundles",
            "../config/spire-agent-wakir.conf",
            "spire_agent_wakir_data",
        ),
        (
            "spire-agent-partner",
            "spire_server_partner_bundles",
            "../config/spire-agent-partner.conf",
            "spire_agent_partner_data",
        ),
    ],
)
def test_per_side_volumes_wired(
    services: dict,
    svc_name: str,
    expected_bundles_volume: str,
    expected_config_file: str,
    expected_data_volume: str,
) -> None:
    """Each side has: config bind-mount, data volume, bundles read-only
    federated-ingest, and Workload-API sockets volume."""
    vols = services[svc_name].get("volumes") or []
    # Config bind-mount.
    assert any(
        v.startswith(expected_config_file) for v in vols if isinstance(v, str)
    ), (
        f"{svc_name} must bind-mount {expected_config_file} at "
        f"/etc/spire/agent/agent.conf"
    )
    # Data named volume.
    assert any(
        v.startswith(f"{expected_data_volume}:") for v in vols if isinstance(v, str)
    ), f"{svc_name} must mount {expected_data_volume}"
    # Bundles read-only ingest from Tag-1 server-side volume.
    assert any(
        v.startswith(f"{expected_bundles_volume}:") and v.endswith(":ro")
        for v in vols
        if isinstance(v, str)
    ), (
        f"{svc_name} must mount {expected_bundles_volume} READ-ONLY at "
        f"/var/lib/spire/bundles"
    )


@pytest.mark.parametrize(
    "svc_name,expected_sockets_volume",
    [
        ("spire-agent-wakir", "spire_agent_wakir_sockets"),
        ("spire-agent-partner", "spire_agent_partner_sockets"),
    ],
)
def test_workload_api_socket_mount_path(
    services: dict, svc_name: str, expected_sockets_volume: str
) -> None:
    """Workload-API socket is at the SPIFFE-spec canonical path
    ``/run/spire/agent-sockets`` (Phase-2.3+ persona-containers mount
    this volume read-only at the same path)."""
    vols = services[svc_name].get("volumes") or []
    matches = [
        v
        for v in vols
        if isinstance(v, str) and v.startswith(f"{expected_sockets_volume}:")
    ]
    assert len(matches) == 1, (
        f"{svc_name} must mount {expected_sockets_volume} exactly once"
    )
    mount_spec = matches[0]
    assert "/run/spire/agent-sockets" in mount_spec, (
        f"{svc_name} sockets volume must mount at "
        f"/run/spire/agent-sockets (SPIFFE-spec); got {mount_spec!r}"
    )


def test_federation_network_external(compose_doc: dict) -> None:
    nets = compose_doc.get("networks") or {}
    fed = nets.get("wakir-federation")
    assert isinstance(fed, dict), (
        "networks.wakir-federation must be declared"
    )
    assert fed.get("external") is True, (
        "networks.wakir-federation must be EXTERNAL (owned by Sprint-8 "
        "Tag-1 federation substrate; agent compose does NOT re-create it)"
    )
    assert fed.get("name") == "wakir-federation"


def test_bundles_volumes_external(compose_doc: dict) -> None:
    """The two federated-bundles volumes are external (owned by Tag-1).
    The per-side agent-data + agent-sockets volumes are internal
    (owned by this compose unit)."""
    vols = compose_doc.get("volumes") or {}
    wakir_bundles = vols.get("spire_server_wakir_bundles") or {}
    partner_bundles = vols.get("spire_server_partner_bundles") or {}
    assert wakir_bundles.get("external") is True, (
        "spire_server_wakir_bundles must be external (Tag-1-owned)"
    )
    assert partner_bundles.get("external") is True, (
        "spire_server_partner_bundles must be external (Tag-1-owned)"
    )

    # Per-side data/sockets are internal — assert they exist and do NOT
    # carry external: true.
    for vol_name in (
        "spire_agent_wakir_data",
        "spire_agent_wakir_sockets",
        "spire_agent_partner_data",
        "spire_agent_partner_sockets",
    ):
        v = vols.get(vol_name)
        assert isinstance(v, dict), f"volume {vol_name} must be declared"
        assert v.get("external") is not True, (
            f"volume {vol_name} must be internal (Tag-2-owned)"
        )


@pytest.mark.parametrize(
    "svc_name", ["spire-agent-wakir", "spire-agent-partner"]
)
def test_agent_joins_federation_network(
    services: dict, svc_name: str
) -> None:
    nets = services[svc_name].get("networks") or []
    assert "wakir-federation" in nets, (
        f"{svc_name} must join the wakir-federation bridge network"
    )
    # No other networks — agents are isolated to the federation bridge.
    assert nets == ["wakir-federation"], (
        f"{svc_name} must ONLY join wakir-federation (got {nets!r})"
    )


def test_resource_envelope(services: dict) -> None:
    for svc_name in ("spire-agent-wakir", "spire-agent-partner"):
        deploy = services[svc_name].get("deploy") or {}
        limits = (deploy.get("resources") or {}).get("limits") or {}
        assert limits.get("cpus") == "0.5", (
            f"{svc_name}.deploy.resources.limits.cpus must be 0.5"
        )
        assert limits.get("memory") == "256M", (
            f"{svc_name}.deploy.resources.limits.memory must be 256M"
        )
