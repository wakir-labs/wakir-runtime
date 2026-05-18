# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""E2E Marathon-Loop integration test (Tag-51 / Tomas).

Simulates the full Phase-3 marathon loop end-to-end:

  Welle-N validation workflow
    -> emits ``out/cutover-acceptance-decision.json``
    -> ``scripts/ci/emit-welle-sign-off.py`` converts it to
       ``state/welle-N-sign-off.json``
    -> Tag-50 Marathon-Final-Bilanz aggregator consumes the seven
       sign-off envelopes + marker + history + cross-welle envelope
    -> aggregator emits ``reports/marathon-final-bilanz.{md,json}``
    -> verdict matches the expected aggregate verdict for the scenario.

Strict hermetic posture: no network, no subprocess, no host fs writes
outside ``tmp_path``. The seven Welle-N validation workflows are
simulated by writing the decision envelopes they would emit directly
into a per-Welle out-dir; the emitter and aggregator are then called
in-process via their public APIs.

Three scenarios are covered:

* ``HAPPY_PATH``  -- all seven Welle decisions READY, COMPLETE-marker
  present with status=COMPLETE, history + drift histograms + marathon
  state full. Expected aggregate verdict: ``MARATHON_READY``.
* ``MID_MARATHON`` -- only the first three Welle decisions are present
  (READY), COMPLETE-marker absent. Expected aggregate verdict:
  ``MARATHON_IN_FLIGHT`` in daily mode; ``MARATHON_BROKEN`` in
  post-welle-7 mode (loud-failure on PENDING).
* ``BLOCK_PATH`` -- six decisions READY, Welle-7 BLOCK, COMPLETE-marker
  absent. Expected aggregate verdict: ``MARATHON_IN_FLIGHT`` in daily
  mode (sign-offs present + audit_ok=false => Henrik slot PARTIAL),
  not MARATHON_READY.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
EMITTER_PATH = REPO_ROOT / "scripts" / "ci" / "emit-welle-sign-off.py"


def _load_emitter():
    spec = importlib.util.spec_from_file_location(
        "emit_welle_sign_off", EMITTER_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


emitter = _load_emitter()

sys.path.insert(0, str(REPO_ROOT / "tooling" / "ci"))
import marathon_final_bilanz_aggregator as agg  # noqa: E402


# Per-Welle (component-long, env-var, ready_for_live_smoke shape vs verdict shape)
WELLE_SHAPES = {
    1: {"long": "v907_verify", "shape": "ready_for_live_smoke"},
    2: {"long": "svid_workload_identity", "shape": "ready_for_live_smoke"},
    3: {"long": "bridge_audit_writer", "shape": "verdict"},
    4: {"long": "state_backing", "shape": "ready_for_live_smoke"},
    5: {"long": "lifecycle_state_machine", "shape": "verdict"},
    6: {"long": "subscribe_loop", "shape": "verdict"},
    7: {"long": "recovery_workflow", "shape": "verdict"},
}


def _make_decision_envelope(welle: int, outcome: str) -> dict:
    """Build a fake Welle-N decision envelope for ``outcome`` in
    {READY, CAUTION, BLOCK}. Shape follows the per-Welle convention
    (Welle-1/2/4: ``ready_for_live_smoke`` boolean; rest: ``verdict``).
    """
    shape = WELLE_SHAPES[welle]["shape"]
    if shape == "ready_for_live_smoke":
        # Welle-1/2/4 cannot express CAUTION distinctly -- collapse to
        # the corresponding boolean. CAUTION is only used in the Welle-3+
        # shape, where the verdict field is the authoritative signal.
        ready = outcome == "READY"
        return {
            "ready_for_live_smoke": ready,
            "score_band_floor": "GREEN",
            "observed_band": "GREEN" if ready else "RED",
        }
    return {
        "verdict": outcome,
        "score_band_floor": "GREEN",
        "observed_band": "GREEN" if outcome == "READY" else "AMBER",
        "hard_block_reasons": [] if outcome != "BLOCK" else ["test-block"],
    }


def _run_marathon_loop(
    *,
    tmp_path: pathlib.Path,
    welle_outcomes: dict[int, str],
    write_complete_marker: bool,
    marker_status: str = "COMPLETE",
    write_history_and_drift: bool = True,
    write_marathon_state: bool = True,
    write_cross_welle_envelope: bool = True,
    mode: str = "daily",
) -> dict:
    """Drive the full loop and return the aggregator envelope.

    Steps:

      1. For each Welle in ``welle_outcomes``, write a per-Welle out-dir
         decision envelope; run the emitter to produce
         ``state/welle-N-sign-off.json``.
      2. Optionally populate the Tomas/Noa/Selin/Amara state files.
      3. Call the aggregator's ``build_envelope`` directly with parsed
         state.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    out_root = tmp_path / "welle-out"
    out_root.mkdir(parents=True, exist_ok=True)
    reports_dir = tmp_path / "reports"

    # 1. emit sign-off envelopes
    for welle, outcome in welle_outcomes.items():
        welle_out = out_root / f"welle-{welle}"
        welle_out.mkdir(parents=True, exist_ok=True)
        decision_path = welle_out / "cutover-acceptance-decision.json"
        decision_path.write_text(
            json.dumps(_make_decision_envelope(welle, outcome), indent=2)
            + "\n",
            encoding="utf-8",
        )
        sign_off_path = state_dir / f"welle-{welle}-sign-off.json"
        rc = emitter.main(
            [
                "--welle",
                str(welle),
                "--decision-envelope",
                str(decision_path),
                "--output",
                str(sign_off_path),
                "--signed-off-at",
                f"2026-06-2{welle}T08:00:00Z",
            ]
        )
        assert rc == 0, f"emitter rc={rc} for welle {welle}"

    # 2. populate Tomas / Noa / Selin / Amara streams
    if write_complete_marker:
        marker_path = state_dir / "phase-3-complete-marker.json"
        marker_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "status": marker_status,
                    "wellen_complete": len(welle_outcomes),
                    "completed_at": "2026-06-29T18:00:00Z",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if write_cross_welle_envelope:
        cross_path = tmp_path / "out" / "cross-welle-hot-spot-verdict.json"
        cross_path.parent.mkdir(parents=True, exist_ok=True)
        cross_path.write_text(
            json.dumps(
                {
                    "schema": "wakir.phase-3c.cross-welle-hot-spot/1",
                    "verdict": "CLEAR",
                    "wellen_observed": list(welle_outcomes.keys()),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if write_history_and_drift:
        history_path = state_dir / "aggregator-failure-rate-history.json"
        history_path.write_text(
            json.dumps(
                [
                    {"run_id": "r1", "conclusion": "success"},
                    {"run_id": "r2", "conclusion": "success"},
                    {"run_id": "r3", "conclusion": "success"},
                ],
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        drift_path = state_dir / "cross-welle-drift-histograms.json"
        drift_path.write_text(
            json.dumps(
                {
                    f"welle-{w}": {"drift_buckets": [0, 0, 0]}
                    for w in WELLE_SHAPES
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if write_marathon_state:
        marathon_path = state_dir / "phase-3-marathon-state.json"
        marathon_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "wellen": {
                        f"welle-{w}-{WELLE_SHAPES[w]['long'].replace('_', '-')}": {
                            "cutover_runs_python_fallback": 5,
                            "cutover_runs_rust": 95,
                            "cutover_runs_total": 100,
                            "decision_latency_ms_samples": [100.0, 120.0],
                            "last_sample_at": "2026-06-29T08:00:00Z",
                        }
                        for w in WELLE_SHAPES
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    # 3. drive aggregator end-to-end via main()
    args = [
        "--state-dir",
        str(state_dir),
        "--cross-welle-envelope",
        str(tmp_path / "out" / "cross-welle-hot-spot-verdict.json"),
        "--output-dir",
        str(reports_dir),
        "--snapshot-at",
        "2026-06-29T20:00:00Z",
        "--mode",
        mode,
    ]
    rc = agg.main(args)
    assert rc == 0
    md_path = reports_dir / "marathon-final-bilanz.md"
    json_path = reports_dir / "marathon-final-bilanz.json"
    assert md_path.exists()
    assert json_path.exists()
    return json.loads(json_path.read_text("utf-8"))


# --- E2E scenarios ---------------------------------------------------------


def test_happy_path_marathon_ready(tmp_path):
    """All seven Welle decisions READY + COMPLETE-marker -> MARATHON_READY."""
    welle_outcomes = {w: "READY" for w in WELLE_SHAPES}
    envelope = _run_marathon_loop(
        tmp_path=tmp_path,
        welle_outcomes=welle_outcomes,
        write_complete_marker=True,
        marker_status="COMPLETE",
        mode="post-welle-7",
    )
    assert envelope["aggregate"]["verdict"] == "MARATHON_READY"
    slot_counts = envelope["aggregate"]["slot_counts"]
    assert slot_counts["READY"] == 5
    assert slot_counts["BROKEN"] == 0
    assert slot_counts["PENDING"] == 0
    # Henrik slot READY: all sign-offs audit_ok=true.
    henrik = next(s for s in envelope["slots"] if s["persona"] == "henrik")
    assert henrik["status"] == "READY"
    # All seven Welle slugs present in the roster.
    roster = envelope["sign_off_roster"]
    assert len(roster) == len(WELLE_SHAPES)
    for entry in roster:
        assert entry["present"] is True
        assert entry["audit_ok"] is True


def test_mid_marathon_daily_mode_is_in_flight(tmp_path):
    """Only Welle-1..3 sign-offs present, no COMPLETE-marker, daily mode.
    Expected: MARATHON_IN_FLIGHT (mid-marathon normal state).
    """
    welle_outcomes = {1: "READY", 2: "READY", 3: "READY"}
    envelope = _run_marathon_loop(
        tmp_path=tmp_path,
        welle_outcomes=welle_outcomes,
        write_complete_marker=False,
        mode="daily",
    )
    assert envelope["aggregate"]["verdict"] == "MARATHON_IN_FLIGHT"
    henrik = next(s for s in envelope["slots"] if s["persona"] == "henrik")
    assert henrik["status"] == "PARTIAL"
    assert envelope["aggregate"]["sign_offs_present"] == 3


def test_mid_marathon_post_welle_7_mode_is_broken(tmp_path):
    """Same mid-marathon state but post-welle-7 mode -> MARATHON_BROKEN.

    Rationale: in post-welle-7 mode every persona is expected to have
    delivered; PENDING slots are loud-failure.
    """
    welle_outcomes = {1: "READY", 2: "READY", 3: "READY"}
    envelope = _run_marathon_loop(
        tmp_path=tmp_path,
        welle_outcomes=welle_outcomes,
        write_complete_marker=False,
        write_history_and_drift=False,
        write_marathon_state=False,
        write_cross_welle_envelope=False,
        mode="post-welle-7",
    )
    assert envelope["aggregate"]["verdict"] == "MARATHON_BROKEN"
    # Multiple slots PENDING since we suppressed the state files.
    slot_counts = envelope["aggregate"]["slot_counts"]
    assert slot_counts["PENDING"] >= 1


def test_block_path_welle_7_blocks_marathon_ready(tmp_path):
    """Six Welle READY + Welle-7 BLOCK -> not MARATHON_READY."""
    welle_outcomes = {w: "READY" for w in WELLE_SHAPES}
    welle_outcomes[7] = "BLOCK"
    envelope = _run_marathon_loop(
        tmp_path=tmp_path,
        welle_outcomes=welle_outcomes,
        write_complete_marker=True,
        marker_status="IN_PROGRESS",
        mode="daily",
    )
    assert envelope["aggregate"]["verdict"] != "MARATHON_READY"
    henrik = next(s for s in envelope["slots"] if s["persona"] == "henrik")
    # Sign-offs all present but one audit_ok=false -> PARTIAL.
    assert henrik["status"] == "PARTIAL"
    welle_7_entry = next(
        e for e in envelope["sign_off_roster"]
        if e["welle"] == "welle-7-recovery-workflow"
    )
    assert welle_7_entry["audit_ok"] is False


def test_caution_path_welle_6_marks_henrik_partial(tmp_path):
    """Welle-6 CAUTION yields audit_ok=false in the sign-off envelope.

    Confirms that the emitter's CAUTION-> audit_ok=false mapping flows
    through to the aggregator's Henrik slot as PARTIAL (so CAUTION
    surfaces to Mira-Hand before live-smoke).
    """
    welle_outcomes = {w: "READY" for w in WELLE_SHAPES}
    welle_outcomes[6] = "CAUTION"
    envelope = _run_marathon_loop(
        tmp_path=tmp_path,
        welle_outcomes=welle_outcomes,
        write_complete_marker=True,
        marker_status="COMPLETE",
        mode="post-welle-7",
    )
    assert envelope["aggregate"]["verdict"] != "MARATHON_READY"
    welle_6_entry = next(
        e for e in envelope["sign_off_roster"]
        if e["welle"] == "welle-6-subscribe-loop"
    )
    assert welle_6_entry["audit_ok"] is False
    # The Welle-6 sign-off file itself records the CAUTION verdict.
    sign_off = json.loads(
        (tmp_path / "state" / "welle-6-sign-off.json").read_text("utf-8")
    )
    assert sign_off["verdict"] == "CAUTION"
    assert any("CAUTION" in n for n in sign_off["notes"])


def test_loop_output_files_are_well_formed(tmp_path):
    """The aggregator's two output files are valid JSON / non-empty Markdown."""
    welle_outcomes = {w: "READY" for w in WELLE_SHAPES}
    envelope = _run_marathon_loop(
        tmp_path=tmp_path,
        welle_outcomes=welle_outcomes,
        write_complete_marker=True,
        mode="post-welle-7",
    )
    md_path = tmp_path / "reports" / "marathon-final-bilanz.md"
    md_content = md_path.read_text("utf-8")
    assert md_content.startswith("# Phase-3 Marathon-Final-Bilanz")
    # All seven Welle slugs surface in the rendered roster.
    for w in WELLE_SHAPES.values():
        long_dashed = w["long"].replace("_", "-")
        assert long_dashed in md_content
    # Envelope contains the expected top-level keys.
    for k in (
        "schema_version",
        "snapshot_at",
        "mode",
        "aggregate",
        "slots",
        "sign_off_roster",
    ):
        assert k in envelope
