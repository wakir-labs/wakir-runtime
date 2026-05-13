# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Sprint-9 Tag-5 race-tolerant retry layer
inside ``bin/proxmox-bringup-smoke``.

These tests reproduce the Pilot-VM 2/6 <-> 4/6 smoke-discrepancy
race windows against scripted mocks that:

1. **Flip a state file** between invocations to simulate a probe
   that fails N times, then succeeds. The smoke script's retry
   wrapper should consume the failing probes, wait, and finally
   record PASS.
2. **Stay broken forever** to verify the retry budget is bounded
   (the smoke script must not hang, even with all retries enabled).

Mock pattern: each probe wrapper script reads/writes a counter
file in ``tmp_path``. The counter starts at 0; the probe returns
non-zero while ``counter < fail_count`` and zero thereafter. The
counter survives across invocations because each ``podman``/``curl``
call is a fresh subprocess.

Sandbox boundary: no real podman, no real systemctl, no real
nats-CLI, no live NATS. Pure hermetic-mock substrate. Per
``feedback_sandbox_host_trennung.md``.
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
# Mock wrappers
# ---------------------------------------------------------------------------


def _write_systemctl_mock(tmp_path: Path) -> Path:
    """All units active; matches the happy-path baseline."""
    p = tmp_path / "systemctl"
    p.write_text(
        '#!/usr/bin/env bash\n'
        'set -u\n'
        'case "${2:-${1:-}}" in\n'
        '  wakir-nats.service) printf "active\\n"; exit 0 ;;\n'
        '  wakir-spire-server-federation-wakir.service) '
        'printf "active\\n"; exit 0 ;;\n'
        '  wakir-spire-agent-wakir.service) '
        'printf "active\\n"; exit 0 ;;\n'
        '  wakir-nats-kv-bucket-init.service) '
        'printf "inactive\\n"; exit 0 ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n',
        encoding="utf-8",
    )
    p.chmod(0o755)
    return p


def _write_noop_sleep(tmp_path: Path) -> Path:
    """A sleep stub that returns immediately — keeps retry loops fast."""
    p = tmp_path / "noop-sleep"
    p.write_text(
        '#!/usr/bin/env bash\n'
        'exit 0\n',
        encoding="utf-8",
    )
    p.chmod(0o755)
    return p


def _write_flipping_curl(
    tmp_path: Path,
    *,
    fail_count: int,
    counter_path: Path,
) -> Path:
    """A curl stub that returns empty (FAIL) the first ``fail_count``
    calls, then a well-formed /jsz body."""
    counter_path.write_text("0", encoding="utf-8")
    script = (
        '#!/usr/bin/env bash\n'
        'set -u\n'
        f'COUNTER="{counter_path}"\n'
        f'FAIL_COUNT={fail_count}\n'
        'n=$(cat "$COUNTER")\n'
        'n=$((n + 1))\n'
        'echo "$n" > "$COUNTER"\n'
        'if [[ $n -le $FAIL_COUNT ]]; then\n'
        '  # Simulate the JetStream-init race: empty body.\n'
        '  exit 0\n'
        'fi\n'
        '# Once the race clears, return a well-formed /jsz body.\n'
        'printf \'{"streams":0,"server_id":"NA..."}\\n\'\n'
        'exit 0\n'
    )
    p = tmp_path / "curl"
    p.write_text(script, encoding="utf-8")
    p.chmod(0o755)
    return p


def _write_flipping_podman(
    tmp_path: Path,
    *,
    fail_count_kv: int,
    counter_path_kv: Path,
) -> Path:
    """A podman stub. The ``kv ls`` path fails ``fail_count_kv`` times,
    then succeeds. Other paths (healthcheck, exec) always succeed."""
    counter_path_kv.write_text("0", encoding="utf-8")
    script = (
        '#!/usr/bin/env bash\n'
        'set -u\n'
        f'COUNTER_KV="{counter_path_kv}"\n'
        f'FAIL_COUNT_KV={fail_count_kv}\n'
        'case "$1" in\n'
        '  healthcheck) exit 0 ;;\n'
        '  exec)\n'
        '    case "$3" in\n'
        '      /opt/spire/bin/spire-server)\n'
        '        printf "Server is healthy.\\n"; exit 0 ;;\n'
        '      /opt/spire/bin/spire-agent)\n'
        '        case "$4" in\n'
        '          healthcheck) '
        'printf "Agent is healthy.\\n"; exit 0 ;;\n'
        '          api) '
        'printf "received 1 X509-SVID(s)\\n"; exit 0 ;;\n'
        '        esac ;;\n'
        '    esac ;;\n'
        '  run)\n'
        '    # nats kv ls path — flip after fail_count.\n'
        '    n=$(cat "$COUNTER_KV")\n'
        '    n=$((n + 1))\n'
        '    echo "$n" > "$COUNTER_KV"\n'
        '    if [[ $n -le $FAIL_COUNT_KV ]]; then\n'
        '      # Race: stream registration pending.\n'
        '      printf "" \n'
        '      exit 0\n'
        '    fi\n'
        '    printf "wakir-marker-stack-acme\\n"\n'
        '    exit 0 ;;\n'
        'esac\n'
        'exit 0\n'
    )
    p = tmp_path / "podman"
    p.write_text(script, encoding="utf-8")
    p.chmod(0o755)
    return p


def _run_smoke(
    env_overrides: dict,
    args: list[str],
    *,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    bash = shutil.which("bash")
    assert bash is not None, "bash not on PATH"
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        [bash, str(_SMOKE), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Race-Toleranz: Check 6 (bucket-stream-init race)
# ---------------------------------------------------------------------------


def test_marker_stack_bucket_present_race_clears_after_2_retries(tmp_path):
    """The bucket-listing race clears after 2 failed probes.

    Reproduces hypothesis 4 (JetStream-stream-init race): the
    bucket exists but ``nats kv ls`` returns empty for the first
    two calls, then the stream-registration finalises and the
    bucket appears.
    """
    counter = tmp_path / "kv_counter"
    systemctl = _write_systemctl_mock(tmp_path)
    podman = _write_flipping_podman(
        tmp_path, fail_count_kv=2, counter_path_kv=counter
    )
    curl = _write_flipping_curl(
        tmp_path, fail_count=0, counter_path=tmp_path / "curl_counter"
    )
    sleep_noop = _write_noop_sleep(tmp_path)
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(systemctl),
        "WAKIR_SMOKE_PODMAN": str(podman),
        "WAKIR_SMOKE_CURL": str(curl),
        "WAKIR_SMOKE_SLEEP": str(sleep_noop),
        "WAKIR_SMOKE_RETRY_MAX": "5",
        "WAKIR_SMOKE_RETRY_BASE": "0.01",
    }
    result = _run_smoke(env, ["--org", "acme"], timeout=15)
    assert result.returncode == 0, (
        f"expected exit 0 after race clears, got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    # The marker-stack-bucket-present line records the attempt count.
    marker_lines = [
        l for l in result.stdout.splitlines()
        if "marker-stack-bucket-present " in l
    ]
    assert marker_lines, result.stdout
    assert "PASS" in marker_lines[0]
    assert "attempts=3" in marker_lines[0], marker_lines[0]


def test_marker_stack_bucket_present_race_clears_after_4_retries(tmp_path):
    """A longer race window (4 failed probes) still resolves."""
    counter = tmp_path / "kv_counter"
    systemctl = _write_systemctl_mock(tmp_path)
    podman = _write_flipping_podman(
        tmp_path, fail_count_kv=4, counter_path_kv=counter
    )
    curl = _write_flipping_curl(
        tmp_path, fail_count=0, counter_path=tmp_path / "curl_counter"
    )
    sleep_noop = _write_noop_sleep(tmp_path)
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(systemctl),
        "WAKIR_SMOKE_PODMAN": str(podman),
        "WAKIR_SMOKE_CURL": str(curl),
        "WAKIR_SMOKE_SLEEP": str(sleep_noop),
        "WAKIR_SMOKE_RETRY_MAX": "5",
        "WAKIR_SMOKE_RETRY_BASE": "0.01",
    }
    result = _run_smoke(env, ["--org", "acme"], timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    marker_lines = [
        l for l in result.stdout.splitlines()
        if "marker-stack-bucket-present " in l
    ]
    assert marker_lines and "PASS" in marker_lines[0]
    assert "attempts=5" in marker_lines[0], marker_lines[0]


def test_marker_stack_bucket_present_race_exhausts_budget(tmp_path):
    """If the race never clears, the smoke fails with a clear reason."""
    counter = tmp_path / "kv_counter"
    systemctl = _write_systemctl_mock(tmp_path)
    podman = _write_flipping_podman(
        tmp_path, fail_count_kv=999, counter_path_kv=counter
    )
    curl = _write_flipping_curl(
        tmp_path, fail_count=0, counter_path=tmp_path / "curl_counter"
    )
    sleep_noop = _write_noop_sleep(tmp_path)
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(systemctl),
        "WAKIR_SMOKE_PODMAN": str(podman),
        "WAKIR_SMOKE_CURL": str(curl),
        "WAKIR_SMOKE_SLEEP": str(sleep_noop),
        "WAKIR_SMOKE_RETRY_MAX": "3",
        "WAKIR_SMOKE_RETRY_BASE": "0.01",
    }
    result = _run_smoke(env, ["--org", "acme"], timeout=15)
    assert result.returncode == 2, result.stdout + result.stderr
    marker_lines = [
        l for l in result.stdout.splitlines()
        if "marker-stack-bucket-present " in l
    ]
    assert marker_lines and "FAIL" in marker_lines[0]
    # 3 retries + 1 initial = 4 attempts.
    assert "attempts=4" in marker_lines[0], marker_lines[0]
    # The reason code surfaces the race window.
    assert "stream-registration-pending" in marker_lines[0]


# ---------------------------------------------------------------------------
# Race-Toleranz: Check 2 (jetstream-init race)
# ---------------------------------------------------------------------------


def test_nats_jetstream_reachable_race_clears_after_1_retry(tmp_path):
    """The /jsz endpoint returns empty once, then the well-formed body."""
    counter = tmp_path / "curl_counter"
    systemctl = _write_systemctl_mock(tmp_path)
    podman = _write_flipping_podman(
        tmp_path, fail_count_kv=0, counter_path_kv=tmp_path / "kv_counter"
    )
    curl = _write_flipping_curl(
        tmp_path, fail_count=1, counter_path=counter
    )
    sleep_noop = _write_noop_sleep(tmp_path)
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(systemctl),
        "WAKIR_SMOKE_PODMAN": str(podman),
        "WAKIR_SMOKE_CURL": str(curl),
        "WAKIR_SMOKE_SLEEP": str(sleep_noop),
        "WAKIR_SMOKE_RETRY_MAX": "3",
        "WAKIR_SMOKE_RETRY_BASE": "0.01",
    }
    result = _run_smoke(env, ["--org", "acme"], timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    jsz_lines = [
        l for l in result.stdout.splitlines()
        if "nats-jetstream-reachable " in l
    ]
    assert jsz_lines and "PASS" in jsz_lines[0]
    assert "attempts=2" in jsz_lines[0], jsz_lines[0]


# ---------------------------------------------------------------------------
# Combined-Race-Window: the Pilot-VM 2/6 -> 4/6 scenario
# ---------------------------------------------------------------------------


def test_pilot_vm_2_to_4_discrepancy_scenario_resolves(tmp_path):
    """The combined Sprint-9 Tag-5 race: jetstream-init AND bucket-stream
    both race-window-pending, both clear inside the retry budget.

    This is the smoke-discrepancy reproduction: without the
    retry layer the smoke would record 4/6 PASS (Check 2 and
    Check 6 FAIL). With the retry layer it records 6/6 PASS.
    """
    systemctl = _write_systemctl_mock(tmp_path)
    podman = _write_flipping_podman(
        tmp_path,
        fail_count_kv=2,
        counter_path_kv=tmp_path / "kv_counter",
    )
    curl = _write_flipping_curl(
        tmp_path, fail_count=2, counter_path=tmp_path / "curl_counter"
    )
    sleep_noop = _write_noop_sleep(tmp_path)
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(systemctl),
        "WAKIR_SMOKE_PODMAN": str(podman),
        "WAKIR_SMOKE_CURL": str(curl),
        "WAKIR_SMOKE_SLEEP": str(sleep_noop),
        "WAKIR_SMOKE_RETRY_MAX": "5",
        "WAKIR_SMOKE_RETRY_BASE": "0.01",
    }
    result = _run_smoke(env, ["--org", "acme", "--json"], timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SUMMARY: 6/6 checks PASS" in result.stdout, result.stdout
    # Both race-tolerant checks must show their attempt count > 1.
    jsz_lines = [
        l for l in result.stdout.splitlines()
        if "nats-jetstream-reachable " in l
    ]
    assert jsz_lines and "attempts=3" in jsz_lines[0]
    marker_lines = [
        l for l in result.stdout.splitlines()
        if "marker-stack-bucket-present " in l
    ]
    assert marker_lines and "attempts=3" in marker_lines[0]


def test_pilot_vm_baseline_2_to_4_without_retry_actually_fails(tmp_path):
    """Sanity: without retries, the same race substrate yields the
    smoke-discrepancy pattern (4/6 PASS).

    This is the proof-of-bug-without-fix invariant: the retry
    layer is the only thing that prevents the 2/6 ↔ 4/6
    oscillation. With ``WAKIR_SMOKE_RETRY_MAX=0`` the smoke
    falls back to single-shot semantics, and the same race
    substrate that yields 6/6 PASS above now yields 4/6 PASS.
    """
    systemctl = _write_systemctl_mock(tmp_path)
    podman = _write_flipping_podman(
        tmp_path,
        fail_count_kv=2,
        counter_path_kv=tmp_path / "kv_counter",
    )
    curl = _write_flipping_curl(
        tmp_path, fail_count=2, counter_path=tmp_path / "curl_counter"
    )
    sleep_noop = _write_noop_sleep(tmp_path)
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(systemctl),
        "WAKIR_SMOKE_PODMAN": str(podman),
        "WAKIR_SMOKE_CURL": str(curl),
        "WAKIR_SMOKE_SLEEP": str(sleep_noop),
        # Retry disabled — Tag-1 baseline semantics.
        "WAKIR_SMOKE_RETRY_MAX": "0",
    }
    result = _run_smoke(env, ["--org", "acme"], timeout=15)
    # Exit 2 (some checks FAIL).
    assert result.returncode == 2, result.stdout + result.stderr
    # Exactly 4/6 PASS (Tag-1 baseline reproduces the Pilot-VM
    # 4/6 discrepancy slice).
    assert "SUMMARY: 4/6 checks PASS" in result.stdout, result.stdout
    # Check 2 (jetstream-reachable) FAIL.
    jsz_lines = [
        l for l in result.stdout.splitlines()
        if "nats-jetstream-reachable " in l
    ]
    assert jsz_lines and "FAIL" in jsz_lines[0]
    # Check 6 (bucket-present) FAIL.
    marker_lines = [
        l for l in result.stdout.splitlines()
        if "marker-stack-bucket-present " in l
    ]
    assert marker_lines and "FAIL" in marker_lines[0]


# ---------------------------------------------------------------------------
# Race-Toleranz: SPIRE-server / agent
# ---------------------------------------------------------------------------


def _write_flipping_podman_spire(
    tmp_path: Path,
    *,
    fail_count_server: int,
    counter_server: Path,
    fail_count_agent: int,
    counter_agent: Path,
) -> Path:
    """A podman stub whose spire-server and spire-agent healthchecks
    each fail N times then succeed."""
    counter_server.write_text("0", encoding="utf-8")
    counter_agent.write_text("0", encoding="utf-8")
    script = (
        '#!/usr/bin/env bash\n'
        'set -u\n'
        f'COUNTER_S="{counter_server}"\n'
        f'FAIL_S={fail_count_server}\n'
        f'COUNTER_A="{counter_agent}"\n'
        f'FAIL_A={fail_count_agent}\n'
        'case "$1" in\n'
        '  exec)\n'
        '    case "$3" in\n'
        '      /opt/spire/bin/spire-server)\n'
        '        n=$(cat "$COUNTER_S")\n'
        '        n=$((n + 1))\n'
        '        echo "$n" > "$COUNTER_S"\n'
        '        if [[ $n -le $FAIL_S ]]; then\n'
        '          printf "server unhealthy\\n" >&2; exit 1\n'
        '        fi\n'
        '        printf "Server is healthy.\\n"; exit 0 ;;\n'
        '      /opt/spire/bin/spire-agent)\n'
        '        case "$4" in\n'
        '          healthcheck)\n'
        '            n=$(cat "$COUNTER_A")\n'
        '            n=$((n + 1))\n'
        '            echo "$n" > "$COUNTER_A"\n'
        '            if [[ $n -le $FAIL_A ]]; then\n'
        '              printf "agent unhealthy\\n" >&2; exit 1\n'
        '            fi\n'
        '            printf "Agent is healthy.\\n"; exit 0 ;;\n'
        '          api) '
        'printf "received 1 X509-SVID(s)\\n"; exit 0 ;;\n'
        '        esac ;;\n'
        '    esac ;;\n'
        '  run) printf "wakir-marker-stack-acme\\n"; exit 0 ;;\n'
        'esac\n'
        'exit 0\n'
    )
    p = tmp_path / "podman"
    p.write_text(script, encoding="utf-8")
    p.chmod(0o755)
    return p


def test_spire_server_health_race_clears(tmp_path):
    """SPIRE-server unhealthy twice, then healthy.

    Models the server-restart-loop race window: the smoke
    catches the server during a restart cycle, retries, and the
    next cycle reports healthy.
    """
    systemctl = _write_systemctl_mock(tmp_path)
    podman = _write_flipping_podman_spire(
        tmp_path,
        fail_count_server=2,
        counter_server=tmp_path / "srv_counter",
        fail_count_agent=0,
        counter_agent=tmp_path / "agt_counter",
    )
    curl = _write_flipping_curl(
        tmp_path, fail_count=0, counter_path=tmp_path / "curl_counter"
    )
    sleep_noop = _write_noop_sleep(tmp_path)
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(systemctl),
        "WAKIR_SMOKE_PODMAN": str(podman),
        "WAKIR_SMOKE_CURL": str(curl),
        "WAKIR_SMOKE_SLEEP": str(sleep_noop),
        "WAKIR_SMOKE_RETRY_MAX": "5",
        "WAKIR_SMOKE_RETRY_BASE": "0.01",
    }
    result = _run_smoke(env, ["--org", "acme"], timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    srv_lines = [
        l for l in result.stdout.splitlines()
        if "spire-server-healthy " in l
    ]
    assert srv_lines and "PASS" in srv_lines[0]
    assert "attempts=3" in srv_lines[0], srv_lines[0]


def test_spire_agent_health_race_clears(tmp_path):
    """SPIRE-agent unhealthy once, then healthy (Kai-Bug-7 fix-window)."""
    systemctl = _write_systemctl_mock(tmp_path)
    podman = _write_flipping_podman_spire(
        tmp_path,
        fail_count_server=0,
        counter_server=tmp_path / "srv_counter",
        fail_count_agent=1,
        counter_agent=tmp_path / "agt_counter",
    )
    curl = _write_flipping_curl(
        tmp_path, fail_count=0, counter_path=tmp_path / "curl_counter"
    )
    sleep_noop = _write_noop_sleep(tmp_path)
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(systemctl),
        "WAKIR_SMOKE_PODMAN": str(podman),
        "WAKIR_SMOKE_CURL": str(curl),
        "WAKIR_SMOKE_SLEEP": str(sleep_noop),
        "WAKIR_SMOKE_RETRY_MAX": "5",
        "WAKIR_SMOKE_RETRY_BASE": "0.01",
    }
    result = _run_smoke(env, ["--org", "acme"], timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    agt_lines = [
        l for l in result.stdout.splitlines()
        if "spire-agent-healthy " in l
    ]
    assert agt_lines and "PASS" in agt_lines[0]
    assert "attempts=2" in agt_lines[0], agt_lines[0]


# ---------------------------------------------------------------------------
# Backwards compatibility: retry-max=0 collapses to Tag-1 single-shot
# ---------------------------------------------------------------------------


def test_retry_max_zero_collapses_to_tag_1_single_shot(tmp_path):
    """With ``WAKIR_SMOKE_RETRY_MAX=0`` the smoke runs each probe exactly once.

    This preserves Tag-1 hermetic-test compatibility (the
    existing ``test_proxmox_bringup_smoke.py`` suite injects
    ``WAKIR_SMOKE_RETRY_MAX=0`` to keep tests fast even when the
    mock represents a permanent-failure scenario).
    """
    counter = tmp_path / "kv_counter"
    systemctl = _write_systemctl_mock(tmp_path)
    # Bucket race clears at attempt 2 — but with retry-max=0
    # we should ONLY see attempt 1, so this should FAIL.
    podman = _write_flipping_podman(
        tmp_path, fail_count_kv=1, counter_path_kv=counter
    )
    curl = _write_flipping_curl(
        tmp_path, fail_count=0, counter_path=tmp_path / "curl_counter"
    )
    sleep_noop = _write_noop_sleep(tmp_path)
    env = {
        "WAKIR_SMOKE_SYSTEMCTL": str(systemctl),
        "WAKIR_SMOKE_PODMAN": str(podman),
        "WAKIR_SMOKE_CURL": str(curl),
        "WAKIR_SMOKE_SLEEP": str(sleep_noop),
        "WAKIR_SMOKE_RETRY_MAX": "0",
    }
    result = _run_smoke(env, ["--org", "acme"], timeout=15)
    assert result.returncode == 2, result.stdout
    marker_lines = [
        l for l in result.stdout.splitlines()
        if "marker-stack-bucket-present " in l
    ]
    # No "attempts=N" suffix when the count is 1 (Tag-1 shape).
    assert marker_lines and "FAIL" in marker_lines[0]
    assert "attempts=" not in marker_lines[0], marker_lines[0]
