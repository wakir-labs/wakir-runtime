# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/phase-3c/welle-4-pre-cutover-probe.sh``.

The probe orchestrates the Pre-Cutover-Sanity workflow for Phase-3c
Welle-4 (state_backing, ADR-0066 KW-26 Doppel-Welle) against the
wakir-pilot live VM (ADR-0058 SSH-Hand).  These tests must run
hermetically in CI: no real SSH connection, no real systemctl, no
real journalctl.

The fake-binary harness is identical to the Welle-1 probe test bed
(PR #267) — ``ssh`` is replaced via ``$WAKIR_SSH_BIN`` and ``date``
via ``$WAKIR_DATE_BIN``.  This deliberate symmetry keeps the probe-
test pattern uniform across all Wellen.

Scope (8 tests, exceeds Auftrag-Tag-42 minimum of 8):

  1. test_help_flag_prints_usage_and_exits_zero
  2. test_missing_ssh_key_returns_precondition_without_dry_run
  3. test_dry_run_aggregates_green_with_expected_hash
  4. test_dry_run_aggregates_caution_without_expected_hash
  5. test_ssh_unreachable_emits_not_exec_verdict
  6. test_all_axes_green_renders_green_aggregate
  7. test_axis_5_pair_overlay_present_renders_block
  8. test_axis_2_smoke_dry_run_failure_renders_block
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
PROBE_SCRIPT = REPO_ROOT / "scripts" / "phase-3c" / "welle-4-pre-cutover-probe.sh"


# ---------------------------------------------------------------------------
# Fake-binary fixtures (parallel to test_welle_1_pre_cutover_probe.py).
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
        "# Fake ssh for welle-4-pre-cutover-probe tests.",
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
    """Fake ``ssh`` returning per-axis stdout selected by needle in last argv."""
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
# Six healthy-axes payload skeleton — reused by happy-path tests.
# ---------------------------------------------------------------------------


def _green_axis_payloads() -> dict:
    # Ordering matters: bash case picks FIRST-MATCH for each fake-ssh
    # invocation.  Needles must be unique per axis-cmd.  The keys below
    # exploit substrings that only appear in one axis-cmd each:
    #
    #   AXIS-1 cmd: contains `state-backing-cli snapshot --json`
    #   AXIS-2 cmd: contains `welle-4-state-backing-cutover-smoke.py`
    #   AXIS-3 cmd: contains `grep -c BackendDecision`
    #   AXIS-4 cmd: contains `state-backing-cli snapshot-hash`
    #   AXIS-5 cmd: contains `BackendDecision.*lifecycle_state_machine`
    #   AXIS-6 cmd: contains `ls -ld /etc/systemd/system/persona-engine.service.d`
    return {
        # AXIS-1 first (most specific snapshot variant before snapshot-hash).
        "state-backing-cli snapshot --json": (
            "STATE-BACKING-SNAPSHOT-OK\nAUDIT-OK\n"
        ),
        "welle-4-state-backing-cutover-smoke.py": (
            "PHASE_PRE OK\nPHASE_CUTOVER OK\nPHASE_POST OK\nRC=0\n"
        ),
        "grep -c BackendDecision": (
            "12\n---COMPONENT-TAIL---\n"
            "May 18 12:00 host persona-engine: "
            "BackendDecision component=state_backing backend=python\n"
        ),
        "state-backing-cli snapshot-hash": '{"hash":"abc123"}\n',
        # AXIS-5 keyed by the pair-component substring in the journalctl
        # grep — unique to AXIS-5's cmd-string.
        "BackendDecision.*lifecycle_state_machine": (
            "---PAIR-AUDIT-TAIL---\n"
            "May 18 12:00 host persona-engine: "
            "BackendDecision component=lifecycle_state_machine backend=python\n"
        ),
        # AXIS-6: rollback-surface uses `ls -ld` (singular dir).
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
    assert "welle-4" in out.lower() or "Pre-Cutover-Sanity-Probe" in out
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
    assert "welle=4" in out
    assert "component=state_backing" in out
    assert "pair-component=lifecycle_state_machine" in out


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


def test_axis_5_pair_overlay_present_renders_block(tmp_path: Path) -> None:
    # If the lifecycle_state_machine (pair) overlay is already wired,
    # the parallel-Welle isolation contract is broken pre-cutover.
    # AXIS-5 cmd contains both the `ls -1 .../persona-engine.service.d/`
    # listing AND the `BackendDecision.*lifecycle_state_machine` grep
    # in a single ssh call — the AXIS-5 payload returns both halves.
    payloads = _green_axis_payloads()
    payloads["BackendDecision.*lifecycle_state_machine"] = (
        "welle-5-lifecycle-state-machine-rust.conf\n"
        "---PAIR-AUDIT-TAIL---\n"
        "May 18 12:00 host persona-engine: "
        "BackendDecision component=lifecycle_state_machine backend=rust\n"
    )
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "abc123", "--min-decisions", "5", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 2, f"expected block (pair-overlay present), got {rc}; out={out}"
    assert "PROBE-VERDICT=BLOCK" in out


def test_axis_2_smoke_dry_run_failure_renders_block(tmp_path: Path) -> None:
    # Welle-4 cutover-smoke dry-run reports a non-zero non-1 RC.
    payloads = _green_axis_payloads()
    payloads["welle-4-state-backing-cutover-smoke.py"] = (
        "PHASE_PRE OK\nPHASE_CUTOVER FAIL — A6 byte-stable hash mismatch\nRC=2\n"
    )
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "abc123", "--min-decisions", "5", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 2, f"expected block (smoke-dry-run rc=2), got {rc}; out={out}"
    assert "PROBE-VERDICT=BLOCK" in out
