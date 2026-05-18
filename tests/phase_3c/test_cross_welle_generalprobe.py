# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/phase-3c/cross-welle-cutover-generalprobe.py.

Hermetic, stdlib-only. The orchestrator is loaded via importlib from
its hyphenated path under ``scripts/phase-3c/``. Every test injects a
mocked ``smoke_runner`` that returns canned :class:`SmokeResult`
instances, so no real welle-smoke subprocess is spawned and no
filesystem state is touched outside ``tmp_path``.

Scope (14 tests, exceeds Auftrag-Tag-40 minimum of 12)
------------------------------------------------------

1.  test_module_loads_and_exports_public_surface
2.  test_plan_constants_match_adr_0066_kw24_kw27
3.  test_filter_plan_full_default_returns_all_four_sub_sequences
4.  test_filter_plan_partial_up_to_welle_3_drops_kw26_kw27
5.  test_filter_plan_partial_from_welle_4_drops_kw24_kw25
6.  test_filter_plan_invalid_range_raises
7.  test_expected_assert_families_union_grows_with_welle_set
8.  test_aggregate_exit_worst_band_wins
9.  test_aggregate_drift_green_path_all_pass
10. test_aggregate_drift_red_on_blocker_fail
11. test_aggregate_drift_amber_on_caution_only_fail
12. test_run_generalprobe_green_path_dispatches_all_welles
13. test_run_generalprobe_dry_run_skips_dispatch
14. test_run_generalprobe_short_circuits_on_rollback
15. test_main_cli_writes_envelope_and_returns_exit_code
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pytest


# ---------------------------------------------------------------------------
# Orchestrator-module loader — handles the hyphenated path.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    # tests/phase_3c/test_cross_welle_generalprobe.py → repo root is two up.
    return here.parent.parent.parent


def _load_orchestrator_module() -> Any:
    script_path = (
        _repo_root()
        / "scripts"
        / "phase-3c"
        / "cross-welle-cutover-generalprobe.py"
    )
    if not script_path.is_file():
        pytest.fail(f"generalprobe script not found at {script_path}")
    spec = importlib.util.spec_from_file_location(
        "cross_welle_cutover_generalprobe", str(script_path)
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot build spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["cross_welle_cutover_generalprobe"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


GP = _load_orchestrator_module()


# ---------------------------------------------------------------------------
# Canned-envelope factory for the mocked smoke-runner.
# ---------------------------------------------------------------------------


def _make_envelope(
    welle: int,
    *,
    band: str = "GREEN",
    exit_code: int = 0,
    asserts: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a canned per-welle envelope matching the real smoke shape."""
    env: Dict[str, Any] = {
        "schema": f"wakir.phase-3c.welle-{welle}-cutover-smoke/1",
        "welle": welle,
        "band": band,
        "exit_code": exit_code,
        "asserts": asserts if asserts is not None else _default_pass_asserts(welle),
    }
    if extra:
        env.update(extra)
    return env


def _default_pass_asserts(welle: int) -> Dict[str, Any]:
    """All-pass asserts dict for `welle`, matching the smoke contract."""
    out: Dict[str, Any] = {}
    for fam in GP.ASSERT_FAMILIES_SHARED:
        out[fam] = {"passed": True, "severity": "blocker", "detail": "ok"}
    a6 = GP._family_a6_for_welle(welle)
    if a6 is not None:
        out[a6] = {"passed": True, "severity": "caution", "detail": "ok"}
    a7 = GP._family_a7_for_welle(welle)
    if a7 is not None:
        out[a7] = {"passed": True, "severity": "caution", "detail": "ok"}
    return out


def _make_runner(
    envelopes_by_welle: Mapping[int, Dict[str, Any]],
    *,
    exit_codes: Optional[Mapping[int, int]] = None,
) -> Any:
    """Build a deterministic smoke-runner that returns canned results.

    The runner ignores all subprocess concerns and synthesises a
    SmokeResult per welle from the supplied dict, optionally writing
    the envelope JSON to ``out_dir / welle-N-envelope.json`` so the
    Marathon-Envelope can refer to it by path.
    """
    if exit_codes is None:
        exit_codes = {w: env.get("exit_code", 0) for w, env in envelopes_by_welle.items()}

    def runner(
        welle: int,
        output_path: Path,
        extra_args: Sequence[str],
        env: Mapping[str, str],
    ) -> "GP.SmokeResult":
        envelope = envelopes_by_welle[welle]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(envelope, sort_keys=True, indent=2), encoding="utf-8"
        )
        return GP.SmokeResult(
            welle=welle,
            exit_code=exit_codes.get(welle, envelope.get("exit_code", 0)),
            band=envelope.get("band", "UNKNOWN"),
            envelope=envelope,
            envelope_path=output_path,
            stderr_tail="",
        )

    return runner


# ---------------------------------------------------------------------------
# 1. Module surface.
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface() -> None:
    """Smoke-test the loader and pin the public-surface contract."""
    must_export = {
        "ASSERT_FAMILIES_SHARED",
        "BAND_GREEN",
        "BAND_CAUTION",
        "BAND_ROLLBACK",
        "ENVELOPE_SCHEMA",
        "EXIT_GREEN",
        "EXIT_CAUTION",
        "EXIT_ROLLBACK",
        "PLAN",
        "SmokeResult",
        "SubSequence",
        "aggregate_drift",
        "aggregate_exit",
        "build_argparser",
        "build_marathon_envelope",
        "default_smoke_runner",
        "expected_assert_families",
        "filter_plan",
        "main",
        "run_generalprobe",
    }
    missing = must_export - set(GP.__all__)
    assert not missing, f"public surface lost: {missing}"
    assert GP.ENVELOPE_SCHEMA == "wakir.phase-3c.cross-welle-generalprobe/1"
    assert GP.EXIT_GREEN == 0
    assert GP.EXIT_CAUTION == 1
    assert GP.EXIT_ROLLBACK == 2


# ---------------------------------------------------------------------------
# 2. ADR-0066 plan constants.
# ---------------------------------------------------------------------------


def test_plan_constants_match_adr_0066_kw24_kw27() -> None:
    """Plan is load-bearing: KW-24 (W1+W2) → KW-25 (W3) → KW-26 (W4+W5) → KW-27 (W6+W7)."""
    assert len(GP.PLAN) == 4
    assert GP.PLAN[0].kw_label == "KW-24"
    assert GP.PLAN[0].welles == (1, 2)
    assert GP.PLAN[0].mode == "parallel"
    assert GP.PLAN[1].kw_label == "KW-25"
    assert GP.PLAN[1].welles == (3,)
    assert GP.PLAN[1].mode == "solo"
    assert GP.PLAN[2].kw_label == "KW-26"
    assert GP.PLAN[2].welles == (4, 5)
    assert GP.PLAN[2].mode == "parallel"
    assert GP.PLAN[3].kw_label == "KW-27"
    assert GP.PLAN[3].welles == (6, 7)
    assert GP.PLAN[3].mode == "parallel"

    # Every welle 1..7 is covered exactly once.
    covered = [w for sub in GP.PLAN for w in sub.welles]
    assert sorted(covered) == [1, 2, 3, 4, 5, 6, 7]


# ---------------------------------------------------------------------------
# 3-6. filter_plan edge-cases.
# ---------------------------------------------------------------------------


def test_filter_plan_full_default_returns_all_four_sub_sequences() -> None:
    plan = GP.filter_plan(GP.PLAN, from_welle=1, up_to_welle=7)
    assert len(plan) == 4
    assert [sub.welles for sub in plan] == [(1, 2), (3,), (4, 5), (6, 7)]


def test_filter_plan_partial_up_to_welle_3_drops_kw26_kw27() -> None:
    plan = GP.filter_plan(GP.PLAN, from_welle=1, up_to_welle=3)
    assert [sub.kw_label for sub in plan] == ["KW-24", "KW-25"]
    assert [sub.welles for sub in plan] == [(1, 2), (3,)]


def test_filter_plan_partial_from_welle_4_drops_kw24_kw25() -> None:
    plan = GP.filter_plan(GP.PLAN, from_welle=4, up_to_welle=7)
    assert [sub.kw_label for sub in plan] == ["KW-26", "KW-27"]
    assert [sub.welles for sub in plan] == [(4, 5), (6, 7)]


def test_filter_plan_partial_single_welle_degrades_parallel_to_solo() -> None:
    """If --from-welle=2 --up-to-welle=2, KW-24 keeps only welle-2 → mode flips to solo."""
    plan = GP.filter_plan(GP.PLAN, from_welle=2, up_to_welle=2)
    assert len(plan) == 1
    assert plan[0].kw_label == "KW-24"
    assert plan[0].welles == (2,)
    assert plan[0].mode == "solo", "single-welle filter must downgrade mode"


def test_filter_plan_invalid_range_raises() -> None:
    with pytest.raises(ValueError):
        GP.filter_plan(GP.PLAN, from_welle=0, up_to_welle=3)
    with pytest.raises(ValueError):
        GP.filter_plan(GP.PLAN, from_welle=1, up_to_welle=8)
    with pytest.raises(ValueError):
        GP.filter_plan(GP.PLAN, from_welle=5, up_to_welle=3)


# ---------------------------------------------------------------------------
# 7. expected_assert_families union.
# ---------------------------------------------------------------------------


def test_expected_assert_families_union_grows_with_welle_set() -> None:
    """Shared families always present; A6/A7 added per welle id."""
    fams_w1 = GP.expected_assert_families([1])
    # Welle-1: shared families only, no A6, no A7.
    for fam in GP.ASSERT_FAMILIES_SHARED:
        assert fam in fams_w1
    assert not any(f.startswith("A6_") for f in fams_w1), (
        f"welle-1 has no A6 family: {fams_w1}"
    )
    assert not any(f.startswith("A7_") for f in fams_w1), (
        f"welle-1 has no A7 family: {fams_w1}"
    )

    fams_all = GP.expected_assert_families([1, 2, 3, 4, 5, 6, 7])
    # All A6 families (welles 2..7) and the welle-specific A7 keys
    # for welles 3..7 must appear.
    assert "A6_svid_fixture_parity" in fams_all
    assert "A6_bridge_audit_stream_parity" in fams_all
    assert "A6_cross_backend_read_compatibility" in fams_all
    assert "A6_fsm_transition_integrity" in fams_all
    assert "A6_subscribe_loop_lag_stability" in fams_all
    assert "A6_recovery_r1_r4_drill" in fams_all
    assert "A7_self_reference_trap_control" in fams_all
    assert "A7_cross_modul_drift_welle_5_fsm" in fams_all
    assert "A7_cross_modul_drift_welle_4_state_backing" in fams_all
    assert "A7_cross_modul_drift_welle_7_recovery" in fams_all
    assert "A7_cross_modul_drift_welle_6_subscribe_loop" in fams_all


# ---------------------------------------------------------------------------
# 8. aggregate_exit — worst band wins.
# ---------------------------------------------------------------------------


def test_aggregate_exit_worst_band_wins() -> None:
    def r(welle: int, code: int) -> "GP.SmokeResult":
        return GP.SmokeResult(
            welle=welle,
            exit_code=code,
            band=GP.BAND_FOR_EXIT.get(code, "UNKNOWN"),
            envelope={},
            envelope_path=None,
            stderr_tail="",
        )

    assert GP.aggregate_exit([]) == GP.EXIT_GREEN
    assert (
        GP.aggregate_exit([r(1, GP.EXIT_GREEN), r(2, GP.EXIT_GREEN)])
        == GP.EXIT_GREEN
    )
    assert (
        GP.aggregate_exit([r(1, GP.EXIT_GREEN), r(2, GP.EXIT_CAUTION)])
        == GP.EXIT_CAUTION
    )
    assert (
        GP.aggregate_exit(
            [r(1, GP.EXIT_CAUTION), r(2, GP.EXIT_ROLLBACK), r(3, GP.EXIT_GREEN)]
        )
        == GP.EXIT_ROLLBACK
    )


# ---------------------------------------------------------------------------
# 9. aggregate_drift — green path.
# ---------------------------------------------------------------------------


def test_aggregate_drift_green_path_all_pass(tmp_path: Path) -> None:
    """All seven welles pass cleanly → drift verdict GREEN, no failed-records."""
    envelopes = {w: _make_envelope(w) for w in range(1, 8)}
    results = [
        GP.SmokeResult(
            welle=w,
            exit_code=0,
            band="GREEN",
            envelope=envelopes[w],
            envelope_path=None,
            stderr_tail="",
        )
        for w in range(1, 8)
    ]
    drift = GP.aggregate_drift(results)
    assert drift["overall_drift_verdict"] == GP.DRIFT_FAMILY_GREEN
    # Every family must be either fully-passed or fully-skipped.
    for fam, rec in drift["families"].items():
        assert not rec["failed_in"], f"family {fam} unexpectedly failed: {rec}"
        assert rec["family_verdict"] == GP.DRIFT_FAMILY_GREEN
    # Welles dispatched recorded.
    assert drift["welles_dispatched"] == list(range(1, 8))


# ---------------------------------------------------------------------------
# 10. aggregate_drift — RED on blocker fail.
# ---------------------------------------------------------------------------


def test_aggregate_drift_red_on_blocker_fail() -> None:
    """A blocker-severity fail in any welle → family RED → overall RED."""
    asserts_w1 = _default_pass_asserts(1)
    asserts_w1["A1_backend_flip"] = {
        "passed": False,
        "severity": "blocker",
        "detail": "v907_verify backend did not flip to rust",
    }
    envelopes = {1: _make_envelope(1, asserts=asserts_w1)}
    envelopes.update({w: _make_envelope(w) for w in range(2, 8)})

    results = [
        GP.SmokeResult(
            welle=w,
            exit_code=2 if w == 1 else 0,
            band="ROLLBACK_RECOMMENDED" if w == 1 else "GREEN",
            envelope=envelopes[w],
            envelope_path=None,
            stderr_tail="",
        )
        for w in range(1, 8)
    ]
    drift = GP.aggregate_drift(results)
    assert drift["overall_drift_verdict"] == GP.DRIFT_FAMILY_RED
    a1 = drift["families"]["A1_backend_flip"]
    assert a1["family_verdict"] == GP.DRIFT_FAMILY_RED
    assert any(f["welle"] == 1 and f["severity"] == "blocker" for f in a1["failed_in"])
    # Other families remain green.
    assert drift["families"]["A2_cross_lang_parity_hash"]["family_verdict"] == GP.DRIFT_FAMILY_GREEN


# ---------------------------------------------------------------------------
# 11. aggregate_drift — AMBER on caution-only fail.
# ---------------------------------------------------------------------------


def test_aggregate_drift_amber_on_caution_only_fail() -> None:
    """A caution-only fail (no blockers) → family AMBER → overall AMBER."""
    asserts_w3 = _default_pass_asserts(3)
    asserts_w3["A3_latency_within_tolerance"] = {
        "passed": False,
        "severity": "caution",
        "detail": "post_p95 above tolerance",
    }
    envelopes = {w: _make_envelope(w) for w in range(1, 8)}
    envelopes[3] = _make_envelope(3, band="CAUTION", exit_code=1, asserts=asserts_w3)
    results = [
        GP.SmokeResult(
            welle=w,
            exit_code=envelopes[w].get("exit_code", 0),
            band=envelopes[w].get("band", "GREEN"),
            envelope=envelopes[w],
            envelope_path=None,
            stderr_tail="",
        )
        for w in range(1, 8)
    ]
    drift = GP.aggregate_drift(results)
    assert drift["overall_drift_verdict"] == GP.DRIFT_FAMILY_AMBER
    a3 = drift["families"]["A3_latency_within_tolerance"]
    assert a3["family_verdict"] == GP.DRIFT_FAMILY_AMBER
    assert any(f["welle"] == 3 and f["severity"] == "caution" for f in a3["failed_in"])


# ---------------------------------------------------------------------------
# 12. run_generalprobe — green path dispatches all welles.
# ---------------------------------------------------------------------------


def test_run_generalprobe_green_path_dispatches_all_welles(tmp_path: Path) -> None:
    envelopes = {w: _make_envelope(w) for w in range(1, 8)}
    runner = _make_runner(envelopes)
    envelope, exit_code = GP.run_generalprobe(
        out_dir=tmp_path / "gp",
        smoke_runner=runner,
        env={"WAKIR_GENERALPROBE_REPO_ROOT": str(_repo_root())},
        now_ts=1747584000,
    )
    assert exit_code == GP.EXIT_GREEN
    assert envelope["marathon_exit_code"] == GP.EXIT_GREEN
    assert envelope["marathon_band"] == GP.BAND_GREEN
    assert envelope["dry_run"] is False
    assert envelope["schema"] == GP.ENVELOPE_SCHEMA
    assert envelope["timestamp_utc"] == 1747584000
    # All seven welles must appear in welle_results, in welle-id order.
    welles_in_results = [r["welle"] for r in envelope["welle_results"]]
    assert welles_in_results == [1, 2, 3, 4, 5, 6, 7]
    # Per-welle envelope files written.
    for w in range(1, 8):
        assert (tmp_path / "gp" / f"welle-{w}-envelope.json").is_file()
    # Drift verdict GREEN.
    assert envelope["cross_welle_drift"]["overall_drift_verdict"] == GP.DRIFT_FAMILY_GREEN


# ---------------------------------------------------------------------------
# 13. run_generalprobe — dry-run skips dispatch.
# ---------------------------------------------------------------------------


def test_run_generalprobe_dry_run_skips_dispatch(tmp_path: Path) -> None:
    invocations: List[int] = []

    def tracking_runner(welle, out, extra, env):  # type: ignore[no-untyped-def]
        invocations.append(welle)
        raise AssertionError("dry-run must not invoke smokes")

    envelope, exit_code = GP.run_generalprobe(
        out_dir=tmp_path / "gp",
        smoke_runner=tracking_runner,
        dry_run=True,
        now_ts=1747584000,
    )
    assert exit_code == GP.EXIT_GREEN
    assert envelope["dry_run"] is True
    assert envelope["welle_results"] == []
    assert envelope["marathon_band"] == GP.BAND_GREEN
    assert invocations == []
    assert len(envelope["plan"]) == 4


# ---------------------------------------------------------------------------
# 14. run_generalprobe — short-circuit on rollback.
# ---------------------------------------------------------------------------


def test_run_generalprobe_short_circuits_on_rollback(tmp_path: Path) -> None:
    """If KW-24 emits ROLLBACK, KW-25..KW-27 must not be dispatched."""
    asserts_w1 = _default_pass_asserts(1)
    asserts_w1["A1_backend_flip"] = {
        "passed": False,
        "severity": "blocker",
        "detail": "synthetic blocker fail",
    }
    envelopes = {
        1: _make_envelope(1, band="ROLLBACK_RECOMMENDED", exit_code=2, asserts=asserts_w1),
        2: _make_envelope(2),
        3: _make_envelope(3),
        4: _make_envelope(4),
        5: _make_envelope(5),
        6: _make_envelope(6),
        7: _make_envelope(7),
    }
    dispatched: List[int] = []

    def counting_runner(welle, out, extra, env):  # type: ignore[no-untyped-def]
        dispatched.append(welle)
        envelope = envelopes[welle]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(envelope), encoding="utf-8")
        return GP.SmokeResult(
            welle=welle,
            exit_code=envelope.get("exit_code", 0),
            band=envelope.get("band", "GREEN"),
            envelope=envelope,
            envelope_path=out,
            stderr_tail="",
        )

    envelope, exit_code = GP.run_generalprobe(
        out_dir=tmp_path / "gp",
        smoke_runner=counting_runner,
        env={"WAKIR_GENERALPROBE_REPO_ROOT": str(_repo_root())},
        now_ts=1747584000,
    )
    assert exit_code == GP.EXIT_ROLLBACK
    assert envelope["marathon_band"] == GP.BAND_ROLLBACK
    # KW-24 ran (welles 1+2), but no later sub-sequence dispatched.
    assert 1 in dispatched
    assert 2 in dispatched
    for later in (3, 4, 5, 6, 7):
        assert later not in dispatched, (
            f"welle-{later} must not be dispatched after KW-24 ROLLBACK"
        )


# ---------------------------------------------------------------------------
# 15. CLI — main writes envelope and returns exit code.
# ---------------------------------------------------------------------------


def test_main_cli_writes_envelope_and_returns_exit_code(tmp_path: Path) -> None:
    """End-to-end CLI: --output writes the JSON envelope; return = exit_code."""
    envelopes = {w: _make_envelope(w) for w in range(1, 8)}
    runner = _make_runner(envelopes)
    out_marathon = tmp_path / "marathon.json"
    out_dir = tmp_path / "envelopes"

    rc = GP.main(
        [
            "--output",
            str(out_marathon),
            "--out-dir",
            str(out_dir),
            "--now",
            "1747584000",
        ],
        smoke_runner=runner,
        env={"WAKIR_GENERALPROBE_REPO_ROOT": str(_repo_root())},
    )
    assert rc == GP.EXIT_GREEN
    assert out_marathon.is_file()
    parsed = json.loads(out_marathon.read_text(encoding="utf-8"))
    assert parsed["schema"] == GP.ENVELOPE_SCHEMA
    assert parsed["marathon_exit_code"] == GP.EXIT_GREEN
    assert parsed["marathon_band"] == GP.BAND_GREEN
    assert parsed["timestamp_utc"] == 1747584000
    assert len(parsed["welle_results"]) == 7

    # CLI argv validation.
    err_buf = io.StringIO()
    rc_bad = GP.main(
        ["--from-welle", "0"],
        stderr=err_buf,
        smoke_runner=runner,
    )
    assert rc_bad == GP.EXIT_ROLLBACK
    assert "from-welle" in err_buf.getvalue()

    err_buf2 = io.StringIO()
    rc_bad2 = GP.main(
        ["--from-welle", "5", "--up-to-welle", "3"],
        stderr=err_buf2,
        smoke_runner=runner,
    )
    assert rc_bad2 == GP.EXIT_ROLLBACK
    assert "from-welle" in err_buf2.getvalue()
