# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic CI-substrate tests for the Tag-41 Phase-3c Pre-Cutover-Sanity
workflow (``.github/workflows/phase-3c-pre-cutover-sanity.yml``) plus
its two helper scripts in ``tooling/ci/``.

Test scope
----------

* Workflow YAML structural shape:
  - three trigger sources (workflow_dispatch + schedule + push),
  - exactly five jobs in the documented order,
  - Step 5 (decision-aggregation) ``needs`` the four upstream steps
    and is gated on ``if: always()`` so it always runs,
  - Mon 06:00 UTC cron present,
  - push trigger path-filtered on the marathon substrates.

* Decision-aggregator semantics
  (``tooling/ci/aggregate_pre_cutover_sanity_verdict.py``):
  - Truth-table walk over all 3**4 = 81 (green|yellow|red)**4
    permutations of the four step-statuses; assert the verdict
    follows the documented rule.
  - Missing env-vars default to red.
  - Verdict-envelope JSON has the schema-required fields.

* Marker-workflow structural verifier
  (``tooling/ci/verify_marker_workflow_structure.py``):
  - Returns 0 for the real Tag-40 marker-workflow on this HEAD.
  - Returns 2 for a synthetic mutation that drops one AC-verify job.
  - Returns 1 for a corrupt YAML.

Sandbox boundary: pure file-system reads + python imports + yaml
parse. No subprocess, no podman, no live-VM, no GitHub API.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from itertools import product
from pathlib import Path
from typing import Iterable

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "phase-3c-pre-cutover-sanity.yml"
)
MARKER_WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "phase-3-complete-marker.yml"
)
AGGREGATOR_SCRIPT = (
    REPO_ROOT / "tooling" / "ci" / "aggregate_pre_cutover_sanity_verdict.py"
)
VERIFIER_SCRIPT = (
    REPO_ROOT / "tooling" / "ci" / "verify_marker_workflow_structure.py"
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    return _load_module(
        "_aggregate_pre_cutover_sanity_verdict", AGGREGATOR_SCRIPT
    )


@pytest.fixture(scope="module")
def verifier():
    return _load_module(
        "_verify_marker_workflow_structure", VERIFIER_SCRIPT
    )


def _on_block(workflow_yaml: dict) -> dict:
    on = workflow_yaml.get("on", workflow_yaml.get(True))
    assert isinstance(on, dict), "workflow.on must be a mapping"
    return on


# ---------------------------------------------------------------------------
# 1. Trigger surface
# ---------------------------------------------------------------------------


def test_workflow_has_workflow_dispatch_trigger(workflow_yaml: dict) -> None:
    on = _on_block(workflow_yaml)
    assert "workflow_dispatch" in on
    wd = on["workflow_dispatch"]
    assert isinstance(wd, dict)
    inputs = (wd.get("inputs") or {})
    assert "verbose" in inputs, "verbose input expected on workflow_dispatch"


def test_workflow_has_monday_06utc_schedule(workflow_yaml: dict) -> None:
    on = _on_block(workflow_yaml)
    assert "schedule" in on
    crons = [entry.get("cron") for entry in on["schedule"]]
    assert "0 6 * * 1" in crons, f"Mon 06:00 UTC cron missing; got {crons}"


def test_workflow_has_path_filtered_push_trigger(workflow_yaml: dict) -> None:
    on = _on_block(workflow_yaml)
    assert "push" in on, "push trigger missing"
    push = on["push"]
    assert isinstance(push, dict)
    branches = push.get("branches", [])
    assert "main" in branches, "push trigger must filter on main"
    paths = push.get("paths", [])
    assert any(p.startswith("scripts/phase-3c/") for p in paths), (
        "scripts/phase-3c/** path-filter expected"
    )
    assert any(p.startswith("docs/phase-3c/") for p in paths), (
        "docs/phase-3c/** path-filter expected"
    )


# ---------------------------------------------------------------------------
# 2. Job topology: five jobs in documented order, decision needs upstream
# ---------------------------------------------------------------------------


REQUIRED_JOBS = (
    "step-1-substanz-inventory-check",
    "step-2-cross-welle-generalprobe-dry-run",
    "step-3-marathon-tracker-state-check",
    "step-4-marker-workflow-dry-run",
    "step-5-decision-aggregation",
)


def test_workflow_has_exactly_five_jobs(workflow_yaml: dict) -> None:
    jobs = workflow_yaml.get("jobs", {})
    assert set(jobs.keys()) == set(REQUIRED_JOBS), (
        f"job set mismatch; got {sorted(jobs)}, want {sorted(REQUIRED_JOBS)}"
    )


def test_step5_needs_all_upstream_and_is_always(workflow_yaml: dict) -> None:
    job = workflow_yaml["jobs"]["step-5-decision-aggregation"]
    needs = job.get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    for upstream in REQUIRED_JOBS[:4]:
        assert upstream in needs, f"step-5 must need {upstream}"
    assert job.get("if") in ("always()", "${{ always() }}"), (
        f"step-5 must use `if: always()`; got {job.get('if')!r}"
    )


def test_step1_uses_required_actions(workflow_yaml: dict) -> None:
    job = workflow_yaml["jobs"]["step-1-substanz-inventory-check"]
    steps = job["steps"]
    assert any(s.get("uses", "").startswith("actions/checkout@") for s in steps)


# ---------------------------------------------------------------------------
# 3. Decision-aggregator truth-table (3 ** 4 = 81 permutations)
# ---------------------------------------------------------------------------


def _expected_verdict(s1: str, s2: str, s3: str, s4: str) -> str:
    states = (s1, s2, s3, s4)
    if any(s == "red" for s in states):
        return "BLOCK"
    yellows = sum(1 for s in states if s == "yellow")
    if yellows >= 2:
        return "BLOCK"
    if yellows == 1:
        return "CAUTION"
    if all(s == "green" for s in states):
        return "READY"
    return "BLOCK"


@pytest.mark.parametrize(
    "permutation",
    list(product(("green", "yellow", "red"), repeat=4)),
)
def test_aggregator_truth_table(aggregator, permutation, monkeypatch, tmp_path):
    s1, s2, s3, s4 = permutation
    monkeypatch.setenv("STEP1_STATUS", s1)
    monkeypatch.setenv("STEP2_STATUS", s2)
    monkeypatch.setenv("STEP3_STATUS", s3)
    monkeypatch.setenv("STEP4_STATUS", s4)
    monkeypatch.setenv("INVENTORY_MISSING", "")
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("GITHUB_REF", raising=False)
    envelope = aggregator.build_envelope(
        {
            "STEP1_STATUS": s1,
            "STEP2_STATUS": s2,
            "STEP3_STATUS": s3,
            "STEP4_STATUS": s4,
            "INVENTORY_MISSING": "",
        }
    )
    expected = _expected_verdict(s1, s2, s3, s4)
    assert envelope["verdict"] == expected, (
        f"states={permutation} expected={expected} got={envelope['verdict']}"
    )
    # Counts must be internally consistent.
    counts = envelope["counts"]
    assert counts["green"] + counts["yellow"] + counts["red"] == 4


def test_aggregator_missing_env_defaults_to_red(aggregator):
    envelope = aggregator.build_envelope({})
    assert envelope["verdict"] == "BLOCK"
    assert envelope["counts"]["red"] == 4
    for v in envelope["step_results"].values():
        assert v == "red"


def test_aggregator_unknown_status_is_red(aggregator):
    envelope = aggregator.build_envelope(
        {
            "STEP1_STATUS": "magenta",
            "STEP2_STATUS": "green",
            "STEP3_STATUS": "green",
            "STEP4_STATUS": "green",
        }
    )
    # One red (magenta -> red), three green -> BLOCK.
    assert envelope["verdict"] == "BLOCK"
    assert envelope["step_results"]["step_1_substanz_inventory_check"] == "red"


def test_aggregator_inventory_missing_recorded(aggregator):
    envelope = aggregator.build_envelope(
        {
            "STEP1_STATUS": "red",
            "STEP2_STATUS": "green",
            "STEP3_STATUS": "green",
            "STEP4_STATUS": "green",
            "INVENTORY_MISSING": "scripts/phase-3c/welle-1-x.py,docs/phase-3c/welle-7-y.md",
        }
    )
    assert envelope["inventory_missing"] == [
        "scripts/phase-3c/welle-1-x.py",
        "docs/phase-3c/welle-7-y.md",
    ]
    assert envelope["verdict"] == "BLOCK"


def test_aggregator_envelope_has_required_schema_fields(aggregator):
    envelope = aggregator.build_envelope(
        {
            "STEP1_STATUS": "green",
            "STEP2_STATUS": "green",
            "STEP3_STATUS": "green",
            "STEP4_STATUS": "green",
        }
    )
    required_keys = {
        "schema_version",
        "workflow",
        "emitted_at_utc",
        "verdict",
        "step_results",
        "failed_steps",
        "inventory_missing",
        "counts",
        "cross_substrate_links",
    }
    assert required_keys.issubset(envelope.keys()), (
        f"missing keys: {required_keys - envelope.keys()}"
    )
    assert envelope["workflow"] == "phase-3c-pre-cutover-sanity"
    assert envelope["schema_version"] == 1
    # Cross-substrate links must include the five paths called out in
    # the operator playbook.
    links = envelope["cross_substrate_links"]
    for key in (
        "cross_welle_generalprobe",
        "marathon_aggregat_tracker",
        "phase_3_complete_marker",
        "live_vm_cutover_drill",
        "phase_3_final_regression_suite",
    ):
        assert key in links


def test_aggregator_writes_output_file(aggregator, tmp_path, monkeypatch):
    out = tmp_path / "verdict.json"
    monkeypatch.setenv("STEP1_STATUS", "green")
    monkeypatch.setenv("STEP2_STATUS", "yellow")
    monkeypatch.setenv("STEP3_STATUS", "green")
    monkeypatch.setenv("STEP4_STATUS", "green")
    rc = aggregator.main(["aggregator", "--output", str(out)])
    assert rc == 0
    assert out.is_file()
    parsed = json.loads(out.read_text())
    assert parsed["verdict"] == "CAUTION"


# ---------------------------------------------------------------------------
# 4. Marker-workflow structural verifier
# ---------------------------------------------------------------------------


def test_verifier_passes_real_marker_workflow(verifier):
    rc = verifier.verify(MARKER_WORKFLOW_PATH)
    assert rc == 0, (
        "real marker workflow on HEAD must verify clean; "
        f"got rc={rc}. Marker substrate regressed."
    )


def test_verifier_rejects_missing_ac_job(verifier, tmp_path):
    # Synthesise a mutated marker-workflow that drops AC-3.
    src = MARKER_WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(src)
    data["jobs"].pop("verify-ac-3-predecessor-closure", None)
    mutant = tmp_path / "marker-mutant.yml"
    mutant.write_text(yaml.safe_dump(data), encoding="utf-8")
    rc = verifier.verify(mutant)
    assert rc == 2, f"expected rc=2 (structural-invalid); got {rc}"


def test_verifier_rejects_emit_without_needs_edge(verifier, tmp_path):
    src = MARKER_WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(src)
    emit = data["jobs"]["emit-phase-3-complete-marker"]
    # Break the needs-edge for AC-5 specifically.
    needs = emit.get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    needs = [n for n in needs if n != "verify-ac-5-ar-hand-ratification"]
    emit["needs"] = needs
    mutant = tmp_path / "marker-no-ac5-needs.yml"
    mutant.write_text(yaml.safe_dump(data), encoding="utf-8")
    rc = verifier.verify(mutant)
    assert rc == 2


def test_verifier_rejects_corrupt_yaml(verifier, tmp_path):
    bad = tmp_path / "corrupt.yml"
    bad.write_text("name: oh\n  jobs: [unbalanced", encoding="utf-8")
    rc = verifier.verify(bad)
    assert rc == 1


def test_verifier_rejects_missing_workflow_dispatch_dry_run(verifier, tmp_path):
    src = MARKER_WORKFLOW_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(src)
    on_key = "on" if "on" in data else True
    wd = data[on_key]["workflow_dispatch"]
    wd["inputs"].pop("dry_run", None)
    mutant = tmp_path / "marker-no-dry-run.yml"
    mutant.write_text(yaml.safe_dump(data), encoding="utf-8")
    rc = verifier.verify(mutant)
    assert rc == 2


# ---------------------------------------------------------------------------
# 5. Inventory-check substrate parity (Step 1 references real artefacts)
# ---------------------------------------------------------------------------


def test_workflow_inventory_paths_exist_on_head(workflow_text: str) -> None:
    """Step-1 inventory check enumerates per-Welle substrates that
    must exist on HEAD. We extract the path-list from the workflow
    text and assert each is present in the working tree."""
    expected_substrates = [
        "scripts/phase-3c/welle-1-v907-verify-cutover-smoke.py",
        "scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py",
        "scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py",
        "scripts/phase-3c/welle-4-state-backing-cutover-smoke.py",
        "scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py",
        "scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py",
        "scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.py",
        ".github/workflows/phase-3c-welle-1-validation.yml",
        ".github/workflows/phase-3c-welle-2-validation.yml",
        ".github/workflows/phase-3c-welle-3-validation.yml",
        ".github/workflows/phase-3c-welle-4-validation.yml",
        ".github/workflows/phase-3c-welle-5-validation.yml",
        ".github/workflows/phase-3c-welle-6-validation.yml",
        ".github/workflows/phase-3c-welle-7-validation.yml",
    ]
    for p in expected_substrates:
        assert p in workflow_text, f"workflow does not reference {p}"
        assert (REPO_ROOT / p).is_file(), (
            f"workflow expects {p} but it is absent on HEAD"
        )


def test_workflow_references_cross_substrate_scripts(workflow_text: str) -> None:
    """Cross-substrate Steps 2/3/4 must reference the real scripts."""
    for ref in (
        "scripts/phase-3c/cross-welle-cutover-generalprobe.py",
        "scripts/phase-3c/marathon-aggregat-tracker.py",
        ".github/workflows/phase-3-complete-marker.yml",
    ):
        assert ref in workflow_text, f"workflow must reference {ref}"


# ---------------------------------------------------------------------------
# 6. Operator-playbook present in workflow comments
# ---------------------------------------------------------------------------


def test_workflow_comments_link_to_operator_playbook(workflow_text: str) -> None:
    """The workflow YAML must carry the operator playbook block (5
    failure-mode entries plus the AR-Hand ratification reminder).
    We sample the substrate-owners by name to make sure the playbook
    is not silently dropped on a refactor."""
    for owner_substrate in (
        "Reza",
        "Selin",
        "Kai",
        "Amara",
        "live-VM",
        "cross-welle-cutover-generalprobe",
        "marathon-aggregat-tracker",
        "test_phase_3_final_regression_suite",
    ):
        assert owner_substrate in workflow_text, (
            f"operator playbook must mention {owner_substrate!r}"
        )


def test_workflow_concurrency_group_set(workflow_yaml: dict) -> None:
    c = workflow_yaml.get("concurrency")
    assert isinstance(c, dict)
    assert c.get("group") == "phase-3c-pre-cutover-sanity"
    assert c.get("cancel-in-progress") is False


def test_workflow_permissions_are_read_only(workflow_yaml: dict) -> None:
    perms = workflow_yaml.get("permissions", {})
    assert perms.get("contents") == "read"
    assert perms.get("actions") == "read"
    # No write-perms should be present anywhere.
    for v in perms.values():
        assert v != "write", "workflow must not request write perms"
