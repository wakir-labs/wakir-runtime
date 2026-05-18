# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/phase-3c/welle-4-state-backing-cutover-smoke.py.

Hermetic, stdlib-only. The smoke module is loaded via importlib from
its hyphenated path under ``scripts/phase-3c/``. The resolver dep is
exercised through a stub module so the tests never import the real
wirelang package, and every test injects ``resolver_module`` +
``binary_probe`` explicitly so no filesystem access happens.

Scope (14 tests; Auftrag-Tag-37 minimum is 12 — exceeded so the
Welle-4-specific cross-modul-drift edges (A6+A7) get explicit per-
axis coverage)
--------------------------------------------------------------------

1.  test_module_loads_and_exports_public_surface
2.  test_engine_boot_components_includes_state_backing_and_partners
3.  test_build_phase_env_pre_sets_all_python
4.  test_build_phase_env_post_flips_focus_to_rust_inmemory
5.  test_build_phase_env_post_supports_rust_natskv_target
6.  test_build_phase_env_rollback_removes_focus_env_var
7.  test_run_cutover_smoke_green_path_exits_zero
8.  test_run_cutover_smoke_caution_on_latency_blowup
9.  test_run_cutover_smoke_rollback_on_fallback
10. test_run_cutover_smoke_rollback_when_post_stays_python
11. test_run_cutover_smoke_rollback_when_rollback_phase_stays_rust
12. test_main_cli_writes_envelope_and_returns_exit_code
13. test_a6_cross_backend_read_compatibility_green_with_stub_backing
14. test_a6_cross_backend_read_compatibility_caution_on_drift
15. test_a7_cross_modul_drift_to_welle_5_fsm_blocks_on_fsm_leak

The first 12 mirror the Welle-3 pattern verbatim (parametrised for
state_backing's three-valued enum vs. Welle-3's two-valued enum).
Tests 13+14 exercise the A6 Cross-Backend-Read-Compatibility assert.
Test 15 is the Cross-Modul-Drift-to-Welle-5 regression-trap:
constructs a resolver-stub where the fsm BackendDecision drifts to
"rust" in PHASE_POST (simulating the parallel-Welle isolation break)
and asserts that A7 fires + exit_code is ROLLBACK_RECOMMENDED.
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
        / "welle-4-state-backing-cutover-smoke.py"
    )
    if not smoke_path.is_file():
        pytest.fail(f"smoke script not found at {smoke_path}")
    spec = importlib.util.spec_from_file_location(
        "welle_4_state_backing_cutover_smoke", str(smoke_path)
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build spec for {smoke_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["welle_4_state_backing_cutover_smoke"] = module
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
    # Welle-4 specific: simulate fsm cross-modul-drift leak.
    fsm_leaks_to_rust_on_state_backing_cutover: bool = False
    rust_backend_value: str = "rust_inmemory"


def build_stub_resolver_module(
    config: Optional[StubResolverConfig] = None,
) -> types.ModuleType:
    """Build a fake rust_backend_switch module wired by the StubResolverConfig.

    The smoke calls ``resolve_<component>_backend(env=..., log_sink=...,
    binary_probe=...)`` for each in-place component, expecting a
    ``(backend, BackendDecision)`` tuple. The stub honours the env-var
    per component and applies the StubResolverConfig overrides for
    the focus-component (state_backing) and the Welle-5 partner
    (fsm) to script failure scenarios.

    This stub exposes ``resolve_state_backing_backend`` directly so
    the upstream-resolver path is exercised (state_backing has been
    upstream since PR #167; no shim path needed for the focus).
    The shim path for the trailing bridge_audit_diff_engine
    component is exercised separately.
    """
    cfg = config or StubResolverConfig()
    module = types.ModuleType("wirelang.persona_engine.rust_backend_switch")

    component_to_env = SMOKE.COMPONENT_TO_ENV
    focus = SMOKE.FOCUS_COMPONENT
    focus_env_var = SMOKE.FOCUS_ENV_VAR
    rust_default = cfg.rust_backend_value

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
                # state_backing has three valid enum values.
                # cutover target is rust_default (rust_inmemory by default).
                if requested in SMOKE.VALID_RUST_VALUES:
                    if cfg.pin_focus_to_python:
                        chosen = "python"
                        fallback_reason = "test_pin_focus_to_python"
                    elif cfg.fallback_on_rust:
                        chosen = "python"
                        fallback_reason = "binary_missing"
                    else:
                        chosen = requested
                    latency_us = cfg.rust_focus_latency_us
                else:
                    if cfg.force_rust_on_rollback and env_var not in env_map:
                        chosen = rust_default
                        fallback_reason = "test_force_rust_on_rollback"
                    else:
                        chosen = "python"
                    latency_us = cfg.python_focus_latency_us
            elif component == SMOKE.WELLE_5_PARTNER_COMPONENT:
                # fsm — Welle-5 partner. By default honours env-var.
                # cfg.fsm_leaks_to_rust_on_state_backing_cutover
                # simulates the cross-modul leak: fsm flips to "rust"
                # whenever the state_backing env-var is set to a rust
                # value, regardless of what WAKIR_FSM_BACKEND says.
                if cfg.fsm_leaks_to_rust_on_state_backing_cutover:
                    sb_value = env_map.get(focus_env_var, "")
                    if sb_value in SMOKE.VALID_RUST_VALUES:
                        chosen = "rust"
                        requested = raw if raw else "python"
                        fallback_reason = "test_fsm_cross_modul_leak"
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
        elif component == "bridge_audit_diff_engine":
            # Expose the upstream resolver too so the smoke uses it
            # (resolver_provenance == "upstream") rather than the shim.
            # The Reza Tag-36 #241 wire-in is simulated as already
            # landed for these tests; shim path is covered in a
            # dedicated test.
            setattr(module, f"resolve_{component}_backend", _make_resolver(component))
        else:
            setattr(module, f"resolve_{component}_backend", _make_resolver(component))

    return module


# ---------------------------------------------------------------------------
# Stub state_backing module for A6 tests.
# ---------------------------------------------------------------------------


def build_stub_state_backing_module(
    *,
    drift_after_first_call: bool = False,
) -> types.ModuleType:
    """Build a fake state_backing module with PersonaStateSnapshot.

    Exposes a dataclass-style ``PersonaStateSnapshot`` plus a module-
    level ``snapshot_to_jcs_bytes`` helper whose output is
    deterministic JCS-canonical bytes. When ``drift_after_first_call``
    is True the module salts the output after the first 3 calls
    (the PRE-baseline batch), simulating a substrate-drift between
    the pre-baseline capture and the post-cutover recomputation.

    Real wirelang module uses JCS-canonical bytes per
    ``tests/fixtures/state-backing-cross-lang/fixtures.json`` (PR
    #183, Tag-23). This stub keeps the test hermetic without
    depending on the real wirelang package being importable.
    """
    mod = types.ModuleType("wirelang.persona_engine.state_backing")

    state = {"call_count": 0}

    @dataclass(frozen=True)
    class PersonaStateSnapshot:
        persona_hash: str
        audit_trace_offset: int
        capability_token_ids: Tuple[str, ...]
        snapshot_at_utc: str
        workspace_state_hash: str

    def snapshot_to_jcs_bytes(snapshot: PersonaStateSnapshot) -> bytes:
        state["call_count"] += 1
        canonical = {
            "audit_trace_offset": snapshot.audit_trace_offset,
            "capability_token_ids": list(snapshot.capability_token_ids),
            "persona_hash": snapshot.persona_hash,
            "snapshot_at_utc": snapshot.snapshot_at_utc,
            "workspace_state_hash": snapshot.workspace_state_hash,
        }
        payload = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        if drift_after_first_call and state["call_count"] > 3:
            # First three calls (PRE-baseline) are clean; next three
            # (POST recomputation) are salted.
            payload += b"DRIFT"
        return payload

    mod.PersonaStateSnapshot = PersonaStateSnapshot  # type: ignore[attr-defined]
    mod.snapshot_to_jcs_bytes = snapshot_to_jcs_bytes  # type: ignore[attr-defined]
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
        "DEFAULT_STATE_BACKING_FIXTURE_RELPATH",
        "ENGINE_BOOT_COMPONENTS",
        "ENVELOPE_SCHEMA",
        "ENV_VALUE_PYTHON",
        "ENV_VALUE_RUST_DEFAULT",
        "ENV_VALUE_RUST_NATSKV",
        "EXIT_CAUTION",
        "EXIT_GREEN",
        "EXIT_ROLLBACK",
        "FOCUS_COMPONENT",
        "FOCUS_ENV_VAR",
        "PHASE_POST",
        "PHASE_PRE",
        "PHASE_ROLLBACK",
        "RESOLVER_PROVENANCE_SHIM",
        "RESOLVER_PROVENANCE_UPSTREAM",
        "SHIM_COMPONENT_PRIMITIVES",
        "STATE_BACKING_DETERMINISTIC_SNAPSHOTS",
        "VALID_RUST_VALUES",
        "WELLE_5_PARTNER_COMPONENT",
        "WELLE_5_PARTNER_ENV_VAR",
        "boot_engine_once",
        "build_argparser",
        "build_envelope",
        "build_phase_env",
        "capture_state_snapshot_baseline_default",
        "derive_exit_code",
        "evaluate_post_cutover_asserts",
        "evaluate_state_snapshot_parity",
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
    assert SMOKE.FOCUS_COMPONENT == "state_backing"
    assert SMOKE.FOCUS_ENV_VAR == "WAKIR_STATE_BACKING_BACKEND"
    assert SMOKE.EXIT_GREEN == 0
    assert SMOKE.EXIT_CAUTION == 1
    assert SMOKE.EXIT_ROLLBACK == 2
    assert SMOKE.ENVELOPE_SCHEMA == "wakir.phase-3c.welle-4-cutover-smoke/1"
    assert SMOKE.DEFAULT_EXPECTED_COMPONENTS == 10
    assert SMOKE.ENV_VALUE_RUST_DEFAULT == "rust_inmemory"
    assert SMOKE.ENV_VALUE_RUST_NATSKV == "rust_natskv"
    assert SMOKE.VALID_RUST_VALUES == ("rust_inmemory", "rust_natskv")
    assert SMOKE.WELLE_5_PARTNER_COMPONENT == "fsm"
    assert SMOKE.WELLE_5_PARTNER_ENV_VAR == "WAKIR_FSM_BACKEND"


def test_engine_boot_components_includes_state_backing_and_partners() -> None:
    """state_backing must be in ENGINE_BOOT_COMPONENTS alongside fsm
    (Welle-5 partner) and the 11-component Welle-4 inventory at
    baseline 4803394 + Reza-Tag-36-#241 wire-in target.
    """
    components = SMOKE.ENGINE_BOOT_COMPONENTS
    assert "state_backing" in components
    assert "fsm" in components, "Welle-5 partner fsm must be in engine inventory"
    # 11 = 10 baseline + bridge_audit_diff_engine (PR #241 wire-in target).
    assert len(components) == 11
    # 9 baseline + bridge_audit_writer + bridge_audit_diff_engine.
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
    assert env[SMOKE.WELLE_5_PARTNER_ENV_VAR] == "python"
    for env_var in SMOKE.COMPONENT_TO_ENV.values():
        assert env[env_var] == "python", env_var


def test_build_phase_env_post_flips_focus_to_rust_inmemory() -> None:
    """Cutover phase: state_backing env-var is 'rust_inmemory' default."""
    env = SMOKE.build_phase_env(SMOKE.PHASE_POST)
    assert env[SMOKE.FOCUS_ENV_VAR] == "rust_inmemory"
    # Welle-5 partner stays at python — the cross-modul-drift contract.
    assert env[SMOKE.WELLE_5_PARTNER_ENV_VAR] == "python"
    for component, env_var in SMOKE.COMPONENT_TO_ENV.items():
        if component == SMOKE.FOCUS_COMPONENT:
            assert env[env_var] == "rust_inmemory"
        else:
            assert env[env_var] == "python", env_var


def test_build_phase_env_post_supports_rust_natskv_target() -> None:
    """Cutover phase: rust_backend_value=rust_natskv overrides default."""
    env = SMOKE.build_phase_env(
        SMOKE.PHASE_POST, rust_backend_value="rust_natskv"
    )
    assert env[SMOKE.FOCUS_ENV_VAR] == "rust_natskv"
    # Welle-5 partner still locked to python.
    assert env[SMOKE.WELLE_5_PARTNER_ENV_VAR] == "python"
    # Invalid rust value raises.
    with pytest.raises(ValueError, match="rust_backend_value"):
        SMOKE.build_phase_env(
            SMOKE.PHASE_POST, rust_backend_value="rust_unknown"
        )


def test_build_phase_env_rollback_removes_focus_env_var() -> None:
    """Rollback phase: focus env-var is absent from the env-map."""
    env = SMOKE.build_phase_env(SMOKE.PHASE_ROLLBACK)
    assert SMOKE.FOCUS_ENV_VAR not in env
    # Welle-5 partner still locked to python.
    assert env[SMOKE.WELLE_5_PARTNER_ENV_VAR] == "python"
    for component, env_var in SMOKE.COMPONENT_TO_ENV.items():
        if component == SMOKE.FOCUS_COMPONENT:
            continue
        assert env[env_var] == "python", env_var


def test_run_cutover_smoke_green_path_exits_zero() -> None:
    """Default config + clean resolver → all asserts pass → exit GREEN.

    Tests pass ``expected_components=11`` to match the smoke's full
    inventory (11 = 10 baseline + bridge_audit_diff_engine).
    """
    resolver = build_stub_resolver_module()
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        now_ts=1_700_000_000,
        skip_state_snapshot_parity=True,
        expected_components=11,  # matches ENGINE_BOOT_COMPONENTS length
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    assert envelope["band"] == "GREEN"
    assert envelope["schema"] == "wakir.phase-3c.welle-4-cutover-smoke/1"
    assert envelope["welle"] == 4
    assert envelope["focus_component"] == "state_backing"
    assert envelope["rust_backend_value"] == "rust_inmemory"
    assert envelope["timestamp_utc"] == 1_700_000_000
    # All blocker asserts pass; A6 is skipped (caution, passed=True).
    for name, record in envelope["asserts"].items():
        assert record["passed"], (name, record)
    assert envelope["asserts"]["A6_cross_backend_read_compatibility"]["skipped"] is True
    # A7 cross-modul-drift is independent of A6 skip and always runs.
    a7 = envelope["asserts"]["A7_cross_modul_drift_welle_5_fsm"]
    assert a7["passed"] is True
    assert a7["skipped"] is False
    assert a7["fsm_chosen_backends"] == ["python"]


def test_run_cutover_smoke_caution_on_latency_blowup() -> None:
    """Latency 1000× baseline → A3 caution → exit CAUTION."""
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
        skip_state_snapshot_parity=True,
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
    assert envelope["asserts"]["A7_cross_modul_drift_welle_5_fsm"]["passed"]


def test_run_cutover_smoke_rollback_on_fallback() -> None:
    """Resolver falls back to python on rust-request → A5 + A1 fail → ROLLBACK."""
    resolver = build_stub_resolver_module(
        StubResolverConfig(fallback_on_rust=True)
    )
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        skip_state_snapshot_parity=True,
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
        skip_state_snapshot_parity=True,
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
        skip_state_snapshot_parity=True,
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
            "--skip-state-snapshot-parity",
        ],
        stdout=stdout,
        stderr=stderr,
        resolver_module=resolver,
    )
    assert rc == SMOKE.EXIT_GREEN, stderr.getvalue()
    assert out_file.is_file()
    rendered = out_file.read_text(encoding="utf-8")
    envelope = json.loads(rendered)
    assert envelope["schema"] == "wakir.phase-3c.welle-4-cutover-smoke/1"
    assert envelope["boots_per_phase"] == 3
    assert envelope["timestamp_utc"] == 1700000001
    assert envelope["exit_code"] == SMOKE.EXIT_GREEN
    assert envelope["welle"] == 4
    assert envelope["focus_component"] == "state_backing"
    assert stdout.getvalue() == ""


def test_a6_cross_backend_read_compatibility_green_with_stub_backing() -> None:
    """A6 cross-backend-read-compatibility green when backing module is byte-stable."""
    resolver = build_stub_resolver_module()
    backing = build_stub_state_backing_module()
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        state_backing_module=backing,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a6 = envelope["asserts"]["A6_cross_backend_read_compatibility"]
    assert a6["passed"] is True
    assert a6["skipped"] is False
    assert a6["severity"] == "caution"
    assert a6["match"] is True
    assert a6["baseline_stream_sha256"] is not None
    assert a6["recomputed_stream_sha256"] == a6["baseline_stream_sha256"]
    # The envelope's cross_backend_read_compatibility block confirms
    # the operator-facing temporal anchor.
    mitigation = envelope["cross_backend_read_compatibility"]
    assert mitigation["baseline_captured_at_phase"] == SMOKE.PHASE_PRE
    assert mitigation["baseline_skipped"] is False
    assert mitigation["baseline_stream_sha256"] is not None
    # A7 cross-modul-drift remains green.
    a7 = envelope["asserts"]["A7_cross_modul_drift_welle_5_fsm"]
    assert a7["passed"] is True


def test_a6_cross_backend_read_compatibility_caution_on_drift() -> None:
    """A6 drift between baseline + recompute → CAUTION exit, A7 still green.

    The stub backing salts its output after the first 3 snapshots
    (the baseline-capture set). The next 3 snapshots (the post-
    cutover recomputation) produce different JCS bytes, causing a
    hash mismatch in A6. A1..A5 + R1 + A7 all stay green because the
    engine-emission substance is intact and the cross-modul partner
    fsm did not drift.
    """
    resolver = build_stub_resolver_module()
    backing = build_stub_state_backing_module(drift_after_first_call=True)
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        state_backing_module=backing,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_CAUTION, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a6 = envelope["asserts"]["A6_cross_backend_read_compatibility"]
    assert a6["passed"] is False
    assert a6["skipped"] is False
    assert a6["match"] is False
    assert a6["baseline_stream_sha256"] != a6["recomputed_stream_sha256"]
    # A1..A5 + R1 + A7 all still pass — engine-emission substance intact.
    assert envelope["asserts"]["A1_backend_flip"]["passed"]
    assert envelope["asserts"]["A2_cross_lang_parity_hash"]["passed"]
    assert envelope["asserts"]["A3_latency_within_tolerance"]["passed"]
    assert envelope["asserts"]["A4_decision_count_in_place"]["passed"]
    assert envelope["asserts"]["A5_fallback_clean"]["passed"]
    assert envelope["asserts"]["R1_rollback_to_python"]["passed"]
    assert envelope["asserts"]["A7_cross_modul_drift_welle_5_fsm"]["passed"]


def test_a7_cross_modul_drift_to_welle_5_fsm_blocks_on_fsm_leak() -> None:
    """A7 fires + ROLLBACK when fsm BackendDecision leaks to rust in PHASE_POST.

    Regression-trap: if the state_backing cutover accidentally leaks
    into the fsm resolver path during the KW-26 Doppel-Welle window
    (e.g. via shared cache, env-var clobber, or back-channel boot-
    order coupling), the A7 cross-modul-drift assert must fire and
    push the exit-code to ROLLBACK. We simulate the bad leak by
    configuring the stub resolver to force fsm to "rust" whenever
    the state_backing env-var is set to a rust value. The smoke
    must detect this in PHASE_POST and flag it.
    """
    cfg = StubResolverConfig(
        fsm_leaks_to_rust_on_state_backing_cutover=True
    )
    resolver = build_stub_resolver_module(cfg)
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        skip_state_snapshot_parity=True,
        expected_components=11,
    )
    # A7 is a blocker → exit_code must be ROLLBACK.
    assert exit_code == SMOKE.EXIT_ROLLBACK, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a7 = envelope["asserts"]["A7_cross_modul_drift_welle_5_fsm"]
    assert a7["passed"] is False
    assert a7["severity"] == "blocker"
    assert "rust" in a7["fsm_chosen_backends"]
    assert a7["expected_fsm_backend"] == "python"
    assert "leaked into fsm path" in a7["detail"]
    # The envelope's cross_modul_drift_mitigation block surfaces
    # the bug for the operator.
    mitigation = envelope["cross_modul_drift_mitigation"]
    assert mitigation["welle_5_partner_component"] == "fsm"
    assert mitigation["welle_5_partner_env_var"] == "WAKIR_FSM_BACKEND"
    assert "rust" in mitigation["fsm_chosen_backends_in_post_phase"]
    # A1..A5 + R1 should still pass (state_backing itself behaves
    # correctly; only fsm drifted).
    assert envelope["asserts"]["A1_backend_flip"]["passed"]
    assert envelope["asserts"]["A5_fallback_clean"]["passed"]
    assert envelope["asserts"]["R1_rollback_to_python"]["passed"]


def test_resolver_shim_used_when_bridge_audit_diff_engine_upstream_missing() -> None:
    """Smoke uses the local shim for bridge_audit_diff_engine when upstream missing.

    Mimics the Reza Tag-36 #241-wire-in-pending state: the resolver
    module exposes the env-var constant and bin-resolver but no
    ``resolve_bridge_audit_diff_engine_backend`` function. The smoke
    must transparently fall back to the local shim, mark the
    provenance as ``"shim"`` for bridge_audit_diff_engine only, and
    still emit a green envelope (all other components are upstream).
    state_backing itself is ALWAYS upstream (PR #167); only the
    trailing 11th component may be shim.
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

    # Use --expected-components 10 to match the post-baseline-pre-
    # wire-in shape: smoke still ENGINE_BOOT_COMPONENTS-iterates
    # all 11, but A4 expects 10 in-place (the missing-upstream
    # resolver flagged as shim is informationally counted via
    # resolver_provenance, not via the A4 component-count).
    # In practice operators pass --expected-components 11 because
    # the smoke still produces 11 BackendDecisions per boot (the
    # shim emits one too). We test with 11 here.
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=module,
        binary_probe=lambda _p: (True, None),
        skip_state_snapshot_parity=True,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    provenance = envelope["resolver_provenance"]
    assert (
        provenance["bridge_audit_diff_engine"] == SMOKE.RESOLVER_PROVENANCE_SHIM
    )
    # state_backing must always be upstream.
    assert provenance["state_backing"] == SMOKE.RESOLVER_PROVENANCE_UPSTREAM
    # Spot-check other components are upstream.
    assert provenance["v907_verify"] == SMOKE.RESOLVER_PROVENANCE_UPSTREAM
    assert provenance["fsm"] == SMOKE.RESOLVER_PROVENANCE_UPSTREAM
    assert envelope["asserts"]["A1_backend_flip"]["passed"]
