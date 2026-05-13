# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``bin/proxmox-bringup-smoke`` (Phase-2 Sprint-9
Tag-1 Operator-Hand Self-Verify after Proxmox VM bring-up).

The smoke skript shells out to ``systemctl``, ``podman``, ``curl``,
and optionally a ``nats`` CLI. Each of these is overridable via env
vars (``WAKIR_SMOKE_SYSTEMCTL``, ``WAKIR_SMOKE_PODMAN``,
``WAKIR_SMOKE_CURL``, ``WAKIR_SMOKE_NATS``). Hermetic tests build
mock wrapper scripts in ``tmp_path`` and point the smoke skript at
them; the skript itself runs unchanged.

Coverage axes (3 tests; combined with the 8 provisioner tests, the
Sprint-9 Tag-1 hermetic surface is 11 new tests):

A. Happy-path: all four mock tools return success; smoke skript
   exits 0; six PASS lines in the log; ``--json`` payload carries
   the expected shape.
B. SPIRE-Agent unhealthy: the agent mock fails; smoke skript exits
   2; the relevant check line is FAIL while other checks PASS.
C. Argument-validation: missing ``--org`` exits 1; malformed
   ``--org`` (e.g. ``with/slash``) exits 1.

These tests do NOT depend on real systemctl, real podman, real curl,
or a live cluster. They are hermetic per the
``feedback_sandbox_host_trennung.md`` boundary.
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


# ---------------------------------------------------------------------------
# Mock-wrapper builder
# ---------------------------------------------------------------------------


def _write_mock(
    path: Path,
    *,
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    branch_on_arg: dict | None = None,
) -> Path:
    """Write a tiny bash mock that prints fixed stdout/stderr and exits.

    If ``branch_on_arg`` is supplied, the mock matches argv[1] against
    each key and switches its (stdout, exit_code) accordingly. This
    lets us drive systemctl-is-active for different unit names from a
    single mock.
    """
    lines = ["#!/usr/bin/env bash", "set -u"]
    if branch_on_arg:
        lines.append('case "${2:-${1:-}}" in')
        for key, (out, ec) in branch_on_arg.items():
            # Escape single quotes in the output payload.
            safe = out.replace("'", "'\\''")
            lines.append(f"  {key}) printf '{safe}\\n'; exit {ec} ;;")
        lines.append("  *) exit 0 ;;")
        lines.append("esac")
    else:
        safe_out = stdout.replace("'", "'\\''")
        safe_err = stderr.replace("'", "'\\''")
        if stdout:
            lines.append(f"printf '{safe_out}\\n'")
        if stderr:
            lines.append(f"printf '{safe_err}\\n' >&2")
        lines.append(f"exit {exit_code}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _build_happy_env(tmp_path: Path) -> dict:
    """Return env-overrides pointing the smoke skript at happy-path mocks."""
    # systemctl: is-active <unit> → "active"; is-failed <unit> → "active"
    # (any non-"failed" string passes the oneshot check).
    systemctl = _write_mock(
        tmp_path / "systemctl",
        branch_on_arg={
            "wakir-nats.service": ("active", 0),
            "wakir-spire-server-federation-wakir.service": ("active", 0),
            "wakir-spire-agent-wakir.service": ("active", 0),
            "wakir-nats-kv-bucket-init.service": ("inactive", 0),
        },
    )
    # podman: branch on argv to differentiate healthcheck/exec/run paths.
    # healthcheck run <ctr> always 0; exec <ctr> spire-server healthcheck
    # prints "Server is healthy."; exec spire-agent healthcheck prints
    # "Agent is healthy."; exec spire-agent api fetch x509 prints SVID;
    # run --rm natsio/nats-box returns the bucket name.
    podman = tmp_path / "podman"
    podman.write_text(
        """#!/usr/bin/env bash
set -u
case "$1" in
  healthcheck)
    exit 0
    ;;
  exec)
    case "$3" in
      /opt/spire/bin/spire-server)
        printf 'Server is healthy.\\n'; exit 0 ;;
      /opt/spire/bin/spire-agent)
        case "$4" in
          healthcheck) printf 'Agent is healthy.\\n'; exit 0 ;;
          api) printf 'received 1 X509-SVID(s)\\n'; exit 0 ;;
        esac ;;
    esac
    ;;
  run)
    # nats kv ls returns bucket list including the requested one.
    printf 'wakir-marker-stack-acme\\n'
    exit 0
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    podman.chmod(0o755)
    # curl: always returns a /jsz-shaped body.
    curl = _write_mock(
        tmp_path / "curl",
        stdout='{"streams":0,"server_id":"NA..."}',
        exit_code=0,
    )
    return {
        "WAKIR_SMOKE_SYSTEMCTL": str(systemctl),
        "WAKIR_SMOKE_PODMAN": str(podman),
        "WAKIR_SMOKE_CURL": str(curl),
    }


def _run_smoke(env_overrides: dict, args: list[str]) -> subprocess.CompletedProcess:
    bash = shutil.which("bash")
    assert bash is not None, "bash not on PATH"
    env = os.environ.copy()
    env.update(env_overrides)
    # PATH must be present for #!/usr/bin/env bash to resolve.
    return subprocess.run(
        [bash, str(_SMOKE), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# A. Happy-path
# ---------------------------------------------------------------------------


def test_happy_path_all_six_checks_pass(tmp_path):
    env = _build_happy_env(tmp_path)
    result = _run_smoke(env, ["--org", "acme", "--json"])

    assert result.returncode == 0, (
        f"expected exit 0 on happy path, got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    # Human log carries one PASS line per check.
    assert "quadlet-units-active" in result.stdout
    assert "nats-jetstream-reachable" in result.stdout
    assert "spire-server-healthy" in result.stdout
    assert "spire-agent-healthy" in result.stdout
    assert "spire-workload-api-reachable" in result.stdout
    assert "marker-stack-bucket-present" in result.stdout
    assert "SUMMARY: 6/6 checks PASS" in result.stdout
    # FAIL must not appear anywhere.
    assert "FAIL" not in result.stdout, result.stdout
    # JSON payload shape.
    assert '"pass":6' in result.stdout
    assert '"fail":0' in result.stdout
    assert '"total":6' in result.stdout


# ---------------------------------------------------------------------------
# B. SPIRE-Agent unhealthy
# ---------------------------------------------------------------------------


def test_spire_agent_unhealthy_causes_exit_2(tmp_path):
    env = _build_happy_env(tmp_path)
    # Override podman so the agent healthcheck fails.
    broken_podman = tmp_path / "podman"
    broken_podman.write_text(
        """#!/usr/bin/env bash
set -u
case "$1" in
  healthcheck) exit 0 ;;
  exec)
    case "$3" in
      /opt/spire/bin/spire-server)
        printf 'Server is healthy.\\n'; exit 0 ;;
      /opt/spire/bin/spire-agent)
        case "$4" in
          healthcheck)
            printf 'Agent is not healthy: socket /run/spire/agent.sock missing\\n' >&2
            exit 1 ;;
          api)
            printf 'no identity issued\\n' >&2
            exit 1 ;;
        esac ;;
    esac
    ;;
  run)
    printf 'wakir-marker-stack-acme\\n'; exit 0 ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    broken_podman.chmod(0o755)
    env["WAKIR_SMOKE_PODMAN"] = str(broken_podman)

    result = _run_smoke(env, ["--org", "acme"])

    assert result.returncode == 2, (
        f"expected exit 2 on agent failure, got {result.returncode}\n"
        f"stdout:\n{result.stdout}"
    )
    # The agent-healthy line is FAIL. The other checks are PASS.
    lines = result.stdout.splitlines()
    agent_lines = [l for l in lines if "spire-agent-healthy " in l]
    assert agent_lines and "FAIL" in agent_lines[0], agent_lines
    server_lines = [l for l in lines if "spire-server-healthy " in l]
    assert server_lines and "PASS" in server_lines[0], server_lines
    nats_lines = [l for l in lines if "nats-jetstream-reachable " in l]
    assert nats_lines and "PASS" in nats_lines[0], nats_lines
    # workload-api-reachable also fails because the same podman exec
    # path returns non-zero with "no identity issued"; but that
    # string is in the "acceptable" branch (record PASS), so the
    # smoke skript still treats it as PASS. We assert that explicitly.
    api_lines = [l for l in lines if "spire-workload-api-reachable " in l]
    assert api_lines and "PASS" in api_lines[0], api_lines


# ---------------------------------------------------------------------------
# C. Argument validation
# ---------------------------------------------------------------------------


def test_argument_validation_rejects_missing_or_malformed_org(tmp_path):
    env = _build_happy_env(tmp_path)
    # Missing --org.
    missing = _run_smoke(env, [])
    assert missing.returncode == 1, missing.stdout + missing.stderr
    assert "--org is required" in missing.stderr

    # Malformed --org (slash).
    slash = _run_smoke(env, ["--org", "with/slash"])
    assert slash.returncode == 1, slash.stdout + slash.stderr
    assert "permitted-character pattern" in slash.stderr

    # Malformed --org (space). Subprocess passes it as a single arg.
    space = _run_smoke(env, ["--org", "with space"])
    assert space.returncode == 1, space.stdout + space.stderr
    assert "permitted-character pattern" in space.stderr
