# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tests for the Tag-62 Bulk-Activation Pre-Walk Recipe.

Hermetic, stdlib-only. Validates:

  - the planner helper
    ``tooling/ops/_bulk_activate_required_checks.py``
  - the shell wrapper
    ``tooling/ops/bulk_activate_required_checks.sh``
  - the envelope schema validator
    ``tooling/ci/validate_bulk_activation_envelope.py``
  - the wiring doc
    ``docs/operations/bulk-activation-pre-walk-recipe.md``
  - the workflow file
    ``.github/workflows/bulk-activation-pre-walk-validator.yml``

Test count: 18 (>= 12 required by Tag-62 brief).
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLANNER_PATH = REPO_ROOT / "tooling" / "ops" / "_bulk_activate_required_checks.py"
WRAPPER_PATH = REPO_ROOT / "tooling" / "ops" / "bulk_activate_required_checks.sh"
VALIDATOR_PATH = REPO_ROOT / "tooling" / "ci" / "validate_bulk_activation_envelope.py"
DOC_PATH = REPO_ROOT / "docs" / "operations" / "bulk-activation-pre-walk-recipe.md"
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "bulk-activation-pre-walk-validator.yml"
)
TAG59_DOC = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "branch-protection-required-checks-tag59.md"
)
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


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "bulk_activate_envelope_validator", VALIDATOR_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_planner(*extra_args: str, tag59=None, tag61=None) -> subprocess.CompletedProcess:
    tag59 = tag59 or TAG59_DOC
    tag61 = tag61 or TAG61_DOC
    return subprocess.run(
        [
            sys.executable,
            str(PLANNER_PATH),
            "--tag59-doc",
            str(tag59),
            "--tag61-doc",
            str(tag61),
            *extra_args,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _run_wrapper(*extra_args: str, env_overrides=None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Make sure $CI does not leak in from the harness — we want the
    # wrapper to see the same shape locally as on a workstation.
    env.pop("CI", None)
    env.pop("BULK_ACTIVATE_OPERATOR_HAND", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(WRAPPER_PATH), *extra_args],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        cwd=str(REPO_ROOT),
    )


class FilesExistTests(unittest.TestCase):

    def test_planner_present(self):
        self.assertTrue(PLANNER_PATH.is_file())

    def test_wrapper_present_and_executable(self):
        self.assertTrue(WRAPPER_PATH.is_file())
        self.assertTrue(os.access(WRAPPER_PATH, os.X_OK))

    def test_validator_present(self):
        self.assertTrue(VALIDATOR_PATH.is_file())

    def test_doc_present(self):
        self.assertTrue(DOC_PATH.is_file())

    def test_workflow_present(self):
        self.assertTrue(WORKFLOW_PATH.is_file())


class PlannerParseTests(unittest.TestCase):

    def setUp(self):
        self.planner = _load_planner()

    def test_tag59_doc_parses_to_five_rows(self):
        text = TAG59_DOC.read_text(encoding="utf-8")
        rows = self.planner.parse_tag59_doc(text)
        self.assertEqual(len(rows), 5)
        for idx, name, wf in rows:
            self.assertGreaterEqual(idx, 1)
            self.assertLessEqual(idx, 5)
            self.assertTrue(name.strip())
            self.assertTrue(wf.startswith(".github/workflows/"))

    def test_tag61_addendum_parses_to_two_rows(self):
        text = TAG61_DOC.read_text(encoding="utf-8")
        rows = self.planner.parse_tag61_addendum(text)
        self.assertEqual(len(rows), 2)
        idxs = [r[0] for r in rows]
        self.assertEqual(sorted(idxs), [6, 7])

    def test_assemble_pool_is_seven_clean(self):
        combined, bilanz, errs = self.planner.assemble_pool(TAG59_DOC, TAG61_DOC)
        self.assertEqual(len(combined), 7)
        self.assertEqual(len(bilanz), 7)
        self.assertEqual(errs, [])

    def test_assemble_pool_contains_unicode_arrow_verbatim(self):
        combined, _bilanz, _errs = self.planner.assemble_pool(TAG59_DOC, TAG61_DOC)
        names = [name for (_, name, _) in combined]
        # The Unicode arrow is part of the verbatim Required-Check
        # display-name; PR #102 memory-lesson says any byte-drift
        # here breaks the gate forever.
        self.assertIn(
            "cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)",
            names,
        )

    def test_assemble_pool_detects_duplicate_when_present(self):
        # Inject a duplicate by writing a synthetic Tag-61 doc with a
        # row whose display-name collides with a Tag-59 row.
        dup_text = TAG61_DOC.read_text(encoding="utf-8").replace(
            "g1-g2 operator-recipe smoke-validation",
            "verify-containerfile-base-image-digest-pins",
        )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(dup_text)
            dup_path = Path(f.name)
        try:
            _combined, _bilanz, errs = self.planner.assemble_pool(TAG59_DOC, dup_path)
            self.assertTrue(any("duplicate" in e for e in errs))
        finally:
            dup_path.unlink(missing_ok=True)


class PlannerCliTests(unittest.TestCase):

    def test_dry_run_human_output_has_verdict_line(self):
        res = _run_planner()
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertIn("verdict: PLAN-CONSISTENT", res.stdout)

    def test_dry_run_json_envelope_is_valid_seven_pool(self):
        res = _run_planner("--json")
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        env = json.loads(res.stdout)
        self.assertEqual(env["tag"], "tag-62")
        self.assertEqual(env["target_pool_size"], 7)
        self.assertEqual(len(env["required_status_checks"]["contexts"]), 7)
        self.assertTrue(env["required_status_checks"]["strict"])
        self.assertEqual(env["verdict"], "PLAN-CONSISTENT")

    def test_put_payload_is_strictly_required_status_checks_only(self):
        res = _run_planner("--put-payload")
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        payload = json.loads(res.stdout)
        # Operator-merge contract: PUT-payload carries ONLY the
        # required_status_checks block. The script intentionally
        # refuses to auto-merge other fields (enforce_admins, ...).
        self.assertEqual(set(payload.keys()), {"required_status_checks"})


class EnvelopeValidatorTests(unittest.TestCase):

    def setUp(self):
        self.validator = _load_validator()

    def test_valid_envelope_passes(self):
        env = {
            "tag": "tag-62",
            "schema": "bulk-activate-required-checks/plan/v1",
            "target_pool_size": 7,
            "parsed_combined_count": 7,
            "parsed_pool_bilanz_count": 7,
            "endpoint": "PUT ...",
            "required_status_checks": {
                "strict": True,
                "contexts": [f"check-{i}" for i in range(7)],
            },
            "errors": [],
            "verdict": "PLAN-CONSISTENT",
        }
        self.assertEqual(self.validator.validate(env), [])

    def test_invalid_pool_size_caught(self):
        env = {
            "tag": "tag-62",
            "schema": "x",
            "target_pool_size": 6,
            "parsed_combined_count": 7,
            "parsed_pool_bilanz_count": 7,
            "endpoint": "PUT ...",
            "required_status_checks": {
                "strict": True,
                "contexts": [f"check-{i}" for i in range(7)],
            },
            "errors": [],
            "verdict": "PLAN-CONSISTENT",
        }
        errs = self.validator.validate(env)
        self.assertTrue(any("target_pool_size" in e for e in errs))

    def test_duplicate_contexts_caught(self):
        env = {
            "tag": "tag-62",
            "schema": "x",
            "target_pool_size": 7,
            "parsed_combined_count": 7,
            "parsed_pool_bilanz_count": 7,
            "endpoint": "PUT ...",
            "required_status_checks": {
                "strict": True,
                "contexts": ["a", "a", "b", "c", "d", "e", "f"],
            },
            "errors": [],
            "verdict": "PLAN-CONSISTENT",
        }
        errs = self.validator.validate(env)
        self.assertTrue(any("duplicate" in e for e in errs))


class WrapperSandboxBoundaryTests(unittest.TestCase):

    def test_dry_run_default_succeeds_and_emits_ready_verdict(self):
        res = _run_wrapper("--dry-run")
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertIn("BULK-ACTIVATION-READY", res.stdout)

    def test_enforce_without_marker_refused(self):
        res = _run_wrapper("--enforce")
        self.assertEqual(res.returncode, 2, msg=res.stdout + res.stderr)
        self.assertIn("REFUSED", res.stderr)

    def test_enforce_on_ci_refused(self):
        res = _run_wrapper(
            "--enforce",
            env_overrides={
                "CI": "true",
                "BULK_ACTIVATE_OPERATOR_HAND": "1",
            },
        )
        self.assertEqual(res.returncode, 2, msg=res.stdout + res.stderr)
        self.assertIn("sandbox-class", res.stderr)


class DocAndWorkflowShapeTests(unittest.TestCase):

    def test_doc_has_required_sections(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        for header in (
            "## §1 — Recipe form and modes",
            "## §2 — Idempotency contract",
            "## §3 — Operator-Hand walk",
            "## §4 — Pre-walk validator workflow",
            "## §5 — Sandbox-Boundary",
        ):
            self.assertIn(header, text, msg=f"missing section header: {header!r}")

    def test_doc_references_predecessor_tag61_addendum(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        self.assertIn("branch-protection-required-checks-tag61-addendum.md", text)
        self.assertIn("branch-protection-required-checks-tag59.md", text)

    def test_workflow_is_workflow_dispatch_only_and_read_only(self):
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        # Trigger: workflow_dispatch only.
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("pull_request:", text)
        self.assertNotIn("push:", text)
        # Permissions are read-only (no write scope reachable).
        self.assertIn("permissions:", text)
        self.assertIn("contents: read", text)
        # No branch-protection write call in the workflow body.
        self.assertNotIn("/branches/main/protection", text)


if __name__ == "__main__":
    unittest.main()
