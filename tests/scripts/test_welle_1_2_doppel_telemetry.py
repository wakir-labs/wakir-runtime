# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/welle-1-2-doppel-telemetry-emitter.py — Tag-32 Mini-Welle.

Hermetic, stdlib + pytest only. Loads the emitter via importlib from
its hyphenated path under ``scripts/``. JSONL inputs are written to
``tmp_path`` fixtures. No network, no live Prometheus, no podman.

The emitter is the Welle-1+2 Day-0 Observability deliverable for the
KW-24 doppel cutover (ADR-0066). It mirrors the Tag-31 Welle-3
emitter's posture (per-welle high-frequency telemetry, independent
Phase-2 stress oracle, red-flag exit code) but emits **per-welle**
panels for both Welle-1 (``v907_verify``) and Welle-2
(``svid_workload_identity``) plus a combined doppel health-score.

Scope (12 tests)
----------------

1.  test_module_loads_and_exports_public_surface
2.  test_welle_fix_set_matches_kw24_doppel_pair
3.  test_resolve_paths_priority_order_cli_env_none
4.  test_ingest_window_for_domain_filters_by_domain_and_time
5.  test_compute_consistency_score_handles_empty_and_mixed
6.  test_load_stress_oracles_per_welle_schema_and_legacy_fallback
7.  test_load_welle_lifecycle_string_and_int_keys
8.  test_build_snapshot_combined_health_score_and_aktiv_count
9.  test_build_snapshot_per_welle_independent_red_flags
10. test_build_snapshot_no_red_flag_when_inputs_missing
11. test_render_prometheus_textfile_emits_per_welle_and_combined_metrics
12. test_main_cli_writes_out_and_prom_textfile_returns_zero_when_green
13. test_main_cli_returns_one_on_any_red_flag_and_two_on_bad_input
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional

import pytest


# ---------------------------------------------------------------------------
# Module loader (hyphenated filename -> importlib.util)
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
EMITTER_PATH = (
    REPO_ROOT / "scripts" / "welle-1-2-doppel-telemetry-emitter.py"
)


def _load_emitter_module():
    spec = importlib.util.spec_from_file_location(
        "welle_1_2_doppel_telemetry_emitter", EMITTER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


emitter = _load_emitter_module()


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 5, 18, 9, 0, 0, tzinfo=timezone.utc)


def _decision(
    *,
    domain: str,
    chosen_backend: str = "rust",
    fallback_reason: Optional[str] = None,
    ts: Optional[datetime] = None,
) -> dict:
    """Build a single BackendDecision JSONL record (dict)."""

    if ts is None:
        ts = _now()
    rec: dict = {
        "domain": domain,
        "requested_backend": "rust",
        "chosen_backend": chosen_backend,
        "fallback_reason": fallback_reason,
        "level": "INFO",
        "msg": "backend-decision",
        "ts": ts.isoformat().replace("+00:00", "Z"),
    }
    return rec


def _seed_jsonl(path: Path, records: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Module surface
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface():
    """Smoke-test the public-API surface so import-time drift is loud."""

    expected = [
        "WelleState",
        "StressOracleStatus",
        "WindowCounts",
        "StressOracle",
        "WelleTelemetry",
        "DoppelTelemetrySnapshot",
        "SCHEMA_ID",
        "WELLE_FIX_SET",
        "DOPPEL_WELLE_CAP",
        "DEFAULT_TICK_INTERVAL_SECONDS",
        "DEFAULT_WINDOW_SECONDS",
        "DEFAULT_DIVERGENCE_THRESHOLD_PCT",
        "PAIR_LABEL",
        "ENV_PHASE_3C_OBS_BASELINE_PATH",
        "ENV_BACKEND_DECISION_JSONL",
        "ENV_PHASE_2_STRESS_OUTPUT",
        "ENV_PHASE_3C_WELLE_LIFECYCLE",
        "resolve_decisions_jsonl_path",
        "resolve_phase2_stress_path",
        "resolve_lifecycle_path",
        "ingest_window_for_domain",
        "compute_consistency_score_pct",
        "load_stress_oracles",
        "load_welle_lifecycle",
        "build_snapshot",
        "render_prometheus_textfile",
        "build_parser",
        "main",
    ]
    for name in expected:
        assert hasattr(emitter, name), f"missing public surface: {name}"

    assert emitter.DOPPEL_WELLE_CAP == 2
    assert emitter.DEFAULT_TICK_INTERVAL_SECONDS == 10
    assert emitter.DEFAULT_WINDOW_SECONDS == 300
    assert emitter.DEFAULT_DIVERGENCE_THRESHOLD_PCT == 0.5
    assert emitter.PAIR_LABEL == "1+2"
    assert (
        emitter.SCHEMA_ID
        == "wakir.persona-engine.welle-1-2-doppel-telemetry.v1"
    )


# ---------------------------------------------------------------------------
# 2. Welle fix-set
# ---------------------------------------------------------------------------


def test_welle_fix_set_matches_kw24_doppel_pair():
    """Welle fix-set is exactly (1, v907_verify) and (2, svid_workload_identity).

    KW 24 is the ADR-0066 first doppel-week. Drift in the fix-set is a
    silent dashboard / runbook break: this test is the canary.
    """

    assert emitter.WELLE_FIX_SET == (
        (1, "v907_verify", "WAKIR_V907_VERIFY_BACKEND"),
        (
            2,
            "svid_workload_identity",
            "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND",
        ),
    )


# ---------------------------------------------------------------------------
# 3. Path resolution
# ---------------------------------------------------------------------------


def test_resolve_paths_priority_order_cli_env_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """CLI flag wins over ENV; first ENV beats second; absent yields None."""

    cli = tmp_path / "cli.jsonl"
    env1 = tmp_path / "env1.jsonl"
    env2 = tmp_path / "env2.jsonl"

    monkeypatch.setenv(emitter.ENV_PHASE_3C_OBS_BASELINE_PATH, str(env1))
    monkeypatch.setenv(emitter.ENV_BACKEND_DECISION_JSONL, str(env2))
    assert emitter.resolve_decisions_jsonl_path(str(cli)) == cli

    assert emitter.resolve_decisions_jsonl_path(None) == env1
    monkeypatch.delenv(emitter.ENV_PHASE_3C_OBS_BASELINE_PATH)
    assert emitter.resolve_decisions_jsonl_path(None) == env2
    monkeypatch.delenv(emitter.ENV_BACKEND_DECISION_JSONL)
    assert emitter.resolve_decisions_jsonl_path(None) is None

    stress = tmp_path / "stress.json"
    monkeypatch.setenv(emitter.ENV_PHASE_2_STRESS_OUTPUT, str(stress))
    assert emitter.resolve_phase2_stress_path(None) == stress
    monkeypatch.delenv(emitter.ENV_PHASE_2_STRESS_OUTPUT)
    assert emitter.resolve_phase2_stress_path(None) is None

    lc = tmp_path / "lc.json"
    monkeypatch.setenv(emitter.ENV_PHASE_3C_WELLE_LIFECYCLE, str(lc))
    assert emitter.resolve_lifecycle_path(None) == lc


# ---------------------------------------------------------------------------
# 4. Ingest window
# ---------------------------------------------------------------------------


def test_ingest_window_for_domain_filters_by_domain_and_time(tmp_path: Path):
    """Each welle's window scan is independent."""

    now = _now()
    inside = now - timedelta(seconds=60)
    outside = now - timedelta(seconds=600)

    path = tmp_path / "decisions.jsonl"
    _seed_jsonl(
        path,
        [
            # Welle-1 (v907_verify): 2 rust, 1 python, 1 fallback inside window
            _decision(domain="v907_verify", chosen_backend="rust", ts=inside),
            _decision(domain="v907_verify", chosen_backend="rust", ts=inside),
            _decision(
                domain="v907_verify", chosen_backend="python", ts=inside
            ),
            _decision(
                domain="v907_verify",
                chosen_backend="rust",
                fallback_reason="binary_missing",
                ts=inside,
            ),
            # Welle-1 outside window -> dropped
            _decision(domain="v907_verify", chosen_backend="rust", ts=outside),
            # Welle-2 (svid_workload_identity): 3 rust, 0 python inside
            _decision(
                domain="svid_workload_identity",
                chosen_backend="rust",
                ts=inside,
            ),
            _decision(
                domain="svid_workload_identity",
                chosen_backend="rust",
                ts=inside,
            ),
            _decision(
                domain="svid_workload_identity",
                chosen_backend="rust",
                ts=inside,
            ),
            # Welle-3 (bridge_audit_writer): NOT in doppel — must be dropped
            _decision(
                domain="bridge_audit_writer",
                chosen_backend="rust",
                ts=inside,
            ),
        ],
    )

    c1, parse_err1 = emitter.ingest_window_for_domain(
        path, domain="v907_verify", window_seconds=300, now=now
    )
    assert c1.python_count == 1
    assert c1.rust_count == 2
    assert c1.fallback_count == 1
    assert c1.total == 4
    assert parse_err1 == 0

    c2, parse_err2 = emitter.ingest_window_for_domain(
        path,
        domain="svid_workload_identity",
        window_seconds=300,
        now=now,
    )
    assert c2.python_count == 0
    assert c2.rust_count == 3
    assert c2.fallback_count == 0
    assert c2.total == 3
    assert parse_err2 == 0

    # Welle-3 records were correctly filtered out of Welle-1 / Welle-2 scans.
    c3_check, _ = emitter.ingest_window_for_domain(
        path,
        domain="bridge_audit_writer",
        window_seconds=300,
        now=now,
    )
    assert c3_check.rust_count == 1

    # Absent file -> zeros, no error.
    cz, pe = emitter.ingest_window_for_domain(
        tmp_path / "missing.jsonl",
        domain="v907_verify",
        window_seconds=300,
        now=now,
    )
    assert cz.total == 0
    assert pe == 0

    # Malformed line bumps parse_errors but does not crash.
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not-json\n")
    _, pe2 = emitter.ingest_window_for_domain(
        path, domain="v907_verify", window_seconds=300, now=now
    )
    assert pe2 == 1


# ---------------------------------------------------------------------------
# 5. Consistency score
# ---------------------------------------------------------------------------


def test_compute_consistency_score_handles_empty_and_mixed():
    """No traffic -> None; pure rust -> 100; mixed -> ratio."""

    assert emitter.compute_consistency_score_pct(emitter.WindowCounts()) is None
    assert (
        emitter.compute_consistency_score_pct(
            emitter.WindowCounts(rust_count=10)
        )
        == 100.0
    )
    mixed = emitter.WindowCounts(
        python_count=2, rust_count=6, fallback_count=2
    )
    # rust/total = 6/10 = 60.0
    assert emitter.compute_consistency_score_pct(mixed) == 60.0


# ---------------------------------------------------------------------------
# 6. Stress oracles (per-welle + legacy fallback)
# ---------------------------------------------------------------------------


def test_load_stress_oracles_per_welle_schema_and_legacy_fallback(
    tmp_path: Path,
):
    """Per-welle entries are honored; legacy root-level falls back to both."""

    # None path -> YELLOW for both welles, distinct reason.
    res = emitter.load_stress_oracles(None)
    assert set(res.keys()) == {1, 2}
    assert all(
        o.status == emitter.StressOracleStatus.YELLOW for o in res.values()
    )
    assert all("not-configured" in o.reason for o in res.values())

    # Missing file -> YELLOW for both with file-not-found reason.
    res = emitter.load_stress_oracles(tmp_path / "missing.json")
    assert all(
        "file-not-found" in o.reason for o in res.values()
    )

    # Preferred schema: per-welle entries.
    p = tmp_path / "stress.json"
    _write_json(
        p,
        {
            "per_welle": {
                "1": {
                    "cross_modul_stress_status": "pass",
                    "cross_modul_stress_score_pct": 99.7,
                },
                "2": {
                    "cross_modul_stress_status": "fail",
                    "cross_modul_stress_score_pct": 88.2,
                },
            }
        },
    )
    res = emitter.load_stress_oracles(p)
    assert res[1].status == emitter.StressOracleStatus.GREEN
    assert res[1].score_pct == 99.7
    assert res[2].status == emitter.StressOracleStatus.RED
    assert res[2].score_pct == 88.2

    # Per-welle schema with missing Welle-2 entry -> Welle-2 falls back to YELLOW
    _write_json(
        p,
        {
            "per_welle": {
                "1": {
                    "cross_modul_stress_status": "pass",
                    "cross_modul_stress_score_pct": 100.0,
                }
            }
        },
    )
    res = emitter.load_stress_oracles(p)
    assert res[1].status == emitter.StressOracleStatus.GREEN
    assert res[2].status == emitter.StressOracleStatus.YELLOW
    assert "welle-entry-missing" in res[2].reason

    # Legacy root-level fallback: applies same status to both welles.
    _write_json(
        p,
        {
            "cross_modul_stress_status": "pass",
            "cross_modul_stress_score_pct": 97.0,
        },
    )
    res = emitter.load_stress_oracles(p)
    assert res[1].status == emitter.StressOracleStatus.GREEN
    assert res[2].status == emitter.StressOracleStatus.GREEN
    assert res[1].score_pct == 97.0
    assert res[2].score_pct == 97.0

    # Malformed JSON -> YELLOW for both with parse-error reason.
    p.write_text("{not-json", encoding="utf-8")
    res = emitter.load_stress_oracles(p)
    assert all(
        o.status == emitter.StressOracleStatus.YELLOW for o in res.values()
    )
    assert all("parse-error" in o.reason for o in res.values())

    # NaN/non-numeric score in per-welle entry -> score None, status preserved.
    p.write_text(
        json.dumps(
            {
                "per_welle": {
                    "1": {
                        "cross_modul_stress_status": "pass",
                        "cross_modul_stress_score_pct": "not-a-number",
                    },
                    "2": {
                        "cross_modul_stress_status": "skipped",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    res = emitter.load_stress_oracles(p)
    assert res[1].status == emitter.StressOracleStatus.GREEN
    assert res[1].score_pct is None
    assert res[2].status == emitter.StressOracleStatus.YELLOW
    assert res[2].score_pct is None


# ---------------------------------------------------------------------------
# 7. Lifecycle
# ---------------------------------------------------------------------------


def test_load_welle_lifecycle_string_and_int_keys(tmp_path: Path):
    """Lifecycle override accepts string and int keys; degrades safely."""

    # Absent -> both PRE_CUTOVER
    res = emitter.load_welle_lifecycle(None)
    assert res[1] == emitter.WelleState.PRE_CUTOVER
    assert res[2] == emitter.WelleState.PRE_CUTOVER

    # Mixed states (both string keys).
    p = tmp_path / "lc.json"
    _write_json(p, {"1": "in_cutover", "2": "post_cutover"})
    res = emitter.load_welle_lifecycle(p)
    assert res[1] == emitter.WelleState.IN_CUTOVER
    assert res[2] == emitter.WelleState.POST_CUTOVER

    # Missing welle key -> PRE_CUTOVER for that welle.
    _write_json(p, {"1": "rollback_active"})
    res = emitter.load_welle_lifecycle(p)
    assert res[1] == emitter.WelleState.ROLLBACK_ACTIVE
    assert res[2] == emitter.WelleState.PRE_CUTOVER

    # Bad value -> PRE_CUTOVER (safe degrade).
    _write_json(p, {"1": "garbage", "2": "welle_complete"})
    res = emitter.load_welle_lifecycle(p)
    assert res[1] == emitter.WelleState.PRE_CUTOVER
    assert res[2] == emitter.WelleState.WELLE_COMPLETE

    # Malformed JSON -> both PRE_CUTOVER (safe degrade).
    p.write_text("{not-json", encoding="utf-8")
    res = emitter.load_welle_lifecycle(p)
    assert res[1] == emitter.WelleState.PRE_CUTOVER
    assert res[2] == emitter.WelleState.PRE_CUTOVER


# ---------------------------------------------------------------------------
# 8. Combined health-score + aktiv-count
# ---------------------------------------------------------------------------


def test_build_snapshot_combined_health_score_and_aktiv_count(tmp_path: Path):
    """Combined score = min(per-welle scores); aktiv-count = sum of in_cutover."""

    now = _now()
    inside = now - timedelta(seconds=30)

    decisions = tmp_path / "d.jsonl"
    _seed_jsonl(
        decisions,
        # Welle-1: 9 rust + 1 python -> 90%
        [
            _decision(domain="v907_verify", chosen_backend="rust", ts=inside)
            for _ in range(9)
        ]
        + [
            _decision(
                domain="v907_verify", chosen_backend="python", ts=inside
            )
        ]
        # Welle-2: 10 rust -> 100%
        + [
            _decision(
                domain="svid_workload_identity",
                chosen_backend="rust",
                ts=inside,
            )
            for _ in range(10)
        ],
    )
    stress = tmp_path / "s.json"
    _write_json(
        stress,
        {
            "per_welle": {
                "1": {
                    "cross_modul_stress_status": "pass",
                    "cross_modul_stress_score_pct": 90.0,
                },
                "2": {
                    "cross_modul_stress_status": "pass",
                    "cross_modul_stress_score_pct": 100.0,
                },
            }
        },
    )
    lifecycle = tmp_path / "lc.json"
    _write_json(lifecycle, {"1": "in_cutover", "2": "in_cutover"})

    snap = emitter.build_snapshot(
        decisions_path=decisions,
        phase2_stress_path=stress,
        lifecycle_path=lifecycle,
        now=now,
    )
    assert snap.welles[0].consistency_score_pct == 90.0
    assert snap.welles[1].consistency_score_pct == 100.0
    # Combined = min(90, 100) = 90.
    assert snap.combined_health_score_pct == 90.0
    # Both welles in_cutover -> pair_aktiv_count = 2
    assert snap.pair_aktiv_count == 2
    assert snap.welles[0].welle_aktiv is True
    assert snap.welles[1].welle_aktiv is True
    # No red-flags (divergence 0 vs oracle).
    assert snap.combined_red_flag is False
    assert snap.combined_red_flag_reason == "ok"
    # Schema preamble fields.
    assert snap.schema_id == emitter.SCHEMA_ID
    assert snap.pair_label == "1+2"
    assert snap.divergence_threshold_pct == 0.5


# ---------------------------------------------------------------------------
# 9. Per-welle independent red-flags
# ---------------------------------------------------------------------------


def test_build_snapshot_per_welle_independent_red_flags(tmp_path: Path):
    """A red Welle-2 must not falsely red-flag a green Welle-1."""

    now = _now()
    inside = now - timedelta(seconds=30)

    decisions = tmp_path / "d.jsonl"
    _seed_jsonl(
        decisions,
        # Welle-1: 100% rust (green vs oracle 100)
        [
            _decision(domain="v907_verify", chosen_backend="rust", ts=inside)
            for _ in range(10)
        ]
        # Welle-2: 90% rust (vs oracle 99 -> divergence 9pp, > 0.5pp)
        + [
            _decision(
                domain="svid_workload_identity",
                chosen_backend="rust",
                ts=inside,
            )
            for _ in range(9)
        ]
        + [
            _decision(
                domain="svid_workload_identity",
                chosen_backend="python",
                ts=inside,
            )
        ],
    )
    stress = tmp_path / "s.json"
    _write_json(
        stress,
        {
            "per_welle": {
                "1": {
                    "cross_modul_stress_status": "pass",
                    "cross_modul_stress_score_pct": 100.0,
                },
                "2": {
                    "cross_modul_stress_status": "pass",
                    "cross_modul_stress_score_pct": 99.0,
                },
            }
        },
    )

    snap = emitter.build_snapshot(
        decisions_path=decisions,
        phase2_stress_path=stress,
        lifecycle_path=None,
        now=now,
    )
    # Welle-1: green
    assert snap.welles[0].consistency_score_pct == 100.0
    assert snap.welles[0].divergence_pct == 0.0
    assert snap.welles[0].divergence_red_flag is False
    assert snap.welles[0].red_flag_reason == "ok"
    # Welle-2: red
    assert snap.welles[1].consistency_score_pct == 90.0
    assert snap.welles[1].divergence_pct == 9.0
    assert snap.welles[1].divergence_red_flag is True
    assert "divergence-9.0000pct" in snap.welles[1].red_flag_reason
    assert "threshold-0.5000pct" in snap.welles[1].red_flag_reason

    # Combined red-flag fires; reason cites Welle-2 specifically.
    assert snap.combined_red_flag is True
    assert snap.combined_red_flag_reason == "welle-2-red-flag"

    # Stress-oracle hard-fail also triggers per-welle red-flag (even if
    # divergence is below threshold).
    _write_json(
        stress,
        {
            "per_welle": {
                "1": {
                    "cross_modul_stress_status": "fail",
                    "cross_modul_stress_score_pct": 100.0,
                },
                "2": {
                    "cross_modul_stress_status": "pass",
                    "cross_modul_stress_score_pct": 99.0,
                },
            }
        },
    )
    snap2 = emitter.build_snapshot(
        decisions_path=decisions,
        phase2_stress_path=stress,
        lifecycle_path=None,
        now=now,
    )
    # Welle-1 self-score 100 vs oracle 100 -> divergence 0, but
    # oracle status RED forces the red-flag.
    assert snap2.welles[0].divergence_red_flag is True
    assert snap2.welles[0].red_flag_reason == "stress-oracle-status-fail"
    # Welle-2 still red from divergence.
    assert snap2.welles[1].divergence_red_flag is True
    # Combined reason cites both welles.
    assert snap2.combined_red_flag_reason == "welle-1+2-red-flag"


# ---------------------------------------------------------------------------
# 10. Inputs missing => no red-flag, distinct reasons
# ---------------------------------------------------------------------------


def test_build_snapshot_no_red_flag_when_inputs_missing(tmp_path: Path):
    """Missing decisions or oracle -> red_flag False, reason explains."""

    now = _now()

    # All inputs absent: no traffic, no oracle, no lifecycle.
    snap = emitter.build_snapshot(
        decisions_path=None,
        phase2_stress_path=None,
        lifecycle_path=None,
        now=now,
    )
    for wt in snap.welles:
        assert wt.consistency_score_pct is None
        assert wt.stress_oracle.status == emitter.StressOracleStatus.YELLOW
        assert wt.divergence_pct is None
        assert wt.divergence_red_flag is False
        assert wt.red_flag_reason == "consistency-score-no-traffic-in-window"
    assert snap.combined_health_score_pct is None
    assert snap.combined_red_flag is False
    assert snap.combined_red_flag_reason == "ok"
    assert snap.pair_aktiv_count == 0

    # Decisions present (so per-welle scores computed), oracle missing.
    inside = now - timedelta(seconds=30)
    decisions = tmp_path / "d.jsonl"
    _seed_jsonl(
        decisions,
        [
            _decision(domain="v907_verify", chosen_backend="rust", ts=inside)
            for _ in range(5)
        ]
        + [
            _decision(
                domain="svid_workload_identity",
                chosen_backend="rust",
                ts=inside,
            )
            for _ in range(5)
        ],
    )
    snap = emitter.build_snapshot(
        decisions_path=decisions,
        phase2_stress_path=None,
        lifecycle_path=None,
        now=now,
    )
    for wt in snap.welles:
        assert wt.consistency_score_pct == 100.0
        assert wt.stress_oracle.score_pct is None
        assert wt.divergence_pct is None
        assert wt.divergence_red_flag is False
        assert wt.red_flag_reason == "stress-oracle-score-missing"
    # Combined score = min(100, 100) = 100, no red-flag.
    assert snap.combined_health_score_pct == 100.0
    assert snap.combined_red_flag is False


# ---------------------------------------------------------------------------
# 11. Prometheus textfile
# ---------------------------------------------------------------------------


def test_render_prometheus_textfile_emits_per_welle_and_combined_metrics(
    tmp_path: Path,
):
    """All metric names appear; per-welle labels stable; combined pair label present."""

    now = _now()
    inside = now - timedelta(seconds=15)
    decisions = tmp_path / "d.jsonl"
    _seed_jsonl(
        decisions,
        [
            _decision(domain="v907_verify", chosen_backend="rust", ts=inside)
            for _ in range(8)
        ]
        + [
            _decision(
                domain="v907_verify", chosen_backend="python", ts=inside
            )
            for _ in range(2)
        ]
        + [
            _decision(
                domain="svid_workload_identity",
                chosen_backend="rust",
                ts=inside,
            )
            for _ in range(7)
        ]
        + [
            _decision(
                domain="svid_workload_identity",
                chosen_backend="python",
                ts=inside,
            )
            for _ in range(3)
        ],
    )
    stress = tmp_path / "s.json"
    _write_json(
        stress,
        {
            "per_welle": {
                "1": {
                    "cross_modul_stress_status": "pass",
                    "cross_modul_stress_score_pct": 80.0,
                },
                "2": {
                    "cross_modul_stress_status": "pass",
                    "cross_modul_stress_score_pct": 70.0,
                },
            }
        },
    )
    lifecycle = tmp_path / "lc.json"
    _write_json(lifecycle, {"1": "in_cutover", "2": "rollback_active"})

    snap = emitter.build_snapshot(
        decisions_path=decisions,
        phase2_stress_path=stress,
        lifecycle_path=lifecycle,
        now=now,
    )
    text = emitter.render_prometheus_textfile(snap)

    per_welle_metrics = [
        "persona_engine_doppel_welle_consistency_score",
        "persona_engine_doppel_welle_stress_oracle_score",
        "persona_engine_doppel_welle_divergence_pct",
        "persona_engine_doppel_welle_divergence_red_flag",
        "persona_engine_doppel_welle_window_python_count",
        "persona_engine_doppel_welle_window_rust_count",
        "persona_engine_doppel_welle_window_fallback_count",
        "persona_engine_doppel_welle_window_seconds",
        "persona_engine_doppel_welle_tick_interval_seconds",
        "persona_engine_doppel_welle_divergence_threshold_pct",
        "persona_engine_doppel_welle_aktiv",
    ]
    for name in per_welle_metrics:
        assert name in text, f"missing per-welle metric: {name}"
        assert f"# HELP {name} " in text, f"missing HELP for: {name}"
        assert f"# TYPE {name} gauge" in text, f"missing TYPE for: {name}"

    combined_metrics = [
        "persona_engine_doppel_welle_combined_health_score",
        "persona_engine_doppel_welle_combined_red_flag",
        "persona_engine_doppel_welle_pair_aktiv_count",
    ]
    for name in combined_metrics:
        assert name in text, f"missing combined metric: {name}"
        assert f"# HELP {name} " in text, f"missing HELP for: {name}"

    # Both welle labels render.
    assert 'welle="1"' in text
    assert 'welle="2"' in text
    assert 'domain="v907_verify"' in text
    assert 'domain="svid_workload_identity"' in text
    # Pair label on combined metrics.
    assert 'pair="1+2"' in text
    # Aktiv state labels render.
    assert 'state="in_cutover"' in text
    assert 'state="rollback_active"' in text

    # Per-welle consistency-score sample appears for each welle.
    cs_lines = [
        ln
        for ln in text.splitlines()
        if ln.startswith("persona_engine_doppel_welle_consistency_score{")
    ]
    assert len(cs_lines) == 2, f"expected 2 consistency samples, got: {cs_lines}"

    # Pair-aktiv-count is exactly 2 since both welles are in_cutover/rollback.
    paktiv_lines = [
        ln
        for ln in text.splitlines()
        if ln.startswith("persona_engine_doppel_welle_pair_aktiv_count{")
    ]
    assert len(paktiv_lines) == 1
    assert paktiv_lines[0].endswith(" 2")


# ---------------------------------------------------------------------------
# 12. CLI green path
# ---------------------------------------------------------------------------


def test_main_cli_writes_out_and_prom_textfile_returns_zero_when_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """No red-flag -> exit 0, both output files written."""

    now = _now()
    inside = now - timedelta(seconds=15)
    decisions = tmp_path / "d.jsonl"
    _seed_jsonl(
        decisions,
        [
            _decision(domain="v907_verify", chosen_backend="rust", ts=inside)
            for _ in range(10)
        ]
        + [
            _decision(
                domain="svid_workload_identity",
                chosen_backend="rust",
                ts=inside,
            )
            for _ in range(10)
        ],
    )
    stress = tmp_path / "s.json"
    _write_json(
        stress,
        {
            "per_welle": {
                "1": {
                    "cross_modul_stress_status": "pass",
                    "cross_modul_stress_score_pct": 100.0,
                },
                "2": {
                    "cross_modul_stress_status": "pass",
                    "cross_modul_stress_score_pct": 100.0,
                },
            }
        },
    )
    out = tmp_path / "snap.json"
    prom = tmp_path / "snap.prom"

    for k in (
        emitter.ENV_PHASE_3C_OBS_BASELINE_PATH,
        emitter.ENV_BACKEND_DECISION_JSONL,
        emitter.ENV_PHASE_2_STRESS_OUTPUT,
        emitter.ENV_PHASE_3C_WELLE_LIFECYCLE,
    ):
        monkeypatch.delenv(k, raising=False)

    rc = emitter.main(
        [
            "--decisions-jsonl",
            str(decisions),
            "--phase2-stress-json",
            str(stress),
            "--out",
            str(out),
            "--prom-textfile",
            str(prom),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_id"] == emitter.SCHEMA_ID
    assert payload["pair_label"] == "1+2"
    assert len(payload["welles"]) == 2
    assert payload["welles"][0]["welle"] == 1
    assert payload["welles"][0]["domain"] == "v907_verify"
    assert payload["welles"][1]["welle"] == 2
    assert payload["welles"][1]["domain"] == "svid_workload_identity"
    assert payload["combined_health_score_pct"] == 100.0
    assert payload["combined_red_flag"] is False
    assert payload["doppel_welle_cap"] == 2

    prom_text = prom.read_text(encoding="utf-8")
    assert "persona_engine_doppel_welle_consistency_score" in prom_text
    assert 'pair="1+2"' in prom_text


# ---------------------------------------------------------------------------
# 13. CLI red-flag + bad-input paths
# ---------------------------------------------------------------------------


def test_main_cli_returns_one_on_any_red_flag_and_two_on_bad_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Any welle red-flag -> exit 1; malformed CLI args -> exit 2."""

    now = _now()
    inside = now - timedelta(seconds=15)
    decisions = tmp_path / "d.jsonl"
    _seed_jsonl(
        decisions,
        # Welle-1 90% (vs oracle 99 -> 9pp red-flag)
        [
            _decision(domain="v907_verify", chosen_backend="rust", ts=inside)
            for _ in range(9)
        ]
        + [
            _decision(
                domain="v907_verify", chosen_backend="python", ts=inside
            )
        ]
        # Welle-2 100% (green vs oracle 100)
        + [
            _decision(
                domain="svid_workload_identity",
                chosen_backend="rust",
                ts=inside,
            )
            for _ in range(10)
        ],
    )
    stress = tmp_path / "s.json"
    _write_json(
        stress,
        {
            "per_welle": {
                "1": {
                    "cross_modul_stress_status": "pass",
                    "cross_modul_stress_score_pct": 99.0,
                },
                "2": {
                    "cross_modul_stress_status": "pass",
                    "cross_modul_stress_score_pct": 100.0,
                },
            }
        },
    )
    out = tmp_path / "snap.json"

    for k in (
        emitter.ENV_PHASE_3C_OBS_BASELINE_PATH,
        emitter.ENV_BACKEND_DECISION_JSONL,
        emitter.ENV_PHASE_2_STRESS_OUTPUT,
        emitter.ENV_PHASE_3C_WELLE_LIFECYCLE,
    ):
        monkeypatch.delenv(k, raising=False)

    rc = emitter.main(
        [
            "--decisions-jsonl",
            str(decisions),
            "--phase2-stress-json",
            str(stress),
            "--out",
            str(out),
        ]
    )
    assert rc == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["combined_red_flag"] is True
    # Welle-1 red, Welle-2 green
    assert payload["welles"][0]["divergence_red_flag"] is True
    assert payload["welles"][1]["divergence_red_flag"] is False
    assert payload["combined_red_flag_reason"] == "welle-1-red-flag"

    # Bad CLI params -> exit 2.
    assert emitter.main(["--tick-interval-seconds", "0"]) == 2
    assert emitter.main(["--window-seconds", "-5"]) == 2
    assert emitter.main(["--divergence-threshold-pct", "-1"]) == 2
