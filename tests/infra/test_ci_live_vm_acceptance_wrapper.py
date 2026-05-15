# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for Sprint-Tag-8 CI-Wrapper for Live-VM-Acceptance:
``scripts/ci-live-vm-acceptance-wrapper.sh``.

Anlass — AR-Direktive 2026-05-15 23:35 CEST. Tomás's Tag-6/9 on-VM
acceptance script is source-of-truth; this wrapper adds the
SSH-driven CI-callable half (operator-host pre-check, repo-pull,
federation-config reset, on-VM acceptance invocation, summary-JSON
emit).

Test-Vector index
-----------------

* ``TV-CW-01`` Bash syntax clean.
* ``TV-CW-02`` --help exits 0 and mentions the required flags.
* ``TV-CW-03`` Missing required flags → rc=3 (wrapper-internal error).
* ``TV-CW-04`` Invalid --federation-mode → rc=3.
* ``TV-CW-05`` Pre-check-only flag is parsed and shorts-circuits before
  the on-VM invocation.
* ``TV-CW-06`` Summary-JSON shape contains the eight expected fields
  (target, side, peer_side, peer_host, federation_mode, started_utc,
  finished_utc, acceptance_rc) — source-level assertion of the
  emit_summary jq call.
* ``TV-CW-07`` Source mentions the four required-tool-precheck (ssh,
  scp, jq) on the operator-host.
* ``TV-CW-08`` Federation-mode auto-detect logic is in the source
  (marker-file check + Quadlet-unit-presence fallback).

Sandbox boundary
----------------

Source inspection + argparse exercise only. The wrapper does
**not** run end-to-end against a live target in this test surface —
that exercise is the on-VM ``federation-live-vm-acceptance.sh`` lane.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER = _REPO_ROOT / "scripts" / "ci-live-vm-acceptance-wrapper.sh"


@pytest.fixture(scope="module")
def wrapper_source() -> str:
    assert _WRAPPER.is_file(), f"wrapper not found: {_WRAPPER}"
    return _WRAPPER.read_text(encoding="utf-8")


# TV-CW-01 -------------------------------------------------------------------


def test_wrapper_bash_syntax_clean() -> None:
    rc = subprocess.run(
        ["bash", "-n", str(_WRAPPER)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert rc.returncode == 0, f"bash -n failed: {rc.stderr!r}"


# TV-CW-02 -------------------------------------------------------------------


def test_wrapper_help_exits_zero() -> None:
    rc = subprocess.run(
        ["bash", str(_WRAPPER), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert rc.returncode == 0, f"--help must exit 0; got rc={rc.returncode}"
    # Help text must mention the required flags.
    for flag in ("--target", "--ssh-user", "--ssh-key"):
        assert flag in rc.stdout, f"--help must document {flag}"


# TV-CW-03 -------------------------------------------------------------------


def test_wrapper_missing_required_flags() -> None:
    rc = subprocess.run(
        ["bash", str(_WRAPPER)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert rc.returncode == 3, (
        f"Missing required flags must exit 3; got {rc.returncode}"
    )
    assert "missing required flags" in rc.stderr.lower(), rc.stderr


# TV-CW-04 -------------------------------------------------------------------


def test_wrapper_invalid_federation_mode() -> None:
    rc = subprocess.run(
        [
            "bash",
            str(_WRAPPER),
            "--target",
            "wakir-pilot.localdomain",
            "--ssh-user",
            "operator",
            "--ssh-key",
            "/tmp/nonexistent-key",
            "--federation-mode",
            "no-such-mode",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert rc.returncode == 3, (
        f"Invalid --federation-mode must exit 3; got {rc.returncode}"
    )


# TV-CW-05 -------------------------------------------------------------------


def test_wrapper_pre_check_only_in_source(wrapper_source: str) -> None:
    """--pre-check-only is parsed and short-circuits before phase 4."""
    assert "--pre-check-only" in wrapper_source
    assert "PRE_CHECK_ONLY=1" in wrapper_source
    # The short-circuit must happen BEFORE Phase 4 (acceptance invocation).
    pc_check = wrapper_source.find('PRE_CHECK_ONLY" -eq 1')
    phase_4 = wrapper_source.find("Phase 4: invoke")
    assert pc_check > 0 and phase_4 > 0
    assert pc_check < phase_4, (
        "Pre-check-only short-circuit must run BEFORE Phase 4"
    )


# TV-CW-06 -------------------------------------------------------------------


def test_summary_json_shape_in_source(wrapper_source: str) -> None:
    """The emit_summary jq invocation declares all expected fields."""
    for field in (
        "target",
        "side",
        "peer_side",
        "peer_host",
        "federation_mode",
        "started_utc",
        "finished_utc",
        "acceptance_rc",
        "acceptance_summary",
        "bug_regressions",
    ):
        assert f'"{field}"' in wrapper_source or f"{field}:" in wrapper_source, (
            f"Summary-JSON must include field '{field}'"
        )


# TV-CW-07 -------------------------------------------------------------------


def test_wrapper_tool_precheck_in_source(wrapper_source: str) -> None:
    """Operator-host tool precheck covers ssh, scp, jq."""
    # The tool-precheck loop enumerates the three required tools; the
    # bash idiom is ``for tool in ssh scp jq``.
    assert "for tool in ssh scp jq" in wrapper_source, (
        "Wrapper must declare the ssh/scp/jq tool-precheck loop"
    )


# TV-CW-08 -------------------------------------------------------------------


def test_federation_mode_auto_detect_in_source(wrapper_source: str) -> None:
    """auto-detect logic exists in the source: marker-file path
    (/etc/wakir/pilot-mode) + Quadlet-unit-presence fallback."""
    assert "/etc/wakir/pilot-mode" in wrapper_source, (
        "Federation-mode auto-detect must read /etc/wakir/pilot-mode marker"
    )
    assert "wakir-spire-server-federation-" in wrapper_source, (
        "Federation-mode auto-detect must inspect federation Quadlet units"
    )


def test_wrapper_does_not_hardcode_target_ip(wrapper_source: str) -> None:
    """The wrapper accepts --target explicitly. Verify the script does
    not unilaterally hardcode 192.168.* as a TARGET default — only as
    a --peer-host default."""
    lines = wrapper_source.splitlines()
    for i, line in enumerate(lines):
        # We forbid 192.168.* on lines that set TARGET= directly.
        if line.strip().startswith("TARGET=") and "192.168" in line:
            pytest.fail(
                f"TARGET= must not hardcode an IP; line {i + 1}: {line!r}"
            )


def test_wrapper_summary_json_contains_bug_regressions(
    wrapper_source: str,
) -> None:
    """The summary-JSON regression-list must enumerate the bugs the
    on-VM acceptance script regression-tests."""
    for bug in ("Bug-36", "Bug-37", "Bug-38"):
        assert f'"{bug}"' in wrapper_source, (
            f"Summary-JSON bug_regressions must include {bug}"
        )
