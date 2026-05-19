# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tests for the Tag-65 Walking-Skeleton Post-Activate-Verify Mode.

Hermetic, stdlib-only. Validates:

  - the planner helper's --post-activate-verify flag
    (``tooling/ops/_bulk_activate_required_checks.py``)
  - the Tag-65 post-activate-snapshot fixture under
    ``tests/observability/fixtures/branch-protection-walking-
    skeleton-tag64/post-activate-snapshot.json``
  - the workflow file's Stage-5 wiring in
    ``.github/workflows/bulk-activation-walking-skeleton-test.yml``

Test count: 15 (>= 12 required by Tag-65 brief).

Post-Activate-Verify invariants under test
==========================================

  1. The clean post-activate snapshot verifies POST-ACTIVATE-CLEAN.
  2. Missing-context detection: a snapshot missing any of the 8
     expected contexts yields POST-ACTIVATE-DEFECT.
  3. Extra-context detection: a snapshot with an extra context not
     in the pool yields POST-ACTIVATE-DEFECT.
  4. Strict-false detection: a snapshot with strict=False yields
     POST-ACTIVATE-DEFECT.
  5. Order-mismatch detection: a snapshot with the right contexts
     but wrong order yields POST-ACTIVATE-DEFECT.
  6. Missing required_status_checks block detection.
  7. Invalid-JSON detection.
  8. Missing-flag detection (--post-activate-snapshot omitted).
  9. The workflow declares Stage 5 with post-activate-verify and
     wires rc5 into Stage 4.
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
FIXTURE_DIR_TAG64 = (
    REPO_ROOT
    / "tests"
    / "observability"
    / "fixtures"
    / "branch-protection-walking-skeleton-tag64"
)
FIX_POST_ACTIVATE = FIXTURE_DIR_TAG64 / "post-activate-snapshot.json"

TAG59_DOC = REPO_ROOT / "docs" / "operations" / "branch-protection-required-checks-tag59.md"
TAG61_DOC = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "branch-protection-required-checks-tag61-addendum.md"
)
TAG64_DOC = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "branch-protection-required-checks-tag64-companion.md"
)


def _load_planner():
    spec = importlib.util.spec_from_file_location(
        "bulk_activate_planner_tag65", PLANNER_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_verify(snapshot_path: Path, extra=None) -> subprocess.CompletedProcess:
    args = [
        sys.executable,
        str(PLANNER_PATH),
        "--tag59-doc", str(TAG59_DOC),
        "--tag61-doc", str(TAG61_DOC),
        "--tag64-doc", str(TAG64_DOC),
        "--post-activate-verify",
        "--post-activate-snapshot", str(snapshot_path),
    ]
    if extra:
        args.extend(extra)
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _write_snapshot(path: Path, contexts, strict=True, branch="main",
                    omit_rsc=False):
    if omit_rsc:
        body = {"branch": branch}
    else:
        body = {
            "branch": branch,
            "required_status_checks": {
                "strict": strict,
                "contexts": list(contexts),
            },
        }
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


EXPECTED_8_POOL = [
    "cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)",
    "pyramide layer-dependency DAG verify (6 layers, 16 edges)",
    "verify-containerfile-base-image-digest-pins",
    "wirelang spec v0.4.3 freeze-seal probe",
    "alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)",
    "pyramide cross-run stability pin (5 fixtures, 3 runs each)",
    "g1-g2 operator-recipe smoke-validation",
    "E2E verdict (READY / DRIFT / DEFECT)",
]


class PostActivateFixtureTests(unittest.TestCase):
    """Tag-65 fixture shape + presence."""

    def test_01_fixture_file_exists(self):
        self.assertTrue(
            FIX_POST_ACTIVATE.is_file(),
            f"missing post-activate-snapshot fixture: {FIX_POST_ACTIVATE}",
        )

    def test_02_fixture_has_exactly_eight_contexts(self):
        snap = json.loads(FIX_POST_ACTIVATE.read_text(encoding="utf-8"))
        contexts = snap["required_status_checks"]["contexts"]
        self.assertEqual(len(contexts), 8, f"got {len(contexts)} contexts, want 8")

    def test_03_fixture_strict_is_true(self):
        snap = json.loads(FIX_POST_ACTIVATE.read_text(encoding="utf-8"))
        self.assertTrue(snap["required_status_checks"]["strict"])

    def test_04_fixture_context_order_matches_expected_pool(self):
        snap = json.loads(FIX_POST_ACTIVATE.read_text(encoding="utf-8"))
        self.assertEqual(
            snap["required_status_checks"]["contexts"], EXPECTED_8_POOL
        )


class PostActivateVerifyCleanPathTests(unittest.TestCase):
    """End-to-end --post-activate-verify clean path."""

    def test_05_verify_clean_snapshot_exits_zero(self):
        result = _run_verify(FIX_POST_ACTIVATE)
        self.assertEqual(
            result.returncode, 0,
            f"verify rc={result.returncode}\nstderr:\n{result.stderr}",
        )
        self.assertIn("POST-ACTIVATE-CLEAN", result.stdout)

    def test_06_verify_clean_snapshot_json_envelope(self):
        result = _run_verify(FIX_POST_ACTIVATE, extra=["--json"])
        self.assertEqual(result.returncode, 0)
        envelope = json.loads(result.stdout)
        self.assertEqual(envelope["verdict"], "POST-ACTIVATE-CLEAN")
        self.assertEqual(envelope["expected_pool_size"], 8)
        self.assertEqual(envelope["discrepancies"], [])
        self.assertEqual(envelope["observed_strict"], True)
        self.assertEqual(len(envelope["observed_contexts"]), 8)


class PostActivateVerifyDefectPathTests(unittest.TestCase):
    """Discrepancy-detection paths."""

    def test_07_missing_context_yields_defect(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "missing.json"
            # Drop the last expected context.
            _write_snapshot(bad, EXPECTED_8_POOL[:-1])
            result = _run_verify(bad)
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing required-check context", result.stdout)
            self.assertIn("POST-ACTIVATE-DEFECT", result.stdout)

    def test_08_extra_context_yields_defect(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "extra.json"
            _write_snapshot(bad, EXPECTED_8_POOL + ["unexpected-leftover-check"])
            result = _run_verify(bad)
            self.assertEqual(result.returncode, 1)
            self.assertIn("extra (unexpected) context", result.stdout)
            self.assertIn("unexpected-leftover-check", result.stdout)

    def test_09_strict_false_yields_defect(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "loose.json"
            _write_snapshot(bad, EXPECTED_8_POOL, strict=False)
            result = _run_verify(bad)
            self.assertEqual(result.returncode, 1)
            self.assertIn("strict is not True", result.stdout)

    def test_10_order_mismatch_yields_defect(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "scrambled.json"
            # Same set, different order — swap first and last.
            scrambled = [EXPECTED_8_POOL[-1]] + EXPECTED_8_POOL[1:-1] + [EXPECTED_8_POOL[0]]
            _write_snapshot(bad, scrambled)
            result = _run_verify(bad)
            self.assertEqual(result.returncode, 1)
            self.assertIn("context order mismatch", result.stdout)

    def test_11_missing_rsc_block_yields_defect(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "no-rsc.json"
            _write_snapshot(bad, [], omit_rsc=True)
            result = _run_verify(bad)
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing required_status_checks block", result.stdout)

    def test_12_invalid_json_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("not-json-{{{", encoding="utf-8")
            result = _run_verify(bad)
            self.assertEqual(result.returncode, 1)
            self.assertIn("REFUSED", result.stderr)
            self.assertIn("invalid JSON", result.stderr)

    def test_13_missing_snapshot_flag_is_refused(self):
        args = [
            sys.executable,
            str(PLANNER_PATH),
            "--tag59-doc", str(TAG59_DOC),
            "--tag61-doc", str(TAG61_DOC),
            "--tag64-doc", str(TAG64_DOC),
            "--post-activate-verify",
        ]
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("REFUSED", result.stderr)
        self.assertIn("--post-activate-snapshot", result.stderr)


class PostActivateInProcessTests(unittest.TestCase):
    """In-process unit tests on the verify helper."""

    def test_14_verify_helper_returns_empty_discrepancies_on_clean(self):
        planner = _load_planner()
        combined, _, errors = planner.assemble_pool(TAG59_DOC, TAG61_DOC, TAG64_DOC)
        self.assertEqual(errors, [])
        snap = json.loads(FIX_POST_ACTIVATE.read_text(encoding="utf-8"))
        discrepancies, report = planner.verify_post_activate_snapshot(combined, snap)
        self.assertEqual(discrepancies, [])
        self.assertEqual(report["verdict"], "POST-ACTIVATE-CLEAN")
        self.assertEqual(report["expected_pool_size"], 8)


class PostActivateWorkflowWiringTests(unittest.TestCase):
    """Workflow Stage-5 wiring."""

    def test_15_workflow_declares_stage5_and_wires_rc5(self):
        wf = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("Stage 5 - Tag-65 Post-Activate-Verify", wf)
        self.assertIn("--post-activate-verify", wf)
        self.assertIn("post-activate-snapshot.json", wf)
        self.assertIn("stage5_rc", wf)
        # Stage-4 final verdict must consider rc5
        self.assertIn('rc5="${{ steps.stage5.outputs.stage5_rc }}"', wf)


if __name__ == "__main__":
    unittest.main()
