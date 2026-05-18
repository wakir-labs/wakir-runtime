# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/phase-3c/welle-6-pre-cutover-probe.sh``.

The probe orchestrates the Pre-Cutover-Sanity workflow for Phase-3c
Welle-6 (subscribe_loop, ADR-0066 §Doppel-Welle KW-27) against the
wakir-pilot live VM (ADR-0058 SSH-Hand).  These tests must run
hermetically in CI: no real SSH connection, no real systemctl, no
real journalctl.  Achieved by:

  1. Replacing ``ssh`` with a fake under ``$WAKIR_SSH_BIN`` that
     records every invocation and emits caller-controlled stdout /
     exit-code.
  2. Pinning ``$WAKIR_DATE_BIN`` to a fake that emits a stable
     timestamp.
  3. Routing log + ssh-key paths into a per-test ``tmp_path``.

Scope (10 tests, exceeds Auftrag-Tag-42 minimum of 8):

  1. test_help_flag_prints_usage_and_exits_zero
  2. test_missing_ssh_key_returns_precondition_without_dry_run
  3. test_dry_run_aggregates_green
  4. test_ssh_unreachable_emits_not_exec_verdict
  5. test_axis_1_ack_queue_below_max_renders_green
  6. test_axis_1_ack_queue_far_above_max_renders_red
  7. test_axis_2_nats_zero_reconnects_renders_green
  8. test_axis_3_fsm_env_missing_renders_red
  9. test_axis_4_cross_modul_drift_welle_7_env_rust_renders_red
  10. test_help_mentions_phase_3_doppel_welle_anchor
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
PROBE_SCRIPT = REPO_ROOT / "scripts" / "phase-3c" / "welle-6-pre-cutover-probe.sh"


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


def _write_fake_ssh_keyed(tmp_path: Path, *, axis_payloads: dict) -> Path:
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
# Tests.
# ---------------------------------------------------------------------------


def test_help_flag_prints_usage_and_exits_zero(tmp_path: Path) -> None:
    rc, out, err, _ = _run_probe(["--help"], tmp_path=tmp_path)
    assert rc == 0, f"expected exit 0 on --help, got {rc}; stderr={err}"
    assert "welle-6-pre-cutover-probe" in out or "Pre-Cutover-Sanity-Probe" in out
    assert "--dry-run" in out
    assert "subscribe_loop" in out
    assert "green" in out and "block" in out


def test_missing_ssh_key_returns_precondition_without_dry_run(tmp_path: Path) -> None:
    rc, _out, err, _ = _run_probe(
        [],
        tmp_path=tmp_path,
        ssh_key_present=False,
    )
    assert rc == 3, f"expected precond exit 3 when ssh-key missing; got {rc}; err={err}"
    assert "SSH key not readable" in err


def test_dry_run_aggregates_green(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--dry-run", "--quiet"],
        tmp_path=tmp_path,
    )
    assert rc == 0, f"expected green dry-run, got {rc}; out={out}"
    assert "PROBE-VERDICT=GREEN" in out
    assert "welle=6" in out
    assert "component=subscribe_loop" in out
    assert "sibling=recovery_workflow" in out


def test_ssh_unreachable_emits_not_exec_verdict(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--quiet"],
        tmp_path=tmp_path,
        fake_ssh_exit=255,
        fake_ssh_payload="",
    )
    assert rc == 4, f"expected not-exec exit 4 on ssh-failure; got {rc}; out={out}"
    assert "PROBE-VERDICT=NOT-EXEC" in out


def _axis_payloads_all_green(ack_queue_depth: int = 12) -> dict:
    """Construct per-axis payloads where each axis returns GREEN.

    Keys are simple needles (no shell-meta) that pick the right
    SSH-command's last argv via bash case-pattern matching.
    """
    # Dict-order matters: bash case picks first matching pattern,
    # so put MORE-SPECIFIC needles first.  Each needle must occur in
    # exactly one axis's remote cmd (the bash `case "$last"`-arg).
    return {
        # AXIS-1 cmd: `persona-engine-cli subscribe-loop-status ...`
        "subscribe-loop-status": (
            '{"ack_queue_depth":' + str(ack_queue_depth) + ',"workers":3}\n'
        ),
        # AXIS-2 cmd: `journalctl ... --since="5 minutes ago" ... nats`
        "5 minutes ago": "0\n",
        # AXIS-3 cmd: `... grep -E "FSMTransition|lifecycle_state_machine"`
        "FSMTransition": (
            "Environment=WAKIR_FSM_BACKEND=rust\n"
            "---AUDIT-FSM-TAIL---\n"
            "May 18 12:00 host persona-engine: FSMTransition backend=rust lifecycle_state_machine pre->stable\n"
        ),
        # AXIS-4 cmd: `... OVERLAY-LIST ...`
        "OVERLAY-LIST": (
            "Environment=WAKIR_FSM_BACKEND=rust\n"
            "---OVERLAY-LIST---\n"
        ),
        # AXIS-5 cmd: `... systemctl is-enabled persona-engine ...`
        "is-enabled persona-engine": (
            "drwxr-xr-x 2 root root /etc/systemd/system/persona-engine.service.d\n"
            "enabled\nsystemctl-OK\njournalctl-OK\n"
        ),
    }


def test_axis_1_ack_queue_below_max_renders_green(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--ack-queue-max", "256", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis=_axis_payloads_all_green(ack_queue_depth=12),
    )
    assert rc == 0, f"expected green aggregate, got {rc}; out={out}"
    assert "PROBE-VERDICT=GREEN" in out


def test_axis_1_ack_queue_far_above_max_renders_red(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--ack-queue-max", "16", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis=_axis_payloads_all_green(ack_queue_depth=9999),
    )
    assert rc == 2, f"expected block (ack-queue-overflow), got {rc}; out={out}"
    assert "PROBE-VERDICT=BLOCK" in out


def test_axis_2_nats_zero_reconnects_renders_green(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis=_axis_payloads_all_green(ack_queue_depth=4),
    )
    assert rc == 0, f"expected green, got {rc}; out={out}"
    assert "PROBE-VERDICT=GREEN" in out


def test_axis_3_fsm_env_missing_renders_red(tmp_path: Path) -> None:
    payloads = _axis_payloads_all_green(ack_queue_depth=4)
    # Replace FSM-tail and overlay-list with versions missing the
    # WAKIR_FSM_BACKEND=rust pin.
    payloads["FSMTransition"] = (
        "Environment=\n---AUDIT-FSM-TAIL---\n"
        # No FSMTransition entries; env absent.
    )
    payloads["OVERLAY-LIST"] = "Environment=\n---OVERLAY-LIST---\n"
    rc, out, _err, _ = _run_probe(
        ["--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 2, f"expected block (fsm-env-missing), got {rc}; out={out}"
    assert "PROBE-VERDICT=BLOCK" in out


def test_axis_4_cross_modul_drift_welle_7_env_rust_renders_red(tmp_path: Path) -> None:
    # AXIS-4: if WAKIR_RECOVERY_WORKFLOW_BACKEND=rust leaked early
    # (Welle-7 already partially cutovert before Welle-6 starts) =>
    # cross-modul-drift RED => BLOCK.
    payloads = _axis_payloads_all_green(ack_queue_depth=4)
    payloads["OVERLAY-LIST"] = (
        "Environment=WAKIR_FSM_BACKEND=rust "
        "WAKIR_RECOVERY_WORKFLOW_BACKEND=rust\n"
        "---OVERLAY-LIST---\n"
    )
    rc, out, _err, _ = _run_probe(
        ["--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 2, f"expected block (cross-modul-drift), got {rc}; out={out}"
    assert "PROBE-VERDICT=BLOCK" in out


def test_help_mentions_phase_3_doppel_welle_anchor(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(["--help"], tmp_path=tmp_path)
    assert rc == 0
    # The help/header must surface ADR-0066 §Doppel-Welle KW-27
    # context so operator-hand-callers can locate the policy anchor.
    assert "Doppel-Welle" in out or "ADR-0066" in out
