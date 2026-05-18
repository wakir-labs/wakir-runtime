# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/observability/phase-3-final-bilanz-generator.py``.

The tests load the script via ``importlib.util`` because the file name
contains hyphens which are not import-friendly. Every test operates on
pure-function inputs (parsed dicts / lists) or on temp-dir fixtures;
no network I/O.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
from typing import Any, Dict, List

import pytest

# --------------------------------------------------------------------
# Module loading
# --------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT_PATH = (
    REPO_ROOT
    / "scripts"
    / "observability"
    / "phase-3-final-bilanz-generator.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "phase_3_final_bilanz_generator", str(SCRIPT_PATH)
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["phase_3_final_bilanz_generator"] = mod
    spec.loader.exec_module(mod)
    return mod


bilanz_mod = _load_module()


# --------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------


def _marathon_state_fixture() -> Dict[str, Any]:
    """All seven wellen present with non-trivial samples.

    Latency samples are deliberately kept well below the per-welle p95
    budget (LATENCY_BUDGET_MS) so the happy-path bilanz registers all
    wellen as latency_status == OK.
    """
    base = {
        "schema_version": "1.0.0",
        "updated_at": "2026-06-29T11:00:00Z",
        "wellen": {},
    }
    for i, wid in enumerate(bilanz_mod.WELLE_ORDER, start=1):
        budget = bilanz_mod.LATENCY_BUDGET_MS[wid]
        # Samples cap at 0.5 * budget so p95 stays comfortably OK.
        peak = budget * 0.5
        base["wellen"][wid] = {
            "cutover_runs_total": 1000 * i,
            "cutover_runs_rust": 990 * i,
            "cutover_runs_python_fallback": 10 * i,
            "decision_latency_ms_samples": [
                peak * 0.25,
                peak * 0.5,
                peak * 0.75,
                peak,
            ],
            "last_sample_at": f"2026-06-2{i % 10}T12:00:00Z",
        }
    return base


def _aggregator_history_fixture() -> List[Dict[str, Any]]:
    return [
        {
            "run_id": "1",
            "started_at": "2026-05-20T11:00:00Z",
            "conclusion": "success",
            "wait_loop_seconds": 600,
            "sub_workflow_failures": [],
        },
        {
            "run_id": "2",
            "started_at": "2026-05-20T12:00:00Z",
            "conclusion": "failure",
            "wait_loop_seconds": 1200,
            "sub_workflow_failures": ["wirelang suite production"],
        },
        {
            "run_id": "3",
            "started_at": "2026-05-21T11:00:00Z",
            "conclusion": "success",
            "wait_loop_seconds": 700,
            "sub_workflow_failures": [],
        },
    ]


def _backend_snapshots_fixture() -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for wid in bilanz_mod.WELLE_ORDER:
        out[wid] = [
            {
                "rust_decisions": 100,
                "python_decisions": 5,
                "timestamp": "2026-06-01T10:00:00Z",
            },
            {
                "rust_decisions": 150,
                "python_decisions": 3,
                "timestamp": "2026-06-02T10:00:00Z",
            },
        ]
    return out


def _drift_histograms_fixture(
    *,
    breach_welle: str = "",
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for wid in bilanz_mod.WELLE_ORDER:
        if wid == breach_welle:
            samples = [0.6, 0.7, 0.8]  # > 0.5 % budget
        else:
            samples = [0.05, 0.1, 0.2]
        out[wid] = {"drift_pct_samples": samples, "bucket_count": 7}
    return out


def _sign_offs_fixture(missing: List[str] = None) -> List[Dict[str, Any]]:
    missing = missing or []
    out: List[Dict[str, Any]] = []
    for wid in bilanz_mod.WELLE_ORDER:
        if wid in missing:
            continue
        out.append(
            {
                "welle_id": wid,
                "signed_off_at": "2026-06-15T10:00:00Z",
                "signed_off_by": "henrik",
                "audit_findings": [],
                "exception_count": 0,
                "audit_ok": True,
            }
        )
    return out


def _complete_marker_fixture(
    *, status: str = "COMPLETE", wellen_complete: int = 7
) -> Dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "status": status,
        "completed_at": "2026-06-29T23:59:00Z",
        "wellen_complete": wellen_complete,
        "approver": "tomas",
        "evidence_refs": ["state/welle-1-sign-off.json"],
    }


# --------------------------------------------------------------------
# Test 1: percentile helper handles n=0, n=1, n>=2.
# --------------------------------------------------------------------


def test_percentile_empty_returns_none():
    assert bilanz_mod.percentile([], 50.0) is None


def test_percentile_single_value():
    assert bilanz_mod.percentile([42.0], 95.0) == 42.0


def test_percentile_p0_p100_match_min_max():
    samples = [1.0, 4.0, 2.0, 3.0]
    assert bilanz_mod.percentile(samples, 0.0) == 1.0
    assert bilanz_mod.percentile(samples, 100.0) == 4.0


def test_percentile_median_of_four_samples():
    # p50 of [1,2,3,4] (inclusive linear interp): rank=1.5 -> 2.5
    assert bilanz_mod.percentile([1.0, 2.0, 3.0, 4.0], 50.0) == pytest.approx(2.5)


def test_percentile_rejects_invalid_pct():
    with pytest.raises(ValueError):
        bilanz_mod.percentile([1.0, 2.0], -1.0)
    with pytest.raises(ValueError):
        bilanz_mod.percentile([1.0, 2.0], 101.0)


# --------------------------------------------------------------------
# Test 2: latency status thresholds.
# --------------------------------------------------------------------


def test_latency_status_ok_warn_breach():
    wid = "welle-1-v907-verify"  # budget 1500 ms
    assert bilanz_mod.latency_status(wid, 100.0) == "OK"
    assert bilanz_mod.latency_status(wid, 1400.0) == "WARN"  # > 0.9 * 1500
    assert bilanz_mod.latency_status(wid, 1700.0) == "BREACH"  # > 1.1 * 1500
    assert bilanz_mod.latency_status(wid, None) == "NO_DATA"


def test_latency_status_unknown_welle_no_budget():
    assert bilanz_mod.latency_status("not-a-welle", 100.0) == "NO_BUDGET"


def test_drift_status_thresholds():
    assert bilanz_mod.drift_status(None) == "NO_DATA"
    assert bilanz_mod.drift_status(0.1) == "OK"
    assert bilanz_mod.drift_status(0.45) == "WARN"  # > 0.8 * 0.5 = 0.4
    assert bilanz_mod.drift_status(0.6) == "BREACH"


# --------------------------------------------------------------------
# Test 3: normalize marathon state preserves all 7 wellen.
# --------------------------------------------------------------------


def test_normalize_marathon_state_emits_seven_wellen():
    norm = bilanz_mod.normalize_marathon_state(_marathon_state_fixture())
    assert set(norm["wellen"].keys()) == set(bilanz_mod.WELLE_ORDER)
    for wid, w in norm["wellen"].items():
        assert w["cutover_runs_total"] > 0
        assert w["rust_share"] is not None
        assert w["decision_latency_ms_p95"] is not None


def test_normalize_marathon_state_tolerates_missing_welle():
    state = {"schema_version": "1.0.0", "wellen": {}}
    norm = bilanz_mod.normalize_marathon_state(state)
    for wid in bilanz_mod.WELLE_ORDER:
        w = norm["wellen"][wid]
        assert w["cutover_runs_total"] == 0
        assert w["rust_share"] is None
        assert w["decision_latency_ms_p95"] is None


# --------------------------------------------------------------------
# Test 4: aggregator history rollup.
# --------------------------------------------------------------------


def test_aggregator_history_rollup_counts():
    ag = bilanz_mod.normalize_aggregator_history(_aggregator_history_fixture())
    assert ag["runs_total"] == 3
    assert ag["runs_success"] == 2
    assert ag["runs_failure"] == 1
    assert ag["failure_rate"] == pytest.approx(1.0 / 3.0)
    assert ag["sub_workflow_failure_buckets"]["wirelang suite production"] == 1


def test_aggregator_history_empty_safe():
    ag = bilanz_mod.normalize_aggregator_history([])
    assert ag["runs_total"] == 0
    assert ag["failure_rate"] is None
    assert ag["wait_loop_p95_s"] is None


# --------------------------------------------------------------------
# Test 5: backend-snapshot rollup.
# --------------------------------------------------------------------


def test_backend_snapshots_rollup_rust_share():
    bs = bilanz_mod.normalize_backend_decision_snapshots(_backend_snapshots_fixture())
    for wid in bilanz_mod.WELLE_ORDER:
        entry = bs[wid]
        assert entry["snapshots_n"] == 2
        assert entry["rust_decisions_total"] == 250
        assert entry["python_decisions_total"] == 8
        assert entry["rust_share"] == pytest.approx(250.0 / 258.0)


# --------------------------------------------------------------------
# Test 6: drift histogram surfaces breach.
# --------------------------------------------------------------------


def test_drift_histogram_flags_breach_welle():
    dh = bilanz_mod.normalize_drift_histograms(
        _drift_histograms_fixture(breach_welle="welle-3-bridge-audit-writer")
    )
    assert dh["welle-3-bridge-audit-writer"]["drift_status"] == "BREACH"
    assert dh["welle-1-v907-verify"]["drift_status"] == "OK"


# --------------------------------------------------------------------
# Test 7: sign-off aggregation flags missing.
# --------------------------------------------------------------------


def test_sign_offs_missing_listed():
    so = bilanz_mod.normalize_sign_offs(
        _sign_offs_fixture(missing=["welle-7-recovery-workflow"])
    )
    assert "welle-7-recovery-workflow" in so["missing_sign_offs"]
    assert so["aggregate_audit_ok"] is False
    assert len(so["by_welle"]) == 6


def test_sign_offs_all_present_audit_ok():
    so = bilanz_mod.normalize_sign_offs(_sign_offs_fixture())
    assert so["missing_sign_offs"] == []
    assert so["aggregate_audit_ok"] is True
    assert so["total_exceptions"] == 0


# --------------------------------------------------------------------
# Test 8: complete marker validation.
# --------------------------------------------------------------------


def test_complete_marker_valid():
    cm = bilanz_mod.validate_complete_marker(_complete_marker_fixture())
    assert cm["is_complete"] is True
    assert cm["validation_errors"] == []


def test_complete_marker_missing():
    cm = bilanz_mod.validate_complete_marker(None)
    assert cm["present"] is False
    assert cm["is_complete"] is False
    assert "marker_file_missing" in cm["validation_errors"]


def test_complete_marker_partial_wellen():
    cm = bilanz_mod.validate_complete_marker(
        _complete_marker_fixture(wellen_complete=5)
    )
    assert cm["is_complete"] is False
    assert any("wellen_complete_expected_7" in e for e in cm["validation_errors"])


def test_complete_marker_not_complete_status():
    cm = bilanz_mod.validate_complete_marker(
        _complete_marker_fixture(status="IN_PROGRESS")
    )
    assert cm["is_complete"] is False
    assert any("status_not_complete" in e for e in cm["validation_errors"])


# --------------------------------------------------------------------
# Test 9: full happy-path bilanz assembly.
# --------------------------------------------------------------------


def test_assemble_bilanz_happy_path():
    bilanz = bilanz_mod.assemble_bilanz(
        marathon_state=_marathon_state_fixture(),
        aggregator_history=_aggregator_history_fixture(),
        backend_snapshots=_backend_snapshots_fixture(),
        drift_histograms=_drift_histograms_fixture(),
        sign_offs=_sign_offs_fixture(),
        complete_marker=_complete_marker_fixture(),
        generated_at="2026-06-30T00:00:00Z",
    )
    exe = bilanz["executive_summary"]
    assert exe["wellen_total"] == 7
    assert exe["wellen_with_sign_off"] == 7
    assert exe["complete_marker_is_complete"] is True
    assert exe["audit_aggregate_ok"] is True
    # All wellen should have drift OK with the default fixture.
    assert exe["drift_status_counts"]["OK"] == 7
    assert bilanz["phase_4_followups"] == [
        "No outstanding follow-ups detected -- Phase-4 may proceed with "
        "the standard pre-substanz aufstellung."
    ]


# --------------------------------------------------------------------
# Test 10: bilanz surfaces follow-ups when breaches present.
# --------------------------------------------------------------------


def test_assemble_bilanz_with_breaches_generates_followups():
    bilanz = bilanz_mod.assemble_bilanz(
        marathon_state=_marathon_state_fixture(),
        aggregator_history=_aggregator_history_fixture(),
        backend_snapshots=_backend_snapshots_fixture(),
        drift_histograms=_drift_histograms_fixture(
            breach_welle="welle-2-svid-workload-identity"
        ),
        sign_offs=_sign_offs_fixture(missing=["welle-7-recovery-workflow"]),
        complete_marker=_complete_marker_fixture(wellen_complete=6),
        generated_at="2026-06-30T00:00:00Z",
    )
    followups = bilanz["phase_4_followups"]
    assert any("drift" in f and "W2" in f for f in followups)
    assert any("MISSING" in f for f in followups)
    assert any("marker not valid" in f for f in followups)


# --------------------------------------------------------------------
# Test 11: markdown rendering well-formed.
# --------------------------------------------------------------------


def test_render_markdown_contains_seven_welle_sections_and_metadata():
    bilanz = bilanz_mod.assemble_bilanz(
        marathon_state=_marathon_state_fixture(),
        aggregator_history=_aggregator_history_fixture(),
        backend_snapshots=_backend_snapshots_fixture(),
        drift_histograms=_drift_histograms_fixture(),
        sign_offs=_sign_offs_fixture(),
        complete_marker=_complete_marker_fixture(),
        generated_at="2026-06-30T00:00:00Z",
    )
    md = bilanz_mod.render_markdown(bilanz)
    assert "# Phase-3 Marathon Final Bilanz" in md
    assert "## 1. Executive Summary" in md
    assert "## 2. Per-Welle Mini-Bilanz" in md
    assert "## 3. Cross-Welle Coupling Bilanz" in md
    assert "## 4. Henrik Audit Aggregate" in md
    assert "## 5. Phase-3-COMPLETE-Marker Validation" in md
    assert "## 6. Phase-4 Follow-up Items" in md
    assert "## 7. Source-of-Truth Inputs" in md
    # Each welle short-label appears.
    for short in bilanz_mod.WELLE_SHORT.values():
        assert short in md
    # Document is substantial (the task brief says ~500..800 lines).
    assert len(md.splitlines()) >= 200


# --------------------------------------------------------------------
# Test 12: end-to-end main() with fixtures on disk.
# --------------------------------------------------------------------


def test_main_writes_md_and_json(tmp_path: pathlib.Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    reports_dir = tmp_path / "reports"

    # Write input fixtures to disk.
    (state_dir / "phase-3-marathon-state.json").write_text(
        json.dumps(_marathon_state_fixture()), encoding="utf-8"
    )
    (state_dir / "aggregator-failure-rate-history.json").write_text(
        json.dumps(_aggregator_history_fixture()), encoding="utf-8"
    )
    snap_dir = state_dir / "backend-decision-snapshots"
    snap_dir.mkdir()
    for wid, snaps in _backend_snapshots_fixture().items():
        (snap_dir / f"{wid}.json").write_text(
            json.dumps(snaps), encoding="utf-8"
        )
    (state_dir / "cross-welle-drift-histograms.json").write_text(
        json.dumps(_drift_histograms_fixture()), encoding="utf-8"
    )
    for s in _sign_offs_fixture():
        # Use index in WELLE_ORDER for file naming.
        idx = bilanz_mod.WELLE_ORDER.index(s["welle_id"]) + 1
        (state_dir / f"welle-{idx}-sign-off.json").write_text(
            json.dumps(s), encoding="utf-8"
        )
    (state_dir / "phase-3-complete-marker.json").write_text(
        json.dumps(_complete_marker_fixture()), encoding="utf-8"
    )

    rc = bilanz_mod.main(
        [
            "--marathon-state",
            str(state_dir / "phase-3-marathon-state.json"),
            "--aggregator-history",
            str(state_dir / "aggregator-failure-rate-history.json"),
            "--backend-snapshots-dir",
            str(snap_dir),
            "--drift-histograms",
            str(state_dir / "cross-welle-drift-histograms.json"),
            "--sign-off-glob",
            str(state_dir / "welle-*-sign-off.json"),
            "--complete-marker",
            str(state_dir / "phase-3-complete-marker.json"),
            "--output-md",
            str(reports_dir / "phase-3-marathon-bilanz.md"),
            "--output-json",
            str(reports_dir / "phase-3-marathon-bilanz.json"),
            "--now-iso",
            "2026-06-30T00:00:00Z",
        ]
    )
    assert rc == 0
    assert (reports_dir / "phase-3-marathon-bilanz.md").exists()
    assert (reports_dir / "phase-3-marathon-bilanz.json").exists()
    payload = json.loads(
        (reports_dir / "phase-3-marathon-bilanz.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["schema_version"] == bilanz_mod.BILANZ_SCHEMA_VERSION
    assert payload["executive_summary"]["wellen_total"] == 7


# --------------------------------------------------------------------
# Test 13: auto-trigger short-circuit when marker missing or not COMPLETE.
# --------------------------------------------------------------------


def test_main_auto_trigger_exits_zero_when_marker_missing(tmp_path: pathlib.Path):
    rc = bilanz_mod.main(
        [
            "--auto-after-complete-marker",
            "--complete-marker",
            str(tmp_path / "does-not-exist.json"),
            "--marathon-state",
            str(tmp_path / "does-not-exist-2.json"),
        ]
    )
    assert rc == 0


def test_main_auto_trigger_exits_zero_when_marker_not_complete(
    tmp_path: pathlib.Path,
):
    marker = tmp_path / "marker.json"
    marker.write_text(
        json.dumps({"status": "IN_PROGRESS", "wellen_complete": 3}),
        encoding="utf-8",
    )
    rc = bilanz_mod.main(
        [
            "--auto-after-complete-marker",
            "--complete-marker",
            str(marker),
            "--marathon-state",
            str(tmp_path / "does-not-exist.json"),
        ]
    )
    assert rc == 0


# --------------------------------------------------------------------
# Test 14: strict mode returns non-zero on breach.
# --------------------------------------------------------------------


def test_main_strict_mode_exits_nonzero_on_breach(tmp_path: pathlib.Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    reports_dir = tmp_path / "reports"
    (state_dir / "phase-3-marathon-state.json").write_text(
        json.dumps(_marathon_state_fixture()), encoding="utf-8"
    )
    (state_dir / "aggregator-failure-rate-history.json").write_text(
        json.dumps(_aggregator_history_fixture()), encoding="utf-8"
    )
    snap_dir = state_dir / "backend-decision-snapshots"
    snap_dir.mkdir()
    for wid, snaps in _backend_snapshots_fixture().items():
        (snap_dir / f"{wid}.json").write_text(
            json.dumps(snaps), encoding="utf-8"
        )
    # Introduce a drift BREACH for welle-1.
    (state_dir / "cross-welle-drift-histograms.json").write_text(
        json.dumps(
            _drift_histograms_fixture(breach_welle="welle-1-v907-verify")
        ),
        encoding="utf-8",
    )
    for s in _sign_offs_fixture():
        idx = bilanz_mod.WELLE_ORDER.index(s["welle_id"]) + 1
        (state_dir / f"welle-{idx}-sign-off.json").write_text(
            json.dumps(s), encoding="utf-8"
        )
    (state_dir / "phase-3-complete-marker.json").write_text(
        json.dumps(_complete_marker_fixture()), encoding="utf-8"
    )

    rc = bilanz_mod.main(
        [
            "--marathon-state",
            str(state_dir / "phase-3-marathon-state.json"),
            "--aggregator-history",
            str(state_dir / "aggregator-failure-rate-history.json"),
            "--backend-snapshots-dir",
            str(snap_dir),
            "--drift-histograms",
            str(state_dir / "cross-welle-drift-histograms.json"),
            "--sign-off-glob",
            str(state_dir / "welle-*-sign-off.json"),
            "--complete-marker",
            str(state_dir / "phase-3-complete-marker.json"),
            "--output-md",
            str(reports_dir / "phase-3-marathon-bilanz.md"),
            "--output-json",
            str(reports_dir / "phase-3-marathon-bilanz.json"),
            "--now-iso",
            "2026-06-30T00:00:00Z",
            "--strict",
        ]
    )
    assert rc == 1


# --------------------------------------------------------------------
# Test 15: deterministic re-run produces same output.
# --------------------------------------------------------------------


def test_assemble_bilanz_is_deterministic():
    args = dict(
        marathon_state=_marathon_state_fixture(),
        aggregator_history=_aggregator_history_fixture(),
        backend_snapshots=_backend_snapshots_fixture(),
        drift_histograms=_drift_histograms_fixture(),
        sign_offs=_sign_offs_fixture(),
        complete_marker=_complete_marker_fixture(),
        generated_at="2026-06-30T00:00:00Z",
    )
    a = bilanz_mod.assemble_bilanz(**args)
    b = bilanz_mod.assemble_bilanz(**args)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# --------------------------------------------------------------------
# Test 16: missing marathon-state file -> rc 2 with descriptive stderr.
# --------------------------------------------------------------------


def test_main_missing_marathon_state_returns_two(tmp_path: pathlib.Path, capsys):
    rc = bilanz_mod.main(
        [
            "--marathon-state",
            str(tmp_path / "absent.json"),
            "--aggregator-history",
            str(tmp_path / "absent2.json"),
            "--backend-snapshots-dir",
            str(tmp_path / "no-dir"),
            "--drift-histograms",
            str(tmp_path / "no-dh.json"),
            "--sign-off-glob",
            str(tmp_path / "welle-*-sign-off.json"),
            "--complete-marker",
            str(tmp_path / "no-cm.json"),
            "--output-md",
            str(tmp_path / "out.md"),
            "--output-json",
            str(tmp_path / "out.json"),
        ]
    )
    assert rc == 2
    captured = capsys.readouterr()
    assert "marathon-state file missing" in captured.err
