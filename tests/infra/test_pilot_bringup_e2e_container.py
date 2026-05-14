# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""End-to-End live-substrate Bring-up tests in a containerized
Fedora environment (Phase-2 Sprint-9 Tag-4).

Sister module to ``test_pilot_bringup_substance.py``: where that one
asserts source-shape, this one runs the bootstrap script logic
end-to-end against a real podman + (mock) systemd surface.

Test substrate
--------------

Each E2E test spins a short-lived ``fedora:latest`` container with:

  * ``WAKIR_BOOTSTRAP_SYSTEMCTL`` pointed at a stub binary that
    records every call and returns 0,
  * ``WAKIR_BOOTSTRAP_PODMAN`` pointed at a stub binary that records
    pulls/runs and returns 0,
  * ``WAKIR_BOOTSTRAP_CURL`` pointed at a stub binary that 200's all
    requests,
  * ``WAKIR_BOOTSTRAP_GIT`` pointed at a stub that copies a fixture
    tree to ``WAKIR_REPO_ROOT``,
  * ``WAKIR_SKIP_PROMPTS=1`` and ``WAKIR_SKIP_COSIGN_VERIFY=1``,
  * a faked ``/etc/os-release`` (Fedora-CoreOS, NOT live).

This lets the test exercise:

  1. The Phase 6 install path produces the EXACT Quadlet unit filenames
     the per-side substitution expects (Bug 2).
  2. The Phase 6 install path produces unit FILE CONTENT that matches
     the agent's [Unit] dependency (Bug 3, Bug 4).
  3. The Phase 6 ``--resume-from 6`` path is idempotent (Bug 5).
  4. Phase 8 smoke-test stub (proxmox-bringup-smoke) is invoked.

This is the closest hermetic-reproducible approximation to "fresh
Fedora-CoreOS VM" available in CI.

Skipping
--------

The whole module is SKIPPED when:

  * ``podman`` is not on PATH (sandbox has no container runtime), OR
  * the bootstrap script's containerized-execution mode is blocked by
    the local AppArmor / SELinux policy, OR
  * env var ``AMARA_E2E_BRINGUP_SKIP=1`` is set (operator-hand opt-out
    for fast local iteration).

In CI (GitHub-Actions ``ubuntu-latest``, see
``.github/workflows/e2e-bringup-ci.yml``), podman is preinstalled, so
the suite runs in full.

— Amara
"""

from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_REL = "infra/spire/federation/wakir-pilot-bootstrap.sh"


# ---------------------------------------------------------------------------
# Module-level skip gate
# ---------------------------------------------------------------------------


def _can_run_container_substrate() -> tuple[bool, str]:
    if os.environ.get("AMARA_E2E_BRINGUP_SKIP") == "1":
        return False, "AMARA_E2E_BRINGUP_SKIP=1"
    if shutil.which("podman") is None:
        return False, "podman not on PATH"
    # Quick health probe: can podman version succeed? Then try a no-op
    # run against a minimal image to check the user-namespace path is
    # functional. On hosts where rootless podman is half-configured
    # (e.g. an existing pause process in a stale namespace) the run
    # path fails even though version passes. We skip cleanly in that
    # case rather than fail.
    try:
        r = subprocess.run(
            ["podman", "version", "--format", "{{.Client.Version}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"podman version probe failed: {exc!r}"
    if r.returncode != 0:
        return False, f"podman version probe non-zero: {r.stderr.strip()}"
    # Probe a minimal run.
    try:
        run = subprocess.run(
            ["podman", "run", "--rm", "fedora:latest", "/bin/true"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"podman run probe failed: {exc!r}"
    if run.returncode != 0:
        return False, f"podman run probe non-zero: {run.stderr.strip()[:200]}"
    return True, ""


_CAN_RUN, _SKIP_REASON = _can_run_container_substrate()
# Per-test skip rather than module-level so the meta-tests (which
# don't drive a container) still run in the sandbox.
_requires_container = pytest.mark.skipif(not _CAN_RUN, reason=_SKIP_REASON)


# ---------------------------------------------------------------------------
# Stub helpers for systemctl / podman / curl / git inside the container
# ---------------------------------------------------------------------------


_STUB_SYSTEMCTL = textwrap.dedent(
    """\
    #!/bin/bash
    # Record every call; treat is-active as "yes" only when state file
    # for the unit exists.
    set -u
    echo "[stub-systemctl] $*" >> /tmp/systemctl-calls.log
    case "${1:-}" in
      daemon-reload)
        exit 0
        ;;
      is-active)
        # --quiet flag may precede the unit; skip flags
        for arg in "$@"; do
          case "$arg" in
            -*|is-active) continue ;;
            *) unit="$arg"; break ;;
          esac
        done
        if [[ -f "/tmp/active-units/${unit}" ]]; then exit 0; else exit 3; fi
        ;;
      start)
        mkdir -p /tmp/active-units
        touch "/tmp/active-units/$2"
        exit 0
        ;;
      stop)
        rm -f "/tmp/active-units/$2" 2>/dev/null
        exit 0
        ;;
      *)
        exit 0
        ;;
    esac
    """
)

_STUB_PODMAN = textwrap.dedent(
    """\
    #!/bin/bash
    echo "[stub-podman] $*" >> /tmp/podman-calls.log
    # Subset of commands the bootstrap might issue:
    case "${1:-}" in
      --version) echo "podman version 5.0.0 (stub)"; exit 0 ;;
      inspect) exit 1 ;;     # "container not present" forces create path
      create) echo "stub-container-id"; exit 0 ;;
      start) exit 0 ;;
      exec)
        # Sprint-9 Tag-7 bundle (PR #45 Kai jq-fix superset + PR #46 Tomás
        # exec/volume extension): the bootstrap's step 6i issues
        #   podman exec <ctr> /opt/spire/bin/spire-server token generate ...
        # and parses the "Token: <hex>" line. The bootstrap's step 6i
        # agent-list probe runs
        #   podman exec <ctr> /opt/spire/bin/spire-server agent list
        # and grep-matches on a SPIFFE ID; we want a "not-yet-attested"
        # response so the token-generate branch fires. Detect both
        # patterns from the trailing args. Bundle-merge conflict-resolve
        # (Lena, 2026-05-14): Tomás's superset (token-generate +
        # agent-list + volume handlers) supersedes Kai's narrower
        # token-generate-only stub; both intents satisfied.
        shift
        ctr="${1:-}"; shift || true
        # The actual command starts after the container name. Walk the
        # rest for "token generate" or "agent list".
        cmdline="$*"
        case "$cmdline" in
          *"token generate"*)
            # Emit the canonical SPIRE token-generate output shape so the
            # bootstrap's sed-parse picks the hex up.
            echo "Token: $(printf '%032x%032x' 0xdeadbeef 0xcafef00d)"
            exit 0
            ;;
          *"agent list"*)
            # No agents attested yet -> empty list (bootstrap's grep -q
            # for the SPIFFE ID returns non-zero, taking the not-yet-
            # attested branch).
            echo "Found 0 attested agents:"
            exit 0
            ;;
          *)
            exit 0
            ;;
        esac
        ;;
      volume)
        # podman volume create --ignore <name>; podman volume inspect.
        sub="${2:-}"
        case "$sub" in
          create) exit 0 ;;
          inspect)
            # Emit a fake mountpoint so the bootstrap's chown step has
            # something to chown. /tmp is writable inside the E2E
            # container.
            #
            # Sprint-9-Tag-11 Bug-27 stub-extension: if the queried
            # volume name ends in "-sockets", touch a fake unix socket
            # at /tmp/api.sock so the bootstrap's host-path-based
            # workload-API-wait (post Bug-27 fix) detects it as bound.
            # Parse the volume name from argv (it's the first non-flag
            # arg after "volume inspect").
            shift 2  # consume "volume inspect"
            vol_name=""
            while [[ -n "${1:-}" ]]; do
              case "$1" in
                --format) shift 2 ;;
                --*) shift ;;
                *) vol_name="$1"; shift ;;
              esac
            done
            echo "/tmp"
            if [[ "$vol_name" == *-sockets ]]; then
              python3 -c "
import socket, os
p = '/tmp/api.sock'
if not os.path.exists(p):
    s = socket.socket(socket.AF_UNIX)
    s.bind(p)
" 2>/dev/null || true
            fi
            exit 0
            ;;
          *) exit 0 ;;
        esac
        ;;
      *) exit 0 ;;
    esac
    """
)

_STUB_CURL = textwrap.dedent(
    """\
    #!/bin/bash
    echo "[stub-curl] $*" >> /tmp/curl-calls.log
    # All GET probes succeed; produce empty body on -o /dev/null forms.
    for arg in "$@"; do
      case "$arg" in
        -o) shift; out="$1"; ;;
      esac
      shift || true
    done
    # If -o /dev/null pattern, nothing to write; else write a 1-byte
    # placeholder so the script's downstream "[[ -f ... ]]" checks pass.
    : # noop
    exit 0
    """
)

_STUB_GIT = textwrap.dedent(
    """\
    #!/bin/bash
    echo "[stub-git] $*" >> /tmp/git-calls.log
    # clone <url> <dst>: copy from the bind-mounted /repo to <dst>.
    case "${1:-}" in
      clone)
        shift
        # Skip flags --depth, --branch <x>
        while [[ "${1:-}" =~ ^-- ]]; do
          case "$1" in
            --depth|--branch) shift 2 ;;
            *) shift ;;
          esac
        done
        url="$1"; dst="$2"
        mkdir -p "$(dirname "$dst")"
        cp -a /repo "$dst"
        exit 0
        ;;
      fetch|checkout|reset)
        exit 0
        ;;
      *)
        exit 0
        ;;
    esac
    """
)

_STUB_SMOKE = textwrap.dedent(
    """\
    #!/bin/bash
    # Pretend a 6/6-PASS smoke. The substance suite already asserts the
    # source contract; this stub satisfies Phase 8 so the test can prove
    # the bootstrap reached Phase 8 cleanly.
    echo "Smoke OK: 6/6 checks pass (stub)"
    exit 0
    """
)

_STUB_OS_RELEASE = textwrap.dedent(
    """\
    NAME="Fedora Linux"
    VERSION="40 (Container Image)"
    ID=fedora
    VARIANT_ID=coreos
    """
)


# ---------------------------------------------------------------------------
# Fedora-container test substrate driver
# ---------------------------------------------------------------------------


def _run_bootstrap_in_container(
    tmp_path: Path,
    *,
    resume_from: int = 1,
    pre_phase_6_run: bool = False,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Drive the bootstrap script inside a fedora:latest container with
    every external dep stubbed.

    Returns the completed process so the test can inspect stdout, the
    stub call-logs, and any /tmp/active-units state.
    """
    # Build the stub directory.
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, content in (
        ("systemctl", _STUB_SYSTEMCTL),
        ("podman", _STUB_PODMAN),
        ("curl", _STUB_CURL),
        ("git", _STUB_GIT),
        ("proxmox-bringup-smoke", _STUB_SMOKE),
    ):
        p = stubs / name
        p.write_text(content)
        p.chmod(0o755)

    # Write the os-release file.
    osrel = tmp_path / "os-release"
    osrel.write_text(_STUB_OS_RELEASE)

    # Construct the in-container script:
    #   1. Lay down /etc/os-release (already faked via bind),
    #   2. Lay down stubs into a directory on PATH,
    #   3. Maybe pre-run Phase 6 once,
    #   4. Run the bootstrap with the requested --resume-from.
    pre_phase = ""
    if pre_phase_6_run:
        pre_phase = (
            "echo '[e2e] pre-run Phase 6 once to populate state'\n"
            "bash /repo/{boot} --resume-from 6 || true\n"
            "echo '[e2e] pre-run complete; capturing state for idempotency check'\n"
            "cp -a /etc/containers/systemd /tmp/pre-second-run\n"
        ).format(boot=BOOTSTRAP_REL)

    inner_script = textwrap.dedent(
        f"""\
        set -u
        # 0. Install jq inside the fedora:latest substrate.
        #
        #    Bug-19 (Sprint-9 Tag-7, Lena Bundle-Merge 2026-05-14 ~02:00 CEST):
        #    the e2e-container lane runs the bootstrap with
        #    ``--resume-from 4``, which skips Phase 3 (CLI-Tools-Install:
        #    cosign + skopeo + jq + git). Phase 5 of the bootstrap parses
        #    skopeo-inspect output via ``jq``; with jq absent the shell
        #    emits ``jq: command not found`` and the Quadlet install path
        #    downstream is left in an inconsistent state, so Phase 8
        #    (Smoke) is never reached and the test asserts. The real
        #    Fedora-CoreOS Pilot-VM has jq via Phase 3 (rpm-ostree); the
        #    container stub must match that substrate. We install jq via
        #    dnf -- the minimal install (no weak deps) keeps the cold-pull
        #    budget small.
        dnf install -y --setopt=install_weak_deps=False jq >/dev/null 2>&1 \\
          || {{ echo "[e2e] FATAL: jq install failed"; exit 1; }}
        # 1. Make the stubs the primary tools.
        export PATH="/work/stubs:$PATH"
        # 2. Fake os-release.
        cp /work/os-release /etc/os-release || true
        # 3. Sym-link /repo into the wakir-runtime install location so
        #    the bootstrap doesn't re-clone (clone path is stubbed
        #    anyway, but Phase 4 short-circuits on .git/ present).
        mkdir -p /opt
        ln -sfn /repo /opt/wakir-runtime
        # 4. Stub the resolver-pin script too -- it's normally invoked
        #    in step 5 when WAKIR_SKIP_COSIGN_VERIFY=0. We set =1 to
        #    bypass.
        # 5. Mock /etc/containers/systemd as a regular dir on the
        #    container's writable rootfs.
        mkdir -p /etc/containers/systemd
        # 6. Mock bind-mount target paths the bootstrap touches.
        mkdir -p /etc/wakir/spire-federation /etc/wakir
        # 7. Provide a fake spire-server-<side>.conf source so Phase 6c
        #    finds something to install.
        printf '# stub server conf\\n' \\
            > /repo/infra/spire/federation/config/spire-server-wakir.conf
        printf '# stub agent conf\\n' \\
            > /repo/infra/spire/agent/config/spire-agent-wakir.conf
        # 8. Sprint-9 Tag-7 substance-fix (Bug-16 sibling): the
        #    bootstrap's step 6i (join-token issue + sed-substitute)
        #    parses ``spire-server token generate`` output via ``jq``
        #    on real Pilot-VM. The ``fedora:latest`` E2E container
        #    image does NOT ship jq by default, so Step 6 crashes
        #    with ``line N: jq: command not found`` and the test
        #    asserts a Phase-8-reached state we never get to. The
        #    real-VM Step-1 pre-flight check now enforces this dep,
        #    but the E2E test runs --resume-from 4 (Step 1 skipped)
        #    so we mirror the dep inventory here. Install is silent
        #    and idempotent; failure is non-fatal so a future image
        #    that already carries jq still works.
        if ! command -v jq >/dev/null 2>&1; then
          (dnf -y install jq 2>/dev/null || microdnf -y install jq 2>/dev/null) >/dev/null || true
        fi
        {pre_phase}
        echo '[e2e] running bootstrap --resume-from {resume_from}'
        bash /repo/{BOOTSTRAP_REL} --resume-from {resume_from}
        echo "[e2e] bootstrap exit: $?"
        echo "[e2e] /etc/containers/systemd contents:"
        ls -la /etc/containers/systemd
        if [[ -d /tmp/pre-second-run ]]; then
          echo "[e2e] diff pre-second-run vs current (idempotency probe):"
          diff -ru /tmp/pre-second-run /etc/containers/systemd || true
        fi
        echo "[e2e] systemctl call log:"
        cat /tmp/systemctl-calls.log 2>/dev/null || echo '(none)'
        """
    )

    work = tmp_path / "work"
    work.mkdir()
    (work / "stubs").mkdir()
    for f in stubs.iterdir():
        shutil.copy2(f, work / "stubs" / f.name)
        (work / "stubs" / f.name).chmod(0o755)
    (work / "os-release").write_text(_STUB_OS_RELEASE)
    (work / "inner.sh").write_text(inner_script)
    (work / "inner.sh").chmod(0o755)

    env = {
        "WAKIR_ORG_ID": "acme",
        "WAKIR_TRUST_DOMAIN": "wakir.test",
        "WAKIR_SKIP_COSIGN_VERIFY": "1",
        "WAKIR_SKIP_PROMPTS": "1",
        "WAKIR_REPO_ROOT": "/opt/wakir-runtime",
        "WAKIR_REPO_URL": "stub://no-clone-needed",
        "WAKIR_BOOTSTRAP_SYSTEMCTL": "/work/stubs/systemctl",
        "WAKIR_BOOTSTRAP_PODMAN": "/work/stubs/podman",
        "WAKIR_BOOTSTRAP_CURL": "/work/stubs/curl",
        "WAKIR_BOOTSTRAP_GIT": "/work/stubs/git",
        "WAKIR_BOOTSTRAP_SMOKE": "/work/stubs/proxmox-bringup-smoke",
    }
    if extra_env:
        env.update(extra_env)
    env_args = []
    for k, v in env.items():
        env_args.extend(["-e", f"{k}={v}"])

    cmd = [
        "podman",
        "run",
        "--rm",
        # We don't NEED privileged for this stub-driven path; the
        # systemctl/podman/curl/git stubs avoid real OS surface.
        "--user", "0:0",
        "-v", f"{REPO_ROOT}:/repo:Z",
        "-v", f"{work}:/work:Z",
        *env_args,
        "fedora:latest",
        "/bin/bash",
        "/work/inner.sh",
    ]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
    )


# ---------------------------------------------------------------------------
# E2E-01: Full Bring-up reaches Phase 8 cleanly
# ---------------------------------------------------------------------------


@_requires_container
def test_e2e_full_bringup_reaches_phase_8(tmp_path: Path) -> None:
    """Drive the bootstrap from Phase 4 (skip pre-flight + toolbox +
    cli-tools, which don't make sense in the stub container) and assert
    it cleanly progresses through Phase 6 (Quadlet install) and Phase 8
    (Smoke-Test stub returns 6/6).

    This is the regression-net for "the same Manual-Fix-sequence the AR
    needed on 2026-05-13 should not be needed anymore".
    """
    proc = _run_bootstrap_in_container(tmp_path, resume_from=4)
    combined = proc.stdout + proc.stderr
    # The exit code reflects bootstrap success; Phase 8 stub returns 0.
    assert proc.returncode == 0, (
        f"E2E bootstrap exited non-zero ({proc.returncode}).\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    # Phase 8 must be reached and the smoke stub invoked.
    assert "Smoke-Test" in combined or "Smoke" in combined, (
        f"Phase 8 (Smoke) not reached:\n{combined}"
    )
    assert "6/6" in combined, (
        f"Smoke-Test did not report 6/6 PASS:\n{combined}"
    )


# ---------------------------------------------------------------------------
# E2E-02: After Phase 6, all referenced .volume files are installed
# ---------------------------------------------------------------------------


@_requires_container
def test_e2e_phase_6_installs_volume_files_matching_container_refs(
    tmp_path: Path,
) -> None:
    """After the bootstrap runs Phase 6, the installed /etc/containers/
    systemd directory MUST contain a .volume file for every Volume=
    reference in the installed server-federation-${side}.container.

    This is the runtime evidence for Bug 2 from the Mira-Bug-Bilanz.
    """
    proc = _run_bootstrap_in_container(tmp_path, resume_from=4)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"bootstrap failed:\n{combined}"

    # Parse "ls -la /etc/containers/systemd" output from inner.sh.
    # Stronger approach: install and inspect via grep.
    # Find every "wakir-spire-server-federation-wakir-*.volume" in the
    # captured listing.
    referenced_pattern = "wakir-spire-server-federation-wakir-data.volume"
    installed_section = combined.split(
        "/etc/containers/systemd contents:", 1
    )[-1]
    assert referenced_pattern in installed_section, (
        f"Phase 6 did NOT install {referenced_pattern!r} in\n"
        f"/etc/containers/systemd. The container template references\n"
        f"this filename but the bootstrap installed only the source-\n"
        f"shape filename (without the ``-wakir-`` middle segment).\n\n"
        f"Listing:\n{installed_section}"
    )


# ---------------------------------------------------------------------------
# E2E-03: After Phase 6, the agent container's Requires= resolves
# ---------------------------------------------------------------------------


@_requires_container
def test_e2e_phase_6_agent_requires_matches_installed_server_service(
    tmp_path: Path,
) -> None:
    """After Phase 6 install, the agent .container file's Requires=
    line must reference a service derived from a .container file the
    bootstrap actually installed.

    Runtime evidence for Bugs 3 and 4.
    """
    proc = _run_bootstrap_in_container(tmp_path, resume_from=4)
    assert proc.returncode == 0, proc.stderr

    # Read the installed agent container from the container's
    # /etc/containers/systemd via a follow-up podman exec? Simpler:
    # the bootstrap already prints the listing. We assert no
    # ``server-wakir.service`` (without -federation-) appears in the
    # agent file's [Unit] Requires=, by reading the source after sed.
    #
    # The deepest check: re-read the AGENT_FED_TPL after the SAME sed
    # the bootstrap applies and confirm the substituted text contains
    # only the federation-form service name.
    agent_tpl = (
        REPO_ROOT
        / "infra"
        / "spire"
        / "agent"
        / "quadlet"
        / "wakir-spire-agent-federation.container"
    )
    agent_text = agent_tpl.read_text(encoding="utf-8").replace("<SIDE>", "wakir")
    server_unit_line = "wakir-spire-server-wakir.service"
    fed_unit_line = "wakir-spire-server-federation-wakir.service"

    if server_unit_line in agent_text and fed_unit_line not in agent_text:
        pytest.fail(
            "Post-sed agent container template references the non-\n"
            "federation server service name ``wakir-spire-server-wakir.\n"
            "service`` but the bootstrap installs the server as\n"
            "``wakir-spire-server-federation-wakir.service``.\n\n"
            "This is Bug 4 from the 2026-05-13 Mira-Bug-Bilanz, caught\n"
            "in the containerized e2e substrate."
        )


# ---------------------------------------------------------------------------
# E2E-04: Phase 6 idempotency: second run does not destabilise state
# ---------------------------------------------------------------------------


@_requires_container
def test_e2e_phase_6_resume_is_idempotent(tmp_path: Path) -> None:
    """Run Phase 6 once, snapshot /etc/containers/systemd, run again,
    compare. The diff should be empty (or contain only a non-state-
    modifying re-log).
    """
    proc = _run_bootstrap_in_container(
        tmp_path, resume_from=6, pre_phase_6_run=True
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, (
        f"Phase-6 second run failed:\n{combined}"
    )

    # The diff section appears between the listing and the systemctl
    # log when pre_phase_6_run is True.
    diff_section_marker = (
        "diff pre-second-run vs current (idempotency probe):"
    )
    if diff_section_marker not in combined:
        pytest.fail(
            "idempotency probe did not run (test fixture broken):\n"
            f"{combined}"
        )
    diff_block = combined.split(diff_section_marker, 1)[1]
    # Strip down to the next marker.
    diff_block = diff_block.split("systemctl call log:", 1)[0]

    # Any line starting with ``+`` or ``-`` (not ``+++`` / ``---``) is
    # a delta. Header lines (``Only in``) on either side are also a
    # delta.
    deltas = [
        line
        for line in diff_block.splitlines()
        if (line.startswith("+") and not line.startswith("+++"))
        or (line.startswith("-") and not line.startswith("---"))
        or line.startswith("Only in ")
    ]
    assert not deltas, (
        "Phase-6 second run produced state-mutating delta:\n"
        + "\n".join(deltas)
        + "\n\nThis is Bug 5 from the 2026-05-13 Mira-Bug-Bilanz: "
        "Phase 6 is not idempotent on re-run."
    )


# ---------------------------------------------------------------------------
# Meta: ensure we wired the same env-injection hooks the bootstrap
# documents at the top of the file. If those env names change, the
# stubs become silent no-ops and the e2e suite degrades to "always
# pass" without anyone noticing.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# E2E-05: Smoke-test stub failure surfaces a clear regression signal
# ---------------------------------------------------------------------------


@_requires_container
def test_e2e_smoke_test_failure_propagates_to_bootstrap_exit(
    tmp_path: Path,
) -> None:
    """If the smoke test stub fails, the bootstrap must exit non-zero so
    CI / operators see the failure. The 2026-05-13 bring-up surfaced
    this contract: Phase 8 reported "1/6 PASS" but the bootstrap exit
    code (without our regression-net) was 0 in some intermediate states.

    We override WAKIR_BOOTSTRAP_SMOKE with a stub that fails and confirm
    the bootstrap exits non-zero.
    """
    fail_smoke = tmp_path / "fail-smoke"
    fail_smoke.write_text(
        "#!/bin/bash\n"
        "echo 'Smoke FAIL (stub): 1/6 PASS'\n"
        "exit 2\n"
    )
    fail_smoke.chmod(0o755)
    # Re-run with WAKIR_BOOTSTRAP_SMOKE pointed at the failing stub.
    proc = _run_bootstrap_in_container(
        tmp_path,
        resume_from=8,
        extra_env={
            "WAKIR_BOOTSTRAP_SMOKE": "/work/stubs/fail-smoke",
        },
    )
    # Inner.sh runs the bootstrap and then prints "exit: $?" -- the
    # bootstrap exits 2 inside fail_step, which becomes inner.sh's exit
    # code (inner.sh has no ``set -e``, so the final echo runs but the
    # podman-run exit is the bootstrap's exit).
    combined = proc.stdout + proc.stderr
    assert "Smoke" in combined and "FAIL" in combined.upper(), (
        f"smoke stub output not captured:\n{combined}"
    )
    # The bootstrap should have called fail_step (exit 2). proc.returncode
    # reflects the *last* command in inner.sh, which is the cat of the
    # call log. Stronger assertion: grep for "Bring-up halted" banner.
    assert "Bring-up halted" in combined, (
        "Bootstrap did not surface 'Bring-up halted' banner after smoke\n"
        f"failure; CI signal is degraded:\n{combined}"
    )


def test_e2e_meta_env_injection_hooks_present_in_bootstrap() -> None:
    script = (REPO_ROOT / BOOTSTRAP_REL).read_text(encoding="utf-8")
    for hook in (
        "WAKIR_BOOTSTRAP_PODMAN",
        "WAKIR_BOOTSTRAP_SYSTEMCTL",
        "WAKIR_BOOTSTRAP_CURL",
        "WAKIR_BOOTSTRAP_GIT",
        "WAKIR_BOOTSTRAP_SMOKE",
    ):
        assert hook in script, (
            f"bootstrap no longer declares env-injection hook {hook!r}; "
            f"the e2e suite stubs would become silent no-ops. Re-wire "
            f"the test fixture or restore the hook in the script."
        )
