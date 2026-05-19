# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-63 Operator-Trigger + Alert-Routing Integration regression tests.

Covers (>= 12 tests; ships 16):

  T01  Helper module importable; canonical verdict constants present.
  T02  ROUTING_TABLES has exactly 4 entries matching Tag-58 mirror-pair set.
  T03  TRIGGER_LANDING_ANCHORS non-empty and contains watch-day anchor.
  T04  summarize_routing_table() returns present=True for each of the 4
       canonical paths on the real repo head.
  T05  summarize_routing_table() captures non-zero alertnames or
       failure-modes for every routing-table on real repo head.
  T06  stage_routing_propagation() green on real repo head.
  T07  stage_routing_propagation() red when 2+ routing-tables missing
       (synthesized isolated tree).
  T08  stage_routing_propagation() yellow when exactly one table is
       empty (alertnames=0, failure_modes=0) and rest are populated.
  T09  stage_trigger_event_landing() green on real repo head.
  T10  stage_trigger_event_landing() red when 2+ tables have zero
       landing-anchors AND zero failure-modes.
  T11  stage_trigger_event_landing() yellow when exactly one table is
       weak (no anchors, no failure-modes).
  T12  aggregate_verdict(): all-green -> INTEGRATION-INTACT.
  T13  aggregate_verdict(): one-yellow -> INTEGRATION-DRIFT.
  T14  aggregate_verdict(): two-yellow -> INTEGRATION-DEFECT.
  T15  aggregate_verdict(): any-red -> INTEGRATION-DEFECT.
  T16  CLI `full` end-to-end on real repo head: exit 0 and writes a
       verdict envelope with schema_version=1, tag=63, valid verdict.
  T17  Workflow YAML mentions Stage 1..Stage 4 jobs by canonical name.
  T18  Workflow YAML path-filter contains all Tag-63 substrates.
  T19  Tag-63 workflow has NO push:/schedule: triggers (only PR + dispatch).
  T20  Stage-envelope schema is stable (schema_version=1, tag=63,
       tool="verify-trigger-routing-integration").

Anchor: Tag-63 Marathon-Continuous-Mode Pre-KW-24 Operator-Trigger +
        Alert-Routing Integration-Test.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "tooling/ci/verify_trigger_routing_integration.py"
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github/workflows/operator-trigger-alert-routing-integration.yml"
)
TAG58_AUDIT_HELPER = REPO_ROOT / "tooling/ci/audit_alert_routing_cross_repo_mirror.py"


def _load_helper():
    mod_name = "verify_trigger_routing_integration"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, str(HELPER_PATH))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_tag58_audit():
    mod_name = "audit_alert_routing_cross_repo_mirror"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, str(TAG58_AUDIT_HELPER))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def helper():
    return _load_helper()


# ---------------------------------------------------------------------------
# T01 - helper module importable + canonical verdict constants present
# ---------------------------------------------------------------------------


def test_t01_helper_constants_present(helper) -> None:
    assert helper.VERDICT_INTACT == "INTEGRATION-INTACT"
    assert helper.VERDICT_DRIFT == "INTEGRATION-DRIFT"
    assert helper.VERDICT_DEFECT == "INTEGRATION-DEFECT"
    assert helper.STAGE_GREEN == "green"
    assert helper.STAGE_YELLOW == "yellow"
    assert helper.STAGE_RED == "red"
    assert helper.CANONICAL_TRIGGER_WORKFLOW == "phase-3c-watch-day-practice-run.yml"


# ---------------------------------------------------------------------------
# T02 - ROUTING_TABLES matches Tag-58 mirror-pair set (4 entries, same paths)
# ---------------------------------------------------------------------------


def test_t02_routing_tables_match_tag58_mirror_pairs(helper) -> None:
    tag58 = _load_tag58_audit()
    tag58_paths = {p.runtime_path for p in tag58.MIRROR_PAIRS}
    tag63_paths = {t.path for t in helper.ROUTING_TABLES}
    assert tag63_paths == tag58_paths, (
        f"Tag-63 ROUTING_TABLES drift from Tag-58 MIRROR_PAIRS:\n"
        f"  tag58: {sorted(tag58_paths)}\n"
        f"  tag63: {sorted(tag63_paths)}"
    )
    assert len(helper.ROUTING_TABLES) == 4


# ---------------------------------------------------------------------------
# T03 - TRIGGER_LANDING_ANCHORS contains the canonical watch-day anchor
# ---------------------------------------------------------------------------


def test_t03_landing_anchors_contain_watch_day(helper) -> None:
    anchors = helper.TRIGGER_LANDING_ANCHORS
    assert "watch-day" in anchors
    assert "0 5 * * 2" in anchors
    assert len(anchors) >= 8


# ---------------------------------------------------------------------------
# T04 - every routing-table present on real repo head
# ---------------------------------------------------------------------------


def test_t04_all_routing_tables_present_on_real_repo(helper) -> None:
    for table in helper.ROUTING_TABLES:
        s = helper.summarize_routing_table(REPO_ROOT, table)
        assert s["present"], f"missing routing-table: {table.path}"
        assert s["size_bytes"] > 0


# ---------------------------------------------------------------------------
# T05 - each routing-table has non-zero alertnames or failure-modes
# ---------------------------------------------------------------------------


def test_t05_routing_tables_have_alertnames_or_failure_modes(helper) -> None:
    for table in helper.ROUTING_TABLES:
        s = helper.summarize_routing_table(REPO_ROOT, table)
        assert s["alertnames"] or s["failure_modes"], (
            f"routing-table {table.path} has neither alertnames "
            f"nor failure-modes: {s!r}"
        )


# ---------------------------------------------------------------------------
# T06 - stage_routing_propagation green on real repo head
# ---------------------------------------------------------------------------


def test_t06_stage_routing_propagation_green(helper) -> None:
    result = helper.stage_routing_propagation(REPO_ROOT)
    assert result.status == helper.STAGE_GREEN, (
        f"expected green, got {result.status} with notes={result.notes}"
    )


# ---------------------------------------------------------------------------
# T07 - stage_routing_propagation red when 2+ tables missing
# ---------------------------------------------------------------------------


def test_t07_stage_routing_propagation_red_when_missing(
    helper, tmp_path: Path
) -> None:
    # Empty isolated tree -- all 4 tables missing.
    fake_root = tmp_path / "isolated"
    fake_root.mkdir()
    result = helper.stage_routing_propagation(fake_root)
    assert result.status == helper.STAGE_RED
    assert len(result.details["missing"]) == 4


# ---------------------------------------------------------------------------
# T08 - stage_routing_propagation yellow when exactly one table empty
# ---------------------------------------------------------------------------


def test_t08_stage_routing_propagation_yellow_when_one_empty(
    helper, tmp_path: Path
) -> None:
    fake_root = tmp_path / "isolated"
    fake_root.mkdir()
    # Create all 4 with content -- 3 with alertnames, 1 empty.
    populated = {
        "docs/observability/pre-mortem-failure-mode-notify-catalog.md":
            "# notify-catalog\n`WakirPhase3FailureModeA1` -- Class-A1 -- watch-day\n",
        "dashboards/phase-3-marathon-alerts.yaml":
            "groups:\n  - name: alerts\n    rules:\n      - alert: WakirPhase3FailureModeA1\n        expr: 1\n",
        "dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml":
            "# placeholder -- no alertnames, no failure-modes\n",
        "scripts/observability/alert-rule-to-mira-notify-bridge.py":
            'ALERT_CATALOG = {\n    "WakirPhase3FailureModeA1": {\n        "failure_mode_id": "A1",\n    },\n}\n',
    }
    for rel, content in populated.items():
        p = fake_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    result = helper.stage_routing_propagation(fake_root)
    assert result.status == helper.STAGE_YELLOW, (
        f"expected yellow, got {result.status} notes={result.notes}"
    )


# ---------------------------------------------------------------------------
# T09 - stage_trigger_event_landing green on real repo head
# ---------------------------------------------------------------------------


def test_t09_stage_trigger_event_landing_green(helper) -> None:
    result = helper.stage_trigger_event_landing(REPO_ROOT)
    assert result.status == helper.STAGE_GREEN, (
        f"expected green, got {result.status} with notes={result.notes}"
    )
    # All four paths must report landed = True.
    assert all(result.details["landing"].values())


# ---------------------------------------------------------------------------
# T10 - stage_trigger_event_landing red when 2+ tables weak
# ---------------------------------------------------------------------------


def test_t10_stage_trigger_event_landing_red_when_weak(helper) -> None:
    # Build synthetic summaries: 2 tables with no anchors + no failure-modes.
    summaries = [
        {
            "path": "docs/observability/pre-mortem-failure-mode-notify-catalog.md",
            "kind": "markdown",
            "present": True,
            "size_bytes": 100,
            "alertnames": ["SomeAlert"],
            "failure_modes": [],
            "landing_anchors": [],
        },
        {
            "path": "dashboards/phase-3-marathon-alerts.yaml",
            "kind": "yaml-alerts",
            "present": True,
            "size_bytes": 100,
            "alertnames": ["SomeAlert"],
            "failure_modes": [],
            "landing_anchors": [],
        },
        {
            "path": "dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml",
            "kind": "yaml-alerts",
            "present": True,
            "size_bytes": 100,
            "alertnames": ["SomeAlert"],
            "failure_modes": ["A1"],
            "landing_anchors": ["watch-day"],
        },
        {
            "path": "scripts/observability/alert-rule-to-mira-notify-bridge.py",
            "kind": "python-catalog",
            "present": True,
            "size_bytes": 100,
            "alertnames": ["SomeAlert"],
            "failure_modes": ["A1"],
            "landing_anchors": ["watch-day"],
        },
    ]
    result = helper.stage_trigger_event_landing(REPO_ROOT, summaries=summaries)
    assert result.status == helper.STAGE_RED, (
        f"expected red, got {result.status} notes={result.notes}"
    )
    assert len(result.details["weak"]) == 2


# ---------------------------------------------------------------------------
# T11 - stage_trigger_event_landing yellow when exactly one weak
# ---------------------------------------------------------------------------


def test_t11_stage_trigger_event_landing_yellow_when_one_weak(helper) -> None:
    summaries = [
        {
            "path": "a",
            "kind": "markdown",
            "present": True,
            "size_bytes": 1,
            "alertnames": [],
            "failure_modes": [],
            "landing_anchors": [],
        },
        {
            "path": "b",
            "kind": "yaml-alerts",
            "present": True,
            "size_bytes": 1,
            "alertnames": [],
            "failure_modes": ["A1"],
            "landing_anchors": [],
        },
        {
            "path": "c",
            "kind": "yaml-alerts",
            "present": True,
            "size_bytes": 1,
            "alertnames": [],
            "failure_modes": [],
            "landing_anchors": ["watch-day"],
        },
        {
            "path": "d",
            "kind": "python-catalog",
            "present": True,
            "size_bytes": 1,
            "alertnames": [],
            "failure_modes": ["A1"],
            "landing_anchors": ["watch-day"],
        },
    ]
    result = helper.stage_trigger_event_landing(REPO_ROOT, summaries=summaries)
    assert result.status == helper.STAGE_YELLOW
    assert result.details["weak"] == ["a"]


# ---------------------------------------------------------------------------
# T12-T15 - aggregate_verdict semantics
# ---------------------------------------------------------------------------


def test_t12_aggregate_all_green(helper) -> None:
    assert helper.aggregate_verdict("green", "green", "green") == helper.VERDICT_INTACT


def test_t13_aggregate_one_yellow(helper) -> None:
    assert helper.aggregate_verdict("green", "yellow", "green") == helper.VERDICT_DRIFT
    assert helper.aggregate_verdict("yellow", "green", "green") == helper.VERDICT_DRIFT
    assert helper.aggregate_verdict("green", "green", "yellow") == helper.VERDICT_DRIFT


def test_t14_aggregate_two_yellow(helper) -> None:
    assert helper.aggregate_verdict("yellow", "yellow", "green") == helper.VERDICT_DEFECT
    assert helper.aggregate_verdict("yellow", "yellow", "yellow") == helper.VERDICT_DEFECT


def test_t15_aggregate_any_red(helper) -> None:
    assert helper.aggregate_verdict("red", "green", "green") == helper.VERDICT_DEFECT
    assert helper.aggregate_verdict("green", "red", "yellow") == helper.VERDICT_DEFECT
    assert helper.aggregate_verdict("yellow", "yellow", "red") == helper.VERDICT_DEFECT


# ---------------------------------------------------------------------------
# T16 - CLI full end-to-end on real repo head: exit 0 + envelope shape
# ---------------------------------------------------------------------------


def test_t16_cli_full_end_to_end(helper, tmp_path: Path) -> None:
    scratch = tmp_path / "out"
    proc = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "full",
            "--repo-root",
            str(REPO_ROOT),
            "--scratch-dir",
            str(scratch),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, (
        f"full CLI failed: rc={proc.returncode}\n"
        f"stdout: {proc.stdout}\n"
        f"stderr: {proc.stderr}"
    )
    verdict_path = scratch / "trigger-routing-integration-verdict.json"
    assert verdict_path.is_file()
    data = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["tag"] == 63
    assert data["tool"] == "verify-trigger-routing-integration"
    assert data["verdict"] in {
        helper.VERDICT_INTACT,
        helper.VERDICT_DRIFT,
        helper.VERDICT_DEFECT,
    }
    assert set(data["stages"].keys()) == {
        "stage_1_operator_trigger_simulation",
        "stage_2_alert_routing_propagation_check",
        "stage_3_trigger_event_landing_verification",
    }
    # On a clean repo, integration must be intact.
    assert data["verdict"] == helper.VERDICT_INTACT


# ---------------------------------------------------------------------------
# T17 - workflow YAML mentions Stage 1..4 by canonical name
# ---------------------------------------------------------------------------


def test_t17_workflow_jobs_named(helper) -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    for token in (
        "stage-1-operator-trigger-simulation",
        "stage-2-alert-routing-propagation-check",
        "stage-3-trigger-event-landing-verification",
        "stage-4-aggregate-verdict",
    ):
        assert token in text, f"workflow missing job id: {token}"
    # Stage display-names visible to required-status-check setup
    for token in (
        "Stage 1 Operator-Trigger-Simulation",
        "Stage 2 Alert-Routing-Propagation-Check",
        "Stage 3 Trigger-Event-Landing-Verification",
        "Stage 4 Aggregate Verdict",
    ):
        assert token in text, f"workflow missing job display-name: {token}"


# ---------------------------------------------------------------------------
# T18 - workflow path-filter mentions all Tag-63 substrates
# ---------------------------------------------------------------------------


def test_t18_workflow_path_filter_substrates() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    expected = (
        ".github/workflows/operator-trigger-alert-routing-integration.yml",
        ".github/workflows/watch-day-operator-trigger-simulation.yml",
        ".github/workflows/alert-routing-cross-repo-mirror.yml",
        "tooling/ci/verify_trigger_routing_integration.py",
        "tooling/ci/simulate_watch_day_operator_trigger.py",
        "tooling/ci/audit_alert_routing_cross_repo_mirror.py",
        "docs/observability/pre-mortem-failure-mode-notify-catalog.md",
        "dashboards/phase-3-marathon-alerts.yaml",
        "dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml",
        "scripts/observability/alert-rule-to-mira-notify-bridge.py",
        "tests/observability/test_trigger_routing_integration_tag63.py",
    )
    for rel in expected:
        assert rel in text, f"path-filter missing substrate: {rel}"


# ---------------------------------------------------------------------------
# T19 - workflow has NO push:/schedule: triggers (only PR + dispatch)
# ---------------------------------------------------------------------------


def test_t19_workflow_no_push_no_schedule() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    # The "on:" block is the prefix; check no `push:` or `schedule:` keys
    # appear at indentation level 2 (inside `on:`).
    assert not re.search(r"^  push:", text, re.MULTILINE), (
        "Tag-63 workflow must not have push: trigger"
    )
    assert not re.search(r"^  schedule:", text, re.MULTILINE), (
        "Tag-63 workflow must not have schedule: trigger"
    )
    assert "workflow_dispatch:" in text
    assert "pull_request:" in text


# ---------------------------------------------------------------------------
# T20 - stage envelope schema stable
# ---------------------------------------------------------------------------


def test_t20_stage_envelope_schema_stable(helper, tmp_path: Path) -> None:
    out = tmp_path / "stage-2.json"
    rc = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "stage-2",
            "--repo-root",
            str(REPO_ROOT),
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    ).returncode
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["tag"] == 63
    assert payload["tool"] == "verify-trigger-routing-integration"
    assert payload["stage"] == "stage_2_alert_routing_propagation_check"
    assert payload["status"] in {"green", "yellow", "red"}
    assert isinstance(payload["notes"], list)
    assert isinstance(payload["details"], dict)
