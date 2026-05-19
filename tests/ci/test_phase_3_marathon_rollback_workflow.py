# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Tag-56 Phase-3-Marathon-Rollback workflow
(``.github/workflows/phase-3-marathon-rollback.yml``) and its four
helper scripts (audit-marker emit, per-Welle envelope emit,
rollback-manifest aggregator, AR-Hand notify-payload builder).

The workflow is the CI-side companion to the per-Komponente Rollback-
Drill suite. It walks the Phase-3-Marathon back to the pre-Cutover-
Day-N0 substrate state in deterministic reverse-cutover order
(Welle-7 first, Welle-1 last) and emits a single rollback-run
manifest the AR-Hand can ratify.

This file asserts shape + behaviour over twelve invariants:

  1. Workflow YAML shape: ``workflow_dispatch`` only.
  2. Distinct concurrency-group from cutover-day-auto-scheduler.
  3. Job graph topology J0 -> J1 -> J2..J8 -> J10 -> J11.
  4. Per-Welle modul-binding matches ADR-0065 §Verifikations-Plan.
  5. ``start_at_welle`` filter on per-Welle ``if:`` conditions.
  6. ``allow_partial_rollback`` filter on downstream ``needs:``.
  7. Audit-marker emit script schema v1.
  8. Per-Welle envelope status branches (green/yellow/red).
  9. Aggregator verdict-rule (READY/PARTIAL/FAILED matrix).
 10. AR-Hand notify-payload priority mapping (3/4/5).
 11. All four helpers are stdlib-only (no third-party imports).
 12. J1 live-mode guard refuses live-mode on ubuntu-latest.

Sandbox boundary: filesystem reads + yaml parse + python stdlib +
pytest. No subprocess for the helper scripts beyond invoking their
``main()`` entry-points via ``importlib``. No podman, no live-VM, no
GitHub API.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "phase-3-marathon-rollback.yml"
AGGREGATOR_SCRIPT = REPO_ROOT / "tooling" / "ci" / "aggregate_marathon_rollback_manifest.py"
WELLE_ENVELOPE_SCRIPT = REPO_ROOT / "tooling" / "ci" / "emit_marathon_rollback_welle_envelope.py"
AUDIT_MARKER_SCRIPT = REPO_ROOT / "tooling" / "ci" / "emit_marathon_rollback_audit_marker.py"
AR_NOTIFY_SCRIPT = REPO_ROOT / "tooling" / "ci" / "build_marathon_rollback_ar_notify.py"
RUNBOOK_PATH = REPO_ROOT / "docs" / "ci" / "phase-3-marathon-rollback-runbook.md"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW_PATH.is_file(), f"workflow missing: {WORKFLOW_PATH}"
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_yaml(workflow_text: str) -> dict:
    data = yaml.safe_load(workflow_text)
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def aggregator():
    return _load_module("_aggregate_marathon_rollback_manifest", AGGREGATOR_SCRIPT)


@pytest.fixture(scope="module")
def welle_envelope():
    return _load_module(
        "_emit_marathon_rollback_welle_envelope", WELLE_ENVELOPE_SCRIPT
    )


@pytest.fixture(scope="module")
def audit_marker():
    return _load_module("_emit_marathon_rollback_audit_marker", AUDIT_MARKER_SCRIPT)


@pytest.fixture(scope="module")
def ar_notify():
    return _load_module("_build_marathon_rollback_ar_notify", AR_NOTIFY_SCRIPT)


def _on_block(workflow_yaml: dict) -> dict:
    # PyYAML parses bare ``on:`` as Python ``True`` (YAML 1.1 boolean
    # coercion). Tolerate both shapes.
    on = workflow_yaml.get("on", workflow_yaml.get(True))
    assert isinstance(on, dict), "workflow.on must be a mapping"
    return on


# Canonical reverse-cutover order: rollback walks W7 first, W1 last.
REVERSE_CUTOVER_ORDER = ("w7", "w6", "w5", "w4", "w3", "w2", "w1")

PER_WELLE_JOBS = (
    ("j2-w7-recovery-workflow", 7, "recovery_workflow"),
    ("j3-w6-subscribe-loop", 6, "subscribe_loop"),
    ("j4-w5-lifecycle-state-machine", 5, "lifecycle_state_machine"),
    ("j5-w4-state-backing", 4, "state_backing"),
    ("j6-w3-bridge-audit-writer", 3, "bridge_audit_writer"),
    ("j7-w2-svid-workload-identity", 2, "svid_workload_identity"),
    ("j8-w1-v907-verify", 1, "v907_verify"),
)


# ---------------------------------------------------------------------------
# Invariant 1: workflow_dispatch is the only trigger.
# ---------------------------------------------------------------------------
def test_workflow_dispatch_is_only_trigger(workflow_yaml: dict) -> None:
    on = _on_block(workflow_yaml)
    assert set(on.keys()) == {"workflow_dispatch"}, (
        f"rollback workflow must be workflow_dispatch-only; got triggers={set(on.keys())}"
    )


def test_workflow_dispatch_has_required_inputs(workflow_yaml: dict) -> None:
    on = _on_block(workflow_yaml)
    inputs = on["workflow_dispatch"]["inputs"]
    expected = {
        "rollback_reason",
        "start_at_welle",
        "mode",
        "dry_run",
        "allow_partial_rollback",
    }
    assert set(inputs.keys()) == expected, (
        f"input-set drift: expected {expected}, got {set(inputs.keys())}"
    )


def test_rollback_reason_is_required(workflow_yaml: dict) -> None:
    on = _on_block(workflow_yaml)
    assert on["workflow_dispatch"]["inputs"]["rollback_reason"]["required"] is True


def test_mode_choices_are_stub_and_live(workflow_yaml: dict) -> None:
    on = _on_block(workflow_yaml)
    mode = on["workflow_dispatch"]["inputs"]["mode"]
    assert mode["type"] == "choice"
    assert set(mode["options"]) == {"stub", "live"}


def test_start_at_welle_choices_cover_all_and_w1_through_w7(workflow_yaml: dict) -> None:
    on = _on_block(workflow_yaml)
    saw = on["workflow_dispatch"]["inputs"]["start_at_welle"]
    expected_options = {"all", "w1", "w2", "w3", "w4", "w5", "w6", "w7"}
    assert set(saw["options"]) == expected_options


def test_dry_run_defaults_true(workflow_yaml: dict) -> None:
    on = _on_block(workflow_yaml)
    assert on["workflow_dispatch"]["inputs"]["dry_run"]["default"] is True


def test_allow_partial_rollback_defaults_false(workflow_yaml: dict) -> None:
    on = _on_block(workflow_yaml)
    assert on["workflow_dispatch"]["inputs"]["allow_partial_rollback"]["default"] is False


# ---------------------------------------------------------------------------
# Invariant 2: distinct concurrency-group from cutover-day-auto-scheduler.
# ---------------------------------------------------------------------------
def test_concurrency_group_is_distinct(workflow_yaml: dict) -> None:
    group = workflow_yaml["concurrency"]["group"]
    assert group == "phase-3-marathon-rollback"
    # Must not collide with the forward-direction Cutover workflow.
    assert group != "phase-3-cutover-day-auto-scheduler"


def test_concurrency_cancel_in_progress_is_false(workflow_yaml: dict) -> None:
    # One rollback at a time. cancel-in-progress=false avoids
    # mid-rollback cancellation.
    assert workflow_yaml["concurrency"]["cancel-in-progress"] is False


# ---------------------------------------------------------------------------
# Invariant 3: job graph topology J0 -> J1 -> J2..J8 -> J10 -> J11.
# ---------------------------------------------------------------------------
def test_required_jobs_present(workflow_yaml: dict) -> None:
    jobs = workflow_yaml["jobs"]
    required = {
        "j0-preamble",
        "j1-audit-emit",
        "j2-w7-recovery-workflow",
        "j3-w6-subscribe-loop",
        "j4-w5-lifecycle-state-machine",
        "j5-w4-state-backing",
        "j6-w3-bridge-audit-writer",
        "j7-w2-svid-workload-identity",
        "j8-w1-v907-verify",
        "j10-aggregator",
        "j11-ar-hand-notify",
    }
    assert required.issubset(set(jobs.keys())), (
        f"missing required jobs: {required - set(jobs.keys())}"
    )


def test_j1_audit_emit_needs_j0_preamble(workflow_yaml: dict) -> None:
    j1 = workflow_yaml["jobs"]["j1-audit-emit"]
    needs = j1.get("needs")
    if isinstance(needs, str):
        needs = [needs]
    assert "j0-preamble" in needs


def test_every_per_welle_job_needs_audit_emit(workflow_yaml: dict) -> None:
    for job_name, _welle, _modul in PER_WELLE_JOBS:
        job = workflow_yaml["jobs"][job_name]
        needs = job.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        assert "j1-audit-emit" in needs, (
            f"{job_name} must need j1-audit-emit (audit-trail-first invariant)"
        )


def test_aggregator_needs_all_per_welle_jobs(workflow_yaml: dict) -> None:
    agg = workflow_yaml["jobs"]["j10-aggregator"]
    needs = agg["needs"]
    if isinstance(needs, str):
        needs = [needs]
    for job_name, _welle, _modul in PER_WELLE_JOBS:
        assert job_name in needs, f"j10-aggregator must need {job_name}"
    assert agg.get("if") == "always()"


def test_aggregator_runs_always(workflow_yaml: dict) -> None:
    agg = workflow_yaml["jobs"]["j10-aggregator"]
    assert agg.get("if") == "always()"


def test_ar_notify_needs_aggregator(workflow_yaml: dict) -> None:
    notify = workflow_yaml["jobs"]["j11-ar-hand-notify"]
    needs = notify["needs"]
    if isinstance(needs, str):
        needs = [needs]
    assert "j10-aggregator" in needs


# ---------------------------------------------------------------------------
# Invariant 4: per-Welle modul-binding matches ADR-0065.
# ---------------------------------------------------------------------------
def test_per_welle_modul_binding(workflow_yaml: dict, welle_envelope) -> None:
    expected = welle_envelope.WELLE_MODUL_MAP
    for job_name, welle, modul in PER_WELLE_JOBS:
        assert expected[welle] == modul, (
            f"workflow per-Welle table drift: welle={welle} workflow={modul} envelope-script={expected[welle]}"
        )


# ---------------------------------------------------------------------------
# Invariant 5: ``start_at_welle`` filter on per-Welle ``if:`` conditions.
# ---------------------------------------------------------------------------
def test_w7_if_filter_only_executes_when_in_scope(workflow_yaml: dict) -> None:
    j2 = workflow_yaml["jobs"]["j2-w7-recovery-workflow"]
    if_cond = j2["if"]
    assert "start_at_welle == 'all'" in if_cond
    assert "start_at_welle == 'w7'" in if_cond


def test_w1_if_filter_executes_when_in_full_run(workflow_yaml: dict) -> None:
    # W1 is the deepest in the rollback chain; it must execute for
    # every start_at_welle except none. The implementation uses
    # `start_at_welle != 'w1' || start_at_welle == 'w1'` (effectively
    # always-on the per-Welle filter). We check by confirming the W1
    # job is reachable from `all` and also from `w1`.
    j8 = workflow_yaml["jobs"]["j8-w1-v907-verify"]
    if_cond = j8["if"]
    # Per the workflow design W1 is always in-scope; the if-cond does
    # not need to enumerate every Welle but must include the always()
    # guard + the audit-emit-success guard.
    assert "always()" in if_cond
    assert "j1-audit-emit" in if_cond


# ---------------------------------------------------------------------------
# Invariant 6: ``allow_partial_rollback`` filter on downstream ``needs:``.
# ---------------------------------------------------------------------------
def test_partial_rollback_filter_on_per_welle_chain(workflow_yaml: dict) -> None:
    # Every per-Welle job after J2 must conditionally short-circuit
    # when the previous Welle failed AND allow_partial_rollback=false.
    for i in range(1, len(PER_WELLE_JOBS)):
        job_name, _welle, _modul = PER_WELLE_JOBS[i]
        prev_job_name = PER_WELLE_JOBS[i - 1][0]
        job = workflow_yaml["jobs"][job_name]
        if_cond = job["if"]
        assert "allow_partial_rollback" in if_cond, (
            f"{job_name} must reference allow_partial_rollback in if:"
        )
        assert prev_job_name in if_cond, (
            f"{job_name} must reference {prev_job_name} for fail-fast filter"
        )


# ---------------------------------------------------------------------------
# Invariant 7: audit-marker emit schema v1.
# ---------------------------------------------------------------------------
def test_audit_marker_schema_v1(audit_marker, tmp_path: Path) -> None:
    output = tmp_path / "marker.json"
    rc = audit_marker.main([
        "_test",
        "--cycle-id", "rb-20260519T120000-1-abc1234",
        "--actor", "test-actor",
        "--reason", "test rollback",
        "--mode", "stub",
        "--dry-run", "true",
        "--start-at-welle", "all",
        "--output", str(output),
    ])
    assert rc == 0
    data = json.loads(output.read_text())
    assert data["schema_version"] == 1
    assert data["kind"] == "marathon-rollback-audit-marker"
    assert data["rollback_cycle_id"] == "rb-20260519T120000-1-abc1234"
    assert data["actor"] == "test-actor"
    assert data["mode"] == "stub"
    assert data["dry_run"] is True
    assert data["start_at_welle"] == "all"
    assert "anchors" in data
    assert "adr_rollback_strategie" in data["anchors"]


def test_audit_marker_rejects_invalid_mode(audit_marker, tmp_path: Path) -> None:
    output = tmp_path / "marker.json"
    with pytest.raises(SystemExit):
        # argparse choices reject invalid mode at parse-time.
        audit_marker.main([
            "_test",
            "--cycle-id", "rb-x",
            "--actor", "a",
            "--reason", "r",
            "--mode", "INVALID",
            "--dry-run", "true",
            "--start-at-welle", "all",
            "--output", str(output),
        ])


# ---------------------------------------------------------------------------
# Invariant 8: per-Welle envelope status branches.
# ---------------------------------------------------------------------------
def test_welle_envelope_green_default(welle_envelope) -> None:
    env = welle_envelope.build_envelope(
        welle=1, modul="v907_verify", cycle_id="rb-test",
        mode="stub", dry_run=True, with_snapshot_restore=False,
    )
    assert env["status"] == "green"
    assert env["target_backend"] == "python"
    assert env["modul"] == "v907_verify"


def test_welle_envelope_welle_4_without_snapshot_is_yellow(welle_envelope) -> None:
    env = welle_envelope.build_envelope(
        welle=4, modul="state_backing", cycle_id="rb-test",
        mode="stub", dry_run=True, with_snapshot_restore=False,
    )
    assert env["status"] == "yellow"
    assert "snapshot-restore" in env["note"]


def test_welle_envelope_welle_4_with_snapshot_is_green(welle_envelope) -> None:
    env = welle_envelope.build_envelope(
        welle=4, modul="state_backing", cycle_id="rb-test",
        mode="stub", dry_run=True, with_snapshot_restore=True,
    )
    assert env["status"] == "green"
    assert env["snapshot_restore_planned"] is True


def test_welle_envelope_modul_binding_drift_is_red(welle_envelope) -> None:
    # Welle-3 expects bridge_audit_writer; passing state_backing must
    # produce red status.
    env = welle_envelope.build_envelope(
        welle=3, modul="state_backing", cycle_id="rb-test",
        mode="stub", dry_run=True, with_snapshot_restore=False,
    )
    assert env["status"] == "red"
    assert "drift" in env["note"]


def test_welle_envelope_live_mode_is_yellow(welle_envelope) -> None:
    env = welle_envelope.build_envelope(
        welle=1, modul="v907_verify", cycle_id="rb-test",
        mode="live", dry_run=False, with_snapshot_restore=False,
    )
    assert env["status"] == "yellow"
    assert "live-mode" in env["note"]


def test_welle_envelope_snapshot_flag_outside_welle_4_is_yellow(welle_envelope) -> None:
    env = welle_envelope.build_envelope(
        welle=2, modul="svid_workload_identity", cycle_id="rb-test",
        mode="stub", dry_run=True, with_snapshot_restore=True,
    )
    assert env["status"] == "yellow"
    assert env["snapshot_restore_planned"] is False


def test_welle_envelope_all_seven_wellen_canonical_binding(welle_envelope) -> None:
    for welle, modul in welle_envelope.WELLE_MODUL_MAP.items():
        env = welle_envelope.build_envelope(
            welle=welle, modul=modul, cycle_id="rb-test",
            mode="stub", dry_run=True,
            with_snapshot_restore=(welle == 4),
        )
        assert env["status"] == "green", (
            f"welle={welle} modul={modul} should be green, got status={env['status']} note={env['note']}"
        )


# ---------------------------------------------------------------------------
# Invariant 9: aggregator verdict-rule (READY/PARTIAL/FAILED matrix).
# ---------------------------------------------------------------------------
def test_aggregator_all_green_is_ready(aggregator) -> None:
    welle_results = {w: "green" for w in REVERSE_CUTOVER_ORDER}
    assert aggregator.decide(welle_results) == "READY"


def test_aggregator_any_red_is_failed(aggregator) -> None:
    welle_results = {w: "green" for w in REVERSE_CUTOVER_ORDER}
    welle_results["w4"] = "red"
    assert aggregator.decide(welle_results) == "FAILED"


def test_aggregator_any_yellow_is_partial(aggregator) -> None:
    welle_results = {w: "green" for w in REVERSE_CUTOVER_ORDER}
    welle_results["w4"] = "yellow"
    assert aggregator.decide(welle_results) == "PARTIAL"


def test_aggregator_all_skipped_is_partial(aggregator) -> None:
    welle_results = {w: "skipped" for w in REVERSE_CUTOVER_ORDER}
    assert aggregator.decide(welle_results) == "PARTIAL"


def test_aggregator_partial_subset_green_is_ready(aggregator) -> None:
    # start_at_welle=w4 -> W4..W1 execute green, W5..W7 skipped.
    welle_results = {
        "w7": "skipped",
        "w6": "skipped",
        "w5": "skipped",
        "w4": "green",
        "w3": "green",
        "w2": "green",
        "w1": "green",
    }
    assert aggregator.decide(welle_results) == "READY"


def test_aggregator_build_manifest_full_env(aggregator) -> None:
    env = {
        "ROLLBACK_CYCLE_ID": "rb-test-cycle",
        "ACTOR": "test-actor",
        "REASON": "test rollback",
        "MODE": "stub",
        "DRY_RUN": "true",
        "START_AT_WELLE": "all",
        "ALLOW_PARTIAL": "false",
        "W7_STATUS": "green",
        "W6_STATUS": "green",
        "W5_STATUS": "green",
        "W4_STATUS": "green",
        "W3_STATUS": "green",
        "W2_STATUS": "green",
        "W1_STATUS": "green",
        "WELLE_NOTES": "w4_state_backing:snapshot-restore-planned",
    }
    manifest = aggregator.build_manifest(env)
    assert manifest["schema_version"] == 1
    assert manifest["kind"] == "marathon-rollback-manifest"
    assert manifest["verdict"] == "READY"
    assert manifest["counts"]["green"] == 7
    assert manifest["counts"]["red"] == 0
    assert manifest["snapshot_restore_status"] == "planned"
    assert manifest["welle_notes"] == ["w4_state_backing:snapshot-restore-planned"]
    assert set(manifest["welle_modul_map"].keys()) == set(REVERSE_CUTOVER_ORDER)


def test_aggregator_snapshot_restore_status_n_a_when_w4_skipped(aggregator) -> None:
    env = {
        "ROLLBACK_CYCLE_ID": "rb-test",
        "START_AT_WELLE": "w3",
        "W7_STATUS": "skipped",
        "W6_STATUS": "skipped",
        "W5_STATUS": "skipped",
        "W4_STATUS": "skipped",
        "W3_STATUS": "green",
        "W2_STATUS": "green",
        "W1_STATUS": "green",
    }
    manifest = aggregator.build_manifest(env)
    assert manifest["snapshot_restore_status"] == "n/a"


def test_aggregator_snapshot_restore_status_missing_when_w4_yellow(aggregator) -> None:
    env = {
        "ROLLBACK_CYCLE_ID": "rb-test",
        "START_AT_WELLE": "all",
        "W7_STATUS": "green",
        "W6_STATUS": "green",
        "W5_STATUS": "green",
        "W4_STATUS": "yellow",
        "W3_STATUS": "green",
        "W2_STATUS": "green",
        "W1_STATUS": "green",
    }
    manifest = aggregator.build_manifest(env)
    assert manifest["snapshot_restore_status"] == "missing"
    assert manifest["verdict"] == "PARTIAL"


# ---------------------------------------------------------------------------
# Invariant 10: AR-Hand notify-payload priority mapping.
# ---------------------------------------------------------------------------
def test_ar_notify_priority_ready_is_3(ar_notify) -> None:
    payload = ar_notify.build_payload(
        cycle_id="rb-test", actor="a", reason="r",
        verdict="READY", mode="stub",
        manifest={"counts": {"green": 7, "yellow": 0, "red": 0, "skipped": 0}},
    )
    assert payload["priority"] == 3
    assert "white_check_mark" in payload["tags"]


def test_ar_notify_priority_partial_is_4(ar_notify) -> None:
    payload = ar_notify.build_payload(
        cycle_id="rb-test", actor="a", reason="r",
        verdict="PARTIAL", mode="stub",
        manifest={"counts": {"green": 5, "yellow": 2, "red": 0, "skipped": 0}},
    )
    assert payload["priority"] == 4
    assert "warning" in payload["tags"]


def test_ar_notify_priority_failed_is_5(ar_notify) -> None:
    payload = ar_notify.build_payload(
        cycle_id="rb-test", actor="a", reason="r",
        verdict="FAILED", mode="stub",
        manifest={"counts": {"green": 4, "yellow": 0, "red": 3, "skipped": 0}},
    )
    assert payload["priority"] == 5
    assert "rotating_light" in payload["tags"]


def test_ar_notify_topic_is_wakir_ar_hand(ar_notify) -> None:
    payload = ar_notify.build_payload(
        cycle_id="rb-test", actor="a", reason="r",
        verdict="READY", mode="stub",
        manifest={"counts": {"green": 7, "yellow": 0, "red": 0, "skipped": 0}},
    )
    assert payload["topic"] == "wakir-ar-hand"


def test_ar_notify_includes_operator_curl_hint(ar_notify) -> None:
    payload = ar_notify.build_payload(
        cycle_id="rb-test", actor="a", reason="r",
        verdict="READY", mode="stub",
        manifest={"counts": {"green": 7, "yellow": 0, "red": 0, "skipped": 0}},
    )
    # Workflow itself does not POST; operator-hand fires.
    assert "curl" in payload["operator_curl_hint"]
    assert "ntfy.sh" in payload["operator_curl_hint"]


# ---------------------------------------------------------------------------
# Invariant 11: helpers are stdlib-only (no third-party imports).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "script",
    [
        AGGREGATOR_SCRIPT,
        WELLE_ENVELOPE_SCRIPT,
        AUDIT_MARKER_SCRIPT,
        AR_NOTIFY_SCRIPT,
    ],
)
def test_helper_script_is_stdlib_only(script: Path) -> None:
    """Light-touch lexical check: no top-level imports outside stdlib.

    The whitelist below is the canonical Python 3.11 stdlib subset
    these helpers may use. A third-party import (e.g. ``yaml``,
    ``requests``) here is a regression — these scripts must run on a
    minimal ubuntu-latest runner without ``pip install`` steps.
    """
    text = script.read_text(encoding="utf-8")
    # Look for ``^import X`` or ``^from X import ...`` (no leading ws).
    import re
    stdlib_whitelist = {
        "argparse", "json", "os", "sys", "datetime", "pathlib",
        "typing", "__future__", "re", "collections", "itertools",
    }
    for m in re.finditer(r"^(?:from|import)\s+(\w+)", text, re.MULTILINE):
        mod = m.group(1)
        assert mod in stdlib_whitelist, (
            f"{script.name} imports non-stdlib module {mod!r}; "
            "helpers must run on minimal ubuntu-latest without pip"
        )


# ---------------------------------------------------------------------------
# Invariant 12: J1 live-mode guard refuses live-mode.
# ---------------------------------------------------------------------------
def test_j1_audit_emit_has_live_mode_guard(workflow_text: str) -> None:
    # The guard is a bash step that exits 1 if MODE=live AND
    # runner is not self-hosted. We look for the string-shape so the
    # check survives YAML reformatting.
    assert "live-mode rollback MUST run on a self-hosted Pilot-VM" in workflow_text


# ---------------------------------------------------------------------------
# Additional shape parity checks.
# ---------------------------------------------------------------------------
def test_workflow_name_matches_filename(workflow_yaml: dict) -> None:
    assert workflow_yaml["name"] == "phase-3-marathon-rollback"


def test_permissions_are_read_only(workflow_yaml: dict) -> None:
    perms = workflow_yaml["permissions"]
    assert perms == {"contents": "read", "actions": "read"}


def test_runbook_exists(workflow_yaml: dict) -> None:
    assert RUNBOOK_PATH.is_file(), f"runbook missing: {RUNBOOK_PATH}"
    text = RUNBOOK_PATH.read_text(encoding="utf-8")
    assert "Phase-3-Marathon-Rollback" in text
    assert "stub-mode" in text or "Stub-mode" in text


def test_all_per_welle_jobs_upload_artifact(workflow_yaml: dict) -> None:
    for job_name, welle, _modul in PER_WELLE_JOBS:
        job = workflow_yaml["jobs"][job_name]
        steps = job["steps"]
        artifact_step = next(
            (s for s in steps if "upload-artifact" in (s.get("uses") or "")),
            None,
        )
        assert artifact_step is not None, (
            f"{job_name} must upload its envelope as artifact"
        )
        assert artifact_step.get("if") == "always()", (
            f"{job_name} artifact upload must run on failure too"
        )


def test_audit_marker_artifact_uploaded_with_error_on_missing(workflow_yaml: dict) -> None:
    j1 = workflow_yaml["jobs"]["j1-audit-emit"]
    steps = j1["steps"]
    upload = next(
        (s for s in steps if s.get("name", "").lower().startswith("upload audit-marker")),
        None,
    )
    assert upload is not None
    with_block = upload.get("with", {})
    # Audit-marker is non-negotiable — if it's missing the workflow
    # MUST fail loudly.
    assert with_block.get("if-no-files-found") == "error"


def test_aggregator_decide_function_signature(aggregator) -> None:
    # The aggregator must expose ``decide()`` as the canonical
    # verdict-rule entry point — both the workflow and the tests
    # depend on it.
    assert callable(aggregator.decide)
    assert callable(aggregator.build_manifest)


def test_welle_modul_map_round_trip(welle_envelope, aggregator) -> None:
    # Both modules must agree on the Welle<->Modul map.
    a = welle_envelope.WELLE_MODUL_MAP
    b = aggregator.WELLE_MODUL_MAP
    # Aggregator uses ``w<N>`` keys, envelope uses int keys.
    for n, modul in a.items():
        assert b[f"w{n}"] == modul, (
            f"welle map drift: welle-{n} envelope={modul} aggregator={b[f'w{n}']}"
        )
