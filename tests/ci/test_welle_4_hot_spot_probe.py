# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Tag-48 Welle-4 Hot-Spot Probe substrate.

Welle-4 = ``state_backing`` (#2 Cross-Welle Hot-Spot per Henrik
Tag-44+45 Mitigation-Map). Tests verify the aggregator decision-rule,
verdict envelope schema, cross-welle propagation block (to Welle-{5,7}),
notify-event emission rule, and the workflow YAML structural shape.

Sandbox: stdlib + pytest + PyYAML only.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from itertools import product
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "phase-3c-welle-4-hot-spot-probe.yml"
)
AGGREGATOR_PATH = (
    REPO_ROOT / "tooling" / "ci" / "welle_4_hot_spot_aggregator.py"
)
RUNBOOK_PATH = (
    REPO_ROOT / "docs" / "ci" / "welle-4-hot-spot-probe-runbook.md"
)

TRI_STATES = ("green", "yellow", "red")

CHECK_KEYS = (
    "check_1_self_reference_trap_pre_detection",
    "check_2_state_backing_persistence_drift",
    "check_3_independent_oracle_probe",
    "check_4_iia_1130_pre_auditor_decision",
)


def _load_aggregator():
    spec = importlib.util.spec_from_file_location(
        "welle_4_hot_spot_aggregator", AGGREGATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["welle_4_hot_spot_aggregator"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def aggregator():
    return _load_aggregator()


@pytest.fixture(scope="module")
def workflow_yaml():
    assert WORKFLOW_PATH.is_file(), f"workflow missing: {WORKFLOW_PATH}"
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _expected_verdict(steps: dict[str, str]) -> str:
    reds = sum(1 for v in steps.values() if v == "red")
    yellows = sum(1 for v in steps.values() if v == "yellow")
    greens = sum(1 for v in steps.values() if v == "green")
    if reds >= 1:
        return "BLOCK"
    if yellows >= 2:
        return "BLOCK"
    if yellows == 1:
        return "CAUTION"
    if greens == 4:
        return "CLEAR"
    return "BLOCK"


def test_decision_truth_table_walk(aggregator):
    """Every (status1, status2, status3, status4) tuple yields the
    documented verdict."""
    count = 0
    for s1, s2, s3, s4 in product(TRI_STATES, repeat=4):
        steps = {
            CHECK_KEYS[0]: s1,
            CHECK_KEYS[1]: s2,
            CHECK_KEYS[2]: s3,
            CHECK_KEYS[3]: s4,
        }
        got = aggregator.decide(steps)
        want = _expected_verdict(steps)
        assert got == want, f"steps={steps} -> got={got} want={want}"
        count += 1
    assert count == 81


def test_missing_env_vars_default_to_red(aggregator):
    envelope = aggregator.build_envelope({})
    for key in CHECK_KEYS:
        assert envelope["check_results"][key] == "red"
    assert envelope["verdict"] == "BLOCK"
    assert sorted(envelope["failed_checks"]) == sorted(CHECK_KEYS)


def test_unknown_status_falls_back_to_red(aggregator):
    env = {
        "CHECK1_STATUS": "blue",
        "CHECK2_STATUS": "  GREEN  ",
        "CHECK3_STATUS": "",
        "CHECK4_STATUS": "yellow",
    }
    envelope = aggregator.build_envelope(env)
    assert envelope["check_results"][CHECK_KEYS[0]] == "red"
    assert envelope["check_results"][CHECK_KEYS[1]] == "green"
    assert envelope["check_results"][CHECK_KEYS[2]] == "red"
    assert envelope["check_results"][CHECK_KEYS[3]] == "yellow"
    assert envelope["verdict"] == "BLOCK"


def test_envelope_schema_fields(aggregator):
    env = {
        "CHECK1_STATUS": "green",
        "CHECK2_STATUS": "green",
        "CHECK3_STATUS": "green",
        "CHECK4_STATUS": "green",
        "GITHUB_RUN_ID": "999",
        "GITHUB_SHA": "abc1234",
        "GITHUB_REF": "refs/heads/main",
    }
    envelope = aggregator.build_envelope(env)
    required = {
        "schema_version", "workflow", "welle", "emitted_at_utc",
        "github_run_id", "github_sha", "github_ref", "verdict",
        "check_results", "failed_checks", "counts",
        "independent_oracle_disagreements", "pre_auditor_state",
        "cross_welle_propagation", "cross_substrate_links",
    }
    missing = required - set(envelope.keys())
    assert not missing, f"envelope missing fields: {missing}"
    assert envelope["welle"] == 4
    assert envelope["schema_version"] == 1
    assert envelope["workflow"] == "phase-3c-welle-4-hot-spot-probe"
    assert envelope["verdict"] == "CLEAR"
    assert envelope["counts"] == {"green": 4, "yellow": 0, "red": 0}
    assert envelope["failed_checks"] == []
    from datetime import datetime
    dt = datetime.fromisoformat(envelope["emitted_at_utc"])
    assert dt.tzinfo is not None


def test_cross_welle_propagation_fires(aggregator):
    """Welle-4 propagation to Welle-{5,7} when persistence-drift red."""
    env = {
        "CHECK1_STATUS": "green",
        "CHECK2_STATUS": "red",
        "CHECK3_STATUS": "green",
        "CHECK4_STATUS": "green",
        "WELLE_4_PERSISTENCE_DRIFT": "red",
    }
    envelope = aggregator.build_envelope(env)
    assert envelope["verdict"] == "BLOCK"
    prop = envelope["cross_welle_propagation"]
    assert prop is not None
    assert prop["trigger"] == "welle-4-persistence-drift-red"
    assert prop["pre_conditional_blocked"] == [5, 7]
    assert "Henrik" in prop["rationale"]


def test_cross_welle_propagation_quiet_on_yellow(aggregator):
    env = {
        "CHECK1_STATUS": "green",
        "CHECK2_STATUS": "yellow",
        "CHECK3_STATUS": "green",
        "CHECK4_STATUS": "green",
        "WELLE_4_PERSISTENCE_DRIFT": "yellow",
    }
    envelope = aggregator.build_envelope(env)
    assert envelope["verdict"] == "CAUTION"
    assert envelope["cross_welle_propagation"] is None


def test_cross_welle_propagation_requires_both_red(aggregator):
    env = {
        "CHECK1_STATUS": "green",
        "CHECK2_STATUS": "red",
        "CHECK3_STATUS": "green",
        "CHECK4_STATUS": "green",
        "WELLE_4_PERSISTENCE_DRIFT": "green",
    }
    envelope = aggregator.build_envelope(env)
    assert envelope["verdict"] == "BLOCK"
    assert envelope["cross_welle_propagation"] is None


def test_notify_event_on_block(tmp_path, aggregator):
    notify = tmp_path / "notify.jsonl"
    env = {
        "CHECK1_STATUS": "red",
        "CHECK2_STATUS": "green",
        "CHECK3_STATUS": "green",
        "CHECK4_STATUS": "green",
    }
    envelope = aggregator.build_envelope(env)
    emitted = aggregator._emit_notify_event(envelope, notify, "BLOCK")
    assert emitted is True
    lines = notify.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["kind"] == "welle-4-hot-spot-probe"
    assert event["verdict"] == "BLOCK"


def test_notify_event_caution_transition_only(tmp_path, aggregator):
    notify = tmp_path / "notify.jsonl"
    env = {
        "CHECK1_STATUS": "yellow",
        "CHECK2_STATUS": "green",
        "CHECK3_STATUS": "green",
        "CHECK4_STATUS": "green",
    }
    envelope = aggregator.build_envelope(env)
    assert envelope["verdict"] == "CAUTION"
    emitted_1 = aggregator._emit_notify_event(envelope, notify, "CLEAR")
    assert emitted_1 is True
    emitted_2 = aggregator._emit_notify_event(envelope, notify, "CAUTION")
    assert emitted_2 is False
    assert len(notify.read_text(encoding="utf-8").splitlines()) == 1


def test_notify_event_clear_silent(tmp_path, aggregator):
    notify = tmp_path / "notify.jsonl"
    env = {
        "CHECK1_STATUS": "green",
        "CHECK2_STATUS": "green",
        "CHECK3_STATUS": "green",
        "CHECK4_STATUS": "green",
    }
    envelope = aggregator.build_envelope(env)
    assert envelope["verdict"] == "CLEAR"
    emitted = aggregator._emit_notify_event(envelope, notify, None)
    assert emitted is False
    assert not notify.exists()


def test_disagreements_and_pre_auditor_state_pass_through(aggregator):
    env = {
        "CHECK1_STATUS": "green",
        "CHECK2_STATUS": "green",
        "CHECK3_STATUS": "red",
        "CHECK4_STATUS": "yellow",
        "INDEPENDENT_ORACLE_DISAGREEMENTS": (
            "oracle-verdict-divergence,axis-cross-modul-fixture-stability"
        ),
        "PRE_AUDITOR_STATE": "pending",
    }
    envelope = aggregator.build_envelope(env)
    assert envelope["independent_oracle_disagreements"] == [
        "oracle-verdict-divergence",
        "axis-cross-modul-fixture-stability",
    ]
    assert envelope["pre_auditor_state"] == "pending"
    env["PRE_AUDITOR_STATE"] = "fubar"
    env2 = aggregator.build_envelope(env)
    assert env2["pre_auditor_state"] == "missing"


def test_main_writes_output_and_notify(tmp_path, monkeypatch, aggregator):
    out_path = tmp_path / "subdir" / "verdict.json"
    notify_path = tmp_path / "notify.jsonl"
    monkeypatch.setenv("CHECK1_STATUS", "green")
    monkeypatch.setenv("CHECK2_STATUS", "yellow")
    monkeypatch.setenv("CHECK3_STATUS", "green")
    monkeypatch.setenv("CHECK4_STATUS", "green")
    rc = aggregator.main([
        "welle_4_hot_spot_aggregator",
        "--output", str(out_path),
        "--notify-out", str(notify_path),
        "--prev-verdict", "CLEAR",
    ])
    assert rc == 0
    assert out_path.is_file()
    envelope = json.loads(out_path.read_text(encoding="utf-8"))
    assert envelope["verdict"] == "CAUTION"
    assert notify_path.is_file()
    assert len(notify_path.read_text(encoding="utf-8").splitlines()) == 1


def test_workflow_has_five_jobs_in_order(workflow_yaml):
    jobs = workflow_yaml["jobs"]
    job_ids = list(jobs.keys())
    expected = [
        "check-1-self-reference-trap",
        "check-2-state-backing-persistence-drift",
        "check-3-independent-oracle",
        "check-4-iia-1130-pre-auditor",
        "aggregate",
    ]
    assert job_ids == expected, f"got jobs: {job_ids}"


def test_aggregate_job_needs_and_if_always(workflow_yaml):
    agg = workflow_yaml["jobs"]["aggregate"]
    needs = agg["needs"]
    expected_needs = {
        "check-1-self-reference-trap",
        "check-2-state-backing-persistence-drift",
        "check-3-independent-oracle",
        "check-4-iia-1130-pre-auditor",
    }
    assert set(needs) == expected_needs
    assert agg.get("if") == "always()"


def test_daily_cron_trigger(workflow_yaml):
    on = workflow_yaml.get("on") or workflow_yaml.get(True)
    assert on is not None
    schedules = on.get("schedule")
    assert schedules
    crons = [item.get("cron") for item in schedules]
    # Welle-4 slot: 35 6 * * *
    assert "35 6 * * *" in crons, f"daily-cron not found in: {crons}"


def test_path_filter_covers_substrate(workflow_yaml):
    on = workflow_yaml.get("on") or workflow_yaml.get(True)
    pr = on.get("pull_request")
    push = on.get("push")
    pr_paths = set(pr.get("paths") or [])
    push_paths = set(push.get("paths") or [])
    required_in_both = {
        "tooling/ci/welle_4_hot_spot_aggregator.py",
        ".github/workflows/phase-3c-welle-4-hot-spot-probe.yml",
        "tests/ci/test_welle_4_hot_spot_probe.py",
        "docs/ci/welle-4-hot-spot-probe-runbook.md",
    }
    missing_pr = required_in_both - pr_paths
    missing_push = required_in_both - push_paths
    assert not missing_pr, f"pr path-filter missing: {missing_pr}"
    assert not missing_push, f"push path-filter missing: {missing_push}"


def test_runbook_cross_references():
    text = RUNBOOK_PATH.read_text(encoding="utf-8")
    assert ".github/workflows/phase-3c-welle-4-hot-spot-probe.yml" in text
    assert "tooling/ci/welle_4_hot_spot_aggregator.py" in text
    assert "Henrik" in text and "Pre-Mortem" in text
    assert "IIA-1130" in text
    assert "state_backing" in text or "persistence" in text.lower()
    assert "Welle-5" in text and "Welle-7" in text
    assert "doppelbetrieb-score-aggregator" in text


def test_aggregator_stdlib_only():
    text = AGGREGATOR_PATH.read_text(encoding="utf-8")
    stdlib_prefixes = (
        "from __future__",
        "import argparse",
        "import json",
        "import os",
        "import sys",
        "from datetime",
        "from pathlib",
        "from typing",
    )
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("import ", "from ")):
            continue
        ok = any(stripped.startswith(prefix) for prefix in stdlib_prefixes)
        assert ok, f"non-stdlib import: {stripped}"


def test_downstream_propagation_wellen_constant(aggregator):
    """Welle-4 propagates to Welle-{5,7} per Henrik Tag-44+45 matrix."""
    assert aggregator.DOWNSTREAM_PROPAGATION_WELLEN == (5, 7)


def test_envelope_deterministic_modulo_timestamp(aggregator):
    env = {
        "CHECK1_STATUS": "green",
        "CHECK2_STATUS": "yellow",
        "CHECK3_STATUS": "green",
        "CHECK4_STATUS": "yellow",
        "GITHUB_RUN_ID": "42",
    }
    e1 = aggregator.build_envelope(env)
    e2 = aggregator.build_envelope(env)
    for k in e1:
        if k == "emitted_at_utc":
            continue
        assert e1[k] == e2[k], f"non-deterministic field: {k}"
    assert e1["verdict"] == "BLOCK"
