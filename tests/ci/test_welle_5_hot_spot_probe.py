# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Tag-48 Welle-5 Hot-Spot Probe substrate.

Welle-5 = ``lifecycle_state_machine`` (propagation-target hot-spot;
FSM-Phantom-Detection live indicator). Propagates to Welle-{7}.

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
    REPO_ROOT / ".github" / "workflows" / "phase-3c-welle-5-hot-spot-probe.yml"
)
AGGREGATOR_PATH = (
    REPO_ROOT / "tooling" / "ci" / "welle_5_hot_spot_aggregator.py"
)
RUNBOOK_PATH = (
    REPO_ROOT / "docs" / "ci" / "welle-5-hot-spot-probe-runbook.md"
)

TRI_STATES = ("green", "yellow", "red")

CHECK_KEYS = (
    "check_1_self_reference_trap_pre_detection",
    "check_2_fsm_phantom_detection_live",
    "check_3_independent_oracle_probe",
    "check_4_iia_1130_pre_auditor_decision",
)


def _load_aggregator():
    spec = importlib.util.spec_from_file_location(
        "welle_5_hot_spot_aggregator", AGGREGATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["welle_5_hot_spot_aggregator"] = mod
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
    assert not missing
    assert envelope["welle"] == 5
    assert envelope["schema_version"] == 1
    assert envelope["workflow"] == "phase-3c-welle-5-hot-spot-probe"
    assert envelope["verdict"] == "CLEAR"
    from datetime import datetime
    dt = datetime.fromisoformat(envelope["emitted_at_utc"])
    assert dt.tzinfo is not None


def test_cross_welle_propagation_fires_to_welle_7(aggregator):
    env = {
        "CHECK1_STATUS": "green",
        "CHECK2_STATUS": "red",
        "CHECK3_STATUS": "green",
        "CHECK4_STATUS": "green",
        "WELLE_5_FSM_PHANTOM_DETECTION": "red",
    }
    envelope = aggregator.build_envelope(env)
    assert envelope["verdict"] == "BLOCK"
    prop = envelope["cross_welle_propagation"]
    assert prop is not None
    assert prop["trigger"] == "welle-5-fsm-phantom-detection-red"
    # Welle-5 propagates only to Welle-7.
    assert prop["pre_conditional_blocked"] == [7]
    assert "Henrik" in prop["rationale"]


def test_cross_welle_propagation_quiet_on_yellow(aggregator):
    env = {
        "CHECK1_STATUS": "green",
        "CHECK2_STATUS": "yellow",
        "CHECK3_STATUS": "green",
        "CHECK4_STATUS": "green",
        "WELLE_5_FSM_PHANTOM_DETECTION": "yellow",
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
        "WELLE_5_FSM_PHANTOM_DETECTION": "green",
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
    assert event["kind"] == "welle-5-hot-spot-probe"
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


def test_main_writes_output_and_notify(tmp_path, monkeypatch, aggregator):
    out_path = tmp_path / "subdir" / "verdict.json"
    notify_path = tmp_path / "notify.jsonl"
    monkeypatch.setenv("CHECK1_STATUS", "green")
    monkeypatch.setenv("CHECK2_STATUS", "yellow")
    monkeypatch.setenv("CHECK3_STATUS", "green")
    monkeypatch.setenv("CHECK4_STATUS", "green")
    rc = aggregator.main([
        "welle_5_hot_spot_aggregator",
        "--output", str(out_path),
        "--notify-out", str(notify_path),
        "--prev-verdict", "CLEAR",
    ])
    assert rc == 0
    envelope = json.loads(out_path.read_text(encoding="utf-8"))
    assert envelope["verdict"] == "CAUTION"
    assert notify_path.is_file()


def test_workflow_has_five_jobs_in_order(workflow_yaml):
    jobs = workflow_yaml["jobs"]
    expected = [
        "check-1-self-reference-trap",
        "check-2-fsm-phantom-detection",
        "check-3-independent-oracle",
        "check-4-iia-1130-pre-auditor",
        "aggregate",
    ]
    assert list(jobs.keys()) == expected


def test_aggregate_job_needs_and_if_always(workflow_yaml):
    agg = workflow_yaml["jobs"]["aggregate"]
    expected_needs = {
        "check-1-self-reference-trap",
        "check-2-fsm-phantom-detection",
        "check-3-independent-oracle",
        "check-4-iia-1130-pre-auditor",
    }
    assert set(agg["needs"]) == expected_needs
    assert agg.get("if") == "always()"


def test_daily_cron_trigger(workflow_yaml):
    on = workflow_yaml.get("on") or workflow_yaml.get(True)
    schedules = on.get("schedule")
    crons = [item.get("cron") for item in schedules]
    # Welle-5 slot: 40 6 * * *
    assert "40 6 * * *" in crons, f"daily-cron not found in: {crons}"


def test_path_filter_covers_substrate(workflow_yaml):
    on = workflow_yaml.get("on") or workflow_yaml.get(True)
    pr_paths = set(on.get("pull_request").get("paths") or [])
    push_paths = set(on.get("push").get("paths") or [])
    required_in_both = {
        "tooling/ci/welle_5_hot_spot_aggregator.py",
        ".github/workflows/phase-3c-welle-5-hot-spot-probe.yml",
        "tests/ci/test_welle_5_hot_spot_probe.py",
        "docs/ci/welle-5-hot-spot-probe-runbook.md",
    }
    assert not (required_in_both - pr_paths)
    assert not (required_in_both - push_paths)


def test_runbook_cross_references():
    text = RUNBOOK_PATH.read_text(encoding="utf-8")
    assert ".github/workflows/phase-3c-welle-5-hot-spot-probe.yml" in text
    assert "tooling/ci/welle_5_hot_spot_aggregator.py" in text
    assert "Henrik" in text and "Pre-Mortem" in text
    assert "IIA-1130" in text
    assert "FSM" in text or "phantom" in text.lower()
    assert "Welle-7" in text
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
    """Welle-5 propagates to Welle-{7} only per Henrik matrix."""
    assert aggregator.DOWNSTREAM_PROPAGATION_WELLEN == (7,)


def test_envelope_deterministic_modulo_timestamp(aggregator):
    env = {
        "CHECK1_STATUS": "green",
        "CHECK2_STATUS": "yellow",
        "CHECK3_STATUS": "green",
        "CHECK4_STATUS": "yellow",
    }
    e1 = aggregator.build_envelope(env)
    e2 = aggregator.build_envelope(env)
    for k in e1:
        if k == "emitted_at_utc":
            continue
        assert e1[k] == e2[k]
    assert e1["verdict"] == "BLOCK"
