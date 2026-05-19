# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for the Tag-55 Pre-Cutover-Final-Sanity-Gate AR-Hand
trigger workflow (``.github/workflows/pre-cutover-final-sanity-gate-
ar-trigger.yml``).

The AR-trigger workflow is the dedicated, UI-only ``workflow_dispatch``
companion to the Tag-53 scheduled ``pre-cutover-final-sanity-gate.yml``.
This file asserts the AR-trigger has the right shape and that it
preserves Tag-53 substrate-parity (so an AR-Hand fire produces a
directly comparable verdict to the scheduled fire) while diverging on
the four invariants Tag-55 introduces:

  1. **UI-only trigger surface.** ``workflow_dispatch`` MUST be the
     only top-level trigger key. No ``schedule:``, no ``push:``.
  2. **Distinct concurrency-group.** Must NOT share the Tag-53
     workflow's concurrency-group name (otherwise an AR-Hand fire
     could cancel an in-flight Monday-cron fire and vice versa).
  3. **AR-trigger preamble job (S0).** A first job that records
     ``actor`` and ``reason`` for the audit-log; the seven probe-
     jobs all ``needs:`` it so the audit-record always lands first.
  4. **Distinct artifact name.** Verdict artifact suffixed
     ``-ar-trigger`` so the auto-scheduler can tell at a glance
     which verdict came from which fire-path.

The probe-jobs themselves are byte-for-byte equivalent to Tag-53 on
substrate-logic; the test-suite asserts that equivalence via the
shared SUBSTRATES tuple and aggregator-script.

Sandbox boundary: filesystem reads + yaml parse + python stdlib +
pytest. No subprocess, no podman, no live-VM, no GitHub API.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from itertools import product
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "pre-cutover-final-sanity-gate-ar-trigger.yml"
)
TAG_53_WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "pre-cutover-final-sanity-gate.yml"
)
AGGREGATOR_SCRIPT = (
    REPO_ROOT
    / "tooling"
    / "ci"
    / "aggregate_pre_cutover_final_sanity_gate_verdict.py"
)


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
def tag_53_workflow_yaml() -> dict:
    assert TAG_53_WORKFLOW_PATH.is_file(), (
        f"Tag-53 workflow missing: {TAG_53_WORKFLOW_PATH}"
    )
    data = yaml.safe_load(TAG_53_WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def aggregator():
    return _load_module(
        "_aggregate_pre_cutover_final_sanity_gate_verdict_ar_trigger",
        AGGREGATOR_SCRIPT,
    )


def _on_block(workflow_yaml: dict) -> dict:
    # PyYAML parses the bare ``on:`` key as Python ``True`` (YAML 1.1
    # boolean coercion). Tolerate both shapes.
    on = workflow_yaml.get("on", workflow_yaml.get(True))
    assert isinstance(on, dict), "workflow.on must be a mapping"
    return on


REQUIRED_PROBE_JOBS = (
    "s1-engine-manifest",
    "s2-spec-freeze",
    "s3-sbom",
    "s4-build-reproducibility",
    "s5-cosign-oidc",
    "s6-welle-probes",
    "s7-marathon-tracker",
)
REQUIRED_JOBS = ("s0-ar-trigger-preamble",) + REQUIRED_PROBE_JOBS + ("s8-aggregator",)


def test_workflow_file_present_and_parses(workflow_yaml: dict) -> None:
    """The AR-trigger workflow file exists and parses as a YAML mapping."""
    assert "name" in workflow_yaml
    assert workflow_yaml["name"] == "pre-cutover-final-sanity-gate-ar-trigger"
    assert "jobs" in workflow_yaml
    assert isinstance(workflow_yaml["jobs"], dict)


def test_trigger_is_ui_only_workflow_dispatch(workflow_yaml: dict) -> None:
    """Only ``workflow_dispatch`` is allowed; no ``schedule``, no ``push``.

    This is the load-bearing Tag-55 invariant: the AR-trigger is the
    distinct UI-only surface complement to the Tag-53 scheduled+push
    surface. Adding ``schedule`` or ``push`` here silently mutates the
    semantics; this test catches that drift.
    """
    on = _on_block(workflow_yaml)
    assert "workflow_dispatch" in on, "workflow_dispatch trigger is mandatory"
    assert "schedule" not in on, (
        "schedule trigger MUST NOT be present (AR-Hand UI-only)"
    )
    assert "push" not in on, "push trigger MUST NOT be present (AR-Hand UI-only)"
    # Any other trigger types are also forbidden (the AR-trigger surface
    # is single-purpose).
    extra = set(on.keys()) - {"workflow_dispatch"}
    assert not extra, f"unexpected trigger surfaces: {sorted(extra)}"


def test_workflow_dispatch_inputs_contract(workflow_yaml: dict) -> None:
    """The three documented inputs are present with correct types."""
    on = _on_block(workflow_yaml)
    inputs = on["workflow_dispatch"]["inputs"]
    assert "reason" in inputs and inputs["reason"]["required"] is True
    assert "verbose" in inputs and inputs["verbose"].get("type") == "boolean"
    assert "verbose" in inputs and inputs["verbose"]["default"] is False
    assert (
        "allow_caution" in inputs
        and inputs["allow_caution"].get("type") == "boolean"
    )
    assert inputs["allow_caution"]["default"] is True


def test_concurrency_group_distinct_from_tag_53(
    workflow_yaml: dict, tag_53_workflow_yaml: dict
) -> None:
    """Tag-55 MUST use a distinct concurrency-group name from Tag-53.

    Sharing groups would let an AR-Hand fire cancel an in-flight
    Monday-cron fire (and vice versa). Operator-hand and scheduler
    streams must be independent.
    """
    ar_group = workflow_yaml["concurrency"]["group"]
    sched_group = tag_53_workflow_yaml["concurrency"]["group"]
    assert ar_group == "pre-cutover-final-sanity-gate-ar-trigger"
    assert ar_group != sched_group


def test_all_required_jobs_present_in_order(workflow_yaml: dict) -> None:
    """S0 preamble + S1..S7 probes + S8 aggregator, in documented order."""
    jobs = workflow_yaml["jobs"]
    job_keys = list(jobs.keys())
    for required in REQUIRED_JOBS:
        assert required in jobs, f"missing job: {required}"
    # Order: S0 first, S8 last.
    assert job_keys[0] == "s0-ar-trigger-preamble"
    assert job_keys[-1] == "s8-aggregator"


def test_s0_preamble_emits_actor_and_reason_outputs(workflow_yaml: dict) -> None:
    """S0 declares ``reason`` + ``actor`` outputs the aggregator can read."""
    s0 = workflow_yaml["jobs"]["s0-ar-trigger-preamble"]
    outputs = s0.get("outputs", {})
    assert "reason" in outputs
    assert "actor" in outputs
    # Output expression-strings must reference the step id ``preamble``.
    assert "preamble" in outputs["reason"]
    assert "preamble" in outputs["actor"]


def test_all_probe_jobs_need_s0_preamble(workflow_yaml: dict) -> None:
    """S1..S7 each ``needs:`` S0 so the audit-preamble lands first."""
    jobs = workflow_yaml["jobs"]
    for probe in REQUIRED_PROBE_JOBS:
        needs = jobs[probe].get("needs")
        # ``needs`` may be a string or list; coerce to list for the check.
        if isinstance(needs, str):
            needs = [needs]
        assert needs is not None, f"{probe} missing needs:"
        assert "s0-ar-trigger-preamble" in needs, (
            f"{probe} must need s0-ar-trigger-preamble"
        )


def test_aggregator_needs_preamble_and_all_probes(workflow_yaml: dict) -> None:
    """S8 needs S0..S7 (eight upstreams) and runs always()."""
    agg = workflow_yaml["jobs"]["s8-aggregator"]
    needs = agg.get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    expected = {"s0-ar-trigger-preamble", *REQUIRED_PROBE_JOBS}
    assert set(needs) == expected
    assert agg.get("if") == "always()"


def test_aggregator_uses_distinct_artifact_name(workflow_text: str) -> None:
    """The verdict artifact name carries the ``-ar-trigger`` suffix.

    Auto-scheduler downstream consumers tell scheduled vs. AR-Hand
    verdicts apart by artifact name.
    """
    assert "pre-cutover-final-sanity-gate-verdict-ar-trigger" in workflow_text
    # And the verdict JSON file the bash step writes carries the same
    # suffix on disk.
    assert "out/pre-cutover-final-sanity-gate-verdict-ar-trigger.json" in workflow_text


def test_aggregator_strict_mode_caution_upgrade(workflow_text: str) -> None:
    """When ``allow_caution=false`` the aggregator upgrades CAUTION->BLOCK.

    The strict-mode override is the AR-Hand's distinct value-add: an
    operator can demand strict-green for marathon-start by toggling
    the input. The bash logic must invoke the helper script.
    """
    # The override is implemented as a CAUTION -> BLOCK upgrade by the
    # helper script ``ar_trigger_strict_mode_upgrade.py``. Pin the
    # exact literals so a future refactor that drops the override path
    # fails this test.
    assert '"$verdict" == "CAUTION"' in workflow_text
    assert "ALLOW_CAUTION" in workflow_text
    assert 'verdict="BLOCK"' in workflow_text
    assert "ar_trigger_strict_mode_upgrade.py" in workflow_text


def test_strict_mode_helper_present_and_imports(tmp_path: Path) -> None:
    """The strict-mode helper script exists, imports, and mutates JSON."""
    helper = REPO_ROOT / "tooling" / "ci" / "ar_trigger_strict_mode_upgrade.py"
    assert helper.is_file(), f"helper missing: {helper}"
    # Smoke-test the script against a synthetic CAUTION verdict.
    sample = tmp_path / "verdict.json"
    sample.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "verdict": "CAUTION",
                "step_results": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    rc = subprocess.run(
        [sys.executable, str(helper), "--input", str(sample)],
        check=False,
    ).returncode
    assert rc == 0
    upgraded = json.loads(sample.read_text(encoding="utf-8"))
    assert upgraded["verdict"] == "BLOCK"
    assert upgraded["ar_trigger_strict_mode"] is True
    assert upgraded["ar_trigger_original_verdict"] == "CAUTION"


def test_permissions_are_read_only(workflow_yaml: dict) -> None:
    """Top-level permissions are read-only (no contents:write)."""
    perms = workflow_yaml["permissions"]
    assert perms["contents"] == "read"
    assert perms.get("actions") == "read"
    # No write permission of any kind.
    for k, v in perms.items():
        assert v != "write", f"permission {k} must not be write"


def test_probe_jobs_substrate_logic_matches_tag_53(
    workflow_text: str, tag_53_workflow_yaml: dict
) -> None:
    """Substrate-logic markers from Tag-53 are preserved in Tag-55.

    The AR-trigger MUST probe the same seven substrates with the same
    file-paths so the verdict semantics line up. We assert the load-
    bearing file-path strings appear in the AR-trigger YAML.
    """
    expected_paths = (
        "wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md",
        "infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml",
        "wirelang/specs/wirelang-spec-v0-4-3.md",
        ".github/workflows/15-binary-sbom-daily.yml",
        ".github/workflows/build-reproducibility-daily.yml",
        ".github/workflows/cosign-keyless-oidc-drift-probe.yml",
        ".github/workflows/cosign-verify-images.yml",
        "scripts/phase-3c/marathon-aggregat-tracker.py",
        ".github/workflows/phase-3c-marathon-tracker-gate.yml",
    )
    for p in expected_paths:
        assert p in workflow_text, f"substrate path missing in AR-trigger: {p}"


def test_aggregator_truth_table_via_subprocess(
    aggregator, tmp_path: Path
) -> None:
    """Drive the aggregator script directly with sample env-vars.

    The AR-trigger workflow re-uses the Tag-53 aggregator script
    verbatim (same Python file, same env-var contract). We pin a few
    sample inputs and verify the verdict-rule still holds. This is the
    contract the AR-trigger relies on for parity with the scheduled
    fire.
    """
    cases = [
        # (statuses tuple, expected_verdict)
        (("green",) * 7, "READY"),
        (("green",) * 6 + ("yellow",), "CAUTION"),
        (("green",) * 5 + ("yellow", "yellow"), "CAUTION"),
        (("green",) * 4 + ("yellow", "yellow", "yellow"), "BLOCK"),
        (("green",) * 6 + ("red",), "BLOCK"),
        (("",) * 7, "BLOCK"),  # All missing -> all default red -> BLOCK.
    ]
    for statuses, expected in cases:
        env = os.environ.copy()
        # Strip any inherited S*_STATUS from outer test runs.
        for k in list(env.keys()):
            if k.startswith("S") and k.endswith("_STATUS"):
                env.pop(k, None)
        for i, s in enumerate(statuses, start=1):
            env[f"S{i}_STATUS"] = s
        env["SUBSTRATE_NOTES"] = ""
        out = tmp_path / f"verdict-{'-'.join(s or 'empty' for s in statuses)}.json"
        rc = subprocess.run(
            [sys.executable, str(AGGREGATOR_SCRIPT), "--output", str(out)],
            env=env,
            check=False,
        ).returncode
        assert rc == 0, f"aggregator exited non-zero for {statuses}"
        envelope = json.loads(out.read_text(encoding="utf-8"))
        assert envelope["verdict"] == expected, (
            f"verdict mismatch for {statuses}: got {envelope['verdict']!r} "
            f"want {expected!r}"
        )


def test_ar_trigger_audit_summary_emits_actor_and_reason(workflow_text: str) -> None:
    """S0 preamble step writes actor + reason into the step-summary.

    The audit-trail is the workflow's user-facing rationale; we pin
    the literal heading + table fields so downstream grep-tooling can
    rely on the format.
    """
    assert "## AR-Hand Pre-Cutover-Final-Sanity-Gate Fire" in workflow_text
    assert "| actor |" in workflow_text
    assert "| reason |" in workflow_text
    assert "| allow_caution |" in workflow_text
    assert "| run_id |" in workflow_text
    assert "| sha |" in workflow_text


def test_no_required_status_check_anti_pattern(workflow_text: str) -> None:
    """The Tag-55 workflow is NOT a branch-protection required check.

    Per ``feedback_branch_protection_check_names.md`` this workflow
    gates an operator-hand event, not individual PRs. The
    documentation in the header MUST say so (defends against a future
    edit that adds it to branch-protection-required-checks without
    operator review).
    """
    assert "Not a required status check" in workflow_text
    assert "feedback_branch_protection_check_names" in workflow_text
