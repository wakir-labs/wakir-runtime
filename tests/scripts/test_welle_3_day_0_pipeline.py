# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/welle-3-day-0-pipeline.sh — Tag-32 Welle-3 Day-0
operator-side orchestrator (ADR-0066).

Hermetic, stdlib-only: every test runs the real bash script inside a
sandbox temp directory and stubs the called subprocess targets
(phase-3c-trigger-gate-aggregator.py, phase-3c-cutover-dry-run.py,
doppelbetrieb-score-aggregator.py, gh) via tiny shim scripts so each
phase failure-mode can be exercised deterministically.

The pipeline script uses python3 (always present) for JSON
emit/parse, so the tests do not need a `jq` binary on the host.

Scope (14 tests, beyond the requested 8)
----------------------------------------

1.  test_script_is_executable_and_has_help
2.  test_phase_mo_happy_path_emits_green_summary
3.  test_phase_mo_component_alias_short_form_accepted
4.  test_phase_mo_yellow_when_gates_yellow
5.  test_phase_mo_red_when_dry_run_blocked
6.  test_phase_mi_dispatch_hermetic_succeeds
7.  test_phase_mi_no_ci_wait_marks_yellow
8.  test_phase_mi5_cross_modul_stress_pass_sets_henrik_caution
9.  test_phase_mi5_cross_modul_stress_fail_blocks
10. test_phase_do_hermetic_emits_green_summary
11. test_phase_do_red_when_changes_requested
12. test_phase_do_red_when_telemetry_red_flag_set
13. test_phase_fr_aggregates_four_phase_artifacts
14. test_phase_fr_no_go_when_any_phase_red
15. test_full_pipeline_all_phases_emit_decision_json
16. test_invalid_phase_argument_rejected
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
SCRIPT = REPO_ROOT / "scripts" / "welle-3-day-0-pipeline.sh"


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


def _stub_cross_modul_stress(
    repo_root: Path, *, threshold_pass: bool, rc: int
) -> None:
    """Patch the doppelbetrieb-score-aggregator with a deterministic stub
    that emits a Cross-Modul-Stress envelope shape understood by Phase Mi.5.
    """
    target = repo_root / "scripts" / "doppelbetrieb-score-aggregator.py"
    # `str(True)` is "True" — exactly what Python source expects as a
    # bool literal. Splicing it into the f-string body keeps the
    # generated stub valid Python.
    target.write_text(
        textwrap.dedent(
            f"""
            #!/usr/bin/env python3
            import json, sys
            payload = {{
                "mode": "cross-modul-stress",
                "threshold_pass": {str(threshold_pass)},
                "axes": [],
                "stub": True,
            }}
            out = None
            for i, a in enumerate(sys.argv):
                if a == "--out" and i + 1 < len(sys.argv):
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
    stub aggregator/dry-run/cross-modul-stress targets so the pipeline
    can exec them."""
    staging = tmp_path / "repo"
    (staging / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, staging / "scripts" / SCRIPT.name)
    # Default stubs (green / completed / pass) — tests override as needed.
    _stub_aggregator(staging, status="green", rc=0)
    _stub_dry_run(staging, dry_run="completed", rc=0)
    _stub_cross_modul_stress(staging, threshold_pass=True, rc=0)
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
        workdir = staging / ".welle-3-day-0-artifacts"
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
    assert "welle-3-day-0-pipeline.sh" in cp.stdout
    assert "--phase" in cp.stdout
    assert "mi5" in cp.stdout.lower()
    assert "bridge_audit_writer" in cp.stdout
    assert "anchor_emitter" in cp.stdout


def test_phase_mo_happy_path_emits_green_summary(tmp_path, env):
    staging = _staging_repo(tmp_path)
    _stub_aggregator(staging, status="green", rc=0)
    _stub_dry_run(staging, dry_run="completed", rc=0)
    cp = _run_pipeline(staging, args=["--phase", "mo", "--dry-run-all"], env=env)
    assert cp.returncode == 0, cp.stderr
    summary = json.loads((staging / ".welle-3-day-0-artifacts"
                          / "phase-mo-summary.json").read_text())
    assert summary["phase"] == "mo"
    assert summary["verdict"] == "green"
    assert summary["exit_code"] == 0
    # Long-form ADR-0065 component name records verbatim.
    assert summary["component"] == "bridge_audit_writer"
    # Resolver-side normalisation also captured.
    assert summary["component_resolver_alias"] == "anchor_emitter"


def test_phase_mo_component_alias_short_form_accepted(tmp_path, env):
    """Operator may pass the in-repo short form (anchor_emitter) on the
    CLI. The pipeline normalises it for the resolver path; the JSON
    records both spellings."""
    staging = _staging_repo(tmp_path)
    _stub_aggregator(staging, status="green", rc=0)
    _stub_dry_run(staging, dry_run="completed", rc=0)
    cp = _run_pipeline(
        staging,
        args=["--phase", "mo", "--component", "anchor_emitter", "--dry-run-all"],
        env=env,
    )
    assert cp.returncode == 0, cp.stderr
    summary = json.loads((staging / ".welle-3-day-0-artifacts"
                          / "phase-mo-summary.json").read_text())
    assert summary["component"] == "anchor_emitter"
    assert summary["component_resolver_alias"] == "anchor_emitter"


def test_phase_mo_yellow_when_gates_yellow(tmp_path, env):
    staging = _staging_repo(tmp_path)
    _stub_aggregator(staging, status="yellow", rc=0)
    _stub_dry_run(staging, dry_run="completed", rc=0)
    cp = _run_pipeline(staging, args=["--phase", "mo", "--dry-run-all"], env=env)
    assert cp.returncode == 1, cp.stderr
    summary = json.loads((staging / ".welle-3-day-0-artifacts"
                          / "phase-mo-summary.json").read_text())
    assert summary["verdict"] == "yellow"
    assert summary["gates_status"] == "yellow"


def test_phase_mo_red_when_dry_run_blocked(tmp_path, env):
    staging = _staging_repo(tmp_path)
    _stub_aggregator(staging, status="green", rc=0)
    _stub_dry_run(staging, dry_run="blocked", rc=0)
    cp = _run_pipeline(staging, args=["--phase", "mo", "--dry-run-all"], env=env)
    assert cp.returncode == 2, cp.stderr
    summary = json.loads((staging / ".welle-3-day-0-artifacts"
                          / "phase-mo-summary.json").read_text())
    assert summary["verdict"] == "red"
    assert summary["dry_status"] == "blocked"


def test_phase_mi_dispatch_hermetic_succeeds(tmp_path, env):
    staging = _staging_repo(tmp_path)
    cp = _run_pipeline(staging, args=["--phase", "mi", "--dry-run-all"], env=env)
    assert cp.returncode == 0, cp.stderr
    summary = json.loads((staging / ".welle-3-day-0-artifacts"
                          / "phase-mi-summary.json").read_text())
    assert summary["verdict"] == "green"
    assert summary["hermetic"] is True
    assert summary["conclusion"] == "hermetic"
    assert summary["workflow"] == "phase-3c-welle-3-validation.yml"


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
    summary = json.loads((staging / ".welle-3-day-0-artifacts"
                          / "phase-mi-summary.json").read_text())
    assert summary["verdict"] == "yellow"
    assert summary["conclusion"] == "not-waited"


def test_phase_mi5_cross_modul_stress_pass_sets_henrik_caution(tmp_path, env):
    """Phase Mi.5 — the Henrik-Caution independent oracle. On a passing
    Cross-Modul-Stress run the envelope flags
    `henrik_caution_applied=true` and the verdict is green."""
    staging = _staging_repo(tmp_path)
    _stub_cross_modul_stress(staging, threshold_pass=True, rc=0)
    cp = _run_pipeline(staging, args=["--phase", "mi5", "--dry-run-all"], env=env)
    assert cp.returncode == 0, cp.stderr
    summary = json.loads((staging / ".welle-3-day-0-artifacts"
                          / "phase-mi5-summary.json").read_text())
    assert summary["phase"] == "mi5"
    assert summary["verdict"] == "green"
    assert summary["exit_code"] == 0
    assert summary["oracle"] == "cross-modul-stress"
    assert summary["oracle_pr"] == "PR-197"
    assert summary["threshold_pass"] == "true"
    assert summary["henrik_caution_applied"] is True
    # Independence rationale is recorded explicitly so audit can read it.
    assert "cross-modul-axes-do-not-touch-bridge-audit-writer" \
        in summary["independence_rationale"]


def test_phase_mi5_cross_modul_stress_fail_blocks(tmp_path, env):
    """A failing Cross-Modul-Stress run blocks Welle-3 outright. The
    Henrik-Caution stamp is NOT applied."""
    staging = _staging_repo(tmp_path)
    _stub_cross_modul_stress(staging, threshold_pass=False, rc=1)
    cp = _run_pipeline(staging, args=["--phase", "mi5", "--dry-run-all"], env=env)
    assert cp.returncode == 2, cp.stderr
    summary = json.loads((staging / ".welle-3-day-0-artifacts"
                          / "phase-mi5-summary.json").read_text())
    assert summary["verdict"] == "red"
    assert summary["henrik_caution_applied"] is False
    assert summary["threshold_pass"] == "false"


def test_phase_do_hermetic_emits_green_summary(tmp_path, env):
    staging = _staging_repo(tmp_path)
    cp = _run_pipeline(staging, args=["--phase", "do", "--dry-run-all"], env=env)
    assert cp.returncode == 0, cp.stderr
    summary = json.loads((staging / ".welle-3-day-0-artifacts"
                          / "phase-do-summary.json").read_text())
    assert summary["verdict"] == "green"
    assert summary["hermetic"] is True
    # When no telemetry snapshot was supplied, the field is recorded
    # as not-present.
    assert summary["welle_3_telemetry"]["snapshot_present"] is False


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
    summary = json.loads((staging / ".welle-3-day-0-artifacts"
                          / "phase-do-summary.json").read_text())
    assert summary["verdict"] == "red"
    assert summary["pr_review"]["changes_requested"] == 1


def test_phase_do_red_when_telemetry_red_flag_set(tmp_path, env):
    """A welle-3-telemetry-emitter snapshot whose
    `divergence_red_flag=true` forces Phase Do to red — the Henrik-
    caution divergence-alert is a hard block at the operator pipeline
    layer."""
    staging = _staging_repo(tmp_path)
    snapshot = staging / "telemetry-snapshot.json"
    snapshot.write_text(json.dumps({
        "schema_id": "welle-3-telemetry-snapshot/v1",
        "divergence_red_flag": True,
        "divergence_pct": 1.25,
        "consistency_score_pct": 88.4,
    }))
    cp = _run_pipeline(
        staging,
        args=["--phase", "do", "--dry-run-all",
              "--telemetry-snapshot", str(snapshot)],
        env=env,
    )
    assert cp.returncode == 2, cp.stderr
    summary = json.loads((staging / ".welle-3-day-0-artifacts"
                          / "phase-do-summary.json").read_text())
    assert summary["verdict"] == "red"
    assert summary["welle_3_telemetry"]["snapshot_present"] is True
    assert summary["welle_3_telemetry"]["divergence_red_flag"] == "true"


def test_phase_fr_aggregates_four_phase_artifacts(tmp_path, env):
    staging = _staging_repo(tmp_path)
    workdir = staging / ".welle-3-day-0-artifacts"
    workdir.mkdir()
    for ph in ("mo", "mi", "do"):
        (workdir / f"phase-{ph}-summary.json").write_text(json.dumps({
            "phase": ph, "verdict": "green", "exit_code": 0
        }))
    # mi5 with the Henrik-Caution stamp set.
    (workdir / "phase-mi5-summary.json").write_text(json.dumps({
        "phase": "mi5",
        "verdict": "green",
        "exit_code": 0,
        "henrik_caution_applied": True,
        "oracle": "cross-modul-stress",
    }))
    cp = _run_pipeline(staging, args=["--phase", "fr", "--dry-run-all"], env=env)
    assert cp.returncode == 0, cp.stderr
    decision = json.loads(
        (workdir / "cutover-acceptance-decision-welle-3.json").read_text()
    )
    assert decision["decision"] == "go"
    assert decision["verdict"] == "green"
    assert decision["exit_code"] == 0
    assert decision["component"] == "bridge_audit_writer"
    assert decision["component_resolver_alias"] == "anchor_emitter"
    assert decision["adr"] == "ADR-0066"
    assert decision["welle"] == 3
    assert decision["henrik_caution_applied"] is True
    assert decision["phases"]["mi5"]["oracle"] == "cross-modul-stress"


def test_phase_fr_no_go_when_any_phase_red(tmp_path, env):
    staging = _staging_repo(tmp_path)
    workdir = staging / ".welle-3-day-0-artifacts"
    workdir.mkdir()
    (workdir / "phase-mo-summary.json").write_text(json.dumps(
        {"phase": "mo", "verdict": "green", "exit_code": 0}))
    (workdir / "phase-mi-summary.json").write_text(json.dumps(
        {"phase": "mi", "verdict": "red", "exit_code": 2}))
    (workdir / "phase-mi5-summary.json").write_text(json.dumps(
        {"phase": "mi5", "verdict": "green", "exit_code": 0,
         "henrik_caution_applied": True}))
    (workdir / "phase-do-summary.json").write_text(json.dumps(
        {"phase": "do", "verdict": "green", "exit_code": 0}))
    cp = _run_pipeline(staging, args=["--phase", "fr", "--dry-run-all"], env=env)
    assert cp.returncode == 2, cp.stderr
    decision = json.loads(
        (workdir / "cutover-acceptance-decision-welle-3.json").read_text()
    )
    assert decision["decision"] == "no-go"
    assert decision["verdict"] == "red"
    assert decision["phases"]["mi"]["verdict"] == "red"


def test_full_pipeline_all_phases_emit_decision_json(tmp_path, env):
    staging = _staging_repo(tmp_path)
    _stub_aggregator(staging, status="green", rc=0)
    _stub_dry_run(staging, dry_run="completed", rc=0)
    _stub_cross_modul_stress(staging, threshold_pass=True, rc=0)
    cp = _run_pipeline(staging, args=["--phase", "all", "--dry-run-all"], env=env)
    assert cp.returncode == 0, cp.stderr
    workdir = staging / ".welle-3-day-0-artifacts"
    for ph in ("mo", "mi", "mi5", "do", "fr"):
        assert (workdir / f"phase-{ph}-summary.json").exists(), \
            f"missing summary for phase {ph}"
    decision = json.loads(
        (workdir / "cutover-acceptance-decision-welle-3.json").read_text()
    )
    assert decision["decision"] == "go"
    assert decision["verdict"] == "green"
    assert decision["welle"] == 3
    assert decision["henrik_caution_applied"] is True


def test_invalid_phase_argument_rejected(tmp_path, env):
    staging = _staging_repo(tmp_path)
    cp = _run_pipeline(staging, args=["--phase", "garbage", "--dry-run-all"], env=env)
    assert cp.returncode == 2
    assert "invalid --phase" in cp.stderr
