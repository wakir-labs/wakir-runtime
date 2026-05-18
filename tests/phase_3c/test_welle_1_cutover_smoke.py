# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/phase-3c/welle-1-v907-verify-cutover-smoke.py.

Hermetic, stdlib-only. The smoke module is loaded via importlib from
its hyphenated path under ``scripts/phase-3c/``. The resolver dep is
exercised through a stub module so the tests never import the real
wirelang package, and every test injects ``resolver_module`` +
``binary_probe`` explicitly so no filesystem access happens.

Scope (10 tests, exceeds Auftrag-Tag-34 minimum of 8)
-----------------------------------------------------

1.  test_module_loads_and_exports_public_surface
2.  test_build_phase_env_pre_sets_all_python
3.  test_build_phase_env_post_flips_focus_to_rust
4.  test_build_phase_env_rollback_removes_focus_env_var
5.  test_run_cutover_smoke_green_path_exits_zero
6.  test_run_cutover_smoke_caution_on_latency_blowup
7.  test_run_cutover_smoke_rollback_on_fallback
8.  test_run_cutover_smoke_rollback_when_post_stays_python
9.  test_run_cutover_smoke_rollback_when_rollback_phase_stays_rust
10. test_main_cli_writes_envelope_and_returns_exit_code
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import types
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Smoke-module loader — handles the hyphenated path.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Locate the wakir-runtime repo root from this test file."""
    here = Path(__file__).resolve()
    # tests/phase_3c/test_welle_1_cutover_smoke.py → repo root is two up.
    return here.parent.parent.parent


def _load_smoke_module() -> Any:
    """Load the cutover-smoke module from its hyphenated path."""
    smoke_path = (
        _repo_root()
        / "scripts"
        / "phase-3c"
        / "welle-1-v907-verify-cutover-smoke.py"
    )
    if not smoke_path.is_file():
        pytest.fail(f"smoke script not found at {smoke_path}")
    spec = importlib.util.spec_from_file_location(
        "welle_1_v907_verify_cutover_smoke", str(smoke_path)
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build spec for {smoke_path}")
    module = importlib.util.module_from_spec(spec)
    # Register the module in sys.modules so `dataclasses.asdict`
    # and `importlib.import_module` lookups inside the loaded module
    # behave normally.
    sys.modules["welle_1_v907_verify_cutover_smoke"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


SMOKE = _load_smoke_module()


# ---------------------------------------------------------------------------
# Stub BackendDecision + stub resolver module — mirrors the production
# rust_backend_switch.BackendDecision shape without importing wirelang.
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

    #: When True, the focus-component resolver returns RUST even if the
    #: env-var says PYTHON. Used to simulate the rollback-failure case.
    force_rust_on_rollback: bool = False
    #: When True, the resolver claims a fallback (binary missing) on
    #: the cutover path. Used to simulate A5 fallback-dirty.
    fallback_on_rust: bool = False
    #: P95-latency injection: focus-component reports this latency on
    #: the cutover (rust) path. Default 50 µs — the ADR-0065 §AC-2
    #: expectation is "Rust ~30-50% faster than Python", so the
    #: GREEN-path stub sets Rust < Python so the latency assert
    #: passes cleanly.
    rust_focus_latency_us: int = 50
    #: P95-latency on the python path. Default 100 µs (higher than
    #: the rust path, matching the ADR-0065 §AC-2 expectation).
    python_focus_latency_us: int = 100
    #: Drop the focus-component entirely on the cutover. Used to
    #: simulate A4 decision-count drift.
    drop_focus_on_rust: bool = False
    #: Force focus-component to stay python even when env=rust. Used
    #: to simulate A1 backend-flip failure.
    pin_focus_to_python: bool = False


def build_stub_resolver_module(
    config: Optional[StubResolverConfig] = None,
) -> types.ModuleType:
    """Build a fake rust_backend_switch module wired by the StubResolverConfig.

    The smoke calls ``resolve_<component>_backend(env=..., log_sink=...,
    binary_probe=...)`` for each in-place component, expecting a
    ``(backend, BackendDecision)`` tuple. The stub honours the env-var
    per component and applies the StubResolverConfig overrides for
    the focus-component to script failure scenarios.
    """
    cfg = config or StubResolverConfig()
    module = types.ModuleType("wirelang.persona_engine.rust_backend_switch")

    # Per-component env-var (mirrors the smoke's COMPONENT_TO_ENV).
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
                # Focus-component honours all StubResolverConfig knobs.
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
                    # Python path on focus.
                    if cfg.force_rust_on_rollback and env_var not in env_map:
                        # Rollback-phase signal: env-var absent.
                        chosen = "rust"
                        fallback_reason = "test_force_rust_on_rollback"
                    else:
                        chosen = "python"
                    latency_us = cfg.python_focus_latency_us
            else:
                # Other components: simple python/rust echo (no failure
                # scenarios needed for the smoke's focus-only asserts).
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
            # Test: drop focus on rust to break A4. We do this by
            # making the resolver raise on the rust path so the smoke
            # detects an empty/short decision list. But the smoke
            # currently relies on the resolver always returning — to
            # cleanly model "engine dropped this component", we
            # instead emit a decision whose domain is *different*
            # from focus, which makes _focus_records return an empty
            # list for that boot's focus slice.
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
                # Emit under a wrong domain to simulate the engine
                # dropping the focus component. _focus_records() will
                # then exclude these.
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
# Tests.
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface() -> None:
    """The smoke module loads from its hyphenated path and exports __all__."""
    expected_exports = {
        "COMPONENT_TO_ENV",
        "DEFAULT_BOOTS_PER_PHASE",
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
        "boot_engine_once",
        "build_argparser",
        "build_envelope",
        "build_phase_env",
        "derive_exit_code",
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
    assert SMOKE.FOCUS_COMPONENT == "v907_verify"
    assert SMOKE.FOCUS_ENV_VAR == "WAKIR_V907_VERIFY_BACKEND"
    assert SMOKE.EXIT_GREEN == 0
    assert SMOKE.EXIT_CAUTION == 1
    assert SMOKE.EXIT_ROLLBACK == 2
    assert SMOKE.ENVELOPE_SCHEMA == "wakir.phase-3c.welle-1-cutover-smoke/1"


def test_build_phase_env_pre_sets_all_python() -> None:
    """Pre-Cutover phase: every Phase-3c env-var is explicitly 'python'."""
    env = SMOKE.build_phase_env(SMOKE.PHASE_PRE)
    assert env[SMOKE.FOCUS_ENV_VAR] == "python"
    for env_var in SMOKE.COMPONENT_TO_ENV.values():
        assert env[env_var] == "python", env_var


def test_build_phase_env_post_flips_focus_to_rust() -> None:
    """Cutover phase: focus env-var is 'rust', all others stay 'python'."""
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
    # Other components still pinned to python (deterministic baseline).
    for component, env_var in SMOKE.COMPONENT_TO_ENV.items():
        if component == SMOKE.FOCUS_COMPONENT:
            continue
        assert env[env_var] == "python", env_var


def test_run_cutover_smoke_green_path_exits_zero() -> None:
    """Default config + clean resolver → all asserts pass → exit GREEN."""
    resolver = build_stub_resolver_module()
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        now_ts=1_700_000_000,
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    assert envelope["band"] == "GREEN"
    assert envelope["schema"] == "wakir.phase-3c.welle-1-cutover-smoke/1"
    assert envelope["welle"] == 1
    assert envelope["focus_component"] == "v907_verify"
    assert envelope["timestamp_utc"] == 1_700_000_000
    # All asserts passed.
    for name, record in envelope["asserts"].items():
        assert record["passed"], (name, record)


def test_run_cutover_smoke_caution_on_latency_blowup() -> None:
    """Latency 10× baseline → A3 caution → exit CAUTION."""
    cfg = SMOKE.DEFAULT_LATENCY_TOLERANCE_PCT
    resolver = build_stub_resolver_module(
        StubResolverConfig(
            python_focus_latency_us=100,
            rust_focus_latency_us=100_000,  # 1000× baseline
        )
    )
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        latency_tolerance_pct=cfg,
    )
    assert exit_code == SMOKE.EXIT_CAUTION, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    assert envelope["band"] == "CAUTION"
    # A1/A2/A5/R1 still pass; A3 is the failure.
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
    )
    assert exit_code == SMOKE.EXIT_ROLLBACK, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    assert envelope["band"] == "ROLLBACK_RECOMMENDED"
    # A1 fails (chosen_backend stayed python), A5 fails (fallback_reason set).
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
            "--output",
            str(out_file),
            "--now",
            "1700000001",
        ],
        stdout=stdout,
        stderr=stderr,
        resolver_module=resolver,
    )
    assert rc == SMOKE.EXIT_GREEN, stderr.getvalue()
    assert out_file.is_file()
    rendered = out_file.read_text(encoding="utf-8")
    envelope = json.loads(rendered)
    assert envelope["schema"] == "wakir.phase-3c.welle-1-cutover-smoke/1"
    assert envelope["boots_per_phase"] == 3
    assert envelope["timestamp_utc"] == 1700000001
    assert envelope["exit_code"] == SMOKE.EXIT_GREEN
    # stdout stays empty when --output is provided.
    assert stdout.getvalue() == ""
