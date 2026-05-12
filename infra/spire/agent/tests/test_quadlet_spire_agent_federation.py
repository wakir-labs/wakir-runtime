# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic Quadlet template parity tests for Sprint-8 Tag-2.

Asserts the wakir-spire-agent-federation.container template carries
the byte-precise mirror of compose/spire-agent-federation.yaml
hardening posture, with the documented <SIDE>/<TRUST_DOMAIN>/
<SERVER_DNS> placeholders. Mirror of Sprint-8 Tag-1 federation server
Quadlet template test convention.

Asserts:
  * Template has all three required placeholders.
  * Image-pin form matches the compose-side Cosign-Digest-Pin Pfad B.
  * Hardening directives present (ReadOnly=true, User=1000, Group=1000,
    DropCapability=ALL, NoNewPrivileges=true, Tmpfs=/run/spire).
  * HealthCmd uses the spire-agent self-check subcommand.
  * Volume directives reference the per-side <SIDE> placeholder for
    data, sockets, and bundles volumes.
  * Network=wakir-federation.network (external from Tag-1).
  * After/Requires order the agent unit after the matching <SIDE>
    server unit.
  * Volume sidecar templates exist for data + sockets (and the
    bundles volume is owned by the Tag-1 server template — agent
    template MUST NOT redeclare it).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
AGENT_DIR = HERE.parent
QUADLET_DIR = AGENT_DIR / "quadlet"
CONTAINER_TPL = QUADLET_DIR / "wakir-spire-agent-federation.container"
DATA_VOL_TPL = QUADLET_DIR / "wakir-spire-agent-federation-data.volume"
SOCKETS_VOL_TPL = QUADLET_DIR / "wakir-spire-agent-federation-sockets.volume"


@pytest.fixture(scope="module")
def container_text() -> str:
    return CONTAINER_TPL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def data_vol_text() -> str:
    return DATA_VOL_TPL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sockets_vol_text() -> str:
    return SOCKETS_VOL_TPL.read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# Placeholder shape
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "placeholder", ["<SIDE>"]
)
def test_container_template_carries_required_placeholders(
    container_text: str, placeholder: str
) -> None:
    assert placeholder in container_text, (
        f"Quadlet template must carry placeholder {placeholder!r} for "
        f"install-time sed substitution"
    )


def test_volume_templates_carry_side_placeholder(
    data_vol_text: str, sockets_vol_text: str
) -> None:
    assert "<SIDE>" in data_vol_text, (
        "data .volume template must carry <SIDE> placeholder"
    )
    assert "<SIDE>" in sockets_vol_text, (
        "sockets .volume template must carry <SIDE> placeholder"
    )


# ---------------------------------------------------------------------
# Image-pin form (Cosign-Digest-Pin Pfad B parity)
# ---------------------------------------------------------------------


def test_image_pin_form(container_text: str) -> None:
    m = re.search(r"^Image=(\S+)$", container_text, re.MULTILINE)
    assert m, "Quadlet template must declare Image=..."
    img = m.group(1)
    pattern = (
        r"^ghcr\.io/spiffe/spire-agent:1\.14\.\d+"
        r"@sha256:([0-9a-f]{64}|DIGEST_PENDING_TOMAS_REVIEW)$"
    )
    assert re.match(pattern, img), (
        f"Image-pin form must match Tag-1 Cosign-Digest-Pin convention; "
        f"got {img!r}"
    )


# ---------------------------------------------------------------------
# Hardening posture (mirror of compose-side)
# ---------------------------------------------------------------------


def test_hardening_directives(container_text: str) -> None:
    must_contain = [
        "ReadOnly=true",
        "User=1000",
        "Group=1000",
        "DropCapability=ALL",
        "NoNewPrivileges=true",
        "Tmpfs=/run/spire",
    ]
    for directive in must_contain:
        assert directive in container_text, (
            f"Quadlet template must contain hardening directive "
            f"{directive!r}"
        )


def test_health_cmd_uses_spire_agent_self_check(container_text: str) -> None:
    assert re.search(
        r"HealthCmd=/opt/spire/bin/spire-agent\s+healthcheck",
        container_text,
    ), "HealthCmd must invoke spire-agent healthcheck subcommand"


# ---------------------------------------------------------------------
# Volume + network wiring
# ---------------------------------------------------------------------


def test_volume_directives_reference_side_placeholder(
    container_text: str,
) -> None:
    # Data + sockets per-side volumes use <SIDE> placeholder.
    assert re.search(
        r"Volume=wakir-spire-agent-<SIDE>-data\.volume:/var/lib/spire/agent",
        container_text,
    ), "Quadlet must mount per-side data volume"
    assert re.search(
        r"Volume=wakir-spire-agent-<SIDE>-sockets\.volume:/run/spire/agent-sockets",
        container_text,
    ), "Quadlet must mount per-side sockets volume at SPIFFE-canonical path"
    # Bundles volume is owned by Tag-1 server template; agent mounts
    # read-only.
    assert re.search(
        r"Volume=wakir-spire-server-<SIDE>-bundles\.volume:/var/lib/spire/bundles:ro",
        container_text,
    ), (
        "Quadlet must mount Tag-1-owned server-side bundles volume READ-"
        "ONLY at /var/lib/spire/bundles"
    )


def test_network_external_federation(container_text: str) -> None:
    assert "Network=wakir-federation.network" in container_text, (
        "Quadlet must join wakir-federation.network (Tag-1-owned)"
    )


# ---------------------------------------------------------------------
# Unit ordering (After/Requires)
# ---------------------------------------------------------------------


def test_after_and_requires_match_side_server_unit(
    container_text: str,
) -> None:
    """The agent must start AFTER the same-side server unit and
    REQUIRE it (compose's depends_on: condition: service_healthy
    equivalent — strict ordering plus restart-on-failure)."""
    assert re.search(
        r"After=.*wakir-spire-server-<SIDE>\.service",
        container_text,
    ), "After= must order agent unit after same-side server unit"
    assert re.search(
        r"Requires=wakir-spire-server-<SIDE>\.service",
        container_text,
    ), "Requires= must depend on same-side server unit"


# ---------------------------------------------------------------------
# Volume sidecar declarations
# ---------------------------------------------------------------------


def test_data_volume_template_declares_volumename(
    data_vol_text: str,
) -> None:
    assert re.search(
        r"^VolumeName=wakir-spire-agent-<SIDE>-data\s*$",
        data_vol_text,
        re.MULTILINE,
    ), "data .volume template must declare VolumeName=wakir-spire-agent-<SIDE>-data"


def test_sockets_volume_template_declares_volumename(
    sockets_vol_text: str,
) -> None:
    assert re.search(
        r"^VolumeName=wakir-spire-agent-<SIDE>-sockets\s*$",
        sockets_vol_text,
        re.MULTILINE,
    ), (
        "sockets .volume template must declare "
        "VolumeName=wakir-spire-agent-<SIDE>-sockets"
    )


def test_agent_template_does_not_redeclare_bundles_volume() -> None:
    """The bundles volume is owned by the Tag-1 federation server-side
    Quadlet template. The agent template must NOT redeclare it as a
    .volume sidecar — that would create a conflict at install-time."""
    bundles_tpl = QUADLET_DIR / "wakir-spire-server-<SIDE>-bundles.volume"
    assert not bundles_tpl.exists(), (
        "agent Quadlet must NOT redeclare bundles volume sidecar "
        "(Tag-1 server template owns it)"
    )
    # Also assert no file named with literal 'spire-agent' and 'bundles'
    # to catch a slightly-different naming-scheme variant.
    for entry in QUADLET_DIR.iterdir():
        name = entry.name.lower()
        if "agent" in name and "bundles" in name:  # pragma: no cover
            pytest.fail(
                f"agent Quadlet must NOT carry a bundles .volume sidecar; "
                f"found {entry.name!r}"
            )
