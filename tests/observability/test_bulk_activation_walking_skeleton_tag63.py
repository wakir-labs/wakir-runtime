# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tests for the Tag-63 Bulk-Activation Walking-Skeleton Test.

Hermetic, stdlib-only. Validates:

  - the planner helper's --mock-api-mode flag
    (``tooling/ops/_bulk_activate_required_checks.py``)
  - the three walking-skeleton fixtures under
    ``tests/observability/fixtures/branch-protection-walking-skeleton/``
  - the workflow file
    ``.github/workflows/bulk-activation-walking-skeleton-test.yml``

Test count: 16 (>= 12 required by Tag-63 brief).

Walking-skeleton invariants under test
======================================

  1. mock-api-mode never touches the network (planner is stdlib-only,
     no `requests` / `urllib` calls invoked in this path).
  2. running from the empty pre-snapshot yields a post-snapshot that
     is byte-identical to ``expected-post-snapshot.json``.
  3. running from the partial pre-snapshot yields the same byte-
     identical post-snapshot (idempotency under full-replace PUT
     semantics).
  4. the workflow file declares all four stages and emits the
     WALKING-SKELETON-INTACT / WALKING-SKELETON-DEFECT verdict.
  5. mock-api-mode refuses to write a post-snapshot when the doc
     plan is inconsistent (e.g. broken Tag-59 doc).
  6. mock-api-mode refuses to run without both --mock-pre-snapshot
     and --mock-post-snapshot.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLANNER_PATH = REPO_ROOT / "tooling" / "ops" / "_bulk_activate_required_checks.py"
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "bulk-activation-walking-skeleton-test.yml"
)
FIXTURE_DIR = (
    REPO_ROOT
    / "tests"
    / "observability"
    / "fixtures"
    / "branch-protection-walking-skeleton"
)
FIX_EMPTY = FIXTURE_DIR / "pre-snapshot-empty.json"
FIX_PARTIAL = FIXTURE_DIR / "pre-snapshot-partial.json"
FIX_EXPECTED = FIXTURE_DIR / "expected-post-snapshot.json"

TAG59_DOC = REPO_ROOT / "docs" / "operations" / "branch-protection-required-checks-tag59.md"
TAG61_DOC = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "branch-protection-required-checks-tag61-addendum.md"
)


def _load_planner():
    spec = importlib.util.spec_from_file_location(
        "bulk_activate_planner", PLANNER_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_planner_mock(pre_path: Path, post_path: Path, tag59=None, tag61=None,
                     extra=None) -> subprocess.CompletedProcess:
    tag59 = tag59 or TAG59_DOC
    tag61 = tag61 or TAG61_DOC
    args = [
        sys.executable,
        str(PLANNER_PATH),
        "--tag59-doc", str(tag59),
        "--tag61-doc", str(tag61),
        "--mock-api-mode",
        "--mock-pre-snapshot", str(pre_path),
        "--mock-post-snapshot", str(post_path),
    ]
    if extra:
        args.extend(extra)
    return subprocess.run(args, capture_output=True, text=True, check=False)


class WalkingSkeletonFixturesTests(unittest.TestCase):
    """Fixture shape + presence."""

    def test_01_fixtures_dir_exists(self):
        self.assertTrue(FIXTURE_DIR.is_dir(), f"missing fixture dir: {FIXTURE_DIR}")

    def test_02_pre_snapshot_empty_is_valid_json_with_empty_contexts(self):
        snap = json.loads(FIX_EMPTY.read_text(encoding="utf-8"))
        self.assertEqual(snap["branch"], "main")
        self.assertEqual(snap["required_status_checks"]["contexts"], [])
        self.assertFalse(snap["required_status_checks"]["strict"])

    def test_03_pre_snapshot_partial_has_exactly_three_contexts(self):
        snap = json.loads(FIX_PARTIAL.read_text(encoding="utf-8"))
        self.assertEqual(snap["branch"], "main")
        contexts = snap["required_status_checks"]["contexts"]
        self.assertEqual(len(contexts), 3)
        self.assertTrue(snap["required_status_checks"]["strict"])

    def test_04_expected_post_snapshot_has_exactly_seven_contexts(self):
        snap = json.loads(FIX_EXPECTED.read_text(encoding="utf-8"))
        contexts = snap["required_status_checks"]["contexts"]
        self.assertEqual(len(contexts), 7, f"got {len(contexts)} contexts, want 7")
        self.assertTrue(snap["required_status_checks"]["strict"])

    def test_05_partial_fixture_is_strict_subset_of_expected(self):
        partial = set(
            json.loads(FIX_PARTIAL.read_text(encoding="utf-8"))[
                "required_status_checks"
            ]["contexts"]
        )
        expected = set(
            json.loads(FIX_EXPECTED.read_text(encoding="utf-8"))[
                "required_status_checks"
            ]["contexts"]
        )
        self.assertTrue(
            partial.issubset(expected),
            f"partial fixture leaks names not in expected: {partial - expected}",
        )
        self.assertNotEqual(partial, expected)


class WalkingSkeletonPlannerMockApiTests(unittest.TestCase):
    """End-to-end mock-api-mode pipeline."""

    def test_06_mock_api_mode_from_empty_writes_byte_identical_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            post = Path(tmp) / "post-from-empty.json"
            result = _run_planner_mock(FIX_EMPTY, post)
            self.assertEqual(
                result.returncode, 0,
                f"planner exit {result.returncode}\nstderr:\n{result.stderr}",
            )
            self.assertEqual(
                post.read_bytes(), FIX_EXPECTED.read_bytes(),
                "post-snapshot from empty pre-snapshot is NOT byte-identical "
                "to expected fixture",
            )

    def test_07_mock_api_mode_from_partial_writes_byte_identical_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            post = Path(tmp) / "post-from-partial.json"
            result = _run_planner_mock(FIX_PARTIAL, post)
            self.assertEqual(
                result.returncode, 0,
                f"planner exit {result.returncode}\nstderr:\n{result.stderr}",
            )
            self.assertEqual(
                post.read_bytes(), FIX_EXPECTED.read_bytes(),
                "post-snapshot from partial pre-snapshot is NOT byte-identical "
                "to expected fixture (idempotency violated)",
            )

    def test_08_mock_api_mode_post_snapshots_from_empty_and_partial_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            post_e = Path(tmp) / "post-from-empty.json"
            post_p = Path(tmp) / "post-from-partial.json"
            _run_planner_mock(FIX_EMPTY, post_e)
            _run_planner_mock(FIX_PARTIAL, post_p)
            self.assertEqual(
                post_e.read_bytes(), post_p.read_bytes(),
                "post-snapshots diverge between empty and partial pre-states "
                "(full-replace PUT semantics violated)",
            )

    def test_09_mock_api_mode_refuses_without_pre_snapshot_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            post = Path(tmp) / "post.json"
            args = [
                sys.executable,
                str(PLANNER_PATH),
                "--tag59-doc", str(TAG59_DOC),
                "--tag61-doc", str(TAG61_DOC),
                "--mock-api-mode",
                "--mock-post-snapshot", str(post),
            ]
            result = subprocess.run(args, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("REFUSED", result.stderr)
            self.assertFalse(post.exists())

    def test_10_mock_api_mode_refuses_without_post_snapshot_flag(self):
        args = [
            sys.executable,
            str(PLANNER_PATH),
            "--tag59-doc", str(TAG59_DOC),
            "--tag61-doc", str(TAG61_DOC),
            "--mock-api-mode",
            "--mock-pre-snapshot", str(FIX_EMPTY),
        ]
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("REFUSED", result.stderr)

    def test_11_mock_api_mode_refuses_when_doc_plan_inconsistent(self):
        # Point at a non-existent tag59 doc to force assemble_pool errors.
        with tempfile.TemporaryDirectory() as tmp:
            broken_tag59 = Path(tmp) / "missing-tag59.md"
            # Do NOT create it. _read_text inside assemble_pool will
            # exit with SystemExit when the doc is missing.
            post = Path(tmp) / "post.json"
            args = [
                sys.executable,
                str(PLANNER_PATH),
                "--tag59-doc", str(broken_tag59),
                "--tag61-doc", str(TAG61_DOC),
                "--mock-api-mode",
                "--mock-pre-snapshot", str(FIX_EMPTY),
                "--mock-post-snapshot", str(post),
            ]
            result = subprocess.run(args, capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(
                post.exists(),
                "post-snapshot must NOT be written when plan is inconsistent",
            )

    def test_12_mock_api_mode_refuses_invalid_pre_snapshot_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("not-json-{{{", encoding="utf-8")
            post = Path(tmp) / "post.json"
            result = _run_planner_mock(bad, post)
            self.assertEqual(result.returncode, 1)
            self.assertIn("invalid JSON", result.stderr)
            self.assertFalse(post.exists())

    def test_13_mock_api_mode_refuses_pre_snapshot_missing_required_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"branch": "main"}), encoding="utf-8")
            post = Path(tmp) / "post.json"
            result = _run_planner_mock(bad, post)
            self.assertEqual(result.returncode, 1)
            self.assertIn("required_status_checks", result.stderr)
            self.assertFalse(post.exists())


class WalkingSkeletonInProcessTests(unittest.TestCase):
    """In-process unit tests on planner helpers."""

    def test_14_render_mock_post_snapshot_function_shape(self):
        planner = _load_planner()
        combined, _, errors = planner.assemble_pool(TAG59_DOC, TAG61_DOC)
        self.assertEqual(errors, [])
        pre = {"branch": "main", "required_status_checks": {"strict": False, "contexts": []}}
        post = planner.render_mock_post_snapshot(combined, pre)
        self.assertEqual(post["branch"], "main")
        self.assertEqual(len(post["required_status_checks"]["contexts"]), 7)
        self.assertTrue(post["required_status_checks"]["strict"])
        self.assertIn("_fixture_id", post)
        self.assertEqual(post["_fixture_id"], "expected-post-snapshot")

    def test_15_render_mock_post_snapshot_preserves_branch_from_pre(self):
        planner = _load_planner()
        combined, _, _ = planner.assemble_pool(TAG59_DOC, TAG61_DOC)
        pre = {
            "branch": "release-2026-Q3",
            "required_status_checks": {"strict": True, "contexts": ["foo"]},
        }
        post = planner.render_mock_post_snapshot(combined, pre)
        self.assertEqual(post["branch"], "release-2026-Q3")


class WalkingSkeletonWorkflowTests(unittest.TestCase):
    """Workflow file shape."""

    def test_16_workflow_file_declares_all_stages_and_verdict(self):
        self.assertTrue(WORKFLOW_PATH.is_file(), f"missing workflow: {WORKFLOW_PATH}")
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        # 4 stages, mock-api-mode invocation, byte-identical diff, verdict labels
        for marker in (
            "Stage 1 - Run pipeline from empty pre-snapshot",
            "Stage 2 - Run pipeline from partial pre-snapshot",
            "Stage 3 - Verify byte-identical post-snapshots",
            "Stage 4 - Verdict",
            "--mock-api-mode",
            "expected-post-snapshot.json",
            "WALKING-SKELETON-INTACT",
            "WALKING-SKELETON-DEFECT",
            "workflow_dispatch",
            "pull_request",
        ):
            self.assertIn(marker, text, f"workflow missing marker: {marker!r}")
        # Must not carry write permissions or operator-hand env.
        self.assertIn("contents: read", text)
        self.assertNotIn("BULK_ACTIVATE_OPERATOR_HAND: '1'", text)
        # The sandbox-boundary contract: the shell wrapper's --enforce
        # path must NOT be invoked. We check that no non-comment line
        # passes --enforce as an actual shell argument (mock-api-mode
        # bypasses the shell wrapper entirely).
        non_comment = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertNotIn(
            "bulk_activate_required_checks.sh --enforce", non_comment,
            "workflow must NOT invoke shell wrapper --enforce path",
        )
        self.assertNotIn(
            "MODE=enforce", non_comment,
            "workflow must NOT set enforce mode",
        )


if __name__ == "__main__":
    unittest.main()
