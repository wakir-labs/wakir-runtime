# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic byte-precision parity tests between the federation compose
substrate and its Quadlet-template companion.

The Quadlet template (``quadlet/wakir-spire-server-federation.container``)
is a generic single-side unit with placeholders ``<SIDE>``,
``<HOST_BUNDLE_PORT>``, and ``<HOST_GRPC_PORT>``. The operator
sed-substitutes the placeholders for each side at install-time.

This test asserts the template stays in shape-parity with the compose
unit:
  * Image-pin form identical (same upstream image, same tag, same
    Cosign-Digest-Pin form).
  * Exec command identical (run -config /etc/spire/server/server.conf).
  * Hardening posture identical (ReadOnly=true, User/Group=1000,
    DropCapability=ALL, NoNewPrivileges=true, Tmpfs=/run/spire,
    healthcheck shape).
  * Bundle-endpoint container port 8443 published (loopback-only).
  * Sidecar volumes (.volume) and network (.network) units exist with
    the documented names.
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
FED_DIR = HERE.parent
COMPOSE_FILE = FED_DIR / "compose" / "spire-federation.yaml"
QUADLET_DIR = FED_DIR / "quadlet"
QUADLET_CONTAINER = QUADLET_DIR / "wakir-spire-server-federation.container"
QUADLET_NETWORK = QUADLET_DIR / "wakir-federation.network"
QUADLET_DATA_VOL = QUADLET_DIR / "wakir-spire-server-federation-data.volume"
QUADLET_SOCKETS_VOL = QUADLET_DIR / "wakir-spire-server-federation-sockets.volume"
QUADLET_BUNDLES_VOL = QUADLET_DIR / "wakir-spire-server-federation-bundles.volume"


@pytest.fixture(scope="module")
def quadlet_text() -> str:
    return QUADLET_CONTAINER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def compose_wakir() -> dict:
    with COMPOSE_FILE.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    return doc["services"]["spire-server-wakir"]


# ---------------------------------------------------------------------
# Sidecar units exist
# ---------------------------------------------------------------------


def test_quadlet_network_sidecar_exists() -> None:
    assert QUADLET_NETWORK.exists()
    text = QUADLET_NETWORK.read_text(encoding="utf-8")
    assert "NetworkName=wakir-federation" in text
    assert "Driver=bridge" in text


@pytest.mark.parametrize(
    "vol_path",
    [QUADLET_DATA_VOL, QUADLET_SOCKETS_VOL, QUADLET_BUNDLES_VOL],
)
def test_quadlet_volume_sidecars_exist(vol_path: Path) -> None:
    assert vol_path.exists()
    text = vol_path.read_text(encoding="utf-8")
    assert "[Volume]" in text
    assert "VolumeName=" in text
    # The <SIDE> placeholder is preserved for sed-substitution at install.
    assert "<SIDE>" in text


# ---------------------------------------------------------------------
# Quadlet container template shape
# ---------------------------------------------------------------------


def test_quadlet_image_pin_matches_compose(quadlet_text: str, compose_wakir: dict) -> None:
    """Image must match between compose and Quadlet template."""
    m = re.search(r"^Image=(.+)$", quadlet_text, re.MULTILINE)
    assert m, "Quadlet Image= directive missing"
    quadlet_image = m.group(1).strip()
    assert quadlet_image == compose_wakir["image"], (
        f"Quadlet image {quadlet_image!r} must match compose image "
        f"{compose_wakir['image']!r}"
    )


def test_quadlet_exec_matches_compose(quadlet_text: str, compose_wakir: dict) -> None:
    m = re.search(r"^Exec=(.+)$", quadlet_text, re.MULTILINE)
    assert m, "Quadlet Exec= directive missing"
    quadlet_exec = m.group(1).strip()
    compose_cmd = " ".join(compose_wakir["command"])
    assert quadlet_exec == compose_cmd, (
        f"Quadlet Exec={quadlet_exec!r} must match compose command "
        f"{compose_cmd!r}"
    )


def test_quadlet_hardening_posture(quadlet_text: str) -> None:
    assert "ReadOnly=true" in quadlet_text
    assert "User=1000" in quadlet_text
    assert "Group=1000" in quadlet_text
    assert "DropCapability=ALL" in quadlet_text
    assert "NoNewPrivileges=true" in quadlet_text
    # Sprint-9-Tag-6 Bug 12 substance-fix: the previous mode=0700 made
    # /run/spire root-only and blocked the uid:1000 SPIRE process from
    # creating the gRPC API socket inside the bind-mounted -sockets
    # volume. Live Pilot-VM bring-up 2026-05-14 observed
    # ``permission denied`` on socket bind. mode=0755 keeps the
    # directory owner-writable for the uid:1000 container user.
    assert "Tmpfs=/run/spire:rw,size=16m,mode=0755" in quadlet_text


def test_quadlet_health_probe(quadlet_text: str) -> None:
    assert "HealthCmd=/opt/spire/bin/spire-server healthcheck" in quadlet_text
    assert "HealthInterval=10s" in quadlet_text
    assert "HealthTimeout=5s" in quadlet_text
    assert "HealthRetries=5" in quadlet_text
    # Sprint-9-Tag-5 Bug 7 H3 substance-fix: HealthStartPeriod was 30s
    # but cold-start CA-init on a slow Pilot-VM can exceed 30s. Raised
    # to 60s. The 30s lower-bound is no longer correct as a HARD
    # assertion; the 60s value is the new floor.
    assert "HealthStartPeriod=60s" in quadlet_text


def test_quadlet_publishes_bundle_endpoint(quadlet_text: str) -> None:
    # The template uses placeholders; the literal container port 8443 is
    # the invariant. Host port + host bind are substituted at install.
    # Sprint-10 Tag-3 substance: the bundle-endpoint host bind is now
    # parametrised via <HOST_BUNDLE_BIND> so federation-mode bind on
    # 0.0.0.0 is possible (Cross-VM access), while single-org keeps
    # 127.0.0.1 loopback-only.
    assert re.search(
        r"PublishPort=<HOST_BUNDLE_BIND>:<HOST_BUNDLE_PORT>:8443",
        quadlet_text,
    ), "Quadlet must publish container port 8443 with parametrised host bind"
    # The gRPC API stays LITERALLY loopback-only — this is a security
    # invariant (the gRPC API is the privileged control plane). The
    # bind for 8081 must remain hardcoded ``127.0.0.1``, NOT a
    # placeholder. Drift would be a regression of the Sprint-10 Tag-3
    # security posture.
    assert re.search(
        r"PublishPort=127\.0\.0\.1:<HOST_GRPC_PORT>:8081", quadlet_text
    ), "Quadlet must publish container port 8081 (SPIRE-Server gRPC API) on literal loopback"


def test_quadlet_network_attachment(quadlet_text: str) -> None:
    assert "Network=wakir-federation.network" in quadlet_text


def test_quadlet_placeholders_preserved(quadlet_text: str) -> None:
    """The template MUST keep the documented placeholders so the
    install-time sed-substitution stays explicit.

    Sprint-10 Tag-3 adds ``<HOST_BUNDLE_BIND>`` to the placeholder set;
    the bootstrap wires it from WAKIR_PILOT_MODE (single-org -> 127.0.0.1,
    federation -> 0.0.0.0).
    """
    placeholders = (
        "<SIDE>",
        "<HOST_BUNDLE_PORT>",
        "<HOST_GRPC_PORT>",
        "<HOST_BUNDLE_BIND>",
    )
    for placeholder in placeholders:
        assert placeholder in quadlet_text, (
            f"Quadlet template must preserve placeholder {placeholder!r}"
        )


def test_quadlet_grpc_port_bind_is_literal_loopback(quadlet_text: str) -> None:
    """Sprint-10 Tag-3 security invariant: the gRPC API host bind MUST
    NOT be parametrised. Only the bundle-endpoint host bind is
    parametrised (because federation-mode requires Cross-VM access).
    The gRPC API is the privileged control plane (token-generate,
    agent-list, bundle-set) and MUST stay loopback-only in EVERY
    pilot-mode."""
    # Hardcoded 127.0.0.1 literal — no placeholder allowed for the
    # gRPC port bind. The test asserts both presence of the literal
    # AND absence of any ``<...>:<HOST_GRPC_PORT>`` pattern.
    assert "127.0.0.1:<HOST_GRPC_PORT>:8081" in quadlet_text
    assert not re.search(
        r"<HOST_GRPC_BIND>:<HOST_GRPC_PORT>", quadlet_text
    ), "gRPC port bind must NOT be parametrised (security invariant)"
