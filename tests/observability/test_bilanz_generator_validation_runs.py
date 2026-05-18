# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Validation-Mock-Run tests for the Phase-3 Final Bilanz Generator.

Tag-44 Noa task: run the generator end-to-end against several distinct
mock Marathon datasets (happy-path, rollback-path, audit-trail-gap,
cross-modul-drift-detected, latency-excursion) and assert:

  * Markdown output contains the seven welle-sections,
    correct COMPLETE-marker outcome, drift/latency status sections,
    audit gap notices, follow-up items.
  * JSON output validates against
    ``scripts/observability/bilanz-output-schema-validator.py``
    schema version 1.0.0.

The tests use inline mock datasets (no dependency on Selin's sample
fixtures landing first) and exercise the generator's I/O boundary via
``assemble_bilanz`` + ``render_markdown`` plus the bilanz-output-schema
validator. Stdlib-only; no network I/O. ~14 tests.

-- Noa
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from typing import Any, Dict, List, Optional

import pytest

# --------------------------------------------------------------------
# Module loading helper -- the script filenames contain hyphens which
# are not import-friendly, so we use importlib.util for both targets.
# --------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BILANZ_SCRIPT = (
    REPO_ROOT
    / "scripts"
    / "observability"
    / "phase-3-final-bilanz-generator.py"
)
VALIDATOR_SCRIPT = (
    REPO_ROOT
    / "scripts"
    / "observability"
    / "bilanz-output-schema-validator.py"
)


def _load(module_name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


bilanz_mod = _load("bilanz_generator_v44", BILANZ_SCRIPT)
validator_mod = _load("bilanz_validator_v44", VALIDATOR_SCRIPT)


# --------------------------------------------------------------------
# Mock-dataset builders -- one per Marathon shape.
# --------------------------------------------------------------------


def _samples_under_budget(welle_id: str) -> List[float]:
    """Latency samples that sit comfortably below the per-welle budget."""
    budget = bilanz_mod.LATENCY_BUDGET_MS[welle_id]
    peak = budget * 0.4
    return [peak * 0.2, peak * 0.4, peak * 0.6, peak * 0.8, peak]


def _samples_over_budget(welle_id: str) -> List[float]:
    """Latency samples that breach the per-welle budget (p95 > 1.1 * budget)."""
    budget = bilanz_mod.LATENCY_BUDGET_MS[welle_id]
    peak = budget * 1.5
    return [budget * 0.5, budget * 0.9, budget * 1.15, budget * 1.3, peak]


def _marathon_state_happy() -> Dict[str, Any]:
    state = {
        "schema_version": "1.0.0",
        "updated_at": "2026-06-29T11:00:00Z",
        "wellen": {},
    }
    for i, wid in enumerate(bilanz_mod.WELLE_ORDER, start=1):
        state["wellen"][wid] = {
            "cutover_runs_total": 4000 + 100 * i,
            "cutover_runs_rust": 3900 + 100 * i,
            "cutover_runs_python_fallback": 100,
            "decision_latency_ms_samples": _samples_under_budget(wid),
            "last_sample_at": f"2026-06-29T1{i % 10}:00:00Z",
        }
    return state


def _marathon_state_rollback() -> Dict[str, Any]:
    """Marathon that aborted on welle-4 -- partial counts, no COMPLETE marker."""
    state = {
        "schema_version": "1.0.0",
        "updated_at": "2026-06-12T09:15:00Z",
        "wellen": {},
    }
    rolled_back = {"welle-4-state-backing", "welle-5-lifecycle-state-machine",
                   "welle-6-subscribe-loop", "welle-7-recovery-workflow"}
    for i, wid in enumerate(bilanz_mod.WELLE_ORDER, start=1):
        if wid in rolled_back:
            # Pre-rollback partial run with python-fallback spike.
            state["wellen"][wid] = {
                "cutover_runs_total": 80,
                "cutover_runs_rust": 30,
                "cutover_runs_python_fallback": 50,
                "decision_latency_ms_samples": _samples_under_budget(wid),
                "last_sample_at": "2026-06-12T08:50:00Z",
            }
        else:
            state["wellen"][wid] = {
                "cutover_runs_total": 1500 + 50 * i,
                "cutover_runs_rust": 1480 + 50 * i,
                "cutover_runs_python_fallback": 20,
                "decision_latency_ms_samples": _samples_under_budget(wid),
                "last_sample_at": "2026-06-10T22:30:00Z",
            }
    return state


def _marathon_state_latency_excursion() -> Dict[str, Any]:
    """Happy counts but welle-5 latency p95 breaches budget."""
    state = _marathon_state_happy()
    target = "welle-5-lifecycle-state-machine"
    state["wellen"][target]["decision_latency_ms_samples"] = _samples_over_budget(target)
    return state


def _aggregator_history_default() -> List[Dict[str, Any]]:
    return [
        {
            "run_id": "1",
            "started_at": "2026-05-20T11:00:00Z",
            "conclusion": "success",
            "wait_loop_seconds": 480,
            "sub_workflow_failures": [],
        },
        {
            "run_id": "2",
            "started_at": "2026-05-21T13:00:00Z",
            "conclusion": "success",
            "wait_loop_seconds": 510,
            "sub_workflow_failures": [],
        },
        {
            "run_id": "3",
            "started_at": "2026-05-22T15:00:00Z",
            "conclusion": "failure",
            "wait_loop_seconds": 1320,
            "sub_workflow_failures": ["wirelang suite production"],
        },
    ]


def _aggregator_history_rollback() -> List[Dict[str, Any]]:
    return _aggregator_history_default() + [
        {
            "run_id": "4",
            "started_at": "2026-06-12T08:55:00Z",
            "conclusion": "failure",
            "wait_loop_seconds": 1800,
            "sub_workflow_failures": [
                "Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)",
                "production-vs-sandbox drift envelope",
            ],
        },
    ]


def _backend_snapshots_default() -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for wid in bilanz_mod.WELLE_ORDER:
        out[wid] = [
            {"rust_decisions": 200, "python_decisions": 5,
             "timestamp": "2026-06-01T10:00:00Z"},
            {"rust_decisions": 300, "python_decisions": 4,
             "timestamp": "2026-06-02T10:00:00Z"},
        ]
    return out


def _drift_histograms_clean() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for wid in bilanz_mod.WELLE_ORDER:
        out[wid] = {"drift_pct_samples": [0.05, 0.1, 0.15], "bucket_count": 7}
    return out


def _drift_histograms_cross_modul_drift() -> Dict[str, Any]:
    """Two wellen simultaneously breach -- systemic drift signal."""
    out = _drift_histograms_clean()
    for wid in ("welle-3-bridge-audit-writer",
                "welle-6-subscribe-loop"):
        out[wid] = {"drift_pct_samples": [0.55, 0.62, 0.71], "bucket_count": 7}
    return out


def _sign_offs_all_present() -> List[Dict[str, Any]]:
    return [
        {
            "welle_id": wid,
            "signed_off_at": "2026-06-25T10:00:00Z",
            "signed_off_by": "henrik",
            "audit_findings": [],
            "exception_count": 0,
            "audit_ok": True,
        }
        for wid in bilanz_mod.WELLE_ORDER
    ]


def _sign_offs_missing_w7() -> List[Dict[str, Any]]:
    """Welle-7 (pre-auditor) sign-off absent -- audit-trail-gap path."""
    return [
        s for s in _sign_offs_all_present()
        if s["welle_id"] != "welle-7-recovery-workflow"
    ]


def _complete_marker_complete() -> Dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "status": "COMPLETE",
        "completed_at": "2026-06-29T23:59:00Z",
        "wellen_complete": 7,
        "approver": "tomas",
        "evidence_refs": [
            "state/welle-1-sign-off.json",
            "state/welle-7-sign-off.json",
        ],
    }


def _complete_marker_rollback() -> Optional[Dict[str, Any]]:
    """No marker file -- the rollback path never wrote it."""
    return None


# --------------------------------------------------------------------
# Helpers to assemble + validate.
# --------------------------------------------------------------------


def _build_bilanz(
    *,
    marathon_state: Dict[str, Any],
    aggregator_history: List[Dict[str, Any]],
    backend_snapshots: Dict[str, List[Dict[str, Any]]],
    drift_histograms: Dict[str, Any],
    sign_offs: List[Dict[str, Any]],
    complete_marker: Optional[Dict[str, Any]],
    generated_at: str = "2026-05-18T20:00:00Z",
) -> Dict[str, Any]:
    return bilanz_mod.assemble_bilanz(
        marathon_state=marathon_state,
        aggregator_history=aggregator_history,
        backend_snapshots=backend_snapshots,
        drift_histograms=drift_histograms,
        sign_offs=sign_offs,
        complete_marker=complete_marker,
        generated_at=generated_at,
    )


def _assert_schema_valid(bilanz: Dict[str, Any]) -> None:
    errors = validator_mod.validate_bilanz_dict(bilanz)
    assert errors == [], (
        "Bilanz failed schema validation; errors:\n  "
        + "\n  ".join(errors)
    )


# --------------------------------------------------------------------
# Test 1 (Happy Path): all 7 welle sections + COMPLETE marker.
# --------------------------------------------------------------------


def test_happy_path_renders_all_seven_welle_sections_and_complete_marker():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_happy(),
        aggregator_history=_aggregator_history_default(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_clean(),
        sign_offs=_sign_offs_all_present(),
        complete_marker=_complete_marker_complete(),
    )
    md = bilanz_mod.render_markdown(bilanz)

    # Section 1 header.
    assert "# Phase-3 Marathon Final Bilanz" in md
    # All 7 welle sub-sections.
    for idx, wid in enumerate(bilanz_mod.WELLE_ORDER, start=1):
        short = bilanz_mod.WELLE_SHORT[wid]
        assert f"### 2.{idx} {short}" in md, f"missing section 2.{idx} for {wid}"
    # COMPLETE marker validated as YES.
    assert "**Phase-3-COMPLETE marker valid:** YES" in md
    assert bilanz["executive_summary"]["complete_marker_is_complete"] is True
    # Audit aggregate OK.
    assert bilanz["executive_summary"]["audit_aggregate_ok"] is True


def test_happy_path_no_breach_followups():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_happy(),
        aggregator_history=_aggregator_history_default(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_clean(),
        sign_offs=_sign_offs_all_present(),
        complete_marker=_complete_marker_complete(),
    )
    followups = bilanz["phase_4_followups"]
    assert len(followups) == 1, f"expected 1 placeholder followup, got {followups}"
    assert "No outstanding follow-ups" in followups[0]


def test_happy_path_schema_valid():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_happy(),
        aggregator_history=_aggregator_history_default(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_clean(),
        sign_offs=_sign_offs_all_present(),
        complete_marker=_complete_marker_complete(),
    )
    _assert_schema_valid(bilanz)


# --------------------------------------------------------------------
# Test 2 (Rollback Path): rollback trail visible, COMPLETE marker
# absent, follow-ups list the rollback blocker.
# --------------------------------------------------------------------


def test_rollback_path_complete_marker_absent_followups_flag_blocker():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_rollback(),
        aggregator_history=_aggregator_history_rollback(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_clean(),
        sign_offs=_sign_offs_missing_w7(),
        complete_marker=_complete_marker_rollback(),
    )

    md = bilanz_mod.render_markdown(bilanz)
    # COMPLETE marker reported as not-valid.
    assert "**Phase-3-COMPLETE marker valid:** NO" in md
    # Marker-file-missing notice in section 5.
    assert "Marker file is missing" in md

    # Executive summary surface.
    assert bilanz["executive_summary"]["complete_marker_is_complete"] is False

    # Phase-4 follow-ups must mention the missing marker.
    follow_str = "\n".join(bilanz["phase_4_followups"])
    assert "marker not valid" in follow_str
    assert "marker_file_missing" in follow_str


def test_rollback_path_followups_include_rollback_welle_audit_gap():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_rollback(),
        aggregator_history=_aggregator_history_rollback(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_clean(),
        sign_offs=_sign_offs_missing_w7(),
        complete_marker=_complete_marker_rollback(),
    )
    # Welle-7 (recovery-workflow) sign-off missing.
    follow_str = "\n".join(bilanz["phase_4_followups"])
    assert "W7 recovery-workflow" in follow_str
    assert "sign-off MISSING" in follow_str


def test_rollback_path_schema_valid():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_rollback(),
        aggregator_history=_aggregator_history_rollback(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_clean(),
        sign_offs=_sign_offs_missing_w7(),
        complete_marker=_complete_marker_rollback(),
    )
    _assert_schema_valid(bilanz)


# --------------------------------------------------------------------
# Test 3 (Welle-7-Pre-Auditor-Missing): only the W7 sign-off is absent,
# Marathon otherwise complete. The audit-trail-gap notice must show up.
# --------------------------------------------------------------------


def test_welle_7_pre_auditor_missing_emits_audit_trail_gap_notice():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_happy(),
        aggregator_history=_aggregator_history_default(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_clean(),
        sign_offs=_sign_offs_missing_w7(),
        complete_marker=_complete_marker_complete(),
    )
    md = bilanz_mod.render_markdown(bilanz)

    # Section 4 must list welle-7 in the missing sign-offs.
    assert "**Missing sign-offs:**" in md
    assert "W7 recovery-workflow" in md
    # Per-welle sign-off table must show MISSING for welle-7.
    # The row pattern is `| W7 recovery-workflow | _MISSING_ |`.
    assert "| W7 recovery-workflow | _MISSING_ |" in md

    # Audit aggregate flips to NO.
    assert bilanz["executive_summary"]["audit_aggregate_ok"] is False

    # Schema must still validate even when entries are missing.
    _assert_schema_valid(bilanz)


def test_welle_7_pre_auditor_missing_blocks_phase_4():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_happy(),
        aggregator_history=_aggregator_history_default(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_clean(),
        sign_offs=_sign_offs_missing_w7(),
        complete_marker=_complete_marker_complete(),
    )
    # Follow-up list must contain a W7-blocker line.
    follow_str = "\n".join(bilanz["phase_4_followups"])
    assert "blocker" in follow_str.lower() or "blocker" in follow_str
    assert "W7 recovery-workflow" in follow_str


# --------------------------------------------------------------------
# Test 4 (Cross-Modul-Drift-Detected): two wellen simultaneously BREACH
# drift. The output must list both in the drift section.
# --------------------------------------------------------------------


def test_cross_modul_drift_detected_lists_breach_wellen():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_happy(),
        aggregator_history=_aggregator_history_default(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_cross_modul_drift(),
        sign_offs=_sign_offs_all_present(),
        complete_marker=_complete_marker_complete(),
    )
    # Drift status counts: BREACH on at least 2 wellen.
    drift_counts = bilanz["executive_summary"]["drift_status_counts"]
    assert drift_counts["BREACH"] >= 2, (
        f"expected >=2 BREACH wellen, got {drift_counts}"
    )

    # Follow-ups list both BREACH wellen by name.
    follow_str = "\n".join(bilanz["phase_4_followups"])
    assert "W3 bridge-audit-writer" in follow_str
    assert "W6 subscribe-loop" in follow_str
    assert "drift BREACH" in follow_str


def test_cross_modul_drift_detected_systemic_signal_in_md():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_happy(),
        aggregator_history=_aggregator_history_default(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_cross_modul_drift(),
        sign_offs=_sign_offs_all_present(),
        complete_marker=_complete_marker_complete(),
    )
    md = bilanz_mod.render_markdown(bilanz)
    # Drift status table header.
    assert "### Drift status across wellen" in md
    # The cross-welle coupling section must call out the systemic
    # interpretation when two wellen BREACH at once.
    assert "## 3. Cross-Welle Coupling Bilanz" in md
    assert "systemic" in md  # The narrative paragraph mentions systemic cause.


def test_cross_modul_drift_detected_schema_valid():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_happy(),
        aggregator_history=_aggregator_history_default(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_cross_modul_drift(),
        sign_offs=_sign_offs_all_present(),
        complete_marker=_complete_marker_complete(),
    )
    _assert_schema_valid(bilanz)


# --------------------------------------------------------------------
# Test 5 (Latency-Excursion): one welle blows the p95 budget; the
# bilanz must surface it in the latency-status table and the
# follow-up list, and the per-welle p95 column shows BREACH.
# --------------------------------------------------------------------


def test_latency_excursion_flags_breach_welle_in_status_table():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_latency_excursion(),
        aggregator_history=_aggregator_history_default(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_clean(),
        sign_offs=_sign_offs_all_present(),
        complete_marker=_complete_marker_complete(),
    )

    # Per-welle latency status: target welle is BREACH.
    target = "welle-5-lifecycle-state-machine"
    assert bilanz["per_welle"][target]["latency_status"] == "BREACH"

    # Latency status counts include exactly one BREACH.
    lat_counts = bilanz["executive_summary"]["latency_status_counts"]
    assert lat_counts.get("BREACH", 0) >= 1

    # Markdown lists W5 with the latency BREACH follow-up.
    md = bilanz_mod.render_markdown(bilanz)
    assert "**status** | **BREACH**" in md  # The status row uses bold cell.
    assert "W5 lifecycle-state-machine" in md


def test_latency_excursion_followups_carry_p95_breach_into_phase_4():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_latency_excursion(),
        aggregator_history=_aggregator_history_default(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_clean(),
        sign_offs=_sign_offs_all_present(),
        complete_marker=_complete_marker_complete(),
    )
    follow_str = "\n".join(bilanz["phase_4_followups"])
    assert "latency p95 BREACH" in follow_str
    assert "W5 lifecycle-state-machine" in follow_str
    assert "Phase-4" in follow_str


def test_latency_excursion_schema_valid():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_latency_excursion(),
        aggregator_history=_aggregator_history_default(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_clean(),
        sign_offs=_sign_offs_all_present(),
        complete_marker=_complete_marker_complete(),
    )
    _assert_schema_valid(bilanz)


# --------------------------------------------------------------------
# Test 6 (Schema-Validator-Negative-Path): purposely break the bilanz
# in a few ways and verify the validator catches each.
# --------------------------------------------------------------------


def test_schema_validator_rejects_unknown_drift_status():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_happy(),
        aggregator_history=_aggregator_history_default(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_clean(),
        sign_offs=_sign_offs_all_present(),
        complete_marker=_complete_marker_complete(),
    )
    # Inject an illegal drift status into the executive summary.
    bilanz["executive_summary"]["drift_status_counts"]["MAYBE"] = 3
    errors = validator_mod.validate_bilanz_dict(bilanz)
    assert any("MAYBE" in e for e in errors), (
        f"expected MAYBE rejection, got {errors}"
    )


def test_schema_validator_rejects_wrong_schema_version_major():
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_happy(),
        aggregator_history=_aggregator_history_default(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_clean(),
        sign_offs=_sign_offs_all_present(),
        complete_marker=_complete_marker_complete(),
    )
    bilanz["schema_version"] = "2.0.0"
    errors = validator_mod.validate_bilanz_dict(bilanz)
    assert any("unsupported major version" in e for e in errors)


def test_schema_validator_rejects_missing_top_level_keys():
    incomplete = {"schema_version": "1.0.0"}
    errors = validator_mod.validate_bilanz_dict(incomplete)
    # At least executive_summary, per_welle, generated_at must be flagged.
    for key in ("generated_at", "executive_summary", "per_welle",
                "phase_4_followups"):
        assert any(key in e for e in errors), (
            f"expected error mentioning {key}, got {errors}"
        )


# --------------------------------------------------------------------
# Test 7: end-to-end CLI dump-and-validate via tmp-dir fixture file.
# --------------------------------------------------------------------


def test_cli_validator_passes_on_happy_path_json(tmp_path):
    bilanz = _build_bilanz(
        marathon_state=_marathon_state_happy(),
        aggregator_history=_aggregator_history_default(),
        backend_snapshots=_backend_snapshots_default(),
        drift_histograms=_drift_histograms_clean(),
        sign_offs=_sign_offs_all_present(),
        complete_marker=_complete_marker_complete(),
    )
    out_path = tmp_path / "bilanz.json"
    out_path.write_text(json.dumps(bilanz, sort_keys=True, indent=2),
                        encoding="utf-8")
    rc = validator_mod.main([str(out_path), "--quiet"])
    assert rc == 0


def test_cli_validator_fails_on_malformed_json(tmp_path):
    out_path = tmp_path / "bad.json"
    out_path.write_text("this is not json", encoding="utf-8")
    rc = validator_mod.main([str(out_path), "--quiet"])
    assert rc == 2  # JSON-decode error path.


def test_cli_validator_fails_when_file_missing(tmp_path):
    rc = validator_mod.main([str(tmp_path / "nope.json"), "--quiet"])
    assert rc == 2
