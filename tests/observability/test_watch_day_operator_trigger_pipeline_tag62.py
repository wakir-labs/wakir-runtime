# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-62 Watch-Day Operator-Trigger Pipeline regression tests (Noa SRE).

Covers (>= 12 tests):

  T01  Helper module importable; canonical constants present.
  T02  stage_pre_trigger() returns green on real repo head.
  T03  stage_pre_trigger() returns red when Tag-56 workflow is missing.
  T04  stage_pre_trigger() returns red on cron drift (`0 5 * * *`).
  T05  stage_pre_trigger() returns red on cron drift (`0 5 * * 1`).
  T06  stage_pre_trigger() returns red when all Tag-61 fixtures missing.
  T07  build_dispatch_envelope() defaults match canonical pins.
  T08  stage_trigger() green on canonical envelope.
  T09  stage_trigger() yellow on diagnostic override.
  T10  stage_trigger() red on workflow drift.
  T11  stage_trigger() red on event-name drift.
  T12  stage_trigger() red on missing keys.
  T13  stage_post_trigger() green on canonical envelope + READY expected.
  T14  stage_post_trigger() red on verdict drift.
  T15  stage_post_trigger() yellow on schema_version drift.
  T16  aggregate_verdict(): all-green -> OPERATOR-TRIGGER-READY.
  T17  aggregate_verdict(): one-yellow -> TRIGGER-CAUTION.
  T18  aggregate_verdict(): two-yellow -> TRIGGER-BLOCKED.
  T19  aggregate_verdict(): any-red -> TRIGGER-BLOCKED.
  T20  CLI pre-trigger end-to-end on real repo head: exit 0.
  T21  CLI trigger end-to-end with canonical pins: exit 0.
  T22  CLI post-trigger end-to-end --fixture-set=green: exit 0.
  T23  CLI post-trigger --fixture-set=red derives BLOCK and matches expected.
  T24  CLI aggregate end-to-end via env-vars: emits valid envelope.
  T25  Workflow YAML mentions Stage 1..Stage 4 jobs by canonical name.
  T26  Workflow YAML path-filter contains all Tag-62 substrates.
  T27  Tag-62 substrate is NOT in any push: trigger (only PR + dispatch).
  T28  Helper module emits stage envelope with stable schema (schema_version=1, tag=62).

Anchor: Tag-62 Marathon-Continuous-Mode Pre-KW-24 Operator-Trigger-
        Test-Pipeline.
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
HELPER_PATH = REPO_ROOT / "tooling/ci/simulate_watch_day_operator_trigger.py"
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/watch-day-operator-trigger-simulation.yml"
TAG56_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/phase-3c-watch-day-practice-run.yml"


def _load_helper():
    mod_name = "simulate_watch_day_operator_trigger"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, str(HELPER_PATH))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def helper():
    return _load_helper()


# ---------------------------------------------------------------------------
# T01 - helper module importable + canonical constants present
# ---------------------------------------------------------------------------


def test_t01_helper_constants_present(helper) -> None:
    assert helper.VERDICT_READY == "OPERATOR-TRIGGER-READY"
    assert helper.VERDICT_CAUTION == "TRIGGER-CAUTION"
    assert helper.VERDICT_BLOCKED == "TRIGGER-BLOCKED"
    assert helper.CANONICAL_WORKFLOW == "phase-3c-watch-day-practice-run.yml"
    assert helper.CANONICAL_REF == "refs/heads/main"
    assert helper.CANONICAL_INPUTS == {"diagnostic": "true"}
    assert set(helper.CANONICAL_DISPATCH_KEYS) == {
        "event",
        "workflow",
        "ref",
        "inputs",
        "actor",
    }


# ---------------------------------------------------------------------------
# T02 - stage_pre_trigger green on real repo head
# ---------------------------------------------------------------------------


def test_t02_stage_pre_trigger_green_on_real_repo(helper) -> None:
    result = helper.stage_pre_trigger(REPO_ROOT)
    assert result.status == helper.STAGE_GREEN, (
        f"expected green, got {result.status} with notes={result.notes}"
    )
    subs = result.details["subordinates"]
    assert subs["cron_pin"] == helper.STAGE_GREEN
    assert subs["alert_routing"] == helper.STAGE_GREEN
    assert subs["replay_fixtures"] == helper.STAGE_GREEN


# ---------------------------------------------------------------------------
# T03 - stage_pre_trigger red when Tag-56 workflow missing
# ---------------------------------------------------------------------------


def test_t03_stage_pre_trigger_red_when_workflow_missing(helper, tmp_path: Path) -> None:
    # Build an isolated minimal tree without Tag-56 workflow.
    fake_root = tmp_path / "isolated"
    (fake_root / "docs" / "observability").mkdir(parents=True)
    (fake_root / "docs" / "observability" / "pre-cutover-watch-day-spec.md").write_text(
        "Mira-Notify routing\ninbox/kai/ routing\n", encoding="utf-8"
    )
    (fake_root / "tests" / "observability" / "fixtures").mkdir(parents=True)
    for n in (
        "watch-day-practice-run-sample-green.json",
        "watch-day-practice-run-sample-caution.json",
        "watch-day-practice-run-sample-red.json",
    ):
        (fake_root / "tests" / "observability" / "fixtures" / n).write_text(
            "{}", encoding="utf-8"
        )
    result = helper.stage_pre_trigger(fake_root)
    assert result.status == helper.STAGE_RED
    assert any("Tag-56 workflow missing" in n for n in result.notes)


# ---------------------------------------------------------------------------
# T04 - stage_pre_trigger red on cron drift to daily
# ---------------------------------------------------------------------------


def test_t04_stage_pre_trigger_red_on_cron_drift_daily(helper, tmp_path: Path) -> None:
    fake_root = _build_fake_tree(
        tmp_path, cron_value='0 5 * * *', mira_notify=True, inbox=True, fixtures=True
    )
    result = helper.stage_pre_trigger(fake_root)
    assert result.status == helper.STAGE_RED
    assert any("cron_pin" in n for n in result.notes)


# ---------------------------------------------------------------------------
# T05 - stage_pre_trigger red on cron drift to monday
# ---------------------------------------------------------------------------


def test_t05_stage_pre_trigger_red_on_cron_drift_monday(helper, tmp_path: Path) -> None:
    fake_root = _build_fake_tree(
        tmp_path, cron_value='0 5 * * 1', mira_notify=True, inbox=True, fixtures=True
    )
    result = helper.stage_pre_trigger(fake_root)
    assert result.status == helper.STAGE_RED
    assert any("cron_pin" in n for n in result.notes)


# ---------------------------------------------------------------------------
# T06 - stage_pre_trigger red when all Tag-61 fixtures missing
# ---------------------------------------------------------------------------


def test_t06_stage_pre_trigger_red_when_fixtures_missing(helper, tmp_path: Path) -> None:
    fake_root = _build_fake_tree(
        tmp_path, cron_value='0 5 * * 2', mira_notify=True, inbox=True, fixtures=False
    )
    result = helper.stage_pre_trigger(fake_root)
    assert result.status == helper.STAGE_RED
    assert any("replay_fixtures" in n for n in result.notes)


# ---------------------------------------------------------------------------
# T07 - build_dispatch_envelope defaults match canonical pins
# ---------------------------------------------------------------------------


def test_t07_build_dispatch_envelope_defaults(helper) -> None:
    env = helper.build_dispatch_envelope()
    assert env["event"] == "workflow_dispatch"
    assert env["workflow"] == "phase-3c-watch-day-practice-run.yml"
    assert env["ref"] == "refs/heads/main"
    assert env["inputs"] == {"diagnostic": "true"}
    assert env["actor"] == "mira-kessler"


# ---------------------------------------------------------------------------
# T08 - stage_trigger green on canonical envelope
# ---------------------------------------------------------------------------


def test_t08_stage_trigger_green_on_canonical(helper) -> None:
    env = helper.build_dispatch_envelope()
    result = helper.stage_trigger(env)
    assert result.status == helper.STAGE_GREEN, result.notes


# ---------------------------------------------------------------------------
# T09 - stage_trigger yellow on diagnostic override
# ---------------------------------------------------------------------------


def test_t09_stage_trigger_yellow_on_diagnostic_override(helper) -> None:
    env = helper.build_dispatch_envelope(inputs={"diagnostic": "false"})
    result = helper.stage_trigger(env)
    assert result.status == helper.STAGE_YELLOW
    assert any("diagnostic" in n for n in result.notes)


# ---------------------------------------------------------------------------
# T10 - stage_trigger red on workflow drift
# ---------------------------------------------------------------------------


def test_t10_stage_trigger_red_on_workflow_drift(helper) -> None:
    env = helper.build_dispatch_envelope(workflow="phase-3c-RENAMED.yml")
    result = helper.stage_trigger(env)
    assert result.status == helper.STAGE_RED
    assert any("workflow drift" in n for n in result.notes)


# ---------------------------------------------------------------------------
# T11 - stage_trigger red on event-name drift
# ---------------------------------------------------------------------------


def test_t11_stage_trigger_red_on_event_drift(helper) -> None:
    env = helper.build_dispatch_envelope()
    env["event"] = "push"
    result = helper.stage_trigger(env)
    assert result.status == helper.STAGE_RED
    assert any("event drift" in n for n in result.notes)


# ---------------------------------------------------------------------------
# T12 - stage_trigger red on missing keys
# ---------------------------------------------------------------------------


def test_t12_stage_trigger_red_on_missing_keys(helper) -> None:
    env = {"event": "workflow_dispatch"}
    result = helper.stage_trigger(env)
    assert result.status == helper.STAGE_RED
    assert any("missing keys" in n for n in result.notes)


# ---------------------------------------------------------------------------
# T13 - stage_post_trigger green on canonical envelope
# ---------------------------------------------------------------------------


def test_t13_stage_post_trigger_green_on_canonical(helper) -> None:
    canonical = {
        "schema_version": 1,
        "tag": 56,
        "tool": "phase-3c-watch-day-practice-run",
        "verdict": "READY",
        "stages": {"step_1_inventory": "green"},
    }
    result = helper.stage_post_trigger(canonical, expected_verdict="READY")
    assert result.status == helper.STAGE_GREEN, result.notes


# ---------------------------------------------------------------------------
# T14 - stage_post_trigger red on verdict drift
# ---------------------------------------------------------------------------


def test_t14_stage_post_trigger_red_on_verdict_drift(helper) -> None:
    env = {
        "schema_version": 1,
        "tag": 56,
        "tool": "phase-3c-watch-day-practice-run",
        "verdict": "BLOCK",
        "stages": {"step_1_inventory": "green"},
    }
    result = helper.stage_post_trigger(env, expected_verdict="READY")
    assert result.status == helper.STAGE_RED
    assert any("verdict drift" in n for n in result.notes)


# ---------------------------------------------------------------------------
# T15 - stage_post_trigger yellow on schema_version drift
# ---------------------------------------------------------------------------


def test_t15_stage_post_trigger_yellow_on_schema_drift(helper) -> None:
    env = {
        "schema_version": 2,
        "tag": 56,
        "tool": "phase-3c-watch-day-practice-run",
        "verdict": "READY",
        "stages": {"step_1_inventory": "green"},
    }
    result = helper.stage_post_trigger(env, expected_verdict="READY")
    assert result.status == helper.STAGE_YELLOW
    assert any("schema_version" in n for n in result.notes)


# ---------------------------------------------------------------------------
# T16 - aggregate_verdict all-green -> READY
# ---------------------------------------------------------------------------


def test_t16_aggregate_all_green(helper) -> None:
    v = helper.aggregate_verdict("green", "green", "green")
    assert v == "OPERATOR-TRIGGER-READY"


# ---------------------------------------------------------------------------
# T17 - aggregate_verdict one-yellow -> CAUTION
# ---------------------------------------------------------------------------


def test_t17_aggregate_one_yellow(helper) -> None:
    assert helper.aggregate_verdict("yellow", "green", "green") == "TRIGGER-CAUTION"
    assert helper.aggregate_verdict("green", "yellow", "green") == "TRIGGER-CAUTION"
    assert helper.aggregate_verdict("green", "green", "yellow") == "TRIGGER-CAUTION"


# ---------------------------------------------------------------------------
# T18 - aggregate_verdict two-yellow -> BLOCKED
# ---------------------------------------------------------------------------


def test_t18_aggregate_two_yellow(helper) -> None:
    assert helper.aggregate_verdict("yellow", "yellow", "green") == "TRIGGER-BLOCKED"
    assert helper.aggregate_verdict("yellow", "green", "yellow") == "TRIGGER-BLOCKED"
    assert helper.aggregate_verdict("green", "yellow", "yellow") == "TRIGGER-BLOCKED"
    assert helper.aggregate_verdict("yellow", "yellow", "yellow") == "TRIGGER-BLOCKED"


# ---------------------------------------------------------------------------
# T19 - aggregate_verdict any-red -> BLOCKED
# ---------------------------------------------------------------------------


def test_t19_aggregate_any_red(helper) -> None:
    assert helper.aggregate_verdict("red", "green", "green") == "TRIGGER-BLOCKED"
    assert helper.aggregate_verdict("green", "red", "green") == "TRIGGER-BLOCKED"
    assert helper.aggregate_verdict("green", "green", "red") == "TRIGGER-BLOCKED"
    assert helper.aggregate_verdict("red", "yellow", "green") == "TRIGGER-BLOCKED"


# ---------------------------------------------------------------------------
# T20 - CLI pre-trigger on real repo: exit 0
# ---------------------------------------------------------------------------


def test_t20_cli_pre_trigger_real_repo_exit_0(tmp_path: Path) -> None:
    out = tmp_path / "stage1.json"
    rc = subprocess.call(
        [
            sys.executable,
            str(HELPER_PATH),
            "pre-trigger",
            "--repo-root",
            str(REPO_ROOT),
            "--output",
            str(out),
        ]
    )
    assert rc == 0, f"pre-trigger CLI exited {rc}"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["tag"] == 62
    assert payload["stage"] == "pre_trigger"
    assert payload["status"] == "green"


# ---------------------------------------------------------------------------
# T21 - CLI trigger end-to-end with canonical pins: exit 0
# ---------------------------------------------------------------------------


def test_t21_cli_trigger_canonical_exit_0(tmp_path: Path) -> None:
    out = tmp_path / "stage2.json"
    rc = subprocess.call(
        [
            sys.executable,
            str(HELPER_PATH),
            "trigger",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["stage"] == "trigger"
    assert payload["status"] == "green"
    env = payload["details"]["envelope"]
    assert env["event"] == "workflow_dispatch"
    assert env["workflow"] == "phase-3c-watch-day-practice-run.yml"


# ---------------------------------------------------------------------------
# T22 - CLI post-trigger --fixture-set=green: exit 0
# ---------------------------------------------------------------------------


def test_t22_cli_post_trigger_green_exit_0(tmp_path: Path) -> None:
    out = tmp_path / "stage3.json"
    rc = subprocess.call(
        [
            sys.executable,
            str(HELPER_PATH),
            "post-trigger",
            "--repo-root",
            str(REPO_ROOT),
            "--fixture-set",
            "green",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "green"
    assert payload["details"]["expected_verdict"] == "READY"
    assert payload["details"]["envelope"]["verdict"] == "READY"


# ---------------------------------------------------------------------------
# T23 - CLI post-trigger --fixture-set=red derives BLOCK
# ---------------------------------------------------------------------------


def test_t23_cli_post_trigger_red_matches_block(tmp_path: Path) -> None:
    out = tmp_path / "stage3-red.json"
    rc = subprocess.call(
        [
            sys.executable,
            str(HELPER_PATH),
            "post-trigger",
            "--repo-root",
            str(REPO_ROOT),
            "--fixture-set",
            "red",
            "--output",
            str(out),
        ]
    )
    # Red fixture expects BLOCK; derived verdict should match; stage green.
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "green"
    assert payload["details"]["expected_verdict"] == "BLOCK"
    assert payload["details"]["envelope"]["verdict"] == "BLOCK"


# ---------------------------------------------------------------------------
# T24 - CLI aggregate end-to-end emits valid envelope
# ---------------------------------------------------------------------------


def test_t24_cli_aggregate_emits_valid_envelope(tmp_path: Path) -> None:
    out = tmp_path / "verdict.json"
    rc = subprocess.call(
        [
            sys.executable,
            str(HELPER_PATH),
            "aggregate",
            "--stage-1",
            "green",
            "--stage-2",
            "green",
            "--stage-3",
            "green",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["tag"] == 62
    assert payload["tool"] == "watch-day-operator-trigger-simulation"
    assert payload["verdict"] == "OPERATOR-TRIGGER-READY"
    assert payload["stages"] == {
        "stage_1_pre_trigger": "green",
        "stage_2_trigger": "green",
        "stage_3_post_trigger": "green",
    }


# ---------------------------------------------------------------------------
# T25 - Workflow YAML mentions Stage 1..Stage 4 jobs by canonical name
# ---------------------------------------------------------------------------


def test_t25_workflow_yaml_has_four_stage_jobs() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "stage-1-pre-trigger-health-check:" in text
    assert "stage-2-simulate-operator-trigger:" in text
    assert "stage-3-post-trigger-verification:" in text
    assert "stage-4-aggregate-verdict:" in text
    # Canonical aggregate-job display name (for branch protection promotion).
    assert "Aggregate Verdict (OPERATOR-TRIGGER-READY/CAUTION/BLOCKED)" in text


# ---------------------------------------------------------------------------
# T26 - Workflow YAML path-filter covers Tag-62 substrates + Tag-56 deps
# ---------------------------------------------------------------------------


def test_t26_workflow_yaml_path_filter_covers_substrates() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    required = [
        ".github/workflows/watch-day-operator-trigger-simulation.yml",
        ".github/workflows/phase-3c-watch-day-practice-run.yml",
        ".github/workflows/watch-day-cron-pre-fire-probe.yml",
        ".github/workflows/watch-day-practice-run-replay.yml",
        "tooling/ci/simulate_watch_day_operator_trigger.py",
        "docs/observability/pre-cutover-watch-day-spec.md",
        "tests/observability/test_watch_day_operator_trigger_pipeline_tag62.py",
        "tests/observability/fixtures/watch-day-practice-run-sample-green.json",
        "tests/observability/fixtures/watch-day-practice-run-sample-caution.json",
        "tests/observability/fixtures/watch-day-practice-run-sample-red.json",
    ]
    for r in required:
        assert r in text, f"path-filter missing: {r}"


# ---------------------------------------------------------------------------
# T27 - Tag-62 workflow has no push: trigger and no schedule: trigger
# ---------------------------------------------------------------------------


def test_t27_workflow_yaml_no_push_no_schedule() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    # Must not have `push:` or `schedule:` blocks in the on: surface.
    # We check at column-2 indent inside on: to avoid false positives
    # on the word `push` appearing in comments.
    # Quick canonical check: the literal markers must not be present.
    assert re.search(r"^\s{2}push:\s*$", text, re.MULTILINE) is None, "push: trigger present"
    assert re.search(r"^\s{2}schedule:\s*$", text, re.MULTILINE) is None, "schedule: trigger present"
    # Positive surface: workflow_dispatch + pull_request must exist.
    assert re.search(r"^\s{2}workflow_dispatch:\s*$", text, re.MULTILINE) is not None
    assert re.search(r"^\s{2}pull_request:\s*$", text, re.MULTILINE) is not None


# ---------------------------------------------------------------------------
# T28 - stage envelope schema stable (schema_version=1, tag=62)
# ---------------------------------------------------------------------------


def test_t28_stage_envelope_schema_stable(helper, tmp_path: Path) -> None:
    out = tmp_path / "stage1.json"
    result = helper.stage_pre_trigger(REPO_ROOT)
    helper._write_stage_envelope("pre_trigger", result, out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["tag"] == 62
    assert payload["tool"] == "watch-day-operator-trigger-simulation"
    assert payload["stage"] == "pre_trigger"
    assert payload["status"] in {"green", "yellow", "red"}
    assert "notes" in payload and isinstance(payload["notes"], list)
    assert "details" in payload and isinstance(payload["details"], dict)


# ---------------------------------------------------------------------------
# Helper: build fake tree with controlled cron/routing/fixture state.
# ---------------------------------------------------------------------------


def _build_fake_tree(
    tmp_path: Path,
    *,
    cron_value: str,
    mira_notify: bool,
    inbox: bool,
    fixtures: bool,
) -> Path:
    fake_root = tmp_path / "fake"
    (fake_root / ".github" / "workflows").mkdir(parents=True)
    workflow_text = f'''# fake workflow
name: phase-3c-watch-day-practice-run
on:
  schedule:
    - cron: "{cron_value}"
'''
    (fake_root / ".github" / "workflows" / "phase-3c-watch-day-practice-run.yml").write_text(
        workflow_text, encoding="utf-8"
    )
    (fake_root / "docs" / "observability").mkdir(parents=True)
    spec_parts = []
    if mira_notify:
        spec_parts.append("Mira-Notify routing")
    if inbox:
        spec_parts.append("inbox/kai/ routing")
    if not spec_parts:
        spec_parts.append("placeholder")
    (fake_root / "docs" / "observability" / "pre-cutover-watch-day-spec.md").write_text(
        "\n".join(spec_parts) + "\n", encoding="utf-8"
    )
    (fake_root / "tests" / "observability" / "fixtures").mkdir(parents=True)
    if fixtures:
        for n in (
            "watch-day-practice-run-sample-green.json",
            "watch-day-practice-run-sample-caution.json",
            "watch-day-practice-run-sample-red.json",
        ):
            (fake_root / "tests" / "observability" / "fixtures" / n).write_text(
                "{}", encoding="utf-8"
            )
    return fake_root
