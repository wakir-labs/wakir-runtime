# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic workflow-structure tests for
``.github/workflows/phase-3c-welle-3-validation.yml``.

Sprint-Tag-31 Mini-Welle (Phase-3c Welle-3 Validation, ADR-0065 +
ADR-0066 solo-execution, Henrik-Caution).

These tests assert the workflow STRUCTURE stays stable so a future
edit that drops a step or breaks the gate-aggregation / dry-run /
cross-modul-stress / decision-render contract regresses with a clear
hermetic-test failure rather than only via the wednesday-cron run.

Siblings:

* ``tests/workflows/test_phase_3c_welle_1_validation.py`` covers the
  same contract for the Welle-1 ``v907_verify`` workflow.
* ``tests/workflows/test_phase_3c_welle_2_validation.py`` covers the
  same contract for the Welle-2 ``svid_workload_identity`` workflow.
* Welle-3 (this file) covers the ``bridge_audit_writer`` workflow.
  The key structural delta: Step 4 is the independent cross-modul-
  stress oracle, NOT the bridge-audit-roundtrip-e2e test (Henrik-
  Caution per ADR-0066 §"Bridge-Audit-Welle bleibt strikt solo").

Sandbox boundary
----------------

Tests parse YAML on disk only. No actions runner, no podman, no
GHCR egress, no live-VM. The dry-run / aggregator / score-aggregator
modules are composed against synthetic inputs that mirror the
workflow's step-1 / step-2 / step-4 invocations.
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
    REPO_ROOT / ".github" / "workflows" / "phase-3c-welle-3-validation.yml"
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
    job = jobs.get("phase-3c-welle-3-validation")
    assert job is not None, (
        "workflow missing 'phase-3c-welle-3-validation' job"
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
    assert workflow_yaml.get("name") == "phase-3c-welle-3-validation"
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
    workflow_dispatch with the three documented inputs. Same cadence as
    Welle-1/2 (the canonical readiness slot three days before the
    Monday Pilot-VM Live-Smoke)."""
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
    steps (gate-aggregator, dry-run, persona-boot, cross-modul-stress,
    decision-render) in that order, plus the standard checkout +
    setup-python + install + inputs + mkdir prelude and the artifact
    upload at the tail.

    Welle-3 specifically: Step 4 id is ``cross-modul-stress`` (NOT
    ``bridge-audit``), reflecting the Henrik-Caution oracle swap."""

    step_ids = [s.get("id") for s in validation_steps if s.get("id")]
    expected_ids = [
        "inputs",
        "gate-aggregator",
        "dry-run",
        "persona-boot",
        "cross-modul-stress",
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
        "Step 4 -",  # independent cross-lang oracle (Henrik-Caution)
        "Step 5 -",  # render cutover-acceptance-decision
    ):
        assert any(
            n and n.replace("—", "-").startswith(required_prefix)
            for n in step_names
        ), (
            f"missing step with name prefix {required_prefix!r}; "
            f"got {step_names}"
        )
    # Welle-3-specific: Step 4 name must reference Henrik-Caution
    # and the independent oracle.
    step_4_name = next(
        (n for n in step_names if n and "Step 4" in n), ""
    )
    assert "Henrik" in step_4_name or "independent" in step_4_name.lower(), (
        f"Step 4 name does not surface Henrik-Caution: {step_4_name!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — invocation contracts: scripts + tests + env-vars (long + short).
# ---------------------------------------------------------------------------


def test_step_invocation_contracts(
    validation_steps: List[dict],
) -> None:
    """Each numbered step references a real in-repo artifact:
    aggregator script (Step 1), dry-run script with
    ``--component bridge_audit_writer`` (Step 2),
    rust_backend_switch test file with ``-k anchor_emitter`` (Step 3),
    doppelbetrieb-score-aggregator with
    ``--mode=cross-modul-stress`` (Step 4). The render step (Step 5)
    is in-line python and is validated by Test 7 instead.

    Step 3 MUST set BOTH ``WAKIR_BRIDGE_AUDIT_WRITER_BACKEND=rust``
    (ADR-0065 long-form, operator-facing) AND
    ``WAKIR_ANCHOR_EMITTER_BACKEND=rust`` (resolver-actual) on the
    step env — that is the Welle-3-specific alias-bridge contract."""
    by_id = {s.get("id"): s for s in validation_steps if s.get("id")}

    # Step 1: aggregator script + --target-binary-count + --json.
    gate_run = by_id["gate-aggregator"].get("run") or ""
    assert (
        "scripts/phase-3c-trigger-gate-aggregator.py" in gate_run
    ), "Step 1 missing aggregator script reference"
    assert "--target-binary-count" in gate_run
    assert "--json" in gate_run
    assert (REPO_ROOT / "scripts" / "phase-3c-trigger-gate-aggregator.py").is_file()

    # Step 2: dry-run script + --component bridge_audit_writer (via
    # the WELLE_COMPONENT env-var) + --boots + --output.
    dry_run = by_id["dry-run"].get("run") or ""
    assert "scripts/phase-3c-cutover-dry-run.py" in dry_run
    assert "--component" in dry_run
    assert "--boots" in dry_run
    assert "--output" in dry_run
    assert (REPO_ROOT / "scripts" / "phase-3c-cutover-dry-run.py").is_file()

    # Step 3: pytest on rust_backend_switch test file with
    # -k anchor_emitter (the short-form test-function-name
    # convention). Both env-var spellings must be set.
    boot_run = by_id["persona-boot"].get("run") or ""
    assert (
        "wirelang/tests/persona_engine/test_rust_backend_switch.py"
        in boot_run
    )
    assert "anchor_emitter" in boot_run, (
        f"Step 3 must filter pytest by -k anchor_emitter; "
        f"got run: {boot_run!r}"
    )
    boot_env = by_id["persona-boot"].get("env") or {}
    assert (
        boot_env.get("WAKIR_BRIDGE_AUDIT_WRITER_BACKEND") == "rust"
    ), (
        f"Step 3 ADR-0065-long-form env-var missing or wrong: {boot_env}"
    )
    assert (
        boot_env.get("WAKIR_ANCHOR_EMITTER_BACKEND") == "rust"
    ), (
        f"Step 3 resolver-actual env-var missing or wrong: {boot_env}"
    )
    assert (
        REPO_ROOT
        / "wirelang"
        / "tests"
        / "persona_engine"
        / "test_rust_backend_switch.py"
    ).is_file()

    # Step 4 (Henrik-Caution): doppelbetrieb-score-aggregator with
    # --mode=cross-modul-stress. Must NOT reference the bridge-audit-
    # roundtrip-e2e oracle (that would be self-Oracle for Welle-3).
    stress_run = by_id["cross-modul-stress"].get("run") or ""
    assert "scripts/doppelbetrieb-score-aggregator.py" in stress_run, (
        f"Step 4 missing score-aggregator script reference; "
        f"got: {stress_run!r}"
    )
    assert "--mode=cross-modul-stress" in stress_run, (
        f"Step 4 must run --mode=cross-modul-stress (Henrik-Caution); "
        f"got: {stress_run!r}"
    )
    assert "test_bridge_audit_roundtrip_e2e" not in stress_run, (
        "Step 4 must NOT use bridge_audit_roundtrip_e2e as oracle "
        "(Henrik-Caution: subject under cutover cannot certify itself)"
    )
    assert (
        REPO_ROOT / "scripts" / "doppelbetrieb-score-aggregator.py"
    ).is_file()


def test_job_level_env_pins_bridge_audit_writer_component(
    validation_job: dict,
) -> None:
    """The job-level env block must pin WELLE_COMPONENT to
    ``bridge_audit_writer`` (ADR-0065 long-form), WELLE_ENV_VAR to
    the matching long-form env-var name, and WELLE_RESOLVER_ENV_VAR
    to the in-repo short-form resolver env-var.

    This is the self-documenting alias-bridge contract: the dry-run
    accepts the long-form name and normalises internally to
    ``anchor_emitter`` via PHASE_3C_COMPONENT_ALIASES; the persona-
    boot step needs the short-form env-var so the resolver picks up
    the flip via os.environ."""
    env = validation_job.get("env") or {}
    assert env.get("WELLE_COMPONENT") == "bridge_audit_writer", (
        f"WELLE_COMPONENT drift: {env}"
    )
    assert (
        env.get("WELLE_ENV_VAR") == "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND"
    ), f"WELLE_ENV_VAR (long-form) drift: {env}"
    assert (
        env.get("WELLE_RESOLVER_ENV_VAR")
        == "WAKIR_ANCHOR_EMITTER_BACKEND"
    ), f"WELLE_RESOLVER_ENV_VAR (short-form) drift: {env}"


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
    # Use a distinct module name so this file's import does not collide
    # with the Welle-1/2 test files' fixture caches.
    return _load_module("phase_3c_trigger_gate_aggregator_welle3_wf", path)


@pytest.fixture(scope="module")
def dry_run_module():
    path = REPO_ROOT / "scripts" / "phase-3c-cutover-dry-run.py"
    return _load_module("phase_3c_cutover_dry_run_welle3_wf", path)


# ---------------------------------------------------------------------------
# Test 5 — alias-resolution: bridge_audit_writer normalises to anchor_emitter.
# ---------------------------------------------------------------------------


def test_dry_run_accepts_bridge_audit_writer_alias(dry_run_module) -> None:
    """The dry-run script's component-acceptance contract MUST accept
    ``bridge_audit_writer`` (ADR-0065 long-form) and normalise to
    ``anchor_emitter`` (in-repo short-form).

    Without this alias, the workflow's Step 2 invocation
    ``--component bridge_audit_writer`` would fail with
    UnknownComponentError, breaking the entire Welle-3 readiness
    check."""
    # Alias normalisation:
    assert (
        dry_run_module.validate_component("bridge_audit_writer")
        == "anchor_emitter"
    )
    # Long-form is registered in the alias map:
    assert (
        "bridge_audit_writer" in dry_run_module.PHASE_3C_COMPONENT_ALIASES
    )
    assert (
        dry_run_module.PHASE_3C_COMPONENT_ALIASES["bridge_audit_writer"]
        == "anchor_emitter"
    )
    # Resolver-actual contract on the short-form:
    assert (
        dry_run_module.COMPONENT_TO_ENV["anchor_emitter"]
        == "WAKIR_ANCHOR_EMITTER_BACKEND"
    )
    assert (
        dry_run_module.COMPONENT_TO_RUST_VALUE["anchor_emitter"] == "rust"
    )


# ---------------------------------------------------------------------------
# Test 6 — dry-run success-criteria for bridge_audit_writer (via alias).
# ---------------------------------------------------------------------------


def test_dry_run_success_criteria_bridge_audit_writer(
    dry_run_module,
) -> None:
    """The bridge_audit_writer dry-run with the workflow's default
    boots count (12) and stub binary-probe must produce a GREEN
    feasibility envelope (all-rust purity, zero fallbacks, latency
    well under budget). This is the substance contract the workflow's
    Step-2 acceptance-decision logic depends on: dry-run band >= GREEN
    floor."""

    # Stub resolver that mirrors the anchor_emitter resolver shape.
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Decision:
        chosen_backend: str
        fallback_reason: Any
        resolution_latency_us: int
        domain: str

    class _StubResolverModule:
        @staticmethod
        def resolve_anchor_emitter_backend(
            *, env, log_sink, binary_probe
        ):
            requested = env.get(
                "WAKIR_ANCHOR_EMITTER_BACKEND", "python"
            )
            return (
                requested,
                _Decision(
                    chosen_backend=requested,
                    fallback_reason=None,
                    resolution_latency_us=42,  # well under 50 ms budget
                    domain="anchor_emitter",
                ),
            )

    # Note: dry_run accepts the long-form name and normalises to
    # anchor_emitter internally; we pass the normalised short-form
    # here because the dry-run's run_dry_run helper expects an
    # already-validated component name.
    envelope = dry_run_module.run_dry_run(
        component="anchor_emitter",
        boots=12,
        resolver_module=_StubResolverModule(),
        now_ts=0,
    )
    # Schema + bookkeeping invariants.
    assert envelope["schema"] == "wakir.phase-3c.dry-run/1"
    assert envelope["component"] == "anchor_emitter"
    assert envelope["env_var"] == "WAKIR_ANCHOR_EMITTER_BACKEND"
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
# .github/workflows/phase-3c-welle-3-validation.yml. The workflow
# inline-python is the single source of truth at run-time; this
# helper is the testable mirror.
def _render_decision(
    *,
    gate_rc: int,
    dry_rc: int,
    boot_rc: int,
    stress_rc: int,
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
    # Step 4 (Henrik-Caution): exit 0 = independent oracle threshold-
    # pass. No "all-skip" tolerance (the aggregator is deterministic).
    stress_ok = stress_rc == 0
    band = (
        dry_run_envelope.get("feasibility", {}).get("band", "UNKNOWN")
    )
    band_order = {"GREEN": 3, "AMBER": 2, "RED": 1, "BLOCKED": 0}
    band_score = band_order.get(band, 0)
    floor_score = band_order.get(floor.upper(), 3)
    band_ok = band_score >= floor_score
    ready = bool(
        (gate_ok or gate_tolerable)
        and dry_ok and boot_ok and stress_ok and band_ok
    )
    return {
        "ready_for_live_smoke": ready,
        "gate_signal": (
            "green" if gate_ok
            else ("yellow_tolerated" if gate_tolerable else "red")
        ),
        "band_ok": band_ok,
        "observed_band": band,
        "stress_ok": stress_ok,
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
        stress_rc=0,
        floor="GREEN",
        trigger_report=trigger,
        dry_run_envelope=envelope,
    )
    assert decision["ready_for_live_smoke"] is True
    assert decision["gate_signal"] == "green"
    assert decision["stress_ok"] is True


def test_decision_policy_henrik_caution_red_blocks_ready() -> None:
    """Welle-3-specific: even when all other steps are green, a RED
    independent-oracle (cross-modul-stress) blocks ready_for_live_smoke.
    This is the Henrik-Caution backstop: the independent consistency
    signal MUST be green for Welle-3 to advance."""
    trigger = {
        "gates": [
            {"id": f"gate-{i}", "status": "green"} for i in range(1, 6)
        ]
    }
    envelope = {"feasibility": {"band": "GREEN"}}
    decision = _render_decision(
        gate_rc=0,
        dry_rc=0,
        boot_rc=0,
        stress_rc=1,  # independent oracle threshold-fail
        floor="GREEN",
        trigger_report=trigger,
        dry_run_envelope=envelope,
    )
    assert decision["ready_for_live_smoke"] is False
    assert decision["stress_ok"] is False


def test_decision_policy_gate4_yellow_tolerated() -> None:
    """Gate-4 yellow alone tolerated (observability-baseline ENV unset).

    The workflow accepts gate-aggregator exit 1 iff Gate-4 is the sole
    yellow gate, mirroring the ADR-0065 §Trigger-Bedingung-4 phrasing."""
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
        stress_rc=0,
        floor="GREEN",
        trigger_report=trigger,
        dry_run_envelope=envelope,
    )
    assert decision["ready_for_live_smoke"] is True
    assert decision["gate_signal"] == "yellow_tolerated"


def test_decision_policy_red_blocks_ready() -> None:
    """Any step red (gate-aggregator red, dry-run fail, persona-boot
    fail) blocks ready_for_live_smoke (cross-modul-stress red is
    covered by the dedicated Henrik-Caution test above)."""
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
        gate_rc=2, dry_rc=0, boot_rc=0, stress_rc=0, floor="GREEN",
        trigger_report=trigger, dry_run_envelope=envelope,
    )
    assert d1["ready_for_live_smoke"] is False
    assert d1["gate_signal"] == "red"
    # Persona-boot red.
    d2 = _render_decision(
        gate_rc=0, dry_rc=0, boot_rc=1, stress_rc=0, floor="GREEN",
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
        gate_rc=0, dry_rc=0, boot_rc=0, stress_rc=0, floor="GREEN",
        trigger_report=trigger, dry_run_envelope=envelope,
    )
    assert d_blocked["ready_for_live_smoke"] is False
    assert d_blocked["band_ok"] is False
    # Floor AMBER, observed AMBER -> ready.
    d_ok = _render_decision(
        gate_rc=0, dry_rc=0, boot_rc=0, stress_rc=0, floor="AMBER",
        trigger_report=trigger, dry_run_envelope=envelope,
    )
    assert d_ok["ready_for_live_smoke"] is True


# ---------------------------------------------------------------------------
# Test 8 — artifact upload bundles the canonical paths (Welle-3 set).
# ---------------------------------------------------------------------------


def test_artifact_upload_bundles_canonical_paths(
    validation_steps: List[dict],
) -> None:
    """The trailing upload-artifact step must collect the canonical
    output paths: the decision JSON, the trigger-report, the dry-run
    envelope, the persona-boot pytest log + junit, and (Welle-3-
    specific) the cross-modul-stress log + rollup.

    Welle-3 names the artifact bundle ``cutover-acceptance-decision-
    welle-3`` so the readiness reports do not collide on the GitHub
    Actions artifact namespace."""
    upload = None
    for s in validation_steps:
        if (s.get("uses") or "").startswith("actions/upload-artifact@"):
            upload = s
            break
    assert upload is not None, "missing actions/upload-artifact step"
    with_block = upload.get("with") or {}
    assert (
        with_block.get("name") == "cutover-acceptance-decision-welle-3"
    ), f"artifact name drift: {with_block.get('name')!r}"
    paths_block = with_block.get("path") or ""
    # The YAML multi-line ``|`` block becomes a string with newlines.
    assert "cutover-acceptance-decision.json" in paths_block
    assert "trigger-gate-report.json" in paths_block
    assert "dry-run-envelope.json" in paths_block
    assert "persona-boot.log" in paths_block
    # Welle-3-specific bundle members (independent-oracle artifacts):
    assert "cross-modul-stress.log" in paths_block, (
        "Welle-3 artifact bundle must include cross-modul-stress.log"
    )
    assert "cross-modul-stress-rollup.json" in paths_block, (
        "Welle-3 artifact bundle must include cross-modul-stress-rollup.json"
    )
    # The bridge-audit log MUST NOT be in the bundle (Welle-3 does not
    # run the bridge-audit-roundtrip oracle).
    assert "bridge-audit.log" not in paths_block, (
        "Welle-3 artifact bundle must NOT include bridge-audit.log "
        "(Welle-3 swaps the oracle for cross-modul-stress per Henrik-"
        "Caution)"
    )
    # retention-days must be set (default would be 90 — too generous).
    assert with_block.get("retention-days") == 30
    # always() guard so the artifact ships even on failure runs.
    assert upload.get("if") == "always()"


# ---------------------------------------------------------------------------
# Test 9 — Henrik-Caution self-documenting marker in the decision schema.
# ---------------------------------------------------------------------------


def test_decision_render_carries_henrik_caution_marker(
    workflow_text: str,
) -> None:
    """The Step-5 decision JSON envelope must carry an explicit
    ``henrik_caution_applied: true`` marker and document the
    independent-oracle source. This is the audit-trail substrate
    Henrik consumes to verify the Welle-3 readiness check applied
    the ADR-0066 §Bridge-Audit-Welle discipline.

    Implementation: the inline python in the workflow writes the
    decision JSON with the marker; we assert the marker literal is
    present in the workflow source (we cannot run the inline python
    hermetic in this test, but the literal-presence guard catches
    the most common drift: a future edit that removes the marker
    or mistypes it)."""
    assert '"henrik_caution_applied": True' in workflow_text, (
        "decision schema must carry henrik_caution_applied=True"
    )
    assert "doppelbetrieb-score-aggregator --mode=cross-modul-stress" in workflow_text, (
        "decision schema must document the independent-oracle source"
    )
    # Welle-3 schema version.
    assert '"schema": "wakir.phase-3c.welle-3-validation/1"' in workflow_text, (
        "decision envelope must declare the Welle-3 schema version"
    )
