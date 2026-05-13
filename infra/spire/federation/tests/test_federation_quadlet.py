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
    assert "Tmpfs=/run/spire:rw,size=16m,mode=0700" in quadlet_text


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
    # the invariant. Host port is substituted at install.
    assert re.search(
        r"PublishPort=127\.0\.0\.1:<HOST_BUNDLE_PORT>:8443", quadlet_text
    ), "Quadlet must publish container port 8443 (bundle-endpoint listener)"
    assert re.search(
        r"PublishPort=127\.0\.0\.1:<HOST_GRPC_PORT>:8081", quadlet_text
    ), "Quadlet must publish container port 8081 (SPIRE-Server gRPC API)"


def test_quadlet_network_attachment(quadlet_text: str) -> None:
    assert "Network=wakir-federation.network" in quadlet_text


def test_quadlet_placeholders_preserved(quadlet_text: str) -> None:
    """The template MUST keep the three documented placeholders so
    the install-time sed-substitution stays explicit."""
    for placeholder in ("<SIDE>", "<HOST_BUNDLE_PORT>", "<HOST_GRPC_PORT>"):
        assert placeholder in quadlet_text, (
            f"Quadlet template must preserve placeholder {placeholder!r}"
        )
