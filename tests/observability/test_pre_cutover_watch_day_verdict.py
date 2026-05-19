#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/observability/pre-cutover-watch-day-verdict.py``.

These tests pin the Tag-54 Watch-Day-Verdict pure-function
reference implementation to the §7 verdict-formula and the
§10 journal-entry schema in
``docs/observability/pre-cutover-watch-day-spec.md``.

Stdlib-only (pytest as runner). No network, no podman, no
live VM.

Test coverage (>= 10 tests):

  1.  test_all_green_inputs_yield_green_verdict
  2.  test_one_missing_dashboard_drops_to_amber
  3.  test_amber_probe_drops_to_amber_not_red
  4.  test_red_probe_forces_red_verdict
  5.  test_hard_zero_slo_burn_forces_red_with_reason
  6.  test_welle_slo_fast_burn_with_tomorrow_cutover_is_red
  7.  test_welle_slo_fast_burn_without_tomorrow_cutover_not_red
  8.  test_ci_gate_failure_forces_red_with_reason
  9.  test_missing_dashboards_and_alert_groups_helpers
  10. test_amber_probes_helper_returns_sorted_welle_ids
  11. test_validate_journal_entry_complete_slot_08_ok
  12. test_validate_journal_entry_missing_field_errors
  13. test_validate_journal_entry_verdict_required_at_slot_16
  14. test_validate_journal_entry_verdict_must_be_null_at_slot_08
  15. test_validate_journal_sequence_full_day_ok
  16. test_validate_journal_sequence_verdict_reconfirmation_mismatch
  17. test_severity_class_lookup_known_triggers
  18. test_severity_class_lookup_unknown_trigger_raises
  19. test_red_blocker_reasons_are_sorted_and_stable
  20. test_cli_writes_verdict_file_for_green_inputs

Anchor: Tag-54 Noa-SRE Pre-Cutover-Watch-Day-Spec.
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
# Loader: import the verdict module from its hyphenated path.
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
_VERDICT_PATH = (
    _REPO_ROOT
    / "scripts"
    / "observability"
    / "pre-cutover-watch-day-verdict.py"
)

_spec = importlib.util.spec_from_file_location(
    "pre_cutover_watch_day_verdict", str(_VERDICT_PATH)
)
assert _spec is not None and _spec.loader is not None
verdict_mod = importlib.util.module_from_spec(_spec)
sys.modules["pre_cutover_watch_day_verdict"] = verdict_mod
_spec.loader.exec_module(verdict_mod)


# ---------------------------------------------------------------------------
# Builders.
# ---------------------------------------------------------------------------

def _all_green_inputs():
    """Build a fully-green WatchDayInputs fixture."""
    return verdict_mod.WatchDayInputs(
        dashboards={d: True for d in verdict_mod.DASHBOARD_IDS},
        alert_groups={a: True for a in verdict_mod.ALERT_GROUP_IDS},
        probe_verdicts={"welle-1": "GREEN", "welle-2": "GREEN"},
        ci_gates={c: True for c in verdict_mod.CI_GATE_IDS},
        firing_slo_burn_rates=frozenset(),
        tomorrow_cutover_welles=frozenset({"welle-1", "welle-2"}),
    )


def _complete_journal_entry(slot: str, verdict: str | None = None):
    """Build a single spec-§10-valid journal entry."""
    return {
        "slot": slot,
        "timestamp_iso": f"2026-06-09T{slot}:00:00+02:00",
        "operator": "noa",
        "cutover_welle": ["welle-1", "welle-2"],
        "dashboards_pass_count": 10,
        "dashboards_fail_count": 0,
        "alerts_pass_count": 2,
        "alerts_fail_count": 0,
        "probes_pass_count": 2,
        "probes_fail_count": 0,
        "ci_gate_c1": "success",
        "ci_gate_c2": "success",
        "verdict": verdict,
        "notes": "",
    }


# ---------------------------------------------------------------------------
# 1. compute_verdict — happy path.
# ---------------------------------------------------------------------------

def test_all_green_inputs_yield_green_verdict():
    inputs = _all_green_inputs()
    assert verdict_mod.compute_verdict(inputs) == "GREEN"
    assert verdict_mod.red_blocker_reasons(inputs) == []


# ---------------------------------------------------------------------------
# 2. Dashboard failure -> AMBER (not RED).
# ---------------------------------------------------------------------------

def test_one_missing_dashboard_drops_to_amber():
    inputs = _all_green_inputs()
    dashboards = dict(inputs.dashboards)
    dashboards["D4"] = False
    inputs = verdict_mod.WatchDayInputs(
        dashboards=dashboards,
        alert_groups=inputs.alert_groups,
        probe_verdicts=inputs.probe_verdicts,
        ci_gates=inputs.ci_gates,
        firing_slo_burn_rates=inputs.firing_slo_burn_rates,
        tomorrow_cutover_welles=inputs.tomorrow_cutover_welles,
    )
    assert verdict_mod.compute_verdict(inputs) == "AMBER"
    assert verdict_mod.red_blocker_reasons(inputs) == []


# ---------------------------------------------------------------------------
# 3. AMBER probe -> AMBER verdict.
# ---------------------------------------------------------------------------

def test_amber_probe_drops_to_amber_not_red():
    inputs = _all_green_inputs()
    inputs = verdict_mod.WatchDayInputs(
        dashboards=inputs.dashboards,
        alert_groups=inputs.alert_groups,
        probe_verdicts={"welle-1": "AMBER", "welle-2": "GREEN"},
        ci_gates=inputs.ci_gates,
        firing_slo_burn_rates=inputs.firing_slo_burn_rates,
        tomorrow_cutover_welles=inputs.tomorrow_cutover_welles,
    )
    assert verdict_mod.compute_verdict(inputs) == "AMBER"
    assert verdict_mod.red_blocker_reasons(inputs) == []


# ---------------------------------------------------------------------------
# 4. RED probe -> RED verdict.
# ---------------------------------------------------------------------------

def test_red_probe_forces_red_verdict():
    inputs = _all_green_inputs()
    inputs = verdict_mod.WatchDayInputs(
        dashboards=inputs.dashboards,
        alert_groups=inputs.alert_groups,
        probe_verdicts={"welle-1": "RED", "welle-2": "GREEN"},
        ci_gates=inputs.ci_gates,
        firing_slo_burn_rates=inputs.firing_slo_burn_rates,
        tomorrow_cutover_welles=inputs.tomorrow_cutover_welles,
    )
    assert verdict_mod.compute_verdict(inputs) == "RED"
    reasons = verdict_mod.red_blocker_reasons(inputs)
    assert "probe-verdict-RED:welle-1" in reasons


# ---------------------------------------------------------------------------
# 5. Hard-zero SLO burn-rate -> RED with reason.
# ---------------------------------------------------------------------------

def test_hard_zero_slo_burn_forces_red_with_reason():
    inputs = _all_green_inputs()
    inputs = verdict_mod.WatchDayInputs(
        dashboards=inputs.dashboards,
        alert_groups=inputs.alert_groups,
        probe_verdicts=inputs.probe_verdicts,
        ci_gates=inputs.ci_gates,
        firing_slo_burn_rates=frozenset({"SLO-5"}),
        tomorrow_cutover_welles=inputs.tomorrow_cutover_welles,
    )
    assert verdict_mod.compute_verdict(inputs) == "RED"
    assert "hard-zero-slo-burn:SLO-5" in verdict_mod.red_blocker_reasons(
        inputs
    )


# ---------------------------------------------------------------------------
# 6. Welle SLO fast-burn with tomorrow-cutover -> RED.
# ---------------------------------------------------------------------------

def test_welle_slo_fast_burn_with_tomorrow_cutover_is_red():
    inputs = _all_green_inputs()
    inputs = verdict_mod.WatchDayInputs(
        dashboards=inputs.dashboards,
        alert_groups=inputs.alert_groups,
        probe_verdicts=inputs.probe_verdicts,
        ci_gates=inputs.ci_gates,
        firing_slo_burn_rates=frozenset({"SLO-1"}),
        tomorrow_cutover_welles=frozenset({"welle-1"}),
    )
    assert verdict_mod.compute_verdict(inputs) == "RED"
    assert any(
        r.startswith("welle-slo-fast-burn-with-tomorrow-cutover")
        for r in verdict_mod.red_blocker_reasons(inputs)
    )


# ---------------------------------------------------------------------------
# 7. Welle SLO fast-burn but NO tomorrow-cutover -> not RED.
# ---------------------------------------------------------------------------

def test_welle_slo_fast_burn_without_tomorrow_cutover_not_red():
    inputs = _all_green_inputs()
    inputs = verdict_mod.WatchDayInputs(
        dashboards=inputs.dashboards,
        alert_groups=inputs.alert_groups,
        probe_verdicts=inputs.probe_verdicts,
        ci_gates=inputs.ci_gates,
        firing_slo_burn_rates=frozenset({"SLO-1"}),
        tomorrow_cutover_welles=frozenset(),
    )
    # No tomorrow-cutover-Welle => SLO-1 fast-burn is not a RED
    # blocker, but it is also not GREEN (the SLO-1 condition for
    # GREEN requires no fast-burn even with no Welle).
    # Per spec §7 GREEN-conditions, SLO-1 fast-burn is only
    # checked relative to tomorrow-cutover-welles. With empty set
    # and no other GREEN-blockers violated, verdict is GREEN.
    assert verdict_mod.compute_verdict(inputs) == "GREEN"
    assert verdict_mod.red_blocker_reasons(inputs) == []


# ---------------------------------------------------------------------------
# 8. CI gate failure -> RED.
# ---------------------------------------------------------------------------

def test_ci_gate_failure_forces_red_with_reason():
    inputs = _all_green_inputs()
    inputs = verdict_mod.WatchDayInputs(
        dashboards=inputs.dashboards,
        alert_groups=inputs.alert_groups,
        probe_verdicts=inputs.probe_verdicts,
        ci_gates={"C1": True, "C2": False},
        firing_slo_burn_rates=inputs.firing_slo_burn_rates,
        tomorrow_cutover_welles=inputs.tomorrow_cutover_welles,
    )
    assert verdict_mod.compute_verdict(inputs) == "RED"
    assert "ci-gate-failed:C2" in verdict_mod.red_blocker_reasons(inputs)


# ---------------------------------------------------------------------------
# 9. Activation-checklist helpers.
# ---------------------------------------------------------------------------

def test_missing_dashboards_and_alert_groups_helpers():
    inputs = _all_green_inputs()
    dashboards = dict(inputs.dashboards)
    dashboards["D2"] = False
    dashboards["D9"] = False
    alert_groups = dict(inputs.alert_groups)
    alert_groups["A1"] = False
    inputs = verdict_mod.WatchDayInputs(
        dashboards=dashboards,
        alert_groups=alert_groups,
        probe_verdicts=inputs.probe_verdicts,
        ci_gates=inputs.ci_gates,
        firing_slo_burn_rates=inputs.firing_slo_burn_rates,
        tomorrow_cutover_welles=inputs.tomorrow_cutover_welles,
    )
    assert verdict_mod.missing_dashboards(inputs) == ["D2", "D9"]
    assert verdict_mod.missing_alert_groups(inputs) == ["A1"]


# ---------------------------------------------------------------------------
# 10. AMBER-probe helper.
# ---------------------------------------------------------------------------

def test_amber_probes_helper_returns_sorted_welle_ids():
    inputs = _all_green_inputs()
    inputs = verdict_mod.WatchDayInputs(
        dashboards=inputs.dashboards,
        alert_groups=inputs.alert_groups,
        probe_verdicts={
            "welle-3": "AMBER",
            "welle-1": "AMBER",
            "welle-2": "GREEN",
        },
        ci_gates=inputs.ci_gates,
        firing_slo_burn_rates=inputs.firing_slo_burn_rates,
        tomorrow_cutover_welles=inputs.tomorrow_cutover_welles,
    )
    assert verdict_mod.amber_probes(inputs) == ["welle-1", "welle-3"]


# ---------------------------------------------------------------------------
# 11. Journal-entry: complete slot=08 entry validates.
# ---------------------------------------------------------------------------

def test_validate_journal_entry_complete_slot_08_ok():
    entry = _complete_journal_entry("08", verdict=None)
    result = verdict_mod.validate_journal_entry(entry)
    assert result.ok, result.errors


# ---------------------------------------------------------------------------
# 12. Journal-entry: missing field.
# ---------------------------------------------------------------------------

def test_validate_journal_entry_missing_field_errors():
    entry = _complete_journal_entry("08", verdict=None)
    del entry["operator"]
    result = verdict_mod.validate_journal_entry(entry)
    assert not result.ok
    assert "missing-field:operator" in result.errors


# ---------------------------------------------------------------------------
# 13. Journal-entry: slot=16 requires verdict.
# ---------------------------------------------------------------------------

def test_validate_journal_entry_verdict_required_at_slot_16():
    entry = _complete_journal_entry("16", verdict=None)
    result = verdict_mod.validate_journal_entry(entry)
    assert not result.ok
    assert any("verdict-required-for-slot-16" in e for e in result.errors)


# ---------------------------------------------------------------------------
# 14. Journal-entry: slot=08 forbids verdict.
# ---------------------------------------------------------------------------

def test_validate_journal_entry_verdict_must_be_null_at_slot_08():
    entry = _complete_journal_entry("08", verdict="GREEN")
    result = verdict_mod.validate_journal_entry(entry)
    assert not result.ok
    assert any("verdict-must-be-null-for-slot-08" in e for e in result.errors)


# ---------------------------------------------------------------------------
# 15. Journal-sequence: full day validates.
# ---------------------------------------------------------------------------

def test_validate_journal_sequence_full_day_ok():
    entries = [
        _complete_journal_entry("08"),
        _complete_journal_entry("10"),
        _complete_journal_entry("12"),
        _complete_journal_entry("14"),
        _complete_journal_entry("16", verdict="GREEN"),
        _complete_journal_entry("18", verdict="GREEN"),
    ]
    result = verdict_mod.validate_journal_sequence(entries)
    assert result.ok, result.errors


# ---------------------------------------------------------------------------
# 16. Journal-sequence: slot=18 must re-confirm slot=16 verdict.
# ---------------------------------------------------------------------------

def test_validate_journal_sequence_verdict_reconfirmation_mismatch():
    entries = [
        _complete_journal_entry("08"),
        _complete_journal_entry("10"),
        _complete_journal_entry("12"),
        _complete_journal_entry("14"),
        _complete_journal_entry("16", verdict="GREEN"),
        _complete_journal_entry("18", verdict="AMBER"),
    ]
    result = verdict_mod.validate_journal_sequence(entries)
    assert not result.ok
    assert any(
        "verdict-reconfirmation-mismatch" in e for e in result.errors
    )


# ---------------------------------------------------------------------------
# 17. Severity-class lookup: known triggers.
# ---------------------------------------------------------------------------

def test_severity_class_lookup_known_triggers():
    assert verdict_mod.severity_class_for("watch-day-verdict-red") == "P"
    assert verdict_mod.severity_class_for("ar-hand-stop-invoked") == "P"
    assert verdict_mod.severity_class_for("hard-zero-slo-breach") == "P"
    assert verdict_mod.severity_class_for("drift-type-a-kai-domain") == "T"
    assert verdict_mod.severity_class_for("wat-pipeline-regression") == "T"


# ---------------------------------------------------------------------------
# 18. Severity-class lookup: unknown trigger -> KeyError (closed set).
# ---------------------------------------------------------------------------

def test_severity_class_lookup_unknown_trigger_raises():
    with pytest.raises(KeyError):
        verdict_mod.severity_class_for("page-everyone-on-vibes")


# ---------------------------------------------------------------------------
# 19. Red-blocker reason ordering is stable.
# ---------------------------------------------------------------------------

def test_red_blocker_reasons_are_sorted_and_stable():
    inputs = verdict_mod.WatchDayInputs(
        dashboards={d: True for d in verdict_mod.DASHBOARD_IDS},
        alert_groups={a: True for a in verdict_mod.ALERT_GROUP_IDS},
        probe_verdicts={
            "welle-3": "RED",
            "welle-1": "RED",
            "welle-2": "RED",
        },
        ci_gates={"C1": False, "C2": False},
        firing_slo_burn_rates=frozenset({"SLO-7", "SLO-2"}),
        tomorrow_cutover_welles=frozenset({"welle-1"}),
    )
    reasons = verdict_mod.red_blocker_reasons(inputs)
    # Probe-reasons sorted lexicographically.
    probe_reasons = [r for r in reasons if r.startswith("probe-verdict-RED")]
    assert probe_reasons == [
        "probe-verdict-RED:welle-1",
        "probe-verdict-RED:welle-2",
        "probe-verdict-RED:welle-3",
    ]
    # Hard-zero SLO reasons sorted.
    slo_reasons = [r for r in reasons if r.startswith("hard-zero-slo-burn")]
    assert slo_reasons == [
        "hard-zero-slo-burn:SLO-2",
        "hard-zero-slo-burn:SLO-7",
    ]
    # CI-gate reasons sorted.
    ci_reasons = [r for r in reasons if r.startswith("ci-gate-failed")]
    assert ci_reasons == [
        "ci-gate-failed:C1",
        "ci-gate-failed:C2",
    ]


# ---------------------------------------------------------------------------
# 20. CLI: writes the verdict file for GREEN inputs.
# ---------------------------------------------------------------------------

def test_cli_writes_verdict_file_for_green_inputs(tmp_path):
    inputs_payload = {
        "dashboards": {d: True for d in verdict_mod.DASHBOARD_IDS},
        "alert_groups": {a: True for a in verdict_mod.ALERT_GROUP_IDS},
        "probe_verdicts": {"welle-1": "GREEN", "welle-2": "GREEN"},
        "ci_gates": {"C1": True, "C2": True},
        "firing_slo_burn_rates": [],
        "tomorrow_cutover_welles": ["welle-1", "welle-2"],
    }
    inputs_file = tmp_path / "inputs.json"
    inputs_file.write_text(json.dumps(inputs_payload), encoding="utf-8")
    verdict_file = tmp_path / "verdict.txt"

    rc = verdict_mod.main(
        ["--inputs", str(inputs_file), "--out-verdict", str(verdict_file)]
    )
    assert rc == 0
    assert verdict_file.read_text(encoding="utf-8").strip() == "GREEN"
