# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic Skizze-Validations tests for the SPIFFE Z-A JWT-SVID skizze.

These tests do NOT spin up a SPIRE server, a NATS cluster, or any
network endpoint. They validate that the Skizze-internal format
constants in ``scripts/spiffe_skizze_constants.py`` are well-formed
according to the proposals in ``docs/spiffe-z-a-jwt-svid-skizze.md``
§2, §3.1, §3.2, §4.1.

When Cross-Review Zone A consensus later overrides one of these
proposals (different trust-domain format, different hash length,
different socket path), these tests break loudly and force a co-edit
of the constants module — the same drift-detection discipline the
dual-anchor parity tests use for the orchestrator-vs-Wirelang bucket
config mirror.

Coverage:

- T-Tag6-Z-A-01: SPIFFE-ID format patterns accept the §3.1 / §3.2
  exemplars and reject obviously malformed inputs.
- T-Tag6-Z-A-02: ``PERSONA_HASH_SHORT_LEN`` is 12 and the regex
  enforces exactly that length on the persona-hash path-component.
- T-Tag6-Z-A-03: Workload-API socket path matches the §4.1 documented
  Phase-2 default and is overridable via the documented env-var name.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


# ---------------------------------------------------------------------
# Module loader: the constants live under
# scripts/spiffe_skizze_constants.py
# ---------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
CONSTANTS_PATH = REPO_ROOT / "scripts" / "spiffe_skizze_constants.py"


def _load_constants():
    spec = importlib.util.spec_from_file_location(
        "spiffe_skizze_constants", CONSTANTS_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def constants():
    return _load_constants()


# ---------------------------------------------------------------------
# T-Tag6-Z-A-01
# ---------------------------------------------------------------------


def test_spiffe_id_pattern_constants_are_well_formed(constants):
    """Persona-ID and Service-ID patterns accept §3.1/§3.2 exemplars
    and reject obviously malformed inputs.

    Pins: §3.1 persona-container SPIFFE-ID pattern, §3.2 substrate-
    service SPIFFE-ID pattern, and §2 trust-domain default
    ``wakir.local``.
    """
    # §2 trust-domain default.
    assert constants.TRUST_DOMAIN_PHASE_2 == "wakir.local"
    # Phase-3a template must contain the ``{org_id}`` placeholder.
    assert "{org_id}" in constants.TRUST_DOMAIN_PHASE_3A_TEMPLATE
    assert constants.TRUST_DOMAIN_PHASE_3A_TEMPLATE.endswith(".wakir.dev")

    # §3.1 persona-ID path-only acceptors (Skizze §3.1 table examples).
    accept_persona = [
        "/agent/mira/a3f2c1e8d4b7",
        "/agent/kai/0123456789ab",
        "/agent/reza/ffffffffffff",
        "/agent/tomas/000000000000",
        "/agent/aisha/deadbeefcafe",
    ]
    for spiffe_path in accept_persona:
        match = constants.PERSONA_ID_PATH_PATTERN.match(spiffe_path)
        assert match is not None, f"expected accept: {spiffe_path}"

    # §3.1 persona-ID path-only rejecters.
    reject_persona = [
        "/agent/Mira/a3f2c1e8d4b7",          # upper-case slug
        "/agent/mira/A3F2C1E8D4B7",          # upper-case hex
        "/agent/mira/a3f2c1e8d4b",           # 11 chars (too short)
        "/agent/mira/a3f2c1e8d4b7c",         # 13 chars (too long)
        "/agent/mira/g3f2c1e8d4b7",          # non-hex char 'g'
        "/agent/m/a3f2c1e8d4b7",             # 1-char slug (below min 2)
        "/agent//a3f2c1e8d4b7",              # empty slug
        "/agent/mira",                        # missing hash
        "agent/mira/a3f2c1e8d4b7",           # missing leading slash
        "/service/mira/a3f2c1e8d4b7",        # wrong type component
    ]
    for spiffe_path in reject_persona:
        match = constants.PERSONA_ID_PATH_PATTERN.match(spiffe_path)
        assert match is None, f"expected reject: {spiffe_path}"

    # §3.1 full-form acceptors (trust-domain + path).
    full_form = (
        f"spiffe://{constants.TRUST_DOMAIN_PHASE_2}"
        "/agent/mira/a3f2c1e8d4b7"
    )
    full_match = constants.PERSONA_ID_FULL_PATTERN.match(full_form)
    assert full_match is not None
    assert full_match.group("trust") == "wakir.local"
    assert full_match.group("slug") == "mira"
    assert full_match.group("hash") == "a3f2c1e8d4b7"

    # §3.2 service-ID path-only acceptors (Skizze §3.2 table; all four
    # known services are present in the KNOWN_PHASE_2_SERVICES set).
    expected_services = {
        "nats",
        "orchestrator",
        "spire-server",
        "health-check-cron",
    }
    assert constants.KNOWN_PHASE_2_SERVICES == frozenset(expected_services)
    for service_name in expected_services:
        path = f"/service/{service_name}"
        match = constants.SERVICE_ID_PATH_PATTERN.match(path)
        assert match is not None, f"expected accept: {path}"
        assert match.group("name") == service_name

    # §3.2 service-ID rejecters.
    reject_service = [
        "/service/NATS",                  # upper-case
        "/service/-leading-hyphen",       # leading hyphen
        "/service/x",                     # 1-char (below min 2)
        "/service/" + "a" * 33,           # 33 chars (above max 32)
        "/service/with spaces",           # whitespace
        "/agent/nats",                    # wrong type component
    ]
    for path in reject_service:
        match = constants.SERVICE_ID_PATH_PATTERN.match(path)
        assert match is None, f"expected reject: {path}"


# ---------------------------------------------------------------------
# T-Tag6-Z-A-02
# ---------------------------------------------------------------------


def test_persona_hash_short_is_12_hex_chars(constants):
    """Persona-hash short form is exactly 12 lower-case hex chars.

    Pins: §3.1 ``<persona-hash-12>`` length proposal. If Z-A consensus
    overrides to 8 / 16 / 32 chars, this test must be co-edited.
    """
    assert constants.PERSONA_HASH_SHORT_LEN == 12

    # The regex must enforce exactly PERSONA_HASH_SHORT_LEN chars.
    base = "/agent/mira/"
    twelve = "a" * constants.PERSONA_HASH_SHORT_LEN
    assert constants.PERSONA_ID_PATH_PATTERN.match(base + twelve) is not None

    # One short.
    eleven = "a" * (constants.PERSONA_HASH_SHORT_LEN - 1)
    assert constants.PERSONA_ID_PATH_PATTERN.match(base + eleven) is None

    # One long.
    thirteen = "a" * (constants.PERSONA_HASH_SHORT_LEN + 1)
    assert constants.PERSONA_ID_PATH_PATTERN.match(base + thirteen) is None

    # Lower-case hex only; reject upper-case even at correct length.
    upper_twelve = "A" * constants.PERSONA_HASH_SHORT_LEN
    assert (
        constants.PERSONA_ID_PATH_PATTERN.match(base + upper_twelve) is None
    )

    # Reject non-hex char at correct length.
    non_hex_twelve = "g" + "a" * (constants.PERSONA_HASH_SHORT_LEN - 1)
    assert (
        constants.PERSONA_ID_PATH_PATTERN.match(base + non_hex_twelve)
        is None
    )


# ---------------------------------------------------------------------
# T-Tag6-Z-A-03
# ---------------------------------------------------------------------


def test_workload_api_socket_path_is_documented_phase_2_default(constants):
    """Workload-API socket path matches §4.1 Phase-2 default and is
    overridable via the documented env-var name.

    Pins: §4.1 ``/run/spire/sockets/agent.sock`` as the boring-default
    Phase-2 socket path, plus ``SPIFFE_ENDPOINT_SOCKET`` as the SPIFFE-
    spec-defined override env-var (matches the ``go-spiffe`` and
    ``HewlettPackard/py-spiffe`` GitHub-repo upstream conventions; the
    PyPI package name for the Python client is ``spiffe``, see Skizze
    §6 §2 Sprint-6-Tag-5 re-write).
    """
    # §4.1 default.
    assert (
        constants.WORKLOAD_API_SOCKET_PATH_PHASE_2
        == "/run/spire/sockets/agent.sock"
    )

    # Path must be absolute (starts with '/') and end with ``.sock``.
    assert constants.WORKLOAD_API_SOCKET_PATH_PHASE_2.startswith("/")
    assert constants.WORKLOAD_API_SOCKET_PATH_PHASE_2.endswith(".sock")

    # Env-var name follows SPIFFE-spec convention (``SPIFFE_ENDPOINT_SOCKET``).
    # Pinning the spelling here prevents a silent drift to a wakir-local
    # name that would break ``spiffe`` PyPI-package consumers (the Python
    # client published from the ``HewlettPackard/py-spiffe`` GitHub repo).
    assert constants.WORKLOAD_API_SOCKET_ENV_VAR == "SPIFFE_ENDPOINT_SOCKET"

    # JWT-SVID TTL default is 15 minutes (SPIRE boring-default).
    assert constants.JWT_SVID_TTL_SECONDS_PHASE_2 == 15 * 60

    # NATS audience default is the Phase-2 single-node URL.
    assert (
        constants.NATS_JWT_AUDIENCE_PHASE_2
        == f"nats://{constants.TRUST_DOMAIN_PHASE_2}"
    )
