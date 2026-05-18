# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Validate Noa's Phase-3 Final Bilanz Generator against five
canonical fixture datasets.

Each dataset under ``tests/fixtures/phase-3-marathon-bilanz/<name>/``
is a self-contained ``state/`` tree that the generator can consume
directly. The tests assert:

  1. Schema validity (every JSON parses, expected top-level keys
     present where the generator requires them).
  2. Byte-stability (regenerating from the source-of-truth builder
     produces byte-identical files to those on disk).
  3. Expected bilanz verdict (per dataset: which executive-summary
     flags must be true/false, which follow-ups must appear).

The tests load the generator script via ``importlib.util`` (its
filename contains hyphens). They invoke ``assemble_bilanz`` directly
to keep the assertions hermetic and fast; the end-to-end ``main()``
path is covered by Noa's existing test suite.

-- Selin
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys
from typing import Any, Dict, List, Tuple

import pytest

# --------------------------------------------------------------------
# Module + path setup
# --------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
GENERATOR_PATH = (
    REPO_ROOT
    / "scripts"
    / "observability"
    / "phase-3-final-bilanz-generator.py"
)
FIXTURES_ROOT = pathlib.Path(__file__).resolve().parent
REGENERATE_PATH = FIXTURES_ROOT / "regenerate.py"

DATASETS = (
    "happy-path",
    "rollback-path",
    "welle-7-missing",
    "cross-drift",
    "latency-excursion",
)


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "phase_3_final_bilanz_generator", str(GENERATOR_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["phase_3_final_bilanz_generator"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_regenerator():
    spec = importlib.util.spec_from_file_location(
        "phase_3_marathon_bilanz_fixture_regenerator", str(REGENERATE_PATH)
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["phase_3_marathon_bilanz_fixture_regenerator"] = mod
    spec.loader.exec_module(mod)
    return mod


bilanz_mod = _load_generator()
regen_mod = _load_regenerator()


# --------------------------------------------------------------------
# Fixture loading helpers
# --------------------------------------------------------------------


def _state_root(dataset: str) -> pathlib.Path:
    return FIXTURES_ROOT / dataset / "state"


def _load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_dataset_inputs(dataset: str) -> Dict[str, Any]:
    state = _state_root(dataset)
    marathon = _load_json(state / "phase-3-marathon-state.json")
    aggregator = _load_json(state / "aggregator-failure-rate-history.json")
    drift = _load_json(state / "cross-welle-drift-histograms.json")
    backend: Dict[str, List[Dict[str, Any]]] = {}
    snap_dir = state / "backend-decision-snapshots"
    if snap_dir.is_dir():
        for wid in bilanz_mod.WELLE_ORDER:
            p = snap_dir / f"{wid}.json"
            if p.exists():
                data = _load_json(p)
                backend[wid] = data if isinstance(data, list) else []
            else:
                backend[wid] = []
    sign_offs: List[Dict[str, Any]] = []
    for p in sorted(state.glob("welle-*-sign-off.json")):
        sign_offs.append(_load_json(p))
    marker_path = state / "phase-3-complete-marker.json"
    complete_marker = _load_json(marker_path) if marker_path.exists() else None
    return {
        "marathon_state": marathon,
        "aggregator_history": aggregator,
        "backend_snapshots": backend,
        "drift_histograms": drift,
        "sign_offs": sign_offs,
        "complete_marker": complete_marker,
    }


def _assemble(dataset: str) -> Dict[str, Any]:
    inputs = _load_dataset_inputs(dataset)
    return bilanz_mod.assemble_bilanz(
        marathon_state=inputs["marathon_state"],
        aggregator_history=inputs["aggregator_history"],
        backend_snapshots=inputs["backend_snapshots"],
        drift_histograms=inputs["drift_histograms"],
        sign_offs=inputs["sign_offs"],
        complete_marker=inputs["complete_marker"],
        generated_at="2026-06-30T00:00:00Z",
    )


# --------------------------------------------------------------------
# 1. Schema-validity sweep
# --------------------------------------------------------------------


@pytest.mark.parametrize("dataset", DATASETS)
def test_marathon_state_schema_valid(dataset: str) -> None:
    payload = _load_json(_state_root(dataset) / "phase-3-marathon-state.json")
    assert payload.get("schema_version") == "1.0.0"
    assert "wellen" in payload
    assert isinstance(payload["wellen"], dict)
    # Every present welle must have the four required fields.
    for wid, w in payload["wellen"].items():
        assert wid in bilanz_mod.WELLE_ORDER, f"unknown welle id: {wid}"
        for key in (
            "cutover_runs_total",
            "cutover_runs_rust",
            "cutover_runs_python_fallback",
            "decision_latency_ms_samples",
        ):
            assert key in w, f"{dataset}/{wid} missing {key}"


@pytest.mark.parametrize("dataset", DATASETS)
def test_aggregator_history_schema_valid(dataset: str) -> None:
    payload = _load_json(
        _state_root(dataset) / "aggregator-failure-rate-history.json"
    )
    assert isinstance(payload, list)
    for entry in payload:
        assert "conclusion" in entry
        assert entry["conclusion"] in {"success", "failure"}
        assert "run_id" in entry
        assert "wait_loop_seconds" in entry


@pytest.mark.parametrize("dataset", DATASETS)
def test_drift_histograms_schema_valid(dataset: str) -> None:
    payload = _load_json(
        _state_root(dataset) / "cross-welle-drift-histograms.json"
    )
    assert isinstance(payload, dict)
    for wid, h in payload.items():
        assert wid in bilanz_mod.WELLE_ORDER
        assert "drift_pct_samples" in h
        assert isinstance(h["drift_pct_samples"], list)


@pytest.mark.parametrize("dataset", DATASETS)
def test_sign_offs_schema_valid(dataset: str) -> None:
    state = _state_root(dataset)
    for path in sorted(state.glob("welle-*-sign-off.json")):
        payload = _load_json(path)
        for key in (
            "welle_id",
            "signed_off_at",
            "signed_off_by",
            "audit_ok",
            "exception_count",
            "audit_findings",
        ):
            assert key in payload, f"{path.name} missing {key}"


@pytest.mark.parametrize("dataset", DATASETS)
def test_complete_marker_schema_valid_or_absent(dataset: str) -> None:
    marker_path = _state_root(dataset) / "phase-3-complete-marker.json"
    if not marker_path.exists():
        # rollback-path intentionally omits the marker.
        assert dataset == "rollback-path"
        return
    payload = _load_json(marker_path)
    assert payload.get("schema_version") == "1.0.0"
    assert "status" in payload
    assert "wellen_complete" in payload


# --------------------------------------------------------------------
# 2. Byte-stability sweep
# --------------------------------------------------------------------


def _walk_state_files(dataset: str) -> List[pathlib.Path]:
    return sorted(
        p for p in (FIXTURES_ROOT / dataset).rglob("*.json") if p.is_file()
    )


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("dataset", DATASETS)
def test_fixtures_are_byte_stable(dataset: str, tmp_path: pathlib.Path) -> None:
    """Regenerating from the builder must yield byte-identical files."""
    builder = regen_mod.DATASETS[dataset]
    regen_mod.write_dataset(dataset, builder(), tmp_path)

    on_disk = _walk_state_files(dataset)
    regenerated_root = tmp_path / dataset
    regenerated = sorted(
        p for p in regenerated_root.rglob("*.json") if p.is_file()
    )

    on_disk_rel = [p.relative_to(FIXTURES_ROOT / dataset) for p in on_disk]
    regen_rel = [p.relative_to(regenerated_root) for p in regenerated]
    assert on_disk_rel == regen_rel, (
        f"{dataset}: file set drift -- "
        f"on-disk={on_disk_rel} regen={regen_rel}"
    )
    for rel in on_disk_rel:
        d_sha = _sha256(FIXTURES_ROOT / dataset / rel)
        r_sha = _sha256(regenerated_root / rel)
        assert d_sha == r_sha, (
            f"{dataset}/{rel}: SHA-256 drift "
            f"on-disk={d_sha} regen={r_sha} -- "
            "run regenerate.py to refresh fixtures."
        )


# --------------------------------------------------------------------
# 3. Generator-constant consistency
# --------------------------------------------------------------------


def test_welle_order_matches_generator() -> None:
    assert regen_mod.WELLE_ORDER == bilanz_mod.WELLE_ORDER


def test_latency_budget_matches_generator() -> None:
    assert regen_mod.LATENCY_BUDGET_MS == bilanz_mod.LATENCY_BUDGET_MS


# --------------------------------------------------------------------
# 4. Per-dataset bilanz verdict assertions
# --------------------------------------------------------------------


def test_happy_path_bilanz_is_all_green() -> None:
    bilanz = _assemble("happy-path")
    exe = bilanz["executive_summary"]
    assert exe["wellen_total"] == 7
    assert exe["wellen_with_sign_off"] == 7
    assert exe["complete_marker_is_complete"] is True
    assert exe["audit_aggregate_ok"] is True
    assert exe["drift_status_counts"]["BREACH"] == 0
    assert exe["drift_status_counts"]["OK"] == 7
    assert exe["latency_status_counts"].get("BREACH", 0) == 0
    assert exe["latency_status_counts"].get("OK", 0) == 7
    # No followups: builder asserts the no-follow-up path produces the
    # canonical single-element list.
    assert bilanz["phase_4_followups"] == [
        "No outstanding follow-ups detected -- Phase-4 may proceed with "
        "the standard pre-substanz aufstellung."
    ]


def test_rollback_path_bilanz_blocks_complete() -> None:
    bilanz = _assemble("rollback-path")
    exe = bilanz["executive_summary"]
    cm = bilanz["complete_marker_validation"]
    # COMPLETE-marker is absent -- generator must reject completeness.
    assert cm["present"] is False
    assert exe["complete_marker_is_complete"] is False
    # W3 carries drift BREACH.
    assert exe["drift_status_counts"]["BREACH"] >= 1
    # W3 has exception_count > 0, audit_ok=false -- aggregate must fail.
    assert exe["audit_aggregate_ok"] is False
    # Missing sign-offs for W4..W7.
    missing = bilanz["audit_aggregate"]["missing_sign_offs"]
    assert "welle-4-state-backing" in missing
    assert "welle-5-lifecycle-state-machine" in missing
    assert "welle-6-subscribe-loop" in missing
    assert "welle-7-recovery-workflow" in missing
    # Followups must mention rollback consequences.
    followups = bilanz["phase_4_followups"]
    assert any("MISSING" in f for f in followups)
    assert any("marker" in f.lower() for f in followups)


def test_welle_7_missing_bilanz_flags_pre_auditor_absent() -> None:
    bilanz = _assemble("welle-7-missing")
    exe = bilanz["executive_summary"]
    aud = bilanz["audit_aggregate"]
    cm = bilanz["complete_marker_validation"]
    assert exe["wellen_with_sign_off"] == 6
    assert "welle-7-recovery-workflow" in aud["missing_sign_offs"]
    assert exe["audit_aggregate_ok"] is False
    # Complete-marker exists but with wellen_complete=6 -- must be
    # invalid.
    assert cm["present"] is True
    assert cm["is_complete"] is False
    assert any(
        "wellen_complete_expected_7" in e for e in cm["validation_errors"]
    )


def test_cross_drift_bilanz_flags_two_wellen_simultaneous_breach() -> None:
    bilanz = _assemble("cross-drift")
    exe = bilanz["executive_summary"]
    assert exe["drift_status_counts"]["BREACH"] == 2
    # Specifically W4 and W5.
    assert (
        bilanz["per_welle"]["welle-4-state-backing"]["drift"]["drift_status"]
        == "BREACH"
    )
    assert (
        bilanz["per_welle"]["welle-5-lifecycle-state-machine"]["drift"][
            "drift_status"
        ]
        == "BREACH"
    )
    # Aggregate audit must be false (W4 + W5 carry exception_count > 0
    # in this fixture).
    assert exe["audit_aggregate_ok"] is False
    # Followups must call out both wellen.
    followups = bilanz["phase_4_followups"]
    assert any("W4" in f and "drift" in f for f in followups)
    assert any("W5" in f and "drift" in f for f in followups)


def test_latency_excursion_bilanz_keeps_audit_ok() -> None:
    bilanz = _assemble("latency-excursion")
    exe = bilanz["executive_summary"]
    # Audit aggregate must remain OK: latency does not gate Henrik.
    assert exe["audit_aggregate_ok"] is True
    # Two wellen breach latency budget.
    assert exe["latency_status_counts"].get("BREACH", 0) == 2
    assert (
        bilanz["per_welle"]["welle-3-bridge-audit-writer"]["latency_status"]
        == "BREACH"
    )
    assert (
        bilanz["per_welle"]["welle-5-lifecycle-state-machine"]["latency_status"]
        == "BREACH"
    )
    # COMPLETE-marker remains valid -- the bilanz must surface the
    # latency excursion via follow-ups, not via marker-validation.
    assert exe["complete_marker_is_complete"] is True
    followups = bilanz["phase_4_followups"]
    assert any(
        "latency" in f and ("W3" in f or "W5" in f) for f in followups
    )


# --------------------------------------------------------------------
# 5. Strict-mode breach detection per dataset
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "dataset,expects_breach",
    [
        ("happy-path", False),
        ("rollback-path", True),
        ("welle-7-missing", True),
        ("cross-drift", True),
        ("latency-excursion", True),
    ],
)
def test_strict_mode_breach_detection(dataset: str, expects_breach: bool) -> None:
    bilanz = _assemble(dataset)
    breaches = bilanz_mod._detect_breach(bilanz)  # type: ignore[attr-defined]
    if expects_breach:
        assert breaches, f"{dataset}: expected at least one BREACH"
    else:
        assert breaches == [], f"{dataset}: unexpected breaches {breaches}"


# --------------------------------------------------------------------
# 6. Markdown rendering smoke
# --------------------------------------------------------------------


@pytest.mark.parametrize("dataset", DATASETS)
def test_markdown_rendering_smoke(dataset: str) -> None:
    bilanz = _assemble(dataset)
    md = bilanz_mod.render_markdown(bilanz)
    assert "# Phase-3 Marathon Final Bilanz" in md
    assert "## 1. Executive Summary" in md
    assert "## 6. Phase-4 Follow-up Items" in md
    # Per-welle table appears at least once per active welle.
    for wid, short in bilanz_mod.WELLE_SHORT.items():
        if wid in bilanz["per_welle"]:
            assert short in md
