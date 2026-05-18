# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/phase-3c/welle-3-bridge-audit-writer-cutover-smoke.py.

Hermetic, stdlib-only. The smoke module is loaded via importlib from
its hyphenated path under ``scripts/phase-3c/``. The resolver dep is
exercised through a stub module so the tests never import the real
wirelang package, and every test injects ``resolver_module`` +
``binary_probe`` explicitly so no filesystem access happens.

Scope (15 tests; Auftrag-Tag-36 minimum is 12 — exceeded so the
Self-Reference-Trap-edge-cases get explicit per-axis coverage)
--------------------------------------------------------------

1.  test_module_loads_and_exports_public_surface
2.  test_engine_boot_components_includes_bridge_audit_writer
3.  test_build_phase_env_pre_sets_all_python
4.  test_build_phase_env_post_flips_focus_to_rust
5.  test_build_phase_env_rollback_removes_focus_env_var
6.  test_run_cutover_smoke_green_path_exits_zero
7.  test_run_cutover_smoke_caution_on_latency_blowup
8.  test_run_cutover_smoke_rollback_on_fallback
9.  test_run_cutover_smoke_rollback_when_post_stays_python
10. test_run_cutover_smoke_rollback_when_rollback_phase_stays_rust
11. test_main_cli_writes_envelope_and_returns_exit_code
12. test_a6_bridge_audit_stream_parity_green_with_stub_writer
13. test_a6_bridge_audit_stream_parity_caution_on_drift
14. test_a7_self_reference_trap_control_blocks_post_phase_capture
15. test_resolver_shim_used_when_upstream_resolver_missing

The first 11 mirror the Welle-2 pattern verbatim. Tests 12+13
exercise the A6 substrate-parity assert. Test 14 is the explicit
Self-Reference-Trap-Mitigation regression-trap: it constructs an
envelope where the bridge-audit-stream baseline was captured in
PHASE_POST and asserts that A7 fires + exit_code is ROLLBACK_
RECOMMENDED. Test 15 verifies the resolver-shim path that handles
the Reza-Tag-36-wire-in-pending state.
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
        / "welle-3-bridge-audit-writer-cutover-smoke.py"
    )
    if not smoke_path.is_file():
        pytest.fail(f"smoke script not found at {smoke_path}")
    spec = importlib.util.spec_from_file_location(
        "welle_3_bridge_audit_writer_cutover_smoke", str(smoke_path)
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build spec for {smoke_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["welle_3_bridge_audit_writer_cutover_smoke"] = module
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


def build_stub_resolver_module(
    config: Optional[StubResolverConfig] = None,
) -> types.ModuleType:
    """Build a fake rust_backend_switch module wired by the StubResolverConfig.

    The smoke calls ``resolve_<component>_backend(env=..., log_sink=...,
    binary_probe=...)`` for each in-place component, expecting a
    ``(backend, BackendDecision)`` tuple. The stub honours the env-var
    per component and applies the StubResolverConfig overrides for
    the focus-component (bridge_audit_writer) to script failure
    scenarios.

    This stub exposes ``resolve_bridge_audit_writer_backend`` directly
    so the upstream-resolver path is exercised. The shim path is
    exercised separately in
    ``test_resolver_shim_used_when_upstream_resolver_missing``.
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
                if requested == "rust":
                    if cfg.pin_focus_to_python:
                        chosen = "python"
                        fallback_reason = "test_pin_focus_to_python"
                    elif cfg.fallback_on_rust:
                        chosen = "python"
                        fallback_reason = "binary_missing"
                    else:
                        chosen = "rust"
                    latency_us = cfg.rust_focus_latency_us
                else:
                    if cfg.force_rust_on_rollback and env_var not in env_map:
                        chosen = "rust"
                        fallback_reason = "test_force_rust_on_rollback"
                    else:
                        chosen = "python"
                    latency_us = cfg.python_focus_latency_us
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
# Stub bridge_audit_writer module for A6 tests.
# ---------------------------------------------------------------------------


def build_stub_bridge_audit_writer_module(
    *,
    drift_after_first_call: bool = False,
) -> types.ModuleType:
    """Build a fake bridge_audit_writer module with EngineeringOutputEvent.

    Exposes a dataclass-style ``EngineeringOutputEvent`` whose
    ``to_jcs_bytes()`` produces a deterministic JCS-canonical byte
    string. When ``drift_after_first_call`` is True the module
    salts the output after the first call, simulating a substrate-
    drift between the pre-baseline capture and the post-cutover
    recomputation.

    Real wirelang module uses JCS-canonical bytes per
    ``tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json``
    (PR #210). This stub keeps the test hermetic without depending on
    the real wirelang package being importable.
    """
    mod = types.ModuleType("wirelang.persona_engine.bridge_audit_writer")

    state = {"call_count": 0}

    @dataclass(frozen=True)
    class EngineeringOutputEvent:
        org_id: str
        persona_id: str
        session_id: str
        step_index: int
        output_kind: str
        output_payload_sha256: str
        engine_version: str
        v907_pin: str
        ts_utc: str

        def to_jcs_bytes(self_inner) -> bytes:
            state["call_count"] += 1
            payload = json.dumps(
                {
                    "engine_version": self_inner.engine_version,
                    "event_kind": "engineering_output",
                    "org_id": self_inner.org_id,
                    "output_kind": self_inner.output_kind,
                    "output_payload_sha256": self_inner.output_payload_sha256,
                    "persona_id": self_inner.persona_id,
                    "schema": "wakir.persona.engineering-output/1",
                    "session_id": self_inner.session_id,
                    "step_index": self_inner.step_index,
                    "ts_utc": self_inner.ts_utc,
                    "v907_pin": self_inner.v907_pin,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            if drift_after_first_call and state["call_count"] > 3:
                # The first three calls (PRE-baseline) are clean; the
                # next three (POST recomputation) are salted.
                payload += b"DRIFT"
            return payload

    mod.EngineeringOutputEvent = EngineeringOutputEvent  # type: ignore[attr-defined]
    mod.ENGINEERING_OUTPUT_SCHEMA = "wakir.persona.engineering-output/1"  # type: ignore[attr-defined]
    return mod


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface() -> None:
    """The smoke module loads from its hyphenated path and exports __all__."""
    expected_exports = {
        "BRIDGE_AUDIT_DETERMINISTIC_EMISSIONS",
        "COMPONENT_TO_ENV",
        "DEFAULT_BOOTS_PER_PHASE",
        "DEFAULT_BRIDGE_AUDIT_STREAM_FIXTURE_RELPATH",
        "DEFAULT_EXPECTED_COMPONENTS",
        "DEFAULT_LATENCY_TOLERANCE_PCT",
        "ENGINE_BOOT_COMPONENTS",
        "ENVELOPE_SCHEMA",
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
        "boot_engine_once",
        "build_argparser",
        "build_envelope",
        "build_phase_env",
        "capture_bridge_audit_stream_baseline",
        "derive_exit_code",
        "evaluate_bridge_audit_stream_parity",
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
    assert SMOKE.FOCUS_COMPONENT == "bridge_audit_writer"
    assert SMOKE.FOCUS_ENV_VAR == "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND"
    assert SMOKE.EXIT_GREEN == 0
    assert SMOKE.EXIT_CAUTION == 1
    assert SMOKE.EXIT_ROLLBACK == 2
    assert SMOKE.ENVELOPE_SCHEMA == "wakir.phase-3c.welle-3-cutover-smoke/1"
    assert SMOKE.DEFAULT_EXPECTED_COMPONENTS == 9


def test_engine_boot_components_includes_bridge_audit_writer() -> None:
    """Bridge-audit-writer must be in ENGINE_BOOT_COMPONENTS as the 10th
    (Welle-3 substrate inventory at baseline 2ec0532 + Reza-Tag-36
    wire-in target).
    """
    components = SMOKE.ENGINE_BOOT_COMPONENTS
    assert components[-1] == "bridge_audit_writer"
    assert len(components) == 10
    # Baseline-9 inventory is preserved (Welle-2 + earlier waves).
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
    ):
        assert must_have in components, must_have


def test_build_phase_env_pre_sets_all_python() -> None:
    """Pre-Cutover phase: every Phase-3c env-var is explicitly 'python'."""
    env = SMOKE.build_phase_env(SMOKE.PHASE_PRE)
    assert env[SMOKE.FOCUS_ENV_VAR] == "python"
    for env_var in SMOKE.COMPONENT_TO_ENV.values():
        assert env[env_var] == "python", env_var


def test_build_phase_env_post_flips_focus_to_rust() -> None:
    """Cutover phase: bridge-audit-writer env-var is 'rust', others 'python'."""
    env = SMOKE.build_phase_env(SMOKE.PHASE_POST)
    assert env[SMOKE.FOCUS_ENV_VAR] == "rust"
    for component, env_var in SMOKE.COMPONENT_TO_ENV.items():
        if component == SMOKE.FOCUS_COMPONENT:
            assert env[env_var] == "rust"
        else:
            assert env[env_var] == "python", env_var


def test_build_phase_env_rollback_removes_focus_env_var() -> None:
    """Rollback phase: focus env-var is absent from the env-map."""
    env = SMOKE.build_phase_env(SMOKE.PHASE_ROLLBACK)
    assert SMOKE.FOCUS_ENV_VAR not in env
    for component, env_var in SMOKE.COMPONENT_TO_ENV.items():
        if component == SMOKE.FOCUS_COMPONENT:
            continue
        assert env[env_var] == "python", env_var


def test_run_cutover_smoke_green_path_exits_zero() -> None:
    """Default config + clean resolver → all asserts pass → exit GREEN.

    Default ``expected_components=9`` matches the Reza-Tag-36-pending
    state. With ``components=10`` boots, A4 would fail; the test
    passes ``expected_components=10`` to match the smoke's full
    inventory.
    """
    resolver = build_stub_resolver_module()
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        now_ts=1_700_000_000,
        skip_bridge_audit_stream_parity=True,
        expected_components=10,  # matches ENGINE_BOOT_COMPONENTS length
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    assert envelope["band"] == "GREEN"
    assert envelope["schema"] == "wakir.phase-3c.welle-3-cutover-smoke/1"
    assert envelope["welle"] == 3
    assert envelope["focus_component"] == "bridge_audit_writer"
    assert envelope["timestamp_utc"] == 1_700_000_000
    # All blocker asserts pass; A6 is skipped (caution, passed=True);
    # A7 is also skipped (no baseline because A6 was skipped).
    for name, record in envelope["asserts"].items():
        assert record["passed"], (name, record)
    assert envelope["asserts"]["A6_bridge_audit_stream_parity"]["skipped"] is True
    assert envelope["asserts"]["A7_self_reference_trap_control"]["skipped"] is True


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
        skip_bridge_audit_stream_parity=True,
        expected_components=10,
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


def test_run_cutover_smoke_rollback_on_fallback() -> None:
    """Resolver falls back to python on rust-request → A5 + A1 fail → ROLLBACK."""
    resolver = build_stub_resolver_module(
        StubResolverConfig(fallback_on_rust=True)
    )
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        skip_bridge_audit_stream_parity=True,
        expected_components=10,
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
        skip_bridge_audit_stream_parity=True,
        expected_components=10,
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
        skip_bridge_audit_stream_parity=True,
        expected_components=10,
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
            "10",
            "--output",
            str(out_file),
            "--now",
            "1700000001",
            "--skip-bridge-audit-stream-parity",
        ],
        stdout=stdout,
        stderr=stderr,
        resolver_module=resolver,
    )
    assert rc == SMOKE.EXIT_GREEN, stderr.getvalue()
    assert out_file.is_file()
    rendered = out_file.read_text(encoding="utf-8")
    envelope = json.loads(rendered)
    assert envelope["schema"] == "wakir.phase-3c.welle-3-cutover-smoke/1"
    assert envelope["boots_per_phase"] == 3
    assert envelope["timestamp_utc"] == 1700000001
    assert envelope["exit_code"] == SMOKE.EXIT_GREEN
    assert envelope["welle"] == 3
    assert stdout.getvalue() == ""


def test_a6_bridge_audit_stream_parity_green_with_stub_writer() -> None:
    """A6 substrate-parity green when writer module is byte-stable."""
    resolver = build_stub_resolver_module()
    writer = build_stub_bridge_audit_writer_module()
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        bridge_audit_writer_module=writer,
        expected_components=10,
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a6 = envelope["asserts"]["A6_bridge_audit_stream_parity"]
    assert a6["passed"] is True
    assert a6["skipped"] is False
    assert a6["severity"] == "caution"
    assert a6["match"] is True
    assert a6["baseline_stream_sha256"] is not None
    assert a6["recomputed_stream_sha256"] == a6["baseline_stream_sha256"]
    # A7 confirms the baseline was captured in PHASE_PRE.
    a7 = envelope["asserts"]["A7_self_reference_trap_control"]
    assert a7["passed"] is True
    assert a7["captured_at_phase"] == SMOKE.PHASE_PRE
    assert a7["expected_phase"] == SMOKE.PHASE_PRE
    # The envelope's self_reference_trap_mitigation block confirms
    # the operator-facing temporal anchor.
    mitigation = envelope["self_reference_trap_mitigation"]
    assert mitigation["baseline_captured_at_phase"] == SMOKE.PHASE_PRE
    assert mitigation["baseline_skipped"] is False
    assert mitigation["baseline_stream_sha256"] is not None


def test_a6_bridge_audit_stream_parity_caution_on_drift() -> None:
    """A6 drift between baseline + recompute → CAUTION exit, A7 still green.

    The stub writer salts its output after the first 3 emissions
    (the baseline-capture set). The next 3 emissions (the post-
    cutover recomputation) produce different JCS bytes, causing a
    hash mismatch in A6. A1..A5 + R1 + A7 all stay green because the
    engine-emission substance is intact and the baseline was still
    captured in PHASE_PRE.
    """
    resolver = build_stub_resolver_module()
    writer = build_stub_bridge_audit_writer_module(drift_after_first_call=True)
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        bridge_audit_writer_module=writer,
        expected_components=10,
    )
    assert exit_code == SMOKE.EXIT_CAUTION, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a6 = envelope["asserts"]["A6_bridge_audit_stream_parity"]
    assert a6["passed"] is False
    assert a6["skipped"] is False
    assert a6["match"] is False
    assert a6["baseline_stream_sha256"] != a6["recomputed_stream_sha256"]
    # A1..A5 + R1 all still pass — engine-emission substance intact.
    assert envelope["asserts"]["A1_backend_flip"]["passed"]
    assert envelope["asserts"]["A2_cross_lang_parity_hash"]["passed"]
    assert envelope["asserts"]["A3_latency_within_tolerance"]["passed"]
    assert envelope["asserts"]["A4_decision_count_in_place"]["passed"]
    assert envelope["asserts"]["A5_fallback_clean"]["passed"]
    assert envelope["asserts"]["R1_rollback_to_python"]["passed"]
    # A7 stays green: the temporal invariant (baseline captured in
    # PHASE_PRE) is intact; the drift is in the encoder, not in
    # *when* the baseline was captured.
    assert envelope["asserts"]["A7_self_reference_trap_control"]["passed"]


def test_a7_self_reference_trap_control_blocks_post_phase_capture() -> None:
    """A7 fires + ROLLBACK when baseline captured_at_phase != PHASE_PRE.

    Regression-trap: if a future refactor accidentally captures the
    baseline from a post-cutover phase, the A7 control-flow invariant
    must fire and push the exit-code to ROLLBACK. We simulate the
    bad refactor by injecting a baseline with
    ``captured_at_phase=PHASE_POST`` and asserting that A7 flags it.
    """
    resolver = build_stub_resolver_module()

    # Inject a baseline that pretends to have been captured during
    # PHASE_POST — the exact regression A7 must catch.
    bad_baseline = {
        "passed": True,
        "skipped": False,
        "severity": "caution",
        "detail": "synthetic post-phase baseline for A7 regression-test",
        "stream_sha256_hex": "f" * 64,
        "per_emission_jcs_sha256": ["f" * 64],
        "emission_count": 1,
        "captured_at_phase": SMOKE.PHASE_POST,  # the bug
    }

    def _bad_baseline_fn() -> Dict[str, Any]:
        return bad_baseline

    # Build a writer module that returns matching bytes so A6 stays
    # green; the only failure should be A7.
    writer = build_stub_bridge_audit_writer_module()

    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        bridge_audit_writer_module=writer,
        bridge_audit_baseline_fn=_bad_baseline_fn,
        expected_components=10,
    )

    # A7 is a blocker → exit_code must be ROLLBACK.
    assert exit_code == SMOKE.EXIT_ROLLBACK, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a7 = envelope["asserts"]["A7_self_reference_trap_control"]
    assert a7["passed"] is False
    assert a7["severity"] == "blocker"
    assert a7["captured_at_phase"] == SMOKE.PHASE_POST
    assert a7["expected_phase"] == SMOKE.PHASE_PRE
    # The envelope's self_reference_trap_mitigation block surfaces
    # the bug for the operator.
    mitigation = envelope["self_reference_trap_mitigation"]
    assert mitigation["baseline_captured_at_phase"] == SMOKE.PHASE_POST


def test_resolver_shim_used_when_upstream_resolver_missing() -> None:
    """Smoke uses the local shim when upstream resolver is not present.

    Mimics the Reza-Tag-36-wire-in-pending state: the resolver module
    exposes the env-var constant and bin-resolver but no
    ``resolve_bridge_audit_writer_backend`` function. The smoke must
    transparently fall back to the local shim, mark the provenance
    as ``"shim"``, and still emit a green envelope (all other
    components are upstream).
    """
    cfg = StubResolverConfig()
    module = build_stub_resolver_module(cfg)
    # Surgically remove the upstream resolve_* function for the focus
    # component so the smoke is forced onto the shim.
    delattr(module, "resolve_bridge_audit_writer_backend")
    # Provide the shim's prerequisites on the module.
    module.BRIDGE_AUDIT_WRITER_BACKEND_ENV = SMOKE.FOCUS_ENV_VAR  # type: ignore[attr-defined]

    def _resolve_bridge_audit_writer_bin(
        env: Optional[Mapping[str, str]] = None,
    ) -> str:
        return "/opt/wakir/bin/wakir-persona-engine-bridge-audit-writer"

    def _binary_available(_bin_path: str) -> Tuple[bool, Optional[str]]:
        return True, None

    module._resolve_bridge_audit_writer_bin = (  # type: ignore[attr-defined]
        _resolve_bridge_audit_writer_bin
    )
    module._binary_available = _binary_available  # type: ignore[attr-defined]

    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=module,
        binary_probe=lambda _p: (True, None),
        skip_bridge_audit_stream_parity=True,
        expected_components=10,
    )
    # The shim takes over for the focus-component only — all other
    # components remain upstream.
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    provenance = envelope["resolver_provenance"]
    assert provenance["bridge_audit_writer"] == SMOKE.RESOLVER_PROVENANCE_SHIM
    # Spot-check that other components are upstream.
    assert provenance["v907_verify"] == SMOKE.RESOLVER_PROVENANCE_UPSTREAM
    assert provenance["svid_workload_identity"] == SMOKE.RESOLVER_PROVENANCE_UPSTREAM
    # The shim's output must still satisfy A1: chosen_backend == rust
    # in the post-cutover phase.
    post_decisions = envelope["phases"][SMOKE.PHASE_POST]
    assert post_decisions["focus_p95_latency_us"] >= 0
    assert envelope["asserts"]["A1_backend_flip"]["passed"]
