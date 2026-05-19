"""Tests for the Tag-59 Branch-Protection Required-Check Wiring Doc.

Hermetic, stdlib-only. Validates both:
 - the live doc shipped in `docs/operations/branch-protection-required-checks-tag59.md`
 - the helper script `tooling/ci/verify_branch_protection_required_checks_doc.py`

Test count: 18 (>= 12 required by Tag-59 brief).
"""

from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "branch-protection-required-checks-tag59.md"
)
HELPER_PATH = (
    REPO_ROOT
    / "tooling"
    / "ci"
    / "verify_branch_protection_required_checks_doc.py"
)


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "verify_bp_doc", HELPER_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HELPER = _load_helper()

# Expected verbatim display-names (from the source PRs).
EXPECTED_DISPLAY_NAMES = (
    "cross-substrate parity (cosign ↔ quadlet ↔ backend-switch)",
    "pyramide layer-dependency DAG verify (6 layers, 16 edges)",
    "verify-containerfile-base-image-digest-pins",
    "wirelang spec v0.4.3 freeze-seal probe",
    "alert-routing cross-repo mirror (wakir-runtime ↔ wakir-protocol)",
)

EXPECTED_WORKFLOW_FILES = (
    ".github/workflows/cross-substrate-parity-gate.yml",
    ".github/workflows/pyramide-layer-dependency-verify-gate.yml",
    ".github/workflows/containerfile-digest-pin-gate.yml",
    ".github/workflows/wirelang-spec-freeze-seal-probe.yml",
    ".github/workflows/alert-routing-cross-repo-mirror.yml",
)


class DocExistsTests(unittest.TestCase):
    def test_doc_exists(self):
        self.assertTrue(DOC_PATH.exists(), f"missing {DOC_PATH}")

    def test_doc_non_empty(self):
        self.assertGreater(DOC_PATH.stat().st_size, 1024)

    def test_helper_exists(self):
        self.assertTrue(HELPER_PATH.exists(), f"missing {HELPER_PATH}")


class FrontmatterTests(unittest.TestCase):
    def setUp(self):
        self.text = DOC_PATH.read_text(encoding="utf-8")

    def test_yaml_frontmatter_present(self):
        self.assertTrue(self.text.startswith("---\n"))
        # closing fence within first 25 lines
        head = "\n".join(self.text.splitlines()[1:25])
        self.assertIn("---", head)

    def test_frontmatter_tag_field(self):
        self.assertIn('tag: "tag-59"', self.text)

    def test_frontmatter_owner_kai(self):
        self.assertIn('owner: "kai"', self.text)

    def test_frontmatter_audience_includes_operator(self):
        self.assertIn("operator", self.text.split("---", 2)[1])


class RequiredSectionTests(unittest.TestCase):
    def setUp(self):
        self.text = DOC_PATH.read_text(encoding="utf-8")
        self.sections = HELPER.split_sections(self.text)

    def test_all_required_sections_present(self):
        for req in HELPER.REQUIRED_SECTIONS:
            self.assertIn(req, self.sections, f"missing: {req}")

    def test_six_top_level_sections(self):
        # exact 6 §N sections at H2 level
        h2 = [
            h
            for h in self.sections
            if h.startswith("§")
        ]
        self.assertEqual(len(h2), 6, f"expected 6 §-sections, got {h2}")


class StatusTableTests(unittest.TestCase):
    def setUp(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        sections = HELPER.split_sections(text)
        self.rows = HELPER.parse_status_table(
            sections[HELPER.REQUIRED_SECTIONS[0]]
        )

    def test_row_count_is_five(self):
        self.assertEqual(len(self.rows), 5)

    def test_display_names_verbatim(self):
        got = [HELPER.extract_backtick(r["display_name"]) for r in self.rows]
        for expected in EXPECTED_DISPLAY_NAMES:
            self.assertIn(expected, got, f"missing display-name: {expected}")

    def test_workflow_files_verbatim(self):
        got = [HELPER.extract_backtick(r["workflow"]) for r in self.rows]
        for expected in EXPECTED_WORKFLOW_FILES:
            self.assertIn(expected, got, f"missing workflow: {expected}")

    def test_display_name_uniqueness(self):
        got = [HELPER.extract_backtick(r["display_name"]) for r in self.rows]
        self.assertEqual(len(got), len(set(got)))

    def test_all_rows_have_pending_status(self):
        for r in self.rows:
            self.assertIn("PENDING", r["status"].upper())


class HelperBehaviorTests(unittest.TestCase):
    def test_verify_real_doc_passes(self):
        findings = HELPER.verify(DOC_PATH)
        errors = [f for f in findings if f.severity == "error"]
        self.assertEqual(errors, [], [f.render() for f in errors])

    def test_verify_missing_doc_fails(self):
        findings = HELPER.verify(Path("/nonexistent/branch-protection.md"))
        self.assertTrue(any(f.severity == "error" for f in findings))

    def test_verify_empty_doc_fails(self, _tmp=[None]):
        import tempfile

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

    def test_main_returns_zero_on_real_doc(self):
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc = HELPER.main(["--doc", str(DOC_PATH)])
        self.assertEqual(rc, 0, buf_err.getvalue())


class SandboxBoundaryTests(unittest.TestCase):
    def setUp(self):
        text = DOC_PATH.read_text(encoding="utf-8")
        self.s6 = HELPER.split_sections(text)[HELPER.REQUIRED_SECTIONS[5]]

    def test_mira_sandbox_marked(self):
        self.assertIn("Mira-Sandbox", self.s6)

    def test_operator_hand_marked(self):
        self.assertIn("Operator-Hand", self.s6)

    def test_adr_0020_referenced(self):
        self.assertIn("ADR-0020", self.s6)


if __name__ == "__main__":
    unittest.main()
