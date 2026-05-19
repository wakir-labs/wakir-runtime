# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic CI-substrate tests for the Tag-56 Phase-3c Watch-Day-
Practice-Run workflow (``.github/workflows/phase-3c-watch-day-
practice-run.yml``) plus its aggregator helper
(``tooling/ci/aggregate_watch_day_practice_run_verdict.py``).

Test scope
----------

* Workflow YAML structural shape:
  - four trigger sources (workflow_dispatch + schedule + push + PR),
  - exactly five jobs in the documented order,
  - Step 5 (decision-aggregation) ``needs`` the four upstream steps
    and is gated on ``if: always()`` so it always runs,
  - Tue 05:00 UTC cron present,
  - push + pull_request path-filters cover spec/verdict/simulator,
  - Step 2 uploads ``watch-day-practice-run-report`` artifact,
  - Step 5 uploads ``watch-day-practice-run-verdict`` artifact.

* Aggregator helper truth-table walk
  (``tooling/ci/aggregate_watch_day_practice_run_verdict.py``):
  - 3**4 = 81 (green|yellow|red)**4 permutations -> READY/CAUTION/
    BLOCK per the documented rule.
  - Empty / unknown step-statuses default to red.
  - JSON envelope schema fields.

* Pin-mode and sequence-mode behaviour:
  - Live practice-run report (from the in-tree Tag-55 simulator)
    passes both pin and sequence modes.
  - Mutated report (verdict swap) trips pin-mode with exit 2.
  - Mutated report (sequence_validation_ok=false) trips sequence-
    mode with exit 2.
  - Missing report -> exit 1.

Sandbox boundary: pure file-system reads + python imports + yaml
parse + subprocess to the in-tree simulator (hermetic by design).
No podman, no NATS, no GitHub API.

Anchor: Tag-56 Noa-SRE Watch-Day-Practice-Run CI-Gate.
Author: Noa Bergstroem (SRE)
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from itertools import product
from pathlib import Path
from typing import Any, Iterable

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "phase-3c-watch-day-practice-run.yml"
)
AGGREGATOR_SCRIPT = (
    REPO_ROOT
    / "tooling"
    / "ci"
    / "aggregate_watch_day_practice_run_verdict.py"
)
SIMULATOR_SCRIPT = (
    REPO_ROOT / "scripts" / "observability" / "watch-day-practice-run.py"
)
SPEC_PATH = (
    REPO_ROOT / "docs" / "observability" / "pre-cutover-watch-day-spec.md"
)
VERDICT_SCRIPT = (
    REPO_ROOT / "scripts" / "observability" / "pre-cutover-watch-day-verdict.py"
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW_PATH.is_file(), f"workflow missing: {WORKFLOW_PATH}"
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_yaml(workflow_text: str) -> dict[str, Any]:
    return yaml.safe_load(workflow_text)


@pytest.fixture(scope="module")
def aggregator():
    return _load_module(
        "tag56_watch_day_aggregator", AGGREGATOR_SCRIPT
    )


@pytest.fixture
def practice_run_report(tmp_path: Path) -> dict[str, Any]:
    """Invoke the in-tree Tag-55 simulator and return its JSON report.

    Hermetic-by-design: the simulator does not touch network or
    podman; see its module docstring §Design contract.
    """
    assert SIMULATOR_SCRIPT.is_file(), f"simulator missing: {SIMULATOR_SCRIPT}"
    out_path = tmp_path / "report.json"
    with out_path.open("w", encoding="utf-8") as fh:
        rc = subprocess.run(
            [sys.executable, str(SIMULATOR_SCRIPT), "--json"],
            stdout=fh,
            stderr=subprocess.PIPE,
            cwd=str(REPO_ROOT),
            check=False,
        )
    assert rc.returncode == 0, (
        f"simulator failed: rc={rc.returncode}, stderr={rc.stderr!r}"
    )
    return json.loads(out_path.read_text(encoding="utf-8"))


@pytest.fixture
def practice_run_report_path(
    tmp_path: Path, practice_run_report: dict[str, Any]
) -> Path:
    p = tmp_path / "report.json"
    p.write_text(json.dumps(practice_run_report), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. Workflow YAML structural shape
# ---------------------------------------------------------------------------


def test_workflow_yaml_parses(workflow_yaml: dict[str, Any]) -> None:
    assert workflow_yaml["name"] == "phase-3c-watch-day-practice-run"


def test_workflow_has_four_triggers(workflow_yaml: dict[str, Any]) -> None:
    # PyYAML parses ``on:`` as the boolean True due to the YAML 1.1
    # ``yes/no/on/off`` convention. Both keys are accepted here so
    # the test stays robust against future YAML loader changes.
    on = workflow_yaml.get("on") or workflow_yaml.get(True)
    assert on is not None, "missing on: section"
    assert "workflow_dispatch" in on
    assert "schedule" in on
    assert "push" in on
    assert "pull_request" in on


def test_workflow_tuesday_cron_present(workflow_yaml: dict[str, Any]) -> None:
    on = workflow_yaml.get("on") or workflow_yaml.get(True)
    schedules = on["schedule"]
    crons = [s["cron"] for s in schedules]
    assert "0 5 * * 2" in crons, f"missing Tue 05:00 UTC cron in {crons!r}"


def test_workflow_path_filter_covers_substrates(
    workflow_yaml: dict[str, Any],
) -> None:
    on = workflow_yaml.get("on") or workflow_yaml.get(True)
    must = {
        "docs/observability/pre-cutover-watch-day-spec.md",
        "scripts/observability/pre-cutover-watch-day-verdict.py",
        "scripts/observability/watch-day-practice-run.py",
    }
    for trigger in ("push", "pull_request"):
        paths = set(on[trigger]["paths"])
        missing = must - paths
        assert not missing, f"{trigger} path-filter missing: {missing!r}"


def test_workflow_five_jobs_in_order(workflow_yaml: dict[str, Any]) -> None:
    jobs = workflow_yaml["jobs"]
    expected_order = [
        "step-1-substrate-inventory-check",
        "step-2-hermetic-practice-run",
        "step-3-per-scenario-verdict-pinning",
        "step-4-slot-sequence-validation",
        "step-5-decision-aggregation",
    ]
    assert list(jobs.keys()) == expected_order


def test_workflow_step5_needs_and_always(
    workflow_yaml: dict[str, Any],
) -> None:
    step5 = workflow_yaml["jobs"]["step-5-decision-aggregation"]
    needs = step5["needs"]
    assert set(needs) == {
        "step-1-substrate-inventory-check",
        "step-2-hermetic-practice-run",
        "step-3-per-scenario-verdict-pinning",
        "step-4-slot-sequence-validation",
    }
    if_expr = step5.get("if")
    assert if_expr == "always()", f"step5 if must be always(), got {if_expr!r}"


def test_workflow_step2_uploads_report_artifact(
    workflow_text: str,
) -> None:
    # The report-artifact name is referenced by step 3 + 4 download
    # steps; an accidental rename would break the chain.
    assert "name: watch-day-practice-run-report" in workflow_text
    assert "actions/upload-artifact@v4" in workflow_text
    assert "actions/download-artifact@v4" in workflow_text


def test_workflow_step5_uploads_verdict_artifact(
    workflow_text: str,
) -> None:
    assert "name: watch-day-practice-run-verdict" in workflow_text


def test_workflow_concurrency_per_ref(workflow_yaml: dict[str, Any]) -> None:
    cc = workflow_yaml["concurrency"]
    assert cc["group"] == "phase-3c-watch-day-practice-run-${{ github.ref }}"
    assert cc["cancel-in-progress"] is False


# ---------------------------------------------------------------------------
# 2. Aggregator helper - aggregate mode truth-table
# ---------------------------------------------------------------------------


def test_aggregator_truth_table(aggregator, tmp_path: Path) -> None:
    """Walk all 3**4 = 81 (green|yellow|red)**4 step-status permutations."""
    output_path = tmp_path / "verdict.json"
    statuses_seq = ("green", "yellow", "red")
    for s1, s2, s3, s4 in product(statuses_seq, repeat=4):
        env = {
            "STEP1_STATUS": s1,
            "STEP2_STATUS": s2,
            "STEP3_STATUS": s3,
            "STEP4_STATUS": s4,
            "INVENTORY_MISSING": "",
        }
        # Run aggregator via in-process call (avoid subprocess overhead
        # over 81 iterations).
        prev_env = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            rc = aggregator.main(
                ["--mode", "aggregate", "--output", str(output_path)]
            )
        finally:
            for k, v in prev_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        assert rc == 0
        envelope = json.loads(output_path.read_text(encoding="utf-8"))
        verdict = envelope["verdict"]
        reds = sum(1 for x in (s1, s2, s3, s4) if x == "red")
        yellows = sum(1 for x in (s1, s2, s3, s4) if x == "yellow")
        if reds == 0 and yellows == 0:
            assert verdict == "READY", (s1, s2, s3, s4, verdict)
        elif reds == 0 and yellows == 1:
            assert verdict == "CAUTION", (s1, s2, s3, s4, verdict)
        else:
            assert verdict == "BLOCK", (s1, s2, s3, s4, verdict)


def test_aggregator_missing_env_defaults_to_red(
    aggregator, tmp_path: Path
) -> None:
    output_path = tmp_path / "verdict.json"
    # Clear all step-status env-vars; aggregator must default to red.
    keys = ("STEP1_STATUS", "STEP2_STATUS", "STEP3_STATUS", "STEP4_STATUS")
    saved = {k: os.environ.pop(k, None) for k in keys}
    os.environ.pop("INVENTORY_MISSING", None)
    try:
        rc = aggregator.main(
            ["--mode", "aggregate", "--output", str(output_path)]
        )
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    assert rc == 0
    envelope = json.loads(output_path.read_text(encoding="utf-8"))
    assert envelope["verdict"] == "BLOCK"
    for v in envelope["steps"].values():
        assert v == "red"


def test_aggregator_envelope_schema(aggregator, tmp_path: Path) -> None:
    output_path = tmp_path / "verdict.json"
    env = {
        "STEP1_STATUS": "green",
        "STEP2_STATUS": "green",
        "STEP3_STATUS": "green",
        "STEP4_STATUS": "green",
        "INVENTORY_MISSING": "docs/observability/pre-cutover-watch-day-spec.md",
    }
    prev = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        rc = aggregator.main(
            ["--mode", "aggregate", "--output", str(output_path)]
        )
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert rc == 0
    envelope = json.loads(output_path.read_text(encoding="utf-8"))
    # Schema fields:
    assert envelope["verdict"] == "READY"
    assert envelope["schema_version"] == 1
    assert set(envelope["steps"].keys()) == {
        "step1_inventory",
        "step2_hermetic_practice_run",
        "step3_per_scenario_verdict_pinning",
        "step4_slot_sequence_validation",
    }
    # INVENTORY_MISSING parses into a list.
    assert envelope["inventory_missing"] == [
        "docs/observability/pre-cutover-watch-day-spec.md"
    ]


# ---------------------------------------------------------------------------
# 3. Pin + sequence mode against the live in-tree simulator
# ---------------------------------------------------------------------------


def test_pin_mode_passes_on_real_simulator(
    aggregator, practice_run_report_path: Path
) -> None:
    rc = aggregator.main(
        ["--mode", "pin", "--report", str(practice_run_report_path)]
    )
    assert rc == 0


def test_sequence_mode_passes_on_real_simulator(
    aggregator, practice_run_report_path: Path
) -> None:
    rc = aggregator.main(
        ["--mode", "sequence", "--report", str(practice_run_report_path)]
    )
    assert rc == 0


def test_pin_mode_catches_verdict_drift(
    aggregator,
    practice_run_report: dict[str, Any],
    tmp_path: Path,
) -> None:
    """A mutated report where one scenario's computed_verdict diverges
    from expected_verdict must trip pin-mode (exit 2)."""
    mutated = copy.deepcopy(practice_run_report)
    # Flip the first scenario's computed_verdict.
    mutated["scenarios"][0]["computed_verdict"] = "RED"
    mutated["scenarios"][0]["expected_verdict"] = "GREEN"
    report_path = tmp_path / "mutated.json"
    report_path.write_text(json.dumps(mutated), encoding="utf-8")
    rc = aggregator.main(
        ["--mode", "pin", "--report", str(report_path)]
    )
    assert rc == 2


def test_pin_mode_catches_red_blocker_drift(
    aggregator,
    practice_run_report: dict[str, Any],
    tmp_path: Path,
) -> None:
    mutated = copy.deepcopy(practice_run_report)
    # Inject a phantom red-blocker into a passing scenario.
    mutated["scenarios"][0]["computed_red_blockers"] = ["phantom-blocker"]
    mutated["scenarios"][0]["expected_red_blockers"] = []
    report_path = tmp_path / "mutated.json"
    report_path.write_text(json.dumps(mutated), encoding="utf-8")
    rc = aggregator.main(
        ["--mode", "pin", "--report", str(report_path)]
    )
    assert rc == 2


def test_sequence_mode_catches_drift(
    aggregator,
    practice_run_report: dict[str, Any],
    tmp_path: Path,
) -> None:
    mutated = copy.deepcopy(practice_run_report)
    mutated["scenarios"][0]["sequence_validation_ok"] = False
    mutated["scenarios"][0]["sequence_validation_errors"] = ["mock-drift"]
    report_path = tmp_path / "mutated.json"
    report_path.write_text(json.dumps(mutated), encoding="utf-8")
    rc = aggregator.main(
        ["--mode", "sequence", "--report", str(report_path)]
    )
    assert rc == 2


def test_pin_mode_missing_report_returns_exit_1(
    aggregator, tmp_path: Path
) -> None:
    missing = tmp_path / "does-not-exist.json"
    rc = aggregator.main(["--mode", "pin", "--report", str(missing)])
    assert rc == 1


def test_sequence_mode_missing_report_returns_exit_1(
    aggregator, tmp_path: Path
) -> None:
    missing = tmp_path / "does-not-exist.json"
    rc = aggregator.main(["--mode", "sequence", "--report", str(missing)])
    assert rc == 1


def test_pin_mode_malformed_report_returns_exit_1(
    aggregator, tmp_path: Path
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not-json{", encoding="utf-8")
    rc = aggregator.main(["--mode", "pin", "--report", str(bad)])
    assert rc == 1


# ---------------------------------------------------------------------------
# 4. Cross-substrate sanity
# ---------------------------------------------------------------------------


def test_workflow_references_aggregator_script(workflow_text: str) -> None:
    """The aggregator script path must literally appear in the YAML so
    a rename of the script breaks the workflow loud and at review-
    time, not silently at runtime."""
    assert (
        "tooling/ci/aggregate_watch_day_practice_run_verdict.py"
        in workflow_text
    )


def test_simulator_and_spec_and_verdict_exist_on_head() -> None:
    """The workflow's Step 1 inventory-check depends on these three
    paths. They must exist on every PR that touches this test
    file."""
    assert SPEC_PATH.is_file(), f"spec missing: {SPEC_PATH}"
    assert VERDICT_SCRIPT.is_file(), f"verdict script missing: {VERDICT_SCRIPT}"
    assert SIMULATOR_SCRIPT.is_file(), f"simulator missing: {SIMULATOR_SCRIPT}"


def test_aggregator_help_lists_three_modes(aggregator) -> None:
    parser = aggregator._build_parser()
    # argparse stores ``choices`` on the ``--mode`` action.
    mode_action = next(
        a for a in parser._actions if "--mode" in (a.option_strings or [])
    )
    assert set(mode_action.choices) == {"pin", "sequence", "aggregate"}
