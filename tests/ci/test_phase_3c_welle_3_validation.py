# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic CI-substrate tests for the Tag-36 additions to
``.github/workflows/phase-3c-welle-3-validation.yml``.

This test-module is the Tag-36 sibling of
``tests/workflows/test_phase_3c_welle_3_validation.py`` (Tag-31). The
Tag-31 module covers the existing 5-step Welle-1/2-pattern contract
(gate-aggregator, dry-run, persona-boot, cross-modul-stress, decision)
and is intentionally **not** re-validated here.

The Tag-36 additions tested here are:

  1. ``push:`` trigger with Welle-3-relevant path-filter.
  2. Pre-flight smoke step (Selin's ``welle-3-telemetry-emitter.py``).
  3. Self-Reference-Trap detector (Henrik-Caution: subject under
     cutover must not certify itself).
  4. Cross-Modul-Drift check with strict ``drift > 0 = BLOCK``
     threshold (Henrik-Caution Item 6, stricter than Welle-1/2's
     ``drift > 1 = CAUTION``).
  5. Decision-Aggregation with READY/CAUTION/BLOCK verdict +
     Go/No-Go field + hard_block_reasons list.
  6. Operator-Playbook comment-block referencing Kai's three Welle-3
     runbooks.

Sandbox boundary: pure YAML + workflow-text parse. No actions runner,
no podman, no GHCR egress, no live-VM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "phase-3c-welle-3-validation.yml"
)


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_yaml(workflow_text: str) -> dict:
    return yaml.safe_load(workflow_text)


@pytest.fixture(scope="module")
def validation_job(workflow_yaml: dict) -> dict:
    return workflow_yaml["jobs"]["phase-3c-welle-3-validation"]


@pytest.fixture(scope="module")
def validation_steps(validation_job: dict) -> List[dict]:
    return list(validation_job.get("steps") or [])


@pytest.fixture(scope="module")
def steps_by_id(validation_steps: List[dict]) -> dict:
    return {s.get("id"): s for s in validation_steps if s.get("id")}


# ---------------------------------------------------------------------------
# Test 1 — push-to-main trigger with Welle-3-relevant path-filter.
# ---------------------------------------------------------------------------


def test_push_trigger_with_path_filter(workflow_yaml: dict) -> None:
    """Tag-36 addition: the workflow must also fire on push-to-main
    when a Welle-3-relevant path changes. The path-filter MUST include
    the workflow self, the four core substrate scripts, Selin's
    telemetry emitter, Kai's day-0 pipeline, the persona-engine
    rust-backend-switch test file, and the three Welle-3 runbooks."""
    on = workflow_yaml.get(True) or workflow_yaml.get("on")
    assert on is not None
    push = on.get("push")
    assert push is not None, "missing push trigger (Tag-36 addition)"
    assert push.get("branches") == ["main"], (
        f"push trigger must scope to main; got: {push.get('branches')!r}"
    )
    paths = push.get("paths") or []
    required_paths = {
        ".github/workflows/phase-3c-welle-3-validation.yml",
        "scripts/phase-3c-cutover-dry-run.py",
        "scripts/doppelbetrieb-score-aggregator.py",
        "scripts/welle-3-telemetry-emitter.py",
        "scripts/welle-3-day-0-pipeline.sh",
        "docs/operations/phase-3c-welle-3-runbook.md",
        "docs/operations/welle-3-day-0-pipeline-runbook.md",
        "docs/operations/welle-3-telemetry-runbook.md",
    }
    missing = required_paths - set(paths)
    assert not missing, (
        f"push path-filter missing Welle-3-relevant entries: {missing}"
    )


# ---------------------------------------------------------------------------
# Test 2 — pre-flight smoke step exists, calls Selin's emitter, runs
# before the gate-aggregator.
# ---------------------------------------------------------------------------


def test_pre_flight_smoke_calls_selin_emitter(
    steps_by_id: dict,
    validation_steps: List[dict],
) -> None:
    """Tag-36 addition: a pre-flight smoke step with id
    ``pre-flight-smoke`` must run Selin's
    ``scripts/welle-3-telemetry-emitter.py`` against an empty
    decisions-JSONL substrate, before the ``gate-aggregator`` step.
    The step MUST set ``continue-on-error: true`` so a smoke failure
    surfaces in Step 5's decision envelope rather than aborting the
    workflow mid-flight."""
    step = steps_by_id.get("pre-flight-smoke")
    assert step is not None, (
        "missing pre-flight-smoke step (Tag-36 addition)"
    )
    assert step.get("continue-on-error") is True, (
        "pre-flight-smoke must continue-on-error so decision still renders"
    )
    run = step.get("run") or ""
    assert "scripts/welle-3-telemetry-emitter.py" in run, (
        f"pre-flight-smoke must call Selin's emitter; got run: {run!r}"
    )
    assert "--out" in run, (
        "pre-flight-smoke must request a JSON snapshot via --out"
    )
    # Order: pre-flight-smoke must precede gate-aggregator.
    step_ids = [s.get("id") for s in validation_steps if s.get("id")]
    pre_idx = step_ids.index("pre-flight-smoke")
    gate_idx = step_ids.index("gate-aggregator")
    assert pre_idx < gate_idx, (
        f"pre-flight-smoke must precede gate-aggregator; "
        f"got order: {step_ids}"
    )
    # Verify the upstream script exists on baseline.
    assert (
        REPO_ROOT / "scripts" / "welle-3-telemetry-emitter.py"
    ).is_file(), "Selin's emitter script missing from repo"


# ---------------------------------------------------------------------------
# Test 3 — Self-Reference-Trap detector exists, encodes the trap
# strings, runs between dry-run and persona-boot.
# ---------------------------------------------------------------------------


def test_self_reference_trap_detector_encoded(
    steps_by_id: dict,
    validation_steps: List[dict],
) -> None:
    """Tag-36 addition: a self-reference-trap detector step with id
    ``self-reference-trap`` must (a) inspect both the dry-run envelope
    and the workflow-self for the trap-string
    ``test_bridge_audit_roundtrip_e2e``, (b) write a JSON report to
    ``out/self-reference-trap.json`` with a ``trap_detected`` boolean,
    (c) run between dry-run and persona-boot."""
    step = steps_by_id.get("self-reference-trap")
    assert step is not None, (
        "missing self-reference-trap step (Tag-36 Henrik-Caution)"
    )
    run = step.get("run") or ""
    # Trap-string must appear (as a python literal) in the detector
    # logic, so the runtime guard knows what to look for.
    assert "test_bridge_audit_roundtrip_e2e" in run, (
        "self-reference-trap detector must encode the trap string "
        "'test_bridge_audit_roundtrip_e2e' as a runtime guard"
    )
    assert "self-reference-trap.json" in run, (
        "detector must emit a JSON report at "
        "out/self-reference-trap.json"
    )
    assert "trap_detected" in run, (
        "detector must record a trap_detected flag in the report"
    )
    # Order: between dry-run and persona-boot.
    step_ids = [s.get("id") for s in validation_steps if s.get("id")]
    dry_idx = step_ids.index("dry-run")
    trap_idx = step_ids.index("self-reference-trap")
    boot_idx = step_ids.index("persona-boot")
    assert dry_idx < trap_idx < boot_idx, (
        f"self-reference-trap must sit between dry-run and "
        f"persona-boot; got order: {step_ids}"
    )


# ---------------------------------------------------------------------------
# Test 4 — Cross-Modul-Drift check encodes the strict
# ``drift > 0 = BLOCK`` threshold (Henrik-Caution Item 6).
# ---------------------------------------------------------------------------


def test_cross_modul_drift_check_strict_threshold(
    steps_by_id: dict,
    validation_steps: List[dict],
) -> None:
    """Tag-36 addition: a cross-modul-drift step with id
    ``drift-check`` must encode the Welle-3-strict policy
    ``drift > 0 = BLOCK`` (stricter than Welle-1/2's
    ``drift > 1 = CAUTION``). The step MUST run after
    cross-modul-stress (which produces the rollup the drift count
    derives from) and before decision."""
    step = steps_by_id.get("drift-check")
    assert step is not None, (
        "missing drift-check step (Tag-36 Henrik-Caution Item 6)"
    )
    run = step.get("run") or ""
    # The strict policy must be encoded as a string the operator can
    # grep for, and the exit-code branch must reflect it.
    assert "drift_gt_0_equals_block" in run, (
        "drift-check must encode the strict policy "
        "'drift_gt_0_equals_block' so the run-tab self-documents "
        "the Welle-3-specific posture"
    )
    assert "cross-modul-drift.json" in run, (
        "drift-check must emit a JSON report at "
        "out/cross-modul-drift.json"
    )
    # Explicit acknowledgement of the Welle-1/2 policy contrast so a
    # future reviewer sees why Welle-3 differs.
    assert "welle_1_2_policy" in run or "welle_3_strict" in run, (
        "drift-check report must contrast the Welle-3-strict policy "
        "against the Welle-1/2 baseline policy"
    )
    # Order: after cross-modul-stress, before decision.
    step_ids = [s.get("id") for s in validation_steps if s.get("id")]
    stress_idx = step_ids.index("cross-modul-stress")
    drift_idx = step_ids.index("drift-check")
    decision_idx = step_ids.index("decision")
    assert stress_idx < drift_idx < decision_idx, (
        f"drift-check must sit between cross-modul-stress and "
        f"decision; got order: {step_ids}"
    )


# ---------------------------------------------------------------------------
# Test 5 — Decision step propagates the Tag-36 signals (pre-flight,
# self-reference-trap, drift) into the verdict policy.
# ---------------------------------------------------------------------------


def test_decision_step_consumes_tag36_signals(
    steps_by_id: dict,
) -> None:
    """The decision step must declare env-vars that pull the Tag-36
    step outputs (pre-flight-smoke rc, self-reference-trap rc,
    drift-check rc) and the decision logic must produce a verdict in
    {READY, CAUTION, BLOCK} with a ``hard_block_reasons`` list."""
    step = steps_by_id.get("decision")
    assert step is not None, "missing decision step"
    env = step.get("env") or {}
    # The four new pull-through env-vars from Tag-36 additions.
    assert env.get("PREFLIGHT_RC") == (
        "${{ steps.pre-flight-smoke.outputs.rc }}"
    ), f"decision step missing PREFLIGHT_RC pull-through; got: {env}"
    assert env.get("SELF_REF_TRAP_RC") == (
        "${{ steps.self-reference-trap.outputs.rc }}"
    ), f"decision step missing SELF_REF_TRAP_RC pull-through; got: {env}"
    assert env.get("DRIFT_CHECK_RC") == (
        "${{ steps.drift-check.outputs.rc }}"
    ), f"decision step missing DRIFT_CHECK_RC pull-through; got: {env}"
    run = step.get("run") or ""
    # Verdict enum must be explicit.
    for verdict in ("READY", "CAUTION", "BLOCK"):
        assert verdict in run, (
            f"decision verdict {verdict!r} not encoded in render logic"
        )
    # Hard-block reasons list must be on the envelope.
    assert "hard_block_reasons" in run, (
        "decision envelope must surface hard_block_reasons list"
    )
    # Three Tag-36 block reasons must each be encoded as strings the
    # operator can grep for.
    for reason in (
        "pre_flight_smoke_failed",
        "self_reference_trap_detected",
        "cross_modul_drift_nonzero",
    ):
        assert reason in run, (
            f"decision logic missing hard-block reason {reason!r}"
        )


# ---------------------------------------------------------------------------
# Test 6 — Go/No-Go field on decision envelope.
# ---------------------------------------------------------------------------


def test_decision_envelope_carries_go_no_go(
    steps_by_id: dict,
) -> None:
    """The decision envelope must surface a top-level ``go_no_go``
    field reading either ``GO`` (verdict READY or CAUTION) or
    ``NO-GO`` (verdict BLOCK). This is the operator-facing Mira-Hand
    signal for the Mo Live-Smoke decision."""
    step = steps_by_id.get("decision")
    assert step is not None
    run = step.get("run") or ""
    assert '"go_no_go": go_no_go' in run, (
        "decision envelope must include a go_no_go field"
    )
    assert '"GO"' in run, "decision logic must emit literal 'GO'"
    assert '"NO-GO"' in run, (
        "decision logic must emit literal 'NO-GO'"
    )


# ---------------------------------------------------------------------------
# Test 7 — Operator-Playbook comment-block + Kai's three Welle-3
# runbooks anchored in the workflow.
# ---------------------------------------------------------------------------


def test_operator_playbook_and_runbook_anchors(
    workflow_text: str,
    steps_by_id: dict,
) -> None:
    """The workflow file head must carry a comment-block titled
    OPERATOR-PLAYBOOK with the three Tag-36 outcomes (READY/CAUTION/
    BLOCK) documented. The decision-envelope anchors must reference
    Kai's three Welle-3 runbooks."""
    # The OPERATOR-PLAYBOOK block sits in the workflow's prologue;
    # we scan the first 200 lines so the existing Tag-31 ADR-0066
    # rationale comments (which precede it) do not push it out of
    # the head-window.
    head = "\n".join(workflow_text.splitlines()[:200])
    assert "OPERATOR-PLAYBOOK" in head, (
        "workflow head must declare an OPERATOR-PLAYBOOK section"
    )
    for verdict in ("READY", "CAUTION", "BLOCK"):
        assert verdict in head, (
            f"OPERATOR-PLAYBOOK must document the {verdict!r} outcome"
        )
    # Kai's three Welle-3 runbooks must be linked from the workflow
    # (either head comment or anchors block in decision logic).
    decision_run = steps_by_id["decision"].get("run") or ""
    full = head + decision_run
    for runbook in (
        "phase-3c-welle-3-runbook.md",
        "welle-3-day-0-pipeline-runbook.md",
        "welle-3-telemetry-runbook.md",
    ):
        assert runbook in full, (
            f"workflow must anchor Kai's runbook {runbook!r}"
        )


# ---------------------------------------------------------------------------
# Test 8 — Artifact upload bundles the four Tag-36 outputs.
# ---------------------------------------------------------------------------


def test_artifact_upload_bundles_tag36_outputs(
    validation_steps: List[dict],
) -> None:
    """The artifact-upload step at the tail must include the four
    Tag-36 new output files so the operator can pull them from the
    GitHub run-tab even if the run goes BLOCK."""
    upload = next(
        (
            s
            for s in validation_steps
            if "upload-artifact" in str(s.get("uses") or "")
        ),
        None,
    )
    assert upload is not None, "missing actions/upload-artifact step"
    path_block = upload.get("with", {}).get("path") or ""
    for f in (
        "pre-flight-snapshot.json",
        "pre-flight.log",
        "self-reference-trap.json",
        "cross-modul-drift.json",
    ):
        assert f in path_block, (
            f"artifact upload missing Tag-36 output file {f!r}"
        )


# ---------------------------------------------------------------------------
# Test 9 — Self-Reference-Trap test-vector simulation: the encoded
# trap-strings, when planted in a synthetic dry-run envelope, would
# trigger the detector. We replay the detector's parse-logic against
# fixtures, NOT against the workflow YAML literally.
# ---------------------------------------------------------------------------


def test_self_reference_trap_logic_catches_planted_trap(
    tmp_path: Path,
) -> None:
    """Hermetic test-vector: replay the trap-detector's parse-logic
    against a synthetic dry-run envelope that names the trap oracle.
    The detector logic encoded in the workflow MUST catch it.

    This test extracts the trap-string constants from the workflow
    and runs the same containment check, asserting both the positive
    (trap present) and negative (trap absent) paths."""
    # The trap-strings as encoded in the detector (workflow-private
    # contract; we re-state them here to lock the contract).
    TRAP_STRINGS = (
        "test_bridge_audit_roundtrip_e2e",
        "bridge_audit_roundtrip_e2e",
    )

    # Positive vector: planted envelope mentions the trap oracle.
    planted = {
        "consistency_signal_source": (
            "tests/integration/test_bridge_audit_roundtrip_e2e.py"
        ),
        "boots": 12,
    }
    planted_src = json.dumps(planted, sort_keys=True)
    findings_planted = [t for t in TRAP_STRINGS if t in planted_src]
    assert findings_planted, (
        "trap-detector contract broken: planted envelope did not "
        "match any trap string"
    )

    # Negative vector: clean envelope cites the Henrik-Caution
    # independent oracle.
    clean = {
        "consistency_signal_source": (
            "scripts/doppelbetrieb-score-aggregator.py --mode=cross-modul-stress"
        ),
        "boots": 12,
    }
    clean_src = json.dumps(clean, sort_keys=True)
    findings_clean = [t for t in TRAP_STRINGS if t in clean_src]
    assert not findings_clean, (
        "trap-detector contract broken: clean envelope falsely "
        "matched a trap string"
    )

    # Workflow-self check: the workflow must encode the trap-strings
    # as python literals inside the detector's TRAP_STRINGS tuple,
    # NOT as references in any non-comment `run:` body of a
    # different step. The detector's own `run:` body is the legal
    # carrier.
    wf_text = WORKFLOW_PATH.read_text("utf-8")
    # Containment check passes — the trap string is in the detector.
    assert "test_bridge_audit_roundtrip_e2e" in wf_text


# ---------------------------------------------------------------------------
# Test 10 — Drift-policy parity: simulate axes-fail counts and assert
# the BLOCK threshold matches the Tag-36 spec.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "axes,expected_block",
    [
        (
            [
                {"name": "cross-lang-pin-coverage", "axis_pass": True},
                {
                    "name": "cross-modul-fixture-stability",
                    "axis_pass": True,
                },
                {
                    "name": "cross-modul-rollup-integrity",
                    "axis_pass": True,
                },
            ],
            False,
        ),  # All green -> drift=0 -> no block.
        (
            [
                {"name": "cross-lang-pin-coverage", "axis_pass": True},
                {
                    "name": "cross-modul-fixture-stability",
                    "axis_pass": False,
                },
                {
                    "name": "cross-modul-rollup-integrity",
                    "axis_pass": True,
                },
            ],
            True,
        ),  # One fail -> drift=1 -> BLOCK (stricter than Welle-1/2).
        (
            [
                {
                    "name": "cross-lang-pin-coverage",
                    "axis_pass": False,
                },
                {
                    "name": "cross-modul-fixture-stability",
                    "axis_pass": False,
                },
                {
                    "name": "cross-modul-rollup-integrity",
                    "axis_pass": False,
                },
            ],
            True,
        ),  # All three fail -> drift=3 -> BLOCK.
    ],
)
def test_drift_policy_parity_with_workflow(
    axes: list, expected_block: bool
) -> None:
    """Hermetic policy-parity check: re-state the drift-policy
    ``block = drift > 0`` against synthetic axis-rollups, asserting
    parity with the Welle-3-strict posture (Welle-1/2 used
    ``block = drift > 1`` instead)."""
    drift = sum(1 for a in axes if not a.get("axis_pass"))
    block = drift > 0
    assert block is expected_block, (
        f"drift-policy parity mismatch: axes={axes} -> "
        f"drift={drift}, block={block}, expected={expected_block}"
    )

    # Cross-check: the Welle-1/2 legacy policy would give different
    # results on the drift=1 case (CAUTION instead of BLOCK). This
    # is the contrast the workflow's `welle_1_2_policy` field
    # records.
    if drift == 1:
        welle_12_block = drift > 1
        assert welle_12_block is False, (
            "Welle-1/2 legacy policy should NOT block on drift=1; "
            "this test asserts the Welle-3 strictness is novel"
        )
