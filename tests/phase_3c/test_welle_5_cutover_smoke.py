# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py.

Hermetic, stdlib-only. The smoke module is loaded via importlib from
its hyphenated path under ``scripts/phase-3c/``. The resolver dep is
exercised through a stub module so the tests never import the real
wirelang package, and every test injects ``resolver_module`` +
``binary_probe`` explicitly so no filesystem access happens.

Scope (16 tests; Auftrag-Tag-38 minimum is 12 — exceeded so the
Welle-5-specific edges (A6 byte-drift, A6 phantom transitions, A7
state_backing-leak, shim path for trailing component, custom
expected-components, hermetic-env-construction) get explicit per-
axis coverage)
--------------------------------------------------------------------

1.  test_module_loads_and_exports_public_surface
2.  test_engine_boot_components_includes_fsm_and_partners
3.  test_build_phase_env_pre_sets_all_python
4.  test_build_phase_env_post_flips_focus_to_rust
5.  test_build_phase_env_rollback_removes_focus_env_var
6.  test_spec_valid_transitions_matches_spec_nine_edges
7.  test_run_cutover_smoke_green_path_exits_zero
8.  test_run_cutover_smoke_caution_on_latency_blowup
9.  test_run_cutover_smoke_rollback_on_fallback
10. test_run_cutover_smoke_rollback_when_post_stays_python
11. test_run_cutover_smoke_rollback_when_rollback_phase_stays_rust
12. test_main_cli_writes_envelope_and_returns_exit_code
13. test_a6_fsm_transition_integrity_green_with_stub_canonical
14. test_a6_fsm_transition_integrity_caution_on_drift
15. test_a6_fsm_transition_integrity_caution_on_phantom_transition
16. test_a7_cross_modul_drift_to_welle_4_state_backing_blocks_on_leak
17. test_resolver_shim_used_when_bridge_audit_diff_engine_upstream_missing
18. test_run_cutover_smoke_pre_pr241_baseline_expected_components_10

The first 12 mirror the Welle-4 pattern verbatim (parametrised for
fsm's two-valued enum vs. state_backing's three-valued enum). Tests
13-15 exercise the A6 FSM-Transition-Integrity assert in three
sub-axes: clean, drift, phantom. Test 16 is the Cross-Modul-Drift-
to-Welle-4 regression-trap (symmetric to Welle-4's A7 test).
Test 17 exercises the shim path for the trailing 11th component.
Test 18 covers the pre-PR-#241 inventory mode.
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


# ---------------------------------------------------------------------------
# Smoke-module loader — handles the hyphenated path.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Locate the wakir-runtime repo root from this test file."""
    here = Path(__file__).resolve()
    return here.parent.parent.parent


def _load_smoke_module() -> Any:
    """Load the cutover-smoke module from its hyphenated path."""
    smoke_path = (
        _repo_root()
        / "scripts"
        / "phase-3c"
        / "welle-5-lifecycle-state-machine-cutover-smoke.py"
    )
    if not smoke_path.is_file():
        pytest.fail(f"smoke script not found at {smoke_path}")
    spec = importlib.util.spec_from_file_location(
        "welle_5_lifecycle_state_machine_cutover_smoke", str(smoke_path)
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build spec for {smoke_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["welle_5_lifecycle_state_machine_cutover_smoke"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


SMOKE = _load_smoke_module()


# ---------------------------------------------------------------------------
# Stub BackendDecision + stub resolver module.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StubBackendDecision:
    """Mirrors wirelang.persona_engine.rust_backend_switch.BackendDecision."""

    domain: str
    requested_backend: str
    chosen_backend: str
    resolution_latency_us: int
    fallback_reason: Optional[str] = None
    bin_path: Optional[str] = None


@dataclass
class StubResolverConfig:
    """Per-component knobs the tests use to script resolver behaviour."""

    force_rust_on_rollback: bool = False
    fallback_on_rust: bool = False
    rust_focus_latency_us: int = 50
    python_focus_latency_us: int = 100
    drop_focus_on_rust: bool = False
    pin_focus_to_python: bool = False
    # Welle-5 specific: simulate state_backing cross-modul-drift leak
    # (symmetric to Welle-4's fsm_leaks_to_rust_on_state_backing_cutover).
    state_backing_leaks_to_rust_on_fsm_cutover: bool = False


def build_stub_resolver_module(
    config: Optional[StubResolverConfig] = None,
) -> types.ModuleType:
    """Build a fake rust_backend_switch module wired by StubResolverConfig.

    The smoke calls ``resolve_<component>_backend(env=..., log_sink=...,
    binary_probe=...)`` for each in-place component, expecting a
    ``(backend, BackendDecision)`` tuple. The stub honours the env-var
    per component and applies StubResolverConfig overrides for the
    focus-component (fsm) and the Welle-4 partner (state_backing) to
    script failure scenarios.

    This stub exposes ``resolve_fsm_backend`` directly so the
    upstream-resolver path is exercised (fsm has been upstream since
    PR #169; no shim path needed for the focus). The shim path for
    the trailing bridge_audit_diff_engine component is exercised
    separately.
    """
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
            latency_us = 30  # generic default

            if component == focus:
                # fsm has only two enum values (python, rust).
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
            elif component == SMOKE.WELLE_4_PARTNER_COMPONENT:
                # state_backing — Welle-4 partner. By default honours
                # env-var.
                # cfg.state_backing_leaks_to_rust_on_fsm_cutover
                # simulates the cross-modul leak: state_backing flips
                # to "rust" whenever WAKIR_FSM_BACKEND is set to
                # "rust", regardless of what
                # WAKIR_STATE_BACKING_BACKEND says.
                if cfg.state_backing_leaks_to_rust_on_fsm_cutover:
                    fsm_value = env_map.get(focus_env_var, "")
                    if fsm_value == SMOKE.ENV_VALUE_RUST:
                        chosen = "rust"
                        requested = raw if raw else "python"
                        fallback_reason = "test_state_backing_cross_modul_leak"
                    else:
                        chosen = "rust" if requested == "rust" else "python"
                else:
                    chosen = "rust" if requested == "rust" else "python"
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
        if component == focus and cfg.drop_focus_on_rust:
            def _resolver_drop(
                env: Optional[Mapping[str, str]] = None,
                *,
                log_sink: Any = None,
                binary_probe: Any = None,
                _component: str = component,
            ) -> Tuple[Any, StubBackendDecision]:
                env_map = env or {}
                raw = env_map.get(focus_env_var, "")
                requested = raw if raw else "python"
                decision = StubBackendDecision(
                    domain="dropped_synthetic",
                    requested_backend=requested,
                    chosen_backend=requested,
                    resolution_latency_us=25,
                    fallback_reason=None,
                    bin_path=None,
                )
                return requested, decision

            setattr(module, f"resolve_{component}_backend", _resolver_drop)
        else:
            setattr(module, f"resolve_{component}_backend", _make_resolver(component))

    return module


# ---------------------------------------------------------------------------
# Stub lifecycle_state_machine_canonical module for A6 tests.
# ---------------------------------------------------------------------------


def build_stub_canonical_module(
    *,
    drift_after_first_call: bool = False,
) -> types.ModuleType:
    """Build a fake lifecycle_state_machine_canonical module.

    Exposes:

      * ``TransitionRecord`` — frozen dataclass mirroring the real
        canonical TransitionRecord (from_state, to_state, ts_utc,
        accepted, reason).
      * ``build_lifecycle_trace_from_records`` — returns a simple
        Trace dict with the inputs.
      * ``serialize_lifecycle_trace`` — JCS-canonical bytes of the
        trace dict.
      * ``lifecycle_trace_sha256_hex`` — hex SHA-256 of the
        serialised bytes.

    When ``drift_after_first_call`` is True the module salts the
    serialised output after the first call (the PRE-baseline batch),
    simulating substrate-drift between the pre-baseline capture and
    the post-cutover recomputation.

    Real wirelang module uses JCS-canonical bytes per
    ``tests/fixtures/lifecycle-state-machine-cross-lang/`` (PR
    #169 / PR #177). This stub keeps the test hermetic without
    depending on the real wirelang package being importable.
    """
    mod = types.ModuleType("wirelang.persona_engine.lifecycle_state_machine_canonical")

    state = {"call_count": 0}

    @dataclass(frozen=True)
    class TransitionRecord:
        from_state: str
        to_state: str
        ts_utc: str
        accepted: bool
        reason: Optional[str] = None

    @dataclass(frozen=True)
    class LifecycleTrace:
        final_state: str
        initial_state: str
        org_id: str
        persona_id: str
        records: Tuple[TransitionRecord, ...]

    def build_lifecycle_trace_from_records(
        *,
        persona_id: str,
        org_id: str,
        initial_state: str,
        records,
    ) -> LifecycleTrace:
        # Walk accepted records to compute final_state.
        state_cursor = initial_state
        for r in records:
            if r.accepted:
                state_cursor = r.to_state
        return LifecycleTrace(
            final_state=state_cursor,
            initial_state=initial_state,
            org_id=org_id,
            persona_id=persona_id,
            records=tuple(records),
        )

    def serialize_lifecycle_trace(trace: LifecycleTrace) -> bytes:
        state["call_count"] += 1
        records_wire = []
        for r in trace.records:
            entry = {
                "accepted": r.accepted,
                "from_state": r.from_state,
                "to_state": r.to_state,
                "ts_utc": r.ts_utc,
            }
            if r.reason is not None:
                entry["reason"] = r.reason
            records_wire.append(entry)
        canonical = {
            "final_state": trace.final_state,
            "initial_state": trace.initial_state,
            "org_id": trace.org_id,
            "persona_id": trace.persona_id,
            "records": records_wire,
            "schema": "wakir.persona-engine.lifecycle-trace/1",
        }
        payload = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        if drift_after_first_call and state["call_count"] > 2:
            # The smoke's _build_and_hash_trace calls
            # serialize_lifecycle_trace once directly AND once
            # indirectly via lifecycle_trace_sha256_hex per
            # baseline/post pass — that's two calls per pass. We
            # drift after the second call so baseline (calls 1+2)
            # is clean and post-cutover recompute (calls 3+4) is
            # salted, producing different hashes.
            payload += b"DRIFT"
        return payload

    def lifecycle_trace_sha256_hex(trace: LifecycleTrace) -> str:
        return hashlib.sha256(serialize_lifecycle_trace(trace)).hexdigest()

    mod.TransitionRecord = TransitionRecord  # type: ignore[attr-defined]
    mod.LifecycleTrace = LifecycleTrace  # type: ignore[attr-defined]
    mod.build_lifecycle_trace_from_records = (  # type: ignore[attr-defined]
        build_lifecycle_trace_from_records
    )
    mod.serialize_lifecycle_trace = serialize_lifecycle_trace  # type: ignore[attr-defined]
    mod.lifecycle_trace_sha256_hex = lifecycle_trace_sha256_hex  # type: ignore[attr-defined]
    return mod


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface() -> None:
    """The smoke module loads from its hyphenated path and exports __all__."""
    expected_exports = {
        "COMPONENT_TO_ENV",
        "DEFAULT_BOOTS_PER_PHASE",
        "DEFAULT_EXPECTED_COMPONENTS",
        "DEFAULT_LATENCY_TOLERANCE_PCT",
        "DETERMINISTIC_LIFECYCLE_TRANSITIONS",
        "DETERMINISTIC_TRACE_INITIAL_STATE",
        "DETERMINISTIC_TRACE_ORG_ID",
        "DETERMINISTIC_TRACE_PERSONA_ID",
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
        "PHASE_POST",
        "PHASE_PRE",
        "PHASE_ROLLBACK",
        "RESOLVER_PROVENANCE_SHIM",
        "RESOLVER_PROVENANCE_UPSTREAM",
        "SHIM_COMPONENT_PRIMITIVES",
        "SPEC_VALID_TRANSITIONS",
        "WELLE_4_PARTNER_COMPONENT",
        "WELLE_4_PARTNER_ENV_VAR",
        "boot_engine_once",
        "build_argparser",
        "build_envelope",
        "build_phase_env",
        "capture_fsm_transition_baseline_default",
        "derive_exit_code",
        "evaluate_fsm_transition_parity",
        "evaluate_post_cutover_asserts",
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
    assert SMOKE.FOCUS_COMPONENT == "fsm"
    assert SMOKE.FOCUS_COMPONENT_LONG == "lifecycle_state_machine"
    assert SMOKE.FOCUS_ENV_VAR == "WAKIR_FSM_BACKEND"
    assert SMOKE.EXIT_GREEN == 0
    assert SMOKE.EXIT_CAUTION == 1
    assert SMOKE.EXIT_ROLLBACK == 2
    assert SMOKE.ENVELOPE_SCHEMA == "wakir.phase-3c.welle-5-cutover-smoke/1"
    assert SMOKE.DEFAULT_EXPECTED_COMPONENTS == 11
    assert SMOKE.ENV_VALUE_PYTHON == "python"
    assert SMOKE.ENV_VALUE_RUST == "rust"
    assert SMOKE.WELLE_4_PARTNER_COMPONENT == "state_backing"
    assert SMOKE.WELLE_4_PARTNER_ENV_VAR == "WAKIR_STATE_BACKING_BACKEND"


def test_engine_boot_components_includes_fsm_and_partners() -> None:
    """fsm must be in ENGINE_BOOT_COMPONENTS alongside state_backing
    (Welle-4 partner) and the 11-component Welle-5 inventory at
    baseline 8ad125a (Tag-38 tip, post-PR-#241 wire-in).
    """
    components = SMOKE.ENGINE_BOOT_COMPONENTS
    assert "fsm" in components
    assert "state_backing" in components, (
        "Welle-4 partner state_backing must be in engine inventory"
    )
    # 11 = 10 baseline + bridge_audit_diff_engine (PR #241 wire-in,
    # landed pre-Tag-38).
    assert len(components) == 11
    for must_have in (
        "v907_verify",
        "svid_workload_identity",
        "bridge_diff",
        "anchor_emitter",
        "state_backing",
        "fsm",
        "subscribe_loop",
        "recovery",
        "federation_resolver",
        "bridge_audit_writer",
        "bridge_audit_diff_engine",
    ):
        assert must_have in components, must_have


def test_build_phase_env_pre_sets_all_python() -> None:
    """Pre-Cutover phase: every Phase-3c env-var is explicitly 'python'."""
    env = SMOKE.build_phase_env(SMOKE.PHASE_PRE)
    assert env[SMOKE.FOCUS_ENV_VAR] == "python"
    assert env[SMOKE.WELLE_4_PARTNER_ENV_VAR] == "python"
    for env_var in SMOKE.COMPONENT_TO_ENV.values():
        assert env[env_var] == "python", env_var


def test_build_phase_env_post_flips_focus_to_rust() -> None:
    """Cutover phase: fsm env-var is 'rust'; partner stays at python."""
    env = SMOKE.build_phase_env(SMOKE.PHASE_POST)
    assert env[SMOKE.FOCUS_ENV_VAR] == "rust"
    # Welle-4 partner stays at python — the cross-modul-drift contract.
    assert env[SMOKE.WELLE_4_PARTNER_ENV_VAR] == "python"
    for component, env_var in SMOKE.COMPONENT_TO_ENV.items():
        if component == SMOKE.FOCUS_COMPONENT:
            assert env[env_var] == "rust"
        else:
            assert env[env_var] == "python", env_var

    # Unknown phase raises.
    with pytest.raises(ValueError, match="unknown phase"):
        SMOKE.build_phase_env("not_a_phase")


def test_build_phase_env_rollback_removes_focus_env_var() -> None:
    """Rollback phase: focus env-var is absent from the env-map."""
    env = SMOKE.build_phase_env(SMOKE.PHASE_ROLLBACK)
    assert SMOKE.FOCUS_ENV_VAR not in env
    # Welle-4 partner still locked to python.
    assert env[SMOKE.WELLE_4_PARTNER_ENV_VAR] == "python"
    for component, env_var in SMOKE.COMPONENT_TO_ENV.items():
        if component == SMOKE.FOCUS_COMPONENT:
            continue
        assert env[env_var] == "python", env_var


def test_spec_valid_transitions_matches_spec_nine_edges() -> None:
    """SPEC_VALID_TRANSITIONS must match the spec §3.3 nine-edge enumeration.

    Mirrors :data:`wirelang.persona_engine.lifecycle_state_machine.VALID_TRANSITIONS`.
    """
    expected = (
        ("uninstantiated", "spawning"),
        ("spawning", "running"),
        ("spawning", "uninstantiated"),
        ("running", "despawning"),
        ("despawning", "uninstantiated"),
        ("uninstantiated", "recovered"),
        ("recovered", "running"),
        ("running", "migrated"),
        ("migrated", "uninstantiated"),
    )
    assert SMOKE.SPEC_VALID_TRANSITIONS == expected
    assert len(SMOKE.SPEC_VALID_TRANSITIONS) == 9
    # Deterministic fixture must only use transitions from the spec.
    deterministic = SMOKE.DETERMINISTIC_LIFECYCLE_TRANSITIONS
    assert len(deterministic) == 6
    for t in deterministic:
        if t["accepted"]:
            assert (t["from_state"], t["to_state"]) in expected, t


def test_run_cutover_smoke_green_path_exits_zero() -> None:
    """Default config + clean resolver → all asserts pass → exit GREEN."""
    resolver = build_stub_resolver_module()
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        now_ts=1_700_000_000,
        skip_fsm_transition_parity=True,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    assert envelope["band"] == "GREEN"
    assert envelope["schema"] == "wakir.phase-3c.welle-5-cutover-smoke/1"
    assert envelope["welle"] == 5
    assert envelope["focus_component"] == "fsm"
    assert envelope["focus_component_long"] == "lifecycle_state_machine"
    assert envelope["timestamp_utc"] == 1_700_000_000
    # All blocker asserts pass; A6 is skipped (caution, passed=True).
    for name, record in envelope["asserts"].items():
        assert record["passed"], (name, record)
    assert envelope["asserts"]["A6_fsm_transition_integrity"]["skipped"] is True
    # A7 cross-modul-drift is independent of A6 skip and always runs.
    a7 = envelope["asserts"]["A7_cross_modul_drift_welle_4_state_backing"]
    assert a7["passed"] is True
    assert a7["skipped"] is False
    assert a7["state_backing_chosen_backends"] == ["python"]


def test_run_cutover_smoke_caution_on_latency_blowup() -> None:
    """Latency 1000x baseline → A3 caution → exit CAUTION."""
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
        skip_fsm_transition_parity=True,
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
    assert envelope["asserts"]["A7_cross_modul_drift_welle_4_state_backing"]["passed"]


def test_run_cutover_smoke_rollback_on_fallback() -> None:
    """Resolver falls back to python on rust-request → A5 + A1 fail → ROLLBACK."""
    resolver = build_stub_resolver_module(
        StubResolverConfig(fallback_on_rust=True)
    )
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        skip_fsm_transition_parity=True,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_ROLLBACK, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    assert envelope["band"] == "ROLLBACK_RECOMMENDED"
    assert not envelope["asserts"]["A1_backend_flip"]["passed"]
    assert not envelope["asserts"]["A5_fallback_clean"]["passed"]


def test_run_cutover_smoke_rollback_when_post_stays_python() -> None:
    """Focus pinned to python even on rust-request → A1 fails → ROLLBACK."""
    resolver = build_stub_resolver_module(
        StubResolverConfig(pin_focus_to_python=True)
    )
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        skip_fsm_transition_parity=True,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_ROLLBACK
    assert envelope["band"] == "ROLLBACK_RECOMMENDED"
    assert not envelope["asserts"]["A1_backend_flip"]["passed"]


def test_run_cutover_smoke_rollback_when_rollback_phase_stays_rust() -> None:
    """Rollback-phase resolver still emits rust → R1 fails → ROLLBACK."""
    resolver = build_stub_resolver_module(
        StubResolverConfig(force_rust_on_rollback=True)
    )
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        skip_fsm_transition_parity=True,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_ROLLBACK
    assert not envelope["asserts"]["R1_rollback_to_python"]["passed"]


def test_main_cli_writes_envelope_and_returns_exit_code(tmp_path: Path) -> None:
    """CLI surface: --output writes JSON envelope, returns smoke exit code."""
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
            "--skip-fsm-transition-parity",
        ],
        stdout=stdout,
        stderr=stderr,
        resolver_module=resolver,
    )
    assert rc == SMOKE.EXIT_GREEN, stderr.getvalue()
    assert out_file.is_file()
    rendered = out_file.read_text(encoding="utf-8")
    envelope = json.loads(rendered)
    assert envelope["schema"] == "wakir.phase-3c.welle-5-cutover-smoke/1"
    assert envelope["boots_per_phase"] == 3
    assert envelope["timestamp_utc"] == 1700000001
    assert envelope["exit_code"] == SMOKE.EXIT_GREEN
    assert envelope["welle"] == 5
    assert envelope["focus_component"] == "fsm"
    assert envelope["focus_component_long"] == "lifecycle_state_machine"
    assert stdout.getvalue() == ""


def test_a6_fsm_transition_integrity_green_with_stub_canonical() -> None:
    """A6 fsm-transition-integrity green when canonical module is byte-stable."""
    resolver = build_stub_resolver_module()
    canonical = build_stub_canonical_module()
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        canonical_module=canonical,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a6 = envelope["asserts"]["A6_fsm_transition_integrity"]
    assert a6["passed"] is True
    assert a6["skipped"] is False
    assert a6["severity"] == "caution"
    assert a6["match"] is True
    assert a6["baseline_trace_sha256"] is not None
    assert a6["recomputed_trace_sha256"] == a6["baseline_trace_sha256"]
    assert a6["phantom_transitions"] == []
    # The envelope's fsm_transition_integrity block confirms the
    # operator-facing temporal anchor.
    integrity = envelope["fsm_transition_integrity"]
    assert integrity["baseline_captured_at_phase"] == SMOKE.PHASE_PRE
    assert integrity["baseline_skipped"] is False
    assert integrity["baseline_trace_sha256"] is not None
    assert integrity["baseline_phantom_transitions"] == []
    assert integrity["spec_valid_transition_count"] == 9
    # A7 cross-modul-drift remains green.
    a7 = envelope["asserts"]["A7_cross_modul_drift_welle_4_state_backing"]
    assert a7["passed"] is True


def test_a6_fsm_transition_integrity_caution_on_drift() -> None:
    """A6 drift between baseline + recompute → CAUTION exit, A7 still green.

    The stub canonical module salts its output after the first call
    (the baseline-capture). The subsequent recomputation call
    produces different JCS bytes, causing a hash mismatch in A6.
    A1..A5 + R1 + A7 all stay green because the engine-emission
    substance is intact and the cross-modul partner state_backing
    did not drift.
    """
    resolver = build_stub_resolver_module()
    canonical = build_stub_canonical_module(drift_after_first_call=True)
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        canonical_module=canonical,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_CAUTION, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a6 = envelope["asserts"]["A6_fsm_transition_integrity"]
    assert a6["passed"] is False
    assert a6["skipped"] is False
    assert a6["match"] is False
    assert a6["baseline_trace_sha256"] != a6["recomputed_trace_sha256"]
    # No phantom transitions — the deterministic fixture stays
    # within the spec; only the byte-form drifted.
    assert a6["phantom_transitions"] == []
    # A1..A5 + R1 + A7 all still pass — engine-emission substance intact.
    assert envelope["asserts"]["A1_backend_flip"]["passed"]
    assert envelope["asserts"]["A2_cross_lang_parity_hash"]["passed"]
    assert envelope["asserts"]["A3_latency_within_tolerance"]["passed"]
    assert envelope["asserts"]["A4_decision_count_in_place"]["passed"]
    assert envelope["asserts"]["A5_fallback_clean"]["passed"]
    assert envelope["asserts"]["R1_rollback_to_python"]["passed"]
    assert envelope["asserts"]["A7_cross_modul_drift_welle_4_state_backing"]["passed"]


def test_a6_fsm_transition_integrity_caution_on_phantom_transition() -> None:
    """A6 fires on a phantom transition (edge outside spec §3.3).

    Directly tests the evaluate_fsm_transition_parity helper with a
    corrupted transition tuple. The baseline records report a phantom
    edge (running -> uninstantiated) which is NOT in
    SPEC_VALID_TRANSITIONS. A6 must flag it.
    """
    canonical = build_stub_canonical_module()
    phantom_transitions: Tuple[Dict[str, Any], ...] = (
        {
            "from_state": "uninstantiated",
            "to_state": "spawning",
            "ts_utc": "2026-05-26T00:00:00Z",
            "accepted": True,
        },
        {
            "from_state": "spawning",
            "to_state": "running",
            "ts_utc": "2026-05-26T00:00:01Z",
            "accepted": True,
        },
        # PHANTOM: running -> uninstantiated is not in spec.
        {
            "from_state": "running",
            "to_state": "uninstantiated",
            "ts_utc": "2026-05-26T00:00:02Z",
            "accepted": True,
        },
    )
    baseline = SMOKE.capture_fsm_transition_baseline_default(
        transitions=phantom_transitions,
        canonical_module=canonical,
    )
    assert baseline is not None
    assert baseline["phantom_transitions"] == [("running", "uninstantiated")]
    # Now evaluate parity with the same phantom-containing fixture
    # — the recompute must flag the phantom edge.
    parity = SMOKE.evaluate_fsm_transition_parity(
        baseline,
        transitions=phantom_transitions,
        canonical_module=canonical,
    )
    assert parity["passed"] is False
    # match=True (hash equal) but phantom present.
    assert parity["match"] is True
    assert parity["phantom_transitions"] == [("running", "uninstantiated")]
    assert "phantom" in parity["detail"].lower()


def test_a7_cross_modul_drift_to_welle_4_state_backing_blocks_on_leak() -> None:
    """A7 fires + ROLLBACK when state_backing leaks to rust in PHASE_POST.

    Regression-trap (symmetric to Welle-4's A7 test): if the fsm
    cutover accidentally leaks into the state_backing resolver path
    during the KW-26 Doppel-Welle window (e.g. via shared cache,
    env-var clobber, or back-channel boot-order coupling), the A7
    cross-modul-drift assert must fire and push the exit-code to
    ROLLBACK. We simulate the bad leak by configuring the stub
    resolver to force state_backing to "rust" whenever
    WAKIR_FSM_BACKEND is set to "rust". The smoke must detect this
    in PHASE_POST and flag it.
    """
    cfg = StubResolverConfig(
        state_backing_leaks_to_rust_on_fsm_cutover=True
    )
    resolver = build_stub_resolver_module(cfg)
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        skip_fsm_transition_parity=True,
        expected_components=11,
    )
    # A7 is a blocker → exit_code must be ROLLBACK.
    assert exit_code == SMOKE.EXIT_ROLLBACK, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a7 = envelope["asserts"]["A7_cross_modul_drift_welle_4_state_backing"]
    assert a7["passed"] is False
    assert a7["severity"] == "blocker"
    assert "rust" in a7["state_backing_chosen_backends"]
    assert a7["expected_state_backing_backend"] == "python"
    assert "leaked into state_backing path" in a7["detail"]
    # The envelope's cross_modul_drift_mitigation block surfaces
    # the bug for the operator.
    mitigation = envelope["cross_modul_drift_mitigation"]
    assert mitigation["welle_4_partner_component"] == "state_backing"
    assert mitigation["welle_4_partner_env_var"] == "WAKIR_STATE_BACKING_BACKEND"
    assert "rust" in mitigation["state_backing_chosen_backends_in_post_phase"]
    # A1..A5 + R1 should still pass (fsm itself behaves correctly;
    # only state_backing drifted).
    assert envelope["asserts"]["A1_backend_flip"]["passed"]
    assert envelope["asserts"]["A5_fallback_clean"]["passed"]
    assert envelope["asserts"]["R1_rollback_to_python"]["passed"]


def test_resolver_shim_used_when_bridge_audit_diff_engine_upstream_missing() -> None:
    """Smoke uses the local shim for bridge_audit_diff_engine when upstream missing.

    Mimics a pre-PR-#241 baseline state: the resolver module
    exposes the env-var constant and bin-resolver but no
    ``resolve_bridge_audit_diff_engine_backend`` function. The smoke
    must transparently fall back to the local shim, mark the
    provenance as ``"shim"`` for bridge_audit_diff_engine only, and
    still emit a green envelope (all other components are upstream).
    fsm itself is ALWAYS upstream (PR #169); only the trailing 11th
    component may be shim.
    """
    cfg = StubResolverConfig()
    module = build_stub_resolver_module(cfg)
    # Surgically remove the upstream resolve_* function for the
    # 11th component so the smoke is forced onto the shim.
    delattr(module, "resolve_bridge_audit_diff_engine_backend")
    # Provide the shim's prerequisites on the module.
    module.BRIDGE_AUDIT_DIFF_ENGINE_BACKEND_ENV = (  # type: ignore[attr-defined]
        "WAKIR_BRIDGE_AUDIT_DIFF_ENGINE_BACKEND"
    )

    def _resolve_bridge_audit_diff_engine_bin(
        env: Optional[Mapping[str, str]] = None,
    ) -> str:
        return "/opt/wakir/bin/wakir-persona-engine-bridge-audit-diff-engine"

    def _binary_available(_bin_path: str) -> Tuple[bool, Optional[str]]:
        return True, None

    module._resolve_bridge_audit_diff_engine_bin = (  # type: ignore[attr-defined]
        _resolve_bridge_audit_diff_engine_bin
    )
    module._binary_available = _binary_available  # type: ignore[attr-defined]

    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=module,
        binary_probe=lambda _p: (True, None),
        skip_fsm_transition_parity=True,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    provenance = envelope["resolver_provenance"]
    assert (
        provenance["bridge_audit_diff_engine"] == SMOKE.RESOLVER_PROVENANCE_SHIM
    )
    # fsm must always be upstream.
    assert provenance["fsm"] == SMOKE.RESOLVER_PROVENANCE_UPSTREAM
    # state_backing (Welle-4 partner) is also always upstream.
    assert provenance["state_backing"] == SMOKE.RESOLVER_PROVENANCE_UPSTREAM
    # Spot-check other components are upstream.
    assert provenance["v907_verify"] == SMOKE.RESOLVER_PROVENANCE_UPSTREAM
    assert envelope["asserts"]["A1_backend_flip"]["passed"]


def test_run_cutover_smoke_pre_pr241_baseline_expected_components_10() -> None:
    """Pre-PR-#241 baseline (10 components) still works via --expected-components 10.

    When operators run the smoke against a baseline that pre-dates
    the bridge_audit_diff_engine wire-in, they pass
    ``--expected-components 10`` and the A4 assert tracks the 10-
    component inventory. The smoke's ENGINE_BOOT_COMPONENTS still
    iterates all 11 entries (the 11th is shim-served when upstream
    is missing) — but the A4 expected-count is set by the caller.

    To make A4 pass with expected_components=10, we simulate the
    pre-PR-#241 state by surgically dropping the 11th component
    from the ENGINE_BOOT_COMPONENTS tuple via the explicit
    ``components=`` kwarg on run_cutover_smoke.
    """
    cfg = StubResolverConfig()
    module = build_stub_resolver_module(cfg)
    # Build a 10-component tuple (drop the trailing
    # bridge_audit_diff_engine slot).
    components_pre_241 = tuple(
        c for c in SMOKE.ENGINE_BOOT_COMPONENTS
        if c != "bridge_audit_diff_engine"
    )
    assert len(components_pre_241) == 10
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=module,
        binary_probe=lambda _p: (True, None),
        skip_fsm_transition_parity=True,
        expected_components=10,
        components=components_pre_241,
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a4 = envelope["asserts"]["A4_decision_count_in_place"]
    assert a4["passed"] is True
    assert envelope["expected_components"] == 10
    # The envelope's engine_boot_components STILL reports the full
    # 11-entry inventory tuple — operators see what the smoke
    # iterates by default, and the --expected-components / components
    # kwargs control what gets counted.
    assert len(envelope["engine_boot_components"]) == 11
