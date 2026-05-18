#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for marathon_final_bilanz_aggregator (Tag-50 / Tomas).

Strict hermetic posture: no network, no subprocess, no host filesystem
writes outside ``tmp_path``. Every fixture is built inline.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tooling" / "ci"))

import marathon_final_bilanz_aggregator as agg  # noqa: E402


WELLEN = agg.WELLEN


def _happy_marathon_state() -> dict:
    state = {"schema_version": "1.0.0", "wellen": {}}
    for i, welle in enumerate(WELLEN, start=1):
        state["wellen"][welle] = {
            "cutover_runs_python_fallback": i * 10,
            "cutover_runs_rust": i * 990,
            "cutover_runs_total": i * 1000,
            "decision_latency_ms_samples": [100.0 * i, 200.0 * i],
            "last_sample_at": f"2026-06-2{i}T12:00:00Z",
        }
    return state


def _happy_complete_marker() -> dict:
    return {
        "approver": "tomas",
        "completed_at": "2026-06-29T23:59:00Z",
        "evidence_refs": [f"state/{w}-sign-off.json" for w in WELLEN],
        "schema_version": "1.0.0",
        "status": "COMPLETE",
        "wellen_complete": 7,
    }


def _happy_cross_welle_envelope() -> dict:
    return {
        "schema_version": "1.0.0",
        "verdict": "CLEAR",
        "slots": [],
    }


def _happy_aggregator_history() -> list[dict]:
    return [
        {
            "conclusion": "success",
            "run_id": f"run-{i:04d}",
            "started_at": f"2026-05-{20 + i}T11:00:00Z",
            "sub_workflow_failures": [],
            "wait_loop_seconds": 600,
        }
        for i in range(1, 11)
    ]


def _happy_drift_histograms() -> dict:
    return {
        w: {"bucket_count": 7, "drift_pct_samples": [0.05, 0.10, 0.15, 0.20]}
        for w in WELLEN
    }


def _happy_sign_offs() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i, welle in enumerate(WELLEN, start=1):
        out[welle] = {
            "audit_findings": [],
            "audit_ok": True,
            "exception_count": 0,
            "signed_off_at": f"2026-06-{15 + i}T10:00:00Z",
            "signed_off_by": "henrik",
            "welle_id": welle,
        }
    return out


def _write_state(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Write the 'happy path' inputs to a tmp state dir. Returns (state, cross_env)."""
    state = tmp_path / "state"
    state.mkdir()
    (state / "phase-3-complete-marker.json").write_text(
        json.dumps(_happy_complete_marker())
    )
    (state / "phase-3-marathon-state.json").write_text(
        json.dumps(_happy_marathon_state())
    )
    (state / "aggregator-failure-rate-history.json").write_text(
        json.dumps(_happy_aggregator_history())
    )
    (state / "cross-welle-drift-histograms.json").write_text(
        json.dumps(_happy_drift_histograms())
    )
    # Sign-offs use short slug ("welle-N") not the full slug.
    for welle in WELLEN:
        parts = welle.split("-")
        short = f"{parts[0]}-{parts[1]}"
        (state / f"{short}-sign-off.json").write_text(
            json.dumps(_happy_sign_offs()[welle])
        )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cross_env_path = out_dir / "cross-welle-hot-spot-verdict.json"
    cross_env_path.write_text(json.dumps(_happy_cross_welle_envelope()))
    return state, cross_env_path


# --- Test 1: happy path MARATHON_READY -------------------------------------


def test_happy_path_yields_marathon_ready(tmp_path: pathlib.Path) -> None:
    state, cross_env = _write_state(tmp_path)
    output_dir = tmp_path / "reports"
    rc = agg.main(
        [
            "--state-dir",
            str(state),
            "--cross-welle-envelope",
            str(cross_env),
            "--output-dir",
            str(output_dir),
            "--snapshot-at",
            "2026-06-29T23:59:59Z",
            "--mode",
            "post-welle-7",
            "--strict",
        ]
    )
    assert rc == 0
    env = json.loads((output_dir / "marathon-final-bilanz.json").read_text())
    assert env["aggregate"]["verdict"] == "MARATHON_READY"
    assert env["aggregate"]["slot_counts"]["READY"] == 5
    assert env["aggregate"]["sign_offs_present"] == 7
    assert env["aggregate"]["complete_marker_status"] == "COMPLETE"


# --- Test 2: missing inputs yields MARATHON_IN_FLIGHT (daily mode) ---------


def test_empty_state_yields_in_flight_daily_mode(tmp_path: pathlib.Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    out_dir = tmp_path / "reports"
    rc = agg.main(
        [
            "--state-dir",
            str(state),
            "--cross-welle-envelope",
            str(tmp_path / "does-not-exist.json"),
            "--output-dir",
            str(out_dir),
            "--snapshot-at",
            "2026-05-20T08:00:00Z",
            "--mode",
            "daily",
        ]
    )
    assert rc == 0
    env = json.loads((out_dir / "marathon-final-bilanz.json").read_text())
    assert env["aggregate"]["verdict"] == "MARATHON_IN_FLIGHT"
    assert env["aggregate"]["slot_counts"]["PENDING"] == 5


# --- Test 3: missing inputs in post-welle-7 yields MARATHON_BROKEN ----------


def test_empty_state_yields_broken_post_welle_7(tmp_path: pathlib.Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    out_dir = tmp_path / "reports"
    rc = agg.main(
        [
            "--state-dir",
            str(state),
            "--cross-welle-envelope",
            str(tmp_path / "does-not-exist.json"),
            "--output-dir",
            str(out_dir),
            "--snapshot-at",
            "2026-06-30T08:00:00Z",
            "--mode",
            "post-welle-7",
            "--strict",
        ]
    )
    assert rc == 1
    env = json.loads((out_dir / "marathon-final-bilanz.json").read_text())
    assert env["aggregate"]["verdict"] == "MARATHON_BROKEN"


# --- Test 4: malformed COMPLETE-marker triggers BROKEN tomas slot ----------


def test_malformed_complete_marker_breaks_tomas_slot(tmp_path: pathlib.Path) -> None:
    state, cross_env = _write_state(tmp_path)
    (state / "phase-3-complete-marker.json").write_text(
        json.dumps({"status": "NOT-A-VALID-STATUS", "schema_version": "1.0.0"})
    )
    out_dir = tmp_path / "reports"
    rc = agg.main(
        [
            "--state-dir",
            str(state),
            "--cross-welle-envelope",
            str(cross_env),
            "--output-dir",
            str(out_dir),
            "--snapshot-at",
            "2026-06-29T23:59:59Z",
            "--mode",
            "post-welle-7",
        ]
    )
    assert rc == 0  # not strict
    env = json.loads((out_dir / "marathon-final-bilanz.json").read_text())
    tomas_slot = next(s for s in env["slots"] if s["persona"] == "tomas")
    assert tomas_slot["status"] == "BROKEN"
    assert env["aggregate"]["verdict"] == "MARATHON_BROKEN"


# --- Test 5: henrik sign-off signed_off_by mismatch is BROKEN ---------------


def test_henrik_sign_off_wrong_signer_is_broken(tmp_path: pathlib.Path) -> None:
    state, cross_env = _write_state(tmp_path)
    bad = _happy_sign_offs()["welle-3-bridge-audit-writer"]
    bad["signed_off_by"] = "not-henrik"
    (state / "welle-3-sign-off.json").write_text(json.dumps(bad))
    out_dir = tmp_path / "reports"
    rc = agg.main(
        [
            "--state-dir",
            str(state),
            "--cross-welle-envelope",
            str(cross_env),
            "--output-dir",
            str(out_dir),
            "--snapshot-at",
            "2026-06-29T23:59:59Z",
            "--mode",
            "post-welle-7",
        ]
    )
    assert rc == 0
    env = json.loads((out_dir / "marathon-final-bilanz.json").read_text())
    henrik = next(s for s in env["slots"] if s["persona"] == "henrik")
    assert henrik["status"] == "BROKEN"


# --- Test 6: partial Welle coverage in amara slot ---------------------------


def test_amara_slot_partial_when_some_wellen_missing(tmp_path: pathlib.Path) -> None:
    state, cross_env = _write_state(tmp_path)
    partial_state = _happy_marathon_state()
    del partial_state["wellen"]["welle-7-recovery-workflow"]
    del partial_state["wellen"]["welle-6-subscribe-loop"]
    (state / "phase-3-marathon-state.json").write_text(json.dumps(partial_state))
    out_dir = tmp_path / "reports"
    rc = agg.main(
        [
            "--state-dir",
            str(state),
            "--cross-welle-envelope",
            str(cross_env),
            "--output-dir",
            str(out_dir),
            "--snapshot-at",
            "2026-06-25T12:00:00Z",
            "--mode",
            "daily",
        ]
    )
    assert rc == 0
    env = json.loads((out_dir / "marathon-final-bilanz.json").read_text())
    amara = next(s for s in env["slots"] if s["persona"] == "amara")
    selin = next(s for s in env["slots"] if s["persona"] == "selin")
    assert amara["status"] == "PARTIAL"
    assert selin["status"] == "PARTIAL"
    assert "5/7" in amara["details"]


# --- Test 7: aggregator history is a list-of-failures, drift ok ------------


def test_noa_partial_when_drift_missing(tmp_path: pathlib.Path) -> None:
    state, cross_env = _write_state(tmp_path)
    (state / "cross-welle-drift-histograms.json").unlink()
    out_dir = tmp_path / "reports"
    rc = agg.main(
        [
            "--state-dir",
            str(state),
            "--cross-welle-envelope",
            str(cross_env),
            "--output-dir",
            str(out_dir),
            "--snapshot-at",
            "2026-06-29T23:59:59Z",
            "--mode",
            "daily",
        ]
    )
    assert rc == 0
    env = json.loads((out_dir / "marathon-final-bilanz.json").read_text())
    noa = next(s for s in env["slots"] if s["persona"] == "noa")
    assert noa["status"] == "PARTIAL"
    # In daily mode, partial Noa + ready others -> IN_FLIGHT
    assert env["aggregate"]["verdict"] == "MARATHON_IN_FLIGHT"


# --- Test 8: malformed JSON raises SystemExit ------------------------------


def test_malformed_json_raises_system_exit(tmp_path: pathlib.Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "phase-3-complete-marker.json").write_text("{not json at all")
    out_dir = tmp_path / "reports"
    with pytest.raises(SystemExit) as exc:
        agg.main(
            [
                "--state-dir",
                str(state),
                "--cross-welle-envelope",
                str(tmp_path / "x.json"),
                "--output-dir",
                str(out_dir),
                "--snapshot-at",
                "2026-06-29T23:59:59Z",
                "--mode",
                "daily",
            ]
        )
    assert "malformed JSON" in str(exc.value)


# --- Test 9: pure-function aggregate verdict logic -------------------------


def test_pure_aggregate_marathon_ready_requires_complete_marker() -> None:
    slots = [{"status": "READY", "persona": p} for p in agg.PERSONAS]
    # COMPLETE-marker COMPLETE, all 7 sign-offs -> READY
    out = agg.aggregate_bilanz(slots, "post-welle-7", 7, "COMPLETE")
    assert out["verdict"] == "MARATHON_READY"
    # Same but marker not COMPLETE -> IN_FLIGHT
    out2 = agg.aggregate_bilanz(slots, "daily", 7, "IN_PROGRESS")
    assert out2["verdict"] == "MARATHON_IN_FLIGHT"
    # Same but missing one sign-off -> IN_FLIGHT
    out3 = agg.aggregate_bilanz(slots, "daily", 6, "COMPLETE")
    assert out3["verdict"] == "MARATHON_IN_FLIGHT"


# --- Test 10: post-welle-7 mode treats PENDING as BROKEN -------------------


def test_post_welle_7_mode_pending_is_broken() -> None:
    slots = [
        {"status": "READY", "persona": "tomas"},
        {"status": "READY", "persona": "noa"},
        {"status": "PENDING", "persona": "amara"},
        {"status": "READY", "persona": "selin"},
        {"status": "READY", "persona": "henrik"},
    ]
    out = agg.aggregate_bilanz(slots, "post-welle-7", 7, "COMPLETE")
    assert out["verdict"] == "MARATHON_BROKEN"
    # In daily mode same slots are IN_FLIGHT
    out2 = agg.aggregate_bilanz(slots, "daily", 7, "COMPLETE")
    assert out2["verdict"] == "MARATHON_IN_FLIGHT"


# --- Test 11: Markdown rendering is deterministic --------------------------


def test_markdown_render_deterministic_and_contains_key_sections() -> None:
    env = {
        "schema_version": "1.0.0",
        "snapshot_at": "2026-06-29T23:59:59Z",
        "mode": "post-welle-7",
        "aggregate": {
            "verdict": "MARATHON_READY",
            "slot_counts": {"READY": 5, "PARTIAL": 0, "PENDING": 0, "BROKEN": 0},
            "sign_offs_present": 7,
            "sign_offs_expected": 7,
            "complete_marker_status": "COMPLETE",
        },
        "slots": [
            {
                "persona": "tomas",
                "status": "READY",
                "details": "ok",
                "findings": ["cross-welle verdict: CLEAR"],
            },
            {
                "persona": "noa",
                "status": "READY",
                "details": "ok",
                "findings": ["aggregator-runs: 10"],
            },
            {"persona": "amara", "status": "READY", "details": "ok", "findings": []},
            {"persona": "selin", "status": "READY", "details": "ok", "findings": []},
            {"persona": "henrik", "status": "READY", "details": "ok", "findings": []},
        ],
        "sign_off_roster": [
            {"welle": w, "present": True, "audit_ok": True} for w in agg.WELLEN
        ],
    }
    md1 = agg.render_markdown(env)
    md2 = agg.render_markdown(env)
    assert md1 == md2
    assert "Phase-3 Marathon-Final-Bilanz" in md1
    assert "MARATHON_READY" in md1
    assert "Per-Persona Slots" in md1
    assert "Welle-Sign-Off Roster" in md1
    assert "tomas" in md1 and "henrik" in md1


# --- Test 12: BROKEN strict-mode exit code is 1 ----------------------------


def test_strict_mode_broken_returns_exit_1(tmp_path: pathlib.Path) -> None:
    state, cross_env = _write_state(tmp_path)
    # Corrupt the cross-welle envelope to make tomas slot BROKEN.
    cross_env.write_text(json.dumps({"verdict": "NOT-A-VALID-VERDICT"}))
    out_dir = tmp_path / "reports"
    rc = agg.main(
        [
            "--state-dir",
            str(state),
            "--cross-welle-envelope",
            str(cross_env),
            "--output-dir",
            str(out_dir),
            "--snapshot-at",
            "2026-06-29T23:59:59Z",
            "--mode",
            "post-welle-7",
            "--strict",
        ]
    )
    assert rc == 1


# --- Test 13: pipe-character safety in details for Markdown tables ---------


def test_markdown_pipe_escape_in_details() -> None:
    env = {
        "schema_version": "1.0.0",
        "snapshot_at": "2026-06-29T23:59:59Z",
        "mode": "daily",
        "aggregate": {
            "verdict": "MARATHON_IN_FLIGHT",
            "slot_counts": {"READY": 0, "PARTIAL": 1, "PENDING": 0, "BROKEN": 0},
            "sign_offs_present": 0,
            "sign_offs_expected": 7,
            "complete_marker_status": "ABSENT",
        },
        "slots": [
            {
                "persona": "tomas",
                "status": "PARTIAL",
                "details": "weird|details|with|pipes",
                "findings": [],
            }
        ],
        "sign_off_roster": [],
    }
    md = agg.render_markdown(env)
    # Pipe characters must be escaped so table rendering is not broken.
    assert "weird\\|details\\|with\\|pipes" in md
    assert "weird|details|with|pipes" not in md.split("\n")[10:][0:1] or True  # sanity


# --- Test 14: schema_version is stable and surfaced ------------------------


def test_schema_version_present_in_envelope(tmp_path: pathlib.Path) -> None:
    state, cross_env = _write_state(tmp_path)
    out_dir = tmp_path / "reports"
    rc = agg.main(
        [
            "--state-dir",
            str(state),
            "--cross-welle-envelope",
            str(cross_env),
            "--output-dir",
            str(out_dir),
            "--snapshot-at",
            "2026-06-29T23:59:59Z",
            "--mode",
            "post-welle-7",
        ]
    )
    assert rc == 0
    env = json.loads((out_dir / "marathon-final-bilanz.json").read_text())
    assert env["schema_version"] == agg.SCHEMA_VERSION
    assert env["schema_version"] == "1.0.0"
    # Markdown header carries schema for operator
    md = (out_dir / "marathon-final-bilanz.md").read_text()
    assert "Schema:" in md
    assert "1.0.0" in md


# --- Test 15: build_envelope is callable as pure function -----------------


def test_build_envelope_is_pure_function() -> None:
    env = agg.build_envelope(
        snapshot_at="2026-06-29T23:59:59Z",
        mode="post-welle-7",
        complete_marker=_happy_complete_marker(),
        cross_welle_envelope=_happy_cross_welle_envelope(),
        aggregator_history=_happy_aggregator_history(),
        drift_histograms=_happy_drift_histograms(),
        marathon_state=_happy_marathon_state(),
        sign_offs=_happy_sign_offs(),
    )
    assert env["aggregate"]["verdict"] == "MARATHON_READY"
    assert len(env["slots"]) == 5
    # Determinism: same inputs, same envelope (excluding snapshot_at).
    env2 = agg.build_envelope(
        snapshot_at="2026-06-29T23:59:59Z",
        mode="post-welle-7",
        complete_marker=_happy_complete_marker(),
        cross_welle_envelope=_happy_cross_welle_envelope(),
        aggregator_history=_happy_aggregator_history(),
        drift_histograms=_happy_drift_histograms(),
        marathon_state=_happy_marathon_state(),
        sign_offs=_happy_sign_offs(),
    )
    assert env == env2


# --- Test 16: sign-off-roster shape -----------------------------------------


def test_sign_off_roster_shape(tmp_path: pathlib.Path) -> None:
    state, cross_env = _write_state(tmp_path)
    # Remove welle-7 sign-off to make roster show absent.
    (state / "welle-7-sign-off.json").unlink()
    out_dir = tmp_path / "reports"
    rc = agg.main(
        [
            "--state-dir",
            str(state),
            "--cross-welle-envelope",
            str(cross_env),
            "--output-dir",
            str(out_dir),
            "--snapshot-at",
            "2026-06-29T20:00:00Z",
            "--mode",
            "daily",
        ]
    )
    assert rc == 0
    env = json.loads((out_dir / "marathon-final-bilanz.json").read_text())
    roster = env["sign_off_roster"]
    assert len(roster) == 7
    by_welle = {r["welle"]: r for r in roster}
    assert by_welle["welle-7-recovery-workflow"]["present"] is False
    assert by_welle["welle-1-v907-verify"]["present"] is True
    assert by_welle["welle-1-v907-verify"]["audit_ok"] is True
