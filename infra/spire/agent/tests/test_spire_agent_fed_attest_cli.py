# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the Sprint-8 Tag-2 spire-agent-fed-
attest CLI Mock (``infra/spire/agent/bin/spire_agent_fed_attest.py``).

Asserts:
  * X.509-SVID Mock subcommand emits a SPIFFE-ID under the requested
    trust-domain.
  * JWT-SVID Mock subcommand emits the ``mock-jwt`` auth_mode_marker
    expected by Reza's RealNatsConnectionAdapter fallback contract.
  * Determinism: same inputs yield same outputs (no clock, no random,
    no network).
  * Audience-binding: different audiences yield different JWT-SVID
    seeds (token_hint differs).
  * Trust-domain mismatch guard: requesting a non-Tag-1-federation
    trust-domain rejects with exit-code 2 (mirror of Tag-1
    spire-fed-bundle convention).
  * Selector validation: malformed selector rejects with ValueError /
    exit-code 2.
  * Closed-set invariant: the accepted trust-domain set is exactly
    {wakir.test, partner.test} — extending requires a server-side
    federates_with block, NOT a CLI-only change.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
AGENT_DIR = HERE.parent
BIN = AGENT_DIR / "bin" / "spire-agent-fed-attest"
MOD = AGENT_DIR / "bin" / "spire_agent_fed_attest.py"


# Add the bin/ directory to sys.path so the module can be imported
# (mirror of Tag-1 spire-fed-bundle test convention).
sys.path.insert(0, str(AGENT_DIR / "bin"))

import spire_agent_fed_attest as fed_attest  # noqa: E402


def _run_cli(*args: str) -> tuple[int, str, str]:
    """Invoke the shim CLI as a subprocess; return (rc, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, str(BIN), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------
# fetch-x509 — X.509-SVID Mock
# ---------------------------------------------------------------------


def test_fetch_x509_wakir_side() -> None:
    out = fed_attest.fetch_x509_svid(
        "1000:1000:/usr/bin/wirelang", "wakir.test"
    )
    assert out["kind"] == "x509-svid-mock"
    assert out["spiffe_id"].startswith("spiffe://wakir.test/workload/")
    assert out["trust_domain"] == "wakir.test"
    assert out["selector"]["uid"] == "1000"
    assert out["selector"]["gid"] == "1000"
    assert out["selector"]["path"] == "/usr/bin/wirelang"


def test_fetch_x509_partner_side() -> None:
    out = fed_attest.fetch_x509_svid(
        "1000:1000:/usr/bin/wirelang", "partner.test"
    )
    assert out["spiffe_id"].startswith("spiffe://partner.test/workload/")
    assert out["trust_domain"] == "partner.test"


def test_fetch_x509_determinism() -> None:
    a = fed_attest.fetch_x509_svid(
        "1000:1000:/usr/bin/wirelang", "wakir.test"
    )
    b = fed_attest.fetch_x509_svid(
        "1000:1000:/usr/bin/wirelang", "wakir.test"
    )
    assert a == b, (
        "fetch-x509 must be deterministic (no clock, no random)"
    )


def test_fetch_x509_cross_trust_domain_yields_different_seeds() -> None:
    """Selector-to-trust-domain mapping is the key Tag-2 substrate
    invariant: same selector, different trust-domains, different
    SVIDs."""
    wakir = fed_attest.fetch_x509_svid(
        "1000:1000:/usr/bin/wirelang", "wakir.test"
    )
    partner = fed_attest.fetch_x509_svid(
        "1000:1000:/usr/bin/wirelang", "partner.test"
    )
    assert wakir["cert_hint"] != partner["cert_hint"], (
        "different trust-domains must yield different Mock cert_hints"
    )
    assert wakir["spiffe_id"] != partner["spiffe_id"], (
        "different trust-domains must yield different SPIFFE-IDs"
    )


def test_fetch_x509_rejects_non_tag1_trust_domain() -> None:
    with pytest.raises(ValueError, match="not in Tag-1 federation pair"):
        fed_attest.fetch_x509_svid(
            "1000:1000:/usr/bin/wirelang", "example.test"
        )


# ---------------------------------------------------------------------
# fetch-jwt — JWT-SVID Mock (fallback path for RealAdapter)
# ---------------------------------------------------------------------


def test_fetch_jwt_emits_mock_jwt_auth_mode_marker() -> None:
    """JWT-SVID fallback path — this is the shape Reza's
    RealNatsConnectionAdapter consumes when SPIRE_AGENT_SOCKET=none.
    The auth_mode_marker literal must match the RealAdapter constant."""
    out = fed_attest.fetch_jwt_svid(
        "1000:1000:/usr/bin/wirelang",
        "nats://wakir-orchestrator",
        "wakir.test",
    )
    assert out["auth_mode_marker"] == "mock-jwt", (
        "JWT-SVID Mock must carry auth_mode_marker='mock-jwt' to match "
        "Reza's RealNatsConnectionAdapter SPIRE_AGENT_SOCKET=none fallback"
    )
    assert out["audience"] == "nats://wakir-orchestrator"


def test_fetch_jwt_audience_binding() -> None:
    """Different audiences yield different token_hints (audience-
    binding pattern)."""
    a = fed_attest.fetch_jwt_svid(
        "1000:1000:/usr/bin/wirelang", "aud-a", "wakir.test"
    )
    b = fed_attest.fetch_jwt_svid(
        "1000:1000:/usr/bin/wirelang", "aud-b", "wakir.test"
    )
    assert a["token_hint"] != b["token_hint"]


def test_fetch_jwt_rejects_empty_audience() -> None:
    with pytest.raises(ValueError, match="audience must be non-empty"):
        fed_attest.fetch_jwt_svid(
            "1000:1000:/usr/bin/wirelang", "", "wakir.test"
        )


# ---------------------------------------------------------------------
# Selector validation
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_selector",
    [
        "",
        "just-one-part",
        "uid:gid",  # missing path
        ":1000:/path",  # empty uid
        "1000::/path",  # empty gid
        "1000:1000:",  # empty path
    ],
)
def test_selector_validation_rejects_malformed(bad_selector: str) -> None:
    with pytest.raises(ValueError):
        fed_attest.fetch_x509_svid(bad_selector, "wakir.test")


# ---------------------------------------------------------------------
# CLI integration (subprocess; exit-code contract)
# ---------------------------------------------------------------------


def test_cli_fetch_x509_returns_json_on_stdout() -> None:
    rc, stdout, stderr = _run_cli(
        "fetch-x509",
        "--selector",
        "1000:1000:/usr/bin/wirelang",
        "--trust-domain",
        "wakir.test",
    )
    assert rc == 0, f"CLI must exit 0; stderr={stderr!r}"
    doc = json.loads(stdout)
    assert doc["kind"] == "x509-svid-mock"
    assert doc["trust_domain"] == "wakir.test"


def test_cli_fetch_jwt_returns_mock_jwt_marker() -> None:
    rc, stdout, _ = _run_cli(
        "fetch-jwt",
        "--selector",
        "1000:1000:/usr/bin/wirelang",
        "--audience",
        "nats://wakir-orchestrator",
        "--trust-domain",
        "partner.test",
    )
    assert rc == 0
    doc = json.loads(stdout)
    assert doc["auth_mode_marker"] == "mock-jwt"
    assert doc["trust_domain"] == "partner.test"


def test_cli_rejects_unknown_trust_domain_with_exit_2() -> None:
    """Trust-domain mismatch guard — exit-code 2 mirrors Tag-1
    spire-fed-bundle convention."""
    rc, _, stderr = _run_cli(
        "fetch-x509",
        "--selector",
        "1000:1000:/usr/bin/wirelang",
        "--trust-domain",
        "example.test",
    )
    # argparse with choices= rejects with exit-code 2 before reaching
    # the body validation — both paths converge to exit-code 2 which
    # is the intended Tag-1 contract.
    assert rc == 2
    assert "example.test" in stderr or "invalid choice" in stderr.lower()


# ---------------------------------------------------------------------
# Closed-set invariant
# ---------------------------------------------------------------------


def test_closed_set_trust_domain_pair() -> None:
    """The accepted trust-domain set is exactly the Tag-1 federation
    pair. Extending requires a server-side federates_with block, NOT
    a CLI-only change — this guard catches accidental scope-creep."""
    assert fed_attest._TRUST_DOMAINS_TAG1 == frozenset(
        {"wakir.test", "partner.test"}
    ), (
        "Tag-1 federation pair must be exactly {wakir.test, partner.test}; "
        "adding more trust-domains requires Cross-Review with Reza and "
        "a server-side federates_with block first"
    )
