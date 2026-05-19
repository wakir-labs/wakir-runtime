# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic CI-substrate tests for the Tag-53 Pre-Cutover-Final-Sanity-Gate
workflow (``.github/workflows/pre-cutover-final-sanity-gate.yml``) and
its decision-aggregator
(``tooling/ci/aggregate_pre_cutover_final_sanity_gate_verdict.py``).

Test scope
----------

* Workflow YAML structural shape:
  - three trigger sources (workflow_dispatch + schedule + push),
  - exactly eight jobs in the documented order (S1..S7 + aggregator),
  - aggregator ``needs`` the seven upstream probes,
  - aggregator runs on ``if: always()``,
  - Mon 05:00 UTC cron present (one hour before Tag-41 sanity),
  - push trigger path-filtered on the seven substrate paths,
  - permissions read-only, concurrency group set.

* Decision-aggregator semantics:
  - Truth-table over a curated set of permutations covering the
    READY / CAUTION / BLOCK decision-rule for seven substrates.
  - Missing env-vars default to red.
  - Verdict-envelope JSON carries the schema-required fields.
  - Threshold ``yellows>=3 -> BLOCK`` is enforced.

Sandbox boundary: pure file-system reads + python imports + yaml
parse. No subprocess, no podman, no live-VM, no GitHub API.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from itertools import product
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = (
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
def aggregator():
    return _load_module(
        "_aggregate_pre_cutover_final_sanity_gate_verdict", AGGREGATOR_SCRIPT
    )


def _on_block(workflow_yaml: dict) -> dict:
    # PyYAML parses the bare ``on:`` key as Python ``True`` (YAML 1.1
    # boolean coercion). Tolerate both shapes.
    on = workflow_yaml.get("on", workflow_yaml.get(True))
    assert isinstance(on, dict), "workflow.on must be a mapping"
    return on


REQUIRED_JOBS = (
    "s1-engine-manifest",
    "s2-spec-freeze",
    "s3-sbom",
    "s4-build-reproducibility",
    "s5-cosign-oidc",
    "s6-welle-probes",
    "s7-marathon-tracker",
    "s8-aggregator",
)


# ---------------------------------------------------------------------------
# 1. Trigger surface
# ---------------------------------------------------------------------------


def test_workflow_has_workflow_dispatch_trigger(workflow_yaml: dict) -> None:
    on = _on_block(workflow_yaml)
    assert "workflow_dispatch" in on
    wd = on["workflow_dispatch"]
    assert isinstance(wd, dict)
    inputs = wd.get("inputs") or {}
    assert "verbose" in inputs, "verbose input expected on workflow_dispatch"


def test_workflow_has_monday_05utc_schedule(workflow_yaml: dict) -> None:
    """Tag-53 runs one hour before Tag-41 (06:00 UTC) so the auto-
    scheduler at 07:00 UTC reads the freshest seven-substrate verdict."""
    on = _on_block(workflow_yaml)
    assert "schedule" in on
    crons = [entry.get("cron") for entry in on["schedule"]]
    assert "0 5 * * 1" in crons, f"Mon 05:00 UTC cron missing; got {crons}"


def test_workflow_has_path_filtered_push_trigger(workflow_yaml: dict) -> None:
    on = _on_block(workflow_yaml)
    assert "push" in on, "push trigger missing"
    push = on["push"]
    assert isinstance(push, dict)
    branches = push.get("branches", [])
    assert "main" in branches, "push trigger must filter on main"
    paths = push.get("paths", [])
    expected_substrate_paths = (
        "scripts/phase-3c/",
        "wirelang/persona_engine/MANIFEST-",
        "wirelang/specs/wirelang-spec-",
        "infra/persona-engine/pin-pack-",
        ".github/workflows/15-binary-sbom-daily.yml",
        ".github/workflows/build-reproducibility-daily.yml",
        ".github/workflows/cosign-keyless-oidc-drift-probe.yml",
        ".github/workflows/phase-3c-marathon-tracker-gate.yml",
    )
    for needle in expected_substrate_paths:
        assert any(p.startswith(needle) or needle in p for p in paths), (
            f"path-filter missing entry covering {needle!r}; got {paths}"
        )


# ---------------------------------------------------------------------------
# 2. Job topology: eight jobs (S1..S7 + aggregator)
# ---------------------------------------------------------------------------


def test_workflow_has_exactly_eight_jobs(workflow_yaml: dict) -> None:
    jobs = workflow_yaml.get("jobs", {})
    assert set(jobs.keys()) == set(REQUIRED_JOBS), (
        f"job set mismatch; got {sorted(jobs)}, want {sorted(REQUIRED_JOBS)}"
    )


def test_aggregator_needs_all_upstream_and_is_always(workflow_yaml: dict) -> None:
    job = workflow_yaml["jobs"]["s8-aggregator"]
    needs = job.get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    for upstream in REQUIRED_JOBS[:7]:
        assert upstream in needs, f"aggregator must need {upstream}"
    assert job.get("if") in ("always()", "${{ always() }}"), (
        f"aggregator must use `if: always()`; got {job.get('if')!r}"
    )


def test_each_probe_job_uses_checkout(workflow_yaml: dict) -> None:
    """Each S1..S7 probe job must run actions/checkout (otherwise
    the workflow has no tree to probe)."""
    for job_id in REQUIRED_JOBS[:7]:
        job = workflow_yaml["jobs"][job_id]
        steps = job["steps"]
        assert any(
            (s.get("uses") or "").startswith("actions/checkout@") for s in steps
        ), f"{job_id} missing actions/checkout step"


def test_each_probe_job_has_status_and_note_outputs(workflow_yaml: dict) -> None:
    """Every probe job must export a ``<id>_status`` and ``<id>_note``
    job-output that the aggregator reads."""
    for idx, job_id in enumerate(REQUIRED_JOBS[:7], start=1):
        job = workflow_yaml["jobs"][job_id]
        outputs = job.get("outputs", {})
        assert f"s{idx}_status" in outputs, (
            f"{job_id} missing s{idx}_status output; got {outputs}"
        )
        assert f"s{idx}_note" in outputs, (
            f"{job_id} missing s{idx}_note output; got {outputs}"
        )


def test_workflow_concurrency_group_set(workflow_yaml: dict) -> None:
    c = workflow_yaml.get("concurrency")
    assert isinstance(c, dict)
    assert c.get("group") == "pre-cutover-final-sanity-gate"
    assert c.get("cancel-in-progress") is False


def test_workflow_permissions_are_read_only(workflow_yaml: dict) -> None:
    perms = workflow_yaml.get("permissions", {})
    assert perms.get("contents") == "read"
    assert perms.get("actions") == "read"
    for v in perms.values():
        assert v != "write", "workflow must not request write perms"


# ---------------------------------------------------------------------------
# 3. Substrate references (each probe must reference its substrate path)
# ---------------------------------------------------------------------------


SUBSTRATE_REFERENCES = (
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


def test_workflow_references_all_substrate_paths(workflow_text: str) -> None:
    for ref in SUBSTRATE_REFERENCES:
        assert ref in workflow_text, f"workflow must reference {ref}"


def test_workflow_inventory_paths_exist_on_head(workflow_text: str) -> None:
    """Substrate paths that must exist on HEAD (S2 spec-freeze is
    explicitly NOT in this list - the spec file is allowed to be
    missing pre-freeze)."""
    must_exist_on_head = (
        "wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md",
        "infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml",
        ".github/workflows/15-binary-sbom-daily.yml",
        ".github/workflows/build-reproducibility-daily.yml",
        ".github/workflows/cosign-keyless-oidc-drift-probe.yml",
        ".github/workflows/cosign-verify-images.yml",
        "scripts/phase-3c/marathon-aggregat-tracker.py",
        ".github/workflows/phase-3c-marathon-tracker-gate.yml",
    )
    for p in must_exist_on_head:
        assert p in workflow_text, f"workflow must reference {p}"
        assert (REPO_ROOT / p).is_file(), (
            f"workflow expects {p} on HEAD but it is absent"
        )


def test_welle_pre_cutover_probes_exist_on_head() -> None:
    """The seven per-Welle pre-cutover-probe shell scripts that S6
    inspects must exist on HEAD."""
    for n in range(1, 8):
        p = REPO_ROOT / "scripts" / "phase-3c" / f"welle-{n}-pre-cutover-probe.sh"
        assert p.is_file(), f"welle-{n}-pre-cutover-probe.sh missing on HEAD"


def test_welle_hot_spot_probe_workflows_exist_on_head() -> None:
    """Welle 3..7 hot-spot probe workflows must exist on HEAD."""
    for n in range(3, 8):
        p = (
            REPO_ROOT
            / ".github"
            / "workflows"
            / f"phase-3c-welle-{n}-hot-spot-probe.yml"
        )
        assert p.is_file(), f"phase-3c-welle-{n}-hot-spot-probe.yml missing on HEAD"


# ---------------------------------------------------------------------------
# 4. Decision-aggregator semantics
# ---------------------------------------------------------------------------


def test_aggregator_seven_substrates_canonical_order(aggregator) -> None:
    assert aggregator.SUBSTRATES == (
        "engine_manifest",
        "spec_freeze",
        "sbom",
        "build_reproducibility",
        "cosign_oidc",
        "welle_probes",
        "marathon_tracker",
    )


def test_aggregator_all_green_is_ready(aggregator) -> None:
    envelope = aggregator.build_envelope(
        {f"S{i}_STATUS": "green" for i in range(1, 8)}
    )
    assert envelope["verdict"] == "READY"
    assert envelope["counts"] == {"green": 7, "yellow": 0, "red": 0}


def test_aggregator_one_yellow_is_caution(aggregator) -> None:
    env = {f"S{i}_STATUS": "green" for i in range(1, 8)}
    env["S2_STATUS"] = "yellow"  # spec-freeze pre-freeze
    envelope = aggregator.build_envelope(env)
    assert envelope["verdict"] == "CAUTION"
    assert envelope["counts"]["yellow"] == 1


def test_aggregator_two_yellow_is_caution(aggregator) -> None:
    env = {f"S{i}_STATUS": "green" for i in range(1, 8)}
    env["S2_STATUS"] = "yellow"
    env["S6_STATUS"] = "yellow"
    envelope = aggregator.build_envelope(env)
    assert envelope["verdict"] == "CAUTION"


def test_aggregator_three_yellow_is_block(aggregator) -> None:
    """The Tag-53 threshold is tighter: three yellow degrades to BLOCK."""
    env = {f"S{i}_STATUS": "green" for i in range(1, 8)}
    env["S2_STATUS"] = "yellow"
    env["S5_STATUS"] = "yellow"
    env["S6_STATUS"] = "yellow"
    envelope = aggregator.build_envelope(env)
    assert envelope["verdict"] == "BLOCK"


def test_aggregator_any_red_is_block(aggregator) -> None:
    for i in range(1, 8):
        env = {f"S{j}_STATUS": "green" for j in range(1, 8)}
        env[f"S{i}_STATUS"] = "red"
        envelope = aggregator.build_envelope(env)
        assert envelope["verdict"] == "BLOCK", (
            f"S{i} red must produce BLOCK; got {envelope['verdict']}"
        )


def test_aggregator_missing_env_defaults_to_red(aggregator) -> None:
    envelope = aggregator.build_envelope({})
    assert envelope["verdict"] == "BLOCK"
    assert envelope["counts"]["red"] == 7
    for v in envelope["step_results"].values():
        assert v == "red"


def test_aggregator_unknown_status_is_red(aggregator) -> None:
    env = {f"S{i}_STATUS": "green" for i in range(1, 8)}
    env["S1_STATUS"] = "magenta"
    envelope = aggregator.build_envelope(env)
    assert envelope["verdict"] == "BLOCK"
    assert envelope["step_results"]["engine_manifest"] == "red"


def test_aggregator_envelope_has_required_schema_fields(aggregator) -> None:
    envelope = aggregator.build_envelope(
        {f"S{i}_STATUS": "green" for i in range(1, 8)}
    )
    required_keys = {
        "schema_version",
        "workflow",
        "tag",
        "emitted_at_utc",
        "verdict",
        "step_results",
        "failed_steps",
        "substrate_notes",
        "counts",
        "decision_rule",
        "cross_substrate_links",
    }
    assert required_keys.issubset(envelope.keys()), (
        f"missing keys: {required_keys - envelope.keys()}"
    )
    assert envelope["workflow"] == "pre-cutover-final-sanity-gate"
    assert envelope["tag"] == "tag-53"
    assert envelope["schema_version"] == 1
    links = envelope["cross_substrate_links"]
    for key in (
        "engine_manifest_pin_pack",
        "spec_freeze_doc",
        "sbom_workflow",
        "build_reproducibility_workflow",
        "cosign_oidc_workflow",
        "marathon_tracker_workflow",
        "tag_41_sanity_workflow",
        "auto_scheduler_workflow",
    ):
        assert key in links


def test_aggregator_substrate_notes_parsed(aggregator) -> None:
    env = {f"S{i}_STATUS": "green" for i in range(1, 8)}
    env["S2_STATUS"] = "yellow"
    env["SUBSTRATE_NOTES"] = (
        "spec_freeze:spec v0.4.3 not yet on HEAD (pre-freeze);"
        "welle_probes:two probes degraded"
    )
    envelope = aggregator.build_envelope(env)
    assert envelope["substrate_notes"] == [
        "spec_freeze:spec v0.4.3 not yet on HEAD (pre-freeze)",
        "welle_probes:two probes degraded",
    ]


def test_aggregator_failed_steps_records_non_green(aggregator) -> None:
    env = {f"S{i}_STATUS": "green" for i in range(1, 8)}
    env["S3_STATUS"] = "red"
    env["S5_STATUS"] = "yellow"
    envelope = aggregator.build_envelope(env)
    assert set(envelope["failed_steps"]) == {"sbom", "cosign_oidc"}


def test_aggregator_writes_output_file(aggregator, tmp_path, monkeypatch) -> None:
    out = tmp_path / "verdict.json"
    for i in range(1, 8):
        monkeypatch.setenv(f"S{i}_STATUS", "green")
    monkeypatch.setenv("S6_STATUS", "yellow")
    rc = aggregator.main(["aggregator", "--output", str(out)])
    assert rc == 0
    assert out.is_file()
    parsed = json.loads(out.read_text())
    assert parsed["verdict"] == "CAUTION"
    assert parsed["workflow"] == "pre-cutover-final-sanity-gate"


def test_aggregator_decide_matches_envelope(aggregator) -> None:
    """The pure ``decide()`` helper must agree with ``build_envelope()``
    for any permutation. We sample 3**7 = 2187 cases via the
    truth-table to lock the rule down."""
    for permutation in product(("green", "yellow", "red"), repeat=7):
        env = {f"S{i+1}_STATUS": permutation[i] for i in range(7)}
        envelope = aggregator.build_envelope(env)
        steps = {
            sub: permutation[i] for i, sub in enumerate(aggregator.SUBSTRATES)
        }
        assert envelope["verdict"] == aggregator.decide(steps), (
            f"decide() drift at {permutation}: "
            f"envelope={envelope['verdict']} decide={aggregator.decide(steps)}"
        )


# ---------------------------------------------------------------------------
# 5. Cross-gate consistency with Tag-41 sanity + Tag-44 auto-scheduler
# ---------------------------------------------------------------------------


def test_workflow_documents_tag_41_relationship(workflow_text: str) -> None:
    """The header comment must explain the ordering with the Tag-41
    sanity workflow (Tag-53 runs first at 05:00 UTC, Tag-41 at 06:00
    UTC, auto-scheduler at 07:00 UTC)."""
    for ref in (
        "Tag-41",
        "Tag-53",
        "auto-scheduler",
        "05:00 UTC",
        "06:00 UTC",
    ):
        assert ref in workflow_text, (
            f"workflow header must mention {ref!r} (cross-gate doc)"
        )


def test_workflow_documents_seven_substrate_set(workflow_text: str) -> None:
    """The header comment must enumerate all seven substrates by name."""
    for substrate in (
        "engine_manifest",
        "spec_freeze",
        "sbom",
        "build_reproducibility",
        "cosign_oidc",
        "welle_probes",
        "marathon_tracker",
    ):
        assert substrate in workflow_text, (
            f"workflow header must name substrate {substrate!r}"
        )
