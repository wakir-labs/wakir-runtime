# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/phase-3c-observability-baseline-tracker.py — Tag-25 Mini-Welle.

Hermetic, stdlib-only: the tracker module is loaded via importlib from
its hyphenated path under ``scripts/``. JSONL inputs are written to
``tmp_path`` fixtures. No network, no live collector, no podman.

The tracker is the Tag-25 burn-up companion to the Tag-24 trigger-gate
aggregator's Gate-4. It reads the same JSONL the aggregator already
consults, computes per-component python-vs-rust splits + fallback
rates, and emits a tri-state status (red <7, yellow 7..14, green
>=14 distinct days) suitable for daily-snapshot artifact emit.

Scope (12 tests)
----------------

1.  test_module_loads_and_exports_public_surface
2.  test_resolve_jsonl_path_priority_order
3.  test_build_report_red_when_no_path_configured
4.  test_build_report_red_when_jsonl_file_missing
5.  test_build_report_red_when_jsonl_empty_or_no_samples
6.  test_build_report_red_when_below_min_days
7.  test_build_report_yellow_between_min_and_comfort
8.  test_build_report_green_at_or_above_comfort_days
9.  test_build_report_per_component_python_rust_fallback_rates
10. test_build_report_tolerates_unknown_components_and_backends
11. test_build_report_handles_malformed_jsonl_lines
12. test_main_cli_writes_out_and_exit_codes_match_status
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Dict, List, Optional

import pytest


# ---------------------------------------------------------------------------
# Module loader (hyphenated filename -> importlib.util)
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKER_PATH = REPO_ROOT / "scripts" / "phase-3c-observability-baseline-tracker.py"


def _load_tracker_module():
    spec = importlib.util.spec_from_file_location(
        "phase_3c_observability_baseline_tracker", TRACKER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


tracker = _load_tracker_module()


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _decision(
    *,
    domain: str = "recovery",
    chosen_backend: str = "python",
    fallback_reason: Optional[str] = None,
    ts: Optional[str] = "2026-05-10T12:00:00Z",
    include_envelope: bool = True,
    ts_field: str = "ts",
) -> dict:
    """Build a single BackendDecision JSONL record (dict)."""

    rec: dict = {
        "domain": domain,
        "requested_backend": "rust",
        "chosen_backend": chosen_backend,
        "resolution_latency_us": 100,
        "fallback_reason": fallback_reason,
        "bin_path": None,
    }
    if include_envelope:
        rec["level"] = "INFO"
        rec["msg"] = "backend-decision"
    if ts is not None:
        rec[ts_field] = ts
    return rec


def _seed_jsonl(path: Path, records: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _seven_distinct_day_decisions() -> List[dict]:
    days = [f"2026-05-{d:02d}T12:00:00Z" for d in range(10, 17)]
    return [_decision(ts=d, chosen_backend="rust") for d in days]


def _fourteen_distinct_day_decisions() -> List[dict]:
    days = [f"2026-05-{d:02d}T12:00:00Z" for d in range(3, 17)]
    return [_decision(ts=d, chosen_backend="rust") for d in days]


# ---------------------------------------------------------------------------
# 1. Module surface
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface():
    """Smoke-test the public-API surface so import-time drift is loud."""

    expected = [
        "BaselineStatus",
        "BaselineReport",
        "ComponentStats",
        "build_report",
        "resolve_jsonl_path",
        "main",
        "build_parser",
        "DEFAULT_BASELINE_MIN_DAYS",
        "DEFAULT_BASELINE_COMFORT_DAYS",
        "ENV_PHASE_3C_OBS_BASELINE_PATH",
        "ENV_BACKEND_DECISION_JSONL",
        "SCHEMA_ID",
    ]
    for name in expected:
        assert hasattr(tracker, name), f"missing public surface: {name}"
    assert tracker.DEFAULT_BASELINE_MIN_DAYS == 7
    assert tracker.DEFAULT_BASELINE_COMFORT_DAYS == 14
    assert (
        tracker.ENV_PHASE_3C_OBS_BASELINE_PATH == "WAKIR_PHASE_3C_OBS_BASELINE_PATH"
    )
    assert tracker.ENV_BACKEND_DECISION_JSONL == "WAKIR_BACKEND_DECISION_JSONL"


# ---------------------------------------------------------------------------
# 2. Path resolution priority
# ---------------------------------------------------------------------------


def test_resolve_jsonl_path_priority_order():
    """CLI flag > primary ENV > secondary ENV > None."""

    # No CLI, no ENV -> None.
    assert tracker.resolve_jsonl_path(None, env={}) is None
    # Whitespace-only CLI counts as unset.
    assert tracker.resolve_jsonl_path("   ", env={}) is None

    # CLI flag wins over both ENVs.
    p = tracker.resolve_jsonl_path(
        "/cli/path.jsonl",
        env={
            tracker.ENV_PHASE_3C_OBS_BASELINE_PATH: "/primary/env.jsonl",
            tracker.ENV_BACKEND_DECISION_JSONL: "/secondary/env.jsonl",
        },
    )
    assert p == Path("/cli/path.jsonl")

    # Primary ENV preferred over secondary.
    p = tracker.resolve_jsonl_path(
        None,
        env={
            tracker.ENV_PHASE_3C_OBS_BASELINE_PATH: "/primary/env.jsonl",
            tracker.ENV_BACKEND_DECISION_JSONL: "/secondary/env.jsonl",
        },
    )
    assert p == Path("/primary/env.jsonl")

    # Secondary ENV fallback when only the secondary is set.
    p = tracker.resolve_jsonl_path(
        None,
        env={tracker.ENV_BACKEND_DECISION_JSONL: "/secondary/env.jsonl"},
    )
    assert p == Path("/secondary/env.jsonl")


# ---------------------------------------------------------------------------
# 3 + 4 + 5. Red-path coverage
# ---------------------------------------------------------------------------


def test_build_report_red_when_no_path_configured():
    """No JSONL path -> red with reason ``no-path-configured``."""

    rpt = tracker.build_report(None)
    assert rpt.status is tracker.BaselineStatus.RED
    assert rpt.reason == "no-path-configured"
    assert rpt.sample_count == 0
    assert rpt.distinct_days == 0
    assert rpt.jsonl_path is None
    assert rpt.exit_code == 2
    assert rpt.components == []


def test_build_report_red_when_jsonl_file_missing(tmp_path: Path):
    """Resolved path that doesn't exist -> red with reason ``jsonl-file-not-found``."""

    rpt = tracker.build_report(tmp_path / "does-not-exist.jsonl")
    assert rpt.status is tracker.BaselineStatus.RED
    assert rpt.reason == "jsonl-file-not-found"
    assert rpt.jsonl_path == str(tmp_path / "does-not-exist.jsonl")
    assert rpt.sample_count == 0


def test_build_report_red_when_jsonl_empty_or_no_samples(tmp_path: Path):
    """Empty JSONL -> red ``no-samples-in-jsonl``; same for all-malformed."""

    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    rpt_empty = tracker.build_report(empty)
    assert rpt_empty.status is tracker.BaselineStatus.RED
    assert rpt_empty.reason == "no-samples-in-jsonl"
    assert rpt_empty.sample_count == 0

    junk = tmp_path / "junk.jsonl"
    junk.write_text("this is not json\n{also: not_json}\n", encoding="utf-8")
    rpt_junk = tracker.build_report(junk)
    assert rpt_junk.status is tracker.BaselineStatus.RED
    assert rpt_junk.reason == "no-samples-in-jsonl"
    assert rpt_junk.parse_errors >= 2


# ---------------------------------------------------------------------------
# 6 + 7 + 8. Threshold tri-state
# ---------------------------------------------------------------------------


def test_build_report_red_when_below_min_days(tmp_path: Path):
    """Six distinct days -> red (below ADR-0065 floor of 7)."""

    path = tmp_path / "six-days.jsonl"
    days = [f"2026-05-{d:02d}T12:00:00Z" for d in range(10, 16)]  # 6 days
    _seed_jsonl(path, [_decision(ts=d, chosen_backend="rust") for d in days])

    rpt = tracker.build_report(path)
    assert rpt.status is tracker.BaselineStatus.RED
    assert rpt.distinct_days == 6
    assert "distinct_days=6" in rpt.reason
    assert "min_days=7" in rpt.reason
    assert rpt.exit_code == 2
    assert rpt.days_of_data == 6  # 2026-05-10 .. 2026-05-15 inclusive


def test_build_report_yellow_between_min_and_comfort(tmp_path: Path):
    """Seven distinct days -> yellow (>=min, <comfort)."""

    path = tmp_path / "seven-days.jsonl"
    _seed_jsonl(path, _seven_distinct_day_decisions())

    rpt = tracker.build_report(path)
    assert rpt.status is tracker.BaselineStatus.YELLOW
    assert rpt.distinct_days == 7
    assert rpt.days_of_data == 7
    assert rpt.exit_code == 1
    assert rpt.min_days_required == 7
    assert rpt.comfort_days_required == 14
    assert rpt.earliest_day == "2026-05-10"
    assert rpt.latest_day == "2026-05-16"


def test_build_report_green_at_or_above_comfort_days(tmp_path: Path):
    """Fourteen distinct days -> green (>=comfort)."""

    path = tmp_path / "fourteen-days.jsonl"
    _seed_jsonl(path, _fourteen_distinct_day_decisions())

    rpt = tracker.build_report(path)
    assert rpt.status is tracker.BaselineStatus.GREEN
    assert rpt.distinct_days == 14
    assert rpt.days_of_data == 14
    assert rpt.exit_code == 0


# ---------------------------------------------------------------------------
# 9. Per-component split
# ---------------------------------------------------------------------------


def test_build_report_per_component_python_rust_fallback_rates(tmp_path: Path):
    """Per-(component, backend) counts + fallback-rates match the JSONL."""

    path = tmp_path / "split.jsonl"
    # recovery: 4 records — 3 python (2 with fallback_reason set), 1 rust.
    # fsm:     2 records — 2 rust, 0 python.
    # v907_verify: 1 record — 1 rust.
    # Each record carries a distinct ts so the 7-day count is irrelevant
    # to the split-fitness assertion (we only assert the split here).
    records = [
        _decision(
            domain="recovery",
            chosen_backend="python",
            fallback_reason="binary_missing",
            ts="2026-05-10T01:00:00Z",
        ),
        _decision(
            domain="recovery",
            chosen_backend="python",
            fallback_reason="binary_not_executable",
            ts="2026-05-10T02:00:00Z",
        ),
        _decision(
            domain="recovery",
            chosen_backend="python",
            fallback_reason=None,
            ts="2026-05-10T03:00:00Z",
        ),
        _decision(
            domain="recovery",
            chosen_backend="rust",
            fallback_reason=None,
            ts="2026-05-10T04:00:00Z",
        ),
        _decision(
            domain="fsm",
            chosen_backend="rust_inmemory",
            fallback_reason=None,
            ts="2026-05-10T05:00:00Z",
        ),
        _decision(
            domain="fsm",
            chosen_backend="rust",
            fallback_reason=None,
            ts="2026-05-10T06:00:00Z",
        ),
        _decision(
            domain="v907_verify",
            chosen_backend="rust",
            fallback_reason=None,
            ts="2026-05-10T07:00:00Z",
        ),
    ]
    _seed_jsonl(path, records)
    rpt = tracker.build_report(path)

    # Status is red (only 1 distinct day) — split assertions are
    # independent of the threshold tri-state.
    assert rpt.sample_count == 7
    assert rpt.distinct_days == 1
    by_comp = {c.component: c for c in rpt.components}

    rec = by_comp["recovery"]
    assert rec.total_decisions == 4
    assert rec.python_count == 3
    assert rec.rust_count == 1
    assert rec.fallback_count == 2  # binary_missing + binary_not_executable
    assert rec.python_rate == pytest.approx(0.75)
    assert rec.rust_rate == pytest.approx(0.25)
    assert rec.fallback_rate == pytest.approx(0.5)

    fsm = by_comp["fsm"]
    assert fsm.total_decisions == 2
    # rust_inmemory and rust both lump into the rust family.
    assert fsm.rust_count == 2
    assert fsm.python_count == 0
    assert fsm.fallback_count == 0
    assert fsm.fallback_rate == 0.0

    v907 = by_comp["v907_verify"]
    assert v907.total_decisions == 1
    assert v907.rust_count == 1


# ---------------------------------------------------------------------------
# 10. Unknown components / backends
# ---------------------------------------------------------------------------


def test_build_report_tolerates_unknown_components_and_backends(tmp_path: Path):
    """Records with missing/empty domain or chosen_backend bucket cleanly."""

    path = tmp_path / "unknown.jsonl"
    _seed_jsonl(
        path,
        [
            _decision(domain="", chosen_backend="rust", ts="2026-05-10T01:00:00Z"),
            _decision(
                domain="recovery", chosen_backend=None, ts="2026-05-10T02:00:00Z"
            ),
            _decision(
                domain="recovery", chosen_backend="weird-thing", ts="2026-05-10T03:00:00Z"
            ),
        ],
    )
    rpt = tracker.build_report(path)
    assert rpt.sample_count == 3
    by_comp = {c.component: c for c in rpt.components}
    # Empty domain bucketed under the unknown sentinel.
    assert tracker.COMPONENT_UNKNOWN_BUCKET in by_comp
    # ``recovery`` saw two records: one with chosen_backend=None ->
    # ``other``; one with ``weird-thing`` -> ``other``.
    rec = by_comp["recovery"]
    assert rec.total_decisions == 2
    assert rec.python_count == 0
    assert rec.rust_count == 0
    assert rec.other_count == 2


# ---------------------------------------------------------------------------
# 11. Malformed-line tolerance
# ---------------------------------------------------------------------------


def test_build_report_handles_malformed_jsonl_lines(tmp_path: Path):
    """Mixed valid + malformed lines: aggregator never crashes."""

    path = tmp_path / "mixed.jsonl"
    payload = [
        json.dumps(_decision(ts="2026-05-10T12:00:00Z", chosen_backend="rust")),
        "this is not json at all",
        # Non-dict JSON (a list) — must be filtered.
        json.dumps(["nope", "still not a record"]),
        # Different msg envelope — filtered.
        json.dumps({"msg": "some-other-event", "domain": "fsm"}),
        json.dumps(_decision(ts="2026-05-11T12:00:00Z", chosen_backend="python")),
        "",  # Empty line OK.
        json.dumps(_decision(ts="2026-05-12T12:00:00Z", chosen_backend="rust")),
    ]
    path.write_text("\n".join(payload) + "\n", encoding="utf-8")

    rpt = tracker.build_report(path)
    assert rpt.sample_count == 3
    assert rpt.distinct_days == 3
    # Two non-empty malformed lines (raw text + JSON-list) + one
    # non-backend-decision dict = three parse-error entries.
    assert rpt.parse_errors == 3


# ---------------------------------------------------------------------------
# 12. CLI entry-point
# ---------------------------------------------------------------------------


def test_main_cli_writes_out_and_exit_codes_match_status(tmp_path: Path):
    """``main()`` prints the JSON, writes ``--out``, and returns the exit-code."""

    # Yellow case: 7 days, exit 1.
    jsonl_path = tmp_path / "baseline.jsonl"
    _seed_jsonl(jsonl_path, _seven_distinct_day_decisions())
    out_path = tmp_path / "report.json"

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = tracker.main(
            [
                "--jsonl-path",
                str(jsonl_path),
                "--out",
                str(out_path),
            ]
        )
    assert rc == 1

    stdout_payload = json.loads(buf.getvalue())
    assert stdout_payload["status"] == "yellow"
    assert stdout_payload["distinct_days"] == 7
    # ``--out`` file matches stdout.
    file_payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert file_payload == stdout_payload

    # Red case: no path configured (no CLI, no ENV) — patch os.environ.
    saved = os.environ.pop(tracker.ENV_PHASE_3C_OBS_BASELINE_PATH, None)
    saved2 = os.environ.pop(tracker.ENV_BACKEND_DECISION_JSONL, None)
    try:
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            rc2 = tracker.main([])
        assert rc2 == 2
        payload2 = json.loads(buf2.getvalue())
        assert payload2["status"] == "red"
        assert payload2["reason"] == "no-path-configured"
    finally:
        if saved is not None:
            os.environ[tracker.ENV_PHASE_3C_OBS_BASELINE_PATH] = saved
        if saved2 is not None:
            os.environ[tracker.ENV_BACKEND_DECISION_JSONL] = saved2

    # Green case: 14 days, exit 0.
    jsonl_green = tmp_path / "baseline-green.jsonl"
    _seed_jsonl(jsonl_green, _fourteen_distinct_day_decisions())
    buf3 = io.StringIO()
    with redirect_stdout(buf3):
        rc3 = tracker.main(["--jsonl-path", str(jsonl_green)])
    assert rc3 == 0
    payload3 = json.loads(buf3.getvalue())
    assert payload3["status"] == "green"
    assert payload3["distinct_days"] == 14


# ---------------------------------------------------------------------------
# 13. Bonus — guard against --min-days / --comfort-days mis-config
# ---------------------------------------------------------------------------


def test_main_cli_rejects_inconsistent_threshold_args(tmp_path: Path):
    """``--comfort-days < --min-days`` exits 2 with a stderr message."""

    rc = tracker.main(["--min-days", "10", "--comfort-days", "5"])
    assert rc == 2
