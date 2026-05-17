# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/welle-3-telemetry-emitter.py — Tag-31 Mini-Welle.

Hermetic, stdlib + pytest only. Loads the emitter via importlib from
its hyphenated path under ``scripts/``. JSONL inputs are written to
``tmp_path`` fixtures. No network, no live Prometheus, no podman.

The emitter is the Welle-3-specific high-frequency telemetry
substrate behind the Phase-3c welle-status dashboard's Welle-3
panels (ADR-0066 Mitigation-2). It reads the same BackendDecision
JSONL the Tag-22/25/30 scripts consult, plus an optional
operator-hand lifecycle override and an optional Phase-2 cross-modul
stress-test output JSON.

Scope (12 tests)
----------------

1.  test_module_loads_and_exports_public_surface
2.  test_resolve_paths_priority_order_cli_env_none
3.  test_ingest_window_filters_by_domain_and_time
4.  test_compute_consistency_score_none_when_window_empty
5.  test_load_stress_oracle_tri_state_and_score_pct
6.  test_load_welle_3_lifecycle_string_and_int_keys
7.  test_build_snapshot_red_flag_on_divergence_exceeds_threshold
8.  test_build_snapshot_red_flag_on_stress_oracle_fail
9.  test_build_snapshot_no_red_flag_when_inputs_missing
10. test_render_prometheus_textfile_emits_stable_metric_names
11. test_main_cli_writes_out_and_prom_textfile_returns_zero_when_green
12. test_main_cli_returns_one_on_divergence_red_flag
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest


# ---------------------------------------------------------------------------
# Module loader (hyphenated filename -> importlib.util)
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
EMITTER_PATH = REPO_ROOT / "scripts" / "welle-3-telemetry-emitter.py"


def _load_emitter_module():
    spec = importlib.util.spec_from_file_location(
        "welle_3_telemetry_emitter", EMITTER_PATH
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
    return datetime(2026, 5, 17, 23, 0, 0, tzinfo=timezone.utc)


def _decision(
    *,
    domain: str = "bridge_audit_writer",
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
        "Welle3TelemetrySnapshot",
        "SCHEMA_ID",
        "WELLE_NUMBER",
        "WELLE_DOMAIN",
        "WELLE_ENV_VAR",
        "DOPPEL_WELLE_CAP",
        "DEFAULT_TICK_INTERVAL_SECONDS",
        "DEFAULT_WINDOW_SECONDS",
        "DEFAULT_DIVERGENCE_THRESHOLD_PCT",
        "ENV_PHASE_3C_OBS_BASELINE_PATH",
        "ENV_BACKEND_DECISION_JSONL",
        "ENV_PHASE_2_STRESS_OUTPUT",
        "ENV_PHASE_3C_WELLE_LIFECYCLE",
        "resolve_decisions_jsonl_path",
        "resolve_phase2_stress_path",
        "resolve_lifecycle_path",
        "ingest_window",
        "compute_consistency_score_pct",
        "load_stress_oracle",
        "load_welle_3_lifecycle",
        "build_snapshot",
        "render_prometheus_textfile",
        "build_parser",
        "main",
    ]
    for name in expected:
        assert hasattr(emitter, name), f"missing public surface: {name}"

    assert emitter.WELLE_NUMBER == 3
    assert emitter.WELLE_DOMAIN == "bridge_audit_writer"
    assert emitter.WELLE_ENV_VAR == "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND"
    assert emitter.DOPPEL_WELLE_CAP == 2
    assert emitter.DEFAULT_TICK_INTERVAL_SECONDS == 10
    assert emitter.DEFAULT_WINDOW_SECONDS == 300
    assert emitter.DEFAULT_DIVERGENCE_THRESHOLD_PCT == 0.5
    assert emitter.SCHEMA_ID == "wakir.persona-engine.welle-3-telemetry.v1"


# ---------------------------------------------------------------------------
# 2. Path resolution
# ---------------------------------------------------------------------------


def test_resolve_paths_priority_order_cli_env_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """CLI flag wins over ENV; first ENV beats second; absent yields None."""

    cli = tmp_path / "cli.jsonl"
    env1 = tmp_path / "env1.jsonl"
    env2 = tmp_path / "env2.jsonl"

    # CLI wins
    monkeypatch.setenv(emitter.ENV_PHASE_3C_OBS_BASELINE_PATH, str(env1))
    monkeypatch.setenv(emitter.ENV_BACKEND_DECISION_JSONL, str(env2))
    assert emitter.resolve_decisions_jsonl_path(str(cli)) == cli

    # ENV-1 beats ENV-2
    assert emitter.resolve_decisions_jsonl_path(None) == env1

    # Drop ENV-1 -> ENV-2 wins
    monkeypatch.delenv(emitter.ENV_PHASE_3C_OBS_BASELINE_PATH)
    assert emitter.resolve_decisions_jsonl_path(None) == env2

    # Drop both -> None
    monkeypatch.delenv(emitter.ENV_BACKEND_DECISION_JSONL)
    assert emitter.resolve_decisions_jsonl_path(None) is None

    # Stress + lifecycle resolution mirror the same shape
    stress = tmp_path / "stress.json"
    monkeypatch.setenv(emitter.ENV_PHASE_2_STRESS_OUTPUT, str(stress))
    assert emitter.resolve_phase2_stress_path(None) == stress
    monkeypatch.delenv(emitter.ENV_PHASE_2_STRESS_OUTPUT)
    assert emitter.resolve_phase2_stress_path(None) is None

    lc = tmp_path / "lc.json"
    monkeypatch.setenv(emitter.ENV_PHASE_3C_WELLE_LIFECYCLE, str(lc))
    assert emitter.resolve_lifecycle_path(None) == lc


# ---------------------------------------------------------------------------
# 3. Ingest window
# ---------------------------------------------------------------------------


def test_ingest_window_filters_by_domain_and_time(tmp_path: Path):
    """Only Welle-3 records inside the window are counted."""

    now = _now()
    inside = now - timedelta(seconds=60)
    outside = now - timedelta(seconds=600)

    path = tmp_path / "decisions.jsonl"
    _seed_jsonl(
        path,
        [
            # in-window, Welle-3, rust -> rust_count++
            _decision(chosen_backend="rust", ts=inside),
            _decision(chosen_backend="rust", ts=inside),
            # in-window, Welle-3, python -> python_count++
            _decision(chosen_backend="python", ts=inside),
            # in-window, Welle-3, fallback -> fallback_count++
            _decision(
                chosen_backend="rust",
                fallback_reason="binary_missing",
                ts=inside,
            ),
            # in-window, but WRONG domain -> dropped
            _decision(domain="v907_verify", ts=inside),
            # Welle-3, but OUTSIDE window -> dropped
            _decision(chosen_backend="rust", ts=outside),
        ],
    )

    counts, parse_errors = emitter.ingest_window(
        path, window_seconds=300, now=now
    )
    assert counts.python_count == 1
    assert counts.rust_count == 2
    assert counts.fallback_count == 1
    assert counts.total == 4
    assert parse_errors == 0

    # Malformed line bumps parse_errors but does not crash
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not-json\n")
    counts2, parse_errors2 = emitter.ingest_window(
        path, window_seconds=300, now=now
    )
    assert parse_errors2 == 1
    assert counts2.total == 4

    # Absent file -> zero counts, no error
    counts3, parse_errors3 = emitter.ingest_window(
        tmp_path / "missing.jsonl", window_seconds=300, now=now
    )
    assert counts3.total == 0
    assert parse_errors3 == 0


# ---------------------------------------------------------------------------
# 4. Consistency score
# ---------------------------------------------------------------------------


def test_compute_consistency_score_none_when_window_empty():
    """No traffic -> None (the 'no-signal' condition)."""

    empty = emitter.WindowCounts()
    assert emitter.compute_consistency_score_pct(empty) is None

    # Pure rust window -> 100 percent
    pure_rust = emitter.WindowCounts(rust_count=10)
    assert emitter.compute_consistency_score_pct(pure_rust) == 100.0

    # Mixed window -> ratio
    mixed = emitter.WindowCounts(
        python_count=1, rust_count=8, fallback_count=1
    )
    assert emitter.compute_consistency_score_pct(mixed) == 80.0


# ---------------------------------------------------------------------------
# 5. Stress oracle
# ---------------------------------------------------------------------------


def test_load_stress_oracle_tri_state_and_score_pct(tmp_path: Path):
    """pass -> GREEN, fail -> RED, skipped/missing -> YELLOW."""

    # None path -> YELLOW with reason
    o = emitter.load_stress_oracle(None)
    assert o.status == emitter.StressOracleStatus.YELLOW
    assert o.score_pct is None
    assert "not-configured" in o.reason

    # Missing file -> YELLOW
    o = emitter.load_stress_oracle(tmp_path / "missing.json")
    assert o.status == emitter.StressOracleStatus.YELLOW
    assert "file-not-found" in o.reason

    # pass
    p = tmp_path / "pass.json"
    _write_json(
        p,
        {
            "cross_modul_stress_status": "pass",
            "cross_modul_stress_score_pct": 99.7,
        },
    )
    o = emitter.load_stress_oracle(p)
    assert o.status == emitter.StressOracleStatus.GREEN
    assert o.score_pct == 99.7

    # fail
    f = tmp_path / "fail.json"
    _write_json(
        f,
        {
            "cross_modul_stress_status": "fail",
            "cross_modul_stress_score_pct": 88.2,
        },
    )
    o = emitter.load_stress_oracle(f)
    assert o.status == emitter.StressOracleStatus.RED
    assert o.score_pct == 88.2

    # skipped, score absent -> YELLOW, score None
    s = tmp_path / "skipped.json"
    _write_json(s, {"cross_modul_stress_status": "skipped"})
    o = emitter.load_stress_oracle(s)
    assert o.status == emitter.StressOracleStatus.YELLOW
    assert o.score_pct is None

    # Malformed JSON -> YELLOW
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")
    o = emitter.load_stress_oracle(bad)
    assert o.status == emitter.StressOracleStatus.YELLOW
    assert "parse-error" in o.reason

    # Unknown status -> YELLOW
    u = tmp_path / "unknown.json"
    _write_json(u, {"cross_modul_stress_status": "ufo"})
    o = emitter.load_stress_oracle(u)
    assert o.status == emitter.StressOracleStatus.YELLOW

    # NaN / inf score -> None
    n = tmp_path / "nan.json"
    n.write_text(
        '{"cross_modul_stress_status": "pass", "cross_modul_stress_score_pct": "not-a-number"}',
        encoding="utf-8",
    )
    o = emitter.load_stress_oracle(n)
    assert o.status == emitter.StressOracleStatus.GREEN
    assert o.score_pct is None


# ---------------------------------------------------------------------------
# 6. Lifecycle
# ---------------------------------------------------------------------------


def test_load_welle_3_lifecycle_string_and_int_keys(tmp_path: Path):
    """Lifecycle override accepts string and int '3' keys; degrades safely."""

    # Absent -> PRE_CUTOVER
    assert (
        emitter.load_welle_3_lifecycle(None)
        == emitter.WelleState.PRE_CUTOVER
    )

    # String key
    p = tmp_path / "lc.json"
    _write_json(p, {"3": "in_cutover"})
    assert (
        emitter.load_welle_3_lifecycle(p)
        == emitter.WelleState.IN_CUTOVER
    )

    # Rollback active
    _write_json(p, {"3": "rollback_active"})
    assert (
        emitter.load_welle_3_lifecycle(p)
        == emitter.WelleState.ROLLBACK_ACTIVE
    )

    # No welle-3 key -> PRE_CUTOVER
    _write_json(p, {"1": "in_cutover"})
    assert (
        emitter.load_welle_3_lifecycle(p)
        == emitter.WelleState.PRE_CUTOVER
    )

    # Bad value -> PRE_CUTOVER (safe degrade)
    _write_json(p, {"3": "garbage"})
    assert (
        emitter.load_welle_3_lifecycle(p)
        == emitter.WelleState.PRE_CUTOVER
    )

    # Malformed JSON -> PRE_CUTOVER (safe degrade)
    p.write_text("{not-json", encoding="utf-8")
    assert (
        emitter.load_welle_3_lifecycle(p)
        == emitter.WelleState.PRE_CUTOVER
    )


# ---------------------------------------------------------------------------
# 7. Divergence red-flag
# ---------------------------------------------------------------------------


def test_build_snapshot_red_flag_on_divergence_exceeds_threshold(
    tmp_path: Path,
):
    """Divergence > threshold -> red-flag set with diagnostic reason."""

    now = _now()
    inside = now - timedelta(seconds=30)

    # Build a window where rust_count/total = 95%
    decisions = tmp_path / "d.jsonl"
    records = [_decision(chosen_backend="rust", ts=inside) for _ in range(19)]
    records.append(_decision(chosen_backend="python", ts=inside))
    _seed_jsonl(decisions, records)

    # Stress oracle reports 98.0% — divergence is 3.0pp, threshold 0.5pp
    stress = tmp_path / "stress.json"
    _write_json(
        stress,
        {
            "cross_modul_stress_status": "pass",
            "cross_modul_stress_score_pct": 98.0,
        },
    )

    snap = emitter.build_snapshot(
        decisions_path=decisions,
        phase2_stress_path=stress,
        lifecycle_path=None,
        now=now,
    )
    assert snap.consistency_score_pct == 95.0
    assert snap.stress_oracle.score_pct == 98.0
    assert snap.divergence_pct == 3.0
    assert snap.divergence_red_flag is True
    assert "divergence-3.0000pct" in snap.red_flag_reason
    assert "threshold-0.5000pct" in snap.red_flag_reason

    # Tighter threshold above the delta -> no red-flag
    snap_ok = emitter.build_snapshot(
        decisions_path=decisions,
        phase2_stress_path=stress,
        lifecycle_path=None,
        divergence_threshold_pct=5.0,
        now=now,
    )
    assert snap_ok.divergence_red_flag is False
    assert snap_ok.red_flag_reason == "ok"


# ---------------------------------------------------------------------------
# 8. Stress-oracle fail = red-flag regardless of math
# ---------------------------------------------------------------------------


def test_build_snapshot_red_flag_on_stress_oracle_fail(tmp_path: Path):
    """A failing stress oracle is itself a rollback trigger."""

    now = _now()
    inside = now - timedelta(seconds=30)

    # Self-score 100%, oracle reports fail at 99.9% — divergence 0.1pp
    # which is BELOW the 0.5pp threshold; but oracle status RED must
    # still raise the red-flag.
    decisions = tmp_path / "d.jsonl"
    _seed_jsonl(
        decisions,
        [_decision(chosen_backend="rust", ts=inside) for _ in range(10)],
    )
    stress = tmp_path / "stress.json"
    _write_json(
        stress,
        {
            "cross_modul_stress_status": "fail",
            "cross_modul_stress_score_pct": 99.9,
        },
    )

    snap = emitter.build_snapshot(
        decisions_path=decisions,
        phase2_stress_path=stress,
        lifecycle_path=None,
        now=now,
    )
    assert snap.consistency_score_pct == 100.0
    assert snap.divergence_pct == pytest.approx(0.1, rel=1e-9)
    assert snap.divergence_red_flag is True
    assert snap.red_flag_reason == "stress-oracle-status-fail"


# ---------------------------------------------------------------------------
# 9. Inputs missing => no red-flag, distinct reasons
# ---------------------------------------------------------------------------


def test_build_snapshot_no_red_flag_when_inputs_missing(tmp_path: Path):
    """Missing decisions or oracle -> red_flag False, reason explains."""

    now = _now()

    # All inputs absent
    snap = emitter.build_snapshot(
        decisions_path=None,
        phase2_stress_path=None,
        lifecycle_path=None,
        now=now,
    )
    assert snap.consistency_score_pct is None
    assert snap.stress_oracle.status == emitter.StressOracleStatus.YELLOW
    assert snap.divergence_pct is None
    assert snap.divergence_red_flag is False
    assert snap.red_flag_reason == "consistency-score-no-traffic-in-window"

    # Decisions present (so score is computed), oracle score absent
    inside = now - timedelta(seconds=30)
    decisions = tmp_path / "d.jsonl"
    _seed_jsonl(
        decisions,
        [_decision(chosen_backend="rust", ts=inside) for _ in range(5)],
    )
    snap = emitter.build_snapshot(
        decisions_path=decisions,
        phase2_stress_path=None,
        lifecycle_path=None,
        now=now,
    )
    assert snap.consistency_score_pct == 100.0
    assert snap.stress_oracle.score_pct is None
    assert snap.divergence_pct is None
    assert snap.divergence_red_flag is False
    assert snap.red_flag_reason == "stress-oracle-score-missing"


# ---------------------------------------------------------------------------
# 10. Prometheus textfile
# ---------------------------------------------------------------------------


def test_render_prometheus_textfile_emits_stable_metric_names(tmp_path: Path):
    """All eleven gauge names appear; labels are stable."""

    now = _now()
    inside = now - timedelta(seconds=15)
    decisions = tmp_path / "d.jsonl"
    _seed_jsonl(
        decisions,
        [_decision(chosen_backend="rust", ts=inside) for _ in range(8)]
        + [_decision(chosen_backend="python", ts=inside) for _ in range(2)],
    )
    stress = tmp_path / "s.json"
    _write_json(
        stress,
        {
            "cross_modul_stress_status": "pass",
            "cross_modul_stress_score_pct": 80.0,
        },
    )
    lifecycle = tmp_path / "lc.json"
    _write_json(lifecycle, {"3": "in_cutover"})

    snap = emitter.build_snapshot(
        decisions_path=decisions,
        phase2_stress_path=stress,
        lifecycle_path=lifecycle,
        now=now,
    )
    text = emitter.render_prometheus_textfile(snap)

    must_have = [
        "persona_engine_welle_3_consistency_score",
        "persona_engine_welle_3_stress_oracle_score",
        "persona_engine_welle_3_divergence_pct",
        "persona_engine_welle_3_divergence_red_flag",
        "persona_engine_welle_3_window_python_count",
        "persona_engine_welle_3_window_rust_count",
        "persona_engine_welle_3_window_fallback_count",
        "persona_engine_welle_3_window_seconds",
        "persona_engine_welle_3_tick_interval_seconds",
        "persona_engine_welle_3_divergence_threshold_pct",
        "persona_engine_welle_3_aktiv",
    ]
    for name in must_have:
        assert name in text, f"missing metric: {name}"
        assert (
            f"# HELP {name} " in text or f"# HELP {name}\n" in text
        ), f"missing HELP comment for: {name}"
        assert f"# TYPE {name} gauge" in text, f"missing TYPE for: {name}"

    # Stable labels
    assert 'welle="3"' in text
    assert 'domain="bridge_audit_writer"' in text
    # State label on welle_aktiv
    assert 'state="in_cutover"' in text
    # Aktiv = 1 because state is in_cutover
    assert "persona_engine_welle_3_aktiv{" in text
    aktiv_lines = [
        ln
        for ln in text.splitlines()
        if ln.startswith("persona_engine_welle_3_aktiv{")
    ]
    assert len(aktiv_lines) == 1
    assert aktiv_lines[0].endswith(" 1")


# ---------------------------------------------------------------------------
# 11. CLI green path
# ---------------------------------------------------------------------------


def test_main_cli_writes_out_and_prom_textfile_returns_zero_when_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """No divergence -> exit 0, both output files written."""

    now = _now()
    inside = now - timedelta(seconds=15)
    decisions = tmp_path / "d.jsonl"
    _seed_jsonl(
        decisions,
        [_decision(chosen_backend="rust", ts=inside) for _ in range(10)],
    )
    stress = tmp_path / "s.json"
    _write_json(
        stress,
        {
            "cross_modul_stress_status": "pass",
            "cross_modul_stress_score_pct": 100.0,
        },
    )
    out = tmp_path / "snap.json"
    prom = tmp_path / "snap.prom"

    # Ensure no stray env overrides leak across tests
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
    assert payload["welle"] == 3
    assert payload["domain"] == "bridge_audit_writer"
    assert payload["consistency_score_pct"] == 100.0
    assert payload["divergence_red_flag"] is False
    assert payload["divergence_pct"] == 0.0

    prom_text = prom.read_text(encoding="utf-8")
    assert "persona_engine_welle_3_consistency_score" in prom_text


# ---------------------------------------------------------------------------
# 12. CLI red-flag path
# ---------------------------------------------------------------------------


def test_main_cli_returns_one_on_divergence_red_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Divergence exceeds threshold -> exit code 1 (rollback signal)."""

    now = _now()
    inside = now - timedelta(seconds=15)
    decisions = tmp_path / "d.jsonl"
    # Self-score 90%
    _seed_jsonl(
        decisions,
        [_decision(chosen_backend="rust", ts=inside) for _ in range(9)]
        + [_decision(chosen_backend="python", ts=inside)],
    )
    # Oracle reports 99% -> divergence 9.0pp
    stress = tmp_path / "s.json"
    _write_json(
        stress,
        {
            "cross_modul_stress_status": "pass",
            "cross_modul_stress_score_pct": 99.0,
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
    assert payload["divergence_red_flag"] is True
    assert payload["consistency_score_pct"] == 90.0
    assert payload["stress_oracle"]["score_pct"] == 99.0

    # Bad CLI param -> exit 2
    rc_bad = emitter.main(["--tick-interval-seconds", "0"])
    assert rc_bad == 2
    rc_bad2 = emitter.main(["--window-seconds", "-5"])
    assert rc_bad2 == 2
    rc_bad3 = emitter.main(["--divergence-threshold-pct", "-1"])
    assert rc_bad3 == 2
