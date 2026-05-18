# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Tag-49 Cross-Welle Hot-Spot Aggregator.

Covers:

* ``tooling/ci/cross_welle_hot_spot_aggregator.py`` decision-rule
  (marathon verdict from per-welle slot list).
* Per-welle slot construction (CLEAR / CAUTION / BLOCK / UNKNOWN /
  POST-CUTOVER mapping).
* Stale-envelope handling (``--max-age-days`` cutoff).
* Transitive closure of cross-welle propagation.
* Top-hot-spot ranking order.
* Notify-event emission rule (BLOCK every run, CAUTION transition).
* Envelope schema field presence.
* Workflow YAML structural shape.
* Runbook references the workflow + aggregator paths.
* CLI ``--print-stdout`` round-trip.

Sandbox: stdlib + pytest + PyYAML only. No subprocess, no network,
no podman, no live-VM.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "cross-welle-hot-spot-aggregator.yml"
)
AGGREGATOR_PATH = (
    REPO_ROOT / "tooling" / "ci" / "cross_welle_hot_spot_aggregator.py"
)
RENDER_SUMMARY_PATH = (
    REPO_ROOT / "tooling" / "ci" / "cross_welle_hot_spot_render_summary.py"
)
RUNBOOK_PATH = (
    REPO_ROOT / "docs" / "ci" / "cross-welle-hot-spot-aggregator-runbook.md"
)

LIVE_WELLEN = (3, 4, 5, 6, 7)
POST_CUTOVER_WELLEN = (1, 2)


def _load_aggregator():
    spec = importlib.util.spec_from_file_location(
        "cross_welle_hot_spot_aggregator", AGGREGATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cross_welle_hot_spot_aggregator"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def aggregator():
    return _load_aggregator()


@pytest.fixture(scope="module")
def workflow_yaml():
    assert WORKFLOW_PATH.is_file(), f"workflow missing: {WORKFLOW_PATH}"
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _write_per_welle_envelope(
    state_root: Path,
    welle: int,
    when: date,
    *,
    verdict: str,
    counts: dict | None = None,
    propagation_targets: list[int] | None = None,
    failed_checks: list[str] | None = None,
) -> Path:
    """Write a per-welle envelope into ``state/welle-N-hot-spot-trend/``."""
    trend = state_root / f"welle-{welle}-hot-spot-trend"
    trend.mkdir(parents=True, exist_ok=True)
    propagation = None
    if propagation_targets:
        propagation = {
            "trigger": f"welle-{welle}-test-trigger",
            "pre_conditional_blocked": propagation_targets,
            "rationale": "test-fixture",
        }
    env = {
        "schema_version": 1,
        "workflow": f"phase-3c-welle-{welle}-hot-spot-probe",
        "welle": welle,
        "emitted_at_utc": datetime(
            when.year, when.month, when.day, tzinfo=timezone.utc
        ).isoformat(timespec="seconds"),
        "verdict": verdict,
        "check_results": {},
        "failed_checks": failed_checks or [],
        "counts": counts or {"green": 4, "yellow": 0, "red": 0},
        "cross_welle_propagation": propagation,
    }
    path = trend / f"{when.isoformat()}.json"
    path.write_text(json.dumps(env, sort_keys=True), encoding="utf-8")
    return path


# ----------------------------------------------------------------------
# Test 1 -- All-CLEAR live-welle slots yield marathon CLEAR.
# ----------------------------------------------------------------------
def test_decide_marathon_all_clear_is_clear(aggregator):
    slots = [
        {"welle": w, "verdict": "CLEAR", "propagation_targets": []}
        for w in LIVE_WELLEN
    ]
    assert aggregator.decide_marathon(slots) == "CLEAR"


# ----------------------------------------------------------------------
# Test 2 -- Any BLOCK live-welle slot yields marathon BLOCK.
# ----------------------------------------------------------------------
def test_decide_marathon_any_block_is_block(aggregator):
    slots = [
        {"welle": 3, "verdict": "BLOCK", "propagation_targets": [4, 5, 7]},
        {"welle": 4, "verdict": "CLEAR", "propagation_targets": []},
        {"welle": 5, "verdict": "CLEAR", "propagation_targets": []},
        {"welle": 6, "verdict": "CLEAR", "propagation_targets": []},
        {"welle": 7, "verdict": "CLEAR", "propagation_targets": []},
    ]
    assert aggregator.decide_marathon(slots) == "BLOCK"


# ----------------------------------------------------------------------
# Test 3 -- Any UNKNOWN (missing telemetry) yields marathon BLOCK.
# ----------------------------------------------------------------------
def test_decide_marathon_any_unknown_is_block(aggregator):
    slots = [
        {"welle": 3, "verdict": "CLEAR", "propagation_targets": []},
        {"welle": 4, "verdict": "CLEAR", "propagation_targets": []},
        {"welle": 5, "verdict": "UNKNOWN", "propagation_targets": []},
        {"welle": 6, "verdict": "CLEAR", "propagation_targets": []},
        {"welle": 7, "verdict": "CLEAR", "propagation_targets": []},
    ]
    assert aggregator.decide_marathon(slots) == "BLOCK"


# ----------------------------------------------------------------------
# Test 4 -- One CAUTION, rest CLEAR -> marathon CAUTION.
# ----------------------------------------------------------------------
def test_decide_marathon_one_caution_no_block_is_caution(aggregator):
    slots = [
        {"welle": 3, "verdict": "CLEAR", "propagation_targets": []},
        {"welle": 4, "verdict": "CAUTION", "propagation_targets": []},
        {"welle": 5, "verdict": "CLEAR", "propagation_targets": []},
        {"welle": 6, "verdict": "CLEAR", "propagation_targets": []},
        {"welle": 7, "verdict": "CLEAR", "propagation_targets": []},
    ]
    assert aggregator.decide_marathon(slots) == "CAUTION"


# ----------------------------------------------------------------------
# Test 5 -- POST-CUTOVER slots are excluded from the marathon verdict.
# ----------------------------------------------------------------------
def test_post_cutover_slots_excluded_from_marathon(aggregator):
    slots = [
        {"welle": 1, "verdict": "POST-CUTOVER", "propagation_targets": []},
        {"welle": 2, "verdict": "POST-CUTOVER", "propagation_targets": []},
        {"welle": 3, "verdict": "CLEAR", "propagation_targets": []},
        {"welle": 4, "verdict": "CLEAR", "propagation_targets": []},
        {"welle": 5, "verdict": "CLEAR", "propagation_targets": []},
        {"welle": 6, "verdict": "CLEAR", "propagation_targets": []},
        {"welle": 7, "verdict": "CLEAR", "propagation_targets": []},
    ]
    # decide_marathon itself filters POST-CUTOVER.
    assert aggregator.decide_marathon(slots) == "CLEAR"


# ----------------------------------------------------------------------
# Test 6 -- Per-welle slot construction from a fixture envelope.
# ----------------------------------------------------------------------
def test_per_welle_slot_from_fixture(tmp_path, aggregator):
    state = tmp_path / "state"
    today = date(2026, 5, 19)
    _write_per_welle_envelope(
        state, 3, today,
        verdict="BLOCK",
        counts={"green": 1, "yellow": 1, "red": 2},
        propagation_targets=[4, 5, 7],
        failed_checks=["check_1_self_reference_trap_pre_detection"],
    )
    envelope = aggregator.build_envelope(today, state)
    slot_3 = next(s for s in envelope["per_welle_slots"] if s["welle"] == 3)
    assert slot_3["verdict"] == "BLOCK"
    assert slot_3["counts"] == {"green": 1, "yellow": 1, "red": 2}
    assert slot_3["propagation_targets"] == [4, 5, 7]
    assert slot_3["dated_at"] == today.isoformat()
    # Welle-1 / Welle-2 with no envelope should be POST-CUTOVER.
    slot_1 = next(s for s in envelope["per_welle_slots"] if s["welle"] == 1)
    assert slot_1["verdict"] == "POST-CUTOVER"
    # Welle-4..7 with no envelope should be UNKNOWN -> marathon BLOCK.
    slot_4 = next(s for s in envelope["per_welle_slots"] if s["welle"] == 4)
    assert slot_4["verdict"] == "UNKNOWN"
    assert envelope["verdict"] == "BLOCK"


# ----------------------------------------------------------------------
# Test 7 -- Stale envelopes (older than max-age-days) treated as missing.
# ----------------------------------------------------------------------
def test_stale_envelope_treated_as_missing(tmp_path, aggregator):
    state = tmp_path / "state"
    today = date(2026, 5, 19)
    # An envelope from 10 days ago is older than the default 2-day cutoff.
    stale = date(2026, 5, 9)
    for w in LIVE_WELLEN:
        _write_per_welle_envelope(state, w, stale, verdict="CLEAR")
    envelope = aggregator.build_envelope(today, state, max_age_days=2)
    live_slots = [
        s for s in envelope["per_welle_slots"] if s["welle"] in LIVE_WELLEN
    ]
    assert all(s["verdict"] == "UNKNOWN" for s in live_slots)
    assert envelope["verdict"] == "BLOCK"


# ----------------------------------------------------------------------
# Test 8 -- Transitive closure of propagation edges.
# ----------------------------------------------------------------------
def test_transitive_closure_propagates_through_chain(aggregator):
    slots = [
        {
            "welle": 3,
            "verdict": "BLOCK",
            "propagation_targets": [4, 5, 7],
        },
        {
            "welle": 4,
            "verdict": "BLOCK",
            "propagation_targets": [5, 7],
        },
        {
            "welle": 5,
            "verdict": "CLEAR",
            "propagation_targets": [7],
        },
        {"welle": 6, "verdict": "CLEAR", "propagation_targets": []},
        {"welle": 7, "verdict": "CLEAR", "propagation_targets": []},
    ]
    union, per_seed = aggregator._transitive_closure(slots)
    # From the BLOCK seeds 3 and 4 we reach {4,5,7} U {5,7} U
    # (transitively through 4 -> 5,7 and 5 -> 7) = {4,5,7}.
    assert union == [4, 5, 7]
    # Welle-3 seed reaches 4, then 4's edges {5,7}, then 5's edge {7}.
    assert per_seed[3] == [4, 5, 7]
    # Welle-4 seed reaches {5, 7}, then 5 -> 7.
    assert per_seed[4] == [5, 7]


# ----------------------------------------------------------------------
# Test 9 -- Ranking surfaces the highest-severity welle first.
# ----------------------------------------------------------------------
def test_ranking_orders_block_above_caution_above_clear(aggregator):
    slots = [
        {
            "welle": 6,
            "verdict": "CAUTION",
            "counts": {"green": 3, "yellow": 1, "red": 0},
            "propagation_targets": [],
        },
        {
            "welle": 3,
            "verdict": "BLOCK",
            "counts": {"green": 1, "yellow": 1, "red": 2},
            "propagation_targets": [4, 5, 7],
        },
        {
            "welle": 7,
            "verdict": "CLEAR",
            "counts": {"green": 4, "yellow": 0, "red": 0},
            "propagation_targets": [],
        },
        {
            "welle": 4,
            "verdict": "BLOCK",
            "counts": {"green": 2, "yellow": 0, "red": 2},
            "propagation_targets": [5, 7],
        },
        {
            "welle": 5,
            "verdict": "CLEAR",
            "counts": {"green": 4, "yellow": 0, "red": 0},
            "propagation_targets": [],
        },
    ]
    ranked = aggregator._rank(slots)
    # Welle-3 (2 reds, propagation fan 3) outranks Welle-4 (2 reds,
    # propagation fan 2). Welle-6 is the lone CAUTION above the
    # clears.
    assert [s["welle"] for s in ranked[:3]] == [3, 4, 6]


# ----------------------------------------------------------------------
# Test 10 -- Notify-event fires on BLOCK every run.
# ----------------------------------------------------------------------
def test_notify_event_fires_on_block(tmp_path, aggregator):
    envelope = {
        "verdict": "BLOCK",
        "emitted_at_utc": "2026-05-19T07:00:00+00:00",
        "today": "2026-05-19",
        "live_welle_counts": {"CLEAR": 4, "CAUTION": 0, "BLOCK": 1, "UNKNOWN": 0},
        "cascade_fan_out": [4, 5, 7],
        "top_hot_spots": [{"welle": 3, "verdict": "BLOCK"}],
    }
    notify = tmp_path / "notify.jsonl"
    assert aggregator.emit_notify_event(envelope, notify, prev_verdict=None)
    assert aggregator.emit_notify_event(envelope, notify, prev_verdict="BLOCK")
    lines = notify.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    parsed = json.loads(lines[0])
    assert parsed["kind"] == "cross-welle-hot-spot-aggregator"
    assert parsed["verdict"] == "BLOCK"
    assert parsed["cascade_fan_out"] == [4, 5, 7]


# ----------------------------------------------------------------------
# Test 11 -- Notify-event suppressed on stable CAUTION.
# ----------------------------------------------------------------------
def test_notify_event_suppressed_on_stable_caution(tmp_path, aggregator):
    envelope = {
        "verdict": "CAUTION",
        "emitted_at_utc": "2026-05-19T07:00:00+00:00",
        "today": "2026-05-19",
        "live_welle_counts": {"CLEAR": 4, "CAUTION": 1, "BLOCK": 0, "UNKNOWN": 0},
        "cascade_fan_out": [],
        "top_hot_spots": [{"welle": 4, "verdict": "CAUTION"}],
    }
    notify = tmp_path / "notify.jsonl"
    # Fires on first transition.
    assert aggregator.emit_notify_event(envelope, notify, prev_verdict="CLEAR")
    # Suppressed on stable CAUTION (prev == CAUTION).
    assert not aggregator.emit_notify_event(
        envelope, notify, prev_verdict="CAUTION"
    )
    lines = notify.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


# ----------------------------------------------------------------------
# Test 12 -- Notify-event never fires on CLEAR.
# ----------------------------------------------------------------------
def test_notify_event_never_fires_on_clear(tmp_path, aggregator):
    envelope = {
        "verdict": "CLEAR",
        "emitted_at_utc": "2026-05-19T07:00:00+00:00",
        "today": "2026-05-19",
        "live_welle_counts": {"CLEAR": 5, "CAUTION": 0, "BLOCK": 0, "UNKNOWN": 0},
        "cascade_fan_out": [],
        "top_hot_spots": [],
    }
    notify = tmp_path / "notify.jsonl"
    assert not aggregator.emit_notify_event(
        envelope, notify, prev_verdict=None
    )
    assert not aggregator.emit_notify_event(
        envelope, notify, prev_verdict="BLOCK"
    )
    assert not notify.exists()


# ----------------------------------------------------------------------
# Test 13 -- Envelope schema fields present and well-typed.
# ----------------------------------------------------------------------
def test_envelope_schema_fields(tmp_path, aggregator):
    state = tmp_path / "state"
    today = date(2026, 5, 19)
    for w in LIVE_WELLEN:
        _write_per_welle_envelope(state, w, today, verdict="CLEAR")
    env = aggregator.build_envelope(today, state)
    expected_keys = {
        "schema_version",
        "workflow",
        "emitted_at_utc",
        "today",
        "max_age_days",
        "live_wellen",
        "post_cutover_wellen",
        "verdict",
        "live_welle_counts",
        "per_welle_slots",
        "cascade_fan_out",
        "cascade_fan_out_per_seed",
        "top_hot_spots",
        "ranking",
        "cross_substrate_links",
    }
    assert expected_keys <= set(env.keys())
    assert env["schema_version"] == 1
    assert env["workflow"] == "cross-welle-hot-spot-aggregator"
    assert env["today"] == today.isoformat()
    assert env["live_wellen"] == list(LIVE_WELLEN)
    assert env["post_cutover_wellen"] == list(POST_CUTOVER_WELLEN)
    assert env["verdict"] == "CLEAR"
    assert env["live_welle_counts"]["CLEAR"] == 5
    assert env["live_welle_counts"]["BLOCK"] == 0
    # cross_substrate_links should reference all five per-welle workflows.
    for w in LIVE_WELLEN:
        key = f"welle_{w}_hot_spot_workflow"
        assert key in env["cross_substrate_links"], key


# ----------------------------------------------------------------------
# Test 14 -- CLI --print-stdout round-trip.
# ----------------------------------------------------------------------
def test_cli_print_stdout_round_trip(tmp_path, capsys, aggregator):
    state = tmp_path / "state"
    today = date(2026, 5, 19)
    for w in LIVE_WELLEN:
        _write_per_welle_envelope(state, w, today, verdict="CLEAR")
    out_path = tmp_path / "out.json"
    rc = aggregator.main(
        [
            "cross_welle_hot_spot_aggregator",
            "--state-root", str(state),
            "--output", str(out_path),
            "--today", today.isoformat(),
            "--print-stdout",
        ]
    )
    assert rc == 0
    file_envelope = json.loads(out_path.read_text(encoding="utf-8"))
    stdout_envelope = json.loads(capsys.readouterr().out)
    assert file_envelope == stdout_envelope
    assert file_envelope["verdict"] == "CLEAR"


# ----------------------------------------------------------------------
# Test 15 -- Workflow YAML has the documented trigger surface.
# ----------------------------------------------------------------------
def test_workflow_yaml_trigger_surface(workflow_yaml):
    # PyYAML parses ``on:`` as the boolean key True; tolerate both forms.
    on_section = workflow_yaml.get("on") or workflow_yaml.get(True)
    assert on_section is not None, "workflow has no 'on' section"
    assert "schedule" in on_section
    crons = [s["cron"] for s in on_section["schedule"]]
    assert "0 7 * * *" in crons
    assert "workflow_dispatch" in on_section
    assert "push" in on_section
    assert "pull_request" in on_section
    # Path-filter includes the four canonical paths.
    push_paths = on_section["push"]["paths"]
    assert "tooling/ci/cross_welle_hot_spot_aggregator.py" in push_paths
    assert ".github/workflows/cross-welle-hot-spot-aggregator.yml" in push_paths
    assert "tests/ci/test_cross_welle_hot_spot_aggregator.py" in push_paths
    assert (
        "docs/ci/cross-welle-hot-spot-aggregator-runbook.md" in push_paths
    )


# ----------------------------------------------------------------------
# Test 16 -- Workflow has a single aggregate job, hermetic posture,
#             permissions: contents: read.
# ----------------------------------------------------------------------
def test_workflow_yaml_aggregate_job_shape(workflow_yaml):
    assert workflow_yaml["permissions"] == {"contents": "read"}
    jobs = workflow_yaml["jobs"]
    assert "aggregate" in jobs
    agg = jobs["aggregate"]
    assert agg["runs-on"] == "ubuntu-latest"
    assert agg["timeout-minutes"] == 10
    step_names = [s.get("name") for s in agg["steps"] if isinstance(s, dict)]
    # Required step sequence:
    assert "Checkout" in step_names
    assert "Set up Python 3.13" in step_names
    assert "Resolve today" in step_names
    assert "Run cross-welle aggregator" in step_names
    assert "Render Job-Summary" in step_names
    assert "Upload artifacts" in step_names
    assert "Persist state (operator-hand only)" in step_names


# ----------------------------------------------------------------------
# Test 17 -- Runbook references the workflow + aggregator paths.
# ----------------------------------------------------------------------
def test_runbook_references_workflow_and_aggregator():
    assert RUNBOOK_PATH.is_file(), f"runbook missing: {RUNBOOK_PATH}"
    text = RUNBOOK_PATH.read_text(encoding="utf-8")
    assert ".github/workflows/cross-welle-hot-spot-aggregator.yml" in text
    assert "tooling/ci/cross_welle_hot_spot_aggregator.py" in text
    assert "Welle-3" in text
    assert "Welle-7" in text


# ----------------------------------------------------------------------
# Test 18 -- Job-Summary renderer emits the expected table + sections.
# ----------------------------------------------------------------------
def test_render_summary_table_and_sections():
    spec = importlib.util.spec_from_file_location(
        "cross_welle_hot_spot_render_summary", RENDER_SUMMARY_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cross_welle_hot_spot_render_summary"] = mod
    spec.loader.exec_module(mod)
    envelope = {
        "per_welle_slots": [
            {
                "welle": 3,
                "verdict": "BLOCK",
                "dated_at": "2026-05-19",
                "counts": {"red": 2, "yellow": 1, "green": 1},
                "propagation_targets": [4, 5, 7],
            },
            {
                "welle": 4,
                "verdict": "CLEAR",
                "dated_at": "2026-05-19",
                "counts": {"red": 0, "yellow": 0, "green": 4},
                "propagation_targets": [],
            },
        ],
        "cascade_fan_out": [4, 5, 7],
        "top_hot_spots": [
            {"welle": 3, "verdict": "BLOCK", "propagation_targets": [4, 5, 7]}
        ],
    }
    out = mod.render(envelope)
    assert "| Welle | Verdict | Dated-at | Counts(r/y/g) | Propagation |" in out
    assert "| 3 | BLOCK | 2026-05-19 | 2/1/1 | 4,5,7 |" in out
    assert "| 4 | CLEAR | 2026-05-19 | 0/0/4 | - |" in out
    assert "## Cascade fan-out" in out
    assert "Transitively reached downstream wellen: [4, 5, 7]" in out
    assert "## Top hot-spots (ranked)" in out
    assert "1. Welle-3 -- BLOCK (propagation_targets=[4, 5, 7])" in out


# ----------------------------------------------------------------------
# Test 19 -- Job-Summary renderer handles missing / empty data.
# ----------------------------------------------------------------------
def test_render_summary_handles_empty_envelope():
    spec = importlib.util.spec_from_file_location(
        "cross_welle_hot_spot_render_summary", RENDER_SUMMARY_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cross_welle_hot_spot_render_summary"] = mod
    spec.loader.exec_module(mod)
    out = mod.render({})
    assert "No propagation block fired." in out
    # POST-CUTOVER slot with no counts must render "-" placeholders.
    out2 = mod.render(
        {
            "per_welle_slots": [
                {
                    "welle": 1,
                    "verdict": "POST-CUTOVER",
                    "dated_at": None,
                    "counts": None,
                    "propagation_targets": [],
                }
            ]
        }
    )
    assert "| 1 | POST-CUTOVER | - | - | - |" in out2
