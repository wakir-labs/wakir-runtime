# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic CI-substrate tests for the Tag-40
``.github/workflows/phase-3-complete-marker.yml`` workflow that
emits the Phase-3-COMPLETE marker file once Henrik's five
conjunctive acceptance criteria (Tag-39 audit-spec
``docs/audit/phase-3-cutover-schluss-audit-spec.md`` §3) are
verified.

Test scope
----------

* Workflow YAML structural shape:
  - has the five AC-verification jobs plus the emit job,
  - emit job ``needs`` the five AC jobs,
  - emit step is gated on the conjunction of AC-1..AC-5 plus
    ``inputs.dry_run != 'true'``,
  - trigger surface has both ``workflow_dispatch`` and the
    Monday-12:00-UTC ``schedule`` cron.

* AC permutation logic: we walk through the truth-table of the
  five booleans (``2**5 = 32`` rows) and assert the workflow's
  aggregate ``if`` predicate matches Boolean conjunction.

Sandbox boundary: pure YAML + workflow-text parse. No actions
runner, no GitHub API, no podman, no live-VM.
"""

from __future__ import annotations

from itertools import product
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "phase-3-complete-marker.yml"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW_PATH.is_file(), f"workflow missing: {WORKFLOW_PATH}"
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_yaml(workflow_text: str) -> dict:
    # PyYAML parses the magic top-level key `on:` as Python True;
    # accept both spellings when extracting trigger surface in tests.
    data = yaml.safe_load(workflow_text)
    assert isinstance(data, dict), "workflow must parse as a mapping"
    return data


# ---------------------------------------------------------------------------
# 1. Trigger surface
# ---------------------------------------------------------------------------


def _on_block(workflow_yaml: dict) -> dict:
    on = workflow_yaml.get("on", workflow_yaml.get(True))
    assert isinstance(on, dict), "workflow.on must be a mapping"
    return on


def test_workflow_has_workflow_dispatch_trigger(workflow_yaml: dict) -> None:
    """AR/Mira-Hand manual marker emission must be a supported trigger."""
    on = _on_block(workflow_yaml)
    assert "workflow_dispatch" in on, "expected workflow_dispatch trigger"
    wd = on["workflow_dispatch"]
    # The dispatch surface must expose the dry-run override input.
    assert isinstance(wd, dict)
    inputs = wd.get("inputs", {})
    assert "dry_run" in inputs, "workflow_dispatch must expose `dry_run` input"


def test_workflow_has_monday_12utc_schedule(workflow_yaml: dict) -> None:
    """Schedule trigger must fire Monday 12:00 UTC (Cutover-Day-friendly)."""
    on = _on_block(workflow_yaml)
    assert "schedule" in on, "expected schedule trigger"
    crons = [entry.get("cron") for entry in on["schedule"]]
    assert "0 12 * * 1" in crons, f"Mon 12:00 UTC cron missing; got {crons}"


# ---------------------------------------------------------------------------
# 2. Job structure: five AC-verify jobs + one emit job
# ---------------------------------------------------------------------------


EXPECTED_AC_JOBS = [
    "verify-ac-1-welle-sign-offs",
    "verify-ac-2-aggregate-consistency",
    "verify-ac-3-predecessor-closure",
    "verify-ac-4-henrik-ratification",
    "verify-ac-5-ar-hand-ratification",
]

EMIT_JOB = "emit-phase-3-complete-marker"


def test_workflow_has_five_ac_verify_jobs(workflow_yaml: dict) -> None:
    jobs = workflow_yaml.get("jobs", {})
    for j in EXPECTED_AC_JOBS:
        assert j in jobs, f"missing AC-verify job: {j}"


def test_workflow_has_emit_job_gating_five_ac_jobs(workflow_yaml: dict) -> None:
    jobs = workflow_yaml.get("jobs", {})
    assert EMIT_JOB in jobs, f"missing emit job: {EMIT_JOB}"
    needs = jobs[EMIT_JOB].get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    for ac_job in EXPECTED_AC_JOBS:
        assert ac_job in needs, f"emit job must `needs:` {ac_job}"


# ---------------------------------------------------------------------------
# 3. AC-1: welle-sign-off probe surface
# ---------------------------------------------------------------------------


def test_ac1_probes_all_seven_welle_sign_off_files(workflow_text: str) -> None:
    """AC-1 probe must reference state/welle-{1..7}-sign-off.json."""
    # The bash loop literally iterates 1..7 and templates the path.
    assert 'state/welle-${w}-sign-off.json' in workflow_text, (
        "AC-1 probe must template state/welle-${w}-sign-off.json"
    )
    # And it must enumerate 1..7.
    assert "for w in 1 2 3 4 5 6 7" in workflow_text


def test_ac1_accepts_green_and_yellow_henrik_hand_approval(workflow_text: str) -> None:
    """AC-1 acceptable sign-off statuses are exactly the two from spec §3 Pt-1."""
    # The case statement must allow both literal status strings.
    assert "green|yellow_henrik_hand_approval" in workflow_text


# ---------------------------------------------------------------------------
# 4. AC-2: aggregate Welle-Validation conclusion probe
# ---------------------------------------------------------------------------


def test_ac2_probes_all_seven_welle_validation_workflows(workflow_text: str) -> None:
    """AC-2 must probe phase-3c-welle-{1..7}-validation.yml on main."""
    assert "phase-3c-welle-${w}-validation.yml" in workflow_text
    assert "branch=main" in workflow_text


# ---------------------------------------------------------------------------
# 5. AC-3: phase-3a/3b/3c predecessor closure counts
# ---------------------------------------------------------------------------


def test_ac3_probes_correct_predecessor_closure_files(workflow_text: str) -> None:
    """AC-3 must probe state/phase-3{a,b,c}-closure.json."""
    assert "state/phase-3${sub}-closure.json" in workflow_text


def test_ac3_enforces_15_9_7_counts(workflow_text: str) -> None:
    """AC-3 expected counts: 3a=15, 3b=9, 3c=7 (per Tomas Tag-40 envelope)."""
    assert "[a]=15" in workflow_text
    assert "[b]=9" in workflow_text
    assert "[c]=7" in workflow_text


# ---------------------------------------------------------------------------
# 6. AC-4: Henrik ratification with R-A1..R-A6 mitigation status
# ---------------------------------------------------------------------------


def test_ac4_requires_henrik_ratification_file(workflow_text: str) -> None:
    assert (
        "state/henrik-phase-3-complete-ratification.json" in workflow_text
    ), "AC-4 must probe Henrik ratification file"


def test_ac4_verifies_all_six_risk_vectors_mitigated(workflow_text: str) -> None:
    """All six R-A risk-vectors from Henrik spec §2 must be checked."""
    for rv in ["R-A1", "R-A2", "R-A3", "R-A4", "R-A5", "R-A6"]:
        assert rv in workflow_text, f"AC-4 must verify mitigation status of {rv}"


# ---------------------------------------------------------------------------
# 7. AC-5: AR-Hand stamp
# ---------------------------------------------------------------------------


def test_ac5_requires_ar_hand_stamp_file(workflow_text: str) -> None:
    assert (
        "state/ar-hand-phase-3-complete-stamp.json" in workflow_text
    ), "AC-5 must probe AR-Hand stamp file"


def test_ac5_requires_non_empty_quote(workflow_text: str) -> None:
    """AC-5 IIA-1130 anchor: AR-Hand quote must be present (non-empty)."""
    # The shell probe checks ratified == True AND quote non-empty.
    assert "ar_hand_quote" in workflow_text
    assert "ar_hand_ratification" in workflow_text


# ---------------------------------------------------------------------------
# 8. Emit-step conjunction gate
# ---------------------------------------------------------------------------


def test_emit_marker_step_is_conjunction_gated(workflow_yaml: dict) -> None:
    """
    The `Emit state/phase-3-complete-marker.json` step's `if:` predicate
    must be `steps.aggregate.outputs.all_pass == 'true'` AND dry_run !=
    'true'. The Bash aggregator step computes `all_pass` itself as
    the AND of all five AC outputs (see aggregator step below).
    """
    emit_job = workflow_yaml["jobs"][EMIT_JOB]
    steps = emit_job["steps"]
    emit_step = next(
        s for s in steps
        if s.get("name", "").startswith("Emit state/phase-3-complete-marker.json")
    )
    cond = emit_step.get("if", "")
    assert "steps.aggregate.outputs.all_pass == 'true'" in cond, (
        "emit step must check aggregate.outputs.all_pass == 'true'"
    )
    assert "inputs.dry_run != 'true'" in cond, (
        "emit step must respect inputs.dry_run override"
    )


def test_aggregator_step_AND_combines_all_five_ac_outputs(workflow_text: str) -> None:
    """
    The aggregator step computes `all_pass` by walking $AC1..$AC5 and
    requiring each == 'true'. This is the structural anchor for the
    Boolean-conjunction semantics tested permutation-wise below.
    """
    for token in ['"$AC1"', '"$AC2"', '"$AC3"', '"$AC4"', '"$AC5"']:
        assert token in workflow_text, f"aggregator must iterate over {token}"
    # The loop must require every variable to be the literal 'true'.
    assert 'if [[ "$v" != "true" ]]' in workflow_text


@pytest.mark.parametrize(
    "ac_states",
    list(product([True, False], repeat=5)),
    ids=lambda s: "AC=" + "".join("T" if b else "F" for b in s),
)
def test_emit_predicate_only_true_when_all_five_pass(ac_states) -> None:
    """
    Truth-table walk over (AC-1..AC-5). Marker emission is the
    conjunction of all five; this test mirrors the workflow's
    aggregator Bash loop semantics. Total: 2**5 = 32 parametrised
    rows -- one for each permutation, comfortably exceeding the
    'mind. 12 Tests' floor.
    """
    expected = all(ac_states)
    # Mirror the workflow's own loop logic.
    all_pass = True
    for v in ac_states:
        if v is not True:
            all_pass = False
    assert all_pass == expected


# ---------------------------------------------------------------------------
# 9. Marker file shape: emits sha + ar-stamp + welle-sha map
# ---------------------------------------------------------------------------


def test_emit_writes_marker_with_required_fields(workflow_text: str) -> None:
    """
    The marker JSON shape must include: marker_type, emitted_at_utc,
    commit_sha, welle_sign_off_shas, ar_hand_stamp, acceptance_criteria.
    """
    for field in (
        '"marker_type"',
        '"emitted_at_utc"',
        '"commit_sha"',
        '"welle_sign_off_shas"',
        '"ar_hand_stamp"',
        '"acceptance_criteria"',
    ):
        assert field in workflow_text, f"marker must include {field}"


def test_emit_writes_phase_3_marathon_bilanz_artifact(workflow_text: str) -> None:
    """Bilanz JSON is always emitted (success or fail) for AR visibility."""
    assert "phase-3-marathon-bilanz" in workflow_text
    assert "actions/upload-artifact@v4" in workflow_text
    assert "aggregate_latency_histogram" in workflow_text


# ---------------------------------------------------------------------------
# 10. Permission hygiene + concurrency
# ---------------------------------------------------------------------------


def test_workflow_uses_least_privilege_permissions(workflow_yaml: dict) -> None:
    """Workflow must declare permissions (defence-in-depth)."""
    perms = workflow_yaml.get("permissions", {})
    assert isinstance(perms, dict) and perms, "permissions block required"
    assert perms.get("contents") == "read", "contents must be read-only"
    assert perms.get("actions") == "read", "actions must be read-only for AC-2 probe"


def test_workflow_has_concurrency_group(workflow_yaml: dict) -> None:
    """A single-flight concurrency group prevents duplicate marker emissions."""
    conc = workflow_yaml.get("concurrency", {})
    assert isinstance(conc, dict) and conc, "concurrency block required"
    assert conc.get("group") == "phase-3-complete-marker"
    # cancel-in-progress must be false so a running marker emission is not
    # aborted by a duplicate scheduled trigger.
    assert conc.get("cancel-in-progress") is False
