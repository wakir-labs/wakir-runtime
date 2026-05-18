# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/welle-1-day-0-pipeline.sh — Tag-32 Welle-1 Day-0
operator-side orchestrator (ADR-0066).

Hermetic, stdlib-only: every test runs the real bash script inside a
sandbox temp directory and stubs the called subprocess targets
(phase-3c-trigger-gate-aggregator.py, phase-3c-cutover-dry-run.py, gh)
via tiny shim scripts so each phase failure-mode can be exercised
deterministically.

The pipeline script uses python3 (always present) for JSON
emit/parse, so the tests do not need a `jq` binary on the host.

Scope (12 tests, beyond the requested 8)
----------------------------------------

1.  test_script_is_executable_and_has_help
2.  test_phase_mo_happy_path_emits_green_summary
3.  test_phase_mo_yellow_when_gates_yellow
4.  test_phase_mo_red_when_dry_run_blocked
5.  test_phase_mi_dispatch_hermetic_succeeds
6.  test_phase_mi_no_ci_wait_marks_yellow
7.  test_phase_do_hermetic_emits_green_summary
8.  test_phase_do_red_when_changes_requested
9.  test_phase_fr_aggregates_three_phase_artifacts
10. test_phase_fr_no_go_when_any_phase_red
11. test_full_pipeline_all_phases_emit_decision_json
12. test_invalid_phase_argument_rejected
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "welle-1-day-0-pipeline.sh"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_stub(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip())
    path.chmod(0o755)


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    """A PATH-prepended directory the test can drop shim binaries into."""
    d = tmp_path / "bin"
    d.mkdir()
    return d


@pytest.fixture
def env(bin_dir):
    """Base env with our bin shim at front of PATH."""
    base = os.environ.copy()
    base["PATH"] = f"{bin_dir}:{base.get('PATH', '')}"
    return base


def _stub_aggregator(repo_root: Path, *, status: str, rc: int) -> None:
    """Patch the trigger-gate-aggregator script with a deterministic stub."""
    target = repo_root / "scripts" / "phase-3c-trigger-gate-aggregator.py"
    target.write_text(
        textwrap.dedent(
            f"""
            #!/usr/bin/env python3
            import json, sys
            payload = {{"overall_status": "{status}",
                       "gates": [],
                       "stub": True}}
            if "--json" in sys.argv:
                print(json.dumps(payload))
            sys.exit({rc})
            """
        ).lstrip()
    )
    target.chmod(0o755)


def _stub_dry_run(repo_root: Path, *, dry_run: str, rc: int) -> None:
    target = repo_root / "scripts" / "phase-3c-cutover-dry-run.py"
    target.write_text(
        textwrap.dedent(
            f"""
            #!/usr/bin/env python3
            import json, sys
            payload = {{"dry_run": "{dry_run}", "stub": True}}
            out = None
            for i, a in enumerate(sys.argv):
                if a == "--output" and i + 1 < len(sys.argv):
                    out = sys.argv[i + 1]
            data = json.dumps(payload)
            if out:
                open(out, "w").write(data)
            else:
                print(data)
            sys.exit({rc})
            """
        ).lstrip()
    )
    target.chmod(0o755)


def _staging_repo(tmp_path: Path) -> Path:
    """Materialise a staging copy of the script + a scripts dir with
    stub aggregator/dry-run targets so the pipeline can exec them."""
    staging = tmp_path / "repo"
    (staging / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, staging / "scripts" / SCRIPT.name)
    # Default stubs (green / completed) — tests override as needed.
    _stub_aggregator(staging, status="green", rc=0)
    _stub_dry_run(staging, dry_run="completed", rc=0)
    return staging


def _run_pipeline(
    staging: Path,
    *,
    args: list,
    env: dict,
    workdir: Path | None = None,
) -> subprocess.CompletedProcess:
    """Execute the pipeline script."""
    if workdir is None:
        workdir = staging / ".welle-1-day-0-artifacts"
    full = [
        "bash",
        str(staging / "scripts" / SCRIPT.name),
        "--repo-root", str(staging),
        "--workdir", str(workdir),
        *args,
    ]
    return subprocess.run(full, env=env, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_script_is_executable_and_has_help(env):
    assert SCRIPT.exists()
    assert os.access(SCRIPT, os.X_OK)
    cp = subprocess.run([str(SCRIPT), "--help"], env=env,
                        capture_output=True, text=True)
    assert cp.returncode == 0
    assert "welle-1-day-0-pipeline.sh" in cp.stdout
    assert "--phase" in cp.stdout
    assert "mo" in cp.stdout.lower()


def test_phase_mo_happy_path_emits_green_summary(tmp_path, env):
    staging = _staging_repo(tmp_path)
    _stub_aggregator(staging, status="green", rc=0)
    _stub_dry_run(staging, dry_run="completed", rc=0)
    cp = _run_pipeline(staging, args=["--phase", "mo", "--dry-run-all"], env=env)
    assert cp.returncode == 0, cp.stderr
    summary = json.loads((staging / ".welle-1-day-0-artifacts"
                          / "phase-mo-summary.json").read_text())
    assert summary["phase"] == "mo"
    assert summary["verdict"] == "green"
    assert summary["exit_code"] == 0
    assert summary["component"] == "v907_verify"


def test_phase_mo_yellow_when_gates_yellow(tmp_path, env):
    staging = _staging_repo(tmp_path)
    _stub_aggregator(staging, status="yellow", rc=0)
    _stub_dry_run(staging, dry_run="completed", rc=0)
    cp = _run_pipeline(staging, args=["--phase", "mo", "--dry-run-all"], env=env)
    assert cp.returncode == 1, cp.stderr
    summary = json.loads((staging / ".welle-1-day-0-artifacts"
                          / "phase-mo-summary.json").read_text())
    assert summary["verdict"] == "yellow"
    assert summary["gates_status"] == "yellow"


def test_phase_mo_red_when_dry_run_blocked(tmp_path, env):
    staging = _staging_repo(tmp_path)
    _stub_aggregator(staging, status="green", rc=0)
    _stub_dry_run(staging, dry_run="blocked", rc=0)
    cp = _run_pipeline(staging, args=["--phase", "mo", "--dry-run-all"], env=env)
    assert cp.returncode == 2, cp.stderr
    summary = json.loads((staging / ".welle-1-day-0-artifacts"
                          / "phase-mo-summary.json").read_text())
    assert summary["verdict"] == "red"
    assert summary["dry_status"] == "blocked"


def test_phase_mi_dispatch_hermetic_succeeds(tmp_path, env):
    staging = _staging_repo(tmp_path)
    cp = _run_pipeline(staging, args=["--phase", "mi", "--dry-run-all"], env=env)
    assert cp.returncode == 0, cp.stderr
    summary = json.loads((staging / ".welle-1-day-0-artifacts"
                          / "phase-mi-summary.json").read_text())
    assert summary["verdict"] == "green"
    assert summary["hermetic"] is True
    assert summary["conclusion"] == "hermetic"


def test_phase_mi_no_ci_wait_marks_yellow(tmp_path, env, bin_dir):
    # Hermetic mode short-circuits the gh path. To exercise --no-ci-wait
    # we need to omit --dry-run-all but inject a fake gh that succeeds.
    fake_gh = bin_dir / "gh"
    _write_stub(
        fake_gh,
        """
        #!/usr/bin/env bash
        if [[ "$1" == "workflow" && "$2" == "run" ]]; then exit 0; fi
        if [[ "$1" == "run" && "$2" == "list" ]]; then echo '42'; exit 0; fi
        exit 0
        """,
    )
    staging = _staging_repo(tmp_path)
    cp = _run_pipeline(staging, args=["--phase", "mi", "--no-ci-wait"], env=env)
    assert cp.returncode == 1, cp.stderr
    summary = json.loads((staging / ".welle-1-day-0-artifacts"
                          / "phase-mi-summary.json").read_text())
    assert summary["verdict"] == "yellow"
    assert summary["conclusion"] == "not-waited"


def test_phase_do_hermetic_emits_green_summary(tmp_path, env):
    staging = _staging_repo(tmp_path)
    cp = _run_pipeline(staging, args=["--phase", "do", "--dry-run-all"], env=env)
    assert cp.returncode == 0, cp.stderr
    summary = json.loads((staging / ".welle-1-day-0-artifacts"
                          / "phase-do-summary.json").read_text())
    assert summary["verdict"] == "green"
    assert summary["hermetic"] is True


def test_phase_do_red_when_changes_requested(tmp_path, env, bin_dir):
    fake_gh = bin_dir / "gh"
    _write_stub(
        fake_gh,
        """
        #!/usr/bin/env bash
        if [[ "$1" == "pr" && "$2" == "list" ]]; then
            echo '[{"number":1,"reviewDecision":"CHANGES_REQUESTED"}]'
            exit 0
        fi
        exit 0
        """,
    )
    staging = _staging_repo(tmp_path)
    cp = _run_pipeline(staging, args=["--phase", "do"], env=env)
    assert cp.returncode == 2, cp.stderr
    summary = json.loads((staging / ".welle-1-day-0-artifacts"
                          / "phase-do-summary.json").read_text())
    assert summary["verdict"] == "red"
    assert summary["pr_review"]["changes_requested"] == 1


def test_phase_fr_aggregates_three_phase_artifacts(tmp_path, env):
    staging = _staging_repo(tmp_path)
    workdir = staging / ".welle-1-day-0-artifacts"
    workdir.mkdir()
    for ph in ("mo", "mi", "do"):
        (workdir / f"phase-{ph}-summary.json").write_text(json.dumps({
            "phase": ph, "verdict": "green", "exit_code": 0
        }))
    cp = _run_pipeline(staging, args=["--phase", "fr", "--dry-run-all"], env=env)
    assert cp.returncode == 0, cp.stderr
    decision = json.loads((workdir / "cutover-acceptance-decision.json").read_text())
    assert decision["decision"] == "go"
    assert decision["verdict"] == "green"
    assert decision["exit_code"] == 0
    assert decision["component"] == "v907_verify"
    assert decision["adr"] == "ADR-0066"
    assert decision["welle"] == 1


def test_phase_fr_no_go_when_any_phase_red(tmp_path, env):
    staging = _staging_repo(tmp_path)
    workdir = staging / ".welle-1-day-0-artifacts"
    workdir.mkdir()
    (workdir / "phase-mo-summary.json").write_text(json.dumps(
        {"phase": "mo", "verdict": "green", "exit_code": 0}))
    (workdir / "phase-mi-summary.json").write_text(json.dumps(
        {"phase": "mi", "verdict": "red", "exit_code": 2}))
    (workdir / "phase-do-summary.json").write_text(json.dumps(
        {"phase": "do", "verdict": "green", "exit_code": 0}))
    cp = _run_pipeline(staging, args=["--phase", "fr", "--dry-run-all"], env=env)
    assert cp.returncode == 2, cp.stderr
    decision = json.loads((workdir / "cutover-acceptance-decision.json").read_text())
    assert decision["decision"] == "no-go"
    assert decision["verdict"] == "red"
    assert decision["phases"]["mi"]["verdict"] == "red"


def test_full_pipeline_all_phases_emit_decision_json(tmp_path, env):
    staging = _staging_repo(tmp_path)
    _stub_aggregator(staging, status="green", rc=0)
    _stub_dry_run(staging, dry_run="completed", rc=0)
    cp = _run_pipeline(staging, args=["--phase", "all", "--dry-run-all"], env=env)
    assert cp.returncode == 0, cp.stderr
    workdir = staging / ".welle-1-day-0-artifacts"
    for ph in ("mo", "mi", "do", "fr"):
        assert (workdir / f"phase-{ph}-summary.json").exists(), \
            f"missing summary for phase {ph}"
    decision = json.loads((workdir / "cutover-acceptance-decision.json").read_text())
    assert decision["decision"] == "go"
    assert decision["verdict"] == "green"


def test_invalid_phase_argument_rejected(tmp_path, env):
    staging = _staging_repo(tmp_path)
    cp = _run_pipeline(staging, args=["--phase", "garbage", "--dry-run-all"], env=env)
    assert cp.returncode == 2
    assert "invalid --phase" in cp.stderr
