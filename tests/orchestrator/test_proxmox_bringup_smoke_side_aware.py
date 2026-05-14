# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Sprint-10 Tag-1 side-aware extensions of
``bin/proxmox-bringup-smoke``.

Sprint-10 Tag-1 adds three substance items to the smoke skript:

1. ``--side <SIDE>`` argument (default: wakir; alt: orbit, partner).
   The skript parametrises Quadlet unit names + container names so the
   same smoke binary runs on EITHER the wakir-side or the orbit-side
   VM with identical shape.
2. ``--peer-side <SIDE>`` argument: activates two new Cross-VM
   Federation checks (``federation-bundle-sync-reachable`` +
   ``federation-cross-trust-domain-verify``). Gated on
   ``WAKIR_FEDERATION_MODE=enabled`` env-var.
3. ``SKIP`` status: when ``--peer-side`` is absent or
   ``WAKIR_FEDERATION_MODE`` is not ``enabled``, the federation checks
   emit ``SKIP`` (not ``FAIL``); summary line carries the skip count.

This test file covers the side-awareness substance — the existing
Sprint-9 Tag-1 tests (test_proxmox_bringup_smoke.py) keep covering
the baseline single-side smoke shape.

All tests are hermetic: bash-mock wrappers for systemctl/podman/curl
that drive the smoke skript through its branches. No real
systemctl/podman/curl/cluster.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SMOKE = _REPO_ROOT / "bin" / "proxmox-bringup-smoke"


def _write_mock_systemctl_for_side(tmp_path: Path, side: str) -> Path:
    """systemctl mock: declares the per-side units active."""
    mock = tmp_path / "systemctl"
    mock.write_text(
        f"""#!/usr/bin/env bash
set -u
# Echo "active" for the side-aware unit names, "active" for nats,
# and "inactive" (acceptable) for the oneshot. Any other unit -> empty.
case "${{2:-${{1:-}}}}" in
  wakir-nats.service) printf 'active\\n'; exit 0 ;;
  wakir-spire-server-federation-{side}.service) printf 'active\\n'; exit 0 ;;
  wakir-spire-agent-{side}.service) printf 'active\\n'; exit 0 ;;
  wakir-nats-kv-bucket-init.service) printf 'inactive\\n'; exit 0 ;;
  *) exit 0 ;;
esac
""",
        encoding="utf-8",
    )
    mock.chmod(0o755)
    return mock


def _write_mock_podman_for_side(
    tmp_path: Path,
    side: str,
    *,
    bundle_list_has_peer_td: str | None = None,
) -> Path:
    """podman mock for the given side.

    Args:
        side: ``wakir`` or ``orbit``; drives the expected container name
            ``wakir-spire-server-federation-<side>``.
        bundle_list_has_peer_td: if non-None, ``spire-server bundle list``
            output includes a "Trust Domain : <td>" header line for the
            given trust-domain (activates the federation-cross-trust-
            domain-verify happy path).
    """
    # The mock branches on $1 (subcommand) and $2 (container name).
    # We use a HEREDOC-shape so the script content is verbatim.
    bundle_list_block = ""
    if bundle_list_has_peer_td:
        bundle_list_block = (
            f"if [[ \"$4\" == bundle && \"$5\" == list ]]; then\n"
            f"  printf 'Trust Domain : {bundle_list_has_peer_td}\\n\\n-----BEGIN CERTIFICATE-----\\nMOCK\\n-----END CERTIFICATE-----\\n'\n"
            f"  exit 0\n"
            f"fi\n"
        )
    mock = tmp_path / "podman"
    mock.write_text(
        f"""#!/usr/bin/env bash
set -u
case "$1" in
  healthcheck) exit 0 ;;
  exec)
    # $2 is container name; $3+ is the command.
    case "$2" in
      wakir-spire-server-federation-{side})
        {bundle_list_block}
        # default: healthcheck
        case "$3" in
          /opt/spire/bin/spire-server)
            printf 'Server is healthy.\\n'; exit 0 ;;
        esac
        ;;
      wakir-spire-agent-{side})
        case "$3" in
          /opt/spire/bin/spire-agent)
            case "$4" in
              healthcheck) printf 'Agent is healthy.\\n'; exit 0 ;;
              api) printf 'received 1 X509-SVID(s)\\n'; exit 0 ;;
            esac ;;
        esac
        ;;
    esac
    ;;
  run) printf 'wakir-marker-stack-acme\\n'; exit 0 ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    mock.chmod(0o755)
    return mock


def _write_mock_curl(tmp_path: Path, *, fed_endpoint_returns_200: bool) -> Path:
    """curl mock: /jsz always returns happy; federation endpoint configurable."""
    success_branch = (
        "printf '{\"keys\":[]}\\n__HTTP_CODE__=200\\n'; exit 0"
        if fed_endpoint_returns_200
        else "printf '__HTTP_CODE__=000\\n'; exit 7"
    )
    mock = tmp_path / "curl"
    mock.write_text(
        f"""#!/usr/bin/env bash
set -u
# Inspect argv for the URL pattern. If it contains :8443 it's the
# federation-bundle endpoint; otherwise it's /jsz.
for arg in "$@"; do
  case "$arg" in
    *spire-server-*:8443*)
      {success_branch}
      ;;
    *jsz*)
      printf '{{"streams":0,"server_id":"NA..."}}\\n'; exit 0 ;;
  esac
done
# default: /jsz happy
printf '{{"streams":0,"server_id":"NA..."}}\\n'; exit 0
""",
        encoding="utf-8",
    )
    mock.chmod(0o755)
    return mock


def _run_smoke(env_overrides: dict, args: list[str]) -> subprocess.CompletedProcess:
    bash = shutil.which("bash")
    assert bash is not None, "bash not on PATH"
    env = os.environ.copy()
    env.update(env_overrides)
    env.setdefault("WAKIR_SMOKE_RETRY_MAX", "0")
    return subprocess.run(
        [bash, str(_SMOKE), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# A. --side default is "wakir" (backwards-compat with Sprint-9 Tag-1)
# ---------------------------------------------------------------------------


def test_default_side_is_wakir(tmp_path):
    """Without --side, the smoke checks wakir-named units."""
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(_write_mock_systemctl_for_side(tmp_path, "wakir")),
        "WAKIR_SMOKE_PODMAN": str(_write_mock_podman_for_side(tmp_path, "wakir")),
        "WAKIR_SMOKE_CURL": str(_write_mock_curl(tmp_path, fed_endpoint_returns_200=False)),
    }
    result = _run_smoke(env, ["--org", "acme"])
    assert result.returncode == 0, (
        f"expected exit 0 default-side-wakir, got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "SUMMARY: 6/6 checks PASS" in result.stdout
    # Federation checks emit SKIP (visible to operator) but do not
    # count toward PASS/FAIL totals. Total stays 6/6.
    fed_lines = [
        l for l in result.stdout.splitlines()
        if "federation-bundle-sync-reachable" in l
        or "federation-cross-trust-domain-verify" in l
    ]
    assert len(fed_lines) == 2, fed_lines
    for line in fed_lines:
        assert "SKIP" in line, line


# ---------------------------------------------------------------------------
# B. --side orbit drives orbit-named container checks
# ---------------------------------------------------------------------------


def test_side_orbit_targets_orbit_named_containers(tmp_path):
    """With --side orbit, the smoke checks orbit-named units."""
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(_write_mock_systemctl_for_side(tmp_path, "orbit")),
        "WAKIR_SMOKE_PODMAN": str(_write_mock_podman_for_side(tmp_path, "orbit")),
        "WAKIR_SMOKE_CURL": str(_write_mock_curl(tmp_path, fed_endpoint_returns_200=False)),
    }
    result = _run_smoke(env, ["--org", "acme", "--side", "orbit"])
    assert result.returncode == 0, (
        f"expected exit 0 side=orbit, got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "SUMMARY: 6/6 checks PASS" in result.stdout


def test_side_orbit_with_wakir_systemctl_mock_fails(tmp_path):
    """Cross-side sanity: orbit-smoke against wakir-mock systemctl FAILS
    because the orbit-named units are not declared active by the wakir
    mock. This catches accidental hardcoding of "wakir" in the smoke
    skript."""
    env = {
        # Wakir-named systemctl mock — orbit units will be reported empty.
        "WAKIR_SMOKE_SYSTEMCTL": str(_write_mock_systemctl_for_side(tmp_path, "wakir")),
        "WAKIR_SMOKE_PODMAN": str(_write_mock_podman_for_side(tmp_path, "orbit")),
        "WAKIR_SMOKE_CURL": str(_write_mock_curl(tmp_path, fed_endpoint_returns_200=False)),
    }
    result = _run_smoke(env, ["--org", "acme", "--side", "orbit"])
    assert result.returncode == 2, (
        f"expected exit 2 cross-side-mock-mismatch, got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    # quadlet-units-active is FAIL because the orbit units are not in
    # the wakir mock's branch list.
    quadlet_lines = [l for l in result.stdout.splitlines() if "quadlet-units-active" in l]
    assert quadlet_lines and "FAIL" in quadlet_lines[0], quadlet_lines


# ---------------------------------------------------------------------------
# C. --peer-side requires WAKIR_FEDERATION_MODE=enabled to activate
# ---------------------------------------------------------------------------


def test_peer_side_without_federation_mode_skips_checks(tmp_path):
    """--peer-side without WAKIR_FEDERATION_MODE=enabled: federation
    checks emit SKIP and the run still passes (other 6/6 ok)."""
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(_write_mock_systemctl_for_side(tmp_path, "wakir")),
        "WAKIR_SMOKE_PODMAN": str(_write_mock_podman_for_side(tmp_path, "wakir")),
        "WAKIR_SMOKE_CURL": str(_write_mock_curl(tmp_path, fed_endpoint_returns_200=False)),
        # WAKIR_FEDERATION_MODE intentionally unset (not "enabled").
    }
    result = _run_smoke(
        env,
        ["--org", "acme", "--side", "wakir", "--peer-side", "orbit"],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # Both federation lines present with SKIP status.
    fed_lines = [
        l for l in result.stdout.splitlines()
        if "federation-bundle-sync-reachable" in l
        or "federation-cross-trust-domain-verify" in l
    ]
    assert len(fed_lines) == 2, fed_lines
    for line in fed_lines:
        assert "SKIP" in line, line
    # Summary mentions the skip count.
    assert "(2 skipped)" in result.stdout, result.stdout
    assert "6/6 checks PASS" in result.stdout


def test_federation_happy_path_8_of_8(tmp_path):
    """Happy-path Cross-VM Federation: WAKIR_FEDERATION_MODE=enabled
    + --peer-side + happy curl + bundle list contains peer-TD =>
    all 8 checks PASS."""
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(_write_mock_systemctl_for_side(tmp_path, "wakir")),
        "WAKIR_SMOKE_PODMAN": str(
            _write_mock_podman_for_side(
                tmp_path, "wakir", bundle_list_has_peer_td="orbit.test",
            )
        ),
        "WAKIR_SMOKE_CURL": str(_write_mock_curl(tmp_path, fed_endpoint_returns_200=True)),
        "WAKIR_FEDERATION_MODE": "enabled",
    }
    result = _run_smoke(
        env,
        ["--org", "acme", "--side", "wakir", "--peer-side", "orbit"],
    )
    assert result.returncode == 0, (
        f"expected 8/8 federation happy-path, got rc={result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    # All 8 checks PASS.
    assert "SUMMARY: 8/8 checks PASS" in result.stdout
    fed_lines = [
        l for l in result.stdout.splitlines()
        if "federation-bundle-sync-reachable" in l
        or "federation-cross-trust-domain-verify" in l
    ]
    assert len(fed_lines) == 2, fed_lines
    for line in fed_lines:
        assert "PASS" in line, line


def test_federation_endpoint_unreachable_fails_only_federation_check(tmp_path):
    """Federation endpoint unreachable (curl exit non-zero) =>
    federation-bundle-sync-reachable FAILS; cross-trust-domain-verify
    independently checks the local bundle cache and can still PASS if
    a prior bundle-exchange seeded it. The smoke exits 2."""
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(_write_mock_systemctl_for_side(tmp_path, "wakir")),
        "WAKIR_SMOKE_PODMAN": str(
            _write_mock_podman_for_side(
                tmp_path, "wakir", bundle_list_has_peer_td="orbit.test",
            )
        ),
        "WAKIR_SMOKE_CURL": str(_write_mock_curl(tmp_path, fed_endpoint_returns_200=False)),
        "WAKIR_FEDERATION_MODE": "enabled",
    }
    result = _run_smoke(
        env,
        ["--org", "acme", "--side", "wakir", "--peer-side", "orbit"],
    )
    assert result.returncode == 2, (
        f"expected exit 2 federation-endpoint-down, got {result.returncode}\n"
        f"stdout:\n{result.stdout}"
    )
    sync_lines = [
        l for l in result.stdout.splitlines()
        if "federation-bundle-sync-reachable" in l
    ]
    assert sync_lines and "FAIL" in sync_lines[0], sync_lines
    verify_lines = [
        l for l in result.stdout.splitlines()
        if "federation-cross-trust-domain-verify" in l
    ]
    # cross-trust-domain-verify reads the local bundle cache via podman
    # exec; if the cache has the peer trust-domain it PASSes
    # independently of the endpoint reachability. This separation is
    # intentional: the two checks measure different facets of the
    # Cross-VM-Federation health.
    assert verify_lines and "PASS" in verify_lines[0], verify_lines


# ---------------------------------------------------------------------------
# D. Argument validation for --side / --peer-side
# ---------------------------------------------------------------------------


def test_side_rejects_uppercase_and_separator_chars(tmp_path):
    """--side must be lowercase ASCII + digits, starting with a letter."""
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(_write_mock_systemctl_for_side(tmp_path, "wakir")),
        "WAKIR_SMOKE_PODMAN": str(_write_mock_podman_for_side(tmp_path, "wakir")),
        "WAKIR_SMOKE_CURL": str(_write_mock_curl(tmp_path, fed_endpoint_returns_200=False)),
    }
    bad_uppercase = _run_smoke(env, ["--org", "acme", "--side", "Wakir"])
    assert bad_uppercase.returncode == 1, bad_uppercase.stdout + bad_uppercase.stderr
    assert "lowercase ASCII" in bad_uppercase.stderr

    bad_dot = _run_smoke(env, ["--org", "acme", "--side", "wakir.test"])
    assert bad_dot.returncode == 1, bad_dot.stdout + bad_dot.stderr
    assert "lowercase ASCII" in bad_dot.stderr

    bad_leading_digit = _run_smoke(env, ["--org", "acme", "--side", "1wakir"])
    assert bad_leading_digit.returncode == 1, bad_leading_digit.stdout + bad_leading_digit.stderr
    assert "lowercase ASCII" in bad_leading_digit.stderr


def test_peer_side_must_differ_from_side(tmp_path):
    """--peer-side == --side is a config error (would federate with self)."""
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(_write_mock_systemctl_for_side(tmp_path, "wakir")),
        "WAKIR_SMOKE_PODMAN": str(_write_mock_podman_for_side(tmp_path, "wakir")),
        "WAKIR_SMOKE_CURL": str(_write_mock_curl(tmp_path, fed_endpoint_returns_200=False)),
    }
    result = _run_smoke(
        env,
        ["--org", "acme", "--side", "wakir", "--peer-side", "wakir"],
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "must differ from --side" in result.stderr
