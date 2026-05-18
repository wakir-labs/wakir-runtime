# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/phase-3c/pre-cutover-probe-phase-live-demo.py``.

These tests must not open a network socket, must not invoke real
``gh``, and must not depend on the live wakir-pilot VM.  The demo
script's only external interaction is:

* ``bash`` running each ``welle-N-pre-cutover-probe.sh`` -- stubbed by
  writing a fake probe-script into a tmp directory under
  ``scripts/phase-3c/`` and pointing ``--repo-root`` at the tmp.
* ``gh`` workflow dispatch -- stubbed by writing a fake ``gh`` binary
  into a tmp dir and passing ``--gh-bin`` via the public
  ``trigger_marathon_dashboard`` helper (CLI builds its own gh-path
  via shutil.which, so we monkeypatch ``shutil.which`` in CLI tests).

Test scope (12 tests, exceeds Auftrag-Tag-43 minimum of 10):

  1.  test_welle_catalogue_has_seven_unique_welles
  2.  test_exit_to_verdict_map_matches_probe_contract
  3.  test_aggregate_marathon_readiness_all_green_is_ready
  4.  test_aggregate_marathon_readiness_one_block_is_block
  5.  test_aggregate_marathon_readiness_seven_not_exec_is_not_ready
  6.  test_aggregate_marathon_readiness_two_caution_is_caution
  7.  test_aggregate_marathon_readiness_three_degraded_is_block
  8.  test_run_single_probe_absent_script_returns_not_exec
  9.  test_run_single_probe_fake_script_exit_zero_is_green
  10. test_run_single_probe_fake_script_exit_two_is_block
  11. test_execute_demo_with_fake_repo_matches_expected_baseline
  12. test_render_ascii_table_contains_per_welle_rows
  13. test_component_overrides_parser_rejects_invalid_input
  14. test_trigger_marathon_dashboard_no_gh_binary_returns_failure
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------
# Module loader.  The demo script lives under ``scripts/phase-3c/``
# with a dashed filename, which is not a valid module path; load it
# via importlib so the tests can call its functions directly.
# ---------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_PATH = REPO_ROOT / "scripts" / "phase-3c" / \
    "pre-cutover-probe-phase-live-demo.py"


@pytest.fixture(scope="module")
def demo_module():
    # Register in sys.modules BEFORE exec_module so dataclasses can
    # resolve forward-refs via cls.__module__ lookup on Python 3.14+.
    mod_name = "pre_cutover_probe_phase_live_demo"
    spec = importlib.util.spec_from_file_location(mod_name, DEMO_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return mod


# ---------------------------------------------------------------------
# Fake-probe-script helper.  Creates a synthetic
# scripts/phase-3c/welle-N-pre-cutover-probe.sh that exits with the
# requested code and prints a canonical PROBE-VERDICT= line.
# ---------------------------------------------------------------------

def _write_fake_probe(
    repo_root: Path,
    welle: int,
    exit_code: int,
    verdict_line: str | None = None,
) -> Path:
    scripts_dir = repo_root / "scripts" / "phase-3c"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script = scripts_dir / f"welle-{welle}-pre-cutover-probe.sh"
    line = verdict_line or _verdict_for_exit(exit_code)
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        # Consume known flags so the demo's argv passes through.
        "while (( $# > 0 )); do shift || break; done\n"
        f"echo '{line}'\n"
        f"exit {exit_code}\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return script


def _verdict_for_exit(rc: int) -> str:
    return {
        0: "PROBE-VERDICT=GREEN",
        1: "PROBE-VERDICT=CAUTION",
        2: "PROBE-VERDICT=BLOCK",
        3: "PROBE-VERDICT=PRECOND-FAIL",
        4: "PROBE-VERDICT=NOT-EXEC",
    }.get(rc, "PROBE-VERDICT=BLOCK")


# ---------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------

def test_welle_catalogue_has_seven_unique_welles(demo_module):
    cat = demo_module.WELLE_CATALOGUE
    assert len(cat) == 7
    welles = [m["welle"] for m in cat]
    assert sorted(welles) == [1, 2, 3, 4, 5, 6, 7]
    components = [m["component"] for m in cat]
    assert len(set(components)) == 7
    # Doppel-Welle pairs are symmetric where defined.
    for m in cat:
        if m["pair_partner"] is not None:
            partner = next(p for p in cat if p["welle"] == m["pair_partner"])
            assert partner["pair_partner"] == m["welle"]


def test_exit_to_verdict_map_matches_probe_contract(demo_module):
    # Mirrors welle-N-pre-cutover-probe.sh sec-Exit-codes.
    m = demo_module.EXIT_TO_VERDICT
    assert m[0] == "GREEN"
    assert m[1] == "CAUTION"
    assert m[2] == "BLOCK"
    assert m[3] == "BLOCK"   # PRECOND maps to BLOCK
    assert m[4] == "NOT-EXEC"


def _mk_probes(demo_module, verdicts: list[str]):
    """Build a list of ProbeResult objects with given verdicts."""
    probes = []
    for i, v in enumerate(verdicts, start=1):
        probes.append(demo_module.ProbeResult(
            welle=i,
            component=f"c{i}",
            kw=24,
            pair_partner=None,
            pair_mode="solo",
            probe_script=f"scripts/phase-3c/welle-{i}-pre-cutover-probe.sh",
            probe_present=True,
            exit_code=0 if v == "GREEN" else 2,
            verdict=v,
            verdict_source="probe-exit-code",
            expected_verdict="GREEN",
            delta="match" if v == "GREEN" else f"drift:{v}-vs-GREEN",
            stdout_tail="",
            duration_seconds=0.1,
            details="",
        ))
    return probes


def test_aggregate_marathon_readiness_all_green_is_ready(demo_module):
    probes = _mk_probes(demo_module, ["GREEN"] * 7)
    assert demo_module.aggregate_marathon_readiness(probes) == "READY"


def test_aggregate_marathon_readiness_one_block_is_block(demo_module):
    probes = _mk_probes(demo_module, ["GREEN"] * 6 + ["BLOCK"])
    assert demo_module.aggregate_marathon_readiness(probes) == "BLOCK"


def test_aggregate_marathon_readiness_seven_not_exec_is_not_ready(demo_module):
    probes = _mk_probes(demo_module, ["NOT-EXEC"] * 7)
    assert demo_module.aggregate_marathon_readiness(probes) == "NOT-READY"


def test_aggregate_marathon_readiness_two_caution_is_caution(demo_module):
    probes = _mk_probes(demo_module, ["GREEN"] * 5 + ["CAUTION"] * 2)
    assert demo_module.aggregate_marathon_readiness(probes) == "CAUTION"


def test_aggregate_marathon_readiness_three_degraded_is_block(demo_module):
    probes = _mk_probes(
        demo_module,
        ["GREEN"] * 4 + ["CAUTION", "CAUTION", "NOT-EXEC"]
    )
    # 3 degraded -> BLOCK per the rule mirror.
    assert demo_module.aggregate_marathon_readiness(probes) == "BLOCK"


def test_run_single_probe_absent_script_returns_not_exec(demo_module, tmp_path):
    repo_root = tmp_path / "repo"
    (repo_root / "scripts" / "phase-3c").mkdir(parents=True)
    workdir = tmp_path / "wd"
    workdir.mkdir()
    meta = {
        "welle": 1, "component": "v907_verify",
        "kw": 24, "pair_partner": 2, "pair_mode": "parallel",
        "expected_dry_run_verdict": "CAUTION",
        "expected_reason": "test",
    }
    result = demo_module.run_single_probe(
        repo_root=repo_root,
        welle_meta=meta,
        workdir=workdir,
        probe_timeout_seconds=10.0,
    )
    assert result.probe_present is False
    assert result.verdict == "NOT-EXEC"
    assert result.exit_code is None
    assert result.delta == "absent"


def test_run_single_probe_fake_script_exit_zero_is_green(demo_module, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_fake_probe(repo_root, welle=6, exit_code=0)
    workdir = tmp_path / "wd"
    workdir.mkdir()
    meta = {
        "welle": 6, "component": "subscribe_loop",
        "kw": 27, "pair_partner": 7, "pair_mode": "doppel",
        "expected_dry_run_verdict": "GREEN",
        "expected_reason": "all axes dry-run-clean",
    }
    result = demo_module.run_single_probe(
        repo_root=repo_root,
        welle_meta=meta,
        workdir=workdir,
        probe_timeout_seconds=10.0,
    )
    assert result.probe_present is True
    assert result.verdict == "GREEN"
    assert result.exit_code == 0
    assert result.delta == "match"
    assert "PROBE-VERDICT=GREEN" in result.stdout_tail


def test_run_single_probe_fake_script_exit_two_is_block(demo_module, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_fake_probe(repo_root, welle=4, exit_code=2)
    workdir = tmp_path / "wd"
    workdir.mkdir()
    meta = {
        "welle": 4, "component": "state_backing",
        "kw": 26, "pair_partner": 5, "pair_mode": "doppel",
        "expected_dry_run_verdict": "CAUTION",
        "expected_reason": "AXIS-4 yellow without --pair-hash",
    }
    result = demo_module.run_single_probe(
        repo_root=repo_root,
        welle_meta=meta,
        workdir=workdir,
        probe_timeout_seconds=10.0,
    )
    assert result.probe_present is True
    assert result.verdict == "BLOCK"
    assert result.exit_code == 2
    # Observed BLOCK vs expected CAUTION = drift.
    assert result.delta.startswith("drift:")


def test_execute_demo_with_fake_repo_matches_expected_baseline(
    demo_module, tmp_path
):
    """End-to-end demo against a synthetic 7-probe repo.

    We seed exactly the verdict-mix the catalogue expects on clean
    main (5 CAUTION + 1 GREEN + 1 BLOCK) and verify the aggregate
    matches the baseline and every per-Welle delta is ``match``.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    # Match WELLE_CATALOGUE expected baseline.
    exit_mix = {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 0, 7: 3}
    for welle, rc in exit_mix.items():
        _write_fake_probe(repo_root, welle=welle, exit_code=rc)

    workdir = tmp_path / "wd"
    workdir.mkdir()
    run = demo_module.execute_demo(
        repo_root=repo_root,
        mode="sandbox-stub",
        gh_trigger=False,
        gh_workflow="phase-3c-pre-cutover-marathon-dashboard.yml",
        gh_ref="main",
        gh_poll_seconds=0,
        probe_timeout_seconds=15.0,
        component_overrides={},
        workdir=workdir,
        now_utc=datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
    )

    assert run.observed_aggregate == "BLOCK"  # Welle-7 BLOCK
    assert run.expected_aggregate == demo_module.EXPECTED_AGGREGATE_BASELINE
    assert run.aggregate_match is True
    # Every per-Welle delta should be "match" since we seeded the
    # exact baseline mix.
    deltas = [p.delta for p in run.probes]
    assert all(d == "match" for d in deltas), deltas
    # Summary counts must add up.
    counts = run.summary_counts
    assert counts["GREEN"] == 1
    assert counts["CAUTION"] == 5
    assert counts["BLOCK"] == 1
    assert counts["NOT-EXEC"] == 0
    # gh_trigger envelope must include 'attempted' even when False.
    assert run.gh_trigger["attempted"] is False


def test_render_ascii_table_contains_per_welle_rows(demo_module, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    for welle in range(1, 8):
        _write_fake_probe(repo_root, welle=welle, exit_code=0)
    workdir = tmp_path / "wd"
    workdir.mkdir()
    run = demo_module.execute_demo(
        repo_root=repo_root,
        mode="sandbox-stub",
        gh_trigger=False,
        gh_workflow="x.yml",
        gh_ref="main",
        gh_poll_seconds=0,
        probe_timeout_seconds=15.0,
        component_overrides={},
        workdir=workdir,
        now_utc=datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc),
    )
    table = demo_module.render_ascii_table(run)
    # All seven components must appear in the table.
    for meta in demo_module.WELLE_CATALOGUE:
        assert meta["component"] in table
    # Doppel-welle coupling section must surface pairs.
    assert "Doppel-Welle Coupling" in table
    assert "ALIGNED" in table  # all-GREEN means every pair is aligned.
    # GH-Trigger section must say not-attempted.
    assert "not-attempted" in table
    # Schema integrity: a heading line for verdicts.
    assert "Per-Welle Verdicts" in table


def test_component_overrides_parser_rejects_invalid_input(demo_module):
    parse = demo_module._parse_component_overrides
    assert parse("") == {}
    assert parse('{"1": "foo"}') == {1: "foo"}
    import argparse as _arg
    with pytest.raises(_arg.ArgumentTypeError):
        parse("not-json")
    with pytest.raises(_arg.ArgumentTypeError):
        parse('["array", "not-object"]')
    with pytest.raises(_arg.ArgumentTypeError):
        parse('{"99": "out-of-range"}')
    with pytest.raises(_arg.ArgumentTypeError):
        parse('{"3": ""}')  # empty component name


def test_trigger_marathon_dashboard_no_gh_binary_returns_failure(demo_module):
    # Pass an explicit non-existent gh path to bypass shutil.which.
    result = demo_module.trigger_marathon_dashboard(
        workflow="phase-3c-pre-cutover-marathon-dashboard.yml",
        ref="main",
        poll_seconds=0,
        gh_bin="/nonexistent/path/to/gh-binary-that-does-not-exist",
    )
    # The OSError path -> ok=False, stderr populated.
    assert result["attempted"] is True
    assert result["ok"] is False
    assert "gh trigger error" in result["stderr"] or \
           "gh binary not on PATH" in result["stderr"]
    assert result["run_url"] is None


def test_trigger_marathon_dashboard_fake_gh_success(demo_module, tmp_path):
    """Run the trigger helper against a fake `gh` that exits 0."""
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'Created workflow_dispatch event for ...'\n"
        "exit 0\n"
    )
    fake_gh.chmod(0o755)
    result = demo_module.trigger_marathon_dashboard(
        workflow="phase-3c-pre-cutover-marathon-dashboard.yml",
        ref="main",
        poll_seconds=0,
        gh_bin=str(fake_gh),
    )
    assert result["attempted"] is True
    assert result["ok"] is True
    assert "Created" in result["stdout"]
    assert result["run_url"] is None  # poll_seconds=0 -> no poll
