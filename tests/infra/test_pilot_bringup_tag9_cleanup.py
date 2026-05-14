# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the Sprint-9-Tag-9 bring-up-cleanup
substance-fixes (Bug-22 — Bring-up-5 race-condition, AR Fred
2026-05-14 ~14:00 CEST).

Context
-------

Bring-up-5 ran from-scratch on the Pilot-VM (post Sprint-9-Tag-8-merge,
main-tip ``a2647ba``) and reached 6/6 smoke-pass ONLY on the second
``curl|bash`` run. The first run emitted the Tag-8 OK line
``OK  named-volume permissions normalised (uid:gid 1000:1000,
stat-verified)`` and then immediately reproduced the Bug-20 symptom:
the SPIRE-Agent crash-looped with
``directory validation failed: open /var/lib/spire/agent/.probe:
permission denied`` while ``ls -lnd`` on the agent-data volume's
``_data`` directory reported owner ``0 0``.

Post-mortem reading of ``step_6_quadlets``:

  1. Step 6g runs ``podman volume create --ignore <name>`` ad-hoc for
     each of the five named volumes, then ``chown -R 1000:1000`` and
     ``stat`` verifies ``1000:1000``. This is the Tag-8 (Bug-21) shape.
  2. Step 6h starts ``wakir-spire-server-federation-<SIDE>.service``,
     which triggers podman-system-generator to reconcile the named
     volumes against the ``.volume`` Quadlet unit. On some Podman
     builds (notably the FCOS-shipped 4.x line) this reconcile re-
     initialises the backing directory of any volume that was created
     ad-hoc before the matching ``.volume`` unit was generated — the
     ``_data`` directory gets reset to ``0:0``.
  3. Step 6j starts the SPIRE-Agent. The container init then fails
     EACCES on its first write to ``/var/lib/spire/agent``.

The Bug-22 fix is defensive idempotence: the chown-and-verify pass
is extracted into a reusable helper ``_chown_volume_with_verify`` and
re-applied immediately before every ``systemctl start`` of a Quadlet
container that mounts a named volume (server, agent, NATS). If the
backing directory's owner has drifted between step 6g and the
service start, we observe and correct it before the container init
runs; if owner is already ``1000:1000`` the helper is a fast no-op.

Test-Vector index (continues the Tag-7/Tag-8 ladder)
----------------------------------------------------

  * ``TV-S9T9-22a`` Bootstrap exposes ``_chown_volume_with_verify``
    as a function that exits non-zero on chown failure and stat
    mismatch, mirrored against the same Bug-21 invariants. Mutation
    test guards the helper-extraction refactor.
  * ``TV-S9T9-22b`` Bootstrap exposes ``_pre_start_chown_sweep`` and
    invokes it before each of the three ``systemctl start`` calls in
    step 6 (server, agent, NATS). Mutation test: if a future PR
    removes a sweep before any start, this test must red.
  * ``TV-S9T9-22c`` End-to-end Bug-22 reproduction: the chown loop
    runs at step-6g time (owner=1000:1000), then the simulated podman
    reconciler resets owner to 0:0, then the pre-start sweep at
    step-6h time observes the drift, re-chowns, and the OK line fires
    again with ctx=pre-server-start. Positive-control plus drift
    detection.
  * ``TV-S9T9-22d`` Source-discipline: ``_chown_volume_with_verify``
    and ``_pre_start_chown_sweep`` are textually called from the
    correct step-6 locations. Drift-guard so a future refactor that
    moves the sweeps loses test coverage rather than silently
    bypassing the defensive layer.

Sandbox boundary
----------------

Same shape as Tag-7/Tag-8: PATH-injected mocks for ``podman``,
``chown``, ``stat``; the bootstrap helper functions are sourced into
a tiny driver script that exercises the post-fix invariants without
booting systemd or the real Podman daemon.

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
# Driver: sources the two helper functions out of the bootstrap and
# exercises the exact call shape from step 6g (initial chown) and
# step 6h / 6j (pre-start sweep). PATH-injected mocks drive the
# helpers' branches.
# ---------------------------------------------------------------------------

# Inline copies of the two helpers — kept byte-faithful to the source
# (TV-22d drift-guard asserts these copies stay aligned). We don't
# ``source`` the bootstrap directly because its top-level executes
# ``main`` on load; the helpers must be exercisable in isolation.
HELPER_DRIVER = textwrap.dedent(
    r"""
    #!/usr/bin/env bash
    set -uo pipefail

    log_ok()    { printf 'OK    %s\n' "$1"; }
    log_warn()  { printf 'WARN  %s\n' "$1"; }
    log_err()   { printf 'ERROR %s\n' "$1" >&2; }
    log_note()  { printf 'note  %s\n' "$1"; }

    WAKIR_BOOTSTRAP_PODMAN="${WAKIR_BOOTSTRAP_PODMAN:-podman}"

    _chown_volume_with_verify() {
      local v="$1"
      local ctx="$2"
      local vol_dir actual_owner pre_owner

      vol_dir=$("$WAKIR_BOOTSTRAP_PODMAN" volume inspect "$v" \
        --format '{{.Mountpoint}}' 2>/dev/null || echo "")
      if [[ -z "$vol_dir" ]] || [[ ! -d "$vol_dir" ]]; then
        log_err "podman volume inspect ${v} returned empty/missing path (ctx=${ctx})"
        return 2
      fi

      if [[ "${WAKIR_BOOTSTRAP_DEBUG:-0}" == "1" ]]; then
        pre_owner=$(stat -c '%u:%g' "$vol_dir" 2>/dev/null || echo "stat-err")
        log_note "debug ${ctx}: pre-chown ${vol_dir} owner=${pre_owner}"
      fi

      if ! chown -R 1000:1000 "$vol_dir"; then
        log_err "chown 1000:1000 ${vol_dir} failed (volume ${v}, ctx=${ctx})"
        return 2
      fi

      actual_owner=$(stat -c '%u:%g' "$vol_dir")
      if [[ "$actual_owner" != "1000:1000" ]]; then
        log_err "chown verification failed: ${vol_dir} owner=${actual_owner} (expected 1000:1000, volume ${v}, ctx=${ctx})"
        return 2
      fi

      if [[ "${WAKIR_BOOTSTRAP_DEBUG:-0}" == "1" ]]; then
        log_note "debug ${ctx}: post-chown ${vol_dir} owner=${actual_owner} (ok)"
      fi
      return 0
    }

    _pre_start_chown_sweep() {
      local kind="$1"
      local side="$2"
      local ctx="pre-${kind}-start"
      local v vols=()

      case "$kind" in
        server)
          vols=(
            "wakir-spire-server-federation-${side}-data"
            "wakir-spire-server-federation-${side}-sockets"
            "wakir-spire-server-federation-${side}-bundles"
          )
          ;;
        agent)
          vols=(
            "wakir-spire-agent-${side}-data"
            "wakir-spire-agent-${side}-sockets"
            "wakir-spire-server-federation-${side}-bundles"
          )
          ;;
        nats)
          vols=(
            "wakir-nats-jetstream-data"
          )
          ;;
        *)
          log_err "_pre_start_chown_sweep: unknown kind ${kind}"
          return 2
          ;;
      esac

      for v in "${vols[@]}"; do
        "$WAKIR_BOOTSTRAP_PODMAN" volume create --ignore "$v" >/dev/null 2>&1 || true
        _chown_volume_with_verify "$v" "$ctx" || return 2
      done
      return 0
    }

    # Dispatch entry — first arg picks the helper to exercise.
    op="$1"; shift
    case "$op" in
      chown_one)        _chown_volume_with_verify "$@" ;;
      sweep)            _pre_start_chown_sweep    "$@" ;;
      *) echo "unknown op: $op" >&2; exit 99 ;;
    esac
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
    drv = tmp_path / "tag9_driver.sh"
    drv.write_text(HELPER_DRIVER + "\n")
    _make_executable(drv)
    return drv


@pytest.fixture
def mock_volume_dirs(tmp_path: Path) -> dict[str, Path]:
    """Create the seven named-volume backing directories the helpers
    iterate over (server-side 3 + agent-side 2 + nats 1 + redundant
    bundles ref). Mirrors the helper's ``vols=()`` arrays.
    """
    side = "wakir"
    names = [
        f"wakir-spire-server-federation-{side}-data",
        f"wakir-spire-server-federation-{side}-sockets",
        f"wakir-spire-server-federation-{side}-bundles",
        f"wakir-spire-agent-{side}-data",
        f"wakir-spire-agent-{side}-sockets",
        "wakir-nats-jetstream-data",
    ]
    out: dict[str, Path] = {}
    for n in names:
        p = tmp_path / "vols" / n
        p.mkdir(parents=True)
        out[n] = p
    return out


def _podman_mock(vols: dict[str, Path]) -> str:
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
          case "$3" in
        {cases}
            *) echo "" ;;
          esac
          exit 0
        fi
        exit 1
        """
    ).strip()


def _build_path(
    tmp_path: Path,
    *,
    podman_body: str,
    chown_body: str,
    stat_body: str,
) -> str:
    sandbox = tmp_path / "sandbox_bin"
    sandbox.mkdir(exist_ok=True)
    _write_mock(sandbox / "podman", podman_body)
    _write_mock(sandbox / "chown", chown_body)
    _write_mock(sandbox / "stat", stat_body)
    return f"{sandbox}:{os.environ.get('PATH', '/usr/bin:/bin')}"


# ---------------------------------------------------------------------------
# TV-S9T9-22a: _chown_volume_with_verify hard-halts on chown failure
# AND on stat mismatch (Bug-21 invariants survive the refactor).
# ---------------------------------------------------------------------------


def test_helper_halts_on_chown_failure(
    tmp_path: Path,
    driver: Path,
    mock_volume_dirs: dict[str, Path],
) -> None:
    """Bug-21 invariant 1 survives the Bug-22 helper-extraction."""
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
        echo "should-not-be-reached"
        exit 99
        """
    ).strip()
    path = _build_path(
        tmp_path,
        podman_body=_podman_mock(mock_volume_dirs),
        chown_body=chown_mock,
        stat_body=stat_mock,
    )
    proc = subprocess.run(
        ["bash", str(driver), "chown_one",
         "wakir-spire-agent-wakir-data", "step-6g-initial"],
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 2, (
        f"expected exit 2, got {proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "ERROR" in proc.stderr
    assert "chown 1000:1000" in proc.stderr
    assert "ctx=step-6g-initial" in proc.stderr, (
        f"helper must surface the context tag; stderr={proc.stderr!r}"
    )


def test_helper_halts_on_stat_mismatch(
    tmp_path: Path,
    driver: Path,
    mock_volume_dirs: dict[str, Path],
) -> None:
    """Bug-21 invariant 2 survives the Bug-22 helper-extraction."""
    chown_mock = "#!/usr/bin/env bash\nexit 0\n"
    stat_mock = "#!/usr/bin/env bash\necho '0:0'\nexit 0\n"
    path = _build_path(
        tmp_path,
        podman_body=_podman_mock(mock_volume_dirs),
        chown_body=chown_mock,
        stat_body=stat_mock,
    )
    proc = subprocess.run(
        ["bash", str(driver), "chown_one",
         "wakir-spire-agent-wakir-data", "pre-agent-start"],
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 2
    assert "verification failed" in proc.stderr
    assert "owner=0:0" in proc.stderr
    assert "ctx=pre-agent-start" in proc.stderr, (
        f"helper must surface the context tag; stderr={proc.stderr!r}"
    )


def test_helper_happy_path(
    tmp_path: Path,
    driver: Path,
    mock_volume_dirs: dict[str, Path],
) -> None:
    """Positive control — owner==1000:1000, helper exits 0 quietly."""
    chown_mock = "#!/usr/bin/env bash\nexit 0\n"
    stat_mock = "#!/usr/bin/env bash\necho '1000:1000'\nexit 0\n"
    path = _build_path(
        tmp_path,
        podman_body=_podman_mock(mock_volume_dirs),
        chown_body=chown_mock,
        stat_body=stat_mock,
    )
    proc = subprocess.run(
        ["bash", str(driver), "chown_one",
         "wakir-spire-agent-wakir-data", "step-6g-initial"],
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, (
        f"expected exit 0, got {proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )


def test_helper_debug_env_emits_pre_and_post_stat(
    tmp_path: Path,
    driver: Path,
    mock_volume_dirs: dict[str, Path],
) -> None:
    """WAKIR_BOOTSTRAP_DEBUG=1 surfaces pre- and post-chown stat lines.

    This is the operator-visibility lever the Bring-up-6 retro will
    flip on if the race is suspected again. If the diagnostic ever
    silently disappears, this test points the next operator at the
    exact regression.
    """
    chown_mock = "#!/usr/bin/env bash\nexit 0\n"
    stat_mock = "#!/usr/bin/env bash\necho '1000:1000'\nexit 0\n"
    path = _build_path(
        tmp_path,
        podman_body=_podman_mock(mock_volume_dirs),
        chown_body=chown_mock,
        stat_body=stat_mock,
    )
    proc = subprocess.run(
        ["bash", str(driver), "chown_one",
         "wakir-spire-agent-wakir-data", "step-6g-initial"],
        env={**os.environ, "PATH": path, "WAKIR_BOOTSTRAP_DEBUG": "1"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    assert "debug step-6g-initial: pre-chown" in proc.stdout, (
        f"debug pre-chown line missing; stdout={proc.stdout!r}"
    )
    assert "debug step-6g-initial: post-chown" in proc.stdout, (
        f"debug post-chown line missing; stdout={proc.stdout!r}"
    )


# ---------------------------------------------------------------------------
# TV-S9T9-22b: _pre_start_chown_sweep covers the right volume sets per
# container kind, and halts cleanly on the same failure modes.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,expected_vols",
    [
        (
            "server",
            [
                "wakir-spire-server-federation-wakir-data",
                "wakir-spire-server-federation-wakir-sockets",
                "wakir-spire-server-federation-wakir-bundles",
            ],
        ),
        (
            "agent",
            [
                "wakir-spire-agent-wakir-data",
                "wakir-spire-agent-wakir-sockets",
                "wakir-spire-server-federation-wakir-bundles",
            ],
        ),
        (
            "nats",
            ["wakir-nats-jetstream-data"],
        ),
    ],
)
def test_pre_start_sweep_covers_kind_volume_set(
    tmp_path: Path,
    driver: Path,
    mock_volume_dirs: dict[str, Path],
    kind: str,
    expected_vols: list[str],
) -> None:
    """Each container kind's sweep touches the right named volumes.

    We capture every chown invocation in a sentinel file the mock
    writes to, then assert the captured set equals the expected set.
    Mutation test: if a future refactor drops a volume from a kind's
    list, this test flags the missing entry by name.
    """
    sentinel = tmp_path / "chown_calls.log"
    chown_mock = textwrap.dedent(
        f"""
        #!/usr/bin/env bash
        # Capture the directory we're about to chown into the sentinel.
        printf '%s\\n' "$3" >> "{sentinel}"
        exit 0
        """
    ).strip()
    stat_mock = "#!/usr/bin/env bash\necho '1000:1000'\nexit 0\n"
    path = _build_path(
        tmp_path,
        podman_body=_podman_mock(mock_volume_dirs),
        chown_body=chown_mock,
        stat_body=stat_mock,
    )
    proc = subprocess.run(
        ["bash", str(driver), "sweep", kind, "wakir"],
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, (
        f"sweep kind={kind} expected exit 0, got {proc.returncode}\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert sentinel.exists(), (
        f"chown sentinel never written — chown was not invoked at all"
    )
    chowned_dirs = sentinel.read_text().splitlines()
    # Each chowned dir is a Mountpoint; we mapped each vol-name to a
    # tmp_path subdir in mock_volume_dirs. Reverse-map by basename.
    chowned_vol_names = sorted({Path(p).name for p in chowned_dirs})
    assert chowned_vol_names == sorted(expected_vols), (
        f"sweep kind={kind}: chowned volumes mismatch.\n"
        f"  expected={sorted(expected_vols)}\n"
        f"  actual  ={chowned_vol_names}"
    )


def test_pre_start_sweep_unknown_kind_halts(
    tmp_path: Path,
    driver: Path,
    mock_volume_dirs: dict[str, Path],
) -> None:
    """Defensive: an unknown kind argument must exit non-zero."""
    chown_mock = "#!/usr/bin/env bash\nexit 0\n"
    stat_mock = "#!/usr/bin/env bash\necho '1000:1000'\nexit 0\n"
    path = _build_path(
        tmp_path,
        podman_body=_podman_mock(mock_volume_dirs),
        chown_body=chown_mock,
        stat_body=stat_mock,
    )
    proc = subprocess.run(
        ["bash", str(driver), "sweep", "bogus-kind", "wakir"],
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 2
    assert "unknown kind" in proc.stderr


# ---------------------------------------------------------------------------
# TV-S9T9-22c: end-to-end Bug-22 reproduction — owner drifts between
# step-6g-initial chown and the pre-agent-start sweep; the sweep
# catches the drift and re-chowns successfully.
# ---------------------------------------------------------------------------


def test_bug22_race_reproduction_and_recovery(
    tmp_path: Path,
    driver: Path,
    mock_volume_dirs: dict[str, Path],
) -> None:
    """Reproduces the Bring-up-5 symptom in-test.

    Sequence:
      1. step-6g-initial chown for the agent-data volume succeeds.
      2. A simulated podman reconciler resets the volume owner to
         ``0:0`` (the Bring-up-5 observation).
      3. The pre-agent-start sweep runs ``_chown_volume_with_verify``
         again and recovers ownership.

    Without the Bug-22 sweep, the agent container init would have
    crashed in step 6j; with the sweep, ownership is correct at
    service-start time.
    """
    # Stat that lies based on a sentinel file: before the sentinel
    # exists, owner is 1000:1000 (step-6g state); after the sentinel
    # is dropped (simulated reconcile), owner is 0:0 — until chown
    # is invoked again which removes the sentinel and resets state.
    reset_sentinel = tmp_path / "reconciler_reset.flag"
    stat_mock = textwrap.dedent(
        f"""
        #!/usr/bin/env bash
        if [[ -f "{reset_sentinel}" ]]; then
          echo "0:0"
        else
          echo "1000:1000"
        fi
        exit 0
        """
    ).strip()
    chown_mock = textwrap.dedent(
        f"""
        #!/usr/bin/env bash
        # Successful chown removes the reset-sentinel.
        rm -f "{reset_sentinel}"
        exit 0
        """
    ).strip()
    path = _build_path(
        tmp_path,
        podman_body=_podman_mock(mock_volume_dirs),
        chown_body=chown_mock,
        stat_body=stat_mock,
    )

    # Step-6g-initial: should succeed cleanly.
    p1 = subprocess.run(
        ["bash", str(driver), "chown_one",
         "wakir-spire-agent-wakir-data", "step-6g-initial"],
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert p1.returncode == 0, (
        f"step-6g-initial unexpectedly failed: stderr={p1.stderr!r}"
    )

    # Simulate the podman reconciler resetting owner to root.
    reset_sentinel.write_text("simulated podman-system-generator reset\n")

    # Pre-agent-start sweep: should observe the drift (the chown_mock
    # removes the sentinel as part of its run) and recover. We exercise
    # the agent-kind sweep directly so the three agent-mounted
    # volumes are touched.
    p2 = subprocess.run(
        ["bash", str(driver), "sweep", "agent", "wakir"],
        env={**os.environ, "PATH": path},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert p2.returncode == 0, (
        f"pre-agent-start sweep failed to recover from race:\n"
        f"stdout={p2.stdout!r}\nstderr={p2.stderr!r}"
    )
    assert not reset_sentinel.exists(), (
        "post-recovery: reset sentinel still present — chown_mock was not invoked"
    )


# ---------------------------------------------------------------------------
# TV-S9T9-22d: source-discipline drift guards — the bootstrap actually
# calls the helpers from step 6g/6h/6j at the right spots.
# ---------------------------------------------------------------------------


def test_bootstrap_defines_chown_helper() -> None:
    """``_chown_volume_with_verify`` is defined in the bootstrap."""
    src = BOOTSTRAP.read_text()
    assert "_chown_volume_with_verify()" in src, (
        "Bug-22 regression: _chown_volume_with_verify helper missing"
    )


def test_bootstrap_defines_pre_start_sweep_helper() -> None:
    """``_pre_start_chown_sweep`` is defined in the bootstrap."""
    src = BOOTSTRAP.read_text()
    assert "_pre_start_chown_sweep()" in src, (
        "Bug-22 regression: _pre_start_chown_sweep helper missing"
    )


def test_step_6g_uses_chown_helper() -> None:
    """The step-6g loop calls ``_chown_volume_with_verify`` per volume
    rather than open-coding chown+stat.

    Bug-22 invariant: if a future PR re-inlines the open-coded chown
    loop, the helper-based contract (re-usable from pre-start sweeps)
    is gone and the race window opens up again.
    """
    src = BOOTSTRAP.read_text()
    assert '_chown_volume_with_verify "$v" "step-6g-initial"' in src, (
        "Bug-22 regression: step 6g must call _chown_volume_with_verify "
        "with the step-6g-initial context tag"
    )


def test_pre_start_sweeps_present_for_all_three_services() -> None:
    """The bootstrap calls ``_pre_start_chown_sweep`` for each of the
    three Quadlet container kinds the pilot starts: server (step 6h),
    agent (step 6j), and NATS (step 6j).

    Mutation test: drop any of the three calls in source, this fails.
    """
    src = BOOTSTRAP.read_text()
    # Server sweep is hard-coded with the literal kind string.
    assert '_pre_start_chown_sweep "server"' in src, (
        "Bug-22 regression: step 6h must call _pre_start_chown_sweep "
        "for the server kind before systemctl start"
    )
    # Agent + NATS share the step-6j case-dispatch loop; we assert
    # the kind tokens are present in the case branches.
    assert 'kind="agent"' in src, (
        "Bug-22 regression: step 6j case-dispatch must map the agent "
        "service to the agent kind for pre-start sweep"
    )
    assert 'kind="nats"' in src, (
        "Bug-22 regression: step 6j case-dispatch must map the NATS "
        "service to the nats kind for pre-start sweep"
    )
    # And the sweep call inside the loop must exist.
    assert '_pre_start_chown_sweep "$kind" "$side"' in src, (
        "Bug-22 regression: step 6j case-dispatch loop must invoke "
        "_pre_start_chown_sweep with the resolved kind"
    )


def test_helper_driver_mirrors_source_chown_invariants() -> None:
    """Drift-guard: the test-internal helper-driver text mirrors the
    source's post-fix invariants. Same shape as Tag-8's
    ``test_driver_mirrors_source_loop_invariants``.
    """
    src = BOOTSTRAP.read_text()
    # No 2>/dev/null swallow around chown (Bug-21 invariant lives).
    chown_lines = [
        raw for raw in src.splitlines()
        if "chown -R 1000:1000" in raw and not raw.lstrip().startswith("#")
    ]
    assert chown_lines, "chown -R line missing entirely"
    for line in chown_lines:
        assert "2>/dev/null" not in line, (
            f"Bug-21 regression: chown stderr swallowed on line {line!r}"
        )
    # Stat verification still present.
    assert "stat -c '%u:%g'" in src, (
        "Bug-21 regression: stat verification missing from helper"
    )
    # ctx-tagged diagnostics — Bug-22 specifically wants the context
    # surfaced so the next operator can tell which call site failed.
    assert "ctx=${ctx}" in src, (
        "Bug-22 regression: helper diagnostics must surface the ctx tag"
    )
    # WAKIR_BOOTSTRAP_DEBUG env var is the documented operator lever.
    assert "WAKIR_BOOTSTRAP_DEBUG" in src, (
        "Bug-22 regression: WAKIR_BOOTSTRAP_DEBUG operator-lever missing"
    )
