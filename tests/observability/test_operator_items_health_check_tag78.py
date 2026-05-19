# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-78 hermetic tests for the Operator-Items Health-Check
substrate (workflow + helper + envelope).

This suite exercises three substrates:

* T-A: helper parsing (Tag-77 master-doc -> Item-ID list +
  Prerequisites bullets).
* T-B: helper per-item check + aggregate verdict (READY / CAUTION
  / BLOCKED) including injected defects.
* T-C: workflow file shape (trigger surface, three stages, artifact
  upload, hermetic posture).

All tests are hermetic: stdlib + pytest + filesystem. No network,
no subprocess outside the helper itself, no podman, no live-VM.
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
MASTER_DOC = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "operator-hand-pending-items-konsolidat.md"
)
HELPER_PATH = (
    REPO_ROOT / "tooling" / "ci" / "health_check_operator_items.py"
)
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "operator-items-health-check.yml"
)


def _load_helper():
    mod_name = "health_check_operator_items"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(
        mod_name, HELPER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass-string-annotations on
    # Python 3.14 can resolve ``cls.__module__`` via sys.modules.
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- T-A: helper parsing ---------------------------------------------


def test_a1_helper_module_loads_with_expected_surface():
    """Helper must expose the documented surface."""
    mod = _load_helper()
    for sym in (
        "parse_master_doc_items",
        "parse_master_doc_prerequisites",
        "check_all_items",
        "aggregate_verdict",
        "build_envelope",
        "main",
        "ITEM_CHECK_RECIPES",
        "ALL_ITEMS",
        "VERDICT_READY",
        "VERDICT_CAUTION",
        "VERDICT_BLOCKED",
    ):
        assert hasattr(mod, sym), f"helper missing symbol '{sym}'"


def test_a2_parse_master_doc_returns_ten_items_in_order():
    """Parser must extract I1..I10 in document order."""
    mod = _load_helper()
    text = MASTER_DOC.read_text(encoding="utf-8")
    items = mod.parse_master_doc_items(text)
    assert items == [f"I{n}" for n in range(1, 11)], (
        f"unexpected item order: {items}"
    )


def test_a3_parse_prerequisites_returns_bullets_per_item():
    """Each of I1..I10 must yield >=2 Prerequisites bullets."""
    mod = _load_helper()
    text = MASTER_DOC.read_text(encoding="utf-8")
    for n in range(1, 11):
        item = f"I{n}"
        bullets = mod.parse_master_doc_prerequisites(text, item)
        assert len(bullets) >= 2, (
            f"{item} has only {len(bullets)} prerequisite bullets"
        )


def test_a4_static_recipes_cover_all_ten_items():
    """``ITEM_CHECK_RECIPES`` must have entries for I1..I10."""
    mod = _load_helper()
    assert set(mod.ITEM_CHECK_RECIPES.keys()) == set(mod.ALL_ITEMS), (
        f"recipes={set(mod.ITEM_CHECK_RECIPES.keys())} "
        f"all_items={set(mod.ALL_ITEMS)}"
    )
    for item, recipe in mod.ITEM_CHECK_RECIPES.items():
        assert len(recipe) >= 1, f"{item} has empty recipe"
        for kind, target in recipe:
            assert kind in {"doc", "workflow", "helper", "state-dir"}, (
                f"{item} recipe has unknown kind '{kind}'"
            )
            assert isinstance(target, str) and target, (
                f"{item} recipe has empty target"
            )


# ---- T-B: helper per-item check + aggregator -------------------------


def test_b1_check_all_items_on_actual_repo_returns_ten_statuses():
    mod = _load_helper()
    statuses = mod.check_all_items(REPO_ROOT)
    assert len(statuses) == 10
    seen = {s.item for s in statuses}
    assert seen == set(mod.ALL_ITEMS)
    for s in statuses:
        assert s.status in {"green", "yellow", "red"}


def test_b2_aggregate_all_green_returns_ready():
    mod = _load_helper()
    statuses = [
        mod.ItemStatus(item=i, status="green") for i in mod.ALL_ITEMS
    ]
    assert mod.aggregate_verdict(statuses) == mod.VERDICT_READY


def test_b3_aggregate_one_yellow_returns_caution():
    mod = _load_helper()
    statuses = [
        mod.ItemStatus(item=i, status="green") for i in mod.ALL_ITEMS
    ]
    statuses[3].status = "yellow"
    assert mod.aggregate_verdict(statuses) == mod.VERDICT_CAUTION


def test_b4_aggregate_two_yellow_returns_caution():
    mod = _load_helper()
    statuses = [
        mod.ItemStatus(item=i, status="green") for i in mod.ALL_ITEMS
    ]
    statuses[0].status = "yellow"
    statuses[5].status = "yellow"
    assert mod.aggregate_verdict(statuses) == mod.VERDICT_CAUTION


def test_b5_aggregate_three_yellow_returns_blocked():
    mod = _load_helper()
    statuses = [
        mod.ItemStatus(item=i, status="green") for i in mod.ALL_ITEMS
    ]
    for idx in (0, 4, 8):
        statuses[idx].status = "yellow"
    assert mod.aggregate_verdict(statuses) == mod.VERDICT_BLOCKED


def test_b6_aggregate_any_red_returns_blocked():
    mod = _load_helper()
    statuses = [
        mod.ItemStatus(item=i, status="green") for i in mod.ALL_ITEMS
    ]
    statuses[6].status = "red"
    assert mod.aggregate_verdict(statuses) == mod.VERDICT_BLOCKED


def test_b7_build_envelope_shape(tmp_path):
    """Envelope must carry the documented top-level fields."""
    mod = _load_helper()
    statuses = [
        mod.ItemStatus(item=i, status="green") for i in mod.ALL_ITEMS
    ]
    env = mod.build_envelope(
        statuses, master_doc_items=mod.ALL_ITEMS
    )
    assert env["envelope"] == "operator-items-health-check"
    assert env["version"] == 1
    assert env["tag"] == "tag-78"
    assert env["verdict"] == mod.VERDICT_READY
    assert env["counts"] == {"green": 10, "yellow": 0, "red": 0}
    assert env["pre_cutover_eve_date"] == "2026-06-26"
    assert env["master_doc_sync"]["ok"] is True
    assert isinstance(env["items"], list) and len(env["items"]) == 10
    for it in env["items"]:
        assert {"item", "status", "missing", "note"} <= set(it.keys())


def test_b8_build_envelope_master_doc_sync_mismatch_marks_false():
    mod = _load_helper()
    statuses = [
        mod.ItemStatus(item=i, status="green") for i in mod.ALL_ITEMS
    ]
    env = mod.build_envelope(
        statuses, master_doc_items=["I1", "I2"]
    )
    assert env["master_doc_sync"]["ok"] is False
    assert "do not match" in env["master_doc_sync"]["note"]


def test_b9_evaluate_item_missing_doc_marks_red_or_yellow(tmp_path):
    """Item with missing recipe-primitive must not be green."""
    mod = _load_helper()
    # Empty repo-root: every recipe-primitive is missing.
    statuses = mod.check_all_items(tmp_path)
    for s in statuses:
        assert s.status != "green", (
            f"{s.item} should be non-green in empty repo, "
            f"got {s.status}"
        )


def test_b10_helper_cli_returns_envelope_on_actual_repo(tmp_path):
    """CLI must print a JSON envelope to stdout and exit 0 or 1."""
    out_path = tmp_path / "env.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--repo-root",
            str(REPO_ROOT),
            "--output",
            str(out_path),
            "--quiet",
        ],
        capture_output=True,
        text=True,
    )
    # rc 0 = READY/CAUTION, rc 1 = BLOCKED. Either is a successful
    # run; rc 2 (master-doc missing) is failure here.
    assert proc.returncode in (0, 1), (
        f"unexpected rc={proc.returncode} stderr={proc.stderr!r}"
    )
    env = json.loads(proc.stdout)
    assert env["envelope"] == "operator-items-health-check"
    assert env["verdict"] in (
        "OPERATOR-ITEMS-READY",
        "OPERATOR-ITEMS-CAUTION",
        "OPERATOR-ITEMS-BLOCKED",
    )
    # Output file must exist and parse.
    assert out_path.is_file()
    on_disk = json.loads(out_path.read_text())
    assert on_disk["verdict"] == env["verdict"]


def test_b11_helper_cli_exit_2_on_missing_doc(tmp_path):
    """Missing master-doc must yield exit code 2."""
    proc = subprocess.run(
        [
            sys.executable,
            str(HELPER_PATH),
            "--repo-root",
            str(tmp_path),
            "--quiet",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2, (
        f"expected rc=2 on missing doc, got rc={proc.returncode} "
        f"stderr={proc.stderr!r}"
    )


# ---- T-C: workflow file shape ----------------------------------------


def test_c1_workflow_file_exists():
    assert WORKFLOW_PATH.is_file(), (
        f"workflow missing at {WORKFLOW_PATH}"
    )


def test_c2_workflow_declares_dispatch_and_daily_cron():
    txt = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in txt, (
        "workflow must declare workflow_dispatch"
    )
    # cron 06:00 UTC daily ("0 6 * * *").
    assert '"0 6 * * *"' in txt, (
        "workflow must declare daily 06:00 UTC cron"
    )


def test_c3_workflow_has_three_stage_jobs():
    txt = WORKFLOW_PATH.read_text(encoding="utf-8")
    for stage in (
        "stage-1-parse-master-doc:",
        "stage-2-check-pre-conditions:",
        "stage-3-aggregate-envelope:",
    ):
        assert stage in txt, f"workflow missing job '{stage}'"


def test_c4_workflow_emits_three_verdict_markers():
    """Workflow body must reference the three envelope markers."""
    txt = WORKFLOW_PATH.read_text(encoding="utf-8")
    for v in (
        "OPERATOR-ITEMS-READY",
        "OPERATOR-ITEMS-CAUTION",
        "OPERATOR-ITEMS-BLOCKED",
    ):
        assert v in txt, f"workflow missing verdict marker '{v}'"


def test_c5_workflow_uploads_envelope_artifact():
    """Stage 3 must upload the envelope JSON as a build artifact."""
    txt = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "actions/upload-artifact@v4" in txt, (
        "workflow must use upload-artifact@v4"
    )
    assert "operator-items-health-check-envelope" in txt, (
        "workflow must upload the named envelope artifact"
    )


def test_c6_workflow_references_helper_path():
    """Workflow must invoke ``tooling/ci/health_check_operator_items.py``."""
    txt = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "tooling/ci/health_check_operator_items.py" in txt


def test_c7_workflow_concurrency_group_pinned():
    """Workflow must declare concurrency group (no overlapping runs)."""
    txt = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "concurrency:" in txt
    assert "group: operator-items-health-check" in txt


def test_c8_workflow_permissions_minimal():
    """Workflow must declare minimal permissions (contents: read)."""
    txt = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "permissions:" in txt
    assert "contents: read" in txt
    # Must NOT declare write surfaces for hermetic posture.
    assert "contents: write" not in txt, (
        "hermetic posture: contents: write not allowed"
    )
    assert "id-token: write" not in txt, (
        "hermetic posture: id-token: write not allowed"
    )


def test_c9_workflow_documents_hermetic_posture_in_header():
    """Workflow header comment must declare hermetic posture +
    explicitly list the live-VM-only primitives that are out of
    scope."""
    txt = WORKFLOW_PATH.read_text(encoding="utf-8")
    head = txt.split("\nname:", 1)[0]
    assert "hermetic" in head.lower()
    for primitive in ("cosign", "systemctl", "podman", "gh"):
        assert primitive in head.lower(), (
            f"header must mention live-VM-only primitive "
            f"'{primitive}' as out-of-scope"
        )


# ---- Integration tests bridging helper + workflow --------------------


def test_int1_workflow_path_filter_includes_helper_and_doc():
    """Workflow push-trigger must re-fire on changes to the
    master-doc, the helper, the tests, and the workflow itself."""
    txt = WORKFLOW_PATH.read_text(encoding="utf-8")
    for p in (
        "docs/operations/operator-hand-pending-items-konsolidat.md",
        "tooling/ci/health_check_operator_items.py",
        "tests/observability/test_operator_items_health_check_tag78.py",
        ".github/workflows/operator-items-health-check.yml",
    ):
        assert p in txt, f"workflow push-trigger must include '{p}'"


def test_int2_helper_recipes_referenced_predecessor_docs_actually_exist():
    """Sanity: every recipe-primitive of kind 'doc' must point to a
    real predecessor-doc on HEAD, otherwise the helper would emit
    permanent red without operator-hand drift."""
    mod = _load_helper()
    missing = []
    for item, recipe in mod.ITEM_CHECK_RECIPES.items():
        for kind, target in recipe:
            if kind == "doc":
                if not (REPO_ROOT / target).is_file():
                    missing.append((item, target))
    # We allow up to 2 doc-targets to be missing (e.g. ADR-cross-
    # repo-migration-pattern.md for I8 may land later in Tag-78+
    # corridor). Beyond that, the helper's static recipes drift
    # away from HEAD and must be re-pinned.
    assert len(missing) <= 2, (
        f"too many doc-primitives missing on HEAD: {missing}"
    )


def test_int3_helper_recipes_referenced_workflows_actually_exist():
    """Sanity: every recipe-primitive of kind 'workflow' must point
    to a real workflow on HEAD."""
    mod = _load_helper()
    missing = []
    for item, recipe in mod.ITEM_CHECK_RECIPES.items():
        for kind, target in recipe:
            if kind == "workflow":
                wf = REPO_ROOT / ".github" / "workflows" / target
                if not wf.is_file():
                    missing.append((item, target))
    assert not missing, (
        f"recipe-workflows must exist on HEAD: {missing}"
    )
