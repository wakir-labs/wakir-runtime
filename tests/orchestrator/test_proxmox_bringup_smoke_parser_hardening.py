# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Sprint-9 Tag-6 smoke-script parser hardening.

Two bug-vectors closed in Sprint-9 Tag-6 (Pilot-VM live-bring-up #2,
2026-05-14):

* **Bug 13** — `nats kv ls` box-table output broke the exact-line
  match (`grep -qx`) used by the marker-stack-bucket probe. nats-CLI
  0.1.5 and the latest `natsio/nats-box` image emit a fancy
  border-drawn table; the bucket line therefore has leading box
  characters (and column separators) that defeat `grep -qx`. We now
  use a regex with character-class boundaries so the bucket name is
  matched as a token regardless of decoration, but a strict
  superstring (e.g. `wakir-marker-stack-acme-tenant`) is still
  rejected.

* **Bug 14** — `spire-agent healthcheck` defaults to the SPIRE
  upstream socket path `/tmp/spire-agent/public/api.sock`. Our
  Workload-API socket is bound to `/run/spire/agent-sockets/api.sock`
  via the `agent-sockets` named volume. Without `-socketPath` the
  healthcheck returns `Agent is unhealthy: unable to determine
  health` even when the Agent is running fine. The fix adds the
  flag so the probe matches the working
  `check_spire_workload_api_reachable` invocation.

Both fixes are observable from outside the smoke script: the script
either invokes the SPIRE binary with the right `-socketPath` flag
(asserted via a spy mock that records its argv) or it does not, and
the script either accepts the box-bordered `nats kv ls` output as a
PASS or it does not. We exercise both surfaces against pure mock
wrappers — no live podman, no live NATS, no live SPIRE.

Sandbox boundary: per ``feedback_sandbox_host_trennung.md`` no live
containers or sockets are involved.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SMOKE = _REPO_ROOT / "bin" / "proxmox-bringup-smoke"


# ---------------------------------------------------------------------------
# Mock-builder helpers (shared shape with the Tag-1 baseline)
# ---------------------------------------------------------------------------


def _write_systemctl_all_active(tmp_path: Path) -> Path:
    p = tmp_path / "systemctl"
    p.write_text(
        '#!/usr/bin/env bash\n'
        'set -u\n'
        'case "${2:-${1:-}}" in\n'
        '  wakir-nats.service) printf "active\\n"; exit 0 ;;\n'
        '  wakir-spire-server-federation-wakir.service) printf "active\\n"; exit 0 ;;\n'
        '  wakir-spire-agent-wakir.service) printf "active\\n"; exit 0 ;;\n'
        '  wakir-nats-kv-bucket-init.service) printf "inactive\\n"; exit 0 ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n',
        encoding="utf-8",
    )
    p.chmod(0o755)
    return p


def _write_curl_jsz_ok(tmp_path: Path) -> Path:
    p = tmp_path / "curl"
    p.write_text(
        '#!/usr/bin/env bash\n'
        'set -u\n'
        'printf \'{"streams":1,"server_id":"NA"}\\n\'\n'
        'exit 0\n',
        encoding="utf-8",
    )
    p.chmod(0o755)
    return p


def _run_smoke(env_overrides: dict, args: list[str]) -> subprocess.CompletedProcess:
    bash = shutil.which("bash")
    assert bash is not None
    env = os.environ.copy()
    env.update(env_overrides)
    # Single-shot retry semantics for deterministic Tag-6 parser tests
    # (the parser fixes are orthogonal to the Tag-5 retry layer).
    env.setdefault("WAKIR_SMOKE_RETRY_MAX", "0")
    return subprocess.run(
        [bash, str(_SMOKE), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Bug 13 — nats kv ls parser hardening
# ---------------------------------------------------------------------------


def _build_bucket_box_output(bucket: str) -> str:
    """Reproduce the nats-CLI-0.1.5 / nats-box-latest box-bordered output.

    Real nats-CLI table emission uses Unicode box-drawing characters
    plus column separators. The probe must accept the bucket name
    when it appears as a column value even with these decorations.
    """
    return (
        "+-----------------------------+-------------+---------+------+--------+----------------------+\n"
        "| Bucket                      | Description | Created | Size | Values | Last Update          |\n"
        "+-----------------------------+-------------+---------+------+--------+----------------------+\n"
        f"| {bucket}    |             |  ...    |  0 B |      0 | 2026-05-13T23:42:00Z |\n"
        "+-----------------------------+-------------+---------+------+--------+----------------------+\n"
    )


def _write_podman_with_box_bucket_output(
    tmp_path: Path, *, output: str
) -> Path:
    """Podman mock that emits `output` from `podman run … nats-box nats kv ls`.

    All other podman paths (healthcheck, exec spire-server/agent,
    fetch x509) return success with the canonical happy-path stdout.
    The `-socketPath` flag is accepted (mock is permissive). The
    important behaviour: argv-based dispatch into the `run` branch
    emits the box-bordered table from the caller-supplied `output`.
    """
    p = tmp_path / "podman"
    p.write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        "case \"$1\" in\n"
        "  healthcheck) exit 0 ;;\n"
        "  exec)\n"
        "    case \"$3\" in\n"
        "      /opt/spire/bin/spire-server) printf 'Server is healthy.\\n'; exit 0 ;;\n"
        "      /opt/spire/bin/spire-agent)\n"
        "        case \"$4\" in\n"
        "          healthcheck) printf 'Agent is healthy.\\n'; exit 0 ;;\n"
        "          api) printf 'received 1 X509-SVID(s)\\n'; exit 0 ;;\n"
        "        esac ;;\n"
        "    esac\n"
        "    ;;\n"
        "  run)\n"
        f"    cat <<'BUCKET_OUTPUT_EOF'\n{output}BUCKET_OUTPUT_EOF\n"
        "    exit 0\n"
        "    ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    p.chmod(0o755)
    return p


def test_bug_13_bucket_probe_accepts_box_bordered_nats_box_output(tmp_path):
    """Live nats-box latest emits a box-table; smoke must still PASS."""
    box_output = _build_bucket_box_output("wakir-marker-stack-acme")
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(_write_systemctl_all_active(tmp_path)),
        "WAKIR_SMOKE_PODMAN": str(
            _write_podman_with_box_bucket_output(tmp_path, output=box_output)
        ),
        "WAKIR_SMOKE_CURL": str(_write_curl_jsz_ok(tmp_path)),
    }

    result = _run_smoke(env, ["--org", "acme"])

    assert result.returncode == 0, (
        f"box-bordered nats kv ls output must PASS the bucket probe; "
        f"got exit {result.returncode}\nstdout:\n{result.stdout}"
    )
    bucket_lines = [
        l for l in result.stdout.splitlines() if "marker-stack-bucket-present" in l
    ]
    assert bucket_lines, f"no bucket line: {result.stdout}"
    assert "PASS" in bucket_lines[0], bucket_lines[0]
    assert "SUMMARY: 6/6 checks PASS" in result.stdout


def test_bug_13_bucket_probe_still_accepts_plain_output(tmp_path):
    """Plain-text nats kv ls (legacy/json-disabled) must still PASS."""
    plain_output = "wakir-marker-stack-acme\n"
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(_write_systemctl_all_active(tmp_path)),
        "WAKIR_SMOKE_PODMAN": str(
            _write_podman_with_box_bucket_output(tmp_path, output=plain_output)
        ),
        "WAKIR_SMOKE_CURL": str(_write_curl_jsz_ok(tmp_path)),
    }

    result = _run_smoke(env, ["--org", "acme"])

    assert result.returncode == 0, result.stdout
    bucket_lines = [
        l for l in result.stdout.splitlines() if "marker-stack-bucket-present" in l
    ]
    assert bucket_lines and "PASS" in bucket_lines[0], bucket_lines


def test_bug_13_bucket_probe_rejects_strict_superstring(tmp_path):
    """A line that contains a superstring (e.g. -tenant suffix) is NOT a match.

    Without character-class boundaries a substring `grep -q` would
    accept `wakir-marker-stack-acme-tenant` as a match for the
    `acme` bucket. The boundary-anchored regex rejects it.
    """
    superstring_output = (
        "+-----------------------------+\n"
        "| Bucket                      |\n"
        "+-----------------------------+\n"
        "| wakir-marker-stack-acme-tenant |\n"
        "+-----------------------------+\n"
    )
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(_write_systemctl_all_active(tmp_path)),
        "WAKIR_SMOKE_PODMAN": str(
            _write_podman_with_box_bucket_output(
                tmp_path, output=superstring_output
            )
        ),
        "WAKIR_SMOKE_CURL": str(_write_curl_jsz_ok(tmp_path)),
    }

    result = _run_smoke(env, ["--org", "acme"])

    assert result.returncode == 2, (
        f"superstring-only output must NOT pass the bucket probe; "
        f"got exit {result.returncode}\nstdout:\n{result.stdout}"
    )
    bucket_lines = [
        l for l in result.stdout.splitlines() if "marker-stack-bucket-present" in l
    ]
    assert bucket_lines and "FAIL" in bucket_lines[0], bucket_lines


def test_bug_13_pre_fix_behaviour_documented_in_assertions(tmp_path):
    """Document the previous failure-mode for audit traceability.

    Before Bug 13 was fixed the script used `grep -qx "$bucket"`.
    Against the box-bordered output the probe would have FAILed even
    though the bucket existed. We do not re-introduce the broken
    behaviour; instead we encode the assertion that the *current*
    parser correctly rejects an output that lacks the bucket name as
    a token. This guards against a regression that would accept any
    nats-box output blindly.
    """
    decoy_output = (
        "+-----------------------------+\n"
        "| Bucket                      |\n"
        "+-----------------------------+\n"
        "| wakir-marker-stack-other    |\n"
        "+-----------------------------+\n"
    )
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(_write_systemctl_all_active(tmp_path)),
        "WAKIR_SMOKE_PODMAN": str(
            _write_podman_with_box_bucket_output(tmp_path, output=decoy_output)
        ),
        "WAKIR_SMOKE_CURL": str(_write_curl_jsz_ok(tmp_path)),
    }
    result = _run_smoke(env, ["--org", "acme"])
    assert result.returncode == 2, result.stdout
    bucket_lines = [
        l for l in result.stdout.splitlines() if "marker-stack-bucket-present" in l
    ]
    assert bucket_lines and "FAIL" in bucket_lines[0], bucket_lines


# ---------------------------------------------------------------------------
# Bug 14 — `spire-agent healthcheck` socketPath flag
# ---------------------------------------------------------------------------


def _write_podman_recording_spy(tmp_path: Path, *, log_path: Path) -> Path:
    """Podman mock that records every argv invocation to `log_path`.

    The recorded log lets the test assert that
    `spire-agent healthcheck` was called WITH `-socketPath
    /run/spire/agent-sockets/api.sock`. For non-spy paths the mock
    returns the same happy-path output as the baseline.

    The mock also enforces the contract: if `spire-agent healthcheck`
    is invoked WITHOUT `-socketPath`, the mock prints SPIRE's actual
    failure mode and exits non-zero. This mirrors the live SPIRE
    binary's behaviour against an unreachable default socket path.
    """
    p = tmp_path / "podman"
    p.write_text(
        f"""#!/usr/bin/env bash
set -u
{{ echo "$@"; }} >> {log_path}
case "$1" in
  healthcheck) exit 0 ;;
  exec)
    case "$3" in
      /opt/spire/bin/spire-server)
        printf 'Server is healthy.\\n'; exit 0 ;;
      /opt/spire/bin/spire-agent)
        case "$4" in
          healthcheck)
            # Enforce: -socketPath must be present, else simulate
            # the SPIRE upstream-default-socket failure.
            seen_socket_path=0
            for arg in "$@"; do
              if [[ "$arg" == "-socketPath" ]]; then
                seen_socket_path=1
              fi
            done
            if [[ $seen_socket_path -eq 1 ]]; then
              printf 'Agent is healthy.\\n'; exit 0
            else
              printf 'Agent is unhealthy: unable to determine health\\n' >&2
              exit 1
            fi ;;
          api) printf 'received 1 X509-SVID(s)\\n'; exit 0 ;;
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
    p.chmod(0o755)
    return p


def test_bug_14_spire_agent_healthcheck_passes_socketpath_flag(tmp_path):
    """The probe must invoke `spire-agent healthcheck -socketPath …`."""
    log_path = tmp_path / "podman.log"
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(_write_systemctl_all_active(tmp_path)),
        "WAKIR_SMOKE_PODMAN": str(
            _write_podman_recording_spy(tmp_path, log_path=log_path)
        ),
        "WAKIR_SMOKE_CURL": str(_write_curl_jsz_ok(tmp_path)),
    }

    result = _run_smoke(env, ["--org", "acme"])

    assert result.returncode == 0, (
        f"smoke must PASS now that healthcheck carries -socketPath; "
        f"got exit {result.returncode}\nstdout:\n{result.stdout}"
    )
    agent_lines = [
        l for l in result.stdout.splitlines() if "spire-agent-healthy " in l
    ]
    assert agent_lines and "PASS" in agent_lines[0], agent_lines

    # Inspect the argv log: at least one invocation must include
    # `healthcheck` and `-socketPath /run/spire/agent-sockets/api.sock`.
    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    healthcheck_invocations = [
        line for line in log_lines
        if " /opt/spire/bin/spire-agent healthcheck" in line
    ]
    assert healthcheck_invocations, (
        f"no spire-agent healthcheck invocation recorded; log:\n"
        + "\n".join(log_lines)
    )
    correct_invocations = [
        line for line in healthcheck_invocations
        if "-socketPath" in line
        and "/run/spire/agent-sockets/api.sock" in line
    ]
    assert correct_invocations, (
        "spire-agent healthcheck invoked WITHOUT -socketPath flag; "
        "Bug 14 regression. Lines seen:\n" + "\n".join(healthcheck_invocations)
    )


def test_bug_14_pre_fix_behaviour_documented_via_failing_mock(tmp_path):
    """Regression-pin: a healthcheck without -socketPath would FAIL.

    The recording-spy mock enforces the contract: if any future
    refactor accidentally drops the `-socketPath` flag the spy's
    failure-branch returns `Agent is unhealthy: …`. We assert that
    the *current* fixed script does NOT hit this branch — i.e. it
    always supplies the flag.
    """
    log_path = tmp_path / "podman.log"
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(_write_systemctl_all_active(tmp_path)),
        "WAKIR_SMOKE_PODMAN": str(
            _write_podman_recording_spy(tmp_path, log_path=log_path)
        ),
        "WAKIR_SMOKE_CURL": str(_write_curl_jsz_ok(tmp_path)),
    }

    result = _run_smoke(env, ["--org", "acme"])

    assert result.returncode == 0, result.stdout
    # The "Agent is unhealthy" string is what the broken-path emits.
    # The fixed script must NOT trigger it.
    assert "Agent is unhealthy: unable to determine health" not in result.stdout, (
        "smoke output mentions the broken-path error string — Bug 14 regression"
    )


def test_bug_14_workload_api_check_remains_consistent(tmp_path):
    """`check_spire_workload_api_reachable` already used `-socketPath`.

    We assert consistency: both Agent-touching probes target the
    same socket path so live behaviour and hermetic behaviour align.
    """
    log_path = tmp_path / "podman.log"
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(_write_systemctl_all_active(tmp_path)),
        "WAKIR_SMOKE_PODMAN": str(
            _write_podman_recording_spy(tmp_path, log_path=log_path)
        ),
        "WAKIR_SMOKE_CURL": str(_write_curl_jsz_ok(tmp_path)),
    }
    result = _run_smoke(env, ["--org", "acme"])
    assert result.returncode == 0, result.stdout

    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    api_lines = [
        line for line in log_lines
        if " /opt/spire/bin/spire-agent api fetch x509" in line
    ]
    assert api_lines, "spire-agent api fetch x509 was never invoked"
    for line in api_lines:
        assert "-socketPath" in line, line
        assert "/run/spire/agent-sockets/api.sock" in line, line
