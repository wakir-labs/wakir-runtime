# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-61 Watch-Day-Practice-Run Multi-Sample-Fixture replay test-suite.

Where the Tag-59 replay-gate (PR #377) only covered a single
GREEN-day sample, Tag-61 extends replay-coverage across all three
Watch-Day verdict-classes that the Tag-54 spec emits:

  * green   - 9/9 scenarios match; overall_pass=True
  * caution - 8/9 scenarios match; one scenario drifted from its
              expected verdict (amber-dashboard-drift over-fired to
              GREEN); overall_pass=False; failed=1
  * red     - 6/9 scenarios diverged including a slot-sequence
              validation error on red-multi-blocker;
              overall_pass=False; failed=3

This file covers (>= 12 tests):

  T01  All three fixtures committed and well-formed JSON.
  T02  Each fixture's sha256 matches the pinned FIXTURE_SETS entry.
  T03  Each fixture's scenario-name list matches its pinned tuple
       in order.
  T04  Each fixture's computed_verdict tuple matches its pinned
       tuple.
  T05  Each fixture's overall_pass matches its pinned flag.
  T06  Replay-helper returns EXIT_OK + REPLAY-STABLE for each set
       when given the correct fixture-set.
  T07  Replay-helper returns EXIT_DIVERGED when CAUTION fixture is
       replayed against GREEN pins (cross-set drift).
  T08  Replay-helper returns EXIT_DIVERGED when RED fixture is
       replayed against CAUTION pins (cross-set drift).
  T09  Replay-helper returns EXIT_DIVERGED when GREEN fixture is
       replayed against RED pins (cross-set drift).
  T10  FIXTURE_SETS dict keys are exactly {green, caution, red}.
  T11  resolve_fixture_set() raises KeyError on unknown set name.
  T12  --fixture-set CLI flag end-to-end: each set emits its
       canonical verdict via subprocess.
  T13  --fixture-set defaults to "green" preserving Tag-59 backwards
       compatibility when no flag is passed.
  T14  Workflow YAML matrix-strategy references all three fixture
       files exactly once each and uses --fixture-set per leg.
  T15  CAUTION fixture has overall_pass=False, failed=1, passed=8.
  T16  RED fixture has overall_pass=False, failed=3, passed=6, and
       at least one sequence_validation_ok=False scenario.
  T17  Cross-fixture-set verdicts are not interchangeable: replay-
       envelope.fixture_set is recorded and matches the requested set.

Author: Noa Bergstroem (SRE)
Anchor: Tag-61 Marathon-Continuous-Mode Multi-Sample-Fixture-
        Erweiterung (Pre-KW-24 Watch-Day-Runbook-Coverage).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests" / "observability" / "fixtures"
HELPER_PATH = REPO_ROOT / "tooling" / "ci" / "aggregate_watch_day_practice_run_verdict.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "watch-day-practice-run-replay.yml"

SETS = ("green", "caution", "red")
FIXTURE_FILES = {
    "green": FIXTURE_DIR / "watch-day-practice-run-sample-green.json",
    "caution": FIXTURE_DIR / "watch-day-practice-run-sample-caution.json",
    "red": FIXTURE_DIR / "watch-day-practice-run-sample-red.json",
}


def _load_helper_module():
    spec = importlib.util.spec_from_file_location(
        "aggregate_watch_day_practice_run_verdict", HELPER_PATH
    )
    assert spec and spec.loader, "helper module not importable"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def helper():
    return _load_helper_module()


# ---------------------------------------------------------------------------
# T01 - All three fixtures committed and well-formed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("set_name", SETS)
def test_t01_fixture_committed_and_well_formed(set_name: str) -> None:
    path = FIXTURE_FILES[set_name]
    assert path.is_file(), f"fixture missing for set {set_name!r}: {path}"
    # well-formed JSON
    json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# T02 - Pinned sha256 per set
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("set_name", SETS)
def test_t02_fixture_sha256_matches_pin(set_name: str, helper) -> None:
    path = FIXTURE_FILES[set_name]
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    pinned = helper.FIXTURE_SETS[set_name]["sha256"]
    assert actual == pinned, (
        f"fixture sha256 drift for set {set_name!r}: "
        f"actual={actual} pinned={pinned}"
    )


# ---------------------------------------------------------------------------
# T03 - Scenario-name list matches pinned tuple in order
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("set_name", SETS)
def test_t03_fixture_scenario_names_and_order(set_name: str, helper) -> None:
    path = FIXTURE_FILES[set_name]
    report = json.loads(path.read_text(encoding="utf-8"))
    expected_names = [n for (n, _v) in helper.FIXTURE_SETS[set_name]["verdicts"]]
    actual_names = [s["scenario"] for s in report["scenarios"]]
    assert actual_names == expected_names


# ---------------------------------------------------------------------------
# T04 - computed_verdict tuple matches pinned tuple
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("set_name", SETS)
def test_t04_fixture_computed_verdicts_match_pin(set_name: str, helper) -> None:
    path = FIXTURE_FILES[set_name]
    report = json.loads(path.read_text(encoding="utf-8"))
    actual_pairs = tuple(
        (s["scenario"], s["computed_verdict"]) for s in report["scenarios"]
    )
    assert actual_pairs == helper.FIXTURE_SETS[set_name]["verdicts"]


# ---------------------------------------------------------------------------
# T05 - overall_pass matches per-set flag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("set_name", SETS)
def test_t05_fixture_overall_pass_matches_pin(set_name: str, helper) -> None:
    path = FIXTURE_FILES[set_name]
    report = json.loads(path.read_text(encoding="utf-8"))
    pinned = helper.FIXTURE_SETS[set_name]["overall_pass"]
    assert report["overall_pass"] is pinned


# ---------------------------------------------------------------------------
# T06 - REPLAY-STABLE for each set when given correct fixture-set
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("set_name", SETS)
def test_t06_replay_helper_each_set_stable(set_name: str, helper, tmp_path: Path) -> None:
    out_path = tmp_path / "envelope.json"
    spec = helper.FIXTURE_SETS[set_name]
    rc = helper.mode_replay(
        FIXTURE_FILES[set_name],
        out_path,
        expected_sha256=spec["sha256"],
        expected_verdicts=spec["verdicts"],
        expected_overall_pass=spec["overall_pass"],
        fixture_set_name=set_name,
    )
    assert rc == helper.EXIT_OK
    envelope = json.loads(out_path.read_text(encoding="utf-8"))
    assert envelope["verdict"] == helper.REPLAY_STABLE
    assert envelope["drift_reasons"] == []
    assert envelope["fixture_set"] == set_name
    assert envelope["fixture_sha256_actual"] == spec["sha256"]


# ---------------------------------------------------------------------------
# T07 - Cross-set drift: CAUTION fixture vs GREEN pins
# ---------------------------------------------------------------------------


def test_t07_caution_fixture_against_green_pins_diverges(
    helper, tmp_path: Path
) -> None:
    out_path = tmp_path / "envelope.json"
    green_spec = helper.FIXTURE_SETS["green"]
    rc = helper.mode_replay(
        FIXTURE_FILES["caution"],
        out_path,
        expected_sha256=green_spec["sha256"],
        expected_verdicts=green_spec["verdicts"],
        expected_overall_pass=green_spec["overall_pass"],
        fixture_set_name="green",
    )
    assert rc == helper.EXIT_DIVERGED
    envelope = json.loads(out_path.read_text(encoding="utf-8"))
    assert envelope["verdict"] == helper.REPLAY_DRIFT
    # We expect all three drift reasons to fire when a CAUTION
    # fixture is compared against GREEN pins: sha256, verdict-pair,
    # and overall_pass.
    reasons = " ".join(envelope["drift_reasons"])
    assert "sha256 drift" in reasons
    assert "verdict-pair drift" in reasons
    assert "overall_pass drift" in reasons


# ---------------------------------------------------------------------------
# T08 - Cross-set drift: RED fixture vs CAUTION pins
# ---------------------------------------------------------------------------


def test_t08_red_fixture_against_caution_pins_diverges(
    helper, tmp_path: Path
) -> None:
    out_path = tmp_path / "envelope.json"
    caution_spec = helper.FIXTURE_SETS["caution"]
    rc = helper.mode_replay(
        FIXTURE_FILES["red"],
        out_path,
        expected_sha256=caution_spec["sha256"],
        expected_verdicts=caution_spec["verdicts"],
        expected_overall_pass=caution_spec["overall_pass"],
        fixture_set_name="caution",
    )
    assert rc == helper.EXIT_DIVERGED
    envelope = json.loads(out_path.read_text(encoding="utf-8"))
    assert envelope["verdict"] == helper.REPLAY_DRIFT
    reasons = " ".join(envelope["drift_reasons"])
    # RED fixture against CAUTION pins: sha + verdict-pair must
    # diverge. overall_pass=False in both so that one does NOT
    # diverge.
    assert "sha256 drift" in reasons
    assert "verdict-pair drift" in reasons
    assert "overall_pass drift" not in reasons


# ---------------------------------------------------------------------------
# T09 - Cross-set drift: GREEN fixture vs RED pins
# ---------------------------------------------------------------------------


def test_t09_green_fixture_against_red_pins_diverges(
    helper, tmp_path: Path
) -> None:
    out_path = tmp_path / "envelope.json"
    red_spec = helper.FIXTURE_SETS["red"]
    rc = helper.mode_replay(
        FIXTURE_FILES["green"],
        out_path,
        expected_sha256=red_spec["sha256"],
        expected_verdicts=red_spec["verdicts"],
        expected_overall_pass=red_spec["overall_pass"],
        fixture_set_name="red",
    )
    assert rc == helper.EXIT_DIVERGED
    envelope = json.loads(out_path.read_text(encoding="utf-8"))
    assert envelope["verdict"] == helper.REPLAY_DRIFT
    reasons = " ".join(envelope["drift_reasons"])
    assert "sha256 drift" in reasons
    assert "verdict-pair drift" in reasons
    assert "overall_pass drift" in reasons


# ---------------------------------------------------------------------------
# T10 - FIXTURE_SETS keys exactness
# ---------------------------------------------------------------------------


def test_t10_fixture_sets_keys(helper) -> None:
    assert set(helper.FIXTURE_SETS.keys()) == {"green", "caution", "red"}
    for set_name, spec in helper.FIXTURE_SETS.items():
        assert set(spec.keys()) == {
            "fixture_name",
            "sha256",
            "verdicts",
            "overall_pass",
        }
        assert isinstance(spec["sha256"], str) and len(spec["sha256"]) == 64
        assert isinstance(spec["verdicts"], tuple) and len(spec["verdicts"]) == 9
        assert isinstance(spec["overall_pass"], bool)
        assert spec["fixture_name"].startswith(
            "watch-day-practice-run-sample-"
        )


# ---------------------------------------------------------------------------
# T11 - resolve_fixture_set raises on unknown name
# ---------------------------------------------------------------------------


def test_t11_resolve_fixture_set_unknown_raises(helper) -> None:
    with pytest.raises(KeyError) as exc:
        helper.resolve_fixture_set("yellow")
    assert "yellow" in str(exc.value)
    # Known sets resolve cleanly.
    for set_name in SETS:
        spec = helper.resolve_fixture_set(set_name)
        assert spec is helper.FIXTURE_SETS[set_name]


# ---------------------------------------------------------------------------
# T12 - End-to-end CLI: each --fixture-set emits its canonical verdict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("set_name", SETS)
def test_t12_cli_fixture_set_flag_each_set(set_name: str, tmp_path: Path) -> None:
    out_path = tmp_path / f"envelope-{set_name}.json"
    rc = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--replay-mode",
            "--fixture-set",
            set_name,
            "--output",
            str(out_path),
        ],
        check=False,
        cwd=str(REPO_ROOT),
    ).returncode
    assert rc == 0, f"set {set_name!r} exited non-zero: {rc}"
    envelope = json.loads(out_path.read_text(encoding="utf-8"))
    assert envelope["verdict"] == "REPLAY-STABLE"
    assert envelope["fixture_set"] == set_name


# ---------------------------------------------------------------------------
# T13 - Default --fixture-set is "green" (Tag-59 BC)
# ---------------------------------------------------------------------------


def test_t13_fixture_set_default_is_green(tmp_path: Path) -> None:
    out_path = tmp_path / "envelope.json"
    rc = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--replay-mode",
            "--output",
            str(out_path),
        ],
        check=False,
        cwd=str(REPO_ROOT),
    ).returncode
    assert rc == 0
    envelope = json.loads(out_path.read_text(encoding="utf-8"))
    assert envelope["fixture_set"] == "green"
    assert envelope["verdict"] == "REPLAY-STABLE"


# ---------------------------------------------------------------------------
# T14 - Workflow YAML matrix references all three sets
# ---------------------------------------------------------------------------


def test_t14_workflow_yaml_matrix_covers_all_sets() -> None:
    assert WORKFLOW_PATH.is_file()
    yaml_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    # Each fixture file referenced exactly once in the path-filter +
    # at least once in the matrix include block.
    for set_name in SETS:
        fname = f"watch-day-practice-run-sample-{set_name}.json"
        assert fname in yaml_text, f"missing fixture-ref: {fname}"
        # And the matrix-leg name appears.
        assert f"fixture_set: {set_name}" in yaml_text
    # --fixture-set wired into the helper invocation.
    assert "--fixture-set ${{ matrix.fixture_set }}" in yaml_text
    # workflow_dispatch + pull_request triggers preserved.
    assert "workflow_dispatch" in yaml_text
    assert "pull_request" in yaml_text
    # REPLAY-STABLE / REPLAY-DRIFT strings still present.
    assert "REPLAY-STABLE" in yaml_text
    assert "REPLAY-DRIFT" in yaml_text


# ---------------------------------------------------------------------------
# T15 - CAUTION fixture shape: 8/9 pass, overall_pass=False
# ---------------------------------------------------------------------------


def test_t15_caution_fixture_shape() -> None:
    report = json.loads(FIXTURE_FILES["caution"].read_text(encoding="utf-8"))
    assert report["overall_pass"] is False
    assert report["failed"] == 1
    assert report["passed"] == 8
    assert report["total"] == 9
    # Exactly one scenario diverged (pass=False).
    failing = [s for s in report["scenarios"] if s["pass"] is False]
    assert len(failing) == 1
    assert failing[0]["scenario"] == "amber-dashboard-drift"
    # The diverged scenario's computed_verdict differs from expected.
    assert failing[0]["computed_verdict"] != failing[0]["expected_verdict"]


# ---------------------------------------------------------------------------
# T16 - RED fixture shape: 3 fails + sequence-validation drift
# ---------------------------------------------------------------------------


def test_t16_red_fixture_shape() -> None:
    report = json.loads(FIXTURE_FILES["red"].read_text(encoding="utf-8"))
    assert report["overall_pass"] is False
    assert report["failed"] == 3
    assert report["passed"] == 6
    assert report["total"] == 9
    failing = [s for s in report["scenarios"] if s["pass"] is False]
    assert len(failing) == 3
    failing_names = {s["scenario"] for s in failing}
    assert failing_names == {"amber-probe", "red-probe", "red-multi-blocker"}
    # At least one scenario has a sequence-validation error.
    seq_drifted = [
        s for s in report["scenarios"] if not s.get("sequence_validation_ok", True)
    ]
    assert len(seq_drifted) >= 1
    assert seq_drifted[0]["scenario"] == "red-multi-blocker"
    assert seq_drifted[0]["sequence_validation_errors"]  # non-empty


# ---------------------------------------------------------------------------
# T17 - envelope.fixture_set is faithfully recorded
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("set_name", SETS)
def test_t17_envelope_records_fixture_set(set_name: str, helper, tmp_path: Path) -> None:
    out_path = tmp_path / "envelope.json"
    spec = helper.FIXTURE_SETS[set_name]
    helper.mode_replay(
        FIXTURE_FILES[set_name],
        out_path,
        expected_sha256=spec["sha256"],
        expected_verdicts=spec["verdicts"],
        expected_overall_pass=spec["overall_pass"],
        fixture_set_name=set_name,
    )
    envelope = json.loads(out_path.read_text(encoding="utf-8"))
    assert envelope["fixture_set"] == set_name
    # Schema-version bumped to 2 in Tag-61.
    assert envelope["schema_version"] == 2
