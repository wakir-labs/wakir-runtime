# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/phase-3c/welle-1-pre-cutover-probe.sh``.

The probe orchestrates the Pre-Cutover-Sanity workflow for Phase-3c
Welle-1 (v907_verify, ADR-0065) against the wakir-pilot live VM
(ADR-0058 SSH-Hand).  These tests must run hermetically in CI: no real
SSH connection, no real systemctl, no real journalctl.  Achieved by:

  1. Replacing ``ssh`` with a fake under ``$WAKIR_SSH_BIN`` that
     records every invocation and emits caller-controlled stdout /
     exit-code.
  2. Pinning ``$WAKIR_DATE_BIN`` to a fake that emits a stable
     timestamp.
  3. Routing log + ssh-key paths into a per-test ``tmp_path``.

Scope (8 tests, exceeds Auftrag-Tag-41 minimum of 6):

  1. test_help_flag_prints_usage_and_exits_zero
  2. test_missing_ssh_key_returns_precondition_without_dry_run
  3. test_dry_run_aggregates_green_with_expected_hash
  4. test_dry_run_aggregates_caution_without_expected_hash
  5. test_ssh_unreachable_emits_not_exec_verdict
  6. test_axis_2_observed_above_min_renders_green
  7. test_axis_2_observed_below_min_above_zero_renders_yellow
  8. test_axis_3_overlay_present_renders_red
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
PROBE_SCRIPT = REPO_ROOT / "scripts" / "phase-3c" / "welle-1-pre-cutover-probe.sh"


# ---------------------------------------------------------------------------
# Fake-binary fixtures.
# ---------------------------------------------------------------------------


def _write_fake_ssh(
    tmp_path: Path,
    *,
    exit_code: int = 0,
    stdout_payload: str = "ok\n",
) -> Path:
    """Create a fake ``ssh`` that logs every invocation and emits a canned stdout.

    The payload is written to a file and ``cat``'d to avoid quoting issues
    with multi-line / shell-meta-character payloads.
    """
    log_path = tmp_path / "fake-ssh.log"
    payload_path = tmp_path / "fake-ssh.payload"
    payload_path.write_text(stdout_payload)
    fake = tmp_path / "fake-ssh"
    lines = [
        "#!/usr/bin/env bash",
        "# Fake ssh for welle-1-pre-cutover-probe tests.",
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
    """Create a fake ``ssh`` that returns different stdout per axis-call.

    Axis is detected by scanning the remote-cmd (last argv) for a needle
    substring.  Each payload is stored in its own sidecar file to avoid
    nested-quote issues; the fake ``cat``s the matching payload file.
    """
    log_path = tmp_path / "fake-ssh.log"
    fake = tmp_path / "fake-ssh"

    payload_files = {}
    for idx, (needle, payload) in enumerate(axis_payloads.items()):
        pf = tmp_path / f"fake-ssh.payload.{idx}"
        pf.write_text(payload)
        payload_files[needle] = pf

    case_lines = []
    for needle, pf in payload_files.items():
        # Need a glob-pattern; bash case patterns must not have unquoted
        # spaces in the pattern itself.  We quote the pattern with double
        # quotes around just the needle text.
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
    """Fake ``date`` emitting deterministic UTC timestamps."""
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
    """Placeholder ssh-key file so the readability gate passes."""
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
    """Invoke the probe script with hermetic fakes.

    Returns ``(returncode, stdout, stderr, fake_ssh_log_path)``.
    """
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
        key = tmp_path / "missing-key"  # intentionally not created

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
    assert "welle-1-pre-cutover-probe" in out or "Pre-Cutover-Sanity-Probe" in out
    assert "--dry-run" in out
    assert "--expected-hash" in out
    # Help mentions exit-code triad explicitly.
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
    assert "welle=1" in out
    assert "component=v907_verify" in out


def test_dry_run_aggregates_caution_without_expected_hash(tmp_path: Path) -> None:
    # AXIS-4 yields YELLOW when no --expected-hash is provided; aggregate
    # must therefore promote to CAUTION even in dry-run.
    rc, out, _err, _ = _run_probe(
        ["--dry-run", "--quiet"],
        tmp_path=tmp_path,
    )
    assert rc == 1, f"expected caution exit 1; got {rc}; out={out}"
    assert "PROBE-VERDICT=CAUTION" in out


def test_ssh_unreachable_emits_not_exec_verdict(tmp_path: Path) -> None:
    # Fake ssh exits non-zero — probe must surface NOT-EXEC aggregate.
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "deadbeef", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_exit=255,
        fake_ssh_payload="",
    )
    assert rc == 4, f"expected not-exec exit 4 on ssh-failure; got {rc}; out={out}"
    assert "PROBE-VERDICT=NOT-EXEC" in out


def test_axis_2_observed_above_min_renders_green(tmp_path: Path) -> None:
    # All five axes must succeed for aggregate=GREEN.  We feed
    # plausible per-axis payloads via the keyed fake-ssh.
    rc, out, _err, _ = _run_probe(
        [
            "--expected-hash",
            "abc123",
            "--min-decisions",
            "5",
            "--quiet",
        ],
        tmp_path=tmp_path,
        fake_ssh_per_axis={
            "persona-engine-cli state-pack": "STATE-PACK-OK\nAUDIT-OK\n",
            "grep -c BackendDecision": "12\n",
            "systemctl show persona-engine -p Environment": (
                "Environment=\n---ENV-OVERLAY-LIST---\n---AUDIT-TAIL---\n"
                "May 18 12:00 host persona-engine: BackendDecision component=v907_verify backend=python\n"
            ),
            "v907-verify-hash": '{"hash":"abc123"}\n',
            "/etc/systemd/system/persona-engine.service.d": (
                "drwxr-xr-x 2 root root /etc/systemd/system/persona-engine.service.d\n"
                "enabled\nsystemctl-OK\njournalctl-OK\n"
            ),
        },
    )
    assert rc == 0, f"expected green aggregate, got {rc}; out={out}"
    assert "PROBE-VERDICT=GREEN" in out


def test_axis_2_observed_below_min_above_zero_renders_yellow(tmp_path: Path) -> None:
    # Override AXIS-2 to return 3 (below default min=11) — aggregate
    # must promote to CAUTION.
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "abc123", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis={
            "persona-engine-cli state-pack": "STATE-PACK-OK\n",
            "grep -c BackendDecision": "3\n",
            "systemctl show persona-engine -p Environment": (
                "Environment=\n---ENV-OVERLAY-LIST---\n---AUDIT-TAIL---\n"
                "May 18 12:00 host persona-engine: BackendDecision component=v907_verify backend=python\n"
            ),
            "v907-verify-hash": '{"hash":"abc123"}\n',
            "/etc/systemd/system/persona-engine.service.d": (
                "drwxr-xr-x ...\nenabled\nsystemctl-OK\njournalctl-OK\n"
            ),
        },
    )
    assert rc == 1, f"expected caution aggregate, got {rc}; out={out}"
    assert "PROBE-VERDICT=CAUTION" in out


def test_axis_3_overlay_present_renders_red(tmp_path: Path) -> None:
    # Overlay drop-in already present in Default-State —> AXIS-3 RED
    # —> aggregate=BLOCK.
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "abc123", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis={
            "persona-engine-cli state-pack": "STATE-PACK-OK\n",
            "grep -c BackendDecision": "20\n",
            "systemctl show persona-engine -p Environment": (
                "Environment=WAKIR_V907_VERIFY_BACKEND=rust\n"
                "---ENV-OVERLAY-LIST---\n"
                "welle-1-v907-verify-rust.conf\n"
                "---AUDIT-TAIL---\n"
                "May 18 12:00 host persona-engine: BackendDecision component=v907_verify backend=rust\n"
            ),
            "v907-verify-hash": '{"hash":"abc123"}\n',
            "/etc/systemd/system/persona-engine.service.d": (
                "drwxr-xr-x ...\nenabled\nsystemctl-OK\njournalctl-OK\n"
            ),
        },
    )
    assert rc == 2, f"expected block (overlay present), got {rc}; out={out}"
    assert "PROBE-VERDICT=BLOCK" in out
