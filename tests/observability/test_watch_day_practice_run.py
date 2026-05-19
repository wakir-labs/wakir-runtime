#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/observability/watch-day-practice-run.py``.

These tests pin the Tag-55 Watch-Day-Practice-Run simulator. The
simulator drives the §4 six-slot procedure end-to-end through
deterministic mock-input scenarios and reuses the Tag-54
``pre-cutover-watch-day-verdict.py`` pure-function reference
implementation for the §7 verdict-formula and §10 schema-validation.

Stdlib-only (pytest as runner). No network, no podman, no live VM.

Test coverage (>= 12 tests):

   1. test_all_green_scenario_yields_green_verdict
   2. test_amber_dashboard_drift_scenario_yields_amber
   3. test_amber_probe_scenario_yields_amber_not_red
   4. test_red_probe_scenario_yields_red_with_reason
   5. test_red_hard_zero_slo_scenario_yields_red
   6. test_red_welle_slo_fast_burn_scenario_yields_red
   7. test_red_ci_gate_fail_scenario_yields_red
   8. test_slo1_burn_without_tomorrow_cutover_does_not_force_red
   9. test_multi_blocker_red_blockers_in_stable_order
  10. test_every_simulated_journal_entry_validates_against_schema
  11. test_every_simulated_slot_sequence_validates_against_schema
  12. test_practice_run_writes_state_directory_when_requested
  13. test_run_practice_built_in_catalogue_is_all_pass
  14. test_cli_exit_zero_on_overall_pass
  15. test_cli_json_output_is_valid_json
  16. test_cli_scenario_filter_runs_subset

Anchor: Tag-55 Noa-SRE Watch-Day-Practice-Run.
Predecessor: Tag-54 Pre-Cutover-Watch-Day Spec.
Author: Noa Bergstroem (SRE)
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Loader: import the practice-run module from its hyphenated path.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_PRACTICE_PATH = (
    _REPO_ROOT
    / "scripts"
    / "observability"
    / "watch-day-practice-run.py"
)

_spec = importlib.util.spec_from_file_location(
    "watch_day_practice_run", str(_PRACTICE_PATH)
)
assert _spec is not None and _spec.loader is not None
practice_mod = importlib.util.module_from_spec(_spec)
sys.modules["watch_day_practice_run"] = practice_mod
_spec.loader.exec_module(practice_mod)


# ---------------------------------------------------------------------------
# 1. all-green -> GREEN.
# ---------------------------------------------------------------------------

def test_all_green_scenario_yields_green_verdict():
    scenario = practice_mod.scenario_all_green()
    result = practice_mod.simulate_scenario(scenario)
    assert result.computed_verdict == "GREEN"
    assert result.expected_verdict == "GREEN"
    assert result.computed_red_blockers == ()
    assert result.pass_ is True
    assert all(s.pass_ for s in result.slot_results)
    assert result.sequence_validation_ok is True


# ---------------------------------------------------------------------------
# 2. dashboard drift -> AMBER (drift-type-A, Noa-domain).
# ---------------------------------------------------------------------------

def test_amber_dashboard_drift_scenario_yields_amber():
    scenario = practice_mod.scenario_amber_dashboard_drift()
    result = practice_mod.simulate_scenario(scenario)
    assert result.computed_verdict == "AMBER"
    assert result.computed_red_blockers == ()
    # Dashboards-fail-count on the dashboard-checking slots reflects
    # the drift; this is what the operator records in the journal.
    slot_08 = next(s for s in result.slot_results if s.slot == "08")
    assert slot_08.journal_entry["dashboards_fail_count"] == 1
    assert slot_08.journal_entry["dashboards_pass_count"] == 9


# ---------------------------------------------------------------------------
# 3. AMBER probe -> AMBER verdict, no RED-blocker.
# ---------------------------------------------------------------------------

def test_amber_probe_scenario_yields_amber_not_red():
    scenario = practice_mod.scenario_amber_probe()
    result = practice_mod.simulate_scenario(scenario)
    assert result.computed_verdict == "AMBER"
    assert result.computed_red_blockers == ()
    assert result.pass_ is True


# ---------------------------------------------------------------------------
# 4. RED probe -> RED verdict with the spec'd reason string.
# ---------------------------------------------------------------------------

def test_red_probe_scenario_yields_red_with_reason():
    scenario = practice_mod.scenario_red_probe()
    result = practice_mod.simulate_scenario(scenario)
    assert result.computed_verdict == "RED"
    assert "probe-verdict-RED:welle-1" in result.computed_red_blockers
    assert result.pass_ is True


# ---------------------------------------------------------------------------
# 5. Hard-zero SLO burn-rate firing -> RED.
# ---------------------------------------------------------------------------

def test_red_hard_zero_slo_scenario_yields_red():
    scenario = practice_mod.scenario_red_hard_zero_slo()
    result = practice_mod.simulate_scenario(scenario)
    assert result.computed_verdict == "RED"
    assert "hard-zero-slo-burn:SLO-5" in result.computed_red_blockers


# ---------------------------------------------------------------------------
# 6. Welle-SLO fast-burn WITH tomorrow-cutover -> RED.
# ---------------------------------------------------------------------------

def test_red_welle_slo_fast_burn_scenario_yields_red():
    scenario = practice_mod.scenario_red_welle_slo_fast_burn()
    result = practice_mod.simulate_scenario(scenario)
    assert result.computed_verdict == "RED"
    assert (
        "welle-slo-fast-burn-with-tomorrow-cutover:SLO-1"
        in result.computed_red_blockers
    )


# ---------------------------------------------------------------------------
# 7. CI-gate failure -> RED.
# ---------------------------------------------------------------------------

def test_red_ci_gate_fail_scenario_yields_red():
    scenario = practice_mod.scenario_red_ci_gate_fail()
    result = practice_mod.simulate_scenario(scenario)
    assert result.computed_verdict == "RED"
    assert "ci-gate-failed:C1" in result.computed_red_blockers


# ---------------------------------------------------------------------------
# 8. SLO-1 burn WITHOUT tomorrow-cutover -> not RED.
# ---------------------------------------------------------------------------

def test_slo1_burn_without_tomorrow_cutover_does_not_force_red():
    scenario = practice_mod.scenario_green_slo1_burn_without_cutover_welle()
    result = practice_mod.simulate_scenario(scenario)
    assert result.computed_verdict == "GREEN"
    assert result.computed_red_blockers == ()
    assert "welle-slo-fast-burn-with-tomorrow-cutover:SLO-1" not in (
        result.computed_red_blockers
    )


# ---------------------------------------------------------------------------
# 9. Multi-blocker: red-blocker order is stable per spec.
# ---------------------------------------------------------------------------

def test_multi_blocker_red_blockers_in_stable_order():
    scenario = practice_mod.scenario_red_multi_blocker()
    result = practice_mod.simulate_scenario(scenario)
    assert result.computed_verdict == "RED"
    # Stable order: probe-RED -> hard-zero -> welle-slo -> ci-gate.
    expected = (
        "probe-verdict-RED:welle-1",
        "hard-zero-slo-burn:SLO-5",
        "welle-slo-fast-burn-with-tomorrow-cutover:SLO-1",
        "ci-gate-failed:C1",
    )
    assert result.computed_red_blockers == expected


# ---------------------------------------------------------------------------
# 10. Per-slot journal-entry schema validates for every scenario.
# ---------------------------------------------------------------------------

def test_every_simulated_journal_entry_validates_against_schema():
    report = practice_mod.run_practice()
    for scenario in report.scenarios:
        for slot in scenario.slot_results:
            assert slot.journal_validation.ok, (
                f"scenario={scenario.scenario_name} slot={slot.slot} "
                f"errors={slot.journal_validation.errors}"
            )


# ---------------------------------------------------------------------------
# 11. Slot-sequence validates for every scenario.
# ---------------------------------------------------------------------------

def test_every_simulated_slot_sequence_validates_against_schema():
    report = practice_mod.run_practice()
    for scenario in report.scenarios:
        assert scenario.sequence_validation_ok, (
            f"scenario={scenario.scenario_name} "
            f"errors={scenario.sequence_validation_errors}"
        )


# ---------------------------------------------------------------------------
# 12. State-directory artefacts are written when requested.
# ---------------------------------------------------------------------------

def test_practice_run_writes_state_directory_when_requested(tmp_path):
    state_root = tmp_path / "watch-day-practice-state"
    report = practice_mod.run_practice(state_root=state_root)
    assert report.overall_pass is True
    # Every scenario must have produced verdict.txt + journal.
    for scenario in report.scenarios:
        sd = state_root / scenario.scenario_name
        assert sd.is_dir(), f"missing state dir for {scenario.scenario_name}"
        verdict_txt = sd / "verdict.txt"
        assert verdict_txt.is_file()
        assert verdict_txt.read_text(encoding="utf-8").strip() == (
            scenario.computed_verdict
        )
        journal = sd / "watch-day-journal.jsonl"
        assert journal.is_file()
        entries = [
            json.loads(line)
            for line in journal.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(entries) == 6
        # Slots are in §4 order.
        assert [e["slot"] for e in entries] == ["08", "10", "12", "14", "16", "18"]
        # slot=16 and slot=18 carry a verdict; the others do not.
        for entry in entries:
            if entry["slot"] in ("16", "18"):
                assert entry["verdict"] in ("GREEN", "AMBER", "RED")
            else:
                assert entry["verdict"] is None


# ---------------------------------------------------------------------------
# 13. The built-in scenario catalogue is internally consistent.
# ---------------------------------------------------------------------------

def test_run_practice_built_in_catalogue_is_all_pass():
    report = practice_mod.run_practice()
    assert report.overall_pass is True, (
        f"failed scenarios: "
        f"{[s.scenario_name for s in report.scenarios if not s.pass_]}"
    )
    # Catalogue must include at least one of each verdict-class.
    verdicts = {s.computed_verdict for s in report.scenarios}
    assert "GREEN" in verdicts
    assert "AMBER" in verdicts
    assert "RED" in verdicts


# ---------------------------------------------------------------------------
# 14. CLI exit-code: 0 on overall pass.
# ---------------------------------------------------------------------------

def test_cli_exit_zero_on_overall_pass(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(_PRACTICE_PATH),
            "--state-root",
            str(tmp_path / "state"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Pre-Cutover Watch-Day Practice-Run Report" in proc.stdout
    assert "overall=PASS" in proc.stdout


# ---------------------------------------------------------------------------
# 15. CLI --json output is valid JSON with the expected shape.
# ---------------------------------------------------------------------------

def test_cli_json_output_is_valid_json():
    proc = subprocess.run(
        [
            sys.executable,
            str(_PRACTICE_PATH),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert "total" in payload
    assert "passed" in payload
    assert "failed" in payload
    assert "overall_pass" in payload
    assert "scenarios" in payload
    assert payload["overall_pass"] is True
    assert payload["total"] == len(payload["scenarios"])


# ---------------------------------------------------------------------------
# 16. CLI --scenario filter runs only the named subset.
# ---------------------------------------------------------------------------

def test_cli_scenario_filter_runs_subset():
    proc = subprocess.run(
        [
            sys.executable,
            str(_PRACTICE_PATH),
            "--json",
            "--scenario",
            "all-green",
            "--scenario",
            "red-probe",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    # red-probe is expected to RED, but its expected_verdict matches
    # so the scenario *passes* (the simulator validates that the
    # spec-§7 implementation behaves as documented). overall_pass
    # must therefore be True for the filtered subset.
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["total"] == 2
    names = {s["scenario"] for s in payload["scenarios"]}
    assert names == {"all-green", "red-probe"}


# ---------------------------------------------------------------------------
# 17. CLI: unknown --scenario filter yields exit-code 2.
# ---------------------------------------------------------------------------

def test_cli_unknown_scenario_filter_exits_nonzero():
    proc = subprocess.run(
        [
            sys.executable,
            str(_PRACTICE_PATH),
            "--scenario",
            "does-not-exist",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "no built-in scenarios matched" in proc.stderr
