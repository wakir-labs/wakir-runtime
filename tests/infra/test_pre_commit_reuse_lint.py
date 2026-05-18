# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the REUSE-Lint pre-commit-hook configuration.

Tag-32 EXT-AUDIT-FOLGE companion. Covers five acceptance-vectors:

1. ``.pre-commit-config.yaml`` shape — file exists, valid YAML,
   declares the three expected hooks with their canonical IDs.
2. Hook trigger conditions — the ``reuse-toml-annotation-drift``
   hook restricts itself to ``REUSE.toml`` via ``files: ...`` and
   the ``spdx-header-check`` hook covers the canonical substance
   file-types.
3. SPDX-Drift-Detection — the ``spdx-header-check`` helper script
   correctly flags a missing-header file and passes a present-
   header file (driven through ``subprocess`` against the helper
   in an isolated ``tmp_path`` worktree).
4. REUSE.toml Annotation-Check — the
   ``reuse-toml-annotation-drift`` helper script detects a stale
   annotation in a synthetic ``REUSE.toml`` and passes when all
   annotation paths match.
5. Runbook presence — the operator runbook exists, declares the
   correct ADR-anchor, and documents the three hook layers plus
   the ``--no-verify`` bypass note.

These tests are hermetic — they neither install ``pre-commit`` nor
contact the network. The helper-scripts are exercised in-process
via ``subprocess`` and a scratch worktree under ``tmp_path``.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# `PyYAML` is installed in the production lane (`tests.yml`) but not
# in the sandbox lane. Tests that need real YAML parsing skip cleanly
# on the sandbox lane; the rest still run via raw text inspection,
# subprocess exercise, etc.
try:
    import yaml as _yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - sandbox lane only
    _yaml = None

requires_yaml = pytest.mark.skipif(
    _yaml is None, reason="PyYAML not installed (sandbox lane)"
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
SPDX_HEADER_SCRIPT = REPO_ROOT / "scripts" / "pre-commit-spdx-header-check.py"
REUSE_DRIFT_SCRIPT = REPO_ROOT / "scripts" / "pre-commit-reuse-toml-drift-check.py"
RUNBOOK = REPO_ROOT / "docs" / "operations" / "pre-commit-reuse-lint-runbook.md"


# --------------------------------------------------------------------
# Acceptance-Vector 1 — `.pre-commit-config.yaml` shape
# --------------------------------------------------------------------


@requires_yaml
def test_pre_commit_config_exists_and_is_valid_yaml() -> None:
    """`.pre-commit-config.yaml` must exist and parse as YAML."""
    assert PRE_COMMIT_CONFIG.is_file(), (
        f"missing pre-commit config: {PRE_COMMIT_CONFIG}"
    )
    with PRE_COMMIT_CONFIG.open("r", encoding="utf-8") as fh:
        config = _yaml.safe_load(fh)
    assert isinstance(config, dict)
    assert "repos" in config
    assert isinstance(config["repos"], list)
    assert len(config["repos"]) >= 2, (
        "expected at least two repos: upstream reuse-tool + local"
    )


@requires_yaml
def test_pre_commit_config_declares_canonical_hook_ids() -> None:
    """The three canonical hook-IDs must be present.

    * ``reuse`` (upstream `fsfe/reuse-tool`)
    * ``spdx-header-check`` (repo-local)
    * ``reuse-toml-annotation-drift`` (repo-local)
    """
    config = _yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    hook_ids = {
        hook["id"]
        for repo in config["repos"]
        for hook in repo.get("hooks", [])
    }
    expected = {"reuse", "spdx-header-check", "reuse-toml-annotation-drift"}
    missing = expected - hook_ids
    assert not missing, (
        f"missing canonical hook-IDs in .pre-commit-config.yaml: {missing}"
    )


# --------------------------------------------------------------------
# Acceptance-Vector 2 — hook trigger conditions
# --------------------------------------------------------------------


@requires_yaml
def test_reuse_toml_drift_hook_restricts_to_reuse_toml() -> None:
    """The drift-hook must only trigger when `REUSE.toml` is staged."""
    config = _yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    drift_hook = None
    for repo in config["repos"]:
        for hook in repo.get("hooks", []):
            if hook["id"] == "reuse-toml-annotation-drift":
                drift_hook = hook
                break
    assert drift_hook is not None
    assert drift_hook.get("files") == r"^REUSE\.toml$", (
        "drift-hook must restrict via `files: ^REUSE\\.toml$`"
    )
    assert drift_hook.get("pass_filenames") is False


@requires_yaml
def test_spdx_header_hook_covers_canonical_substance_types() -> None:
    """The SPDX-header hook must cover the canonical substance file-types.

    The set mirrors the path-filter in the server-side
    ``license-gate.yml`` so client- and server-side enforcement scope
    do not diverge.
    """
    config = _yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    spdx_hook = None
    for repo in config["repos"]:
        for hook in repo.get("hooks", []):
            if hook["id"] == "spdx-header-check":
                spdx_hook = hook
                break
    assert spdx_hook is not None
    types_or = set(spdx_hook.get("types_or", []))
    expected_types = {"python", "rust", "shell", "toml", "yaml", "markdown"}
    missing = expected_types - types_or
    assert not missing, (
        f"spdx-header-check must cover all substance types; missing: {missing}"
    )


# --------------------------------------------------------------------
# Acceptance-Vector 3 — SPDX-Drift-Detection (helper script)
# --------------------------------------------------------------------


def _init_git_repo(root: Path) -> None:
    """Initialize a hermetic git repo in ``root`` for hook exercise.

    No network, no user config — uses ``-c`` overrides so the test
    runs in a CI environment without ``git config --global user.*``.
    """
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "tomas-test",
            "GIT_AUTHOR_EMAIL": "tomas-test@wakir.local",
            "GIT_COMMITTER_NAME": "tomas-test",
            "GIT_COMMITTER_EMAIL": "tomas-test@wakir.local",
        }
    )
    subprocess.check_call(
        ["git", "init", "-q", "-b", "main"], cwd=root, env=env
    )
    subprocess.check_call(
        ["git", "config", "user.email", "tomas-test@wakir.local"],
        cwd=root,
    )
    subprocess.check_call(
        ["git", "config", "user.name", "tomas-test"], cwd=root
    )


def test_spdx_header_script_blocks_missing_header(tmp_path: Path) -> None:
    """A newly-added `.py` file without SPDX header must trigger exit 1."""
    assert SPDX_HEADER_SCRIPT.is_file()

    # Build a scratch worktree that mirrors the repo layout the hook
    # expects: `scripts/pre-commit-spdx-header-check.py` is one level
    # below the worktree root because the helper uses `parents[1]`.
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    helper_dst = scripts / "pre-commit-spdx-header-check.py"
    helper_dst.write_bytes(SPDX_HEADER_SCRIPT.read_bytes())
    helper_dst.chmod(0o755)

    _init_git_repo(tmp_path)

    # Add a `.py` file *without* SPDX header and stage it.
    bad = tmp_path / "new_module.py"
    bad.write_text(
        textwrap.dedent(
            '''\
            """Forgot to add SPDX header."""
            def f() -> int:
                return 42
            '''
        ),
        encoding="utf-8",
    )
    subprocess.check_call(["git", "add", "new_module.py"], cwd=tmp_path)

    # Invoke the hook the way `pre-commit` would (file as argv[1]).
    result = subprocess.run(
        [sys.executable, str(helper_dst), "new_module.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, (
        f"hook should block missing-SPDX file; output: {result.stderr}"
    )
    assert "missing SPDX-License-Identifier" in result.stderr


def test_spdx_header_script_passes_present_header(tmp_path: Path) -> None:
    """A newly-added `.py` file *with* SPDX header must return exit 0."""
    assert SPDX_HEADER_SCRIPT.is_file()

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    helper_dst = scripts / "pre-commit-spdx-header-check.py"
    helper_dst.write_bytes(SPDX_HEADER_SCRIPT.read_bytes())
    helper_dst.chmod(0o755)

    _init_git_repo(tmp_path)

    good = tmp_path / "good_module.py"
    # Build the SPDX-tag through concatenation to avoid `reuse lint`
    # falsely picking up this test string as a real header.
    spdx_tag = "SPDX-License" + "-Identifier: Apache-2.0"
    good.write_text(
        f"# {spdx_tag}\n"
        "# Copyright (c) 2026 Callandor GmbH and contributors\n"
        '"""Has the canonical SPDX header."""\n'
        "def f() -> int:\n    return 42\n",
        encoding="utf-8",
    )
    subprocess.check_call(["git", "add", "good_module.py"], cwd=tmp_path)

    result = subprocess.run(
        [sys.executable, str(helper_dst), "good_module.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"hook should pass present-SPDX file; stderr: {result.stderr}"
    )


def test_spdx_header_script_skips_modified_files(tmp_path: Path) -> None:
    """Modified files (status `M`, not `A`) must not block the commit.

    Legacy-churn discipline: pre-commit defends against drift in
    *new* files. The server-side license-gate enforces the full-
    tree invariant for everything else.
    """
    assert SPDX_HEADER_SCRIPT.is_file()

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    helper_dst = scripts / "pre-commit-spdx-header-check.py"
    helper_dst.write_bytes(SPDX_HEADER_SCRIPT.read_bytes())
    helper_dst.chmod(0o755)

    _init_git_repo(tmp_path)

    # Create the file, commit it (so it's now tracked), then modify
    # it. The hook sees a modified (M) file — not an added (A) file —
    # and must let it through even without SPDX header.
    legacy = tmp_path / "legacy_module.py"
    legacy.write_text(
        '"""Legacy file without SPDX header."""\n', encoding="utf-8"
    )
    subprocess.check_call(["git", "add", "legacy_module.py"], cwd=tmp_path)
    subprocess.check_call(
        ["git", "commit", "-q", "-m", "init legacy"], cwd=tmp_path
    )

    # Now modify and re-stage — status will be `M`.
    legacy.write_text(
        '"""Legacy file, slightly changed."""\nx = 1\n', encoding="utf-8"
    )
    subprocess.check_call(["git", "add", "legacy_module.py"], cwd=tmp_path)

    result = subprocess.run(
        [sys.executable, str(helper_dst), "legacy_module.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"hook must let modified-only files through; stderr: {result.stderr}"
    )


# --------------------------------------------------------------------
# Acceptance-Vector 4 — REUSE.toml Annotation-Check (helper script)
# --------------------------------------------------------------------


def test_reuse_toml_drift_script_detects_stale_annotation(
    tmp_path: Path,
) -> None:
    """A `[[annotations]]` block matching zero files must trigger exit 1."""
    assert REUSE_DRIFT_SCRIPT.is_file()

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    helper_dst = scripts / "pre-commit-reuse-toml-drift-check.py"
    helper_dst.write_bytes(REUSE_DRIFT_SCRIPT.read_bytes())
    helper_dst.chmod(0o755)

    # Build a synthetic REUSE.toml with one valid annotation (matches
    # the helper script we just wrote into `scripts/`) and one stale
    # annotation (matches a non-existent path).
    (tmp_path / "REUSE.toml").write_text(
        textwrap.dedent(
            """\
            version = 1
            SPDX-PackageName = "wakir-runtime-test"

            [[annotations]]
            path = "scripts/**"
            precedence = "closest"
            SPDX-FileCopyrightText = "2026 Callandor GmbH"
            SPDX-License-Identifier = "Apache-2.0"

            [[annotations]]
            path = "nonexistent/**"
            precedence = "closest"
            SPDX-FileCopyrightText = "2026 Callandor GmbH"
            SPDX-License-Identifier = "BUSL-1.1"
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(helper_dst)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, (
        f"drift-check must reject stale annotation; stderr: {result.stderr}"
    )
    assert "stale" in result.stderr.lower() or "nonexistent" in result.stderr


def test_reuse_toml_drift_script_passes_when_all_paths_match(
    tmp_path: Path,
) -> None:
    """All `[[annotations]]` paths matching at least one file => exit 0."""
    assert REUSE_DRIFT_SCRIPT.is_file()

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    helper_dst = scripts / "pre-commit-reuse-toml-drift-check.py"
    helper_dst.write_bytes(REUSE_DRIFT_SCRIPT.read_bytes())
    helper_dst.chmod(0o755)

    (tmp_path / "REUSE.toml").write_text(
        textwrap.dedent(
            """\
            version = 1
            SPDX-PackageName = "wakir-runtime-test"

            [[annotations]]
            path = "scripts/**"
            precedence = "closest"
            SPDX-FileCopyrightText = "2026 Callandor GmbH"
            SPDX-License-Identifier = "Apache-2.0"
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(helper_dst)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"drift-check must pass when all paths match; stderr: {result.stderr}"
    )


def test_reuse_toml_drift_script_rejects_invalid_toml(tmp_path: Path) -> None:
    """Broken TOML must yield a clear exit-1 diagnostic."""
    assert REUSE_DRIFT_SCRIPT.is_file()

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    helper_dst = scripts / "pre-commit-reuse-toml-drift-check.py"
    helper_dst.write_bytes(REUSE_DRIFT_SCRIPT.read_bytes())
    helper_dst.chmod(0o755)

    # Deliberately broken TOML.
    (tmp_path / "REUSE.toml").write_text(
        "version = 1\n[[annotations]\npath = 'oops'\n",  # missing `]`
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(helper_dst)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "not valid TOML" in result.stderr or "TOML" in result.stderr


# --------------------------------------------------------------------
# Acceptance-Vector 5 — Runbook presence
# --------------------------------------------------------------------


def test_runbook_exists_and_anchors_to_adr_0061() -> None:
    """Runbook must exist and anchor to ADR-0061 + Tag-32 EXT-AUDIT-FOLGE."""
    assert RUNBOOK.is_file(), f"missing runbook: {RUNBOOK}"
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "ADR-0061" in text
    assert "Tag-32" in text or "EXT-AUDIT" in text


def test_runbook_documents_three_hook_layers() -> None:
    """Runbook must reference all three hook layers."""
    text = RUNBOOK.read_text(encoding="utf-8")
    # Layer 1
    assert "reuse lint" in text.lower()
    # Layer 2
    assert "spdx-header-check" in text
    # Layer 3
    assert "reuse-toml-annotation-drift" in text


def test_runbook_documents_no_verify_bypass_discouraged() -> None:
    """`--no-verify` bypass must be documented with a discouragement note."""
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "--no-verify" in text
    # Either "NICHT EMPFOHLEN" (German) or "not recommended" (English)
    # must appear in proximity to the bypass section.
    assert (
        "NICHT EMPFOHLEN" in text
        or "nicht empfohlen" in text.lower()
        or "not recommended" in text.lower()
    )


# --------------------------------------------------------------------
# Bonus invariants — script file-hygiene
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "script",
    [SPDX_HEADER_SCRIPT, REUSE_DRIFT_SCRIPT],
)
def test_helper_script_has_shebang_and_is_executable(script: Path) -> None:
    """Helper scripts must have shebang + executable bit (Unix discipline)."""
    assert script.is_file()
    first_line = script.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#!"), (
        f"{script.name}: missing shebang"
    )
    assert "python" in first_line.lower()
    mode = script.stat().st_mode
    assert mode & 0o111, f"{script.name}: not executable"
