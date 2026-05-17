# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic workflow-structure tests for
``.github/workflows/phase-3c-welle-1-validation.yml``.

Sprint-Tag-25 Mini-Welle (Phase-3c Welle-1 Validation, ADR-0065).

These tests assert the workflow STRUCTURE stays stable so a future
edit that drops a step or breaks the gate-aggregation / dry-run /
decision-render contract regresses with a clear hermetic-test
failure rather than only via the wednesday-cron run.

Sandbox boundary
----------------

Tests parse YAML on disk only. No actions runner, no podman, no
GHCR egress, no live-VM. The dry-run / aggregator scoring contract
is validated by composing the in-tree aggregator + dry-run modules
against synthetic inputs that mirror the workflow's step-1 / step-2
invocations.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "phase-3c-welle-1-validation.yml"
)


# ---------------------------------------------------------------------------
# YAML loader fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert WORKFLOW.is_file(), f"missing workflow: {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_yaml(workflow_text: str) -> dict:
    # The workflow has a leading ``on:`` mapping key that PyYAML parses
    # as the boolean True; that is fine because we introspect the
    # ``jobs`` subtree and only consult ``on`` via the string key.
    return yaml.safe_load(workflow_text)


@pytest.fixture(scope="module")
def validation_job(workflow_yaml: dict) -> dict:
    jobs = workflow_yaml.get("jobs", {})
    job = jobs.get("phase-3c-welle-1-validation")
    assert job is not None, (
        "workflow missing 'phase-3c-welle-1-validation' job"
    )
    return job


@pytest.fixture(scope="module")
def validation_steps(validation_job: dict) -> List[dict]:
    steps = validation_job.get("steps")
    assert isinstance(steps, list) and steps, (
        "validation job has no steps"
    )
    return steps


# ---------------------------------------------------------------------------
# Test 1 — workflow YAML parses + name + permissions invariant.
# ---------------------------------------------------------------------------


def test_workflow_yaml_format_and_top_level(workflow_yaml: dict) -> None:
    """The workflow file must be valid YAML with the expected name +
    permissions shape (least-privilege: ``contents: read`` only)."""
    assert workflow_yaml.get("name") == "phase-3c-welle-1-validation"
    perms = workflow_yaml.get("permissions")
    assert isinstance(perms, dict), (
        "workflow must declare top-level permissions"
    )
    # Validation workflow only reads the repo; no write surfaces.
    assert perms.get("contents") == "read"
    # Explicit guard: refuse drift to broader scopes.
    assert set(perms.keys()) == {"contents"}, (
        f"unexpected permission scopes: {sorted(perms.keys())}"
    )


# ---------------------------------------------------------------------------
# Test 2 — trigger surface: scheduled + workflow_dispatch.
# ---------------------------------------------------------------------------


def test_trigger_surface_schedule_and_dispatch(
    workflow_yaml: dict,
) -> None:
    """Trigger surface must expose both the wednesday-cron schedule and
    workflow_dispatch with the three documented inputs."""
    # PyYAML parses the bare ``on:`` mapping key as boolean True.
    on = workflow_yaml.get(True) or workflow_yaml.get("on")
    assert on is not None, "workflow missing 'on' trigger block"
    schedule = on.get("schedule")
    assert isinstance(schedule, list) and schedule, (
        "missing schedule trigger"
    )
    # Single weekly cron at Wednesday 06:00 UTC.
    assert len(schedule) == 1
    assert schedule[0].get("cron") == "0 6 * * 3", (
        f"unexpected cron: {schedule[0].get('cron')!r}"
    )
    dispatch = on.get("workflow_dispatch")
    assert dispatch is not None, "missing workflow_dispatch trigger"
    inputs = dispatch.get("inputs") or {}
    assert set(inputs.keys()) == {
        "target-binary-count",
        "boots",
        "score-band-floor",
    }, f"unexpected dispatch inputs: {sorted(inputs.keys())}"
    # Sanity: each input declares a default.
    for name, spec in inputs.items():
        assert "default" in spec, (
            f"dispatch input {name!r} missing default"
        )


# ---------------------------------------------------------------------------
# Test 3 — five mandatory steps in order, with stable step-ids.
# ---------------------------------------------------------------------------


def test_five_validation_steps_in_order(
    validation_steps: List[dict],
) -> None:
    """The workflow ships exactly five Mira-Hand-defined validation
    steps (gate-aggregator, dry-run, persona-boot, bridge-audit,
    decision-render) in that order, plus the standard checkout +
    setup-python + install + inputs + mkdir prelude and the artifact
    upload at the tail."""

    step_ids = [s.get("id") for s in validation_steps if s.get("id")]
    expected_ids = [
        "inputs",
        "gate-aggregator",
        "dry-run",
        "persona-boot",
        "bridge-audit",
        "decision",
    ]
    # Substring containment + order; the workflow may carry additional
    # un-ID'd steps (checkout, setup-python, install, mkdir, upload).
    indices = [step_ids.index(x) for x in expected_ids]
    assert indices == sorted(indices), (
        f"step-id order drift: got {step_ids}"
    )
    # Step names — the operator-facing labels Mira sees in the run-tab.
    step_names = [s.get("name") for s in validation_steps]
    for required_prefix in (
        "Step 1 -",  # trigger-gate aggregator
        "Step 2 -",  # cutover-dry-run
        "Step 3 -",  # test-persona-boot
        "Step 4 -",  # bridge-audit-roundtrip
        "Step 5 -",  # render cutover-acceptance-decision
    ):
        assert any(
            n and n.replace("—", "-").startswith(required_prefix)
            for n in step_names
        ), (
            f"missing step with name prefix {required_prefix!r}; "
            f"got {step_names}"
        )


# ---------------------------------------------------------------------------
# Test 4 — invocation contracts: scripts + tests referenced exist.
# ---------------------------------------------------------------------------


def test_step_invocation_contracts(
    validation_steps: List[dict],
) -> None:
    """Each numbered step references a real in-repo artifact:
    aggregator script (Step 1), dry-run script (Step 2), rust_backend_
    switch test file (Step 3), bridge-audit-roundtrip-e2e test file
    (Step 4). The render step (Step 5) is in-line python and is
    validated by Test 6 instead."""
    by_id = {s.get("id"): s for s in validation_steps if s.get("id")}

    # Step 1: aggregator script + --target-binary-count + --json.
    gate_run = by_id["gate-aggregator"].get("run") or ""
    assert (
        "scripts/phase-3c-trigger-gate-aggregator.py" in gate_run
    ), "Step 1 missing aggregator script reference"
    assert "--target-binary-count" in gate_run
    assert "--json" in gate_run
    assert (REPO_ROOT / "scripts" / "phase-3c-trigger-gate-aggregator.py").is_file()

    # Step 2: dry-run script + --component + --boots + --output.
    dry_run = by_id["dry-run"].get("run") or ""
    assert "scripts/phase-3c-cutover-dry-run.py" in dry_run
    assert "--component" in dry_run
    assert "--boots" in dry_run
    assert "--output" in dry_run
    assert (REPO_ROOT / "scripts" / "phase-3c-cutover-dry-run.py").is_file()

    # Step 3: pytest on rust_backend_switch test file with -k v907_verify.
    boot_run = by_id["persona-boot"].get("run") or ""
    assert (
        "wirelang/tests/persona_engine/test_rust_backend_switch.py"
        in boot_run
    )
    assert "v907_verify" in boot_run
    # Env-var must be set on the step level (not just inline) so the
    # resolver picks it up via os.environ for the boot-decision path.
    boot_env = by_id["persona-boot"].get("env") or {}
    assert boot_env.get("WAKIR_V907_VERIFY_BACKEND") == "rust", (
        f"Step 3 env-var missing or wrong: {boot_env}"
    )
    assert (
        REPO_ROOT
        / "wirelang"
        / "tests"
        / "persona_engine"
        / "test_rust_backend_switch.py"
    ).is_file()

    # Step 4: bridge-audit-roundtrip-e2e test file.
    bridge_run = by_id["bridge-audit"].get("run") or ""
    assert (
        "tests/integration/test_bridge_audit_roundtrip_e2e.py"
        in bridge_run
    )
    assert (
        REPO_ROOT
        / "tests"
        / "integration"
        / "test_bridge_audit_roundtrip_e2e.py"
    ).is_file()


# ---------------------------------------------------------------------------
# Helpers — load aggregator + dry-run modules for live composition checks.
# ---------------------------------------------------------------------------


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def aggregator_module():
    path = REPO_ROOT / "scripts" / "phase-3c-trigger-gate-aggregator.py"
    return _load_module("phase_3c_trigger_gate_aggregator_wf", path)


@pytest.fixture(scope="module")
def dry_run_module():
    path = REPO_ROOT / "scripts" / "phase-3c-cutover-dry-run.py"
    return _load_module("phase_3c_cutover_dry_run_wf", path)


# ---------------------------------------------------------------------------
# Test 5 — gate-aggregation succeeds against the live repo (smoke).
# ---------------------------------------------------------------------------


def test_gate_aggregation_against_live_repo(aggregator_module) -> None:
    """Composing the aggregator against the live repo must produce a
    valid five-gate report; Gate-4 yellow tolerance is permitted (the
    observability-baseline ENV is not set in the test environment),
    but the report must structurally have five gates and a JSON-
    serialisable shape that matches the workflow's Step-1 contract."""
    report = aggregator_module.aggregate(REPO_ROOT)
    rendered = report.to_dict()
    # Schema invariant.
    assert rendered["schema"] == "wakir.phase-3c.trigger-gate-report/1"
    # Five gates with stable ids.
    gates = rendered.get("gates", [])
    assert len(gates) == 5, f"expected 5 gates, got {len(gates)}"
    ids = [g["id"] for g in gates]
    assert ids == ["gate-1", "gate-2", "gate-3", "gate-4", "gate-5"]
    # Report is JSON-serialisable (the workflow pipes the JSON through
    # stdout into the trigger-gate-report.json artifact).
    json.dumps(rendered)
    # Exit code is one of {0, 1, 2}; the workflow tolerates 0 and 1
    # (Gate-4 yellow) and fails on 2.
    assert report.exit_code in (0, 1, 2)


# ---------------------------------------------------------------------------
# Test 6 — dry-run success-criteria for v907_verify.
# ---------------------------------------------------------------------------


def test_dry_run_success_criteria_v907_verify(dry_run_module) -> None:
    """The v907_verify dry-run with the workflow's default boots count
    (12) and stub binary-probe must produce a GREEN feasibility envelope
    (all-rust purity, zero fallbacks, latency well under budget). This
    is the substance contract the workflow's Step-2 acceptance-decision
    logic depends on: dry-run band >= GREEN floor."""

    # Stub resolver that returns a frozen-dataclass-compatible decision
    # without importing the wirelang package. We mirror the resolver
    # contract: a callable named ``resolve_v907_verify_backend`` that
    # returns ``(backend, decision)`` where ``decision`` has
    # ``chosen_backend``, ``fallback_reason``, ``resolution_latency_us``,
    # and ``domain`` fields.
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Decision:
        chosen_backend: str
        fallback_reason: Any
        resolution_latency_us: int
        domain: str

    class _StubResolverModule:
        @staticmethod
        def resolve_v907_verify_backend(*, env, log_sink, binary_probe):
            requested = env.get("WAKIR_V907_VERIFY_BACKEND", "python")
            return (
                requested,
                _Decision(
                    chosen_backend=requested,
                    fallback_reason=None,
                    resolution_latency_us=42,  # well under 50 ms budget
                    domain="v907_verify",
                ),
            )

    envelope = dry_run_module.run_dry_run(
        component="v907_verify",
        boots=12,
        resolver_module=_StubResolverModule(),
        now_ts=0,
    )
    # Schema + bookkeeping invariants.
    assert envelope["schema"] == "wakir.phase-3c.dry-run/1"
    assert envelope["component"] == "v907_verify"
    assert envelope["env_var"] == "WAKIR_V907_VERIFY_BACKEND"
    assert envelope["boots"] == 12
    assert envelope["dry_run"] == "completed"
    # Success-criterion: GREEN band, score >= 0.95.
    feas = envelope["feasibility"]
    assert feas["band"] == "GREEN", (
        f"expected GREEN band, got {feas['band']}; envelope={envelope}"
    )
    assert feas["cutover_feasibility_score"] >= 0.95
    # Twelve decisions, all chose rust, zero fallbacks.
    assert len(envelope["decisions"]) == 12
    assert envelope["chosen_backend_counts"] == {"rust": 12}
    assert envelope["fallback_reason_counts"].get("null", 0) == 12


# ---------------------------------------------------------------------------
# Test 7 — decision-render policy: ready iff all-green + band-floor.
# ---------------------------------------------------------------------------


# Standalone re-implementation of the workflow's Step-5 decision
# policy, kept in lockstep with the inline python in
# .github/workflows/phase-3c-welle-1-validation.yml. The workflow
# inline-python is the single source of truth at run-time; this
# helper is the testable mirror.
def _render_decision(
    *,
    gate_rc: int,
    dry_rc: int,
    boot_rc: int,
    bridge_rc: int,
    floor: str,
    trigger_report: Dict[str, Any],
    dry_run_envelope: Dict[str, Any],
) -> Dict[str, Any]:
    gate_ok = gate_rc == 0
    gate_tolerable = False
    if gate_rc == 1:
        gates = trigger_report.get("gates", [])
        non_green = [g for g in gates if g.get("status") != "green"]
        gate_tolerable = (
            len(non_green) == 1 and non_green[0].get("id") == "gate-4"
        )
    dry_ok = dry_rc == 0
    boot_ok = boot_rc == 0
    bridge_ok = bridge_rc in (0, 5)
    band = (
        dry_run_envelope.get("feasibility", {}).get("band", "UNKNOWN")
    )
    band_order = {"GREEN": 3, "AMBER": 2, "RED": 1, "BLOCKED": 0}
    band_score = band_order.get(band, 0)
    floor_score = band_order.get(floor.upper(), 3)
    band_ok = band_score >= floor_score
    ready = bool(
        (gate_ok or gate_tolerable)
        and dry_ok and boot_ok and bridge_ok and band_ok
    )
    return {
        "ready_for_live_smoke": ready,
        "gate_signal": (
            "green" if gate_ok
            else ("yellow_tolerated" if gate_tolerable else "red")
        ),
        "band_ok": band_ok,
        "observed_band": band,
    }


def test_decision_policy_ready_path() -> None:
    """All four steps green and band == GREEN -> ready_for_live_smoke."""
    trigger = {
        "gates": [
            {"id": f"gate-{i}", "status": "green"} for i in range(1, 6)
        ],
        "all_green": True,
    }
    envelope = {
        "feasibility": {"band": "GREEN", "cutover_feasibility_score": 1.0}
    }
    decision = _render_decision(
        gate_rc=0,
        dry_rc=0,
        boot_rc=0,
        bridge_rc=0,
        floor="GREEN",
        trigger_report=trigger,
        dry_run_envelope=envelope,
    )
    assert decision["ready_for_live_smoke"] is True
    assert decision["gate_signal"] == "green"


def test_decision_policy_gate4_yellow_tolerated() -> None:
    """Gate-4 yellow alone tolerated (observability-baseline ENV unset).

    The workflow accepts gate-aggregator exit 1 iff Gate-4 is the sole
    yellow gate, mirroring the ADR-0065 §Trigger-Bedingung-4 phrasing
    ("skip-with-warning when baseline ENV unset")."""
    trigger = {
        "gates": [
            {"id": "gate-1", "status": "green"},
            {"id": "gate-2", "status": "green"},
            {"id": "gate-3", "status": "green"},
            {"id": "gate-4", "status": "yellow"},
            {"id": "gate-5", "status": "green"},
        ]
    }
    envelope = {
        "feasibility": {"band": "GREEN", "cutover_feasibility_score": 0.98}
    }
    decision = _render_decision(
        gate_rc=1,
        dry_rc=0,
        boot_rc=0,
        bridge_rc=0,
        floor="GREEN",
        trigger_report=trigger,
        dry_run_envelope=envelope,
    )
    assert decision["ready_for_live_smoke"] is True
    assert decision["gate_signal"] == "yellow_tolerated"


def test_decision_policy_red_blocks_ready() -> None:
    """Any step red (gate-aggregator red, dry-run fail, persona-boot
    fail, bridge-audit fail) blocks ready_for_live_smoke."""
    trigger = {
        "gates": [
            {"id": "gate-1", "status": "red"},
            {"id": "gate-2", "status": "green"},
            {"id": "gate-3", "status": "green"},
            {"id": "gate-4", "status": "yellow"},
            {"id": "gate-5", "status": "green"},
        ]
    }
    envelope = {"feasibility": {"band": "GREEN"}}
    # Gate red.
    d1 = _render_decision(
        gate_rc=2, dry_rc=0, boot_rc=0, bridge_rc=0, floor="GREEN",
        trigger_report=trigger, dry_run_envelope=envelope,
    )
    assert d1["ready_for_live_smoke"] is False
    assert d1["gate_signal"] == "red"
    # Persona-boot red.
    d2 = _render_decision(
        gate_rc=0, dry_rc=0, boot_rc=1, bridge_rc=0, floor="GREEN",
        trigger_report=trigger, dry_run_envelope=envelope,
    )
    assert d2["ready_for_live_smoke"] is False


def test_decision_policy_band_floor_enforced() -> None:
    """Dry-run band below the configured floor blocks ready_for_live_smoke."""
    trigger = {
        "gates": [
            {"id": f"gate-{i}", "status": "green"} for i in range(1, 6)
        ]
    }
    envelope = {"feasibility": {"band": "AMBER"}}
    # Floor GREEN, observed AMBER -> not ready.
    d_blocked = _render_decision(
        gate_rc=0, dry_rc=0, boot_rc=0, bridge_rc=0, floor="GREEN",
        trigger_report=trigger, dry_run_envelope=envelope,
    )
    assert d_blocked["ready_for_live_smoke"] is False
    assert d_blocked["band_ok"] is False
    # Floor AMBER, observed AMBER -> ready.
    d_ok = _render_decision(
        gate_rc=0, dry_rc=0, boot_rc=0, bridge_rc=0, floor="AMBER",
        trigger_report=trigger, dry_run_envelope=envelope,
    )
    assert d_ok["ready_for_live_smoke"] is True


# ---------------------------------------------------------------------------
# Test 8 — artifact upload bundles the canonical paths.
# ---------------------------------------------------------------------------


def test_artifact_upload_bundles_canonical_paths(
    validation_steps: List[dict],
) -> None:
    """The trailing upload-artifact step must collect the five
    canonical output paths: the decision JSON, the trigger-report,
    the dry-run envelope, and the two pytest run logs."""
    upload = None
    for s in validation_steps:
        if (s.get("uses") or "").startswith("actions/upload-artifact@"):
            upload = s
            break
    assert upload is not None, "missing actions/upload-artifact step"
    with_block = upload.get("with") or {}
    assert with_block.get("name") == "cutover-acceptance-decision"
    paths_block = with_block.get("path") or ""
    # The YAML multi-line ``|`` block becomes a string with newlines.
    assert "cutover-acceptance-decision.json" in paths_block
    assert "trigger-gate-report.json" in paths_block
    assert "dry-run-envelope.json" in paths_block
    assert "persona-boot.log" in paths_block
    assert "bridge-audit.log" in paths_block
    # retention-days must be set (default would be 90 — too generous).
    assert with_block.get("retention-days") == 30
    # always() guard so the artifact ships even on failure runs.
    assert upload.get("if") == "always()"
