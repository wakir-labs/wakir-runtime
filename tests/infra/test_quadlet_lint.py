# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic acceptance tests for the Sprint-9-Tag-9 Bug-23 Quadlet-Lint
substance-fix (``infra/spire/federation/bin/wakir-quadlet-lint.sh``).

Context
-------

The Pilot-VM bring-up has hit a "Live-Bring-up-Sandbox-Gap" four
iterations in a row (Bugs 20/21/22 and counting). Each time the
hermetic test surface gave green, the live VM reproduced a new
substance bug that should have been catchable at PR-time. AR Fred
rejected ADR-0060 (Live-VM-CI-Gate) for budget reasons ("kein Geld"),
so the Tag-9 cleanup has to close the gap via cost-free static
analysis.

The Quadlet-Lint script wraps ``/usr/libexec/podman/quadlet --dryrun``
against a substituted snapshot of the Wakir Quadlet inventory — both
``wakir`` and ``partner`` sides — and reports any structural error
(missing volume reference, malformed ``Volume=`` syntax, broken
Image= pin, etc.). It is free, fast, runs in any ubuntu-latest
GitHub-Actions runner with ``podman`` installed, and catches the
exact class of bugs that the last four iterations have leaked
through.

Test-Vector index
-----------------

  * ``TV-S9T9-23a`` Lint script exits 0 on the unmodified repo. Drift-
    guard: if any future PR introduces a Quadlet-source mismatch,
    this gate reds before merge.
  * ``TV-S9T9-23b`` Mutation: rewrite one ``Volume=`` reference to a
    non-existent volume name in a temp-copy of the repo; lint MUST
    exit non-zero AND name the bogus reference in its stderr.
  * ``TV-S9T9-23c`` Mutation: corrupt the ``[Container]`` section of
    a unit by removing the ``Image=`` directive; lint MUST exit
    non-zero. Different failure mode from 23b so the test exercises
    a second branch of the quadlet generator.
  * ``TV-S9T9-23d`` Exit-3 envelope: when the podman quadlet binary
    is absent (CI runner without podman), the script exits 3 (skip-
    able) rather than 2 (hard-fail). Lets the CI workflow distinguish
    "lint says you broke it" from "lint could not run at all".
  * ``TV-S9T9-23e`` Discovery sanity: the staging step produces 18
    units / side (mirror of the bootstrap install count). If the
    Quadlet inventory grows or shrinks, this test surfaces the
    drift.

Sandbox boundary
----------------

The tests invoke the real script against the real repo plus tmp-copies
for mutation cases. The ``podman quadlet`` binary is required and
discovered via ``/usr/libexec/podman/quadlet``; if absent the suite
skips with a clear message.

-- Tomás
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
LINT_SCRIPT = (
    REPO_ROOT
    / "infra"
    / "spire"
    / "federation"
    / "bin"
    / "wakir-quadlet-lint.sh"
)

# /usr/libexec/podman/quadlet is the binary; ubuntu-latest + apt
# install podman provides it. We skip the whole module if it is
# missing rather than fail — the CI lane handles the skip-vs-fail
# distinction explicitly.
QUADLET_BIN = Path(os.environ.get("QUADLET_BIN", "/usr/libexec/podman/quadlet"))


pytestmark = pytest.mark.skipif(
    not QUADLET_BIN.exists(),
    reason=f"podman quadlet binary not at {QUADLET_BIN}",
)


def _run_lint(root: Path, *, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "WAKIR_REPO_ROOT": str(root)}
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(root / "infra" / "spire" / "federation" / "bin" / "wakir-quadlet-lint.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# TV-S9T9-23a: clean repo passes lint with exit 0.
# ---------------------------------------------------------------------------


def test_clean_repo_passes_lint() -> None:
    """The repo at HEAD must lint cleanly. This is the
    state-of-the-tree assertion — any incoming PR that breaks
    Quadlet-source coherence reds this test."""
    proc = _run_lint(REPO_ROOT)
    assert proc.returncode == 0, (
        f"lint failed on clean repo. exit={proc.returncode}\n"
        f"stdout={proc.stdout}\n"
        f"stderr={proc.stderr}"
    )
    assert "side=wakir OK" in proc.stdout
    assert "side=partner OK" in proc.stdout


# ---------------------------------------------------------------------------
# TV-S9T9-23b: mutation — bogus Volume= reference is caught.
# ---------------------------------------------------------------------------


def _copy_repo(src: Path, dst: Path) -> None:
    """Copy the relevant subtree (quadlet sources + lint script) into
    a tmp dir. Faster than copying the whole repo (.git etc.)."""
    paths = [
        "quadlet",
        "infra/spire/federation/quadlet",
        "infra/spire/federation/bin/wakir-quadlet-lint.sh",
        "infra/spire/agent/quadlet",
    ]
    for rel in paths:
        s = src / rel
        d = dst / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)


def test_mutation_bogus_volume_reference_caught(tmp_path: Path) -> None:
    """Rewrite one ``Volume=`` line to reference a non-existent
    ``.volume`` and lint must red. This is the exact failure mode the
    Phase-2.1 dual-side bring-up could produce if a Sprint-N-Tag-M PR
    introduces a Volume= typo — the live VM would then crash on first
    start. Bug-23's purpose is to fail this case at PR-time."""
    _copy_repo(REPO_ROOT, tmp_path)
    target = (
        tmp_path
        / "infra/spire/agent/quadlet/wakir-spire-agent-federation.container"
    )
    text = target.read_text()
    mutated = text.replace(
        "Volume=wakir-spire-agent-<SIDE>-data.volume:/var/lib/spire/agent:Z",
        "Volume=wakir-spire-bogus-typo.volume:/var/lib/spire/agent:Z",
    )
    assert mutated != text, (
        "mutation no-op — source line not found. Refactor regression?"
    )
    target.write_text(mutated)

    proc = _run_lint(tmp_path)
    assert proc.returncode == 2, (
        f"lint should have exited 2 on bogus Volume= reference, "
        f"got {proc.returncode}.\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert "wakir-spire-bogus-typo.volume" in proc.stderr, (
        f"lint diagnostic should name the bogus reference. stderr={proc.stderr!r}"
    )


# ---------------------------------------------------------------------------
# TV-S9T9-23c: mutation — missing Image= directive is caught.
# ---------------------------------------------------------------------------


def test_mutation_missing_image_directive_caught(tmp_path: Path) -> None:
    """Strip the ``Image=`` line from a container unit and lint must
    red. Different failure mode from 23b — exercises the generator's
    ``[Container]``-section validation branch."""
    _copy_repo(REPO_ROOT, tmp_path)
    target = (
        tmp_path
        / "infra/spire/federation/quadlet/wakir-spire-server-federation.container"
    )
    text = target.read_text()
    mutated_lines = [
        line for line in text.splitlines() if not line.startswith("Image=")
    ]
    mutated = "\n".join(mutated_lines) + "\n"
    assert mutated != text, "mutation no-op — no Image= line found"
    target.write_text(mutated)

    proc = _run_lint(tmp_path)
    assert proc.returncode == 2, (
        f"lint should have exited 2 on missing Image= directive, "
        f"got {proc.returncode}.\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )


# ---------------------------------------------------------------------------
# TV-S9T9-23d: exit-3 envelope when quadlet binary is absent.
# ---------------------------------------------------------------------------


def test_missing_quadlet_binary_exits_3(tmp_path: Path) -> None:
    """If ``$QUADLET_BIN`` does not point at an executable, the script
    exits 3 (skip-able) rather than 2 (failure). The CI workflow uses
    this distinction to decide whether to fail-the-build or warn-only.
    """
    _copy_repo(REPO_ROOT, tmp_path)
    proc = _run_lint(
        tmp_path,
        env_overrides={"QUADLET_BIN": "/nonexistent/path/to/quadlet"},
    )
    assert proc.returncode == 3, (
        f"lint should have exited 3 on missing quadlet binary, "
        f"got {proc.returncode}.\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    assert "binary not found" in proc.stderr


# ---------------------------------------------------------------------------
# TV-S9T9-23e: discovery sanity — the staging step covers the full
# inventory.
# ---------------------------------------------------------------------------


def test_inventory_count_stable() -> None:
    """The clean-run reports 27 units / side. Drift-guard: if the
    Quadlet inventory grows or shrinks, this test surfaces the change
    so the next operator updates the expected count consciously rather
    than absorbing the drift.

    Sprint-Pengine-7 Tag-5 OI-PILOT-1 + OI-PILOT-4: 18 → 21 (three new
    Quadlet artefacts on the wakir-side — wakir-persona-tomas.container,
    wakir-persona-tomas-workspace.volume, and
    wakir-recovery-drill-anchor.container). The .timer sidecar is a
    plain systemd .timer (installed under /etc/systemd/system/) and is
    not part of the Quadlet-generator inventory the lint walks.

    Tag-22 Mini-Welle Phase-3b Rust-CLI installer: 21 → 23 (two new
    top-level Quadlet artefacts — wakir-rust-cli.container and
    wakir-rust-cli-bin.volume; the installer is a oneshot that copies
    five Rust-CLI binaries from the carrier image into /opt/wakir/bin/
    on the host).

    Tag-55 Cosign-Strict-Mode G5 substanz-vollendung: 23 → 27 (four new
    top-level Quadlet artefacts — wakir-rust-cli-welle4.container,
    wakir-rust-cli-welle5.container, wakir-rust-cli-welle6.container,
    wakir-rust-cli-welle7.container; each installs one welle-suffix
    Rust-CLI binary from a dedicated single-binary image per the Tag-33
    Mini-Welle policy inventory convention).
    """
    proc = _run_lint(REPO_ROOT)
    assert proc.returncode == 0, proc.stderr
    # The final OK line is e.g. ``all sides OK (27 units / side)``.
    assert "(27 units / side)" in proc.stdout, (
        f"inventory drift: expected 27 units / side in OK line, "
        f"got stdout={proc.stdout!r}"
    )


def test_lint_script_is_executable() -> None:
    """The script ships executable so CI can invoke it without an
    explicit ``bash`` prefix."""
    assert os.access(LINT_SCRIPT, os.X_OK), (
        f"{LINT_SCRIPT} is not executable — chmod +x lost in commit?"
    )
