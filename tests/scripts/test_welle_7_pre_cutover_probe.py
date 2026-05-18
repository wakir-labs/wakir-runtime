# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/phase-3c/welle-7-pre-cutover-probe.sh``.

Welle-7 is the LAST pre-cutover-probe of Phase-3 (recovery_workflow,
ADR-0066 §Doppel-Welle KW-27 / Phase-3-Ende).  These tests exercise
the six axis verdicts + the IIA-1130 Pre-Auditor-Decision pre-
condition gate.

Sandbox boundary identical to the welle-6 sibling: ``ssh``,
``date`` and the ssh-key are all stubbed via env-vars; no real
SSH connection opens.

Scope (10 tests, exceeds Auftrag-Tag-42 minimum of 8):

  1. test_help_flag_prints_usage_and_exits_zero
  2. test_help_mentions_phase_3_marathon_schluss_markierung
  3. test_missing_pre_auditor_decision_returns_precondition
  4. test_invalid_json_pre_auditor_decision_returns_precondition
  5. test_missing_ssh_key_returns_precondition
  6. test_dry_run_with_pre_auditor_present_aggregates_caution_without_hash
  7. test_dry_run_with_pre_auditor_and_expected_hash_aggregates_green
  8. test_ssh_unreachable_emits_not_exec
  9. test_axis_2_state_backing_missing_renders_red
  10. test_axis_3_cross_modul_drift_welle_6_env_rust_renders_red
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path
from typing import List, Optional, Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROBE_SCRIPT = REPO_ROOT / "scripts" / "phase-3c" / "welle-7-pre-cutover-probe.sh"


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


def _write_pre_auditor_decision(
    tmp_path: Path,
    *,
    payload: Optional[str] = None,
) -> Path:
    """Create the IIA-1130 Pre-Auditor-Decision file."""
    path = tmp_path / "welle-7-pre-auditor-decision.json"
    if payload is None:
        payload = json.dumps(
            {
                "verdict": "PROCEED",
                "auditor": "Henrik Voss",
                "iia_anchor": "IIA-1130",
                "date_utc": "2026-05-18T11:00:00Z",
                "welle": 7,
                "component": "recovery_workflow",
            },
            indent=2,
        )
    path.write_text(payload)
    return path


def _run_probe(
    args: List[str],
    *,
    tmp_path: Path,
    fake_ssh_payload: str = "ok\n",
    fake_ssh_exit: int = 0,
    fake_ssh_per_axis: Optional[dict] = None,
    ssh_key_present: bool = True,
    pre_auditor_present: bool = True,
    pre_auditor_payload: Optional[str] = None,
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

    if pre_auditor_present:
        pa_path = _write_pre_auditor_decision(
            tmp_path, payload=pre_auditor_payload
        )
    else:
        pa_path = tmp_path / "welle-7-pre-auditor-decision.json"  # not created

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
            "WAKIR_PROBE_PRE_AUDITOR_PATH": str(pa_path),
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


def _axis_payloads_all_green() -> dict:
    """Per-axis SSH-payloads where each axis returns GREEN.

    Order matters (bash case picks first match).  Each needle must
    occur in exactly one axis's remote cmd-string.
    """
    return {
        # AXIS-1 cmd: `persona-engine-cli recovery-drill-snapshot ...`
        "recovery-drill-snapshot": (
            '{"phases":["R1","R2","R3","R4"],"timestamp":"2026-05-18"}\n'
            'R1->R2->R3->R4 ok\n'
        ),
        # AXIS-2 cmd: `... grep -E "state_backing|StateBackingRead" ...`
        "StateBackingRead": (
            "Environment=WAKIR_STATE_BACKING_BACKEND=rust\n"
            "---AUDIT-STATE-BACKING-TAIL---\n"
            "StateBackingRead backend=rust state_backing op=load\n"
        ),
        # AXIS-3 cmd: `... OVERLAY-LIST ...`
        "OVERLAY-LIST": (
            "Environment=WAKIR_STATE_BACKING_BACKEND=rust\n"
            "---OVERLAY-LIST---\n"
        ),
        # AXIS-4 cmd: `... BackendDecision ... WELLE-7-COMPONENT-PRESENCE ...`
        "WELLE-7-COMPONENT-PRESENCE": (
            "15\n"
            "---WELLE-7-COMPONENT-PRESENCE---\n"
            "May 18 12:00 host persona-engine: BackendDecision component=recovery_workflow backend=python\n"
        ),
        # AXIS-5 cmd: `persona-engine-cli recovery-outcome-hash ...`
        "recovery-outcome-hash": '{"hash":"abc123"}\n',
        # AXIS-6 cmd: `... systemctl is-enabled persona-engine ...`
        "is-enabled persona-engine": (
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
    assert "welle-7-pre-cutover-probe" in out or "Pre-Cutover-Sanity-Probe" in out
    assert "--dry-run" in out
    assert "recovery_workflow" in out
    assert "--pre-auditor-path" in out
    assert "green" in out and "block" in out


def test_help_mentions_phase_3_marathon_schluss_markierung(tmp_path: Path) -> None:
    # §0 of the probe's header explicitly marks this as the LAST
    # pre-cutover-probe of Phase-3.  The help-text must surface this
    # so an operator running --help understands the gate's role.
    rc, out, _err, _ = _run_probe(["--help"], tmp_path=tmp_path)
    assert rc == 0
    assert "Last" in out or "Phase-3" in out
    assert "Phase-3-COMPLETE-Marker" in out or "phase-3" in out.lower()


def test_missing_pre_auditor_decision_returns_precondition(tmp_path: Path) -> None:
    rc, out, err, _ = _run_probe(
        ["--dry-run", "--quiet"],
        tmp_path=tmp_path,
        pre_auditor_present=False,
    )
    assert rc == 3, f"expected precond exit 3 when pre-auditor missing; got {rc}; err={err}"
    assert "PROBE-VERDICT=PRECOND-FAIL" in out
    assert "pre-auditor-decision-MISSING" in out


def test_invalid_json_pre_auditor_decision_returns_precondition(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--dry-run", "--quiet"],
        tmp_path=tmp_path,
        pre_auditor_payload="this is { not [ valid json",
    )
    # Python3 is typically present in CI, so JSON-parse should fail.
    # If python3 is absent the script falls back to non-empty check
    # and this test would xpass — but in our CI environment python3
    # is always present.
    assert rc == 3, f"expected precond exit 3 on invalid json; got {rc}; out={out}"
    assert "PROBE-VERDICT=PRECOND-FAIL" in out
    assert "INVALID-JSON" in out


def test_missing_ssh_key_returns_precondition(tmp_path: Path) -> None:
    rc, _out, err, _ = _run_probe(
        [],
        tmp_path=tmp_path,
        ssh_key_present=False,
    )
    assert rc == 3, f"expected precond exit 3 when ssh-key missing; got {rc}; err={err}"
    assert "SSH key not readable" in err


def test_dry_run_with_pre_auditor_present_aggregates_caution_without_hash(tmp_path: Path) -> None:
    # In --dry-run we never reach the per-axis remote calls; but
    # AXIS-5 cross-lang-parity early-returns YELLOW when no
    # --expected-hash is provided (the early-return is BEFORE the
    # dry-run check), so the aggregate is CAUTION.
    rc, out, _err, _ = _run_probe(
        ["--dry-run", "--quiet"],
        tmp_path=tmp_path,
    )
    assert rc == 1, f"expected caution exit 1; got {rc}; out={out}"
    assert "PROBE-VERDICT=CAUTION" in out
    assert "welle=7" in out
    assert "component=recovery_workflow" in out


def test_dry_run_with_pre_auditor_and_expected_hash_aggregates_green(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--dry-run", "--expected-hash", "deadbeef", "--quiet"],
        tmp_path=tmp_path,
    )
    assert rc == 0, f"expected green dry-run, got {rc}; out={out}"
    assert "PROBE-VERDICT=GREEN" in out


def test_ssh_unreachable_emits_not_exec(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "deadbeef", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_exit=255,
        fake_ssh_payload="",
    )
    assert rc == 4, f"expected not-exec exit 4 on ssh-failure; got {rc}; out={out}"
    assert "PROBE-VERDICT=NOT-EXEC" in out


def test_axis_2_state_backing_missing_renders_red(tmp_path: Path) -> None:
    payloads = _axis_payloads_all_green()
    # Strip the WAKIR_STATE_BACKING_BACKEND=rust pin from the
    # state-backing-tail payload => AXIS-2 RED => BLOCK.
    payloads["StateBackingRead"] = (
        "Environment=\n---AUDIT-STATE-BACKING-TAIL---\n"
        # No StateBackingRead entries; env absent.
    )
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "abc123", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 2, f"expected block (state-backing-missing), got {rc}; out={out}"
    assert "PROBE-VERDICT=BLOCK" in out


def test_axis_3_cross_modul_drift_welle_6_env_rust_renders_red(tmp_path: Path) -> None:
    payloads = _axis_payloads_all_green()
    # Welle-6 env-var leaked to rust during Welle-7 pre-state =>
    # AXIS-3 RED (symmetric to Welle-6 AXIS-4).
    payloads["OVERLAY-LIST"] = (
        "Environment=WAKIR_STATE_BACKING_BACKEND=rust "
        "WAKIR_SUBSCRIBE_LOOP_BACKEND=rust\n"
        "---OVERLAY-LIST---\n"
    )
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "abc123", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 2, f"expected block (cross-modul-drift to welle-6), got {rc}; out={out}"
    assert "PROBE-VERDICT=BLOCK" in out
