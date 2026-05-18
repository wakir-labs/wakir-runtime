# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for
``scripts/phase-3c/live-vm-federation-2-cluster-cutover-stress.sh``.

The drill orchestrates the Phase-3c 2-Cluster Federation
Cutover-Stress sequence against ``wakir-pilot`` + ``wakir-orbit``
(ADR-0066 production-setup federation-topology).  These tests run
hermetically: every remote call is short-circuited via
``--sandbox-stub-mode`` so no real SSH connection is opened.

Scope (16 tests, exceeds Auftrag-Tag-44 minimum of 12):

  1.  test_help_flag_prints_usage_and_exits_zero
  2.  test_missing_welle_returns_precondition
  3.  test_invalid_welle_returns_precondition
  4.  test_invalid_action_returns_precondition
  5.  test_full_marathon_excludes_welle_arg
  6.  test_happy_path_welle_1_renders_green_verdict
  7.  test_phase_a_reach_failure_returns_not_executed
  8.  test_phase_a_federation_disabled_returns_block
  9.  test_phase_a_non_default_backend_returns_caution
 10.  test_phase_b_boot_audit_below_min_returns_caution
 11.  test_phase_b_boot_audit_zero_hits_returns_block
 12.  test_phase_c_drift_detected_returns_block
 13.  test_phase_c_zero_python_hits_returns_caution
 14.  test_phase_d_trust_refresh_failure_returns_block
 15.  test_dry_run_does_not_consult_stub_vars
 16.  test_single_phase_drift_check_runs_only_phase_c
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path
from typing import Dict, Optional, Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = (
    REPO_ROOT
    / "scripts"
    / "phase-3c"
    / "live-vm-federation-2-cluster-cutover-stress.sh"
)


# ---------------------------------------------------------------------------
# Stub-env helpers.
# ---------------------------------------------------------------------------


def _green_path_env(tmp_path: Path) -> Dict[str, str]:
    """Stub-env that produces a GREEN verdict for Welle-1."""
    env = os.environ.copy()
    env.update(
        {
            # Phase A — both sides reachable, federation-on, python-default.
            "WAKIR_STUB_PILOT_REACH": "PILOT_REACH_OK",
            "WAKIR_STUB_ORBIT_REACH": "ORBIT_REACH_OK",
            "WAKIR_STUB_PILOT_FEDERATION_MODE": "enabled",
            "WAKIR_STUB_ORBIT_FEDERATION_MODE": "enabled",
            "WAKIR_STUB_PILOT_BACKEND_DEFAULT": "BACKEND=python",
            "WAKIR_STUB_ORBIT_BACKEND_DEFAULT": "BACKEND=python",
            # Phase B — overlay install + restart + boot-audit hits at min.
            "WAKIR_STUB_PILOT_INSTALL_OVERLAY_DIR": "ok",
            "WAKIR_STUB_PILOT_WRITE_OVERLAY": "ok",
            "WAKIR_STUB_PILOT_DAEMON_RELOAD": "ok",
            "WAKIR_STUB_PILOT_RESTART_SERVICE": "ok",
            "WAKIR_STUB_PILOT_BOOT_AUDIT": "5",
            # Phase C — orbit emits python; no drift.
            "WAKIR_STUB_ORBIT_DRIFT_PYTHON": "3",
            "WAKIR_STUB_ORBIT_DRIFT_OTHER": "0",
            # Phase D — trust-refresh ok + 1 partner bundle on each side.
            "WAKIR_STUB_PILOT_TRUST_REFRESH": "ok",
            "WAKIR_STUB_ORBIT_TRUST_REFRESH": "ok",
            "WAKIR_STUB_PILOT_TRUST_OBSERVE": "1",
            "WAKIR_STUB_ORBIT_TRUST_OBSERVE": "1",
            # Isolate log dir into the per-test tmp_path.
            "WAKIR_STRESS_LOG_DIR": str(tmp_path / "stress-log"),
        }
    )
    return env


def _run(
    env: Dict[str, str],
    *args: str,
    capture: bool = True,
) -> Tuple[int, str, str]:
    """Invoke the drill and return ``(rc, stdout, stderr)``."""
    cmd = ["bash", str(SCRIPT), *args]
    proc = subprocess.run(
        cmd,
        env=env,
        capture_output=capture,
        text=True,
        timeout=20,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_help_flag_prints_usage_and_exits_zero(tmp_path: Path) -> None:
    env = os.environ.copy()
    rc, stdout, stderr = _run(env, "--help")
    assert rc == 0, f"--help should exit 0; got {rc}: {stderr}"
    combined = stdout + stderr
    assert "Phase-3c 2-Cluster Federation Cutover-Stress-Drill" in combined
    # All four phase actions documented.
    assert "pre-stress-setup" in combined
    assert "drift-check" in combined
    assert "trust-stress" in combined


def test_missing_welle_returns_precondition(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["WAKIR_STRESS_LOG_DIR"] = str(tmp_path / "stress-log")
    rc, _, stderr = _run(env, "--sandbox-stub-mode")
    assert rc == 3, f"missing --welle should exit 3; got {rc}: {stderr}"
    assert "either --full-marathon or --welle required" in stderr


def test_invalid_welle_returns_precondition(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["WAKIR_STRESS_LOG_DIR"] = str(tmp_path / "stress-log")
    rc, _, stderr = _run(env, "--welle", "9", "--sandbox-stub-mode")
    assert rc == 3, f"--welle 9 should exit 3; got {rc}: {stderr}"
    assert "must be 1..7" in stderr


def test_invalid_action_returns_precondition(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["WAKIR_STRESS_LOG_DIR"] = str(tmp_path / "stress-log")
    rc, _, stderr = _run(
        env,
        "--welle",
        "1",
        "--action",
        "nonsense",
        "--sandbox-stub-mode",
    )
    assert rc == 3, f"unknown action should exit 3; got {rc}: {stderr}"
    assert "--action must be" in stderr


def test_full_marathon_excludes_welle_arg(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["WAKIR_STRESS_LOG_DIR"] = str(tmp_path / "stress-log")
    rc, _, stderr = _run(
        env,
        "--full-marathon",
        "--welle",
        "1",
        "--sandbox-stub-mode",
    )
    assert rc == 3
    assert "--full-marathon excludes --welle" in stderr


def test_happy_path_welle_1_renders_green_verdict(tmp_path: Path) -> None:
    env = _green_path_env(tmp_path)
    rc, _, stderr = _run(
        env,
        "--welle",
        "1",
        "--sandbox-stub-mode",
    )
    assert rc == 0, f"happy-path should exit 0; got {rc}: {stderr}"
    # All four phase-verdicts present.
    assert "phase A green" in stderr
    assert "phase B green" in stderr
    assert "phase C green" in stderr
    assert "phase D green" in stderr
    assert "STRESS-VERDICT=GREEN" in stderr
    # Per-phase rc summary lists 0/0/0/0.
    assert "(A=0 B=0 C=0 D=0)" in stderr


def test_phase_a_reach_failure_returns_not_executed(tmp_path: Path) -> None:
    env = _green_path_env(tmp_path)
    # Empty reach payloads from both sides — phase A must short-circuit
    # to PROBE-NOT-EXECUTED with exit-code 4.
    env["WAKIR_STUB_PILOT_REACH"] = ""
    env["WAKIR_STUB_ORBIT_REACH"] = ""
    rc, _, stderr = _run(
        env,
        "--welle",
        "1",
        "--sandbox-stub-mode",
    )
    assert rc == 4, f"unreachable should exit 4; got {rc}: {stderr}"
    assert "VM unreachable" in stderr
    assert "STRESS-VERDICT=PROBE-NOT-EXECUTED" in stderr


def test_phase_a_federation_disabled_returns_block(tmp_path: Path) -> None:
    env = _green_path_env(tmp_path)
    # Orbit reports federation disabled — phase A must hard-block.
    env["WAKIR_STUB_ORBIT_FEDERATION_MODE"] = "disabled"
    rc, _, stderr = _run(
        env,
        "--welle",
        "1",
        "--sandbox-stub-mode",
    )
    assert rc == 2, f"federation-disabled should exit 2; got {rc}: {stderr}"
    assert "federation not enabled on both sides" in stderr


def test_phase_a_non_default_backend_returns_caution(tmp_path: Path) -> None:
    env = _green_path_env(tmp_path)
    # Pilot already on rust — phase A surfaces this as a CAUTION (yellow,
    # exit 1) so an Operator-Hand-Decision is required before stressing.
    env["WAKIR_STUB_PILOT_BACKEND_DEFAULT"] = "BACKEND=rust"
    rc, _, stderr = _run(
        env,
        "--welle",
        "1",
        "--action",
        "pre-stress-setup",
        "--sandbox-stub-mode",
    )
    assert rc == 1, f"non-default backend should exit 1; got {rc}: {stderr}"
    assert "pilot not in default backend" in stderr


def test_phase_b_boot_audit_below_min_returns_caution(tmp_path: Path) -> None:
    env = _green_path_env(tmp_path)
    env["WAKIR_STUB_PILOT_BOOT_AUDIT"] = "2"  # below default min=5
    rc, _, stderr = _run(
        env,
        "--welle",
        "1",
        "--action",
        "stress-only",
        "--sandbox-stub-mode",
    )
    assert rc == 1, f"hits below min should exit 1; got {rc}: {stderr}"
    assert "phase B yellow" in stderr
    assert "below min" in stderr


def test_phase_b_boot_audit_zero_hits_returns_block(tmp_path: Path) -> None:
    env = _green_path_env(tmp_path)
    env["WAKIR_STUB_PILOT_BOOT_AUDIT"] = "0"
    rc, _, stderr = _run(
        env,
        "--welle",
        "1",
        "--action",
        "stress-only",
        "--sandbox-stub-mode",
    )
    assert rc == 2, f"zero hits should exit 2; got {rc}: {stderr}"
    assert "phase B red" in stderr


def test_phase_c_drift_detected_returns_block(tmp_path: Path) -> None:
    env = _green_path_env(tmp_path)
    # Orbit observes rust-backend records — federation isolation broken.
    env["WAKIR_STUB_ORBIT_DRIFT_OTHER"] = "4"
    rc, _, stderr = _run(
        env,
        "--welle",
        "1",
        "--action",
        "drift-check",
        "--sandbox-stub-mode",
    )
    assert rc == 2, f"drift should exit 2; got {rc}: {stderr}"
    assert "federation isolation BROKEN" in stderr


def test_phase_c_zero_python_hits_returns_caution(tmp_path: Path) -> None:
    env = _green_path_env(tmp_path)
    env["WAKIR_STUB_ORBIT_DRIFT_PYTHON"] = "0"
    env["WAKIR_STUB_ORBIT_DRIFT_OTHER"] = "0"
    rc, _, stderr = _run(
        env,
        "--welle",
        "1",
        "--action",
        "drift-check",
        "--sandbox-stub-mode",
    )
    assert rc == 1, f"quiet engine should exit 1; got {rc}: {stderr}"
    assert "phase C yellow" in stderr


def test_phase_d_trust_refresh_failure_returns_block(tmp_path: Path) -> None:
    env = _green_path_env(tmp_path)
    env["WAKIR_STUB_PILOT_TRUST_REFRESH"] = "REFRESH_FAIL"
    rc, _, stderr = _run(
        env,
        "--welle",
        "1",
        "--action",
        "trust-stress",
        "--sandbox-stub-mode",
    )
    assert rc == 2, f"trust-refresh-fail should exit 2; got {rc}: {stderr}"
    assert "bundle refresh failed" in stderr


def test_dry_run_does_not_consult_stub_vars(tmp_path: Path) -> None:
    """--dry-run is the live-infra-plan mode; it must not consume stub
    env-vars (those belong to --sandbox-stub-mode).  In dry-run the
    drill bypasses the SSH-key existence check (no real key required
    for planning) and every ``remote_exec`` emits a fixed
    ``DRY-RUN-STDOUT`` payload.  Phase A reach check treats that
    payload as non-empty (so reach "passes"), but the federation-mode
    check compares against the literal ``"enabled"`` token —
    ``DRY-RUN-STDOUT`` does NOT match, so phase A returns 2 (BLOCK).

    The substantive assertion: even though the green-path stub-vars
    are set in env, the dry-run does not silently green-light the
    drill.  The federation-mode discriminator stops the run.
    """
    env = _green_path_env(tmp_path)
    rc, stdout, stderr = _run(
        env,
        "--welle",
        "1",
        "--dry-run",
    )
    assert rc == 2, f"dry-run should exit 2 (federation-mode check); got {rc}: {stderr}"
    assert "federation not enabled on both sides" in stderr
    # Stub vars must not have been consumed: the DRY-RUN-STDOUT
    # payload is what the script actually saw for federation_mode.
    assert "DRY-RUN-STDOUT" in stderr
    # And the dry-run trace shows every SSH command that would have
    # been sent, so the operator gets a plan-only artefact.
    assert "DRY-RUN ssh" in stderr


def test_single_phase_drift_check_runs_only_phase_c(tmp_path: Path) -> None:
    """--action drift-check must skip phase A/B/D and only run C."""
    env = _green_path_env(tmp_path)
    rc, _, stderr = _run(
        env,
        "--welle",
        "1",
        "--action",
        "drift-check",
        "--sandbox-stub-mode",
    )
    assert rc == 0, f"single-phase drift-check happy-path should exit 0; got {rc}: {stderr}"
    assert "phase C green" in stderr
    # Phase A/B/D markers MUST be absent from the log.
    assert "phase A" not in stderr
    assert "phase B" not in stderr
    assert "phase D" not in stderr
