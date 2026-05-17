# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic workflow-structure tests for the Phase-3c Welle-4/5/6/7
validation workflows.

Sprint-Tag-32 Mini-Welle (Phase-3c Welle-4-7 Bundle, ADR-0065 +
ADR-0066 parallel-execution).

This file is the test counterpart for the Bundle-PR that ships the
four sibling validation workflows in one go:

* `.github/workflows/phase-3c-welle-4-validation.yml`
  (`state_backing`, KW 26 Doppel-Welle with Welle-5)
* `.github/workflows/phase-3c-welle-5-validation.yml`
  (`lifecycle_state_machine`, KW 26 Doppel-Welle with Welle-4)
* `.github/workflows/phase-3c-welle-6-validation.yml`
  (`subscribe_loop`, KW 27 Doppel-Welle with Welle-7)
* `.github/workflows/phase-3c-welle-7-validation.yml`
  (`recovery_workflow`, KW 27 Doppel-Welle with Welle-6)

Assertion shape mirrors the per-welle test files
(`test_phase_3c_welle_1_validation.py`,
`test_phase_3c_welle_2_validation.py`) so a future single-workflow
drift surfaces against all five test files. The Welle-4-7 file uses
parameter-ised fixtures because the four workflows share most of
their contract; per-welle deltas (cross-modul step on Welle-4/5,
env-var per component) are asserted in dedicated tests.

Sandbox boundary
----------------

Tests parse YAML on disk only. No actions runner, no podman, no
GHCR egress, no live-VM. The dry-run / aggregator scoring contract
is validated by composing the in-tree aggregator + dry-run modules
against synthetic inputs that mirror the workflow's step-1 / step-2
invocations.

Test count (16+ as required by Bundle-Auftrag)
----------------------------------------------

Per-welle smoke (Tests 1-4, parametrised over 4 wellen = 16 tests):

  Test 1: YAML format + permissions invariant.
  Test 2: trigger surface (schedule + workflow_dispatch).
  Test 3: validation step order + step-ids.
  Test 4: step invocation contracts (scripts, tests, env-vars).

Bundle-specific assertions (Tests 5+):

  Test 5: Welle-4/5 carry the cross-modul-stress step; Welle-6/7 do not.
  Test 6: each workflow's env block pins the right component.
  Test 7: dry-run module accepts each welle's component spelling.
  Test 8: decision-render policy mirrors workflow inline-python.
  Test 9: artifact upload bundles canonical paths per welle.
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
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


# Per-welle fixture metadata. Keys map to the workflow path, the
# canonical job-id, the component short name used in the dry-run
# substrate, the env-var the rust opt-in carries, the pytest -k
# selector for the rust_backend_switch test vectors, the requested
# Rust value (almost all "rust" except state_backing which uses
# "rust_inmemory"), whether the workflow carries the cross-modul-
# stress step (Welle-4/5 only), the long-form component name for
# the decision envelope, the artifact bundle name, and the doppel-
# welle partner component name.
WELLE_TABLE: Dict[int, Dict[str, Any]] = {
    4: {
        "workflow": WORKFLOWS_DIR / "phase-3c-welle-4-validation.yml",
        "job_id": "phase-3c-welle-4-validation",
        "component_short": "state_backing",
        "component_long": "state_backing",
        "env_var": "WAKIR_STATE_BACKING_BACKEND",
        "rust_value": "rust_inmemory",
        "pytest_selector": "state_backing",
        "has_cross_modul": True,
        "artifact_name": "cutover-acceptance-decision-welle-4",
        "doppel_partner": "lifecycle_state_machine",
        "decision_schema": "wakir.phase-3c.welle-4-validation/1",
    },
    5: {
        "workflow": WORKFLOWS_DIR / "phase-3c-welle-5-validation.yml",
        "job_id": "phase-3c-welle-5-validation",
        "component_short": "fsm",
        "component_long": "lifecycle_state_machine",
        "env_var": "WAKIR_FSM_BACKEND",
        "rust_value": "rust",
        "pytest_selector": "fsm",
        "has_cross_modul": True,
        "artifact_name": "cutover-acceptance-decision-welle-5",
        "doppel_partner": "state_backing",
        "decision_schema": "wakir.phase-3c.welle-5-validation/1",
    },
    6: {
        "workflow": WORKFLOWS_DIR / "phase-3c-welle-6-validation.yml",
        "job_id": "phase-3c-welle-6-validation",
        "component_short": "subscribe_loop",
        "component_long": "subscribe_loop",
        "env_var": "WAKIR_SUBSCRIBE_LOOP_BACKEND",
        "rust_value": "rust",
        "pytest_selector": "subscribe_loop",
        "has_cross_modul": False,
        "artifact_name": "cutover-acceptance-decision-welle-6",
        "doppel_partner": "recovery_workflow",
        "decision_schema": "wakir.phase-3c.welle-6-validation/1",
    },
    7: {
        "workflow": WORKFLOWS_DIR / "phase-3c-welle-7-validation.yml",
        "job_id": "phase-3c-welle-7-validation",
        "component_short": "recovery",
        "component_long": "recovery_workflow",
        "env_var": "WAKIR_RECOVERY_BACKEND",
        "rust_value": "rust",
        "pytest_selector": "recovery",
        "has_cross_modul": False,
        "artifact_name": "cutover-acceptance-decision-welle-7",
        "doppel_partner": "subscribe_loop",
        "decision_schema": "wakir.phase-3c.welle-7-validation/1",
    },
}


def _load_yaml(p: Path) -> dict:
    assert p.is_file(), f"missing workflow: {p}"
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _job(workflow_yaml: dict, job_id: str) -> dict:
    jobs = workflow_yaml.get("jobs", {})
    assert job_id in jobs, f"missing job {job_id!r} in {list(jobs.keys())}"
    return jobs[job_id]


def _steps(job: dict) -> List[dict]:
    steps = job.get("steps") or []
    assert isinstance(steps, list) and steps, "job has no steps"
    return steps


# ---------------------------------------------------------------------------
# Parametrised Tests 1-4 - per-welle smoke (16 tests total).
# ---------------------------------------------------------------------------


@pytest.fixture(params=sorted(WELLE_TABLE.keys()), ids=lambda w: f"welle-{w}")
def welle(request) -> Dict[str, Any]:
    """Yields one welle metadata dict per parametrisation."""
    meta = dict(WELLE_TABLE[request.param])
    meta["welle"] = request.param
    return meta


@pytest.fixture
def workflow_yaml(welle: Dict[str, Any]) -> dict:
    return _load_yaml(welle["workflow"])


@pytest.fixture
def validation_job(workflow_yaml: dict, welle: Dict[str, Any]) -> dict:
    return _job(workflow_yaml, welle["job_id"])


@pytest.fixture
def validation_steps(validation_job: dict) -> List[dict]:
    return _steps(validation_job)


# Test 1 (parametrised x 4 wellen).
def test_workflow_yaml_format_and_top_level(
    workflow_yaml: dict, welle: Dict[str, Any]
) -> None:
    """YAML parses, name matches, permissions least-privilege
    (`contents: read` only)."""
    assert workflow_yaml.get("name") == welle["job_id"], (
        f"workflow name drift: {workflow_yaml.get('name')!r}"
    )
    perms = workflow_yaml.get("permissions")
    assert isinstance(perms, dict), "missing top-level permissions"
    assert perms.get("contents") == "read"
    assert set(perms.keys()) == {"contents"}, (
        f"unexpected permission scopes: {sorted(perms.keys())}"
    )


# Test 2 (parametrised x 4 wellen).
def test_trigger_surface_schedule_and_dispatch(
    workflow_yaml: dict, welle: Dict[str, Any]
) -> None:
    """Wednesday-06:00-UTC cron + three documented dispatch inputs."""
    # PyYAML parses the bare ``on:`` key as Python True; allow both.
    on = workflow_yaml.get(True) or workflow_yaml.get("on")
    assert on is not None, "missing 'on' block"
    schedule = on.get("schedule")
    assert isinstance(schedule, list) and len(schedule) == 1
    assert schedule[0].get("cron") == "0 6 * * 3", (
        f"welle-{welle['welle']} cron drift: {schedule[0].get('cron')!r}"
    )
    dispatch = on.get("workflow_dispatch")
    assert dispatch is not None, "missing workflow_dispatch"
    inputs = dispatch.get("inputs") or {}
    assert set(inputs.keys()) == {
        "target-binary-count",
        "boots",
        "score-band-floor",
    }, f"welle-{welle['welle']} dispatch inputs drift: {sorted(inputs.keys())}"
    for name, spec in inputs.items():
        assert "default" in spec, (
            f"welle-{welle['welle']} input {name!r} missing default"
        )


# Test 3 (parametrised x 4 wellen).
def test_validation_steps_in_order(
    validation_steps: List[dict], welle: Dict[str, Any]
) -> None:
    """Mandatory step-ids in chronological order. Welle-4/5 carry the
    extra `cross-modul-stress` step; Welle-6/7 do not."""
    step_ids = [s.get("id") for s in validation_steps if s.get("id")]
    expected = [
        "inputs",
        "gate-aggregator",
        "dry-run",
        "persona-boot",
        "bridge-audit",
    ]
    if welle["has_cross_modul"]:
        expected.append("cross-modul-stress")
    expected.append("decision")
    indices = [step_ids.index(x) for x in expected]
    assert indices == sorted(indices), (
        f"welle-{welle['welle']} step-id order drift: {step_ids}"
    )


# Test 4 (parametrised x 4 wellen).
def test_step_invocation_contracts(
    validation_steps: List[dict], welle: Dict[str, Any]
) -> None:
    """Each step references real in-repo artifacts and the persona-boot
    step pins the right env-var."""
    by_id = {s.get("id"): s for s in validation_steps if s.get("id")}

    # Step 1: aggregator script + --target-binary-count + --json.
    gate_run = by_id["gate-aggregator"].get("run") or ""
    assert "scripts/phase-3c-trigger-gate-aggregator.py" in gate_run
    assert "--target-binary-count" in gate_run
    assert "--json" in gate_run
    assert (REPO_ROOT / "scripts" / "phase-3c-trigger-gate-aggregator.py").is_file()

    # Step 2: dry-run script with the welle's component (via env).
    dry_run = by_id["dry-run"].get("run") or ""
    assert "scripts/phase-3c-cutover-dry-run.py" in dry_run
    assert "--component" in dry_run
    assert "--boots" in dry_run
    assert "--output" in dry_run
    assert (REPO_ROOT / "scripts" / "phase-3c-cutover-dry-run.py").is_file()

    # Step 3: rust_backend_switch test file with pytest -k selector +
    # the welle-specific env-var carrying the right Rust value.
    boot_step = by_id["persona-boot"]
    boot_run = boot_step.get("run") or ""
    assert (
        "wirelang/tests/persona_engine/test_rust_backend_switch.py"
        in boot_run
    )
    assert welle["pytest_selector"] in boot_run, (
        f"welle-{welle['welle']} pytest -k drift"
    )
    boot_env = boot_step.get("env") or {}
    assert boot_env.get(welle["env_var"]) == welle["rust_value"], (
        f"welle-{welle['welle']} env-var drift: "
        f"{welle['env_var']}={boot_env.get(welle['env_var'])!r}; "
        f"expected {welle['rust_value']!r}"
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
        REPO_ROOT / "tests" / "integration" / "test_bridge_audit_roundtrip_e2e.py"
    ).is_file()


# ---------------------------------------------------------------------------
# Test 5 - cross-modul-stress step only on Welle-4 and Welle-5.
# ---------------------------------------------------------------------------


def test_cross_modul_stress_step_only_on_welle_4_and_5() -> None:
    """The KW-26 Doppel-Welle (Welle-4 + Welle-5) carries the cross-
    modul-stress step per ADR-0066 §Mitigations §1. Welle-6 and Welle-7
    (KW-27 Doppel-Welle) rely on the regular Phase-2-Acceptance-Gate
    daily rollup which already aggregates the subscribe_loop x
    recovery_workflow drift axis. The Bundle-Auftrag (Tag-32) is
    explicit about this asymmetry; this test pins it."""
    for w in (4, 5):
        meta = WELLE_TABLE[w]
        steps = _steps(_job(_load_yaml(meta["workflow"]), meta["job_id"]))
        ids = [s.get("id") for s in steps if s.get("id")]
        assert "cross-modul-stress" in ids, (
            f"welle-{w} missing cross-modul-stress step"
        )
        # The step must invoke the aggregator with the cross-modul-stress mode.
        cm_step = next(s for s in steps if s.get("id") == "cross-modul-stress")
        run = cm_step.get("run") or ""
        assert "scripts/doppelbetrieb-score-aggregator.py" in run
        assert "--mode cross-modul-stress" in run
        assert "out/cross-modul-stress.json" in run
    for w in (6, 7):
        meta = WELLE_TABLE[w]
        steps = _steps(_job(_load_yaml(meta["workflow"]), meta["job_id"]))
        ids = [s.get("id") for s in steps if s.get("id")]
        assert "cross-modul-stress" not in ids, (
            f"welle-{w} unexpectedly carries cross-modul-stress step"
        )


# ---------------------------------------------------------------------------
# Test 6 - job-level env block pins the right component per welle.
# ---------------------------------------------------------------------------


def test_job_level_env_pins_per_welle_component() -> None:
    """Each workflow's job-level env block pins WELLE_COMPONENT to the
    welle's component short-form and WELLE_ENV_VAR to the matching
    env-var name. Welle-5 and Welle-7 additionally carry
    WELLE_COMPONENT_LONG with the ADR-0066 long-form name."""
    for w, meta in WELLE_TABLE.items():
        job = _job(_load_yaml(meta["workflow"]), meta["job_id"])
        env = job.get("env") or {}
        assert env.get("WELLE_COMPONENT") == meta["component_short"], (
            f"welle-{w} WELLE_COMPONENT drift: {env}"
        )
        assert env.get("WELLE_ENV_VAR") == meta["env_var"], (
            f"welle-{w} WELLE_ENV_VAR drift: {env}"
        )
        if w in (5, 7):
            assert (
                env.get("WELLE_COMPONENT_LONG") == meta["component_long"]
            ), (
                f"welle-{w} missing WELLE_COMPONENT_LONG; got env={env}"
            )


# ---------------------------------------------------------------------------
# Helpers - load dry-run + aggregator modules for live composition.
# ---------------------------------------------------------------------------


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def dry_run_module():
    path = REPO_ROOT / "scripts" / "phase-3c-cutover-dry-run.py"
    return _load_module("phase_3c_cutover_dry_run_welle_4_7_bundle", path)


# ---------------------------------------------------------------------------
# Test 7 - dry-run module accepts each welle's component spelling.
# ---------------------------------------------------------------------------


def test_dry_run_module_accepts_welle_components(dry_run_module) -> None:
    """The dry-run script must accept each welle's component spelling
    (long form for Welle-5/7, short form for Welle-4/6) and normalise
    to the in-repo short form. The COMPONENT_TO_ENV +
    COMPONENT_TO_RUST_VALUE maps must carry the expected entries."""
    for w, meta in WELLE_TABLE.items():
        # Long-form alias resolves to short-form.
        normalised = dry_run_module.validate_component(meta["component_long"])
        assert normalised == meta["component_short"], (
            f"welle-{w} alias drift: "
            f"{meta['component_long']!r} -> {normalised!r}"
        )
        # Short-form acceptance.
        assert (
            dry_run_module.validate_component(meta["component_short"])
            == meta["component_short"]
        )
        # Component is registered in PHASE_3C_COMPONENTS.
        assert (
            meta["component_short"] in dry_run_module.PHASE_3C_COMPONENTS
        )
        # Env-var map.
        assert (
            dry_run_module.COMPONENT_TO_ENV[meta["component_short"]]
            == meta["env_var"]
        )
        # Rust-value map (state_backing = rust_inmemory; others = rust).
        assert (
            dry_run_module.COMPONENT_TO_RUST_VALUE[meta["component_short"]]
            == meta["rust_value"]
        )


# ---------------------------------------------------------------------------
# Test 8 - decision-render policy mirrors the workflow inline-python.
# ---------------------------------------------------------------------------


def _render_decision(
    *,
    gate_rc: int,
    dry_rc: int,
    boot_rc: int,
    bridge_rc: int,
    cross_modul_rc: int = 0,
    has_cross_modul: bool = False,
    floor: str,
    trigger_report: Dict[str, Any],
    dry_run_envelope: Dict[str, Any],
) -> Dict[str, Any]:
    """Standalone re-implementation of the workflow's decision-render
    inline-python. Kept in lockstep with the four workflows; the
    workflow inline-python is the run-time single source of truth and
    this helper is the testable mirror."""
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
    cross_modul_ok = (cross_modul_rc == 0) if has_cross_modul else True
    band = dry_run_envelope.get("feasibility", {}).get("band", "UNKNOWN")
    band_order = {"GREEN": 3, "AMBER": 2, "RED": 1, "BLOCKED": 0}
    band_score = band_order.get(band, 0)
    floor_score = band_order.get(floor.upper(), 3)
    band_ok = band_score >= floor_score
    ready = bool(
        (gate_ok or gate_tolerable)
        and dry_ok and boot_ok and bridge_ok and band_ok
        and cross_modul_ok
    )
    return {
        "ready_for_live_smoke": ready,
        "gate_signal": (
            "green" if gate_ok
            else ("yellow_tolerated" if gate_tolerable else "red")
        ),
        "band_ok": band_ok,
        "observed_band": band,
        "cross_modul_ok": cross_modul_ok,
    }


def test_decision_policy_ready_path_all_wellen() -> None:
    """All four steps green and band == GREEN -> ready. For Welle-4/5
    also requires cross-modul-stress green. Both arms covered."""
    trigger = {
        "gates": [
            {"id": f"gate-{i}", "status": "green"} for i in range(1, 6)
        ],
        "all_green": True,
    }
    envelope = {
        "feasibility": {"band": "GREEN", "cutover_feasibility_score": 1.0}
    }
    # Welle-6/7 path (no cross-modul).
    d_67 = _render_decision(
        gate_rc=0, dry_rc=0, boot_rc=0, bridge_rc=0,
        has_cross_modul=False, floor="GREEN",
        trigger_report=trigger, dry_run_envelope=envelope,
    )
    assert d_67["ready_for_live_smoke"] is True
    # Welle-4/5 path (cross-modul green required).
    d_45_green = _render_decision(
        gate_rc=0, dry_rc=0, boot_rc=0, bridge_rc=0,
        cross_modul_rc=0,
        has_cross_modul=True, floor="GREEN",
        trigger_report=trigger, dry_run_envelope=envelope,
    )
    assert d_45_green["ready_for_live_smoke"] is True
    # Welle-4/5 path - cross-modul red blocks ready.
    d_45_red = _render_decision(
        gate_rc=0, dry_rc=0, boot_rc=0, bridge_rc=0,
        cross_modul_rc=1,
        has_cross_modul=True, floor="GREEN",
        trigger_report=trigger, dry_run_envelope=envelope,
    )
    assert d_45_red["ready_for_live_smoke"] is False
    assert d_45_red["cross_modul_ok"] is False


def test_decision_policy_gate4_yellow_tolerated() -> None:
    """Gate-4 yellow alone tolerated (observability-baseline ENV unset).
    Posture identical to Welle-1/2."""
    trigger = {
        "gates": [
            {"id": "gate-1", "status": "green"},
            {"id": "gate-2", "status": "green"},
            {"id": "gate-3", "status": "green"},
            {"id": "gate-4", "status": "yellow"},
            {"id": "gate-5", "status": "green"},
        ]
    }
    envelope = {"feasibility": {"band": "GREEN"}}
    d = _render_decision(
        gate_rc=1, dry_rc=0, boot_rc=0, bridge_rc=0,
        cross_modul_rc=0, has_cross_modul=True,
        floor="GREEN",
        trigger_report=trigger, dry_run_envelope=envelope,
    )
    assert d["ready_for_live_smoke"] is True
    assert d["gate_signal"] == "yellow_tolerated"


def test_decision_policy_band_floor_enforced() -> None:
    """Dry-run band below the configured floor blocks ready."""
    trigger = {
        "gates": [
            {"id": f"gate-{i}", "status": "green"} for i in range(1, 6)
        ]
    }
    envelope = {"feasibility": {"band": "AMBER"}}
    d_blocked = _render_decision(
        gate_rc=0, dry_rc=0, boot_rc=0, bridge_rc=0,
        has_cross_modul=False, floor="GREEN",
        trigger_report=trigger, dry_run_envelope=envelope,
    )
    assert d_blocked["ready_for_live_smoke"] is False
    assert d_blocked["band_ok"] is False
    d_ok = _render_decision(
        gate_rc=0, dry_rc=0, boot_rc=0, bridge_rc=0,
        has_cross_modul=False, floor="AMBER",
        trigger_report=trigger, dry_run_envelope=envelope,
    )
    assert d_ok["ready_for_live_smoke"] is True


def test_decision_envelope_schema_per_welle() -> None:
    """Each workflow's decision envelope carries the welle-specific
    schema version (`wakir.phase-3c.welle-{N}-validation/1`). The
    workflow's inline-python writes this field; we grep the workflow
    YAML run-block for the literal so a future copy-paste from a
    sibling workflow cannot silently keep the wrong schema."""
    for w, meta in WELLE_TABLE.items():
        steps = _steps(_job(_load_yaml(meta["workflow"]), meta["job_id"]))
        decision_step = next(s for s in steps if s.get("id") == "decision")
        run = decision_step.get("run") or ""
        assert meta["decision_schema"] in run, (
            f"welle-{w} decision schema drift; "
            f"expected {meta['decision_schema']!r} in inline-python"
        )


# ---------------------------------------------------------------------------
# Test 9 - artifact upload bundles the canonical paths per welle.
# ---------------------------------------------------------------------------


def test_artifact_upload_bundles_canonical_paths_per_welle() -> None:
    """The trailing upload-artifact step must collect the canonical
    output paths for each welle. Welle-4/5 additionally bundle the
    cross-modul-stress.json file. Each artifact bundle carries a
    welle-specific name so the four readiness reports do not collide
    on the GitHub Actions artifact namespace when they run in the
    same week."""
    canonical = {
        "cutover-acceptance-decision.json",
        "trigger-gate-report.json",
        "dry-run-envelope.json",
        "persona-boot.log",
        "persona-boot-junit.xml",
        "bridge-audit.log",
        "bridge-audit-junit.xml",
    }
    for w, meta in WELLE_TABLE.items():
        steps = _steps(_job(_load_yaml(meta["workflow"]), meta["job_id"]))
        upload = None
        for s in steps:
            if (s.get("uses") or "").startswith("actions/upload-artifact@"):
                upload = s
                break
        assert upload is not None, f"welle-{w} missing upload-artifact step"
        with_block = upload.get("with") or {}
        assert with_block.get("name") == meta["artifact_name"], (
            f"welle-{w} artifact name drift: {with_block.get('name')!r}"
        )
        paths_block = with_block.get("path") or ""
        for fname in canonical:
            assert fname in paths_block, (
                f"welle-{w} upload bundle missing {fname}"
            )
        if meta["has_cross_modul"]:
            assert "cross-modul-stress.json" in paths_block, (
                f"welle-{w} upload bundle missing cross-modul-stress.json"
            )
        else:
            assert "cross-modul-stress.json" not in paths_block, (
                f"welle-{w} upload bundle unexpectedly includes "
                "cross-modul-stress.json"
            )
        assert with_block.get("retention-days") == 30
        assert upload.get("if") == "always()"


# ---------------------------------------------------------------------------
# Test 10 - dry-run produces feasibility envelope for each welle's
# component. Compose against the in-tree dry-run module with a stub
# resolver per welle (mirrors the workflow's Step-2 invocation).
# ---------------------------------------------------------------------------


def test_dry_run_success_criteria_per_welle(dry_run_module) -> None:
    """The dry-run with stub resolver per welle must produce a GREEN
    feasibility envelope (all-rust purity, zero fallbacks). This is
    the substance contract the workflow's Step-2 acceptance-decision
    logic depends on."""
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Decision:
        chosen_backend: str
        fallback_reason: Any
        resolution_latency_us: int
        domain: str

    for w, meta in WELLE_TABLE.items():
        component_short = meta["component_short"]
        rust_value = meta["rust_value"]
        env_var = meta["env_var"]
        # Stub resolver module exposing
        # ``resolve_<component_short>_backend(env, log_sink, binary_probe)``.
        resolver_fn_name = f"resolve_{component_short}_backend"

        class _StubResolverModule:
            pass

        def _make_resolver(fn_name, env_var_, rust_value_, domain):
            def _resolver(*, env, log_sink, binary_probe):
                requested = env.get(env_var_, "python")
                return (
                    requested,
                    _Decision(
                        chosen_backend=requested,
                        fallback_reason=None,
                        resolution_latency_us=42,
                        domain=domain,
                    ),
                )
            return _resolver

        # Map welle short-form to the BackendDecision.domain value the
        # dry-run script expects (mirrors COMPONENT_TO_DOMAIN). For all
        # four wellen the short-form equals the domain value.
        domain = component_short
        setattr(
            _StubResolverModule,
            resolver_fn_name,
            staticmethod(_make_resolver(
                resolver_fn_name, env_var, rust_value, domain
            )),
        )
        envelope = dry_run_module.run_dry_run(
            component=component_short,
            boots=12,
            resolver_module=_StubResolverModule(),
            now_ts=0,
        )
        assert envelope["schema"] == "wakir.phase-3c.dry-run/1"
        assert envelope["component"] == component_short, (
            f"welle-{w} envelope component drift: "
            f"{envelope['component']!r}"
        )
        assert envelope["env_var"] == env_var
        assert envelope["boots"] == 12
        feas = envelope["feasibility"]
        assert feas["band"] == "GREEN", (
            f"welle-{w} dry-run band drift: {feas['band']!r}; "
            f"envelope={envelope}"
        )
        assert feas["cutover_feasibility_score"] >= 0.95
        # 12 decisions, all chose the Rust value, zero fallbacks.
        assert len(envelope["decisions"]) == 12
        assert envelope["chosen_backend_counts"] == {rust_value: 12}


# ---------------------------------------------------------------------------
# Test 11 - cross-modul-stress envelope shape (Welle-4/5 only).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def aggregator_module():
    path = REPO_ROOT / "scripts" / "doppelbetrieb-score-aggregator.py"
    return _load_module("doppelbetrieb_score_aggregator_welle_4_7", path)


def test_cross_modul_stress_envelope_shape(aggregator_module) -> None:
    """The aggregator's `cross-modul-stress` mode produces exactly
    three axes: state_backing x lifecycle_state_machine,
    subscribe_loop x recovery_workflow, and v907_verify x
    svid_workload_identity. This is the envelope the Welle-4/5
    workflows consume in their Step 5."""
    axes = aggregator_module.run_cross_modul_stress()
    assert len(axes) == 3, f"axis count drift: {len(axes)}"
    labels = {a.label for a in axes}
    assert labels == {
        "cross-modul-state-backing-lifecycle-state-machine",
        "cross-modul-subscribe-loop-recovery-workflow",
        "cross-modul-v907-verify-svid-workload-identity",
    }, f"axis label drift: {labels}"
    # Each axis yields a JSON-serialisable result.
    envelope = aggregator_module.build_envelope(axes)
    json.dumps(envelope)
    # The envelope's `axes` block must be present so the workflow can
    # introspect it for the decision summary. The aggregator schema
    # `wakir.doppelbetrieb.aggregator/2` stores axes as a dict keyed
    # by axis label rather than a list; assert dict shape so the
    # workflow's Step 5 envelope consumer (Welle-4/5) reads correctly.
    axes_block = envelope.get("axes")
    assert isinstance(axes_block, dict), (
        f"axes block must be a dict; got {type(axes_block).__name__}"
    )
    assert {
        "cross-modul-state-backing-lifecycle-state-machine",
        "cross-modul-subscribe-loop-recovery-workflow",
        "cross-modul-v907-verify-svid-workload-identity",
    }.issubset(set(axes_block.keys())), (
        f"axes block missing cross-modul keys; got {sorted(axes_block.keys())}"
    )


# ---------------------------------------------------------------------------
# Test 12 - the four runbooks exist and reference the correct ADRs.
# ---------------------------------------------------------------------------


def test_runbooks_exist_per_welle() -> None:
    """Each welle ships a dedicated runbook under docs/operations/.
    Bundle-Auftrag (Tag-32) requires 4 separate files."""
    for w in (4, 5, 6, 7):
        runbook = (
            REPO_ROOT
            / "docs"
            / "operations"
            / f"phase-3c-welle-{w}-runbook.md"
        )
        assert runbook.is_file(), f"missing runbook: {runbook}"
        text = runbook.read_text(encoding="utf-8")
        # Each runbook anchors both ADR-0065 and ADR-0066.
        assert "0065" in text, f"welle-{w} runbook missing ADR-0065 anchor"
        assert "0066" in text, f"welle-{w} runbook missing ADR-0066 anchor"
