# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/phase-3c-cutover-dry-run.py — Tag-24 Mini-Welle.

Hermetic, stdlib-only: the dry-run module is loaded via importlib
from its hyphenated path under ``scripts/``. The resolver dependency
is exercised through a stub module so the tests do not have to
import the real wirelang package, and the binary-probe seam is
explicitly stubbed in every test so no filesystem access happens.

Scope (16 tests)
----------------

1.  test_module_loads_and_exports_public_surface
2.  test_validate_component_accepts_in_repo_short_forms
3.  test_validate_component_accepts_adr_0065_aliases
4.  test_validate_component_rejects_empty_and_none
5.  test_validate_component_rejects_unknown
6.  test_validate_component_rejects_svid_with_explicit_hint
7.  test_build_cutover_env_targets_only_requested_component
8.  test_build_cutover_env_state_backing_variant
9.  test_run_boot_sequence_emits_one_decision_per_boot
10. test_latency_envelope_handles_empty_and_typical_samples
11. test_compute_feasibility_score_green_band
12. test_compute_feasibility_score_red_band_on_full_fallback
13. test_run_dry_run_returns_completed_envelope_with_stub_probe
14. test_run_dry_run_blocked_when_probe_real_finds_binary_missing
15. test_main_cli_writes_json_envelope_to_stdout
16. test_main_cli_rejects_unknown_component_with_exit_2
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Module loader (hyphenated filename -> importlib.util)
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
DRY_RUN_PATH = REPO_ROOT / "scripts" / "phase-3c-cutover-dry-run.py"


def _load_dry_run_module():
    spec = importlib.util.spec_from_file_location(
        "phase_3c_cutover_dry_run", DRY_RUN_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


dry_run_mod = _load_dry_run_module()


# ---------------------------------------------------------------------------
# Resolver-stub: minimal substitute for
# ``wirelang.persona_engine.rust_backend_switch``. Provides one
# ``resolve_<domain>_backend`` function per supported component plus
# the binary-probe seams ``_binary_available`` and
# ``_resolve_<domain>_bin``.
# ---------------------------------------------------------------------------


class _StubDecision:
    """Plain dataclass-like stand-in for BackendDecision.

    Implements the same fields the dry-run aggregator reads via
    ``dataclasses.asdict``. We avoid an actual ``@dataclass`` so the
    test stub stays import-free.
    """

    __slots__ = (
        "domain",
        "requested_backend",
        "chosen_backend",
        "resolution_latency_us",
        "fallback_reason",
        "bin_path",
        "__dataclass_fields__",
    )

    def __init__(
        self,
        domain: str,
        requested_backend: str,
        chosen_backend: str,
        resolution_latency_us: int,
        fallback_reason: Optional[str],
        bin_path: Optional[str],
    ):
        self.domain = domain
        self.requested_backend = requested_backend
        self.chosen_backend = chosen_backend
        self.resolution_latency_us = resolution_latency_us
        self.fallback_reason = fallback_reason
        self.bin_path = bin_path
        # asdict() requires a dataclass marker; we synthesise one
        # so the dry-run's asdict() call resolves to our slots.
        self.__dataclass_fields__ = {}

    # ``dataclasses.asdict`` actually requires a real dataclass; the
    # dry-run uses it for production resolvers but we go through the
    # field-by-field copy by adapting via ``_to_dict``.
    def _to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "requested_backend": self.requested_backend,
            "chosen_backend": self.chosen_backend,
            "resolution_latency_us": self.resolution_latency_us,
            "fallback_reason": self.fallback_reason,
            "bin_path": self.bin_path,
        }


def _make_stub_resolver_module(
    *,
    latency_seq: Optional[List[int]] = None,
    force_fallback: bool = False,
    bin_path_value: str = "/opt/wakir/bin/wakir-persona-engine-stub",
    binary_available: bool = True,
    binary_fallback_reason: Optional[str] = None,
):
    """Build an ad-hoc resolver-module-like object.

    ``latency_seq`` cycles through the supplied microsecond values so
    tests can pin the latency envelope. ``force_fallback`` flips the
    decision's chosen_backend to ``"python"`` with a fallback_reason
    even when the env says ``rust`` — used for the RED-band test.
    """

    seq = list(latency_seq) if latency_seq else [100]
    state = {"idx": 0}

    def _next_latency() -> int:
        val = seq[state["idx"] % len(seq)]
        state["idx"] += 1
        return val

    def _make_resolver(domain_value: str, rust_value: str):
        def _resolver(env=None, *, log_sink=None, binary_probe=None):
            # Mirror real resolver: consult env-var, dispatch probe,
            # build a decision record.
            env_var_name = {
                "recovery": "WAKIR_RECOVERY_BACKEND",
                "state_backing": "WAKIR_STATE_BACKING_BACKEND",
                "fsm": "WAKIR_FSM_BACKEND",
                "v907_verify": "WAKIR_V907_VERIFY_BACKEND",
                "bridge_diff": "WAKIR_BRIDGE_DIFF_BACKEND",
                "subscribe_loop": "WAKIR_SUBSCRIBE_LOOP_BACKEND",
                "anchor_emitter": "WAKIR_ANCHOR_EMITTER_BACKEND",
            }[domain_value]
            requested = (env or {}).get(env_var_name, "python")
            latency = _next_latency()
            if force_fallback or requested == "python":
                decision = _StubDecision(
                    domain=domain_value,
                    requested_backend=requested,
                    chosen_backend="python",
                    resolution_latency_us=latency,
                    fallback_reason=(
                        "binary_missing"
                        if force_fallback
                        else (
                            "explicit_python"
                            if requested == "python"
                            else None
                        )
                    ),
                    bin_path=(
                        bin_path_value if force_fallback else None
                    ),
                )
                return ("python", decision)
            # Requested rust* and not forced-fallback: respect probe.
            if binary_probe is not None:
                ok, fallback = binary_probe(bin_path_value)
                if not ok:
                    decision = _StubDecision(
                        domain=domain_value,
                        requested_backend=requested,
                        chosen_backend="python",
                        resolution_latency_us=latency,
                        fallback_reason=fallback or "binary_missing",
                        bin_path=bin_path_value,
                    )
                    return ("python", decision)
            decision = _StubDecision(
                domain=domain_value,
                requested_backend=requested,
                chosen_backend=rust_value,
                resolution_latency_us=latency,
                fallback_reason=None,
                bin_path=bin_path_value,
            )
            return (rust_value, decision)

        return _resolver

    class _Module:
        pass

    mod = _Module()
    for dom, rust_val in (
        ("recovery", "rust"),
        ("state_backing", "rust_inmemory"),
        ("fsm", "rust"),
        ("v907_verify", "rust"),
        ("bridge_diff", "rust"),
        ("subscribe_loop", "rust"),
        ("anchor_emitter", "rust"),
    ):
        setattr(mod, f"resolve_{dom}_backend", _make_resolver(dom, rust_val))
        # Bin-resolver seam (used by --probe-real branch).
        setattr(
            mod,
            f"_resolve_{dom}_bin",
            lambda env, _bp=bin_path_value: _bp,
        )

    def _binary_available(_bin: str) -> Tuple[bool, Optional[str]]:
        return binary_available, binary_fallback_reason

    mod._binary_available = _binary_available  # type: ignore[attr-defined]
    return mod


# ---------------------------------------------------------------------------
# Monkey-patch asdict so the stub decision flows through dry_run_mod
# without dragging in a real dataclass. dry_run.run_boot_sequence
# calls dataclasses.asdict on the decision; we replace the import in
# the loaded module with our own to-dict adapter.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_asdict(monkeypatch):
    """Patch dataclasses.asdict so it understands _StubDecision._to_dict."""

    import dataclasses as _dc

    original_asdict = _dc.asdict

    def _safe_asdict(obj, *args, **kwargs):
        to_dict = getattr(obj, "_to_dict", None)
        if callable(to_dict):
            return to_dict()
        return original_asdict(obj, *args, **kwargs)

    monkeypatch.setattr(dry_run_mod, "asdict", _safe_asdict)
    yield


# ---------------------------------------------------------------------------
# 1. Module surface
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface():
    expected = {
        "COMPONENT_TO_DOMAIN",
        "COMPONENT_TO_ENV",
        "COMPONENT_TO_RUST_VALUE",
        "DEFAULT_BOOTS",
        "DEFAULT_P95_LATENCY_BUDGET_US",
        "DryRunBlockedError",
        "PHASE_3C_COMPONENTS",
        "PHASE_3C_COMPONENT_ALIASES",
        "SCORE_BAND_AMBER",
        "SCORE_BAND_GREEN",
        "UnknownComponentError",
        "build_argparser",
        "build_cutover_env",
        "build_envelope",
        "compute_feasibility_score",
        "latency_envelope",
        "main",
        "run_boot_sequence",
        "run_dry_run",
        "validate_component",
    }
    assert set(dry_run_mod.__all__) == expected
    for name in expected:
        assert hasattr(dry_run_mod, name), f"missing export: {name}"


# ---------------------------------------------------------------------------
# 2-6. validate_component
# ---------------------------------------------------------------------------


def test_validate_component_accepts_in_repo_short_forms():
    for name in (
        "v907_verify",
        "svid_workload_identity",
        "bridge_diff",
        "anchor_emitter",
        "state_backing",
        "fsm",
        "subscribe_loop",
        "recovery",
    ):
        assert dry_run_mod.validate_component(name) == name
        # Case-insensitive + strip behaviour.
        assert dry_run_mod.validate_component(f"  {name.upper()}  ") == name


def test_validate_component_accepts_adr_0065_aliases():
    assert dry_run_mod.validate_component("lifecycle_state_machine") == "fsm"
    assert dry_run_mod.validate_component("recovery_workflow") == "recovery"
    assert (
        dry_run_mod.validate_component("bridge_audit_writer")
        == "anchor_emitter"
    )


def test_validate_component_rejects_empty_and_none():
    with pytest.raises(dry_run_mod.UnknownComponentError):
        dry_run_mod.validate_component("")
    with pytest.raises(dry_run_mod.UnknownComponentError):
        dry_run_mod.validate_component("   ")
    with pytest.raises(dry_run_mod.UnknownComponentError):
        dry_run_mod.validate_component(None)


def test_validate_component_rejects_unknown():
    with pytest.raises(dry_run_mod.UnknownComponentError) as exc:
        dry_run_mod.validate_component("definitely_not_a_component")
    assert "definitely_not_a_component" in str(exc.value)


def test_validate_component_accepts_svid_workload_identity_tag25():
    """Tag-25 Mini-Welle (ADR-0065 Welle-2 pre-condition) added the
    ``svid_workload_identity`` resolver to the seven-switch substrate
    (now eight). The dry-run aggregator now lists it as the eighth
    component at the ADR-0065-mandated Welle-2 position rather than
    fail-closed.
    """
    assert (
        dry_run_mod.validate_component("svid_workload_identity")
        == "svid_workload_identity"
    )
    # Component is now part of the canonical PHASE_3C_COMPONENTS tuple.
    assert "svid_workload_identity" in dry_run_mod.PHASE_3C_COMPONENTS
    # Resolver maps to the matching WAKIR_*_BACKEND env-var.
    assert (
        dry_run_mod.COMPONENT_TO_ENV["svid_workload_identity"]
        == "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND"
    )
    # Default cutover-env opts svid into "rust" (no rust_inmemory split).
    assert (
        dry_run_mod.COMPONENT_TO_RUST_VALUE["svid_workload_identity"]
        == "rust"
    )


# ---------------------------------------------------------------------------
# 7-8. build_cutover_env
# ---------------------------------------------------------------------------


def test_build_cutover_env_targets_only_requested_component():
    env = dry_run_mod.build_cutover_env("v907_verify")
    assert env["WAKIR_V907_VERIFY_BACKEND"] == "rust"
    # All other Phase-3c env-vars are explicitly set to python so the
    # boot path is deterministic.
    for env_var in dry_run_mod.COMPONENT_TO_ENV.values():
        if env_var == "WAKIR_V907_VERIFY_BACKEND":
            continue
        assert env[env_var] == "python", (
            f"unexpected non-python value for {env_var}: {env[env_var]!r}"
        )
    # Hermetic: no inherited env entries.
    assert "PATH" not in env
    assert "HOME" not in env


def test_build_cutover_env_state_backing_variant():
    env_in_memory = dry_run_mod.build_cutover_env(
        "state_backing", state_backing_variant="rust_inmemory"
    )
    assert env_in_memory["WAKIR_STATE_BACKING_BACKEND"] == "rust_inmemory"
    env_natskv = dry_run_mod.build_cutover_env(
        "state_backing", state_backing_variant="rust_natskv"
    )
    assert env_natskv["WAKIR_STATE_BACKING_BACKEND"] == "rust_natskv"
    with pytest.raises(ValueError):
        dry_run_mod.build_cutover_env(
            "state_backing", state_backing_variant="bogus"
        )


# ---------------------------------------------------------------------------
# 9. run_boot_sequence
# ---------------------------------------------------------------------------


def test_run_boot_sequence_emits_one_decision_per_boot():
    stub_mod = _make_stub_resolver_module(latency_seq=[100, 200, 300, 400, 500])
    env = dry_run_mod.build_cutover_env("v907_verify")
    records = dry_run_mod.run_boot_sequence(
        "v907_verify",
        boots=5,
        env=env,
        resolver_module=stub_mod,
        binary_probe=lambda _bin: (True, None),
    )
    assert len(records) == 5
    assert {r["domain"] for r in records} == {"v907_verify"}
    assert all(r["chosen_backend"] == "rust" for r in records)
    # Latency_seq is rotated 1:1.
    assert [r["resolution_latency_us"] for r in records] == [
        100,
        200,
        300,
        400,
        500,
    ]
    # boots=0 is invalid.
    with pytest.raises(ValueError):
        dry_run_mod.run_boot_sequence(
            "v907_verify", boots=0, env=env, resolver_module=stub_mod
        )


# ---------------------------------------------------------------------------
# 10. latency_envelope
# ---------------------------------------------------------------------------


def test_latency_envelope_handles_empty_and_typical_samples():
    assert dry_run_mod.latency_envelope([]) == {
        "avg": 0,
        "p50": 0,
        "p95": 0,
        "p99": 0,
        "count": 0,
    }
    samples = [
        {"resolution_latency_us": v}
        for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    ]
    env = dry_run_mod.latency_envelope(samples)
    assert env["count"] == 10
    assert env["avg"] == 55
    # Nearest-rank percentile semantics — p50 ranks at ceil(0.5*10)=5
    # → ordered[4] = 50; p95 at ceil(0.95*10)=10 → 100.
    assert env["p50"] == 50
    assert env["p95"] == 100
    assert env["p99"] == 100
    # Bool and string latencies are filtered out (not int-treatable).
    mixed = [
        {"resolution_latency_us": 100},
        {"resolution_latency_us": True},
        {"resolution_latency_us": "200"},
        {"resolution_latency_us": 200},
    ]
    env_mixed = dry_run_mod.latency_envelope(mixed)
    assert env_mixed["count"] == 2
    assert env_mixed["avg"] == 150


# ---------------------------------------------------------------------------
# 11-12. compute_feasibility_score
# ---------------------------------------------------------------------------


def test_compute_feasibility_score_green_band():
    # 10 boots, all rust, all 100us, no fallback → all sub-scores 1.0.
    records = [
        {
            "domain": "v907_verify",
            "requested_backend": "rust",
            "chosen_backend": "rust",
            "resolution_latency_us": 100,
            "fallback_reason": None,
            "bin_path": "/opt/wakir/bin/x",
        }
        for _ in range(10)
    ]
    out = dry_run_mod.compute_feasibility_score(
        records,
        requested_backend="rust",
        p95_latency_budget_us=50_000,
    )
    assert out["cutover_feasibility_score"] == pytest.approx(1.0, abs=0.0001)
    assert out["band"] == "GREEN"
    assert out["subscores"]["backend_purity"] == 1.0
    assert out["subscores"]["latency_score"] == 1.0
    assert out["subscores"]["fallback_score"] == 1.0
    assert out["weights"] == {
        "backend_purity": 0.5,
        "latency_score": 0.3,
        "fallback_score": 0.2,
    }


def test_compute_feasibility_score_red_band_on_full_fallback():
    # All boots fell back to python: purity=0, fallback=1 → score=0.3.
    records = [
        {
            "domain": "v907_verify",
            "requested_backend": "rust",
            "chosen_backend": "python",
            "resolution_latency_us": 100,
            "fallback_reason": "binary_missing",
            "bin_path": "/opt/wakir/bin/x",
        }
        for _ in range(10)
    ]
    out = dry_run_mod.compute_feasibility_score(
        records,
        requested_backend="rust",
        p95_latency_budget_us=50_000,
    )
    # purity = 0, latency_score = 1.0 (100 < 50_000), fallback_score = 0.0
    # → 0.5*0 + 0.3*1.0 + 0.2*0.0 = 0.3
    assert out["cutover_feasibility_score"] == pytest.approx(0.3, abs=0.0001)
    assert out["band"] == "RED"


# ---------------------------------------------------------------------------
# 13-14. run_dry_run end-to-end
# ---------------------------------------------------------------------------


def test_run_dry_run_returns_completed_envelope_with_stub_probe():
    stub_mod = _make_stub_resolver_module(latency_seq=[50, 60, 70, 80])
    env = dry_run_mod.run_dry_run(
        component="v907_verify",
        boots=4,
        resolver_module=stub_mod,
        now_ts=1_700_000_000,
    )
    assert env["dry_run"] == "completed"
    assert env["component"] == "v907_verify"
    assert env["env_var"] == "WAKIR_V907_VERIFY_BACKEND"
    assert env["requested_backend"] == "rust"
    assert env["probe_mode"] == "stub"
    assert env["timestamp_utc"] == 1_700_000_000
    assert env["schema"] == "wakir.phase-3c.dry-run/1"
    assert len(env["decisions"]) == 4
    assert env["latency"]["count"] == 4
    assert env["feasibility"]["band"] == "GREEN"
    assert env["chosen_backend_counts"] == {"rust": 4}
    assert env["fallback_reason_counts"] == {"null": 4}


def test_run_dry_run_blocked_when_probe_real_finds_binary_missing():
    stub_mod = _make_stub_resolver_module(
        binary_available=False,
        binary_fallback_reason="binary_missing",
    )
    env = dry_run_mod.run_dry_run(
        component="v907_verify",
        boots=4,
        probe_real=True,
        resolver_module=stub_mod,
        now_ts=1_700_000_000,
    )
    assert env["dry_run"] == "blocked"
    assert env["probe_mode"] == "real"
    assert "error" in env and env["error"]
    assert "binary_missing" in env["error"]
    assert env["decisions"] == []  # no boots were spent
    assert env["feasibility"]["band"] == "BLOCKED"
    assert env["feasibility"]["cutover_feasibility_score"] == 0.0


# ---------------------------------------------------------------------------
# 15-16. CLI main() exit-code and stdout shape.
# ---------------------------------------------------------------------------


def test_main_cli_writes_json_envelope_to_stdout(monkeypatch):
    """End-to-end: monkey-patch the resolver-import seam to inject our
    stub module, run main() with default args, parse stdout as JSON."""
    stub_mod = _make_stub_resolver_module(latency_seq=[100])
    monkeypatch.setattr(dry_run_mod, "_import_resolver", lambda: stub_mod)
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    rc = dry_run_mod.main(
        argv=["--component", "v907_verify", "--boots", "3", "--now", "1700000000"],
        stdout=out_buf,
        stderr=err_buf,
    )
    assert rc == 0
    rendered = out_buf.getvalue()
    parsed = json.loads(rendered)
    assert parsed["component"] == "v907_verify"
    assert parsed["boots"] == 3
    assert parsed["timestamp_utc"] == 1_700_000_000
    assert parsed["dry_run"] == "completed"
    assert parsed["feasibility"]["band"] == "GREEN"
    assert len(parsed["decisions"]) == 3


def test_main_cli_rejects_unknown_component_with_exit_2(monkeypatch):
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    rc = dry_run_mod.main(
        argv=["--component", "no_such_component"],
        stdout=out_buf,
        stderr=err_buf,
    )
    assert rc == 2
    assert "no_such_component" in err_buf.getvalue()
    assert out_buf.getvalue() == ""
