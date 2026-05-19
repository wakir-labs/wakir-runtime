# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-59 Watch-Day-Practice-Run Dry-Run-Replay test-suite.

Coverage matrix (>= 10 tests):

  T01  Fixture file is committed in-tree and well-formed JSON.
  T02  Fixture sha256 matches the pinned Tag-59 constant.
  T03  Fixture contains exactly the nine pinned scenario names in
       the pinned order.
  T04  Fixture computed_verdict per scenario matches the pinned
       expectation tuple.
  T05  Fixture overall_pass == True.
  T06  Replay-helper (mode=replay) on the committed fixture returns
       EXIT_OK and emits REPLAY-STABLE.
  T07  Replay-helper detects sha256 drift when the fixture body is
       perturbed (added trailing whitespace).
  T08  Replay-helper detects verdict-tuple drift when a scenario's
       computed_verdict is rewritten (sha-coverage holds it loud).
  T09  Replay-helper returns EXIT_ERROR when the fixture is missing.
  T10  Replay-helper returns EXIT_ERROR when the fixture is malformed
       JSON.
  T11  Replay-helper detects overall_pass drift (True -> False).
  T12  --replay-mode CLI alias is equivalent to --mode replay.
  T13  Replay envelope is JSON-stable: sorted keys, deterministic.
  T14  Replay-mode does not invoke the live practice-run simulator
       (purely a fixture-replay, hermetic).
  T15  Workflow YAML references the committed fixture path exactly.

Author: Noa Bergstroem (SRE)
Anchor: Tag-59 Pre-Sealing KW-24.
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
FIXTURE_PATH = REPO_ROOT / "tests" / "observability" / "fixtures" / "watch-day-practice-run-sample.json"
HELPER_PATH = REPO_ROOT / "tooling" / "ci" / "aggregate_watch_day_practice_run_verdict.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "watch-day-practice-run-replay.yml"


# Lazy-import the helper module without polluting sys.path.
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


@pytest.fixture(scope="module")
def fixture_bytes() -> bytes:
    return FIXTURE_PATH.read_bytes()


@pytest.fixture(scope="module")
def fixture_report(fixture_bytes: bytes) -> dict:
    return json.loads(fixture_bytes.decode("utf-8"))


# ---------------------------------------------------------------------------
# T01 - Fixture committed + well-formed
# ---------------------------------------------------------------------------


def test_t01_fixture_committed_and_well_formed() -> None:
    assert FIXTURE_PATH.is_file(), f"fixture missing: {FIXTURE_PATH}"
    # well-formed JSON
    json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# T02 - Pinned sha256
# ---------------------------------------------------------------------------


def test_t02_fixture_sha256_matches_pin(fixture_bytes: bytes, helper) -> None:
    actual = hashlib.sha256(fixture_bytes).hexdigest()
    assert actual == helper.TAG59_FIXTURE_SHA256, (
        f"fixture sha256 drift: actual={actual} pinned={helper.TAG59_FIXTURE_SHA256}"
    )


# ---------------------------------------------------------------------------
# T03 - Scenario names + order
# ---------------------------------------------------------------------------


def test_t03_fixture_scenario_names_and_order(
    fixture_report: dict, helper
) -> None:
    expected_names = [n for (n, _v) in helper.TAG59_PINNED_VERDICTS]
    actual_names = [s["scenario"] for s in fixture_report["scenarios"]]
    assert actual_names == expected_names


# ---------------------------------------------------------------------------
# T04 - Verdict tuple per scenario
# ---------------------------------------------------------------------------


def test_t04_fixture_computed_verdicts_match_pin(
    fixture_report: dict, helper
) -> None:
    actual_pairs = tuple(
        (s["scenario"], s["computed_verdict"]) for s in fixture_report["scenarios"]
    )
    assert actual_pairs == helper.TAG59_PINNED_VERDICTS


# ---------------------------------------------------------------------------
# T05 - overall_pass=True
# ---------------------------------------------------------------------------


def test_t05_fixture_overall_pass_is_true(fixture_report: dict) -> None:
    assert fixture_report.get("overall_pass") is True
    assert fixture_report.get("failed") == 0
    assert fixture_report.get("total") == 9
    assert fixture_report.get("passed") == 9


# ---------------------------------------------------------------------------
# T06 - Replay-helper on committed fixture: STABLE
# ---------------------------------------------------------------------------


def test_t06_replay_helper_on_committed_fixture_stable(helper, tmp_path: Path) -> None:
    out_path = tmp_path / "envelope.json"
    rc = helper.mode_replay(FIXTURE_PATH, out_path)
    assert rc == helper.EXIT_OK
    envelope = json.loads(out_path.read_text(encoding="utf-8"))
    assert envelope["verdict"] == helper.REPLAY_STABLE
    assert envelope["drift_reasons"] == []
    assert envelope["fixture_sha256_actual"] == helper.TAG59_FIXTURE_SHA256


# ---------------------------------------------------------------------------
# T07 - sha256 drift detection
# ---------------------------------------------------------------------------


def test_t07_replay_helper_detects_sha_drift(
    helper, tmp_path: Path, fixture_bytes: bytes
) -> None:
    # Perturb the fixture body. We append a trailing newline so the
    # JSON parser still loads cleanly but the bytes diverge.
    perturbed = tmp_path / "perturbed.json"
    perturbed.write_bytes(fixture_bytes + b"\n")
    out_path = tmp_path / "envelope.json"
    rc = helper.mode_replay(perturbed, out_path)
    assert rc == helper.EXIT_DIVERGED
    envelope = json.loads(out_path.read_text(encoding="utf-8"))
    assert envelope["verdict"] == helper.REPLAY_DRIFT
    assert any("sha256 drift" in r for r in envelope["drift_reasons"])


# ---------------------------------------------------------------------------
# T08 - verdict-tuple drift detection
# ---------------------------------------------------------------------------


def test_t08_replay_helper_detects_verdict_tuple_drift(
    helper, tmp_path: Path, fixture_report: dict
) -> None:
    # Rewrite one scenario's computed_verdict and re-serialize. The
    # sha256 will also drift (so we expect both reasons to fire), but
    # we explicitly assert the verdict-tuple-drift branch.
    mutated = json.loads(json.dumps(fixture_report))  # deep copy via JSON
    mutated["scenarios"][0]["computed_verdict"] = "MUTATED"
    perturbed = tmp_path / "mutated.json"
    perturbed.write_text(json.dumps(mutated, indent=2, sort_keys=True), encoding="utf-8")
    out_path = tmp_path / "envelope.json"
    rc = helper.mode_replay(perturbed, out_path)
    assert rc == helper.EXIT_DIVERGED
    envelope = json.loads(out_path.read_text(encoding="utf-8"))
    assert envelope["verdict"] == helper.REPLAY_DRIFT
    assert any("verdict-pair drift" in r for r in envelope["drift_reasons"])


# ---------------------------------------------------------------------------
# T09 - missing fixture
# ---------------------------------------------------------------------------


def test_t09_replay_helper_missing_fixture(helper, tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"
    out_path = tmp_path / "envelope.json"
    rc = helper.mode_replay(missing, out_path)
    assert rc == helper.EXIT_ERROR


# ---------------------------------------------------------------------------
# T10 - malformed fixture
# ---------------------------------------------------------------------------


def test_t10_replay_helper_malformed_fixture(helper, tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    out_path = tmp_path / "envelope.json"
    rc = helper.mode_replay(bad, out_path)
    assert rc == helper.EXIT_ERROR


# ---------------------------------------------------------------------------
# T11 - overall_pass drift
# ---------------------------------------------------------------------------


def test_t11_replay_helper_detects_overall_pass_drift(
    helper, tmp_path: Path, fixture_report: dict
) -> None:
    mutated = json.loads(json.dumps(fixture_report))
    mutated["overall_pass"] = False
    perturbed = tmp_path / "fail.json"
    perturbed.write_text(json.dumps(mutated, indent=2, sort_keys=True), encoding="utf-8")
    out_path = tmp_path / "envelope.json"
    rc = helper.mode_replay(perturbed, out_path)
    assert rc == helper.EXIT_DIVERGED
    envelope = json.loads(out_path.read_text(encoding="utf-8"))
    assert any("overall_pass drift" in r for r in envelope["drift_reasons"])


# ---------------------------------------------------------------------------
# T12 - --replay-mode CLI alias
# ---------------------------------------------------------------------------


def test_t12_replay_mode_cli_alias_equivalent(tmp_path: Path) -> None:
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    out_c = tmp_path / "c.json"
    # Variant A: explicit --mode replay
    rc_a = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--mode",
            "replay",
            "--fixture-path",
            str(FIXTURE_PATH),
            "--output",
            str(out_a),
        ],
        check=False,
    ).returncode
    # Variant B: --mode override + --replay-mode alias
    rc_b = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--mode",
            "pin",  # will be overridden by --replay-mode alias
            "--replay-mode",
            "--fixture-path",
            str(FIXTURE_PATH),
            "--output",
            str(out_b),
        ],
        check=False,
    ).returncode
    # Variant C: --replay-mode alone (the form the workflow uses).
    # Regression-pin: --mode must NOT be required when --replay-mode
    # is given (Tag-59 first-CI-run found this gap).
    rc_c = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--replay-mode",
            "--fixture-path",
            str(FIXTURE_PATH),
            "--output",
            str(out_c),
        ],
        check=False,
    ).returncode
    assert rc_a == 0
    assert rc_b == 0
    assert rc_c == 0
    a = json.loads(out_a.read_text(encoding="utf-8"))
    b = json.loads(out_b.read_text(encoding="utf-8"))
    c = json.loads(out_c.read_text(encoding="utf-8"))
    assert a == b == c
    assert a["verdict"] == "REPLAY-STABLE"


# ---------------------------------------------------------------------------
# T13 - envelope JSON-stable
# ---------------------------------------------------------------------------


def test_t13_envelope_json_is_sorted_and_deterministic(
    helper, tmp_path: Path
) -> None:
    out1 = tmp_path / "e1.json"
    out2 = tmp_path / "e2.json"
    helper.mode_replay(FIXTURE_PATH, out1)
    helper.mode_replay(FIXTURE_PATH, out2)
    a = out1.read_text(encoding="utf-8")
    b = out2.read_text(encoding="utf-8")
    assert a == b, "envelope output is not deterministic"
    # also verify keys are sorted
    raw = out1.read_text(encoding="utf-8").rstrip("\n")
    parsed = json.loads(raw)
    assert list(parsed.keys()) == sorted(parsed.keys())


# ---------------------------------------------------------------------------
# T14 - hermetic: no live-simulator invocation
# ---------------------------------------------------------------------------


def test_t14_replay_mode_is_hermetic_no_simulator_subprocess(
    helper, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sentinel: if mode_replay ever spawns a subprocess (live
    # simulator), this monkeypatch will trip. The replay-mode is
    # supposed to be pure fixture-replay.
    calls: list = []

    def _forbidden_popen(*args, **kwargs):  # pragma: no cover - sentinel
        calls.append((args, kwargs))
        raise AssertionError(
            "replay-mode must not spawn subprocesses; got: "
            f"args={args} kwargs={kwargs}"
        )

    monkeypatch.setattr(subprocess, "Popen", _forbidden_popen)
    monkeypatch.setattr(subprocess, "run", _forbidden_popen)
    monkeypatch.setattr(subprocess, "check_output", _forbidden_popen)

    out_path = tmp_path / "envelope.json"
    rc = helper.mode_replay(FIXTURE_PATH, out_path)
    assert rc == helper.EXIT_OK
    assert calls == []


# ---------------------------------------------------------------------------
# T15 - workflow YAML refers to committed fixture
# ---------------------------------------------------------------------------


def test_t15_workflow_yaml_references_fixture_path() -> None:
    assert WORKFLOW_PATH.is_file()
    yaml_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "tests/observability/fixtures/watch-day-practice-run-sample.json" in yaml_text
    assert "tooling/ci/aggregate_watch_day_practice_run_verdict.py" in yaml_text
    assert "REPLAY-STABLE" in yaml_text
    assert "REPLAY-DRIFT" in yaml_text
    # workflow_dispatch + pull_request triggers
    assert "workflow_dispatch" in yaml_text
    assert "pull_request" in yaml_text
