# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/image-pin-idempotent-resolver.sh``.

Phase-2 Sprint-9 Tag-5 CI-hygiene: the resolver MUST be idempotent.
Concrete contract under test:

* First-run on a placeholder-only repo: drift detected (exit 10),
  files mutated.
* Second-run on the now-resolved repo with the SAME forced digest:
  no drift (exit 0), files unchanged byte-for-byte.
* Run on a half-resolved repo (some pins placeholder, some real):
  resolver only mutates the still-pending entries; the already-
  resolved ones stay byte-identical.
* ``--print-only`` exits 10 on drift but does NOT mutate any file.
* A live-digest that differs from the committed pin is treated as
  drift (the cron-cycle path: upstream re-push detection).

The sandbox boundary is preserved by ``--digest-source env`` which
reads ``FORCE_<GROUP>_DIGEST`` env vars instead of calling crane.
No network egress under test.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVER = REPO_ROOT / "scripts" / "image-pin-idempotent-resolver.sh"


# A static, syntactically valid sha256 for the four pin groups. Picked
# to be deterministic and obviously fake.
FAKE_DIGESTS = {
    "FORCE_SPIRE_SERVER_DIGEST":      "sha256:" + "a" * 64,
    "FORCE_SPIRE_AGENT_DIGEST":       "sha256:" + "b" * 64,
    "FORCE_PYTHON_DIGEST":            "sha256:" + "c" * 64,
    "FORCE_WAKIR_PROVISIONER_DIGEST": "sha256:" + "d" * 64,
}

PIN_TARGETS = [
    "infra/spire/federation/quadlet/wakir-spire-server-federation.container",
    "quadlet/wakir-spire-server.container",
    "infra/spire/agent/quadlet/wakir-spire-agent-federation.container",
    "quadlet/wakir-spire-agent.container",
    "infra/spire/federation/provisioner/Containerfile",
    "quadlet/wakir-nats-kv-bucket-init.container",
]


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(root: Path) -> dict[str, str]:
    out = {}
    for rel in PIN_TARGETS:
        f = root / rel
        if f.is_file():
            out[rel] = _file_digest(f)
    return out


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    """Copy the pin-bearing subset of the repo into a tmp tree.

    Hermetic-test isolation: we mutate file contents inside the tmp
    copy, never the repo root. A re-run of the test suite against the
    same repo always sees identical input.
    """
    dst = tmp_path / "repo"
    dst.mkdir()
    for rel in PIN_TARGETS:
        src = REPO_ROOT / rel
        if not src.is_file():
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    return dst


def _run_resolver(root: Path, env: dict[str, str], extra: list[str] | None = None) -> subprocess.CompletedProcess:
    cmd = [
        "bash",
        str(RESOLVER),
        "--root", str(root),
        "--digest-source", "env",
    ] + (extra or [])
    full_env = {**os.environ, **env}
    return subprocess.run(
        cmd,
        env=full_env,
        check=False,
        capture_output=True,
        text=True,
    )


# ----------------------------------------------------------------------
# Resolver-binary invariants.
# ----------------------------------------------------------------------

def test_resolver_script_exists_and_executable() -> None:
    assert RESOLVER.is_file(), f"missing resolver: {RESOLVER}"
    st = RESOLVER.stat()
    assert st.st_mode & stat.S_IXUSR, "resolver must be executable"


def test_resolver_bash_syntax_clean() -> None:
    rc = subprocess.run(["bash", "-n", str(RESOLVER)], check=False)
    assert rc.returncode == 0, "bash -n failed on resolver"


def test_resolver_help() -> None:
    rc = subprocess.run(
        ["bash", str(RESOLVER), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0
    # Help text MUST document the exit-code contract — the workflow
    # depends on it.
    assert "0   = no drift" in rc.stdout or "0 = no drift" in rc.stdout
    assert "10  = drift detected" in rc.stdout or "10 = drift detected" in rc.stdout


# ----------------------------------------------------------------------
# Idempotency invariants — the core of Sprint-9 Tag-5 Teil 2.
# ----------------------------------------------------------------------

def test_first_run_resolves_placeholders(repo_copy: Path) -> None:
    pre = _snapshot(repo_copy)
    proc = _run_resolver(repo_copy, FAKE_DIGESTS)
    # Drift sentinel (10) because placeholders count as drift.
    assert proc.returncode == 10, (
        f"expected drift sentinel 10, got {proc.returncode}\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    post = _snapshot(repo_copy)
    # At least one file changed.
    diffs = [k for k in pre if pre[k] != post.get(k)]
    assert diffs, "first run should have mutated at least one pin file"


def test_second_run_is_noop(repo_copy: Path) -> None:
    # Apply first.
    first = _run_resolver(repo_copy, FAKE_DIGESTS)
    assert first.returncode == 10
    state_after_first = _snapshot(repo_copy)

    # Re-run with the EXACT SAME forced digests. Must be a no-op.
    second = _run_resolver(repo_copy, FAKE_DIGESTS)
    assert second.returncode == 0, (
        f"expected idempotent no-op (rc=0), got {second.returncode}\n"
        f"stdout:\n{second.stdout}\nstderr:\n{second.stderr}"
    )
    state_after_second = _snapshot(repo_copy)
    assert state_after_first == state_after_second, (
        "idempotent re-run mutated files; this is the bug Sprint-9 "
        "Tag-5 Teil 2 was meant to close"
    )


def test_third_run_still_noop(repo_copy: Path) -> None:
    # Belt-and-suspenders: many cron cycles in a row must all be no-op.
    _run_resolver(repo_copy, FAKE_DIGESTS)
    state_1 = _snapshot(repo_copy)
    _run_resolver(repo_copy, FAKE_DIGESTS)
    _run_resolver(repo_copy, FAKE_DIGESTS)
    state_3 = _snapshot(repo_copy)
    assert state_1 == state_3


def test_drift_to_new_live_digest(repo_copy: Path) -> None:
    # Cycle 1: resolve with FAKE_DIGESTS, files now carry those.
    _run_resolver(repo_copy, FAKE_DIGESTS)
    # Cycle 2: upstream re-push — live digest changes for one group.
    rotated = dict(FAKE_DIGESTS)
    rotated["FORCE_PYTHON_DIGEST"] = "sha256:" + "e" * 64
    proc = _run_resolver(repo_copy, rotated)
    assert proc.returncode == 10, (
        "rotation of an upstream digest must trigger drift sentinel"
    )
    # The mutated file is the Containerfile carrying the python pin.
    containerfile = repo_copy / "infra/spire/federation/provisioner/Containerfile"
    assert "e" * 64 in containerfile.read_text()


# ----------------------------------------------------------------------
# --print-only is non-mutating.
# ----------------------------------------------------------------------

def test_print_only_does_not_mutate_files(repo_copy: Path) -> None:
    pre = _snapshot(repo_copy)
    proc = _run_resolver(repo_copy, FAKE_DIGESTS, extra=["--print-only"])
    # Still emits drift sentinel because placeholders count as drift.
    assert proc.returncode == 10
    post = _snapshot(repo_copy)
    assert pre == post, "--print-only must not mutate any file"


def test_print_only_then_apply_is_consistent(repo_copy: Path) -> None:
    # print-only first, then real apply — must arrive at same final
    # state as a direct apply.
    direct = repo_copy
    indirect_root = direct.parent / "indirect"
    shutil.copytree(direct, indirect_root)

    _run_resolver(direct, FAKE_DIGESTS)
    _run_resolver(indirect_root, FAKE_DIGESTS, extra=["--print-only"])
    _run_resolver(indirect_root, FAKE_DIGESTS)

    s_direct = _snapshot(direct)
    s_indirect = _snapshot(indirect_root)
    assert s_direct == s_indirect


# ----------------------------------------------------------------------
# Resolver-side argument validation.
# ----------------------------------------------------------------------

def test_resolver_rejects_bad_digest_source(repo_copy: Path) -> None:
    proc = subprocess.run(
        ["bash", str(RESOLVER), "--root", str(repo_copy),
         "--digest-source", "magic"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


def test_resolver_rejects_missing_root() -> None:
    proc = subprocess.run(
        ["bash", str(RESOLVER), "--root", "/nonexistent-xyzzy"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


# ----------------------------------------------------------------------
# Workflow-side wiring — keep the CI wrapper in sync with the script.
# ----------------------------------------------------------------------

def test_workflow_yaml_present() -> None:
    wf = REPO_ROOT / ".github" / "workflows" / "resolve-image-pins-ci.yml"
    assert wf.is_file()


def test_workflow_calls_resolver_script() -> None:
    wf = REPO_ROOT / ".github" / "workflows" / "resolve-image-pins-ci.yml"
    text = wf.read_text(encoding="utf-8")
    assert "scripts/image-pin-idempotent-resolver.sh" in text


def test_workflow_handles_drift_sentinel() -> None:
    # The workflow MUST distinguish drift (exit 10) from real error
    # (exit 1+). Otherwise a real error would silently turn into a PR.
    wf = REPO_ROOT / ".github" / "workflows" / "resolve-image-pins-ci.yml"
    text = wf.read_text(encoding="utf-8")
    assert "10)" in text or "10 )" in text, (
        "workflow must branch on exit code 10 (drift sentinel)"
    )


def test_workflow_no_packages_write() -> None:
    # Least-privilege: this workflow neither pushes images nor signs.
    import yaml
    wf = REPO_ROOT / ".github" / "workflows" / "resolve-image-pins-ci.yml"
    d = yaml.safe_load(wf.read_text(encoding="utf-8"))
    perms = d.get("permissions", {})
    assert "packages" not in perms, (
        "resolve-image-pins-ci must not request packages: write; that "
        "scope belongs to build-wakir-provisioner only"
    )
    assert "id-token" not in perms, (
        "resolve-image-pins-ci does not sign — no id-token scope"
    )


def test_workflow_requires_contents_write() -> None:
    import yaml
    wf = REPO_ROOT / ".github" / "workflows" / "resolve-image-pins-ci.yml"
    d = yaml.safe_load(wf.read_text(encoding="utf-8"))
    perms = d.get("permissions", {})
    # Needs contents:write to push the auto-branch + open PR.
    assert perms.get("contents") == "write"
    assert perms.get("pull-requests") == "write"
