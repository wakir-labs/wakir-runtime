# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tests for scripts/phase-3c-trigger-gate-aggregator.py — Tag-24 Mini-Welle.

Hermetic, stdlib + PyYAML (already a wakir-runtime baseline dep): the
aggregator module is loaded via importlib from its hyphenated path
under ``scripts/``. Inputs are fabricated under ``tmp_path`` fixtures
that mirror the real repo layout (``scripts/``, ``policies/``,
``quadlet/``, ``wirelang/persona_engine/``). No real cosign / podman /
systemctl invocation. No network.

Scope (12 tests)
----------------

1.  test_module_loads_and_exports_public_surface
2.  test_gate_1_green_when_all_seven_resolvers_defined
3.  test_gate_1_red_when_resolvers_missing
4.  test_gate_2_green_at_target_count_yellow_below_red_above
5.  test_gate_2_red_when_file_missing_or_yaml_broken
6.  test_gate_3_green_at_target_yellow_below_distinct_count_only
7.  test_gate_4_yellow_when_env_unset_and_aggregator_present
8.  test_gate_4_green_when_baseline_has_required_days
9.  test_gate_4_red_when_observability_aggregator_missing
10. test_gate_5_green_executable_yellow_non_exec_red_missing
11. test_aggregate_emits_ready_for_phase_3c_only_when_all_green
12. test_main_cli_json_and_exit_codes
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Dict, List

import pytest


# ---------------------------------------------------------------------------
# Module loader (hyphenated filename -> importlib.util)
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATOR_PATH = REPO_ROOT / "scripts" / "phase-3c-trigger-gate-aggregator.py"


def _load_aggregator_module():
    spec = importlib.util.spec_from_file_location(
        "phase_3c_trigger_gate_aggregator", AGGREGATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


agg = _load_aggregator_module()


# ---------------------------------------------------------------------------
# Synthetic-repo fixture
# ---------------------------------------------------------------------------


def _seed_switch_module(repo: Path, resolvers: List[str]) -> None:
    """Write a fake rust_backend_switch.py with the named def lines."""

    dst = repo / agg.PATH_RUST_BACKEND_SWITCH
    dst.parent.mkdir(parents=True, exist_ok=True)
    body_lines = [
        "# SPDX-License-Identifier: BUSL-1.1",
        '"""Fake module — test fixture."""',
        "",
    ]
    for name in resolvers:
        body_lines.append(f"def {name}(*args, **kwargs):")
        body_lines.append("    return None")
        body_lines.append("")
    dst.write_text("\n".join(body_lines), encoding="utf-8")


def _seed_cosign_policy(repo: Path, binary_names: List[str]) -> None:
    """Write a minimal YAML policy with the given binaries inventory."""

    dst = repo / agg.PATH_COSIGN_POLICY
    dst.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "schema_version: wakir.cosign-policy.phase-3b/1",
        "policy:",
        "  name: test-fixture",
        "binaries:",
    ]
    for n in binary_names:
        lines.append(f"  - name: {n}")
        lines.append(f"    component: persona-engine-{n}")
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _seed_quadlet(repo: Path, components: List[str]) -> None:
    """Write a fake quadlet container file referencing the given components."""

    dst = repo / agg.PATH_QUADLET_INSTALLER
    dst.parent.mkdir(parents=True, exist_ok=True)
    tokens = " ".join(f"wakir-persona-engine-{c}" for c in components)
    body = [
        "[Unit]",
        "Description=test",
        "[Container]",
        f'Exec=-c "set -e; for b in {tokens}; do test -x /opt/wakir/bin/$b; done"',
        "[Install]",
        "WantedBy=multi-user.target",
    ]
    dst.write_text("\n".join(body) + "\n", encoding="utf-8")


def _seed_obs_aggregator(repo: Path) -> None:
    dst = repo / agg.PATH_OBS_AGGREGATOR
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("# fake aggregator\n", encoding="utf-8")


def _seed_live_vm_driver(repo: Path, executable: bool = True) -> None:
    dst = repo / agg.PATH_LIVE_VM_DRIVER
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("#!/usr/bin/env bash\necho ok\n", encoding="utf-8")
    if executable:
        st = dst.stat()
        dst.chmod(st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _seed_baseline_jsonl(path: Path, day_dates: List[str]) -> None:
    """Write a JSONL file with one backend-decision record per supplied date."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for d in day_dates:
            fh.write(
                json.dumps(
                    {
                        "ts": f"{d}T12:00:00Z",
                        "msg": "backend-decision",
                        "domain": "recovery",
                        "chosen_backend": "python",
                    }
                )
                + "\n"
            )


def _seed_full_repo(repo: Path) -> None:
    """Seed a complete, all-gates-green synthetic repo."""

    _seed_switch_module(repo, list(agg.PHASE_3B_RESOLVER_NAMES))
    seven = [
        "recovery",
        "state-backing",
        "fsm",
        "v907-verify",
        "bridge-diff",
        "subscribe-loop",
        "anchor-emitter",
    ]
    _seed_cosign_policy(repo, seven)
    _seed_quadlet(repo, seven)
    _seed_obs_aggregator(repo)
    _seed_live_vm_driver(repo, executable=True)


# ---------------------------------------------------------------------------
# 1. Module surface
# ---------------------------------------------------------------------------


def test_module_loads_and_exports_public_surface():
    """The aggregator exposes the expected gate-evaluator + aggregator API."""

    expected = [
        "evaluate_gate_1_phase_3b_resolvers",
        "evaluate_gate_2_cosign_inventory",
        "evaluate_gate_3_quadlet_inventory",
        "evaluate_gate_4_observability_baseline",
        "evaluate_gate_5_live_vm_driver",
        "aggregate",
        "main",
        "GateStatus",
        "GateResult",
        "AggregatorReport",
        "PHASE_3B_RESOLVER_NAMES",
        "DEFAULT_TARGET_BINARY_COUNT",
        "OBSERVABILITY_BASELINE_PATH_ENV",
    ]
    for name in expected:
        assert hasattr(agg, name), f"missing public surface: {name}"
    # Sanity: there are exactly seven resolvers expected.
    assert len(agg.PHASE_3B_RESOLVER_NAMES) == 7
    assert agg.DEFAULT_TARGET_BINARY_COUNT == 7


# ---------------------------------------------------------------------------
# 2 + 3. Gate-1 resolvers
# ---------------------------------------------------------------------------


def test_gate_1_green_when_all_seven_resolvers_defined(tmp_path):
    _seed_switch_module(tmp_path, list(agg.PHASE_3B_RESOLVER_NAMES))
    g = agg.evaluate_gate_1_phase_3b_resolvers(tmp_path)
    assert g.status is agg.GateStatus.GREEN
    assert g.evidence["found_count"] == 7
    assert g.evidence["missing_resolvers"] == []


def test_gate_1_red_when_resolvers_missing(tmp_path):
    # Only six of seven defined — the anchor-emitter resolver is the
    # Tag-23 final wire-in; omit it to simulate a pre-Tag-23 state.
    subset = [n for n in agg.PHASE_3B_RESOLVER_NAMES if n != "resolve_anchor_emitter_backend"]
    _seed_switch_module(tmp_path, subset)
    g = agg.evaluate_gate_1_phase_3b_resolvers(tmp_path)
    assert g.status is agg.GateStatus.RED
    assert g.evidence["found_count"] == 6
    assert g.evidence["missing_resolvers"] == ["resolve_anchor_emitter_backend"]


def test_gate_1_red_when_file_missing(tmp_path):
    g = agg.evaluate_gate_1_phase_3b_resolvers(tmp_path)
    assert g.status is agg.GateStatus.RED
    assert g.evidence["error"] == "file-missing"


# ---------------------------------------------------------------------------
# 4 + 5. Gate-2 cosign
# ---------------------------------------------------------------------------


def test_gate_2_green_at_target_count_yellow_below_red_above(tmp_path):
    # Exact match -> green
    _seed_cosign_policy(tmp_path, ["a", "b", "c", "d", "e", "f", "g"])
    g_green = agg.evaluate_gate_2_cosign_inventory(tmp_path, target_count=7)
    assert g_green.status is agg.GateStatus.GREEN
    assert g_green.evidence["found_count"] == 7

    # Below target -> yellow (work-in-progress)
    _seed_cosign_policy(tmp_path, ["a", "b", "c", "d", "e"])
    g_yellow = agg.evaluate_gate_2_cosign_inventory(tmp_path, target_count=7)
    assert g_yellow.status is agg.GateStatus.YELLOW
    assert g_yellow.evidence["found_count"] == 5

    # Above target -> red (unexpected drift)
    _seed_cosign_policy(tmp_path, ["a", "b", "c", "d", "e", "f", "g", "h"])
    g_red = agg.evaluate_gate_2_cosign_inventory(tmp_path, target_count=7)
    assert g_red.status is agg.GateStatus.RED
    assert g_red.evidence["found_count"] == 8


def test_gate_2_red_when_file_missing_or_yaml_broken(tmp_path):
    # File missing
    g_missing = agg.evaluate_gate_2_cosign_inventory(tmp_path, target_count=7)
    assert g_missing.status is agg.GateStatus.RED
    assert g_missing.evidence["error"] == "file-missing"

    # YAML present but ``binaries`` key missing
    p = tmp_path / agg.PATH_COSIGN_POLICY
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("schema_version: foo\npolicy:\n  name: bar\n", encoding="utf-8")
    g_broken = agg.evaluate_gate_2_cosign_inventory(tmp_path, target_count=7)
    assert g_broken.status is agg.GateStatus.RED
    assert "binaries" in g_broken.evidence["error"]


# ---------------------------------------------------------------------------
# 6. Gate-3 quadlet
# ---------------------------------------------------------------------------


def test_gate_3_green_at_target_yellow_below_distinct_count_only(tmp_path):
    # Repeated tokens collapse to distinct count — the for-loop and the
    # in-image-path probe both reference the same set; only the
    # distinct binaries count toward the inventory invariant.
    components = ["recovery", "state-backing", "fsm", "v907-verify", "bridge-diff", "subscribe-loop", "anchor-emitter"]
    dst = tmp_path / agg.PATH_QUADLET_INSTALLER
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Mention each twice to exercise the set() dedup.
    repeated = components + components
    tokens = " ".join(f"wakir-persona-engine-{c}" for c in repeated)
    dst.write_text(
        f'Exec=-c "for b in {tokens}; do echo $b; done"\n',
        encoding="utf-8",
    )
    g = agg.evaluate_gate_3_quadlet_inventory(tmp_path, target_count=7)
    assert g.status is agg.GateStatus.GREEN
    assert g.evidence["found_count"] == 7
    assert g.evidence["binary_components"] == sorted(components)

    # Five components -> yellow (Tag-22 baseline state)
    _seed_quadlet(tmp_path, components[:5])
    g_yellow = agg.evaluate_gate_3_quadlet_inventory(tmp_path, target_count=7)
    assert g_yellow.status is agg.GateStatus.YELLOW
    assert g_yellow.evidence["found_count"] == 5

    # Missing file -> red
    (tmp_path / agg.PATH_QUADLET_INSTALLER).unlink()
    g_red = agg.evaluate_gate_3_quadlet_inventory(tmp_path, target_count=7)
    assert g_red.status is agg.GateStatus.RED


# ---------------------------------------------------------------------------
# 7 + 8 + 9. Gate-4 observability baseline
# ---------------------------------------------------------------------------


def test_gate_4_yellow_when_env_unset_and_aggregator_present(tmp_path):
    _seed_obs_aggregator(tmp_path)
    g = agg.evaluate_gate_4_observability_baseline(tmp_path, env={})
    assert g.status is agg.GateStatus.YELLOW
    assert g.evidence["aggregator_present"] is True
    assert g.evidence["baseline"]["reason"] == "env-not-set"


def test_gate_4_green_when_baseline_has_required_days(tmp_path):
    _seed_obs_aggregator(tmp_path)
    baseline = tmp_path / "obs-baseline.jsonl"
    # Seven distinct days — exactly at threshold.
    days = [f"2026-05-{d:02d}" for d in range(10, 17)]
    _seed_baseline_jsonl(baseline, days)
    g = agg.evaluate_gate_4_observability_baseline(
        tmp_path,
        env={agg.OBSERVABILITY_BASELINE_PATH_ENV: str(baseline)},
        min_days=7,
    )
    assert g.status is agg.GateStatus.GREEN
    assert g.evidence["baseline_days_found"] == 7

    # Six days — below threshold, yellow with reason.
    _seed_baseline_jsonl(baseline, days[:6])
    g_short = agg.evaluate_gate_4_observability_baseline(
        tmp_path,
        env={agg.OBSERVABILITY_BASELINE_PATH_ENV: str(baseline)},
        min_days=7,
    )
    assert g_short.status is agg.GateStatus.YELLOW
    assert g_short.evidence["baseline_days_found"] == 6
    assert g_short.evidence["baseline"]["reason"] == "baseline-too-short"


def test_gate_4_red_when_observability_aggregator_missing(tmp_path):
    g = agg.evaluate_gate_4_observability_baseline(tmp_path, env={})
    assert g.status is agg.GateStatus.RED
    assert g.evidence["aggregator_present"] is False


def test_gate_4_yellow_when_baseline_file_missing(tmp_path):
    _seed_obs_aggregator(tmp_path)
    g = agg.evaluate_gate_4_observability_baseline(
        tmp_path,
        env={agg.OBSERVABILITY_BASELINE_PATH_ENV: str(tmp_path / "nope.jsonl")},
    )
    assert g.status is agg.GateStatus.YELLOW
    assert g.evidence["baseline"]["reason"] == "file-not-found"


# ---------------------------------------------------------------------------
# 10. Gate-5 live-vm driver
# ---------------------------------------------------------------------------


def test_gate_5_green_executable_yellow_non_exec_red_missing(tmp_path):
    # Missing -> red.
    g_red = agg.evaluate_gate_5_live_vm_driver(tmp_path)
    assert g_red.status is agg.GateStatus.RED
    assert g_red.evidence["exists"] is False

    # Present + non-exec -> yellow.
    _seed_live_vm_driver(tmp_path, executable=False)
    g_yellow = agg.evaluate_gate_5_live_vm_driver(tmp_path)
    assert g_yellow.status is agg.GateStatus.YELLOW
    assert g_yellow.evidence["executable"] is False

    # Present + exec -> green.
    _seed_live_vm_driver(tmp_path, executable=True)
    g_green = agg.evaluate_gate_5_live_vm_driver(tmp_path)
    assert g_green.status is agg.GateStatus.GREEN
    assert g_green.evidence["executable"] is True


# ---------------------------------------------------------------------------
# 11. End-to-end aggregator
# ---------------------------------------------------------------------------


def test_aggregate_emits_ready_for_phase_3c_only_when_all_green(tmp_path):
    _seed_full_repo(tmp_path)

    # Seed a 7-day baseline so gate-4 is green.
    baseline = tmp_path / "obs.jsonl"
    _seed_baseline_jsonl(baseline, [f"2026-05-{d:02d}" for d in range(10, 17)])

    rpt = agg.aggregate(
        tmp_path,
        target_binary_count=7,
        env={agg.OBSERVABILITY_BASELINE_PATH_ENV: str(baseline)},
        min_baseline_days=7,
    )
    assert rpt.all_green is True
    assert rpt.ready_for_phase_3c is True
    assert rpt.exit_code == 0
    assert len(rpt.gates) == 5

    # Drop the quadlet inventory to 5 — aggregator turns yellow, exit 1.
    _seed_quadlet(tmp_path, ["recovery", "state-backing", "fsm", "v907-verify", "bridge-diff"])
    rpt_yellow = agg.aggregate(
        tmp_path,
        target_binary_count=7,
        env={agg.OBSERVABILITY_BASELINE_PATH_ENV: str(baseline)},
        min_baseline_days=7,
    )
    assert rpt_yellow.ready_for_phase_3c is False
    assert rpt_yellow.exit_code == 1
    statuses = {g.id: g.status for g in rpt_yellow.gates}
    assert statuses["gate-3"] is agg.GateStatus.YELLOW

    # Drop the switch module — aggregator turns red, exit 2.
    (tmp_path / agg.PATH_RUST_BACKEND_SWITCH).unlink()
    rpt_red = agg.aggregate(
        tmp_path,
        target_binary_count=7,
        env={agg.OBSERVABILITY_BASELINE_PATH_ENV: str(baseline)},
        min_baseline_days=7,
    )
    assert rpt_red.ready_for_phase_3c is False
    assert rpt_red.exit_code == 2


def test_report_to_dict_round_trips_through_json(tmp_path):
    _seed_full_repo(tmp_path)
    rpt = agg.aggregate(tmp_path, target_binary_count=7, env={})
    payload = rpt.to_dict()
    # Round-trip via JSON serialisation.
    parsed = json.loads(json.dumps(payload))
    assert parsed["schema"] == "wakir.phase-3c.trigger-gate-report/1"
    assert set(g["id"] for g in parsed["gates"]) == {
        "gate-1",
        "gate-2",
        "gate-3",
        "gate-4",
        "gate-5",
    }
    # all_green key always present and a bool.
    assert isinstance(parsed["all_green"], bool)
    assert isinstance(parsed["ready_for_phase_3c"], bool)


# ---------------------------------------------------------------------------
# 12. CLI surface
# ---------------------------------------------------------------------------


def test_main_cli_json_and_exit_codes(tmp_path):
    _seed_full_repo(tmp_path)
    baseline = tmp_path / "obs.jsonl"
    _seed_baseline_jsonl(baseline, [f"2026-05-{d:02d}" for d in range(10, 17)])

    env_backup = os.environ.get(agg.OBSERVABILITY_BASELINE_PATH_ENV)
    os.environ[agg.OBSERVABILITY_BASELINE_PATH_ENV] = str(baseline)
    try:
        # --json with all-green setup -> exit 0
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = agg.main(
                [
                    "--repo-root",
                    str(tmp_path),
                    "--target-binary-count",
                    "7",
                    "--min-baseline-days",
                    "7",
                    "--json",
                ]
            )
        assert rc == 0
        parsed = json.loads(buf.getvalue())
        assert parsed["ready_for_phase_3c"] is True

        # Human-readable summary path also runs and yields exit 0.
        buf_h = io.StringIO()
        with redirect_stdout(buf_h):
            rc_h = agg.main(
                [
                    "--repo-root",
                    str(tmp_path),
                    "--target-binary-count",
                    "7",
                    "--min-baseline-days",
                    "7",
                ]
            )
        assert rc_h == 0
        assert "READY" in buf_h.getvalue()
    finally:
        if env_backup is None:
            os.environ.pop(agg.OBSERVABILITY_BASELINE_PATH_ENV, None)
        else:
            os.environ[agg.OBSERVABILITY_BASELINE_PATH_ENV] = env_backup
