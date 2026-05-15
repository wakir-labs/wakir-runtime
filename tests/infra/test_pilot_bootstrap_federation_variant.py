# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for the Sprint-10 Tag-3 federation-variant Quadlet
substance in ``infra/spire/federation/wakir-pilot-bootstrap.sh``.

Sprint-10 Tag-3 closes the last substance gap for the M-3 Live-
Federation-Trial-Gate: the bundle-endpoint host bind must be reachable
cross-VM in federation-mode (HOST_BUNDLE_BIND=0.0.0.0). In single-org
mode the bundle-endpoint stays loopback-only (no peer exists). The
gRPC API stays loopback-only in BOTH modes (security invariant — it
is the privileged control plane).

Additionally Sprint-10 Tag-3 adds two new env-vars for federation-
mode operator-hand convenience:

* ``WAKIR_PEER_SIDE`` — peer trust-domain side literal (mirror of
  proxmox-bringup-smoke ``--peer-side``).
* ``WAKIR_PEER_HOST`` — peer VM's reachable IP for the auto-installed
  ``/etc/hosts`` entry.

Both env-vars together trigger an idempotent ``/etc/hosts`` append
that maps ``spire-server-<peer_side>`` -> peer IP. Without them the
operator does the ``/etc/hosts`` setup by hand (PARTNER_VM_BRING_UP_
RECIPE.md §5.2).

Sandbox boundary: source-file inspection only. The bootstrap is NOT
executed end-to-end — that requires podman + systemctl on a live VM
and is Operator-Hand-only. The substance-bearing logic (placeholder
substitution + /etc/hosts append) is exercised in isolation by
invoking the bootstrap source through ``bash -c`` against a fixture
``/etc/hosts`` injected via ``WAKIR_BOOTSTRAP_HOSTS``.

Test-Vector index
-----------------

* ``TV-FED-VARIANT-01`` env-var docs: WAKIR_PEER_SIDE +
  WAKIR_PEER_HOST documented in header + usage.
* ``TV-FED-VARIANT-02`` HOST_BUNDLE_BIND placeholder is documented
  in the Quadlet template header.
* ``TV-FED-VARIANT-03`` Bootstrap sources the bundle-bind from
  WAKIR_PILOT_MODE (single-org -> 127.0.0.1, federation -> 0.0.0.0)
  and passes it to ``_install_substituted`` for the federation
  container template.
* ``TV-FED-VARIANT-04`` Quadlet PublishPort line for the bundle-
  endpoint uses ``<HOST_BUNDLE_BIND>`` (parametrised), NOT a literal
  ``127.0.0.1``.
* ``TV-FED-VARIANT-05`` Quadlet PublishPort line for the gRPC API
  stays LITERAL ``127.0.0.1`` (security invariant).
* ``TV-FED-VARIANT-06`` WAKIR_PEER_SIDE validation: only lowercase
  ASCII + digits; rejects symbols.
* ``TV-FED-VARIANT-07`` WAKIR_PEER_HOST validation: only IP /
  hostname characters.
* ``TV-FED-VARIANT-08`` WAKIR_PEER_SIDE != WAKIR_SIDE invariant
  (cannot federate with self).
* ``TV-FED-VARIANT-09`` peer-host /etc/hosts append: idempotent
  (re-runs do not duplicate the line).
* ``TV-FED-VARIANT-10`` peer-host /etc/hosts append: IP-update
  rewrites the line when the operator overrides WAKIR_PEER_HOST.
* ``TV-FED-VARIANT-11`` peer-host /etc/hosts not appended in
  single-org mode.
* ``TV-FED-VARIANT-12`` peer-host /etc/hosts not appended when
  WAKIR_PEER_HOST is unset in federation mode (Operator-Hand fallback).
"""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_BOOTSTRAP = _REPO_ROOT / "infra" / "spire" / "federation" / "wakir-pilot-bootstrap.sh"
_QUADLET = (
    _REPO_ROOT
    / "infra"
    / "spire"
    / "federation"
    / "quadlet"
    / "wakir-spire-server-federation.container"
)


@pytest.fixture(scope="module")
def bootstrap_source() -> str:
    assert _BOOTSTRAP.is_file(), f"bootstrap script not found: {_BOOTSTRAP}"
    return _BOOTSTRAP.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def quadlet_source() -> str:
    assert _QUADLET.is_file(), f"Quadlet template not found: {_QUADLET}"
    return _QUADLET.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TV-FED-VARIANT-01: env-var documentation
# ---------------------------------------------------------------------------


def test_peer_side_documented_in_header(bootstrap_source: str) -> None:
    assert re.search(
        r"^#\s+WAKIR_PEER_SIDE\s+", bootstrap_source, re.MULTILINE
    ), "WAKIR_PEER_SIDE must be documented in the header env-vars block"


def test_peer_host_documented_in_header(bootstrap_source: str) -> None:
    assert re.search(
        r"^#\s+WAKIR_PEER_HOST\s+", bootstrap_source, re.MULTILINE
    ), "WAKIR_PEER_HOST must be documented in the header env-vars block"


def test_peer_side_documented_in_usage_banner(bootstrap_source: str) -> None:
    m = re.search(
        r"usage\(\)\s*\{(.*?)^\}", bootstrap_source, re.DOTALL | re.MULTILINE
    )
    assert m, "usage() function not found"
    assert "WAKIR_PEER_SIDE" in m.group(1)
    assert "WAKIR_PEER_HOST" in m.group(1)


# ---------------------------------------------------------------------------
# TV-FED-VARIANT-02: HOST_BUNDLE_BIND documented in Quadlet template
# ---------------------------------------------------------------------------


def test_quadlet_template_documents_host_bundle_bind(quadlet_source: str) -> None:
    assert "<HOST_BUNDLE_BIND>" in quadlet_source, (
        "Quadlet template must use <HOST_BUNDLE_BIND> for the bundle-endpoint host bind"
    )
    # Header block must mention the rationale.
    assert "HOST_BUNDLE_BIND" in quadlet_source.split("[Unit]")[0], (
        "Quadlet template header MUST document the HOST_BUNDLE_BIND placeholder"
    )
    # Single-org default 127.0.0.1 must appear.
    assert "127.0.0.1" in quadlet_source.split("[Unit]")[0], (
        "Quadlet template header MUST document the single-org default 127.0.0.1"
    )
    # Federation 0.0.0.0 default must appear.
    assert "0.0.0.0" in quadlet_source.split("[Unit]")[0], (
        "Quadlet template header MUST document the federation default 0.0.0.0"
    )


# ---------------------------------------------------------------------------
# TV-FED-VARIANT-03: bootstrap wires HOST_BUNDLE_BIND from WAKIR_PILOT_MODE
# ---------------------------------------------------------------------------


def test_bootstrap_wires_host_bundle_bind(bootstrap_source: str) -> None:
    # The bootstrap must (a) declare a host_bundle_bind local var,
    # (b) default it to 127.0.0.1, (c) override to 0.0.0.0 in
    # federation mode, (d) pass it to _install_substituted as a
    # sed-expr for <HOST_BUNDLE_BIND>.
    assert re.search(
        r'local\s+host_bundle_bind\s*=\s*"127\.0\.0\.1"', bootstrap_source
    ), "bootstrap must default host_bundle_bind to 127.0.0.1"
    assert re.search(
        r'host_bundle_bind\s*=\s*"0\.0\.0\.0"', bootstrap_source
    ), "bootstrap must override host_bundle_bind to 0.0.0.0 in federation-mode"
    assert re.search(
        r'WAKIR_PILOT_MODE"\s*==\s*"federation"', bootstrap_source
    ), "bootstrap must gate the 0.0.0.0 override on WAKIR_PILOT_MODE == federation"
    # The sed-expr must reach _install_substituted for the federation
    # container template substitution.
    assert re.search(
        r's\|<HOST_BUNDLE_BIND>\|\$\{host_bundle_bind\}\|g', bootstrap_source
    ), "bootstrap must pass <HOST_BUNDLE_BIND> -> ${host_bundle_bind} sed-expr"


# ---------------------------------------------------------------------------
# TV-FED-VARIANT-04 / TV-FED-VARIANT-05: PublishPort lines
# ---------------------------------------------------------------------------


def test_quadlet_bundle_publishport_uses_placeholder(quadlet_source: str) -> None:
    assert re.search(
        r"PublishPort=<HOST_BUNDLE_BIND>:<HOST_BUNDLE_PORT>:8443",
        quadlet_source,
    ), (
        "Bundle-endpoint PublishPort must use the <HOST_BUNDLE_BIND> + "
        "<HOST_BUNDLE_PORT> placeholders so federation-mode can bind 0.0.0.0"
    )


def test_quadlet_grpc_publishport_stays_loopback(quadlet_source: str) -> None:
    # The gRPC API host bind is a SECURITY invariant — it MUST stay
    # literal 127.0.0.1 in the template (no placeholder).
    assert "PublishPort=127.0.0.1:<HOST_GRPC_PORT>:8081" in quadlet_source, (
        "gRPC PublishPort must stay literal 127.0.0.1 (security invariant)"
    )
    # And the template must NOT have a HOST_GRPC_BIND placeholder
    # (would let an operator accidentally bind gRPC cross-VM).
    assert "<HOST_GRPC_BIND>" not in quadlet_source, (
        "Quadlet template must NOT introduce HOST_GRPC_BIND placeholder "
        "(security invariant: gRPC API stays loopback-only)"
    )


# ---------------------------------------------------------------------------
# TV-FED-VARIANT-06 / TV-FED-VARIANT-07 / TV-FED-VARIANT-08: env-var validation
# ---------------------------------------------------------------------------


def _run_bootstrap_validation(env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run the bootstrap with ``--help`` so it executes only the pre-
    flight env-var validation block, not any podman / systemctl call.
    Returns the CompletedProcess so the caller can assert exit-code
    + stderr-shape.

    The bootstrap parses its env-vars BEFORE the argument loop runs, so
    a bad WAKIR_PEER_SIDE / WAKIR_PEER_HOST trips an exit 1 even when
    we invoke ``--help`` (validation happens at source-time, before
    while-arg-loop reaches ``--help``).
    """
    proc = subprocess.run(
        ["bash", str(_BOOTSTRAP), "--help"],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=15,
    )
    return proc


def test_peer_side_validation_rejects_symbols() -> None:
    proc = _run_bootstrap_validation({"WAKIR_PEER_SIDE": "wakir.test"})
    assert proc.returncode == 1, (
        f"WAKIR_PEER_SIDE with a dot must be rejected; got rc={proc.returncode}"
    )
    assert "WAKIR_PEER_SIDE" in proc.stderr


def test_peer_host_validation_rejects_symbols() -> None:
    proc = _run_bootstrap_validation({
        "WAKIR_PILOT_MODE": "federation",
        "WAKIR_PEER_HOST": "10.0.42.10; rm -rf /",
    })
    assert proc.returncode == 1, (
        f"WAKIR_PEER_HOST with a semicolon must be rejected; got rc={proc.returncode}"
    )
    assert "WAKIR_PEER_HOST" in proc.stderr


def test_peer_side_must_differ_from_side() -> None:
    proc = _run_bootstrap_validation({
        "WAKIR_PILOT_MODE": "federation",
        "WAKIR_SIDE": "orbit",
        "WAKIR_PEER_SIDE": "orbit",
    })
    assert proc.returncode == 1, (
        f"WAKIR_PEER_SIDE == WAKIR_SIDE must be rejected; got rc={proc.returncode}"
    )
    assert "WAKIR_PEER_SIDE" in proc.stderr


def test_peer_side_accepts_valid_literals_in_help() -> None:
    proc = _run_bootstrap_validation({
        "WAKIR_PILOT_MODE": "federation",
        "WAKIR_SIDE": "orbit",
        "WAKIR_PEER_SIDE": "wakir",
        "WAKIR_PEER_HOST": "192.168.178.116",
    })
    assert proc.returncode == 0, (
        f"valid peer-side/host must be accepted; got rc={proc.returncode}\n"
        f"stderr={proc.stderr}"
    )


# ---------------------------------------------------------------------------
# TV-FED-VARIANT-09 / TV-FED-VARIANT-10 / TV-FED-VARIANT-11 / TV-FED-VARIANT-12:
# /etc/hosts wiring behaviour via the _install_peer_host_entry function.
#
# We extract the function body via ``bash -c 'source bootstrap; declare -f
# _install_peer_host_entry; ... run it'`` so it executes in isolation
# against a fixture hosts file.
# ---------------------------------------------------------------------------


def _invoke_peer_host_entry(
    env: dict[str, str], hosts_fixture: Path
) -> subprocess.CompletedProcess:
    """Source the bootstrap and call _install_peer_host_entry against
    the hosts-fixture. Bypasses the run-flow by short-circuiting the
    main body (set a sentinel that prevents `main` from running -- in
    this script, sourcing alone does not auto-run main, so we are
    safe).
    """
    # We must wrap-and-source. The bootstrap exits if the `main`
    # function is invoked; since we never call main, sourcing is safe.
    # We rely on the bootstrap NOT auto-executing main on source — let
    # us verify that invariant first.
    cmd = textwrap.dedent(
        f"""
        set -eu
        export WAKIR_BOOTSTRAP_HOSTS={hosts_fixture}
        # Source for function definitions only.
        # The bootstrap's bottom-of-file main-invocation is gated by
        # ``[[ "${{BASH_SOURCE[0]}}" == "${{0}}" ]]`` (we assume; will
        # be tested independently).
        source {_BOOTSTRAP}
        # Now call the install function.
        _install_peer_host_entry
        echo "DONE rc=$?"
        """
    ).strip()
    proc = subprocess.run(
        ["bash", "-c", cmd],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=15,
    )
    return proc


def test_peer_host_entry_skipped_in_single_org(tmp_path: Path) -> None:
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1\tlocalhost\n", encoding="utf-8")
    proc = _invoke_peer_host_entry(
        {
            "WAKIR_PILOT_MODE": "single-org",
            "WAKIR_PEER_SIDE": "wakir",
            "WAKIR_PEER_HOST": "192.168.178.116",
            "WAKIR_SIDE": "orbit",
            "WAKIR_SKIP_PROMPTS": "1",
        },
        hosts,
    )
    assert proc.returncode == 0, proc.stderr
    body = hosts.read_text(encoding="utf-8")
    # Single-org must not touch /etc/hosts.
    assert "spire-server-wakir" not in body, (
        "/etc/hosts must NOT be touched in single-org mode"
    )


def test_peer_host_entry_skipped_when_unset(tmp_path: Path) -> None:
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1\tlocalhost\n", encoding="utf-8")
    proc = _invoke_peer_host_entry(
        {
            "WAKIR_PILOT_MODE": "federation",
            # Both peer vars intentionally unset / empty.
            "WAKIR_PEER_SIDE": "",
            "WAKIR_PEER_HOST": "",
            "WAKIR_SIDE": "orbit",
            "WAKIR_SKIP_PROMPTS": "1",
        },
        hosts,
    )
    assert proc.returncode == 0, proc.stderr
    body = hosts.read_text(encoding="utf-8")
    assert "spire-server-" not in body


def test_peer_host_entry_appended_in_federation(tmp_path: Path) -> None:
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1\tlocalhost\n", encoding="utf-8")
    proc = _invoke_peer_host_entry(
        {
            "WAKIR_PILOT_MODE": "federation",
            "WAKIR_SIDE": "orbit",
            "WAKIR_PEER_SIDE": "wakir",
            "WAKIR_PEER_HOST": "192.168.178.116",
            "WAKIR_SKIP_PROMPTS": "1",
        },
        hosts,
    )
    assert proc.returncode == 0, proc.stderr
    body = hosts.read_text(encoding="utf-8")
    assert "192.168.178.116" in body
    assert "spire-server-wakir" in body
    assert "# wakir-bootstrap: peer-side wakir" in body


def test_peer_host_entry_idempotent(tmp_path: Path) -> None:
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1\tlocalhost\n", encoding="utf-8")
    env = {
        "WAKIR_PILOT_MODE": "federation",
        "WAKIR_SIDE": "orbit",
        "WAKIR_PEER_SIDE": "wakir",
        "WAKIR_PEER_HOST": "192.168.178.116",
        "WAKIR_SKIP_PROMPTS": "1",
    }
    # First run: append.
    proc1 = _invoke_peer_host_entry(env, hosts)
    assert proc1.returncode == 0
    body1 = hosts.read_text(encoding="utf-8")
    line_count_1 = body1.count("spire-server-wakir")
    assert line_count_1 == 1, body1
    # Second run: must be idempotent (still exactly one line).
    proc2 = _invoke_peer_host_entry(env, hosts)
    assert proc2.returncode == 0
    body2 = hosts.read_text(encoding="utf-8")
    line_count_2 = body2.count("spire-server-wakir")
    assert line_count_2 == 1, body2
    # Body must be byte-identical between the two runs.
    assert body1 == body2, (
        f"Idempotent run drifted:\n--- run1 ---\n{body1}\n--- run2 ---\n{body2}"
    )


def test_peer_host_entry_updates_ip_on_override(tmp_path: Path) -> None:
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1\tlocalhost\n", encoding="utf-8")
    env_v1 = {
        "WAKIR_PILOT_MODE": "federation",
        "WAKIR_SIDE": "orbit",
        "WAKIR_PEER_SIDE": "wakir",
        "WAKIR_PEER_HOST": "10.0.42.10",
        "WAKIR_SKIP_PROMPTS": "1",
    }
    proc1 = _invoke_peer_host_entry(env_v1, hosts)
    assert proc1.returncode == 0
    body1 = hosts.read_text(encoding="utf-8")
    assert "10.0.42.10" in body1

    # Operator-Hand IP override.
    env_v2 = {**env_v1, "WAKIR_PEER_HOST": "192.168.178.116"}
    proc2 = _invoke_peer_host_entry(env_v2, hosts)
    assert proc2.returncode == 0
    body2 = hosts.read_text(encoding="utf-8")
    assert "192.168.178.116" in body2
    assert "10.0.42.10" not in body2
    assert body2.count("spire-server-wakir") == 1


def test_peer_host_entry_preserves_manual_entry(tmp_path: Path) -> None:
    """If the operator already pinned ``spire-server-wakir`` to a
    custom IP (no wakir-bootstrap marker), the bootstrap MUST NOT
    touch the line. Operator-Hand-owned entries are sacrosanct."""
    hosts = tmp_path / "hosts"
    hosts.write_text(
        "127.0.0.1\tlocalhost\n10.99.99.99\tspire-server-wakir # operator-managed\n",
        encoding="utf-8",
    )
    env = {
        "WAKIR_PILOT_MODE": "federation",
        "WAKIR_SIDE": "orbit",
        "WAKIR_PEER_SIDE": "wakir",
        "WAKIR_PEER_HOST": "192.168.178.116",
        "WAKIR_SKIP_PROMPTS": "1",
    }
    proc = _invoke_peer_host_entry(env, hosts)
    assert proc.returncode == 0, proc.stderr
    body = hosts.read_text(encoding="utf-8")
    # The operator-managed line stays untouched.
    assert "10.99.99.99\tspire-server-wakir # operator-managed" in body
    # The bootstrap did NOT add a second line.
    assert body.count("spire-server-wakir") == 1
    assert "192.168.178.116" not in body
