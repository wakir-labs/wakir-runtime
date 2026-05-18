# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/phase-3c/welle-5-pre-cutover-probe.sh``.

Mirror of test_welle_4_pre_cutover_probe.py for the Welle-5
(lifecycle_state_machine / fsm) pre-cutover probe.  Welle-5 has 7 axes
(5+1 per Auftrag: FSM-integrity carries phantom-scan as a single
axis, +1 rollback-probe) — tests cover the FSM-specific axes:
state-persistence, transition-integrity, phantom-transition-scan, and
the symmetric Cross-Modul-Drift A5 to Welle-4.

Scope (8 tests):

  1. test_help_flag_prints_usage_and_exits_zero
  2. test_missing_ssh_key_returns_precondition_without_dry_run
  3. test_dry_run_aggregates_green_with_expected_hash
  4. test_dry_run_aggregates_caution_without_expected_hash
  5. test_ssh_unreachable_emits_not_exec_verdict
  6. test_all_axes_green_renders_green_aggregate
  7. test_axis_5_pair_overlay_present_renders_block_symmetric
  8. test_axis_3_phantom_transitions_detected_renders_block
"""

from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path
from typing import List, Optional, Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROBE_SCRIPT = REPO_ROOT / "scripts" / "phase-3c" / "welle-5-pre-cutover-probe.sh"


# ---------------------------------------------------------------------------
# Fake-binary fixtures.
# ---------------------------------------------------------------------------


def _write_fake_ssh(
    tmp_path: Path,
    *,
    exit_code: int = 0,
    stdout_payload: str = "ok\n",
) -> Path:
    log_path = tmp_path / "fake-ssh.log"
    payload_path = tmp_path / "fake-ssh.payload"
    payload_path.write_text(stdout_payload)
    fake = tmp_path / "fake-ssh"
    lines = [
        "#!/usr/bin/env bash",
        "# Fake ssh for welle-5-pre-cutover-probe tests.",
        f"printf 'invocation\\n' >> {str(log_path)!r}",
        'for arg in "$@"; do',
        f"  printf 'arg: %s\\n' \"$arg\" >> {str(log_path)!r}",
        "done",
        f"cat {str(payload_path)!r}",
        f"exit {exit_code}",
    ]
    fake.write_text("\n".join(lines) + "\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return fake


def _write_fake_ssh_keyed(
    tmp_path: Path,
    *,
    axis_payloads: dict,
) -> Path:
    log_path = tmp_path / "fake-ssh.log"
    fake = tmp_path / "fake-ssh"

    payload_files = {}
    for idx, (needle, payload) in enumerate(axis_payloads.items()):
        pf = tmp_path / f"fake-ssh.payload.{idx}"
        pf.write_text(payload)
        payload_files[needle] = pf

    case_lines = []
    for needle, pf in payload_files.items():
        case_lines.append(f'*"{needle}"*) cat {str(pf)!r}; exit 0 ;;')
    case_lines.append("*) printf 'unmatched\\n'; exit 0 ;;")
    case_block = "\n  ".join(case_lines)

    script = (
        "#!/usr/bin/env bash\n"
        f"printf 'invocation\\n' >> {str(log_path)!r}\n"
        'for arg in "$@"; do\n'
        f"  printf 'arg: %s\\n' \"$arg\" >> {str(log_path)!r}\n"
        "done\n"
        'last="${@: -1}"\n'
        'case "$last" in\n'
        f"  {case_block}\n"
        "esac\n"
    )
    fake.write_text(script)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return fake


def _write_fake_date(tmp_path: Path) -> Path:
    fake = tmp_path / "fake-date"
    body = textwrap.dedent(
        """\
        #!/usr/bin/env bash
        fmt="${@: -1}"
        case "$fmt" in
            *%Y%m%dT*)    printf '20260518T120000Z' ;;
            *%Y-%m-%dT*)  printf '2026-05-18T12:00:00Z' ;;
            *)            printf '20260518T120000Z' ;;
        esac
        """
    )
    fake.write_text(body)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return fake


def _write_fake_ssh_key(tmp_path: Path) -> Path:
    key = tmp_path / "fake-key"
    key.write_text("# fake key for tests\n")
    key.chmod(0o600)
    return key


def _run_probe(
    args: List[str],
    *,
    tmp_path: Path,
    fake_ssh_payload: str = "ok\n",
    fake_ssh_exit: int = 0,
    fake_ssh_per_axis: Optional[dict] = None,
    ssh_key_present: bool = True,
    extra_env: Optional[dict] = None,
) -> Tuple[int, str, str, Path]:
    if fake_ssh_per_axis is not None:
        fake_ssh = _write_fake_ssh_keyed(tmp_path, axis_payloads=fake_ssh_per_axis)
    else:
        fake_ssh = _write_fake_ssh(
            tmp_path,
            exit_code=fake_ssh_exit,
            stdout_payload=fake_ssh_payload,
        )
    fake_date = _write_fake_date(tmp_path)

    if ssh_key_present:
        key = _write_fake_ssh_key(tmp_path)
    else:
        key = tmp_path / "missing-key"

    log_dir = tmp_path / "probe-logs"
    log_dir.mkdir(exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "WAKIR_SSH_BIN": str(fake_ssh),
            "WAKIR_DATE_BIN": str(fake_date),
            "WAKIR_PILOT_SSH_KEY": str(key),
            "WAKIR_PROBE_LOG_DIR": str(log_dir),
            "WAKIR_PILOT_HOST": "test-pilot",
            "WAKIR_PILOT_USER": "root",
        }
    )
    if extra_env:
        env.update(extra_env)

    result = subprocess.run(
        ["bash", str(PROBE_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
    )
    return result.returncode, result.stdout, result.stderr, tmp_path / "fake-ssh.log"


# ---------------------------------------------------------------------------
# Seven healthy-axes payload skeleton.
# ---------------------------------------------------------------------------


def _green_axis_payloads() -> dict:
    # Ordering matters: bash case picks FIRST-MATCH for each fake-ssh
    # invocation.  Needles must be unique per axis-cmd.  Each key below
    # exploits a substring that appears in exactly one axis-cmd:
    #
    #   AXIS-1 cmd: contains `lifecycle-state-machine-cli state-snapshot`
    #   AXIS-2 cmd: contains `welle-5-lifecycle-state-machine-cutover-smoke.py`
    #   AXIS-3 cmd: contains `lifecycle-state-machine-cli trace-validate`
    #   AXIS-4 cmd: contains `BackendDecision.*lifecycle_state_machine`
    #   AXIS-5 cmd: contains `BackendDecision.*state_backing`
    #   AXIS-6 cmd: contains `lifecycle-state-machine-cli state-hash`
    #   AXIS-7 cmd: contains `ls -ld /etc/systemd/system/persona-engine.service.d`
    return {
        "lifecycle-state-machine-cli state-snapshot": (
            "FSM-STATE-SNAPSHOT-OK\nAUDIT-OK\n"
        ),
        "welle-5-lifecycle-state-machine-cutover-smoke.py": (
            "PHASE_PRE OK\nPHASE_CUTOVER OK\nPHASE_POST OK\nRC=0\n"
        ),
        "lifecycle-state-machine-cli trace-validate": (
            '{"valid":true}\n{"phantom_transitions":[],"phantom_count":0}\n'
        ),
        # AXIS-4: backend-decision count line first (`12`) + component-tail.
        "BackendDecision.*lifecycle_state_machine": (
            "12\n---COMPONENT-TAIL---\n"
            "May 18 12:00 host persona-engine: "
            "BackendDecision component=lifecycle_state_machine backend=python\n"
        ),
        # AXIS-5: pair-component (state_backing) audit query.  Pair
        # overlay absent in default-state.
        "BackendDecision.*state_backing": (
            "---PAIR-AUDIT-TAIL---\n"
            "May 18 12:00 host persona-engine: "
            "BackendDecision component=state_backing backend=python\n"
        ),
        # AXIS-6 cross-lang hash.
        "lifecycle-state-machine-cli state-hash": '{"hash":"abc123"}\n',
        # AXIS-7: rollback-surface uses `ls -ld` (singular dir).
        "ls -ld /etc/systemd/system/persona-engine.service.d": (
            "drwxr-xr-x 2 root root /etc/systemd/system/persona-engine.service.d\n"
            "enabled\nsystemctl-OK\njournalctl-OK\n"
        ),
    }


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_help_flag_prints_usage_and_exits_zero(tmp_path: Path) -> None:
    rc, out, err, _ = _run_probe(["--help"], tmp_path=tmp_path)
    assert rc == 0, f"expected exit 0 on --help, got {rc}; stderr={err}"
    assert "welle-5" in out.lower() or "Pre-Cutover-Sanity-Probe" in out
    assert "--dry-run" in out
    assert "--expected-hash" in out
    assert "--pair-component" in out
    assert "green" in out and "block" in out


def test_missing_ssh_key_returns_precondition_without_dry_run(tmp_path: Path) -> None:
    rc, _out, err, _ = _run_probe(
        ["--expected-hash", "abc"],
        tmp_path=tmp_path,
        ssh_key_present=False,
    )
    assert rc == 3, f"expected precond exit 3 when ssh-key missing; got {rc}; err={err}"
    assert "SSH key not readable" in err


def test_dry_run_aggregates_green_with_expected_hash(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--dry-run", "--expected-hash", "deadbeef", "--quiet"],
        tmp_path=tmp_path,
    )
    assert rc == 0, f"expected green dry-run, got {rc}; out={out}"
    assert "PROBE-VERDICT=GREEN" in out
    assert "welle=5" in out
    assert "component=lifecycle_state_machine" in out
    assert "pair-component=state_backing" in out


def test_dry_run_aggregates_caution_without_expected_hash(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--dry-run", "--quiet"],
        tmp_path=tmp_path,
    )
    assert rc == 1, f"expected caution exit 1; got {rc}; out={out}"
    assert "PROBE-VERDICT=CAUTION" in out


def test_ssh_unreachable_emits_not_exec_verdict(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "deadbeef", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_exit=255,
        fake_ssh_payload="",
    )
    assert rc == 4, f"expected not-exec exit 4 on ssh-failure; got {rc}; out={out}"
    assert "PROBE-VERDICT=NOT-EXEC" in out


def test_all_axes_green_renders_green_aggregate(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "abc123", "--min-decisions", "5", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis=_green_axis_payloads(),
    )
    assert rc == 0, f"expected green aggregate, got {rc}; out={out}"
    assert "PROBE-VERDICT=GREEN" in out


def test_axis_5_pair_overlay_present_renders_block_symmetric(tmp_path: Path) -> None:
    # Symmetric to Welle-4: if state_backing overlay is already wired
    # on the VM, the Welle-5 cutover MUST NOT start (isolation broken).
    payloads = _green_axis_payloads()
    payloads["BackendDecision.*state_backing"] = (
        "welle-4-state-backing-rust.conf\n"
        "---PAIR-AUDIT-TAIL---\n"
        "May 18 12:00 host persona-engine: "
        "BackendDecision component=state_backing backend=rust\n"
    )
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "abc123", "--min-decisions", "5", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 2, f"expected block (pair-overlay present), got {rc}; out={out}"
    assert "PROBE-VERDICT=BLOCK" in out


def test_axis_3_phantom_transitions_detected_renders_block(tmp_path: Path) -> None:
    # AXIS-3 returns RED when trace-validate yields {"valid":false} AND
    # the phantom-transition list is non-empty.
    payloads = _green_axis_payloads()
    payloads["lifecycle-state-machine-cli trace-validate"] = (
        '{"valid":false,"reason":"phantom-edge detected"}\n'
        '{"phantom_transitions":[{"from":"X","to":"Y"}],"phantom_count":1}\n'
    )
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "abc123", "--min-decisions", "5", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 2, f"expected block (phantom transitions), got {rc}; out={out}"
    assert "PROBE-VERDICT=BLOCK" in out
