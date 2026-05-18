# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/phase-3c/live-vm-cutover-drill.sh``.

The drill orchestrates the Mira-Hand SSH-Cutover sequence against the
wakir-pilot live VM (ADR-0058 §Nachtrag).  These tests must run
hermetically in CI sandboxes: no real SSH connection, no real systemctl,
no real journalctl.  We achieve that by:

  1. Replacing the ``ssh`` binary the script invokes with a fake under
     ``$WAKIR_SSH_BIN`` that records every invocation and emits caller-
     controlled stdout / exit-code.
  2. Pinning ``$WAKIR_DATE_BIN`` to a fake that emits a stable
     timestamp, so log lines and overlay-filenames are deterministic.
  3. Pinning ``$WAKIR_DRILL_LOG_DIR`` and ``$WAKIR_PILOT_SSH_KEY`` into
     a per-test tmp_path so no host paths leak.

Scope (15 tests, exceeds Auftrag-Tag-40 minimum of 12)
------------------------------------------------------

1.  test_help_flag_prints_usage_and_exits_zero
2.  test_missing_action_returns_precondition
3.  test_invalid_welle_returns_precondition
4.  test_invalid_action_returns_precondition
5.  test_full_marathon_excludes_welle_arg
6.  test_dry_run_welle_1_pre_emits_snapshot_steps
7.  test_dry_run_welle_1_cutover_renders_single_env_overlay
8.  test_dry_run_welle_3_cutover_renders_two_env_lines
9.  test_dry_run_welle_4_uses_rust_inmemory_value
10. test_dry_run_welle_1_rollback_emits_removal_and_python_verify
11. test_dry_run_post_succeeds_when_backend_decisions_present
12. test_full_marathon_dry_run_walks_seven_wellen_in_order
13. test_sequence_gate_blocks_welle_2_without_welle_1_signoff
14. test_sequence_gate_passes_when_parent_signoff_present
15. test_ssh_key_missing_returns_precondition_without_dry_run
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import textwrap
from pathlib import Path
from typing import List, Optional, Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DRILL_SCRIPT = REPO_ROOT / "scripts" / "phase-3c" / "live-vm-cutover-drill.sh"


# ---------------------------------------------------------------------------
# Fake-binary fixtures.
# ---------------------------------------------------------------------------


def _write_fake_ssh(
    tmp_path: Path,
    *,
    exit_code: int = 0,
    stdout_payload: str = "5\n",
) -> Path:
    """Create a fake ``ssh`` binary that logs every invocation."""
    log_path = tmp_path / "fake-ssh.log"
    fake = tmp_path / "fake-ssh"
    body = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        # Fake ssh for live-vm-cutover-drill tests.
        # Logs the entire argv to {log_path} and emits a canned stdout.
        printf '--- ssh invocation ---\\n' >> '{log_path}'
        for arg in "$@"; do
            printf 'arg: %s\\n' "$arg" >> '{log_path}'
        done
        printf '%s' '{stdout_payload}'
        exit {exit_code}
        """
    )
    fake.write_text(body)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return fake


def _write_fake_date(tmp_path: Path) -> Path:
    """Create a fake ``date`` binary that emits a stable timestamp.

    Important: the drill script invokes the bin both with
    ``-u +%Y%m%dT%H%M%SZ`` (compact) and ``-u +%Y-%m-%dT%H:%M:%SZ``
    (dashed); the fake serves both via switch on the format arg.
    """
    fake = tmp_path / "fake-date"
    body = textwrap.dedent(
        """\
        #!/usr/bin/env bash
        # Fake date: emits a fixed timestamp in either compact or dashed.
        fmt="${@: -1}"
        case "$fmt" in
            *%Y%m%dT*)      printf '20260518T120000Z' ;;
            *%Y-%m-%dT*)    printf '2026-05-18T12:00:00Z' ;;
            *)              printf '20260518T120000Z' ;;
        esac
        """
    )
    fake.write_text(body)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return fake


def _write_fake_ssh_key(tmp_path: Path) -> Path:
    """Write a placeholder ssh-key file so the readability gate passes."""
    key = tmp_path / "fake-key"
    key.write_text("# fake key for tests\n")
    key.chmod(0o600)
    return key


def _run_drill(
    args: List[str],
    *,
    tmp_path: Path,
    fake_ssh_payload: str = "5\n",
    fake_ssh_exit: int = 0,
    ssh_key_present: bool = True,
    extra_env: Optional[dict] = None,
) -> Tuple[int, str, str, Path]:
    """Invoke the drill script with hermetic fakes.

    Returns ``(returncode, stdout, stderr, fake_ssh_log_path)``.
    """
    fake_ssh = _write_fake_ssh(
        tmp_path,
        exit_code=fake_ssh_exit,
        stdout_payload=fake_ssh_payload,
    )
    fake_date = _write_fake_date(tmp_path)

    if ssh_key_present:
        key = _write_fake_ssh_key(tmp_path)
    else:
        key = tmp_path / "missing-key"  # file intentionally not created

    log_dir = tmp_path / "drill-logs"
    log_dir.mkdir(exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "WAKIR_SSH_BIN": str(fake_ssh),
            "WAKIR_DATE_BIN": str(fake_date),
            "WAKIR_PILOT_SSH_KEY": str(key),
            "WAKIR_DRILL_LOG_DIR": str(log_dir),
            "WAKIR_PILOT_HOST": "test-pilot",
            "WAKIR_PILOT_USER": "root",
        }
    )
    if extra_env:
        env.update(extra_env)

    result = subprocess.run(
        ["bash", str(DRILL_SCRIPT), *args],
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
    rc, out, err, _ = _run_drill(["--help"], tmp_path=tmp_path)
    assert rc == 0, f"expected exit 0 on --help, got {rc}; stderr={err}"
    assert "live-vm-cutover-drill.sh" in out
    assert "--welle N" in out
    assert "--action ACTION" in out
    assert "--full-marathon" in out


def test_missing_action_returns_precondition(tmp_path: Path) -> None:
    rc, _, err, _ = _run_drill(["--welle", "1"], tmp_path=tmp_path)
    assert rc == 3, f"expected precond exit 3 when --action omitted; got {rc}"
    assert "either --full-marathon or" in err or "either --full-marathon or" in err.lower()


def test_invalid_welle_returns_precondition(tmp_path: Path) -> None:
    rc, _, err, _ = _run_drill(
        ["--welle", "99", "--action", "cutover", "--dry-run"],
        tmp_path=tmp_path,
    )
    assert rc == 3
    assert "must be in 1..7" in err


def test_invalid_action_returns_precondition(tmp_path: Path) -> None:
    rc, _, err, _ = _run_drill(
        ["--welle", "1", "--action", "explode", "--dry-run"],
        tmp_path=tmp_path,
    )
    assert rc == 3
    assert "--action must be" in err


def test_full_marathon_excludes_welle_arg(tmp_path: Path) -> None:
    rc, _, err, _ = _run_drill(
        ["--full-marathon", "--welle", "1", "--action", "cutover", "--dry-run"],
        tmp_path=tmp_path,
    )
    assert rc == 3
    assert "--full-marathon excludes" in err


def test_dry_run_welle_1_pre_emits_snapshot_steps(tmp_path: Path) -> None:
    rc, out, _err, _log = _run_drill(
        [
            "--welle",
            "1",
            "--action",
            "pre",
            "--dry-run",
            "--skip-gate",
        ],
        tmp_path=tmp_path,
    )
    assert rc == 0, f"expected green pre; got {rc}\n{out}"
    assert "pre: welle=1 component=v907_verify" in out
    # Pre-snapshot must capture service-status, journal-pre, and overlay listing.
    assert "service-status.txt" in out
    assert "journal-pre.txt" in out
    assert "overlay-listing.txt" in out
    assert "manifest.txt" in out


def test_dry_run_welle_1_cutover_renders_single_env_overlay(tmp_path: Path) -> None:
    rc, out, _err, _log = _run_drill(
        [
            "--welle",
            "1",
            "--action",
            "cutover",
            "--dry-run",
            "--skip-gate",
        ],
        tmp_path=tmp_path,
    )
    assert rc == 0
    # Welle-1 uses exactly one Environment= line.
    env_lines = re.findall(r'Environment="WAKIR_V907_VERIFY_BACKEND=rust"', out)
    assert len(env_lines) == 1, f"expected exactly one env-line; got {len(env_lines)}\n{out}"
    assert "welle-1-v907-verify-rust.conf" in out
    assert "systemctl daemon-reload" in out
    assert "systemctl restart wakir-persona-engine.service" in out
    assert "BackendDecision" in out and "v907_verify" in out and "backend=rust" in out


def test_dry_run_welle_3_cutover_renders_two_env_lines(tmp_path: Path) -> None:
    # Welle-3 has two env vars: WAKIR_BRIDGE_AUDIT_WRITER_BACKEND
    # + WAKIR_ANCHOR_EMITTER_BACKEND.  The overlay must contain both.
    rc, out, _err, _log = _run_drill(
        [
            "--welle",
            "3",
            "--action",
            "cutover",
            "--dry-run",
            "--skip-gate",
        ],
        tmp_path=tmp_path,
    )
    assert rc == 0
    assert 'Environment="WAKIR_BRIDGE_AUDIT_WRITER_BACKEND=rust"' in out
    assert 'Environment="WAKIR_ANCHOR_EMITTER_BACKEND=rust"' in out
    assert "welle-3-bridge-audit-writer-rust.conf" in out


def test_dry_run_welle_4_uses_rust_inmemory_value(tmp_path: Path) -> None:
    # Welle-4 is the only Welle that uses a non-"rust" env value.
    rc, out, _err, _log = _run_drill(
        [
            "--welle",
            "4",
            "--action",
            "cutover",
            "--dry-run",
            "--skip-gate",
        ],
        tmp_path=tmp_path,
    )
    assert rc == 0
    assert 'Environment="WAKIR_STATE_BACKING_BACKEND=rust_inmemory"' in out
    assert "welle-4-state-backing-rust.conf" in out
    # Boot-audit must look for backend=rust_inmemory in BackendDecision stream.
    assert "backend=rust_inmemory" in out


def test_dry_run_welle_1_rollback_emits_removal_and_python_verify(
    tmp_path: Path,
) -> None:
    rc, out, _err, _log = _run_drill(
        [
            "--welle",
            "1",
            "--action",
            "rollback",
            "--dry-run",
        ],
        tmp_path=tmp_path,
    )
    assert rc == 0
    assert "rm -f" in out and "welle-1-v907-verify-rust.conf" in out
    assert "systemctl daemon-reload" in out
    assert "systemctl restart wakir-persona-engine.service" in out
    # After rollback the wait-loop must look for backend=python.
    assert "backend=python" in out
    assert "rollback verified: backend=python" in out


def test_dry_run_post_succeeds_when_backend_decisions_present(tmp_path: Path) -> None:
    rc, out, _err, _log = _run_drill(
        [
            "--welle",
            "2",
            "--action",
            "post",
            "--dry-run",
            "--skip-gate",
        ],
        tmp_path=tmp_path,
        extra_env={"WAKIR_FAKE_BOOT_HITS": "10"},
    )
    assert rc == 0
    assert "post: welle=2 component=svid_workload_identity" in out
    assert "post-verify green for welle=2" in out


def test_full_marathon_dry_run_walks_seven_wellen_in_order(tmp_path: Path) -> None:
    rc, out, _err, _log = _run_drill(
        ["--full-marathon", "--dry-run"],
        tmp_path=tmp_path,
    )
    assert rc == 0, f"expected marathon green; got {rc}\n{out}"
    # Each Welle must announce itself in numeric order.
    for idx in range(1, 8):
        assert f"full-marathon: welle={idx}" in out, f"missing welle={idx} announce"
    # The marathon-log file must have been created in the per-test log-dir.
    marathon_log = next((tmp_path / "drill-logs").glob("marathon-*.log"), None)
    assert marathon_log is not None and marathon_log.is_file()
    # All seven sign-off markers must exist post-marathon.
    signoff_dir = tmp_path / "drill-logs" / "signoff"
    assert signoff_dir.is_dir()
    for idx in range(1, 8):
        marker = signoff_dir / f"welle-{idx}.signoff"
        assert marker.is_file(), f"missing sign-off marker for welle={idx}"
        body = marker.read_text()
        assert "verdict=green" in body


def test_sequence_gate_blocks_welle_2_without_welle_1_signoff(tmp_path: Path) -> None:
    # No sign-off marker exists yet → welle-2 cutover must hit gate.
    rc, _out, err, _log = _run_drill(
        ["--welle", "2", "--action", "cutover", "--dry-run"],
        tmp_path=tmp_path,
    )
    assert rc == 3, f"expected gate-block exit 3; got {rc}; err={err}"
    assert "missing sign-off for parent welle(s)" in err


def test_sequence_gate_passes_when_parent_signoff_present(tmp_path: Path) -> None:
    # Pre-seed welle-1 sign-off, then run welle-2 cutover.  Gate must pass.
    signoff_dir = tmp_path / "drill-logs" / "signoff"
    signoff_dir.mkdir(parents=True, exist_ok=True)
    (signoff_dir / "welle-1.signoff").write_text(
        "welle=1\nverdict=green\ntimestamp=2026-05-18T12:00:00Z\n"
    )
    rc, out, err, _log = _run_drill(
        ["--welle", "2", "--action", "cutover", "--dry-run"],
        tmp_path=tmp_path,
    )
    assert rc == 0, f"expected green; got {rc}; err={err}\n{out}"
    assert "welle-2-svid-workload-identity-rust.conf" in out


def test_ssh_key_missing_returns_precondition_without_dry_run(tmp_path: Path) -> None:
    # In live (non-dry-run) mode the SSH-key existence is a hard
    # pre-condition.  Verify exit 3 + clear error.
    rc, _out, err, _log = _run_drill(
        ["--welle", "1", "--action", "pre", "--skip-gate"],
        tmp_path=tmp_path,
        ssh_key_present=False,
    )
    assert rc == 3
    assert "SSH key not readable" in err
