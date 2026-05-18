# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/phase-3c/welle-2-pre-cutover-probe.sh``.

The probe orchestrates the Pre-Cutover-Sanity workflow for Phase-3c
Welle-2 (``svid_workload_identity``, ADR-0065 §Option-B + ADR-0066
KW-24) against the wakir-pilot live VM (ADR-0058 SSH-Hand).  These
tests must run hermetically in CI: no real SSH connection, no real
systemctl, no real journalctl.  Achieved by:

  1. Replacing ``ssh`` with a fake under ``$WAKIR_SSH_BIN`` that
     records every invocation and emits caller-controlled stdout /
     exit-code, optionally keyed per-axis by needle substring.
  2. Pinning ``$WAKIR_DATE_BIN`` to a fake that emits a stable
     timestamp.
  3. Routing log + ssh-key paths into a per-test ``tmp_path``.

Scope (10 tests, exceeds Auftrag-Tag-42 minimum of 8):

  1. test_help_flag_prints_usage_and_exits_zero
  2. test_missing_ssh_key_returns_precondition_without_dry_run
  3. test_dry_run_aggregates_green_with_expected_hash
  4. test_dry_run_aggregates_caution_without_expected_hash
  5. test_ssh_unreachable_emits_not_exec_verdict
  6. test_all_axes_green_renders_green
  7. test_axis_1_invalid_spiffe_id_renders_caution
  8. test_axis_2_cert_expired_renders_block
  9. test_axis_2_cert_ttl_below_warn_renders_caution
 10. test_axis_5_overlay_present_renders_block
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
PROBE_SCRIPT = REPO_ROOT / "scripts" / "phase-3c" / "welle-2-pre-cutover-probe.sh"


# ---------------------------------------------------------------------------
# Fake-binary fixtures (mirror the Welle-1 helpers; kept self-contained so
# each Welle test module stays independent).
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
        "# Fake ssh for welle-2-pre-cutover-probe tests.",
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
# Per-axis payload builders.  Constants reflect a known-good Default-State.
# Tests override individual entries to flip axes.
# ---------------------------------------------------------------------------


# A cert window comfortably greater than the default warn threshold
# (3600 s).  not_before well in the past, not_after well in the future.
_GREEN_CERT_PAYLOAD = (
    '{"spiffe_id":"spiffe://wakir-pilot/persona-engine",'
    '"not_before":1747000000,"not_after":1900000000}\n'
    "\n"
    # Pinned date-fake emits "20260518T120000Z" / "2026-05-18T12:00:00Z"
    # for any "+%Y%m%dT*" / "+%Y-%m-%dT*" format.  Remote command in
    # AXIS-2 invokes the *remote* `date -u +%s` which uses the system
    # date binary.  We use a stable epoch close to mid-2026.
    "1747570800\n"
)


def _green_axis_payloads() -> dict:
    return {
        "persona-engine-cli svid-workload-identity-resolve": (
            '{"spiffe_id":"spiffe://wakir-pilot.local/persona-engine",'
            '"trust_domain":"wakir-pilot.local"}\n'
        ),
        "persona-engine-cli svid-workload-identity-cert": _GREEN_CERT_PAYLOAD,
        "grep -c BackendDecision": (
            "20\n---COMPONENT-ROW---\n"
            "May 18 12:00 host persona-engine: "
            "BackendDecision component=svid_workload_identity backend=python\n"
        ),
        "svid-workload-identity-hash": '{"hash":"svidhash123"}\n',
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
    assert "welle-2-pre-cutover-probe" in out or "Pre-Cutover-Sanity-Probe" in out
    assert "--dry-run" in out
    assert "--expected-hash" in out
    assert "--min-cert-ttl" in out
    assert "--trust-domain-regex" in out
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
        ["--dry-run", "--expected-hash", "svidhash123", "--quiet"],
        tmp_path=tmp_path,
    )
    assert rc == 0, f"expected green dry-run, got {rc}; out={out}"
    assert "PROBE-VERDICT=GREEN" in out
    assert "welle=2" in out
    assert "component=svid_workload_identity" in out


def test_dry_run_aggregates_caution_without_expected_hash(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--dry-run", "--quiet"],
        tmp_path=tmp_path,
    )
    assert rc == 1, f"expected caution exit 1; got {rc}; out={out}"
    assert "PROBE-VERDICT=CAUTION" in out


def test_ssh_unreachable_emits_not_exec_verdict(tmp_path: Path) -> None:
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "svidhash123", "--quiet"],
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
            "svidhash123",
            "--min-decisions",
            "5",
            "--min-cert-ttl",
            "600",
            "--warn-cert-ttl",
            "3600",
            "--quiet",
        ],
        tmp_path=tmp_path,
        fake_ssh_per_axis=_green_axis_payloads(),
    )
    assert rc == 0, f"expected green aggregate, got {rc}; out={out}"
    assert "PROBE-VERDICT=GREEN" in out


def test_axis_1_invalid_spiffe_id_renders_caution(tmp_path: Path) -> None:
    payloads = _green_axis_payloads()
    # Override AXIS-1: returns a parseable spiffe-URI that fails a
    # strict trust-domain regex (we tighten the regex via CLI).  Probe
    # treats regex-mismatch as YELLOW, not RED, because parse succeeded.
    payloads["persona-engine-cli svid-workload-identity-resolve"] = (
        '{"spiffe_id":"spiffe://attacker.example/persona-engine",'
        '"trust_domain":"attacker.example"}\n'
    )
    rc, out, _err, _ = _run_probe(
        [
            "--expected-hash",
            "svidhash123",
            "--min-decisions",
            "5",
            "--trust-domain-regex",
            r"^spiffe://wakir-pilot\\.local/.+$",
            "--quiet",
        ],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 1, f"expected caution (axis-1 yellow), got {rc}; out={out}"
    assert "PROBE-VERDICT=CAUTION" in out


def test_axis_2_cert_expired_renders_block(tmp_path: Path) -> None:
    payloads = _green_axis_payloads()
    # not_after in the past relative to the remote `date -u +%s` we
    # emit in payload tail (~ 1747570800).
    payloads["persona-engine-cli svid-workload-identity-cert"] = (
        '{"not_before":1700000000,"not_after":1700001000}\n'
        "\n"
        "1747570800\n"
    )
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "svidhash123", "--min-decisions", "5", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 2, f"expected block (cert expired), got {rc}; out={out}"
    assert "PROBE-VERDICT=BLOCK" in out


def test_axis_2_cert_ttl_below_warn_renders_caution(tmp_path: Path) -> None:
    payloads = _green_axis_payloads()
    # TTL = not_after - now = 1747572000 - 1747570800 = 1200 s.
    # That is >= --min-cert-ttl 600 but < --warn-cert-ttl 3600 → YELLOW.
    payloads["persona-engine-cli svid-workload-identity-cert"] = (
        '{"not_before":1747000000,"not_after":1747572000}\n'
        "\n"
        "1747570800\n"
    )
    rc, out, _err, _ = _run_probe(
        [
            "--expected-hash",
            "svidhash123",
            "--min-decisions",
            "5",
            "--min-cert-ttl",
            "600",
            "--warn-cert-ttl",
            "3600",
            "--quiet",
        ],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 1, f"expected caution (cert ttl below warn), got {rc}; out={out}"
    assert "PROBE-VERDICT=CAUTION" in out


def test_axis_5_overlay_present_renders_block(tmp_path: Path) -> None:
    payloads = _green_axis_payloads()
    # Inject the Welle-2 overlay filename into the AXIS-5 OVERLAY-LIST.
    payloads["/etc/systemd/system/persona-engine.service.d"] = (
        "drwxr-xr-x 2 root root /etc/systemd/system/persona-engine.service.d\n"
        "enabled\nsystemctl-OK\njournalctl-OK\n"
        "---OVERLAY-LIST---\n"
        "welle-2-svid-workload-identity-rust.conf\n"
    )
    rc, out, _err, _ = _run_probe(
        ["--expected-hash", "svidhash123", "--min-decisions", "5", "--quiet"],
        tmp_path=tmp_path,
        fake_ssh_per_axis=payloads,
    )
    assert rc == 2, f"expected block (overlay present), got {rc}; out={out}"
    assert "PROBE-VERDICT=BLOCK" in out
