# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py.

Hermetic, stdlib-only. The smoke module is loaded via importlib from
its hyphenated path under ``scripts/phase-3c/``. The resolver dep is
exercised through a stub module so the tests never import the real
wirelang package, and every test injects ``resolver_module`` +
``binary_probe`` explicitly so no filesystem access happens.

Scope (12 tests, exceeds Auftrag-Tag-35 minimum of 10)
------------------------------------------------------

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
11. test_a6_svid_fixture_parity_green_with_stub_canonical
12. test_a6_svid_fixture_parity_caution_on_drift

The first 10 mirror the Welle-1 pattern verbatim (asserts at every
parity-relevant axis); tests 11+12 exercise the SVID-specific A6
substrate-parity assert that distinguishes Welle-2 from Welle-1.
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
        / "welle-2-svid-workload-identity-cutover-smoke.py"
    )
    if not smoke_path.is_file():
        pytest.fail(f"smoke script not found at {smoke_path}")
    spec = importlib.util.spec_from_file_location(
        "welle_2_svid_workload_identity_cutover_smoke", str(smoke_path)
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build spec for {smoke_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["welle_2_svid_workload_identity_cutover_smoke"] = module
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
    the focus-component (svid_workload_identity) to script failure
    scenarios.
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
# Stub SVID-canonical module for A6 tests.
# ---------------------------------------------------------------------------


def build_stub_svid_canonical_module(
    *,
    drift_fixture_name: Optional[str] = None,
) -> types.ModuleType:
    """Build a fake svid_workload_identity_canonical module.

    Exposes ``snapshot_sha256_for_bindings(bindings)`` which returns
    a deterministic SHA-256 over the JSON-serialised bindings list.
    When ``drift_fixture_name`` is set and the bindings list comes
    from a fixture with that name (heuristically: matches a token in
    the bindings' first ``org_id`` field), the helper salts the hash
    so the smoke's A6 detects substrate drift.

    Real wirelang module uses JCS-canonical bytes per
    ``tests/fixtures/svid-workload-cross-lang/fixtures.json``; this
    stub keeps the test hermetic without depending on the real
    wirelang package being importable in the test env. Tests pin the
    baseline hash by computing the stub's output once and writing it
    into a synthetic fixture file in tmp_path.
    """
    mod = types.ModuleType("wirelang.identity.svid_workload_identity_canonical")

    def snapshot_sha256_for_bindings(bindings: Any) -> str:
        payload = json.dumps(bindings, sort_keys=True, separators=(",", ":"))
        salt = ""
        if drift_fixture_name is not None and bindings:
            try:
                if drift_fixture_name in json.dumps(bindings, sort_keys=True):
                    salt = "drift"
            except (TypeError, ValueError):
                salt = ""
        return hashlib.sha256((payload + salt).encode("utf-8")).hexdigest()

    mod.snapshot_sha256_for_bindings = snapshot_sha256_for_bindings  # type: ignore[attr-defined]
    return mod


def _synthetic_svid_fixtures(stub_module: Any) -> Dict[str, Any]:
    """Build a minimal synthetic fixtures.json payload pinned to the stub.

    Two fixtures are enough to exercise A6 happy + drift paths.
    """
    fixtures: List[Dict[str, Any]] = []
    for name, bindings in (
        ("f01-empty-identity-set", []),
        (
            "f02-single-org-single-spiffe",
            [
                {
                    "org_id": "wakir-labs",
                    "persona_id": "mira",
                    "spiffe_id": "spiffe://wakir.wakir-labs/persona/mira",
                    "not_after_utc": "2026-06-18T00:00:00Z",
                    "bind_state_sha256": "sha256:" + ("a" * 64),
                    "expired": False,
                }
            ],
        ),
    ):
        baseline = stub_module.snapshot_sha256_for_bindings(bindings)
        fixtures.append(
            {
                "name": name,
                "input_bindings": bindings,
                "expected": {"snapshot_sha256_hex": baseline},
            }
        )
    return {
        "schema_version": "wakir.identity.svid-workload-cross-lang/1",
        "fixtures": fixtures,
    }


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
        "DEFAULT_SVID_FIXTURE_RELPATH",
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
        "evaluate_svid_fixture_parity",
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
    assert SMOKE.FOCUS_COMPONENT == "svid_workload_identity"
    assert SMOKE.FOCUS_ENV_VAR == "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND"
    assert SMOKE.EXIT_GREEN == 0
    assert SMOKE.EXIT_CAUTION == 1
    assert SMOKE.EXIT_ROLLBACK == 2
    assert SMOKE.ENVELOPE_SCHEMA == "wakir.phase-3c.welle-2-cutover-smoke/1"
    # Engine-realität after PR #200 federation_resolver: 9 components.
    assert SMOKE.DEFAULT_EXPECTED_COMPONENTS == 9
    assert "federation_resolver" in SMOKE.ENGINE_BOOT_COMPONENTS


def test_build_phase_env_pre_sets_all_python() -> None:
    """Pre-Cutover phase: every Phase-3c env-var is explicitly 'python'."""
    env = SMOKE.build_phase_env(SMOKE.PHASE_PRE)
    assert env[SMOKE.FOCUS_ENV_VAR] == "python"
    for env_var in SMOKE.COMPONENT_TO_ENV.values():
        assert env[env_var] == "python", env_var


def test_build_phase_env_post_flips_focus_to_rust() -> None:
    """Cutover phase: SVID env-var is 'rust', all others stay 'python'."""
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
    """Default config + clean resolver → all asserts pass → exit GREEN."""
    resolver = build_stub_resolver_module()
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        now_ts=1_700_000_000,
        skip_svid_fixture_parity=True,
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    assert envelope["band"] == "GREEN"
    assert envelope["schema"] == "wakir.phase-3c.welle-2-cutover-smoke/1"
    assert envelope["welle"] == 2
    assert envelope["focus_component"] == "svid_workload_identity"
    assert envelope["timestamp_utc"] == 1_700_000_000
    # All blocker asserts pass; A6 is skipped (caution, passed=True).
    for name, record in envelope["asserts"].items():
        assert record["passed"], (name, record)
    # A6 is skipped because skip_svid_fixture_parity=True.
    assert envelope["asserts"]["A6_svid_fixture_parity"]["skipped"] is True


def test_run_cutover_smoke_caution_on_latency_blowup() -> None:
    """Latency 1000× baseline → A3 caution → exit CAUTION."""
    cfg = SMOKE.DEFAULT_LATENCY_TOLERANCE_PCT
    resolver = build_stub_resolver_module(
        StubResolverConfig(
            python_focus_latency_us=100,
            rust_focus_latency_us=100_000,
        )
    )
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        latency_tolerance_pct=cfg,
        skip_svid_fixture_parity=True,
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
        skip_svid_fixture_parity=True,
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
        skip_svid_fixture_parity=True,
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
        skip_svid_fixture_parity=True,
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
            "--skip-svid-fixture-parity",
        ],
        stdout=stdout,
        stderr=stderr,
        resolver_module=resolver,
    )
    assert rc == SMOKE.EXIT_GREEN, stderr.getvalue()
    assert out_file.is_file()
    rendered = out_file.read_text(encoding="utf-8")
    envelope = json.loads(rendered)
    assert envelope["schema"] == "wakir.phase-3c.welle-2-cutover-smoke/1"
    assert envelope["boots_per_phase"] == 3
    assert envelope["timestamp_utc"] == 1700000001
    assert envelope["exit_code"] == SMOKE.EXIT_GREEN
    assert stdout.getvalue() == ""


def test_a6_svid_fixture_parity_green_with_stub_canonical(tmp_path: Path) -> None:
    """A6 substrate-parity green when canonical module agrees with fixtures."""
    canonical = build_stub_svid_canonical_module()
    fixtures = _synthetic_svid_fixtures(canonical)
    fixture_path = tmp_path / "fixtures.json"
    fixture_path.write_text(json.dumps(fixtures), encoding="utf-8")

    resolver = build_stub_resolver_module()
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        svid_fixture_path=fixture_path,
        svid_canonical_module=canonical,
    )
    assert exit_code == SMOKE.EXIT_GREEN, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a6 = envelope["asserts"]["A6_svid_fixture_parity"]
    assert a6["passed"] is True
    assert a6["skipped"] is False
    assert a6["severity"] == "caution"
    # Two recomputed fixtures, both matching.
    assert len(a6["recomputed"]) == 2
    for entry in a6["recomputed"]:
        assert entry["match"] is True


def test_a6_svid_fixture_parity_caution_on_drift(tmp_path: Path) -> None:
    """A6 substrate-parity drift on one fixture → CAUTION exit, not ROLLBACK."""
    # Build a "clean" canonical module to pin baseline hashes...
    pin_canonical = build_stub_svid_canonical_module()
    fixtures = _synthetic_svid_fixtures(pin_canonical)
    fixture_path = tmp_path / "fixtures.json"
    fixture_path.write_text(json.dumps(fixtures), encoding="utf-8")

    # ...then run with a "drifted" canonical that salts one fixture's hash.
    drift_canonical = build_stub_svid_canonical_module(
        drift_fixture_name="wakir-labs"
    )

    resolver = build_stub_resolver_module()
    envelope, exit_code = SMOKE.run_cutover_smoke(
        resolver_module=resolver,
        binary_probe=lambda _p: (True, None),
        svid_fixture_path=fixture_path,
        svid_canonical_module=drift_canonical,
    )
    assert exit_code == SMOKE.EXIT_CAUTION, json.dumps(
        envelope["asserts"], indent=2, sort_keys=True
    )
    a6 = envelope["asserts"]["A6_svid_fixture_parity"]
    assert a6["passed"] is False
    assert a6["skipped"] is False
    assert a6["severity"] == "caution"
    # A1..A5 + R1 all still pass — the engine-emission substance is intact.
    assert envelope["asserts"]["A1_backend_flip"]["passed"]
    assert envelope["asserts"]["A2_cross_lang_parity_hash"]["passed"]
    assert envelope["asserts"]["A3_latency_within_tolerance"]["passed"]
    assert envelope["asserts"]["A4_decision_count_in_place"]["passed"]
    assert envelope["asserts"]["A5_fallback_clean"]["passed"]
    assert envelope["asserts"]["R1_rollback_to_python"]["passed"]
    # At least one recomputed fixture did not match.
    mismatches = [r for r in a6["recomputed"] if not r["match"]]
    assert mismatches, a6
