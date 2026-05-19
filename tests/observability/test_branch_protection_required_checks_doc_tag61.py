# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tests for the Tag-61 Branch-Protection Required-Check Wiring Doc Addendum.

Hermetic, stdlib-only. Validates both:
 - the live doc shipped in
   `docs/operations/branch-protection-required-checks-tag61-addendum.md`
 - the helper script
   `tooling/ci/verify_branch_protection_required_checks_doc_tag61.py`

Test count: 21 (>= 12 required by Tag-61 brief).
"""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "branch-protection-required-checks-tag61-addendum.md"
)
HELPER_PATH = (
    REPO_ROOT
    / "tooling"
    / "ci"
    / "verify_branch_protection_required_checks_doc_tag61.py"
)
TAG59_DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "branch-protection-required-checks-tag59.md"
)


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "verify_bp_doc_tag61", HELPER_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HELPER = _load_helper()

# Expected verbatim Tag-61 new display-names (from the source PRs
# #386 + #387 workflow `jobs.<id>.name:` fields).
EXPECTED_NEW_DISPLAY_NAMES = (
    "pyramide cross-run stability pin (5 fixtures, 3 runs each)",
    "g1-g2 operator-recipe smoke-validation",
)

EXPECTED_NEW_WORKFLOW_FILES = (
    ".github/workflows/pyramide-cross-run-stability-pin-gate.yml",
    ".github/workflows/g1-g2-operator-recipe-smoke-validation.yml",
)


class DocExistsTests(unittest.TestCase):
    def test_doc_exists(self):
        self.assertTrue(DOC_PATH.exists(), f"missing {DOC_PATH}")

    def test_doc_non_empty(self):
        self.assertGreater(DOC_PATH.stat().st_size, 1024)

    def test_helper_exists(self):
        self.assertTrue(HELPER_PATH.exists(), f"missing {HELPER_PATH}")

    def test_predecessor_doc_exists(self):
        self.assertTrue(
            TAG59_DOC_PATH.exists(),
            f"Tag-61 addendum references Tag-59 predecessor "
            f"which must exist: {TAG59_DOC_PATH}",
        )


class FrontmatterTests(unittest.TestCase):
    def setUp(self):
        self.text = DOC_PATH.read_text(encoding="utf-8")

    def test_yaml_frontmatter_present(self):
        self.assertTrue(self.text.startswith("---\n"))
        head = "\n".join(self.text.splitlines()[1:30])
        self.assertIn("---", head)

    def test_frontmatter_tag_field_is_tag61(self):
        self.assertIn('tag: "tag-61"', self.text)

    def test_frontmatter_owner_kai(self):
        self.assertIn('owner: "kai"', self.text)

    def test_frontmatter_predecessor_references_tag59(self):
        self.assertIn(
            "branch-protection-required-checks-tag59.md", self.text
        )
        # Field must literally be `predecessor:`.
        first_block = self.text.split("---", 2)[1]
        self.assertIn("predecessor:", first_block)

    def test_frontmatter_audience_includes_operator(self):
        self.assertIn("operator", self.text.split("---", 2)[1])

    def test_frontmatter_related_prs_lists_386_and_387(self):
        first_block = self.text.split("---", 2)[1]
        self.assertIn("#386", first_block)
        self.assertIn("#387", first_block)


class RequiredSectionTests(unittest.TestCase):
    def setUp(self):
        self.text = DOC_PATH.read_text(encoding="utf-8")
        self.sections = HELPER.split_sections(self.text)

    def test_all_required_sections_present(self):
        for req in HELPER.REQUIRED_SECTIONS:
            self.assertIn(req, self.sections, f"missing: {req}")

    def test_six_top_level_sections(self):
        h2 = [h for h in self.sections if h.startswith("§")]
        self.assertEqual(len(h2), 6, f"expected 6 §-sections, got {h2}")


class AddendumTableTests(unittest.TestCase):
    def setUp(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        sections = HELPER.split_sections(text)
        self.tables = HELPER.parse_all_tables(
            sections[HELPER.REQUIRED_SECTIONS[0]]
        )

    def test_at_least_two_tables_in_section_1(self):
        # First = addendum 2-row, second = Gesamt-Pool-Bilanz 7-row.
        self.assertGreaterEqual(len(self.tables), 2)

    def test_new_addendum_row_count_is_two(self):
        self.assertEqual(len(self.tables[0]), 2)

    def test_pool_total_row_count_is_seven(self):
        self.assertEqual(len(self.tables[1]), 7)

    def test_new_display_names_verbatim(self):
        got = [HELPER.extract_backtick(r[1]) for r in self.tables[0]]
        for expected in EXPECTED_NEW_DISPLAY_NAMES:
            self.assertIn(
                expected, got, f"missing new display-name: {expected}"
            )

    def test_new_workflow_files_verbatim(self):
        got = [HELPER.extract_backtick(r[2]) for r in self.tables[0]]
        for expected in EXPECTED_NEW_WORKFLOW_FILES:
            self.assertIn(
                expected, got, f"missing workflow file: {expected}"
            )

    def test_no_tag59_displayname_duplicated(self):
        new_names = [
            HELPER.extract_backtick(r[1]) for r in self.tables[0]
        ]
        intersect = set(new_names) & HELPER.TAG59_DISPLAY_NAMES
        self.assertEqual(intersect, set(), f"Tag-59 collision: {intersect}")

    def test_new_rows_have_pending_or_audit_status(self):
        for r in self.tables[0]:
            status_upper = r[5].upper()
            self.assertTrue(
                "PENDING" in status_upper or "AUDIT" in status_upper,
                f"row status unexpected: {r[5]!r}",
            )


class ActivationOrderTests(unittest.TestCase):
    def setUp(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        sections = HELPER.split_sections(text)
        self.tables = HELPER.parse_all_tables(
            sections[HELPER.REQUIRED_SECTIONS[3]]
        )

    def test_order_table_has_seven_rows(self):
        self.assertGreaterEqual(len(self.tables), 1)
        self.assertEqual(len(self.tables[0]), 7)

    def test_each_row_has_risk_level(self):
        for idx, row in enumerate(self.tables[0], start=1):
            risk_cell = row[3].lower()
            matched = any(
                rl in risk_cell for rl in HELPER.VALID_RISK_LEVELS
            )
            self.assertTrue(
                matched,
                f"row {idx} has no risk-level token: {row[3]!r}",
            )

    def test_tag61_checks_present_in_order_table(self):
        joined = "\n".join(
            "|".join(r) for r in self.tables[0]
        )
        for expected in EXPECTED_NEW_DISPLAY_NAMES:
            self.assertIn(expected, joined)


class HelperBehaviorTests(unittest.TestCase):
    def test_verify_real_doc_passes(self):
        findings = HELPER.verify(DOC_PATH)
        errors = [f for f in findings if f.severity == "error"]
        self.assertEqual(errors, [], [f.render() for f in errors])

    def test_verify_missing_doc_fails(self):
        findings = HELPER.verify(
            Path("/nonexistent/branch-protection-tag61.md")
        )
        self.assertTrue(any(f.severity == "error" for f in findings))

    def test_verify_empty_doc_fails(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False
        ) as f:
            f.write("")
            p = Path(f.name)
        try:
            findings = HELPER.verify(p)
            self.assertTrue(any(f.severity == "error" for f in findings))
        finally:
            p.unlink()

    def test_verify_doc_without_predecessor_field_fails(self):
        # Doc with sections but no predecessor frontmatter must fail.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(
                "---\n"
                'title: "broken"\n'
                "---\n\n"
                "# Broken doc\n"
            )
            p = Path(f.name)
        try:
            findings = HELPER.verify(p)
            messages = [fi.message for fi in findings]
            self.assertTrue(
                any("predecessor" in m for m in messages),
                f"no predecessor-related finding in {messages}",
            )
        finally:
            p.unlink()

    def test_main_returns_zero_on_real_doc(self):
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc = HELPER.main(["--doc", str(DOC_PATH)])
        self.assertEqual(rc, 0, buf_err.getvalue())

    def test_main_returns_nonzero_on_missing_doc(self):
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc = HELPER.main(["--doc", "/nonexistent/x.md"])
        self.assertNotEqual(rc, 0)


class SandboxBoundaryTests(unittest.TestCase):
    def setUp(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        self.s6 = HELPER.split_sections(text)[
            HELPER.REQUIRED_SECTIONS[5]
        ]

    def test_mira_sandbox_marked(self):
        self.assertIn("Mira-Sandbox", self.s6)

    def test_operator_hand_marked(self):
        self.assertIn("Operator-Hand", self.s6)

    def test_adr_0020_referenced(self):
        self.assertIn("ADR-0020", self.s6)


if __name__ == "__main__":
    unittest.main()
