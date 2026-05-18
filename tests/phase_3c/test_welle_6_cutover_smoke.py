# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py.

Hermetic, stdlib-only. The smoke module is loaded via importlib
from its hyphenated path under ``scripts/phase-3c/``. The resolver
dep is exercised through a stub module so the tests never import
the real wirelang package, and every test injects
``resolver_module`` + ``binary_probe`` explicitly so no filesystem
access happens.

Scope (15 tests; Auftrag-Tag-39 minimum is 12 — exceeded so the
Welle-6-specific edges (A6 byte-drift, A6 lag-distribution drift,
A7 recovery-leak, shim path for trailing component, custom
expected-components, hermetic-env-construction with FSM-pin) get
explicit per-axis coverage)
--------------------------------------------------------------------

1.  test_module_loads_and_exports_public_surface
2.  test_engine_boot_components_includes_subscribe_loop_and_partners
3.  test_build_phase_env_pre_sets_all_python_except_fsm
4.  test_build_phase_env_post_flips_focus_to_rust
5.  test_build_phase_env_rollback_removes_focus_env_var
6.  test_deterministic_lag_samples_have_expected_shape
7.  test_run_cutover_smoke_green_path_exits_zero
8.  test_run_cutover_smoke_caution_on_latency_blowup
9.  test_run_cutover_smoke_rollback_on_fallback
10. test_run_cutover_smoke_rollback_when_post_stays_python
11. test_run_cutover_smoke_rollback_when_rollback_phase_stays_rust
12. test_main_cli_writes_envelope_and_returns_exit_code
13. test_a6_lag_stability_green_with_stub_canonical
14. test_a6_lag_stability_caution_on_byte_drift
15. test_a7_cross_modul_drift_to_welle_7_recovery_blocks_on_leak
16. test_resolver_shim_used_when_bridge_audit_diff_engine_upstream_missing
17. test_fsm_post_cutover_state_reports_rust_default
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
        / "welle-6-subscribe-loop-cutover-smoke.py"
    )
    if not smoke_path.is_file():
        pytest.fail(f"smoke script not found at {smoke_path}")
    spec = importlib.util.spec_from_file_location(
        "welle_6_subscribe_loop_cutover_smoke", str(smoke_path)
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build spec for {smoke_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["welle_6_subscribe_loop_cutover_smoke"] = module
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
    # Welle-6 specific: simulate recovery cross-modul-drift leak.
    recovery_leaks_to_rust_on_subscribe_loop_cutover: bool = False


def build_stub_resolver_module(
    config: Optional[StubResolverConfig] = None,
) -> types.ModuleType:
    """Build a fake rust_backend_switch module wired by StubResolverConfig."""
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
            elif component == SMOKE.WELLE_7_PARTNER_COMPONENT:
                if cfg.recovery_leaks_to_rust_on_subscribe_loop_cutover:
                    sl_value = env_map.get(focus_env_var, "")
                    if sl_value == SMOKE.ENV_VALUE_RUST:
                        chosen = "rust"
                        requested = raw if raw else "python"
                        fallback_reason = "test_recovery_cross_modul_leak"
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
        setattr(module, f"resolve_{component}_backend", _make_resolver(component))

    return module


def build_stub_subscribe_ack_module(
    *,
    drift_after_first_call: bool = False,
) -> types.ModuleType:
    """Build a fake subscribe_ack module.

    Exposes:
      * ``SubscribeAckRecord`` — frozen dataclass.
      * ``build_subscribe_ack_record`` — constructor.
      * ``serialize_subscribe_ack`` — JCS-canonical bytes.
      * ``ack_record_sha256_hex`` — hex SHA-256 of the bytes.

    When ``drift_after_first_call`` is True the module salts the
    serialised output after the first two calls (PRE-baseline batch),
    simulating substrate-drift between baseline and recompute.
    """
    mod = types.ModuleType("wirelang.persona_engine.subscribe_ack")
    state = {"call_count": 0}

    @dataclass(frozen=True)
    class SubscribeAckRecord:
        persona_id: str
        org_id: str
        prompt_sha256: str
        frame_index: int
        ts_utc: str
        outcome: str = "processed"
        outcome_reason: Optional[str] = None

    def build_subscribe_ack_record(
        *,
        persona_id: str,
        org_id: str,
        prompt_sha256: str,
        frame_index: int,
        ts_utc: str,
        outcome: str = "processed",
        outcome_reason: Optional[str] = None,
    ) -> SubscribeAckRecord:
        return SubscribeAckRecord(
            persona_id=persona_id,
            org_id=org_id,
            prompt_sha256=prompt_sha256,
            frame_index=frame_index,
            ts_utc=ts_utc,
            outcome=outcome,
            outcome_reason=outcome_reason,
        )

    def serialize_subscribe_ack(record: SubscribeAckRecord) -> bytes:
        state["call_count"] += 1
        canonical = {
            "frame_index": record.frame_index,
            "org_id": record.org_id,
            "outcome": record.outcome,
            "persona_id": record.persona_id,
            "prompt_sha256": record.prompt_sha256,
            "ts_utc": record.ts_utc,
        }
        if record.outcome_reason is not None:
            canonical["outcome_reason"] = record.outcome_reason
        payload = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        if drift_after_first_call and state["call_count"] > 2:
            # Smoke calls serialize twice per pass (direct + via
            # sha256_hex). Drift kicks in for the post-cutover pass.
            payload += b"DRIFT"
        return payload

    def ack_record_sha256_hex(record: SubscribeAckRecord) -> str:
        return hashlib.sha256(serialize_subscribe_ack(record)).hexdigest()

    mod.SubscribeAckRecord = SubscribeAckRecord  # type: ignore[attr-defined]
    mod.build_subscribe_ack_record = build_subscribe_ack_record  # type: ignore[attr-defined]
    mod.serialize_subscribe_ack = serialize_subscribe_ack  # type: ignore[attr-defined]
    mod.ack_record_sha256_hex = ack_record_sha256_hex  # type: ignore[attr-defined]
    return mod


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface() -> None:
    expected_exports = {
        "COMPONENT_TO_ENV",
        "DEFAULT_BOOTS_PER_PHASE",
        "DEFAULT_EXPECTED_COMPONENTS",
        "DEFAULT_LAG_DISTRIBUTION_DRIFT_PCT",
        "DEFAULT_LATENCY_TOLERANCE_PCT",
        "DETERMINISTIC_ACK_AUFTRAG_ID",
        "DETERMINISTIC_ACK_FRAME_INDEX",
        "DETERMINISTIC_ACK_ORG_ID",
        "DETERMINISTIC_ACK_OUTCOME",
        "DETERMINISTIC_ACK_PERSONA_ID",
        "DETERMINISTIC_ACK_PROMPT_SHA256",
        "DETERMINISTIC_ACK_SUBJECT",
        "DETERMINISTIC_ACK_TS_UTC",
        "DETERMINISTIC_LAG_SAMPLES_SEC",
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
        "WELLE_7_PARTNER_COMPONENT",
        "WELLE_7_PARTNER_ENV_VAR",
        "boot_engine_once",
        "build_argparser",
        "build_envelope",
        "build_phase_env",
        "capture_lag_stability_baseline_default",
        "derive_exit_code",
        "evaluate_fsm_post_cutover_state",
        "evaluate_lag_stability_parity",
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
    assert SMOKE.FOCUS_COMPONENT == "subscribe_loop"
    assert SMOKE.FOCUS_COMPONENT_LONG == "subscribe_loop"
    assert SMOKE.FOCUS_ENV_VAR == "WAKIR_SUBSCRIBE_LOOP_BACKEND"
    assert SMOKE.EXIT_GREEN == 0
    assert SMOKE.EXIT_CAUTION == 1
    assert SMOKE.EXIT_ROLLBACK == 2
    assert SMOKE.ENVELOPE_SCHEMA == "wakir.phase-3c.welle-6-cutover-smoke/1"
    assert SMOKE.DEFAULT_EXPECTED_COMPONENTS == 11
    assert SMOKE.ENV_VALUE_PYTHON == "python"
    assert SMOKE.ENV_VALUE_RUST == "rust"
    assert SMOKE.WELLE_7_PARTNER_COMPONENT == "recovery"
    assert SMOKE.WELLE_7_PARTNER_ENV_VAR == "WAKIR_RECOVERY_BACKEND"
    assert SMOKE.FSM_POST_KW26_COMPONENT == "fsm"
    assert SMOKE.FSM_POST_KW26_ENV_VAR == "WAKIR_FSM_BACKEND"
    assert SMOKE.FSM_POST_KW26_BACKEND == "rust"


def test_engine_boot_components_includes_subscribe_loop_and_partners() -> None:
    components = SMOKE.ENGINE_BOOT_COMPONENTS
    assert "subscribe_loop" in components
    assert "recovery" in components, (
        "Welle-7 partner recovery must be in engine inventory"
    )
    assert "fsm" in components, (
        "FSM-Awareness partner fsm must be in engine inventory"
    )
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


def test_build_phase_env_pre_sets_all_python_except_fsm() -> None:
    """Pre-Cutover phase: every env-var is 'python' EXCEPT fsm which
    is pinned to 'rust' (FSM-Awareness, post-KW-26 production state)."""
    env = SMOKE.build_phase_env(SMOKE.PHASE_PRE)
    assert env[SMOKE.FOCUS_ENV_VAR] == "python"
    assert env[SMOKE.WELLE_7_PARTNER_ENV_VAR] == "python"
    # FSM pinned to rust per FSM-Awareness.
    assert env[SMOKE.FSM_POST_KW26_ENV_VAR] == "rust"
    for component, env_var in SMOKE.COMPONENT_TO_ENV.items():
        if component == SMOKE.FSM_POST_KW26_COMPONENT:
            assert env[env_var] == "rust", env_var
        else:
            assert env[env_var] == "python", env_var


def test_build_phase_env_post_flips_focus_to_rust() -> None:
    """Cutover phase: subscribe_loop env-var is 'rust'; partner stays
    at python; FSM stays at rust (post-KW-26 production state)."""
    env = SMOKE.build_phase_env(SMOKE.PHASE_POST)
    assert env[SMOKE.FOCUS_ENV_VAR] == "rust"
    assert env[SMOKE.WELLE_7_PARTNER_ENV_VAR] == "python"
    assert env[SMOKE.FSM_POST_KW26_ENV_VAR] == "rust"
    for component, env_var in SMOKE.COMPONENT_TO_ENV.items():
        if component == SMOKE.FOCUS_COMPONENT:
            assert env[env_var] == "rust"
        elif component == SMOKE.FSM_POST_KW26_COMPONENT:
            assert env[env_var] == "rust"
        else:
            assert env[env_var] == "python", env_var

    with pytest.raises(ValueError, match="unknown phase"):
        SMOKE.build_phase_env("not_a_phase")


def test_build_phase_env_rollback_removes_focus_env_var() -> None:
    """Rollback phase: focus env-var is absent from the env-map; FSM
    stays pinned to rust."""
    env = SMOKE.build_phase_env(SMOKE.PHASE_ROLLBACK)
    assert SMOKE.FOCUS_ENV_VAR not in env
    assert env[SMOKE.WELLE_7_PARTNER_ENV_VAR] == "python"
    assert env[SMOKE.FSM_POST_KW26_ENV_VAR] == "rust"
    for component, env_var in SMOKE.COMPONENT_TO_ENV.items():
        if component == SMOKE.FOCUS_COMPONENT:
            continue
        if component == SMOKE.FSM_POST_KW26_COMPONENT:
            assert env[env_var] == "rust"
            continue
        assert env[env_var] == "python", env_var


def test_deterministic_lag_samples_have_expected_shape() -> None:
    """Deterministic lag fixture must have 12 samples bracketing the
    sub-millisecond histogram bucket spec."""
    samples = SMOKE.DETERMINISTIC_LAG_SAMPLES_SEC
    assert len(samples) == 12
    # All samples sub-second.
    for s in samples:
        assert 0.0 < s < 1.0, s
    # Monotonically non-decreasing (deterministic shape).
    for prev, curr in zip(samples, samples[1:]):
        assert prev <= curr


def test_run_cutover_smoke_green_path_exits_zero() -> None:
    """Default config + clean resolver → all asserts pass → exit GREEN."""
    resolver = build_stub_resolver_module()
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        now_ts=1_700_000_000,
        skip_lag_stability_parity=True,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    assert envelope["band"] == "GREEN"
    assert envelope["schema"] == "wakir.phase-3c.welle-6-cutover-smoke/1"
    assert envelope["welle"] == 6
    assert envelope["focus_component"] == "subscribe_loop"
    assert envelope["focus_component_long"] == "subscribe_loop"
    assert envelope["timestamp_utc"] == 1_700_000_000
    for name, record in envelope["asserts"].items():
        assert record["passed"], (name, record)
    assert envelope["asserts"]["A6_subscribe_loop_lag_stability"]["skipped"] is True
    a7 = envelope["asserts"]["A7_cross_modul_drift_welle_7_recovery"]
    assert a7["passed"] is True
    assert a7["skipped"] is False
    assert a7["recovery_chosen_backends"] == ["python"]
    # FSM-Awareness surfaces the expected post-KW-26 state.
    fsm_state = envelope["fsm_post_cutover_state"]
    assert fsm_state["fsm_in_expected_post_kw26_state"] is True
    assert fsm_state["fsm_chosen_backends"] == ["rust"]


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
        skip_lag_stability_parity=True,
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
    assert envelope["asserts"]["A7_cross_modul_drift_welle_7_recovery"]["passed"]


def test_run_cutover_smoke_rollback_on_fallback() -> None:
    resolver = build_stub_resolver_module(
        StubResolverConfig(fallback_on_rust=True)
    )
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        skip_lag_stability_parity=True,
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
        skip_lag_stability_parity=True,
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
        skip_lag_stability_parity=True,
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
            "--skip-lag-stability-parity",
        ],
        stdout=stdout,
        stderr=stderr,
        resolver_module=resolver,
    )
    assert rc == SMOKE.EXIT_GREEN, stderr.getvalue()
    assert out_file.is_file()
    rendered = out_file.read_text(encoding="utf-8")
    envelope = json.loads(rendered)
    assert envelope["schema"] == "wakir.phase-3c.welle-6-cutover-smoke/1"
    assert envelope["boots_per_phase"] == 3
    assert envelope["timestamp_utc"] == 1700000001
    assert envelope["exit_code"] == SMOKE.EXIT_GREEN
    assert envelope["welle"] == 6
    assert envelope["focus_component"] == "subscribe_loop"
    assert stdout.getvalue() == ""


def test_a6_lag_stability_green_with_stub_canonical() -> None:
    """A6 lag-stability green when subscribe_ack module is byte-stable."""
    resolver = build_stub_resolver_module()
    canonical = build_stub_subscribe_ack_module()
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        canonical_module=canonical,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a6 = envelope["asserts"]["A6_subscribe_loop_lag_stability"]
    assert a6["passed"] is True
    assert a6["skipped"] is False
    assert a6["severity"] == "caution"
    assert a6["match"] is True
    assert a6["baseline_ack_record_sha256"] is not None
    assert a6["recomputed_ack_record_sha256"] == a6["baseline_ack_record_sha256"]
    assert a6["lag_drift_within_envelope"] is True
    # The envelope's lag_stability block confirms the operator-facing
    # temporal anchor.
    lag = envelope["lag_stability"]
    assert lag["baseline_captured_at_phase"] == SMOKE.PHASE_PRE
    assert lag["baseline_skipped"] is False
    assert lag["baseline_ack_record_sha256"] is not None
    assert lag["drift_pct"] == 25
    assert lag["lag_sample_count"] == 12
    # A7 cross-modul-drift remains green.
    a7 = envelope["asserts"]["A7_cross_modul_drift_welle_7_recovery"]
    assert a7["passed"] is True


def test_a6_lag_stability_caution_on_byte_drift() -> None:
    """A6 byte-drift between baseline + recompute → CAUTION exit."""
    resolver = build_stub_resolver_module()
    canonical = build_stub_subscribe_ack_module(drift_after_first_call=True)
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        canonical_module=canonical,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_CAUTION, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a6 = envelope["asserts"]["A6_subscribe_loop_lag_stability"]
    assert a6["passed"] is False
    assert a6["skipped"] is False
    assert a6["match"] is False
    assert a6["baseline_ack_record_sha256"] != a6["recomputed_ack_record_sha256"]
    # A1..A5 + R1 + A7 all still pass — engine-emission substance intact.
    assert envelope["asserts"]["A1_backend_flip"]["passed"]
    assert envelope["asserts"]["A2_cross_lang_parity_hash"]["passed"]
    assert envelope["asserts"]["A3_latency_within_tolerance"]["passed"]
    assert envelope["asserts"]["A4_decision_count_in_place"]["passed"]
    assert envelope["asserts"]["A5_fallback_clean"]["passed"]
    assert envelope["asserts"]["R1_rollback_to_python"]["passed"]
    assert envelope["asserts"]["A7_cross_modul_drift_welle_7_recovery"]["passed"]


def test_a7_cross_modul_drift_to_welle_7_recovery_blocks_on_leak() -> None:
    """A7 fires + ROLLBACK when recovery leaks to rust in PHASE_POST."""
    cfg = StubResolverConfig(
        recovery_leaks_to_rust_on_subscribe_loop_cutover=True
    )
    resolver = build_stub_resolver_module(cfg)
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        skip_lag_stability_parity=True,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_ROLLBACK, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a7 = envelope["asserts"]["A7_cross_modul_drift_welle_7_recovery"]
    assert a7["passed"] is False
    assert a7["severity"] == "blocker"
    assert "rust" in a7["recovery_chosen_backends"]
    assert a7["expected_recovery_backend"] == "python"
    assert "leaked into recovery path" in a7["detail"]
    mitigation = envelope["cross_modul_drift_mitigation"]
    assert mitigation["welle_7_partner_component"] == "recovery"
    assert mitigation["welle_7_partner_env_var"] == "WAKIR_RECOVERY_BACKEND"
    assert "rust" in mitigation["recovery_chosen_backends_in_post_phase"]
    assert envelope["asserts"]["A1_backend_flip"]["passed"]
    assert envelope["asserts"]["A5_fallback_clean"]["passed"]
    assert envelope["asserts"]["R1_rollback_to_python"]["passed"]


def test_resolver_shim_used_when_bridge_audit_diff_engine_upstream_missing() -> None:
    """Smoke uses the local shim for bridge_audit_diff_engine when upstream missing."""
    cfg = StubResolverConfig()
    module = build_stub_resolver_module(cfg)
    delattr(module, "resolve_bridge_audit_diff_engine_backend")
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
        skip_lag_stability_parity=True,
        expected_components=11,
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    provenance = envelope["resolver_provenance"]
    assert (
        provenance["bridge_audit_diff_engine"] == SMOKE.RESOLVER_PROVENANCE_SHIM
    )
    assert provenance["subscribe_loop"] == SMOKE.RESOLVER_PROVENANCE_UPSTREAM
    assert provenance["recovery"] == SMOKE.RESOLVER_PROVENANCE_UPSTREAM
    assert provenance["fsm"] == SMOKE.RESOLVER_PROVENANCE_UPSTREAM
    assert envelope["asserts"]["A1_backend_flip"]["passed"]


def test_fsm_post_cutover_state_reports_rust_default() -> None:
    """FSM-Awareness pre-check reports that fsm is in expected
    post-KW-26 state (Welle-5 cutover already complete; fsm pinned
    to rust in the smoke env-map)."""
    resolver = build_stub_resolver_module()
    envelope, _exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        skip_lag_stability_parity=True,
        expected_components=11,
    )
    fsm_state = envelope["fsm_post_cutover_state"]
    assert fsm_state["fsm_in_expected_post_kw26_state"] is True
    assert fsm_state["expected_fsm_backend"] == "rust"
    assert fsm_state["fsm_chosen_backends"] == ["rust"]
    assert "expected post-KW-26 state" in fsm_state["detail"]
