# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic CI-substrate tests for the Tomas Tag-44 Phase-3 Cutover-Day
Auto-Scheduler workflow plus its decision-tree module.

Test scope
----------

1. Workflow YAML structural shape
   (``.github/workflows/phase-3-cutover-day-auto-scheduler.yml``):
     - three trigger sources (workflow_dispatch + schedule + push),
     - Monday 07:00 UTC cron present,
     - permissions block declares actions:write for gh workflow run,
     - decide-and-dispatch job present with required steps in order,
     - dry_run_override workflow_dispatch input documented.

2. Decision-tree week-action mapping
   (``tooling/ci/decide_cutover_day_dispatch.py``):
     - KW-24 -> Welle-1+2 doppel, marker false,
     - KW-25 -> Welle-3 solo, marker false,
     - KW-26 -> Welle-4+5 doppel, marker false,
     - KW-27 -> Welle-6+7 doppel, marker true,
     - any other week -> PROBE_ONLY.

3. Gate evaluation truth table:
     - all three gates green/READY/ratified -> PROCEED,
     - sanity=BLOCK overrides everything -> BLOCK,
     - reza-trend=red -> BLOCK,
     - sanity=missing or reza=missing -> BLOCK,
     - sanity=CAUTION (only soft) -> DRY_RUN_ONLY,
     - reza=yellow (only soft) -> DRY_RUN_ONLY,
     - ar-hand=False (only soft) -> DRY_RUN_ONLY,
     - combined soft signals -> DRY_RUN_ONLY.

4. Dispatch-plan composition:
     - KW-24 PROCEED -> 2 welle-workflows, no marker,
     - KW-27 PROCEED -> 2 welle-workflows + marker,
     - KW-27 DRY_RUN_ONLY -> 2 welle-workflows, no marker (marker only
       on real proceed),
     - any cutover-week BLOCK -> empty workflow list,
     - PROBE_ONLY any gate state -> pre-cutover-sanity workflow.

5. Input parsers (file readers):
     - non-existent file -> "missing" / False,
     - malformed JSON -> "red" / "BLOCK" / False,
     - well-formed JSON with valid value -> parsed value.

6. End-to-end envelope-shape sanity-check.

Sandbox boundary
----------------

Pure stdlib + pyyaml + pytest. No subprocess, no gh, no network.
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
    REPO_ROOT
    / ".github"
    / "workflows"
    / "phase-3-cutover-day-auto-scheduler.yml"
)
DECIDE_SCRIPT = (
    REPO_ROOT / "tooling" / "ci" / "decide_cutover_day_dispatch.py"
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
def workflow_yaml() -> dict:
    assert WORKFLOW_PATH.is_file(), f"workflow missing: {WORKFLOW_PATH}"
    data = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def decide():
    return _load_module("_decide_cutover_day_dispatch", DECIDE_SCRIPT)


# ---------------------------------------------------------------------------
# 1. Workflow YAML structural shape
# ---------------------------------------------------------------------------


def test_workflow_yaml_present_and_parseable(workflow_yaml):
    assert workflow_yaml.get("name") == "phase-3-cutover-day-auto-scheduler"


def test_workflow_three_trigger_sources(workflow_yaml):
    # PyYAML parses the bare `on:` key as the boolean True, so we
    # accept either spelling here.
    triggers = workflow_yaml.get("on") or workflow_yaml.get(True)
    assert isinstance(triggers, dict), f"on: not a dict: {triggers!r}"
    assert "workflow_dispatch" in triggers
    assert "schedule" in triggers
    assert "push" in triggers


def test_workflow_monday_seven_utc_cron(workflow_yaml):
    triggers = workflow_yaml.get("on") or workflow_yaml.get(True)
    schedule = triggers["schedule"]
    assert any(s.get("cron") == "0 7 * * 1" for s in schedule), (
        f"expected '0 7 * * 1' cron, got {schedule!r}"
    )


def test_workflow_workflow_dispatch_inputs(workflow_yaml):
    triggers = workflow_yaml.get("on") or workflow_yaml.get(True)
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert "force_iso_week" in inputs
    assert "dry_run_override" in inputs


def test_workflow_permissions_actions_write(workflow_yaml):
    perms = workflow_yaml["permissions"]
    assert perms.get("actions") == "write", (
        "gh workflow run requires actions:write"
    )
    assert perms.get("contents") == "read"


def test_workflow_decide_and_dispatch_job_present(workflow_yaml):
    jobs = workflow_yaml["jobs"]
    assert "decide-and-dispatch" in jobs


def test_workflow_required_step_names_in_order(workflow_yaml):
    steps = workflow_yaml["jobs"]["decide-and-dispatch"]["steps"]
    names = [s.get("name", "") for s in steps]
    expected_subseq = [
        "Resolve ISO calendar week (UTC)",
        "Fetch latest pre-cutover-sanity verdict artifact",
        "Render dispatch-plan envelope (decision-tree)",
        "Upload dispatch-plan envelope artifact",
        "Notify-cascade (Slack-mock / notify-stream append)",
        "Upload notify-stream artifact",
        "Fan-out dispatch (TRIGGER mode only)",
        "Probe-only fan-out (PROBE mode)",
        "Terminal-status gate",
    ]
    # All expected names must appear in this order (subsequence).
    idx = 0
    for n in names:
        if idx < len(expected_subseq) and n == expected_subseq[idx]:
            idx += 1
    assert idx == len(expected_subseq), (
        f"missing or out-of-order steps; got names {names!r}"
    )


# ---------------------------------------------------------------------------
# 2. Week-action mapping (four KW-paths)
# ---------------------------------------------------------------------------


def test_week_action_kw_24_welle_1_plus_2(decide):
    wa = decide.decide_week_action(24)
    assert wa.kind == "WELLE_1_PLUS_2"
    assert wa.wellen == (1, 2)
    assert wa.complete_marker is False


def test_week_action_kw_25_welle_3_solo(decide):
    wa = decide.decide_week_action(25)
    assert wa.kind == "WELLE_3"
    assert wa.wellen == (3,)
    assert wa.complete_marker is False


def test_week_action_kw_26_welle_4_plus_5(decide):
    wa = decide.decide_week_action(26)
    assert wa.kind == "WELLE_4_PLUS_5"
    assert wa.wellen == (4, 5)
    assert wa.complete_marker is False


def test_week_action_kw_27_welle_6_plus_7_with_marker(decide):
    wa = decide.decide_week_action(27)
    assert wa.kind == "WELLE_6_PLUS_7"
    assert wa.wellen == (6, 7)
    assert wa.complete_marker is True


@pytest.mark.parametrize("week", [1, 20, 23, 28, 30, 52])
def test_week_action_probe_only_outside_cutover_weeks(decide, week):
    wa = decide.decide_week_action(week)
    assert wa.kind == "PROBE_ONLY"
    assert wa.wellen == ()
    assert wa.complete_marker is False


# ---------------------------------------------------------------------------
# 3. Gate evaluation truth-table
# ---------------------------------------------------------------------------


def test_gate_all_green_proceeds(decide):
    v = decide.evaluate_gates(
        decide.GateInputs(
            reza_trend="green",
            sanity_verdict="READY",
            ar_hand_ratified=True,
        )
    )
    assert v.kind == "PROCEED"
    assert v.missing_inputs == ()


def test_gate_sanity_block_overrides_all(decide):
    # Even with everything else green, sanity=BLOCK forces BLOCK.
    v = decide.evaluate_gates(
        decide.GateInputs(
            reza_trend="green",
            sanity_verdict="BLOCK",
            ar_hand_ratified=True,
        )
    )
    assert v.kind == "BLOCK"


def test_gate_reza_red_blocks(decide):
    v = decide.evaluate_gates(
        decide.GateInputs(
            reza_trend="red",
            sanity_verdict="READY",
            ar_hand_ratified=True,
        )
    )
    assert v.kind == "BLOCK"


def test_gate_sanity_missing_blocks(decide):
    v = decide.evaluate_gates(
        decide.GateInputs(
            reza_trend="green",
            sanity_verdict="missing",
            ar_hand_ratified=True,
        )
    )
    assert v.kind == "BLOCK"
    assert "sanity_verdict" in v.missing_inputs


def test_gate_reza_missing_blocks(decide):
    v = decide.evaluate_gates(
        decide.GateInputs(
            reza_trend="missing",
            sanity_verdict="READY",
            ar_hand_ratified=True,
        )
    )
    assert v.kind == "BLOCK"
    assert "reza_trend" in v.missing_inputs


def test_gate_sanity_caution_only_soft_degrades_dry_run(decide):
    v = decide.evaluate_gates(
        decide.GateInputs(
            reza_trend="green",
            sanity_verdict="CAUTION",
            ar_hand_ratified=True,
        )
    )
    assert v.kind == "DRY_RUN_ONLY"


def test_gate_reza_yellow_only_soft_degrades_dry_run(decide):
    v = decide.evaluate_gates(
        decide.GateInputs(
            reza_trend="yellow",
            sanity_verdict="READY",
            ar_hand_ratified=True,
        )
    )
    assert v.kind == "DRY_RUN_ONLY"


def test_gate_ar_hand_unratified_only_soft_degrades_dry_run(decide):
    v = decide.evaluate_gates(
        decide.GateInputs(
            reza_trend="green",
            sanity_verdict="READY",
            ar_hand_ratified=False,
        )
    )
    assert v.kind == "DRY_RUN_ONLY"


def test_gate_combined_soft_signals_still_dry_run(decide):
    v = decide.evaluate_gates(
        decide.GateInputs(
            reza_trend="yellow",
            sanity_verdict="CAUTION",
            ar_hand_ratified=False,
        )
    )
    assert v.kind == "DRY_RUN_ONLY"


# Truth-table sweep over all 4*4*2 = 32 permutations. Spot-check that
# whatever the rule outputs is one of the three valid kinds and is
# consistent with the cascading priority documented in the module.
@pytest.mark.parametrize(
    "reza,sanity,ratified",
    list(product(
        ["green", "yellow", "red", "missing"],
        ["READY", "CAUTION", "BLOCK", "missing"],
        [True, False],
    )),
)
def test_gate_truth_table_well_formed(decide, reza, sanity, ratified):
    v = decide.evaluate_gates(
        decide.GateInputs(
            reza_trend=reza,
            sanity_verdict=sanity,
            ar_hand_ratified=ratified,
        )
    )
    assert v.kind in {"PROCEED", "DRY_RUN_ONLY", "BLOCK"}
    # If sanity is BLOCK -> always BLOCK.
    if sanity == "BLOCK":
        assert v.kind == "BLOCK"
    # If reza is red -> always BLOCK.
    if reza == "red":
        assert v.kind == "BLOCK"
    # If both hard-blocks absent and any input missing -> BLOCK.
    if sanity != "BLOCK" and reza != "red" and (
        sanity == "missing" or reza == "missing"
    ):
        assert v.kind == "BLOCK"
    # PROCEED requires the ideal triple.
    if (
        reza == "green"
        and sanity == "READY"
        and ratified
    ):
        assert v.kind == "PROCEED"


# ---------------------------------------------------------------------------
# 4. Dispatch-plan composition
# ---------------------------------------------------------------------------


def _proceed(decide):
    return decide.GateVerdict(
        kind="PROCEED",
        reza_trend="green",
        sanity_verdict="READY",
        ar_hand_ratified=True,
        missing_inputs=(),
    )


def _dry_run(decide):
    return decide.GateVerdict(
        kind="DRY_RUN_ONLY",
        reza_trend="green",
        sanity_verdict="CAUTION",
        ar_hand_ratified=True,
        missing_inputs=(),
    )


def _block(decide):
    return decide.GateVerdict(
        kind="BLOCK",
        reza_trend="red",
        sanity_verdict="READY",
        ar_hand_ratified=True,
        missing_inputs=(),
    )


def test_plan_kw_24_proceed_two_welle_workflows(decide):
    wa = decide.decide_week_action(24)
    plan = decide.build_dispatch_plan(wa, _proceed(decide), iso_week=24)
    assert plan.mode == "TRIGGER"
    assert plan.workflows == (
        "phase-3c-welle-1-validation.yml",
        "phase-3c-welle-2-validation.yml",
    )
    assert plan.trigger_complete_marker is False
    assert len(plan.tracker_updates) == 2


def test_plan_kw_25_proceed_welle_3_solo(decide):
    wa = decide.decide_week_action(25)
    plan = decide.build_dispatch_plan(wa, _proceed(decide), iso_week=25)
    assert plan.mode == "TRIGGER"
    assert plan.workflows == ("phase-3c-welle-3-validation.yml",)
    assert plan.trigger_complete_marker is False
    assert len(plan.tracker_updates) == 1


def test_plan_kw_27_proceed_includes_complete_marker(decide):
    wa = decide.decide_week_action(27)
    plan = decide.build_dispatch_plan(wa, _proceed(decide), iso_week=27)
    assert plan.mode == "TRIGGER"
    assert plan.workflows[:2] == (
        "phase-3c-welle-6-validation.yml",
        "phase-3c-welle-7-validation.yml",
    )
    assert plan.workflows[-1] == "phase-3-complete-marker.yml"
    assert plan.trigger_complete_marker is True
    assert len(plan.tracker_updates) == 2


def test_plan_kw_27_dry_run_excludes_complete_marker(decide):
    # The complete-marker must only fire on real PROCEED. In DRY_RUN,
    # we still render the welle workflows for visibility but suppress
    # the marker trigger flag.
    wa = decide.decide_week_action(27)
    plan = decide.build_dispatch_plan(wa, _dry_run(decide), iso_week=27)
    assert plan.mode == "DRY_RUN"
    assert plan.trigger_complete_marker is False
    assert "phase-3-complete-marker.yml" not in plan.workflows


def test_plan_kw_24_block_empties_workflows(decide):
    wa = decide.decide_week_action(24)
    plan = decide.build_dispatch_plan(wa, _block(decide), iso_week=24)
    assert plan.mode == "BLOCK"
    assert plan.workflows == ()
    assert plan.tracker_updates == ()


def test_plan_probe_week_returns_sanity_workflow(decide):
    wa = decide.decide_week_action(20)
    plan = decide.build_dispatch_plan(wa, _proceed(decide), iso_week=20)
    assert plan.mode == "PROBE"
    assert plan.workflows == ("phase-3c-pre-cutover-sanity.yml",)
    assert plan.trigger_complete_marker is False


def test_plan_probe_week_ignores_gate_block(decide):
    # In a non-cutover week, even a BLOCK verdict still produces a
    # PROBE plan - the probe is gate-independent (the probe IS the
    # gate input feed for the next cutover-week).
    wa = decide.decide_week_action(20)
    plan = decide.build_dispatch_plan(wa, _block(decide), iso_week=20)
    assert plan.mode == "PROBE"
    assert plan.workflows == ("phase-3c-pre-cutover-sanity.yml",)


# ---------------------------------------------------------------------------
# 5. Input parsers
# ---------------------------------------------------------------------------


def test_parse_reza_trend_missing_file_returns_missing(tmp_path, decide):
    assert decide.parse_reza_trend(tmp_path / "nope.json") == "missing"


def test_parse_reza_trend_none_returns_missing(decide):
    assert decide.parse_reza_trend(None) == "missing"


def test_parse_reza_trend_malformed_json_returns_red(tmp_path, decide):
    p = tmp_path / "trend.json"
    p.write_text("{ not valid json", encoding="utf-8")
    assert decide.parse_reza_trend(p) == "red"


def test_parse_reza_trend_valid_green(tmp_path, decide):
    p = tmp_path / "trend.json"
    p.write_text(json.dumps({"trend": "green"}), encoding="utf-8")
    assert decide.parse_reza_trend(p) == "green"


def test_parse_reza_trend_unknown_value_returns_red(tmp_path, decide):
    p = tmp_path / "trend.json"
    p.write_text(json.dumps({"trend": "purple"}), encoding="utf-8")
    assert decide.parse_reza_trend(p) == "red"


def test_parse_sanity_verdict_missing_file(tmp_path, decide):
    assert decide.parse_sanity_verdict(tmp_path / "nope.json") == "missing"


def test_parse_sanity_verdict_valid_caution(tmp_path, decide):
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"verdict": "CAUTION"}), encoding="utf-8")
    assert decide.parse_sanity_verdict(p) == "CAUTION"


def test_parse_sanity_verdict_malformed_json_returns_block(tmp_path, decide):
    p = tmp_path / "v.json"
    p.write_text("{ broken", encoding="utf-8")
    assert decide.parse_sanity_verdict(p) == "BLOCK"


def test_parse_ar_hand_flag_missing_file_returns_false(tmp_path, decide):
    assert decide.parse_ar_hand_flag(tmp_path / "nope.json") is False


def test_parse_ar_hand_flag_true_payload(tmp_path, decide):
    p = tmp_path / "flag.json"
    p.write_text(
        json.dumps({"ar_hand_ratified": True, "ratified_at": "2026-06-08"}),
        encoding="utf-8",
    )
    assert decide.parse_ar_hand_flag(p) is True


def test_parse_ar_hand_flag_false_payload(tmp_path, decide):
    p = tmp_path / "flag.json"
    p.write_text(
        json.dumps({"ar_hand_ratified": False}),
        encoding="utf-8",
    )
    assert decide.parse_ar_hand_flag(p) is False


def test_parse_ar_hand_flag_malformed_json_returns_false(tmp_path, decide):
    p = tmp_path / "flag.json"
    p.write_text("{ not json", encoding="utf-8")
    assert decide.parse_ar_hand_flag(p) is False


# ---------------------------------------------------------------------------
# 6. End-to-end envelope shape
# ---------------------------------------------------------------------------


def test_envelope_shape_kw_24_proceed(decide):
    inputs = decide.GateInputs(
        reza_trend="green",
        sanity_verdict="READY",
        ar_hand_ratified=True,
    )
    envelope = decide.build_envelope(
        iso_week=24,
        inputs=inputs,
        now_iso="2026-06-08T07:00:00Z",
    )
    assert envelope["version"] == "1.0"
    assert envelope["iso_week"] == 24
    assert envelope["week_action"]["kind"] == "WELLE_1_PLUS_2"
    assert envelope["gate_verdict"]["kind"] == "PROCEED"
    assert envelope["dispatch"]["mode"] == "TRIGGER"
    assert envelope["notify"]["headline"].startswith(
        "Phase-3c KW-24 Cutover-Day: TRIGGER"
    )


def test_envelope_shape_kw_27_dry_run_marker_suppressed(decide):
    inputs = decide.GateInputs(
        reza_trend="green",
        sanity_verdict="CAUTION",
        ar_hand_ratified=True,
    )
    envelope = decide.build_envelope(
        iso_week=27,
        inputs=inputs,
        now_iso="2026-06-29T07:00:00Z",
    )
    assert envelope["dispatch"]["mode"] == "DRY_RUN"
    assert envelope["dispatch"]["trigger_complete_marker"] is False
    assert "phase-3-complete-marker.yml" not in envelope["dispatch"][
        "workflows"
    ]


def test_envelope_shape_probe_week(decide):
    inputs = decide.GateInputs(
        reza_trend="green",
        sanity_verdict="READY",
        ar_hand_ratified=True,
    )
    envelope = decide.build_envelope(
        iso_week=22,
        inputs=inputs,
        now_iso="2026-05-25T07:00:00Z",
    )
    assert envelope["week_action"]["kind"] == "PROBE_ONLY"
    assert envelope["dispatch"]["mode"] == "PROBE"
    assert envelope["dispatch"]["workflows"] == [
        "phase-3c-pre-cutover-sanity.yml"
    ]


# ---------------------------------------------------------------------------
# CLI smoke (no subprocess: invoke main() directly)
# ---------------------------------------------------------------------------


def test_cli_main_writes_envelope_file(tmp_path, decide):
    out = tmp_path / "plan.json"
    # All input files absent -> sanity=missing -> BLOCK -> rc=2.
    rc = decide.main([
        "--iso-week", "24",
        "--reza-trend-path", str(tmp_path / "nope-r.json"),
        "--sanity-verdict-path", str(tmp_path / "nope-s.json"),
        "--ar-hand-flag-path", str(tmp_path / "nope-a.json"),
        "--now-iso", "2026-06-08T07:00:00Z",
        "--output", str(out),
    ])
    assert rc == 2
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["dispatch"]["mode"] == "BLOCK"


def test_cli_main_proceed_full_inputs(tmp_path, decide):
    trend = tmp_path / "trend.json"
    trend.write_text(json.dumps({"trend": "green"}), encoding="utf-8")
    verdict = tmp_path / "verdict.json"
    verdict.write_text(json.dumps({"verdict": "READY"}), encoding="utf-8")
    flag = tmp_path / "flag.json"
    flag.write_text(
        json.dumps({"ar_hand_ratified": True}), encoding="utf-8"
    )
    out = tmp_path / "plan.json"
    rc = decide.main([
        "--iso-week", "27",
        "--reza-trend-path", str(trend),
        "--sanity-verdict-path", str(verdict),
        "--ar-hand-flag-path", str(flag),
        "--now-iso", "2026-06-29T07:00:00Z",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["dispatch"]["mode"] == "TRIGGER"
    assert payload["dispatch"]["trigger_complete_marker"] is True
