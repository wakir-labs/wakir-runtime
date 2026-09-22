# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the step-6 convergence substance-fix
(Bug-40 -- "installed" was not "applied").

Measured evidence (Operator-Hand, Live-VM, 2026-09-21/22)
--------------------------------------------------------

``step_6_quadlet`` rendered the SPIRE-server Quadlet unit, wrote it to
the systemd unit directory, ran ``daemon-reload``, found the service
``active`` and skipped the start with ``OK <unit> already active``.

  * unit file on disk:  ``PublishPort=0.0.0.0:8443:8443``
  * actual listener:    ``127.0.0.1:8443``
  * unit file written:  2026-09-21 20:11:44
  * container running since: 2026-09-20 19:59:46

The container had been created by an earlier run, from an earlier
version of the unit. A ``systemctl restart`` made the installed
directive live within a second. Generalised: any Quadlet change --
image pin, mount, env, resource limit -- could be installed, logged
``OK`` and never applied. The bootstrap was idempotent, not convergent.

What this file drives
---------------------

Behaviour, not source text. Each vector sources the bootstrap (its
``BASH_SOURCE`` main-gate makes that safe), points the three path
overrides at a tmp tree, injects a ``systemctl`` mock that records
every invocation, and calls the real helpers.

  * ``TV-CONV-1``  changed unit definition + running service
    -> ``systemctl restart`` is issued. This is the vector that goes
    RED when the restart is skipped.
  * ``TV-CONV-2``  NEGATIVE CONTROL: unchanged definition + running
    service -> no ``start``, no ``restart``, exit 0.
  * ``TV-CONV-3``  stopped service -> ``start`` (not ``restart``).
  * ``TV-CONV-4``  no applied-state record (the 2026-09-21 case: unit
    from run N-1, container from run N-2) -> one convergence restart,
    and the run after that restarts nothing.
  * ``TV-CONV-5``  a change to the bind-mounted config file -- not the
    ``.container`` unit -- also restarts. That is the class the
    ``ca_ttl`` / ``federates_with`` edits fall into.
  * ``TV-CONV-6``  the in-run change signal alone (install rewrote the
    file, applied-state record already matches) restarts.
  * ``TV-CONV-7``  ``_install_if_changed`` on identical content does
    not write and emits no change signal.
  * ``TV-CONV-8``  the Bug-25 wait points run on the RESTART path, not
    only on the cold-start path.
  * ``TV-CONV-9``  MUTATION CONTROL: with the drift check rolled back
    to "skip when active", TV-CONV-1's assertion goes red -- proof the
    vector actually tests the fix and not the scaffolding.
  * ``TV-CONV-10`` the ``already active`` skip marker is gone from the
    bootstrap and the in-sync line names the running-vs-installed
    relation instead.
  * ``TV-CONV-11`` every step-6 install path feeds the change signal
    (drift guard; supplements, never replaces, the behaviour vectors).
  * ``TV-CONV-12`` ``_carried_join_token`` round-trips the injected
    token, so a re-run renders a byte-identical agent unit instead of
    restarting the agent into ``-joinToken
    WAKIR_JOIN_TOKEN_PLACEHOLDER`` on every run.

Sandbox boundary
----------------

No systemd, no podman, no root. ``WAKIR_BOOTSTRAP_SYSTEMCTL`` points at
a mock; ``_pre_start_chown_sweep`` is stubbed in the driver (volume
ownership is Bug-22's surface, covered elsewhere);
``WAKIR_BOOTSTRAP_SKIP_SOCKET_WAIT=1`` short-circuits the agent
Workload-API socket wait -- its log line is what TV-CONV-8 asserts on.

-- Kai
"""

from __future__ import annotations

import os
import stat as stat_mod
import subprocess
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = (
    REPO_ROOT / "infra" / "spire" / "federation" / "wakir-pilot-bootstrap.sh"
)

SIDE = "wakir"
SERVER_UNIT = f"wakir-spire-server-federation-{SIDE}.service"
AGENT_UNIT = f"wakir-spire-agent-{SIDE}.service"
SERVER_CONTAINER_FILE = f"wakir-spire-server-federation-{SIDE}.container"
AGENT_CONTAINER_FILE = f"wakir-spire-agent-{SIDE}.container"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _make_executable(path: Path) -> None:
    path.chmod(
        path.stat().st_mode
        | stat_mod.S_IXUSR
        | stat_mod.S_IXGRP
        | stat_mod.S_IXOTH
    )


class Substrate:
    """A tmp stand-in for the VM's unit/config/state directories plus a
    recording ``systemctl``."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.quadlet = tmp_path / "quadlet"
        self.etc = tmp_path / "etc-wakir"
        self.applied = tmp_path / "applied-state"
        self.bin = tmp_path / "bin"
        for d in (self.quadlet, self.etc / "spire-federation", self.bin):
            d.mkdir(parents=True, exist_ok=True)
        self.systemctl_log = tmp_path / "systemctl.log"
        self.systemctl_log.write_text("")
        self.active_dir = tmp_path / "active"
        self.active_dir.mkdir()
        self.systemctl = self.bin / "systemctl-mock"
        self.systemctl.write_text(
            textwrap.dedent(
                f"""
                #!/usr/bin/env bash
                printf '%s\\n' "$*" >> {self.systemctl_log}
                unit="${{@: -1}}"
                case "$1" in
                  is-active)
                    [[ -f "{self.active_dir}/$unit" ]] && exit 0
                    exit 3
                    ;;
                  start|restart)
                    touch "{self.active_dir}/$unit"
                    exit 0
                    ;;
                  *) exit 0 ;;
                esac
                """
            ).strip()
            + "\n"
        )
        _make_executable(self.systemctl)

    # -- substrate state ----------------------------------------------
    def set_active(self, unit: str) -> None:
        (self.active_dir / unit).touch()

    def set_inactive(self, unit: str) -> None:
        f = self.active_dir / unit
        if f.exists():
            f.unlink()

    def write_unit(self, name: str, text: str) -> Path:
        p = self.quadlet / name
        p.write_text(text)
        return p

    def write_server_conf(self, text: str) -> Path:
        p = self.etc / "spire-federation" / f"spire-server-{SIDE}.conf"
        p.write_text(text)
        return p

    @property
    def calls(self) -> list[str]:
        return [
            line
            for line in self.systemctl_log.read_text().splitlines()
            if line.strip()
        ]

    def reset_calls(self) -> None:
        self.systemctl_log.write_text("")

    def stamp(self, unit: str) -> Path:
        return self.applied / f"{unit}.applied"

    # -- driver -------------------------------------------------------
    def run(self, body: str, timeout: int = 30) -> subprocess.CompletedProcess:
        drv = self.root / "driver.sh"
        drv.write_text(
            textwrap.dedent(
                f"""
                #!/usr/bin/env bash
                set -u
                source "{BOOTSTRAP}" >/dev/null 2>&1

                # Bug-22 surface, not this file's: volume ownership.
                _pre_start_chown_sweep() {{
                  printf 'chown-sweep %s\\n' "$1"
                  return 0
                }}
                """
            ).strip()
            + "\n"
            + textwrap.dedent(body)
            + "\n"
        )
        _make_executable(drv)
        return subprocess.run(
            ["bash", str(drv)],
            env={
                **os.environ,
                "WAKIR_SIDE": SIDE,
                "WAKIR_BOOTSTRAP_QUADLET_DIR": str(self.quadlet),
                "WAKIR_BOOTSTRAP_ETC_DIR": str(self.etc),
                "WAKIR_BOOTSTRAP_APPLIED_STATE_DIR": str(self.applied),
                "WAKIR_BOOTSTRAP_SYSTEMCTL": str(self.systemctl),
                "WAKIR_BOOTSTRAP_SKIP_SOCKET_WAIT": "1",
                "WAKIR_BOOTSTRAP_WAIT_ACTIVE_TIMEOUT": "10",
                "WAKIR_BOOTSTRAP_WAIT_ACTIVE_POLL": "1",
            },
            capture_output=True,
            text=True,
            timeout=timeout,
        )


@pytest.fixture
def substrate(tmp_path: Path) -> Substrate:
    return Substrate(tmp_path)


def _restart_calls(calls: list[str], unit: str) -> list[str]:
    return [c for c in calls if c.startswith(f"restart {unit}")]


def _start_calls(calls: list[str], unit: str) -> list[str]:
    return [c for c in calls if c.startswith(f"start {unit}")]


# ---------------------------------------------------------------------------
# TV-CONV-1: a changed unit definition on a running service is applied.
# ---------------------------------------------------------------------------


def test_changed_unit_definition_is_restarted(substrate: Substrate) -> None:
    """The 2026-09-21 case in miniature: the service is running, the
    installed unit says something else than what it was started from.
    The bootstrap must restart it -- not log OK and walk away."""
    substrate.write_unit(
        SERVER_CONTAINER_FILE, "PublishPort=127.0.0.1:8443:8443\n"
    )
    substrate.set_active(SERVER_UNIT)
    # Record "this is what the running container was created from".
    first = substrate.run(f'_record_unit_applied "{SERVER_UNIT}"')
    assert first.returncode == 0, first.stderr
    assert substrate.stamp(SERVER_UNIT).is_file()

    # An operator/earlier run changes the directive. Nothing restarts it.
    substrate.write_unit(
        SERVER_CONTAINER_FILE, "PublishPort=0.0.0.0:8443:8443\n"
    )
    substrate.reset_calls()

    proc = substrate.run(
        f'_converge_service_unit "{SERVER_UNIT}" "server"; echo "rc=$?"'
    )
    assert "rc=0" in proc.stdout, f"{proc.stdout}\n{proc.stderr}"
    assert _restart_calls(substrate.calls, SERVER_UNIT), (
        "Bug-40 regression: a running unit whose installed definition "
        "changed was NOT restarted; the change stays installed-only.\n"
        f"systemctl calls: {substrate.calls}\nstdout: {proc.stdout}"
    )
    assert "restart issued" in proc.stdout
    # And the applied-state record now matches the new definition, so
    # the next run leaves it alone.
    assert "0.0.0.0" not in substrate.stamp(SERVER_UNIT).read_text()


# ---------------------------------------------------------------------------
# TV-CONV-2: negative control -- an unchanged run restarts nothing.
# ---------------------------------------------------------------------------


def test_unchanged_unit_is_not_restarted(substrate: Substrate) -> None:
    """No restart storm: if the running container was created from
    exactly the installed definition, the unit is left alone."""
    substrate.write_unit(
        SERVER_CONTAINER_FILE, "PublishPort=0.0.0.0:8443:8443\n"
    )
    substrate.write_server_conf("ca_ttl = \"24h\"\n")
    substrate.set_active(SERVER_UNIT)
    substrate.run(f'_record_unit_applied "{SERVER_UNIT}"')
    substrate.reset_calls()

    proc = substrate.run(
        f'_converge_service_unit "{SERVER_UNIT}" "server"; echo "rc=$?"'
    )
    assert "rc=0" in proc.stdout, f"{proc.stdout}\n{proc.stderr}"
    assert not _restart_calls(substrate.calls, SERVER_UNIT), (
        f"unchanged unit must not be restarted; calls={substrate.calls}"
    )
    assert not _start_calls(substrate.calls, SERVER_UNIT), (
        f"unchanged unit must not be started; calls={substrate.calls}"
    )
    assert "chown-sweep" not in proc.stdout, (
        "no restart means no pre-start volume sweep either"
    )
    assert "matches the installed unit" in proc.stdout


# ---------------------------------------------------------------------------
# TV-CONV-3: a stopped unit is started, not restarted.
# ---------------------------------------------------------------------------


def test_stopped_unit_is_started(substrate: Substrate) -> None:
    substrate.write_unit(SERVER_CONTAINER_FILE, "PublishPort=x\n")
    substrate.set_inactive(SERVER_UNIT)

    proc = substrate.run(
        f'_converge_service_unit "{SERVER_UNIT}" "server"; echo "rc=$?"'
    )
    assert "rc=0" in proc.stdout, f"{proc.stdout}\n{proc.stderr}"
    assert _start_calls(substrate.calls, SERVER_UNIT)
    assert not _restart_calls(substrate.calls, SERVER_UNIT)
    assert "unit not running" in proc.stdout
    # Cold start keeps the Bug-22 pre-start volume sweep.
    assert "chown-sweep server" in proc.stdout


# ---------------------------------------------------------------------------
# TV-CONV-4: the 2026-09-21 case -- no applied-state record at all.
# ---------------------------------------------------------------------------


def test_unverifiable_running_config_converges_once_then_settles(
    substrate: Substrate,
) -> None:
    """A running unit with no applied-state record is exactly the
    2026-09-21 situation: the unit came from one run, the container
    from another, and nothing on the box can say whether they agree.
    The honest answer is one convergence restart -- and then quiet."""
    substrate.write_unit(
        SERVER_CONTAINER_FILE, "PublishPort=0.0.0.0:8443:8443\n"
    )
    substrate.set_active(SERVER_UNIT)
    assert not substrate.stamp(SERVER_UNIT).exists()

    first = substrate.run(
        f'_converge_service_unit "{SERVER_UNIT}" "server"; echo "rc=$?"'
    )
    assert "rc=0" in first.stdout, f"{first.stdout}\n{first.stderr}"
    assert _restart_calls(substrate.calls, SERVER_UNIT), (
        "a running unit of unverifiable provenance must be converged "
        f"once; calls={substrate.calls}"
    )
    assert "no applied-state record" in first.stdout

    substrate.reset_calls()
    second = substrate.run(
        f'_converge_service_unit "{SERVER_UNIT}" "server"; echo "rc=$?"'
    )
    assert "rc=0" in second.stdout
    assert not _restart_calls(substrate.calls, SERVER_UNIT), (
        "the run after the convergence pass must restart nothing; "
        f"calls={substrate.calls}"
    )


# ---------------------------------------------------------------------------
# TV-CONV-5: a changed bind-mounted config file also needs applying.
# ---------------------------------------------------------------------------


def test_changed_mounted_config_restarts_unit(substrate: Substrate) -> None:
    """The ``.container`` file is not the whole definition. A SPIRE
    server config change (``ca_ttl``, ``federates_with``) is mounted
    into the container and is just as dead until the restart."""
    substrate.write_unit(SERVER_CONTAINER_FILE, "PublishPort=x\n")
    substrate.write_server_conf('ca_ttl = "24h"\n')
    substrate.set_active(SERVER_UNIT)
    substrate.run(f'_record_unit_applied "{SERVER_UNIT}"')
    substrate.reset_calls()

    substrate.write_server_conf('ca_ttl = "168h"\n')
    proc = substrate.run(
        f'_converge_service_unit "{SERVER_UNIT}" "server"; echo "rc=$?"'
    )
    assert "rc=0" in proc.stdout, f"{proc.stdout}\n{proc.stderr}"
    assert _restart_calls(substrate.calls, SERVER_UNIT), (
        "a changed mounted config must be applied, not just installed; "
        f"calls={substrate.calls}"
    )


# ---------------------------------------------------------------------------
# TV-CONV-6: the in-run install signal alone is enough.
# ---------------------------------------------------------------------------


def test_in_run_install_signal_alone_triggers_restart(
    substrate: Substrate,
) -> None:
    """Isolates change-signal 1: the applied-state record is written
    AFTER the install, so the fingerprints agree and only the in-run
    marker can fire. It must."""
    substrate.write_unit(SERVER_CONTAINER_FILE, "PublishPort=old\n")
    substrate.set_active(SERVER_UNIT)
    src = substrate.root / "rendered.container"
    src.write_text("PublishPort=new\n")

    proc = substrate.run(
        f"""
        _install_if_changed "{src}" \\
          "{substrate.quadlet}/{SERVER_CONTAINER_FILE}"
        _record_unit_applied "{SERVER_UNIT}"
        _converge_service_unit "{SERVER_UNIT}" "server"; echo "rc=$?"
        """
    )
    assert "rc=0" in proc.stdout, f"{proc.stdout}\n{proc.stderr}"
    assert "definition changed in this run" in proc.stdout
    assert _restart_calls(substrate.calls, SERVER_UNIT), (
        f"in-run install signal ignored; calls={substrate.calls}"
    )


# ---------------------------------------------------------------------------
# TV-CONV-7: identical content is not a change (Bug 5 stays intact).
# ---------------------------------------------------------------------------


def test_identical_install_emits_no_change_signal(
    substrate: Substrate,
) -> None:
    target = substrate.write_unit(SERVER_CONTAINER_FILE, "PublishPort=same\n")
    substrate.set_active(SERVER_UNIT)
    src = substrate.root / "rendered.container"
    src.write_text("PublishPort=same\n")
    before = target.stat().st_mtime_ns

    proc = substrate.run(
        f"""
        _install_if_changed "{src}" "{target}"
        _record_unit_applied "{SERVER_UNIT}"
        _converge_service_unit "{SERVER_UNIT}" "server"; echo "rc=$?"
        """
    )
    assert "rc=0" in proc.stdout, f"{proc.stdout}\n{proc.stderr}"
    assert "definition changed in this run" not in proc.stdout
    assert target.stat().st_mtime_ns == before, (
        "Bug 5 regression: identical content must not be overwritten"
    )
    assert not _restart_calls(substrate.calls, SERVER_UNIT)


# ---------------------------------------------------------------------------
# TV-CONV-8: the Bug-25 wait points cover the restart path.
# ---------------------------------------------------------------------------


def test_bug_25_wait_points_run_on_the_restart_path(
    substrate: Substrate,
) -> None:
    """A restart re-opens the same activating / socket-bind race as a
    cold start. Both waits must fire after a restart, not only after a
    start."""
    substrate.write_unit(AGENT_CONTAINER_FILE, "Exec=-config a -joinToken t1\n")
    substrate.set_active(AGENT_UNIT)
    substrate.run(f'_record_unit_applied "{AGENT_UNIT}"')
    substrate.write_unit(AGENT_CONTAINER_FILE, "Exec=-config a -joinToken t2\n")
    substrate.reset_calls()

    proc = substrate.run(
        f'_converge_service_unit "{AGENT_UNIT}" "agent"; echo "rc=$?"'
    )
    assert "rc=0" in proc.stdout, f"{proc.stdout}\n{proc.stderr}"
    calls = substrate.calls
    assert _restart_calls(calls, AGENT_UNIT)
    restart_idx = calls.index(f"restart {AGENT_UNIT}")
    post = calls[restart_idx + 1:]
    assert any(c.startswith("is-active") for c in post), (
        "Bug-25 regression: no is-active probe after the restart; "
        f"calls={calls}"
    )
    assert "workload-API socket wait skipped" in proc.stdout, (
        "Bug-25 regression: the agent Workload-API socket wait does not "
        f"run on the restart path; stdout={proc.stdout}"
    )


# ---------------------------------------------------------------------------
# TV-CONV-9: mutation control.
# ---------------------------------------------------------------------------


def test_mutation_rollback_to_skip_when_active_goes_red(
    substrate: Substrate,
) -> None:
    """Roll the drift check back to the pre-fix behaviour ("running is
    good enough") and TV-CONV-1's assertion must fail. Without this
    control, TV-CONV-1 could be passing on the scaffolding rather than
    on the fix."""
    substrate.write_unit(SERVER_CONTAINER_FILE, "PublishPort=old\n")
    substrate.set_active(SERVER_UNIT)
    substrate.run(f'_record_unit_applied "{SERVER_UNIT}"')
    substrate.write_unit(SERVER_CONTAINER_FILE, "PublishPort=new\n")
    substrate.reset_calls()

    proc = substrate.run(
        f"""
        # Mutation: the pre-Bug-40 semantics -- an active unit is never
        # reconsidered.
        _unit_definition_drifted() {{ return 1; }}
        _converge_service_unit "{SERVER_UNIT}" "server"; echo "rc=$?"
        """
    )
    assert "rc=0" in proc.stdout
    assert not _restart_calls(substrate.calls, SERVER_UNIT), (
        "mutation control is a no-op: the rollback still restarted the "
        "unit, so TV-CONV-1 does not actually test the drift check"
    )


# ---------------------------------------------------------------------------
# TV-CONV-10: the log no longer claims OK for an unapplied unit.
# ---------------------------------------------------------------------------


def test_already_active_skip_marker_is_gone() -> None:
    """``OK <unit> already active`` was the line that made a skipped
    restart look like success. It must not come back -- and the line
    that replaces it must state the running-vs-installed relation."""
    src = BOOTSTRAP.read_text()
    emitting = [
        line.strip()
        for line in src.splitlines()
        if "already active" in line and not line.strip().startswith("#")
    ]
    assert not emitting, (
        "Bug-40 regression: the 'already active' skip marker is back. "
        "An OK line must not stand for 'we did not check whether the "
        f"running container matches the installed unit': {emitting}"
    )
    assert "matches the installed unit" in src


# ---------------------------------------------------------------------------
# TV-CONV-11: drift guard -- every step-6 install feeds the signal.
# ---------------------------------------------------------------------------


def test_step_6_install_paths_go_through_the_change_signal() -> None:
    """Supplement to the behaviour vectors: an install path that writes
    a unit file without ``_install_if_changed`` would be invisible to
    the convergence logic."""
    import re

    src = BOOTSTRAP.read_text()
    m = re.search(r"step_6_quadlet\(\) \{.*?^\}", src, re.DOTALL | re.MULTILINE)
    assert m, "step_6_quadlet body not found"
    body = m.group(0)
    stray = [
        line.strip()
        for line in body.splitlines()
        if "install -m 644" in line and not line.strip().startswith("#")
    ]
    assert not stray, (
        "step-6 writes a unit file outside _install_if_changed, so the "
        f"change signal misses it: {stray}"
    )
    assert "_install_if_changed" in body
    assert "_converge_service_unit" in body


# ---------------------------------------------------------------------------
# TV-CONV-12: join-token round-trip.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unit_text,expected",
    [
        ("Exec=-config /etc/spire/agent/agent.conf -joinToken abc123\n", "abc123"),
        (
            "Exec=-config /etc/spire/agent/agent.conf "
            "-joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER\n",
            "",
        ),
        ("Exec=-config /etc/spire/agent/agent.conf\n", ""),
    ],
)
def test_carried_join_token(
    substrate: Substrate, unit_text: str, expected: str
) -> None:
    """Without the round-trip, the rendered agent unit (placeholder)
    never equals the installed one (real token): every run would rewrite
    it, and -- now that the bootstrap converges -- restart the agent
    into ``-joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER``, which is the
    Bug-37 crash-loop."""
    unit = substrate.write_unit(AGENT_CONTAINER_FILE, unit_text)
    proc = substrate.run(f'printf "[%s]" "$(_carried_join_token "{unit}")"')
    assert proc.returncode == 0, proc.stderr
    assert f"[{expected}]" in proc.stdout


def test_carried_join_token_on_missing_file(substrate: Substrate) -> None:
    proc = substrate.run(
        f'printf "[%s]" "$(_carried_join_token "{substrate.root}/nope")"'
    )
    assert proc.returncode == 0, proc.stderr
    assert "[]" in proc.stdout


# ---------------------------------------------------------------------------
# TV-CONV-13: never apply an agent unit that still has the placeholder.
# ---------------------------------------------------------------------------


def test_agent_unit_with_placeholder_token_is_not_applied(
    substrate: Substrate,
) -> None:
    """Before convergence, an agent unit left holding
    ``WAKIR_JOIN_TOKEN_PLACEHOLDER`` was survivable by accident: it was
    never applied. It was still armed for the next VM reboot, where
    systemd would start the agent with a literal placeholder as its
    join-token (Bug-37 crash-loop). Now that the bootstrap applies what
    it installs, that unit must be refused loudly, not applied."""
    substrate.write_unit(
        AGENT_CONTAINER_FILE,
        "Exec=-config /etc/spire/agent/agent.conf "
        "-joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER\n",
    )
    substrate.set_active(AGENT_UNIT)

    proc = substrate.run(
        f'_converge_service_unit "{AGENT_UNIT}" "agent"; echo "rc=$?"'
    )
    assert "rc=2" in proc.stdout, (
        f"expected a hard stop; stdout={proc.stdout} stderr={proc.stderr}"
    )
    assert "WAKIR_JOIN_TOKEN_PLACEHOLDER" in proc.stderr
    assert not _restart_calls(substrate.calls, AGENT_UNIT), (
        f"agent restarted into a placeholder unit; calls={substrate.calls}"
    )
    assert not _start_calls(substrate.calls, AGENT_UNIT)


def test_step_6i_injects_whenever_the_placeholder_is_present() -> None:
    """Drift guard for the other half: the token injection must key on
    the placeholder being present, not on the agent being unattested.
    A re-installed unit carries the placeholder again even when the
    agent is long since attested."""
    import re

    src = BOOTSTRAP.read_text()
    m = re.search(
        r"if \[\[ -f \"\$agent_quadlet_dst\" \]\] \\\n"
        r"\s+&& grep -q \"WAKIR_JOIN_TOKEN_PLACEHOLDER\" \"\$agent_quadlet_dst\"; then",
        src,
    )
    assert m, (
        "step 6i must issue a join-token whenever the installed agent "
        "unit carries the placeholder, independent of the attestation "
        "state -- otherwise step 6j has to refuse to apply the unit."
    )
