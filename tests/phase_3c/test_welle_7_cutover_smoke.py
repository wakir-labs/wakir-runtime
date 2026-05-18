# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.py.

Hermetic, stdlib-only. The smoke module is loaded via importlib
from its hyphenated path under ``scripts/phase-3c/``.

Scope (17 tests; Auftrag-Tag-39 minimum is 12 — exceeded so the
Welle-7-specific edges (A6 byte-drift, A6 phase-ordering violation,
A7 subscribe_loop-leak, shim path for trailing component,
state_backing-pin, fsm-pin) get explicit per-axis coverage)
--------------------------------------------------------------------

1.  test_module_loads_and_exports_public_surface
2.  test_engine_boot_components_includes_recovery_and_partners
3.  test_build_phase_env_pre_pins_state_backing_and_fsm_to_rust
4.  test_build_phase_env_post_flips_focus_to_rust
5.  test_build_phase_env_rollback_removes_focus_env_var
6.  test_spec_valid_recovery_phases_matches_spec_four_phases
7.  test_run_cutover_smoke_green_path_exits_zero
8.  test_run_cutover_smoke_caution_on_latency_blowup
9.  test_run_cutover_smoke_rollback_on_fallback
10. test_run_cutover_smoke_rollback_when_post_stays_python
11. test_run_cutover_smoke_rollback_when_rollback_phase_stays_rust
12. test_main_cli_writes_envelope_and_returns_exit_code
13. test_a6_recovery_drill_green_with_stub_canonical
14. test_a6_recovery_drill_caution_on_byte_drift
15. test_a6_recovery_drill_caution_on_phase_ordering_violation
16. test_a7_cross_modul_drift_to_welle_6_subscribe_loop_blocks_on_leak
17. test_state_backing_and_fsm_post_cutover_state_report_rust_default
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import pytest


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    return here.parent.parent.parent


def _load_smoke_module() -> Any:
    smoke_path = (
        _repo_root()
        / "scripts"
        / "phase-3c"
        / "welle-7-recovery-workflow-cutover-smoke.py"
    )
    if not smoke_path.is_file():
        pytest.fail(f"smoke script not found at {smoke_path}")
    spec = importlib.util.spec_from_file_location(
        "welle_7_recovery_workflow_cutover_smoke", str(smoke_path)
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build spec for {smoke_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["welle_7_recovery_workflow_cutover_smoke"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


SMOKE = _load_smoke_module()


@dataclass(frozen=True)
class StubBackendDecision:
    domain: str
    requested_backend: str
    chosen_backend: str
    resolution_latency_us: int
    fallback_reason: Optional[str] = None
    bin_path: Optional[str] = None


@dataclass
class StubResolverConfig:
    force_rust_on_rollback: bool = False
    fallback_on_rust: bool = False
    rust_focus_latency_us: int = 50
    python_focus_latency_us: int = 100
    pin_focus_to_python: bool = False
    # Welle-7 specific: simulate subscribe_loop cross-modul-drift leak.
    subscribe_loop_leaks_to_rust_on_recovery_cutover: bool = False


def build_stub_resolver_module(
    config: Optional[StubResolverConfig] = None,
) -> types.ModuleType:
    cfg = config or StubResolverConfig()
    module = types.ModuleType("wirelang.persona_engine.rust_backend_switch")

    component_to_env = SMOKE.COMPONENT_TO_ENV
    focus = SMOKE.FOCUS_COMPONENT
    focus_env_var = SMOKE.FOCUS_ENV_VAR

    def _make_resolver(component: str) -> Callable[..., Tuple[Any, StubBackendDecision]]:
        def _resolver(
            env: Optional[Mapping[str, str]] = None,
            *,
            log_sink: Any = None,
            binary_probe: Any = None,
        ) -> Tuple[Any, StubBackendDecision]:
            env_map = env or {}
            env_var = component_to_env[component]
            raw = env_map.get(env_var, "")
            requested = raw if raw else "python"
            chosen = requested
            fallback_reason: Optional[str] = None
            latency_us = 30

            if component == focus:
                if requested == SMOKE.ENV_VALUE_RUST:
                    if cfg.pin_focus_to_python:
                        chosen = "python"
                        fallback_reason = "test_pin_focus_to_python"
                    elif cfg.fallback_on_rust:
                        chosen = "python"
                        fallback_reason = "binary_missing"
                    else:
                        chosen = SMOKE.ENV_VALUE_RUST
                    latency_us = cfg.rust_focus_latency_us
                else:
                    if cfg.force_rust_on_rollback and env_var not in env_map:
                        chosen = SMOKE.ENV_VALUE_RUST
                        fallback_reason = "test_force_rust_on_rollback"
                    else:
                        chosen = "python"
                    latency_us = cfg.python_focus_latency_us
            elif component == SMOKE.WELLE_6_PARTNER_COMPONENT:
                if cfg.subscribe_loop_leaks_to_rust_on_recovery_cutover:
                    rec_value = env_map.get(focus_env_var, "")
                    if rec_value == SMOKE.ENV_VALUE_RUST:
                        chosen = "rust"
                        requested = raw if raw else "python"
                        fallback_reason = "test_subscribe_loop_cross_modul_leak"
                    else:
                        chosen = "rust" if requested == "rust" else "python"
                else:
                    chosen = "rust" if requested == "rust" else "python"
                latency_us = 25
            elif component == SMOKE.STATE_BACKING_POST_KW26_COMPONENT:
                # state_backing has a three-valued enum.
                # In the post-KW-26 production state the env-var is
                # "rust_inmemory"; the stub honours that.
                if requested in ("rust_inmemory", "rust_natskv"):
                    chosen = requested
                else:
                    chosen = "python"
                latency_us = 25
            else:
                chosen = "rust" if requested == "rust" else "python"
                latency_us = 25

            decision = StubBackendDecision(
                domain=component,
                requested_backend=requested,
                chosen_backend=chosen,
                resolution_latency_us=latency_us,
                fallback_reason=fallback_reason,
                bin_path=None,
            )
            return chosen, decision

        return _resolver

    for component in SMOKE.ENGINE_BOOT_COMPONENTS:
        setattr(module, f"resolve_{component}_backend", _make_resolver(component))

    return module


def build_stub_recovery_canonical_module(
    *,
    drift_after_first_call: bool = False,
) -> types.ModuleType:
    """Build a fake recovery_workflow_canonical module.

    Exposes a minimal surface that the smoke's
    ``_build_and_hash_recovery_outcome`` can consume via the
    fallback path (smoke-internal JSON-canonical hash). The stub
    deliberately does NOT expose the rfc8785-dependent
    ``recovery_outcome_jcs_bytes`` so the smoke's fallback path is
    exercised end-to-end.

    When ``drift_after_first_call`` is True the module surfaces a
    ``recovery_outcome_canonical_dict`` that mutates output after
    the first call, simulating substrate-drift.
    """
    mod = types.ModuleType("wirelang.persona_engine.recovery_workflow_canonical")
    state = {"call_count": 0}

    # We omit recovery_outcome_canonical_dict and friends so the
    # smoke uses its smoke-internal fallback. To simulate drift,
    # we provide a custom builder that mutates output.
    if drift_after_first_call:
        def recovery_outcome_canonical_dict(
            *,
            trigger: Any,
            phases: List[Any],
            final_state: str,
            success: bool,
        ) -> Dict[str, Any]:
            state["call_count"] += 1
            phases_out = []
            for p in phases:
                phases_out.append({
                    "audit_annotation": getattr(p, "audit_annotation", ""),
                    "elapsed_sec": 0,
                    "phase": getattr(p, "phase", ""),
                    "soft_cap_exceeded": False,
                    "terminal_status": getattr(p, "terminal_status", ""),
                })
            return {
                "final_state": final_state,
                "phases": phases_out,
                "schema": "wakir.persona-engine.recovery-outcome/1",
                "success": success,
                "total_elapsed_sec": 0,
                "trigger": getattr(trigger, "value", str(trigger)),
            }

        def recovery_outcome_jcs_bytes(canonical_dict: Dict[str, Any]) -> bytes:
            payload = json.dumps(
                canonical_dict,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            if state["call_count"] > 1:
                payload += b"DRIFT"
            return payload

        def recovery_outcome_sha256_hex(canonical_dict: Dict[str, Any]) -> str:
            return hashlib.sha256(recovery_outcome_jcs_bytes(canonical_dict)).hexdigest()

        mod.recovery_outcome_canonical_dict = (  # type: ignore[attr-defined]
            recovery_outcome_canonical_dict
        )
        mod.recovery_outcome_jcs_bytes = recovery_outcome_jcs_bytes  # type: ignore[attr-defined]
        mod.recovery_outcome_sha256_hex = recovery_outcome_sha256_hex  # type: ignore[attr-defined]

    return mod


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface() -> None:
    expected_exports = {
        "COMPONENT_TO_ENV",
        "DEFAULT_BOOTS_PER_PHASE",
        "DEFAULT_EXPECTED_COMPONENTS",
        "DEFAULT_LATENCY_TOLERANCE_PCT",
        "DETERMINISTIC_RECOVERY_OUTCOME",
        "ENGINE_BOOT_COMPONENTS",
        "ENVELOPE_SCHEMA",
        "ENV_VALUE_PYTHON",
        "ENV_VALUE_RUST",
        "EXIT_CAUTION",
        "EXIT_GREEN",
        "EXIT_ROLLBACK",
        "FOCUS_COMPONENT",
        "FOCUS_COMPONENT_LONG",
        "FOCUS_ENV_VAR",
        "FSM_POST_KW26_BACKEND",
        "FSM_POST_KW26_COMPONENT",
        "FSM_POST_KW26_ENV_VAR",
        "PHASE_POST",
        "PHASE_PRE",
        "PHASE_ROLLBACK",
        "RESOLVER_PROVENANCE_SHIM",
        "RESOLVER_PROVENANCE_UPSTREAM",
        "SHIM_COMPONENT_PRIMITIVES",
        "SPEC_VALID_RECOVERY_PHASES",
        "SPEC_VALID_RECOVERY_TRIGGERS",
        "STATE_BACKING_POST_KW26_BACKEND",
        "STATE_BACKING_POST_KW26_COMPONENT",
        "STATE_BACKING_POST_KW26_ENV_VAR",
        "WELLE_6_PARTNER_COMPONENT",
        "WELLE_6_PARTNER_ENV_VAR",
        "boot_engine_once",
        "build_argparser",
        "build_envelope",
        "build_phase_env",
        "capture_recovery_drill_baseline_default",
        "derive_exit_code",
        "evaluate_fsm_post_cutover_state",
        "evaluate_post_cutover_asserts",
        "evaluate_recovery_drill_parity",
        "evaluate_state_backing_post_cutover_state",
        "latency_p95",
        "main",
        "parity_hash",
        "run_cutover_smoke",
        "run_phase",
    }
    actual_exports = set(SMOKE.__all__)
    assert expected_exports == actual_exports, (
        f"missing={expected_exports - actual_exports!r} "
        f"extra={actual_exports - expected_exports!r}"
    )
    assert SMOKE.FOCUS_COMPONENT == "recovery"
    assert SMOKE.FOCUS_COMPONENT_LONG == "recovery_workflow"
    assert SMOKE.FOCUS_ENV_VAR == "WAKIR_RECOVERY_BACKEND"
    assert SMOKE.EXIT_GREEN == 0
    assert SMOKE.EXIT_CAUTION == 1
    assert SMOKE.EXIT_ROLLBACK == 2
    assert SMOKE.ENVELOPE_SCHEMA == "wakir.phase-3c.welle-7-cutover-smoke/1"
    assert SMOKE.DEFAULT_EXPECTED_COMPONENTS == 11
    assert SMOKE.WELLE_6_PARTNER_COMPONENT == "subscribe_loop"
    assert SMOKE.WELLE_6_PARTNER_ENV_VAR == "WAKIR_SUBSCRIBE_LOOP_BACKEND"
    assert SMOKE.STATE_BACKING_POST_KW26_COMPONENT == "state_backing"
    assert SMOKE.STATE_BACKING_POST_KW26_ENV_VAR == "WAKIR_STATE_BACKING_BACKEND"
    assert SMOKE.STATE_BACKING_POST_KW26_BACKEND == "rust_inmemory"
    assert SMOKE.FSM_POST_KW26_BACKEND == "rust"


def test_engine_boot_components_includes_recovery_and_partners() -> None:
    components = SMOKE.ENGINE_BOOT_COMPONENTS
    assert "recovery" in components
    assert "subscribe_loop" in components, (
        "Welle-6 partner subscribe_loop must be in engine inventory"
    )
    assert "state_backing" in components
    assert "fsm" in components
    assert len(components) == 11


def test_build_phase_env_pre_pins_state_backing_and_fsm_to_rust() -> None:
    """Pre-Cutover phase: every env-var is 'python' EXCEPT
    state_backing AND fsm which are pinned to 'rust' (post-KW-26
    production state)."""
    env = SMOKE.build_phase_env(SMOKE.PHASE_PRE)
    assert env[SMOKE.FOCUS_ENV_VAR] == "python"
    assert env[SMOKE.WELLE_6_PARTNER_ENV_VAR] == "python"
    # state_backing pinned to rust_inmemory; fsm pinned to rust per
    # State-Backing-Awareness and FSM-Awareness.
    assert env[SMOKE.STATE_BACKING_POST_KW26_ENV_VAR] == "rust_inmemory"
    assert env[SMOKE.FSM_POST_KW26_ENV_VAR] == "rust"
    for component, env_var in SMOKE.COMPONENT_TO_ENV.items():
        if component == SMOKE.STATE_BACKING_POST_KW26_COMPONENT:
            assert env[env_var] == "rust_inmemory", env_var
        elif component == SMOKE.FSM_POST_KW26_COMPONENT:
            assert env[env_var] == "rust", env_var
        else:
            assert env[env_var] == "python", env_var


def test_build_phase_env_post_flips_focus_to_rust() -> None:
    env = SMOKE.build_phase_env(SMOKE.PHASE_POST)
    assert env[SMOKE.FOCUS_ENV_VAR] == "rust"
    assert env[SMOKE.WELLE_6_PARTNER_ENV_VAR] == "python"
    assert env[SMOKE.STATE_BACKING_POST_KW26_ENV_VAR] == "rust_inmemory"
    assert env[SMOKE.FSM_POST_KW26_ENV_VAR] == "rust"
    for component, env_var in SMOKE.COMPONENT_TO_ENV.items():
        if component == SMOKE.FOCUS_COMPONENT:
            assert env[env_var] == "rust"
        elif component == SMOKE.STATE_BACKING_POST_KW26_COMPONENT:
            assert env[env_var] == "rust_inmemory"
        elif component == SMOKE.FSM_POST_KW26_COMPONENT:
            assert env[env_var] == "rust"
        else:
            assert env[env_var] == "python", env_var

    with pytest.raises(ValueError, match="unknown phase"):
        SMOKE.build_phase_env("not_a_phase")


def test_build_phase_env_rollback_removes_focus_env_var() -> None:
    env = SMOKE.build_phase_env(SMOKE.PHASE_ROLLBACK)
    assert SMOKE.FOCUS_ENV_VAR not in env
    assert env[SMOKE.WELLE_6_PARTNER_ENV_VAR] == "python"
    assert env[SMOKE.STATE_BACKING_POST_KW26_ENV_VAR] == "rust_inmemory"
    assert env[SMOKE.FSM_POST_KW26_ENV_VAR] == "rust"


def test_spec_valid_recovery_phases_matches_spec_four_phases() -> None:
    """SPEC_VALID_RECOVERY_PHASES must match spec §3.7.4."""
    assert SMOKE.SPEC_VALID_RECOVERY_PHASES == ("R1", "R2", "R3", "R4")
    assert len(SMOKE.SPEC_VALID_RECOVERY_PHASES) == 4
    # Deterministic fixture walks R1..R4 in spec order.
    fixture_phases = [
        p["phase"] for p in SMOKE.DETERMINISTIC_RECOVERY_OUTCOME["phases"]
    ]
    assert tuple(fixture_phases) == SMOKE.SPEC_VALID_RECOVERY_PHASES
    # Spec triggers are the three-entry closed enum.
    assert SMOKE.SPEC_VALID_RECOVERY_TRIGGERS == (
        "CrashDetected",
        "DespawnMidOperation",
        "StateCorruption",
    )


def test_run_cutover_smoke_green_path_exits_zero() -> None:
    resolver = build_stub_resolver_module()
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        now_ts=1_700_000_000,
        skip_recovery_drill_parity=True,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    assert envelope["band"] == "GREEN"
    assert envelope["schema"] == "wakir.phase-3c.welle-7-cutover-smoke/1"
    assert envelope["welle"] == 7
    assert envelope["focus_component"] == "recovery"
    assert envelope["focus_component_long"] == "recovery_workflow"
    assert envelope["timestamp_utc"] == 1_700_000_000
    for name, record in envelope["asserts"].items():
        assert record["passed"], (name, record)
    assert envelope["asserts"]["A6_recovery_r1_r4_drill"]["skipped"] is True
    a7 = envelope["asserts"]["A7_cross_modul_drift_welle_6_subscribe_loop"]
    assert a7["passed"] is True
    assert a7["skipped"] is False
    assert a7["subscribe_loop_chosen_backends"] == ["python"]
    # State-Backing-Awareness + FSM-Awareness fields.
    sb_state = envelope["state_backing_post_cutover_state"]
    assert sb_state["state_backing_in_expected_post_kw26_state"] is True
    assert sb_state["state_backing_chosen_backends"] == ["rust_inmemory"]
    fsm_state = envelope["fsm_post_cutover_state"]
    assert fsm_state["fsm_in_expected_post_kw26_state"] is True


def test_run_cutover_smoke_caution_on_latency_blowup() -> None:
    tol = SMOKE.DEFAULT_LATENCY_TOLERANCE_PCT
    resolver = build_stub_resolver_module(
        StubResolverConfig(
            python_focus_latency_us=100,
            rust_focus_latency_us=100_000,
        )
    )
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        latency_tolerance_pct=tol,
        skip_recovery_drill_parity=True,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_CAUTION, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    assert envelope["band"] == "CAUTION"
    assert envelope["asserts"]["A1_backend_flip"]["passed"]
    assert envelope["asserts"]["A2_cross_lang_parity_hash"]["passed"]
    assert not envelope["asserts"]["A3_latency_within_tolerance"]["passed"]
    assert envelope["asserts"]["A5_fallback_clean"]["passed"]
    assert envelope["asserts"]["R1_rollback_to_python"]["passed"]
    assert envelope["asserts"]["A7_cross_modul_drift_welle_6_subscribe_loop"]["passed"]


def test_run_cutover_smoke_rollback_on_fallback() -> None:
    resolver = build_stub_resolver_module(
        StubResolverConfig(fallback_on_rust=True)
    )
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        skip_recovery_drill_parity=True,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_ROLLBACK, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    assert envelope["band"] == "ROLLBACK_RECOMMENDED"
    assert not envelope["asserts"]["A1_backend_flip"]["passed"]
    assert not envelope["asserts"]["A5_fallback_clean"]["passed"]


def test_run_cutover_smoke_rollback_when_post_stays_python() -> None:
    resolver = build_stub_resolver_module(
        StubResolverConfig(pin_focus_to_python=True)
    )
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        skip_recovery_drill_parity=True,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_ROLLBACK
    assert envelope["band"] == "ROLLBACK_RECOMMENDED"
    assert not envelope["asserts"]["A1_backend_flip"]["passed"]


def test_run_cutover_smoke_rollback_when_rollback_phase_stays_rust() -> None:
    resolver = build_stub_resolver_module(
        StubResolverConfig(force_rust_on_rollback=True)
    )
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        skip_recovery_drill_parity=True,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_ROLLBACK
    assert not envelope["asserts"]["R1_rollback_to_python"]["passed"]


def test_main_cli_writes_envelope_and_returns_exit_code(tmp_path: Path) -> None:
    out_file = tmp_path / "envelope.json"
    resolver = build_stub_resolver_module()
    stdout = io.StringIO()
    stderr = io.StringIO()
    rc = SMOKE.main(
        argv=[
            "--boots-per-phase",
            "3",
            "--expected-components",
            "11",
            "--output",
            str(out_file),
            "--now",
            "1700000001",
            "--skip-recovery-drill-parity",
        ],
        stdout=stdout,
        stderr=stderr,
        resolver_module=resolver,
    )
    assert rc == SMOKE.EXIT_GREEN, stderr.getvalue()
    assert out_file.is_file()
    rendered = out_file.read_text(encoding="utf-8")
    envelope = json.loads(rendered)
    assert envelope["schema"] == "wakir.phase-3c.welle-7-cutover-smoke/1"
    assert envelope["boots_per_phase"] == 3
    assert envelope["timestamp_utc"] == 1700000001
    assert envelope["exit_code"] == SMOKE.EXIT_GREEN
    assert envelope["welle"] == 7
    assert envelope["focus_component"] == "recovery"
    assert envelope["focus_component_long"] == "recovery_workflow"
    assert stdout.getvalue() == ""


def test_a6_recovery_drill_green_with_stub_canonical() -> None:
    """A6 recovery-drill green when canonical module is byte-stable.

    The stub canonical module provides NO public API surface, so
    the smoke uses its internal JSON-canonical fallback path. The
    hash is deterministic across the pre/post window because the
    fixture is byte-stable.
    """
    resolver = build_stub_resolver_module()
    canonical = build_stub_recovery_canonical_module()  # empty stub
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        canonical_module=canonical,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a6 = envelope["asserts"]["A6_recovery_r1_r4_drill"]
    assert a6["passed"] is True
    assert a6["skipped"] is False
    assert a6["severity"] == "caution"
    assert a6["match"] is True
    assert a6["baseline_recovery_outcome_sha256"] is not None
    assert a6["recomputed_recovery_outcome_sha256"] == a6["baseline_recovery_outcome_sha256"]
    assert a6["phase_ordering_violations"] == []
    integrity = envelope["recovery_drill_integrity"]
    assert integrity["baseline_captured_at_phase"] == SMOKE.PHASE_PRE
    assert integrity["baseline_skipped"] is False
    assert integrity["spec_valid_recovery_phases"] == ["R1", "R2", "R3", "R4"]


def test_a6_recovery_drill_caution_on_byte_drift() -> None:
    """A6 byte-drift between baseline + recompute → CAUTION exit.

    The drift-enabled stub provides the canonical-dict + jcs-bytes
    surface and salts the JCS bytes on the second call (post-cutover
    recompute), producing a hash mismatch.
    """
    resolver = build_stub_resolver_module()
    canonical = build_stub_recovery_canonical_module(drift_after_first_call=True)
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        canonical_module=canonical,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_CAUTION, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a6 = envelope["asserts"]["A6_recovery_r1_r4_drill"]
    assert a6["passed"] is False
    assert a6["skipped"] is False
    assert a6["match"] is False
    assert a6["baseline_recovery_outcome_sha256"] != a6["recomputed_recovery_outcome_sha256"]
    assert envelope["asserts"]["A1_backend_flip"]["passed"]
    assert envelope["asserts"]["A2_cross_lang_parity_hash"]["passed"]
    assert envelope["asserts"]["A5_fallback_clean"]["passed"]
    assert envelope["asserts"]["R1_rollback_to_python"]["passed"]
    assert envelope["asserts"]["A7_cross_modul_drift_welle_6_subscribe_loop"]["passed"]


def test_a6_recovery_drill_caution_on_phase_ordering_violation() -> None:
    """A6 fires on a phase-ordering violation (out-of-spec phase or order)."""
    canonical = build_stub_recovery_canonical_module()
    bad_outcome: Dict[str, Any] = {
        "trigger": "CrashDetected",
        "final_state": "running",
        "success": True,
        "phases": [
            # PHANTOM: R2 before R1 violates spec order.
            {
                "phase": "R2",
                "terminal_status": "reloaded",
                "audit_annotation": "out-of-order",
            },
            {
                "phase": "R1",
                "terminal_status": "detected",
                "audit_annotation": "out-of-order",
            },
            {
                "phase": "R3",
                "terminal_status": "re_registered",
                "audit_annotation": "ok",
            },
            {
                "phase": "R4",
                "terminal_status": "resumed",
                "audit_annotation": "ok",
            },
        ],
    }
    baseline = SMOKE.capture_recovery_drill_baseline_default(
        outcome=bad_outcome,
        canonical_module=canonical,
    )
    assert baseline is not None
    # The baseline records the violations but does NOT fail itself
    # (the baseline just captures + reports; the parity-eval acts on them).
    assert len(baseline["phase_ordering_violations"]) > 0
    # Now evaluate parity with the same bad-ordering fixture.
    parity = SMOKE.evaluate_recovery_drill_parity(
        baseline,
        outcome=bad_outcome,
        canonical_module=canonical,
    )
    assert parity["passed"] is False
    # match=True (hash equal) but ordering violations present.
    assert parity["match"] is True
    assert len(parity["phase_ordering_violations"]) > 0


def test_a7_cross_modul_drift_to_welle_6_subscribe_loop_blocks_on_leak() -> None:
    """A7 fires + ROLLBACK when subscribe_loop leaks to rust in PHASE_POST."""
    cfg = StubResolverConfig(
        subscribe_loop_leaks_to_rust_on_recovery_cutover=True
    )
    resolver = build_stub_resolver_module(cfg)
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        skip_recovery_drill_parity=True,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_ROLLBACK, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a7 = envelope["asserts"]["A7_cross_modul_drift_welle_6_subscribe_loop"]
    assert a7["passed"] is False
    assert a7["severity"] == "blocker"
    assert "rust" in a7["subscribe_loop_chosen_backends"]
    assert a7["expected_subscribe_loop_backend"] == "python"
    assert "leaked into subscribe_loop path" in a7["detail"]
    mitigation = envelope["cross_modul_drift_mitigation"]
    assert mitigation["welle_6_partner_component"] == "subscribe_loop"
    assert mitigation["welle_6_partner_env_var"] == "WAKIR_SUBSCRIBE_LOOP_BACKEND"
    assert "rust" in mitigation["subscribe_loop_chosen_backends_in_post_phase"]
    assert envelope["asserts"]["A1_backend_flip"]["passed"]
    assert envelope["asserts"]["A5_fallback_clean"]["passed"]
    assert envelope["asserts"]["R1_rollback_to_python"]["passed"]


def test_state_backing_and_fsm_post_cutover_state_report_rust_default() -> None:
    """State-Backing-Awareness + FSM-Awareness pre-checks confirm
    both substrates are in expected post-KW-26 state."""
    resolver = build_stub_resolver_module()
    envelope, _exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        skip_recovery_drill_parity=True,
        expected_components=11,
    )
    sb_state = envelope["state_backing_post_cutover_state"]
    assert sb_state["state_backing_in_expected_post_kw26_state"] is True
    assert sb_state["expected_state_backing_backend"] == "rust_inmemory"
    assert sb_state["state_backing_chosen_backends"] == ["rust_inmemory"]
    fsm_state = envelope["fsm_post_cutover_state"]
    assert fsm_state["fsm_in_expected_post_kw26_state"] is True
    assert fsm_state["expected_fsm_backend"] == "rust"
    assert fsm_state["fsm_chosen_backends"] == ["rust"]
