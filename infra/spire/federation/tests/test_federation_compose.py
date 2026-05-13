# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the Sprint-8 Tag-1 SPIRE-Federation
substrate (``infra/spire/federation/compose/spire-federation.yaml``).

Pure compose-parse + invariant assertions. No image pull, no
container run, no SVID issuance, no podman/docker socket touch.

Asserts:
  * The compose file parses, has two services (``spire-server-wakir``
    and ``spire-server-partner``) with the documented Phase-2.1
    image-pin form (tag@sha256 or tag@sha256:placeholder).
  * Each service uses the correct hermetic trust-domain via the
    bind-mounted config file (``wakir.test`` / ``partner.test``).
  * Both services share the dedicated ``wakir-federation`` bridge
    network (NOT the Sprint-6 ``wakir-orchestrator`` network).
  * Both services declare a bundle-endpoint listener at the
    documented loopback host ports (8443 wakir, 8444 partner).
  * Both services have the Sprint-6 hardening posture (cap_drop: ALL,
    no-new-privileges, read_only, non-root user, tmpfs for
    /run/spire, healthcheck with the SPIRE-Server self-check
    subcommand).
  * Both config files declare a ``federation { bundle_endpoint }``
    block and a ``federates_with`` block targeting the peer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - pyyaml is a dev-dep
    pytest.skip("pyyaml not installed", allow_module_level=True)


HERE = Path(__file__).resolve().parent
FED_DIR = HERE.parent
COMPOSE_FILE = FED_DIR / "compose" / "spire-federation.yaml"
WAKIR_CONF = FED_DIR / "config" / "spire-server-wakir.conf"
PARTNER_CONF = FED_DIR / "config" / "spire-server-partner.conf"


@pytest.fixture(scope="module")
def compose_doc() -> dict:
    with COMPOSE_FILE.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    assert isinstance(doc, dict), (
        "compose/spire-federation.yaml top-level must be a mapping"
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


def test_two_federation_services_present(services: dict) -> None:
    assert set(services.keys()) == {"spire-server-wakir", "spire-server-partner"}, (
        "exactly two federation services expected: spire-server-wakir + "
        "spire-server-partner"
    )


@pytest.mark.parametrize("svc_name", ["spire-server-wakir", "spire-server-partner"])
def test_image_pin_form(services: dict, svc_name: str) -> None:
    img = services[svc_name].get("image")
    assert isinstance(img, str), f"{svc_name}.image must be a string"
    # Image-pin form: ghcr.io/spiffe/spire-server:1.14.6@sha256:<digest>
    # The digest is either a 64-hex literal OR the placeholder token
    # ``DIGEST_PENDING_TOMAS_REVIEW`` (Cosign-Skizze follow-up). Mirror
    # of the Sprint-6 invariant in test_compose_spire_cosign_pin.py.
    pat = re.compile(
        r"^ghcr\.io/spiffe/spire-server:1\.14\.\d+@sha256:"
        r"(?:DIGEST_PENDING_TOMAS_REVIEW|[0-9a-f]{64})$"
    )
    assert pat.match(img), (
        f"{svc_name}.image {img!r} does not match the Phase-2.1 Cosign-Digest-"
        "Pin form (tag@sha256:placeholder-or-64hex)"
    )


@pytest.mark.parametrize("svc_name", ["spire-server-wakir", "spire-server-partner"])
def test_hardening_posture(services: dict, svc_name: str) -> None:
    svc = services[svc_name]
    assert svc.get("read_only") is True, f"{svc_name}.read_only must be true"
    assert svc.get("user") == "1000:1000", (
        f"{svc_name}.user must be 1000:1000 (non-root)"
    )
    assert svc.get("cap_drop") == ["ALL"], (
        f"{svc_name}.cap_drop must drop ALL capabilities"
    )
    sec_opt = svc.get("security_opt") or []
    assert "no-new-privileges:true" in sec_opt, (
        f"{svc_name}.security_opt must include no-new-privileges:true"
    )
    tmpfs = svc.get("tmpfs") or []
    assert any("/run/spire" in t for t in tmpfs), (
        f"{svc_name}.tmpfs must include /run/spire"
    )


@pytest.mark.parametrize("svc_name", ["spire-server-wakir", "spire-server-partner"])
def test_healthcheck_shape(services: dict, svc_name: str) -> None:
    hc = services[svc_name].get("healthcheck") or {}
    test = hc.get("test") or []
    assert test and test[0] == "CMD", f"{svc_name}.healthcheck must use CMD form"
    binary = test[1] if len(test) > 1 else ""
    assert binary.endswith("/spire-server"), (
        f"{svc_name}.healthcheck must invoke the spire-server binary, got {test!r}"
    )
    assert "healthcheck" in test, (
        f"{svc_name}.healthcheck.test must include the 'healthcheck' subcommand"
    )


# ---------------------------------------------------------------------
# Bundle-endpoint port-publish
# ---------------------------------------------------------------------


def test_wakir_publishes_bundle_endpoint_loopback(services: dict) -> None:
    ports = services["spire-server-wakir"].get("ports") or []
    # Container 8443 is the bundle-endpoint listener (see config).
    # Wakir-side maps to host 127.0.0.1:8443.
    assert "127.0.0.1:8443:8443" in ports, (
        f"spire-server-wakir.ports must publish 127.0.0.1:8443:8443, got {ports!r}"
    )


def test_partner_publishes_bundle_endpoint_loopback(services: dict) -> None:
    ports = services["spire-server-partner"].get("ports") or []
    assert "127.0.0.1:8444:8443" in ports, (
        f"spire-server-partner.ports must publish 127.0.0.1:8444:8443, got {ports!r}"
    )


def test_grpc_ports_no_clash(services: dict) -> None:
    # Wakir-grpc on host 8082, partner-grpc on host 8083, container 8081.
    # No shared host port between the two sides.
    wakir_ports = services["spire-server-wakir"].get("ports") or []
    partner_ports = services["spire-server-partner"].get("ports") or []
    assert "127.0.0.1:8082:8081" in wakir_ports
    assert "127.0.0.1:8083:8081" in partner_ports
    # No overlapping host port across the two sides.
    wakir_host_ports = {p.split(":")[1] for p in wakir_ports}
    partner_host_ports = {p.split(":")[1] for p in partner_ports}
    assert wakir_host_ports.isdisjoint(partner_host_ports), (
        f"host ports must not overlap: wakir={wakir_host_ports} partner={partner_host_ports}"
    )


# ---------------------------------------------------------------------
# Network isolation from Sprint-6 substrate
# ---------------------------------------------------------------------


def test_dedicated_federation_network(compose_doc: dict, services: dict) -> None:
    nets = compose_doc.get("networks") or {}
    assert "wakir-federation" in nets, (
        "compose must declare a 'wakir-federation' network"
    )
    fed_net = nets["wakir-federation"]
    assert fed_net.get("name") == "wakir-federation", (
        f"network name must be 'wakir-federation', got {fed_net.get('name')!r}"
    )
    # Both services attached to wakir-federation, not to wakir-orchestrator.
    for svc_name in ("spire-server-wakir", "spire-server-partner"):
        svc_nets = services[svc_name].get("networks") or []
        assert "wakir-federation" in svc_nets, (
            f"{svc_name} must attach to wakir-federation, got {svc_nets!r}"
        )
        assert "wakir-orchestrator" not in svc_nets, (
            f"{svc_name} MUST NOT attach to the Sprint-6 wakir-orchestrator "
            "network — federation substrate isolation invariant"
        )


# ---------------------------------------------------------------------
# Config file shape
# ---------------------------------------------------------------------


def test_wakir_config_trust_domain(compose_doc: dict) -> None:
    text = WAKIR_CONF.read_text(encoding="utf-8")
    assert re.search(r'trust_domain\s*=\s*"wakir\.test"', text), (
        "spire-server-wakir.conf must declare trust_domain = \"wakir.test\""
    )


def test_partner_config_trust_domain(compose_doc: dict) -> None:
    text = PARTNER_CONF.read_text(encoding="utf-8")
    assert re.search(r'trust_domain\s*=\s*"partner\.test"', text), (
        "spire-server-partner.conf must declare trust_domain = \"partner.test\""
    )


def test_wakir_config_federation_block() -> None:
    text = WAKIR_CONF.read_text(encoding="utf-8")
    # federation { bundle_endpoint { ... } }
    assert re.search(
        r"federation\s*\{[^}]*bundle_endpoint\s*\{", text, re.DOTALL
    ), "spire-server-wakir.conf must declare a federation { bundle_endpoint { } } block"
    # https_spiffe profile for the hermetic bootstrap
    assert 'profile = "https_spiffe"' in text, (
        "spire-server-wakir.conf must use https_spiffe profile for the hermetic "
        "bootstrap"
    )
    # Bundle-endpoint port 8443
    assert re.search(r'port\s*=\s*8443', text), (
        "spire-server-wakir.conf bundle_endpoint must listen on port 8443"
    )


def test_partner_config_federation_block() -> None:
    text = PARTNER_CONF.read_text(encoding="utf-8")
    assert re.search(
        r"federation\s*\{[^}]*bundle_endpoint\s*\{", text, re.DOTALL
    ), "spire-server-partner.conf must declare a federation { bundle_endpoint { } } block"
    assert 'profile = "https_spiffe"' in text
    assert re.search(r'port\s*=\s*8443', text)


def test_wakir_federates_with_partner() -> None:
    text = WAKIR_CONF.read_text(encoding="utf-8")
    assert re.search(r'federates_with\s+"partner\.test"', text), (
        "spire-server-wakir.conf must declare federates_with \"partner.test\""
    )
    assert "spire-server-partner:8443" in text, (
        "spire-server-wakir.conf federates_with peer must target the partner's "
        "bundle-endpoint URL"
    )
    assert "spiffe://partner.test/spire/server" in text, (
        "spire-server-wakir.conf must pin the peer's bundle-endpoint SPIFFE-ID"
    )


def test_partner_federates_with_wakir() -> None:
    text = PARTNER_CONF.read_text(encoding="utf-8")
    assert re.search(r'federates_with\s+"wakir\.test"', text), (
        "spire-server-partner.conf must declare federates_with \"wakir.test\""
    )
    assert "spire-server-wakir:8443" in text
    assert "spiffe://wakir.test/spire/server" in text


def test_volume_bind_mounts_match_config(services: dict) -> None:
    """Each service must bind-mount its OWN config file (no swap)."""
    wakir_vols = services["spire-server-wakir"].get("volumes") or []
    partner_vols = services["spire-server-partner"].get("volumes") or []
    assert any(
        "../config/spire-server-wakir.conf:/etc/spire/server/server.conf:ro" in v
        for v in wakir_vols
    ), f"spire-server-wakir must bind-mount its own config, got {wakir_vols!r}"
    assert any(
        "../config/spire-server-partner.conf:/etc/spire/server/server.conf:ro" in v
        for v in partner_vols
    ), f"spire-server-partner must bind-mount its own config, got {partner_vols!r}"
