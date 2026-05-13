# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the Sprint-8 Tag-2 SPIRE-Agent
federation configs (``config/spire-agent-{wakir,partner}.conf``).

Pure string-presence + key-presence invariants. No HCL parser
dependency (the SPIRE-Server only validates HCL at runtime; the
hermetic substrate asserts shape via regex/string-presence so the
test suite stays dep-free).

Asserts:
  * Each side's trust_domain literal matches the Tag-1 federation pair.
  * Each side's server_address matches the Tag-1 federation server-side
    DNS name on the wakir-federation bridge network.
  * trust_bundle_path is wired to the federated-bundles ingest volume.
  * trust_bundle_format is ``spiffe`` (JWKS — federation https_spiffe
    profile parity).
  * insecure_bootstrap is FALSE for federation (stricter than the
    Sprint-6 single-trust-domain agent).
  * Workload-API socket_path follows the SPIFFE-spec convention
    ``/run/spire/agent-sockets/api.sock``.
  * NodeAttestor=join_token, KeyManager=memory, WorkloadAttestor=unix
    (parity with Sprint-6 Tag-9 agent.conf).
  * Per-side trust-domain literals are mutually exclusive (a wakir-
    side config does NOT reference partner.test and vice-versa,
    excluding peer-reference contexts — none exist in agent config).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
AGENT_DIR = HERE.parent
WAKIR_CONF = AGENT_DIR / "config" / "spire-agent-wakir.conf"
PARTNER_CONF = AGENT_DIR / "config" / "spire-agent-partner.conf"


@pytest.fixture(scope="module")
def wakir_conf_text() -> str:
    return WAKIR_CONF.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def partner_conf_text() -> str:
    return PARTNER_CONF.read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# Trust-domain literals
# ---------------------------------------------------------------------


def test_wakir_trust_domain_literal(wakir_conf_text: str) -> None:
    assert re.search(
        r'trust_domain\s*=\s*"wakir\.test"', wakir_conf_text
    ), "wakir-side trust_domain must be 'wakir.test'"


def test_partner_trust_domain_literal(partner_conf_text: str) -> None:
    assert re.search(
        r'trust_domain\s*=\s*"partner\.test"', partner_conf_text
    ), "partner-side trust_domain must be 'partner.test'"


def _strip_hcl_comments(text: str) -> str:
    """Return text with ``#``-prefixed comment lines removed.

    Agent config has no federates_with block (server-side concern); the
    HCL body MUST NOT reference the cross-side trust-domain. Comment
    lines are exempt — header rationale references the peer side for
    operator orientation but the active HCL config must stay
    side-isolated.
    """
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def test_wakir_does_not_carry_partner_trust_domain_in_hcl_body(
    wakir_conf_text: str,
) -> None:
    body = _strip_hcl_comments(wakir_conf_text)
    assert "partner.test" not in body, (
        "wakir-side agent config HCL body must not reference partner.test "
        "(no federates_with block on agent side; comments excluded)"
    )


def test_partner_does_not_carry_wakir_trust_domain_in_hcl_body(
    partner_conf_text: str,
) -> None:
    body = _strip_hcl_comments(partner_conf_text)
    assert "wakir.test" not in body, (
        "partner-side agent config HCL body must not reference wakir.test "
        "(no federates_with block on agent side; comments excluded)"
    )


# ---------------------------------------------------------------------
# Server-Admin-API wiring (per-side DNS)
# ---------------------------------------------------------------------


def test_wakir_server_address(wakir_conf_text: str) -> None:
    assert re.search(
        r'server_address\s*=\s*"spire-server-wakir"', wakir_conf_text
    ), "wakir-side server_address must be 'spire-server-wakir'"


def test_partner_server_address(partner_conf_text: str) -> None:
    assert re.search(
        r'server_address\s*=\s*"spire-server-partner"',
        partner_conf_text,
    ), "partner-side server_address must be 'spire-server-partner'"


@pytest.mark.parametrize(
    "conf_text_fix",
    ["wakir_conf_text", "partner_conf_text"],
)
def test_server_port_8081(conf_text_fix: str, request: pytest.FixtureRequest) -> None:
    text = request.getfixturevalue(conf_text_fix)
    assert re.search(r'server_port\s*=\s*"8081"', text), (
        f"{conf_text_fix} server_port must be 8081 (parity with Tag-1 "
        f"federation server gRPC bind_port)"
    )


# ---------------------------------------------------------------------
# Federation trust-bundle wiring
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "conf_text_fix",
    ["wakir_conf_text", "partner_conf_text"],
)
def test_trust_bundle_path_wired_to_federation_bundles(
    conf_text_fix: str, request: pytest.FixtureRequest
) -> None:
    text = request.getfixturevalue(conf_text_fix)
    assert re.search(
        r'trust_bundle_path\s*=\s*"/var/lib/spire/bundles/bootstrap\.jwks"',
        text,
    ), (
        f"{conf_text_fix} trust_bundle_path must be wired to the "
        f"federated-bundles ingest path /var/lib/spire/bundles/bootstrap.jwks"
    )


@pytest.mark.parametrize(
    "conf_text_fix",
    ["wakir_conf_text", "partner_conf_text"],
)
def test_trust_bundle_format_jwks(
    conf_text_fix: str, request: pytest.FixtureRequest
) -> None:
    text = request.getfixturevalue(conf_text_fix)
    assert re.search(
        r'trust_bundle_format\s*=\s*"spiffe"', text
    ), (
        f"{conf_text_fix} trust_bundle_format must be 'spiffe' (JWKS — "
        f"federation https_spiffe profile parity with Tag-1)"
    )


@pytest.mark.parametrize(
    "conf_text_fix",
    ["wakir_conf_text", "partner_conf_text"],
)
def test_insecure_bootstrap_false_for_federation(
    conf_text_fix: str, request: pytest.FixtureRequest
) -> None:
    text = request.getfixturevalue(conf_text_fix)
    assert re.search(
        r'insecure_bootstrap\s*=\s*false', text
    ), (
        f"{conf_text_fix} insecure_bootstrap must be false for federation "
        f"(stricter than Sprint-6 single-trust-domain agent config)"
    )


# ---------------------------------------------------------------------
# Workload-API socket-path (SPIFFE-spec convention)
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "conf_text_fix",
    ["wakir_conf_text", "partner_conf_text"],
)
def test_workload_api_socket_path_spiffe_canonical(
    conf_text_fix: str, request: pytest.FixtureRequest
) -> None:
    text = request.getfixturevalue(conf_text_fix)
    assert re.search(
        r'socket_path\s*=\s*"/run/spire/agent-sockets/api\.sock"',
        text,
    ), (
        f"{conf_text_fix} socket_path must be the SPIFFE-spec canonical "
        f"/run/spire/agent-sockets/api.sock (Phase-2.3+ persona-Workload-"
        f"API consumers depend on this convention)"
    )


# ---------------------------------------------------------------------
# Plugin shape (parity with Sprint-6 Tag-9)
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "conf_text_fix,expected_plugins",
    [
        (
            "wakir_conf_text",
            ["NodeAttestor \"join_token\"", "KeyManager \"memory\"", "WorkloadAttestor \"unix\""],
        ),
        (
            "partner_conf_text",
            ["NodeAttestor \"join_token\"", "KeyManager \"memory\"", "WorkloadAttestor \"unix\""],
        ),
    ],
)
def test_plugin_shape(
    conf_text_fix: str,
    expected_plugins: list[str],
    request: pytest.FixtureRequest,
) -> None:
    text = request.getfixturevalue(conf_text_fix)
    for plugin_decl in expected_plugins:
        assert plugin_decl in text, (
            f"{conf_text_fix} must declare plugin {plugin_decl!r}"
        )
