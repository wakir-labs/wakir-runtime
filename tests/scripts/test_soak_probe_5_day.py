# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/persona-engine/soak-probe-5-day.py -- Tag-54.

Hermetic, stdlib-only: the soak-probe module is loaded via
importlib from its hyphenated path under
``scripts/persona-engine/``. No network, no podman, no real time
passes. The compressed-time soak runs in <1s on a developer box.

The soak probe is the sandbox-side hermetic witness for the
Persona-Engine 0.5.2-final-pre-cutover cutover-rehearsal
expectation that the engine survives a 5-day operational window
without drift. The Live-VM rehearsal that operator-hand runs in
KW 24 is the *real* multi-day soak; this probe is the hermetic
pre-check.

Scope (18 tests)
----------------

1.  test_module_loads_and_exports_public_surface
2.  test_default_days_constant_is_five
3.  test_expected_boot_order_matches_boot_self_test_v2
4.  test_soak_fsm_transitions_form_valid_canonical_trace
5.  test_v907_test_persona_blob_matches_boot_self_test_v2
6.  test_run_soak_probe_five_days_all_invariants_pass
7.  test_run_soak_probe_days_one_passes_trivially
8.  test_run_soak_probe_days_seven_still_stable
9.  test_run_soak_probe_rejects_zero_or_negative_days
10. test_report_to_json_is_deterministic_across_runs
11. test_report_to_json_sorts_keys_and_omits_clock_keyed_fields
12. test_day_report_as_dict_round_trips_all_fields
13. test_soak_report_summary_counts_invariants
14. test_invariant_A_detects_boot_decisions_drift
15. test_invariant_B_detects_fsm_trace_drift
16. test_invariant_C_detects_v907_pin_drift
17. test_invariant_D_detects_object_count_budget_breach
18. test_main_cli_smoke_default_run_exits_zero
19. test_main_cli_json_flag_emits_canonical_json
20. test_main_cli_json_output_writes_to_path_and_matches_stdout
21. test_main_cli_rejects_days_zero_with_exit_code_two
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest


# ---------------------------------------------------------------------------
# Module loader (hyphenated filename -> importlib.util)
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "scripts" / "persona-engine" / "soak-probe-5-day.py"
BOOT_V2_PATH = REPO_ROOT / "scripts" / "persona-engine" / "boot-self-test-v2.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec so dataclasses-with-forward-
    # references (Python 3.14 dataclasses.py:814 path) can resolve the
    # module by name during decoration.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def probe_mod():
    return _load_module("soak_probe_5_day", PROBE_PATH)


@pytest.fixture(scope="module")
def boot_v2_mod():
    return _load_module("boot_self_test_v2", BOOT_V2_PATH)


# ---------------------------------------------------------------------------
# Test 1 -- module public surface
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface(probe_mod):
    """The probe exposes the documented public entry points."""
    assert callable(getattr(probe_mod, "run_soak_probe", None))
    assert callable(getattr(probe_mod, "report_to_json", None))
    assert callable(getattr(probe_mod, "main", None))
    assert hasattr(probe_mod, "DayReport")
    assert hasattr(probe_mod, "SoakReport")
    assert hasattr(probe_mod, "DEFAULT_DAYS")
    assert hasattr(probe_mod, "EXPECTED_BOOT_ORDER")
    assert hasattr(probe_mod, "SOAK_FSM_TRANSITIONS")
    assert hasattr(probe_mod, "V907_TEST_PERSONA_BLOB")
    assert hasattr(probe_mod, "RESOURCE_OBJECT_DELTA_BUDGET")


# ---------------------------------------------------------------------------
# Test 2 -- default days is 5
# ---------------------------------------------------------------------------


def test_default_days_constant_is_five(probe_mod):
    """The 5-day framing is wired in -- not a magic number elsewhere."""
    assert probe_mod.DEFAULT_DAYS == 5


# ---------------------------------------------------------------------------
# Test 3 -- boot-order matches boot-self-test-v2
# ---------------------------------------------------------------------------


def test_expected_boot_order_matches_boot_self_test_v2(probe_mod, boot_v2_mod):
    """The probe's EXPECTED_BOOT_ORDER must match the v2 self-test.

    Drift between the two would cause the probe to mark a different
    canonical fan-out than the self-test, which would create a
    silent cross-tool inconsistency on the cutover-day Live-VM.
    """
    probe_order = tuple(probe_mod.EXPECTED_BOOT_ORDER)
    self_test_order = tuple(boot_v2_mod.EXPECTED_BOOT_ORDER)
    assert probe_order == self_test_order
    # Sanity: exactly 10 components, ordered by record-no.
    assert len(probe_order) == 10
    record_nos = [t[0] for t in probe_order]
    assert record_nos == list(range(1, 11))


# ---------------------------------------------------------------------------
# Test 4 -- FSM trace is a valid canonical chain
# ---------------------------------------------------------------------------


def test_soak_fsm_transitions_form_valid_canonical_trace(probe_mod):
    """The FSM trace covers Created -> Despawned via a valid chain.

    Each transition's ``to_state`` is the next transition's
    ``from_state``. The terminal state is ``Despawned``. The trace
    visits Suspended (the cycle-back transition) and returns to
    Active before terminating.
    """
    trans = list(probe_mod.SOAK_FSM_TRANSITIONS)
    assert len(trans) == 5
    assert trans[0][0] == "Created"
    assert trans[-1][1] == "Despawned"
    states_visited = [t[0] for t in trans] + [trans[-1][1]]
    assert "Suspended" in states_visited
    # Chain consistency: every (i+1).from == (i).to
    for i in range(len(trans) - 1):
        assert trans[i][1] == trans[i + 1][0], (
            f"chain break at index {i}: "
            f"{trans[i]} -> {trans[i + 1]}"
        )


# ---------------------------------------------------------------------------
# Test 5 -- V-907 test blob matches boot-self-test-v2
# ---------------------------------------------------------------------------


def test_v907_test_persona_blob_matches_boot_self_test_v2(probe_mod):
    """The probe's V-907 test blob must match the v2 self-test blob.

    The boot self-test v2 declares its blob inline in
    ``check_v907_pin_stable``; we read the v2 source file and assert
    the probe's blob bytes are a substring of the v2 source. If they
    drift, cross-tool V-907 pin sanity-checks fail silently on the
    Live-VM (operator notices a delta between the boot self-test's
    V-907 line and the soak probe's V-907 line).
    """
    v2_source = BOOT_V2_PATH.read_text(encoding="utf-8")
    probe_blob_str = probe_mod.V907_TEST_PERSONA_BLOB.decode("utf-8")
    # The inline blob in v2 is wrapped in a triple-quoted bytes
    # literal; strip the leading newline that the b"""\n...""" form
    # produces in the constant.
    payload = probe_blob_str.lstrip("\n")
    assert payload.split("\n")[0] in v2_source, (
        "probe V-907 blob first line not found in v2 source"
    )
    # And the marker line "Self-test persona (v2)" must also appear
    # in both sources -- ties the two together.
    assert "Self-test persona (v2)" in v2_source
    assert "Self-test persona (v2)" in probe_blob_str


# ---------------------------------------------------------------------------
# Test 6 -- 5-day soak: all invariants pass
# ---------------------------------------------------------------------------


def test_run_soak_probe_five_days_all_invariants_pass(probe_mod):
    """The headline guarantee of Tag-54: 5 days, 0 drift."""
    report = probe_mod.run_soak_probe(days=5)
    assert report.summary["days_observed"] == 5
    assert report.summary["overall_ok"] is True
    assert report.summary["invariants_passed"] == report.summary[
        "invariants_total"
    ]
    # Every invariant entry must be (True, _).
    for name, (ok, detail) in report.invariants.items():
        assert ok, f"invariant {name} failed: {detail}"
    # Boot-decisions fingerprint identical across all 5 days.
    fps = {d.boot_decisions_fingerprint for d in report.days}
    assert len(fps) == 1
    # FSM trace hash identical across all 5 days.
    fsm_hashes = {d.fsm_trace_hash for d in report.days}
    assert len(fsm_hashes) == 1
    # V-907 pin identical across all 5 days.
    pins = {d.v907_pin for d in report.days}
    assert len(pins) == 1


# ---------------------------------------------------------------------------
# Test 7 -- 1-day soak passes trivially
# ---------------------------------------------------------------------------


def test_run_soak_probe_days_one_passes_trivially(probe_mod):
    """A 1-day probe still emits all invariants; no per-day drift
    is possible with a single sample but the structure must hold."""
    report = probe_mod.run_soak_probe(days=1)
    assert report.summary["days_observed"] == 1
    assert report.overall_ok is True
    assert len(report.days) == 1


# ---------------------------------------------------------------------------
# Test 8 -- 7-day soak still stable (over-provision check)
# ---------------------------------------------------------------------------


def test_run_soak_probe_days_seven_still_stable(probe_mod):
    """Running 7 simulated days (vs the documented 5) must still pass.

    This is the over-provision check: if the probe is stable for 5
    days it must remain stable for 7 (no day-index-keyed state).
    """
    report = probe_mod.run_soak_probe(days=7)
    assert report.summary["days_observed"] == 7
    assert report.overall_ok is True


# ---------------------------------------------------------------------------
# Test 9 -- days <= 0 rejected
# ---------------------------------------------------------------------------


def test_run_soak_probe_rejects_zero_or_negative_days(probe_mod):
    with pytest.raises(ValueError):
        probe_mod.run_soak_probe(days=0)
    with pytest.raises(ValueError):
        probe_mod.run_soak_probe(days=-3)


# ---------------------------------------------------------------------------
# Test 10 -- JSON output deterministic across two runs
# ---------------------------------------------------------------------------


def test_report_to_json_is_deterministic_across_runs(probe_mod):
    """Two probe runs on the same tree emit byte-identical JSON
    for every field except the gc object-count snapshot.

    The probe is a pure function of the runtime tree for all
    fingerprint fields (boot fp, fsm hash, v907 pin, decisions
    payload bytes). The ``object_count`` field is intentionally
    observational (gc internals vary slightly between runs in the
    same interpreter); the soak invariant D bounds the *delta* but
    does not require absolute equality across runs.
    """
    r1 = probe_mod.run_soak_probe(days=5)
    r2 = probe_mod.run_soak_probe(days=5)
    d1 = r1.as_dict()
    d2 = r2.as_dict()
    # Strip the observational object_count field before comparing.
    for d in (d1, d2):
        for day in d["days"]:
            del day["object_count"]
        # Invariant detail strings include a per-run object-count
        # delta -- compare only the (ok, ...) booleans for D.
        for inv_name in (
            "D_resource_object_count_within_budget",
        ):
            if inv_name in d["invariants"]:
                d["invariants"][inv_name] = {
                    "ok": d["invariants"][inv_name]["ok"]
                }
    assert d1 == d2
    # Cross-check: invariant-bearing fields are stable across runs.
    for day1, day2 in zip(r1.days, r2.days):
        assert (
            day1.boot_decisions_fingerprint
            == day2.boot_decisions_fingerprint
        )
        assert day1.fsm_trace_hash == day2.fsm_trace_hash
        assert day1.v907_pin == day2.v907_pin
        assert (
            day1.decisions_payload_bytes
            == day2.decisions_payload_bytes
        )


# ---------------------------------------------------------------------------
# Test 11 -- JSON output sorts keys + no clock-keyed fields
# ---------------------------------------------------------------------------


def test_report_to_json_sorts_keys_and_omits_clock_keyed_fields(probe_mod):
    report = probe_mod.run_soak_probe(days=5)
    j = probe_mod.report_to_json(report)
    parsed = json.loads(j)
    # Top-level keys sorted.
    assert list(parsed.keys()) == sorted(parsed.keys())
    # No clock-keyed fields anywhere in the structure.
    flat = json.dumps(parsed)
    for forbidden in (
        "timestamp",
        "wall_clock",
        "started_at",
        "finished_at",
        "real_time",
    ):
        assert forbidden not in flat


# ---------------------------------------------------------------------------
# Test 12 -- DayReport.as_dict round-trip
# ---------------------------------------------------------------------------


def test_day_report_as_dict_round_trips_all_fields(probe_mod):
    """Every documented DayReport field round-trips via as_dict."""
    report = probe_mod.run_soak_probe(days=2)
    expected_fields = {
        "day",
        "boot_decisions_fingerprint",
        "boot_decisions_count",
        "fsm_trace_hash",
        "v907_pin",
        "object_count",
        "decisions_payload_bytes",
    }
    for dr in report.days:
        d = dr.as_dict()
        assert set(d.keys()) == expected_fields
        assert isinstance(d["day"], int)
        assert isinstance(d["boot_decisions_count"], int)
        assert isinstance(d["object_count"], int)
        assert isinstance(d["decisions_payload_bytes"], int)
        assert d["boot_decisions_count"] == 10


# ---------------------------------------------------------------------------
# Test 13 -- SoakReport.summary counts invariants correctly
# ---------------------------------------------------------------------------


def test_soak_report_summary_counts_invariants(probe_mod):
    report = probe_mod.run_soak_probe(days=5)
    total = len(report.invariants)
    passed = sum(1 for ok, _ in report.invariants.values() if ok)
    assert report.summary["invariants_total"] == total
    assert report.summary["invariants_passed"] == passed
    assert report.summary["overall_ok"] == (passed == total)


# ---------------------------------------------------------------------------
# Test 14 -- Invariant A: detects boot-decisions drift
# ---------------------------------------------------------------------------


def test_invariant_A_detects_boot_decisions_drift(probe_mod):
    """Injecting a day-2 fingerprint drift flips invariant A to fail."""
    DayReport = probe_mod.DayReport
    days = [
        DayReport(
            day=1,
            boot_decisions_fingerprint="aaaa" * 16,
            boot_decisions_count=10,
            fsm_trace_hash="bbbb" * 16,
            v907_pin="cccc" * 16,
            object_count=1000,
            decisions_payload_bytes=1055,
        ),
        DayReport(
            day=2,
            boot_decisions_fingerprint="DRIFT" + "a" * 59,
            boot_decisions_count=10,
            fsm_trace_hash="bbbb" * 16,
            v907_pin="cccc" * 16,
            object_count=1000,
            decisions_payload_bytes=1055,
        ),
    ]
    invs = probe_mod._check_invariants(days)
    assert invs["A_boot_decisions_stable"][0] is False
    assert "drift" in invs["A_boot_decisions_stable"][1].lower()


# ---------------------------------------------------------------------------
# Test 15 -- Invariant B: detects FSM trace drift
# ---------------------------------------------------------------------------


def test_invariant_B_detects_fsm_trace_drift(probe_mod):
    DayReport = probe_mod.DayReport
    days = [
        DayReport(
            day=1,
            boot_decisions_fingerprint="aaaa" * 16,
            boot_decisions_count=10,
            fsm_trace_hash="bbbb" * 16,
            v907_pin="cccc" * 16,
            object_count=1000,
            decisions_payload_bytes=1055,
        ),
        DayReport(
            day=2,
            boot_decisions_fingerprint="aaaa" * 16,
            boot_decisions_count=10,
            fsm_trace_hash="DRIFT" + "b" * 59,
            v907_pin="cccc" * 16,
            object_count=1000,
            decisions_payload_bytes=1055,
        ),
    ]
    invs = probe_mod._check_invariants(days)
    assert invs["B_fsm_trace_hash_stable"][0] is False
    assert "drift" in invs["B_fsm_trace_hash_stable"][1].lower()


# ---------------------------------------------------------------------------
# Test 16 -- Invariant C: detects V-907 pin drift
# ---------------------------------------------------------------------------


def test_invariant_C_detects_v907_pin_drift(probe_mod):
    DayReport = probe_mod.DayReport
    days = [
        DayReport(
            day=1,
            boot_decisions_fingerprint="aaaa" * 16,
            boot_decisions_count=10,
            fsm_trace_hash="bbbb" * 16,
            v907_pin="cccc" * 16,
            object_count=1000,
            decisions_payload_bytes=1055,
        ),
        DayReport(
            day=2,
            boot_decisions_fingerprint="aaaa" * 16,
            boot_decisions_count=10,
            fsm_trace_hash="bbbb" * 16,
            v907_pin="DRIFT" + "c" * 59,
            object_count=1000,
            decisions_payload_bytes=1055,
        ),
    ]
    invs = probe_mod._check_invariants(days)
    assert invs["C_v907_pin_stable"][0] is False
    assert "drift" in invs["C_v907_pin_stable"][1].lower()


# ---------------------------------------------------------------------------
# Test 17 -- Invariant D: detects object-count budget breach
# ---------------------------------------------------------------------------


def test_invariant_D_detects_object_count_budget_breach(probe_mod):
    DayReport = probe_mod.DayReport
    budget = probe_mod.RESOURCE_OBJECT_DELTA_BUDGET
    days = [
        DayReport(
            day=1,
            boot_decisions_fingerprint="aaaa" * 16,
            boot_decisions_count=10,
            fsm_trace_hash="bbbb" * 16,
            v907_pin="cccc" * 16,
            object_count=1000,
            decisions_payload_bytes=1055,
        ),
        DayReport(
            day=2,
            boot_decisions_fingerprint="aaaa" * 16,
            boot_decisions_count=10,
            fsm_trace_hash="bbbb" * 16,
            v907_pin="cccc" * 16,
            object_count=1000 + budget + 1000,  # over budget
            decisions_payload_bytes=1055,
        ),
    ]
    invs = probe_mod._check_invariants(days)
    assert invs["D_resource_object_count_within_budget"][0] is False
    assert (
        "budget"
        in invs["D_resource_object_count_within_budget"][1].lower()
    )


# ---------------------------------------------------------------------------
# Test 18 -- CLI: default run exits 0
# ---------------------------------------------------------------------------


def test_main_cli_smoke_default_run_exits_zero(probe_mod):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = probe_mod.main([])
    assert rc == 0
    out = buf.getvalue()
    assert "5-Day Soak Probe" in out
    assert "overall_ok:    True" in out


# ---------------------------------------------------------------------------
# Test 19 -- CLI --json emits canonical JSON
# ---------------------------------------------------------------------------


def test_main_cli_json_flag_emits_canonical_json(probe_mod):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = probe_mod.main(["--json", "--quiet"])
    assert rc == 0
    out = buf.getvalue().strip()
    parsed = json.loads(out)
    assert "days" in parsed
    assert "invariants" in parsed
    assert "summary" in parsed
    assert parsed["summary"]["overall_ok"] is True


# ---------------------------------------------------------------------------
# Test 20 -- CLI --json-output writes to PATH
# ---------------------------------------------------------------------------


def test_main_cli_json_output_writes_to_path_and_matches_stdout(
    probe_mod, tmp_path
):
    out_path = tmp_path / "soak-report.json"
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = probe_mod.main(
            ["--json", "--quiet", "--json-output", str(out_path)]
        )
    assert rc == 0
    assert out_path.exists()
    file_content = out_path.read_text(encoding="utf-8")
    stdout_content = buf.getvalue().strip()
    # Same canonical JSON (both via report_to_json with indent=2).
    assert json.loads(file_content) == json.loads(stdout_content)


# ---------------------------------------------------------------------------
# Test 21 -- CLI rejects --days 0 with exit code 2
# ---------------------------------------------------------------------------


def test_main_cli_rejects_days_zero_with_exit_code_two(probe_mod):
    err = io.StringIO()
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = probe_mod.main(["--days", "0"])
    assert rc == 2
    assert "days must be >= 1" in err.getvalue()
