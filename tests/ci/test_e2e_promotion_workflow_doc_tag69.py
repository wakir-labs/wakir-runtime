# REUSE-IgnoreStart
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Hermetic tests for the Tag-69 E2E-Smoke Required-Status-Check
Promotion-Workflow-Doc and its verifier-helper.

Auftrag-Anker
-------------

Tag-69 Amara Auftrag (Mira, 2026-05-19, Continuous-Mode-Marathon):
Operator-Hand-Promotion-Workflow-Doc that bundles the concrete
sequence of actions for promoting the Tag-63 E2E-Smoke verdict-check
from audit-only to enforced-Required-Status-Check in the 8-Pool
branch-protection-activation lifecycle. Cross-Anchor zu Kai-#389
(Tag-61 Addendum), Kai-#396 (Tag-62 Bulk-Activation-Pre-Walk-Recipe),
Tomas-#404 (Tag-63 REUSE-Wrap Stability-Window-Probe-Pattern),
Amara-#411 (Tag-64-Companion) und Amara-#416 (Tag-65 E2E-Stability-
Window-Probe).

Scope (doc + verifier-helper)
-----------------------------

This module verifies two surfaces:

* The Tag-69 promotion-workflow doc
  (``docs/operations/e2e-smoke-required-check-promotion-workflow.md``):
  - frontmatter sanity (title, status, owner, tag, predecessor)
  - cross-anchor PRs and Cross-Review-Markers in frontmatter
  - required sections §1..§7 present with verbatim headings
  - §2 Stability-Window-Confirmed prerequisite recipe
  - §3 PUT-payload with 8-pool display-names in Tag-64-§4 risk-order
  - §3 enforce_admins discipline
  - §4 four verification sub-sections
  - §5 rollback-PUT (7-pool, E2E-verdict excluded) + diagnostic-tree
  - §6 cross-anchor section references all three predecessor PRs
  - §7 Sandbox-Boundary axis + Cross-Review-Markers

* The Tag-69 verifier-helper
  (``tooling/ci/verify_e2e_promotion_workflow_doc.py``):
  - returns 0 against the as-checked-in doc
  - returns non-zero against a doc with a missing required section
  - returns non-zero against a doc with a malformed PUT-payload
  - returns non-zero against a rollback-payload that still contains
    the E2E-verdict display-name
  - the verifier's frontmatter regex tolerates a leading HTML
    SPDX comment block before the YAML frontmatter opener

Hermetic posture
----------------

stdlib + unittest. No subprocess into the network. The verifier is
loaded as a module (same pattern as the Tag-65 test). The doc is
parsed as text.

Scope discipline (Amara, ADR-0036/0043/0044/0066)
-------------------------------------------------

This test pins only the Tag-69 promotion-workflow-doc substrate.
It does NOT modify the Tag-63 E2E-Smoke aggregator (PR #400), the
Tag-65 stability-window aggregator (PR #416), the persona-engine
substrate (Selin-Domaene, Zone-O), the WAT-core / V-907 substrate
(Tomas-Domaene, Zone-K), the identity-substrate (Reza-Domaene,
Zone-L), or the container-infra (Kai-Domaene, Zone-J).

Cross-Review-Markers
--------------------

* Zone-M: QA × Tomas — promotion-eligibility-gate inherits from
  PR-#404 Stability-Window-Probe-Pattern. Drift in the trinary
  verdict-shape is a Zone-M signal.
* Zone-M: QA × Kai — PUT-payload-assembly is the Kai-Tag-62
  Bulk-Activation-Helper's emit-shape. Drift between helper-emit
  and §3.2 inline-payload is a Zone-M signal.
* Zone-N: QA × Henrik — the Stability-Window-verdict-envelope,
  pre/post-PUT snapshots, smoke-PR URL, and forensic-capture are
  Audit-Evidence-Inputs. Drift in their structure or completeness
  is a Zone-N signal.
"""

from __future__ import annotations

import importlib.util
import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = (
    REPO_ROOT / "tooling" / "ci" / "verify_e2e_promotion_workflow_doc.py"
)
DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "e2e-smoke-required-check-promotion-workflow.md"
)
TAG64_COMPANION_DOC_PATH = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "branch-protection-required-checks-tag64-companion.md"
)
TAG65_AGGREGATOR_PATH = (
    REPO_ROOT / "tooling" / "ci" / "aggregate_e2e_stability_window.py"
)
BULK_ACTIVATION_RECIPE_PATH = (
    REPO_ROOT
    / "docs"
    / "operations"
    / "bulk-activation-pre-walk-recipe.md"
)


def _load_verifier():
    """Load the Tag-69 verifier as a module."""
    mod_name = "verify_e2e_promotion_workflow_doc_tag69"
    spec = importlib.util.spec_from_file_location(mod_name, VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDocExistsAndPasses(unittest.TestCase):
    """The doc is present and the verifier returns 0 (no findings)."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        self.assertTrue(DOC_PATH.exists(), f"missing doc: {DOC_PATH}")

    def test_t01_doc_file_exists_and_nonempty(self) -> None:
        text = DOC_PATH.read_text(encoding="utf-8")
        self.assertGreater(len(text.strip()), 100)

    def test_t02_verifier_returns_zero_against_checked_in_doc(self) -> None:
        findings = self.m.verify(DOC_PATH)
        errors = [f for f in findings if f.severity == "error"]
        self.assertEqual(
            errors,
            [],
            f"unexpected errors against checked-in doc: {errors}",
        )


class TestFrontmatter(unittest.TestCase):
    """Frontmatter sanity surface."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        self.text = DOC_PATH.read_text(encoding="utf-8")

    def test_t03_frontmatter_owner_amara(self) -> None:
        # Anchored multi-line match (the doc has a leading SPDX HTML
        # comment before the YAML frontmatter opener).
        self.assertIsNotNone(
            re.search(r'^owner:\s*"amara"', self.text, re.MULTILINE)
        )

    def test_t04_frontmatter_tag_tag69(self) -> None:
        self.assertIsNotNone(
            re.search(r'^tag:\s*"tag-69"', self.text, re.MULTILINE)
        )

    def test_t05_frontmatter_predecessor_targets_tag64_companion(self) -> None:
        self.assertIn(
            "branch-protection-required-checks-tag64-companion.md",
            self.text,
        )

    def test_t06_frontmatter_cross_review_markers_required_tokens(
        self,
    ) -> None:
        for token in self.m.REQUIRED_CROSS_REVIEW_TOKENS:
            self.assertIn(
                token,
                self.text,
                f"missing required Cross-Review-Marker token: {token}",
            )

    def test_t07_frontmatter_cross_anchor_prs_present(self) -> None:
        for pr in self.m.REQUIRED_CROSS_ANCHOR_PRS:
            self.assertIn(
                pr,
                self.text,
                f"missing required cross-anchor PR: {pr}",
            )

    def test_t08_frontmatter_regex_tolerates_leading_html_comment(
        self,
    ) -> None:
        # The doc has a leading SPDX HTML comment before the YAML
        # frontmatter opener. The verifier's fm-regex must tolerate
        # that (not anchored at start-of-file).
        self.assertTrue(
            self.text.startswith("<!--"),
            "doc no longer starts with leading HTML comment — adjust "
            "verifier regex if intentional",
        )
        findings = self.m.verify(DOC_PATH)
        fm_errors = [f for f in findings if "frontmatter" in f.section]
        self.assertEqual(
            fm_errors,
            [],
            f"frontmatter errors despite leading-comment-tolerant regex: "
            f"{fm_errors}",
        )


class TestRequiredSections(unittest.TestCase):
    """Required sections §1..§7 present with verbatim headings."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        self.text = DOC_PATH.read_text(encoding="utf-8")
        self.sections = self.m.split_sections(self.text)

    def test_t09_all_seven_sections_present_verbatim(self) -> None:
        for req in self.m.REQUIRED_SECTIONS:
            self.assertIn(
                req,
                self.sections,
                f"missing required section heading: {req}",
            )

    def test_t10_section_count_is_at_least_seven(self) -> None:
        # The verifier expects exactly the 7 documented top-level
        # sections. Extra top-level headings would imply scope-creep.
        top_level_count = sum(
            1
            for line in self.text.splitlines()
            if line.startswith("## ")
        )
        self.assertEqual(
            top_level_count,
            len(self.m.REQUIRED_SECTIONS),
            f"expected exactly {len(self.m.REQUIRED_SECTIONS)} top-level "
            f"§ sections, got {top_level_count}",
        )


class TestStabilityWindowGate(unittest.TestCase):
    """§2 Stability-Window-Confirmed prerequisite gate."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        text = DOC_PATH.read_text(encoding="utf-8")
        sections = self.m.split_sections(text)
        self.s2 = sections[self.m.REQUIRED_SECTIONS[1]]

    def test_t11_stability_window_confirmed_verdict_token_present(
        self,
    ) -> None:
        self.assertIn("STABILITY-WINDOW-CONFIRMED", self.s2)

    def test_t12_workflow_dispatch_recipe_present(self) -> None:
        self.assertIn(
            "gh workflow run pre-cutover-final-acceptance-e2e-smoke",
            self.s2,
        )

    def test_t13_tag65_aggregator_reference_present(self) -> None:
        self.assertIn("aggregate_e2e_stability_window.py", self.s2)

    def test_t14_freshness_window_24h_documented(self) -> None:
        # Accepts "24h" or "24 h" or "24-hour".
        self.assertTrue(
            any(token in self.s2 for token in ("24h", "24 h", "24-hour")),
            "freshness-window not explicitly documented",
        )

    def test_t15_three_back_to_back_runs_documented(self) -> None:
        # The recipe runs the E2E-Smoke three times in a loop.
        self.assertIn("for i in 1 2 3", self.s2)


class TestPutPayloadDiscipline(unittest.TestCase):
    """§3 PUT-payload contents and discipline."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        text = DOC_PATH.read_text(encoding="utf-8")
        sections = self.m.split_sections(text)
        self.s3 = sections[self.m.REQUIRED_SECTIONS[2]]
        self.payload = self.m.extract_json_payload_contexts(self.s3)

    def test_t16_put_payload_contexts_array_extracted(self) -> None:
        self.assertIsNotNone(self.payload)
        assert self.payload is not None
        self.assertEqual(len(self.payload), 8)

    def test_t17_put_payload_matches_tag64_companion_risk_order(self) -> None:
        self.assertEqual(
            list(self.payload or []),
            list(self.m.EXPECTED_POOL_DISPLAY_NAMES),
        )

    def test_t18_put_payload_8th_slot_is_e2e_verdict(self) -> None:
        assert self.payload is not None
        self.assertEqual(
            self.payload[7],
            "E2E verdict (READY / DRIFT / DEFECT)",
        )

    def test_t19_put_payload_enforce_admins_true(self) -> None:
        self.assertIn('"enforce_admins": true', self.s3)

    def test_t20_put_payload_strict_true(self) -> None:
        # The strict-mode requires up-to-date branches before merge.
        self.assertIn('"strict": true', self.s3)


class TestVerificationSubsections(unittest.TestCase):
    """§4 has exactly four verification sub-sections."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        text = DOC_PATH.read_text(encoding="utf-8")
        sections = self.m.split_sections(text)
        self.s4 = sections[self.m.REQUIRED_SECTIONS[3]]

    def test_t21_four_verification_subsections(self) -> None:
        subs = sorted(
            {
                m.group(1)
                for m in re.finditer(r"^### §4\.(\d+)", self.s4, re.MULTILINE)
            }
        )
        self.assertEqual(subs, ["1", "2", "3", "4"])


class TestRollbackDiscipline(unittest.TestCase):
    """§5 rollback-PUT excludes the E2E-verdict; diagnostic-tree has 3 rows."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        text = DOC_PATH.read_text(encoding="utf-8")
        sections = self.m.split_sections(text)
        self.s5 = sections[self.m.REQUIRED_SECTIONS[4]]
        self.rollback = self.m.extract_json_payload_contexts(self.s5)

    def test_t22_rollback_payload_has_exactly_seven_entries(self) -> None:
        self.assertIsNotNone(self.rollback)
        assert self.rollback is not None
        self.assertEqual(len(self.rollback), 7)

    def test_t23_rollback_payload_excludes_e2e_verdict(self) -> None:
        assert self.rollback is not None
        self.assertNotIn(
            "E2E verdict (READY / DRIFT / DEFECT)",
            self.rollback,
            "rollback-PUT must NOT include the E2E-verdict — that "
            "defeats the rollback",
        )

    def test_t24_rollback_payload_matches_7pool_order(self) -> None:
        assert self.rollback is not None
        self.assertEqual(
            list(self.rollback),
            list(self.m.EXPECTED_ROLLBACK_DISPLAY_NAMES),
        )

    def test_t25_diagnostic_tree_has_three_failure_mode_rows(self) -> None:
        tables = self.m.parse_all_tables(self.s5)
        self.assertGreater(len(tables), 0)
        # The diagnostic-tree is the first table in §5.
        diag = tables[0]
        self.assertEqual(
            len(diag),
            self.m.EXPECTED_DIAGNOSTIC_ROW_COUNT,
            f"diagnostic-tree must have exactly "
            f"{self.m.EXPECTED_DIAGNOSTIC_ROW_COUNT} rows (A/B/C)",
        )

    def test_t26_re_promotion_requires_fresh_confirmation(self) -> None:
        # The §5.3 re-promotion-discipline must explicitly invalidate
        # the previous confirmation.
        self.assertIn("fresh Tag-65 Stability-Window-Confirmation", self.s5)


class TestCrossAnchorSection(unittest.TestCase):
    """§6 references all three predecessor PRs by number."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        text = DOC_PATH.read_text(encoding="utf-8")
        sections = self.m.split_sections(text)
        self.s6 = sections[self.m.REQUIRED_SECTIONS[5]]

    def test_t27_pr_389_referenced_in_section_6(self) -> None:
        self.assertIn("#389", self.s6)

    def test_t28_pr_396_referenced_in_section_6(self) -> None:
        self.assertIn("#396", self.s6)

    def test_t29_pr_404_referenced_in_section_6(self) -> None:
        self.assertIn("#404", self.s6)

    def test_t30_cross_anchor_section_has_three_named_subsections(
        self,
    ) -> None:
        subs = re.findall(r"^### §6\.(\d+)", self.s6, re.MULTILINE)
        self.assertEqual(sorted(set(subs)), ["1", "2", "3"])


class TestSandboxBoundary(unittest.TestCase):
    """§7 Sandbox-Boundary table + Cross-Review-Markers."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        text = DOC_PATH.read_text(encoding="utf-8")
        sections = self.m.split_sections(text)
        self.s7 = sections[self.m.REQUIRED_SECTIONS[6]]

    def test_t31_sandbox_boundary_axis_and_adr_0020(self) -> None:
        self.assertIn("Mira-Sandbox", self.s7)
        self.assertIn("Operator-Hand", self.s7)
        self.assertIn("ADR-0020", self.s7)

    def test_t32_zone_m_and_zone_n_markers_in_section_7(self) -> None:
        self.assertIn("Zone-M", self.s7)
        self.assertIn("Zone-N", self.s7)


class TestCrossSubstrateAnchors(unittest.TestCase):
    """The predecessor substrates this doc anchors to actually exist."""

    def test_t33_tag64_companion_doc_exists(self) -> None:
        self.assertTrue(
            TAG64_COMPANION_DOC_PATH.exists(),
            f"missing predecessor doc: {TAG64_COMPANION_DOC_PATH}",
        )

    def test_t34_tag65_aggregator_helper_exists(self) -> None:
        self.assertTrue(
            TAG65_AGGREGATOR_PATH.exists(),
            f"missing Tag-65 aggregator helper: {TAG65_AGGREGATOR_PATH}",
        )

    def test_t35_bulk_activation_pre_walk_recipe_exists(self) -> None:
        self.assertTrue(
            BULK_ACTIVATION_RECIPE_PATH.exists(),
            f"missing bulk-activation-pre-walk-recipe doc: "
            f"{BULK_ACTIVATION_RECIPE_PATH}",
        )


class TestVerifierNegativeCases(unittest.TestCase):
    """The verifier returns non-zero when the doc is malformed."""

    def setUp(self) -> None:
        self.m = _load_verifier()
        self.original = DOC_PATH.read_text(encoding="utf-8")

    def _verify_modified(self, modified_text: str) -> list:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".md",
            delete=False,
            encoding="utf-8",
        ) as fh:
            fh.write(modified_text)
            tmp_path = Path(fh.name)
        try:
            return self.m.verify(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_t36_missing_section_emits_error(self) -> None:
        # Strip §7 entirely.
        marker = "## §7 — Sandbox-Boundary"
        idx = self.original.find(marker)
        self.assertGreater(idx, 0)
        modified = self.original[:idx]
        findings = self._verify_modified(modified)
        errors = [f for f in findings if f.severity == "error"]
        self.assertTrue(
            any("§7" in f.section for f in errors),
            f"expected a §7-missing error, got: {errors}",
        )

    def test_t37_rollback_payload_with_e2e_verdict_emits_error(self) -> None:
        # Locate the §5 section directly and inject the E2E-verdict
        # display-name into the rollback payload's contexts array.
        sections = self.m.split_sections(self.original)
        s5_heading = self.m.REQUIRED_SECTIONS[4]
        s5_body = sections[s5_heading]
        # The rollback array's last entry (in §5.2) ends with the
        # g1-g2-line followed by a closing-bracket line. Append the
        # E2E-verdict display-name before the close-bracket.
        anchor = '"g1-g2 operator-recipe smoke-validation"\n    ]'
        replacement = (
            '"g1-g2 operator-recipe smoke-validation",\n'
            '      "E2E verdict (READY / DRIFT / DEFECT)"\n    ]'
        )
        self.assertIn(
            anchor,
            s5_body,
            "rollback-payload anchor not found in §5 — has the "
            "rollback-payload structure changed?",
        )
        # Apply substitution only on the §5-body and reassemble.
        modified_s5 = s5_body.replace(anchor, replacement, 1)
        self.assertNotEqual(modified_s5, s5_body)
        modified = self.original.replace(s5_body, modified_s5, 1)
        self.assertNotEqual(modified, self.original)
        findings = self._verify_modified(modified)
        errors = [f for f in findings if f.severity == "error"]
        self.assertTrue(
            any("rollback" in f.section.lower() for f in errors),
            f"expected a rollback-error when E2E-verdict is in rollback "
            f"payload, got: {errors}",
        )

    def test_t38_missing_enforce_admins_emits_error(self) -> None:
        # Drop enforce_admins from the §3.2 PUT-payload only (first
        # occurrence). We replace only inside §3.
        sections = self.m.split_sections(self.original)
        s3_heading = self.m.REQUIRED_SECTIONS[2]
        s3_body = sections[s3_heading]
        # Build a copy of the doc with enforce_admins removed from §3.
        # Anchor on a unique string just below the §3 contexts-array
        # close.
        anchor = (
            '"E2E verdict (READY / DRIFT / DEFECT)"\n    ]\n  },\n  '
            '"enforce_admins": true'
        )
        replacement = (
            '"E2E verdict (READY / DRIFT / DEFECT)"\n    ]\n  },\n  '
            '"enforce_admins_DROPPED_FOR_TEST": true'
        )
        modified = self.original.replace(anchor, replacement, 1)
        self.assertNotEqual(modified, self.original)
        findings = self._verify_modified(modified)
        errors = [f for f in findings if f.severity == "error"]
        self.assertTrue(
            any("enforce" in f.section.lower() for f in errors),
            f"expected an enforce_admins error, got: {errors}",
        )

    def test_t39_verifier_main_exits_zero_on_checked_in_doc(self) -> None:
        # The verifier's main() returns 0 against the checked-in doc.
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc = self.m.main(["--doc", str(DOC_PATH)])
        self.assertEqual(rc, 0)
        self.assertIn("OK", buf_out.getvalue())

    def test_t40_verifier_main_exits_nonzero_on_missing_doc(self) -> None:
        # The verifier returns non-zero against a missing-doc path.
        buf_out = io.StringIO()
        buf_err = io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc = self.m.main(
                ["--doc", "/tmp/tag-69-nonexistent-doc-path-9999.md"]
            )
        self.assertEqual(rc, 1)
        self.assertIn("FAIL", buf_err.getvalue())


if __name__ == "__main__":
    unittest.main()
