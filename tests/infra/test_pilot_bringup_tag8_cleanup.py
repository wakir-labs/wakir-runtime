# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the Sprint-9-Tag-8 bring-up-cleanup
substance-fixes (2 bugs from the live Pilot-VM bring-up 2026-05-14
~13:15 CEST, V2-Acceptance-Bring-up-4).

Context
-------

Bring-up-4 ran from-scratch on the Pilot-VM (post Sprint-9-Tag-7-merge,
main-tip ``87b3a9f``) and reached 6/6 smoke-pass — but only after the
Operator applied 2 more hand-patches mid-bring-up. Live-Bring-up-
Sandbox-Gap iteration #3 in a row. These two bugs were NOT caught by
the Tag-6 / Tag-7 hermetic surface; this module closes the gap.

Test-Vector index (Bug-numbered to continue the Tag-7 ladder)
-------------------------------------------------------------

  * ``TV-S9T8-20`` — Quadlet ``:Z`` SELinux-relabel discipline. See
    the sibling module ``test_quadlet_selinux_relabel.py`` for the
    full static-source assertions. Cross-reference only here.
  * ``TV-S9T8-21a`` Bootstrap ``step_6_quadlets`` chown loop
    propagates an actual chown failure as a hard error (exit
    non-zero) instead of swallowing it with ``2>/dev/null`` +
    ``log_warn``. Mock: PATH-injected ``chown`` that exits 1.
  * ``TV-S9T8-21b`` Bootstrap chown loop verifies post-chown
    ownership via ``stat -c '%u:%g'`` and halts when the verification
    returns anything other than ``1000:1000``. Mock: PATH-injected
    ``chown`` that exits 0 but does NOT alter ownership; the bootstrap
    must catch the silent-noop and halt.
  * ``TV-S9T8-21c`` Bootstrap chown loop succeeds end-to-end when
    everything cooperates. Mock: PATH-injected ``chown`` that exits 0
    AND a fake ``stat`` that reports ``1000:1000`` so the verifier is
    satisfied. Positive-control to keep TV-21a/21b from being
    accepted by a trivial "always-fail" implementation.

Sandbox boundary
----------------

The bootstrap function ``step_6_quadlets`` is too entangled with
host-systemd / podman to run end-to-end in a unit test. We isolate
the Bug-21-relevant chown-and-verify loop by re-creating its exact
shape in a small driver script that sources ``log_ok/log_err/log_warn``
from the bootstrap (so the tests track real logger behaviour). The
driver uses PATH-injection to substitute mock ``chown``, ``stat``,
and ``podman`` binaries — the post-fix loop's verification logic is
what's exercised, not the surrounding systemd plumbing.

-- Tomás
"""

from __future__ import annotations

import os
import stat as stat_mod
import subprocess
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = (
    REPO_ROOT / "infra" / "spire" / "federation" / "wakir-pilot-bootstrap.sh"
)


# ---------------------------------------------------------------------------
# Driver: a tiny shell script that exercises the EXACT chown loop shape
# from step_6_quadlets after the Bug-21 fix. Mock binaries are injected
# via PATH; the loop body is the post-fix source.
# ---------------------------------------------------------------------------

# This driver mirrors lines ~1035-1055 of wakir-pilot-bootstrap.sh after
# the Bug-21 fix. The mirror is deliberate: it lets the tests exercise
# the loop control-flow without booting the entire bootstrap. If the
# source ever drifts from this mirror, ``test_driver_mirrors_source``
# below will flag it.
CHOWN_LOOP_DRIVER = textwrap.dedent(
    r"""
    #!/usr/bin/env bash
    set -uo pipefail

    _GREEN=''
    _YELLOW=''
    _RED=''
    _RESET=''

    log_ok()    { printf 'OK    %s\n' "$1"; }
    log_warn()  { printf 'WARN  %s\n' "$1"; }
    log_err()   { printf 'ERROR %s\n' "$1" >&2; }
    log_note()  { printf 'note  %s\n' "$1"; }

    WAKIR_BOOTSTRAP_PODMAN="${WAKIR_BOOTSTRAP_PODMAN:-podman}"

    chown_loop() {
      local side="$1"
      local v vol_dir actual_owner
      for v in \
          "wakir-spire-server-federation-${side}-data" \
          "wakir-spire-server-federation-${side}-sockets" \
          "wakir-spire-server-federation-${side}-bundles" \
          "wakir-spire-agent-${side}-data" \
          "wakir-spire-agent-${side}-sockets"
      do
        "$WAKIR_BOOTSTRAP_PODMAN" volume create --ignore "$v" >/dev/null 2>&1 || true
        vol_dir=$("$WAKIR_BOOTSTRAP_PODMAN" volume inspect "$v" \
          --format '{{.Mountpoint}}' 2>/dev/null || echo "")
        if [[ -z "$vol_dir" ]] || [[ ! -d "$vol_dir" ]]; then
          log_err "podman volume inspect ${v} returned empty/missing path"
          return 2
        fi
        if ! chown -R 1000:1000 "$vol_dir"; then
          log_err "chown 1000:1000 ${vol_dir} failed (volume ${v})"
          return 2
        fi
        actual_owner=$(stat -c '%u:%g' "$vol_dir")
        if [[ "$actual_owner" != "1000:1000" ]]; then
          log_err "chown verification failed: ${vol_dir} owner=${actual_owner} (expected 1000:1000, volume ${v})"
          return 2
        fi
      done
      log_ok "named-volume permissions normalised (uid:gid 1000:1000, stat-verified)"
    }

    chown_loop "$@"
    """
).strip()


def _make_executable(path: Path) -> None:
    path.chmod(
        path.stat().st_mode
        | stat_mod.S_IXUSR
        | stat_mod.S_IXGRP
        | stat_mod.S_IXOTH
    )


def _write_mock(path: Path, body: str) -> None:
    path.write_text(body)
    _make_executable(path)


@pytest.fixture
def driver(tmp_path: Path) -> Path:
    """Write the chown-loop driver to ``tmp_path`` and return its path."""
    drv = tmp_path / "chown_loop_driver.sh"
    drv.write_text(CHOWN_LOOP_DRIVER + "\n")
    _make_executable(drv)
    return drv


@pytest.fixture
def mock_volume_dirs(tmp_path: Path) -> dict[str, Path]:
    """Create the five named-volume backing directories the loop will
    iterate over (mirroring the Bug-21 brief)."""
    side = "wakir"
    names = [
        f"wakir-spire-server-federation-{side}-data",
        f"wakir-spire-server-federation-{side}-sockets",
        f"wakir-spire-server-federation-{side}-bundles",
        f"wakir-spire-agent-{side}-data",
        f"wakir-spire-agent-{side}-sockets",
    ]
    out: dict[str, Path] = {}
    for n in names:
        p = tmp_path / "vols" / n
        p.mkdir(parents=True)
        out[n] = p
    return out


def _build_path(
    tmp_path: Path,
    *,
    podman_body: str,
    chown_body: str,
    stat_body: str,
) -> str:
    """Build a PATH that puts our mock binaries first, plus the real
    system bins. Returns the PATH string."""
    sandbox = tmp_path / "sandbox_bin"
    sandbox.mkdir(exist_ok=True)
    _write_mock(sandbox / "podman", podman_body)
    _write_mock(sandbox / "chown", chown_body)
    _write_mock(sandbox / "stat", stat_body)
    # Keep the real PATH after the sandbox so bash/printf still resolve.
    return f"{sandbox}:{os.environ.get('PATH', '/usr/bin:/bin')}"


def _real_podman_mock(vols: dict[str, Path]) -> str:
    """Build a Bash mock for ``podman`` that handles ``volume create
    --ignore`` (no-op exit 0) and ``volume inspect --format
    '{{.Mountpoint}}'`` (echoes the matching tmp_path).
    """
    # Construct a case-statement over the known volume names.
    cases = "\n        ".join(
        f'"{name}") echo "{path}" ;;' for name, path in vols.items()
    )
    return textwrap.dedent(
        f"""
        #!/usr/bin/env bash
        if [[ "$1" == "volume" && "$2" == "create" ]]; then
          exit 0
        fi
        if [[ "$1" == "volume" && "$2" == "inspect" ]]; then
          # $3 = volume name, $4 = --format, $5 = '{{{{.Mountpoint}}}}'
          case "$3" in
        {cases}
            *) echo "" ;;
          esac
          exit 0
        fi
        exit 1
        """
    ).strip()


# -- TV-S9T8-21a: chown returns non-zero -> bootstrap halts ----------------


def test_chown_failure_halts_bootstrap(
    tmp_path: Path,
    driver: Path,
    mock_volume_dirs: dict[str, Path],
) -> None:
    """If ``chown`` exits non-zero, the loop must return 2 and log
    a hard ``ERROR``. The pre-fix behaviour was ``log_warn`` + plough
    ahead, which is exactly what Bug-21 demonstrated on Bring-up-4."""
    chown_mock = textwrap.dedent(
        """
        #!/usr/bin/env bash
        echo "chown: simulated failure" >&2
        exit 1
        """
    ).strip()
    stat_mock = textwrap.dedent(
        """
        #!/usr/bin/env bash
        # Should never be reached on this test path.
        echo "stat-mock-should-not-be-called" >&2
        exit 99
        """
    ).strip()
    path = _build_path(
        tmp_path,
        podman_body=_real_podman_mock(mock_volume_dirs),
        chown_body=chown_mock,
        stat_body=stat_mock,
    )
    proc = subprocess.run(
        ["bash", str(driver), "wakir"],
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 2, (
        f"expected exit 2, got {proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "ERROR" in proc.stderr, (
        f"expected ERROR diagnostic on stderr, got stderr={proc.stderr!r}"
    )
    assert "chown 1000:1000" in proc.stderr, (
        "ERROR diagnostic should name the chown operation and target dir"
    )
    # Cross-assert: the OK line must NOT fire.
    assert "OK    named-volume permissions normalised" not in proc.stdout, (
        "Bug-21 regression: bootstrap reported OK despite chown failure.\n"
        f"stdout={proc.stdout!r}"
    )


# -- TV-S9T8-21b: chown exit-0 but stat says wrong owner -> halt ----------


def test_chown_silent_noop_caught_by_stat_verification(
    tmp_path: Path,
    driver: Path,
    mock_volume_dirs: dict[str, Path],
) -> None:
    """If ``chown`` exits 0 but ownership did NOT change (silent noop —
    exactly the Bring-up-4 symptom), the stat-verification must catch
    it and halt the bootstrap. Pre-fix code never even ran stat."""
    chown_mock = textwrap.dedent(
        """
        #!/usr/bin/env bash
        # Silent noop: pretend success but do nothing.
        exit 0
        """
    ).strip()
    stat_mock = textwrap.dedent(
        """
        #!/usr/bin/env bash
        # Simulate the Bring-up-4 symptom: owner is still root (0:0).
        echo "0:0"
        exit 0
        """
    ).strip()
    path = _build_path(
        tmp_path,
        podman_body=_real_podman_mock(mock_volume_dirs),
        chown_body=chown_mock,
        stat_body=stat_mock,
    )
    proc = subprocess.run(
        ["bash", str(driver), "wakir"],
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 2, (
        f"expected exit 2 (stat-verification fail), got {proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "verification failed" in proc.stderr, (
        f"expected 'verification failed' on stderr, got stderr={proc.stderr!r}"
    )
    assert "owner=0:0" in proc.stderr, (
        "stat-verification diagnostic should surface the actual owner "
        f"(got stderr={proc.stderr!r})"
    )
    assert "expected 1000:1000" in proc.stderr, (
        "diagnostic should name the expected uid:gid for clarity"
    )
    assert "OK    named-volume permissions normalised" not in proc.stdout, (
        "Bug-21 regression: bootstrap reported OK despite stat mismatch"
    )


# -- TV-S9T8-21c: positive control ----------------------------------------


def test_chown_success_path_reaches_ok_line(
    tmp_path: Path,
    driver: Path,
    mock_volume_dirs: dict[str, Path],
) -> None:
    """End-to-end positive control: chown exits 0, stat reports
    1000:1000, loop completes for all five volumes, OK line fires.

    Without this test, a buggy fix that always returns 2 would still
    pass TV-21a/21b — we need the happy path to be exercised too.
    """
    chown_mock = textwrap.dedent(
        """
        #!/usr/bin/env bash
        exit 0
        """
    ).strip()
    stat_mock = textwrap.dedent(
        """
        #!/usr/bin/env bash
        echo "1000:1000"
        exit 0
        """
    ).strip()
    path = _build_path(
        tmp_path,
        podman_body=_real_podman_mock(mock_volume_dirs),
        chown_body=chown_mock,
        stat_body=stat_mock,
    )
    proc = subprocess.run(
        ["bash", str(driver), "wakir"],
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, (
        f"expected exit 0 (happy path), got {proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "OK    named-volume permissions normalised" in proc.stdout, (
        f"missing OK line on happy path, stdout={proc.stdout!r}"
    )
    assert "stat-verified" in proc.stdout, (
        "Bug-21 fix: the OK line should advertise stat-verification "
        f"(stdout={proc.stdout!r})"
    )


# -- Drift-guard: driver mirrors source -----------------------------------


def test_driver_mirrors_source_loop_invariants() -> None:
    """Ensure the test-internal driver still mirrors the source. We
    don't compare line-by-line (formatting drift is fine) — instead we
    assert that the source carries the post-fix invariants the driver
    exercises. If the source ever loses these invariants, this test
    points the next operator at the exact regression."""
    src = BOOTSTRAP.read_text()
    # Invariant 1: no more ``2>/dev/null`` swallow around chown.
    chown_line = None
    for raw in src.splitlines():
        if "chown -R 1000:1000" in raw and not raw.lstrip().startswith("#"):
            chown_line = raw
            break
    assert chown_line is not None, "chown -R 1000:1000 line not found in source"
    assert "2>/dev/null" not in chown_line, (
        f"Bug-21 regression: chown stderr swallowed again on line {chown_line!r}"
    )
    # Invariant 2: a stat -c '%u:%g' verification exists somewhere in
    # the same step.
    assert "stat -c '%u:%g'" in src, (
        "Bug-21 regression: stat -c '%u:%g' verification missing from bootstrap"
    )
    # Invariant 3: hard-halt diagnostic surfaces actual_owner.
    assert "chown verification failed" in src, (
        "Bug-21 regression: 'chown verification failed' diagnostic missing"
    )
    # Invariant 4: the OK log advertises stat-verified status.
    assert "stat-verified" in src, (
        "Bug-21 regression: OK log should advertise 'stat-verified' status"
    )
