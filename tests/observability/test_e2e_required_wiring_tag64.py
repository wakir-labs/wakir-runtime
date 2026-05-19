# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tests for the Tag-64 E2E-verdict Required-Status-Check Wiring.

Hermetic, stdlib-only. Validates:

  - the Tag-64 Companion doc
    (``docs/operations/branch-protection-required-checks-tag64-
    companion.md``)
  - the additive Tag-64 extension of the Tag-62 bulk-activation
    planner (``tooling/ops/_bulk_activate_required_checks.py``)
  - the three Tag-64 walking-skeleton fixtures under
    ``tests/observability/fixtures/branch-protection-walking-
    skeleton-tag64/``
  - additivity discipline: the planner's 7-Pool fallback (no
    ``--tag64-doc``) is byte-identical to the Tag-62 lineage,
    so Kai's Tag-62 walking-skeleton path is preserved.

Test count: 16 (>= 12 required by Tag-64 brief).

Tag-64 invariants under test
============================

  1. The Tag-64 Companion doc parses as one §1 row (row 8) with the
     verbatim display-name ``E2E verdict (READY / DRIFT / DEFECT)``.
  2. The Tag-64 §1 Gesamt-Pool-Bilanz lists all 8 rows in order.
  3. The Companion doc references the existing Tag-63 workflow file
     (``.github/workflows/pre-cutover-final-acceptance-e2e-smoke.
     yml``) and the workflow file's ``e2e-verdict`` job declares
     the same verbatim ``name:``.
  4. Running the planner WITHOUT ``--tag64-doc`` yields the
     unchanged Tag-62-lineage 7-Pool envelope (no regression in
     Kai's walking-skeleton path).
  5. Running the planner WITH ``--tag64-doc`` yields the 8-Pool
     envelope with the new check appended in position 8.
  6. mock-api-mode WITH ``--tag64-doc`` from the empty pre-snapshot
     yields a post-snapshot byte-identical to the Tag-64 expected
     fixture.
  7. mock-api-mode WITH ``--tag64-doc`` from the partial-7Pool
     pre-snapshot yields the same byte-identical Tag-64 post-
     snapshot (idempotency under full-replace PUT semantics).
  8. The Tag-64 expected post-snapshot fixture's
     ``required_status_checks.contexts`` is exactly the eight
     verbatim display-names, in the documented Pool-Bilanz order.
  9. The Companion doc declares Operator-Hand-Sandbox-Boundary
     for the gh-api Branch-Protection PUT (no Mira-Sandbox
     activation path).
 10. The Companion doc declares the §3.3 Concurrency-Race-Falle
     specific to dispatch-only workflows.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLANNER_PATH = REPO_ROOT / "tooling" / "ops" / "_bulk_activate_required_checks.py"
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "pre-cutover-final-acceptance-e2e-smoke.yml"
)

FIXTURE_DIR_TAG64 = (
    REPO_ROOT
    / "tests"
    / "observability"
    / "fixtures"
    / "branch-protection-walking-skeleton-tag64"
)
FIX_EMPTY = FIXTURE_DIR_TAG64 / "pre-snapshot-empty.json"
FIX_PARTIAL = FIXTURE_DIR_TAG64 / "pre-snapshot-partial-7pool.json"
FIX_EXPECTED = FIXTURE_DIR_TAG64 / "expected-post-snapshot.json"

# Tag-63 lineage fixtures (must remain unchanged in Tag-64).
FIXTURE_DIR_TAG63 = (
    REPO_ROOT
    / "tests"
    / "observability"
    / "fixtures"
    / "branch-protection-walking-skeleton"
)
FIX_TAG63_EXPECTED = FIXTURE_DIR_TAG63 / "expected-post-snapshot.json"

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


EXPECTED_TAG64_DISPLAY_NAME = "E2E verdict (READY / DRIFT / DEFECT)"
EXPECTED_TAG64_WORKFLOW = (
    ".github/workflows/pre-cutover-final-acceptance-e2e-smoke.yml"
)
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


def _load_planner():
    spec = importlib.util.spec_from_file_location(
        "bulk_activate_planner_tag64", PLANNER_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_planner(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PLANNER_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestTag64CompanionDoc(unittest.TestCase):
    """Tag-64 Companion doc parse + content invariants."""

    def test_companion_doc_exists(self):
        self.assertTrue(
            TAG64_DOC.is_file(),
            "Tag-64 Companion doc must exist at "
            "docs/operations/branch-protection-required-checks-tag64-companion.md",
        )

    def test_companion_doc_declares_owner_amara(self):
        text = TAG64_DOC.read_text(encoding="utf-8")
        # Frontmatter owner field
        self.assertRegex(
            text,
            r'owner:\s*"amara"',
            "Tag-64 Companion frontmatter must declare owner: amara",
        )

    def test_companion_doc_references_tag61_predecessor(self):
        text = TAG64_DOC.read_text(encoding="utf-8")
        self.assertIn(
            "branch-protection-required-checks-tag61-addendum.md",
            text,
            "Tag-64 Companion must reference Tag-61 addendum as predecessor",
        )

    def test_companion_section_1_declares_row_8(self):
        """The §1 Erweiterung table has a row at index 8 with the
        verbatim E2E-verdict display-name + the Tag-63 workflow file."""
        text = TAG64_DOC.read_text(encoding="utf-8")
        # Locate the row in §1 table
        row_re = re.compile(
            r"\|\s*8\s*\|\s*`(?P<name>[^`]+)`\s*\|\s*`(?P<wf>[^`]+)`\s*\|",
            re.MULTILINE,
        )
        match = row_re.search(text)
        self.assertIsNotNone(match, "Tag-64 §1 row 8 not found")
        self.assertEqual(match.group("name"), EXPECTED_TAG64_DISPLAY_NAME)
        self.assertEqual(match.group("wf"), EXPECTED_TAG64_WORKFLOW)

    def test_companion_pool_bilanz_lists_all_8_in_order(self):
        """The §1 Gesamt-Pool-Bilanz lists all 8 slot rows in pool
        order (slot 1..8)."""
        text = TAG64_DOC.read_text(encoding="utf-8")
        bilanz_re = re.compile(
            r"\|\s*(?P<slot>\d+)\s*\|\s*`(?P<name>[^`]+)`\s*\|"
            r"\s*(?P<status>[A-Z][A-Z0-9-]+(?:-[A-Z0-9-]+)*)\s*\|"
            r"\s*(?P<src>Tag-\d+|\*\*Tag-\d+\*\*)\s*\|",
            re.MULTILINE,
        )
        rows = [
            (int(m.group("slot")), m.group("name"))
            for m in bilanz_re.finditer(text)
        ]
        self.assertEqual(
            len(rows),
            8,
            f"Tag-64 §1 Gesamt-Pool-Bilanz must list 8 rows, got {len(rows)}",
        )
        slots = [r[0] for r in rows]
        names = [r[1] for r in rows]
        self.assertEqual(slots, list(range(1, 9)))
        self.assertEqual(names, EXPECTED_8_POOL)

    def test_companion_doc_declares_operator_hand_sandbox_boundary(self):
        """§6 must declare the gh-api Branch-Protection PUT as
        Operator-Hand (not Mira-Sandbox)."""
        text = TAG64_DOC.read_text(encoding="utf-8")
        self.assertIn(
            "gh-api Branch-Protection PUT",
            text,
            "Tag-64 Companion §6 must reference gh-api Branch-Protection PUT",
        )
        # The Operator-Hand-Spalte for the PUT-Row must be marked **JA**
        self.assertRegex(
            text,
            r"gh-api Branch-Protection PUT.*\|.*\bnein\b.*\|.*\*\*JA\*\*",
            "PUT-Row in §6 boundary table must be Mira-Sandbox=nein, Operator-Hand=JA",
        )

    def test_companion_doc_declares_concurrency_race_falle(self):
        """§3.3 must call out the dispatch-only Concurrency-Race-Falle."""
        text = TAG64_DOC.read_text(encoding="utf-8")
        self.assertIn(
            "Concurrency-Race-Falle",
            text,
            "Tag-64 Companion §3.3 must document Concurrency-Race-Falle",
        )

    def test_companion_doc_declares_pending_operator_audit_only(self):
        """The new check #8 must be initially gated as AUDIT-ONLY
        (highest risk-stage, dispatch-only trigger)."""
        text = TAG64_DOC.read_text(encoding="utf-8")
        # Row 8 in the Pool-Bilanz has PENDING-OPERATOR-AUDIT-ONLY
        row8_re = re.compile(
            r"\|\s*8\s*\|\s*`E2E verdict[^`]+`\s*\|"
            r"\s*PENDING-OPERATOR-AUDIT-ONLY\s*\|",
            re.MULTILINE,
        )
        self.assertRegex(
            text,
            row8_re,
            "Tag-64 #8 must be PENDING-OPERATOR-AUDIT-ONLY in Pool-Bilanz",
        )


class TestTag64WorkflowJobName(unittest.TestCase):
    """Verify the Tag-63 workflow file's e2e-verdict job declares
    the verbatim ``name:`` field that the Tag-64 doc expects."""

    def test_workflow_file_exists(self):
        self.assertTrue(
            WORKFLOW_PATH.is_file(),
            f"Tag-63 E2E-smoke workflow must exist at {WORKFLOW_PATH}",
        )

    def test_workflow_declares_e2e_verdict_job_name_verbatim(self):
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        # The job-display-name appears as a `name:` field inside a
        # jobs.<id>: block. We grep for the exact string.
        expected_name_line = f"name: {EXPECTED_TAG64_DISPLAY_NAME}"
        self.assertIn(
            expected_name_line,
            text,
            (
                "Workflow file must declare the job-name verbatim as "
                f"'{EXPECTED_TAG64_DISPLAY_NAME}' so it appears as the "
                "Required-Status-Check display-name. Check-Name-Verbatim-"
                "Disziplin per feedback_branch_protection_check_names."
            ),
        )


class TestTag64PlannerAdditivity(unittest.TestCase):
    """Verify the planner extension is additive: 7-Pool fallback
    behaviour is unchanged when --tag64-doc is omitted."""

    def test_planner_7pool_fallback_human_output_unchanged_count(self):
        """Without --tag64-doc, human output declares pool-size 7."""
        result = _run_planner(
            [
                "--tag59-doc", str(TAG59_DOC),
                "--tag61-doc", str(TAG61_DOC),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("target pool size: 7", result.stdout)
        self.assertIn("contexts: 7 entries", result.stdout)
        self.assertIn("verdict: PLAN-CONSISTENT", result.stdout)
        # The Tag-62 plan label is preserved.
        self.assertIn("Tag-62 Bulk-Activation Pre-Walk Plan", result.stdout)

    def test_planner_8pool_human_output_with_tag64_doc(self):
        """With --tag64-doc, human output declares pool-size 8."""
        result = _run_planner(
            [
                "--tag59-doc", str(TAG59_DOC),
                "--tag61-doc", str(TAG61_DOC),
                "--tag64-doc", str(TAG64_DOC),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("target pool size: 8", result.stdout)
        self.assertIn("contexts: 8 entries", result.stdout)
        self.assertIn("verdict: PLAN-CONSISTENT", result.stdout)
        # The Tag-64 plan label is shown.
        self.assertIn("Tag-64 Bulk-Activation Pre-Walk Plan", result.stdout)
        # The new check is in position 8.
        self.assertIn(f"  8. {EXPECTED_TAG64_DISPLAY_NAME}", result.stdout)

    def test_planner_json_envelope_7pool_default(self):
        result = _run_planner(
            [
                "--tag59-doc", str(TAG59_DOC),
                "--tag61-doc", str(TAG61_DOC),
                "--json",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        env = json.loads(result.stdout)
        self.assertEqual(env["tag"], "tag-62")
        self.assertEqual(env["target_pool_size"], 7)
        self.assertEqual(len(env["required_status_checks"]["contexts"]), 7)
        self.assertEqual(env["verdict"], "PLAN-CONSISTENT")

    def test_planner_json_envelope_8pool_with_tag64(self):
        result = _run_planner(
            [
                "--tag59-doc", str(TAG59_DOC),
                "--tag61-doc", str(TAG61_DOC),
                "--tag64-doc", str(TAG64_DOC),
                "--json",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        env = json.loads(result.stdout)
        self.assertEqual(env["tag"], "tag-64")
        self.assertEqual(env["target_pool_size"], 8)
        self.assertEqual(
            env["required_status_checks"]["contexts"], EXPECTED_8_POOL
        )
        self.assertEqual(env["verdict"], "PLAN-CONSISTENT")

    def test_planner_put_payload_8pool(self):
        result = _run_planner(
            [
                "--tag59-doc", str(TAG59_DOC),
                "--tag61-doc", str(TAG61_DOC),
                "--tag64-doc", str(TAG64_DOC),
                "--put-payload",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["required_status_checks"]["contexts"], EXPECTED_8_POOL
        )
        self.assertTrue(payload["required_status_checks"]["strict"])


class TestTag64MockApiMode(unittest.TestCase):
    """Verify mock-api-mode produces the byte-identical Tag-64
    post-snapshot from both pre-snapshot fixtures."""

    def test_mock_api_from_empty_yields_byte_identical_expected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "post.json"
            result = _run_planner(
                [
                    "--tag59-doc", str(TAG59_DOC),
                    "--tag61-doc", str(TAG61_DOC),
                    "--tag64-doc", str(TAG64_DOC),
                    "--mock-api-mode",
                    "--mock-pre-snapshot", str(FIX_EMPTY),
                    "--mock-post-snapshot", str(out),
                ]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            generated = out.read_bytes()
            expected = FIX_EXPECTED.read_bytes()
            self.assertEqual(
                generated,
                expected,
                "post-snapshot from empty pre must be byte-identical "
                "to Tag-64 expected fixture",
            )

    def test_mock_api_from_partial_7pool_yields_byte_identical_expected(self):
        """Idempotency: starting from the partial 7-Pool pre-state
        the full-replace PUT yields the same byte-identical 8-Pool
        post-snapshot as starting from empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "post.json"
            result = _run_planner(
                [
                    "--tag59-doc", str(TAG59_DOC),
                    "--tag61-doc", str(TAG61_DOC),
                    "--tag64-doc", str(TAG64_DOC),
                    "--mock-api-mode",
                    "--mock-pre-snapshot", str(FIX_PARTIAL),
                    "--mock-post-snapshot", str(out),
                ]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            generated = out.read_bytes()
            expected = FIX_EXPECTED.read_bytes()
            self.assertEqual(
                generated,
                expected,
                "post-snapshot from partial-7pool pre must be byte-"
                "identical to Tag-64 expected fixture (idempotency)",
            )


class TestTag64FixtureShape(unittest.TestCase):
    """Verify the Tag-64 expected fixture has the documented shape."""

    def test_expected_fixture_lists_exactly_8_contexts_in_order(self):
        data = json.loads(FIX_EXPECTED.read_text(encoding="utf-8"))
        self.assertEqual(
            data["required_status_checks"]["contexts"], EXPECTED_8_POOL
        )
        self.assertTrue(data["required_status_checks"]["strict"])
        self.assertEqual(data["branch"], "main")
        self.assertEqual(data["_fixture_id"], "expected-post-snapshot")

    def test_tag63_fixture_unchanged_by_tag64(self):
        """Tag-63 expected fixture must NOT have grown to 8 entries.
        Additivity discipline: Tag-64 must not mutate Tag-63 artefacts."""
        data = json.loads(FIX_TAG63_EXPECTED.read_text(encoding="utf-8"))
        self.assertEqual(
            len(data["required_status_checks"]["contexts"]),
            7,
            "Tag-63 expected fixture must remain 7-Pool — Tag-64 is additive, not mutative",
        )
        self.assertNotIn(
            EXPECTED_TAG64_DISPLAY_NAME,
            data["required_status_checks"]["contexts"],
            "Tag-64 E2E-verdict must not appear in the Tag-63 lineage fixture",
        )


if __name__ == "__main__":
    unittest.main()
