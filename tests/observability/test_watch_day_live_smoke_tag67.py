# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-67 Watch-Day Pre-Cutover Live-Smoke tests (Noa SRE).

Pins the substance contract of:

  * ``tooling/ci/aggregate_watch_day_pre_cutover_live_smoke.py``
    -- aggregator helper + substrate-inventory + coupling-map mode.

  * ``.github/workflows/watch-day-pre-cutover-live-smoke.yml``
    -- six-stage Pre-Cutover probe workflow.

Hermetic: pytest + stdlib + python 3.11. No subprocess except the
inline integration test that drives the helper end-to-end.

Author: Noa Bergstroem (SRE)
Anchor: Tag-67 Marathon-Continuous-Mode Pre-KW-24 Watch-Day
        Pre-Cutover Live-Smoke Probe.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = (
    REPO_ROOT
    / "tooling"
    / "ci"
    / "aggregate_watch_day_pre_cutover_live_smoke.py"
)
WORKFLOW = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "watch-day-pre-cutover-live-smoke.yml"
)


def _import_helper():
    mod_name = "aggregate_watch_day_pre_cutover_live_smoke"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, HELPER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# T01 -- helper script + workflow physically exist on disk.
# ---------------------------------------------------------------------------


def test_t01_helper_and_workflow_exist():
    assert HELPER.is_file(), f"helper missing: {HELPER}"
    assert WORKFLOW.is_file(), f"workflow missing: {WORKFLOW}"
    # Helper is pure-stdlib: no third-party imports
    text = HELPER.read_text()
    assert "import argparse" in text
    assert "import json" in text
    # SPDX header present
    assert "SPDX-License-Identifier: Apache-2.0" in text


# ---------------------------------------------------------------------------
# T02 -- helper module imports cleanly + exposes canonical constants.
# ---------------------------------------------------------------------------


def test_t02_helper_module_imports_and_exposes_constants():
    mod = _import_helper()
    assert hasattr(mod, "SUBSTRATE_INVENTORY")
    assert hasattr(mod, "STAGE_KEYS")
    assert hasattr(mod, "STAGE_LABELS")
    assert hasattr(mod, "VERDICT_INTACT")
    assert hasattr(mod, "VERDICT_DRIFT")
    assert hasattr(mod, "VERDICT_DEFECT")
    assert mod.VERDICT_INTACT == "LIVE-SMOKE-INTACT"
    assert mod.VERDICT_DRIFT == "DRIFT"
    assert mod.VERDICT_DEFECT == "DEFECT"
    # Six stages, six labels
    assert len(mod.STAGE_KEYS) == 6
    assert len(mod.STAGE_LABELS) == 6


# ---------------------------------------------------------------------------
# T03 -- substrate inventory covers every required tag in Tag-54..66.
# ---------------------------------------------------------------------------


def test_t03_substrate_inventory_covers_required_tags():
    mod = _import_helper()
    tags_in_inventory = {tag for tag, _, _ in mod.SUBSTRATE_INVENTORY}
    required = {"Tag-56", "Tag-57", "Tag-59", "Tag-61", "Tag-62", "Tag-63", "Tag-66"}
    assert required.issubset(tags_in_inventory), (
        f"missing tags in SUBSTRATE_INVENTORY: {required - tags_in_inventory}"
    )


# ---------------------------------------------------------------------------
# T04 -- every substrate-inventory path physically exists in the repo.
# ---------------------------------------------------------------------------


def test_t04_substrate_inventory_paths_exist():
    mod = _import_helper()
    missing: list[str] = []
    for tag, kind, rel in mod.SUBSTRATE_INVENTORY:
        if not (REPO_ROOT / rel).is_file():
            missing.append(f"{tag}/{kind}/{rel}")
    assert not missing, f"substrate-inventory paths missing on disk: {missing}"


# ---------------------------------------------------------------------------
# T05 -- _classify_verdict truth table (LIVE-SMOKE-INTACT case).
# ---------------------------------------------------------------------------


def test_t05_classify_verdict_intact():
    mod = _import_helper()
    assert (
        mod._classify_verdict(["green"] * 6) == mod.VERDICT_INTACT
    )


# ---------------------------------------------------------------------------
# T06 -- _classify_verdict truth table (DRIFT case: 1 or 2 yellow).
# ---------------------------------------------------------------------------


def test_t06_classify_verdict_drift():
    mod = _import_helper()
    one_yellow = ["green", "green", "yellow", "green", "green", "green"]
    two_yellow = ["green", "yellow", "green", "yellow", "green", "green"]
    assert mod._classify_verdict(one_yellow) == mod.VERDICT_DRIFT
    assert mod._classify_verdict(two_yellow) == mod.VERDICT_DRIFT


# ---------------------------------------------------------------------------
# T07 -- _classify_verdict truth table (DEFECT case: any red, or >=3 yellow).
# ---------------------------------------------------------------------------


def test_t07_classify_verdict_defect():
    mod = _import_helper()
    one_red = ["green", "green", "red", "green", "green", "green"]
    three_yellow = ["yellow", "yellow", "yellow", "green", "green", "green"]
    assert mod._classify_verdict(one_red) == mod.VERDICT_DEFECT
    assert mod._classify_verdict(three_yellow) == mod.VERDICT_DEFECT


# ---------------------------------------------------------------------------
# T08 -- aggregate-mode end-to-end via subprocess emits verdict envelope.
# ---------------------------------------------------------------------------


def test_t08_aggregate_mode_subprocess_intact(tmp_path: Path):
    out = tmp_path / "verdict.json"
    env = os.environ.copy()
    for key in ("STAGE1_STATUS", "STAGE2_STATUS", "STAGE3_STATUS",
                "STAGE4_STATUS", "STAGE5_STATUS", "STAGE6_STATUS"):
        env[key] = "green"
    rc = subprocess.call(
        [sys.executable, str(HELPER), "aggregate", "--output", str(out)],
        env=env,
    )
    assert rc == 0
    envelope = json.loads(out.read_text())
    assert envelope["verdict"] == "LIVE-SMOKE-INTACT"
    assert envelope["kind"] == "watch-day-pre-cutover-live-smoke-verdict"
    assert len(envelope["stages"]) == 6
    for stage in envelope["stages"]:
        assert stage["status"] == "green"


# ---------------------------------------------------------------------------
# T09 -- aggregate-mode missing env var emits error + non-zero rc.
# ---------------------------------------------------------------------------


def test_t09_aggregate_mode_missing_env_var(tmp_path: Path):
    out = tmp_path / "verdict.json"
    env = os.environ.copy()
    # Strip any pre-existing stage vars
    for key in ("STAGE1_STATUS", "STAGE2_STATUS", "STAGE3_STATUS",
                "STAGE4_STATUS", "STAGE5_STATUS", "STAGE6_STATUS"):
        env.pop(key, None)
    # Set only 5 of 6
    for key in ("STAGE1_STATUS", "STAGE2_STATUS", "STAGE3_STATUS",
                "STAGE4_STATUS", "STAGE5_STATUS"):
        env[key] = "green"
    rc = subprocess.call(
        [sys.executable, str(HELPER), "aggregate", "--output", str(out)],
        env=env,
        stderr=subprocess.DEVNULL,
    )
    assert rc == 1


# ---------------------------------------------------------------------------
# T10 -- aggregate-mode invalid status value emits error.
# ---------------------------------------------------------------------------


def test_t10_aggregate_mode_invalid_status(tmp_path: Path):
    out = tmp_path / "verdict.json"
    env = os.environ.copy()
    for key in ("STAGE1_STATUS", "STAGE2_STATUS", "STAGE3_STATUS",
                "STAGE4_STATUS", "STAGE5_STATUS", "STAGE6_STATUS"):
        env[key] = "green"
    env["STAGE3_STATUS"] = "rainbow"
    rc = subprocess.call(
        [sys.executable, str(HELPER), "aggregate", "--output", str(out)],
        env=env,
        stderr=subprocess.DEVNULL,
    )
    assert rc == 1


# ---------------------------------------------------------------------------
# T11 -- pin-substrate mode passes on real repo root.
# ---------------------------------------------------------------------------


def test_t11_pin_substrate_real_repo(tmp_path: Path):
    rc = subprocess.call(
        [sys.executable, str(HELPER), "pin-substrate",
         "--repo-root", str(REPO_ROOT)],
    )
    assert rc == 0


# ---------------------------------------------------------------------------
# T12 -- pin-substrate mode fails on empty repo root.
# ---------------------------------------------------------------------------


def test_t12_pin_substrate_empty_repo_root(tmp_path: Path):
    rc = subprocess.call(
        [sys.executable, str(HELPER), "pin-substrate",
         "--repo-root", str(tmp_path)],
        stderr=subprocess.DEVNULL,
    )
    assert rc == 2


# ---------------------------------------------------------------------------
# T13 -- coupling-map mode emits well-formed envelope with all anchor tags.
# ---------------------------------------------------------------------------


def test_t13_coupling_map_mode(tmp_path: Path):
    out = tmp_path / "coupling_map.json"
    rc = subprocess.call(
        [sys.executable, str(HELPER), "coupling-map", "--output", str(out)],
    )
    assert rc == 0
    envelope = json.loads(out.read_text())
    assert envelope["kind"] == "watch-day-pre-cutover-live-smoke-coupling-map"
    tag_set = {entry["tag"] for entry in envelope["tags"]}
    assert {"Tag-56", "Tag-57", "Tag-59", "Tag-61", "Tag-62", "Tag-63", "Tag-66"}.issubset(tag_set)


# ---------------------------------------------------------------------------
# T14 -- workflow YAML structure: six stage steps + verdict step present.
# ---------------------------------------------------------------------------


def test_t14_workflow_yaml_structure():
    text = WORKFLOW.read_text()
    assert "name: watch-day-pre-cutover-live-smoke" in text
    # Six stage steps + aggregate verdict
    for label in (
        "Stage 1 - practice-run-ci-gate (Tag-56)",
        "Stage 2 - cron-pre-fire-probe (Tag-57)",
        "Stage 3 - replay-multi-sample (Tag-59+61)",
        "Stage 4 - operator-trigger-integration (Tag-62+63)",
        "Stage 5 - audit-trail-verify (Tag-66)",
        "Stage 6 - substrate-coupling-map (Tag-67)",
        "Aggregate verdict",
    ):
        assert label in text, f"missing stage label in workflow: {label}"
    # Triggers
    assert "workflow_dispatch:" in text
    assert "pull_request:" in text
    # Path-filter must cover all sibling workflows + new aggregator + test
    for path in (
        ".github/workflows/watch-day-pre-cutover-live-smoke.yml",
        ".github/workflows/phase-3c-watch-day-practice-run.yml",
        ".github/workflows/watch-day-cron-pre-fire-probe.yml",
        ".github/workflows/watch-day-practice-run-replay.yml",
        ".github/workflows/watch-day-operator-trigger-simulation.yml",
        ".github/workflows/operator-trigger-alert-routing-integration.yml",
        ".github/workflows/watch-day-operator-trigger-audit-trail-verify.yml",
        "tooling/ci/aggregate_watch_day_pre_cutover_live_smoke.py",
        "tests/observability/test_watch_day_live_smoke_tag67.py",
    ):
        assert path in text, f"missing path-filter entry in workflow: {path}"


# ---------------------------------------------------------------------------
# T15 -- workflow permissions are minimal (contents: read only).
# ---------------------------------------------------------------------------


def test_t15_workflow_permissions_minimal():
    text = WORKFLOW.read_text()
    # Top-level permissions block, read-only
    assert "permissions:\n  contents: read" in text
    # No write-* anywhere in the file
    assert "write" not in text.split("permissions:", 1)[1].split("\njobs:", 1)[0]


# ---------------------------------------------------------------------------
# T16 -- helper is REUSE/SPDX-compliant + has author + anchor header.
# ---------------------------------------------------------------------------


def test_t16_helper_reuse_compliance():
    text = HELPER.read_text()
    assert "SPDX-License-Identifier: Apache-2.0" in text
    assert "SPDX-FileCopyrightText" in text or "Copyright (c) 2026" in text
    assert "Noa Bergstroem" in text
    assert "Tag-67" in text
    workflow_text = WORKFLOW.read_text()
    assert "SPDX-License-Identifier: Apache-2.0" in workflow_text
    assert "Tag-67" in workflow_text
