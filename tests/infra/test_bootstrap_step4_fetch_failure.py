# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic behaviour tests for step 4 of the pilot bootstrap: a git
call that fails must stop the step, not be overwritten by the exit
status of the next one.

The defect
----------

``step_4_repo_clone`` updated an existing checkout like this::

    (
      cd "$WAKIR_REPO_ROOT"
      git fetch --depth 1 origin "$branch"   >/dev/null 2>&1
      git checkout "$branch"                 >/dev/null 2>&1
      git reset --hard "origin/${branch}"    >/dev/null 2>&1
    ) || { log_err "git fetch/reset failed"; return 2; }
    log_ok "repo updated to origin/${branch}"

Three commands, three output redirections, and one exit status -- the
subshell returns the status of ``reset --hard`` alone. ``reset --hard
origin/<branch>`` reads a *remote-tracking ref that already exists on
disk*; it does not talk to the remote and it does not care whether the
fetch that was supposed to refresh that ref succeeded. So when the
fetch failed -- no route to the forge, credentials expired, remote
renamed -- the step reset the checkout to whatever the last successful
fetch had left behind, possibly weeks old, and logged
``repo updated to origin/<branch>``.

That is the same class as the defects found in this file on the same
day: a step that reports success for something that did not happen. It
is worse than a loud failure in two directions at once -- the tree is
silently older than the log claims, and every later step, every smoke
check and every acceptance verdict downstream is computed against it.

What these vectors drive
------------------------

Behaviour, against a real ``git`` and a real local remote. No network:
the "remote" is a bare repository in ``tmp_path``, and an unreachable
remote is produced by renaming it out from under the checkout, which is
exactly the shape of the failure being guarded (fetch fails, the stale
``refs/remotes/origin/<branch>`` is still there and still resettable).

  * ``TV-S4F-1``  a failed fetch returns non-zero and says so.
  * ``TV-S4F-2``  a failed fetch leaves the checkout alone -- it does
    not reset the tree to a stale remote-tracking ref.
  * ``TV-S4F-3``  a failed fetch does not emit the success line.
  * ``TV-S4F-4``  the underlying git error reaches the operator instead
    of ``/dev/null``.
  * ``TV-S4F-5``  NEGATIVE CONTROL: a reachable remote still updates the
    checkout to the remote tip and returns 0. The guard must not turn
    the normal path into a failure.
  * ``TV-S4F-6``  MUTATION CONTROL: with the pre-fix subshell restored
    in a copy of the bootstrap, TV-S4F-1..4 invert -- rc=0 and the
    success line -- which is what proves these vectors test the fix and
    not the scaffolding.

Sandbox boundary
----------------

No network, no root, no systemd, no podman. Only ``git`` against paths
under ``tmp_path``. The bootstrap is sourced (its ``BASH_SOURCE``
main-gate makes that safe) and ``step_4_repo_clone`` is called
directly.

-- the QA zone
"""

from __future__ import annotations

import os
import re
import stat as stat_mod
import subprocess
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = (
    REPO_ROOT / "infra" / "spire" / "federation" / "wakir-pilot-bootstrap.sh"
)

GIT_ENV = {
    "GIT_AUTHOR_NAME": "bootstrap-test",
    "GIT_AUTHOR_EMAIL": "bootstrap-test@example.invalid",
    "GIT_COMMITTER_NAME": "bootstrap-test",
    "GIT_COMMITTER_EMAIL": "bootstrap-test@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


# ---------------------------------------------------------------------------
# Fixture substrate: a bare "remote" and a checkout, both in tmp_path.
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"git {' '.join(args)} failed in {cwd}:\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    return proc.stdout.strip()


def _make_executable(path: Path) -> None:
    path.chmod(
        path.stat().st_mode
        | stat_mod.S_IXUSR
        | stat_mod.S_IXGRP
        | stat_mod.S_IXOTH
    )


class NodeRepo:
    """A checkout at ``node/`` fed by a bare remote at ``origin.git``,
    plus a driver that calls the real ``step_4_repo_clone``."""

    BRANCH = "main"

    def __init__(self, tmp_path: Path, bootstrap: Path | None = None) -> None:
        self.root = tmp_path
        self.bootstrap = bootstrap or BOOTSTRAP
        self.origin = tmp_path / "origin.git"
        self.node = tmp_path / "node"

        _git(tmp_path, "init", "--bare", "-b", self.BRANCH, str(self.origin))
        seed = tmp_path / "seed"
        seed.mkdir()
        _git(seed, "init", "-b", self.BRANCH)
        (seed / "README.md").write_text("baseline\n")
        _git(seed, "add", "README.md")
        _git(seed, "commit", "-m", "baseline")
        _git(seed, "remote", "add", "origin", str(self.origin))
        _git(seed, "push", "origin", self.BRANCH)
        self.seed = seed

        _git(
            tmp_path,
            "clone",
            "--depth",
            "1",
            "--branch",
            self.BRANCH,
            str(self.origin),
            str(self.node),
        )

    # -- substrate manipulation ---------------------------------------
    def head(self) -> str:
        return _git(self.node, "rev-parse", "HEAD")

    def origin_tip(self) -> str:
        return _git(self.origin, "rev-parse", self.BRANCH)

    def commit_on_node(self, text: str) -> str:
        """Put work on the node that the canonical branch does not have
        -- a change an operator injected to measure it before merge."""
        (self.node / "INJECTED.md").write_text(text)
        _git(self.node, "add", "INJECTED.md")
        _git(self.node, "commit", "-m", f"injected: {text.strip()}")
        return self.head()

    def advance_remote(self, text: str) -> str:
        (self.seed / "README.md").write_text(text)
        _git(self.seed, "add", "README.md")
        _git(self.seed, "commit", "-m", f"remote: {text.strip()}")
        _git(self.seed, "push", "origin", self.BRANCH)
        return self.origin_tip()

    def break_remote(self) -> None:
        """Make ``git fetch`` fail while leaving the stale
        ``refs/remotes/origin/<branch>`` in place -- the exact condition
        under which ``reset --hard origin/<branch>`` still 'succeeds'."""
        self.origin.rename(self.root / "origin-gone.git")

    # -- driver -------------------------------------------------------
    def run_step4(self, timeout: int = 60) -> subprocess.CompletedProcess:
        drv = self.root / "driver.sh"
        drv.write_text(
            textwrap.dedent(
                f"""
                #!/usr/bin/env bash
                set -u
                source "{self.bootstrap}" >/dev/null 2>&1
                step_4_repo_clone
                echo "rc=$?"
                """
            ).strip()
            + "\n"
        )
        _make_executable(drv)
        return subprocess.run(
            ["bash", str(drv)],
            env={
                **os.environ,
                **GIT_ENV,
                "WAKIR_REPO_ROOT": str(self.node),
                "WAKIR_REPO_BRANCH": self.BRANCH,
                "WAKIR_REPO_PROVENANCE_FILE": str(self.root / "provenance.env"),
                "WAKIR_SKIP_PROMPTS": "1",
            },
            capture_output=True,
            text=True,
            timeout=timeout,
        )


@pytest.fixture
def node(tmp_path: Path) -> NodeRepo:
    return NodeRepo(tmp_path)


def _rc(proc: subprocess.CompletedProcess) -> int:
    m = re.search(r"^rc=(\d+)$", proc.stdout, re.MULTILINE)
    assert m is not None, f"driver printed no rc line:\n{proc.stdout}\n{proc.stderr}"
    return int(m.group(1))


# ---------------------------------------------------------------------------
# TV-S4F-1..4: a failed fetch is a failed step.
# ---------------------------------------------------------------------------


def test_failed_fetch_returns_nonzero(node: NodeRepo) -> None:
    """TV-S4F-1. The remote is gone. The step must not return 0."""
    node.commit_on_node("a fix to be measured\n")
    node.break_remote()

    proc = node.run_step4()

    assert _rc(proc) != 0, (
        "a step that could not reach the remote reported success; the "
        "exit status of `reset --hard` had overwritten the exit status "
        "of `fetch`.\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )


def test_failed_fetch_does_not_reset_the_checkout(node: NodeRepo) -> None:
    """TV-S4F-2. The stale remote-tracking ref is still on disk and
    ``reset --hard origin/<branch>`` would happily use it. It must not
    be used: the tree stays as the operator left it, and the step says
    it failed rather than quietly discarding the work."""
    injected = node.commit_on_node("a fix to be measured\n")
    node.break_remote()

    node.run_step4()

    assert node.head() == injected, (
        "the checkout was reset to a stale remote-tracking ref after the "
        "fetch failed; whatever was on the node is gone and nothing in "
        "the log said so."
    )
    assert (node.node / "INJECTED.md").is_file()


def test_failed_fetch_does_not_claim_an_update(node: NodeRepo) -> None:
    """TV-S4F-3. The success line is evidence downstream. It must not
    appear for an update that did not happen."""
    node.commit_on_node("a fix to be measured\n")
    node.break_remote()

    proc = node.run_step4()

    assert "repo updated to origin/" not in proc.stdout, (
        "the step logged a successful update after the fetch failed:\n"
        f"{proc.stdout}"
    )


def test_failed_fetch_surfaces_the_git_error(node: NodeRepo) -> None:
    """TV-S4F-4. ``>/dev/null 2>&1`` on all three calls meant the
    operator got no reason. The reason is the difference between a
    five-minute fix and a twenty-minute run with no evidence."""
    node.commit_on_node("a fix to be measured\n")
    node.break_remote()

    proc = node.run_step4()
    combined = proc.stdout + proc.stderr

    assert "git fetch failed" in combined, (
        f"no named failure in the output:\n{combined}"
    )
    assert re.search(r"repository|not found|does not appear", combined, re.I), (
        "git's own diagnostic was discarded; the operator is told that "
        f"something failed but not what:\n{combined}"
    )


# ---------------------------------------------------------------------------
# TV-S4F-5: negative control.
# ---------------------------------------------------------------------------


def test_reachable_remote_still_updates_the_checkout(node: NodeRepo) -> None:
    """TV-S4F-5. NEGATIVE CONTROL. The guard must leave the normal path
    exactly as it was: a reachable remote updates the checkout to the
    branch tip and returns 0."""
    tip = node.advance_remote("moved on\n")
    assert node.head() != tip

    proc = node.run_step4()

    assert _rc(proc) == 0, f"{proc.stdout}\n{proc.stderr}"
    assert node.head() == tip, (
        "the checkout was not advanced to the remote tip; the guard "
        "broke the path it was supposed to leave alone."
    )
    assert "repo updated to origin/main" in proc.stdout


# ---------------------------------------------------------------------------
# TV-S4F-6: mutation control.
# ---------------------------------------------------------------------------


PRE_FIX_STEP_4 = textwrap.dedent(
    """
    step_4_repo_clone() {
      log_step 4 "$TOTAL_STEPS" "Repo klonen nach ${WAKIR_REPO_ROOT}"

      if [[ -d "${WAKIR_REPO_ROOT}/.git" ]]; then
        log_ok "repo already present; fetching latest on ${WAKIR_REPO_BRANCH}"
        (
          cd "$WAKIR_REPO_ROOT"
          "$WAKIR_BOOTSTRAP_GIT" fetch --depth 1 origin "$WAKIR_REPO_BRANCH" \\
            >/dev/null 2>&1
          "$WAKIR_BOOTSTRAP_GIT" checkout "$WAKIR_REPO_BRANCH" >/dev/null 2>&1
          "$WAKIR_BOOTSTRAP_GIT" reset --hard "origin/${WAKIR_REPO_BRANCH}" \\
            >/dev/null 2>&1
        ) || { log_err "git fetch/reset failed"; return 2; }
        log_ok "repo updated to origin/${WAKIR_REPO_BRANCH}"
        return 0
      fi
      return 2
    }
    """
).strip()


def test_mutation_control_pre_fix_form_reproduces_the_defect(
    tmp_path: Path,
) -> None:
    """TV-S4F-6. MUTATION CONTROL. Append the pre-fix definition of
    ``step_4_repo_clone`` to a copy of the bootstrap -- the later
    definition wins in bash -- and run TV-S4F-1's scenario against it.

    It must return 0 and log the success line. If this test ever goes
    red, the vectors above are passing for some reason other than the
    guard, and they are worth nothing."""
    mutated = tmp_path / "bootstrap-pre-fix.sh"
    mutated.write_text(
        BOOTSTRAP.read_text() + "\n\n# --- mutation ---\n" + PRE_FIX_STEP_4 + "\n"
    )
    _make_executable(mutated)

    substrate = tmp_path / "substrate"
    substrate.mkdir()
    node = NodeRepo(substrate, bootstrap=mutated)
    node.commit_on_node("a fix to be measured\n")
    node.break_remote()

    proc = node.run_step4()

    assert _rc(proc) == 0, (
        "the pre-fix form did NOT reproduce the defect, so the vectors "
        "above are not measuring the guard.\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    assert "repo updated to origin/main" in proc.stdout, (
        "the pre-fix form did not emit the false success line; the "
        f"mutation is not the defect:\n{proc.stdout}"
    )
