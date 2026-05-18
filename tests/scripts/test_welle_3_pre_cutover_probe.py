# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/phase-3c/welle-3-pre-cutover-probe.sh``.

The probe orchestrates the Pre-Cutover-Sanity workflow for Phase-3c
Welle-3 (``bridge_audit_writer``, ADR-0066 KW-25) against the
wakir-pilot live VM (ADR-0058 SSH-Hand).  Welle-3 carries one
additional axis beyond the Welle-1/2 shape: AXIS-0
(Self-Reference-Trap-Pre-Check) which guards against the
Consistency-Oracle-Selbst-Cutover-Risiko Henrik flagged.

Hermetic strategy mirrors the Welle-1/2 test bed: fake ssh, fake date,
per-axis keyed payloads.

Scope (10 tests, exceeds Auftrag-Tag-42 minimum of 8):

  1. test_help_flag_prints_usage_and_exits_zero
  2. test_missing_ssh_key_returns_precondition_without_dry_run
  3. test_dry_run_aggregates_green_with_expected_hash
  4. test_dry_run_aggregates_caution_without_expected_hash
  5. test_ssh_unreachable_emits_not_exec_verdict
  6. test_all_axes_green_renders_green
  7. test_axis_0_self_reference_trap_drift_renders_block
  8. test_axis_0_self_reference_one_row_drift_renders_caution
  9. test_axis_1_no_head_advance_renders_block
 10. test_axis_2_independent_oracle_partial_match_renders_caution
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
PROBE_SCRIPT = REPO_ROOT / "scripts" / "phase-3c" / "welle-3-pre-cutover-probe.sh"


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
        "# Fake ssh for welle-3-pre-cutover-probe tests.",
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
# Per-axis payload builder.  Known-good Default-State.
# ---------------------------------------------------------------------------


def _green_axis_payloads() -> dict:
    return {
        # AXIS-0: in-engine head_seq matches independent-oracle tail seq.
        "persona-engine-cli bridge-audit-head": (
            '{"head_seq":420,"start_seq":400}\n'
            "---INDEPENDENT-ORACLE---\n"
            '{"seq":420,"ts":"2026-05-18T12:00:00Z","row":"audit-row"}\n'
        ),
        # AXIS-2: identical 5 seqs visible in both views.
        "persona-engine-cli audit-replay": (
            '{"seq":416}\n{"seq":417}\n{"seq":418}\n{"seq":419}\n{"seq":420}\n'
            "---ON-DISK-TAIL---\n"
            '{"seq":416}\n{"seq":417}\n{"seq":418}\n{"seq":419}\n{"seq":420}\n'
        ),
        # AXIS-3: 20 BackendDecisions, python row present.
        "grep -c BackendDecision": (
            "20\n---COMPONENT-ROW---\n"
            "May 18 12:00 host persona-engine: "
            "BackendDecision component=bridge_audit_writer backend=python\n"
        ),
        # AXIS-4: hash matches expected.
        "bridge-audit-writer-hash": '{"hash":"bridgehash321"}\n',
        # AXIS-5: rollback levers present, no overlay.
        "/etc/systemd/system/persona-engine.service.d": (
            "drwxr-xr-x 2 root root /etc/systemd/system/persona-engine.service.d\n"
            "enabled\nsystemctl-OK\njournalctl-OK\n"
            "---OVERLAY-LIST---\n"
        ),
    }


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_help_flag_prints_usage_and_exits_zero(tmp_path: Path) -> None:
    rc, out, err, _ = _run_probe(["--help"], tmp_path=tmp_path)
    assert rc == 0, f"expected exit 0 on --help, got {rc}; stderr={err}"
    assert "welle-3-pre-cutover-probe" in out or "Pre-Cutover-Sanity-Probe" in out
    assert "--dry-run" in out
    assert "--expected-hash" in out
    assert "--min-head-delta" in out
    assert "--replay-tail-n" in out
    assert "--audit-log-path" in out
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
        ["--dry-run", "--expected-hash", "bridgehash321", "--quiet"],
        tmp_path=tmp_path,
    )
    assert rc == 0, f"expected green dry-run, got {rc}; out={out}"
    assert "PROBE-VERDICT=GREEN" in out
    assert "welle=3" in out
    assert "component=bridge_audit_writer" in out


def test_dry_run_aggregates_caution_without_expected_hash(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--dry-run", "--quiet"],
        tmp_path=tmp_path,
    )
    assert rc == 1, f"expected caution exit 1; got {rc}; out={out}"
    assert "PROBE-VERDICT=CAUTION" in out


def test_ssh_unreachable_emits_not_exec_verdict(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "bridgehash321", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_exit=255,
        fake_ssh_payload="",
    )
    assert rc == 4, f"expected not-exec exit 4 on ssh-failure; got {rc}; out={out}"
    assert "PROBE-VERDICT=NOT-EXEC" in out


def test_all_axes_green_renders_green(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        [
            "--expected-hash",
            "bridgehash321",
            "--min-decisions",
            "5",
            "--min-head-delta",
            "5",
            "--replay-tail-n",
            "5",
            "--replay-match-min",
            "4",
            "--quiet",
        ],
        tmp_path=tmp_path,
        fake_ssh_per_axis=_green_axis_payloads(),
    )
    assert rc == 0, f"expected green aggregate, got {rc}; out={out}"
    assert "PROBE-VERDICT=GREEN" in out


def test_axis_0_self_reference_trap_drift_renders_block(tmp_path: Path) -> None:
    payloads = _green_axis_payloads()
    # Engine head_seq=420; independent oracle reports seq=400 (delta=20).
    # Self-reference-trap guard: engine cannot be ahead of (or behind)
    # the independent oracle by more than 1.  delta=20 -> RED.
    payloads["persona-engine-cli bridge-audit-head"] = (
        '{"head_seq":420,"start_seq":400}\n'
        "---INDEPENDENT-ORACLE---\n"
        '{"seq":400,"ts":"2026-05-18T12:00:00Z","row":"stale-row"}\n'
    )
    rc, out, _err, _ = _run_probe(
        [
            "--expected-hash",
            "bridgehash321",
            "--min-decisions",
            "5",
            "--min-head-delta",
            "5",
            "--quiet",
        ],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 2, f"expected block (self-ref drift), got {rc}; out={out}"
    assert "PROBE-VERDICT=BLOCK" in out


def test_axis_0_self_reference_one_row_drift_renders_caution(tmp_path: Path) -> None:
    payloads = _green_axis_payloads()
    # 1-row drift is the in-flight tolerance window: GREEN-adjacent
    # but not strictly identical -> YELLOW.
    payloads["persona-engine-cli bridge-audit-head"] = (
        '{"head_seq":421,"start_seq":400}\n'
        "---INDEPENDENT-ORACLE---\n"
        '{"seq":420,"ts":"2026-05-18T12:00:00Z","row":"audit-row"}\n'
    )
    rc, out, _err, _ = _run_probe(
        [
            "--expected-hash",
            "bridgehash321",
            "--min-decisions",
            "5",
            "--min-head-delta",
            "5",
            "--quiet",
        ],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 1, f"expected caution (1-row drift), got {rc}; out={out}"
    assert "PROBE-VERDICT=CAUTION" in out


def test_axis_1_no_head_advance_renders_block(tmp_path: Path) -> None:
    payloads = _green_axis_payloads()
    # head_seq == start_seq → delta=0 → RED.
    payloads["persona-engine-cli bridge-audit-head"] = (
        '{"head_seq":400,"start_seq":400}\n'
        "---INDEPENDENT-ORACLE---\n"
        '{"seq":400,"ts":"2026-05-18T12:00:00Z","row":"audit-row"}\n'
    )
    rc, out, _err, _ = _run_probe(
        [
            "--expected-hash",
            "bridgehash321",
            "--min-decisions",
            "5",
            "--min-head-delta",
            "5",
            "--quiet",
        ],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 2, f"expected block (no head advance), got {rc}; out={out}"
    assert "PROBE-VERDICT=BLOCK" in out


def test_axis_2_independent_oracle_partial_match_renders_caution(tmp_path: Path) -> None:
    payloads = _green_axis_payloads()
    # 4 of 5 seqs match → YELLOW per --replay-match-min 4 default.
    payloads["persona-engine-cli audit-replay"] = (
        '{"seq":416}\n{"seq":417}\n{"seq":418}\n{"seq":419}\n{"seq":420}\n'
        "---ON-DISK-TAIL---\n"
        '{"seq":416}\n{"seq":417}\n{"seq":418}\n{"seq":419}\n{"seq":999}\n'
    )
    rc, out, _err, _ = _run_probe(
        [
            "--expected-hash",
            "bridgehash321",
            "--min-decisions",
            "5",
            "--min-head-delta",
            "5",
            "--replay-tail-n",
            "5",
            "--replay-match-min",
            "4",
            "--quiet",
        ],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 1, f"expected caution (axis-2 partial match), got {rc}; out={out}"
    assert "PROBE-VERDICT=CAUTION" in out
