# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic behaviour tests for the tree an acceptance run measured, and
for the run's obligation to say which tree that was.

The defect
----------

Step 4 of the bootstrap ended with ``reset --hard origin/<branch>``,
unconditionally, on every run. The live-VM acceptance lane calls the
full bootstrap, so the lane could measure exactly one thing: what was
already on the branch. A change could not be measured on the substrate
before it was merged.

Measured, 2026-09-22: a branch state placed on a substrate node to
verify a convergence fix was reset away by step 4 before the step under
test ran. The run then exercised baseline code, logged ``already
active`` for the thing it was supposed to prove, and hung twenty
minutes later on a service the reverted unit had put back into a crash
loop -- while the same log reported that service as started. No
evidence in either direction.

The order was therefore backwards: believe, merge, then measure.

The fix, and the part that matters more than the switch
-------------------------------------------------------

``WAKIR_REPO_REF_MODE`` lets step 4 pin a ref or leave the checkout
alone. That is the easy half. The hard half is that an acceptance report
you cannot tell apart from a canonical one is *worse* than the state it
replaces -- before, at least everyone knew it was always the branch. So:

  * step 4 measures the tree it ends up with, and writes a provenance
    record. The verdict is measured, never taken from the mode flag: a
    pin that lands on the branch tip is canonical, a track-remote run
    whose comparison could not be made is not.
  * the acceptance lanes read the record back, print which tree the run
    used on every path including the failure paths, and finish a
    non-canonical run as ``NOT EVIDENCE`` with exit 10 instead of
    ``PASS`` -- with the regression list omitted, because that list is
    what gets quoted afterwards.
  * the record carries a per-run nonce, so a record left behind by an
    earlier run cannot be read as a statement about this one.

Test-Vector index
-----------------

Step 4 behaviour, against a real ``git`` and a bare remote in tmp_path:

  * ``TV-PROV-1``  track-remote (default) lands on the branch tip and
    records ``canonical=yes``.
  * ``TV-PROV-2``  keep leaves an injected commit on the node alone --
    RED before the fix, because step 4 reset it away -- and records
    ``canonical=no``.
  * ``TV-PROV-3``  pin moves the checkout to the requested ref and
    records ``canonical=no`` when that ref is not the branch tip.
  * ``TV-PROV-4``  pin onto the branch tip records ``canonical=yes``.
    The verdict is a measurement, not a restatement of the mode.
  * ``TV-PROV-5``  a clean-tip checkout with an edited file on the node
    records ``canonical=no``. This is the shape that would otherwise
    hand out a PASS for a tree nobody can reconstruct.
  * ``TV-PROV-6``  NEGATIVE CONTROL against the mechanism being gameable
    in the useful direction: keep-mode with an unreachable remote cannot
    compare, and records ``canonical=no`` rather than defaulting to yes.
  * ``TV-PROV-7``  the run-id the caller passes in comes back in the
    record.
  * ``TV-PROV-8``  an unwritable record fails the step. A run that
    cannot be attributed to a tree must not proceed as if it could.
  * ``TV-PROV-9``  misconfiguration is refused up front: an unknown
    ref-mode, pin without a ref, and a ref without pin-mode.

Reader behaviour (``scripts/lib/repo-provenance.sh``):

  * ``TV-PROV-10`` a canonical record for this run is evidence.
  * ``TV-PROV-11`` a record from a different run is ``stale`` and is not
    evidence -- the vector that keeps a leftover file from making a
    fresh run look canonical.
  * ``TV-PROV-12`` no record at all is ``missing`` and is not evidence.
    Absence of a measurement is not a measurement.
  * ``TV-PROV-13`` a ``canonical=no`` record is not evidence and its
    reason survives into the printed line.
  * ``TV-PROV-14`` an unknown schema is not evidence.
  * ``TV-PROV-15`` CONTROL for TV-PROV-11: loading the same stale record
    *without* a run-id reports it as canonical. The nonce is what makes
    the difference, and this vector is what says so.
  * ``TV-PROV-16`` every field step 4 writes is a field the reader
    consumes -- one writer, one reader, driven end to end rather than
    compared by eye.

Lane wiring (drift guards; they supplement the vectors above and do not
replace them -- see the module's limits in the report):

  * ``TV-PROV-17`` both acceptance entry points source the reader, hand
    the nonce to the bootstrap, print the tree line, and gate their PASS
    banner on the verdict.
  * ``TV-PROV-18`` the federation lane's not-evidence exit comes before
    its regression list, so the list cannot be printed for a run that
    does not count.

Mutation control:

  * ``TV-PROV-19`` with the pre-fix step 4 restored in a copy of the
    bootstrap, keep-mode resets the node anyway and leaves no record --
    the 2026-09-22 state, reproduced. If it ever goes green, TV-PROV-2
    is passing for some reason other than the fix.

Sandbox boundary
----------------

No network, no root, no systemd, no podman, no substrate. ``git`` runs
only against paths under ``tmp_path``. The bootstrap is sourced (its
``BASH_SOURCE`` main-gate makes that safe) and ``step_4_repo_clone`` is
called directly; the reader is sourced into a driver and its functions
are called directly.

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
PROVENANCE_LIB = REPO_ROOT / "scripts" / "lib" / "repo-provenance.sh"
FED_ACCEPTANCE = REPO_ROOT / "scripts" / "federation-live-vm-acceptance.sh"
CANONICAL_ACCEPTANCE = (
    REPO_ROOT / "scripts" / "acceptance" / "wakir-pilot-acceptance.sh"
)

GIT_ENV = {
    "GIT_AUTHOR_NAME": "bootstrap-test",
    "GIT_AUTHOR_EMAIL": "bootstrap-test@example.invalid",
    "GIT_COMMITTER_NAME": "bootstrap-test",
    "GIT_COMMITTER_EMAIL": "bootstrap-test@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}

RUN_ID = "run-test-0001"


def _make_executable(path: Path) -> None:
    path.chmod(
        path.stat().st_mode
        | stat_mod.S_IXUSR
        | stat_mod.S_IXGRP
        | stat_mod.S_IXOTH
    )


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
        f"git {' '.join(args)} failed in {cwd}:\n{proc.stdout}\n{proc.stderr}"
    )
    return proc.stdout.strip()


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class Substrate:
    """A bare remote plus a checkout, both under tmp_path, and a driver
    that calls the real ``step_4_repo_clone``."""

    BRANCH = "main"

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.origin = tmp_path / "origin.git"
        self.node = tmp_path / "node"
        self.provenance = tmp_path / "provenance.env"

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

    # -- substrate state ----------------------------------------------
    def head(self) -> str:
        return _git(self.node, "rev-parse", "HEAD")

    def origin_tip(self) -> str:
        return _git(self.origin, "rev-parse", self.BRANCH)

    def commit_on_node(self, text: str) -> str:
        """Work placed on the node that the branch does not have."""
        (self.node / "INJECTED.md").write_text(text)
        _git(self.node, "add", "INJECTED.md")
        _git(self.node, "commit", "-m", "injected change to be measured")
        return self.head()

    def edit_on_node(self, text: str) -> None:
        """An in-place edit, uncommitted -- the operator who patched a
        config on the node and then ran acceptance."""
        (self.node / "README.md").write_text(text)

    def advance_remote(self, text: str) -> str:
        (self.seed / "README.md").write_text(text)
        _git(self.seed, "add", "README.md")
        _git(self.seed, "commit", "-m", "remote moves on")
        _git(self.seed, "push", "origin", self.BRANCH)
        return self.origin_tip()

    def side_branch(self, name: str, text: str) -> str:
        """A ref on the remote that is not the branch tip -- the shape of
        a change under review."""
        _git(self.seed, "checkout", "-b", name)
        (self.seed / "SIDE.md").write_text(text)
        _git(self.seed, "add", "SIDE.md")
        _git(self.seed, "commit", "-m", "change under review")
        sha = _git(self.seed, "rev-parse", "HEAD")
        _git(self.seed, "push", "origin", name)
        _git(self.seed, "checkout", self.BRANCH)
        return sha

    def break_remote(self) -> None:
        self.origin.rename(self.root / "origin-gone.git")

    # -- drivers ------------------------------------------------------
    def run_step4(self, **env: str) -> subprocess.CompletedProcess:
        drv = self.root / "driver-step4.sh"
        drv.write_text(
            textwrap.dedent(
                f"""
                #!/usr/bin/env bash
                set -u
                source "{BOOTSTRAP}" >/dev/null 2>&1
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
                "WAKIR_REPO_PROVENANCE_FILE": str(self.provenance),
                "WAKIR_PROVENANCE_RUN_ID": RUN_ID,
                "WAKIR_SKIP_PROMPTS": "1",
                **env,
            },
            capture_output=True,
            text=True,
            timeout=90,
        )

    def record(self) -> dict[str, str]:
        assert self.provenance.is_file(), "step 4 wrote no provenance record"
        out: dict[str, str] = {}
        for line in self.provenance.read_text().splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            out[key] = val
        return out


@pytest.fixture
def sub(tmp_path: Path) -> Substrate:
    return Substrate(tmp_path)


def _rc(proc: subprocess.CompletedProcess) -> int:
    m = re.search(r"^rc=(\d+)$", proc.stdout, re.MULTILINE)
    assert m is not None, (
        f"driver printed no rc line:\n{proc.stdout}\n{proc.stderr}"
    )
    return int(m.group(1))


def _run_reader(
    tmp_path: Path,
    record_text: str | None,
    expect_run_id: str,
) -> subprocess.CompletedProcess:
    """Source the shipped reader and call its real functions."""
    rec = tmp_path / "reader-record.env"
    if record_text is not None:
        rec.write_text(record_text)
    drv = tmp_path / "driver-reader.sh"
    drv.write_text(
        textwrap.dedent(
            f"""
            #!/usr/bin/env bash
            set -u
            source "{PROVENANCE_LIB}"
            wakir_provenance_load "{expect_run_id}"
            echo "load_rc=$?"
            echo "status=${{WAKIR_PROVENANCE_STATUS}}"
            if wakir_provenance_is_evidence; then
              echo "evidence=yes"
            else
              echo "evidence=no"
            fi
            echo "line=$(wakir_provenance_tree_line)"
            echo "not_evidence_rc=${{WAKIR_PROVENANCE_NOT_EVIDENCE_RC}}"
            """
        ).strip()
        + "\n"
    )
    _make_executable(drv)
    return subprocess.run(
        ["bash", str(drv)],
        env={**os.environ, "WAKIR_REPO_PROVENANCE_FILE": str(rec)},
        capture_output=True,
        text=True,
        timeout=30,
    )


def _field(proc: subprocess.CompletedProcess, key: str) -> str:
    m = re.search(rf"^{key}=(.*)$", proc.stdout, re.MULTILINE)
    assert m is not None, f"{key} not in driver output:\n{proc.stdout}\n{proc.stderr}"
    return m.group(1)


CANONICAL_RECORD = textwrap.dedent(
    f"""
    # a record
    WAKIR_PROVENANCE_SCHEMA=wakir-runtime/repo-provenance@1
    WAKIR_PROVENANCE_RUN_ID={RUN_ID}
    WAKIR_PROVENANCE_WRITTEN_UTC=2026-09-22T10:00:00Z
    WAKIR_PROVENANCE_REPO_ROOT=/opt/wakir-runtime
    WAKIR_PROVENANCE_BRANCH=main
    WAKIR_PROVENANCE_REF_MODE=track-remote
    WAKIR_PROVENANCE_REQUESTED_REF=main
    WAKIR_PROVENANCE_HEAD=1111111111111111111111111111111111111111
    WAKIR_PROVENANCE_REMOTE_TIP=1111111111111111111111111111111111111111
    WAKIR_PROVENANCE_WORKTREE=clean
    WAKIR_PROVENANCE_CANONICAL=yes
    WAKIR_PROVENANCE_REASON=HEAD is the origin/main tip and the worktree is clean
    """
).strip() + "\n"


# ---------------------------------------------------------------------------
# TV-PROV-1..9: step 4 behaviour.
# ---------------------------------------------------------------------------


def test_track_remote_lands_on_the_branch_tip(sub: Substrate) -> None:
    """TV-PROV-1. The default path is unchanged and is the one that
    produces evidence."""
    tip = sub.advance_remote("moved on\n")

    proc = sub.run_step4()

    assert _rc(proc) == 0, f"{proc.stdout}\n{proc.stderr}"
    assert sub.head() == tip
    rec = sub.record()
    assert rec["WAKIR_PROVENANCE_CANONICAL"] == "yes", rec
    assert rec["WAKIR_PROVENANCE_REF_MODE"] == "track-remote"
    assert rec["WAKIR_PROVENANCE_HEAD"] == tip
    assert rec["WAKIR_PROVENANCE_WORKTREE"] == "clean"


def test_keep_mode_does_not_reset_the_node(sub: Substrate) -> None:
    """TV-PROV-2. The 2026-09-22 case. Work is placed on the node to be
    measured; step 4 must leave it there.

    This is the vector that is red before the fix: step 4 reset to the
    branch tip whatever the caller wanted, so the run measured baseline
    code and said nothing about the change."""
    injected = sub.commit_on_node("the fix under test\n")

    proc = sub.run_step4(WAKIR_REPO_REF_MODE="keep")

    assert _rc(proc) == 0, f"{proc.stdout}\n{proc.stderr}"
    assert sub.head() == injected, (
        "step 4 reset the checkout although it was told to keep it; the "
        "change to be measured is gone and the run measures the branch."
    )
    assert (sub.node / "INJECTED.md").is_file()

    rec = sub.record()
    assert rec["WAKIR_PROVENANCE_REF_MODE"] == "keep"
    assert rec["WAKIR_PROVENANCE_HEAD"] == injected
    assert rec["WAKIR_PROVENANCE_CANONICAL"] == "no", (
        "a run against an injected tree was recorded as canonical; the "
        "switch would then produce reports indistinguishable from real "
        f"acceptance evidence. record={rec}"
    )
    assert rec["WAKIR_PROVENANCE_REMOTE_TIP"] == sub.origin_tip()
    assert "not the origin/main tip" in rec["WAKIR_PROVENANCE_REASON"]


def test_pin_mode_moves_to_the_requested_ref(sub: Substrate) -> None:
    """TV-PROV-3. A change under review, fetched by ref and measured
    before it is merged -- the workflow the old step 4 made impossible."""
    review = sub.side_branch("change-under-review", "under review\n")

    proc = sub.run_step4(
        WAKIR_REPO_REF_MODE="pin", WAKIR_REPO_REF="change-under-review"
    )

    assert _rc(proc) == 0, f"{proc.stdout}\n{proc.stderr}"
    assert sub.head() == review
    assert (sub.node / "SIDE.md").is_file()

    rec = sub.record()
    assert rec["WAKIR_PROVENANCE_REF_MODE"] == "pin"
    assert rec["WAKIR_PROVENANCE_REQUESTED_REF"] == "change-under-review"
    assert rec["WAKIR_PROVENANCE_CANONICAL"] == "no", rec


def test_pin_onto_the_branch_tip_is_canonical(sub: Substrate) -> None:
    """TV-PROV-4. The verdict is measured, not declared.

    Reading it off the mode flag would have been simpler and would have
    been one more check that reports what it was told. Pinning the
    branch tip *is* the branch tip, and the record says so."""
    tip = sub.advance_remote("moved on\n")

    proc = sub.run_step4(WAKIR_REPO_REF_MODE="pin", WAKIR_REPO_REF="main")

    assert _rc(proc) == 0, f"{proc.stdout}\n{proc.stderr}"
    assert sub.head() == tip
    rec = sub.record()
    assert rec["WAKIR_PROVENANCE_REF_MODE"] == "pin"
    assert rec["WAKIR_PROVENANCE_CANONICAL"] == "yes", (
        "a pin that landed exactly on the branch tip was reported as "
        f"non-canonical; the verdict is following the flag, not the tree. {rec}"
    )


def test_dirty_worktree_on_the_tip_is_not_canonical(sub: Substrate) -> None:
    """TV-PROV-5. HEAD is the tip and the tree still is not what the tip
    says. An edit made on the node by hand is exactly how the substrate
    and the branch drift apart without a commit to point at."""
    proc = sub.run_step4()
    assert _rc(proc) == 0
    assert sub.record()["WAKIR_PROVENANCE_CANONICAL"] == "yes"

    sub.edit_on_node("patched on the node\n")
    proc = sub.run_step4(WAKIR_REPO_REF_MODE="keep")

    assert _rc(proc) == 0, f"{proc.stdout}\n{proc.stderr}"
    rec = sub.record()
    assert rec["WAKIR_PROVENANCE_WORKTREE"] == "dirty"
    assert rec["WAKIR_PROVENANCE_CANONICAL"] == "no", (
        "HEAD matched the tip and the verdict stopped looking; the files "
        f"the run actually used were not the ones the tip names. {rec}"
    )


def test_unmeasurable_tree_is_never_canonical(sub: Substrate) -> None:
    """TV-PROV-6. NEGATIVE CONTROL on the direction of failure.

    keep-mode fetches only to compare. With the remote unreachable there
    is nothing to compare against, and the answer must be "not
    canonical" -- never "canonical because nothing objected"."""
    sub.break_remote()
    _git(sub.node, "update-ref", "-d", "refs/remotes/origin/main")

    proc = sub.run_step4(WAKIR_REPO_REF_MODE="keep")

    assert _rc(proc) == 0, f"{proc.stdout}\n{proc.stderr}"
    rec = sub.record()
    assert rec["WAKIR_PROVENANCE_REMOTE_TIP"] == "unknown", rec
    assert rec["WAKIR_PROVENANCE_CANONICAL"] == "no", (
        "a tree that could not be compared against anything was recorded "
        f"as canonical. {rec}"
    )


def test_record_carries_the_callers_run_id(sub: Substrate) -> None:
    """TV-PROV-7. The nonce is what separates this run's record from the
    one an earlier run left behind."""
    proc = sub.run_step4()
    assert _rc(proc) == 0
    assert sub.record()["WAKIR_PROVENANCE_RUN_ID"] == RUN_ID


def test_unwritable_record_fails_the_step(sub: Substrate) -> None:
    """TV-PROV-8. A run that cannot be attributed to a tree must not
    continue as though it could. The record is load-bearing, so failing
    to write it is a failed step."""
    blocked = sub.root / "blocked"
    blocked.write_text("not a directory\n")

    proc = sub.run_step4(
        WAKIR_REPO_PROVENANCE_FILE=str(blocked / "sub" / "provenance.env")
    )

    assert _rc(proc) != 0, (
        "step 4 could not record which tree it produced and reported "
        f"success anyway:\n{proc.stdout}\n{proc.stderr}"
    )


@pytest.mark.parametrize(
    "env,needle",
    [
        ({"WAKIR_REPO_REF_MODE": "whatever"}, "WAKIR_REPO_REF_MODE must be"),
        ({"WAKIR_REPO_REF_MODE": "pin"}, "requires WAKIR_REPO_REF"),
        (
            {"WAKIR_REPO_REF_MODE": "track-remote", "WAKIR_REPO_REF": "x"},
            "would be ignored",
        ),
        (
            {"WAKIR_REPO_REF_MODE": "pin", "WAKIR_REPO_REF": "--upload-pack=x"},
            "must not start with",
        ),
    ],
)
def test_misconfiguration_is_refused_up_front(
    sub: Substrate, env: dict[str, str], needle: str
) -> None:
    """TV-PROV-9. A ref that would be silently ignored is the same defect
    class in miniature: the operator believes the run is pinned while it
    is not. All four shapes are rejected before anything runs."""
    drv = sub.root / "driver-cfg.sh"
    drv.write_text(
        textwrap.dedent(
            f"""
            #!/usr/bin/env bash
            set -u
            source "{BOOTSTRAP}" >/dev/null
            echo "sourced-ok"
            """
        ).strip()
        + "\n"
    )
    _make_executable(drv)
    proc = subprocess.run(
        ["bash", str(drv)],
        env={
            **os.environ,
            **GIT_ENV,
            "WAKIR_REPO_ROOT": str(sub.node),
            "WAKIR_REPO_BRANCH": "main",
            "WAKIR_REPO_PROVENANCE_FILE": str(sub.provenance),
            "WAKIR_SKIP_PROMPTS": "1",
            **env,
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "sourced-ok" not in proc.stdout, (
        f"the bootstrap accepted {env}:\n{proc.stdout}\n{proc.stderr}"
    )
    assert needle in proc.stderr, f"{env}: {proc.stderr}"


# ---------------------------------------------------------------------------
# TV-PROV-10..16: the reader.
# ---------------------------------------------------------------------------


def test_canonical_record_is_evidence(tmp_path: Path) -> None:
    """TV-PROV-10."""
    proc = _run_reader(tmp_path, CANONICAL_RECORD, RUN_ID)
    assert _field(proc, "status") == "canonical"
    assert _field(proc, "evidence") == "yes"
    assert "1111111111" in _field(proc, "line")
    assert _field(proc, "not_evidence_rc") == "10"


def test_a_record_from_another_run_is_not_evidence(tmp_path: Path) -> None:
    """TV-PROV-11. A leftover record from last week describes last week's
    tree. Reading it as this run's would reintroduce the whole defect
    one level up: a verdict about a tree nobody measured."""
    proc = _run_reader(tmp_path, CANONICAL_RECORD, "run-test-0002")
    assert _field(proc, "status") == "stale", proc.stdout
    assert _field(proc, "evidence") == "no"
    assert "UNKNOWN" in _field(proc, "line")


def test_a_missing_record_is_not_evidence(tmp_path: Path) -> None:
    """TV-PROV-12. An older bootstrap on the node writes no record. The
    absence of a measurement is not a passing measurement."""
    proc = _run_reader(tmp_path, None, RUN_ID)
    assert _field(proc, "status") == "missing", proc.stdout
    assert _field(proc, "evidence") == "no"


def test_a_non_canonical_record_carries_its_reason(tmp_path: Path) -> None:
    """TV-PROV-13. The reason is the whole point: a reader of the report
    must be able to tell *what* the run measured instead."""
    rec = CANONICAL_RECORD.replace(
        "WAKIR_PROVENANCE_CANONICAL=yes", "WAKIR_PROVENANCE_CANONICAL=no"
    ).replace(
        "WAKIR_PROVENANCE_REASON=HEAD is the origin/main tip and the worktree is clean",
        "WAKIR_PROVENANCE_REASON=HEAD abc is not the origin/main tip def",
    )
    proc = _run_reader(tmp_path, rec, RUN_ID)
    assert _field(proc, "status") == "non-canonical"
    assert _field(proc, "evidence") == "no"
    assert "HEAD abc is not the origin/main tip def" in _field(proc, "line")


def test_an_unknown_schema_is_not_evidence(tmp_path: Path) -> None:
    """TV-PROV-14. Guessing at an unfamiliar shape is how a reader ends
    up reporting its own defaults as a measurement."""
    rec = CANONICAL_RECORD.replace(
        "repo-provenance@1", "repo-provenance@99"
    )
    proc = _run_reader(tmp_path, rec, RUN_ID)
    assert _field(proc, "status") == "schema-mismatch"
    assert _field(proc, "evidence") == "no"


def test_control_without_a_run_id_the_stale_record_passes(
    tmp_path: Path,
) -> None:
    """TV-PROV-15. CONTROL for TV-PROV-11. The same stale record, loaded
    without a nonce, is reported as canonical. That is what the nonce
    buys, stated as a behaviour rather than as a comment."""
    proc = _run_reader(tmp_path, CANONICAL_RECORD, "")
    assert _field(proc, "status") == "canonical", proc.stdout
    assert _field(proc, "evidence") == "yes"


def test_every_field_the_writer_emits_reaches_the_reader(
    sub: Substrate,
) -> None:
    """TV-PROV-16. One writer, one reader, driven end to end: step 4
    produces a real record and the shipped reader consumes it. A key the
    writer emits and the reader drops would otherwise be invisible until
    a report was missing the field that mattered."""
    assert _rc(sub.run_step4()) == 0
    written = sub.record()

    drv = sub.root / "driver-roundtrip.sh"
    drv.write_text(
        textwrap.dedent(
            f"""
            #!/usr/bin/env bash
            set -u
            source "{PROVENANCE_LIB}"
            wakir_provenance_load "{RUN_ID}" || true
            for k in {" ".join(sorted(written))}; do
              printf 'got:%s=%s\\n' "$k" "${{!k}}"
            done
            """
        ).strip()
        + "\n"
    )
    _make_executable(drv)
    proc = subprocess.run(
        ["bash", str(drv)],
        env={
            **os.environ,
            "WAKIR_REPO_PROVENANCE_FILE": str(sub.provenance),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    read_back = dict(
        line[len("got:") :].split("=", 1)
        for line in proc.stdout.splitlines()
        if line.startswith("got:")
    )
    assert read_back == written, (
        "the reader did not round-trip every field step 4 wrote:\n"
        f"written={written}\nread={read_back}"
    )


# ---------------------------------------------------------------------------
# TV-PROV-17..18: lane wiring. Drift guards -- they supplement the
# vectors above. The acceptance scripts refuse to run off a substrate
# (root, podman, systemd), so their wiring is asserted on the source and
# their decision logic is tested through the reader, above.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script", [FED_ACCEPTANCE, CANONICAL_ACCEPTANCE], ids=lambda p: p.name
)
def test_acceptance_entry_points_are_wired_to_the_verdict(script: Path) -> None:
    """TV-PROV-17."""
    body = script.read_text()
    syntax = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True, timeout=30
    )
    assert syntax.returncode == 0, syntax.stderr

    assert "scripts/lib/repo-provenance.sh" in body, (
        f"{script.name} does not source the provenance reader"
    )
    assert "wakir_provenance_new_run_id" in body, (
        f"{script.name} does not mint a run-id, so a leftover record from "
        "an earlier run would be read as this run's"
    )
    assert "WAKIR_PROVENANCE_RUN_ID=" in body, (
        f"{script.name} does not hand the run-id to the bootstrap"
    )
    assert "WAKIR_REPO_REF_MODE=" in body, (
        f"{script.name} does not forward the ref-mode, so the lane cannot "
        "measure anything but the branch"
    )
    assert "wakir_provenance_tree_line" in body, (
        f"{script.name} never prints which tree the run used"
    )
    assert "wakir_provenance_is_evidence" in body, (
        f"{script.name} does not gate its verdict on the tree"
    )
    assert "NOT EVIDENCE" in body, (
        f"{script.name} has no distinct outcome for a run that passed "
        "against a tree that is not the branch"
    )
    assert 'exit "$WAKIR_PROVENANCE_NOT_EVIDENCE_RC"' in body, (
        f"{script.name} does not exit with the not-evidence code; a "
        "caller reading only the exit status would see a pass"
    )


def test_the_regression_list_is_not_printed_for_a_non_evidence_run() -> None:
    """TV-PROV-18. The seven ``regression-tested: clean`` lines are what
    gets quoted afterwards. They must be unreachable for a run that did
    not measure the branch, so the not-evidence exit has to come first."""
    body = FED_ACCEPTANCE.read_text()
    exit_at = body.index('exit "$WAKIR_PROVENANCE_NOT_EVIDENCE_RC"')
    first_claim = body.index(
        'log "Bug-30 (named-block-syntax) regression-tested: clean"'
    )
    assert exit_at < first_claim, (
        "the not-evidence exit comes after the regression list, so a run "
        "against an unknown tree still prints seven claims about it"
    )


# ---------------------------------------------------------------------------
# TV-PROV-19: mutation control for the measurability half.
# ---------------------------------------------------------------------------


PRE_FIX_STEP_4 = textwrap.dedent(
    """
    step_4_repo_clone() {
      log_step 4 "$TOTAL_STEPS" "Repo klonen nach ${WAKIR_REPO_ROOT}"
      if [[ -d "${WAKIR_REPO_ROOT}/.git" ]]; then
        log_ok "repo already present; fetching latest on ${WAKIR_REPO_BRANCH}"
        _git_repo "fetch" fetch --depth 1 origin "$WAKIR_REPO_BRANCH" >/dev/null \\
          || return 2
        _git_repo "checkout" checkout "$WAKIR_REPO_BRANCH" >/dev/null || return 2
        _git_repo "reset" reset --hard "origin/${WAKIR_REPO_BRANCH}" >/dev/null \\
          || return 2
        log_ok "repo updated to origin/${WAKIR_REPO_BRANCH}"
        return 0
      fi
      return 2
    }
    """
).strip()


def test_mutation_control_pre_fix_step_4_wipes_the_node(tmp_path: Path) -> None:
    """TV-PROV-19. MUTATION CONTROL for TV-PROV-2.

    Append the pre-fix ``step_4_repo_clone`` to a copy of the bootstrap
    -- the later definition wins in bash -- and ask it to keep the node.
    It resets the checkout anyway, and leaves no record of which tree the
    run is about to use. That is the state the acceptance lane was in on
    2026-09-22: the change under test was gone before the steps that were
    supposed to exercise it ran, and nothing in the output said so.

    If this ever goes green, TV-PROV-2 is passing for some reason other
    than the fix."""
    mutated = tmp_path / "bootstrap-pre-fix.sh"
    mutated.write_text(
        BOOTSTRAP.read_text() + "\n\n# --- mutation ---\n" + PRE_FIX_STEP_4 + "\n"
    )
    _make_executable(mutated)

    substrate_dir = tmp_path / "substrate"
    substrate_dir.mkdir()
    sub = Substrate(substrate_dir)
    injected = sub.commit_on_node("the fix under test\n")
    tip = sub.origin_tip()

    drv = sub.root / "driver-mutation.sh"
    drv.write_text(
        textwrap.dedent(
            f"""
            #!/usr/bin/env bash
            set -u
            source "{mutated}" >/dev/null 2>&1
            step_4_repo_clone
            echo "rc=$?"
            """
        ).strip()
        + "\n"
    )
    _make_executable(drv)
    proc = subprocess.run(
        ["bash", str(drv)],
        env={
            **os.environ,
            **GIT_ENV,
            "WAKIR_REPO_ROOT": str(sub.node),
            "WAKIR_REPO_BRANCH": "main",
            "WAKIR_REPO_REF_MODE": "keep",
            "WAKIR_REPO_PROVENANCE_FILE": str(sub.provenance),
            "WAKIR_PROVENANCE_RUN_ID": RUN_ID,
            "WAKIR_SKIP_PROMPTS": "1",
        },
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert _rc(proc) == 0, f"{proc.stdout}\n{proc.stderr}"
    assert sub.head() == tip and sub.head() != injected, (
        "the pre-fix form did not reset the node, so TV-PROV-2 is not "
        f"measuring the fix.\n{proc.stdout}\n{proc.stderr}"
    )
    assert not (sub.node / "INJECTED.md").exists()
    assert not sub.provenance.exists(), (
        "the pre-fix form left a provenance record; the mutation is not "
        "the defect"
    )
