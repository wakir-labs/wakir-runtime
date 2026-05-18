# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic CI-substrate tests for the Tag-39 promotion of
``.github/workflows/phase-3c-welle-6-validation.yml`` to the Welle-3
pattern (PR #238, ``0e54699``).

Tag-39 promotes the Welle-6 validation workflow from the Tag-32
4-step bundle stub to the Welle-3 strict pattern with the same
additions Tag-38 applied to Welle-5 (PR #248):

  1. ``push:`` trigger with Welle-6-relevant path-filter.
  2. Pre-flight smoke step (subscribe_loop-resolver smoke via the
     cutover-dry-run in single-boot mode).
  3. Subscribe-Loop-Lag-Histogramm-Integrity-Check + Phantom-Bucket-
     Detection (Welle-6-specific equivalent of Welle-3's Self-
     Reference-Trap detector and Welle-5's FSM-Transition-Integrity
     detector; guards against silent lag-histogramm-drift between
     Python and Rust resolvers).
  4. Cross-Modul-Drift to Welle-7 ``recovery_workflow`` (symmetric A7
     pendant) with strict ``drift > 0 = BLOCK`` threshold (same
     posture as Welle-3 and Welle-5, stricter than Welle-1/2's
     ``drift > 1 = CAUTION``).
  5. Decision-Aggregation with READY/CAUTION/BLOCK verdict +
     Go/No-Go field + hard_block_reasons list.
  6. Operator-Playbook comment-block referencing Kai's Welle-6
     runbook plus the Welle-7 Doppel-Welle partner runbook.

Sandbox boundary: pure YAML + workflow-text parse. No actions runner,
no podman, no GHCR egress, no live-VM.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "phase-3c-welle-6-validation.yml"
)


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_yaml(workflow_text: str) -> dict:
    return yaml.safe_load(workflow_text)


@pytest.fixture(scope="module")
def validation_job(workflow_yaml: dict) -> dict:
    return workflow_yaml["jobs"]["phase-3c-welle-6-validation"]


@pytest.fixture(scope="module")
def validation_steps(validation_job: dict) -> List[dict]:
    return list(validation_job.get("steps") or [])


@pytest.fixture(scope="module")
def steps_by_id(validation_steps: List[dict]) -> dict:
    return {s.get("id"): s for s in validation_steps if s.get("id")}


# ---------------------------------------------------------------------------
# Test 1 - push-to-main trigger with Welle-6-relevant path-filter.
# ---------------------------------------------------------------------------


def test_push_trigger_with_welle_6_path_filter(workflow_yaml: dict) -> None:
    """Tag-39 addition: the workflow must also fire on push-to-main
    when a Welle-6-relevant path changes. The path-filter MUST include
    the workflow self, the core substrate scripts, the persona-engine
    rust-backend-switch test file, the acceptance test, this hermetic
    test, the Welle-6 runbook, AND the Welle-7 partner runbook (the
    Cross-Modul-Drift axis depends on both workflows' substrate)."""
    on = workflow_yaml.get(True) or workflow_yaml.get("on")
    assert on is not None
    push = on.get("push")
    assert push is not None, "missing push trigger (Tag-39 addition)"
    assert push.get("branches") == ["main"], (
        f"push trigger must scope to main; got: {push.get('branches')!r}"
    )
    paths = push.get("paths") or []
    required_paths = {
        ".github/workflows/phase-3c-welle-6-validation.yml",
        "scripts/phase-3c-trigger-gate-aggregator.py",
        "scripts/phase-3c-cutover-dry-run.py",
        "scripts/doppelbetrieb-score-aggregator.py",
        "wirelang/tests/persona_engine/test_rust_backend_switch.py",
        "tests/acceptance/phase_3c/test_welle_6_subscribe_loop_e2e.py",
        "tests/ci/test_phase_3c_welle_6_validation.py",
        "docs/operations/phase-3c-welle-6-runbook.md",
        "docs/operations/phase-3c-welle-7-runbook.md",
    }
    missing = required_paths - set(paths)
    assert not missing, (
        f"push path-filter missing Welle-6-relevant entries: {missing}"
    )


# ---------------------------------------------------------------------------
# Test 2 - pre-flight smoke step exists, calls cutover-dry-run in
# single-boot mode, runs before the gate-aggregator.
# ---------------------------------------------------------------------------


def test_pre_flight_smoke_runs_before_gate_aggregator(
    steps_by_id: dict,
    validation_steps: List[dict],
) -> None:
    """Tag-39 addition: a pre-flight smoke step with id
    ``pre-flight-smoke`` must run the cutover-dry-run in single-boot
    mode (boots=1) against the ``subscribe_loop`` component, BEFORE
    the gate-aggregator step. The step must record the result via
    ``pre-flight-smoke.outputs.ok`` for the decision step to consume.
    """
    assert "pre-flight-smoke" in steps_by_id, (
        "missing pre-flight smoke step (Tag-39 addition)"
    )
    pre_flight = steps_by_id["pre-flight-smoke"]
    run_block = pre_flight.get("run") or ""
    assert "phase-3c-cutover-dry-run.py" in run_block, (
        "pre-flight smoke must call phase-3c-cutover-dry-run.py "
        "(the subscribe_loop-resolver smoke substrate)"
    )
    assert "--boots 1" in run_block, (
        "pre-flight smoke must use single-boot mode (--boots 1)"
    )
    assert (
        "WELLE_COMPONENT" in run_block
        or "--component subscribe_loop" in run_block
    ), (
        "pre-flight smoke must target the subscribe_loop component"
    )
    # Step must record ok=true|false output for the decision step.
    assert "ok=true" in run_block and "ok=false" in run_block, (
        "pre-flight smoke must emit ok=true|false output"
    )
    # Order: pre-flight-smoke before gate-aggregator.
    ids_in_order = [s.get("id") for s in validation_steps]
    pre_idx = ids_in_order.index("pre-flight-smoke")
    gate_idx = ids_in_order.index("gate-aggregator")
    assert pre_idx < gate_idx, (
        "pre-flight smoke must run before the gate-aggregator step"
    )


# ---------------------------------------------------------------------------
# Test 3 - Subscribe-Loop-Lag-Histogramm-Integrity step exists with
# phantom + missing bucket detection.
# ---------------------------------------------------------------------------


def test_subscribe_loop_lag_integrity_step_present(
    steps_by_id: dict,
    workflow_text: str,
) -> None:
    """Tag-39 addition: a Welle-6-specific Subscribe-Loop-Lag-
    Histogramm-Integrity-Check step must exist (id
    ``subscribe-loop-lag-integrity``) and inspect the dry-run envelope
    for phantom + missing bucket sets. The step must record an
    ``integrity_violation`` signal in the
    ``subscribe-loop-lag-integrity.json`` artifact for the decision
    step to consume.
    """
    assert "subscribe-loop-lag-integrity" in steps_by_id, (
        "missing Subscribe-Loop-Lag-Integrity step (Tag-39 addition)"
    )
    step = steps_by_id["subscribe-loop-lag-integrity"]
    run_block = step.get("run") or ""
    # The step must reference the dry-run envelope as input.
    assert "dry-run-envelope.json" in run_block, (
        "Subscribe-Loop-Lag-Integrity step must inspect "
        "dry-run-envelope.json"
    )
    # The step must surface both phantom + missing bucket concepts.
    assert "phantom_buckets" in run_block, (
        "Subscribe-Loop-Lag-Integrity step must check for "
        "phantom_buckets"
    )
    assert "missing_buckets" in run_block, (
        "Subscribe-Loop-Lag-Integrity step must check for "
        "missing_buckets"
    )
    # The step must emit an integrity_violation signal.
    assert "integrity_violation" in run_block, (
        "Subscribe-Loop-Lag-Integrity step must emit an "
        "integrity_violation signal"
    )
    # The step must write subscribe-loop-lag-integrity.json artifact.
    assert "subscribe-loop-lag-integrity.json" in run_block, (
        "Subscribe-Loop-Lag-Integrity step must write "
        "subscribe-loop-lag-integrity.json"
    )


# ---------------------------------------------------------------------------
# Test 4 - Cross-Modul-Drift step exists with symmetric A7 posture
# to Welle-7, strict drift > 0 = BLOCK threshold.
# ---------------------------------------------------------------------------


def test_cross_modul_drift_symmetric_a7_pendant_strict(
    steps_by_id: dict,
) -> None:
    """Tag-39 addition: a Cross-Modul-Drift step with id
    ``cross-modul-drift`` must exist, run the doppelbetrieb-score-
    aggregator in cross-modul-stress mode, AND apply a strict
    ``drift > 0 = BLOCK`` threshold via inline parse. The step must
    record the drift verdict in ``cross-modul-drift.json`` AND
    declare itself the symmetric A7 pendant to Welle-7 (the workflow
    that runs the mirror check from recovery_workflow's perspective).
    """
    assert "cross-modul-drift" in steps_by_id, (
        "missing Cross-Modul-Drift step (Tag-39 addition)"
    )
    step = steps_by_id["cross-modul-drift"]
    run_block = step.get("run") or ""
    # Must call the doppelbetrieb-score-aggregator in cross-modul-
    # stress mode.
    assert "doppelbetrieb-score-aggregator.py" in run_block
    assert "cross-modul-stress" in run_block, (
        "drift step must use cross-modul-stress aggregator mode"
    )
    # Strict drift > 0 = BLOCK threshold (Welle-3/5 posture).
    assert "drift_gt_0_equals_block" in run_block, (
        "drift step must declare strict drift>0=BLOCK policy"
    )
    # Symmetric A7 pendant to Welle-7 recovery_workflow.
    assert "symmetric_a7_pendant" in run_block, (
        "drift step must mark itself the symmetric A7 pendant"
    )
    assert "recovery_workflow" in run_block, (
        "drift step must declare recovery_workflow as Doppel-Welle "
        "partner"
    )
    # Must write cross-modul-drift.json artifact.
    assert "cross-modul-drift.json" in run_block, (
        "drift step must write cross-modul-drift.json"
    )


# ---------------------------------------------------------------------------
# Test 5 - Decision step produces verdict + go/no-go + hard-block-
# reasons fields, schema v2, exit reflects verdict.
# ---------------------------------------------------------------------------


def test_decision_step_emits_verdict_go_no_go_hard_block(
    steps_by_id: dict,
) -> None:
    """Tag-39 addition: the decision step must emit the v2 schema with
    READY/CAUTION/BLOCK verdict, a Go/No-Go field, a
    hard_block_reasons list, and exit-code semantics that map
    verdict-in-{READY,CAUTION} to exit 0 and BLOCK to exit 1.
    """
    assert "decision" in steps_by_id
    step = steps_by_id["decision"]
    run_block = step.get("run") or ""

    # v2 schema (Tag-39 promotion from Tag-32 v1 stub to Welle-3-
    # pattern v2).
    assert "wakir.phase-3c.welle-6-validation/2" in run_block, (
        "decision step must emit schema v2 (Tag-39 promotion)"
    )
    # Verdict trichotomy.
    for token in ("READY", "CAUTION", "BLOCK"):
        assert f'"{token}"' in run_block or f"'{token}'" in run_block, (
            f"decision step must produce verdict={token} branch"
        )
    # Go/No-Go field.
    assert '"go_no_go"' in run_block
    # Hard-block reasons list.
    assert "hard_block_reasons" in run_block
    # Hard-block reason strings the verdict logic must produce.
    for reason in (
        "pre_flight_smoke_failed",
        "subscribe_loop_lag_integrity_violated",
        "cross_modul_drift_nonzero",
        "trigger_gate_aggregator_red",
        "dry_run_failed",
        "persona_boot_failed",
        "bridge_audit_roundtrip_failed",
        "feasibility_band_below_floor",
    ):
        assert reason in run_block, (
            f"decision step must surface hard-block reason "
            f"{reason!r}"
        )
    # Exit-code semantics: verdict in (READY, CAUTION) -> 0; BLOCK -> 1.
    assert "sys.exit(0 if verdict in" in run_block, (
        "decision step must exit 0 for READY/CAUTION verdicts"
    )


# ---------------------------------------------------------------------------
# Test 6 - Decision envelope wiring: all upstream-step exit-codes
# flow into the decision step env block.
# ---------------------------------------------------------------------------


def test_decision_step_env_wires_all_upstream_outputs(
    steps_by_id: dict,
) -> None:
    """The decision step must wire every upstream signal source
    (pre-flight smoke, gate-aggregator, dry-run, lag-integrity,
    persona-boot, bridge-audit, cross-modul-drift, score-band-floor,
    boots, binary-count) into its env block. Missing wiring means
    the verdict logic cannot see that signal.
    """
    step = steps_by_id["decision"]
    env_block = step.get("env") or {}
    required = {
        "GATE_RC",
        "DRY_RUN_RC",
        "BOOT_RC",
        "BRIDGE_RC",
        "STRESS_RC",
        "DRIFT_RC",
        "LAG_INTEGRITY_RC",
        "PREFLIGHT_RC",
        "PREFLIGHT_OK",
        "SCORE_BAND_FLOOR",
        "BOOTS_INPUT",
        "BIN_COUNT_INPUT",
    }
    missing = required - set(env_block.keys())
    assert not missing, (
        f"decision step env-block missing wiring: {missing}"
    )
    # Spot-check that the wiring expression references the upstream
    # step output (not a literal string).
    for key in ("LAG_INTEGRITY_RC", "DRIFT_RC", "PREFLIGHT_RC"):
        val = env_block[key]
        assert "steps." in str(val), (
            f"env wiring for {key} must reference a steps.* output; "
            f"got: {val!r}"
        )


# ---------------------------------------------------------------------------
# Test 7 - artifact upload includes all Tag-39 envelope inputs.
# ---------------------------------------------------------------------------


def test_artifact_upload_includes_tag_39_envelope_inputs(
    validation_steps: List[dict],
) -> None:
    """The upload-artifact step must include every artifact the
    Tag-39 pipeline produces, so an operator can re-derive the
    verdict from the artifact bundle alone.
    """
    upload = next(
        (
            s for s in validation_steps
            if (s.get("uses") or "").startswith("actions/upload-artifact")
        ),
        None,
    )
    assert upload is not None, "missing upload-artifact step"
    with_block = upload.get("with") or {}
    assert (
        with_block.get("name") == "cutover-acceptance-decision-welle-6"
    )
    paths_block = with_block.get("path") or ""
    required_paths = [
        "out/cutover-acceptance-decision.json",
        "out/trigger-gate-report.json",
        "out/dry-run-envelope.json",
        "out/persona-boot.log",
        "out/persona-boot-junit.xml",
        "out/bridge-audit.log",
        "out/bridge-audit-junit.xml",
        "out/cross-modul-stress.log",
        "out/cross-modul-stress-rollup.json",
        "out/cross-modul-drift.json",
        "out/subscribe-loop-lag-integrity.json",
        "out/pre-flight-snapshot.json",
        "out/pre-flight.log",
    ]
    for p in required_paths:
        assert p in paths_block, (
            f"artifact upload missing required path: {p}"
        )


# ---------------------------------------------------------------------------
# Test 8 - Operator-Playbook comment-block references Welle-6
# runbook + Welle-7 Doppel-Welle partner.
# ---------------------------------------------------------------------------


def test_operator_playbook_references_kai_runbook(
    workflow_text: str,
) -> None:
    """The Tag-39 promotion adds an Operator-Playbook comment-block
    explaining READY/CAUTION/BLOCK rules and anchoring to Kai's
    Welle-6 runbook (`docs/operations/phase-3c-welle-6-runbook.md`)
    AND the Welle-7 Doppel-Welle partner runbook (the Cross-Modul-
    Drift axis is symmetric between them).
    """
    assert "OPERATOR-PLAYBOOK" in workflow_text, (
        "missing Operator-Playbook comment-block (Tag-39 addition)"
    )
    # Verdict-rule labels.
    for label in ("READY", "CAUTION", "BLOCK"):
        marker = f"#   {label}"
        assert marker in workflow_text, (
            f"Operator-Playbook missing verdict rule label: {label}"
        )
    # Runbook anchors.
    assert (
        "docs/operations/phase-3c-welle-6-runbook.md" in workflow_text
    ), "Operator-Playbook must anchor to Kai's Welle-6 runbook"
    assert (
        "docs/operations/phase-3c-welle-7-runbook.md" in workflow_text
    ), (
        "Operator-Playbook must anchor to the Welle-7 Doppel-Welle "
        "partner runbook"
    )


# ---------------------------------------------------------------------------
# Test 9 - Triggers cover schedule, workflow_dispatch, and push;
# schedule cron matches the canonical Wednesday-06UTC slot.
# ---------------------------------------------------------------------------


def test_trigger_surface_schedule_dispatch_push(
    workflow_yaml: dict,
) -> None:
    """The workflow must keep the three trigger types: schedule
    (Wednesday 06:00 UTC canonical slot), workflow_dispatch (with
    the standard three dispatch inputs), and push-to-main with the
    Welle-6-relevant path-filter.
    """
    on = workflow_yaml.get(True) or workflow_yaml.get("on")
    assert on is not None
    schedule = on.get("schedule")
    assert schedule, "missing schedule trigger"
    crons = [entry.get("cron") for entry in schedule]
    assert "0 6 * * 3" in crons, (
        f"schedule cron must include Wednesday 06:00 UTC; got: {crons}"
    )
    dispatch = on.get("workflow_dispatch")
    assert dispatch is not None, "missing workflow_dispatch trigger"
    inputs = (dispatch or {}).get("inputs") or {}
    required_inputs = {"target-binary-count", "boots", "score-band-floor"}
    missing = required_inputs - set(inputs.keys())
    assert not missing, (
        f"workflow_dispatch missing inputs: {missing}"
    )
    push = on.get("push")
    assert push is not None
    assert push.get("branches") == ["main"]


# ---------------------------------------------------------------------------
# Test 10 - decision step always-runs and references the welle_7
# partner workflow anchor in the envelope.
# ---------------------------------------------------------------------------


def test_decision_step_runs_always_and_anchors_welle_7_partner(
    steps_by_id: dict,
) -> None:
    """The decision step must run even if upstream steps red
    (`if: always()`), so the decision artifact captures the failure
    state. The emitted envelope must anchor the Welle-7 Doppel-Welle
    partner workflow path so an operator can navigate to the mirror
    drift-check from the artifact alone.
    """
    step = steps_by_id["decision"]
    if_clause = step.get("if")
    assert if_clause == "always()" or if_clause is True, (
        f"decision step must use if: always(); got: {if_clause!r}"
    )
    run_block = step.get("run") or ""
    assert "phase-3c-welle-7-validation.yml" in run_block, (
        "decision envelope must anchor the Welle-7 partner workflow"
    )
    # Verdict-band tolerance: dry-run feasibility band must compare
    # against the score-band-floor input.
    assert "band_order" in run_block, (
        "decision step must apply band-floor tolerance"
    )
    # ADR anchors in the envelope.
    for adr in ("0065", "0066"):
        assert adr in run_block, (
            f"decision envelope must anchor ADR-{adr}"
        )
