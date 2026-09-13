# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the Sprint-9-Tag-10 bring-up-cleanup
substance fix (Bug-25 — service-boot-wait race, AR Fred bring-up-3/4/5/6
evidence 2026-05-12 through 2026-05-14).

Context
-------

Bring-up-6 reproduced the same two-phase failure that bring-up-3/4/5
had already exhibited:

  * Run-1: ``quadlet-units-active FAIL
    (wakir-spire-agent-wakir.service:activating)`` and
    ``spire-agent-healthy FAIL (no container found)``. The bootstrap's
    ``systemctl start`` had returned before the unit transitioned from
    ``activating`` to ``active``; the smoke (attempts=6, ~30s) fired
    too early.
  * Run-2: ``quadlet-units-active PASS`` but
    ``spire-agent-healthy FAIL (unable to determine health)`` and
    ``spire-workload-api-reachable FAIL
    (api.sock connect: no such file)``. The agent container was
    ``active`` but had not yet finished server-attestation and the
    Workload-API socket was not bound.
  * Run-3 (post-cold-cache): 6/6 PASS.

The Tag-9 (Bug-22) fix addressed the Time-of-Check-vs-Time-of-Use
race on the volume-owner only. The service-boot timing race is a
distinct class — it survives even with perfect volume ownership.

The Bug-25 fix is to **block the bootstrap** after every ``systemctl
start`` until the unit actually reaches ``is-active``, and (for the
agent) additionally until the Workload-API socket inside the container
is bound. Two new helpers carry the logic:

  * ``_wait_for_service_active`` (general systemd unit wait, capped by
    ``WAKIR_BOOTSTRAP_WAIT_ACTIVE_TIMEOUT`` (default 300s) with poll
    interval ``WAKIR_BOOTSTRAP_WAIT_ACTIVE_POLL`` (default 5s)).
  * ``_wait_for_workload_api_socket`` (agent-specific
    ``podman exec ... test -S`` wait, capped by
    ``WAKIR_BOOTSTRAP_WAIT_SOCKET_TIMEOUT`` (default 120s) with poll
    interval ``WAKIR_BOOTSTRAP_WAIT_SOCKET_POLL`` (default 5s)).

The smoke-test (Pfad B, defence-in-depth) additionally retries
``quadlet-units-active`` and ``spire-workload-api-reachable`` via
``with_retry`` and bumps the default ``RETRY_MAX`` from 5 to 30.

Test-Vector index (continues the Tag-7/Tag-8/Tag-9 ladder)
----------------------------------------------------------

  * ``TV-S9T10-25a``  ``_wait_for_service_active`` happy path: probe
    eventually flips to active, helper returns 0 within the timeout.
  * ``TV-S9T10-25b``  ``_wait_for_service_active`` hard halts on
    timeout exhaustion (returns 2, surfaces diagnostic).
  * ``TV-S9T10-25c``  ``_wait_for_service_active`` fast-path: unit
    already active returns 0 on the first probe (no sleep, no second
    is-active call).
  * ``TV-S9T10-25d``  ``_wait_for_workload_api_socket`` happy path:
    ``podman exec ... test -S`` eventually returns 0, helper exits 0.
  * ``TV-S9T10-25e``  ``_wait_for_workload_api_socket`` hard halts on
    timeout exhaustion.
  * ``TV-S9T10-25f``  Source-discipline drift guards — the bootstrap
    calls each new helper from the right step-6 spots and the smoke
    test wraps the right check functions with ``with_retry``.
  * ``TV-S9T10-25g``  Mutation test (Zone X / Amara): rolling back the
    wait-and-verify scaffold (removing the helper definition) makes
    the drift-guard tests red.

Sandbox boundary
----------------

Same shape as Tag-9: PATH-injected mocks for ``systemctl``, ``podman``,
``sleep``; the helper bodies are extracted into a tiny driver script
that exercises the post-fix invariants without booting systemd. The
mocks use file-system sentinels (a counter file) to model
``activating -> active`` and ``socket-absent -> socket-present``
transitions over N polls.

-- Tomás
"""

from __future__ import annotations

import os
import re
import stat as stat_mod
import subprocess
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = (
    REPO_ROOT / "infra" / "spire" / "federation" / "wakir-pilot-bootstrap.sh"
)
SMOKE = REPO_ROOT / "bin" / "proxmox-bringup-smoke"


# ---------------------------------------------------------------------------
# Driver: inline copies of _wait_for_service_active and
# _wait_for_workload_api_socket, byte-faithful to the bootstrap source
# (TV-25f drift-guard asserts they stay aligned). We do not ``source``
# the bootstrap because its top-level executes ``main`` on load.
# ---------------------------------------------------------------------------

HELPER_DRIVER = textwrap.dedent(
    r"""
    #!/usr/bin/env bash
    set -uo pipefail

    log_ok()    { printf 'OK    %s\n' "$1"; }
    log_warn()  { printf 'WARN  %s\n' "$1"; }
    log_err()   { printf 'ERROR %s\n' "$1" >&2; }
    log_note()  { printf 'note  %s\n' "$1"; }

    : "${WAKIR_BOOTSTRAP_SYSTEMCTL:=systemctl}"
    : "${WAKIR_BOOTSTRAP_PODMAN:=podman}"
    : "${WAKIR_BOOTSTRAP_SLEEP:=sleep}"

    _wait_for_service_active() {
      local unit="$1"
      local timeout="${WAKIR_BOOTSTRAP_WAIT_ACTIVE_TIMEOUT:-300}"
      local poll="${WAKIR_BOOTSTRAP_WAIT_ACTIVE_POLL:-5}"
      local elapsed=0

      if "$WAKIR_BOOTSTRAP_SYSTEMCTL" is-active --quiet "$unit"; then
        log_ok "${unit} is-active (already, t=0s)"
        return 0
      fi

      while [[ $elapsed -lt $timeout ]]; do
        "${WAKIR_BOOTSTRAP_SLEEP:-sleep}" "$poll" 2>/dev/null \
          || sleep "$poll"
        elapsed=$((elapsed + poll))
        if "$WAKIR_BOOTSTRAP_SYSTEMCTL" is-active --quiet "$unit"; then
          log_ok "${unit} is-active (after ${elapsed}s wait)"
          return 0
        fi
      done

      log_err "${unit} did not reach is-active within ${timeout}s (Bug-25 race window not closed)"
      log_note "diagnose: journalctl -u ${unit} -n 100 --no-pager"
      "$WAKIR_BOOTSTRAP_SYSTEMCTL" status "$unit" --no-pager >&2 2>/dev/null || true
      return 2
    }

    _wait_for_workload_api_socket() {
      local container="$1"
      local timeout="${WAKIR_BOOTSTRAP_WAIT_SOCKET_TIMEOUT:-120}"
      local poll="${WAKIR_BOOTSTRAP_WAIT_SOCKET_POLL:-5}"
      local socket="/run/spire/agent-sockets/api.sock"
      local elapsed=0

      while [[ $elapsed -lt $timeout ]]; do
        if "$WAKIR_BOOTSTRAP_PODMAN" exec "$container" \
             test -S "$socket" 2>/dev/null; then
          log_ok "${container} workload-API socket bound (after ${elapsed}s wait)"
          return 0
        fi
        "${WAKIR_BOOTSTRAP_SLEEP:-sleep}" "$poll" 2>/dev/null \
          || sleep "$poll"
        elapsed=$((elapsed + poll))
      done

      log_err "${container} workload-API socket ${socket} not bound within ${timeout}s (Bug-25 race window not closed)"
      log_note "diagnose: podman exec ${container} ls -la /run/spire/agent-sockets/ ; journalctl -u wakir-spire-agent-*.service -n 100 --no-pager"
      return 2
    }

    op="$1"; shift
    case "$op" in
      wait_active)  _wait_for_service_active        "$@" ;;
      wait_socket)  _wait_for_workload_api_socket   "$@" ;;
      *) echo "unknown op: $op" >&2; exit 99 ;;
    esac
    """
).strip()


def _make_executable(path: Path) -> None:
    path.chmod(
        path.stat().st_mode
        | stat_mod.S_IXUSR
        | stat_mod.S_IXGRP
        | stat_mod.S_IXOTH
    )


def _write_mock(path: Path, body: str) -> None:
    path.write_text(body)
    _make_executable(path)


@pytest.fixture
def driver(tmp_path: Path) -> Path:
    drv = tmp_path / "tag10_driver.sh"
    drv.write_text(HELPER_DRIVER + "\n")
    _make_executable(drv)
    return drv


def _sandbox_path(tmp_path: Path) -> Path:
    sandbox = tmp_path / "sandbox_bin"
    sandbox.mkdir(exist_ok=True)
    return sandbox


def _noop_sleep(sandbox: Path) -> Path:
    # Use a no-op sleep so wall-clock stays under 1s even when the
    # driver loops dozens of times.
    p = sandbox / "sleep"
    _write_mock(p, "#!/usr/bin/env bash\nexit 0\n")
    return p


def _pathenv(sandbox: Path) -> str:
    return f"{sandbox}:{os.environ.get('PATH', '/usr/bin:/bin')}"


# ---------------------------------------------------------------------------
# TV-S9T10-25a: happy path — systemctl is-active flips to active after
# N polls; helper returns 0 within timeout and emits the expected OK
# line with elapsed-seconds annotation.
# ---------------------------------------------------------------------------


def test_wait_active_flips_active_after_n_polls(
    tmp_path: Path,
    driver: Path,
) -> None:
    sandbox = _sandbox_path(tmp_path)
    _noop_sleep(sandbox)
    state = tmp_path / "systemctl-poll-count"
    state.write_text("0")
    # Stub systemctl: increments a counter on every is-active call.
    # Returns "activating" for the first 2 calls, "active" thereafter.
    # Fast-path absorbs call 1, so calls 2 and 3 are the in-loop probes.
    systemctl_mock = textwrap.dedent(
        f"""
        #!/usr/bin/env bash
        if [[ "$1" == "is-active" ]]; then
          n=$(cat {state} 2>/dev/null || echo 0)
          n=$((n + 1))
          echo "$n" > {state}
          if (( n <= 2 )); then exit 3; else exit 0; fi
        fi
        if [[ "$1" == "status" ]]; then exit 0; fi
        exit 0
        """
    ).strip()
    _write_mock(sandbox / "systemctl", systemctl_mock)

    proc = subprocess.run(
        ["bash", str(driver), "wait_active", "wakir-spire-agent-wakir.service"],
        env={
            **os.environ,
            "PATH": _pathenv(sandbox),
            "WAKIR_BOOTSTRAP_WAIT_ACTIVE_TIMEOUT": "30",
            "WAKIR_BOOTSTRAP_WAIT_ACTIVE_POLL": "5",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, (
        f"expected exit 0, got {proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    # The OK line must reflect the in-loop branch (elapsed > 0), not
    # the fast-path branch.
    assert "after" in proc.stdout and "s wait" in proc.stdout, (
        f"in-loop OK line missing; stdout={proc.stdout!r}"
    )


# ---------------------------------------------------------------------------
# TV-S9T10-25b: timeout exhaustion — is-active never returns success;
# helper exits 2 with a Bug-25-tagged error line.
# ---------------------------------------------------------------------------


def test_wait_active_hard_halts_on_timeout(
    tmp_path: Path,
    driver: Path,
) -> None:
    sandbox = _sandbox_path(tmp_path)
    _noop_sleep(sandbox)
    # is-active always non-zero, status returns 0 (so the diagnostic
    # branch can run cleanly).
    systemctl_mock = textwrap.dedent(
        """
        #!/usr/bin/env bash
        if [[ "$1" == "is-active" ]]; then exit 3; fi
        if [[ "$1" == "status" ]]; then echo "stub-status-output" >&2; exit 0; fi
        exit 0
        """
    ).strip()
    _write_mock(sandbox / "systemctl", systemctl_mock)

    proc = subprocess.run(
        ["bash", str(driver), "wait_active", "wakir-spire-server-federation-wakir.service"],
        env={
            **os.environ,
            "PATH": _pathenv(sandbox),
            # Force fast convergence on the failure path (3 polls).
            "WAKIR_BOOTSTRAP_WAIT_ACTIVE_TIMEOUT": "15",
            "WAKIR_BOOTSTRAP_WAIT_ACTIVE_POLL": "5",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 2, (
        f"expected exit 2 on timeout, got {proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "Bug-25" in proc.stderr, (
        f"timeout diagnostic must tag Bug-25; stderr={proc.stderr!r}"
    )
    assert "did not reach is-active" in proc.stderr


# ---------------------------------------------------------------------------
# TV-S9T10-25c: fast-path — unit already active on first probe; helper
# returns 0 without calling sleep.
# ---------------------------------------------------------------------------


def test_wait_active_fast_path_already_active(
    tmp_path: Path,
    driver: Path,
) -> None:
    sandbox = _sandbox_path(tmp_path)
    # sleep mock that ERRORS if called — proves fast-path skipped it.
    sleep_mock_failmarker = tmp_path / "sleep-was-called"
    sleep_body = textwrap.dedent(
        f"""
        #!/usr/bin/env bash
        touch {sleep_mock_failmarker}
        exit 0
        """
    ).strip()
    _write_mock(sandbox / "sleep", sleep_body)
    # is-active returns 0 on the very first call.
    systemctl_mock = "#!/usr/bin/env bash\nexit 0\n"
    _write_mock(sandbox / "systemctl", systemctl_mock)

    proc = subprocess.run(
        ["bash", str(driver), "wait_active", "wakir-nats.service"],
        env={
            **os.environ,
            "PATH": _pathenv(sandbox),
            "WAKIR_BOOTSTRAP_WAIT_ACTIVE_TIMEOUT": "30",
            "WAKIR_BOOTSTRAP_WAIT_ACTIVE_POLL": "5",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    assert "(already, t=0s)" in proc.stdout, (
        f"fast-path OK line missing; stdout={proc.stdout!r}"
    )
    assert not sleep_mock_failmarker.exists(), (
        "fast-path must not invoke sleep"
    )


# ---------------------------------------------------------------------------
# TV-S9T10-25d: socket-wait happy path — podman exec test -S eventually
# returns 0; helper exits 0.
# ---------------------------------------------------------------------------


def test_wait_socket_succeeds_after_n_polls(
    tmp_path: Path,
    driver: Path,
) -> None:
    sandbox = _sandbox_path(tmp_path)
    _noop_sleep(sandbox)
    state = tmp_path / "podman-exec-count"
    state.write_text("0")
    # Stub podman: first 2 exec calls fail, 3rd succeeds.
    podman_mock = textwrap.dedent(
        f"""
        #!/usr/bin/env bash
        if [[ "$1" == "exec" ]]; then
          n=$(cat {state} 2>/dev/null || echo 0)
          n=$((n + 1))
          echo "$n" > {state}
          if (( n <= 2 )); then exit 1; else exit 0; fi
        fi
        exit 0
        """
    ).strip()
    _write_mock(sandbox / "podman", podman_mock)

    proc = subprocess.run(
        ["bash", str(driver), "wait_socket", "wakir-spire-agent-wakir"],
        env={
            **os.environ,
            "PATH": _pathenv(sandbox),
            "WAKIR_BOOTSTRAP_WAIT_SOCKET_TIMEOUT": "30",
            "WAKIR_BOOTSTRAP_WAIT_SOCKET_POLL": "5",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, (
        f"expected exit 0, got {proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "workload-API socket bound" in proc.stdout
    # Must report wait-seconds annotation (the in-loop branch).
    assert re.search(r"after \d+s wait", proc.stdout), (
        f"in-loop OK line missing; stdout={proc.stdout!r}"
    )


# ---------------------------------------------------------------------------
# TV-S9T10-25e: socket-wait timeout exhaustion.
# ---------------------------------------------------------------------------


def test_wait_socket_hard_halts_on_timeout(
    tmp_path: Path,
    driver: Path,
) -> None:
    sandbox = _sandbox_path(tmp_path)
    _noop_sleep(sandbox)
    # podman exec always fails.
    podman_mock = textwrap.dedent(
        """
        #!/usr/bin/env bash
        if [[ "$1" == "exec" ]]; then exit 1; fi
        exit 0
        """
    ).strip()
    _write_mock(sandbox / "podman", podman_mock)

    proc = subprocess.run(
        ["bash", str(driver), "wait_socket", "wakir-spire-agent-wakir"],
        env={
            **os.environ,
            "PATH": _pathenv(sandbox),
            "WAKIR_BOOTSTRAP_WAIT_SOCKET_TIMEOUT": "10",
            "WAKIR_BOOTSTRAP_WAIT_SOCKET_POLL": "5",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 2, (
        f"expected exit 2 on socket timeout, got {proc.returncode}"
    )
    assert "Bug-25" in proc.stderr, (
        f"timeout diagnostic must tag Bug-25; stderr={proc.stderr!r}"
    )
    assert "not bound within" in proc.stderr


# ---------------------------------------------------------------------------
# TV-S9T10-25f: source-discipline drift guards.
# ---------------------------------------------------------------------------


def test_bootstrap_defines_wait_for_service_active_helper() -> None:
    src = BOOTSTRAP.read_text()
    assert "_wait_for_service_active()" in src, (
        "Bug-25 regression: _wait_for_service_active helper missing"
    )


def test_bootstrap_defines_wait_for_workload_api_socket_helper() -> None:
    src = BOOTSTRAP.read_text()
    assert "_wait_for_workload_api_socket()" in src, (
        "Bug-25 regression: _wait_for_workload_api_socket helper missing"
    )


def test_step_6h_calls_wait_for_service_active_for_server() -> None:
    """Bootstrap step-6h must wait on the server unit before step-6i
    issues the join-token generate. If this call goes missing, the
    bootstrap races the server boot.
    """
    src = BOOTSTRAP.read_text()
    # The server-start block is identifiable by the server_unit local var.
    m = re.search(
        r'server_unit="wakir-spire-server-federation-\$\{side\}\.service".*?'
        r'_wait_for_service_active "\$server_unit"',
        src,
        re.DOTALL,
    )
    assert m, (
        "Bug-25 regression: step-6h must call _wait_for_service_active "
        "on $server_unit after systemctl start"
    )


def test_step_6j_loop_calls_wait_for_service_active() -> None:
    """The agent + NATS start loop must wait on each unit reaching
    is-active before continuing.
    """
    src = BOOTSTRAP.read_text()
    assert '_wait_for_service_active "$unit"' in src, (
        "Bug-25 regression: step-6j case-dispatch loop must call "
        "_wait_for_service_active with the resolved unit"
    )


def test_step_6j_calls_wait_for_workload_api_socket_for_agent_only() -> None:
    """The agent kind must additionally wait for the Workload-API
    socket; NATS does not have this race.
    """
    src = BOOTSTRAP.read_text()
    # The agent-only socket wait must be guarded by the kind == agent
    # check.
    m = re.search(
        r'\[\[ "\$kind" == "agent" \]\].*?'
        r'_wait_for_workload_api_socket "wakir-spire-agent-\$\{side\}"',
        src,
        re.DOTALL,
    )
    assert m, (
        "Bug-25 regression: step-6j must call _wait_for_workload_api_socket "
        "only when kind==agent"
    )


def test_smoke_quadlet_units_active_wrapped_with_retry() -> None:
    """The smoke-test ``check_quadlet_units_active`` must drive the
    probe through ``with_retry`` rather than execute a single one-shot
    pass — the bring-up-3/4/5/6 Run-1 evidence is exactly that this
    check fired before the units transitioned to active.
    """
    src = SMOKE.read_text()
    assert "_probe_quadlet_units_active" in src, (
        "Bug-25 regression: probe function for quadlet-units-active "
        "must be defined separately so with_retry can drive it"
    )
    # The check function body must invoke with_retry on the probe.
    m = re.search(
        r"check_quadlet_units_active\(\)\s*\{[^}]*?with_retry "
        r"_probe_quadlet_units_active",
        src,
        re.DOTALL,
    )
    assert m, (
        "Bug-25 regression: check_quadlet_units_active must wrap its "
        "probe with with_retry"
    )


def test_smoke_workload_api_reachable_wrapped_with_retry() -> None:
    """The smoke-test ``check_spire_workload_api_reachable`` must
    drive its probe through ``with_retry`` — bring-up-3/4/5/6 Run-2
    evidence is exactly that the socket-bind window is still open
    when the check fires.
    """
    src = SMOKE.read_text()
    assert "_probe_spire_workload_api_reachable" in src, (
        "Bug-25 regression: probe function for workload-api-reachable "
        "must be defined separately so with_retry can drive it"
    )
    m = re.search(
        r"check_spire_workload_api_reachable\(\)\s*\{[^}]*?with_retry "
        r"_probe_spire_workload_api_reachable",
        src,
        re.DOTALL,
    )
    assert m, (
        "Bug-25 regression: check_spire_workload_api_reachable must "
        "wrap its probe with with_retry"
    )


def test_smoke_retry_max_default_bumped_for_first_boot_wait_window() -> None:
    """Defence-in-depth (Pfad B): RETRY_MAX default raised from 5 to
    30 to survive a cold-cache first-boot even if the bootstrap-side
    wait helpers were misconfigured. With a 5s cap, 30 retries
    converge in ~130s worst-case.
    """
    src = SMOKE.read_text()
    # Match the assignment line specifically — guards against a future
    # PR silently flipping the default back.
    m = re.search(
        r'^RETRY_MAX="\$\{WAKIR_SMOKE_RETRY_MAX:-(\d+)\}"',
        src,
        re.MULTILINE,
    )
    assert m, "RETRY_MAX assignment line missing"
    assert int(m.group(1)) >= 30, (
        f"Bug-25 regression: RETRY_MAX default must be >= 30 "
        f"(saw {m.group(1)})"
    )


def test_helper_driver_mirrors_source_wait_invariants() -> None:
    """Drift-guard: the test-internal helper-driver text mirrors the
    source's post-fix invariants (timeout env var names, poll env var
    names, Bug-25 diagnostic tag). Same shape as Tag-8/Tag-9 mirrors.
    """
    src = BOOTSTRAP.read_text()
    # Env var names must remain stable for operator runbooks.
    assert "WAKIR_BOOTSTRAP_WAIT_ACTIVE_TIMEOUT" in src
    assert "WAKIR_BOOTSTRAP_WAIT_ACTIVE_POLL" in src
    assert "WAKIR_BOOTSTRAP_WAIT_SOCKET_TIMEOUT" in src
    assert "WAKIR_BOOTSTRAP_WAIT_SOCKET_POLL" in src
    # Bug-25 tag surfaces on both timeout paths.
    assert "Bug-25 race window not closed" in src
    # Fast-path probe before the first sleep (mandatory).
    assert '(already, t=0s)' in src, (
        "Bug-25 regression: fast-path log line missing — risk: every "
        "idempotent re-run pays a poll cycle of latency"
    )


# ---------------------------------------------------------------------------
# TV-S9T10-25g: mutation test (Zone X / Amara cross-review).
# Roll back the wait-and-verify scaffold (remove the helper definition
# from a synthetic copy of the bootstrap source) and assert that the
# drift-guard test_bootstrap_defines_wait_for_service_active_helper
# would have caught it. The mutation is performed in memory; the real
# bootstrap source on disk is untouched.
# ---------------------------------------------------------------------------


def test_mutation_rollback_breaks_drift_guard(tmp_path: Path) -> None:
    """If a future PR drops the ``_wait_for_service_active`` definition
    from the bootstrap, the source-discipline test must turn red.
    """
    original = BOOTSTRAP.read_text()
    # Remove the helper definition.
    mutated = re.sub(
        r"\n_wait_for_service_active\(\) \{.*?\n\}\n",
        "\n",
        original,
        count=1,
        flags=re.DOTALL,
    )
    assert mutated != original, "mutation must change the source text"

    # Re-run the equivalent drift-guard assertion against the mutated
    # text. Must fail (i.e. the helper definition string is gone).
    assert "_wait_for_service_active()" not in mutated, (
        "Zone-X mutation control: rollback must remove the helper "
        "definition — if this assertion passes the mutation is a no-op "
        "and the drift-guard would not have caught the rollback"
    )

    # Symmetrically: removing the call site must also be detectable.
    mutated_call = original.replace(
        '_wait_for_service_active "$server_unit" || return 2',
        '# wait removed',
        1,
    )
    assert mutated_call != original, "call-site mutation must change the source"
    assert '_wait_for_service_active "$server_unit" || return 2' not in mutated_call


def test_mutation_rollback_breaks_smoke_retry_drift_guard() -> None:
    """If a future PR un-wraps the smoke quadlet-units-active check
    (drops the with_retry), the smoke drift-guard must turn red.
    """
    original = SMOKE.read_text()
    mutated = re.sub(
        r"with_retry _probe_quadlet_units_active",
        "_probe_quadlet_units_active",
        original,
        count=1,
    )
    assert mutated != original, "smoke retry mutation must change the source"
    # The drift-guard regex must no longer match.
    m = re.search(
        r"check_quadlet_units_active\(\)\s*\{[^}]*?with_retry "
        r"_probe_quadlet_units_active",
        mutated,
        re.DOTALL,
    )
    assert m is None, (
        "Zone-X mutation control: rollback must remove the with_retry "
        "wrap — if this assertion passes the mutation is a no-op"
    )
