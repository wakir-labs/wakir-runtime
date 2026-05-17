# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/phase-3c-welle-status-emitter.py — Tag-30 Mini-Welle.

Hermetic, stdlib + pytest only. Loads the emitter via importlib from
its hyphenated path under ``scripts/``. JSONL inputs are written to
``tmp_path`` fixtures. No network, no live Prometheus, no podman.

The emitter is the per-welle live-status substrate behind the Grafana
``persona-engine-phase-3c-welle-status.json`` dashboard. It reads the
same BackendDecision JSONL the Tag-22 aggregator and the Tag-25
tracker consult, plus an optional operator-hand lifecycle override
(``{<welle>: <state>}``) and an optional Phase-2-Acceptance-Gate
output JSON (for the cross-modul-drift indicator).

Scope (12 tests)
----------------

1.  test_module_loads_and_exports_public_surface
2.  test_resolve_decisions_jsonl_path_priority_order
3.  test_resolve_phase2_acceptance_path_and_lifecycle_path
4.  test_build_snapshot_defaults_pre_cutover_when_lifecycle_absent
5.  test_build_snapshot_per_welle_python_rust_fallback_split
6.  test_build_snapshot_lifecycle_override_advances_states
7.  test_build_snapshot_marathon_progress_pct_counts_welle_complete
8.  test_build_snapshot_welle_aktiv_counter_and_cap_exceeded
9.  test_build_snapshot_rollback_active_exit_code_1
10. test_build_snapshot_cross_modul_drift_tri_state
11. test_build_snapshot_latency_percentiles_per_backend
12. test_render_prometheus_textfile_emits_stable_metric_names
13. test_main_cli_writes_out_and_prom_textfile
14. test_invalid_lifecycle_state_exits_2
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest


# ---------------------------------------------------------------------------
# Module loader (hyphenated filename -> importlib.util)
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
EMITTER_PATH = REPO_ROOT / "scripts" / "phase-3c-welle-status-emitter.py"


def _load_emitter_module():
    spec = importlib.util.spec_from_file_location(
        "phase_3c_welle_status_emitter", EMITTER_PATH
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


def _decision(
    *,
    domain: str,
    chosen_backend: str = "rust",
    fallback_reason: Optional[str] = None,
    resolution_latency_us: Optional[int] = 100,
    ts: Optional[str] = "2026-05-17T12:00:00Z",
    include_envelope: bool = True,
) -> dict:
    """Build a single BackendDecision JSONL record (dict)."""

    rec: dict = {
        "domain": domain,
        "requested_backend": "rust",
        "chosen_backend": chosen_backend,
        "fallback_reason": fallback_reason,
        "bin_path": None,
    }
    if resolution_latency_us is not None:
        rec["resolution_latency_us"] = resolution_latency_us
    if include_envelope:
        rec["level"] = "INFO"
        rec["msg"] = "backend-decision"
    if ts is not None:
        rec["ts"] = ts
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
        "CrossModulDriftStatus",
        "WelleStatus",
        "WelleStatusSnapshot",
        "LatencyStats",
        "build_snapshot",
        "resolve_decisions_jsonl_path",
        "resolve_phase2_acceptance_path",
        "resolve_lifecycle_path",
        "load_lifecycle",
        "load_cross_modul_drift",
        "ingest_decisions",
        "render_prometheus_textfile",
        "main",
        "build_parser",
        "WELLE_DOMAIN_MAP",
        "WELLE_TOTAL",
        "DOPPEL_WELLE_CAP",
        "ENV_PHASE_3C_OBS_BASELINE_PATH",
        "ENV_BACKEND_DECISION_JSONL",
        "ENV_PHASE_2_ACCEPTANCE_OUTPUT",
        "ENV_PHASE_3C_WELLE_LIFECYCLE",
        "SCHEMA_ID",
    ]
    for name in expected:
        assert hasattr(emitter, name), f"missing public surface: {name}"

    # The welle inventory must cover the seven welles ADR-0066
    # enumerates. Adding an eighth is intentional schema-bump.
    assert set(emitter.WELLE_DOMAIN_MAP.keys()) == {1, 2, 3, 4, 5, 6, 7}
    assert emitter.WELLE_TOTAL == 7
    assert emitter.DOPPEL_WELLE_CAP == 2


# ---------------------------------------------------------------------------
# 2. Path resolution
# ---------------------------------------------------------------------------


def test_resolve_decisions_jsonl_path_priority_order(tmp_path: Path):
    """CLI flag wins; env-1 beats env-2; absent ENV yields None."""

    cli = tmp_path / "cli.jsonl"
    env1 = tmp_path / "env1.jsonl"
    env2 = tmp_path / "env2.jsonl"

    # CLI wins
    out = emitter.resolve_decisions_jsonl_path(
        str(cli),
        env={
            emitter.ENV_PHASE_3C_OBS_BASELINE_PATH: str(env1),
            emitter.ENV_BACKEND_DECISION_JSONL: str(env2),
        },
    )
    assert out == cli

    # ENV-1 wins over ENV-2
    out = emitter.resolve_decisions_jsonl_path(
        None,
        env={
            emitter.ENV_PHASE_3C_OBS_BASELINE_PATH: str(env1),
            emitter.ENV_BACKEND_DECISION_JSONL: str(env2),
        },
    )
    assert out == env1

    # ENV-2 picked up when ENV-1 unset
    out = emitter.resolve_decisions_jsonl_path(
        None,
        env={emitter.ENV_BACKEND_DECISION_JSONL: str(env2)},
    )
    assert out == env2

    # Nothing -> None
    out = emitter.resolve_decisions_jsonl_path(None, env={})
    assert out is None

    # Whitespace-only counts as unset
    out = emitter.resolve_decisions_jsonl_path(
        "   ",
        env={emitter.ENV_PHASE_3C_OBS_BASELINE_PATH: "   "},
    )
    assert out is None


def test_resolve_phase2_acceptance_path_and_lifecycle_path(tmp_path: Path):
    """The sibling resolvers have the documented priority order."""

    cli = tmp_path / "cli.json"
    env = tmp_path / "env.json"

    out = emitter.resolve_phase2_acceptance_path(
        str(cli), env={emitter.ENV_PHASE_2_ACCEPTANCE_OUTPUT: str(env)}
    )
    assert out == cli

    out = emitter.resolve_phase2_acceptance_path(
        None, env={emitter.ENV_PHASE_2_ACCEPTANCE_OUTPUT: str(env)}
    )
    assert out == env

    out = emitter.resolve_phase2_acceptance_path(None, env={})
    assert out is None

    out = emitter.resolve_lifecycle_path(
        str(cli), env={emitter.ENV_PHASE_3C_WELLE_LIFECYCLE: str(env)}
    )
    assert out == cli

    out = emitter.resolve_lifecycle_path(
        None, env={emitter.ENV_PHASE_3C_WELLE_LIFECYCLE: str(env)}
    )
    assert out == env

    out = emitter.resolve_lifecycle_path(None, env={})
    assert out is None


# ---------------------------------------------------------------------------
# 3. build_snapshot — defaults
# ---------------------------------------------------------------------------


def test_build_snapshot_defaults_pre_cutover_when_lifecycle_absent(
    tmp_path: Path,
):
    """Empty lifecycle override -> every welle is PRE_CUTOVER."""

    jsonl = tmp_path / "decisions.jsonl"
    _seed_jsonl(jsonl, [])  # empty file, valid path

    snap = emitter.build_snapshot(
        decisions_path=jsonl,
        phase2_path=None,
        lifecycle_path=None,
    )

    assert len(snap.welles) == 7
    for w in snap.welles:
        assert w.state == emitter.WelleState.PRE_CUTOVER
        assert w.total_decisions == 0
        assert w.python_count == 0
        assert w.rust_count == 0

    assert snap.welle_aktiv_count == 0
    assert snap.cap_exceeded is False
    assert snap.marathon_progress_pct == 0.0
    assert snap.exit_code == 0
    # Phase-2 input missing -> yellow tri-state default
    assert snap.cross_modul_drift == emitter.CrossModulDriftStatus.YELLOW


# ---------------------------------------------------------------------------
# 4. Per-welle python/rust/fallback split
# ---------------------------------------------------------------------------


def test_build_snapshot_per_welle_python_rust_fallback_split(tmp_path: Path):
    """The python-vs-rust counts and fallback-rate are wired per welle."""

    jsonl = tmp_path / "decisions.jsonl"
    records = []
    # Welle-1 (v907_verify): 4 rust, 1 python with fallback_reason=binary_missing
    records += [
        _decision(domain="v907_verify", chosen_backend="rust") for _ in range(4)
    ]
    records.append(
        _decision(
            domain="v907_verify",
            chosen_backend="python",
            fallback_reason="binary_missing",
        )
    )
    # Welle-4 (state_backing): 3 rust_inmemory (still rust family)
    records += [
        _decision(domain="state_backing", chosen_backend="rust_inmemory")
        for _ in range(3)
    ]
    # Welle-5 (lifecycle_state_machine): 2 python (no fallback_reason -> still
    # python-family but NOT counted as fallback)
    records += [
        _decision(domain="lifecycle_state_machine", chosen_backend="python")
        for _ in range(2)
    ]
    _seed_jsonl(jsonl, records)

    snap = emitter.build_snapshot(
        decisions_path=jsonl, phase2_path=None, lifecycle_path=None
    )

    by_num = {w.welle: w for w in snap.welles}

    w1 = by_num[1]
    assert w1.domain == "v907_verify"
    assert w1.rust_count == 4
    assert w1.python_count == 1
    assert w1.fallback_count == 1
    assert w1.total_decisions == 5
    assert w1.fallback_rate == pytest.approx(0.2, abs=1e-6)
    assert w1.rust_rate == pytest.approx(0.8, abs=1e-6)

    w4 = by_num[4]
    assert w4.domain == "state_backing"
    assert w4.rust_count == 3
    assert w4.python_count == 0
    assert w4.fallback_count == 0
    assert w4.total_decisions == 3

    w5 = by_num[5]
    assert w5.domain == "lifecycle_state_machine"
    assert w5.python_count == 2
    assert w5.fallback_count == 0  # python WITHOUT fallback_reason

    # Untouched welles still rendered, with zero counts.
    w7 = by_num[7]
    assert w7.domain == "recovery_workflow"
    assert w7.total_decisions == 0


# ---------------------------------------------------------------------------
# 5. Lifecycle override
# ---------------------------------------------------------------------------


def test_build_snapshot_lifecycle_override_advances_states(tmp_path: Path):
    """Override map advances per-welle state without auto-progression."""

    jsonl = tmp_path / "decisions.jsonl"
    _seed_jsonl(jsonl, [])

    lifecycle = tmp_path / "lifecycle.json"
    _write_json(
        lifecycle,
        {
            "1": "in_cutover",
            "2": "in_cutover",
            "3": "welle_complete",
            "5": "post_cutover",
        },
    )

    snap = emitter.build_snapshot(
        decisions_path=jsonl, phase2_path=None, lifecycle_path=lifecycle
    )

    by_num = {w.welle: w for w in snap.welles}
    assert by_num[1].state == emitter.WelleState.IN_CUTOVER
    assert by_num[2].state == emitter.WelleState.IN_CUTOVER
    assert by_num[3].state == emitter.WelleState.WELLE_COMPLETE
    assert by_num[4].state == emitter.WelleState.PRE_CUTOVER  # not overridden
    assert by_num[5].state == emitter.WelleState.POST_CUTOVER
    assert by_num[6].state == emitter.WelleState.PRE_CUTOVER
    assert by_num[7].state == emitter.WelleState.PRE_CUTOVER


# ---------------------------------------------------------------------------
# 6. Marathon progress gauge
# ---------------------------------------------------------------------------


def test_build_snapshot_marathon_progress_pct_counts_welle_complete(
    tmp_path: Path,
):
    """Marathon progress = (count(welle_complete) / WELLE_TOTAL) * 100."""

    jsonl = tmp_path / "decisions.jsonl"
    _seed_jsonl(jsonl, [])

    lifecycle = tmp_path / "lifecycle.json"
    _write_json(
        lifecycle,
        {
            "1": "welle_complete",
            "2": "welle_complete",
            "3": "post_cutover",   # post is NOT complete yet
            "4": "welle_complete",
        },
    )

    snap = emitter.build_snapshot(
        decisions_path=jsonl, phase2_path=None, lifecycle_path=lifecycle
    )
    # 3 complete out of 7 -> ~42.857
    assert snap.marathon_progress_pct == pytest.approx(
        100.0 * 3 / 7, abs=1e-4
    )

    # All seven complete -> 100
    _write_json(lifecycle, {str(i): "welle_complete" for i in range(1, 8)})
    snap = emitter.build_snapshot(
        decisions_path=jsonl, phase2_path=None, lifecycle_path=lifecycle
    )
    assert snap.marathon_progress_pct == 100.0


# ---------------------------------------------------------------------------
# 7. Welle-aktiv counter + cap
# ---------------------------------------------------------------------------


def test_build_snapshot_welle_aktiv_counter_and_cap_exceeded(tmp_path: Path):
    """Welle-aktiv counts in_cutover+rollback_active; >2 -> cap exceeded."""

    jsonl = tmp_path / "decisions.jsonl"
    _seed_jsonl(jsonl, [])
    lifecycle = tmp_path / "lifecycle.json"

    # Two in_cutover — at the cap, NOT exceeded.
    _write_json(lifecycle, {"1": "in_cutover", "2": "in_cutover"})
    snap = emitter.build_snapshot(
        decisions_path=jsonl, phase2_path=None, lifecycle_path=lifecycle
    )
    assert snap.welle_aktiv_count == 2
    assert snap.doppel_welle_cap == 2
    assert snap.cap_exceeded is False
    assert snap.exit_code == 0

    # Three active -> cap exceeded -> exit-code 1
    _write_json(
        lifecycle,
        {"1": "in_cutover", "2": "in_cutover", "3": "in_cutover"},
    )
    snap = emitter.build_snapshot(
        decisions_path=jsonl, phase2_path=None, lifecycle_path=lifecycle
    )
    assert snap.welle_aktiv_count == 3
    assert snap.cap_exceeded is True
    assert snap.exit_code == 1

    # in_cutover + rollback_active are both "aktiv".
    _write_json(
        lifecycle, {"1": "in_cutover", "4": "rollback_active"}
    )
    snap = emitter.build_snapshot(
        decisions_path=jsonl, phase2_path=None, lifecycle_path=lifecycle
    )
    assert snap.welle_aktiv_count == 2
    assert snap.cap_exceeded is False
    # rollback_active alone still triggers exit_code=1 (covered next test)


# ---------------------------------------------------------------------------
# 8. Rollback exit-code
# ---------------------------------------------------------------------------


def test_build_snapshot_rollback_active_exit_code_1(tmp_path: Path):
    """Any welle in ROLLBACK_ACTIVE -> exit-code 1, regardless of cap."""

    jsonl = tmp_path / "decisions.jsonl"
    _seed_jsonl(jsonl, [])
    lifecycle = tmp_path / "lifecycle.json"
    _write_json(lifecycle, {"3": "rollback_active"})

    snap = emitter.build_snapshot(
        decisions_path=jsonl, phase2_path=None, lifecycle_path=lifecycle
    )
    assert snap.welle_aktiv_count == 1
    assert snap.cap_exceeded is False
    assert snap.exit_code == 1


# ---------------------------------------------------------------------------
# 9. Cross-modul-drift tri-state
# ---------------------------------------------------------------------------


def test_build_snapshot_cross_modul_drift_tri_state(tmp_path: Path):
    """pass -> green, fail -> red, skipped -> yellow, missing -> yellow."""

    jsonl = tmp_path / "decisions.jsonl"
    _seed_jsonl(jsonl, [])
    phase2 = tmp_path / "phase2.json"

    _write_json(phase2, {"cross_modul_pin_status": "pass"})
    snap = emitter.build_snapshot(
        decisions_path=jsonl, phase2_path=phase2, lifecycle_path=None
    )
    assert snap.cross_modul_drift == emitter.CrossModulDriftStatus.GREEN
    assert snap.cross_modul_reason == "cross-modul-pin-pass"

    _write_json(phase2, {"cross_modul_pin_status": "fail"})
    snap = emitter.build_snapshot(
        decisions_path=jsonl, phase2_path=phase2, lifecycle_path=None
    )
    assert snap.cross_modul_drift == emitter.CrossModulDriftStatus.RED
    assert snap.cross_modul_reason == "cross-modul-pin-fail"

    _write_json(phase2, {"cross_modul_pin_status": "skipped"})
    snap = emitter.build_snapshot(
        decisions_path=jsonl, phase2_path=phase2, lifecycle_path=None
    )
    assert snap.cross_modul_drift == emitter.CrossModulDriftStatus.YELLOW

    # Status field missing -> yellow.
    _write_json(phase2, {})
    snap = emitter.build_snapshot(
        decisions_path=jsonl, phase2_path=phase2, lifecycle_path=None
    )
    assert snap.cross_modul_drift == emitter.CrossModulDriftStatus.YELLOW

    # File missing -> yellow.
    snap = emitter.build_snapshot(
        decisions_path=jsonl,
        phase2_path=tmp_path / "absent.json",
        lifecycle_path=None,
    )
    assert snap.cross_modul_drift == emitter.CrossModulDriftStatus.YELLOW
    assert snap.cross_modul_reason == "phase-2-acceptance-file-not-found"


# ---------------------------------------------------------------------------
# 10. Latency percentiles
# ---------------------------------------------------------------------------


def test_build_snapshot_latency_percentiles_per_backend(tmp_path: Path):
    """Latency p50/p95/p99 computed per backend family per welle."""

    jsonl = tmp_path / "decisions.jsonl"
    records = []
    # Welle-1: 10 rust latencies 100..1000us, 5 python latencies 5000..5400us
    for i in range(10):
        records.append(
            _decision(
                domain="v907_verify",
                chosen_backend="rust",
                resolution_latency_us=(i + 1) * 100,
            )
        )
    for i in range(5):
        records.append(
            _decision(
                domain="v907_verify",
                chosen_backend="python",
                fallback_reason="explicit_python",
                resolution_latency_us=5000 + i * 100,
            )
        )
    _seed_jsonl(jsonl, records)

    snap = emitter.build_snapshot(
        decisions_path=jsonl, phase2_path=None, lifecycle_path=None
    )
    w1 = next(w for w in snap.welles if w.welle == 1)

    # Rust: 10 samples, sorted = [100,200,...,1000]
    assert w1.rust_latency.count == 10
    # statistics.median for n=10 even -> mean(500, 600) = 550.
    assert w1.rust_latency.p50_us == 550
    # Nearest-rank p95: rank=int(0.95*10)=9 -> value=900.
    assert w1.rust_latency.p95_us == 900
    # Nearest-rank p99: rank=int(0.99*10)=9 -> value=900.
    assert w1.rust_latency.p99_us == 900

    # Python: 5 samples, sorted = [5000,5100,5200,5300,5400]
    assert w1.python_latency.count == 5
    # statistics.median for n=5 odd -> middle = 5200.
    assert w1.python_latency.p50_us == 5200
    # p95: rank=int(0.95*5)=4 -> value=5300
    assert w1.python_latency.p95_us == 5300
    # p99: rank=int(0.99*5)=4 -> value=5300
    assert w1.python_latency.p99_us == 5300

    # Welle with no records has None latencies.
    w7 = next(w for w in snap.welles if w.welle == 7)
    assert w7.rust_latency.count == 0
    assert w7.rust_latency.p50_us is None
    assert w7.python_latency.p99_us is None


# ---------------------------------------------------------------------------
# 11. Prometheus textfile rendering
# ---------------------------------------------------------------------------


def test_render_prometheus_textfile_emits_stable_metric_names(tmp_path: Path):
    """The textfile rendering emits the documented metric-family set."""

    jsonl = tmp_path / "decisions.jsonl"
    records = [
        _decision(domain="v907_verify", chosen_backend="rust"),
        _decision(
            domain="state_backing",
            chosen_backend="python",
            fallback_reason="binary_missing",
        ),
    ]
    _seed_jsonl(jsonl, records)
    lifecycle = tmp_path / "lifecycle.json"
    _write_json(lifecycle, {"1": "in_cutover", "3": "welle_complete"})
    phase2 = tmp_path / "phase2.json"
    _write_json(phase2, {"cross_modul_pin_status": "pass"})

    snap = emitter.build_snapshot(
        decisions_path=jsonl,
        phase2_path=phase2,
        lifecycle_path=lifecycle,
    )
    text = emitter.render_prometheus_textfile(snap)

    required_metric_names = [
        "persona_engine_phase_3c_welle_state",
        "persona_engine_phase_3c_welle_decisions_total",
        "persona_engine_phase_3c_welle_fallback_total",
        "persona_engine_phase_3c_welle_latency_us",
        "persona_engine_phase_3c_marathon_progress_pct",
        "persona_engine_phase_3c_welle_aktiv_count",
        "persona_engine_phase_3c_doppel_welle_cap",
        "persona_engine_phase_3c_cap_exceeded",
        "persona_engine_phase_3c_cross_modul_drift",
    ]
    for name in required_metric_names:
        assert f"# HELP {name} " in text, f"missing HELP {name}"
        assert f"# TYPE {name} gauge" in text, f"missing TYPE {name}"

    # Welle-1 in_cutover -> the one-hot sample for that state == 1.
    assert (
        'persona_engine_phase_3c_welle_state{welle="1",'
        'domain="v907_verify",state="in_cutover"} 1.0'
        in text
    )
    # And the other states for welle-1 are zero.
    assert (
        'persona_engine_phase_3c_welle_state{welle="1",'
        'domain="v907_verify",state="pre_cutover"} 0.0'
        in text
    )

    # Cross-modul drift one-hot at green.
    assert (
        'persona_engine_phase_3c_cross_modul_drift{status="green"} 1.0'
        in text
    )
    assert (
        'persona_engine_phase_3c_cross_modul_drift{status="red"} 0.0'
        in text
    )


# ---------------------------------------------------------------------------
# 12. CLI integration — --out + --prom-textfile
# ---------------------------------------------------------------------------


def test_main_cli_writes_out_and_prom_textfile(tmp_path: Path):
    """The CLI writes both the JSON snapshot and the Prometheus textfile."""

    jsonl = tmp_path / "decisions.jsonl"
    _seed_jsonl(
        jsonl,
        [
            _decision(domain="v907_verify", chosen_backend="rust"),
            _decision(domain="recovery_workflow", chosen_backend="python"),
        ],
    )
    out_json = tmp_path / "snapshot.json"
    out_prom = tmp_path / "snapshot.prom"

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = emitter.main(
            [
                "--decisions-jsonl",
                str(jsonl),
                "--out",
                str(out_json),
                "--prom-textfile",
                str(out_prom),
            ]
        )

    assert rc == 0, buf.getvalue()
    assert out_json.is_file()
    assert out_prom.is_file()

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["schema"] == emitter.SCHEMA_ID
    assert len(payload["welles"]) == 7

    prom = out_prom.read_text(encoding="utf-8")
    assert "persona_engine_phase_3c_marathon_progress_pct " in prom

    # Stdout also has the JSON snapshot.
    stdout_obj = json.loads(buf.getvalue())
    assert stdout_obj["welles"][0]["welle"] == 1


# ---------------------------------------------------------------------------
# 13. Invalid lifecycle yields exit-code 2
# ---------------------------------------------------------------------------


def test_invalid_lifecycle_state_exits_2(tmp_path: Path):
    """Unknown lifecycle state -> emitter exits 2 with a clear message."""

    jsonl = tmp_path / "decisions.jsonl"
    _seed_jsonl(jsonl, [])
    lifecycle = tmp_path / "lifecycle.json"
    _write_json(lifecycle, {"1": "bogus_state"})

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = emitter.main(
            [
                "--decisions-jsonl",
                str(jsonl),
                "--lifecycle-json",
                str(lifecycle),
            ]
        )

    assert rc == 2

    # Out-of-range welle number also errors out.
    _write_json(lifecycle, {"99": "in_cutover"})
    rc = emitter.main(
        [
            "--decisions-jsonl",
            str(jsonl),
            "--lifecycle-json",
            str(lifecycle),
        ]
    )
    assert rc == 2

    # Empty CLI + no ENV -> exits 2 with explanatory stderr.
    rc = emitter.main([])
    assert rc == 2


# ---------------------------------------------------------------------------
# 14. ingest_decisions tolerates malformed JSONL
# ---------------------------------------------------------------------------


def test_ingest_decisions_tolerates_malformed_jsonl(tmp_path: Path):
    """Bad lines counted as parse-errors, good ones still tallied."""

    jsonl = tmp_path / "decisions.jsonl"
    with jsonl.open("w", encoding="utf-8") as fh:
        fh.write("not json at all\n")
        fh.write(json.dumps({"unrelated": "shape"}) + "\n")
        fh.write(
            json.dumps(
                _decision(domain="v907_verify", chosen_backend="rust")
            )
            + "\n"
        )
        fh.write("\n")  # blank line ignored
        fh.write(
            json.dumps(
                _decision(domain="", chosen_backend="rust")  # blank domain
            )
            + "\n"
        )
        fh.write(
            json.dumps({"msg": "not-backend-decision", "domain": "x"}) + "\n"
        )

    by_domain, parse_errors = emitter.ingest_decisions(jsonl)
    assert "v907_verify" in by_domain
    assert by_domain["v907_verify"].rust_count == 1
    # Non-decision msg, blank domain, bad-json line, unrelated dict — each
    # counts. Liberal-reader still rejects "msg=not-backend-decision" and
    # the blank-domain record.
    assert parse_errors >= 3
